"""From a person's words to real candidate figures ("il prezzo del miele argentino di settembre non è
3,20 ma 3,40").

The AI only READS the sentence: it returns a structured request (what kind of figure, country, price
type, period, old and new value, unit, currency, reason) through the configured provider
(services/llm.py: PALADEX_LLM_PROVIDER + its key). It never picks a database row and its numbers are
kept only when they are written in the sentence. The backend then looks the request up in the
database with ordinary filters and returns up to five REAL figures with their current value and
provenance, and the change each one would get. Nothing is written here: the person confirms one
candidate and the interface sends it to POST /api/corrections.

Privacy: a sentence about a supplier offer ("offerta", "fornitore", a supplier name held in the
private Offerte page) is never sent to the AI: the answer is ``route: "quotes"`` and the interface
opens the private Offerte page. The company name is replaced by a neutral word before the call.
"""
from __future__ import annotations

import math
import re
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..api.common import iso, source_brief
from ..config import get_settings
from ..enums import PriceType, Variety
from ..models import (
    PriceObservation,
    ProductionStat,
    Source,
    SupplierQuote,
    TradeFlowObservation,
    utcnow,
)
from ..reference.countries import country_name, is_known_iso3
from . import corrections, ingest, llm
from .corrections import CorrectionError

MAX_TEXT = 1000
MAX_CANDIDATES = 5
MATCH_TOLERANCE = 0.015          # an old value "matches" a stored one within 1.5 %
COMPANY_RX = re.compile(r"(?i)\bparodi(?:\s+group)?\b")
QUOTE_RX = re.compile(r"(?i)\b(?:offert[ae]\w*|offers?\b|offer(?:ed|ing)\b|fornitor\w*|suppliers?\b|preventiv\w*|"
                      r"ci ha offerto|mi ha offerto|quotazione del fornitore)")
PRICE_TYPES = [p.value for p in PriceType]
VARIETIES = [v.value for v in Variety]
METRICS = list(corrections.METRIC_WORDS)

SCHEMA = {
    "route": "correction | quotes | unclear",
    "kind": "value_correction | flag_wrong | note",
    "table": "price_observations | trade_flows | production_stats | null",
    "country_iso3": "ISO 3166 alpha-3 or null",
    "partner_iso3": "ISO 3166 alpha-3 or null (trade only)",
    "flow": "import | export | null",
    "price_type": " | ".join(PRICE_TYPES) + " | null",
    "variety": "one of the varieties listed, or null",
    "metric": " | ".join(METRICS) + " | null",
    "trade_measure": "net_weight_kg | value | null",
    "period": "YYYY | YYYY-MM | YYYY-Qn | null",
    "source_hint": "the source the person names (USDA, ISMEA, Eurostat ...) or null",
    "old_value": "number written in the text as the wrong value, or null",
    "new_value": "number written in the text as the right value, or null",
    "low": "number or null", "high": "number or null",
    "unit": "kg | lb | t | 100kg | q | null",
    "currency": "ISO 4217 (EUR, USD ...) or null",
    "reason": "why, in the person's words, or null",
    "note_text": "for a note: the information to keep, in the person's words, or null",
    "summary": "one short sentence, in the person's language, saying what you understood",
}


def _system(today: date) -> str:
    return (
        "You read ONE sentence written by an expert of the world honey market who uses Paladex, an internal "
        "database of official honey statistics (prices, trade flows, production). He says that a figure shown "
        "is wrong, or doubtful, or he adds a note about a country. Turn the sentence into the JSON request "
        "below. You never choose database rows and you never invent anything: every number must be written in "
        "the sentence (Italian decimals use a comma: '3,40' is 3.4); a field that is not stated is null.\n"
        "- kind 'value_correction': he gives the right value of a figure (table: price_observations for prices "
        "and unit values, trade_flows for imports/exports quantities or values, production_stats for "
        "production, colonies, yields).\n"
        "- kind 'flag_wrong': he says a figure is wrong or suspicious but gives no right value.\n"
        "- kind 'note': information about a country to keep (no figure to change); put it in note_text.\n"
        "- route 'quotes': the sentence is about an offer or a price proposed by a supplier to his company "
        "(that goes to the private offers page, not here). route 'unclear': you cannot tell.\n"
        f"- price_type: {', '.join(PRICE_TYPES)} (wholesale_bulk = bulk prices to importers, e.g. USDA, Italian "
        "price lists; import/export_unit_value = customs value per kg).\n"
        f"- variety: {', '.join(VARIETIES)}; 'miele argentino' means country ARG; polyflora = millefiori.\n"
        f"- metric (production_stats): {', '.join(METRICS)}.\n"
        f"- period: a month 'settembre' without a year is the most recent September not after today ({today.isoformat()}).\n"
        "- unit and currency of the RIGHT value as written ('3,40 euro al chilo' -> EUR, kg; 'tonnellate' -> t)."
    )


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip().replace(",", "."))
        except ValueError:
            return None
    if not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return None
    return float(v)


