"""JSON and CSV exports of a run result.

CSV uses stable columns (CSV_COLUMNS) with one row per: status (processing, reconciliation
outcome, invoice arithmetic, human review), invoice field, line-item field, ledger candidate,
side-by-side comparison, finding, check, follow-up item, and the review note. Text cells that start with a
spreadsheet-formula prefix are escaped with a leading apostrophe.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal, InvalidOperation

from .models import RunResult

CSV_COLUMNS = [
    "export_label", "run_id", "document_id", "ledger_name", "mode", "provider", "model",
    "workflow_status", "reconciliation_outcome", "arithmetic_status", "review_status",
    "section", "name", "item_index", "value", "ledger_entry_id", "ledger_row", "ledger_value", "difference",
    "evidence_page", "evidence_lines", "evidence_quote", "evidence_status",
    "code", "status", "blocking", "message", "policy_ref",
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def export_label(result: RunResult) -> str:
    return "Unreviewed draft" if result.review_status == "Unreviewed" else f"Reviewed: {result.review_status}"


def to_json(result: RunResult) -> str:
    data = result.model_dump(mode="json")
    data = {"export_label": export_label(result), **data}
    return json.dumps(data, indent=2)


def escape_cell(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        try:
            Decimal(text)
            return text  # a plain number is not a formula
        except InvalidOperation:
            return "'" + text
    return text


def to_csv(result: RunResult) -> str:
    meta = result.run_metadata
    base = {
        "export_label": export_label(result), "run_id": result.run_id, "document_id": result.document_id,
        "ledger_name": meta.ledger_name, "mode": meta.mode, "provider": meta.provider, "model": meta.model,
        "workflow_status": result.workflow_status, "reconciliation_outcome": result.reconciliation_outcome,
        "arithmetic_status": result.arithmetic_status, "review_status": result.review_status,
    }
    rows = [{**base, "section": "document", "name": "document_type", "value": result.document_type,
             "message": result.unsupported_reason}]
    for name, value in (("processing", result.workflow_status), ("ledger_reconciliation", result.reconciliation_outcome),
                        ("invoice_arithmetic", result.arithmetic_status), ("human_review", result.review_status)):
        rows.append({**base, "section": "status", "name": name, "value": value})
    draft = result.extracted_fields
    if draft is not None:
        for path, ev in draft.iter_values():
            idx = None
            name = path
            if path.startswith("line_items["):
                idx = int(path[len("line_items["):path.index("]")])
                name = path.split(".", 1)[1]
            e = ev.evidence
            rows.append({**base, "section": "line_item" if idx is not None else "field", "name": name,
                         "item_index": idx, "value": ev.value,
                         "evidence_page": e.page_number if e else None,
                         "evidence_lines": f"{e.line_start}-{e.line_end}" if e else None,
                         "evidence_quote": e.quote if e else None,
                         "evidence_status": e.status if e else ("absent" if ev.value is not None else None)})
    selected = result.ledger_entry.ledger_entry_id if result.ledger_entry else None
    for e in result.ledger_candidates:
        rows.append({**base, "section": "ledger_candidate", "name": e.vendor_name, "value": e.invoice_number,
                     "ledger_entry_id": e.ledger_entry_id, "ledger_row": e.row_number,
                     "ledger_value": f"{e.currency} {e.gross_amount} on {e.invoice_date}",
                     "status": "compared" if e.ledger_entry_id == selected else "not compared"})
    for c in result.comparison:
        rows.append({**base, "section": "comparison", "name": c.field, "value": c.invoice_value,
                     "ledger_entry_id": selected, "ledger_row": result.ledger_entry.row_number if result.ledger_entry else None,
                     "ledger_value": c.ledger_value, "difference": c.difference, "status": c.status, "message": c.note})
    for f in result.findings:
        rows.append({**base, "section": "finding", "name": f.field, "code": f.code,
                     "status": "blocking" if f.blocking else "info", "blocking": "yes" if f.blocking else "no",
                     "message": f.message})
    for c in result.check_results:
        rows.append({**base, "section": "check", "name": c.name, "status": c.status, "message": c.reason})
    for item in result.checklist:
        rows.append({**base, "section": "follow_up", "name": item.field, "code": item.finding_code,
                     "message": item.action, "policy_ref": item.policy_ref})
    rows.append({**base, "section": "review", "name": "review_note", "value": result.review_note,
                 "status": result.review_status})
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: escape_cell(row.get(k)) for k in CSV_COLUMNS})
    return buf.getvalue()
