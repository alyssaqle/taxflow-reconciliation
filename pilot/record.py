"""Record actual live TaxFlow results for the 20 pilot tasks (shown in the assisted condition).
Usage: python -m pilot.record"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from taxflow.ledger import parse_ledger_csv
from taxflow.parsing import parse_text
from taxflow.pipeline import run_live
from taxflow.providers import build_provider, read_settings

ROOT = Path(__file__).resolve().parent


def main() -> None:
    settings = read_settings(tomllib.loads((ROOT.parent / ".streamlit" / "secrets.toml").read_text()))
    provider = build_provider(settings)
    ledger = parse_ledger_csv((ROOT / "data" / "pilot_ledger.csv").read_text(), "pilot_ledger.csv")
    (ROOT / "recorded").mkdir(exist_ok=True)
    for t in json.loads((ROOT / "data" / "tasks.json").read_text()):
        tid = t["task_id"]
        doc = parse_text((ROOT / "data" / "invoices" / f"{tid}.txt").read_text(), document_id=f"pilot-{tid}", name=f"{tid}.txt")
        r = run_live(doc, ledger, provider)
        (ROOT / "recorded" / f"{tid}.json").write_text(r.model_dump_json(indent=1))
        print(tid, r.workflow_status, r.reconciliation_outcome, r.arithmetic_status)


if __name__ == "__main__":
    main()