def _choice(v, allowed) -> str | None:
    return v if isinstance(v, str) and v in allowed else None


def _iso3(v) -> str | None:
    c = v.strip().upper() if isinstance(v, str) else None
    return c if c and is_known_iso3(c) else None


def _period(v) -> str | None:
    s = v.strip().upper() if isinstance(v, str) else ""
    return s if re.fullmatch(r"\d{4}(-\d{2}|-Q[1-4])?", s) else None


def _text(v, n: int = 500) -> str | None:
    return v.strip()[:n] if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none") else None


def numbers_in(text: str) -> set[float]:
    """Every value a number written in `text` can have ('3,40' and '3.40' are 3.4; '1.200' is 1200 or
    1.2), times a thousand / a million when the sentence says 'mila', 'migliaia', 'thousand', 'milioni'..."""
    from .ai_enrich import _NUM, _readings

    vals: set[float] = set()
    for m in _NUM.finditer(text or ""):
        whole, parts = _readings(m.group(0))
        for d in whole.union(*parts) if parts else whole:
            vals.add(float(d))
    low = (text or "").lower()
    if re.search(r"\b(?:mila|migliai\w*|thousands?|k)\b", low):
        vals |= {v * 1000 for v in vals}
    if re.search(r"\b(?:milion\w*|millions?|mln)\b", low):
        vals |= {v * 1_000_000 for v in vals}
    return vals


def validate(data: dict, text: str) -> dict:
    """Keep only what is allowed; numbers only when they are written in the sentence."""
    numbers_in_text = numbers_in(text)

    def written(v) -> float | None:
        n = _num(v)
        if n is None:
            return None
        return n if any(abs(n - w) <= 1e-9 * max(1.0, abs(n)) for w in numbers_in_text) else None

    out = {
        "route": _choice(data.get("route"), ("correction", "quotes", "unclear")) or "unclear",
        "kind": _choice(data.get("kind"), ("value_correction", "flag_wrong", "note")),
        "table": _choice(data.get("table"), tuple(corrections.TABLES)),
        "country_iso3": _iso3(data.get("country_iso3")),
        "partner_iso3": _iso3(data.get("partner_iso3")),
        "flow": _choice(data.get("flow"), ("import", "export")),
        "price_type": _choice(data.get("price_type"), PRICE_TYPES),
        "variety": _choice(data.get("variety"), VARIETIES),
        "metric": _choice(data.get("metric"), METRICS),
        "trade_measure": _choice(data.get("trade_measure"), corrections.TRADE_FIELDS),
        "period": _period(data.get("period")),
        "source_hint": _text(data.get("source_hint"), 60),
        "old_value": written(data.get("old_value")),
        "new_value": written(data.get("new_value")),
        "low": written(data.get("low")),
        "high": written(data.get("high")),
        "unit": corrections.clean_unit(_text(data.get("unit"), 20)),
        "currency": None,
        "reason": _text(data.get("reason")),
        "note_text": _text(data.get("note_text"), corrections.MAX_TEXT),
        "summary": _text(data.get("summary"), 300),
    }
    try:
        out["currency"] = corrections.clean_currency(_text(data.get("currency"), 10))
    except CorrectionError:
        out["currency"] = None
    if out["unit"] is not None and out["unit"] not in ingest.KG_PER_UNIT:
        out["unit"] = None
    if out["kind"] is None and out["route"] == "correction":
        out["kind"] = "value_correction" if out["new_value"] is not None else "flag_wrong"
    if out["kind"] == "value_correction" and out["new_value"] is None:
        out["kind"] = "flag_wrong"
    return out


