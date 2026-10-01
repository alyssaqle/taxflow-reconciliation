"""Run the live agent on bundled samples and save "Recorded live run" packets.

Usage:  python -m taxflow.record              (all six samples)
        python -m taxflow.record wrong_total  (one sample)

Only successful (Complete) live runs are saved. Recorded files carry provider, model,
and timestamp provenance; they contain no credentials and no source text beyond quotes.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from .pipeline import RECORDED_DIR, run_live
from .providers import ProviderError, build_provider, read_settings
from .samples import SAMPLES, load_sample


def main(argv: list[str]) -> int:
    secrets_path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    secrets = tomllib.loads(secrets_path.read_text()) if secrets_path.exists() else {}
    settings = read_settings(secrets)
    try:
        provider = build_provider(settings)
    except ProviderError as exc:
        print(f"Cannot run live: {exc}")
        return 2
    key = settings.get("AZURE_OPENAI_API_KEY", "")
    RECORDED_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for sid in argv or list(SAMPLES):
        res = run_live(load_sample(sid), provider, on_status=lambda m: None)
        tools = ", ".join(f"{t.tool}:{t.status}" for t in res.tool_trace) or "none"
        print(f"{sid}: {res.workflow_status} · {res.document_type} · findings "
              f"{[f.code for f in res.findings]} · tools {tools} · {res.run_metadata.model_requests} requests")
        if res.workflow_status != "Complete":
            print(f"  not saved: {res.run_metadata.error}")
            failures += 1
            continue
        data = res.model_dump_json(indent=2)
        if key and key in data:
            print("  not saved: output contained the credential value")
            failures += 1
            continue
        (RECORDED_DIR / f"{sid}.json").write_text(data + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
