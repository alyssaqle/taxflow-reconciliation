"""Allowlisted Python tools the model may call.

Tools read the validated server-side draft held in a per-run ``ToolContext``.
They never accept amounts from the model, never read evaluation labels, and
resolve only the current session's document ID.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import checks, policy
from .models import CheckResult, Finding, InvoiceDraft, ToolTraceEntry
from .parsing import ParsedDocument

REQUIRED_TOOLS = ("validate_intake", "reconcile_invoice", "lookup_intake_policy")


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    doc: ParsedDocument
    draft: InvoiceDraft
    invoked_by: str
    validation: tuple[list[Finding], list[CheckResult]] | None = None
    reconciliation: tuple[list[Finding], list[CheckResult]] | None = None
    policy_refs: list[str] | None = None
    succeeded: set[str] = field(default_factory=set)
    trace: list[ToolTraceEntry] = field(default_factory=list)

    def _check_doc(self, document_id: Any) -> None:
        if document_id != self.doc.document_id:
            raise ToolError("document_id does not match the current session's document")


def _validate_intake(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    findings, results = checks.validate(ctx.draft)
    ctx.validation = (findings, results)
    return {
        "finding_codes": sorted({f.code for f in findings}),
        "findings": [{"code": f.code, "field": f.field, "message": f.message} for f in findings],
        "checks": [{"name": c.name, "status": c.status, "reason": c.reason} for c in results],
    }


def _reconcile_invoice(ctx: ToolContext, args: dict) -> dict:
    ctx._check_doc(args.get("document_id"))
    findings, results = checks.reconcile(ctx.draft)
    ctx.reconciliation = (findings, results)
    return {
        "finding_codes": sorted({f.code for f in findings}),
        "findings": [{"code": f.code, "field": f.field, "message": f.message, **f.details} for f in findings],
        "checks": [{"name": c.name, "status": c.status, "reason": c.reason, **c.details} for c in results],
    }


def _lookup_intake_policy(ctx: ToolContext, args: dict) -> dict:
    codes = args.get("finding_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes) or len(codes) > 20:
        raise ToolError("finding_codes must be a list of at most 20 strings")
    unknown = sorted(set(codes) - policy.known_codes() - {"NO_FINDINGS"})
    rules = policy.lookup(codes)
    ctx.policy_refs = [r.ref for r in rules]
    return {
        "policy_version": policy.load_policy()[0],
        "rules": [{"ref": r.ref, "title": r.title, "applies_to": r.applies_to, "follow_up": r.follow_up} for r in rules],
        "unknown_codes_ignored": unknown,
    }


TOOLS: dict[str, Callable[[ToolContext, dict], dict]] = {
    "validate_intake": _validate_intake,
    "reconcile_invoice": _reconcile_invoice,
    "lookup_intake_policy": _lookup_intake_policy,
}

_DOC_PARAM = {
    "type": "object",
    "properties": {"document_id": {"type": "string", "description": "ID of the current document."}},
    "required": ["document_id"],
    "additionalProperties": False,
}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "validate_intake",
        "description": "Check the stored invoice draft for required fields, supported structure, "
                       "source-evidence status, date format, currency, and numeric validity.",
        "parameters": _DOC_PARAM, "strict": True}},
    {"type": "function", "function": {
        "name": "reconcile_invoice",
        "description": "Recalculate item totals, subtotal, and total from the stored draft with Decimal "
                       "arithmetic and return comparisons or explicit skipped-check reasons.",
        "parameters": _DOC_PARAM, "strict": True}},
    {"type": "function", "function": {
        "name": "lookup_intake_policy",
        "description": "Retrieve the fictional intake policy rules (with stable reference IDs) that apply "
                       "to the given finding codes. Pass an empty list for a clean invoice.",
        "parameters": {
            "type": "object",
            "properties": {"finding_codes": {"type": "array", "items": {"type": "string"}}},
            "required": ["finding_codes"],
            "additionalProperties": False,
        }, "strict": True}},
]


def _bounded(obj: Any, limit: int = 200) -> Any:
    text = json.dumps(obj, default=str)
    return obj if len(text) <= limit else {"truncated": text[:limit] + "…"}


def _summary(name: str, result: dict) -> str:
    if name == "lookup_intake_policy":
        return "Policy refs: " + ", ".join(r["ref"] for r in result["rules"])
    codes = result["finding_codes"]
    skipped = [c["name"] for c in result["checks"] if c["status"] == "not_checked"]
    s = f"Findings: {', '.join(codes) if codes else 'none'}"
    if skipped:
        s += f"; not checked: {', '.join(skipped)}"
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
