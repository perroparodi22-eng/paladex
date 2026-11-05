"""Global search: one box for countries, varieties, price series, news, reports, regulations and
sources. Results are grouped; every item carries a `target` (an in-app route such as
/paesi/ARG or /prezzi?origin=ARG&variety=acacia, or the external URL of an official document).

Search is cross-language: a word recognised as a country or a variety is expanded to its
Italian and English names (e.g. "ungheria" also finds "Hungary", "castagno" finds "chestnut").
"""
from __future__ import annotations

import re
import unicodedata
from itertools import pairwise
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import Variety
from ..models import NewsArticle, PriceObservation, RegulationItem, Report, Source
from ..reference.countries import COUNTRY_KEYWORDS, countries, lookup_iso3
from ..reference.varieties import CORE_VARIETIES, LABELS, normalize_variety
from .common import demo_clause, freshness, iso, source_brief, sources_by_id

router = APIRouter(tags=["search"])

GROUP_ORDER = ("countries", "varieties", "prices", "news", "reports", "regulations", "sources")
MAX_TOKENS = 6
SNIPPET_CHARS = 220

# Words that carry no meaning on their own in a honey-market search (IT / EN / ES / DE).
STOPWORDS = {
    "di", "del", "della", "dello", "dei", "degli", "delle", "da", "dal", "in", "il", "lo", "la", "le", "gli", "un",
    "una", "uno", "e", "ed", "per", "con", "su", "a", "al", "alla", "the", "of", "and", "for", "on", "to", "from",
    "de", "y", "miele", "mieli", "honey", "honeys", "miel", "honig",
}
_SKIP_VARIETIES = {Variety.UNSPECIFIED.value, Variety.OTHER.value}

# Market vocabulary in Italian and English: a word in one group also searches the others,
# so "dazi" finds English news about "tariffs" (and vice versa).
_SYNONYM_GROUPS: list[set[str]] = [
    {"dazi", "dazio", "tariff", "tariffs", "duty", "duties", "antidumping", "anti-dumping", "dumping"},
    {"prezzi", "prezzo", "quotazioni", "price", "prices", "pricing"},
    {"raccolto", "raccolti", "harvest", "harvests", "crop", "crops"},
    {"esportazioni", "esportazione", "export", "exports", "exporter", "exporters"},
    {"importazioni", "importazione", "import", "imports", "importer", "importers"},
    {"adulterazione", "adulterato", "frode", "frodi", "adulteration", "adulterated", "fraud"},
    {"siccita", "siccità", "drought"},
    {"gelate", "gelata", "gelo", "frost", "frosts"},
    {"normative", "normativa", "regolamento", "regolamenti", "regulation", "regulations", "rules"},
    {"produzione", "production", "output"},
    {"apicoltori", "apicoltore", "beekeepers", "beekeeper", "beekeeping", "apicoltura"},
    {"biologico", "biologica", "organic"},
    {"alveari", "alveare", "colonie", "hives", "colonies"},
    {"api", "bees", "bee"},
]
_SYNONYMS: dict[str, set[str]] = {w: g for g in _SYNONYM_GROUPS for w in g}

_COUNTRIES = [c for c in countries()]
_COUNTRY_BY_ISO3 = {c["iso3"]: c for c in _COUNTRIES}


