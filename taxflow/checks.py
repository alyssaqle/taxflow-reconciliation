"""Deterministic Python checks: completeness, validity, evidence, and arithmetic.

Rounding rule (documented): each calculated item total is quantity x unit_price,
rounded to cents with ROUND_HALF_UP. Differences strictly greater than USD 0.01
are flagged. The subtotal is compared with the sum of the *stated* line totals,
so a single wrong line total is reported once (ITEM_MISMATCH) rather than
cascading; the sum of calculated totals is reported in the check details.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .evidence import evidence_problems
from .models import ITEM_FIELDS, MONEY_FIELDS, CheckResult, Finding, InvoiceDraft

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
_MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")
_QTY_RE = re.compile(r"^\d+(\.\d+)?$")

REQUIRED_SCALARS = ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")
ARITHMETIC_CODES = {"ITEM_MISMATCH", "SUBTOTAL_MISMATCH", "TOTAL_MISMATCH"}


def money(value: str | None) -> Decimal | None:
    """Parse a nonnegative decimal-string amount with at most two decimals; None if invalid."""
    if value is None or not _MONEY_RE.match(value.strip()):
        return None
    return Decimal(value.strip())


def quantity(value: str | None) -> Decimal | None:
    if value is None or not _QTY_RE.match(value.strip()):
        return None
    q = Decimal(value.strip())
    return q if q > 0 else None


def fmt(d: Decimal) -> str:
    return str(d.quantize(CENT, rounding=ROUND_HALF_UP))


def _f(code, field, message, **details) -> Finding:
    src = "reconcile_invoice" if code in ARITHMETIC_CODES else "validate_intake"
    return Finding(code=code, field=field, message=message, source=src, details=details)


def required_field_findings(draft: InvoiceDraft) -> list[Finding]:
    out = []
    for name in REQUIRED_SCALARS:
        if draft.scalar(name).value is None:
            out.append(_f("MISSING_FIELD", name, f"Required field {name} is missing."))
    if not draft.line_items:
        out.append(_f("MISSING_FIELD", "line_items", "No usable line items were found."))
    else:
        for i, item in enumerate(draft.line_items):
            for name in ITEM_FIELDS:
                if getattr(item, name).value is None:
                    path = f"line_items[{i}].{name}"
                    out.append(_f("MISSING_FIELD", path, f"Line item {i + 1} is missing {name}."))
    return out


def validate(draft: InvoiceDraft) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    checks: list[CheckResult] = []

    missing = required_field_findings(draft)
    findings += missing
    checks.append(CheckResult(
        name="required_fields",
        status="fail" if missing else "pass",
        details={"missing": [f.field for f in missing]},
    ))

    invalid: list[Finding] = []
    for name in MONEY_FIELDS:
        v = draft.scalar(name).value
        if v is not None and money(v) is None:
            invalid.append(_f("INVALID_AMOUNT", name, f"{name} '{v}' is not a nonnegative amount."))
    for i, item in enumerate(draft.line_items or []):
        for name in ("unit_price", "line_total"):
            v = getattr(item, name).value
            if v is not None and money(v) is None:
                invalid.append(_f("INVALID_AMOUNT", f"line_items[{i}].{name}", f"'{v}' is not a nonnegative amount."))
        q = item.quantity.value
        if q is not None and quantity(q) is None:
            invalid.append(_f("INVALID_AMOUNT", f"line_items[{i}].quantity", f"Quantity '{q}' is not a positive number."))
    findings += invalid
    checks.append(CheckResult(name="amount_validity", status="fail" if invalid else "pass",
                              details={"invalid": [f.field for f in invalid]}))

    date_val = draft.invoice_date.value
    if date_val is None:
        checks.append(CheckResult(name="invoice_date", status="not_checked", reason="invoice_date is missing"))
    else:
        try:
            dt.date.fromisoformat(date_val)
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
                raise ValueError
            checks.append(CheckResult(name="invoice_date", status="pass"))
        except ValueError:
            findings.append(_f("INVALID_DATE", "invoice_date", f"Invoice date '{date_val}' is not an ISO date."))
            checks.append(CheckResult(name="invoice_date", status="fail"))

    cur = draft.currency.value
    if cur is None:
        checks.append(CheckResult(name="currency", status="not_checked", reason="currency is missing"))
    elif cur.strip().upper() != "USD":
        findings.append(_f("UNSUPPORTED_CURRENCY", "currency", f"Currency '{cur}' is not supported; v1 accepts USD only."))
        checks.append(CheckResult(name="currency", status="fail"))
    else:
        checks.append(CheckResult(name="currency", status="pass"))

    if draft.unsupported_structures:
        findings.append(_f("UNSUPPORTED_STRUCTURE", None,
                           "Invoice contains adjustments v1 does not calculate: " + ", ".join(draft.unsupported_structures) + ".",
                           structures=draft.unsupported_structures))
        checks.append(CheckResult(name="supported_structure", status="fail"))
    else:
        checks.append(CheckResult(name="supported_structure", status="pass"))

    problems = evidence_problems(draft)
    for path, reason in problems:
        findings.append(_f("UNSUPPORTED_EVIDENCE", path, f"Source evidence for {path} is not verified: {reason}."))
    checks.append(CheckResult(name="source_evidence", status="fail" if problems else "pass",
                              details={"unverified": [p for p, _ in problems]}))
    return findings, checks


def reconcile(draft: InvoiceDraft) -> tuple[list[Finding], list[CheckResult]]:
    findings: list[Finding] = []
    checks: list[CheckResult] = []

    if draft.unsupported_structures:
        reason = "unsupported adjustment structure; v1 does not calculate it"
        for name in ("item_totals", "subtotal", "total"):
            checks.append(CheckResult(name=name, status="not_checked", reason=reason))
        return findings, checks

    items = draft.line_items or []
    stated_totals: list[Decimal | None] = []
    calc_totals: list[Decimal | None] = []
    if not items:
        checks.append(CheckResult(name="item_totals", status="not_checked", reason="no line items"))
    for i, item in enumerate(items):
        q, p, t = quantity(item.quantity.value), money(item.unit_price.value), money(item.line_total.value)
        stated_totals.append(t)
        name = f"item_total[{i}]"
        if q is None or p is None or t is None:
            missing = [n for n, v in (("quantity", q), ("unit_price", p), ("line_total", t)) if v is None]
            calc_totals.append(None)
            checks.append(CheckResult(name=name, status="not_checked",
                                      reason="missing or invalid " + ", ".join(missing)))
            continue
        expected = (q * p).quantize(CENT, rounding=ROUND_HALF_UP)
        calc_totals.append(expected)
        diff = t - expected
        details = {"expected": fmt(expected), "stated": fmt(t), "difference": fmt(diff)}
        if abs(diff) > TOLERANCE:
            findings.append(_f("ITEM_MISMATCH", f"line_items[{i}].line_total",
                               f"Line item {i + 1}: {item.quantity.value} x {fmt(p)} = USD {fmt(expected)}, "
                               f"but the stated line total is USD {fmt(t)} (difference USD {fmt(diff)}).", **details))
            checks.append(CheckResult(name=name, status="fail", details=details))
        else:
            checks.append(CheckResult(name=name, status="pass", details=details))

    sub = money(draft.subtotal.value)
    if not items:
        checks.append(CheckResult(name="subtotal", status="not_checked", reason="no line items"))
    elif any(t is None for t in stated_totals):
        checks.append(CheckResult(name="subtotal", status="not_checked", reason="a line total is missing or invalid"))
    elif sub is None:
        checks.append(CheckResult(name="subtotal", status="not_checked", reason="subtotal is missing or invalid"))
    else:
        item_sum = sum(stated_totals, Decimal("0"))
        diff = sub - item_sum
        details = {"expected": fmt(item_sum), "stated": fmt(sub), "difference": fmt(diff)}
        if all(c is not None for c in calc_totals):
            details["sum_of_calculated_item_totals"] = fmt(sum(calc_totals, Decimal("0")))
        if abs(diff) > TOLERANCE:
            findings.append(_f("SUBTOTAL_MISMATCH", "subtotal",
                               f"Line totals add up to USD {fmt(item_sum)}, but the stated subtotal is USD {fmt(sub)} "
                               f"(difference USD {fmt(diff)}).", **details))
            checks.append(CheckResult(name="subtotal", status="fail", details=details))
        else:
            checks.append(CheckResult(name="subtotal", status="pass", details=details))

    tax, total = money(draft.tax.value), money(draft.total.value)
    if sub is None or tax is None or total is None:
        missing = [n for n, v in (("subtotal", sub), ("tax", tax), ("total", total)) if v is None]
        checks.append(CheckResult(name="total", status="not_checked",
                                  reason="missing or invalid " + ", ".join(missing)))
    else:
        expected = sub + tax
        diff = total - expected
        details = {"expected": fmt(expected), "stated": fmt(total), "difference": fmt(diff)}
        if abs(diff) > TOLERANCE:
            direction = "higher" if diff > 0 else "lower"
            findings.append(_f("TOTAL_MISMATCH", "total",
                               f"USD {fmt(sub)} + USD {fmt(tax)} = USD {fmt(expected)}; the stated total USD {fmt(total)} "
                               f"is USD {fmt(abs(diff))} {direction}.", **details))
            checks.append(CheckResult(name="total", status="fail", details=details))
        else:
            checks.append(CheckResult(name="total", status="pass", details=details))
    return findings, checks
