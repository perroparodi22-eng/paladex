"""Daily AI briefing (Milestone 6): a two-minute morning read, written by the AI from the day's facts.

`generate_daily(session)` runs at 07:00 (scheduler.py) and on demand (POST
/api/assistant/briefing/regenerate). For each language:

1. **Facts** (`build_facts`): the same rule-based selection as the overview's daily summary
   (api/overview.py: relevant news of the last days, official reports of the last two weeks,
   monthly price moves, trade changes among the main flows), each turned into a numbered context
   block with its provenance (the news and reports with their own excerpt / commentary), plus
   regulation items and duty changes of the last week and newly published production figures.
2. **Writing**: with an AI provider, the model writes the briefing in seven sections (important
   news, new official reports, relevant price changes, trade developments, production and harvest,
   regulatory updates, implications for Parodi Group), every point citing its blocks.
3. **Post-check** (`services.assistant.check_sentences`): citations must exist and every number
   must appear in the cited blocks; a briefing with too many failing points is not stored.
4. **Storage**: one `Briefing` row per date and language, in the format api/overview.py reads
   (`content["bullets"]`, see its docstring), so the overview shows it in place of the rule-based
   summary, badged as AI. The implications are labelled as AI analysis in their own text.

Without an AI provider nothing happens: the overview keeps its rule-based summary (labelled "not AI").
The facts sent to the provider are public-source data only (never supplier offers).
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import overview as ov
from ..api.common import iso
from ..models import Briefing, NewsArticle, Report
from . import assistant, llm
from .assistant import (
    COMPANY_BASIS,
    Fact,
    Retriever,
    check_sentences,
    context_payload,
    fact_status,
    parse_ai_sections,
)

log = logging.getLogger(__name__)

LANGS = ("it", "en")
MAX_FACTS = 30
CHANGE_DAYS = 7               # regulation items and duty changes of the last week
PRODUCTION_NEW_DAYS = 30      # production figures published in the last month
MAX_DROPPED_SHARE = 0.4

# key, Italian title, English title, bullet kind for the overview's icon
SECTIONS = (
    ("news", "Notizie importanti", "Important news", "news"),
    ("reports", "Nuovi report ufficiali", "New official reports", "report"),
    ("prices", "Variazioni di prezzo rilevanti", "Relevant price changes", "price"),
    ("trade", "Sviluppi del commercio", "Trade developments", "trade"),
    ("production", "Produzione e raccolti", "Production and harvest", "production"),
    ("regulation", "Aggiornamenti normativi", "Regulatory updates", "regulation"),
    ("implications", "Implicazioni per Parodi Group (analisi IA)", "Implications for Parodi Group (AI analysis)", "text"),
)
SECTION_KEYS = tuple(s[0] for s in SECTIONS)
ANALYSIS_LABEL = {"it": "Analisi IA", "en": "AI analysis"}
ANALYSIS_PUBLISHER = {"it": "Analisi IA sui dati citati", "en": "AI analysis of the cited data"}

_run_lock = threading.Lock()

SYSTEM_PROMPT = {
    "it": """Sei l'analista di mercato di un importatore italiano e statunitense di miele sfuso (container da 20 t, fusti da 300 kg). Scrivi in italiano il briefing del mattino per il titolare: una lettura di due minuti.

