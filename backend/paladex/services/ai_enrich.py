"""AI enrichment of news: Italian/English headline translations and 2-3 sentence summaries.

Rules (see docs/DEVELOPING.md, "AI output is labelled"):
* the model only sees the headline and the publisher's own excerpt - never the full
  article, which we do not fetch - and is told not to add any fact;
* a summary or translated headline that contains a number not present in the headline /
  excerpt is rejected (cheap guard against invented figures);
* AI fields are stored in dedicated columns (`summary_*`, `title_*`, `ai_model`,
  `ai_processed_at`) and the UI always labels them as AI; the source's own excerpt
  (`snippet`) is never modified;
* with no provider configured nothing happens: the UI shows the excerpt labelled
  "Estratto della fonte".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import NewsArticle, utcnow
from . import llm

log = logging.getLogger(__name__)

BATCH_SIZE = 6
RECENT_DAYS = 10
MIN_RELEVANCE = 35          # "medium" and above (see services.news.relevance_level)
MAX_CONSECUTIVE_FAILURES = 2
SUMMARY_MAX_CHARS = 700

SYSTEM_PROMPT = """You assist the owner of Parodi Group, an Italian/US importer of bulk honey, who skims honey-market news every morning.
For each article you receive ONLY its headline and, when available, the publisher's own short excerpt. You do not see the article.

Strict rules:
1. Use ONLY information written in the headline and excerpt. Never add facts, figures, names, dates, causes, consequences or context that are not written there, even if you believe them to be true. Do not speculate.
2. summary_it (Italian) and summary_en (English): 2-3 short, neutral, factual sentences (max 60 words each).
   If the excerpt is missing or adds nothing to the headline, write ONE sentence restating the headline and then add exactly:
   Italian: "Informazioni limitate: la fonte fornisce solo il titolo."  English: "Limited information: the source provides only the headline."
