"""Market assistant ("Assistente IA"): answers the owner's questions from the LOCAL database only,
with source, date, period and status for every fact.

One question (`answer()`):

1. **Understand** (`parse_question`): deterministic parsing of countries (reference names in
   IT/EN/ES and adjectives such as "argentino", through the news country tagger and the reference
   lookup), honey varieties (`normalize_variety` on words and word pairs), price-type words, time
   words ("questa settimana", "quest'anno", years), source names ("report USDA") and topics
   (prices, trade, production, news, reports, regulations, duties, supplier offers, purchase
   costs, exchange rates). Only when nothing is recognised and an AI provider is configured, the
   model may suggest entities; they are kept only when they validate against the reference lists.
2. **Retrieve** (`Retriever` + `retrieve`): numbered context blocks ("facts") built from the
   database only. Prices are never mixed: every block is one series (source, price type, origin,
   variety, market, grade, terms, frequency) at one period, and m/m and y/y are computed on that
   same series. Trade totals and unit values, production, news (default: last 30 days), official
   reports (the USDA narrative when the report has one), regulations, import duties and tariff
   quotas, ECB exchange rates and, only when the question is about them, the supplier offers.
   Each block carries source, URL, publication date, period, unit and a status: verified official
   / published by an industry source / provisional / estimate / historical / press report /
   entered by the user.
3. **Compose**: with an AI provider, a system prompt in the user's language forbids any fact that
   is not in the context and requires citations; the model returns sentences grouped into the
   sections 'Fatti verificati', 'Contesto storico', 'Stime', 'Analisi (IA)' and 'Previsioni (IA,
   incerte)'. **Post-check** (`check_sentences`): every citation must point at an existing block
   and every number of a sentence must appear in the blocks it cites AS THE SAME KIND (`scan_numbers`):
   a quantity must be a quantity there, a date / period / document number the same date, period or
   number, so a day, a year or a quota number never vouches for a price (formatting differences are
   allowed: 1,234.5 / 1.234,5 / 12 % / rounding to fewer decimals). Failing sentences are dropped;
   when too many fail, the AI answer is rejected and the retrieved facts are shown instead, with a
   warning. Without a provider the retrieved facts are the answer ("Ecco i dati disponibili nel
   database…"), `ai_used=False`, with how to enable the AI.
4. **History**: the last questions and answers stay on this PC in `data_dir/assistant/history.json`.

Privacy: supplier offers are business data. They are retrieved (and sent to the AI provider) only
when the question is about offers, and even then the provider sees "Offerta A/B/C" instead of the
supplier names, and never the free-text notes.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..api import overview as ov
from ..api.common import demo_clause, iso, source_brief
from ..config import get_settings
from ..enums import Variety
from ..models import (
    Briefing,
    FxRate,
    NewsArticle,
    ProductionStat,
    RegulationItem,
    Report,
    Source,
    SupplierQuote,
    TariffMeasure,
    TradeFlowObservation,
    utcnow,
)
from ..reference.countries import country_name, is_known_iso3, lookup_iso3
from ..reference.varieties import LABELS as VARIETY_LABELS
from ..reference.varieties import normalize_variety
from . import llm
from .ai_enrich import _NUM, _readings
from .news import fold, tag_countries

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_FACTS = 36                 # context blocks per answer (keeps the prompt and the page readable)
NEWS_DAYS = 30                 # default news window
NEWS_LIMIT = 6
NEWS_MEDIUM = 35               # services.news relevance levels: medium >= 35, high >= 60
NEWS_HIGH = 60
REG_DAYS = 120                 # "recent" regulations
EVENT_DAYS = 7                 # "questa settimana"
HISTORICAL_DAYS = 365          # a period that ended longer ago than this is "historical context"
PRICE_RECENT_DAYS = 400        # a series whose newest point is older than this is not "the latest"
PRICE_MAX_AGE_DAYS = 3 * 365   # ... and older than this it is left to the price explorer
REPORT_TEXT_MAX_AGE_DAYS = 400 # an older report commentary is only mentioned, not quoted
NARRATIVE_CHARS = 1500         # report commentary given to the model
NARRATIVE_SHOWN_CHARS = 600    # ... and shown on screen
YTD_MIN_KG = 500_000           # 500 t: smaller flows swing too much to be ranked
HISTORY_MAX = 40
MAX_DROPPED_SHARE = 0.4        # more AI sentences than this failing the post-check -> answer rejected
QUESTION_MAX_CHARS = 1000

PRICE_TYPE_ORDER = [p.value for p in ov.PRICE_TYPE_PRIORITY]
PRICE_CAPS = {"wholesale_bulk": 3, "import_unit_value": 3, "export_unit_value": 2, "producer": 1, "retail": 1, "other": 1}
MARKET_PRIORITY = ["EU27", "ITA", "USA", "DEU", "ESP", "FRA", "BEL", "NLD", "POL", "GBR"]
COLOR_PRIORITY = ["white", "extra light amber", "light amber", "amber", "amber or darker", None]
FREQ_PRIORITY = {"M": 0, "A": 1, "Q": 1, "W": 2, "D": 2}
STATUS_CAUTION = ("demo", "ai_assessment", "forecast", "estimate", "provisional", "user_entered", "published", "live")
PSEUDO = {"WLD", "EU27", "EU28", "EXTRA_EU", "INTRA_EU"}
GENERAL_ORIGINS = ("ERGA_OMNES", "ALL")
EU27_MEMBERS = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL",
    "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
}
# Origins Parodi Group buys from (purchase-cost questions, quota status).
KEY_ORIGINS = ["ARG", "UKR", "CHN", "BRA", "VNM", "IND", "URY", "MEX", "SRB", "TUR"]
COST_PRICE_TYPES = ("wholesale_bulk", "import_unit_value", "export_unit_value")
# Company context the model may repeat (20 t containers, 300 kg drums): part of every number check.
COMPANY_BASIS = "20 t 20.000 kg 300 kg"

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    "verified_official": {"it": "Dato ufficiale verificato", "en": "Verified official data"},
    "verified_industry": {"it": "Dato pubblicato da fonte di settore", "en": "Published by an industry source"},
    "provisional": {"it": "Dato provvisorio", "en": "Provisional data"},
    "estimate": {"it": "Stima della fonte", "en": "Source estimate"},
    "historical": {"it": "Dato storico", "en": "Historical data"},
    "press": {"it": "Notizia (non verificata)", "en": "News report (not verified)"},
    "user": {"it": "Inserito da voi", "en": "Entered by you"},
}

SECTION_TITLES = {
    "verified": {"it": "Fatti verificati", "en": "Verified facts"},
    "historical": {"it": "Contesto storico", "en": "Historical context"},
    "estimates": {"it": "Stime", "en": "Estimates"},
    "news": {"it": "Notizie", "en": "News"},
    "quotes": {"it": "Le vostre offerte", "en": "Your supplier offers"},
    "analysis": {"it": "Analisi (IA)", "en": "Analysis (AI)"},
    "forecast": {"it": "Previsioni (IA, incerte)", "en": "Outlook (AI, uncertain)"},
}
AI_SECTIONS = ("verified", "historical", "estimates", "analysis", "forecast")
FACT_SECTIONS = frozenset({"verified", "historical", "estimates"})   # every sentence needs a citation
STATUS_SECTION = {
    "verified_official": "verified", "verified_industry": "verified", "provisional": "verified",
    "historical": "historical", "estimate": "estimates", "press": "news", "user": "quotes",
}
PLAIN_SECTIONS = ("quotes", "verified", "estimates", "historical", "news")

TOPIC_LABELS = {
    "prices": {"it": "prezzi", "en": "prices"},
    "trade": {"it": "commercio", "en": "trade"},
    "production": {"it": "produzione e raccolti", "en": "production and harvest"},
    "news": {"it": "notizie", "en": "news"},
    "report": {"it": "report ufficiali", "en": "official reports"},
    "regulation": {"it": "normative", "en": "regulations"},
    "duties": {"it": "dazi e contingenti", "en": "duties and quotas"},
    "quotes": {"it": "offerte dei fornitori", "en": "supplier offers"},
    "costs": {"it": "costi di acquisto", "en": "purchase costs"},
    "world": {"it": "mercato mondiale", "en": "world market"},
    "fx": {"it": "cambi", "en": "exchange rates"},
    "compare": {"it": "confronto", "en": "comparison"},
}

COLOR_LABELS = {
    "water white": {"it": "bianco acqua", "en": "water white"},
    "extra white": {"it": "extra bianco", "en": "extra white"},
    "white": {"it": "bianco", "en": "white"},
    "extra light amber": {"it": "ambra extra chiaro", "en": "extra light amber"},
    "light amber": {"it": "ambra chiaro", "en": "light amber"},
    "amber": {"it": "ambra", "en": "amber"},
    "amber or darker": {"it": "ambra o più scuro", "en": "amber or darker"},
    "dark amber": {"it": "ambra scuro", "en": "dark amber"},
    "dark": {"it": "scuro", "en": "dark"},
}

DOC_TYPE_LABELS = {
    "regulation": {"it": "regolamento", "en": "regulation"},
    "directive": {"it": "direttiva", "en": "directive"},
    "proposal": {"it": "proposta", "en": "proposal"},
    "antidumping": {"it": "antidumping", "en": "anti-dumping"},
    "food_safety_notification": {"it": "allerta alimentare RASFF", "en": "RASFF food-safety notification"},
    "residue_alert": {"it": "lista residui", "en": "residue list"},
    "export_rule": {"it": "norma sull'export", "en": "export rule"},
    "notice": {"it": "avviso ufficiale", "en": "official notice"},
    "price_floor": {"it": "prezzo minimo all'export", "en": "minimum export price"},
    "tariff": {"it": "tariffa", "en": "tariff"},
    "agreement": {"it": "accordo", "en": "agreement"},
    "import_alert": {"it": "allerta all'import", "en": "import alert"},
}
# Regulation types that can move a purchase cost (proposals and food-safety alerts are handled apart).
COST_DOC_TYPES = ["regulation", "antidumping", "tariff", "price_floor", "export_rule", "agreement", "import_alert",
                  "notice", "residue_alert"]

MEASURE_LABELS = {
    "mfn": {"it": "dazio per i paesi terzi", "en": "third-country duty"},
    "preference": {"it": "dazio preferenziale", "en": "preferential duty"},
    "trq_in": {"it": "dazio nel contingente tariffario", "en": "in-quota duty"},
    "trq_out": {"it": "dazio fuori contingente", "en": "out-of-quota duty"},
    "antidumping": {"it": "dazio antidumping", "en": "anti-dumping duty"},
    "surcharge": {"it": "dazio aggiuntivo", "en": "additional duty"},
    "other": {"it": "misura aggiuntiva", "en": "additional measure"},
}
QUOTA_STATUS = {"exhausted": ("esaurito", "exhausted"), "open": ("aperto", "open"), "critical": ("critico", "critical"),
                "blocked": ("bloccato", "blocked")}
LANDED_MISSING = {
    "freight_missing": ("trasporto", "freight"), "insurance_missing": ("assicurazione", "insurance"),
    "origin_costs_missing": ("costi all'origine", "origin costs"), "incoterm_missing": ("Incoterm", "Incoterm"),
    "fx_missing": ("cambio", "exchange rate"), "duty_unavailable": ("dazio", "duty"),
    "freight_no_quantity": ("quantità per ripartire il trasporto", "quantity to spread the freight"),
    "cost_no_quantity": ("quantità per ripartire i costi", "quantity to spread the costs"),
}

_MONTHS = {
    "it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def _l(lang: str, it: str, en: str) -> str:
    return it if lang == "it" else en


def clock_today() -> date:
    """The assistant's and the briefing's 'today' (one place, patched in tests)."""
    return date.today()


def clock_now() -> datetime:
    """'Now' as naive UTC, like every timestamp in the database (patched in tests)."""
    return utcnow()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _num(v: float, lang: str, digits: int = 2) -> str:
    return ov.fmt_num(v, lang, digits)


def _pct(v: float, lang: str) -> str:
    return ov.fmt_pct(v, lang)


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _date(v: Any, lang: str) -> str:
    d = _as_date(v)
    return ov.fmt_date(d, lang) if d else "—"


def _period(label: str | None, lang: str) -> str:
    if not label:
        return "—"
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})", label)
    if m:
        return _l(lang, f"settimana {int(m.group(2))} del {m.group(1)}", f"week {int(m.group(2))} of {m.group(1)}")
    return ov.fmt_period(label, lang)


def _tonnes(kg: float | None, lang: str) -> str:
    return ov.fmt_tonnes(kg, lang)


def _money(v: float | None, cur: str, lang: str) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e6:
        return f"{_num(v / 1e6, lang, 1)} {_l(lang, 'mln', 'm')} {cur}"
    return f"{_num(v, lang, 0)} {cur}"


def _months_span(m: int, year: int, lang: str) -> str:
    names = _MONTHS[lang]
    return f"{names[0]} {year}" if m == 1 else f"{names[0]}–{names[m - 1]} {year}"


def _clip(text: str | None, n: int) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _terms_hint(terms: str | None, limit: int = 60) -> str | None:
    """First clause of a series' terms ("fusto da 3 q.li", "CIF", "bulk honey, paid to importers"),
    cut at a comma boundary and without a dangling parenthesis."""
    first = (terms or "").split(";")[0].strip()
    if not first:
        return None
    if len(first) > limit:
        cut = first[:limit].rsplit(",", 1)[0].strip()
        first = cut if len(cut) >= 8 else first[:limit].rstrip()
    if first.count("(") > first.count(")"):
        first = first[: first.rfind("(")].strip()
    return first or None


def _pct_duty(m: TariffMeasure, lang: str) -> str:
    """The duty as published, in the reader's number format when it is a plain percentage."""
    txt = (m.duty_text or "").strip()
    if m.ad_valorem_pct is not None and re.fullmatch(r"\d+(?:[.,]\d+)?\s*%", txt):
        digits = 0 if float(m.ad_valorem_pct).is_integer() else 1
        return f"{_num(m.ad_valorem_pct, lang, digits)}%"
    return txt or "—"


def _most_cautious(statuses) -> str | None:
    found = {s for s in statuses if s}
    for s in STATUS_CAUTION:
        if s in found:
            return s
    return next(iter(found), None)


def fact_status(data_status: str | None, reliability: str | None, period_end: date | None, today: date,
                *, stale: bool = False) -> str:
    """verified_official | verified_industry | provisional | estimate | historical | press | user."""
    if reliability == "user" or data_status == "user_entered":
        return "user"
    if reliability in ("trade_press", "aggregator"):
        return "press"
    if data_status in ("estimate", "forecast"):
        return "estimate"
    if data_status == "provisional":
        return "provisional"
    if stale or (period_end is not None and (today - period_end).days > HISTORICAL_DAYS):
        return "historical"
    return "verified_official" if reliability == "official" else "verified_industry"


def _area_name(iso3: str | None, lang: str) -> str:
    if iso3 in ("EU27", "EU28", "EU"):
        return _l(lang, "Unione Europea", "European Union")
    if iso3 == "WLD":
        return _l(lang, "Mondo", "World")
    return country_name(iso3, lang) or (iso3 or "—")


def _jurisdiction_name(code: str | None, lang: str) -> str:
    if not code:
        return "—"
    if code.upper() in ("EU", "EU27"):
        return _l(lang, "Unione Europea", "European Union")
    iso3 = lookup_iso3(code)
    return country_name(iso3, lang) if iso3 else code


def _price_type_label(key: str, lang: str) -> str:
    lab = ov.PRICE_TYPE_LABELS.get(key)
    return lab[lang] if lab else key


# ---------------------------------------------------------------------------
# Understanding the question
# ---------------------------------------------------------------------------


@dataclass
class Period:
    kind: str                      # "days" | "year"
    start: date
    end: date
    days: int | None = None
    year: int | None = None
    label_it: str = ""
    label_en: str = ""

    def label(self, lang: str) -> str:
        return self.label_it if lang == "it" else self.label_en

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days,
                "year": self.year, "label_it": self.label_it, "label_en": self.label_en}


def _days_period(n: int, today: date) -> Period:
    start = today - timedelta(days=n)
    return Period("days", start, today, days=n,
                  label_it=f"ultimi {n} giorni ({ov.fmt_date(start, 'it')} – {ov.fmt_date(today, 'it')})",
                  label_en=f"last {n} days ({ov.fmt_date(start, 'en')} – {ov.fmt_date(today, 'en')})")


def _year_period(y: int, today: date) -> Period:
    current = y == today.year
    return Period("year", date(y, 1, 1), min(date(y, 12, 31), today), year=y,
                  label_it=f"anno {y}" + (" (fino a oggi)" if current else ""),
                  label_en=f"year {y}" + (" (to date)" if current else ""))