def _fold(s: str) -> str:
    """lower-case, strip accents, keep letters/digits/spaces."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(col, text: str):
    return col.ilike(f"%{_escape_like(text)}%", escape="\\")


def _tokens(q: str) -> list[str]:
    raw = [t for t in re.split(r"[\s,;/]+", q.lower()) if len(t.strip(".-'\"")) >= 2]
    raw = [t.strip(".-'\"") for t in raw]
    meaningful = [t for t in raw if t not in STOPWORDS]
    return (meaningful or raw)[:MAX_TOKENS]


# ------------------------------------------------------------------ recognisers
def _word_prefix(needle: str, hay: str) -> bool:
    return bool(needle) and re.search(rf"(^|\s){re.escape(needle)}", hay) is not None


def match_countries(q: str, tokens: list[str]) -> list[str]:
    """ISO3 codes matched by the query: exact names/aliases/codes first, then name prefixes."""
    exact: list[str] = []
    qs = q.strip()
    if qs and not qs.isdigit():
        iso3 = lookup_iso3(qs)
        if iso3 in _COUNTRY_BY_ISO3:
            exact.append(iso3)
    words = [_fold(t) for t in tokens]
    candidates = list(words) + [f"{a} {b}" for a, b in pairwise(words)]
    for cand in candidates:
        if len(cand) < 4 or cand.isdigit():
            continue
        iso3 = lookup_iso3(cand)
        if iso3 in _COUNTRY_BY_ISO3 and iso3 not in exact:
            exact.append(iso3)
    prefix: list[str] = []
    needles = {n for n in [_fold(qs)] + words if len(n) >= 3 and not n.isdigit()}
    for c in _COUNTRIES:
        if c["iso3"] in exact:
            continue
        names = (_fold(c["name_it"]), _fold(c["name_en"]))
        if any(_word_prefix(n, name) for n in needles for name in names):
            prefix.append(c["iso3"])
    prefix.sort(key=lambda i: (not _COUNTRY_BY_ISO3[i]["priority"], _COUNTRY_BY_ISO3[i]["name_it"]))
    return exact + prefix


def _variety_names(v: str) -> list[str]:
    out: set[str] = {v.replace("_", " ")}
    for lang in ("it", "en"):
        label = LABELS.get(v, {}).get(lang, "")
        for part in re.split(r"[/()]", label):
            part = part.strip().lower()
            if len(part) >= 3:
                out.add(part)
                out.add(_fold(part))
    return sorted(out)


def match_varieties(q: str, tokens: list[str]) -> list[str]:
    found: list[str] = []
    candidates = [q.strip()] + tokens
    for cand in candidates:
        if len(cand) < 3:
            continue
        v, _organic = normalize_variety(cand)
        if v not in _SKIP_VARIETIES and v not in found:
            found.append(v)
    needles = {_fold(c) for c in candidates if len(_fold(c)) >= 3}
    for v in LABELS:
        if v in _SKIP_VARIETIES or v in found:
            continue
        if any(_word_prefix(n, _fold(name)) for n in needles for name in _variety_names(v)):
            found.append(v)
    return found


def _term_alternatives(token: str) -> tuple[list[str], str | None]:
    """A search word plus its translations, and the ISO3 code if it names a country."""
    alts: set[str] = {token}
    folded = _fold(token)
    if folded and folded != token:
        alts.add(folded)
    alts |= _SYNONYMS.get(token, set()) | _SYNONYMS.get(folded, set())
    iso3 = lookup_iso3(folded) if len(folded) >= 4 and not folded.isdigit() else None
    if iso3 not in _COUNTRY_BY_ISO3:
        iso3 = None
    if iso3:
        c = _COUNTRY_BY_ISO3[iso3]
        alts |= {c["name_it"].lower(), c["name_en"].lower(), *COUNTRY_KEYWORDS.get(iso3, [])}
    if len(token) >= 3:
        v, _ = normalize_variety(token)
        if v not in _SKIP_VARIETIES:
            alts |= set(_variety_names(v))
    return sorted(a for a in alts if len(a) >= 2), iso3


def _text_condition(fields: list, specs: list[tuple[list[str], str | None]], countries_col=None, extra=None):
    """Every search word must appear (in any of its languages) in at least one field."""
    conds = []
    for alts, iso3 in specs:
        ors = [_like(f, a) for f in fields for a in alts]
        if iso3 and countries_col is not None:
            ors.append(cast(countries_col, String).like(f'%"{iso3}"%'))
        if extra is not None:
            ors.extend(extra(alts))
        conds.append(or_(*ors))
    return and_(*conds)


def _excerpt(text: str | None, alts: list[str], n: int = SNIPPET_CHARS) -> str | None:
    if not text:
        return None
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= n:
        return t
    low = t.lower()
    pos = min((p for p in (low.find(a.lower()) for a in alts) if p >= 0), default=0)
    start = max(0, pos - n // 3)
    chunk = t[start:start + n].strip()
    return ("…" if start > 0 else "") + chunk + ("…" if start + n < len(t) else "")


def _q(path: str, **params) -> str:
    params = {k: v for k, v in params.items() if v}
    return path + (f"?{urlencode(params)}" if params else "")


# ------------------------------------------------------------------ groups
def _price_presence(db: Session) -> tuple[set[str], set[str]]:
    base = [PriceObservation.is_current.is_(True), demo_clause(PriceObservation, db)]
    origins = {o for (o,) in db.execute(select(PriceObservation.origin_iso3).where(*base).distinct()) if o}
    varieties = {v for (v,) in db.execute(select(PriceObservation.variety).where(*base).distinct()) if v}
    return origins, varieties


def _country_item(iso3: str, with_prices: set[str]) -> dict:
    c = _COUNTRY_BY_ISO3[iso3]
    return {"iso3": iso3, "name_it": c["name_it"], "name_en": c["name_en"], "region": c["region"],
            "priority": c["priority"], "has_prices": iso3 in with_prices, "target": f"/paesi/{iso3}", "external": False}


def _variety_item(v: str, with_prices: set[str]) -> dict:
    return {"key": v, "it": LABELS[v]["it"], "en": LABELS[v]["en"], "core": v in CORE_VARIETIES,
            "has_prices": v in with_prices, "target": _q("/prezzi", variety=v), "external": False}


def _price_hints(db: Session, isos: list[str], vars_: list[str], limit: int) -> tuple[list[dict], int]:
    P = PriceObservation
    if not isos and not vars_:
        return [], 0
    where = [P.is_current.is_(True), demo_clause(P, db)]
    if isos and vars_:
        where += [P.origin_iso3.in_(isos), P.variety.in_(vars_)]
    elif isos:
        where.append(P.origin_iso3.in_(isos))
    else:
        where += [P.variety.in_(vars_), P.origin_iso3.is_not(None)]
    rows = db.execute(
        select(P.origin_iso3, P.variety, P.price_type, func.count(), func.max(P.period_end), func.max(P.period_label),
               func.count(func.distinct(P.source_id)), func.max(P.is_demo))
        .where(*where).group_by(P.origin_iso3, P.variety, P.price_type)
    ).all()
    merged: dict[tuple, dict] = {}
    for origin, variety, pt, n, last_end, last_label, n_src, demo in rows:
        m = merged.setdefault((origin, variety), {
            "origin_iso3": origin, "variety": variety, "price_types": [], "observations": 0,
            "latest_period_end": None, "latest_period_label": None, "sources": 0, "is_demo": False,
        })
        m["price_types"].append(pt)
        m["observations"] += n
        m["sources"] = max(m["sources"], n_src)
        m["is_demo"] = m["is_demo"] or bool(demo)
        if m["latest_period_end"] is None or (last_end and last_end > m["latest_period_end"]):
            m["latest_period_end"] = last_end
            m["latest_period_label"] = last_label
    # most recent data first, then the richest series
    items = sorted(merged.values(), key=lambda m: (-(m["latest_period_end"].toordinal() if m["latest_period_end"] else 0),
                                                   -m["observations"]))
    out = []
    for m in items[:limit]:
        origin = m["origin_iso3"]
        c = _COUNTRY_BY_ISO3.get(origin or "")
        out.append({
            **m,
            "latest_period_end": iso(m["latest_period_end"]),
            "price_types": sorted(m["price_types"]),
            "origin_name_it": c["name_it"] if c else origin,
            "origin_name_en": c["name_en"] if c else origin,
            "variety_it": LABELS.get(m["variety"], {}).get("it", m["variety"]),
            "variety_en": LABELS.get(m["variety"], {}).get("en", m["variety"]),
            "target": _q("/prezzi", origin=origin, variety=m["variety"]),
            "external": False,
        })
    return out, len(items)


def _news(db: Session, specs, q: str, limit: int) -> tuple[list[dict], int]:
    N = NewsArticle
    fields = [N.title, N.title_it, N.title_en, N.snippet, N.summary_it, N.summary_en, N.publisher]
    stmt = select(N).where(demo_clause(N, db), N.duplicate_of_id.is_(None),
                           _text_condition(fields, specs, countries_col=N.countries))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(N.published_at.desc().nulls_last(), N.relevance_score.desc(), N.id.desc()).limit(limit)).all()
    srcs = sources_by_id(db)
    alts = [a for a_list, _ in specs for a in a_list]
    target = _q("/notizie", q=q)
    return [{
        "id": a.id, "title": a.title, "title_it": a.title_it, "title_en": a.title_en, "title_is_ai": bool(a.title_it or a.title_en),
        "publisher": a.publisher, "language": a.language, "published_at": iso(a.published_at),
        "collected_at": iso(a.collected_at), "url": a.url, "snippet": _excerpt(a.snippet, alts),
        "summary_it": _excerpt(a.summary_it, alts), "summary_en": _excerpt(a.summary_en, alts),
        "summary_is_ai": bool(a.summary_it or a.summary_en), "countries": a.countries or [],
        "source": source_brief(srcs.get(a.source_id)), "is_demo": a.is_demo,
        "target": target, "external": False,
    } for a in rows], total


def _source_ids_matching(alts: list[str]):
    return Report.source_id.in_(select(Source.id).where(or_(*[_like(c, a) for c in (Source.name, Source.publisher, Source.key) for a in alts])))


def _reports(db: Session, specs, limit: int) -> tuple[list[dict], int]:
    R = Report
    fields = [R.title, R.summary_it, R.summary_en, R.narrative, R.period_label]
    stmt = select(R).where(demo_clause(R, db), _text_condition(fields, specs, extra=lambda alts: [_source_ids_matching(alts)]))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(R.published_at.desc().nulls_last(), R.id.desc()).limit(limit)).all()
    srcs = sources_by_id(db)
    alts = [a for a_list, _ in specs for a in a_list]
    return [{
        "id": r.id, "title": r.title, "period_label": r.period_label, "published_at": iso(r.published_at),
        "collected_at": iso(r.collected_at), "url": r.url,
        "file_url": f"/api/reports/{r.id}/file" if r.raw_document_id else None,
        "summary_it": _excerpt(r.summary_it, alts), "summary_en": _excerpt(r.summary_en, alts),
        "summary_is_ai": r.summary_is_ai, "excerpt": _excerpt(r.narrative, alts),
        "source": source_brief(srcs.get(r.source_id)), "is_demo": r.is_demo,
        "target": r.url, "external": True,
    } for r in rows], total


def _regulations(db: Session, specs, limit: int) -> tuple[list[dict], int]:
    G = RegulationItem
    fields = [G.title, G.reference, G.summary_it, G.summary_en, G.doc_type, G.jurisdiction]
    stmt = select(G).where(demo_clause(G, db), _text_condition(fields, specs, countries_col=G.countries))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(G.published_at.desc().nulls_last(), G.id.desc()).limit(limit)).all()
    srcs = sources_by_id(db)
    alts = [a for a_list, _ in specs for a in a_list]
    return [{
        "id": g.id, "title": g.title, "reference": g.reference, "jurisdiction": g.jurisdiction, "doc_type": g.doc_type,
        "status": g.status, "published_at": iso(g.published_at), "effective_date": iso(g.effective_date), "url": g.url,
        "summary_it": _excerpt(g.summary_it, alts), "summary_en": _excerpt(g.summary_en, alts),
        "summary_is_ai": g.summary_is_ai, "source": source_brief(srcs.get(g.source_id)), "is_demo": g.is_demo,
        "target": g.url, "external": True,
    } for g in rows], total


def _sources(db: Session, specs, limit: int) -> tuple[list[dict], int]:
    S = Source
    fields = [S.name, S.publisher, S.key, S.category, S.homepage]
    rows = db.scalars(select(S).where(S.key != "demo", _text_condition(fields, specs)).order_by(S.name)).all()
    return [{
        "key": s.key, "name": s.name, "name_en": s.name_en, "publisher": s.publisher, "category": s.category,
        "reliability": s.reliability,
        "enabled": s.enabled, "homepage": s.homepage, "last_run_status": s.last_run_status,
        "latest_published_at": iso(s.latest_published_at), "freshness": freshness(s),
        "target": f"/fonti#{s.key}", "external": False,
    } for s in rows[:limit]], len(rows)


def _suggestions(with_prices: set[str], var_prices: set[str]) -> dict:
    prio = [c for c in _COUNTRIES if c["priority"]]
    prio.sort(key=lambda c: (c["iso3"] not in with_prices, c["name_it"]))
    return {
        "countries": [_country_item(c["iso3"], with_prices) for c in prio[:12]],
        "varieties": [_variety_item(v, var_prices) for v in CORE_VARIETIES],
    }


@router.get("/search")
def search(q: str = Query("", max_length=200), limit: int = Query(8, ge=1, le=50), db: Session = Depends(get_db)):
    q = (q or "").strip()
    origins_with_prices, varieties_with_prices = _price_presence(db)
    groups: dict[str, dict] = {k: {"key": k, "items": [], "total": 0, "see_all": None} for k in GROUP_ORDER}
    tokens = _tokens(q) if len(q) >= 2 else []
    if tokens:
        isos = match_countries(q, tokens)
        vars_ = match_varieties(q, tokens)
        groups["countries"].update(items=[_country_item(i, origins_with_prices) for i in isos[:limit]], total=len(isos))
        groups["varieties"].update(items=[_variety_item(v, varieties_with_prices) for v in vars_[:limit]], total=len(vars_))
        hints, n_hints = _price_hints(db, isos[:5], vars_[:5], limit)
        groups["prices"].update(items=hints, total=n_hints,
                                see_all=_q("/prezzi", origin=isos[0] if len(isos) == 1 else None,
                                           variety=vars_[0] if len(vars_) == 1 else None) if hints else None)
        specs = [_term_alternatives(t) for t in tokens]
        news, n_news = _news(db, specs, q, limit)
        groups["news"].update(items=news, total=n_news, see_all=_q("/notizie", q=q) if news else None)
        reports, n_rep = _reports(db, specs, limit)
        groups["reports"].update(items=reports, total=n_rep)
        regs, n_regs = _regulations(db, specs, limit)
        groups["regulations"].update(items=regs, total=n_regs, see_all=_q("/normative", q=q) if regs else None)
        srcs, n_srcs = _sources(db, specs, limit)
        groups["sources"].update(items=srcs, total=n_srcs, see_all="/fonti" if srcs else None)
    total = sum(len(g["items"]) for g in groups.values())
    return {
        "query": q,
        "tokens": tokens,
        "total": total,
        "groups": [groups[k] for k in GROUP_ORDER],
        "suggestions": _suggestions(origins_with_prices, varieties_with_prices) if total == 0 else None,
    }
