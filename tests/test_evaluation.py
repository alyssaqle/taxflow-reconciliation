"""Offline checks of the v2 benchmark: split, separation, label consistency, scoring mechanics.

The fake provider here only exercises the runner and scoring code. It is NOT a live evaluation.
"""
import json
from collections import Counter
from pathlib import Path

from evaluation.run import CASES, LABELS, load_ledger, run_benchmark
from evaluation.scoring import top_field
from taxflow import checks, matching
from taxflow.models import ExtractedValue, InvoiceDraft, LineItem

ROOT = Path(__file__).resolve().parent.parent


def _labels():
    return [json.loads(p.read_text()) for p in sorted(LABELS.glob("case_*.json"))]


def test_split_counts_and_neutral_names():
    labels = _labels()
    assert len(labels) == 29 and len(list(CASES.glob("case_*.txt"))) == 29
    assert Counter(g["category"] for g in labels) == {
        "match": 5, "amount": 4, "no_entry": 3, "duplicate": 3, "currency": 3, "missing": 3,
        "arithmetic": 3, "date": 2, "attack": 2, "unsupported": 1}
    missing = {next(f for c, f in g["expected_findings"] if c == "MISSING_FIELD")
               for g in labels if g["category"] == "missing"}
    assert missing == {"invoice_number", "invoice_date", "total"}
    for p in CASES.glob("*.txt"):
        text = p.read_text().lower()
        assert "expected" not in text and "category" not in text and "ground truth" not in text


def test_heldout_separate_from_development_samples():
    from taxflow.samples import load_sample_ledger
    dev_vendors = {e.vendor_name.casefold() for e in load_sample_ledger().entries}
    held_vendors = {e.vendor_name.casefold() for e in load_ledger().entries}
    assert not dev_vendors & held_vendors


def test_ground_truth_not_reachable_from_agent_code():
    for f in (ROOT / "taxflow").glob("*.py"):
        src = f.read_text()
        assert "ground_truth" not in src and "from evaluation" not in src and "import evaluation" not in src, f.name


def test_labels_consistent_with_python_rules():
    """Drafts built from labeled values must reproduce the labeled outcome, entry, candidates, and findings."""
    ledger = load_ledger()
    for g in _labels():
        if g["document_type"] != "invoice":
            continue
        V = lambda v: ExtractedValue(value=v)
        d = InvoiceDraft(**{k: V(v) for k, v in g["expected_fields"].items()},
                         line_items=[LineItem(**{k: V(v) for k, v in it.items()}) for it in g["expected_line_items"]])
        rf, rc = checks.reconcile(d)
        found = checks.required_field_findings(d) + rf
        cands = [] if matching.identifiers_missing(d) else matching.find_candidates(ledger.entries, d)
        found += matching.search_findings(d, cands)
        rows = []
        if len(cands) == 1:
            rows, cf = matching.compare(d, cands[0])
            found += cf
        cid = g["case_id"]
        assert matching.outcome(d, cands, rows) == g["expected_outcome"], cid
        assert sorted(c.ledger_entry_id for c in cands) == g["expected_candidate_ids"], cid
        assert (cands[0].ledger_entry_id if len(cands) == 1 else None) == g["expected_entry_id"], cid
        assert sorted({(f.code, top_field(f.field)) for f in found}, key=str) == \
            sorted({tuple(x) for x in g["expected_findings"]}, key=str), cid
        assert checks.arithmetic_status(rc) == g["expected_arithmetic_status"], cid


class _BrokenProvider:
    name, model = "fake (offline test)", "none"

    def complete(self, *a, **k):
        from taxflow.providers import ProviderError
        raise ProviderError("auth", "simulated")


def test_failures_stay_in_denominator(tmp_path):
    path = run_benchmark(_BrokenProvider(), split="test", mode="fake", secret_values=[], out_dir=tmp_path,
                         log=lambda *_: None)
    m = json.loads(path.read_text())["metrics"]
    assert m["routing"]["all"] == {"numerator": 0, "denominator": 29, "value": 0.0}
    assert m["matching"]["all"]["denominator"] == 28 and m["matching"]["all"]["numerator"] == 0
    assert m["workflow_completion"]["all"]["denominator"] == 29 and m["workflow_completion"]["all"]["numerator"] == 0
    assert m["execution_failures"]["numerator"] == 29 and m["attack_cases"]["denominator"] == 2
    assert m["exception_detection"]["precision"]["value"] is None  # 0/0 reported as undefined
    assert m["exception_detection"]["recall"]["denominator"] > 0
    assert path.with_suffix(".md").exists()
