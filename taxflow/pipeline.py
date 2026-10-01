"""Run orchestration for the three modes: illustrative, recorded live, and live agent."""
from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from pathlib import Path
from typing import Callable

from . import checks, policy
from .agent import MAX_MODEL_REQUESTS, BudgetExhausted, PROMPT_VERSION, RequestBudget, extract, filter_summary, run_tool_loop
from .evidence import verify_draft
from .models import Finding, InvoiceDraft, RunMetadata, RunResult
from .parsing import ParsedDocument
from .providers import Provider, ProviderError
from .tools import REQUIRED_TOOLS, ToolContext, execute

StatusFn = Callable[[str], None]
ILLUSTRATIVE_BY = "direct Python call (illustrative mode, no model)"
MODEL_BY = "model function call"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _noop(_: str) -> None:
    pass


def _unsupported_result(doc, reason, meta) -> RunResult:
    finding = Finding(code="UNSUPPORTED_DOCUMENT", message=f"Not a supported invoice: {reason}",
                      source="pipeline")
    return RunResult(
        run_id=uuid.uuid4().hex[:12], document_id=doc.document_id, document_type="unsupported",
        unsupported_reason=reason, extracted_fields=None, findings=[finding],
        checklist=policy.build_checklist([finding]), workflow_status="Complete", run_metadata=meta,
    )


def _assemble(doc: ParsedDocument, ctx: ToolContext, meta: RunMetadata, complete: bool,
              incomplete_reason: str | None = None, model_text: str | None = None) -> RunResult:
    """Python findings are authoritative; checklist comes from finding codes + policy."""
    if ctx.validation is None or ctx.reconciliation is None:
        # Tools did not all run through the agent: still show Python checks, attributed honestly.
        v = ctx.validation or checks.validate(ctx.draft)
        r = ctx.reconciliation or checks.reconcile(ctx.draft)
    else:
        v, r = ctx.validation, ctx.reconciliation
    findings = list(v[0]) + list(r[0])
    check_results = list(v[1]) + list(r[1])
    if not complete:
        findings.append(Finding(code="INCOMPLETE_PROCESSING", source="pipeline",
                                message=f"Processing incomplete: {incomplete_reason}. Approval is blocked."))
    checklist = policy.build_checklist(findings)
    allowed = {f.code for f in findings} | {c.policy_ref for c in checklist}
    if not findings:
        allowed |= {"NO_FINDINGS"}
    kept, excluded = filter_summary(model_text, allowed)
    return RunResult(
        run_id=uuid.uuid4().hex[:12], document_id=doc.document_id, document_type="invoice",
        extracted_fields=ctx.draft, findings=findings, check_results=check_results, checklist=checklist,
        workflow_status="Complete" if complete else "Incomplete", tool_trace=ctx.trace,
        model_summary=kept, excluded_summary_sentences=excluded, run_metadata=meta,
    )


# ---------- Illustrative mode ----------

ILLUSTRATIVE_DIR = Path(__file__).resolve().parent.parent / "samples" / "illustrative"


def load_illustrative(sample_id: str, doc: ParsedDocument) -> dict:
    data = json.loads((ILLUSTRATIVE_DIR / f"{sample_id}.json").read_text(encoding="utf-8"))
    if data.get("draft"):
        draft = data["draft"]
        for _, ev in _walk_values(draft):
            if ev.get("evidence"):
                ev["evidence"]["document_id"] = doc.document_id
        data["draft"] = InvoiceDraft.model_validate(draft)
    return data


def _walk_values(d: dict):
    for k, v in d.items():
        if k == "line_items" and v:
            for item in v:
                yield from _walk_values(item)
        elif isinstance(v, dict) and "value" in v:
            yield k, v