3. title_it and title_en: faithful translations of the headline (if the headline is already in that language, return it unchanged). No added words, no clickbait.
4. Keep numbers, units, currencies, percentages and proper names exactly as written (you may translate the words around them).
5. Return one entry per input article, using the same "id"."""

SCHEMA_BATCH = {"articles": [{"id": 0, "title_it": "...", "title_en": "...", "summary_it": "...", "summary_en": "..."}]}

_LANG_FIELDS = {"it": ("title_it", "summary_it"), "en": ("title_en", "summary_en")}
_NUM = re.compile(r"\d[\d.,'   ]*\d|\d")


def _numbers(text: str | None) -> set[str]:
    """Digit strings in `text`, separators removed ('1.200,50' -> '120050')."""
    out = set()
    for m in _NUM.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if digits:
            out.add(digits.lstrip("0") or "0")
    return out


def _numbers_ok(output: str | None, source_text: str) -> bool:
    if not output:
        return True
    allowed = _numbers(source_text)
    for n in _numbers(output):
        if n in allowed:
            continue
        # tolerate a number split differently ("20 %" vs "20%", "3,000" vs "3000") by substring check
        if any(n in a for a in allowed):
            continue
        return False
    return True


def _clean(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    v = re.sub(r"\s+", " ", value).strip()
    return v[:limit] if v else None


def _payload(a: NewsArticle) -> dict:
    return {
        "id": a.id,
        "language": a.language,
        "publisher": a.publisher,
        "headline": a.title,
        "excerpt": a.snippet or None,
    }


def _apply(a: NewsArticle, data: dict, fields: tuple[str, ...]) -> bool:
    """Validate and store the AI fields for one article. Returns True if anything stored."""
    source_text = f"{a.title}\n{a.snippet or ''}"
    stored = False
    for f in fields:
        limit = 600 if f.startswith("title") else SUMMARY_MAX_CHARS
        value = _clean(data.get(f), limit)
        if value is None:
            continue
        if not _numbers_ok(value, source_text):
            log.warning("AI %s for news %s rejected: contains numbers not in the source", f, a.id)
            continue
        setattr(a, f, value)
        stored = True
    return stored


def _candidates(session: Session, limit: int) -> list[NewsArticle]:
    since = utcnow() - timedelta(days=RECENT_DAYS)
    when = func.coalesce(NewsArticle.published_at, NewsArticle.collected_at)
    return list(session.scalars(
        select(NewsArticle)
        .where(
            NewsArticle.ai_processed_at.is_(None),
            NewsArticle.duplicate_of_id.is_(None),
            NewsArticle.is_demo.is_(False),
            NewsArticle.relevance_score >= MIN_RELEVANCE,
            NewsArticle.collected_at >= since,
        )
        .order_by(NewsArticle.relevance_score.desc(), when.desc())
        .limit(limit)
    ))


def enrich_news(session: Session, limit: int | None = None, *, batch_size: int = BATCH_SIZE) -> dict:
    """Translate + summarise recent relevant articles that have no AI fields yet.

    Returns stats: {"enabled", "candidates", "processed", "rejected_fields", "errors"}.
    """
    settings = get_settings()
    stats = {"enabled": settings.llm_enabled(), "candidates": 0, "processed": 0, "errors": 0}
    if not stats["enabled"]:
        return stats
    limit = settings.llm_max_articles_per_run if limit is None else limit
    articles = _candidates(session, limit)
    stats["candidates"] = len(articles)
    if not articles:
        return stats
    info = llm.provider_info(settings)
    failures = 0
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        user = ("Articles (JSON):\n" + json.dumps([_payload(a) for a in batch], ensure_ascii=False, indent=1))
        try:
            result = llm.complete_json(SYSTEM_PROMPT, user, SCHEMA_BATCH,
                                       max_tokens=min(4000, 450 * len(batch) + 200), settings=settings)
        except llm.LLMUnavailable:
            break
        except llm.LLMError as exc:
            stats["errors"] += 1
            failures += 1
            log.warning("AI enrichment batch failed: %s", exc)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                break
            continue
        failures = 0
        rows = result.get("articles") or result.get("items") or []
        by_id = {}
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                try:
                    by_id[int(r.get("id"))] = r
                except (TypeError, ValueError):
                    continue
        now = utcnow()
        for a in batch:
            data = by_id.get(a.id)
            if data is None:
                continue  # left for the next run
            _apply(a, data, ("title_it", "title_en", "summary_it", "summary_en"))
            a.ai_model = info.label
            a.ai_processed_at = now
            stats["processed"] += 1
        session.commit()
    return stats


def translate_article(session: Session, article_id: int, lang: str, *, force: bool = False) -> NewsArticle:
    """On-demand translation (headline + short summary) of one article into `lang` ('it'|'en').

    Raises LookupError (unknown id), ValueError (bad lang), llm.LLMUnavailable, llm.LLMError.
    """
    if lang not in _LANG_FIELDS:
        raise ValueError("lang must be 'it' or 'en'")
    article = session.get(NewsArticle, article_id)
    if article is None:
        raise LookupError(article_id)
    title_f, summary_f = _LANG_FIELDS[lang]
    if not force and getattr(article, title_f) and getattr(article, summary_f):
        return article
    info = llm.provider_info()
    target = "Italian" if lang == "it" else "English"
    schema = {"articles": [{"id": 0, title_f: "...", summary_f: "..."}]}
    user = (f"Translate into {target} only ({title_f}, {summary_f}).\nArticles (JSON):\n"
            + json.dumps([_payload(article)], ensure_ascii=False, indent=1))
    result = llm.complete_json(SYSTEM_PROMPT, user, schema, max_tokens=700)
    rows = result.get("articles") or result.get("items") or []
    data = next((r for r in rows if isinstance(r, dict) and str(r.get("id")) == str(article.id)), None)
    if data is None and len(rows) == 1 and isinstance(rows[0], dict):
        data = rows[0]
    if data is None or not _apply(article, data, (title_f, summary_f)):
        raise llm.LLMError("Il modello non ha restituito una traduzione utilizzabile")
    article.ai_model = info.label
    article.ai_processed_at = article.ai_processed_at or utcnow()
    session.commit()
    return article
