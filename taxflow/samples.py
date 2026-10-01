"""Synthetic development samples and the sample ledger (not evaluation cases)."""
from __future__ import annotations

from pathlib import Path

from .ledger import Ledger, parse_ledger_csv
from .parsing import ParsedDocument, parse_text

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
LEDGER_DIR = SAMPLES_DIR / "ledger"
SAMPLE_LEDGER = LEDGER_DIR / "sample_ledger.csv"
TEMPLATE_LEDGER = LEDGER_DIR / "ledger_template.csv"

SAMPLES = {
    "matched_clean": "Matched: invoice agrees with ledger",
    "arithmetic_wrong_ledger_agrees": "Ledger agrees (950) but invoice arithmetic expects 880",
    "amount_difference": "Amount differs from ledger",
    "currency_difference": "Currency differs from ledger (EUR vs USD)",
    "date_difference": "Date differs from ledger (2 pages)",
    "duplicate_candidates": "Two ledger entries match (ambiguous)",
    "no_matching_entry": "No matching ledger entry",
    "missing_invoice_number": "Missing invoice number",
    "missing_currency": "Currency not stated ($ only)",
    "embedded_instruction": "Instruction embedded in invoice text",
    "unsupported_document": "Unsupported document (purchase order)",
}


def load_sample(sample_id: str) -> ParsedDocument:
    if sample_id not in SAMPLES:
        raise KeyError(sample_id)
    text = (SAMPLES_DIR / f"{sample_id}.txt").read_text(encoding="utf-8")
    return parse_text(text, document_id=f"sample-{sample_id}", name=f"{sample_id}.txt")


def load_sample_ledger() -> Ledger:
    return parse_ledger_csv(SAMPLE_LEDGER.read_text(encoding="utf-8"), SAMPLE_LEDGER.name)
