"""Offline tests for ledger CSV validation and deterministic matching/comparison."""
import pytest

from taxflow import matching
from taxflow.ledger import COLUMNS, TEMPLATE_CSV, LedgerError, decode_ledger_upload, parse_ledger_csv
from taxflow.models import ExtractedValue, InvoiceDraft
from taxflow.parsing import InputError
from taxflow.pipeline import run_illustrative
from taxflow.samples import TEMPLATE_LEDGER, load_sample, load_sample_ledger

HEADER = ",".join(COLUMNS)


def L(*rows):
    return parse_ledger_csv(HEADER + "\n" + "\n".join(rows) + "\n", "t.csv")


def V(v):
    return ExtractedValue(value=v)


def inv(number="INV-1", vendor="Acme Ltd", date="2026-09-01", currency="USD", total="100.00"):
    return InvoiceDraft(invoice_number=V(number), vendor_name=V(vendor), invoice_date=V(date),
                        currency=V(currency), total=V(total))


# ---------- Ledger validation ----------

def test_template_and_sample_ledger_valid():
    assert TEMPLATE_CSV.strip() == HEADER == TEMPLATE_LEDGER.read_text().strip()
    led = load_sample_ledger()
    assert len(led.entries) == 12 and led.entries[0].row_number == 2


def test_column_errors():
    with pytest.raises(LedgerError, match="missing column"):
        parse_ledger_csv("ledger_entry_id,invoice_number\nA,1\n", "x.csv")
    with pytest.raises(LedgerError, match="unexpected column"):
        parse_ledger_csv(HEADER + ",notes\nA,1,V,2026-01-01,USD,1.00,x\n", "x.csv")


@pytest.mark.parametrize("row,msg", [
    ("A,INV-1,Acme,2026-13-01,USD,1.00", "invoice_date"),
    ("A,INV-1,Acme,01/02/2026,USD,1.00", "invoice_date"),
    ("A,INV-1,Acme,2026-01-01,ABC,1.00", "currency"),
    ("A,INV-1,Acme,2026-01-01,XAU,1.00", "currency"),
    ("A,INV-1,Acme,2026-01-01,USD,-1.00", "gross_amount"),
    ("A,INV-1,Acme,2026-01-01,USD,1.005", "gross_amount"),
    ("A,INV-1,Acme,2026-01-01,USD,\"1,000.00\"", "gross_amount"),
    (",INV-1,Acme,2026-01-01,USD,1.00", "ledger_entry_id is empty"),
    ("A,,Acme,2026-01-01,USD,1.00", "invoice_number is empty"),
])
def test_row_validation(row, msg):
    with pytest.raises(LedgerError, match=msg):
        L(row)


def test_duplicate_entry_ids_and_row_numbers():
    with pytest.raises(LedgerError, match="row 3: ledger_entry_id 'A' duplicates row 2"):
        L("A,INV-1,Acme,2026-01-01,USD,1.00", "A,INV-2,Acme,2026-01-01,USD,1.00")


def test_upload_limits():
    with pytest.raises(InputError):
        decode_ledger_upload(b"", "a.csv")
    with pytest.raises(InputError):
        decode_ledger_upload(b"\xff\xfe", "a.csv")
    with pytest.raises(InputError):
        decode_ledger_upload(HEADER.encode(), "a.txt")
    with pytest.raises(LedgerError, match="no ledger entries"):
        decode_ledger_upload((HEADER + "\n").encode(), "a.csv")
    led = decode_ledger_upload(("﻿" + HEADER + "\nA,INV-1,Acme,2026-01-01,usd,1.00\n").encode(), "a.csv")
    assert led.entries[0].currency == "USD"


# ---------- Matching ----------

def test_normalization_is_conservative():
    led = L("A,inv-1, ACME   ltd ,2026-09-01,USD,100.00", "B,INV1,Acme Ltd,2026-09-01,USD,100.00",
            "C,INV-1,Acme Ltd.,2026-09-01,USD,100.00")
    ids = [e.ledger_entry_id for e in matching.find_candidates(led.entries, inv())]
    assert ids == ["A"]  # case/whitespace only; no punctuation stripping, no fuzzy matching


def test_all_candidates_returned_and_amount_never_selects():
    led = L("A,INV-1,Acme Ltd,2026-09-01,USD,100.00", "B,INV-1,Acme Ltd,2026-09-01,USD,999.00",
            "C,INV-9,Acme Ltd,2026-09-01,USD,100.00")
    d = inv()
    cands = matching.find_candidates(led.entries, d)
    assert [c.ledger_entry_id for c in cands] == ["A", "B"]
    assert matching.outcome(d, cands, []) == "Ambiguous match"
    assert [f.code for f in matching.search_findings(d, cands)] == ["LEDGER_AMBIGUOUS"]
    # same amount, different number: no match
    other = inv(number="INV-5")
    assert matching.find_candidates(led.entries, other) == []
    assert matching.outcome(other, [], []) == "No matching entry"


