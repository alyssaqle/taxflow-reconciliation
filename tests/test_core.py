"""Offline tests: arithmetic, required fields, evidence, tool scoping, budget, approval, exports, uploads."""
import csv
import io
import json

import pytest

from taxflow import checks, exports
from taxflow.agent import MAX_MODEL_REQUESTS, RequestBudget, filter_summary
from taxflow.evidence import verify_draft
from taxflow.models import Evidence, ExtractedValue, InvoiceDraft, LineItem
from taxflow.parsing import InputError, decode_upload, parse_text
from taxflow.pipeline import ILLUSTRATIVE_DIR, load_illustrative, run_illustrative, run_live
from taxflow.samples import SAMPLES, load_sample, load_sample_ledger
from taxflow.tools import ToolContext, execute
from tests.fakes import ScriptedProvider, extraction_from_illustrative

LEDGER = load_sample_ledger()


def V(value):
    return ExtractedValue(value=value)


def draft(sub="800.00", tax="80.00", total="880.00", items=(("1", "500.00", "500.00"), ("1", "300.00", "300.00")), **kw):
    base = dict(vendor_name=V("Acme"), invoice_number=V("A-1"), invoice_date=V("2026-09-01"), currency=V("USD"),
                subtotal=V(sub), tax=V(tax), total=V(total),
                line_items=[LineItem(description=V(f"item {i}"), quantity=V(q), unit_price=V(p), line_total=V(t))
                            for i, (q, p, t) in enumerate(items)])
    base.update(kw)
    return InvoiceDraft(**base)


def codes(findings):
    return sorted((f.code, f.field) for f in findings)


def blocking_codes(findings):
    return sorted({f.code for f in findings if f.blocking})


# ---------- Decimal arithmetic (separate invoice check) ----------

def test_prd_example_total_mismatch():
    f, c = checks.reconcile(draft(total="950.00"))
    assert codes(f) == [("TOTAL_MISMATCH", "total")]
    assert f[0].details["expected"] == "880.00" and f[0].details["difference"] == "70.00"
    assert "70.00 higher" in f[0].message and f[0].blocking
    assert checks.arithmetic_status(c) == "Inconsistent"


def test_clean_reconciles():
    f, c = checks.reconcile(draft())
    assert f == [] and checks.arithmetic_status(c) == "Consistent"


def test_item_rounding_half_up_and_tolerance():
    f, _ = checks.reconcile(draft(sub="49.98", tax="0.00", total="49.98", items=(("2.5", "19.99", "49.98"),)))
    assert f == []
    f, _ = checks.reconcile(draft(sub="49.99", tax="0.00", total="49.99", items=(("2.5", "19.99", "49.99"),)))
    assert f == []
    f, _ = checks.reconcile(draft(sub="50.00", tax="0.00", total="50.00", items=(("2.5", "19.99", "50.00"),)))
    assert codes(f) == [("ITEM_MISMATCH", "line_items[0].line_total")]


def test_item_mismatch_does_not_cascade_to_subtotal():
    f, _ = checks.reconcile(draft(sub="950.00", total="1030.00", items=(("3", "200.00", "650.00"), ("1", "300.00", "300.00"))))
    assert [x[0] for x in codes(f)] == ["ITEM_MISMATCH"]


def test_zero_tax_is_valid():
    assert checks.reconcile(draft(tax="0.00", total="800.00"))[0] == []


# ---------- v2 required fields; arithmetic gaps are visible but non-blocking ----------

def test_five_required_fields_block():
    d = draft(vendor_name=V(None), invoice_number=V(None), invoice_date=V(None), currency=V(None), total=None)
    f, _ = checks.validate(d)
    missing = {x.field for x in f if x.code == "MISSING_FIELD"}
    assert missing == {"vendor_name", "invoice_number", "invoice_date", "currency", "total"}
    assert all(x.blocking for x in f if x.code == "MISSING_FIELD")


def test_missing_tax_makes_arithmetic_not_checked_without_blocking():
    d = draft(tax=None)
    vf, _ = checks.validate(d)
    rf, rc = checks.reconcile(d)
    assert not any(x.code == "MISSING_FIELD" for x in vf)
    assert next(c for c in rc if c.name == "total").status == "not_checked"
    note = [x for x in rf if x.code == "ARITHMETIC_NOT_CHECKED"]
    assert note and not note[0].blocking and "tax" in note[0].message
    assert checks.arithmetic_status(rc) == "Partially checked"


