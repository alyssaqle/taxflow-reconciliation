"""Source-evidence verification.

A quote that occurs in the cited span shows *where* a value came from. It does not
prove the field interpretation is right, so extracted values are scored separately
in evaluation. Here we check, where practical, that the normalized value is
consistent with the cited text (numbers, dates, explicit currency).
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from .currency import supported_codes
from .models import Evidence, ExtractedValue, InvoiceDraft
from .parsing import ParsedDocument

MAX_SPAN_LINES = 6

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d])")
_USD_RE = re.compile(r"\bUSD\b|\bU\.?\s?S\.?\s+dollars?\b|\bUS\s+dollars?\b", re.IGNORECASE)


def norm_ws(text: str) -> str:
    return " ".join(text.split())


def numbers_in(text: str) -> set[Decimal]:
    out = set()
    for whole, frac in _NUMBER_RE.findall(text):
        try:
            out.add(Decimal(whole.replace(",", "") + (frac or "")))
        except InvalidOperation:
            pass
    return out


def _safe_date(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def dates_in(text: str) -> list[tuple[str, bool]]:
    """Return (iso_date, ambiguous) candidates found in text."""
    found: list[tuple[str, bool]] = []
    for y, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        if iso := _safe_date(int(y), int(m), int(d)):
            found.append((iso, False))
    for mon, d, y in re.findall(_MONTH_RE + r"\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE):
        if iso := _safe_date(int(y), _MONTHS[mon.lower()], int(d)):
            found.append((iso, False))
    for d, mon, y in re.findall(r"\b(\d{1,2})[\s\-./]+" + _MONTH_RE + r"[\s\-./,]+(\d{4})", text, re.IGNORECASE):
        if iso := _safe_date(int(y), _MONTHS[mon.lower()], int(d)):
            found.append((iso, False))
    for a, b, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        a_i, b_i, y_i = int(a), int(b), int(y)
        options = {x for x in (_safe_date(y_i, a_i, b_i), _safe_date(y_i, b_i, a_i)) if x}
        ambiguous = len(options) > 1
        found.extend((iso, ambiguous) for iso in options)
    return found


def _field_kind(path: str) -> str:
    leaf = path.split(".")[-1]
    if leaf in ("subtotal", "tax", "total", "unit_price", "line_total", "quantity"):
        return "number"
    if leaf == "invoice_date":
        return "date"
    if leaf == "currency":
        return "currency"
    return "text"


def _value_consistent(kind: str, value: str, quote: str) -> tuple[bool, str | None]:
    if kind == "number":
        try:
            v = Decimal(value)
        except InvalidOperation:
            return False, "value is not a decimal number"
        if v in numbers_in(quote):
            return True, None
        return False, "value does not appear as a number in the quote"
    if kind == "date":
        candidates = dates_in(quote)
        matches = [amb for iso, amb in candidates if iso == value]
        if not matches:
            return False, "date does not match a date written in the quote"
        if any(matches):
            return False, "date in the source is ambiguous (day/month order)"
        return True, None
    if kind == "currency":
        code = value.strip().upper()
        if re.search(rf"\b{re.escape(code)}\b", quote) or (code == "USD" and _USD_RE.search(quote)):
            return True, None
        name = supported_codes().get(code)
        if name and re.search(rf"\b{re.escape(name)}s?\b", quote, re.IGNORECASE):
            return True, None
        return False, f"{code} is not stated explicitly in the quote (a currency symbol alone is not enough)"
    ok = norm_ws(value).casefold() in norm_ws(quote).casefold()
    return ok, None if ok else "value text not found in quote"


def verify_value(path: str, ev: ExtractedValue, doc: ParsedDocument) -> ExtractedValue:
    """Return a copy of ``ev`` with evidence status set."""
    if ev.value is None:
        return ExtractedValue(value=None, evidence=None)
    if ev.evidence is None:
        return ev.model_copy()
    e = ev.evidence.model_copy()

    def bad(note: str) -> ExtractedValue:
        e.status, e.note = "unsupported", note
        return ExtractedValue(value=ev.value, evidence=e)

    if e.document_id != doc.document_id:
        return bad("reference points to a different document")
    if not doc.has_span(e.page_number, e.line_start, e.line_end):
        return bad("page or line range does not exist")
    if e.line_end - e.line_start + 1 > MAX_SPAN_LINES:
        return bad(f"span is wider than {MAX_SPAN_LINES} lines")
    quote = norm_ws(e.quote)
    if not quote:
        return bad("quote is empty")
    if quote not in norm_ws(doc.span_text(e.page_number, e.line_start, e.line_end)):
        return bad("quote does not occur in the cited lines")
    ok, note = _value_consistent(_field_kind(path), ev.value, e.quote)
    if not ok:
        return bad(note or "value not supported by quote")
    e.status, e.note = "verified", None
    return ExtractedValue(value=ev.value, evidence=e)


def verify_draft(draft: InvoiceDraft, doc: ParsedDocument) -> InvoiceDraft:
    out = draft.model_copy(deep=True)
    for name in ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"):
        setattr(out, name, verify_value(name, getattr(out, name), doc))
    for i, item in enumerate(out.line_items or []):
        for name in ("description", "quantity", "unit_price", "line_total"):
            setattr(item, name, verify_value(f"line_items[{i}].{name}", getattr(item, name), doc))
    return out


def evidence_problems(draft: InvoiceDraft) -> list[tuple[str, str]]:
    """(field path, reason) for every non-null value lacking verified evidence."""
    problems = []
    for path, ev in draft.iter_values():
        if ev.value is None:
            continue
        if ev.evidence is None:
            problems.append((path, "no source reference"))
        elif ev.evidence.status != "verified":
            problems.append((path, ev.evidence.note or "unverified source reference"))
    return problems


def make_evidence(doc: ParsedDocument, page: int, start: int, end: int, quote: str) -> Evidence:
    return Evidence(document_id=doc.document_id, page_number=page, line_start=start, line_end=end, quote=quote)
