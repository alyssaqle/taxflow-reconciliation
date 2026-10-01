"""Run TaxFlow's extraction stage (or a regex baseline) on FATURA OCR text, then score.

Usage:
  python -m benchmarks.fatura.run --split dev  --mode live
  python -m benchmarks.fatura.run --split eval --mode live --token-budget 3000000
  python -m benchmarks.fatura.run --split eval --mode baseline

Live mode uses the deployed code path: parse_text -> agent.extract (Azure OpenAI, strict schema)
-> evidence.verify_draft -> checks.validate / checks.reconcile. There is no ledger for public
documents, so ledger tools are not part of this benchmark. Per document: at most 3 model requests
(extraction, one schema repair, one transient retry). The agent never sees labels: they are read
by the scorer only after all predictions are written.

Raw predictions (with quotes from the documents) go to data_private/. Reports with metrics and
per-document correctness flags go to reports/.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from taxflow import checks
from taxflow.agent import PROMPT_VERSION, BudgetExhausted, RequestBudget, extract
from taxflow.evidence import dates_in, verify_draft
from taxflow.models import SCHEMA_VERSION, ExtractedValue, InvoiceDraft
from taxflow.parsing import parse_text
from taxflow.providers import ProviderError, build_provider, read_settings

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DATA = PROJECT / "data_private" / "fatura"
MANIFEST = HERE / "manifest.csv"
FIELDS = ("vendor_name", "invoice_number", "invoice_date", "currency", "total", "subtotal", "tax")


def manifest(split: str) -> list[dict]:
    with MANIFEST.open() as f:
        return [r for r in csv.DictReader(f) if r["split"] == split]


# ---------------- regex baseline (same OCR text, no model) ----------------

def _amount_on(lines, pattern, exclude=None, last=True):
    for line in lines:
        if re.search(pattern, line, re.I) and not (exclude and re.search(exclude, line, re.I)):
            nums = re.findall(r"\d[\d,]*\.\d{2}", line)
            if nums:
                return f"{float((nums[-1] if last else nums[0]).replace(',', '')):.2f}", line
    return None, None


def baseline_extract(text: str) -> InvoiceDraft:
    lines = [l for l in text.splitlines() if l.strip()]
    num = None
    m = re.search(r"invoice\s*(?:number|id|#|no\.?)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9/\-]+)", text, re.I)
    if m:
        num = m.group(1)
    date = None
    for l in lines:
        if re.search(r"date", l, re.I) and not re.search(r"due", l, re.I):
            c = [iso for iso, amb in dates_in(l) if not amb]
            if c:
                date = c[0]
                break
    total, tline = _amount_on(lines, r"\b(total|balance due|amount due)\b", exclude=r"sub[_\s-]?total|in words")
    sub, _ = _amount_on(lines, r"sub[_\s-]?total")
    tax, _ = _amount_on(lines, r"^\W*tax\b")
    cur = None
    if tline:
        cm = re.search(r"\b(EUR|USD|GBP|INR|CAD|AUD)\b", tline)
        cur = cm.group(1) if cm else None
    vendor = next((l.strip() for l in lines if not re.search(r"invoice|tax|commercial|bill|address|date", l, re.I)), None)
    V = lambda v: ExtractedValue(value=v)
    return InvoiceDraft(vendor_name=V(vendor), invoice_number=V(num), invoice_date=V(date), currency=V(cur),
                        total=V(total), subtotal=V(sub), tax=V(tax))


# ---------------- per-document run ----------------

def run_doc(row: dict, mode: str, provider) -> dict:
    doc_id = row["doc_id"]
    text = (DATA / "ocr" / f"{doc_id}.txt").read_text()
    out = {"doc_id": doc_id, "mode": mode, "ocr_seconds": float(row["ocr_seconds"])}
    t0 = time.perf_counter()
    budget = RequestBudget(limit=3)
    try:
        doc = parse_text(text, document_id=doc_id, name=f"{doc_id}.txt")
        if mode == "baseline":
            draft, doc_type = baseline_extract(text), "invoice"
        else:
            ex = extract(provider, doc, budget)
            draft, doc_type = ex.draft, ex.document_type
            out["unsupported_reason"] = ex.unsupported_reason
        out["document_type"] = doc_type
        if draft is not None:
            if mode != "baseline":
                draft = verify_draft(draft, doc)
            vf, _ = checks.validate(draft)
            rf, rc = checks.reconcile(draft)
            out["fields"] = {f: draft.scalar(f).value for f in FIELDS}
            out["evidence"] = {f: (draft.scalar(f).evidence.status if draft.scalar(f).evidence else None)
                               for f in FIELDS}
            out["evidence_notes"] = {f: draft.scalar(f).evidence.note for f in FIELDS
                                     if draft.scalar(f).evidence and draft.scalar(f).evidence.status != "verified"}
            out["quotes"] = {f: draft.scalar(f).evidence.quote for f in FIELDS if draft.scalar(f).evidence}
            out["item_count"] = len(draft.line_items or [])
            out["unsupported_structures"] = draft.unsupported_structures
            out["findings"] = sorted({(f.code, f.field) for f in vf + rf}, key=str)
            out["arithmetic_status"] = checks.arithmetic_status(rc)
        out["status"] = "ok"
    except ProviderError as exc:
        out["status"], out["error"] = "failed", f"{exc.kind}: {exc}"
    except BudgetExhausted as exc:
        out["status"], out["error"] = "failed", f"budget: {exc}"
    except Exception as exc:  # recorded, never hidden
        out["status"], out["error"] = "failed", f"{type(exc).__name__}: {exc}"
    out["extract_seconds"] = round(time.perf_counter() - t0, 3)
    out["model_requests"] = budget.used
    out["token_usage"] = dict(budget.usage)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "eval"], required=True)
    ap.add_argument("--mode", choices=["live", "baseline"], required=True)
    ap.add_argument("--max-docs", type=int, default=None)
    ap.add_argument("--token-budget", type=int, default=3_000_000, help="stop starting new documents past this")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)

    rows = manifest(args.split)[: args.max_docs]
    provider = None
    if args.mode == "live":
        p = PROJECT / ".streamlit" / "secrets.toml"
        settings = read_settings(tomllib.loads(p.read_text()) if p.exists() else {})
        try:
            provider = build_provider(settings)
        except ProviderError as exc:
            print(f"Cannot run live: {exc}", file=sys.stderr)
            return 2

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{args.split}-{args.mode}"
    run_dir = DATA / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tokens, lock, preds, skipped = [0], Lock(), [], []

    def work(row):
        with lock:
            if tokens[0] >= args.token_budget:
                skipped.append(row["doc_id"])
                return None
        res = run_doc(row, args.mode, provider)
        with lock:
            tokens[0] += res["token_usage"].get("total_tokens", 0)
            n = len(preds) + 1
        if n % 25 == 0:
            print(f"  {n}/{len(rows)} · tokens {tokens[0]:,}", flush=True)
        return res

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1 if args.mode == "baseline" else args.workers) as ex:
        for res in ex.map(work, rows):
            if res is not None:
                preds.append(res)
    wall = time.perf_counter() - start
    with (run_dir / "predictions.jsonl").open("w") as f:
        for p in preds:
            f.write(json.dumps(p, default=list) + "\n")
    meta = {"run_id": run_id, "split": args.split, "mode": args.mode, "documents_selected": len(rows),
            "documents_attempted": len(preds), "documents_skipped_budget": skipped, "token_budget": args.token_budget,
            "tokens_used": tokens[0], "wall_seconds": round(wall, 1), "workers": args.workers,
            "provider": provider.name if provider else "none (regex baseline)",
            "model": provider.model if provider else None, "prompt_version": PROMPT_VERSION if provider else None,
            "schema_version": SCHEMA_VERSION}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved raw predictions to {run_dir}")
    from .score import score_run  # labels are read only from here on
    score_run(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
