"""TaxFlow — invoice-to-ledger reconciliation with source evidence. Run: python -m streamlit run app.py"""
from __future__ import annotations

import html
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import streamlit as st

from taxflow import exports
from taxflow.ledger import TEMPLATE_CSV, Ledger, decode_ledger_upload
from taxflow.models import RunResult
from taxflow.parsing import InputError, ParsedDocument, decode_upload
from taxflow.pipeline import RECORDED_DIR, load_recorded, run_illustrative, run_live
from taxflow.providers import ProviderError, build_provider, live_mode_enabled, missing_settings, read_settings
from taxflow.samples import SAMPLE_LEDGER, SAMPLES, load_sample, load_sample_ledger

st.set_page_config(page_title="TaxFlow · Invoice reconciliation", page_icon="🧾", layout="wide")

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
  border-radius:8px;padding:8px 0;max-height:560px;overflow:auto;white-space:pre}
.tf-line{display:block;padding:0 10px}
.tf-line .n{display:inline-block;width:3.2em;color:#8796AA;user-select:none}
.tf-hl{background:#D7F0EE;border-left:3px solid #0F7C7A}
.tf-page{display:block;padding:4px 10px;color:#5B6B82;font-weight:600;border-top:1px dashed #D5DEE8;margin-top:4px}
.tf-status{border:1px solid #D5DEE8;border-radius:8px;padding:8px 12px;background:#FFFFFF}
.tf-status .k{font-size:0.75rem;color:#5B6B82;text-transform:uppercase;letter-spacing:0.04em}
.tf-status .v{font-weight:700;margin-top:2px}
table.tf-ledger{border-collapse:collapse;font-size:0.82rem;width:100%;background:#FFFFFF}
table.tf-ledger th,table.tf-ledger td{border:1px solid #D5DEE8;padding:4px 6px;text-align:left}
table.tf-ledger tr.hl td{background:#D7F0EE}
table.tf-ledger tr.cand td{background:#FFF4DB}
</style>
"""

OUTCOME_KIND = {"Matched": "ok", "Discrepancy found": "bad", "No matching entry": "bad", "Ambiguous match": "bad",
                "Needs clarification": "warn", "Unsupported document": "bad", "Incomplete": "bad"}
ARITH_KIND = {"Consistent": "ok", "Inconsistent": "bad", "Not checked": "warn", "Partially checked": "warn"}


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
    return [s for s in SAMPLES if (RECORDED_DIR / f"{s}.json").exists()]


def _reset_result() -> None:
    for k in ("result", "selected_ref", "future", "progress", "run_error"):
        st.session_state.pop(k, None)


def _clear_session() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def _badge(text: str, kind: str) -> str:
    return f'<span class="tf-badge tf-{kind}">{html.escape(text)}</span>'


# ---------------- Sources ----------------

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


def render_ledger_table(ledger: Ledger, res: RunResult | None) -> None:
    compared = res.ledger_entry.ledger_entry_id if res and res.ledger_entry else None
    cands = {e.ledger_entry_id for e in (res.ledger_candidates if res else [])}
    cols = ["row", "ledger_entry_id", "invoice_number", "vendor_name", "invoice_date", "currency", "gross_amount"]
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = []
    for e in ledger.entries:
        cls = "hl" if e.ledger_entry_id == compared else ("cand" if e.ledger_entry_id in cands else "")
        vals = [e.row_number, e.ledger_entry_id, e.invoice_number, e.vendor_name, e.invoice_date, e.currency, e.gross_amount]
        body.append(f'<tr class="{cls}">' + "".join(f"<td>{html.escape(str(v))}</td>" for v in vals) + "</tr>")
    st.markdown(f'<div style="max-height:260px;overflow:auto"><table class="tf-ledger"><tr>{head}</tr>{"".join(body)}'
                "</table></div>", unsafe_allow_html=True)
    st.caption(f"`{ledger.name}` · {len(ledger.entries)} entries · read-only. "
               "Teal = compared entry · amber = candidate not compared. Row 1 is the header.")


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


REQUIRED_LABELS = {"vendor_name": "Vendor", "invoice_number": "Invoice number", "invoice_date": "Invoice date",
                   "currency": "Currency", "total": "Stated total"}
ARITH_LABELS = {"subtotal": "Subtotal", "tax": "Tax (stated)"}


def _field_row(draft, name: str, label: str) -> None:
    ev = draft.scalar(name)
    c1, c2, c3, c4 = st.columns([1.3, 1.6, 1.3, 0.9])
    c1.markdown(f"**{label}**")
    c2.write(ev.value if ev.value is not None else "— (null)")
    c3.markdown(_ev_label(ev), unsafe_allow_html=True)
    with c4:
        _source_button(ev, f"src-{name}")


def render_status_strip(res: RunResult) -> None:
    items = [
        ("Processing", res.workflow_status, "ok" if res.workflow_status == "Complete" else "bad"),
        ("Ledger reconciliation", res.reconciliation_outcome or "—", OUTCOME_KIND.get(res.reconciliation_outcome, "muted")),
        ("Invoice arithmetic", res.arithmetic_status or "—", ARITH_KIND.get(res.arithmetic_status, "muted")),
        ("Human review", res.review_status, "muted" if res.review_status == "Unreviewed" else
         ("ok" if res.review_status == "Approved" else "warn")),
    ]
    cols = st.columns(4)
    for col, (k, v, kind) in zip(cols, items):
        col.markdown(f'<div class="tf-status"><div class="k">{k}</div><div class="v tf-{kind}">{html.escape(v)}</div></div>',
                     unsafe_allow_html=True)


def render_invoice_fields(res: RunResult) -> None:
    draft = res.extracted_fields
    if res.document_type == "unsupported":
        st.markdown(_badge("Unsupported document", "bad"), unsafe_allow_html=True)
        st.write(f"Routed to follow-up: {res.unsupported_reason}. No invoice fields were extracted and the ledger was not searched.")
        return
    if draft is None:
        st.info("No extracted record (the run did not reach extraction).")
        return
    st.caption("Required for reconciliation")
    for name, label in REQUIRED_LABELS.items():
        _field_row(draft, name, label)
    st.caption("Used only for the invoice's own arithmetic check")
    for name, label in ARITH_LABELS.items():
        _field_row(draft, name, label)
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
        label = ("Source verified", "ok") if statuses == {"verified"} else (
            ("Source unsupported", "bad") if "bad" in statuses else ("Incomplete", "warn"))
        c3.markdown(_badge(*label), unsafe_allow_html=True)
        with c4:
            target = next((e for e in (item.line_total, item.description) if e.evidence), item.line_total)
            _source_button(target, f"src-item-{i}")


def render_ledger_match(res: RunResult) -> None:
    outcome = res.reconciliation_outcome
    st.markdown(_badge(outcome or "—", OUTCOME_KIND.get(outcome, "muted")), unsafe_allow_html=True)
    if res.ledger_entry:
        e = res.ledger_entry
        st.write(f"Compared with ledger entry **{e.ledger_entry_id}** (CSV row {e.row_number}).")
    elif outcome == "Ambiguous match":
        st.write("Several entries share this invoice number and vendor. **None was selected**; the analyst must decide.")
    elif outcome == "No matching entry":
        st.write("No entry has this invoice number and vendor. Entries with similar numbers or equal amounts are "
                 "**not** used as matches.")
    elif outcome == "Needs clarification" and not res.ledger_candidates and not res.comparison:
        st.write("The ledger was not searched because an identifier is missing.")
    if res.ledger_candidates:
        st.dataframe([{"Entry": e.ledger_entry_id, "CSV row": e.row_number, "Invoice no.": e.invoice_number,
                       "Vendor": e.vendor_name, "Date": e.invoice_date, "Currency": e.currency, "Gross": e.gross_amount}
                      for e in res.ledger_candidates], hide_index=True, width="stretch")


def render_comparison(res: RunResult) -> None:
    if not res.comparison:
        st.caption("No side-by-side comparison: it runs only when exactly one ledger entry matches.")
        return
    label = {"agree": "AGREE", "differ": "DIFFERS", "not_checked": "NOT CHECKED"}
    names = {"stated_total_vs_gross_amount": "Stated total vs gross amount"}
    st.dataframe([{"Field": names.get(c.field, c.field), "Invoice": c.invoice_value or "— (null)",
                   "Ledger": c.ledger_value, "Result": label[c.status], "Difference": c.difference or "",
                   "Note": c.note or ""} for c in res.comparison], hide_index=True, width="stretch")
    st.caption("Currency is compared first and never converted. Amounts agree when |difference| ≤ 0.01. "
               "The ledger is compared with the invoice's **stated** total, never a recalculated one.")


def render_findings(res: RunResult) -> None:
    blocking = [f for f in res.findings if f.blocking]
    info = [f for f in res.findings if not f.blocking]
    if not blocking:
        st.markdown(_badge("No blocking exceptions", "ok"), unsafe_allow_html=True)
    for f in blocking:
        st.markdown(f'{_badge("BLOCKING", "bad")} <code>{html.escape(f.code)}</code> {html.escape(f.message)}',
                    unsafe_allow_html=True)
    for f in info:
        st.markdown(f'{_badge("NOTE", "muted")} <code>{html.escape(f.code)}</code> {html.escape(f.message)}',
                    unsafe_allow_html=True)


def render_arithmetic(res: RunResult) -> None:
    rows = [c for c in res.check_results if c.name.startswith("item_total") or c.name in ("item_totals", "subtotal", "total")]
    st.markdown(_badge(f"Invoice arithmetic: {res.arithmetic_status or '—'}", ARITH_KIND.get(res.arithmetic_status, "muted")),
                unsafe_allow_html=True)
    if not rows:
        return
    st.dataframe([{"Check": c.name, "Result": {"pass": "PASS", "fail": "FAIL", "not_checked": "NOT CHECKED"}[c.status],
                   "Detail": c.reason or ", ".join(f"{k}: {v}" for k, v in c.details.items() if v not in ([], None, ""))}
                  for c in rows], hide_index=True, width="stretch")
    st.caption("Separate from the ledger comparison. A wrong invoice total is flagged here even when the ledger agrees.")


def render_checks(res: RunResult) -> None:
    rows = [c for c in res.check_results if not (c.name.startswith("item_total") or c.name in ("item_totals", "subtotal", "total"))]
    if not rows:
        return
    st.dataframe([{"Check": c.name, "Result": {"pass": "PASS", "fail": "FAIL", "not_checked": "NOT CHECKED"}[c.status],
                   "Detail": c.reason or ", ".join(f"{k}: {v}" for k, v in c.details.items() if v not in ([], None, ""))}
                  for c in rows], hide_index=True, width="stretch")


def render_trace(res: RunResult) -> None:
    meta = res.run_metadata
    if meta.mode == "illustrative":
        st.caption("Illustrative mode: these Python tools were executed directly by the app. No model chose them.")
    elif meta.mode == "recorded_live":
        st.caption("Recorded live run: these tool calls were chosen by the model during the original run.")
    else:
        st.caption("Live run: these tool calls were chosen by the model through function calling and executed in Python.")
    if res.required_tools:
        st.caption("Required for this outcome: " + ", ".join(f"`{t}`" for t in res.required_tools))
    if not res.tool_trace:
        st.write("No tools were executed.")
        return
    st.dataframe([{"#": t.step, "Tool": t.tool, "Arguments": json.dumps(t.arguments), "Status": t.status,
                   "Result": t.result_summary, "ms": t.duration_ms, "Invoked by": t.invoked_by}
                  for t in res.tool_trace], hide_index=True, width="stretch")


def render_review(res: RunResult) -> None:
    st.markdown("#### Review decision")
    if res.blocking_findings or res.workflow_status != "Complete":
        st.write("Recommended decision: **Needs follow-up**.")
    note = st.text_area("Review note (optional; it does not remove any finding)", value=res.review_note,
                        key=f"note-{res.run_id}", max_chars=2000)
    res.review_note = note
    c1, c2, _ = st.columns([1, 1, 2])
    can = res.can_approve
    if c1.button("Approve", disabled=not can, type="primary", key=f"approve-{res.run_id}"):
        res.review_status = "Approved"
        st.rerun()
    if c2.button("Needs follow-up", key=f"followup-{res.run_id}"):
        res.review_status = "Needs follow-up"
        st.rerun()
    if not can:
        why = ("processing is not Complete" if res.workflow_status != "Complete"
               else f"{len(res.blocking_findings)} blocking exception(s)")
        st.caption(f"Approval is disabled: {why}.")

    st.markdown("#### Export")
    st.caption(f"Exports are labeled: {exports.export_label(res)}")
    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Download JSON", exports.to_json(res), file_name=f"taxflow-{res.document_id}-{res.run_id}.json",
                       mime="application/json")
    d2.download_button("Download CSV", exports.to_csv(res), file_name=f"taxflow-{res.document_id}-{res.run_id}.csv",
                       mime="text/csv")


def render_mode_banner(res: RunResult | None, mode: str) -> None:
    if mode == MODE_ILLUSTRATIVE:
        st.warning("**Illustrative demo.** Invoice extraction is a hand-prepared draft, not model output. The ledger "
                   "search, comparison, and arithmetic checks are real Python. No model is called.")
    elif mode == MODE_RECORDED:
        if res is not None and res.run_metadata.recorded_from:
            r = res.run_metadata.recorded_from
            st.info(f"**Recorded live run.** Replay of an actual run on {r['provider']} · deployment `{r['model']}` · "
                    f"{r['timestamp']}. No inference happens now. Your review choices apply to this replay only.")
        else:
            st.info("**Recorded live run.** Replays a saved actual run against the sample ledger. No inference happens now.")
    else:
        st.success("**Live agent.** Actual model inference and Python tool calls on the current invoice and ledger.")


# ---------------- Running ----------------

def _start_run(mode: str, doc: ParsedDocument, ledger: Ledger, sample_id: str | None, settings: dict) -> None:
    progress: list[str] = []
    lock = threading.Lock()

    def on_status(msg: str) -> None:
        with lock:
            progress.append(msg)

    if mode == MODE_LIVE:
        provider = build_provider(settings)  # raises ProviderError on config problems

        def job():
            return run_live(doc, ledger, provider, on_status)
    else:
        def job():
            return run_illustrative(doc, sample_id, ledger, on_status)

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

def _select_inputs(mode: str) -> tuple[ParsedDocument | None, str | None, Ledger | None]:
    c_inv, c_led = st.columns(2, gap="large")
    doc, sample_id, ledger = None, None, None
    with c_inv:
        st.markdown("##### 1 · Invoice")
        source = "Bundled sample"
        if mode == MODE_LIVE:
            source = st.radio("Invoice input", ["Bundled sample", "Upload synthetic TXT"], horizontal=True,
                              key="input_kind", on_change=_reset_result)
        if source == "Bundled sample":
            ids = _recorded_ids() if mode == MODE_RECORDED else list(SAMPLES)
            sample_id = st.selectbox("Synthetic invoice", ids, format_func=lambda s: SAMPLES[s],
                                     key=f"sample-{mode}", on_change=_reset_result)
            doc = load_sample(sample_id)
        else:
            up = st.file_uploader("Synthetic invoice (.txt, UTF-8, max 2 MB / 20,000 characters)", type=["txt"],
                                  key="upload", on_change=_reset_result)
            if up is not None:
                try:
                    doc = decode_upload(up.getvalue(), up.name)
                except InputError as exc:
                    st.error(f"Invoice rejected: {exc}")
    with c_led:
        st.markdown("##### 2 · Accounting ledger")
        lsource = "Sample ledger"
        if mode == MODE_LIVE:
            lsource = st.radio("Ledger input", ["Sample ledger", "Upload accounting CSV"], horizontal=True,
                               key="ledger_kind", on_change=_reset_result)
        if lsource == "Sample ledger":
            ledger = load_sample_ledger()
            st.caption(f"Using `{ledger.name}` ({len(ledger.entries)} fictional entries).")
        else:
            lup = st.file_uploader("Accounting CSV (UTF-8, max 2 MB / 5,000 rows)", type=["csv"], key="ledger_upload",
                                   on_change=_reset_result)
            if lup is not None:
                try:
                    ledger = decode_ledger_upload(lup.getvalue(), lup.name)
                    st.caption(f"Validated `{ledger.name}`: {len(ledger.entries)} entries.")
                except InputError as exc:
                    st.error(str(exc))
        d1, d2 = st.columns(2)
        d1.download_button("CSV template", TEMPLATE_CSV, file_name="ledger_template.csv", mime="text/csv")
        d2.download_button("Sample ledger", SAMPLE_LEDGER.read_text(encoding="utf-8"), file_name=SAMPLE_LEDGER.name,
                           mime="text/csv")
    if mode == MODE_LIVE:
        st.caption("Use fictional documents only. Uploads stay in this session's memory and are not stored.")
    return doc, sample_id, ledger


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
        if st.button("Clear session", help="Remove the documents, result, note, and decision"):
            _clear_session()
            st.rerun()
    if mode == MODE_LIVE and (missing := missing_settings(settings)):
        st.error("Live mode is enabled but these settings are missing: " + ", ".join(missing)
                 + ". Add them to .streamlit/secrets.toml or environment variables.")

    doc, sample_id, ledger = _select_inputs(mode)
    key = (doc.document_id if doc else None, ledger.ledger_id if ledger else None)
    if st.session_state.get("input_key") != key:
        _reset_result()  # new invoice or ledger resets any prior result and decision
        st.session_state.input_key = key

    running = st.session_state.get("future") is not None
    b1, b2 = st.columns([1, 3])
    analyze = b1.button("Analyze invoice", type="primary", disabled=doc is None or ledger is None or running)
    if st.session_state.get("result") is not None or st.session_state.get("run_error"):
        if b2.button("Reset result"):
            _reset_result()
            st.rerun()

    if analyze and doc is not None and ledger is not None:
        _reset_result()  # a new run always resets the prior decision
        if mode == MODE_RECORDED:
            st.session_state.result = load_recorded(sample_id)
        else:
            try:
                _start_run(mode, doc, ledger, sample_id, settings)
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
    if doc is None or ledger is None:
        st.info("Choose or upload both an invoice and an accounting ledger to begin.")
        return

    if res is not None:
        render_status_strip(res)
        if res.workflow_status in ("Failed", "Incomplete"):
            st.error(f"Processing {res.workflow_status}: {res.run_metadata.error or 'see findings'}. "
                     "No result is presented as a success. Use Retry or Reset.")

    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown(f"#### Invoice source · `{doc.name}`")
        st.caption("Read-only. Line numbers are what evidence references cite.")
        render_source(doc, st.session_state.get("selected_ref"))
    with right:
        st.markdown("#### Extracted invoice fields")
        if res is None:
            st.write("Select **Analyze invoice** to extract fields, search the ledger, compare, and check arithmetic.")
        else:
            render_invoice_fields(res)
    st.markdown("#### Accounting ledger")
    render_ledger_table(ledger, res)
    if res is None:
        return

    st.divider()
    m1, m2 = st.columns([1, 1.4], gap="large")
    with m1:
        st.markdown("#### Ledger match")
        render_ledger_match(res)
    with m2:
        st.markdown("#### Side-by-side comparison")
        render_comparison(res)

    st.divider()
    e1, e2 = st.columns([1.2, 1], gap="large")
    with e1:
        st.markdown("#### Exceptions")
        render_findings(res)
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
    with e2:
        st.markdown("#### Invoice arithmetic (separate check)")
        render_arithmetic(res)
        with st.expander("Other validation checks"):
            render_checks(res)

    st.divider()
    st.markdown("#### Activity log")
    render_trace(res)
    m = res.run_metadata
    st.caption(f"Run `{res.run_id}` · mode {m.mode} · provider {m.provider or 'none'} · model {m.model or 'none'} · "
               f"model requests {m.model_requests}" + (f"/{m.request_budget}" if m.request_budget else "")
               + (f" · tokens {m.token_usage.get('total_tokens')}" if m.token_usage else "")
               + (f" · {m.duration_ms} ms" if m.duration_ms is not None else "")
               + f" · ledger {m.ledger_name} ({m.ledger_id})")
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
TaxFlow helps a tax or finance analyst confirm that each **invoice agrees with the client's accounting entry**,
and prepares an evidence-backed exception report. **A person makes the review decision.**

- **Matching:** exact invoice number + vendor name (whitespace/case normalized). No fuzzy matching; an equal
  amount never selects a record. Several candidates → *Ambiguous match*; none → *No matching entry*.
- **Comparison:** currency first (never converted), then the invoice's **stated total** vs the ledger **gross
  amount** (tax included, Decimal, ±0.01), then the invoice date.
- **Invoice arithmetic** is a separate check: a stated total of 950 with subtotal 800 + tax 80 agrees with a
  ledger amount of 950 but is still flagged as arithmetic expecting 880.
- All data is **synthetic and fictional**. TaxFlow does not file taxes, calculate tax liability, pay invoices,
  post entries, certify compliance, or send messages. Independent project; no affiliation with any firm is implied.

**Modes.** *Illustrative demo*: hand-prepared extraction, real Python checks, no model. *Recorded live run*:
replay of an actual saved live run with provenance. *Live agent* (local/private only): actual Azure OpenAI
inference and model-chosen Python tool calls.
""")


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    settings = _settings()
    st.title("TaxFlow")
    st.markdown("**Reconcile invoices with accounting records, with source evidence.** Pick an invoice and a ledger, "
                "analyze, inspect the match and every difference, and decide what needs follow-up.")
    tab_review, tab_eval, tab_about = st.tabs(["Review", "Evaluation", "About"])
    with tab_review:
        page_review(settings)
    with tab_eval:
        page_evaluation()
    with tab_about:
        page_about()


main()