def test_vendor_must_match_too():
    led = L("A,INV-1,Other Co,2026-09-01,USD,100.00")
    assert matching.find_candidates(led.entries, inv()) == []


def test_missing_identifiers_not_searched():
    d = inv(number=None)
    assert matching.find_candidates(L("A,INV-1,Acme Ltd,2026-09-01,USD,100.00").entries, d) == []
    assert [f.code for f in matching.search_findings(d, [])] == ["LEDGER_NOT_SEARCHED"]
    assert matching.outcome(d, [], []) == "Needs clarification"


def _cmp(entry_row, **inv_kw):
    led = L(entry_row)
    d = inv(**inv_kw)
    rows, findings = matching.compare(d, led.entries[0])
    return {r.field: r for r in rows}, sorted(f.code for f in findings), matching.outcome(d, list(led.entries), rows)


def test_compare_matched_and_tolerance():
    rows, codes, out = _cmp("A,INV-1,Acme Ltd,2026-09-01,USD,100.01")
    assert codes == [] and out == "Matched" and rows["stated_total_vs_gross_amount"].difference == "-0.01"
    rows, codes, out = _cmp("A,INV-1,Acme Ltd,2026-09-01,USD,100.02")
    assert codes == ["LEDGER_AMOUNT_MISMATCH"] and out == "Discrepancy found"


def test_currency_compared_first_and_blocks_amount():
    rows, codes, out = _cmp("A,INV-1,Acme Ltd,2026-09-01,EUR,100.00")
    assert codes == ["LEDGER_CURRENCY_MISMATCH"] and out == "Discrepancy found"
    assert rows["stated_total_vs_gross_amount"].status == "not_checked"


def test_date_mismatch():
    rows, codes, out = _cmp("A,INV-1,Acme Ltd,2026-09-02,USD,100.00")
    assert codes == ["LEDGER_DATE_MISMATCH"] and out == "Discrepancy found"


@pytest.mark.parametrize("kw,incomplete", [({"date": None}, ["invoice_date"]),
                                           ({"total": None}, ["stated_total_vs_gross_amount"]),
                                           ({"currency": None}, ["currency", "stated_total_vs_gross_amount"])])
def test_incomplete_comparison_is_never_matched(kw, incomplete):
    rows, codes, out = _cmp("A,INV-1,Acme Ltd,2026-09-01,USD,100.00", **kw)
    assert codes == ["LEDGER_COMPARISON_INCOMPLETE"] and out == "Needs clarification"


def test_missing_currency_dev_sample():
    """Missing currency is covered in development tests (not in the held-out set)."""
    r = run_illustrative(load_sample("missing_currency"), "missing_currency", load_sample_ledger())
    assert r.reconciliation_outcome == "Needs clarification"
    assert {(f.code, f.field) for f in r.findings if f.blocking} == {("MISSING_FIELD", "currency"),
                                                                     ("LEDGER_COMPARISON_INCOMPLETE", None)}
    assert r.ledger_entry.ledger_entry_id == "DEV-1008" and not r.can_approve


def test_dev_samples_outcomes():
    led = load_sample_ledger()
    expected = {
        "matched_clean": ("Matched", "DEV-1001"),
        "arithmetic_wrong_ledger_agrees": ("Matched", "DEV-1007"),
        "amount_difference": ("Discrepancy found", "DEV-1002"),
        "currency_difference": ("Discrepancy found", "DEV-1005"),
        "date_difference": ("Discrepancy found", "DEV-1006"),
        "duplicate_candidates": ("Ambiguous match", None),
        "no_matching_entry": ("No matching entry", None),  # DEV-1010 has the same amount but a different number
        "missing_invoice_number": ("Needs clarification", None),  # DEV-1011 has the same amount
        "embedded_instruction": ("Matched", "DEV-1009"),
        "unsupported_document": ("Unsupported document", None),
    }
    for sid, (out, eid) in expected.items():
        r = run_illustrative(load_sample(sid), sid, led)
        assert r.reconciliation_outcome == out, sid
        assert (r.ledger_entry.ledger_entry_id if r.ledger_entry else None) == eid, sid


def test_indexed_lookup_equals_linear_scan():
    """The index is an optimization only: same matching rule, same candidates, same order."""
    led = L("A,INV-1,Acme Ltd,2026-09-01,USD,100.00", "B, inv-1 ,ACME  LTD,2026-09-01,USD,100.00",
            "C,INV-1,Acme Ltd.,2026-09-01,USD,100.00", "D,INV-2,Acme Ltd,2026-09-01,USD,100.00")
    for d in (inv(), inv(number=" INV-1"), inv(vendor="acme ltd."), inv(number="INV-9"), inv(number=None)):
        if matching.identifiers_missing(d):
            continue
        assert matching.find_candidates_indexed(led.index, d) == matching.find_candidates(led.entries, d)
    sample = load_sample_ledger()
    for e in sample.entries:
        d = inv(number=e.invoice_number, vendor=e.vendor_name)
        assert matching.find_candidates_indexed(sample.index, d) == matching.find_candidates(sample.entries, d)
