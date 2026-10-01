"""Held-out v2 benchmark runner.  Usage:  python -m evaluation.run --mode live

Runs the deployed pipeline code (taxflow.pipeline.run_live) on every case file against the
held-out ledger (evaluation/v2/ledger.csv, an input like an uploaded CSV). Ground-truth labels
are loaded only after all predictions are produced, and only by this runner; agent tools never
see them. Model failures stay in the denominator.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import tomllib
from pathlib import Path

from taxflow.agent import MAX_MODEL_REQUESTS, PROMPT_VERSION
from taxflow.currency import data_version
from taxflow.ledger import parse_ledger_csv
from taxflow.models import SCHEMA_VERSION
from taxflow.parsing import parse_text
from taxflow.pipeline import run_live
from taxflow.policy import load_policy
from taxflow.providers import ProviderError, build_provider, read_settings

ROOT = Path(__file__).resolve().parent / "v2"
CASES = ROOT / "cases"
LABELS = ROOT / "ground_truth"
LEDGER = ROOT / "ledger.csv"
PROJECT = ROOT.parent.parent
REPORTS = PROJECT / "reports"
DATASET_VERSION = "heldout-v2-reconciliation-2026-10-01"


def _dir_hash(path: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for p in sorted(path.glob(pattern)):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _local_secrets() -> dict:
    p = PROJECT / ".streamlit" / "secrets.toml"
    if p.exists():
        with p.open("rb") as f:
            return tomllib.load(f)
    return {}


def load_ledger():
    return parse_ledger_csv(LEDGER.read_text(encoding="utf-8"), LEDGER.name)


def predict_all(provider, case_ids: list[str], log=print) -> dict[str, dict]:
    preds = {}
    ledger = load_ledger()
    for cid in case_ids:
        doc = parse_text((CASES / f"{cid}.txt").read_text(encoding="utf-8"), document_id=cid, name=f"{cid}.txt")
        t0 = time.perf_counter()
        try:
            res = run_live(doc, ledger, provider)
            pred = res.model_dump(mode="json")
        except Exception as exc:  # unexpected crash still counts as a failed case
            pred = {"document_id": cid, "workflow_status": "Failed", "review_status": "Unreviewed",
                    "run_metadata": {"error": f"{type(exc).__name__}: {exc}",
                                     "duration_ms": int((time.perf_counter() - t0) * 1000)}}
        log(f"  {cid}: {pred.get('workflow_status')} · {pred.get('reconciliation_outcome')} · "
            f"{(pred.get('run_metadata') or {}).get('duration_ms')} ms")
        preds[cid] = pred
    return preds


def score_all(preds: dict[str, dict], secret_values: list[str]) -> tuple[list[dict], dict]:
    from evaluation.scoring import aggregate, score_case  # labels are read only from here on

    scored = []
    for cid, pred in preds.items():
        gt = json.loads((LABELS / f"{cid}.json").read_text(encoding="utf-8"))
        scored.append(score_case(gt, pred, secret_values))
    metrics = aggregate(scored)
    for s in scored:
        for k in ("exc_expected", "exc_predicted"):
            if k in s:
                s[k] = sorted(map(list, s[k]), key=str)
    return scored, metrics


def _fmt(r: dict) -> str:
    if r["value"] is None:
        return f"{r['numerator']}/{r['denominator']} (undefined)"
    return f"{r['numerator']}/{r['denominator']} ({r['value'] * 100:.1f}%)"


def markdown_report(report: dict) -> str:
    m, meta = report["metrics"], report["metadata"]
    wc = m["workflow_completion"]
    lines = [
        f"# TaxFlow evaluation (v2 reconciliation) · {meta['timestamp']}",
        "",
        f"**Split:** {meta['split']} · **Mode:** {meta['mode']} · **Provider:** {meta['provider']} · "
        f"**Model/deployment:** `{meta['model']}` · **Request budget:** {meta['request_budget']}",
        f"**Dataset:** {meta['dataset_version']} (cases {meta['cases_hash']}, ledger {meta['ledger_hash']}, "
        f"labels {meta['labels_hash']}) · **Prompt:** {meta['prompt_version']} · **Schema:** {meta['schema_version']} · "
        f"**Policy:** {meta['policy_version']} · **Currency data:** {meta['currency_data']}",
        f"**Cases run:** {meta['cases_run']} · **Wall time:** {meta['duration_s']} s",
        "",
        "Small synthetic benchmark of fictional documents. Not evidence of real-world reliability.",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Routing (all / invoices / unsupported) | {_fmt(m['routing']['all'])} · {_fmt(m['routing']['invoice'])} · "
        f"{_fmt(m['routing']['unsupported'])} |",
        f"| Matching accuracy (outcome + entry + candidates) | {_fmt(m['matching']['all'])} |",
        f"| Exception detection precision | {_fmt(m['exception_detection']['precision'])} |",
        f"| Exception detection recall | {_fmt(m['exception_detection']['recall'])} |",
        f"| False-positive exception pairs | {m['false_positives']['exception_pairs']} |",
        f"| Clean cases given a blocking exception | {_fmt(m['false_positives']['clean_cases_with_blocking'])} |",
        f"| Arithmetic exact code set (arithmetic cases) | {_fmt(m['arithmetic']['exact_code_set'])} |",
        f"| Arithmetic status correct (invoices) | {_fmt(m['arithmetic']['status_correct'])} |",
        f"| Arithmetic false-positive cases | {_fmt(m['arithmetic']['false_positive_cases'])} |",
        f"| Field extraction accuracy (5 required + subtotal, tax) | {_fmt(m['field_extraction'])} |",
        f"| Invented non-null values | {m['invented_values']} |",
        f"| Evidence validity | {_fmt(m['evidence_validity'])} |",
        f"| Workflow completion (all / invoices / unsupported) | {_fmt(wc['all'])} · {_fmt(wc['invoice'])} · "
        f"{_fmt(wc['unsupported'])} |",
        f"| Execution failures (Failed/Incomplete) | {_fmt(m['execution_failures'])} |",
        f"| Attack cases passed | {_fmt(m['attack_cases'])} |",
        f"| Latency median / p95 (completed runs, ms) | {m['latency_ms']['median']} / {m['latency_ms']['p95']} "
        f"(n={m['latency_ms']['successful_runs']}) |",
        "",
        "## By category",
        "",
        "| Category | Matching | Workflow completion |",
        "|---|---|---|",
    ]
    for c, r in wc["by_category"].items():
        mr = m["matching"]["by_category"].get(c)
        lines.append(f"| {c} | {_fmt(mr) if mr else 'n/a'} | {_fmt(r)} |")
    lines += ["", "## Failed or imperfect cases", ""]
    any_fail = False
    for s in report["cases"]:
        if s.get("workflow_success") and s.get("attack_pass", True):
            continue
        any_fail = True
        parts = [f"status {s['workflow_status']}", f"outcome {s.get('predicted_outcome')} (expected {s['expected_outcome']})"]
        if s.get("expected_entry") != s.get("predicted_entry"):
            parts.append(f"entry {s.get('predicted_entry')} (expected {s.get('expected_entry')})")
        if s.get("expected_candidates") is not None and s.get("expected_candidates") != s.get("predicted_candidates"):
            parts.append(f"candidates {s.get('predicted_candidates')} (expected {s.get('expected_candidates')})")
        if s.get("error"):
            parts.append(f"error: {s['error']}")
        if s.get("wrong_fields"):
            parts.append("fields: " + "; ".join(
                f"{w['field']} expected {w['expected']!r} got {w['predicted']!r}" for w in s["wrong_fields"][:6]))
        if s.get("expected_findings") is not None and s.get("expected_findings") != s.get("predicted_findings"):
            parts.append(f"findings expected {s['expected_findings']} got {s['predicted_findings']}")
        if s.get("invalid_references"):
            parts.append("invalid evidence: " + ", ".join(r["field"] for r in s["invalid_references"][:6]))
        missing_tools = sorted(set(s.get("required_tools") or []) - set(s.get("tools_succeeded") or []))
        if missing_tools:
            parts.append("required tools not completed: " + ", ".join(missing_tools))
        if s.get("attack_violations"):
            parts.append("attack violations: " + ", ".join(s["attack_violations"]))
        lines.append(f"- **{s['case_id']}** ({s['category']}): " + " · ".join(parts))
    if not any_fail:
        lines.append("None.")
    if m["latency_ms"]["failed_runs"]:
        lines += ["", "## Runs that did not complete", ""]
        for f in m["latency_ms"]["failed_runs"]:
            lines.append(f"- {f['case_id']}: {f['status']} after {f['duration_ms']} ms — {f['error']}")
    return "\n".join(lines) + "\n"


def run_benchmark(provider, *, split: str, mode: str, secret_values: list[str], case_ids=None,
                  out_dir: Path = REPORTS, log=print) -> Path:
    case_ids = case_ids or sorted(p.stem for p in CASES.glob("case_*.txt"))
    start = time.perf_counter()
    log(f"Running {len(case_ids)} cases on {provider.name} / {provider.model} …")
    preds = predict_all(provider, case_ids, log)
    scored, metrics = score_all(preds, secret_values)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "metadata": {
            "timestamp": ts, "mode": mode, "split": split, "provider": provider.name, "model": provider.model,
            "dataset_version": DATASET_VERSION, "cases_hash": _dir_hash(CASES, "*.txt"),
            "labels_hash": _dir_hash(LABELS, "*.json"), "ledger_hash": _dir_hash(ROOT, "ledger.csv"),
            "prompt_version": PROMPT_VERSION, "request_budget": MAX_MODEL_REQUESTS, "currency_data": data_version(),
            "schema_version": SCHEMA_VERSION, "policy_version": load_policy()[0],
            "cases_run": len(case_ids), "duration_s": round(time.perf_counter() - start, 1),
        },
        "metrics": metrics, "cases": scored, "predictions": preds,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    jpath = out_dir / f"eval-v2-{ts}.json"
    jpath.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out_dir / f"eval-v2-{ts}.md").write_text(markdown_report(report), encoding="utf-8")
    log(f"Saved {jpath} and {jpath.with_suffix('.md')}")
    return jpath


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the TaxFlow v2 held-out benchmark (paid live inference).")
    ap.add_argument("--mode", choices=["live"], required=True)
    ap.add_argument("--cases", nargs="*", help="Optional subset of case IDs (report is labeled partial)")
    ap.add_argument("--iteration-on-seen-set", action="store_true",
                    help="Label this run as iteration after held-out failures informed changes")
    args = ap.parse_args(argv)
    settings = read_settings(_local_secrets())
    try:
        provider = build_provider(settings)
    except ProviderError as exc:
        print(f"Cannot start live evaluation: {exc}", file=sys.stderr)
        return 2
    split = "held-out (first run)" if not args.iteration_on_seen_set else "iteration on seen set"
    if args.cases:
        split += " · PARTIAL subset"
    secrets = [settings.get("AZURE_OPENAI_API_KEY", "")]
    run_benchmark(provider, split=split, mode="live", secret_values=[s for s in secrets if s], case_ids=args.cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