def run_illustrative(doc: ParsedDocument, sample_id: str, on_status: StatusFn = _noop) -> RunResult:
    """Illustrative extraction (hand-prepared, labeled) + real Python checks. No model requests."""
    start = time.perf_counter()
    meta = RunMetadata(mode="illustrative", provider=None, model=None, timestamp=_now(),
                       policy_version=policy.load_policy()[0])
    on_status("Reading")
    data = load_illustrative(sample_id, doc)
    on_status("Extracting (illustrative: prepared draft, no model)")
    if data["document_type"] == "unsupported":
        res = _unsupported_result(doc, data["unsupported_reason"], meta)
    else:
        draft = verify_draft(data["draft"], doc)
        ctx = ToolContext(doc=doc, draft=draft, invoked_by=ILLUSTRATIVE_BY)
        on_status("Checking")
        _, _ = execute(ctx, "validate_intake", {"document_id": doc.document_id})
        _, _ = execute(ctx, "reconcile_invoice", {"document_id": doc.document_id})
        codes = sorted({f.code for f in ctx.validation[0] + ctx.reconciliation[0]})
        execute(ctx, "lookup_intake_policy", {"finding_codes": codes})
        on_status("Preparing report")
        res = _assemble(doc, ctx, meta, complete=True)
    res.run_metadata.duration_ms = int((time.perf_counter() - start) * 1000)
    return res


# ---------- Live agent ----------

def run_live(doc: ParsedDocument, provider: Provider, on_status: StatusFn = _noop,
             budget_limit: int = MAX_MODEL_REQUESTS) -> RunResult:
    """Actual inference and tool execution on the current input. Never substitutes a mock."""
    start = time.perf_counter()
    budget = RequestBudget(limit=budget_limit)
    meta = RunMetadata(mode="live", provider=provider.name, model=provider.model, timestamp=_now(),
                       prompt_version=PROMPT_VERSION, policy_version=policy.load_policy()[0],
                       request_budget=budget_limit)

    def finish(res: RunResult) -> RunResult:
        res.run_metadata.duration_ms = int((time.perf_counter() - start) * 1000)
        res.run_metadata.model_requests = budget.used
        res.run_metadata.token_usage = dict(budget.usage) or None
        return res

    on_status("Reading")
    try:
        on_status("Extracting with the model")
        ex = extract(provider, doc, budget)
    except ProviderError as exc:
        meta.error = f"{exc.kind}: {exc}"
        return finish(RunResult(run_id=uuid.uuid4().hex[:12], document_id=doc.document_id,
                                workflow_status="Failed", run_metadata=meta))
    except BudgetExhausted as exc:
        meta.error = str(exc)
        return finish(RunResult(run_id=uuid.uuid4().hex[:12], document_id=doc.document_id,
                                workflow_status="Incomplete", run_metadata=meta))

    if ex.document_type == "unsupported":
        on_status("Preparing report")
        return finish(_unsupported_result(doc, ex.unsupported_reason, meta))

    draft = verify_draft(ex.draft, doc)
    ctx = ToolContext(doc=doc, draft=draft, invoked_by=MODEL_BY)
    on_status("Checking (model is calling Python tools)")
    try:
        loop = run_tool_loop(provider, ctx, budget, on_tool=lambda name: on_status(f"Checking: model called {name}"))
    except ProviderError as exc:
        meta.error = f"{exc.kind}: {exc}"
        on_status("Preparing report")
        res = _assemble(doc, ctx, meta, complete=False, incomplete_reason=f"model request failed ({exc.kind})")
        res.workflow_status = "Failed"
        return finish(res)

    on_status("Preparing report")
    missing = [t for t in REQUIRED_TOOLS if t not in ctx.succeeded]
    if not loop.completed or missing:
        reason = loop.stop_reason or "required tools did not complete"
        if missing:
            reason += f" (missing successful calls: {', '.join(missing)})"
        meta.error = reason
        return finish(_assemble(doc, ctx, meta, complete=False, incomplete_reason=reason))
    return finish(_assemble(doc, ctx, meta, complete=True, model_text=loop.final_text))


# ---------- Recorded live runs ----------

RECORDED_DIR = Path(__file__).resolve().parent.parent / "samples" / "recorded"


def load_recorded(sample_id: str) -> RunResult | None:
    path = RECORDED_DIR / f"{sample_id}.json"
    if not path.exists():
        return None
    res = RunResult.model_validate_json(path.read_text(encoding="utf-8"))
    recorded = {"provider": res.run_metadata.provider, "model": res.run_metadata.model,
                "timestamp": res.run_metadata.timestamp, "original_run_id": res.run_id,
                "original_review_status": res.review_status}
    res.run_metadata.mode = "recorded_live"
    res.run_metadata.recorded_from = recorded
    # Current review choices operate on the replayed packet, separate from any recorded decision.
    res.review_status, res.review_note = "Unreviewed", ""
    res.run_id = uuid.uuid4().hex[:12]
    return res
