"""App-level tests with Streamlit's AppTest (no network; simulates the public deployment)."""
import os

from streamlit.testing.v1 import AppTest


def _run_analysis(at):
    next(b for b in at.button if b.label == "Analyze invoice").click().run()
    for _ in range(20):
        if "result" in at.session_state and at.session_state["result"] is not None:
            return at.session_state["result"]
        at.run()
    raise AssertionError("no result")


def _app():
    """No credentials, live mode off (ignores any local secrets.toml)."""
    os.environ["LIVE_MODE_ENABLED"] = "false"
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.secrets["LIVE_MODE_ENABLED"] = "false"
    at = at.run()
    at.radio[0].set_value("Illustrative demo").run()
    return at


def test_public_mode_has_no_upload_and_no_live_option():
    at = _app()
    assert not at.exception
    assert "Live agent" not in at.radio[0].options
    assert len(at.get("file_uploader")) == 0
    labels = [b.label for b in at.get("download_button")]
    assert "CSV template" in labels and "Sample ledger" in labels


def test_approve_then_rerun_resets_decision():
    at = _app()
    at.selectbox[0].set_value("matched_clean").run()
    res = _run_analysis(at)
    assert res.can_approve and res.reconciliation_outcome == "Matched"
    approve = next(b for b in at.button if b.label == "Approve")
    assert not approve.disabled
    approve.click().run()
    assert at.session_state["result"].review_status == "Approved"
    res2 = _run_analysis(at)
    assert res2.run_id != res.run_id and res2.review_status == "Unreviewed"


def test_arithmetic_blocks_even_when_ledger_agrees_and_new_input_resets():
    at = _app()
    at.selectbox[0].set_value("arithmetic_wrong_ledger_agrees").run()
    res = _run_analysis(at)
    assert not at.exception
    assert res.reconciliation_outcome == "Matched" and res.arithmetic_status == "Inconsistent"
    assert next(b for b in at.button if b.label == "Approve").disabled
    next(b for b in at.button if b.label == "Needs follow-up").click().run()
    assert at.session_state["result"].review_status == "Needs follow-up"
    at.selectbox[0].set_value("matched_clean").run()
    assert at.session_state["result"] is None if "result" in at.session_state else True


def test_every_sample_renders():
    at = _app()
    for sid in at.selectbox[0].options:
        at.selectbox[0].set_value(sid).run()
        _run_analysis(at)
        assert not at.exception, sid


def test_recorded_mode_replays_with_provenance():
    at = _app()
    if "Recorded live run" not in at.radio[0].options:
        return  # no recordings yet
    at.radio[0].set_value("Recorded live run").run()
    next(b for b in at.button if b.label == "Analyze invoice").click().run()
    res = at.session_state["result"]
    assert res.run_metadata.mode == "recorded_live" and res.run_metadata.recorded_from["model"]
    assert res.review_status == "Unreviewed"
    assert all(t.invoked_by == "model function call" for t in res.tool_trace)