@dataclass
class Question:
    text: str
    lang: str
    countries: list[str] = field(default_factory=list)
    eu: bool = False
    jurisdictions: list[str] = field(default_factory=list)   # importing side of a duty question: EU / US
    varieties: list[str] = field(default_factory=list)
    price_types: list[str] = field(default_factory=list)
    topics: set[str] = field(default_factory=set)
    flow: str | None = None
    direction: str | None = None
    period: Period | None = None
    years: list[int] = field(default_factory=list)
    source_keys: list[str] = field(default_factory=list)
    mode: str = "overview"
    llm_entities: bool = False

    @property
    def is_about_quotes(self) -> bool:
        return "quotes" in self.topics

    @property
    def days(self) -> int | None:
        return self.period.days if self.period and self.period.kind == "days" else None

    def understood(self) -> dict:
        lang = self.lang
        return {
            "mode": self.mode,
            "countries": [{"iso3": c, "name": _area_name(c, lang)} for c in self.countries],
            "eu": self.eu,
            "jurisdictions": self.jurisdictions,
            "varieties": [{"key": v, "name": VARIETY_LABELS.get(v, {}).get(lang, v)} for v in self.varieties],
            "price_types": [{"key": p, "name": _price_type_label(p, lang)} for p in self.price_types],
            "topics": [{"key": t, "name": TOPIC_LABELS[t][lang]} for t in sorted(self.topics) if t in TOPIC_LABELS],
            "flow": self.flow,
            "direction": self.direction,
            "period": self.period.to_dict() if self.period else None,
            "years": self.years,
            "sources": self.source_keys,
            "llm_entities": self.llm_entities,
        }


def _rx(p: str) -> re.Pattern:
    return re.compile(p)


TOPIC_PATTERNS: dict[str, re.Pattern] = {
    "prices": _rx(r"\b(?:prezz\w*|price\w*|pricing|quotazion\w*|listin\w*|valor\w* unitar\w*|unit values?|precio\w*|"
                  r"preco\w*|quanto cost\w*|how much)"),
    "trade": _rx(r"\b(?:esport\w*|export\w*|import(?!ant)\w*|commerc\w*|trade|scambi\w*|spedizion\w*|shipments?|"
                 r"volum\w*|flussi|flows?|dogan\w*|customs)"),
    "production": _rx(r"\b(?:produzion\w*|production|produc(?:e|ed|es|ing|tion)|produttiv\w*|raccolt\w*|harvest\w*|"
                      r"alveari|colonie|hives?|colonies|rese\b|resa\b|yields?|cosech\w*|meteo|weather|siccit\w*|"
                      r"drought|fioritur\w*|flowering)"),
    "news": _rx(r"\b(?:notizi\w*|news|novita|articol\w*|stampa|press|headlines?|sviluppi|developments?|"
                r"success[oa]|happen\w*|accadut\w*)"),
    "report": _rx(r"\b(?:report\w*|rapport[oi]\b|bollettin\w*|bulletins?|relazion\w*|pubblicazion\w*|"
                  r"national honey report|riassum\w*|summari[sz]\w*)"),
    "regulation": _rx(r"\b(?:normativ\w*|regolament\w*|regulat\w*|legg[ei]\b|laws?\b|direttiv\w*|directives?|"
                      r"anti-?dumping|rasff|allert\w*|food safety|sicurezza alimentare|certificaz\w*|residu\w*)"),
    "duties": _rx(r"\b(?:dazi\w*|dazio|dut(?:y|ies)|tarif\w*|contingent\w*|tariff quotas?|quote tariffarie|arancel\w*)"),
    "quotes": _rx(r"\b(?:offert[ae]\w*|offers?\b|fornitor\w*|suppliers?|preventiv\w*)"),
    "costs": _rx(r"\b(?:cost[oi] di acquisto|purchas\w* costs?|nostri costi|our costs|costo sbarcato|landed cost|"
                 r"costi\b|costs\b|acquist\w*|buying|procurement)"),
    "fx": _rx(r"\b(?:cambi[oa]?\b|tasso di cambio|exchange rates?|euro[/ -]dollaro|eur ?/ ?usd|dollaro|dollar\b)"),
    "compare": _rx(r"\b(?:confront\w*|compar\w*|rispetto a\b|versus|vs\b|differenz\w*|difference)"),
    "world": _rx(r"\b(?:mercato mondiale|mercati mondiali|mondo|mondiale|world(?:wide)?|global\w*|"
                 r"internazional\w*|international)"),
}
DATA_TOPICS = {"prices", "trade", "production", "regulation", "duties", "fx"}

PRICE_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("import_unit_value", _rx(r"\b(?:valor\w* unitar\w* (?:all'?)?import\w*|import unit values?|"
                              r"prezz\w* (?:all'?)?import\w*|import prices?|\bcif\b)")),
    ("export_unit_value", _rx(r"\b(?:valor\w* unitar\w* (?:all'?)?esport\w*|export unit values?|"
                              r"prezz\w* (?:all'?)?esport\w*|export prices?|\bfob\b)")),
    ("wholesale_bulk", _rx(r"\b(?:ingrosso|all'ingrosso|sfus\w*|bulk|wholesale|fust[oi]\b|drums?|granel|"
                           r"agli importatori|to importers)")),
    ("producer", _rx(r"\b(?:produttor\w*|alla produzione|apicoltor\w*|beekeepers?|producer|farm[- ]gate)")),
    ("retail", _rx(r"\b(?:dettaglio|retail|scaffal\w*|supermercat\w*|consumator\w*|consumer prices?)")),
]
_GENERIC_UNIT_VALUE = _rx(r"\b(?:valor\w* unitar\w*|unit values?)")

# Source names in a question ("report USDA") are a hint, never a country ("USDA" contains "US").
SOURCE_HINTS: list[tuple[re.Pattern, str]] = [
    (_rx(r"\busda\b|national honey report|\bams\b"), "usda_honey_report"),
    (_rx(r"\beurostat\b|\bcomext\b"), "eurostat_comext"),
    (_rx(r"\bfao(?:stat)?\b"), "faostat"),
    (_rx(r"\bcomtrade\b"), "un_comtrade"),
    (_rx(r"\bosservatorio\b|informamiele|\bonm\b"), "onm_informamiele"),
    (_rx(r"\bismea\b"), "ismea_miele"),
    (_rx(r"\bcuneo\b"), "cciaa_cuneo_miele"),
    (_rx(r"\bsiena\b|\barezzo\b"), "cciaa_siena_miele"),
    (_rx(r"\bdg agri\b|commissione europea|european commission"), "ec_honey_market"),
    (_rx(r"\brasff\b"), "rasff_honey"),
    (_rx(r"federal register"), "us_federal_register"),
]
_SOURCE_WORDS = _rx(r"\b(?:usda|fda|ams|fao|faostat|eurostat|comext|comtrade|ismea|federal register)\b")

_EU_WORDS = _rx(r"\b(?:unione europea|european union|union europea|europe[oaie]?|europa|europe)\b")
_EU_CASED = re.compile(r"(?<![\w-])(?:UE|EU)(?![\w])")
_EXTRA_COUNTRY_WORDS = {
    "USA": _rx(r"\b(?:american[oaie]|americans?|statunitens[ei]|stati uniti|united states)\b"),
}
# Short reference names that are also ordinary words in a question ("male", "Turkey" the bird...).
_NAME_STOPWORDS = {"mali", "male", "chad", "niger", "georgia", "jordan", "guinea", "turkey", "chile", "oman"}

_DIR_UP = _rx(r"\b(?:aument\w*|cresc\w*|crebber\w*|salit\w*|rialz\w*|increas\w*|grow\w*|grew|rise|rose|risen|"
              r"higher|piu alt\w*)")
_DIR_DOWN = _rx(r"\b(?:diminu\w*|calat\w*|calo\b|cal[ai]\b|scese|scesi|ridott\w*|ridu\w*|decreas\w*|declin\w*|fell|"
                r"fall\w*|drop\w*|lower|piu bass\w*)")


def _period_from_text(f: str, today: date) -> Period | None:
    m = re.search(r"\b(?:ultim[ie]|last|past|negli ultimi|nelle ultime)\s+(\d{1,3})\s+"
                  r"(giorni|days|settimane|weeks|mesi|months|anni|years)\b", f)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        n_days = n * {"giorni": 1, "days": 1, "settimane": 7, "weeks": 7, "mesi": 30, "months": 30,
                      "anni": 365, "years": 365}[unit]
        return _days_period(max(1, min(n_days, 3650)), today)
    if re.search(r"\b(?:oggi|today|stamattina|this morning)\b", f):
        return _days_period(2, today)
    if re.search(r"\b(?:questa settimana|this week|settimana scorsa|last week|past week|ultima settimana|"
                 r"in settimana|settimana)\b", f):
        return _days_period(EVENT_DAYS, today)
    if re.search(r"\b(?:questo mese|this month|ultimo mese|last month|mese scorso|past month)\b", f):
        return _days_period(30, today)
    if re.search(r"\b(?:quest'anno|quest anno|questo anno|this year|anno in corso|current year|year to date|"
                 r"ytd|da inizio anno)\b", f):
        return _year_period(today.year, today)
    if re.search(r"\b(?:anno scorso|l'anno passato|last year|previous year|anno precedente)\b", f):
        return _year_period(today.year - 1, today)
    return None


def parse_countries(text: str) -> tuple[list[str], bool]:
    """(ISO3 codes in order of mention, EU mentioned). Source names never count as countries."""
    cleaned = _SOURCE_WORDS.sub(" ", fold(text))
    original = re.sub(r"(?i)\b(?:usda|fda|faostat|fao|eurostat|comtrade)\b", " ", text)
    found: list[str] = [c for c in tag_countries(original) if c not in PSEUDO]
    for iso3, rx in _EXTRA_COUNTRY_WORDS.items():
        if iso3 not in found and rx.search(cleaned):
            found.append(iso3)
    # Countries without news keywords: reference names (EN/IT/ES/FR/DE) on 1-3 word n-grams.
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", cleaned)
    taken: set[int] = set()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            if any(j in taken for j in range(i, i + n)):
                continue
            gram = " ".join(words[i:i + n])
            if len(gram) < 4 or gram in _NAME_STOPWORDS:
                continue
            code = lookup_iso3(gram)
            if code and code not in PSEUDO and is_known_iso3(code):
                taken.update(range(i, i + n))
                if code not in found:
                    found.append(code)
    eu = bool(_EU_WORDS.search(cleaned) or _EU_CASED.search(text))
    return found, eu


