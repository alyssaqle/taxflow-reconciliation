"""Ledger scale benchmark: pure-Python matching/comparison at 1k / 10k / 100k generated rows.

Usage: python -m benchmarks.ledger_scale.run [--impl both|scan|indexed]

For each scale: time CSV loading + validation (parse_ledger_csv), index construction, and per-query
lookup and lookup+compare+outcome, for (a) the original linear-scan implementation and (b) the indexed
implementation, on the same 1,000 labeled queries. Labels are read only after predictions.
No model is called: this measures deterministic matching, not the AI workflow.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import statistics
import time
from pathlib import Path

from taxflow import matching
from taxflow.ledger import parse_ledger_csv
from taxflow.models import ExtractedValue, InvoiceDraft

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data_private" / "ledger_scale"
REPORTS = HERE.parents[1] / "reports"
SCALES = (1_000, 10_000, 100_000)


def draft_of(q: dict) -> InvoiceDraft:
    V = lambda v: ExtractedValue(value=v)
    return InvoiceDraft(invoice_number=V(q["invoice_number"]), vendor_name=V(q["vendor_name"]),
                        invoice_date=V(q["invoice_date"]), currency=V(q["currency"]), total=V(q["total"]))


def predict(ledger, queries, impl: str) -> tuple[list[dict], list[float], list[float]]:
    lookup_ms, full_ms, preds = [], [], []
    index = ledger.index if impl == "indexed" else None
    for q in queries:
        d = draft_of(q)
        t0 = time.perf_counter()
        if matching.identifiers_missing(d):
            cands = []
        elif impl == "indexed":
            cands = matching.find_candidates_indexed(index, d)
        else:
            cands = matching.find_candidates(ledger.entries, d)
        t1 = time.perf_counter()
        rows, cmp_findings = matching.compare(d, cands[0]) if len(cands) == 1 else ([], [])
        outcome = matching.outcome(d, cands, rows)
        codes = sorted({f.code for f in matching.search_findings(d, cands) + cmp_findings})
        t2 = time.perf_counter()
        lookup_ms.append((t1 - t0) * 1000)
        full_ms.append((t2 - t0) * 1000)
        preds.append({"query_id": q["query_id"], "outcome": outcome,
                      "entry_id": cands[0].ledger_entry_id if len(cands) == 1 else None,
                      "candidate_ids": sorted(c.ledger_entry_id for c in cands), "codes": codes})
    return preds, lookup_ms, full_ms


def p95(xs):
    return sorted(xs)[max(0, int(round(0.95 * len(xs))) - 1)]


def score(preds, labels) -> dict:
    lab = {l["query_id"]: l for l in labels}
    tp = fp = fn = routing_ok = cand_ok = 0
    by_kind: dict[str, list[int]] = {}
    errors = []
    for p in preds:
        l = lab[p["query_id"]]
        exp, got = l["expected_entry_id"], p["entry_id"]
        if got is not None and got == exp:
            tp += 1
        elif got is not None:
            fp += 1  # false match: selected an entry that is not the expected one (or none was expected)
        if exp is not None and got != exp:
            fn += 1  # missed match
        ok = (p["outcome"] == l["expected_outcome"] and got == exp and p["candidate_ids"] == l["expected_candidate_ids"]
              and p["codes"] == sorted(l["expected_codes"]))
        routing_ok += ok
        cand_ok += p["candidate_ids"] == l["expected_candidate_ids"]
        by_kind.setdefault(l["kind"], [0, 0])
        by_kind[l["kind"]][0] += ok
        by_kind[l["kind"]][1] += 1
        if not ok and len(errors) < 20:
            errors.append({"query_id": p["query_id"], "kind": l["kind"], "expected": l, "predicted": p})
    n = len(preds)
    return {"queries": n, "true_matches": tp, "false_matches": fp, "missed_matches": fn,
            "match_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "match_recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "routing_correct": routing_ok, "candidate_sets_correct": cand_ok,
            "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_kind.items())}, "errors": errors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["both", "scan", "indexed"], default="both")
    args = ap.parse_args(argv)
    impls = ["scan", "indexed"] if args.impl == "both" else [args.impl]
    results = {}
    for n in SCALES:
        text = (DATA / f"ledger_{n}.csv").read_text()
        t0 = time.perf_counter()
        ledger = parse_ledger_csv(text, f"ledger_{n}.csv", max_rows=n)
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        _ = ledger.index
        index_s = time.perf_counter() - t0
        queries = [json.loads(l) for l in (DATA / f"queries_{n}.jsonl").read_text().splitlines()]
        res = {"rows": len(ledger.entries), "csv_load_and_validate_s": round(load_s, 3), "index_build_s": round(index_s, 3)}
        preds_by_impl = {}
        for impl in impls:
            t0 = time.perf_counter()
            preds, lk, full = predict(ledger, queries, impl)
            wall = time.perf_counter() - t0
            preds_by_impl[impl] = preds
            res[impl] = {"lookup_ms_median": round(statistics.median(lk), 4), "lookup_ms_p95": round(p95(lk), 4),
                         "lookup_compare_ms_median": round(statistics.median(full), 4),
                         "lookup_compare_ms_p95": round(p95(full), 4), "queries_wall_s": round(wall, 3)}
        labels = [json.loads(l) for l in (DATA / f"labels_{n}.jsonl").read_text().splitlines()]  # read after predictions
        for impl in impls:
            res[impl]["accuracy"] = score(preds_by_impl[impl], labels)
        if len(impls) == 2:
            res["scan_and_indexed_identical"] = preds_by_impl["scan"] == preds_by_impl["indexed"]
        results[str(n)] = res
        print(f"{n:>7}: load {load_s:.2f}s, index {index_s:.3f}s, "
              + ", ".join(f"{i} median {res[i]['lookup_ms_median']} ms" for i in impls), flush=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"timestamp": ts, "python": platform.python_version(), "machine": platform.machine(),
            "platform": platform.platform(), "manifest": json.loads((HERE / "manifest.json").read_text())}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"ledger-scale-{ts}.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1))
    (REPORTS / f"ledger-scale-{ts}.md").write_text(markdown(meta, results, impls))
    print(f"Report: reports/ledger-scale-{ts}.md")
    return 0


def markdown(meta, results, impls) -> str:
    L = [f"# Ledger scale benchmark · {meta['timestamp']}", "",
         "**Data:** generated synthetic ledgers (seed "
         f"{meta['manifest']['seed']}); not real client data and not derived from public documents. "
         "1,000 constructed, labeled queries per scale (mix in `benchmarks/ledger_scale/generate.py`). "
         "**Pure Python matching/comparison only: no model calls**; this is not AI workflow latency.",
         f"**Machine:** {meta['platform']} · Python {meta['python']}", "",
         "| Rows | CSV load+validate (s) | Index build (s) | Impl | Lookup median / p95 (ms) | Lookup+compare median / p95 (ms) "
         "| Precision | Recall | False / missed matches | Routing correct | Candidate sets correct |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        for impl in impls:
            a = r[impl]["accuracy"]
            L.append(f"| {int(n):,} | {r['csv_load_and_validate_s']} | {r['index_build_s'] if impl == 'indexed' else '—'} | {impl} "
                     f"| {r[impl]['lookup_ms_median']} / {r[impl]['lookup_ms_p95']} "
                     f"| {r[impl]['lookup_compare_ms_median']} / {r[impl]['lookup_compare_ms_p95']} "
                     f"| {a['match_precision']} | {a['match_recall']} | {a['false_matches']} / {a['missed_matches']} "
                     f"| {a['routing_correct']}/{a['queries']} | {a['candidate_sets_correct']}/{a['queries']} |")
    L += ["", "## Routing by query kind (indexed)", ""]
    last = impls[-1]
    for n, r in results.items():
        L.append(f"- **{int(n):,} rows:** " + ", ".join(f"{k} {v}" for k, v in r[last]["accuracy"]["by_kind"].items()))
    if len(impls) == 2:
        L += ["", "Scan and indexed predictions identical on every query: "
              + ", ".join(f"{int(n):,}: {r['scan_and_indexed_identical']}" for n, r in results.items())]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
