"""TaxFlow — invoice intake review with source evidence. Run: python -m streamlit run app.py"""
from __future__ import annotations

import html
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import streamlit as st

from taxflow import exports
from taxflow.models import RunResult
from taxflow.parsing import InputError, ParsedDocument, decode_upload
from taxflow.pipeline import RECORDED_DIR, load_recorded, run_illustrative, run_live
from taxflow.providers import ProviderError, build_provider, live_mode_enabled, missing_settings, read_settings
from taxflow.samples import SAMPLES, load_sample

st.set_page_config(page_title="TaxFlow · Invoice intake", page_icon="🧾", layout="wide")

MODE_ILLUSTRATIVE = "Illustrative demo"
MODE_RECORDED = "Recorded live run"
MODE_LIVE = "Live agent"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

CSS = """
<style>
.tf-badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:0.8rem;font-weight:600;
  border:1px solid currentColor;margin-right:6px}
.tf-ok{color:#0F7C7A}.tf-bad{color:#B42318}.tf-warn{color:#8A5A00}.tf-muted{color:#5B6B82}
.tf-src{font-family:ui-monospace,Menlo,monospace;font-size:0.82rem;background:#FFFFFF;border:1px solid #D5DEE8;
  border-radius:8px;padding:8px 0;max-height:620px;overflow:auto;white-space:pre}
.tf-line{display:block;padding:0 10px}
.tf-line .n{display:inline-block;width:3.2em;color:#8796AA;user-select:none}
.tf-hl{background:#D7F0EE;border-left:3px solid #0F7C7A}
.tf-page{display:block;padding:4px 10px;color:#5B6B82;font-weight:600;border-top:1px dashed #D5DEE8;margin-top:4px}
</style>
"""


@st.cache_resource
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="taxflow-run")


def _settings() -> dict:
    try:
        secrets = st.secrets
    except Exception:
        secrets = None
    return read_settings(secrets)


def _recorded_ids() -> list[str]:
    return sorted(p.stem for p in RECORDED_DIR.glob("*.json") if p.stem in SAMPLES)


def _reset_result() -> None:
    for k in ("result", "selected_ref", "future", "progress", "run_error"):
        st.session_state.pop(k, None)


def _clear_session() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def _badge(text: str, kind: str) -> str:
    return f'<span class="tf-badge tf-{kind}">{html.escape(text)}</span>'


# ---------------- Source viewer ----------------

def render_source(doc: ParsedDocument, ref: tuple[int, int, int] | None) -> None:
    parts = []
    for p, lines in enumerate(doc.pages, start=1):
        parts.append(f'<span class="tf-page">Page {p}</span>')
        for i, text in enumerate(lines, start=1):
            hl = ref is not None and ref[0] == p and ref[1] <= i <= ref[2]
            cls = "tf-line tf-hl" if hl else "tf-line"
            parts.append(f'<span class="{cls}"><span class="n">{i:>3}</span>{html.escape(text) or " "}</span>')
    st.markdown(f'<div class="tf-src">{"".join(parts)}</div>', unsafe_allow_html=True)
    if ref:
        st.caption(f"Highlighted: page {ref[0]}, lines {ref[1]}–{ref[2]}")


# ---------------- Result panels ----------------

def _ev_label(ev) -> str:
    if ev.value is None:
        return _badge("Not found", "warn")
    if ev.evidence is None:
        return _badge("No source", "bad")
    if ev.evidence.status == "verified":
        return _badge("Source verified", "ok")
    return _badge("Source unsupported", "bad")


def _source_button(ev, key: str) -> None:
    e = ev.evidence
    if e is None or ev.value is None:
        st.write("")
        return
    if st.button(f"p{e.page_number} L{e.line_start}" + (f"–{e.line_end}" if e.line_end != e.line_start else ""),
                 key=key, help="Show this source in the viewer"):
        st.session_state.selected_ref = (e.page_number, e.line_start, e.line_end)
        st.rerun()


FIELD_LABELS = {
    "vendor_name": "Vendor", "invoice_number": "Invoice number", "invoice_date": "Invoice date",
    "currency": "Currency", "subtotal": "Subtotal", "tax": "Tax (stated)", "total": "Total",
}


