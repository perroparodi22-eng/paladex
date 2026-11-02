"""Minimal LLM provider abstraction (no SDK dependency, plain httpx).

Providers:
* ``anthropic`` - Messages API, ``POST https://api.anthropic.com/v1/messages``
  (headers ``x-api-key`` + ``anthropic-version: 2023-06-01``), model ``settings.anthropic_model``.
* ``openai``    - Chat Completions, ``POST https://api.openai.com/v1/chat/completions``
  (``Authorization: Bearer``), model ``settings.openai_model``, JSON mode.

Security: the endpoints are constants (keys are only ever sent to the provider they belong
to), keys are never logged nor included in exception messages, and nothing here is exposed
to the browser.

Use `complete_json()`; it raises `LLMUnavailable` when no provider/key is configured and
`LLMError` for any provider failure (after one retry for transient errors).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

TIMEOUT = httpx.Timeout(90.0, connect=10.0)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
RETRY_DELAY_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 20.0


class LLMUnavailable(Exception):
    """No AI provider configured (PALADEX_LLM_PROVIDER / API key missing)."""


class LLMError(Exception):
    """The provider call failed or returned something unusable."""


@dataclass(frozen=True)
class ProviderInfo:
    provider: str
    model: str

    @property
    def label(self) -> str:
        """Stored in `ai_model` columns, e.g. 'anthropic:claude-sonnet-5-5'."""
        return f"{self.provider}:{self.model}"[:80]


def is_enabled(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).llm_enabled()


def provider_info(settings: Settings | None = None) -> ProviderInfo:
    s = settings or get_settings()
    if not s.llm_enabled():
        raise LLMUnavailable("Nessun servizio di IA configurato (PALADEX_LLM_PROVIDER e chiave API).")
    if s.llm_provider == "anthropic":
        return ProviderInfo("anthropic", s.anthropic_model)
    return ProviderInfo("openai", s.openai_model)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict:
    """Robustly pull a JSON object out of a model reply (code fences, prose around it,
    trailing commas). A top-level list is wrapped as {"items": [...]}."""
    if not text or not text.strip():
        raise LLMError("Risposta vuota dal modello")
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for cand in candidates:
        cand = cand.strip()
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                value = json.loads(attempt)
                return value if isinstance(value, dict) else {"items": value}
            except json.JSONDecodeError:
                pass
        # first decodable object/array inside surrounding prose
        for i, ch in enumerate(cand):
            if ch not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(cand[i:])
            except json.JSONDecodeError:
                try:
                    value, _ = decoder.raw_decode(re.sub(r",\s*([}\]])", r"\1", cand[i:]))
                except json.JSONDecodeError:
                    continue
            if isinstance(value, (dict, list)):
                return value if isinstance(value, dict) else {"items": value}
    raise LLMError("La risposta del modello non contiene JSON valido")


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------


def _system_with_schema(system: str, schema_hint: Any) -> str:
    if schema_hint is None:
        return system + "\n\nReply with a single JSON object only, no prose and no code fences."
    hint = schema_hint if isinstance(schema_hint, str) else json.dumps(schema_hint, ensure_ascii=False, indent=1)
    return (f"{system}\n\nReply with a single JSON object only (no prose, no code fences), with this shape:\n"
            f"{hint}")


def _anthropic_request(s: Settings, system: str, user: str, max_tokens: int) -> tuple[str, dict, dict]:
    headers = {
        "x-api-key": s.anthropic_api_key or "",
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": s.anthropic_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    return ANTHROPIC_URL, headers, body


def _anthropic_text(data: dict) -> str:
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    if not text and data.get("stop_reason") == "refusal":
        raise LLMError("Il modello ha rifiutato la richiesta")
    return text


def _openai_request(s: Settings, system: str, user: str, max_tokens: int) -> tuple[str, dict, dict]:
    headers = {"Authorization": f"Bearer {s.openai_api_key or ''}", "Content-Type": "application/json"}
    body = {
        "model": s.openai_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max_tokens,
    }
    return OPENAI_URL, headers, body


def _openai_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("Risposta senza 'choices'")
    msg = choices[0].get("message") or {}
    if msg.get("refusal"):
        raise LLMError("Il modello ha rifiutato la richiesta")
    return msg.get("content") or ""


def _error_detail(resp: httpx.Response) -> str:
    """Provider error message (never echoes request headers / keys)."""
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or "")[:300]
        if isinstance(err, str):
            return err[:300]
    except ValueError:
        pass
    return resp.reason_phrase or ""


def complete_json(
    system: str,
    user: str,
    schema_hint: Any = None,
    max_tokens: int = 1024,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Ask the configured model for a JSON object. Raises LLMUnavailable / LLMError."""
    s = settings or get_settings()
    info = provider_info(s)
    full_system = _system_with_schema(system, schema_hint)
    if info.provider == "anthropic":
        url, headers, body = _anthropic_request(s, full_system, user, max_tokens)
        to_text = _anthropic_text
    else:
        url, headers, body = _openai_request(s, full_system, user, max_tokens)
        to_text = _openai_text

    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        last_error = "?"
        for attempt in (1, 2):  # one retry on transient failures
            try:
                resp = http.post(url, headers=headers, json=body, timeout=TIMEOUT)
            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt == 1:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                raise LLMError(f"{info.provider}: nessuna risposta entro il tempo limite") from None
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                if attempt == 1:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                raise LLMError(f"{info.provider}: errore di rete ({type(exc).__name__})") from None
            if resp.status_code in RETRY_STATUS and attempt == 1:
                ra = resp.headers.get("retry-after", "")
                delay = float(ra) if ra.replace(".", "", 1).isdigit() else RETRY_DELAY_SECONDS
                time.sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
                last_error = f"HTTP {resp.status_code}"
                continue
            if resp.status_code in (401, 403):
                raise LLMError(f"{info.provider}: chiave API non valida o senza permessi (HTTP {resp.status_code})")
            if resp.status_code != 200:
                raise LLMError(f"{info.provider}: HTTP {resp.status_code} {_error_detail(resp)}".strip())
            try:
                data = resp.json()
            except ValueError:
                raise LLMError(f"{info.provider}: risposta non in formato JSON") from None
            text = to_text(data)
            if (data.get("stop_reason") == "max_tokens"
                    or ((data.get("choices") or [{}])[0].get("finish_reason") == "length")):
                log.warning("LLM output truncated at max_tokens=%s", max_tokens)
            return extract_json(text)
        raise LLMError(f"{info.provider}: {last_error}")
    finally:
        if own:
            http.close()
