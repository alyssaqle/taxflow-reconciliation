"""Model provider adapter. All provider configuration lives in this module.

Azure OpenAI is called through its v1 API with the official ``openai`` SDK:
base URL ``https://<resource>.openai.azure.com/openai/v1/``, deployment name passed
as ``model``, no api-version (verified against Microsoft Learn, 2026-09-30).
The SDK's own retries are disabled so every attempt counts against the agent's budget.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

REQUEST_TIMEOUT_SECONDS = 45.0

SETTING_NAMES = (
    "MODEL_PROVIDER",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "LIVE_MODE_ENABLED",
    "MODEL_TEMPERATURE",
)


class ProviderError(Exception):
    """kind: transient | auth | unsupported | config | other"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw_message: dict[str, Any] = field(default_factory=dict)  # assistant message to append to history


class Provider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[dict], *, tools: list[dict] | None = None,
                 response_format: dict | None = None) -> ModelReply: ...


def read_settings(secrets: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Environment variables take precedence over Streamlit secrets."""
    out = {}
    for key in SETTING_NAMES:
        val = os.environ.get(key)
        if val is None and secrets is not None:
            try:
                val = secrets.get(key)
            except Exception:  # st.secrets raises if no secrets file exists
                val = None
        if val is not None:
            out[key] = str(val)
    return out


def live_mode_enabled(settings: Mapping[str, str]) -> bool:
    return settings.get("LIVE_MODE_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def missing_settings(settings: Mapping[str, str]) -> list[str]:
    need = ("AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")
    return [k for k in need if not settings.get(k) or "<" in settings.get(k, "")]


class AzureOpenAIProvider:
    name = "Azure OpenAI (v1 API, Chat Completions)"

    def __init__(self, base_url: str, api_key: str, deployment: str, temperature: float | None = 0.0):
        from openai import OpenAI

        if not base_url.rstrip("/").endswith("/openai/v1"):
            raise ProviderError("config", "AZURE_OPENAI_BASE_URL must end with /openai/v1/")
        self.model = deployment
        self.temperature = temperature
        self._client = OpenAI(base_url=base_url.rstrip("/") + "/", api_key=api_key,
                              timeout=REQUEST_TIMEOUT_SECONDS, max_retries=0)

    def complete(self, messages, *, tools=None, response_format=None) -> ModelReply:
        import openai

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:  # reasoning deployments reject it: set MODEL_TEMPERATURE = "none"
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError,
                openai.InternalServerError) as exc:
            raise ProviderError("transient", f"{type(exc).__name__}: transient provider error") from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):
            raise ProviderError("auth", "Authentication failed. Check the API key and resource URL.") from None
        except openai.NotFoundError:
            raise ProviderError("config", "Deployment not found. Check AZURE_OPENAI_DEPLOYMENT and the base URL.") from None
        except openai.BadRequestError as exc:
            msg = str(getattr(exc, "message", "")) or "bad request"
            kind = "unsupported" if any(w in msg.lower() for w in ("not supported", "unsupported", "response_format", "tools")) else "other"
            raise ProviderError(kind, f"Request rejected by the provider: {msg[:300]}") from None
        except openai.APIError as exc:
            raise ProviderError("other", f"{type(exc).__name__}: provider error") from None

        choice = resp.choices[0]
        msg = choice.message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments) for c in (msg.tool_calls or [])]
        raw = {"role": "assistant", "content": msg.content}
        if calls:
            raw["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls
            ]
        usage = {}
        if resp.usage:
            usage = {"prompt_tokens": resp.usage.prompt_tokens or 0,
                     "completion_tokens": resp.usage.completion_tokens or 0,
                     "total_tokens": resp.usage.total_tokens or 0}
        return ModelReply(content=msg.content, tool_calls=calls, finish_reason=choice.finish_reason,
                          usage=usage, raw_message=raw)


def build_provider(settings: Mapping[str, str]) -> Provider:
    provider = settings.get("MODEL_PROVIDER", "azure_openai")
    if provider != "azure_openai":
        raise ProviderError("config", f"MODEL_PROVIDER '{provider}' is not implemented; use azure_openai.")
    missing = missing_settings(settings)
    if missing:
        raise ProviderError("config", "Missing settings: " + ", ".join(missing))
    temp = settings.get("MODEL_TEMPERATURE", "0").strip().lower()
    return AzureOpenAIProvider(settings["AZURE_OPENAI_BASE_URL"], settings["AZURE_OPENAI_API_KEY"],
                               settings["AZURE_OPENAI_DEPLOYMENT"],
                               temperature=None if temp in ("", "none") else float(temp))