def render_record(res: RunResult) -> None:
    draft = res.extracted_fields
    if res.document_type == "unsupported":
        st.markdown(_badge("Unsupported document", "bad"), unsafe_allow_html=True)
        st.write(f"Routed to follow-up: {res.unsupported_reason}. No invoice fields were extracted.")
        return
    if draft is None:
        st.info("No extracted record (the run did not reach extraction).")
        return
    for name, label in FIELD_LABELS.items():
        ev = draft.scalar(name)
        c1, c2, c3, c4 = st.columns([1.3, 1.6, 1.3, 0.9])
        c1.markdown(f"**{label}**")
        c2.write(ev.value if ev.value is not None else "— (null)")
        c3.markdown(_ev_label(ev), unsafe_allow_html=True)
        with c4:
            _source_button(ev, f"src-{name}")
    st.markdown("**Line items**")
    if not draft.line_items:
        st.write("— (null)")
    for i, item in enumerate(draft.line_items or []):
        c1, c2, c3, c4 = st.columns([2.2, 1.6, 1.3, 0.9])
        c1.write(item.description.value or "— (no description)")
        c2.write(f"{item.quantity.value or '—'} × {item.unit_price.value or '—'} = {item.line_total.value or '—'}")
        evs = [item.description, item.quantity, item.unit_price, item.line_total]
        statuses = {("verified" if (e.evidence and e.evidence.status == "verified") else
                     "missing" if e.value is None else "bad") for e in evs}
        if statuses == {"verified"}:
            c3.markdown(_badge("Source verified", "ok"), unsafe_allow_html=True)
        elif "bad" in statuses:
            c3.markdown(_badge("Source unsupported", "bad"), unsafe_allow_html=True)
        else:
            c3.markdown(_badge("Incomplete", "warn"), unsafe_allow_html=True)
        with c4:
            target = next((e for e in (item.line_total, item.description) if e.evidence), item.line_total)
            _source_button(target, f"src-item-{i}")


def render_findings(res: RunResult) -> None:
    if not res.findings:
        st.markdown(_badge("No blocking findings", "ok"), unsafe_allow_html=True)
        return
    for f in res.findings:
        label = "BLOCKING" if f.blocking else "INFO"
        st.markdown(f'{_badge(label, "bad" if f.blocking else "muted")} <code>{html.escape(f.code)}</code> '
                    f'{html.escape(f.message)}', unsafe_allow_html=True)


def render_checks(res: RunResult) -> None:
    if not res.check_results:
        st.caption("No checks were run for this result.")
        return
    rows = []
    for c in res.check_results:
        status = {"pass": "PASS", "fail": "FAIL", "not_checked": "NOT CHECKED"}[c.status]
        detail = c.reason or ", ".join(f"{k}: {v}" for k, v in c.details.items() if v not in ([], None, ""))
        rows.append({"Check": c.name, "Result": status, "Detail": detail})
    st.dataframe(rows, hide_index=True, width="stretch")


def render_trace(res: RunResult) -> None:
    meta = res.run_metadata
    if meta.mode == "illustrative":
        st.caption("Illustrative mode: these Python tools were executed directly by the app. No model chose them.")
    elif meta.mode == "recorded_live":
        st.caption("Recorded live run: these tool calls were chosen by the model during the original run.")
    else:
        st.caption("Live run: these tool calls were chosen by the model through function calling and executed in Python.")
    if not res.tool_trace:
        st.write("No tools were executed.")
        return
    st.dataframe([{"#": t.step, "Tool": t.tool, "Arguments": json.dumps(t.arguments), "Status": t.status,
                   "Result": t.result_summary, "ms": t.duration_ms, "Invoked by": t.invoked_by}
                  for t in res.tool_trace], hide_index=True, width="stretch")


def render_review(res: RunResult) -> None:
    st.markdown("#### Review decision")
    st.write(f"Processing: **{res.workflow_status}** · Review: **{res.review_status}**")
    note = st.text_area("Review note (optional)", value=res.review_note, key=f"note-{res.run_id}", max_chars=2000)
    res.review_note = note
    c1, c2, _ = st.columns([1, 1, 2])
    can = res.can_approve
    if c1.button("Approve intake", disabled=not can, type="primary", key=f"approve-{res.run_id}"):
        res.review_status = "Approved intake"
        st.rerun()
    if c2.button("Needs follow-up", key=f"followup-{res.run_id}"):
        res.review_status = "Needs follow-up"
        st.rerun()
    if not can:
        why = ("processing is not Complete" if res.workflow_status != "Complete"
               else f"{len(res.blocking_findings)} blocking finding(s)")
        st.caption(f"Approval is disabled: {why}.")

    st.markdown("#### Export")
    label = exports.export_label(res)
    st.caption(f"Exports are labeled: {label}")
    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Download JSON", exports.to_json(res), file_name=f"taxflow-{res.document_id}-{res.run_id}.json",
                       mime="application/json")
    d2.download_button("Download CSV", exports.to_csv(res), file_name=f"taxflow-{res.document_id}-{res.run_id}.csv",
                       mime="text/csv")


