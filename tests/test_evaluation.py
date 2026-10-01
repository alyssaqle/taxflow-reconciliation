"""Offline checks of the benchmark: label consistency, separation, and scoring mechanics.

The fake provider here only exercises the runner and scoring code. It is NOT a live evaluation.
"""
import json
from pathlib import Path

from taxflow import checks
from taxflow.models import ExtractedValue, InvoiceDraft, LineItem
from evaluation.run import CASES, LABELS, run_benchmark
from evaluation.scoring import top_field
from tests.fakes import ScriptedProvider

ROOT = Path(__file__).resolve().parent.parent


def _labels():
    return [json.loads(p.read_text()) for p in sorted(LABELS.glob("case_*.json"))]


def test_split_counts_and_neutral_names():
    labels = _labels()
    assert len(labels) == 24 and len(list(CASES.glob("case_*.txt"))) == 24
    counts = {}
    for g in labels:
        counts[g["category"]] = counts.get(g["category"], 0) + 1
    assert counts == {"complete": 8, "missing": 6, "inconsistent": 4, "attack": 3, "unsupported": 3}
    for p in CASES.glob("*.txt"):  # case files carry no category hints
        text = p.read_text().lower()
        assert "expected" not in text and "category" not in text


def test_ground_truth_not_reachable_from_agent_code():
    for f in (ROOT / "taxflow").glob("*.py"):
        src = f.read_text()
        assert "ground_truth" not in src and "from evaluation" not in src and "import evaluation" not in src, f.name


def test_labels_consistent_with_python_checks():
    """Building a draft from labeled values must reproduce the labeled findings (evidence excluded)."""
    for g in _labels():
        if g["document_type"] != "invoice":
            continue
        V = lambda v: ExtractedValue(value=v)
        d = InvoiceDraft(**{k: V(v) for k, v in g["expected_fields"].items()},
                         line_items=[LineItem(**{k: V(v) for k, v in it.items()}) for it in g["expected_line_items"]])
        found = checks.required_field_findings(d) + checks.reconcile(d)[0]
        got = sorted({(f.code, top_field(f.field)) for f in found})
        assert got == sorted(tuple(x) for x in g["expected_findings"]), g["case_id"]


class _BrokenProvider:
    name, model = "fake (offline test)", "none"

    def complete(self, *a, **k):
        from taxflow.providers import ProviderError
        raise ProviderError("auth", "simulated")


def test_failures_stay_in_denominator(tmp_path):
    path = run_benchmark(_BrokenProvider(), split="test", mode="fake", secret_values=[], out_dir=tmp_path, log=lambda *_: None)
    rep = json.loads(path.read_text())
    m = rep["metrics"]
    assert m["routing"]["all"]["denominator"] == 24 and m["routing"]["all"]["numerator"] == 0
    assert m["field_extraction"]["denominator"] > 0 and m["field_extraction"]["numerator"] == 0
    assert m["workflow_completion"]["all"] == {"numerator": 0, "denominator": 24, "value": 0.0}
    assert m["attack_cases"]["denominator"] == 3 and m["attack_cases"]["numerator"] == 0
    assert len(m["latency_ms"]["failed_runs"]) == 24
    assert m["missing_field_detection"]["precision"]["value"] is None  # 0/0 reported as undefined
    assert (path.with_suffix(".md")).exists()
