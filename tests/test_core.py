"""Offline tests: arithmetic, missing fields, evidence, scoping, budget, approval/reset, exports, uploads."""
import csv
import io
import json

import pytest

from taxflow import checks, exports
from taxflow.agent import RequestBudget, filter_summary
from taxflow.evidence import verify_draft
from taxflow.models import Evidence, ExtractedValue, InvoiceDraft, LineItem
from taxflow.parsing import InputError, decode_upload, parse_text
from taxflow.pipeline import load_illustrative, run_illustrative, run_live
from taxflow.samples import SAMPLES, load_sample
from taxflow.tools import ToolContext, execute
from tests.fakes import ScriptedProvider, extraction_from_illustrative


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


# ---------- Decimal arithmetic ----------

def test_prd_example_total_mismatch():
    f, c = checks.reconcile(draft(total="950.00"))
    assert codes(f) == [("TOTAL_MISMATCH", "total")]
    tm = f[0]
    assert tm.details["expected"] == "880.00" and tm.details["difference"] == "70.00"
    assert "70.00 higher" in tm.message


def test_clean_reconciles():
    f, c = checks.reconcile(draft())
    assert f == [] and all(x.status == "pass" for x in c)


def test_item_rounding_half_up_and_tolerance():
    # 2.5 x 19.99 = 49.975 -> 49.98 (ROUND_HALF_UP)
    f, _ = checks.reconcile(draft(sub="49.98", tax="0.00", total="49.98", items=(("2.5", "19.99", "49.98"),)))
    assert f == []
    # a 0.01 difference is within tolerance; 0.02 is flagged
    f, _ = checks.reconcile(draft(sub="49.99", tax="0.00", total="49.99", items=(("2.5", "19.99", "49.99"),)))
    assert f == []
    f, _ = checks.reconcile(draft(sub="50.00", tax="0.00", total="50.00", items=(("2.5", "19.99", "50.00"),)))
    assert codes(f) == [("ITEM_MISMATCH", "line_items[0].line_total")]


def test_item_mismatch_does_not_cascade_to_subtotal():
    f, _ = checks.reconcile(draft(sub="900.00", total="980.00", items=(("3", "200.00", "600.00"), ("1", "300.00", "300.00")),))
    assert [x[0] for x in codes(f)] == []  # 3 x 200 = 600 ok
    f, _ = checks.reconcile(draft(sub="950.00", total="1030.00", items=(("3", "200.00", "650.00"), ("1", "300.00", "300.00"))))
    assert [x[0] for x in codes(f)] == ["ITEM_MISMATCH"]


def test_combined_mismatches():
    f, _ = checks.reconcile(draft(sub="850.00", total="999.00", items=(("1", "500.00", "550.00"), ("1", "300.00", "300.00"))))
    assert {x.code for x in f} == {"ITEM_MISMATCH", "TOTAL_MISMATCH"}
    f, _ = checks.reconcile(draft(sub="810.00", total="890.00"))
    assert {x.code for x in f} == {"SUBTOTAL_MISMATCH"}


def test_zero_tax_is_valid():
    f, _ = checks.reconcile(draft(tax="0.00", total="800.00"))
    assert f == []


# ---------- Missing / invalid; skipped checks are not passes ----------

def test_missing_tax_skips_total_check():
    d = draft(tax=None)
    vf, _ = checks.validate(d)
    rf, rc = checks.reconcile(d)
    assert ("MISSING_FIELD", "tax") in codes(vf)
    total_check = next(c for c in rc if c.name == "total")
    assert total_check.status == "not_checked" and "tax" in total_check.reason
    assert rf == []


def test_missing_item_details():
    d = draft(items=((None, None, "800.00"),))
    vf, _ = checks.validate(d)
    assert ("MISSING_FIELD", "line_items[0].quantity") in codes(vf)
    _, rc = checks.reconcile(d)
    assert next(c for c in rc if c.name == "item_total[0]").status == "not_checked"


def test_invalid_amount_and_date_and_currency():
    d = draft(sub="-5", invoice_date=V("09/01/2026"), currency=V("EUR"))
    vf, _ = checks.validate(d)
    got = {c for c, _ in codes(vf)}
    assert {"INVALID_AMOUNT", "INVALID_DATE", "UNSUPPORTED_CURRENCY"} <= got
    _, rc = checks.reconcile(d)
    assert next(c for c in rc if c.name == "subtotal").status == "not_checked"