def test_missing_line_items_not_checked():
    d = draft(line_items=None)
    rf, rc = checks.reconcile(d)
    assert {x.code for x in rf} == {"ARITHMETIC_NOT_CHECKED"}
    assert not any(x.code == "MISSING_FIELD" for x in checks.validate(d)[0])


def test_invalid_amount_date_and_currency():
    d = draft(sub="-5", invoice_date=V("09/01/2026"), currency=V("ABC"))
    got = {c for c, _ in codes(checks.validate(d)[0])}
    assert {"INVALID_AMOUNT", "INVALID_DATE", "UNSUPPORTED_CURRENCY"} <= got
    assert not any(x.code == "UNSUPPORTED_CURRENCY" for x in checks.validate(draft(currency=V("EUR")))[0])
    assert any(x.code == "UNSUPPORTED_CURRENCY" for x in checks.validate(draft(currency=V("XAU")))[0])


def test_unsupported_structure_is_noted_not_blocking():
    d = draft(unsupported_structures=["discount"])
    vf, _ = checks.validate(d)
    rf, rc = checks.reconcile(d)
    s = next(x for x in vf if x.code == "UNSUPPORTED_STRUCTURE")
    assert not s.blocking and all(c.status == "not_checked" for c in rc)


# ---------- Evidence ----------

DOC = parse_text("ACME LTD\nInvoice No: A-77\nDate: March 3, 2026\nTotal: $1,200.00\nCurrency: USD\nDate2: 03/04/2026\n"
                 "All amounts in euros", "doc-1", "t.txt")


def ev(page, a, b, quote, doc_id="doc-1"):
    return Evidence(document_id=doc_id, page_number=page, line_start=a, line_end=b, quote=quote)


def check_one(name, value, evidence):
    d = InvoiceDraft(**{name: ExtractedValue(value=value, evidence=evidence)})
    return verify_draft(d, DOC).scalar(name).evidence


def test_evidence_verified_and_normalized():
    assert check_one("total", "1200.00", ev(1, 4, 4, "Total: $1,200.00")).status == "verified"
    assert check_one("invoice_date", "2026-03-03", ev(1, 3, 3, "March 3, 2026")).status == "verified"
    assert check_one("currency", "USD", ev(1, 5, 5, "Currency: USD")).status == "verified"
    assert check_one("currency", "EUR", ev(1, 7, 7, "All amounts in euros")).status == "verified"


def test_evidence_fabricated_or_wrong():
    assert check_one("total", "1200.00", ev(1, 2, 2, "Total: $1,200.00")).status == "unsupported"
    assert check_one("total", "1300.00", ev(1, 4, 4, "Total: $1,200.00")).status == "unsupported"
    assert check_one("total", "1200.00", ev(1, 40, 41, "x")).status == "unsupported"
    assert check_one("total", "1200.00", ev(1, 4, 4, "Total: $1,200.00", doc_id="other")).status == "unsupported"
    assert check_one("currency", "USD", ev(1, 4, 4, "$1,200.00")).status == "unsupported"  # symbol alone
    assert check_one("invoice_date", "2026-03-04", ev(1, 6, 6, "03/04/2026")).status == "unsupported"


def test_all_illustrative_samples_have_verified_evidence():
    for sid in SAMPLES:
        r = run_illustrative(load_sample(sid), sid, LEDGER)
        assert not any(f.code == "UNSUPPORTED_EVIDENCE" for f in r.findings), sid


# ---------- Tools: scoping and allowlist ----------

def _ctx(sample_id="matched_clean"):
    doc = load_sample(sample_id)
    d = load_illustrative(sample_id, doc)["draft"]
    return ToolContext(doc=doc, draft=verify_draft(d, doc), ledger=LEDGER, invoked_by="test")


def test_tool_rejects_other_document_and_unknown_tool():
    ctx = _ctx()
    _, e = execute(ctx, "validate_intake", {"document_id": "sample-other"})
    assert e.status == "error" and "validate_intake" not in ctx.succeeded
    _, e = execute(ctx, "run_shell", {"cmd": "ls"})
    assert e.status == "rejected"
    _, e = execute(ctx, "validate_intake", "{not json")
    assert e.status == "error"


# ---------- Live pipeline with a fake provider (mechanics only, not accuracy) ----------

