"""Score a FATURA run against derived labels. Scoring rules are fixed here before evaluation.

Comparison (per field):
* vendor_name, invoice_number: case-folded, all non-alphanumeric characters removed (OCR often drops or
  changes hyphens/spaces; this is applied identically to the regex baseline).
* invoice_date: exact ISO string.  currency: exact upper-case code (or null).
* total, subtotal, tax: numeric equality to the cent.

Label states: a value (scored for accuracy), None (expected null: scored for "correct null" vs
"invented"), or UNKNOWN (not scored; counted in coverage). Failed requests count as wrong for every
scorable field (missing predictions).

Required fields: vendor_name, invoice_number, invoice_date, currency, total.
"All required correct" = every *scorable* required field correct (denominator: documents with at
least one scorable required field); "strict" = all five scorable and correct.

OCR ceiling: share of value labels whose normalized value occurs in the normalized OCR text — an
upper bound on what any text-only extractor could get exactly right.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .labels import UNKNOWN

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DATA = PROJECT / "data_private" / "fatura"
REPORTS = PROJECT / "reports"
FIELDS = ("vendor_name", "invoice_number", "invoice_date", "currency", "total", "subtotal", "tax")
REQUIRED = ("vendor_name", "invoice_number", "invoice_date", "currency", "total")
MONEY = {"total", "subtotal", "tax"}


def norm(field: str, v):
    if v is None:
        return None
    s = str(v)
    if field in MONEY:
        try:
            return Decimal(s.replace(",", "").replace("$", "").strip()).quantize(Decimal("0.01"))
        except InvalidOperation:
            return ("invalid", s)
    if field == "currency":
        return s.strip().upper()
    if field == "invoice_date":
        return s.strip()
    return re.sub(r"[^0-9a-z]", "", s.casefold())


def _ocr_has(field: str, label: str, ocr: str) -> bool:
    flat = re.sub(r"[^0-9a-z.]", "", ocr.casefold())
    if field in MONEY:
        return f"{Decimal(label):.2f}" in flat
    if field == "invoice_date":
        import datetime as dt
        return re.sub(r"[^0-9a-z.]", "", dt.date.fromisoformat(label).strftime("%d-%b-%Y").casefold()) in flat
    if field == "currency":
        return label.casefold() in flat
    return norm(field, label) in re.sub(r"[^0-9a-z]", "", ocr.casefold())


def _ratio(n, d):
    return {"numerator": n, "denominator": d, "value": round(n / d, 4) if d else None}


def _pct(r):
    return f"{r['numerator']}/{r['denominator']}" + (f" ({100 * r['value']:.1f}%)" if r["value"] is not None else " (undefined)")


def score_run(run_dir: Path) -> Path:
    meta = json.loads((run_dir / "meta.json").read_text())
    preds = [json.loads(l) for l in (run_dir / "predictions.jsonl").read_text().splitlines()]
    per_field = {f: Counter() for f in FIELDS}
    docs, lat_extract, lat_total, failures, tokens = [], [], [], [], []
    routing = Counter()
    for p in preds:
        lab = json.loads((DATA / "labels" / f"{p['doc_id']}.json").read_text())
        ocr = (DATA / "ocr" / f"{p['doc_id']}.txt").read_text()
        ok = p["status"] == "ok"
        if not ok:
            failures.append({"doc_id": p["doc_id"], "error": p.get("error")})
        routed_invoice = ok and p.get("document_type") == "invoice"
        routing["invoice_routed"] += routed_invoice
        fields = p.get("fields") or {}
        ev = p.get("evidence") or {}
        findings = {tuple(x) for x in (p.get("findings") or [])}
        flags = {}
        for f in FIELDS:
            exp, got = lab.get(f, UNKNOWN), fields.get(f)
            c = per_field[f]
            if exp == UNKNOWN:
                c["unknown"] += 1
                if got is not None:
                    c["pred_on_unknown"] += 1
                continue
            if exp is None:
                c["expected_null"] += 1
                if got is None:
                    c["correct_null"] += 1
                    flags[f] = True
                else:
                    c["invented"] += 1
                    flags[f] = False
                if f in REQUIRED:
                    routing["expected_missing_required"] += 1
                    routing["missing_required_flagged"] += ("MISSING_FIELD", f) in findings
                continue
            c["scored"] += 1
            c["ocr_ceiling"] += _ocr_has(f, exp, ocr)
            if got is None:
                c["missing"] += 1
                flags[f] = False
            elif norm(f, got) == norm(f, exp):
                c["correct"] += 1
                flags[f] = True
            else:
                c["wrong"] += 1
                flags[f] = False
            if got is not None and ok:
                c["evidence_total"] += 1
                c["evidence_verified"] += ev.get(f) == "verified"
        req_flags = [flags[f] for f in REQUIRED if f in flags]
        all_req = bool(req_flags) and all(req_flags)
        strict = len(req_flags) == len(REQUIRED) and all(req_flags)
        if lab.get("expected_unsupported_structure"):
            routing["expected_structure"] += 1
            routing["structure_flagged"] += bool(p.get("unsupported_structures"))
        else:
            routing["no_structure_expected"] += 1
            routing["structure_false_flag"] += bool(p.get("unsupported_structures"))
        # evidence over every non-null predicted field (incl. unknown labels)
        for f in FIELDS:
            if fields.get(f) is not None:
                routing["evidence_all_total"] += 1
                routing["evidence_all_verified"] += ev.get(f) == "verified"
        docs.append({"doc_id": p["doc_id"], "status": p["status"], "routed_invoice": routed_invoice,
                     "field_correct": flags, "all_required_correct": all_req if req_flags else None,
                     "strict_all_required": strict, "n_scorable_required": len(req_flags)})
        if ok:
            lat_extract.append(p["extract_seconds"])
            lat_total.append(p["extract_seconds"] + p["ocr_seconds"])
        tokens.append(p.get("token_usage", {}).get("total_tokens", 0))

    def q95(xs):
        return sorted(xs)[max(0, int(round(0.95 * len(xs))) - 1)] if xs else None

    agg = Counter()
    for f in FIELDS:
        for k in ("scored", "correct", "missing", "wrong", "expected_null", "correct_null", "invented"):
            agg[k] += per_field[f][k]
    req_docs = [d for d in docs if d["all_required_correct"] is not None]
    metrics = {
        "per_field": {f: {"accuracy": _ratio(c["correct"], c["scored"]), "missing": c["missing"], "wrong": c["wrong"],
                          "expected_null": c["expected_null"], "correct_null": c["correct_null"],
                          "invented": c["invented"], "unknown_not_scored": c["unknown"],
                          "ocr_ceiling": _ratio(c["ocr_ceiling"], c["scored"]),
                          "evidence_valid": _ratio(c["evidence_verified"], c["evidence_total"])}
                      for f, c in per_field.items()},
        "aggregate_accuracy": _ratio(agg["correct"], agg["scored"]),
        "missing_predictions": agg["missing"], "wrong_values": agg["wrong"],
        "invented_values": _ratio(agg["invented"], agg["expected_null"]),
        "docs_all_scorable_required_correct": _ratio(sum(d["all_required_correct"] for d in req_docs), len(req_docs)),
        "docs_strict_all_five_required_correct": _ratio(sum(d["strict_all_required"] for d in docs),
                                                        sum(d["n_scorable_required"] == 5 for d in docs)),
        "evidence_validity_all_predicted": _ratio(routing["evidence_all_verified"], routing["evidence_all_total"]),
        "routed_as_invoice": _ratio(routing["invoice_routed"], len(preds)),
        "missing_required_routed_to_follow_up": _ratio(routing["missing_required_flagged"], routing["expected_missing_required"]),
        "unsupported_structure_flagged": _ratio(routing["structure_flagged"], routing["expected_structure"]),
        "unsupported_structure_false_flags": _ratio(routing["structure_false_flag"], routing["no_structure_expected"]),
        "failed_requests": _ratio(len(failures), len(preds)),
        "latency_seconds": {
            "extraction_median": statistics.median(lat_extract) if lat_extract else None, "extraction_p95": q95(lat_extract),
            "ocr_plus_extraction_median": statistics.median(lat_total) if lat_total else None,
            "ocr_plus_extraction_p95": q95(lat_total)},
        "tokens": {"total": sum(tokens), "per_doc_median": statistics.median(tokens) if tokens else None},
    }
    report = {"meta": meta, "metrics": metrics, "failures": failures, "documents": docs}
    stem = f"fatura-{meta['split']}-{meta['mode']}-{meta['run_id'].split('-')[0]}"
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{stem}.json").write_text(json.dumps(report, indent=1))
    (REPORTS / f"{stem}.md").write_text(_markdown(meta, metrics, failures))
    print(f"Report: reports/{stem}.md")
    return REPORTS / f"{stem}.md"


def _markdown(meta, m, failures) -> str:
    L = [f"# FATURA extraction benchmark · {meta['split']} · {meta['mode']} · {meta['run_id']}", "",
         "**Data:** FATURA (Limam, Dhiaf & Kessentini 2023, Zenodo doi:10.5281/zenodo.8261508, CC BY 4.0): "
         "**synthetic** invoice images generated from 50 templates by the dataset authors. Dev and eval use "
         "disjoint templates. Input to TaxFlow is our own Tesseract 5 OCR of each image (2x Lanczos upscale, psm 3; settings chosen on dev only); the images are "
         "processed by our pipeline, but OCR is Tesseract, not a TaxFlow model.",
         f"**System:** {meta['provider']} · model `{meta['model']}` · prompt {meta['prompt_version']} · "
         f"schema {meta['schema_version']}",
         f"**Documents:** selected {meta['documents_selected']}, attempted {meta['documents_attempted']}, "
         f"skipped by token budget {len(meta['documents_skipped_budget'])} (budget {meta['token_budget']:,}; "
         f"used {meta['tokens_used']:,}) · wall time {meta['wall_seconds']} s", "",
         "| Field | Accuracy | Missing | Wrong | Expected null → correct / invented | Not scored (unknown) | OCR ceiling | Evidence valid |",
         "|---|---|---|---|---|---|---|---|"]
    for f, r in m["per_field"].items():
        L.append(f"| {f} | {_pct(r['accuracy'])} | {r['missing']} | {r['wrong']} | {r['correct_null']} / {r['invented']} "
                 f"of {r['expected_null']} | {r['unknown_not_scored']} | {_pct(r['ocr_ceiling'])} | {_pct(r['evidence_valid'])} |")
    lat = m["latency_seconds"]
    L += ["", "| Aggregate metric | Result |", "|---|---|",
          f"| Aggregate field accuracy | {_pct(m['aggregate_accuracy'])} |",
          f"| Missing predictions / wrong values | {m['missing_predictions']} / {m['wrong_values']} |",
          f"| Invented values (expected null) | {_pct(m['invented_values'])} |",
          f"| Docs with all scorable required fields correct | {_pct(m['docs_all_scorable_required_correct'])} |",
          f"| Docs with all 5 required fields scorable and correct | {_pct(m['docs_strict_all_five_required_correct'])} |",
          f"| Evidence validity (all non-null predictions) | "
          f"{'n/a (baseline produces no evidence)' if meta['mode'] == 'baseline' else _pct(m['evidence_validity_all_predicted'])} |",
          f"| Routed as invoice | {_pct(m['routed_as_invoice'])} |",
          f"| Missing required field routed to follow-up | {_pct(m['missing_required_routed_to_follow_up'])} |",
          f"| Discount / multi-GST flagged as unsupported structure | {_pct(m['unsupported_structure_flagged'])} |",
          f"| Unsupported structure false flags | {_pct(m['unsupported_structure_false_flags'])} |",
          f"| Failed requests | {_pct(m['failed_requests'])} |",
          f"| Extraction latency median / p95 (s) | {lat['extraction_median']} / {lat['extraction_p95']} |",
          f"| OCR + extraction latency median / p95 (s) | {lat['ocr_plus_extraction_median']} / {lat['ocr_plus_extraction_p95']} |",
          f"| Tokens total / median per doc | {m['tokens']['total']:,} / {m['tokens']['per_doc_median']} |", ""]
    if failures:
        L += ["## Failed requests", ""] + [f"- {f['doc_id']}: {f['error']}" for f in failures] + [""]
    return "\n".join(L)
