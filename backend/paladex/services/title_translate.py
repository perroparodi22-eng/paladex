"""Italian headlines for news in other languages, without an AI key.

Why: the country feeds bring headlines in Serbian, Ukrainian, Hungarian, Polish, Greek... With an
AI provider configured, `services.ai_enrich` translates and summarises them. Without one (the
default) a headline in Cyrillic told the owner nothing. This module fills `title_it` with a
MACHINE translation from MyMemory (mymemory.translated.net, Translated srl), a free translation
service that needs no key.

What is sent: the headline only (public text the publisher put in its feed), the language pair
and the application's generic User-Agent. Never the company name, never anything of the owner's.
Switch it off with ``PALADEX_TITLE_TRANSLATION=false`` in ``.env``.

Rules
-----
* It is a machine translation and is always labelled as one (`ai_model = "mymemory"`, shown as
  "Traduzione automatica" with the original headline one hover away). The original `title` is
  never changed.
* Only the service's machine translation of the exact headline is accepted (`created-by: MT!`), or
  an exact (100%) translation-memory match: a "similar sentence" from someone else's memory is not
  a translation of this headline.
* A translation whose numbers do not match the headline's is rejected (`ai_enrich._numbers_ok`:
  a headline saying 40-45 thousand tonnes must not come back saying 4,5).
* MyMemory allows 5,000 characters a day without registration and 50,000 with a contact e-mail
  (its "Usage limits" page, read on 10 Nov 2026). The budget below stays under that; the owner
  may give an address in ``PALADEX_TITLE_TRANSLATION_EMAIL`` to use the larger allowance. When the
  service says the allowance is used up, nothing more is asked until the next day.
* With an AI provider configured this module does nothing: the AI translates (and later replaces
  a machine translation when it enriches the article).

Order: languages the owner does not read first (anything but Italian, English, Spanish,
Portuguese, German, French), then those, then English; inside each group the relevant articles
(score >= 35) before the others, newest first. So the daily allowance goes to the headlines that
are both unreadable and important.
"""
from __future__ import annotations

import html
import logging
import threading
import time
from datetime import date

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting, NewsArticle
from .ai_enrich import MIN_RELEVANCE, READABLE_LANGUAGES, _numbers_ok

log = logging.getLogger(__name__)

API_URL = "https://api.mymemory.translated.net/get"
MODEL_LABEL = "mymemory"                 # stored in NewsArticle.ai_model
TARGET = "it"
DAILY_CHARS_ANONYMOUS = 4500             # the service's limit is 5,000 characters a day
DAILY_CHARS_WITH_EMAIL = 45000           # ... and 50,000 with a contact e-mail
MAX_REQUESTS_PER_RUN = 60
SECONDS_BETWEEN_REQUESTS = 1.2
MAX_TITLE_CHARS = 400                    # the service accepts 500 bytes per request
STATE_KEY = "title_translation:state"
FAILED_KEEP = 800                        # ids not asked again (rejected answers), newest kept
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Language codes the service wants written differently from ours.
_SERVICE_CODE = {"zh": "zh-CN", "no": "nb", "sh": "sr"}

_run_lock = threading.Lock()


def is_machine(model: str | None) -> bool:
    """True when a stored translation came from this module (not from an AI provider)."""
    return (model or "").startswith(MODEL_LABEL)


def enabled(settings=None) -> bool:
    s = settings or get_settings()
    return bool(s.title_translation) and not s.llm_enabled()


# ---------------------------------------------------------------------------
# One headline
# ---------------------------------------------------------------------------


class QuotaReached(Exception):
    """The service says today's free allowance is used up."""


def pick_translation(payload: dict) -> str | None:
    """The machine translation of the exact headline from a MyMemory answer, or None.
    Raises QuotaReached when the answer is the service's "allowance used up" notice."""
    data = payload.get("responseData") or {}
    top = str(data.get("translatedText") or "")
    status = str(payload.get("responseStatus") or "")
    if payload.get("quotaFinished") or status == "429" or "MYMEMORY WARNING" in top.upper():
        raise QuotaReached(top[:160])
    if status != "200":
        return None
    for m in payload.get("matches") or []:
        if not isinstance(m, dict):
            continue
        exact_memory = float(m.get("match") or 0) >= 0.999
        if str(m.get("created-by") or "") == "MT!" or exact_memory:
            text = html.unescape(str(m.get("translation") or "")).strip()
            if text:
                return text
    return None


def acceptable(original: str, translated: str | None) -> bool:
    if not translated:
        return False
    t = translated.strip()
    if not t or t.casefold() == original.strip().casefold():
        return False                      # nothing was translated
    if len(t) > 3 * len(original) + 40 or "MYMEMORY" in t.upper():
        return False
    return _numbers_ok(t, original)


