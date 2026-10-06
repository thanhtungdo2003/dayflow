"""AI providers. Nothing is sent anywhere unless the user picked a provider AND ticked the
per-feature consent flags (`ai.allow_chat`, `ai.allow_reports`) — callers check those.

Kinds:
* `openai`    — any /v1/chat/completions API (Mistral, Gemini, Groq, Mangso, Ollama, LM Studio…),
                stdlib HTTP only.
* `anthropic` — Claude via the official `anthropic` SDK (optional extra: `pip install .[ai]`).
* `opencode`  — the locally installed OpenCode CLI (see ai/opencode.py).

API keys never live in config.json; they are stored per provider in the encrypted vault.
Default model lists are starting points — "load models" asks the provider for its live list.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable, Protocol
from urllib.parse import urlsplit

from ..config import AIConfig

log = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class AIProviderError(Exception):
    pass


class AIProvider(Protocol):
    name: str
    is_local: bool

    def complete(self, system: str, prompt: str) -> str: ...


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    kind: str                       # none | openai | anthropic | opencode
    base_url: str = ""
    needs_key: bool = True
    local: bool = False             # data stays on this machine
    url_editable: bool = False
    models: tuple[str, ...] = ()
    key_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


PROVIDERS: dict[str, ProviderSpec] = {p.id: p for p in (
    ProviderSpec("none", "Không dùng AI", "none", needs_key=False, local=True),
    ProviderSpec("openai_compatible", "Máy chủ cục bộ (Ollama, LM Studio)", "openai",
                 "http://localhost:11434/v1", needs_key=False, local=True, url_editable=True,
                 models=("llama3.1", "qwen2.5", "gemma2")),
    ProviderSpec("mistral", "Mistral AI", "openai", "https://api.mistral.ai/v1",
                 models=("mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"),
                 key_url="https://console.mistral.ai/api-keys"),
    ProviderSpec("gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
                 models=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"),
                 key_url="https://aistudio.google.com/apikey"),
    ProviderSpec("groq", "Groq", "openai", "https://api.groq.com/openai/v1",
                 models=("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"),
                 key_url="https://console.groq.com/keys"),
    ProviderSpec("mangso", "Mangso", "openai", "https://ai.mangso.net/v1", key_url="https://ai.mangso.net"),
    ProviderSpec("anthropic", "Anthropic Claude", "anthropic",
                 models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"),
                 key_url="https://console.anthropic.com/settings/keys"),
    ProviderSpec("opencode", "OpenCode CLI (đã cài trên máy)", "opencode", needs_key=False,
                 models=("opencode/big-pickle",)),
)}


def spec_for(provider: str) -> ProviderSpec:
    return PROVIDERS.get(provider, PROVIDERS["none"])


def is_local_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in ("localhost", "127.0.0.1", "::1")


def base_url_for(config: AIConfig, provider: str) -> str:
    spec = spec_for(provider)
    return (config.base_url or spec.base_url) if spec.url_editable else spec.base_url


def model_for(config: AIConfig, provider: str) -> str:
    spec = spec_for(provider)
    return (config.models.get(provider)
            or (config.model if provider == config.provider else "")
            or (spec.models[0] if spec.models else ""))


def _http_error(exc: Exception) -> AIProviderError:
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            body = json.loads(exc.read() or b"{}")
            err = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(err, list) and err:
                err = err[0].get("error", err[0]) if isinstance(err[0], dict) else err[0]
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except (ValueError, AttributeError):
            pass
        return AIProviderError(f"HTTP {exc.code}" + (f": {str(detail)[:200]}" if detail else ""))
    if isinstance(exc, urllib.error.URLError):
        return AIProviderError(f"không kết nối được ({exc.reason})")
    return AIProviderError(f"lỗi: {type(exc).__name__}")


def _request(url: str, api_key: str, timeout: int, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": "PersonalWorkAgent"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - provider URL from registry/user
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise _http_error(exc) from exc


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 60, name: str = "openai_compatible"):
        self.name = name
        self._base = base_url.rstrip("/")
        self._model = model
        self._key = api_key
        self._timeout = timeout
        self.is_local = is_local_url(base_url)

    def complete(self, system: str, prompt: str) -> str:
        if not self._model:
            raise AIProviderError("chưa chọn model")
        data = _request(f"{self._base}/chat/completions", self._key, self._timeout, {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.2,
        })
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("phản hồi không hợp lệ") from exc

    def list_models(self) -> list[str]:
        data = _request(f"{self._base}/models", self._key, self._timeout)
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        ids = []
        for item in items or []:
            mid = item.get("id") or item.get("name") if isinstance(item, dict) else str(item)
            if mid:
                ids.append(mid.removeprefix("models/"))
        return sorted(set(ids))


class AnthropicProvider:
    name = "anthropic"
    is_local = False

    def __init__(self, api_key: str, model: str = "", timeout: int = 60):
        try:
            import anthropic  # optional dependency
        except ImportError as exc:
            raise AIProviderError("chưa cài gói 'anthropic'") from exc
        if not api_key:
            raise AIProviderError("chưa nhập API key")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout), max_retries=2)
        self._model = model or DEFAULT_ANTHROPIC_MODEL

    def complete(self, system: str, prompt: str) -> str:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                # Server-side fallback: on a safety refusal, the API retries on a suitable model.
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
        except self._anthropic.APIStatusError as exc:
            raise AIProviderError(f"HTTP {exc.status_code}") from exc
        except self._anthropic.APIConnectionError as exc:
            raise AIProviderError("không kết nối được") from exc
        if response.stop_reason == "refusal":
            raise AIProviderError("yêu cầu bị từ chối")
        return "".join(block.text for block in response.content if block.type == "text")

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._client.models.list())
        except self._anthropic.APIStatusError as exc:
            raise AIProviderError(f"HTTP {exc.status_code}") from exc
        except self._anthropic.APIConnectionError as exc:
            raise AIProviderError("không kết nối được") from exc


def create_provider(config: AIConfig, provider: str, api_key: str, model: str | None = None,
                    base_url: str | None = None):
    """Build a provider object; raises AIProviderError when it cannot work."""
    spec = spec_for(provider)
    model = model if model is not None else model_for(config, provider)
    if spec.kind == "none":
        raise AIProviderError("chưa chọn nhà cung cấp")
    if spec.needs_key and not api_key:
        raise AIProviderError("chưa nhập API key")
    if spec.kind == "openai":
        url = base_url if (base_url and spec.url_editable) else base_url_for(config, provider)
        return OpenAICompatibleProvider(url, model, api_key, config.timeout_seconds, name=provider)
    if spec.kind == "anthropic":
        return AnthropicProvider(api_key, model, config.timeout_seconds)
    if spec.kind == "opencode":
        from .opencode import OpenCodeProvider
        return OpenCodeProvider(model, config.opencode_path, config.opencode_timeout_seconds)
    raise AIProviderError("nhà cung cấp không hỗ trợ")


def build_provider(config: AIConfig, key_lookup: Callable[[str], str]) -> AIProvider | None:
    """The configured provider, or None when AI is off or misconfigured."""
    if spec_for(config.provider).kind == "none":
        return None
    try:
        return create_provider(config, config.provider, key_lookup(config.provider))
    except AIProviderError as exc:
        log.warning("AI provider unavailable: %s", exc)
        return None