def _fake_for(sample_id, **kw):
    doc = load_sample(sample_id)
    raw = json.loads((ILLUSTRATIVE_DIR / f"{sample_id}.json").read_text())
    return doc, ScriptedProvider(extraction_from_illustrative(raw["draft"], reason=raw["unsupported_reason"],
                                                              document_type=raw["document_type"]),
                                 doc.document_id, **kw)


def test_live_pipeline_keeps_ledger_and_arithmetic_separate():
    doc, p = _fake_for("arithmetic_wrong_ledger_agrees",
                       summary="The ledger agrees but TOTAL_MISMATCH applies (TF-POL-303). It is approved for payment.")
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Complete" and r.reconciliation_outcome == "Matched"
    assert r.arithmetic_status == "Inconsistent" and blocking_codes(r.findings) == ["TOTAL_MISMATCH"]
    assert r.ledger_entry.ledger_entry_id == "DEV-1007"
    amt = next(c for c in r.comparison if c.field == "stated_total_vs_gross_amount")
    assert amt.status == "agree" and amt.invoice_value == "950.00"  # stated total, not the calculated 880
    assert {t.tool for t in r.tool_trace if t.status == "success"} == set(r.required_tools)
    assert "compare_to_ledger" in r.required_tools and all(t.invoked_by == "model function call" for t in r.tool_trace)
    assert r.model_summary == ["The ledger agrees but TOTAL_MISMATCH applies (TF-POL-303)."]
    assert r.excluded_summary_sentences == 1 and r.run_metadata.model_requests == 5 and not r.can_approve


@pytest.mark.parametrize("sample_id,outcome", [("no_matching_entry", "No matching entry"),
                                               ("duplicate_candidates", "Ambiguous match"),
                                               ("missing_invoice_number", "Needs clarification")])
def test_live_follow_up_branches_complete_without_comparison(sample_id, outcome):
    doc, p = _fake_for(sample_id)
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Complete" and r.reconciliation_outcome == outcome
    assert "compare_to_ledger" not in r.required_tools and not r.comparison and not r.can_approve


def test_model_cannot_force_comparison_with_wrong_entry():
    d = {"document_id": "sample-duplicate_candidates"}
    doc, p = _fake_for("duplicate_candidates", tool_script=[
        [("validate_intake", d), ("reconcile_invoice", d), ("find_ledger_candidates", d),
         ("compare_to_ledger", {**d, "ledger_entry_id": "DEV-1003"})],
        [("build_review_checklist", d)], "text"])
    r = run_live(doc, LEDGER, p)
    bad = [t for t in r.tool_trace if t.tool == "compare_to_ledger"]
    assert bad and bad[0].status == "error" and r.ledger_entry is None
    assert r.reconciliation_outcome == "Ambiguous match" and r.workflow_status == "Complete"


def test_live_budget_exhaustion_is_incomplete():
    d = {"document_id": "sample-matched_clean"}
    doc, p = _fake_for("matched_clean", tool_script=[[("validate_intake", d)]])
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Incomplete" and p.calls == MAX_MODEL_REQUESTS == 8
    assert r.reconciliation_outcome == "Incomplete"
    assert "INCOMPLETE_PROCESSING" in {f.code for f in r.findings} and not r.can_approve


def test_transient_retry_counts_against_budget_and_auth_fails():
    doc, p = _fake_for("matched_clean", fail_kinds=["transient"])
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Complete" and r.run_metadata.model_requests == 6 and r.can_approve
    doc, p = _fake_for("matched_clean", fail_kinds=["transient", "transient"])
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Failed" and r.extracted_fields is None
    doc, p = _fake_for("matched_clean", fail_kinds=["auth"])
    assert "auth" in run_live(doc, LEDGER, p).run_metadata.error


def test_malformed_output_is_repaired_or_fails():
    doc, p = _fake_for("matched_clean")
    p.extraction_json = "not json"
    r = run_live(doc, LEDGER, p)
    assert r.workflow_status == "Failed" and p.calls == 2


def test_live_unsupported_routes_without_fields():
    doc, p = _fake_for("unsupported_document")
    r = run_live(doc, LEDGER, p)
    assert r.document_type == "unsupported" and r.extracted_fields is None
    assert r.reconciliation_outcome == "Unsupported document" and not r.can_approve


