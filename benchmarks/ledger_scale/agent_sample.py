"""End-to-end live agent sample against the 100,000-row generated ledger.

Usage: python -m benchmarks.ledger_scale.agent_sample [--per-kind 2]

Takes N queries per kind from the 100k query set, renders each as a plain-text synthetic invoice,
and runs the full deployed agent (run_live: extraction -> model-chosen tool calls -> Python checks).
This measures full AI workflow latency and correctness with a large ledger loaded; it is a small
sample, not 100,000 invoices through the model. Labels are read after all runs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
import tomllib
from decimal import Decimal
from pathlib import Path

from taxflow.ledger import parse_ledger_csv
from taxflow.parsing import parse_text
from taxflow.pipeline import run_live
from taxflow.providers import build_provider, read_settings

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DATA = PROJECT / "data_private" / "ledger_scale"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def render(q: dict) -> str:
    total = Decimal(q["total"])
    tax = (total * Decimal("0.08") / Decimal("1.08")).quantize(Decimal("0.01"))
    sub = total - tax
    L = [q["vendor_name"].strip(), "", "INVOICE"]
    if q["invoice_number"]:
        L.append(f"Invoice Number: {q['invoice_number'].strip()}")
    y, m, d = map(int, q["invoice_date"].split("-"))
    L += [f"Invoice Date: {MONTHS[m - 1]} {d}, {y}", f"Currency: {q['currency']}", "",
          f"{'Description':<26}{'Qty':>5}{'Unit Price':>14}{'Line Total':>14}",
          f"{'Professional services':<26}{'1':>5}{sub:>14,.2f}{sub:>14,.2f}", "",
          f"Subtotal: {sub:,.2f}", f"Tax: {tax:,.2f}", f"Total: {total:,.2f}", "",
          "Synthetic test document generated from a constructed query. All names are fictional."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-kind", type=int, default=2)
    args = ap.parse_args(argv)
    settings = read_settings(tomllib.loads((PROJECT / ".streamlit" / "secrets.toml").read_text()))
    provider = build_provider(settings)
    t0 = time.perf_counter()
    ledger = parse_ledger_csv((DATA / "ledger_100000.csv").read_text(), "ledger_100000.csv", max_rows=100_000)
    _ = ledger.index
    load_s = time.perf_counter() - t0
    queries = [json.loads(l) for l in (DATA / "queries_100000.jsonl").read_text().splitlines()]
    kinds_of = {json.loads(l)["query_id"]: json.loads(l)["kind"] for l in (DATA / "labels_100000.jsonl").read_text().splitlines()}
    # selection uses only the kind tag to stratify; expected answers are read after the runs
    picked, seen = [], {}
    for q in queries:
        k = kinds_of[q["query_id"]]
        if seen.get(k, 0) < args.per_kind:
            picked.append(q)
            seen[k] = seen.get(k, 0) + 1
    results = []
    for q in picked:
        doc = parse_text(render(q), document_id=q["query_id"], name=f"{q['query_id']}.txt")
        r = run_live(doc, ledger, provider)
        results.append({"query_id": q["query_id"], "status": r.workflow_status, "outcome": r.reconciliation_outcome,
                        "entry_id": r.ledger_entry.ledger_entry_id if r.ledger_entry else None,
                        "candidate_ids": sorted(c.ledger_entry_id for c in r.ledger_candidates),
                        "seconds": (r.run_metadata.duration_ms or 0) / 1000, "requests": r.run_metadata.model_requests,
                        "tokens": (r.run_metadata.token_usage or {}).get("total_tokens"),
                        "tools_ok": set(r.required_tools) <= {t.tool for t in r.tool_trace if t.status == "success"}})
        print(q["query_id"], r.workflow_status, r.reconciliation_outcome, flush=True)
    labels = {json.loads(l)["query_id"]: json.loads(l) for l in (DATA / "labels_100000.jsonl").read_text().splitlines()}
    ok = 0
    for res in results:
        lab = labels[res["query_id"]]
        res["kind"] = lab["kind"]
        res["correct"] = (res["status"] == "Complete" and res["outcome"] == lab["expected_outcome"]
                          and res["entry_id"] == lab["expected_entry_id"] and res["candidate_ids"] == lab["expected_candidate_ids"])
        ok += res["correct"]
    secs = [r["seconds"] for r in results if r["status"] == "Complete"]
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"timestamp": ts, "ledger_rows": len(ledger.entries), "ledger_load_and_index_s": round(load_s, 2),
              "provider": provider.name, "model": provider.model, "invoices": len(results), "correct": ok,
              "completed": len(secs), "median_s": statistics.median(secs) if secs else None,
              "p95_s": sorted(secs)[max(0, int(round(0.95 * len(secs))) - 1)] if secs else None,
              "median_requests": statistics.median(r["requests"] for r in results),
              "results": results}
    (PROJECT / "reports" / f"ledger-agent-sample-{ts}.json").write_text(json.dumps(report, indent=1))
    md = [f"# Full agent workflow against a 100,000-row generated ledger · {ts}", "",
          f"{len(results)} rendered synthetic invoices ({args.per_kind} per query kind) through the full live agent "
          f"({provider.name}, `{provider.model}`). Ledger load + validation + index: {load_s:.2f} s (once).", "",
          f"- Correct outcome, entry, and candidate set: **{ok}/{len(results)}**",
          f"- Completed runs: {len(secs)}/{len(results)}; all required tools succeeded: "
          f"{sum(r['tools_ok'] for r in results)}/{len(results)}",
          f"- End-to-end latency median / p95: {report['median_s']} s / {report['p95_s']} s; "
          f"median model requests {report['median_requests']}", "",
          "| Query | Kind | Correct | Outcome | Seconds | Requests | Tokens |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['query_id']} | {r['kind']} | {r['correct']} | {r['outcome']} | {r['seconds']:.1f} | {r['requests']} | {r['tokens']} |"
           for r in results]
    (PROJECT / "reports" / f"ledger-agent-sample-{ts}.md").write_text("\n".join(md) + "\n")
    print(f"Report: reports/ledger-agent-sample-{ts}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