def translate_title(title: str, language: str, *, client: httpx.Client, email: str | None = None) -> str | None:
    """Italian machine translation of `title`, or None when the answer is not usable.
    Raises QuotaReached, or httpx errors on network failure."""
    src = _SERVICE_CODE.get(language, language)
    params = {"q": title[:MAX_TITLE_CHARS], "langpair": f"{src}|{TARGET}"}
    if email:
        params["de"] = email
    resp = client.get(API_URL, params=params)
    if resp.status_code == 429:
        raise QuotaReached("HTTP 429")
    resp.raise_for_status()
    text = pick_translation(resp.json())
    return text[:600] if acceptable(title, text) else None


# ---------------------------------------------------------------------------
# The pass after each collection
# ---------------------------------------------------------------------------


def _state(session: Session) -> dict:
    row = session.get(AppSetting, STATE_KEY)
    state = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    if state.get("day") != date.today().isoformat():
        state = {"day": date.today().isoformat(), "chars": 0, "quota_reached": False,
                 "failed": list(state.get("failed") or [])}
    state.setdefault("failed", [])
    return state


def _save(session: Session, state: dict) -> None:
    state["failed"] = list(state.get("failed") or [])[-FAILED_KEEP:]
    row = session.get(AppSetting, STATE_KEY)
    if row is None:
        session.add(AppSetting(key=STATE_KEY, value=dict(state)))
    else:
        row.value = dict(state)          # a new object, so SQLAlchemy sees the JSON change
    session.flush()


def candidates(session: Session, limit: int, skip: set[int]) -> list[NewsArticle]:
    """Articles that need an Italian headline, most useful first (see the module docstring)."""
    N = NewsArticle
    when = func.coalesce(N.published_at, N.collected_at)
    group = case((N.language.not_in(READABLE_LANGUAGES), 0), (N.language != "en", 1), else_=2)
    q = (select(N)
         .where(N.title_it.is_(None), N.duplicate_of_id.is_(None), N.is_demo.is_(False),
                N.language.is_not(None), N.language != TARGET)
         .order_by(group, case((N.relevance_score >= MIN_RELEVANCE, 0), else_=1), when.desc(), N.id.desc())
         .limit(limit + len(skip)))
    return [a for a in session.scalars(q) if a.id not in skip][:limit]


def translate_pending(session: Session, *, max_requests: int = MAX_REQUESTS_PER_RUN,
                      client: httpx.Client | None = None, pause: float = SECONDS_BETWEEN_REQUESTS) -> dict:
    """Translate headlines until the run's or the day's allowance is used. Returns stats:
    {"enabled", "translated", "rejected", "chars", "quota_reached"} (+ "skipped" when not run)."""
    settings = get_settings()
    stats = {"enabled": enabled(settings), "translated": 0, "rejected": 0, "chars": 0, "quota_reached": False}
    if not stats["enabled"]:
        return stats
    if not _run_lock.acquire(blocking=False):
        stats["skipped"] = "already_running"
        return stats
    own_client = client is None
    try:
        state = _state(session)
        email = (settings.title_translation_email or "").strip() or None
        budget = DAILY_CHARS_WITH_EMAIL if email else DAILY_CHARS_ANONYMOUS
        if state.get("quota_reached"):
            stats["quota_reached"] = True
            return stats
        if own_client:
            client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": settings.user_agent})
        todo = candidates(session, max_requests, set(state["failed"]))
        for i, a in enumerate(todo):
            cost = min(len(a.title), MAX_TITLE_CHARS)
            if state["chars"] + cost > budget:
                break
            if i and pause:
                session.commit()                       # never wait with an open write transaction
                time.sleep(pause)
            try:
                text = translate_title(a.title, a.language, client=client, email=email)
            except QuotaReached as exc:
                log.info("title translation: the service's daily allowance is used up (%s)", exc)
                state["quota_reached"] = stats["quota_reached"] = True
                break
            except (httpx.HTTPError, ValueError) as exc:
                log.info("title translation stopped: %s: %s", type(exc).__name__, str(exc)[:160])
                break                                   # network trouble: try again at the next run
            state["chars"] += cost
            stats["chars"] += cost
            if text is None:
                state["failed"].append(a.id)
                stats["rejected"] += 1
                continue
            a.title_it = text
            if not a.ai_model:
                a.ai_model = MODEL_LABEL
            stats["translated"] += 1
        _save(session, state)
        session.commit()
        return stats
    finally:
        if own_client and client is not None:
            client.close()
        _run_lock.release()