def _supplier_names(session: Session) -> list[str]:
    names = {n.strip() for n in session.scalars(select(SupplierQuote.supplier_name).distinct()) if n and len(n.strip()) >= 3}
    return sorted(names, key=len, reverse=True)


def is_about_offers(session: Session, text: str) -> bool:
    if QUOTE_RX.search(text):
        return True
    low = text.lower()
    return any(re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", low) for n in _supplier_names(session))


def scrub(text: str) -> str:
    return COMPANY_RX.sub("[azienda]", text)


# ---------------------------------------------------------------------------
# Candidates (always resolved here, from the database)
# ---------------------------------------------------------------------------


def _period_bounds(label: str | None) -> tuple[date, date] | None:
    if not label:
        return None
    from ..api.prices import parse_period_bound

    return parse_period_bound(label, end=False), parse_period_bound(label, end=True)


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and b != 0 and abs(a - b) / abs(b) <= MATCH_TOLERANCE


def _matches_old(table: str, row, old: float | None) -> bool:
    if old is None:
        return False
    if table == "price_observations":
        reps = [row.price_value, row.price_per_kg, row.usd_per_kg, row.eur_per_kg]
        reps += [x * ingest.KG_PER_UNIT["lb"] for x in (row.price_per_kg, row.usd_per_kg, row.eur_per_kg) if x]
        return any(_close(old, r) for r in reps)
    if table == "trade_flows":
        reps = [row.value, row.net_weight_kg, (row.net_weight_kg or 0) / 1000 or None, row.usd_value, row.eur_value]
        return any(_close(old, r) for r in reps)
    return any(_close(old, r) for r in (row.value, row.value * 1000 if row.value else None,
                                        row.value / 1000 if row.value else None))


def _source_ids(session: Session, hint: str | None) -> list[int] | None:
    if not hint:
        return None
    h = hint.strip().lower()
    ids = [s.id for s in session.scalars(select(Source)) if h in (s.key or "").lower() or h in (s.name or "").lower()
           or h in (s.publisher or "").lower() or h in (s.name_en or "").lower()]
    return ids or None


def _query(session: Session, table: str, req: dict, relax: int):
    """Current, real rows matching the request; `relax` drops the least certain filters first."""
    model = corrections.TABLES[table]
    q = select(model).where(model.is_current.is_(True), model.is_demo.is_(False))
    country = req.get("country_iso3")
    period = _period_bounds(req.get("period"))
    sids = _source_ids(session, req.get("source_hint")) if relax < 2 else None
    if sids:
        q = q.where(model.source_id.in_(sids))
    if period and relax < 3:
        q = q.where(model.period_start <= period[1], model.period_end >= period[0])
    if table == "price_observations":
        P = PriceObservation
        if country:
            q = q.where(or_(P.origin_iso3 == country, P.market_iso3 == country) if relax >= 1 else P.origin_iso3 == country)
        if req.get("price_type") and relax < 2:
            q = q.where(P.price_type == req["price_type"])
        if req.get("variety") and relax < 1:
            q = q.where(P.variety == req["variety"])
    elif table == "trade_flows":
        T = TradeFlowObservation
        q = q.where(T.hs_code.like("0409%"))
        if country:
            q = q.where(T.reporter_iso3 == country)
        if req.get("flow"):
            q = q.where(T.flow == req["flow"])
        q = q.where(T.partner_iso3 == (req.get("partner_iso3") or "WLD")) if relax < 1 else q
    else:
        S = ProductionStat
        if country:
            q = q.where(S.country_iso3 == country)
        q = q.where(S.metric == (req.get("metric") or "production")) if relax < 2 else q
    return list(session.scalars(q.order_by(model.period_start.desc(), model.id.desc()).limit(400)))


def find_candidates(session: Session, req: dict, limit: int = MAX_CANDIDATES) -> list[tuple[str, object]]:
    tables = [req["table"]] if req.get("table") else ["price_observations", "production_stats", "trade_flows"]
    if not req.get("country_iso3") and not req.get("period") and not req.get("old_value"):
        return []           # too vague to look anything up: the interface asks for more
    found: list[tuple[str, object]] = []
    for table in tables:
        for relax in range(4):
            rows = _query(session, table, req, relax)
            if rows:
                break
        seen: set[tuple] = set()
        ranked = []
        for r in rows:
            k = (r.source_id, r.series_key)
            if k in seen:
                continue
            seen.add(k)
            ranked.append(r)
        old = req.get("old_value")
        ranked.sort(key=lambda r: (not _matches_old(table, r, old), -r.period_start.toordinal()))
        found += [(table, r) for r in ranked[:limit]]
        if found and req.get("table"):
            break
    old = req.get("old_value")
    found.sort(key=lambda tr: not _matches_old(tr[0], tr[1], old))
    return found[:limit]


def describe(session: Session, table: str, row, req: dict | None, lang: str) -> dict:
    """A candidate figure: current value, provenance, and the change the request would make."""
    src = session.get(Source, row.source_id)
    field = corrections.main_field(table, (req or {}).get("trade_measure")
                                   or ("value" if (req or {}).get("currency") and table == "trade_flows" else None))
    unit, ccy = corrections.unit_currency(table, row, field)
    current = {"value": getattr(row, field), "unit": unit, "currency": ccy, "data_status": row.data_status,
               "reliability": row.reliability}
    if table == "price_observations":
        current.update(low=row.price_low, high=row.price_high,
                       per_kg={"native": row.price_per_kg, "USD": row.usd_per_kg, "EUR": row.eur_per_kg})
    out = {
        "table": table, "row_id": row.id, "source": source_brief(src), "series_key": row.series_key,
        "period_label": row.period_label, "field": field,
        "label": corrections.figure_label(table, row, lang, field),
        "current": current,
        "correction": corrections.row_correction(row),
        "matches_old_value": _matches_old(table, row, (req or {}).get("old_value")),
        "provenance": {"source_url": row.source_url, "published_at": iso(row.published_at),
                       "collected_at": iso(row.collected_at), "period_start": iso(row.period_start),
                       "period_end": iso(row.period_end), "frequency": row.frequency},
        "link": corrections.figure_link(table, row),
        "proposal": None, "proposal_error": None,
    }
    if req and req.get("kind") == "value_correction" and req.get("new_value") is not None:
        official = corrections.official_of(session, corrections.TABLES[table], row)
        try:
            norm = corrections.normalize(session, table, official, value=req["new_value"], low=req.get("low"),
                                         high=req.get("high"), unit=req.get("unit"), currency=req.get("currency"),
                                         field=field)
            out["proposal"] = {
                "from": current["value"], "to": norm["main"], "unit": unit, "currency": ccy, "field": norm["field"],
                "entered": norm["entered"],
                "create": {"kind": "value_correction", "target": {"table": table, "row_id": row.id},
                           "value": req["new_value"], "low": req.get("low"), "high": req.get("high"),
                           "unit": norm["entered"].get("unit"), "currency": norm["entered"].get("currency"),
                           "field": norm["field"] if table == "trade_flows" else None, "reason": req.get("reason")},
            }
        except CorrectionError as exc:
            out["proposal_error"] = exc.detail()
    elif req and req.get("kind") == "flag_wrong":
        out["proposal"] = {"create": {"kind": "flag_wrong", "target": {"table": table, "row_id": row.id},
                                      "reason": req.get("reason")}}
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def interpret(session: Session, text: str, lang: str = "it", context: dict | None = None,
              today: date | None = None) -> dict:
    """POST /api/corrections/interpret. Raises CorrectionError (409 `ai_unavailable` without a key)."""
    lang = lang if lang in ("it", "en") else "it"
    text = (text or "").strip()
    if not text:
        raise CorrectionError("missing_text", "Scrivere che cosa non va.", "Write what is wrong.")
    if len(text) > MAX_TEXT:
        raise CorrectionError("text_too_long", f"Testo troppo lungo (al massimo {MAX_TEXT} caratteri).",
                              f"Text too long ({MAX_TEXT} characters at most).")
    settings = get_settings()
    if not settings.llm_enabled():
        raise CorrectionError("ai_unavailable",
                              "L'IA non è configurata: compilare il modulo (dato, valore, motivo).",
                              "The AI is not configured: fill in the form (figure, value, reason).", status=409)
    today = today or date.today()
    ctx_row = None
    if context and context.get("table"):
        _model, ctx_row = corrections.resolve_target(session, context.get("table"), row_id=context.get("row_id"),
                                                     source_key=context.get("source_key"),
                                                     series_key=context.get("series_key"))
    base = {"text": text, "lang": lang, "candidates": [], "note": None}
    if is_about_offers(session, text):
        return {**base, "route": "quotes", "kind": None, "understood": None, "ai": None,
                "message_it": "Sembra un'offerta di un fornitore: va inserita nella pagina riservata Offerte "
                              "(non viene inviata all'IA né salvata qui).",
                "message_en": "This looks like a supplier offer: enter it in the private Offers page "
                              "(it is not sent to the AI nor stored here)."}
    info = llm.provider_info(settings)
    user = f"SENTENCE: {scrub(text)}\nLANGUAGE: {lang}\nTODAY: {today.isoformat()}"
    if ctx_row is not None:
        table = corrections.TABLE_OF[type(ctx_row)]
        unit, ccy = corrections.unit_currency(table, ctx_row)
        user += (f"\nTHE FIGURE HE POINTED AT: {corrections.figure_label(table, ctx_row, 'en')} "
                 f"(table {table}), current value {getattr(ctx_row, corrections.main_field(table))} "
                 f"{ccy or ''}{'/' if ccy and unit else ''}{unit or ''}")
    try:
        data = llm.complete_json(_system(today), user, SCHEMA, max_tokens=700, settings=settings)
    except llm.LLMUnavailable:
        raise CorrectionError("ai_unavailable", "L'IA non è configurata.", "The AI is not configured.", status=409) from None
    except llm.LLMError as exc:
        raise CorrectionError("ai_error", "L'IA non ha risposto: riprovare o compilare il modulo.",
                              "The AI did not answer: try again or fill in the form.", status=502,
                              error=str(exc)[:300]) from None
    req = validate(data if isinstance(data, dict) else {}, text)
    if ctx_row is not None:
        req["table"] = corrections.TABLE_OF[type(ctx_row)]
        if req["route"] == "unclear" and req["new_value"] is not None:
            req["route"], req["kind"] = "correction", "value_correction"
    ai = {"provider": info.provider, "model": info.model}
    interpretation = {"text": text, "understood": req, "model": info.label, "at": corrections.iso_utc(utcnow())}
    out = {**base, "route": req["route"], "kind": req["kind"], "understood": req, "ai": ai,
           "ai_interpretation": interpretation, "message_it": req["summary"] if lang == "it" else None,
           "message_en": req["summary"] if lang == "en" else None}
    if req["route"] == "quotes":
        out["message_it"] = ("Sembra un'offerta di un fornitore: va inserita nella pagina riservata Offerte "
                             "(non viene salvata qui).")
        out["message_en"] = "This looks like a supplier offer: enter it in the private Offers page (nothing is stored here)."
        return out
    if req["kind"] == "note":
        iso3 = req["country_iso3"] or (corrections.figure_country(req["table"], ctx_row) if ctx_row is not None else None)
        out["note"] = {"country_iso3": iso3, "country_name": country_name(iso3, lang) if iso3 else None,
                       "text": req["note_text"] or text,
                       "create": {"kind": "note", "country_iso3": iso3, "text": req["note_text"] or text,
                                  **({"target": {"table": req["table"], "row_id": ctx_row.id}} if ctx_row is not None else {})}}
        out["route"] = "correction"
        return out
    if req["route"] != "correction" and ctx_row is None:
        return out
    rows = [(req["table"], ctx_row)] if ctx_row is not None else find_candidates(session, req)
    out["candidates"] = [describe(session, t, r, req, lang) for t, r in rows]
    return out