def render_mode_banner(res: RunResult | None, mode: str) -> None:
    if mode == MODE_ILLUSTRATIVE:
        st.warning("**Illustrative demo.** Extraction is a hand-prepared draft, clearly not model output. "
                   "The completeness, evidence, and arithmetic checks are real Python checks. No model is called.")
    elif mode == MODE_RECORDED:
        if res is not None and res.run_metadata.recorded_from:
            r = res.run_metadata.recorded_from
            st.info(f"**Recorded live run.** Replay of an actual run on {r['provider']} · deployment `{r['model']}` · "
                    f"{r['timestamp']}. No inference happens now. Your review choices apply to this replay only.")
        else:
            st.info("**Recorded live run.** Replays a saved actual run. No inference happens now.")
    else:
        st.success("**Live agent.** Actual model inference and Python tool calls on the current input.")


# ---------------- Running ----------------

def _start_run(mode: str, doc: ParsedDocument, sample_id: str | None, settings: dict) -> None:
    progress: list[str] = []
    lock = threading.Lock()

    def on_status(msg: str) -> None:
        with lock:
            progress.append(msg)

    if mode == MODE_LIVE:
        provider = build_provider(settings)  # raises ProviderError on config problems

        def job():
            return run_live(doc, provider, on_status)
    else:
        def job():
            return run_illustrative(doc, sample_id, on_status)

    st.session_state.progress = progress
    st.session_state.future = _executor().submit(job)


def _poll_run() -> None:
    fut: Future | None = st.session_state.get("future")
    if fut is None:
        return
    progress = st.session_state.get("progress", [])
    if not fut.done():
        with st.status(progress[-1] if progress else "Starting…", expanded=True):
            for p in progress:
                st.write(p)
        time.sleep(0.4)
        st.rerun()
    st.session_state.future = None
    try:
        st.session_state.result = fut.result()
    except Exception as exc:  # unexpected error: surface it, never fabricate success
        st.session_state.run_error = f"{type(exc).__name__}: {exc}"


# ---------------- Page ----------------