def test_unsupported_structure_skips_arithmetic():
    d = draft(unsupported_structures=["discount"])
    vf, _ = checks.validate(d)
    rf, rc = checks.reconcile(d)
    assert "UNSUPPORTED_STRUCTURE" in {f.code for f in vf}
    assert rf == [] and all(c.status == "not_checked" for c in rc)


# ---------- Evidence ----------

DOC = parse_text("ACME LTD\nInvoice No: A-77\nDate: March 3, 2026\nTotal: $1,200.00\nCurrency: USD\nDate2: 03/04/2026",
                 "doc-1", "t.txt")


def ev(page, a, b, quote, doc_id="doc-1"):
    return Evidence(document_id=doc_id, page_number=page, line_start=a, line_end=b, quote=quote)


def check_one(name, value, evidence):
    d = InvoiceDraft(**{name: ExtractedValue(value=value, evidence=evidence)})
    return verify_draft(d, DOC).scalar(name).evidence


def test_evidence_verified_and_normalized():
    assert check_one("total", "1200.00", ev(1, 4, 4, "Total: $1,200.00")).status == "verified"
    assert check_one("invoice_date", "2026-03-03", ev(1, 3, 3, "March 3, 2026")).status == "verified"
    assert check_one("currency", "USD", ev(1, 5, 5, "Currency: USD")).status == "verified"


def test_evidence_fabricated_or_wrong():
    assert check_one("total", "1200.00", ev(1, 2, 2, "Total: $1,200.00")).status == "unsupported"  # wrong line
    assert check_one("total", "1300.00", ev(1, 4, 4, "Total: $1,200.00")).status == "unsupported"  # value mismatch
    assert check_one("total", "1200.00", ev(1, 40, 41, "x")).status == "unsupported"  # nonexistent span
    assert check_one("total", "1200.00", ev(1, 4, 4, "Total: $1,200.00", doc_id="other")).status == "unsupported"
    # dollar sign alone does not establish USD
    assert check_one("currency", "USD", ev(1, 4, 4, "$1,200.00")).status == "unsupported"
    # ambiguous numeric date
    assert check_one("invoice_date", "2026-03-04", ev(1, 6, 6, "03/04/2026")).status == "unsupported"


def test_value_without_evidence_is_flagged():
    d = draft()
    f, _ = checks.validate(verify_draft(d, DOC))
    assert any(x.code == "UNSUPPORTED_EVIDENCE" for x in f)


def test_all_illustrative_samples_have_verified_evidence():
    for sid in SAMPLES:
        r = run_illustrative(load_sample(sid), sid)
        assert not any(f.code == "UNSUPPORTED_EVIDENCE" for f in r.findings), sid


# ---------- Tools: scoping and allowlist ----------

def test_tool_rejects_other_document_and_unknown_tool():
    doc = load_sample("clean_invoice")
    d = load_illustrative("clean_invoice", doc)["draft"]
    ctx = ToolContext(doc=doc, draft=verify_draft(d, doc), invoked_by="test")
    _, e = execute(ctx, "validate_intake", {"document_id": "sample-wrong_total"})
    assert e.status == "error" and "validate_intake" not in ctx.succeeded
    _, e = execute(ctx, "run_shell", {"cmd": "ls"})
    assert e.status == "rejected"
    _, e = execute(ctx, "validate_intake", "{not json")
    assert e.status == "error"


# ---------- Live pipeline with a fake provider (mechanics only) ----------

def _fake_for(sample_id, **kw):
    doc = load_sample(sample_id)
    raw = json.loads((load_illustrative.__globals__["ILLUSTRATIVE_DIR"] / f"{sample_id}.json").read_text())
    return doc, ScriptedProvider(extraction_from_illustrative(raw["draft"], reason=raw["unsupported_reason"],
                                                              document_type=raw["document_type"]),
                                 doc.document_id, **kw)


def test_live_pipeline_requires_all_tools_and_uses_python_findings():
    doc, p = _fake_for("wrong_total", summary="TOTAL_MISMATCH: the total is off. Also it is approved for payment.")
    r = run_live(doc, p)
    assert r.workflow_status == "Complete"
    assert {t.tool for t in r.tool_trace if t.status == "success"} == {"validate_intake", "reconcile_invoice", "lookup_intake_policy"}
    assert all(t.invoked_by == "model function call" for t in r.tool_trace)
    assert [f.code for f in r.findings] == ["TOTAL_MISMATCH"]
    assert r.model_summary == ["TOTAL_MISMATCH: the total is off."] and r.excluded_summary_sentences == 1
    assert r.run_metadata.model_requests == 4 and not r.can_approve


