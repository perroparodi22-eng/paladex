"""Weekly AI web search for recent figures ("Other sources (non-official)"), OFF by default.

When the owner switches it on (Sources page, or ``PALADEX_WEB_FINDINGS_AI=true``) and Anthropic is the
configured AI provider with a key, the ``web_findings`` collector asks Claude, with Anthropic's
server-side web search tool, for the newest 2025/2026 figures of the countries that lack recent ones.
The answer must be findings in the exact seed format, each with a verbatim quote and the page it is on.

Nothing the model says is stored as such: every proposed finding goes through the same check as the
seed (``services.web_verify``): Paladex opens the page itself and stores the finding only if the quote
and the number are there. What is sent: the country's name, the list of metrics, today's date and the
rules. Never the company's name, a supplier quote or any figure from the database.

Provider: Anthropic only (Messages API, ``web_search_20250305``: basic web search, available on every
current model, results returned to Claude directly; ``max_uses`` caps the searches of each request).
OpenAI is not supported for this search: the interface says so.

Cost (the estimate shown on the Sources page, list prices of the Claude API read on 2026-11-05 at
platform.claude.com/docs/en/about-claude/pricing): web search $10 per 1,000 searches, plus the tokens;
the model is ``settings.web_findings_ai_model`` (default ``claude-haiku-5-5``: $0.10 per million input
tokens, $0.50 per million output tokens for prompts up to 100,000 tokens). The real usage of every
run (requests, searches, tokens, cost at these prices) is recorded in the app setting
``web_findings_ai_usage``.

Plain httpx, like ``services.llm`` (the app has no SDK dependency); the key is sent only to
api.anthropic.com and never logged.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from ..config import Settings
from . import llm

log = logging.getLogger(__name__)

AI_SETTING = "web_findings_ai"              # {"enabled": bool, "max_searches": int} (set from the Sources page)
AI_USAGE_SETTING = "web_findings_ai_usage"  # the last runs' usage, newest last
AI_STATE_SETTING = "web_findings_ai_state"  # {iso3: {"searched_at", "proposed", "verified", "searched", "queries"}}

WEB_SEARCH_TOOL = "web_search_20250305"
SEARCHES_PER_COUNTRY = 3                    # max_uses of one request (one country)
MAX_CONTINUATIONS = 2                       # pause_turn resumptions per country
MAX_TOKENS = 4096
TIMEOUT = httpx.Timeout(240.0, connect=10.0)
MAX_SEARCHES_LIMIT = 100                    # highest cap the owner can choose
USAGE_RUNS_KEPT = 12

# --- prices (USD), Claude API list prices read on PRICES_CHECKED_ON --------------------------------
PRICES_CHECKED_ON = "2026-11-05"
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
WEB_SEARCH_USD_PER_1000 = 10.0
PRICES: dict[str, dict[str, Any]] = {
    # per million tokens
    "claude-haiku-5-5": {"label": "Claude Haiku 5.5", "input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01,
                         "long": {"over": 100_000, "input": 0.50, "output": 2.50, "cache_write": 0.625, "cache_read": 0.05}},
    "claude-sonnet-5-5": {"label": "Claude Sonnet 5.5", "input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10},
    "claude-opus-5-5": {"label": "Claude Opus 5.5", "input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
}
# Assumptions of the estimate (basic web search puts the results in the prompt; thinking is billed as output).
ASSUMED_INPUT_TOKENS_PER_SEARCH = 20_000
ASSUMED_OUTPUT_TOKENS_PER_SEARCH = 2_000
RUNS_PER_MONTH = 52 / 12                    # weekly

METRICS_TEXT = ("production (honey production volume), exports and imports (volume or value of natural honey, "
                "HS 0409), hives (number of beehives / bee colonies), producer_price (price paid to beekeepers), "
                "export_price (export price or export unit value of honey)")

SYSTEM = f"""You look for the newest published figures about natural honey in ONE country, for a market-intelligence \
database. Use web search. Report ONLY figures you have actually read on a web page or PDF during this search.

