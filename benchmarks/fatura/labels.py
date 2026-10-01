"""Mapping from FATURA annotations to TaxFlow fields (fixed before any scoring).

FATURA (Limam, Dhiaf & Kessentini, 2023; Zenodo doi:10.5281/zenodo.8261508; CC BY 4.0) contains
10,000 *synthetic* invoice images generated from 50 templates, annotated with box text per class.

Mapping (annotation class -> TaxFlow field, value derivation):
* NUMBER        -> invoice_number : text after the label "Invoice number" / "INVOICE ID" / "INVOICE #".
* DATE          -> invoice_date   : "DD-Mon-YYYY" after the last ":" -> ISO date.
* SELLER_NAME   -> vendor_name    : full text.
* TOTAL         -> total          : number in the TOTAL text ("TOTAL", "BALANCE DUE", "DUE_AMOUNT").
* (TOTAL text)  -> currency       : ISO code (EUR/USD/...) written in the TOTAL text. When the TOTAL text
                                    shows only "$" and no annotation text anywhere contains an ISO code,
                                    the expected currency is null (TaxFlow never infers currency from a
                                    symbol). Otherwise, if no code is written in TOTAL, currency is unknown.
* SUB_TOTAL     -> subtotal       : number in the text.
* TAX           -> tax            : last number in the text (e.g. "TAX:VAT (3.88%): 28.18 EUR" -> 28.18).
* DISCOUNT, or two or more distinct tax components (TAX plus "GST(n%)" classes) -> expected
  unsupported_structures non-empty (follow-up routing). A single GST line is one tax component.

Absent annotations: a field is "expected null" only when its annotation class is absent AND no
annotation text contains that field's label keywords (e.g. no "invoice number"/"invoice id"/"invoice #");
otherwise it is "unknown" and not scored (reported as coverage). Nothing is invented.
"""
from __future__ import annotations

import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ISO_CODES = ("EUR", "USD", "GBP", "INR", "CAD", "AUD", "JPY", "CHF")
UNKNOWN = "__unknown__"


def _text(ann: dict, key: str) -> str | None:
    v = ann.get(key)
    return v.get("text") if isinstance(v, dict) and v.get("text") else None


def _num(text: str, last: bool = False) -> str | None:
    nums = re.findall(r"\d[\d,]*\.\d{2}|\d[\d,]*", text)
    if not nums:
        return None
    return f"{float((nums[-1] if last else nums[0]).replace(',', '')):.2f}"


def _all_text(ann: dict) -> str:
    return " ".join(v["text"] for v in ann.values() if isinstance(v, dict) and v.get("text"))


def derive(ann: dict) -> dict:
    """Return expected values: a string, None (expected null), or UNKNOWN (not scored)."""
    alltext = _all_text(ann)
    out: dict = {}

    n = _text(ann, "NUMBER")
    if n:
        m = re.match(r"\s*(?:invoice\s+number|invoice\s+id|invoice\s*#)\s*[:#]?\s*(.+?)\s*$", n, re.I | re.S)
        out["invoice_number"] = m.group(1).strip() if m else UNKNOWN
    else:
        out["invoice_number"] = UNKNOWN if re.search(r"invoice\s*(number|id|#|no)", alltext, re.I) else None

    d = _text(ann, "DATE")
    if d:
        m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", d)
        try:
            out["invoice_date"] = dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except (AttributeError, KeyError, ValueError):
            out["invoice_date"] = UNKNOWN
    else:
        out["invoice_date"] = UNKNOWN if re.search(r"\bdate\b", alltext.replace("Due Date", ""), re.I) else None

    out["vendor_name"] = _text(ann, "SELLER_NAME") or UNKNOWN

    t = _text(ann, "TOTAL")
    out["total"] = _num(t.split(":")[-1]) if t else UNKNOWN
    if t:
        code = next((c for c in ISO_CODES if re.search(rf"\b{c}\b", t)), None)
        if code:
            out["currency"] = code
        elif "$" in t and not any(re.search(rf"\b{c}\b", alltext) for c in ISO_CODES):
            out["currency"] = None
        else:
            out["currency"] = UNKNOWN
    else:
        out["currency"] = UNKNOWN

    st = _text(ann, "SUB_TOTAL")
    out["subtotal"] = _num(st.split(":")[-1]) if st else UNKNOWN
    tx = _text(ann, "TAX")
    out["tax"] = _num(tx, last=True) if tx else UNKNOWN

    tax_components = sum(1 for k in ann if k.startswith("GST(")) + (1 if (ann.get("TAX") or _text(ann, "TAX")) else 0)
    out["expected_unsupported_structure"] = bool(_text(ann, "DISCOUNT") or ann.get("DISCOUNT") or tax_components >= 2)
    return out
