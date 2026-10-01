"""Allowlisted Python tools the model may call.

Tools read the validated server-side invoice draft and the session's validated ledger held
in a per-run ``ToolContext``. They never accept amounts from the model, never read
evaluation labels, and resolve only the current session's document ID.

Required tools depend on the outcome: validate_intake, reconcile_invoice,
find_ledger_candidates, and build_review_checklist always; compare_to_ledger only when
exactly one candidate exists (no impossible comparison is demanded otherwise).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import checks, matching, policy
from .ledger import Ledger
from .models import CheckResult, ChecklistItem, ComparisonRow, Finding, InvoiceDraft, LedgerEntry, ToolTraceEntry
from .parsing import ParsedDocument

BASE_TOOLS = ("validate_intake", "reconcile_invoice", "find_ledger_candidates", "build_review_checklist")


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    doc: ParsedDocument
    draft: InvoiceDraft
    ledger: Ledger
    invoked_by: str
    validation: tuple[list[Finding], list[CheckResult]] | None = None
    reconciliation: tuple[list[Finding], list[CheckResult]] | None = None
    candidates: list[LedgerEntry] | None = None  # None until the ledger search has run
    search_findings: list[Finding] = field(default_factory=list)
    comparison: tuple[list[ComparisonRow], list[Finding]] | None = None
    checklist: list[ChecklistItem] | None = None
    outcome: str | None = None
    succeeded: set[str] = field(default_factory=set)
    trace: list[ToolTraceEntry] = field(default_factory=list)

    def _check_doc(self, document_id: Any) -> None:
        if document_id != self.doc.document_id:
            raise ToolError("document_id does not match the current session's document")

    @property
    def unique_candidate(self) -> LedgerEntry | None:
        return self.candidates[0] if self.candidates is not None and len(self.candidates) == 1 else None

    def required_tools(self) -> list[str]:
        req = list(BASE_TOOLS)
        if self.unique_candidate is not None:
            req.insert(3, "compare_to_ledger")
        return req

    def all_findings(self) -> list[Finding]:
        out: list[Finding] = []
        for part in (self.validation, self.reconciliation):
            if part:
                out += part[0]
        out += self.search_findings
        if self.comparison:
            out += self.comparison[1]
        return out


def _validate_intake(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    findings, results = checks.validate(ctx.draft)
    ctx.validation = (findings, results)
    return {
        "finding_codes": sorted({f.code for f in findings}),
        "findings": [{"code": f.code, "field": f.field, "blocking": f.blocking, "message": f.message} for f in findings],
        "checks": [{"name": c.name, "status": c.status, "reason": c.reason} for c in results],
    }


def _reconcile_invoice(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    findings, results = checks.reconcile(ctx.draft)
    ctx.reconciliation = (findings, results)
    return {
        "arithmetic_status": checks.arithmetic_status(results),
        "finding_codes": sorted({f.code for f in findings}),
        "findings": [{"code": f.code, "field": f.field, "blocking": f.blocking, "message": f.message, **f.details}
                     for f in findings],
        "checks": [{"name": c.name, "status": c.status, "reason": c.reason, **c.details} for c in results],
    }


def _entry_dict(e: LedgerEntry) -> dict:
    return e.model_dump()


def _find_ledger_candidates(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    missing = matching.identifiers_missing(ctx.draft)
    ctx.candidates = [] if missing else matching.find_candidates_indexed(ctx.ledger.index, ctx.draft)
    ctx.search_findings = matching.search_findings(ctx.draft, ctx.candidates)
    if missing:
        return {"searched": False, "reason": "invoice is missing " + " and ".join(missing), "candidates": [],
                "finding_codes": [f.code for f in ctx.search_findings]}
    return {
        "searched": True, "candidate_count": len(ctx.candidates),
        "candidates": [_entry_dict(e) for e in ctx.candidates],
        "next_step": ("call compare_to_ledger with this ledger_entry_id" if len(ctx.candidates) == 1
                      else "do not call compare_to_ledger; call build_review_checklist"),
        "finding_codes": [f.code for f in ctx.search_findings],
    }


def _compare_to_ledger(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    if ctx.candidates is None:
        raise ToolError("call find_ledger_candidates first")
    entry = ctx.unique_candidate
    if entry is None:
        raise ToolError(f"comparison requires exactly one candidate; found {len(ctx.candidates)}")
    if args.get("ledger_entry_id") != entry.ledger_entry_id:
        raise ToolError("ledger_entry_id is not the unique candidate returned by find_ledger_candidates")
    rows, findings = matching.compare(ctx.draft, entry)
    ctx.comparison = (rows, findings)
    return {
        "ledger_entry_id": entry.ledger_entry_id, "row_number": entry.row_number,
        "comparison": [r.model_dump() for r in rows],
        "finding_codes": sorted({f.code for f in findings}),
        "findings": [{"code": f.code, "message": f.message} for f in findings],
    }


def _build_review_checklist(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    pending = [n for n, done in (("validate_intake", ctx.validation), ("reconcile_invoice", ctx.reconciliation),
                                 ("find_ledger_candidates", ctx.candidates)) if done is None]
    if ctx.unique_candidate is not None and ctx.comparison is None:
        pending.append("compare_to_ledger")
    if pending:
        raise ToolError("run these tools first: " + ", ".join(pending))
    findings = ctx.all_findings()
    rows = ctx.comparison[0] if ctx.comparison else []
    ctx.outcome = matching.outcome(ctx.draft, ctx.candidates, rows)
    ctx.checklist = policy.build_checklist(findings)
    return {
        "reconciliation_outcome": ctx.outcome,
        "arithmetic_status": checks.arithmetic_status(ctx.reconciliation[1]),
        "blocking_codes": sorted({f.code for f in findings if f.blocking}),
        "non_blocking_codes": sorted({f.code for f in findings if not f.blocking}),
        "checklist": [{"ref": c.policy_ref, "code": c.finding_code, "field": c.field, "action": c.action}
                      for c in ctx.checklist],
        "policy_version": policy.load_policy()[0],
    }


TOOLS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "validate_intake": _validate_intake,
    "reconcile_invoice": _reconcile_invoice,
    "find_ledger_candidates": _find_ledger_candidates,
    "compare_to_ledger": _compare_to_ledger,
    "build_review_checklist": _build_review_checklist,
}

_DOC_PARAM = {
    "type": "object",
    "properties": {"document_id": {"type": "string", "description": "ID of the current document."}},
    "required": ["document_id"],
    "additionalProperties": False,
}


def _spec(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": parameters, "strict": True}}


TOOL_SPECS = [
    _spec("validate_intake", "Check the stored invoice draft for the five required reconciliation fields, "
          "source-evidence status, date format, ISO currency, and numeric validity.", _DOC_PARAM),
    _spec("reconcile_invoice", "Check the invoice's own arithmetic (item totals, subtotal, total) with Decimal. "
          "Reports Not checked where inputs are missing.", _DOC_PARAM),
    _spec("find_ledger_candidates", "Search the session's accounting ledger for entries with the same invoice "
          "number and vendor name (exact after whitespace/case normalization). Returns all candidates.", _DOC_PARAM),
    _spec("compare_to_ledger", "Compare the invoice with the single candidate ledger entry: currency first, then "
          "stated total vs gross amount, then date. Only valid when exactly one candidate was found.", {
              "type": "object",
              "properties": {"document_id": {"type": "string"}, "ledger_entry_id": {"type": "string"}},
              "required": ["document_id", "ledger_entry_id"], "additionalProperties": False}),
    _spec("build_review_checklist", "Assemble the reconciliation outcome and the policy-referenced follow-up "
          "checklist from the Python findings. Call after the other required tools.", _DOC_PARAM),
]


def _bounded(obj: Any, limit: int = 200) -> Any:
    text = json.dumps(obj, default=str)
    return obj if len(text) <= limit else {"truncated": text[:limit] + "…"}


def _summary(name: str, result: dict) -> str:
    if name == "build_review_checklist":
        return f"Outcome: {result['reconciliation_outcome']}; refs: " + ", ".join(c["ref"] for c in result["checklist"])
    if name == "find_ledger_candidates":
        if not result["searched"]:
            return f"Not searched: {result['reason']}"
        ids = [c["ledger_entry_id"] for c in result["candidates"]]
        return f"{len(ids)} candidate(s)" + (": " + ", ".join(ids) if ids else "")
    if name == "compare_to_ledger":
        parts = [f"{r['field']}={r['status']}" for r in result["comparison"] if r["field"] not in ("invoice_number", "vendor_name")]
        return f"{result['ledger_entry_id']}: " + ", ".join(parts)
    codes = result["finding_codes"]
    s = f"Findings: {', '.join(codes) if codes else 'none'}"
    if name == "reconcile_invoice":
        s = f"Arithmetic {result['arithmetic_status']}; " + s
    return s


def execute(ctx: ToolContext, name: str, raw_args: str | dict) -> tuple[str, ToolTraceEntry]:
    """Run one allowlisted tool. Returns (content for the model, trace entry)."""
    start = time.perf_counter()
    step = len(ctx.trace) + 1
    status, args = "success", {}
    try:
        if name not in TOOLS:
            status = "rejected"
            raise ToolError(f"tool '{name}' is not allowlisted")
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        result = TOOLS[name](ctx, args)
        content, summary = json.dumps(result), _summary(name, result)
        ctx.succeeded.add(name)
    except (ToolError, json.JSONDecodeError, TypeError, ValueError) as exc:
        status = "rejected" if status == "rejected" else "error"
        content = json.dumps({"error": str(exc)})
        summary = f"Error: {exc}"
    entry = ToolTraceEntry(
        step=step, tool=name, arguments=_bounded(args), status=status, result_summary=summary,
        duration_ms=int((time.perf_counter() - start) * 1000), invoked_by=ctx.invoked_by,
    )
    ctx.trace.append(entry)
    return content, entry