Rules:
- Periods 2025 or 2026 only (calendar, marketing or crop year). Never older periods.
- Metrics: {METRICS_TEXT}.
- quote: copy ONE sentence or table row from the page character for character (20 to 300 characters) that \
contains the figure. Do not translate, shorten, paraphrase, correct or join sentences. Each quote is checked \
automatically against the page and discarded if it is not there word for word.
- value_as_published: the figure exactly as printed, with its unit (for example "75.000 toneladas").
- value: the same figure as a plain number in `unit`; never convert currencies or units.
- source_url: the exact address of the page or PDF that contains the quote (not a search page, not a homepage).
- status: official_final | official_provisional | official_estimate (these three only for official bodies) | \
forecast | estimate | reported.
- kind: official_statistic | official_publication | government_statement | usda_fas | international_body | \
association | trade_press | news | market_report. is_official is true only for governments, ministries, \
statistics offices, USDA FAS, FAO, the European Commission and similar public bodies.
- Never estimate, compute, round, add up or combine figures. If nothing reliable is found, return no findings.
- Reply with one JSON object only, no prose and no code fences."""

SCHEMA_HINT = {
    "findings": [{
        "country_iso3": "ISO3", "metric": "production", "period_label": "2025", "period_start": "2025-01-01",
        "period_end": "2025-12-31", "value": 75000, "unit": "t", "value_as_published": "75.000 toneladas",
        "status": "estimate", "kind": "association", "is_official": False, "publisher": "...",
        "source_url": "https://...", "source_title": "...", "published_at": "YYYY-MM-DD or null", "language": "es",
        "quote": "exact sentence from the page", "also_reported_by": [], "notes": None,
    }],
    "searched": "what you searched for, in one sentence",
}


class AiSearchError(Exception):
    """The provider call failed (message safe to show: never contains the key)."""


@dataclass
class AiSearchResult:
    findings: list[dict] = field(default_factory=list)
    searched: str = ""
    queries: list[str] = field(default_factory=list)
    result_urls: list[str] = field(default_factory=list)
    search_errors: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: new_usage())


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def stored_settings(session) -> dict:
    from ..models import AppSetting

    row = session.get(AppSetting, AI_SETTING)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def ai_status(session, settings: Settings) -> dict:
    """The switch, the cap and whether the search can run (provider and key)."""
    stored = stored_settings(session)
    enabled = bool(stored["enabled"]) if "enabled" in stored else bool(settings.web_findings_ai)
    cap = stored.get("max_searches") or settings.web_findings_ai_max_searches
    cap = max(1, min(MAX_SEARCHES_LIMIT, int(cap)))
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        unavailable = None
    elif settings.llm_provider == "openai":
        unavailable = "provider_not_supported"
    else:
        unavailable = "no_key"
    return {
        "enabled": enabled,
        "enabled_by": "setting" if "enabled" in stored else ("env" if settings.web_findings_ai else "default"),
        "max_searches": cap,
        "provider": "anthropic",
        "configured_provider": settings.llm_provider,
        "model": settings.web_findings_ai_model,
        "unavailable": unavailable,
        "will_run": enabled and unavailable is None,
    }


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

def new_usage() -> dict:
    return {"requests": 0, "searches": 0, "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": 0.0, "cost_known": True}


def request_cost(model: str, usage: dict) -> float | None:
    """Cost in USD of one Messages API answer at the list prices above (None for an unknown model)."""
    p = PRICES.get(model)
    if p is None:
        return None
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cw = int(usage.get("cache_creation_input_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    searches = int(((usage.get("server_tool_use") or {}).get("web_search_requests")) or 0)
    tier = p
    if "long" in p and inp + cw + cr > p["long"]["over"]:
        tier = p["long"]
    tokens = (inp * tier["input"] + out * tier["output"] + cw * tier["cache_write"] + cr * tier["cache_read"]) / 1e6
    return round(tokens + searches * WEB_SEARCH_USD_PER_1000 / 1000, 6)


def add_usage(total: dict, model: str, usage: dict) -> None:
    total["requests"] += 1
    total["searches"] += int(((usage.get("server_tool_use") or {}).get("web_search_requests")) or 0)
    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        total[k] += int(usage.get(k) or 0)
    cost = request_cost(model, usage)
    if cost is None:
        total["cost_known"] = False
    else:
        total["cost_usd"] = round(total["cost_usd"] + cost, 6)


def estimate(model: str, max_searches: int) -> dict:
    """Cost estimate of one run and of a month (weekly runs) at the cap, with the prices and the
    assumptions it rests on."""
    p = PRICES.get(model)
    base = {"model": model, "max_searches": max_searches, "prices_checked_on": PRICES_CHECKED_ON,
            "prices_source": PRICES_SOURCE, "web_search_usd_per_1000": WEB_SEARCH_USD_PER_1000,
            "assumed_input_tokens_per_search": ASSUMED_INPUT_TOKENS_PER_SEARCH,
            "assumed_output_tokens_per_search": ASSUMED_OUTPUT_TOKENS_PER_SEARCH,
            "runs_per_month": round(RUNS_PER_MONTH, 2)}
    if p is None:
        return {**base, "known": False}
    per_search = (WEB_SEARCH_USD_PER_1000 / 1000 + ASSUMED_INPUT_TOKENS_PER_SEARCH * p["input"] / 1e6
                  + ASSUMED_OUTPUT_TOKENS_PER_SEARCH * p["output"] / 1e6)
    per_run = per_search * max_searches
    return {**base, "known": True, "model_label": p["label"], "input_usd_per_mtok": p["input"],
            "output_usd_per_mtok": p["output"], "long_context": p.get("long"),
            "per_search_usd": round(per_search, 4), "per_run_usd": round(per_run, 2),
            "per_month_usd": round(per_run * RUNS_PER_MONTH, 2)}


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------

def build_request(settings: Settings, *, country_name: str, iso3: str, today: date, max_uses: int) -> tuple[dict, dict]:
    """(headers, body) of the first request for one country."""
    user = (f"Country: {country_name} (ISO 3166 alpha-3: {iso3}). Today is {today.isoformat()}.\n"
            f"Find the newest figures published for 2025 or 2026 for these metrics: {METRICS_TEXT}.\n"
            f"Answer with one JSON object of this shape:\n{json.dumps(SCHEMA_HINT, ensure_ascii=False)}")
    headers = {"x-api-key": settings.anthropic_api_key or "", "anthropic-version": llm.ANTHROPIC_VERSION,
               "content-type": "application/json"}
    body = {
        "model": settings.web_findings_ai_model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "tools": [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max(1, int(max_uses))}],
    }
    return headers, body


def _post(client: httpx.Client, headers: dict, body: dict) -> dict:
    last = "?"
    for attempt in (1, 2):
        try:
            resp = client.post(llm.ANTHROPIC_URL, headers=headers, json=body, timeout=TIMEOUT)
        except httpx.TimeoutException:
            last = "no answer within the time limit"
        except httpx.HTTPError as exc:
            last = f"network error ({type(exc).__name__})"
        else:
            if resp.status_code in llm.RETRY_STATUS and attempt == 1:
                ra = resp.headers.get("retry-after", "")
                time.sleep(min(float(ra) if ra.replace(".", "", 1).isdigit() else llm.RETRY_DELAY_SECONDS,
                               llm.MAX_RETRY_AFTER_SECONDS))
                last = f"HTTP {resp.status_code}"
                continue
            if resp.status_code in (401, 403):
                raise AiSearchError(f"Anthropic: API key not valid or without permission (HTTP {resp.status_code})")
            if resp.status_code != 200:
                raise AiSearchError(f"Anthropic: HTTP {resp.status_code} {llm._error_detail(resp)}".strip())
            try:
                return resp.json()
            except ValueError:
                raise AiSearchError("Anthropic: the answer is not JSON") from None
        if attempt == 1:
            time.sleep(llm.RETRY_DELAY_SECONDS)
    raise AiSearchError(f"Anthropic: {last}")


def search_country(client: httpx.Client, settings: Settings, *, country_name: str, iso3: str, today: date,
                   max_uses: int) -> AiSearchResult:
    """Ask the model for one country's recent figures. Raises AiSearchError."""
    headers, body = build_request(settings, country_name=country_name, iso3=iso3, today=today, max_uses=max_uses)
    out = AiSearchResult()
    model = body["model"]
    data: dict = {}
    for _ in range(1 + MAX_CONTINUATIONS):
        data = _post(client, headers, body)
        add_usage(out.usage, model, data.get("usage") or {})
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "server_tool_use" and block.get("name") == "web_search":
                q = (block.get("input") or {}).get("query")
                if q:
                    out.queries.append(str(q)[:200])
            elif block.get("type") == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    out.result_urls += [str(r.get("url")) for r in content if isinstance(r, dict) and r.get("url")]
                elif isinstance(content, dict):
                    out.search_errors.append(str(content.get("error_code") or "error"))
        if data.get("stop_reason") != "pause_turn":
            break
        # resume the paused turn: send the paused assistant message back unchanged
        body = {**body, "messages": [*body["messages"], {"role": "assistant", "content": data.get("content") or []}]}
    if data.get("stop_reason") == "refusal":
        raise AiSearchError("Anthropic: the model declined the request")
    if data.get("stop_reason") == "pause_turn":
        log.warning("AI web search for %s still paused after %s continuations", iso3, MAX_CONTINUATIONS)
        return out
    text = "".join(b.get("text", "") for b in data.get("content") or []
                   if isinstance(b, dict) and b.get("type") == "text")
    if not text.strip():
        return out
    try:
        parsed = llm.extract_json(text)
    except llm.LLMError as exc:
        raise AiSearchError(f"Anthropic: {exc}") from None
    items = parsed.get("findings", parsed.get("items"))
    out.findings = [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []
    out.searched = str(parsed.get("searched") or "")[:500]
    return out