Usa ESCLUSIVAMENTE i blocchi del CONTESTO (dati del database locale). Regole obbligatorie:
1. Nessun fatto, numero, data, nome, causa o conseguenza che non sia scritto nel contesto. Nessuna conoscenza esterna.
2. Ogni punto è una frase breve (al massimo due) e indica in "refs" gli id dei blocchi da cui proviene; usa solo id presenti nel contesto. Copia i numeri esattamente come sono scritti; non calcolare nuove percentuali, differenze o medie.
3. Non mescolare tipi di prezzo (all'ingrosso, al produttore, valori unitari doganali, dettaglio): indica sempre tipo, mercato e periodo. Indica il periodo dei dati; le notizie vanno attribuite alla testata.
4. Sezioni, nell'ordine (ometti quelle senza fatti nel contesto): "news" notizie importanti; "reports" nuovi report ufficiali; "prices" variazioni di prezzo rilevanti; "trade" sviluppi del commercio; "production" produzione e raccolti; "regulation" aggiornamenti normativi; "implications" implicazioni per l'azienda: 1-3 punti di analisi per un importatore di miele sfuso, basati solo sui fatti citati (indica i loro id in "refs"), senza numeri nuovi e con prudenza.
5. Scegli solo ciò che conta per un importatore di miele sfuso; al massimo 250 parole in totale.""",
    "en": """You are the market analyst of an Italian and US importer of bulk honey (20 t containers, 300 kg drums). Write the owner's morning briefing in English: a two-minute read.

Use ONLY the blocks of the CONTEXT (data from the local database). Mandatory rules:
1. No fact, number, date, name, cause or consequence that is not written in the context. No outside knowledge.
2. Each point is one short sentence (two at most) and lists in "refs" the ids of the blocks it comes from; use only ids present in the context. Copy numbers exactly as written; do not compute new percentages, differences or averages.
3. Never mix price types (wholesale, producer, customs unit values, retail): always state type, market and period. State the period of the data; attribute news to the outlet.
4. Sections, in this order (omit those with no facts in the context): "news" important news; "reports" new official reports; "prices" relevant price changes; "trade" trade developments; "production" production and harvest; "regulation" regulatory updates; "implications" implications for the company: 1-3 points of analysis for a bulk honey importer, based only on the cited facts (list their ids in "refs"), with no new numbers and with caution.
5. Keep only what matters to a bulk honey importer; at most 250 words in total.""",
}

SCHEMA = {"sections": [{"key": "news | reports | prices | trade | production | regulation | implications",
                        "bullets": [{"text": "one short sentence", "refs": [1]}]}]}


def _bullet_fact(r: Retriever, b: dict, kind: str) -> Fact:
    """An overview bullet (price move, trade change) as a context block, keeping its provenance."""
    src = b.get("source") or {}
    return Fact(kind=kind, title=b["text"][:160], text=b["text"],
                status=fact_status(b.get("data_status"), src.get("reliability"), None, r.today),
                source=b.get("source"), url=b.get("url"), link=b.get("link"), published_at=b.get("date"),
                period_label=b.get("period_label"), data_status=b.get("data_status"), reliability=src.get("reliability"),
                is_demo=bool(b.get("is_demo")), price_type=b.get("price_type"), country=b.get("origin_iso3"),
                key=f"bullet:{kind}:{b['text']}", meta={"change_pct": b.get("change_pct")})


def _series_of(ctx: ov.Ctx, b: dict) -> ov.PriceSeries | None:
    """The price series an overview price bullet was written from (same origin, type, latest period
    and m/m change; its link names the variety)."""
    for s in ctx.price_series():
        if (s.origin_iso3 == b.get("origin_iso3") and s.price_type == b.get("price_type")
                and s.latest.period_label == b.get("period_label") and f"variety={s.variety}" in (b.get("link") or "")
                and s.latest.source_url == b.get("url")):
            mom = ov.series_changes(s)["mom_pct"]
            if mom is not None and b.get("change_pct") is not None and abs(mom - b["change_pct"]) < 1e-9:
                return s
    return None


def build_facts(session: Session, lang: str, today: date | None = None) -> Retriever:
    """The day's facts: the overview's rule-based briefing selection + regulation, duty and
    production updates. Each section's blocks are tagged with `meta["section"]`."""
    r = Retriever(session, lang, today, limit=MAX_FACTS)
    ctx = r.octx

    def tag(section: str, start: int) -> None:
        for f in r.facts.items[start:]:
            f.meta.setdefault("section", section)

    # 1. news and reports picked by the overview's rules, as rich blocks (excerpt, commentary)
    start = len(r.facts)
    urls = [b["url"] for b in ov._briefing_news(ctx) if b.get("url")]
    if urls:
        rows = {a.url: a for a in session.scalars(select(NewsArticle).where(NewsArticle.url.in_(urls)))}
        for u in urls:
            if u in rows:
                r.add(r.news_fact(rows[u]))
    tag("news", start)
    start = len(r.facts)
    for b in ov._briefing_reports(ctx):
        # the bullet is "Nuovo report ufficiale: «<title>»." for one Report row (a source may reuse its URL)
        cands = session.scalars(select(Report).where(Report.url == b["url"])).all() if b.get("url") else []
        rep = next((x for x in cands if x.title and x.title in b["text"]), None)
        if rep is not None:
            r.add(r.report_fact(rep))
            if rep.narrative:
                r.add(r.report_text_fact(rep))
        else:
            r.add(_bullet_fact(r, b, "report"))
    tag("reports", start)
    # 2. price moves picked by the overview's rule, as full series blocks (market, terms, both changes)
    start = len(r.facts)
    for b in ov._briefing_prices(ctx):
        s = _series_of(ctx, b)
        r.add(r.price_fact(s) if s is not None else _bullet_fact(r, b, "price"))
    tag("prices", start)
    # 3. trade changes: the overview's own bullets
    start = len(r.facts)
    for b in ov._briefing_trade(ctx):
        r.add(_bullet_fact(r, b, "trade"))
    tag("trade", start)
    # 4. beyond the overview's rules: production figures, regulation items and duty changes
    start = len(r.facts)
    r.production_facts(top=5, published_since=r.today - timedelta(days=PRODUCTION_NEW_DAYS))
    tag("production", start)
    start = len(r.facts)
    r.regulation_facts(days=CHANGE_DAYS, limit=5)
    r.duty_change_facts(datetime.combine(r.today - timedelta(days=CHANGE_DAYS), datetime.min.time()))
    tag("regulation", start)
    return r


def _section_blocks(r: Retriever) -> list[dict]:
    """Context blocks with the section each one was selected for."""
    blocks = context_payload(r.facts, allow_private=False)
    by_id = {f.id: f for f in r.facts}
    for b in blocks:
        b["section"] = by_id[b["id"]].meta.get("section")
    return blocks


def compose(r: Retriever, lang: str) -> dict:
    """Ask the model for the briefing and post-check it. Returns {"sections", "bullets", "dropped",
    "total", "rejected"}. Raises llm.LLMUnavailable / llm.LLMError."""
    import json

    user = (f"DATA DI OGGI / TODAY: {r.today.isoformat()}\n"
            "CONTESTO / CONTEXT (JSON; \"section\" is where each block was selected):\n"
            + json.dumps(_section_blocks(r), ensure_ascii=False, indent=1))
    data = llm.complete_json(SYSTEM_PROMPT[lang], user, SCHEMA, max_tokens=2000)
    by_key = parse_ai_sections(data, SECTION_KEYS)
    extra = f"{r.today.isoformat()}\n{COMPANY_BASIS}"
    sections, bullets, dropped, total = [], [], [], 0
    for key, it_title, en_title, kind in SECTIONS:
        items = by_key.get(key) or []
        total += len(items)
        kept, bad = check_sentences(items, r.facts, require_refs=key != "implications", extra_basis=extra,
                                    allow_private=False)
        dropped += [{**d, "section": key} for d in bad]
        if not kept:
            continue
        title = it_title if lang == "it" else en_title
        analysis = key == "implications"
        sections.append({"key": key, "title": title, "is_analysis": analysis, "count": len(kept)})
        for it in kept:
            cited = [r.facts.get(i) for i in it["refs"]]
            first = cited[0] if cited and not analysis else None
            bullets.append({
                "kind": kind, "section": key, "section_title": title, "is_analysis": analysis,
                "text": f"{ANALYSIS_LABEL[lang]} — {it['text']}" if analysis else it["text"],
                "refs": it["refs"],
                "source": first.source if first else None,
                "publisher": first.source_name if first else (ANALYSIS_PUBLISHER[lang] if analysis else None),
                "date": first.published_at if first else None,
                "period_label": first.period_label if first else None,
                "url": first.url if first else None,
                "link": first.link if first else None,
                "data_status": first.data_status if first else None,
                "is_demo": any(f.is_demo for f in cited),
                "is_ai": True,
            })
    factual = sum(s["count"] for s in sections if not s["is_analysis"])
    rejected = factual == 0 or (total > 0 and len(dropped) / total > MAX_DROPPED_SHARE)
    return {"sections": sections, "bullets": bullets, "dropped": dropped, "total": total, "rejected": rejected}


def _existing(session: Session, day: date, lang: str) -> Briefing | None:
    return session.scalars(select(Briefing).where(Briefing.briefing_date == day, Briefing.language == lang)).first()


def generate_daily(session: Session, langs: tuple[str, ...] | list[str] = LANGS, *, force: bool = False,
                   today: date | None = None) -> dict:
    """Write and store today's AI briefing for each language (see the module docstring).

    Returns {"enabled", "date", "generator", "results": {lang: {"status": generated | exists |
    no_facts | rejected | error, ...}}}. Without an AI provider: {"enabled": False, ...} and nothing
    is written. `force` replaces a briefing already stored for the day."""
    today = today or assistant.clock_today()
    out: dict[str, Any] = {"enabled": llm.is_enabled(), "date": today.isoformat(), "generator": None, "results": {}}
    if not out["enabled"]:
        out["skipped"] = "llm_disabled"
        return out
    if not _run_lock.acquire(blocking=False):
        out["skipped"] = "already_running"
        return out
    try:
        info = llm.provider_info()
        out["generator"] = info.label
        for lang in [x for x in langs if x in LANGS]:
            out["results"][lang] = _generate_one(session, lang, today, info, force)
    finally:
        _run_lock.release()
    return out


def _generate_one(session: Session, lang: str, today: date, info: llm.ProviderInfo, force: bool) -> dict:
    existing = _existing(session, today, lang)
    if existing is not None and not force:
        return {"status": "exists", "generator": existing.generator, "generated_at": iso(existing.generated_at)}
    r = build_facts(session, lang, today)
    if not len(r.facts):
        return {"status": "no_facts"}
    try:
        res = compose(r, lang)
    except llm.LLMUnavailable:
        return {"status": "error", "error": "llm_unavailable"}
    except llm.LLMError as exc:
        log.warning("AI briefing (%s) failed: %s", lang, exc)
        return {"status": "error", "error": str(exc)}
    checks = {"sentences": res["total"], "dropped": len(res["dropped"]), "dropped_items": res["dropped"]}
    if res["rejected"]:
        log.warning("AI briefing (%s) rejected by the post-check: %s", lang, checks)
        return {"status": "rejected", "checks": checks}
    now = assistant.clock_now()
    content = {
        "version": 1, "is_ai": True, "lang": lang, "generator": info.label, "generated_at": iso(now),
        "sections": res["sections"], "bullets": res["bullets"],
        "facts": [f.to_dict(lang) for f in r.facts], "checks": checks,
    }
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(Briefing(briefing_date=today, language=lang, generated_at=now, generator=info.label, content=content))
    session.commit()
    return {"status": "generated", "bullets": len(res["bullets"]), "sections": [s["key"] for s in res["sections"]],
            "checks": checks}


def stored(session: Session, lang: str, today: date | None = None) -> dict | None:
    """Today's stored briefing (as written by `generate_daily`), or None."""
    b = _existing(session, today or assistant.clock_today(), lang)
    if b is None:
        return None
    content = b.content if isinstance(b.content, dict) else {}
    return {"date": iso(b.briefing_date), "language": b.language, "generator": b.generator,
            "generated_at": iso(b.generated_at), "is_ai": b.generator != "rules",
            "sections": content.get("sections") or [], "bullets": content.get("bullets") or [],
            "facts": content.get("facts") or [], "checks": content.get("checks")}
