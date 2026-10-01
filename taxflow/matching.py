"""Deterministic invoice-to-ledger matching and comparison.

Rules (v2):
* Candidates are ledger entries whose invoice_number AND vendor_name equal the invoice's,
  after conservative normalization (trim, collapse internal whitespace, case-fold). No fuzzy
  matching, and an amount match never selects a record.
* All candidates are returned. One candidate -> compare; several -> Ambiguous match;
  none -> No matching entry; missing identifiers -> Needs clarification (no search).
* Currency is compared before amounts and is never converted. A currency mismatch means
  the amounts are not compared numerically.
* The invoice's *stated* total is compared with the ledger gross amount (tax included) using
  Decimal with a tolerance of 0.01 in the shared currency: |difference| <= 0.01 agrees.
  The stated total is never replaced by a calculated total.
* Matched requires the currency, amount, and date comparisons all to complete and agree.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .checks import fmt, money
from .currency import is_supported, normalize
from .models import ComparisonRow, Finding, InvoiceDraft, LedgerEntry

AMOUNT_TOLERANCE = Decimal("0.01")


def norm_key(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()).casefold() or None


def identifiers_missing(draft: InvoiceDraft) -> list[str]:
    return [f for f in ("invoice_number", "vendor_name") if norm_key(draft.scalar(f).value) is None]


def find_candidates(entries, draft: InvoiceDraft) -> list[LedgerEntry]:
    """Reference implementation: linear scan over all entries (kept for equivalence checks)."""
    num, vendor = norm_key(draft.invoice_number.value), norm_key(draft.vendor_name.value)
    if num is None or vendor is None:
        return []
    return [e for e in entries if norm_key(e.invoice_number) == num and norm_key(e.vendor_name) == vendor]


def build_index(entries) -> dict[tuple[str, str], list[LedgerEntry]]:
    """Map the same normalized (invoice_number, vendor_name) key to entries, preserving row order."""
    index: dict[tuple[str, str], list[LedgerEntry]] = {}
    for e in entries:
        index.setdefault((norm_key(e.invoice_number), norm_key(e.vendor_name)), []).append(e)
    return index


def find_candidates_indexed(index: dict, draft: InvoiceDraft) -> list[LedgerEntry]:
    """Same rule and result order as find_candidates, using a prebuilt index (O(1) per lookup)."""
    num, vendor = norm_key(draft.invoice_number.value), norm_key(draft.vendor_name.value)
    if num is None or vendor is None:
        return []
    return list(index.get((num, vendor), []))


def _f(code: str, message: str, field: str | None = None, **details) -> Finding:
    return Finding(code=code, field=field, message=message, source="ledger", details=details)


def search_findings(draft: InvoiceDraft, candidates: list[LedgerEntry]) -> list[Finding]:
    missing = identifiers_missing(draft)
    if missing:
        return [_f("LEDGER_NOT_SEARCHED", "Ledger not searched: the invoice is missing " + " and ".join(missing) + ".",
                   missing=missing)]
    if not candidates:
        return [_f("LEDGER_NO_MATCH", f"No ledger entry has invoice number '{draft.invoice_number.value}' "
                                      f"and vendor '{draft.vendor_name.value}'.")]
    if len(candidates) > 1:
        ids = [c.ledger_entry_id for c in candidates]
        return [_f("LEDGER_AMBIGUOUS", f"{len(ids)} ledger entries match this invoice number and vendor: "
                                       + ", ".join(ids) + ". None was selected.", candidate_ids=ids)]
    return []


def _valid_date(v: str | None) -> bool:
    try:
        return v is not None and dt.date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def compare(draft: InvoiceDraft, entry: LedgerEntry) -> tuple[list[ComparisonRow], list[Finding]]:
    rows: list[ComparisonRow] = []
    findings: list[Finding] = []
    eid = entry.ledger_entry_id

    rows.append(ComparisonRow(field="invoice_number", invoice_value=draft.invoice_number.value,
                              ledger_value=entry.invoice_number, status="agree", note="used to match"))
    rows.append(ComparisonRow(field="vendor_name", invoice_value=draft.vendor_name.value,
                              ledger_value=entry.vendor_name, status="agree", note="used to match"))

    inv_cur = normalize(draft.currency.value)
    if inv_cur is None:
        cur_row = ComparisonRow(field="currency", invoice_value=None, ledger_value=entry.currency,
                                status="not_checked", note="invoice currency not stated explicitly")
    elif not is_supported(inv_cur):
        cur_row = ComparisonRow(field="currency", invoice_value=inv_cur, ledger_value=entry.currency,
                                status="not_checked", note="invoice currency is not a supported ISO 4217 code")
    elif inv_cur == entry.currency:
        cur_row = ComparisonRow(field="currency", invoice_value=inv_cur, ledger_value=entry.currency, status="agree")
    else:
        cur_row = ComparisonRow(field="currency", invoice_value=inv_cur, ledger_value=entry.currency, status="differ",
                                note="no conversion is performed")
        findings.append(_f("LEDGER_CURRENCY_MISMATCH", f"Invoice currency {inv_cur} differs from ledger entry {eid} "
                                                       f"currency {entry.currency}. Amounts were not compared.",
                           field="currency", ledger_entry_id=eid))
    rows.append(cur_row)

    total, gross = money(draft.total.value), money(entry.gross_amount)
    if cur_row.status == "differ":
        amt = ComparisonRow(field="stated_total_vs_gross_amount", invoice_value=draft.total.value,
                            ledger_value=entry.gross_amount, status="not_checked",
                            note="currencies differ; amounts are not compared or converted")
    elif cur_row.status == "not_checked":
        amt = ComparisonRow(field="stated_total_vs_gross_amount", invoice_value=draft.total.value,
                            ledger_value=entry.gross_amount, status="not_checked",
                            note="currency not confirmed; amounts are not compared")
    elif total is None:
        amt = ComparisonRow(field="stated_total_vs_gross_amount", invoice_value=draft.total.value,
                            ledger_value=entry.gross_amount, status="not_checked",
                            note="invoice stated total is missing or invalid")
    else:
        diff = total - gross
        if abs(diff) <= AMOUNT_TOLERANCE:
            amt = ComparisonRow(field="stated_total_vs_gross_amount", invoice_value=fmt(total),
                                ledger_value=fmt(gross), status="agree", difference=fmt(diff))
        else:
            amt = ComparisonRow(field="stated_total_vs_gross_amount", invoice_value=fmt(total),
                                ledger_value=fmt(gross), status="differ", difference=fmt(diff))
            direction = "higher" if diff > 0 else "lower"
            findings.append(_f("LEDGER_AMOUNT_MISMATCH",
                               f"Invoice stated total {inv_cur} {fmt(total)} is {inv_cur} {fmt(abs(diff))} {direction} than "
                               f"ledger entry {eid} gross amount {entry.currency} {fmt(gross)}.",
                               field="total", ledger_entry_id=eid, difference=fmt(diff)))
    rows.append(amt)

    inv_date = draft.invoice_date.value
    if not _valid_date(inv_date):
        date_row = ComparisonRow(field="invoice_date", invoice_value=inv_date, ledger_value=entry.invoice_date,
                                 status="not_checked", note="invoice date is missing or not a valid ISO date")
    elif inv_date == entry.invoice_date:
        date_row = ComparisonRow(field="invoice_date", invoice_value=inv_date, ledger_value=entry.invoice_date,
                                 status="agree")
    else:
        date_row = ComparisonRow(field="invoice_date", invoice_value=inv_date, ledger_value=entry.invoice_date,
                                 status="differ")
        findings.append(_f("LEDGER_DATE_MISMATCH", f"Invoice date {inv_date} differs from ledger entry {eid} "
                                                   f"date {entry.invoice_date}.", field="invoice_date",
                           ledger_entry_id=eid))
    rows.append(date_row)

    # Comparisons that could not run for reasons other than an already-reported currency mismatch.
    incomplete = [r.field for r in rows if r.status == "not_checked"
                  and not (r.field == "stated_total_vs_gross_amount" and cur_row.status == "differ")]
    if incomplete:
        findings.append(_f("LEDGER_COMPARISON_INCOMPLETE",
                           "Ledger comparison incomplete for: " + ", ".join(incomplete) + ".",
                           ledger_entry_id=eid, incomplete=incomplete))
    return rows, findings


def outcome(draft: InvoiceDraft, candidates: list[LedgerEntry], rows: list[ComparisonRow]) -> str:
    if identifiers_missing(draft):
        return "Needs clarification"
    if not candidates:
        return "No matching entry"
    if len(candidates) > 1:
        return "Ambiguous match"
    if any(r.status == "differ" for r in rows):
        return "Discrepancy found"
    if not rows or any(r.status == "not_checked" for r in rows):
        return "Needs clarification"
    return "Matched"
