"""News API: honey-market news from RSS/Atom feeds, with tags, relevance, duplicates and
(optional, always labelled) AI translations/summaries.

Endpoints (prefix /api):
    GET  /news                     list + facets (see `list_news`)
    GET  /news/topics              topic keys with IT/EN labels
    GET  /news/{id}                one article with all its duplicates
    POST /news/{id}/translate      on-demand AI translation (409 when no AI configured)
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import NewsArticle, Source, utcnow
from ..reference.countries import country_name
from ..services import news as news_service
from .common import demo_clause, iso, show_demo, source_brief

router = APIRouter(tags=["news"])

MAX_PAGE_SIZE = 100
MAX_PAGE = 100_000            # far beyond any real list; a larger number overflowed SQLite's integer (HTTP 500)

TOP_CANDIDATES = 2000         # sort=top ranks at most this many articles (the highest-scored of the period)
_CODE = re.compile(r"^[A-Z0-9_]{2,8}$")
_LANG = re.compile(r"^[a-z]{2,3}$")


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _like_term(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _json_has_any(column, values: list[str]):
    """JSON list column contains any of `values` (validated codes, so LIKE is safe)."""
    text = cast(column, String)
    return or_(*[text.like(f'%"{v}"%') for v in values])


def _when():
    return func.coalesce(NewsArticle.published_at, NewsArticle.collected_at)


class Filters:
    """Parsed and validated query parameters."""

    def __init__(self, db: Session, q, country, topic, source, from_, to, lang, min_relevance, include_duplicates):
        self.q_terms = [t for t in re.split(r"\s+", (q or "").strip()) if len(t) >= 2][:8]
        self.countries = [c.upper() for c in _split(country)]
        bad = [c for c in self.countries if not _CODE.match(c)]
        if bad:
            raise HTTPException(400, f"Codice paese non valido / invalid country code: {', '.join(bad)}")
        self.topics = _split(topic)
        bad = [t for t in self.topics if t not in news_service.TOPICS]
        if bad:
            raise HTTPException(400, f"Tema sconosciuto / unknown topic: {', '.join(bad)}")
        self.source_keys = _split(source)
        self.langs = [lng.lower() for lng in _split(lang)]
        bad = [lng for lng in self.langs if not _LANG.match(lng)]
        if bad:
            raise HTTPException(400, f"Lingua non valida / invalid language: {', '.join(bad)}")
        self.from_ = from_
        self.to = to
        self.min_relevance = min_relevance
        self.include_duplicates = include_duplicates
        self.source_ids: list[int] = []
        if self.source_keys:
            self.source_ids = list(db.scalars(select(Source.id).where(Source.key.in_(self.source_keys))))
        self.db = db

    def base(self) -> list:
        """Conditions shared by the list and every facet."""
        N = NewsArticle
        conds = [demo_clause(N, self.db)]
        if not self.include_duplicates:
            conds.append(N.duplicate_of_id.is_(None))
        if self.min_relevance:
            conds.append(N.relevance_score >= self.min_relevance)
        if self.from_:
            conds.append(_when() >= datetime.combine(self.from_, time.min))
        if self.to:
            conds.append(_when() < datetime.combine(self.to + timedelta(days=1), time.min))
        for term in self.q_terms:
            pattern = _like_term(term)
            conds.append(or_(*[
                col.ilike(pattern, escape="\\")
                for col in (N.title, N.snippet, N.title_it, N.title_en, N.summary_it, N.summary_en, N.publisher)
            ]))
        return conds

    def dimension(self, name: str):
        N = NewsArticle
        if name == "countries" and self.countries:
            return _json_has_any(N.countries, self.countries)
        if name == "topics" and self.topics:
            return _json_has_any(N.topics, self.topics)
        if name == "sources" and self.source_keys:
            return N.source_id.in_(self.source_ids or [-1])
        if name == "languages" and self.langs:
            return N.language.in_(self.langs)
        return None

    def all(self) -> list:
        conds = self.base()
        for dim in ("countries", "topics", "sources", "languages"):
            c = self.dimension(dim)
            if c is not None:
                conds.append(c)
        return conds

    def echo(self) -> dict:
        return {
            "q": " ".join(self.q_terms) or None, "country": self.countries, "topic": self.topics,
            "source": self.source_keys, "from": iso(self.from_), "to": iso(self.to), "lang": self.langs,
            "min_relevance": self.min_relevance, "include_duplicates": self.include_duplicates,
        }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _display(a: NewsArticle, lang: str) -> dict:
    """What to show in UI language `lang`, with AI flags (the frontend never has to guess)."""
    same_lang = bool(a.language) and a.language[:2] == lang
    ai_title = a.title_it if lang == "it" else a.title_en
    if same_lang or not ai_title:
        title, title_is_ai = a.title, False
    else:
        title, title_is_ai = ai_title, ai_title.strip() != a.title.strip()
    summary = a.summary_it if lang == "it" else a.summary_en
    return {
        "title": title,
        "title_is_ai": title_is_ai,
        "needs_translation": not same_lang and not ai_title,
        "summary": summary,
        "summary_is_ai": bool(summary),
        "excerpt": a.snippet,           # publisher's own text ("Estratto della fonte"), original language
    }


def _outlet(d: NewsArticle, sources: dict[int, Source]) -> dict:
    s = sources.get(d.source_id)
    return {
        "id": d.id, "publisher": d.publisher or (s.publisher if s else None), "url": d.url,
        "published_at": iso(d.published_at), "collected_at": iso(d.collected_at),
        "language": d.language, "source_key": s.key if s else None, "source_name": s.name if s else None,
        "source_name_en": s.name_en if s else None,
    }


def serialize_article(a: NewsArticle, sources: dict[int, Source], duplicates: list[NewsArticle] | None = None,
                      original: NewsArticle | None = None) -> dict:
    src = sources.get(a.source_id)
    outlets: list[dict] = []
    seen_pub: set[str] = set()
    for d in duplicates or []:
        o = _outlet(d, sources)
        key = (o["publisher"] or o["url"] or "").strip().lower()
        if key in seen_pub:
            continue
        seen_pub.add(key)
        outlets.append(o)
    return {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "source_url": a.url,
        "canonical_url": a.canonical_url,
        "publisher": a.publisher or (src.publisher if src else None),
        "language": a.language,
        "published_at": iso(a.published_at),
        "collected_at": iso(a.collected_at),
        "image_url": a.image_url,
        "snippet": a.snippet,
        "countries": a.countries or [],
        "topics": a.topics or [],
        "relevance_score": a.relevance_score,
        "relevance_level": news_service.relevance_level(a.relevance_score),
        "relevance_reason": a.relevance_reason,
        "relevance_reason_it": news_service.explain_reason(a.relevance_reason, "it"),
        "relevance_reason_en": news_service.explain_reason(a.relevance_reason, "en"),
        "title_it": a.title_it,
        "title_en": a.title_en,
        "summary_it": a.summary_it,
        "summary_en": a.summary_en,
        "summary_is_ai": bool(a.summary_it or a.summary_en),
        "ai_model": a.ai_model,
        "ai_processed_at": iso(a.ai_processed_at),
        "display": {"it": _display(a, "it"), "en": _display(a, "en")},
        "duplicate_of_id": a.duplicate_of_id,
        "duplicate_of": (
            {"id": original.id, "title": original.title,
             "publisher": original.publisher or (sources[original.source_id].publisher
                                                  if original.source_id in sources else None),
             "url": original.url, "published_at": iso(original.published_at)}
            if original is not None else None
        ),
        "duplicate_count": a.duplicate_count or 0,
        "duplicate_outlets": outlets,
        "source": source_brief(src),
        "reliability": src.reliability if src else None,
        "data_status": "published",
        "is_demo": a.is_demo,
    }


def _sources(db: Session) -> dict[int, Source]:
    return {s.id: s for s in db.scalars(select(Source))}


def _duplicates_of(db: Session, ids: list[int]) -> dict[int, list[NewsArticle]]:
    out: dict[int, list[NewsArticle]] = {}
    if not ids:
        return out
    rows = db.scalars(
        select(NewsArticle).where(NewsArticle.duplicate_of_id.in_(ids), demo_clause(NewsArticle, db))
        .order_by(_when().asc(), NewsArticle.id.asc())
    )
    for d in rows:
        out.setdefault(d.duplicate_of_id, []).append(d)
    return out


def _facets(db: Session, f: Filters, sources: dict[int, Source]) -> dict:
    N = NewsArticle
    rows = db.execute(select(N.countries, N.topics, N.source_id, N.language).where(*f.base())).all()
    want_c, want_t, want_s, want_l = set(f.countries), set(f.topics), set(f.source_ids), set(f.langs)

    def ok(row, skip: str) -> bool:
        countries, topics, sid, lang = row
        if skip != "countries" and want_c and not (want_c & set(countries or [])):
            return False
        if skip != "topics" and want_t and not (want_t & set(topics or [])):
            return False
        if skip != "sources" and f.source_keys and sid not in want_s:
            return False
        if skip != "languages" and want_l and lang not in want_l:
            return False
        return True

    c_count: dict[str, int] = {}
    t_count: dict[str, int] = {}
    s_count: dict[int, int] = {}
    l_count: dict[str, int] = {}
    for row in rows:
        if ok(row, "countries"):
            for c in set(row[0] or []):
                c_count[c] = c_count.get(c, 0) + 1
        if ok(row, "topics"):
            for t in set(row[1] or []):
                t_count[t] = t_count.get(t, 0) + 1
        if ok(row, "sources"):
            s_count[row[2]] = s_count.get(row[2], 0) + 1
        if ok(row, "languages") and row[3]:
            l_count[row[3]] = l_count.get(row[3], 0) + 1
    return {
        "countries": [
            {"key": k, "count": n, "name_it": country_name(k, "it"), "name_en": country_name(k, "en"),
             "origin_of_interest": k in news_service.ORIGINS_OF_INTEREST}
            for k, n in sorted(c_count.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "topics": [{"key": k, "it": v["it"], "en": v["en"], "count": t_count.get(k, 0)}
                   for k, v in news_service.TOPICS.items()],
        "sources": [
            {"key": sources[sid].key, "name": sources[sid].name, "name_en": sources[sid].name_en,
             "publisher": sources[sid].publisher,
             "reliability": sources[sid].reliability, "count": n}
            for sid, n in sorted(s_count.items(), key=lambda kv: (-kv[1], sources[kv[0]].name if kv[0] in sources else ""))
            if sid in sources
        ],
        "languages": [{"key": k, "count": n} for k, n in sorted(l_count.items(), key=lambda kv: (-kv[1], kv[0]))],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/news/topics")
def news_topics():
    return {
        "topics": news_service.topic_list(),
        "relevance_levels": {"high": 60, "medium": 35},
    }


@router.get("/news")
def list_news(
    q: str | None = Query(None, description="Full-text search (all words must appear): titles, excerpts, "
                                            "AI summaries, publisher"),
    country: str | None = Query(None, description="ISO3, comma-separated (any)"),
    topic: str | None = Query(None, description="topic keys, comma-separated (any)"),
    source: str | None = Query(None, description="source keys, comma-separated (any)"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    lang: str | None = Query(None, description="article language(s), e.g. 'it' or 'en,it'"),
    min_relevance: int = Query(0, ge=0, le=100),
    include_duplicates: bool = Query(False),
    sort: str = Query("date", pattern="^(date|relevance|top)$",
                      description="date (newest first), relevance (score), or top: the most important of the "
                                  "period — score, plus a little for each further outlet that carried the "
                                  "story, minus a little for each day of age"),
    days: int | None = Query(None, ge=1, le=366, description="only the last N days (counted by the server, so "
                                                             "the request does not change from day to day)"),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    f = Filters(db, q, country, topic, source, from_, to, lang, min_relevance, include_duplicates)
    N = NewsArticle
    now = utcnow()
    conds = f.all()
    if days:
        conds.append(_when() >= now - timedelta(days=days))
    total = db.scalar(select(func.count()).select_from(N).where(*conds)) or 0
    if sort == "top":
        # ranked in Python: the candidates are one period's relevant articles (hundreds at most)
        ranked = db.execute(select(N.id, N.relevance_score, N.duplicate_count, _when(), N.title_norm).where(*conds)
                            .order_by(N.relevance_score.desc(), _when().desc(), N.id.desc()).limit(TOP_CANDIDATES)).all()
        ranked.sort(key=lambda r: (-news_service.importance(r[1], r[2], r[3], now), -r[0]))
        # one line per story: a second outlet's differently worded article on the same story is
        # passed over (it stays in the full list and in `total`)
        distinct: list = []
        for r in ranked:
            if len(distinct) >= page * page_size:
                break
            if not any(news_service.same_story(r[4] or "", r[3], d[4] or "", d[3]) for d in distinct):
                distinct.append(r)
        ids = [r[0] for r in distinct[(page - 1) * page_size: page * page_size]]
        by_id = {a.id: a for a in db.scalars(select(N).where(N.id.in_(ids)))} if ids else {}
        rows = [by_id[i] for i in ids if i in by_id]
    else:
        order = ([N.relevance_score.desc(), _when().desc(), N.id.desc()] if sort == "relevance"
                 else [_when().desc(), N.id.desc()])
        rows = list(db.scalars(select(N).where(*conds).order_by(*order)
                               .offset((page - 1) * page_size).limit(page_size)))
    sources = _sources(db)
    dups = _duplicates_of(db, [a.id for a in rows if a.duplicate_of_id is None and a.duplicate_count])
    originals = {}
    orig_ids = [a.duplicate_of_id for a in rows if a.duplicate_of_id]
    if orig_ids:
        originals = {o.id: o for o in db.scalars(select(N).where(N.id.in_(orig_ids)))}
    items = [serialize_article(a, sources, dups.get(a.id), originals.get(a.duplicate_of_id)) for a in rows]

    news_sources = [s for s in sources.values() if s.category == "news"]
    last_checked = max((s.last_run_at for s in news_sources if s.last_run_at), default=None)
    last_collected = db.scalar(select(func.max(N.collected_at)).where(demo_clause(N, db)))
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "sort": sort,
        "days": days,
        "filters": f.echo(),
        "facets": _facets(db, f, sources),
        "llm_enabled": get_settings().llm_enabled(),
        "updated": {
            "last_checked_at": iso(last_checked),
            "last_collected_at": iso(last_collected),
            "sources_total": len(news_sources),
            "sources_enabled": sum(1 for s in news_sources if s.enabled),
        },
    }


def _get_article(db: Session, article_id: int) -> NewsArticle:
    a = db.get(NewsArticle, article_id)
    if a is None or (a.is_demo and not show_demo(db)):
        raise HTTPException(404, "Notizia non trovata / article not found")
    return a


def _detail(db: Session, a: NewsArticle) -> dict:
    sources = _sources(db)
    root_id = a.duplicate_of_id or a.id
    dups = _duplicates_of(db, [root_id]).get(root_id, [])
    original = db.get(NewsArticle, a.duplicate_of_id) if a.duplicate_of_id else None
    item = serialize_article(a, sources, dups if a.duplicate_of_id is None else None, original)
    # every outlet that carried the story (original first), for the detail view
    story = ([original] if original is not None else [a]) + dups
    item["duplicates"] = [_outlet(d, sources) | {"title": d.title, "is_this": d.id == a.id} for d in story]
    item["llm_enabled"] = get_settings().llm_enabled()
    return item


@router.get("/news/{article_id}")
def get_news(article_id: int, db: Session = Depends(get_db)):
    return _detail(db, _get_article(db, article_id))


@router.post("/news/{article_id}/translate")
def translate_news(article_id: int, lang: str = Query(..., pattern="^(it|en)$"), force: bool = False,
                   db: Session = Depends(get_db)):
    from ..services import ai_enrich, llm

    a = _get_article(db, article_id)
    if not get_settings().llm_enabled():
        raise HTTPException(
            409,
            "Traduzione automatica non disponibile: nessun servizio di IA configurato "
            "(impostare PALADEX_LLM_PROVIDER e la relativa chiave API). / "
            "Automatic translation unavailable: no AI provider configured.",
        )
    try:
        ai_enrich.translate_article(db, a.id, lang, force=force)
    except llm.LLMUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    except llm.LLMError as exc:
        raise HTTPException(502, f"Servizio di IA non disponibile al momento / AI service error: {exc}") from None
    db.refresh(a)
    return _detail(db, a)
