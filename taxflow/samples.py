"""Six synthetic development samples (not evaluation cases)."""
from __future__ import annotations

from pathlib import Path

from .parsing import ParsedDocument, parse_text

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

SAMPLES = {
    "clean_invoice": "Clean invoice",
    "missing_invoice_number": "Missing invoice number",
    "wrong_total": "Wrong total (800 + 80 vs 950)",
    "wrong_line_item_total": "Wrong line-item total (2 pages)",
    "embedded_instruction": "Instruction embedded in invoice text",
    "unsupported_document": "Unsupported document (purchase order)",
}


def load_sample(sample_id: str) -> ParsedDocument:
    if sample_id not in SAMPLES:
        raise KeyError(sample_id)
    text = (SAMPLES_DIR / f"{sample_id}.txt").read_text(encoding="utf-8")
    return parse_text(text, document_id=f"sample-{sample_id}", name=f"{sample_id}.txt")