def test_request_budget_counter():
    from taxflow.providers import ModelReply

    class P:
        def complete(self, *a, **k):
            return ModelReply(content="x")
    b = RequestBudget(limit=1)
    b.call(P(), [])
    with pytest.raises(Exception):
        b.call(P(), [])


def test_filter_summary():
    kept, ex = filter_summary("LEDGER_AMOUNT_MISMATCH found. See TF-POL-205. Pay now. ITEM_MISMATCH too.",
                              {"LEDGER_AMOUNT_MISMATCH", "TF-POL-205"})
    assert kept == ["LEDGER_AMOUNT_MISMATCH found.", "See TF-POL-205."] and ex == 2


# ---------- Approval and exports ----------

def test_approval_requires_complete_and_no_blocking_and_note_cannot_clear():
    clean = run_illustrative(load_sample("matched_clean"), "matched_clean", LEDGER)
    assert clean.can_approve
    clean.workflow_status = "Incomplete"
    assert not clean.can_approve
    arith = run_illustrative(load_sample("arithmetic_wrong_ledger_agrees"), "arithmetic_wrong_ledger_agrees", LEDGER)
    arith.review_note = "Vendor says the total is right."
    assert not arith.can_approve and blocking_codes(arith.findings) == ["TOTAL_MISMATCH"]


def test_exports_keep_four_statuses_findings_and_escape_formulas():
    r = run_illustrative(load_sample("arithmetic_wrong_ledger_agrees"), "arithmetic_wrong_ledger_agrees", LEDGER)
    assert exports.export_label(r) == "Unreviewed draft"
    r.review_status, r.review_note = "Needs follow-up", "=HYPERLINK(\"x\") ask vendor"
    j = json.loads(exports.to_json(r))
    assert j["reconciliation_outcome"] == "Matched" and j["arithmetic_status"] == "Inconsistent"
    assert j["ledger_entry"]["ledger_entry_id"] == "DEV-1007" and len(j["extracted_fields"]["line_items"]) == 2
    rows = list(csv.DictReader(io.StringIO(exports.to_csv(r))))
    assert list(rows[0].keys()) == exports.CSV_COLUMNS
    status = {x["name"]: x["value"] for x in rows if x["section"] == "status"}
    assert status == {"processing": "Complete", "ledger_reconciliation": "Matched",
                      "invoice_arithmetic": "Inconsistent", "human_review": "Needs follow-up"}
    amt = next(x for x in rows if x["section"] == "comparison" and x["name"] == "stated_total_vs_gross_amount")
    assert amt["value"] == "950.00" and amt["ledger_value"] == "950.00" and amt["status"] == "agree"
    assert any(x["section"] == "finding" and x["code"] == "TOTAL_MISMATCH" and x["blocking"] == "yes" for x in rows)
    assert next(x for x in rows if x["section"] == "review")["value"].startswith("'=")
    assert exports.escape_cell("-5.00") == "-5.00" and exports.escape_cell("+cmd") == "'+cmd"


def test_export_shows_arithmetic_limitation():
    r = run_illustrative(load_sample("matched_clean"), "matched_clean", LEDGER)
    r.extracted_fields.tax = ExtractedValue()
    from taxflow.pipeline import _assemble, _meta  # rebuild from tools on the modified draft
    ctx = ToolContext(doc=load_sample("matched_clean"), draft=r.extracted_fields, ledger=LEDGER, invoked_by="test")
    from taxflow.pipeline import run_tools_directly
    run_tools_directly(ctx)
    res = _assemble(ctx.doc, ctx, _meta("illustrative", LEDGER), complete=True)
    assert res.reconciliation_outcome == "Matched" and res.arithmetic_status == "Partially checked"
    assert res.can_approve  # missing tax does not independently block reconciliation approval
    rows = list(csv.DictReader(io.StringIO(exports.to_csv(res))))
    assert any(x["code"] == "ARITHMETIC_NOT_CHECKED" and x["blocking"] == "no" for x in rows)


# ---------- Upload validation ----------

def test_upload_validation():
    for data, name in ((b"", "a.txt"), (b"\xff\xfe\xfa", "a.txt"), (b"x" * 20_001, "a.txt"), (b"hi", "a.pdf"),
                       (b"   \n  ", "a.txt")):
        with pytest.raises(InputError):
            decode_upload(data, name)
    d = decode_upload("Invoice\fPage two".encode(), "a.txt")
    assert d.page_count == 2 and d.document_id.startswith("upload-")