def parse_varieties(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", fold(text))
    grams = words + [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    out: list[str] = []
    for g in grams:
        v, _organic = normalize_variety(g)
        if v not in (Variety.UNSPECIFIED.value, Variety.OTHER.value) and v not in out:
            out.append(v)
    if Variety.ORGANIC_POLYFLORA.value in out and Variety.POLYFLORA.value in out:
        out.remove(Variety.POLYFLORA.value)
    return out


def parse_question(text: str, lang: str = "it", today: date | None = None) -> Question:
    """Deterministic understanding of a question (no AI involved)."""
    today = today or clock_today()
    lang = lang if lang in ("it", "en") else "it"
    f = fold(text or "")
    q = Question(text=text, lang=lang)
    q.countries, q.eu = parse_countries(text or "")
    q.varieties = parse_varieties(text or "")
    q.topics = {key for key, rx in TOPIC_PATTERNS.items() if rx.search(f)}
    q.price_types = [key for key, rx in PRICE_TYPE_PATTERNS if rx.search(f)]
    if not q.price_types and _GENERIC_UNIT_VALUE.search(f):
        q.price_types = ["import_unit_value", "export_unit_value"]
    if q.price_types:
        q.topics.add("prices")
    q.source_keys = list(dict.fromkeys(key for rx, key in SOURCE_HINTS if rx.search(f)))
    exp = bool(re.search(r"\b(?:esport\w*|export\w*)", f))
    imp = bool(re.search(r"\bimport(?!ant)\w*", f))
    q.flow = "export" if exp and not imp else "import" if imp and not exp else None
    up, down = bool(_DIR_UP.search(f)), bool(_DIR_DOWN.search(f))
    q.direction = "increase" if up and not down else "decrease" if down and not up else None
    q.period = _period_from_text(f, today)
    q.years = sorted({int(y) for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", f)})
    if q.period is None and len(q.years) == 1:
        q.period = _year_period(q.years[0], today)
    # "dazi USA sul miele brasiliano": the United States (or the EU) is the importing side, not an origin.
    if q.topics & {"duties", "regulation"}:
        if "USA" in q.countries and len(q.countries) > 1:
            q.countries.remove("USA")
            q.jurisdictions.append("US")
        if q.eu and q.countries:
            q.jurisdictions.append("EU")
    # "costi" also matches the plain word "costo": with offers in the question it is about the offers.
    if "costs" in q.topics and "quotes" in q.topics:
        q.topics.discard("costs")
    q.mode = _mode(q)
    return q


def _mode(q: Question) -> str:
    t = q.topics
    if "quotes" in t:
        return "quotes"
    if "report" in t and (q.source_keys or not q.countries):
        return "report"
    if q.source_keys and not (t & DATA_TOPICS) and not q.varieties:
        return "report"                     # "Cosa dice l'Osservatorio?"
    if "costs" in t and not q.countries:
        return "costs"
    if "compare" in t and len(q.countries) >= 2:
        return "compare"
    if "world" in t and not q.countries:
        return "events"
    if q.days and q.days <= 31 and not q.countries and not (t & DATA_TOPICS):
        return "events"
    if "trade" in t and not q.countries:
        return "trade_ranking"
    if q.countries:
        return "country"
    if q.varieties or q.price_types or "prices" in t:
        return "prices"
    if "news" in t:
        return "news"
    if t & {"regulation", "duties"}:
        return "regulation"
    if "production" in t:
        return "production"
    if "fx" in t:
        return "fx"
    if "costs" in t:
        return "costs"
    if q.eu:
        return "country"
    return "overview"


ENTITY_SCHEMA = {"countries": ["ISO3"], "varieties": ["polyflora"], "price_types": ["wholesale_bulk"],
                 "topics": ["prices"], "flow": "export|import|null", "period_days": None, "year": None}


def llm_entities(q: Question, today: date | None = None) -> Question:
    """Ask the model to read a question the rules did not understand; keep only validated values."""
    today = today or clock_today()
    system = ("You extract search entities from a question about the world honey market. "
              "countries: ISO 3166 alpha-3 codes of the countries named or implied by an adjective. "
              f"varieties: from {sorted(v.value for v in Variety)}. price_types: from {sorted(PRICE_TYPE_ORDER)}. "
              f"topics: from {sorted(TOPIC_LABELS)}. flow: export, import or null. "
              "period_days: number of past days the question is about, or null. year: a calendar year or null. "
              "Never guess: leave lists empty when unsure.")
    data = llm.complete_json(system, f"Question: {q.text}", ENTITY_SCHEMA, max_tokens=300)
    countries = [c.upper() for c in data.get("countries") or [] if isinstance(c, str)]
    q.countries += [c for c in countries if len(c) == 3 and is_known_iso3(c) and c not in PSEUDO and c not in q.countries]
    valid_v = {v.value for v in Variety} - {Variety.UNSPECIFIED.value, Variety.OTHER.value}
    q.varieties += [v for v in data.get("varieties") or [] if v in valid_v and v not in q.varieties]
    q.price_types += [p for p in data.get("price_types") or [] if p in PRICE_TYPE_ORDER and p not in q.price_types]
    q.topics |= {t for t in data.get("topics") or [] if t in TOPIC_LABELS}
    if q.flow is None and data.get("flow") in ("export", "import"):
        q.flow = data["flow"]
    pd_ = data.get("period_days")
    if q.period is None and isinstance(pd_, int) and not isinstance(pd_, bool) and 0 < pd_ <= 3650:
        q.period = _days_period(pd_, today)
    y = data.get("year")
    if q.period is None and isinstance(y, int) and not isinstance(y, bool) and 1990 <= y <= today.year:
        q.period = _year_period(y, today)
    q.llm_entities = True
    q.mode = _mode(q)
    return q


def _understood_nothing(q: Question) -> bool:
    return not (q.countries or q.varieties or q.price_types or q.topics or q.period or q.source_keys or q.eu)


# ---------------------------------------------------------------------------
# Facts (context blocks)
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    kind: str                           # price | trade | production | news | report | report_text | regulation | duty | fx | quote
    title: str
    text: str
    status: str
    source: dict | None = None
    url: str | None = None              # original document / article / API call
    link: str | None = None             # in-app page
    published_at: str | None = None
    period_label: str | None = None
    unit: str | None = None
    data_status: str | None = None
    reliability: str | None = None
    is_demo: bool = False
    private: bool = False               # supplier data: never sent to the model unless asked about offers
    llm_title: str | None = None        # what the model sees, when different (pseudonymised offers)
    llm_text: str | None = None         # ... or longer (report commentary)
    country: str | None = None
    price_type: str | None = None
    key: str | None = None
    meta: dict = field(default_factory=dict)
    id: int = 0

    @property
    def source_name(self) -> str | None:
        s = self.source or {}
        return s.get("publisher") or s.get("name")

    def basis_text(self) -> str:
        """Everything a sentence citing this block may quote (numbers are checked against it)."""
        parts = [self.title, self.text, self.llm_title or "", self.llm_text or "", self.period_label or "",
                 self.published_at or "", self.unit or ""]
        return "\n".join(p for p in parts if p)

    def to_dict(self, lang: str) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "text": self.text, "status": self.status,
            "status_label": STATUS_LABELS[self.status][lang], "source": self.source, "source_name": self.source_name,
            "url": self.url, "link": self.link, "published_at": self.published_at, "period_label": self.period_label,
            "unit": self.unit, "data_status": self.data_status, "reliability": self.reliability,
            "is_demo": self.is_demo, "private": self.private, "country": self.country, "price_type": self.price_type,
            "change_pct": self.meta.get("change_pct"),
            **({"quote_id": self.meta["quote_id"]} if self.kind == "quote" else {}),
        }

    def to_llm(self) -> dict:
        return {"id": self.id, "type": self.kind, "status": STATUS_LABELS[self.status]["en"],
                "title": self.llm_title or self.title, "text": self.llm_text or self.text,
                "source": self.source_name if not self.private else "(entered by the user)",
                "published": self.published_at, "period": self.period_label, "unit": self.unit}


class FactSet:
    """Numbered facts; a key already present is not added twice."""

    def __init__(self, limit: int = MAX_FACTS):
        self.items: list[Fact] = []
        self.limit = limit
        self._keys: dict[str, Fact] = {}
        self.overflow = 0

    def add(self, fact: Fact | None) -> Fact | None:
        if fact is None:
            return None
        if fact.key and fact.key in self._keys:
            return None
        if len(self.items) >= self.limit:
            self.overflow += 1
            return None
        fact.id = len(self.items) + 1
        self.items.append(fact)
        if fact.key:
            self._keys[fact.key] = fact
        return fact

    def get(self, fid: int) -> Fact | None:
        return self.items[fid - 1] if 1 <= fid <= len(self.items) else None

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class Retriever:
    """Builds facts from the local database. One instance per answer (or briefing language)."""

    def __init__(self, session: Session, lang: str = "it", today: date | None = None, limit: int = MAX_FACTS):
        self.db = session
        self.lang = lang
        self.today = today or clock_today()
        # a day other than today (a briefing written for a given date) is read as of its noon
        self.now = clock_now() if self.today == clock_today() else datetime.combine(self.today, time(12, 0))
        self.facts = FactSet(limit)
        self.notes: list[str] = []
        self._octx: ov.Ctx | None = None
        self._tctx = None
        self._sources: dict[int, Source] | None = None

    # -- shared lookups --------------------------------------------------------
    @property
    def octx(self) -> ov.Ctx:
        if self._octx is None:
            self._octx = ov.Ctx(self.db, self.lang)
            self._octx.today, self._octx.now = self.today, self.now   # the overview's rules on the same day
        return self._octx

    @property
    def tctx(self):
        if self._tctx is None:
            from ..api import trade as tr

            self._tctx = tr.Ctx(self.db, self.today)
        return self._tctx

    @property
    def sources(self) -> dict[int, Source]:
        if self._sources is None:
            self._sources = {s.id: s for s in self.db.scalars(select(Source))}
        return self._sources

    def source_id(self, key: str) -> int | None:
        return next((s.id for s in self.sources.values() if s.key == key), None)

    def country(self, iso3: str | None) -> str:
        return self.octx.country(iso3)

    def t(self, it: str, en: str) -> str:
        return _l(self.lang, it, en)

    def note(self, it: str, en: str) -> None:
        msg = self.t(it, en)
        if msg not in self.notes:
            self.notes.append(msg)

    def add(self, fact: Fact | None) -> bool:
        return self.facts.add(fact) is not None

    # -- prices ------------------------------------------------------------------
    def _variety_name(self, s: ov.PriceSeries) -> str | None:
        if s.variety == Variety.UNSPECIFIED.value:
            return None
        if s.variety == Variety.OTHER.value:
            raw = (s.latest.variety_raw or "").strip()
            return raw[:40] if raw else self.t("altra varietà", "other variety")
        return VARIETY_LABELS.get(s.variety, {}).get(self.lang, s.variety)

    def series_name(self, s: ov.PriceSeries) -> str:
        """'Argentina · Millefiori (bianco)': origin, variety (when stated) and colour grade."""
        origin = self.country(s.origin_iso3) if s.origin_iso3 else (s.latest.origin_label or self.country(s.market_iso3))
        name = origin
        variety = self._variety_name(s)
        if variety:
            name += f" · {variety}"
        if s.color_grade:
            color = COLOR_LABELS.get(s.color_grade, {}).get(self.lang, s.color_grade)
            name += f", {color}" if name.endswith(")") else f" ({color})"
        return name

    def _market(self, s: ov.PriceSeries) -> str | None:
        if not s.market_iso3 or s.market_iso3 == s.origin_iso3:
            return None
        where = self.country(s.market_iso3)
        if s.price_type == "export_unit_value":
            return self.t(f"destinazione: {where}", f"destination: {where}")
        return self.t(f"mercato: {where}", f"market: {where}")

    def _series_rank(self, s: ov.PriceSeries, by_origin: bool) -> tuple:
        recent = s.latest_start >= self.today - timedelta(days=PRICE_RECENT_DAYS)
        rel = s.latest.reliability if s.latest else None
        return ((not recent, 0 if recent else -s.latest_start.toordinal())
                + ((ov._rank(ov.ORIGIN_PRIORITY, s.origin_iso3),) if by_origin else ())
                + (FREQ_PRIORITY.get(s.frequency, 3), ov._rank(MARKET_PRIORITY, s.market_iso3),
                   ov._rank(ov.RELIABILITY_PRIORITY, rel), ov._rank(ov.VARIETY_PRIORITY, s.variety),
                   ov._rank(COLOR_PRIORITY, s.color_grade), -s.latest_start.toordinal(), -s.n_points))

    @staticmethod
    def _changes_at(s: ov.PriceSeries, idx: int) -> dict:
        """m/m and y/y of point `idx` on its own series (same as ov.series_changes, at any point)."""
        pts = s.points
        last = pts[idx]
        freq = last.frequency
        prev_m = prev_y = None
        earlier = ov.same_product(pts[:idx], last)     # never a change from one honey of the bucket to another
        if freq in ("D", "W", "M"):
            prev_m = ov._find_point(earlier, last.period_start - ov.relativedelta(months=1), ov._tolerance(freq))
        if freq in ("D", "W", "M", "Q", "A"):
            prev_y = ov._find_point(earlier, last.period_start - ov.relativedelta(years=1), ov._tolerance(freq))
        return {
            "mom_pct": ov.pct_change(last.price_per_kg, prev_m.price_per_kg) if prev_m else None,
            "mom_period_label": prev_m.period_label if prev_m else None,
            "yoy_pct": ov.pct_change(last.price_per_kg, prev_y.price_per_kg) if prev_y else None,
            "yoy_period_label": prev_y.period_label if prev_y else None,
        }

    def price_fact(self, s: ov.PriceSeries, idx: int = -1, *, note: str | None = None) -> Fact:
        lang = self.lang
        idx = idx if idx >= 0 else len(s.points) - 1
        p = s.points[idx]
        ch = self._changes_at(s, idx)
        src = self.octx.source(s.source_id)
        name = self.series_name(s)
        ptype = _price_type_label(s.price_type, lang).lower()
        market = self._market(s)
        hint = _terms_hint(p.terms)
        head = f"{name} — {ptype}" + (f", {market}" if market else "") + (f" ({hint})" if hint else "")
        cur = p.currency
        bits = []
        if (p.unit or "kg") != "kg":
            pub = f"{_num(p.price_value, lang)} {cur}/{p.unit}"
            if p.price_low is not None and p.price_high is not None and p.price_low != p.price_high:
                pub += self.t(f", intervallo {_num(p.price_low, lang)}–{_num(p.price_high, lang)} {cur}/{p.unit}",
                              f", range {_num(p.price_low, lang)}–{_num(p.price_high, lang)} {cur}/{p.unit}")
            bits.append(self.t(f"come pubblicato: {pub}", f"as published: {pub}"))
        elif p.price_low is not None and p.price_high is not None and p.price_low != p.price_high:
            bits.append(self.t(f"intervallo {_num(p.price_low, lang)}–{_num(p.price_high, lang)} {cur}/kg",
                               f"range {_num(p.price_low, lang)}–{_num(p.price_high, lang)} {cur}/kg"))
        if cur != "EUR" and p.eur_per_kg:
            bits.append(self.t(f"≈ {_num(p.eur_per_kg, lang)} EUR/kg al cambio BCE",
                               f"≈ {_num(p.eur_per_kg, lang)} EUR/kg at the ECB rate"))
        text = f"{head}: {_num(p.price_per_kg, lang)} {cur}/kg" + (f" ({'; '.join(bits)})" if bits else "")
        text += f", {_period(p.period_label, lang)}."
        changes = []
        if ch["mom_pct"] is not None:
            changes.append(self.t(f"{_pct(ch['mom_pct'], lang)} sul mese precedente ({_period(ch['mom_period_label'], lang)})",
                                  f"{_pct(ch['mom_pct'], lang)} on the previous month ({_period(ch['mom_period_label'], lang)})"))
        if ch["yoy_pct"] is not None:
            label = _period(ch["yoy_period_label"], lang)
            changes.append(self.t(f"{_pct(ch['yoy_pct'], lang)} sull'anno precedente ({label})" if p.frequency == "A"
                                  else f"{_pct(ch['yoy_pct'], lang)} sullo stesso periodo dell'anno prima ({label})",
                                  f"{_pct(ch['yoy_pct'], lang)} on the previous year ({label})" if p.frequency == "A"
                                  else f"{_pct(ch['yoy_pct'], lang)} on the same period a year earlier ({label})"))
        if changes:
            text += " " + self.t("Variazione: ", "Change: ") + ", ".join(changes) + "."
        elif p.frequency == "M":
            text += self.t(" Variazione non calcolabile (mancano i periodi di confronto).",
                           " Change not computable (comparison periods missing).")
        if note:
            text += f" {note}"
        # Sub-annual series are judged on their source's rhythm too (a June figure in November is late);
        # an annual figure only on the age of its period (the latest complete year is not "old").
        stale = p.frequency != "A" and ov.item_freshness(p.published_at or p.period_end, src.expected_max_age_days
                                                         if src else None, p.frequency, self.today)["status"] == "stale"
        return Fact(
            kind="price", title=f"{name} · {ptype}" + (f" · {market}" if market else ""), text=text,
            status=fact_status(p.data_status, p.reliability or (src.reliability if src else None), p.period_end,
                               self.today, stale=stale),
            source=source_brief(src), url=p.source_url, link=ov._prices_link(s), published_at=iso(p.published_at),
            period_label=p.period_label, unit=f"{cur}/kg", data_status=p.data_status, reliability=p.reliability,
            is_demo=p.is_demo, country=s.origin_iso3, price_type=s.price_type,
            key="price:" + "|".join("" if k is None else str(k) for k in s.key) + f"@{p.period_label}",
            meta={"change_pct": ch["mom_pct"]},
        )

    def _usable_series(self, pool: list[ov.PriceSeries]) -> list[ov.PriceSeries]:
        """Series not older than PRICE_MAX_AGE_DAYS (a 2014 producer price says nothing about today)."""
        oldest = self.today - timedelta(days=PRICE_MAX_AGE_DAYS)
        return [s for s in pool if s.latest_start >= oldest]

    def price_facts(self, *, origins: list[str] | None = None, varieties: list[str] | None = None,
                    price_types: list[str] | None = None, caps: dict | None = None, markets: list[str] | None = None,
                    max_total: int | None = None) -> int:
        """Latest point of the best series per price type (each fact one series, never mixed)."""
        pool = self._usable_series([
            s for s in self.octx.price_series()
            if (not origins or s.origin_iso3 in origins) and (not varieties or s.variety in varieties)
            and (not price_types or s.price_type in price_types) and (not markets or s.market_iso3 in markets)])
        caps = caps or PRICE_CAPS
        by_origin = not origins or len(origins) > 1
        by_type: dict[str, list[ov.PriceSeries]] = defaultdict(list)
        for s in pool:
            by_type[s.price_type].append(s)
        recent_from = self.today - timedelta(days=PRICE_RECENT_DAYS)
        added = 0
        for pt in PRICE_TYPE_ORDER:
            cands = sorted(by_type.get(pt, []), key=lambda s: self._series_rank(s, by_origin))
            chosen: list[ov.PriceSeries] = []
            for s in cands:
                if len(chosen) >= caps.get(pt, 1):
                    break
                # weekly surveillance values only when no monthly series covers the same origin
                if s.frequency in ("W", "D") and any(c.frequency == "M" and c.origin_iso3 == s.origin_iso3 for c in cands):
                    continue
                # several origins: one series per origin and type
                if by_origin and any(c.origin_iso3 == s.origin_iso3 for c in chosen):
                    continue
                # an old series only when no recent one of this type exists for the origin
                if s.latest_start < recent_from and any(c.origin_iso3 == s.origin_iso3 and c.latest_start >= recent_from
                                                        for c in cands):
                    continue
                chosen.append(s)
            for s in chosen:
                if max_total is not None and added >= max_total:
                    return added
                added += self.add(self.price_fact(s))
        return added

    def compare_price_facts(self, countries: list[str]) -> int:
        """Series with the same source, type, market, frequency, currency, variety, grade and terms for
        every country, read at their latest COMMON period: the only directly comparable prices."""
        groups: dict[tuple, dict[str, ov.PriceSeries]] = defaultdict(dict)
        recent = self.today - timedelta(days=PRICE_RECENT_DAYS)
        for s in self.octx.price_series():
            if s.origin_iso3 not in countries or s.latest_start < recent:
                continue
            k = (s.source_id, s.price_type, s.market_iso3, s.frequency, s.currency, s.variety, s.color_grade, s.terms)
            cur = groups[k].get(s.origin_iso3)
            if cur is None or s.latest_start > cur.latest_start:
                groups[k][s.origin_iso3] = s
        common = [k for k, d in groups.items() if len(d) == len(countries)]

        def rank(k: tuple) -> tuple:
            src = self.octx.source(k[0])
            return (ov._rank(PRICE_TYPE_ORDER, k[1]), FREQ_PRIORITY.get(k[3], 3), ov._rank(MARKET_PRIORITY, k[2]),
                    ov._rank(ov.RELIABILITY_PRIORITY, src.reliability if src else None))

        added = 0
        for k in sorted(common, key=rank)[:3]:
            d = groups[k]
            periods = set.intersection(*({p.period_start for p in d[c].points} for c in countries))
            if not periods:
                continue
            when = max(periods)
            for c in countries:
                s = d[c]
                idx = next(i for i, p in enumerate(s.points) if p.period_start == when)
                note = None
                if idx != len(s.points) - 1:
                    note = self.t(f"(Periodo comune del confronto; il dato più recente di questa serie è "
                                  f"{_period(s.latest.period_label, self.lang)}.)",
                                  f"(Common period of the comparison; this series' newest figure is "
                                  f"{_period(s.latest.period_label, self.lang)}.)")
                added += self.add(self.price_fact(s, idx, note=note))
        if not common:
            names = ", ".join(self.country(c) for c in countries)
            self.note(f"Nessuna serie di prezzo con stessa fonte, tipo, mercato e periodo per {names}: i prezzi "
                      f"mostrati non sono direttamente confrontabili tra loro.",
                      f"No price series with the same source, type, market and period for {names}: the prices "
                      f"shown are not directly comparable with each other.")
        return added

    def price_moves(self, *, days: int = ov.PRICE_RECENT_DAYS, min_pct: float = ov.PRICE_MOVE_MIN_PCT, cap: int = 5,
                    origins: list[str] | None = None, price_types: tuple[str, ...] | None = None) -> int:
        """Monthly price moves of the latest published month, one per origin and price type (weekly
        surveillance values are never 'moves', as in the overview)."""
        recent_from = self.today - timedelta(days=days)
        moves = []
        for s in self.octx.price_series():
            if s.latest_start < recent_from or s.frequency not in ov.MOVE_FREQUENCIES:
                continue
            if (origins and s.origin_iso3 not in origins) or (price_types and s.price_type not in price_types):
                continue
            ch = ov.series_changes(s)
            if ch["mom_pct"] is not None and abs(ch["mom_pct"]) >= min_pct:
                moves.append((s, ch))
        moves.sort(key=lambda m: (ov._rank(PRICE_TYPE_ORDER, m[0].price_type), ov._rank(ov.ORIGIN_PRIORITY, m[0].origin_iso3),
                                  ov._rank(MARKET_PRIORITY, m[0].market_iso3), -abs(m[1]["mom_pct"])))
        added, seen = 0, set()
        for s, _ch in moves:
            k = (s.price_type, s.origin_iso3)
            if added >= cap or k in seen:
                continue
            seen.add(k)
            added += self.add(self.price_fact(s))
        return added

    # -- trade -------------------------------------------------------------------
    def _trade_total_fact(self, row: dict, flow: str) -> Fact:
        lang = self.lang
        name = self.country(row["iso3"])
        what = self.t("esportazioni totali di miele" if flow == "export" else "importazioni totali di miele",
                      "total honey exports" if flow == "export" else "total honey imports")
        text = f"{name} — {what} {row['year']}: {_tonnes(row['net_weight_kg'], lang)}"
        extra = []
        if row.get("usd_value"):
            extra.append(_money(row["usd_value"], "USD", lang))
        if row.get("unit_value_usd_per_kg"):
            extra.append(self.t(f"valore unitario {_num(row['unit_value_usd_per_kg'], lang)} USD/kg",
                                f"unit value {_num(row['unit_value_usd_per_kg'], lang)} USD/kg"))
        if extra:
            text += f" ({'; '.join(extra)})"
        prev = row.get("prev")
        if prev and prev.get("net_weight_kg") is not None:
            text += f"; {prev['year']}: {_tonnes(prev['net_weight_kg'], lang)}"
            if row.get("yoy_volume_pct") is not None:
                text += f" ({_pct(row['yoy_volume_pct'], lang)})"
        text += "."
        if row.get("summed_from_partners"):
            text += self.t(" Totale ottenuto sommando i paesi partner dichiarati.", " Total summed from the declared partner countries.")
        if row.get("summed_from_months"):
            text += self.t(" Totale annuo sommato dai dati mensili.", " Annual total summed from monthly data.")
        return Fact(kind="trade", title=f"{name} · {what} · {row['year']}", text=text,
                    status=fact_status(row.get("data_status"), row.get("reliability"), _as_date(row.get("period_end")), self.today),
                    source=row.get("source"), url=row.get("source_url"), link=f"/paesi/{row['iso3']}",
                    published_at=row.get("published_at"), period_label=str(row["year"]), unit="t",
                    data_status=row.get("data_status"), reliability=row.get("reliability"),
                    is_demo=bool(row.get("is_demo")), country=row["iso3"], key=f"trade:{row['iso3']}:{flow}:{row['year']}",
                    meta={"change_pct": row.get("yoy_volume_pct")})

    def trade_country_facts(self, iso3: str, flows: tuple[str, ...] = ("export", "import")) -> int:
        """Latest complete year of the country's own declarations (the flow that matters for it)."""
        from ..api import trade as tr

        totals = tr.Totals(self.tctx, flows=list(flows), reporters=[iso3])
        rows = {}
        for flow in flows:
            c = totals.latest_complete(iso3, flow)
            if c is not None:
                rows[flow] = tr.candidate_total(self.tctx, c, totals)
        if len(rows) == 2:   # an origin's imports (or a market's exports) are negligible: keep the one that matters
            e, i = rows["export"].get("net_weight_kg") or 0, rows["import"].get("net_weight_kg") or 0
            if e < 0.1 * i:
                rows.pop("export")
            elif i < 0.1 * e:
                rows.pop("import")
        return sum(self.add(self._trade_total_fact(row, flow)) for flow, row in rows.items())

    def _monthly(self, *, source_key: str, flow: str, year: int, reporter: str | None = None,
                 partner: str | None = None, by: str = "partner") -> tuple[dict, dict] | None:
        """{key: {(year, month): [kg, value]}} + meta, for monthly rows of one source (years year-1, year)."""
        sid = self.source_id(source_key)
        if sid is None:
            return None
        T = TradeFlowObservation
        key_col = T.partner_iso3 if by == "partner" else T.reporter_iso3
        conds = [T.is_current.is_(True), demo_clause(T, self.db), T.source_id == sid, T.flow == flow,
                 T.frequency == "M", T.period_start >= date(year - 1, 1, 1), T.period_start < date(year + 1, 1, 1)]
        if reporter:
            conds.append(T.reporter_iso3 == reporter)
        if partner:
            conds.append(T.partner_iso3 == partner)
        q = (select(key_col, T.period_start, func.sum(T.net_weight_kg), func.sum(T.value), func.min(T.currency),
                    func.max(T.currency), func.max(T.published_at), func.group_concat(T.data_status.distinct()),
                    func.max(T.is_demo), func.max(T.source_url))
             .where(*conds).group_by(key_col, T.period_start))
        data: dict[str, dict] = defaultdict(dict)
        meta = {"published_at": None, "statuses": set(), "is_demo": False, "currencies": set(), "url": None, "sid": sid}
        for k, start, kg, val, c1, c2, pub, sts, demo, url in self.db.execute(q):
            data[k][(start.year, start.month)] = [kg or 0.0, val]
            meta["currencies"] |= {c for c in (c1, c2) if c}
            if pub and (meta["published_at"] is None or pub > meta["published_at"]):
                meta["published_at"] = pub
            meta["statuses"] |= set((sts or "").split(","))
            meta["is_demo"] = meta["is_demo"] or bool(demo)
            meta["url"] = meta["url"] or url
        return data, meta

    @staticmethod
    def _ytd_months(data: dict, year: int) -> int:
        """Largest m such that months 1..m of `year` and of `year-1` are all published (any key)."""
        have = {ym for d in data.values() for ym in d}
        m = 0
        while m < 12 and (year, m + 1) in have and (year - 1, m + 1) in have:
            m += 1
        return m

    def ytd_by_key(self, *, source_key: str, flow: str, year: int, reporter: str | None = None,
                   partner: str | None = None, by: str = "partner") -> list[dict]:
        """Year-to-date totals per partner (or reporter): the same published months of `year` and `year-1`."""
        got = self._monthly(source_key=source_key, flow=flow, year=year, reporter=reporter, partner=partner, by=by)
        if not got:
            return []
        data, meta = got
        m = self._ytd_months(data, year)
        if m == 0:
            return []
        out = []
        ccy = next(iter(meta["currencies"])) if len(meta["currencies"]) == 1 else None
        for k, d in data.items():
            if k in PSEUDO and partner is None:
                continue
            cur = [d.get((year, i)) for i in range(1, m + 1)]
            prev = [d.get((year - 1, i)) for i in range(1, m + 1)]
            cur_kg = sum(x[0] for x in cur if x)
            prev_kg = sum(x[0] for x in prev if x)
            vals = [x[1] for x in cur if x]
            cur_val = sum(vals) if vals and all(v is not None for v in vals) else None
            out.append({"key": k, "year": year, "months": m, "cur_kg": cur_kg, "prev_kg": prev_kg,
                        "pct": ov.pct_change(cur_kg, prev_kg) if prev_kg else None,
                        "uv": (cur_val / cur_kg) if cur_val and cur_kg and ccy else None, "currency": ccy,
                        "published_at": meta["published_at"], "data_status": _most_cautious(meta["statuses"]),
                        "is_demo": meta["is_demo"], "url": meta["url"], "sid": meta["sid"]})
        return out

    def _ytd_fact(self, r: dict, *, what_it: str, what_en: str, key: str, country: str | None) -> Fact:
        lang = self.lang
        span = _months_span(r["months"], r["year"], lang)
        prev_span = _months_span(r["months"], r["year"] - 1, lang)
        text = f"{self.t(what_it, what_en)}, {span}: {_tonnes(r['cur_kg'], lang)}"
        if r["uv"]:
            text += self.t(f" (valore unitario medio {_num(r['uv'], lang)} {r['currency']}/kg)",
                           f" (average unit value {_num(r['uv'], lang)} {r['currency']}/kg)")
        text += f"; {prev_span}: {_tonnes(r['prev_kg'], lang)}"
        if r["pct"] is not None:
            text += f" ({_pct(r['pct'], lang)})"
        text += "."
        src = self.sources.get(r["sid"])
        return Fact(kind="trade", title=f"{self.t(what_it, what_en)} · {span}", text=text,
                    status=fact_status(r["data_status"], src.reliability if src else None, None, self.today),
                    source=source_brief(src), url=r["url"], link="/commercio", published_at=iso(r["published_at"]),
                    period_label=span, unit="t", data_status=r["data_status"],
                    reliability=src.reliability if src else None, is_demo=r["is_demo"], country=country, key=key,
                    meta={"change_pct": r["pct"]})

    def _eu_import_fact(self, r: dict) -> Fact:
        name = self.country(r["key"])
        f = self._ytd_fact(r, what_it=f"Importazioni UE (27 paesi) di miele da {name}",
                           what_en=f"EU (27) honey imports from {name}",
                           key=f"ytd:EU27:import:{r['key']}:{r['year']}", country=r["key"])
        f.text += self.t(" Dato dichiarato dall'UE (Eurostat), non dal paese d'origine.",
                         " Declared by the EU (Eurostat), not by the origin country.")
        return f

    def eu_imports_ytd_facts(self, partners: list[str], year: int | None = None) -> int:
        year = year or self.today.year
        rows = self.ytd_by_key(source_key="eurostat_comext", flow="import", year=year, reporter="EU27")
        if not rows and year == self.today.year:
            rows = self.ytd_by_key(source_key="eurostat_comext", flow="import", year=year - 1, reporter="EU27")
        return sum(self.add(self._eu_import_fact(r)) for r in rows if r["key"] in partners)

    def trade_ranking_facts(self, flow: str, direction: str, year: int) -> int:
        """Which countries' exports (or imports) rose / fell: the months already published this year
        (EU import declarations as the mirror of exports to the EU; Brazil's own monthly exports),
        then the latest complete year each country declared. Ranked by the change in tonnes."""
        from ..api import trade as tr

        sign = -1 if direction == "decrease" else 1
        added = 0
        if flow == "export":
            rows = self.ytd_by_key(source_key="eurostat_comext", flow="import", year=year, reporter="EU27")
            big = [r for r in rows if r["cur_kg"] >= YTD_MIN_KG or r["prev_kg"] >= YTD_MIN_KG]
            big = [r for r in big if r["prev_kg"] > 0]
            sel = sorted((r for r in big if sign * (r["cur_kg"] - r["prev_kg"]) > 0),
                         key=lambda r: -sign * (r["cur_kg"] - r["prev_kg"]))
            for r in sel[:6]:
                added += self.add(self._eu_import_fact(r))
            if big:
                ups = sum(1 for r in big if r["cur_kg"] > r["prev_kg"])
                span = _months_span(big[0]["months"], year, self.lang)
                self.note(f"Esportazioni verso l'UE, {span}: {ups} origini su {len(big)} (oltre 500 t) in aumento sugli "
                          f"stessi mesi del {year - 1}, secondo le importazioni dichiarate dall'UE.",
                          f"Exports to the EU, {span}: {ups} of {len(big)} origins (above 500 t) up on the same months "
                          f"of {year - 1}, according to the imports declared by the EU.")
            elif year == self.today.year:
                self.note(f"Per il {year} non ci sono ancora dati mensili di commercio nel database.",
                          f"There are no monthly trade data for {year} in the database yet.")
            for r in self.ytd_by_key(source_key="br_comexstat", flow="export", year=year, by="reporter"):
                if r["key"] not in PSEUDO and r["prev_kg"] and sign * (r["cur_kg"] - r["prev_kg"]) > 0:
                    name = self.country(r["key"])
                    added += self.add(self._ytd_fact(r, what_it=f"{name} — esportazioni di miele dichiarate",
                                                     what_en=f"{name} — declared honey exports",
                                                     key=f"ytd:{r['key']}:export:{r['year']}", country=r["key"]))
        # latest complete calendar year, as each country declared it (top 20 by volume)
        lead = tr.trade_leaders(flow=flow, year=None, metric="volume", basis="declared", limit=300, db=self.db)
        top = [r for r in lead.get("rows", [])[:20] if r.get("prev") and r["prev"].get("net_weight_kg") is not None]
        sel = sorted((r for r in top if sign * (r["net_weight_kg"] - r["prev"]["net_weight_kg"]) > 0),
                     key=lambda r: -sign * (r["net_weight_kg"] - r["prev"]["net_weight_kg"]))
        for r in sel[:5]:
            added += self.add(self._trade_total_fact(r, flow))
        if lead.get("year"):
            self.note(f"Ultimo anno completo con dati annuali dichiarati: {lead['year']} (tra i primi 20 paesi per volume).",
                      f"Latest complete year of declared annual data: {lead['year']} (among the top 20 countries by volume).")
        if year == self.today.year:
            self.note(f"Per il {year} non esiste ancora un totale annuale: uso i mesi già pubblicati, confrontati con gli "
                      f"stessi mesi del {year - 1}.",
                      f"There is no annual total for {year} yet: the months already published are compared with the "
                      f"same months of {year - 1}.")
        return added

    # -- production --------------------------------------------------------------
    def production_facts(self, iso3s: list[str] | None = None, top: int | None = None,
                         published_since: date | None = None) -> int:
        """Latest annual production per country (the source covering most countries), with the year before."""
        from ..api.countries import TONNES_PER_UNIT

        P = ProductionStat
        q = select(P).where(P.is_current.is_(True), demo_clause(P, self.db), P.metric == "production", P.frequency == "A")
        if iso3s:
            q = q.where(P.country_iso3.in_(iso3s))
        series: dict[tuple[str, int], list] = defaultdict(list)
        coverage: dict[int, set] = defaultdict(set)
        for r in self.db.scalars(q.order_by(P.period_start)):
            if (r.unit or "").lower() in TONNES_PER_UNIT and r.country_iso3 not in PSEUDO:
                series[(r.country_iso3, r.source_id)].append(r)
                coverage[r.source_id].add(r.country_iso3)
        best: dict[str, list] = {}
        for (c, sid), rows in series.items():
            k = (len(coverage[sid]), rows[-1].period_start)
            if c not in best or k > (len(coverage[best[c][0].source_id]), best[c][-1].period_start):
                best[c] = rows
        items = list(best.items())
        if published_since:
            items = [kv for kv in items if kv[1][-1].published_at and kv[1][-1].published_at >= published_since]
        if top:
            items.sort(key=lambda kv: -(kv[1][-1].value * TONNES_PER_UNIT[kv[1][-1].unit.lower()]))
            items = items[:top]
        elif iso3s:
            items.sort(key=lambda kv: iso3s.index(kv[0]))
        added = 0
        for c, rows in items:
            last = rows[-1]
            t = last.value * TONNES_PER_UNIT[last.unit.lower()]
            prev = next((r for r in reversed(rows[:-1]) if r.period_start.year == last.period_start.year - 1), None)
            src = self.sources.get(last.source_id)
            name = self.country(c)
            text = self.t(f"{name} — produzione di miele {last.period_label}: {_num(t, self.lang, 0)} t",
                          f"{name} — honey production {last.period_label}: {_num(t, self.lang, 0)} t")
            ch = None
            if prev is not None:
                pt = prev.value * TONNES_PER_UNIT[prev.unit.lower()]
                text += f"; {prev.period_label}: {_num(pt, self.lang, 0)} t"
                ch = ov.pct_change(t, pt)
                if ch is not None:
                    text += f" ({_pct(ch, self.lang)})"
            text += "."
            if last.data_status in ("estimate", "forecast"):
                text += self.t(" Il dato più recente è una stima della fonte.", " The latest figure is the source's estimate.")
            added += self.add(Fact(
                kind="production", title=self.t(f"{name} · produzione", f"{name} · production"), text=text,
                status=fact_status(last.data_status, last.reliability, last.period_end, self.today),
                source=source_brief(src), url=last.source_url, link=f"/paesi/{c}", published_at=iso(last.published_at),
                period_label=last.period_label, unit="t", data_status=last.data_status, reliability=last.reliability,
                is_demo=last.is_demo, country=c, key=f"prod:{c}:{last.period_label}", meta={"change_pct": ch}))
        return added

    # -- news ----------------------------------------------------------------------
    def news_facts(self, *, countries: list[str] | None = None, days: int = NEWS_DAYS, limit: int = NEWS_LIMIT,
                   min_relevance: int = 0) -> int:
        N = NewsArticle
        q = select(N).where(N.duplicate_of_id.is_(None), demo_clause(N, self.db),
                            ov._news_since(self.now - timedelta(days=days)))
        if countries:
            q = q.where(or_(*[cast(N.countries, String).like(f'%"{c}"%') for c in countries]))
        if min_relevance:
            q = q.where(N.relevance_score >= min_relevance)
        rows = self.db.scalars(q.order_by(N.relevance_score.desc(), func.coalesce(N.published_at, N.collected_at).desc())
                               .limit(limit)).all()
        return sum(self.add(self.news_fact(a)) for a in rows)

    def news_fact(self, a: NewsArticle) -> Fact:
        """A news item is a press report (never a verified fact), attributed to its outlet."""
        title, title_ai = ov._news_title(a, self.lang)
        src = self.sources.get(a.source_id)
        publisher = a.publisher or (src.publisher if src else None) or (src.name if src else "—")
        when = a.published_at or a.collected_at
        text = f"{publisher}, {_date(when, self.lang)}: «{title}»"
        if title_ai:
            text += self.t(" (titolo tradotto con IA)", " (headline translated by AI)")
        if a.snippet:
            text += self.t(" — estratto della fonte: ", " — source excerpt: ") + _clip(a.snippet, 240)
        return Fact(kind="news", title=title, text=text, status="press", source=source_brief(src), url=a.url,
                    link="/notizie", published_at=iso(_as_date(when)), reliability=src.reliability if src else None,
                    is_demo=a.is_demo, country=(a.countries or [None])[0], key=f"news:{a.id}",
                    meta={"relevance": a.relevance_score})

    # -- reports -------------------------------------------------------------------
    def _report_pub(self, r: Report) -> date:
        return r.published_at or r.collected_at.date()

    def _report_url(self, r: Report) -> str | None:
        return f"/api/reports/{r.id}/file" if r.raw_document_id else r.url

    def report_fact(self, r: Report) -> Fact:
        src = self.sources.get(r.source_id)
        pub = self._report_pub(r)
        when = self.t(f"pubblicato il {_date(pub, self.lang)}", f"published on {_date(pub, self.lang)}") if r.published_at \
            else self.t(f"raccolto il {_date(pub, self.lang)} (data di pubblicazione non indicata)",
                        f"collected on {_date(pub, self.lang)} (publication date not given)")
        text = f"{src.name if src else '—'}: «{r.title}», {when}"
        if r.period_label:
            text += self.t(f" (periodo dei dati: {_period(r.period_label, self.lang)})",
                           f" (data period: {_period(r.period_label, self.lang)})")
        text += "."
        status = "historical" if (self.today - pub).days > 120 else \
            fact_status("published", src.reliability if src else None, None, self.today)
        return Fact(kind="report", title=r.title, text=text, status=status, source=source_brief(src),
                    url=self._report_url(r), link="/notizie", published_at=iso(r.published_at), period_label=r.period_label,
                    reliability=src.reliability if src else None, is_demo=r.is_demo, key=f"report:{r.id}",
                    meta={"original_url": r.url})

    def report_text_fact(self, r: Report) -> Fact | None:
        """The report's own market commentary (verbatim excerpt), when it has one."""
        if not r.narrative:
            return None
        src = self.sources.get(r.source_id)
        pub = self._report_pub(r)
        own = self.t("testo originale della fonte" + (", in inglese" if src and src.language == "en" else ""),
                     "the source's own text")
        lead = self.t(f"Commento di mercato del report «{r.title}» ({own}): ", f"Market commentary of the report “{r.title}” ({own}): ")
        status = "historical" if (self.today - pub).days > 120 else \
            fact_status("published", src.reliability if src else None, None, self.today)
        return Fact(kind="report_text", title=self.t(f"Commento — {r.title}", f"Commentary — {r.title}"),
                    text=lead + _clip(r.narrative, NARRATIVE_SHOWN_CHARS), llm_text=lead + _clip(r.narrative, NARRATIVE_CHARS),
                    status=status, source=source_brief(src), url=self._report_url(r), link="/notizie",
                    published_at=iso(r.published_at), period_label=r.period_label,
                    reliability=src.reliability if src else None, is_demo=r.is_demo, key=f"report_text:{r.id}")

    def _reports(self, source_keys: list[str] | None, days: int | None, limit: int) -> list[Report]:
        R = Report
        q = select(R).where(demo_clause(R, self.db))
        if source_keys:
            ids = [i for i in (self.source_id(k) for k in source_keys) if i is not None]
            if not ids:
                return []
            q = q.where(R.source_id.in_(ids))
        if days:
            since = self.today - timedelta(days=days)
            q = q.where(or_(R.published_at >= since, R.published_at.is_(None)
                            & (R.collected_at >= datetime.combine(since, datetime.min.time()))))
        return list(self.db.scalars(q.order_by(func.coalesce(R.published_at, func.date(R.collected_at)).desc(),
                                               R.collected_at.desc()).limit(limit)))

    def latest_report_facts(self, source_keys: list[str]) -> int:
        """'Riassumi l'ultimo report USDA': the newest report of the source, its commentary and the prices
        it published (one per origin and type); an older commentary is mentioned, never passed off as new."""
        rows = self._reports(source_keys, None, 30)
        if not rows:
            return 0
        latest = rows[0]
        added = self.add(self.report_fact(latest))
        if latest.narrative:
            added += self.add(self.report_text_fact(latest))
        else:
            self.note(f"Il report più recente («{latest.title}») non contiene un testo di commento: sono disponibili le "
                      f"sue tabelle dei prezzi.",
                      f"The latest report (“{latest.title}”) contains no commentary text: its price tables are available.")
            older = next((r for r in rows[1:] if r.narrative), None)
            if older is not None:
                pub = self._report_pub(older)
                if (self.today - pub).days <= REPORT_TEXT_MAX_AGE_DAYS:
                    added += self.add(self.report_fact(older)) + self.add(self.report_text_fact(older))
                    self.note(f"Il commento più recente è quello del report pubblicato il {_date(pub, 'it')}: è mostrato "
                              f"come contesto.",
                              f"The most recent commentary is that of the report published on {_date(pub, 'en')}: shown "
                              f"as context.")
                else:
                    self.note(f"L'ultimo commento di mercato disponibile risale al report pubblicato il {_date(pub, 'it')}: "
                              f"troppo vecchio per descrivere il mercato di oggi, non è riportato.",
                              f"The latest market commentary available is in the report published on {_date(pub, 'en')}: "
                              f"too old to describe today's market, it is not quoted.")
        return added + self.report_price_facts(latest)

    def report_facts(self, days: int, limit: int = 4) -> int:
        """Reports published in the window, with their commentary when recent."""
        added = 0
        for r in self._reports(None, days, limit):
            added += self.add(self.report_fact(r))
            if r.narrative and (self.today - self._report_pub(r)).days <= 60:
                added += self.add(self.report_text_fact(r))
        return added

    def report_price_facts(self, r: Report, cap: int = 8) -> int:
        """The prices published in one report (its archived document), one per origin and type."""
        if not r.raw_document_id:
            return 0
        wanted = [(s, i) for s in self.octx.price_series() for i, p in enumerate(s.points)
                  if p.raw_document_id == r.raw_document_id and i == len(s.points) - 1
                  and s.price_type in ("wholesale_bulk", "producer", "import_unit_value")]
        wanted.sort(key=lambda si: (ov._rank(PRICE_TYPE_ORDER, si[0].price_type), ov._rank(ov.ORIGIN_PRIORITY, si[0].origin_iso3),
                                    ov._rank(ov.VARIETY_PRIORITY, si[0].variety), ov._rank(COLOR_PRIORITY, si[0].color_grade)))
        added, seen = 0, set()
        for s, i in wanted:
            k = (s.price_type, s.origin_iso3)
            if k in seen or added >= cap:
                continue
            seen.add(k)
            added += self.add(self.price_fact(s, i))
        return added

    # -- regulations and duties --------------------------------------------------
    def regulation_fact(self, r: RegulationItem) -> Fact:
        src = self.sources.get(r.source_id)
        dt = DOC_TYPE_LABELS.get(r.doc_type, {}).get(self.lang, r.doc_type)
        pub = r.published_at or r.collected_at.date()
        ref = (r.reference or "").strip()
        ref = ref if ref and len(ref) <= 40 and ":/" not in ref else ""
        text = f"{_jurisdiction_name(r.jurisdiction, self.lang)} — {dt}: «{_clip(r.title, 220)}»" + (f" ({ref})" if ref else "")
        text += ", " + self.t(f"pubblicato il {_date(pub, self.lang)}", f"published on {_date(pub, self.lang)}")
        if r.status:
            text += self.t(f", stato: {r.status}", f", status: {r.status}")
        text += "."
        return Fact(kind="regulation", title=_clip(r.title, 160), text=text,
                    status=fact_status("published", src.reliability if src else None, None, self.today),
                    source=source_brief(src), url=r.url, link="/normative", published_at=iso(pub),
                    reliability=src.reliability if src else None, is_demo=r.is_demo,
                    country=(r.countries or [None])[0], key=f"reg:{r.id}")

    def regulation_facts(self, *, countries: list[str] | None = None, days: int = REG_DAYS, limit: int = 5,
                         doc_types: list[str] | None = None, exclude_types: list[str] | None = None,
                         jurisdictions: list[str] | None = None) -> int:
        R = RegulationItem
        since = self.today - timedelta(days=days)
        q = select(R).where(demo_clause(R, self.db), or_(R.published_at >= since, R.published_at.is_(None)
                                                          & (R.collected_at >= datetime.combine(since, datetime.min.time()))))
        if countries:
            q = q.where(or_(*[cast(R.countries, String).like(f'%"{c}"%') for c in countries]))
        if doc_types:
            q = q.where(R.doc_type.in_(doc_types))
        if exclude_types:
            q = q.where(R.doc_type.not_in(exclude_types))
        if jurisdictions:
            q = q.where(R.jurisdiction.in_(jurisdictions))
        rows = self.db.scalars(q.order_by(R.published_at.desc().nulls_last(), R.id.desc()).limit(limit)).all()
        return sum(self.add(self.regulation_fact(r)) for r in rows)

    def _duty_fact(self, m: TariffMeasure, origins: list[str]) -> Fact:
        """One measure; a tariff quota shared by several origins is ONE fact naming all of them."""
        lang = self.lang
        src = self.sources.get(m.source_id)
        who = _jurisdiction_name(m.jurisdiction, lang)
        what = MEASURE_LABELS.get(m.measure_type, MEASURE_LABELS["other"])[lang]
        general = m.origin_iso3 in GENERAL_ORIGINS
        scope = self.t("tutti i paesi terzi", "all third countries") if general else ", ".join(self.country(o) for o in origins)
        if m.quota_order_number:
            inside = {"trq_in": ("dazio nel contingente", "in-quota duty"),
                      "trq_out": ("dazio fuori contingente", "out-of-quota duty")}.get(m.measure_type, (what, what))
            text = self.t(f"{who} — contingente tariffario {m.quota_order_number} ({scope}): {inside[0]} {_pct_duty(m, lang)}",
                          f"{who} — tariff quota {m.quota_order_number} ({scope}): {inside[1]} {_pct_duty(m, lang)}")
        else:
            text = f"{who} — {what} ({scope}): {_pct_duty(m, lang)}"
        if m.hs_code and m.hs_code.endswith("0010"):
            text += self.t(" (solo miele di Mānuka)", " (Mānuka honey only)")
        if m.quota_order_number:
            from .tariffs import quota_fill_pct

            if m.quota_volume_kg is not None and m.quota_balance_kg is not None:
                text += self.t(f"; residuo {_tonnes(m.quota_balance_kg, lang)} su {_tonnes(m.quota_volume_kg, lang)}",
                               f"; {_tonnes(m.quota_balance_kg, lang)} left of {_tonnes(m.quota_volume_kg, lang)}")
                fill = quota_fill_pct(m.quota_volume_kg, m.quota_balance_kg)
                if fill is not None:
                    text += self.t(f" ({_num(fill, lang, 0)}% utilizzato)", f" ({_num(fill, lang, 0)}% used)")
            if m.quota_status:
                it_, en_ = QUOTA_STATUS.get(m.quota_status, (m.quota_status, m.quota_status))
                text += self.t(f", stato: {it_}", f", status: {en_}")
            if ((m.extra or {}).get("quota") or {}).get("shared_by_group"):
                text += self.t(" (contingente condiviso con altri paesi)", " (quota shared with other countries)")
            if m.valid_from and m.valid_to:
                text += self.t(f"; periodo {_date(m.valid_from, lang)} – {_date(m.valid_to, lang)}",
                               f"; period {_date(m.valid_from, lang)} – {_date(m.valid_to, lang)}")
        text += self.t(f". Verificato il {_date(m.as_of, lang)}", f". Verified on {_date(m.as_of, lang)}")
        if m.legal_reference:
            text += self.t(f"; base giuridica {m.legal_reference}", f"; legal basis {m.legal_reference}")
        text += "."
        return Fact(kind="duty", title=f"{who} · {what} · {scope}", text=text,
                    status=fact_status(m.data_status, m.reliability, None, self.today), source=source_brief(src),
                    url=m.legal_url or m.consult_url or m.source_url, link="/normative", published_at=iso(m.as_of),
                    data_status=m.data_status, reliability=m.reliability, is_demo=m.is_demo,
                    country=None if general else origins[0],
                    key=f"quota:{m.jurisdiction}:{m.quota_order_number}" if m.quota_order_number else f"duty:{m.id}")

    def duty_facts(self, origins: list[str], *, jurisdictions: tuple[str, ...] = ("EU", "US"),
                   general: bool = True, quotas_only: bool = False) -> int:
        """Current duties for the origins (+ the general third-country duty); quotas grouped by order number."""
        M = TariffMeasure
        rows = self.db.scalars(select(M).where(M.is_current.is_(True), demo_clause(M, self.db),
                                               M.jurisdiction.in_(jurisdictions),
                                               M.origin_iso3.in_(list(origins) + list(GENERAL_ORIGINS)))).all()
        order = {"mfn": 0, "trq_in": 1, "trq_out": 2, "preference": 3, "antidumping": 4, "surcharge": 5, "other": 6}
        review = 0
        groups: dict[tuple, list[TariffMeasure]] = defaultdict(list)
        for m in rows:
            if (m.extra or {}).get("needs_review"):
                review += m.origin_iso3 in origins
                continue
            is_general = m.origin_iso3 in GENERAL_ORIGINS
            if is_general and (not general or m.measure_type != "mfn"):
                continue
            if quotas_only and not is_general and not m.quota_order_number:
                continue
            k = (m.jurisdiction, m.measure_type, m.quota_order_number) if m.quota_order_number else (m.id,)
            groups[k].append(m)
        ranked = sorted(groups.values(), key=lambda ms: (ms[0].jurisdiction, ms[0].origin_iso3 in GENERAL_ORIGINS,
                                                          order.get(ms[0].measure_type, 9),
                                                          min(ov._rank(KEY_ORIGINS, m.origin_iso3) for m in ms)))
        added = 0
        for ms in ranked:
            ms.sort(key=lambda m: (ov._rank(origins, m.origin_iso3), m.origin_iso3))
            added += self.add(self._duty_fact(ms[0], [m.origin_iso3 for m in ms]))
        if review:
            self.note(f"{review} misure aggiuntive (soprattutto dazi USA del capitolo 99) hanno un'applicabilità al miele "
                      f"ancora da verificare: sono elencate nella sezione Normative e dazi.",
                      f"{review} additional measures (mostly US Chapter 99 duties) have an applicability to honey still to "
                      f"be verified: they are listed in the Regulations & tariffs section.")
        return added

    def duty_change_facts(self, since: datetime) -> int:
        """Measures re-published with a different content (a new revision) since `since`."""
        M = TariffMeasure
        rows = self.db.scalars(select(M).where(M.is_current.is_(True), demo_clause(M, self.db), M.collected_at >= since,
                                               M.revision > 1).limit(5)).all()
        added = 0
        for m in rows:
            f = self._duty_fact(m, [m.origin_iso3])
            f.text = self.t("Misura modificata di recente — ", "Recently changed measure — ") + f.text
            f.key = f"dutychange:{m.id}"
            added += self.add(f)
        return added

    # -- exchange rates ------------------------------------------------------------
    def fx_fact(self, currency: str = "USD") -> int:
        F = FxRate
        latest = self.db.scalars(select(F).where(F.currency == currency).order_by(F.rate_date.desc()).limit(1)).first()
        if latest is None:
            return 0

        def on_or_before(d: date):
            return self.db.scalars(select(F).where(F.currency == currency, F.rate_date <= d, F.rate_date >= d - timedelta(days=10))
                                   .order_by(F.rate_date.desc()).limit(1)).first()

        lang = self.lang
        text = self.t(f"Cambio di riferimento BCE: 1 EUR = {_num(latest.per_eur, lang, 4)} {currency} il {_date(latest.rate_date, lang)}",
                      f"ECB reference rate: 1 EUR = {_num(latest.per_eur, lang, 4)} {currency} on {_date(latest.rate_date, lang)}")
        parts = []
        for back, it_, en_ in ((30, "in un mese", "in a month"), (365, "in un anno", "in a year")):
            prev = on_or_before(latest.rate_date - timedelta(days=back))
            if prev:
                ch = _pct(ov.pct_change(latest.per_eur, prev.per_eur), lang)
                parts.append(f"{_date(prev.rate_date, lang)}: {_num(prev.per_eur, lang, 4)} ({ch} {self.t(it_, en_)})")
        if parts:
            text += "; " + "; ".join(parts)
        text += self.t(". Un valore più alto significa un euro più forte (acquisti in dollari meno cari in euro).",
                       ". A higher figure means a stronger euro (dollar purchases cheaper in euro).")
        src = next((s for s in self.sources.values() if s.key == "ecb_fx"), None)
        return int(self.add(Fact(
            kind="fx", title=self.t(f"Cambio EUR/{currency} (BCE)", f"EUR/{currency} exchange rate (ECB)"), text=text,
            status="verified_official", source=source_brief(src), url=src.homepage if src else None, link=None,
            published_at=iso(latest.rate_date), period_label=iso(latest.rate_date), unit=f"{currency}/EUR",
            data_status="published", reliability="official", key=f"fx:{currency}")))

    # -- supplier offers -------------------------------------------------------------
    def quote_facts(self, quote_ids: list[int] | None = None, limit: int = 3) -> list[SupplierQuote]:
        Q = SupplierQuote
        q = select(Q).where(demo_clause(Q, self.db))
        if quote_ids:
            q = q.where(Q.id.in_(quote_ids))
        else:
            q = q.where(Q.archived.is_(False), or_(Q.valid_until.is_(None), Q.valid_until >= self.today))
        rows = self.db.scalars(q.order_by(Q.date_received.desc(), Q.id.desc()).limit(10 if quote_ids else limit)).all()
        for i, row in enumerate(rows):
            self.add(self._quote_fact(row, "ABCDEFGHIJ"[i]))
        return list(rows)

    def _quote_fact(self, r: SupplierQuote, letter: str) -> Fact:
        lang = self.lang
        body = f"{self.country(r.origin_iso3)} · {VARIETY_LABELS.get(r.variety, {}).get(lang, r.variety)}"
        if r.variety_note:
            body += f" ({_clip(r.variety_note, 60)})"
        price = f"{_num(r.price_per_kg, lang)} {r.currency}/kg"
        if r.price_unit == "lb" and r.price_quoted is not None:
            price += self.t(f" ({_num(r.price_quoted, lang)} {r.currency}/lb come offerto)",
                            f" ({_num(r.price_quoted, lang)} {r.currency}/lb as quoted)")
        if r.incoterm:
            price += f" {r.incoterm}" + (f" {r.incoterm_place}" if r.incoterm_place else "")
        parts = [price]
        if r.quantity_kg:
            parts.append(self.t(f"quantità {_tonnes(r.quantity_kg, lang)}", f"quantity {_tonnes(r.quantity_kg, lang)}"))
        if r.packaging:
            parts.append(self.t(f"imballo: {r.packaging}", f"packaging: {r.packaging}"))
        if r.shipping_cost is not None:
            basis = {"per_container": self.t("per container", "per container"), "per_kg": "/kg",
                     "total": self.t("totale", "total")}.get(r.shipping_cost_basis or "", r.shipping_cost_basis or "")
            parts.append(self.t(f"trasporto {_num(r.shipping_cost, lang)} {r.shipping_cost_currency or r.currency} {basis}",
                                f"freight {_num(r.shipping_cost, lang)} {r.shipping_cost_currency or r.currency} {basis}").strip())
        if r.insurance_pct is not None:
            parts.append(self.t(f"assicurazione {_num(r.insurance_pct, lang)}%", f"insurance {_num(r.insurance_pct, lang)}%"))
        if r.duty_pct is not None:
            parts.append(self.t(f"dazio indicato da voi {_num(r.duty_pct, lang)}%", f"duty you entered {_num(r.duty_pct, lang)}%"))
        dates = self.t(f"ricevuta il {_date(r.date_received, lang)}", f"received on {_date(r.date_received, lang)}")
        if r.valid_until:
            dates += self.t(f", valida fino al {_date(r.valid_until, lang)}", f", valid until {_date(r.valid_until, lang)}")
        parts.append(dates)
        landed = landed_cost_text(self.db, r, lang, today=self.today)
        if landed:
            parts.append(landed)
        detail = "; ".join(parts) + "."
        alias = self.t(f"Offerta {letter}", f"Offer {letter}")
        return Fact(kind="quote", title=f"{r.supplier_name} — {body}", text=f"{r.supplier_name} ({alias}) — {body}: {detail}",
                    llm_title=f"{alias} — {body}", llm_text=f"{alias} — {body}: {detail}", status="user",
                    source=None, url=None, link="/offerte", published_at=iso(r.date_received), unit=f"{r.currency}/kg",
                    data_status="user_entered", reliability="user", is_demo=r.is_demo, private=True,
                    country=r.origin_iso3, key=f"quote:{r.id}", meta={"alias": alias, "quote_id": r.id})

    # -- what happened in a window ----------------------------------------------------
    def event_facts(self, days: int) -> int:
        """Reports, prices, trade data, regulations, duty changes and news that arrived in the window."""
        since = self.today - timedelta(days=days)
        since_dt = datetime.combine(since, datetime.min.time())
        added = self.report_facts(days=days, limit=4)
        # prices PUBLISHED in the window (a row merely collected now with an old period is not news)
        recent_period = self.today - timedelta(days=ov.PRICE_RECENT_DAYS)
        fresh = [s for s in self._usable_series(self.octx.price_series())
                 if s.latest_start >= recent_period and ((s.latest.published_at and s.latest.published_at >= since)
                                                         or (s.latest.published_at is None and s.latest.collected_at >= since_dt))]
        fresh.sort(key=lambda s: (FREQ_PRIORITY.get(s.frequency, 3), ov._rank(PRICE_TYPE_ORDER, s.price_type),
                                  ov._rank(ov.ORIGIN_PRIORITY, s.origin_iso3), ov._rank(MARKET_PRIORITY, s.market_iso3),
                                  -abs(ov.series_changes(s)["mom_pct"] or 0)))
        seen: set[tuple] = set()
        n = 0
        for s in fresh:
            k = (s.price_type, s.origin_iso3)
            if k in seen or n >= 6:
                continue
            seen.add(k)
            n += self.add(self.price_fact(s))
        added += n
        added += self.trade_window_facts(since)
        added += self.regulation_facts(days=days, limit=5)
        added += self.duty_change_facts(since_dt)
        added += self.news_facts(days=days, limit=6, min_relevance=NEWS_MEDIUM)
        return added

    def trade_window_facts(self, since: date) -> int:
        """Trade periods a source PUBLISHED in the window, with its three largest flows."""
        T = TradeFlowObservation
        rows = self.db.execute(
            select(T.source_id, T.period_label, func.max(T.published_at))
            .where(T.is_current.is_(True), demo_clause(T, self.db), T.published_at >= since)
            .group_by(T.source_id, T.period_label)
        ).all()
        latest: dict[int, tuple] = {}
        for sid, label, pub in rows:
            if sid not in latest or label > latest[sid][0]:
                latest[sid] = (label, pub)
        added = 0
        for sid, (label, pub) in latest.items():
            top = self.db.execute(
                select(T.reporter_iso3, T.partner_iso3, T.flow, T.net_weight_kg, T.source_url, T.data_status, T.is_demo)
                .where(T.is_current.is_(True), demo_clause(T, self.db), T.source_id == sid, T.period_label == label,
                       T.net_weight_kg.is_not(None), T.reporter_iso3.not_in(list(PSEUDO - {"EU27"})),
                       T.partner_iso3.not_in(list(PSEUDO)))
                .order_by(T.net_weight_kg.desc()).limit(3)
            ).all()
            if not top:
                continue
            src = self.sources.get(sid)
            arrow = {"import": "←", "export": "→"}
            flows = ", ".join(f"{self.country(r)} {arrow.get(f, '·')} {self.country(p)} {_tonnes(kg, self.lang)}"
                              for r, p, f, kg, *_ in top)
            status = _most_cautious({t[5] for t in top})
            added += self.add(Fact(
                kind="trade", title=self.t(f"Nuovi dati di commercio · {_period(label, 'it')}",
                                           f"New trade data · {_period(label, 'en')}"),
                text=self.t(f"Nuovi dati di commercio pubblicati da {src.name if src else '—'} per {_period(label, 'it')}. "
                            f"Flussi principali: {flows}.",
                            f"New trade data published by {src.name if src else '—'} for {_period(label, 'en')}. "
                            f"Largest flows: {flows}."),
                status=fact_status(status, src.reliability if src else None, None, self.today), source=source_brief(src),
                url=top[0][4], link="/commercio", published_at=iso(pub), period_label=label, unit="t", data_status=status,
                reliability=src.reliability if src else None, is_demo=any(t[6] for t in top), key=f"tradewin:{sid}:{label}"))
        return added


# ---------------------------------------------------------------------------
# Landed cost (services.landed_cost, Milestone 7)
# ---------------------------------------------------------------------------


def landed_cost_text(session: Session, quote: SupplierQuote, lang: str, *, today: date | None = None) -> str | None:
    """The landed cost per kg computed by `services.landed_cost` for an offer (a range when a tariff
    quota gives two alternatives), and what it lacks. Never estimated here: no result, no sentence."""
    try:
        from . import landed_cost as lc

        res = lc.calculate(session, lc.input_from_model(quote), today=today or clock_today())
    except Exception:  # an optional enrichment must never break an answer
        log.warning("landed cost for quote %s not available", quote.id, exc_info=True)
        return None
    h = (res or {}).get("headline") or {}
    lo, hi = h.get("eur_per_kg_min"), h.get("eur_per_kg_max")
    if lo is None:
        return None
    value = _num(lo, lang) if hi is None or abs(hi - lo) < 0.005 else f"{_num(lo, lang)}–{_num(hi, lang)}"
    text = _l(lang, f"costo sbarcato calcolato da Paladex: {value} EUR/kg", f"landed cost computed by Paladex: {value} EUR/kg")
    if h.get("alternatives"):
        text += _l(lang, " (con e senza contingente tariffario)", " (with and without the tariff quota)")
    missing = [LANDED_MISSING[c][0 if lang == "it" else 1] for c in h.get("missing") or [] if c in LANDED_MISSING]
    if not h.get("complete", True):
        text += _l(lang, ", incompleto" + (f" (manca: {', '.join(missing)})" if missing else ""),
                   ", incomplete" + (f" (missing: {', '.join(missing)})" if missing else ""))
    return text


# ---------------------------------------------------------------------------
# Retrieval plan per question
# ---------------------------------------------------------------------------


def retrieve(session: Session, q: Question, *, quote_ids: list[int] | None = None,
             today: date | None = None) -> Retriever:
    r = Retriever(session, q.lang, today)
    days = q.days
    mode = q.mode
    if mode == "quotes":
        _plan_quotes(r, quote_ids)
    elif mode == "report":
        if q.source_keys:
            found = r.latest_report_facts(q.source_keys)
        else:
            found = r.report_facts(days=days or 45)
        if not found:
            r.note("Nessun report ufficiale corrispondente nel database.", "No matching official report in the database.")
    elif mode == "events":
        window = days or EVENT_DAYS
        if r.event_facts(window) == 0:
            label = q.period.label(q.lang) if q.period else r.t(f"ultimi {window} giorni", f"last {window} days")
            r.note(f"Nel periodo considerato ({label}) non risultano nuovi dati, report, normative o notizie nel database: "
                   f"mostro le ultime variazioni di prezzo pubblicate.",
                   f"No new data, reports, regulations or news in the database for the period considered ({label}): "
                   f"showing the latest published price changes.")
            r.price_moves(cap=4)
    elif mode == "costs":
        _plan_costs(r)
    elif mode == "compare":
        _plan_compare(r, q)
    elif mode == "trade_ranking":
        year = q.period.year if q.period and q.period.kind == "year" and q.period.year else r.today.year
        if not r.trade_ranking_facts(q.flow or "export", q.direction or "increase", year):
            r.note("Nessun dato di commercio utilizzabile per rispondere.", "No usable trade data to answer.")
    elif mode == "country":
        _plan_country(r, q)
    elif mode == "prices":
        markets = ["EU27"] if q.eu else None
        if not r.price_facts(varieties=q.varieties or None, price_types=q.price_types or None, markets=markets,
                             caps={k: 6 for k in PRICE_CAPS}, max_total=10):
            r.note("Nessun prezzo nel database per i criteri richiesti.", "No price in the database for the requested criteria.")
    elif mode == "news":
        if not r.news_facts(days=days or NEWS_DAYS, limit=8):
            r.note(f"Nessuna notizia negli ultimi {days or NEWS_DAYS} giorni nel database.",
                   f"No news in the last {days or NEWS_DAYS} days in the database.")
    elif mode == "regulation":
        r.regulation_facts(days=days or REG_DAYS, limit=8, jurisdictions=q.jurisdictions or None)
        if "duties" in q.topics:
            r.duty_facts(KEY_ORIGINS, jurisdictions=tuple(q.jurisdictions) or ("EU", "US"), quotas_only=True)
    elif mode == "production":
        r.production_facts(top=8)
    elif mode == "fx":
        r.fx_fact("USD")
    else:   # nothing recognised: what changed recently
        r.note("Non ho riconosciuto nella domanda paesi, varietà o argomenti: mostro le novità più recenti nel database.",
               "I did not recognise countries, varieties or topics in the question: showing the latest news in the database.")
        r.event_facts(days or 14)
    if not len(r.facts) and not r.notes:
        r.note("Non ho trovato dati nel database per rispondere a questa domanda.",
               "I found no data in the database to answer this question.")
    return r


def _plan_country(r: Retriever, q: Question) -> None:
    countries = q.countries[:3]
    topics = q.topics & {"prices", "trade", "production", "news", "regulation", "duties"}
    if not topics:
        topics = {"prices", "trade", "production", "news", "duties"}
    window = q.days or NEWS_DAYS
    for c in countries:
        name = r.country(c)
        if "prices" in topics and not r.price_facts(origins=[c], varieties=q.varieties or None,
                                                    price_types=q.price_types or None):
            r.note(f"Nessun prezzo recente nel database per {name} con i criteri richiesti.",
                   f"No recent price in the database for {name} with the requested criteria.")
        if ("trade" in topics or topics == {"prices"}) and c not in EU27_MEMBERS:
            r.eu_imports_ytd_facts([c])
        if "trade" in topics:
            r.trade_country_facts(c, flows=(q.flow,) if q.flow else ("export", "import"))
        if "production" in topics and not r.production_facts([c]):
            r.note(f"Nessun dato di produzione per {name}.", f"No production data for {name}.")
        if "duties" in topics:
            r.duty_facts([c], jurisdictions=tuple(q.jurisdictions) or ("EU", "US"))
        if topics & {"regulation", "duties", "prices"}:
            r.regulation_facts(countries=[c], days=q.days or (365 if "regulation" in topics else REG_DAYS), limit=4,
                               jurisdictions=q.jurisdictions or None)
    if countries and topics & {"news", "prices"}:
        names = ", ".join(r.country(c) for c in countries)
        if not r.news_facts(countries=countries, days=window, limit=5):
            r.note(f"Nessuna notizia su {names} negli ultimi {window} giorni nel database.",
                   f"No news about {names} in the last {window} days in the database.")
            if topics == {"news"}:
                if r.news_facts(countries=countries, days=180, limit=3):
                    r.note("Mostro le notizie più recenti disponibili, con la loro data.",
                           "Showing the most recent news available, with their dates.")
                # with no news, the most useful context is what the data say about that market
                r.note(f"Per contesto, ecco gli ultimi dati del database su {names}.",
                       f"For context, here are the latest data in the database on {names}.")
                for c in countries[:2]:
                    r.regulation_facts(countries=[c], days=365, limit=3)
                    r.price_facts(origins=[c], caps={"wholesale_bulk": 1, "import_unit_value": 1, "export_unit_value": 1})
                    if c not in EU27_MEMBERS:
                        r.eu_imports_ytd_facts([c])
                    r.trade_country_facts(c)
                    r.production_facts([c])
    if q.eu and not countries:
        r.price_facts(markets=["EU27"], price_types=q.price_types or ["import_unit_value"], caps={"import_unit_value": 5})
        r.duty_facts(KEY_ORIGINS, jurisdictions=("EU",), quotas_only=True)


def _plan_compare(r: Retriever, q: Question) -> None:
    countries = q.countries[:4]
    r.compare_price_facts(countries)
    for c in countries:
        r.price_facts(origins=[c], varieties=q.varieties or None, price_types=q.price_types or None,
                      caps={"wholesale_bulk": 1, "import_unit_value": 1, "export_unit_value": 1, "producer": 1})
    for c in countries:
        r.trade_country_facts(c, flows=(q.flow,) if q.flow else ("export", "import"))
    r.eu_imports_ytd_facts([c for c in countries if c not in EU27_MEMBERS])
    r.production_facts(countries)
    r.duty_facts(countries, jurisdictions=("EU",))
    r.news_facts(countries=countries, days=q.days or NEWS_DAYS, limit=4)


def _plan_costs(r: Retriever) -> None:
    """What moves Parodi Group's purchase cost: prices of the origins it buys from, the dollar, the
    duties and quota balances, recent rules on trade, and high-relevance news."""
    origins = [o for o in KEY_ORIGINS if o not in EU27_MEMBERS]
    if not r.price_moves(cap=5, origins=origins, price_types=COST_PRICE_TYPES):
        r.price_facts(origins=origins[:5], price_types=["wholesale_bulk", "import_unit_value"], max_total=5)
    r.fx_fact("USD")
    r.duty_facts(origins, jurisdictions=("EU",), quotas_only=True)
    r.regulation_facts(days=90, limit=4, doc_types=COST_DOC_TYPES)
    r.regulation_facts(days=60, limit=2, doc_types=["food_safety_notification"], countries=origins)
    r.news_facts(days=NEWS_DAYS, limit=3, min_relevance=NEWS_HIGH)
    # The notes go to the AI provider with the question: never the company name.
    r.note("Sono considerate le origini da cui l'azienda acquista abitualmente: "
           + ", ".join(r.country(o) for o in origins) + ".",
           "The origins the company usually buys from are considered: " + ", ".join(r.country(o) for o in origins) + ".")


def _plan_quotes(r: Retriever, quote_ids: list[int] | None) -> None:
    rows = r.quote_facts(quote_ids)
    if not rows:
        r.note("Nessuna offerta di fornitori valida nel database: inseritele nella sezione «Offerte fornitori» per "
               "poterle confrontare.",
               "No valid supplier offer in the database: enter them in the “Supplier quotes” section to compare them.")
        return
    if not quote_ids:
        r.note(f"Confronto le {len(rows)} offerte valide più recenti." if len(rows) > 1 else
               "Nel database c'è una sola offerta valida.",
               f"Comparing the {len(rows)} most recent valid offers." if len(rows) > 1 else
               "The database holds a single valid offer.")
    origins = list(dict.fromkeys(row.origin_iso3 for row in rows))
    for o in origins:   # market references of the same origin: customs unit value at import, wholesale
        r.price_facts(origins=[o], price_types=["import_unit_value", "wholesale_bulk"],
                      caps={"wholesale_bulk": 1, "import_unit_value": 1})
    r.duty_facts(origins, jurisdictions=("EU",))
    if any(row.currency != "EUR" for row in rows):
        r.fx_fact("USD")
    r.note("Le offerte sono dati vostri: restano su questo computer e il servizio di IA vede solo «Offerta A/B/C», "
           "mai il nome del fornitore né le note.",
           "Offers are your own data: they stay on this computer and the AI service only sees “Offer A/B/C”, never "
           "the supplier name or the notes.")


# ---------------------------------------------------------------------------
# Post-check: numbers and citations
# ---------------------------------------------------------------------------

_CITE = re.compile(r"\s*\[\s*(\d+(?:\s*[,;–-]\s*\d+)*)\s*\]")


def extract_citations(text: str) -> tuple[str, list[int]]:
    """'... 3,96 USD/kg [2][5].' -> ('... 3,96 USD/kg.', [2, 5]). Ranges '[2-4]' are expanded."""
    refs: list[int] = []
    for m in _CITE.finditer(text or ""):
        for part in re.split(r"\s*[,;]\s*", m.group(1)):
            rng = re.split(r"\s*[–-]\s*", part)
            if len(rng) == 2 and rng[0].isdigit() and rng[1].isdigit() and 0 <= int(rng[1]) - int(rng[0]) < 20:
                refs.extend(range(int(rng[0]), int(rng[1]) + 1))
            elif part.strip().isdigit():
                refs.append(int(part))
    clean = _CITE.sub("", text or "")
    clean = re.sub(r"\s+([.,;:])", r"\1", clean)
    return re.sub(r"\s{2,}", " ", clean).strip(), list(dict.fromkeys(refs))


# Numbers are compared BY KIND. A quantity of the answer (price, volume, percentage, rate...) must
# be a quantity of the cited context; a date, day, month, year, week or quarter must be the same
# date or period there; an identifier (document, legal act, tariff-quota or customs-code number)
# the same identifier. So an invented "5,00 USD/kg" never passes because 5 is the day of a
# publication date, nor "2026 t" because 2026 is a year, nor "90881 t" because 090881 is a quota.

_MONTH_WORDS = {
    "gennaio": 1, "genn": 1, "gen": 1, "january": 1, "jan": 1,
    "febbraio": 2, "february": 2, "feb": 2,
    "marzo": 3, "march": 3, "mar": 3,
    "aprile": 4, "april": 4, "apr": 4,
    "maggio": 5, "may": 5, "mag": 5,
    "giugno": 6, "june": 6, "jun": 6, "giu": 6,
    "luglio": 7, "july": 7, "jul": 7, "lug": 7,
    "agosto": 8, "august": 8, "aug": 8, "ago": 8,
    "settembre": 9, "september": 9, "sept": 9, "sett": 9, "sep": 9, "set": 9,
    "ottobre": 10, "october": 10, "oct": 10, "ott": 10,
    "novembre": 11, "november": 11, "nov": 11,
    "dicembre": 12, "december": 12, "dec": 12, "dic": 12,
}
_MON = r"(?P<mon>" + "|".join(sorted(_MONTH_WORDS, key=len, reverse=True)) + r")\.?(?!\w)"
_YEAR = r"(?P<y>(?:19|20)\d{2})"
# A number followed by a unit is a quantity, never a year or a code ("2026 t", "090881 kg").
_UNIT = r"(?!\s*(?:%|\$|€|¢|£|(?:t|kg|lb|q\.?li|usd|eur|tonn\w*|tons?|mln|million\w*|mila|thousand|bn)\b))"
_DASHES = str.maketrans({"–": "-", "—": "-", "‑": "-", "−": "-"})


def _mon(m: re.Match) -> int:
    return _MONTH_WORDS[m.group("mon").rstrip(".")]


def _mkdate(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _month(y: int, mo: int) -> tuple[int, int] | None:
    return (y, mo) if 1 <= mo <= 12 else None


# (kind, pattern, value builder): applied in this order; each match is masked before the next rule.
_NUMBER_RULES: list[tuple[str, re.Pattern, Any]] = [
    ("date", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[t ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\b"),
     lambda m: _mkdate(int(m[1]), int(m[2]), int(m[3]))),
    ("date", re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), lambda m: _mkdate(int(m[3]), int(m[2]), int(m[1]))),
    ("period", re.compile(r"\b(\d{4})-w(\d{1,2})\b"), lambda m: (int(m[1]), "W", int(m[2]))),
    ("period", re.compile(r"\b(?:settimana|sett\.|week|wk\.?)\s+(\d{1,2})\s+(?:del\s+|of\s+)?(\d{4})\b"),
     lambda m: (int(m[2]), "W", int(m[1]))),
    ("period", re.compile(r"\b(\d{4})-q([1-4])\b"), lambda m: (int(m[1]), "Q", int(m[2]))),
    ("period", re.compile(r"\b[qt]([1-4])\s+(\d{4})\b"), lambda m: (int(m[2]), "Q", int(m[1]))),
    ("period", re.compile(r"\b([1-4])°\s*trim\.?\s+(\d{4})\b"), lambda m: (int(m[2]), "Q", int(m[1]))),
    ("date", re.compile(r"\b(?P<d>\d{1,2})\s+(?:de\s+)?" + _MON + r",?\s+(?:de\s+|del\s+)?" + _YEAR + r"\b"),
     lambda m: _mkdate(int(m["y"]), _mon(m), int(m["d"]))),
    ("date", re.compile(r"\b" + _MON + r"\s+(?P<d>\d{1,2}),?\s+" + _YEAR + r"\b"),
     lambda m: _mkdate(int(m["y"]), _mon(m), int(m["d"]))),
    ("month", re.compile(r"\b" + _MON + r"\s+(?:del\s+|of\s+|de\s+)?" + _YEAR + r"\b"), lambda m: (int(m["y"]), _mon(m))),
    ("day", re.compile(r"\b(?P<d>\d{1,2})\s+(?:de\s+)?" + _MON), lambda m: (_mon(m), int(m["d"])) if int(m["d"]) <= 31 else None),
    ("day", re.compile(r"\b" + _MON + r"\s+(?P<d>\d{1,2})\b(?![.,]\d)"),
     lambda m: (_mon(m), int(m["d"])) if int(m["d"]) <= 31 else None),
    ("month", re.compile(r"\b(\d{4})-(\d{2})\b(?!-\d)"), lambda m: _month(int(m[1]), int(m[2]))),
    ("month", re.compile(r"\b(\d{1,2})[-/](\d{4})\b"), lambda m: _month(int(m[2]), int(m[1]))),
    ("years", re.compile(r"\b((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\b"), lambda m: (int(m[1]), int(m[2]))),
    ("years", re.compile(r"\b((?:19|20)\d{2})[-/](\d{2})\b"),                       # season "2024-25"
     lambda m: (int(m[1]), int(m[1]) + 1) if int(m[2]) == (int(m[1]) + 1) % 100 else None),
    # identifiers: "N°09", "n. 44", "No. 09/2026-27"; Federal Register "2026-18701"; CELEX "32026R2228";
    # legal acts "R1988/20", "2026/2228"; RASFF "2026.8785"; quota "090881"; customs code "0409.00.00"
    ("id", re.compile(r"\b(?:n[°º]|no\.|nr\.?|n\.)\s*\d+(?:[/.-]\d+)*\b"), lambda m: m[0]),
    ("id", re.compile(r"\b(?:19|20)\d{2}-\d{4,6}\b"), lambda m: m[0]),
    ("id", re.compile(r"\b\d+[a-z]{1,4}\d+(?:[/.-]\d+)*\b"), lambda m: m[0]),
    ("id", re.compile(r"\b[a-z]{1,6}\d+(?:[/.-]\d+)*\b"), lambda m: m[0]),
    ("id", re.compile(r"\b\d{1,4}/\d{1,5}(?:-\d{2,4})?\b"), lambda m: m[0]),
    ("id", re.compile(r"\b(?:19|20)\d{2}\.\d{3,}\b"), lambda m: m[0]),
    ("id", re.compile(r"\b0\d{2,}(?:\.\d+)*\b" + _UNIT), lambda m: m[0]),
    ("year", re.compile(r"(?<![\d.,'’  ])" + _YEAR + r"(?!\d)(?![.,'’]\d)" + _UNIT), lambda m: int(m["y"])),
]


@dataclass
class NumberScan:
    """The numbers of a text by kind (see `scan_numbers`)."""
    values: set = field(default_factory=set)      # Decimal readings of the quantities
    dates: set = field(default_factory=set)       # date
    days: set = field(default_factory=set)        # (month, day) written without a year
    months: set = field(default_factory=set)      # (year, month)
    years: set = field(default_factory=set)       # int
    periods: set = field(default_factory=set)     # (year, "W" | "Q", n)
    ids: set = field(default_factory=set)         # normalised identifier text
    tokens: list = field(default_factory=list)    # (position, kind, text as written, value), in order


def scan_numbers(text: str) -> NumberScan:
    """Classify every number of `text`: dates, periods and identifiers first, then years written
    alone, then the remaining numbers as quantities (all their '.'/',' readings)."""
    original = text or ""
    # one character in, one character out: positions stay valid in the original text
    norm = "".join(c.lower() if len(c.lower()) == 1 else c for c in original).translate(_DASHES)
    chars = list(norm)
    out = NumberScan()
    sets = {"date": out.dates, "day": out.days, "month": out.months, "year": out.years, "period": out.periods,
            "id": out.ids}
    for kind, rx, build in _NUMBER_RULES:
        for m in rx.finditer("".join(chars)):
            value = build(m)
            if value is None:
                continue
            if kind == "id":
                value = re.sub(r"\s+", "", value)
            out.tokens.append((m.start(), kind, original[m.start():m.end()], value))
            if kind == "years":
                out.years.update(value)
            else:
                sets[kind].add(value)
            chars[m.start():m.end()] = " " * (m.end() - m.start())
    for m in _NUM.finditer("".join(chars)):
        whole, parts = _readings(m.group(0))
        out.tokens.append((m.start(), "num", original[m.start():m.end()], (whole, parts)))
        out.values |= whole
        for p in parts:
            out.values |= p
    out.tokens.sort(key=lambda tok: tok[0])
    return out


def _rounded_match(v: Decimal, allowed: set[Decimal]) -> bool:
    """`v` is a value of the context rounded to fewer decimals (3.957 -> 3,96; 1304.7 t -> 1.305 t).
    Rounding a small number to an integer (2,6 -> 3) is not accepted: it changes the figure too much."""
    exp = v.as_tuple().exponent
    d = -exp if isinstance(exp, int) and exp < 0 else 0
    for a in allowed:
        a_exp = a.as_tuple().exponent
        a_d = -a_exp if isinstance(a_exp, int) and a_exp < 0 else 0
        if a_d <= d or (d == 0 and abs(a) < 10):
            continue
        if round(a, d) == v:
            return True
    return False


def _quantity_supported(readings: tuple[set, list], allowed: set[Decimal]) -> bool:
    """A quantity of the answer is a quantity of the context: same value whatever the separators
    (1,234.5 / 1.234,5 / 1 234,5), or the context's value rounded to fewer decimals."""
    whole, parts = readings
    if whole & allowed or (parts and all(p & allowed for p in parts)):
        return True
    if whole and any(_rounded_match(v, allowed) for v in whole):
        return True
    return bool(parts) and all(any(_rounded_match(v, allowed) for v in p) for p in parts)


def unsupported_numbers(sentence: str, basis: str) -> list[str]:
    """Numbers of `sentence` (as written, in order) that are not in `basis` AS THE SAME KIND: a
    quantity must be a quantity of the basis, a date / period / identifier the same date, period or
    identifier. Date parts, years and document numbers of the basis never make a quantity valid."""
    s, b = scan_numbers(sentence), scan_numbers(basis)
    years = b.years | {d.year for d in b.dates} | {y for y, _ in b.months} | {p[0] for p in b.periods}
    months = b.months | {(d.year, d.month) for d in b.dates}
    days = b.days | {(d.month, d.day) for d in b.dates}
    checks = {
        "num": lambda v: _quantity_supported(v, b.values),
        "date": lambda v: v in b.dates,
        "day": lambda v: v in days,
        "month": lambda v: v in months,
        "year": lambda v: v in years,
        "years": lambda v: all(y in years for y in v),
        "period": lambda v: v in b.periods,
        "id": lambda v: v in b.ids,
    }
    return [text for _pos, kind, text, value in s.tokens if not checks[kind](value)]


def check_sentences(items: list[Any], facts: FactSet, *, require_refs: bool, extra_basis: str = "",
                    allow_private: bool = True) -> tuple[list[dict], list[dict]]:
    """Validate model sentences: every citation must exist (and be allowed), every number must be in
    the cited blocks (or the question / data notes). Returns (kept [{"text", "refs"}],
    dropped [{"text", "reason", "numbers"?}])."""
    kept, dropped = [], []
    for it in items or []:
        if isinstance(it, str):
            raw, refs_in = it, []
        elif isinstance(it, dict):
            raw, refs_in = str(it.get("text") or ""), it.get("refs") or []
        else:
            continue
        text, refs_txt = extract_citations(raw)
        if not text:
            continue
        refs: list[int] = []
        bad_refs: list = []
        for x in list(refs_in if isinstance(refs_in, list) else [refs_in]) + refs_txt:
            try:
                fid = int(x)
            except (TypeError, ValueError):
                bad_refs.append(x)
                continue
            fact = facts.get(fid)
            if fact is None or (fact.private and not allow_private):
                bad_refs.append(fid)
            elif fid not in refs:
                refs.append(fid)
        if bad_refs:
            dropped.append({"text": text, "reason": "bad_citation", "refs": bad_refs})
            continue
        if require_refs and not refs:
            dropped.append({"text": text, "reason": "no_citation"})
            continue
        basis = "\n".join([extra_basis] + [facts.get(f).basis_text() for f in refs])
        bad = unsupported_numbers(text, basis)
        if bad:
            dropped.append({"text": text, "reason": "invented_number", "numbers": bad})
            continue
        kept.append({"text": text, "refs": refs})
    return kept, dropped


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = {
    "it": """Sei l'analista di mercato di un importatore italiano e statunitense di miele sfuso (container da 20 t, fusti da 300 kg). Rispondi in italiano, in modo chiaro e breve, alla domanda del titolare.

Usa ESCLUSIVAMENTE i blocchi del CONTESTO, che provengono dal database locale (fonti ufficiali, listini di settore, notizie, offerte inserite dall'utente). Regole obbligatorie:
1. Non aggiungere nessun fatto, numero, data, nome, causa o conseguenza che non sia scritto nel contesto, anche se pensi che sia vero. Nessuna conoscenza esterna.
2. Ogni frase con un fatto indica in "refs" gli id dei blocchi da cui proviene; usa solo id presenti nel contesto. Copia i numeri esattamente come sono scritti nel contesto (stesse cifre e unità). Non calcolare nuove percentuali, differenze, medie o conversioni.
3. Non mescolare tipi di prezzo: prezzo all'ingrosso, prezzo al produttore, valore unitario all'import o all'export (dogana) e prezzo al dettaglio sono serie diverse. Indica sempre tipo, mercato e periodo; confronta solo dati con stesso tipo, mercato e periodo.
4. Indica il periodo dei dati: un dato vecchio non va presentato come attuale. Le notizie non sono dati verificati: attribuiscile alla testata.
5. Sezioni (ometti quelle vuote): "verified" = Fatti verificati (dati ufficiali o pubblicati recenti; un dato provvisorio va detto provvisorio); "historical" = Contesto storico (dati più vecchi); "estimates" = Stime (stime o previsioni della fonte, dichiarate come tali); "analysis" = Analisi (IA): la tua interpretazione per un importatore, basata solo sui fatti citati, senza numeri nuovi; "forecast" = Previsioni (IA, incerte): solo tendenze possibili, qualitative, senza numeri, con l'incertezza esplicita.
6. Se i dati non bastano per rispondere, scrivilo chiaramente in "insufficient_note" e non inventare.
7. Al massimo 220 parole in totale. Frasi brevi, per un lettore non tecnico.""",
    "en": """You are the market analyst of an Italian and US importer of bulk honey (20 t containers, 300 kg drums). Answer the owner's question in English, clearly and briefly.

Use ONLY the blocks of the CONTEXT, which come from the local database (official sources, industry price lists, news, offers entered by the user). Mandatory rules:
1. Do not add any fact, number, date, name, cause or consequence that is not written in the context, even if you believe it is true. No outside knowledge.
2. Every sentence stating a fact lists in "refs" the ids of the blocks it comes from; use only ids present in the context. Copy numbers exactly as written in the context (same digits and units). Do not compute new percentages, differences, averages or conversions.
3. Never mix price types: wholesale price, producer price, import or export unit value (customs) and retail price are different series. Always state type, market and period; compare only data with the same type, market and period.
4. State the period of the data: old data must not be presented as current. News reports are not verified data: attribute them to the outlet.
5. Sections (omit empty ones): "verified" = Verified facts (recent official or published data; a provisional figure must be called provisional); "historical" = Historical context (older data); "estimates" = Estimates (the source's estimates or forecasts, stated as such); "analysis" = Analysis (AI): your interpretation for an importer, based only on the cited facts, with no new numbers; "forecast" = Outlook (AI, uncertain): possible qualitative tendencies only, no numbers, with the uncertainty stated.
6. If the data are not enough to answer, say so plainly in "insufficient_note" and do not invent.
7. At most 220 words in total. Short sentences, for a non-technical reader.""",
}

ANSWER_SCHEMA = {
    "sections": [{"key": "verified | historical | estimates | analysis | forecast",
                  "sentences": [{"text": "one sentence", "refs": [1, 2]}]}],
    "insufficient_note": "string or null",
}
_SECTION_ALIASES = {"facts": "verified", "verified_facts": "verified", "history": "historical", "estimate": "estimates",
                    "outlook": "forecast", "forecasts": "forecast", "analisi": "analysis", "previsioni": "forecast"}


def _intro(q: Question, r: Retriever, ai: bool) -> str:
    lang = q.lang
    u = q.understood()
    parts = [c["name"] for c in u["countries"]]
    if q.eu:
        parts.append(_l(lang, "Unione Europea", "European Union"))
    parts += [v["name"] for v in u["varieties"]] + [p["name"].lower() for p in u["price_types"]]
    parts += [t["name"] for t in u["topics"] if t["key"] != "compare"]
    if q.period:
        parts.append(q.period.label(lang))
    about = " · ".join(dict.fromkeys(parts))
    if not len(r.facts):
        return _l(lang, "Non ho trovato nel database dati sufficienti per rispondere.",
                  "I did not find enough data in the database to answer.")
    if ai:
        return _l(lang, f"Risposta redatta dall'IA solo con i {len(r.facts)} dati recuperati dal database"
                  + (f" ({about})." if about else "."),
                  f"Answer written by the AI using only the {len(r.facts)} items retrieved from the database"
                  + (f" ({about})." if about else "."))
    return _l(lang, "Ecco i dati disponibili nel database" + (f" su: {about}." if about else "."),
              "Here are the data available in the database" + (f" on: {about}." if about else "."))


def structured_sections(r: Retriever) -> list[dict]:
    """The retrieved facts as the answer, grouped by status (no AI involved)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in r.facts:
        groups[STATUS_SECTION.get(f.status, "verified")].append({"text": f.text, "refs": [f.id], "kind": f.kind,
                                                                 "status": f.status})
    return [{"key": k, "title": SECTION_TITLES[k][r.lang], "ai": False, "analysis": False, "items": groups[k]}
            for k in PLAIN_SECTIONS if groups.get(k)]


def how_to_enable(lang: str) -> dict:
    return {
        "file": ".env",
        "lines": ["PALADEX_LLM_PROVIDER=anthropic", "PALADEX_ANTHROPIC_API_KEY=…"],
        "alternative": ["PALADEX_LLM_PROVIDER=openai", "PALADEX_OPENAI_API_KEY=…"],
        "text": _l(lang, "Per attivare l'analisi IA, aggiungere al file .env nella cartella del programma "
                         "PALADEX_LLM_PROVIDER=anthropic e PALADEX_ANTHROPIC_API_KEY con la chiave (oppure openai e "
                         "PALADEX_OPENAI_API_KEY), poi riavviare Paladex.",
                   "To enable AI analysis, add PALADEX_LLM_PROVIDER=anthropic and PALADEX_ANTHROPIC_API_KEY with the key "
                   "(or openai and PALADEX_OPENAI_API_KEY) to the .env file in the program folder, then restart Paladex."),
    }


def context_payload(facts: FactSet, *, allow_private: bool) -> list[dict]:
    """The blocks sent to the model (supplier offers only when the question is about them)."""
    return [f.to_llm() for f in facts if allow_private or not f.private]


def parse_ai_sections(data: dict, keys: tuple[str, ...]) -> dict[str, list]:
    """{section key: [sentences]} from the model's JSON, tolerant of a few key spellings."""
    by_key: dict[str, list] = defaultdict(list)
    for sec in data.get("sections") if isinstance(data.get("sections"), list) else []:
        if not isinstance(sec, dict):
            continue
        key = str(sec.get("key") or "").strip().lower()
        key = _SECTION_ALIASES.get(key, key)
        if key not in keys:
            continue
        items = sec.get("sentences") or sec.get("items") or sec.get("bullets") or []
        by_key[key].extend(items if isinstance(items, list) else [])
    return by_key


def compose_with_llm(q: Question, r: Retriever) -> dict:
    """Ask the model; post-check every sentence. Raises llm.LLMError / LLMUnavailable."""
    facts = r.facts
    allow_private = q.is_about_quotes
    notes = "\n".join(f"- {n}" for n in r.notes)
    user = (f"DOMANDA / QUESTION: {q.text.strip()}\n"
            f"DATA DI OGGI / TODAY: {r.today.isoformat()}\n"
            + (f"NOTE SUI DATI / DATA NOTES:\n{notes}\n" if notes else "")
            + "CONTESTO / CONTEXT (JSON):\n" + json.dumps(context_payload(facts, allow_private=allow_private),
                                                         ensure_ascii=False, indent=1))
    data = llm.complete_json(SYSTEM_PROMPT[q.lang], user, ANSWER_SCHEMA, max_tokens=2200)
    extra = "\n".join([q.text, *r.notes, r.today.isoformat(), q.period.label(q.lang) if q.period else "", COMPANY_BASIS])
    by_key = parse_ai_sections(data, AI_SECTIONS)
    sections, dropped, total = [], [], 0
    for key in AI_SECTIONS:
        items = by_key.get(key) or []
        total += len(items)
        kept, bad = check_sentences(items, facts, require_refs=key in FACT_SECTIONS, extra_basis=extra,
                                    allow_private=allow_private)
        dropped += [{**d, "section": key} for d in bad]
        if kept:
            sections.append({"key": key, "title": SECTION_TITLES[key][q.lang], "ai": True,
                             "analysis": key in ("analysis", "forecast"), "items": kept})
    insufficient_note = None
    note = data.get("insufficient_note")
    if isinstance(note, str) and note.strip() and note.strip().lower() not in ("null", "none"):
        clean, _refs = extract_citations(note)
        if not unsupported_numbers(clean, extra + "\n" + "\n".join(f.basis_text() for f in facts)):
            insufficient_note = clean
    factual = sum(len(s["items"]) for s in sections if s["key"] in FACT_SECTIONS)
    rejected = (total > 0 and len(dropped) / total > MAX_DROPPED_SHARE) or (factual == 0 and not insufficient_note)
    return {"sections": sections, "dropped": dropped, "total": total, "rejected": rejected,
            "insufficient_note": insufficient_note}


def answer(session: Session, question: str, lang: str = "it", *, quote_ids: list[int] | None = None,
           today: date | None = None, save: bool = True) -> dict:
    """Answer one question from the local database (see the module docstring)."""
    lang = lang if lang in ("it", "en") else "it"
    question = (question or "").strip()[:QUESTION_MAX_CHARS]
    settings = get_settings()
    ai_enabled = settings.llm_enabled()
    q = parse_question(question, lang, today)
    if quote_ids:
        q.topics.add("quotes")
        q.mode = "quotes"
    warnings: list[str] = []
    if ai_enabled and _understood_nothing(q):
        try:
            q = llm_entities(q, today)
        except (llm.LLMError, llm.LLMUnavailable) as exc:
            log.info("entity extraction by the model failed: %s", exc)
    r = retrieve(session, q, quote_ids=quote_ids, today=today)
    out: dict[str, Any] = {
        "question": question, "lang": lang, "asked_at": iso(clock_now()), "understood": q.understood(),
        "ai_used": False, "ai": {"enabled": ai_enabled, "provider": None, "model": None},
        "facts": [f.to_dict(lang) for f in r.facts], "notes": list(r.notes), "warnings": warnings,
        "is_demo": any(f.is_demo for f in r.facts), "insufficient": len(r.facts) == 0, "insufficient_note": None,
        "checks": None, "private_data_used": any(f.private for f in r.facts), "sent_private_to_ai": False,
    }
    if ai_enabled:
        info = llm.provider_info(settings)
        out["ai"].update(provider=info.provider, model=info.model)
    composed = None
    if ai_enabled and len(r.facts):
        try:
            composed = compose_with_llm(q, r)
            out["sent_private_to_ai"] = q.is_about_quotes and out["private_data_used"]
        except llm.LLMUnavailable:
            composed = None
        except llm.LLMError as exc:
            warnings.append(_l(lang, f"Il servizio di IA non ha risposto ({exc}): mostro i dati recuperati dal database.",
                               f"The AI service did not answer ({exc}): showing the data retrieved from the database."))
    if composed is not None:
        out["checks"] = {"sentences": composed["total"], "dropped": len(composed["dropped"]),
                         "dropped_items": composed["dropped"], "rejected": composed["rejected"]}
        if composed["rejected"]:
            warnings.append(_l(lang, "La risposta dell'IA è stata scartata perché conteneva numeri o citazioni non "
                                     "presenti nei dati: mostro i dati recuperati dal database.",
                               "The AI answer was discarded because it contained numbers or citations not found in the "
                               "data: showing the data retrieved from the database."))
        else:
            out["ai_used"] = True
            out["sections"] = composed["sections"]
            out["insufficient_note"] = composed["insufficient_note"]
            n = len(composed["dropped"])
            if n:
                warnings.append(_l(lang, f"{n} frasi della risposta dell'IA sono state rimosse perché contenevano numeri "
                                         f"o citazioni non verificabili sulle fonti." if n > 1 else
                                         "1 frase della risposta dell'IA è stata rimossa perché conteneva numeri o "
                                         "citazioni non verificabili sulle fonti.",
                                   f"{n} sentences of the AI answer were removed because they contained numbers or "
                                   f"citations that could not be checked against the sources." if n > 1 else
                                   "1 sentence of the AI answer was removed because it contained numbers or citations "
                                   "that could not be checked against the sources."))
    if not out["ai_used"]:
        out["sections"] = structured_sections(r)
        if not ai_enabled:
            out["how_to_enable"] = how_to_enable(lang)
    out["intro"] = _intro(q, r, out["ai_used"])
    if save and question:
        out["id"] = append_history(out)
    return out


# ---------------------------------------------------------------------------
# History (local JSON file)
# ---------------------------------------------------------------------------

_history_lock = threading.Lock()


def _history_path() -> Path:
    return get_settings().data_dir / "assistant" / "history.json"


def _read_history() -> list[dict]:
    try:
        data = json.loads(_history_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append_history(ans: dict) -> str:
    entry_id = uuid.uuid4().hex[:12]
    entry = {"id": entry_id, "asked_at": ans.get("asked_at"), "question": ans.get("question"), "lang": ans.get("lang"),
             "ai_used": bool(ans.get("ai_used")), "answer": {**ans, "id": entry_id}}
    with _history_lock:
        items = ([entry] + _read_history())[:HISTORY_MAX]
        p = _history_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
    return entry_id


def load_history(limit: int = HISTORY_MAX) -> list[dict]:
    with _history_lock:
        items = _read_history()
    return [{"id": e.get("id"), "asked_at": e.get("asked_at"), "question": e.get("question"), "lang": e.get("lang"),
             "ai_used": bool(e.get("ai_used")), "facts": len((e.get("answer") or {}).get("facts") or []),
             "insufficient": bool((e.get("answer") or {}).get("insufficient"))}
            for e in items[:limit]]


def history_entry(entry_id: str) -> dict | None:
    with _history_lock:
        items = _read_history()
    return next((e.get("answer") for e in items if e.get("id") == entry_id), None)


def clear_history() -> int:
    with _history_lock:
        n = len(_read_history())
        _history_path().unlink(missing_ok=True)
    return n


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def status(session: Session) -> dict:
    s = get_settings()
    enabled = s.llm_enabled()
    info = llm.provider_info(s) if enabled else None
    today = clock_today()
    briefings = session.scalars(select(Briefing).where(Briefing.briefing_date == today)).all()
    Q = SupplierQuote
    quotes = session.scalar(select(func.count()).select_from(Q).where(
        demo_clause(Q, session), Q.archived.is_(False), or_(Q.valid_until.is_(None), Q.valid_until >= today))) or 0
    return {
        "llm_enabled": enabled,
        "provider": info.provider if info else None,
        "model": info.model if info else None,
        "provider_configured": s.llm_provider in ("anthropic", "openai"),
        "key_missing": s.llm_provider in ("anthropic", "openai") and not enabled,
        "how_to_enable": {"it": how_to_enable("it"), "en": how_to_enable("en")},
        "briefing": {
            "date": today.isoformat(),
            "schedule": "07:00",
            "items": [{"language": b.language, "generator": b.generator, "is_ai": b.generator != "rules",
                       "generated_at": iso(b.generated_at),
                       "bullets": len((b.content or {}).get("bullets") or []) if isinstance(b.content, dict) else 0}
                      for b in briefings],
        },
        "history_count": len(_read_history()),
        "quotes_count": quotes,
        "limits": {"max_facts": MAX_FACTS, "news_days": NEWS_DAYS, "question_max_chars": QUESTION_MAX_CHARS},
    }
