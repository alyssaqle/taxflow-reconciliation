"""Credential-dependent live smoke test. Skipped unless RUN_LIVE_TESTS=1 and Azure settings exist.

    RUN_LIVE_TESTS=1 python -m pytest tests/live -q
"""
import os
import tomllib
from pathlib import Path

import pytest

from taxflow.pipeline import run_live
from taxflow.providers import build_provider, missing_settings, read_settings
from taxflow.samples import load_sample, load_sample_ledger

_secrets = Path(__file__).resolve().parents[2] / ".streamlit" / "secrets.toml"
SETTINGS = read_settings(tomllib.loads(_secrets.read_text()) if _secrets.exists() else {})

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1" or bool(missing_settings(SETTINGS)),
                                reason="live test: set RUN_LIVE_TESTS=1 and configure Azure settings")


def test_live_ledger_agrees_but_arithmetic_wrong():
    res = run_live(load_sample("arithmetic_wrong_ledger_agrees"), load_sample_ledger(), build_provider(SETTINGS))
    assert res.workflow_status == "Complete", res.run_metadata.error
    assert set(res.required_tools) <= {t.tool for t in res.tool_trace if t.status == "success"}
    assert "compare_to_ledger" in res.required_tools
    assert all(t.invoked_by == "model function call" for t in res.tool_trace)
    assert res.reconciliation_outcome == "Matched" and res.ledger_entry.ledger_entry_id == "DEV-1007"
    tm = [f for f in res.findings if f.code == "TOTAL_MISMATCH"]
    assert tm and tm[0].details["expected"] == "880.00" and not res.can_approve
