"""Scripted fake provider for offline tests. A mocked provider does not establish agent accuracy."""
from __future__ import annotations

import json

from taxflow.providers import ModelReply, ProviderError, ToolCall


def extraction_from_illustrative(sample_draft: dict | None, document_type="invoice", reason=None) -> str:
    def strip(v):
        if v["evidence"]:
            v = {"value": v["value"], "evidence": {k: v["evidence"][k] for k in ("page_number", "line_start", "line_end", "quote")}}
        return v
    if sample_draft is None:
        return json.dumps({"document_type": document_type, "unsupported_reason": reason, "unsupported_structures": [],
                           "fields": {k: {"value": None, "evidence": None} for k in
                                      ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")},
                           "line_items": None})
    fields = {k: strip(sample_draft[k]) for k in ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")}
    items = [{k: strip(i[k]) for k in ("description", "quantity", "unit_price", "line_total")} for i in sample_draft["line_items"]]
    return json.dumps({"document_type": "invoice", "unsupported_reason": None, "unsupported_structures": [],
                       "fields": fields, "line_items": items})


class ScriptedProvider:
    """Extraction returns ``extraction_json``; tool rounds follow a well-behaved agent unless overridden."""

    name = "fake (offline test)"
    model = "fake-model"

    def __init__(self, extraction_json: str, document_id: str, *, tool_script=None, fail_kinds=None, summary=None):
        self.extraction_json = extraction_json
        self.document_id = document_id
        self.tool_script = tool_script  # list of lists of (name, args) or "text"
        self.fail_kinds = list(fail_kinds or [])
        self.summary = summary
        self.calls = 0
        self.tool_round = 0

    def complete(self, messages, *, tools=None, response_format=None):
        self.calls += 1
        if self.fail_kinds:
            kind = self.fail_kinds.pop(0)
            if kind:
                raise ProviderError(kind, f"simulated {kind}")
        if response_format is not None:
            return ModelReply(content=self.extraction_json, finish_reason="stop",
                              raw_message={"role": "assistant", "content": self.extraction_json},
                              usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        script = self.tool_script or self._default_script(messages)
        step = script[min(self.tool_round, len(script) - 1)]
        self.tool_round += 1
        if step == "text":
            text = self.summary or "The checks found the listed issues; see TF-POL-000."
            return ModelReply(content=text, finish_reason="stop", raw_message={"role": "assistant", "content": text})
        calls = [ToolCall(f"call_{self.calls}_{i}", n, json.dumps(a)) for i, (n, a) in enumerate(step)]
        raw = {"role": "assistant", "content": None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls]}
        return ModelReply(content=None, tool_calls=calls, finish_reason="tool_calls", raw_message=raw)

    def _default_script(self, messages):
        codes = []
        for m in messages:
            if m.get("role") == "tool":
                codes += json.loads(m["content"]).get("finding_codes", [])
        d = {"document_id": self.document_id}
        return [
            [("validate_intake", d), ("reconcile_invoice", d)],
            [("lookup_intake_policy", {"finding_codes": sorted(set(codes))})],
            "text",
        ]