def test_live_budget_exhaustion_is_incomplete():
    d = {"document_id": "sample-clean_invoice"}
    doc, p = _fake_for("clean_invoice", tool_script=[[("validate_intake", d)]])  # never calls the other tools
    r = run_live(doc, p)
    assert r.workflow_status == "Incomplete" and p.calls == 6
    assert "INCOMPLETE_PROCESSING" in {f.code for f in r.findings} and not r.can_approve


def test_transient_retry_counts_against_budget_and_auth_fails():
    doc, p = _fake_for("clean_invoice", fail_kinds=["transient"])
    r = run_live(doc, p)
    assert r.workflow_status == "Complete" and r.run_metadata.model_requests == 5 and r.can_approve
    doc, p = _fake_for("clean_invoice", fail_kinds=["transient", "transient"])
    r = run_live(doc, p)
    assert r.workflow_status == "Failed" and r.extracted_fields is None
    doc, p = _fake_for("clean_invoice", fail_kinds=["auth"])
    r = run_live(doc, p)
    assert r.workflow_status == "Failed" and "auth" in r.run_metadata.error


def test_malformed_output_is_repaired_or_fails():
    doc, p = _fake_for("clean_invoice")
    p.extraction_json = "not json"
    r = run_live(doc, p)
    assert r.workflow_status == "Failed" and p.calls == 2


def test_live_unsupported_routes_without_fields():
    doc, p = _fake_for("unsupported_document")
    r = run_live(doc, p)
    assert r.document_type == "unsupported" and r.extracted_fields is None
    assert [f.code for f in r.findings] == ["UNSUPPORTED_DOCUMENT"] and not r.can_approve


def test_request_budget_counter():
    b = RequestBudget(limit=1)

    class P:
        def complete(self, *a, **k):
            from taxflow.providers import ModelReply
            return ModelReply(content="x")
    b.call(P(), [])
    with pytest.raises(Exception):
        b.call(P(), [])


def test_filter_summary():
    kept, ex = filter_summary("TOTAL_MISMATCH found. See TF-POL-203. Pay now. ITEM_MISMATCH too.",
                              {"TOTAL_MISMATCH", "TF-POL-203"})
    assert kept == ["TOTAL_MISMATCH found.", "See TF-POL-203."] and ex == 2


# ---------- Approval blocking and exports ----------

def test_approval_requires_complete_and_no_blocking():
    clean = run_illustrative(load_sample("clean_invoice"), "clean_invoice")
    assert clean.can_approve
    clean.workflow_status = "Incomplete"
    assert not clean.can_approve
    flawed = run_illustrative(load_sample("missing_invoice_number"), "missing_invoice_number")
    assert not flawed.can_approve


def test_exports_keep_findings_notes_and_escape_formulas():
    r = run_illustrative(load_sample("wrong_total"), "wrong_total")
    assert exports.export_label(r) == "Unreviewed draft"
    r.review_status, r.review_note = "Needs follow-up", "=HYPERLINK(\"x\") ask vendor"
    j = json.loads(exports.to_json(r))
    assert j["export_label"] == "Reviewed: Needs follow-up"
    assert j["findings"][0]["code"] == "TOTAL_MISMATCH" and len(j["extracted_fields"]["line_items"]) == 2
    rows = list(csv.DictReader(io.StringIO(exports.to_csv(r))))
    assert list(rows[0].keys()) == exports.CSV_COLUMNS
    assert any(x["section"] == "finding" and x["code"] == "TOTAL_MISMATCH" for x in rows)
    note = next(x for x in rows if x["section"] == "review")
    assert note["value"].startswith("'=")
    assert sum(1 for x in rows if x["section"] == "line_item") == 8
    assert exports.escape_cell("-5.00") == "-5.00" and exports.escape_cell("+cmd") == "'+cmd"


# ---------- Upload validation ----------

def test_upload_validation():
    with pytest.raises(InputError):
        decode_upload(b"", "a.txt")
    with pytest.raises(InputError):
        decode_upload(b"\xff\xfe\xfa", "a.txt")
    with pytest.raises(InputError):
        decode_upload(b"x" * 20_001, "a.txt")
    with pytest.raises(InputError):
        decode_upload(b"hello", "a.pdf")
    with pytest.raises(InputError):
        decode_upload(b"   \n  ", "a.txt")
    d = decode_upload("Invoice\fPage two".encode(), "a.txt")
    assert d.page_count == 2 and d.document_id.startswith("upload-")