def page_review(settings: dict) -> None:
    live_on = live_mode_enabled(settings)
    modes = [MODE_ILLUSTRATIVE]
    if _recorded_ids():
        modes.insert(0, MODE_RECORDED)
    if live_on:
        modes.append(MODE_LIVE)

    top1, top2 = st.columns([2, 1])
    with top1:
        mode = st.radio("Mode", modes, horizontal=True, key="mode", on_change=_reset_result)
    with top2:
        if st.button("Clear session", help="Remove the document, result, note, and decision"):
            _clear_session()
            st.rerun()

    if mode == MODE_LIVE:
        missing = missing_settings(settings)
        if missing:
            st.error("Live mode is enabled but these settings are missing: " + ", ".join(missing)
                     + ". Add them to .streamlit/secrets.toml or environment variables.")

    # ----- Input -----
    sample_ids = _recorded_ids() if mode == MODE_RECORDED else list(SAMPLES)
    source = "Bundled sample"
    if mode == MODE_LIVE:
        source = st.radio("Input", ["Bundled sample", "Upload synthetic TXT"], horizontal=True,
                          key="input_kind", on_change=_reset_result)
    doc, sample_id = None, None
    if source == "Bundled sample":
        sample_id = st.selectbox("Synthetic sample", sample_ids, format_func=lambda s: SAMPLES[s],
                                 key=f"sample-{mode}", on_change=_reset_result)
        doc = load_sample(sample_id)
    else:
        up = st.file_uploader("Synthetic invoice (.txt, UTF-8, max 2 MB / 20,000 characters)", type=["txt"],
                              key="upload", on_change=_reset_result)
        st.caption("Use fictional documents only. Uploads stay in this session's memory and are not stored.")
        if up is not None:
            try:
                doc = decode_upload(up.getvalue(), up.name)
            except InputError as exc:
                st.error(f"Upload rejected: {exc}")

    if doc is not None and st.session_state.get("doc_id") != doc.document_id:
        _reset_result()
        st.session_state.doc_id = doc.document_id

    running = st.session_state.get("future") is not None
    b1, b2 = st.columns([1, 3])
    analyze = b1.button("Analyze invoice", type="primary", disabled=doc is None or running)
    if st.session_state.get("result") is not None or st.session_state.get("run_error"):
        if b2.button("Reset result"):
            _reset_result()
            st.rerun()

    if analyze and doc is not None:
        _reset_result()  # a new run always resets the prior decision
        if mode == MODE_RECORDED:
            st.session_state.result = load_recorded(sample_id)
        else:
            try:
                _start_run(mode, doc, sample_id, settings)
            except ProviderError as exc:
                st.session_state.run_error = f"{exc.kind}: {exc}"
        st.rerun()

    _poll_run()
    res: RunResult | None = st.session_state.get("result")
    render_mode_banner(res, mode)

    if err := st.session_state.get("run_error"):
        st.error(f"Run failed: {err}")
        if st.button("Retry"):
            _reset_result()
            st.rerun()

    if doc is None:
        st.info("Choose a sample or upload a synthetic TXT invoice to begin.")
        return

    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown(f"#### Source · `{doc.name}`")
        st.caption("Read-only. Line numbers are what evidence references cite.")
        render_source(doc, st.session_state.get("selected_ref"))
    with right:
        if res is None:
            st.markdown("#### Extracted record")
            st.write("Select **Analyze invoice** to read, extract, check, and prepare the report.")
            return
        st.markdown("#### Extracted record")
        if res.workflow_status in ("Failed", "Incomplete"):
            st.error(f"Processing {res.workflow_status}: {res.run_metadata.error or 'see findings'}. "
                     "No result is presented as a success. Use Retry or Reset.")
        render_record(res)
        st.markdown("#### Findings")
        render_findings(res)
        with st.expander("Check results (pass / fail / not checked)"):
            render_checks(res)

    if res is None:
        return
    st.divider()
    f1, f2 = st.columns([1, 1.15], gap="large")
    with f1:
        st.markdown("#### Recommended follow-up")
        for item in res.checklist:
            target = f" · `{item.field}`" if item.field else ""
            st.markdown(f"- **{item.policy_ref}** · `{item.finding_code}`{target}: {item.action}")
        if res.model_summary:
            st.markdown("**Model summary** (only sentences citing verified findings or policy refs are shown)")
            for s in res.model_summary:
                st.markdown(f"> {s}")
        if res.excluded_summary_sentences:
            st.caption(f"{res.excluded_summary_sentences} model sentence(s) excluded: no supported finding or policy reference.")
    with f2:
        st.markdown("#### Activity log")
        render_trace(res)
        m = res.run_metadata
        st.caption(f"Run `{res.run_id}` · mode {m.mode} · provider {m.provider or 'none'} · model {m.model or 'none'} · "
                   f"model requests {m.model_requests}"
                   + (f"/{m.request_budget}" if m.request_budget else "")
                   + (f" · tokens {m.token_usage.get('total_tokens')}" if m.token_usage else "")
                   + (f" · {m.duration_ms} ms" if m.duration_ms is not None else ""))
    st.divider()
    render_review(res)


def page_evaluation() -> None:
    st.markdown("### Evaluation")
    st.caption("This view only reads saved reports. It never launches a paid evaluation. "
               "Run `python -m evaluation.run --mode live` locally to create a report.")
    reports = sorted(REPORTS_DIR.glob("eval-*.md"), reverse=True)
    if not reports:
        st.info("No evaluation report has been saved yet, so no results are shown.")
        return
    choice = st.selectbox("Saved report", reports, format_func=lambda p: p.name)
    st.markdown(choice.read_text(encoding="utf-8"))


def page_about() -> None:
    st.markdown("""
### About TaxFlow
TaxFlow is a portfolio prototype that assists the **first review of an incoming invoice**: it reads the
document, organizes key fields with source references, checks completeness and arithmetic with Python
`Decimal`, and prepares a review packet. **A person makes the review decision.**

- All documents are **synthetic and fictional**. No real clients or business impact are claimed.
- TaxFlow does **not** file taxes, calculate tax liability, pay invoices, certify compliance, or send messages.
  The stated tax amount is treated as an input; its legal correctness is not assessed.
- Version 1 supports English, explicit-USD invoices of 1–5 pages without discounts, credits, shipping,
  or multiple tax components. Other inputs route to follow-up.
- Independent project; no affiliation with any firm is implied.

**Modes.** *Illustrative demo*: hand-prepared extraction, real Python checks, no model. *Recorded live run*:
replay of an actual saved live run with provenance. *Live agent* (local/private only): actual Azure OpenAI
inference and model-chosen Python tool calls.
""")


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    settings = _settings()
    st.title("TaxFlow")
    st.markdown("**Review invoice intake with source evidence.** Pick a synthetic invoice, analyze it, inspect where "
                "every value came from, and decide whether it is ready for intake or needs follow-up.")
    tab_review, tab_eval, tab_about = st.tabs(["Review", "Evaluation", "About"])
    with tab_review:
        page_review(settings)
    with tab_eval:
        page_evaluation()
    with tab_about:
        page_about()


main()
