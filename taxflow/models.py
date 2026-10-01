"""Typed records for TaxFlow invoice intake.

Values are kept as strings (decimal strings, ISO dates) exactly as normalized at
extraction time. Arithmetic always re-parses them with ``decimal.Decimal``.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "reconciliation-v2"

SCALAR_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax",
    "total",
)
ITEM_FIELDS = ("description", "quantity", "unit_price", "line_total")
MONEY_FIELDS = ("subtotal", "tax", "total")

WorkflowStatus = Literal["Ready", "Running", "Complete", "Failed", "Incomplete"]
ReviewStatus = Literal["Unreviewed", "Approved", "Needs follow-up"]
ReconciliationOutcome = Literal[
    "Matched", "Discrepancy found", "No matching entry", "Ambiguous match",
    "Needs clarification", "Unsupported document", "Incomplete",
]
ArithmeticStatus = Literal["Consistent", "Inconsistent", "Not checked", "Partially checked"]
ComparisonStatus = Literal["agree", "differ", "not_checked"]
EvidenceStatus = Literal["verified", "unsupported", "absent"]
CheckStatus = Literal["pass", "fail", "not_checked"]


class Evidence(BaseModel):
    document_id: str
    page_number: int
    line_start: int
    line_end: int
    quote: str
    status: EvidenceStatus = "absent"
    note: str | None = None


class ExtractedValue(BaseModel):
    value: str | None = None
    evidence: Evidence | None = None


class LineItem(BaseModel):
    description: ExtractedValue = Field(default_factory=ExtractedValue)
    quantity: ExtractedValue = Field(default_factory=ExtractedValue)
    unit_price: ExtractedValue = Field(default_factory=ExtractedValue)
    line_total: ExtractedValue = Field(default_factory=ExtractedValue)


class InvoiceDraft(BaseModel):
    vendor_name: ExtractedValue = Field(default_factory=ExtractedValue)
    invoice_number: ExtractedValue = Field(default_factory=ExtractedValue)
    invoice_date: ExtractedValue = Field(default_factory=ExtractedValue)
    currency: ExtractedValue = Field(default_factory=ExtractedValue)
    line_items: list[LineItem] | None = None
    subtotal: ExtractedValue = Field(default_factory=ExtractedValue)
    tax: ExtractedValue = Field(default_factory=ExtractedValue)
    total: ExtractedValue = Field(default_factory=ExtractedValue)
    # Adjustment structures the v1 calculator does not support (discount, shipping, ...).
    unsupported_structures: list[str] = Field(default_factory=list)

    def scalar(self, name: str) -> ExtractedValue:
        return getattr(self, name)

    def iter_values(self):
        """Yield (path, ExtractedValue) for every scalar and item field."""
        for name in SCALAR_FIELDS:
            yield name, self.scalar(name)
        for i, item in enumerate(self.line_items or []):
            for name in ITEM_FIELDS:
                yield f"line_items[{i}].{name}", getattr(item, name)


class LedgerEntry(BaseModel):
    ledger_entry_id: str
    row_number: int  # spreadsheet row: header is row 1, first entry is row 2
    invoice_number: str
    vendor_name: str
    invoice_date: str
    currency: str
    gross_amount: str


class ComparisonRow(BaseModel):
    field: str
    invoice_value: str | None
    ledger_value: str | None
    status: ComparisonStatus
    note: str | None = None
    difference: str | None = None


class Finding(BaseModel):
    code: str
    field: str | None = None
    message: str
    blocking: bool = True
    source: str
    details: dict[str, Any] = Field(default_factory=dict)


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ChecklistItem(BaseModel):
    finding_code: str
    field: str | None = None
    policy_ref: str
    action: str


class ToolTraceEntry(BaseModel):
    step: int
    tool: str
    arguments: dict[str, Any]
    status: Literal["success", "error", "rejected"]
    result_summary: str
    duration_ms: int
    invoked_by: str  # "model function call" or "direct Python call (illustrative)"


class RunMetadata(BaseModel):
    mode: Literal["illustrative", "recorded_live", "live"]
    provider: str | None = None
    model: str | None = None
    schema_version: str = SCHEMA_VERSION
    prompt_version: str | None = None
    policy_version: str | None = None
    dataset_version: str | None = None
    timestamp: str
    duration_ms: int | None = None
    model_requests: int = 0
    request_budget: int | None = None
    token_usage: dict[str, int] | None = None
    recorded_from: dict[str, Any] | None = None
    ledger_id: str | None = None
    ledger_name: str | None = None
    currency_data: str | None = None
    error: str | None = None


class RunResult(BaseModel):
    """workflow_status = processing; reconciliation_outcome = ledger comparison;
    arithmetic_status = invoice's own arithmetic; review_status = human decision."""

    run_id: str
    document_id: str
    document_type: Literal["invoice", "unsupported"] | None = None
    unsupported_reason: str | None = None
    extracted_fields: InvoiceDraft | None = None
    findings: list[Finding] = Field(default_factory=list)
    check_results: list[CheckResult] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    workflow_status: WorkflowStatus = "Ready"
    review_status: ReviewStatus = "Unreviewed"
    review_note: str = ""
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    model_summary: list[str] = Field(default_factory=list)
    excluded_summary_sentences: int = 0
    run_metadata: RunMetadata
    # Ledger reconciliation (kept separate from invoice arithmetic and from the human decision)
    reconciliation_outcome: ReconciliationOutcome | None = None
    ledger_candidates: list[LedgerEntry] = Field(default_factory=list)
    ledger_entry: LedgerEntry | None = None
    comparison: list[ComparisonRow] = Field(default_factory=list)
    arithmetic_status: ArithmeticStatus | None = None
    required_tools: list[str] = Field(default_factory=list)

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    @property
    def can_approve(self) -> bool:
        return self.workflow_status == "Complete" and not self.blocking_findings
