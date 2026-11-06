"""Alert rules and events (Milestone 7b).

A rule (`AlertRule`) watches one kind of data; `evaluate_all()` runs after every collection
(`collectors.runner.post_collection_hooks`) and stores one `AlertEvent` per new fact. Rules:

* ``price_change``  one price type + origin + variety (+ market, colour optional), a threshold in %
                    and a direction (up / down / any). For every matching MONTHLY series (weekly
                    series are never used: a week-on-week move is noise for a bulk buyer) the latest
                    month is compared with the exact previous month, in the currency the source
                    publishes (no exchange-rate effect). Customs unit values of consignments under
                    10 t are left out, exactly as on the price pages (`api.prices.bulk_unit_value_clause`).
* ``new_report``    one event per new official report release of the chosen sources.
* ``news_keyword``  keywords (IT/EN, matched at the start of words, accents ignored), countries
                    and a minimum relevance; one event per article that is not a duplicate.
* ``regulation``    jurisdictions, document types, countries: one event per new official document,
                    plus (optional) every new duty measure or new revision of a duty measure whose
                    duty, quota status, quota volume, validity or legal basis changed (a quota
                    balance drawn down day by day is not an event; a quota becoming exhausted is).
* ``trade_change``  reporter, partner, flow, threshold % year on year on monthly or annual totals
                    (net weight), one source per figure as on the trade pages.

Rules about events:

* Events are deduplicated by (rule, entity/period): the same fact never fires twice.
* Only data that is new for the rule fires, so a new rule never floods the feed with history.
  Exception: ``new_report`` also looks back 14 days when the rule starts watching, so a rule
  created just after a release still reports it.
* Demo rows never produce events (events are stored and would outlive the demo data).
* A value corrected by a person (reliability ``user``, services/corrections.py) never produces a
  market event: price and trade rules leave out corrected rows and every figure that includes one,
  since the event would name the source. The correction's own notices (the source published a new
  value, a received correction in conflict) are raised by services/corrections.py. An undo restores
  the official row with its original ``collected_at``, so it is not new data either.
* Messages are factual (numbers, period, source, publication date), in Italian and English, and
  never contain AI text.

What counts as new (the "watch" rule; it holds whatever the order of collections and imports):

* A rule starts watching when it is created, when its conditions change and when it is switched
  back on. It then stores, in ``params["_meta"]``, the moment (``since``) and, for every table
  the alerts read, the highest row id at that moment (``marks``). Row ids only grow (history is
  append-only), so an id above the mark means the row entered THIS database after the watch start.
  The first evaluation of a rule takes this baseline again (what is in the database then is known).
* A row is new for a rule when BOTH hold: its id is above the rule's mark for its table, and its
  ``collected_at`` is later than the rule's watch start AND later than the latest bulk import of
  history (`bulk_import_cut`).
* Bulk imports keep the original ``collected_at`` of every row. The starter data
  (`services.starter`) records ``imported_at`` and ``data_collected_until`` in app_settings
  (``starter_data``) and those two dates set the cut. So rows that a snapshot adds to a database
  whose rules already exist have ids above the marks but a collection time before the cut, and
  never fire. Rules created after an import have marks above every imported row. Any other bulk
  import of history must leave the same trace (`note_bulk_import`).
* Per-row rules (news, documents, duty measures) only look at rows collected in the last
  ``RESCAN_DAYS`` days. A late AI translation can still make an article match, and the evaluation
  stays fast after years of data.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..enums import AlertType, PriceType, Severity
from ..models import (
    AlertEvent,
    AlertRule,
    NewsArticle,
    PriceObservation,
    RegulationItem,
    Report,
    Source,
    TariffMeasure,
    TradeFlowObservation,
    utcnow,
)

log = logging.getLogger(__name__)

SEED_SETTING = "alerts_default_rules_seeded"
# Latest bulk import of history other than the starter data (see `note_bulk_import`).
BULK_IMPORT_SETTING = "alerts_bulk_import"
STARTER_SETTING = "starter_data"        # services.starter.SETTING_KEY (read without importing it)
REPORT_LOOKBACK_DAYS = 14
PREVIEW_WINDOW_DAYS = 30
RESCAN_DAYS = 60
# Backfill guard: a document first collected long after its publication (a collector filling in an
# archive, a newly added source) is history, not news. Days between publication and collection.
RECENCY_DAYS = {"news": 14, "regulation": 30, "report": 45}
MAX_PREVIEW_ITEMS = 25
META_KEY = "_meta"

ALERT_TYPES = [t.value for t in AlertType]
DIRECTIONS = ("up", "down", "any")
TRADE_FREQS = ("M", "A")

# Tariff fields whose change is worth an alert (a balance drawn down day by day is not).
TARIFF_SIGNIFICANT = ("duty_text", "ad_valorem_pct", "specific_amount", "specific_unit", "quota_status",
                      "quota_volume_kg", "valid_from", "valid_to", "measure_type", "legal_reference")


# ---------------------------------------------------------------------------
# Default rules (seeded once; the owner may edit, disable or delete them)
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[dict] = [
    {
        "seed": "price_arg_polyflora_wholesale",
        "name": "Argentina millefiori +5% (prezzo all'ingrosso)",
        "alert_type": AlertType.PRICE_CHANGE.value,
        "params": {"price_type": PriceType.WHOLESALE_BULK.value, "origin": "ARG", "variety": "polyflora",
                   "market": None, "color_grade": None, "threshold_pct": 5.0, "direction": "up"},
    },
    {
        "seed": "report_usda_nhr",
        "name": "Nuovo National Honey Report USDA",
        "alert_type": AlertType.NEW_REPORT.value,
        "params": {"source_keys": ["usda_honey_report"]},
    },
    {
        "seed": "news_china_export",
        "name": "Notizie importanti sull'export di miele cinese",
        "alert_type": AlertType.NEWS_KEYWORD.value,
        "params": {"keywords": ["export", "esport", "出口", "dumping", "dazi", "tariff"], "countries": ["CHN"],
                   "min_relevance": 60},
    },
    {
        "seed": "regulation_eu_import",
        "name": "Modifiche alla normativa UE sull'import di miele",
        "alert_type": AlertType.REGULATION.value,
        "params": {"jurisdictions": ["EU"], "doc_types": [], "countries": [], "include_tariffs": True},
    },
    {
        "seed": "trade_eu_imports_yoy",
        "name": "Variazioni significative dei volumi commerciali (>20% a/a)",
        "alert_type": AlertType.TRADE_CHANGE.value,
        "params": {"reporter": "EU27", "partner": "WLD", "flow": "import", "threshold_pct": 20.0, "freq": "M",
                   "direction": "any"},
    },
]


def ensure_default_rules(session: Session) -> int:
    """Create the example rules the first time Paladex starts (idempotent: a flag in app_settings
    records that it was done, so a rule the owner deleted is never re-created)."""
    from sqlalchemy.dialects.sqlite import insert

    from ..api.common import get_setting
    from ..models import AppSetting

    if get_setting(session, SEED_SETTING):
        return 0
    # Claim the flag first, atomically: the first request of a fresh install often arrives
    # together with others (top-bar bell, rule list, feed). The insert takes SQLite's write lock,
    # so a concurrent claim waits for this transaction and then finds the flag: only one seeds.
    claimed = session.execute(insert(AppSetting).values(key=SEED_SETTING, value=True)
                              .on_conflict_do_nothing(index_elements=["key"])).rowcount
    if not claimed:
        return 0
    have = {r.name for r in session.scalars(select(AlertRule))}
    now = utcnow()
    n = 0
    for spec in DEFAULT_RULES:
        if spec["name"] in have:
            continue
        params = start_watch(session, spec["params"], now, {META_KEY: {"seed": spec["seed"]}})
        session.add(AlertRule(name=spec["name"], alert_type=spec["alert_type"], params=params, enabled=True,
                              created_at=now))
        n += 1
    session.flush()
    return n


# ---------------------------------------------------------------------------
# Rule parameters and the watch rule (see the module docstring)
# ---------------------------------------------------------------------------

# Tables the alerts read, by table name (the keys of `_meta.marks`).
WATCHED_MODELS = (PriceObservation, TradeFlowObservation, Report, NewsArticle, RegulationItem, TariffMeasure)


def public_params(params: dict | None) -> dict:
    """Parameters without the internal bookkeeping key."""
    return {k: v for k, v in (params or {}).items() if k != META_KEY}


def rule_since(rule: AlertRule) -> datetime:
    """Moment from which the rule watches new data (creation, last edit or re-activation)."""
    meta = (rule.params or {}).get(META_KEY) or {}
    return _parse_dt(meta.get("since")) or rule.created_at or utcnow()


def high_water_marks(session: Session) -> dict[str, int]:
    """Highest row id of every watched table (0 for an empty table)."""
    return {m.__tablename__: int(session.scalar(select(func.max(m.id))) or 0) for m in WATCHED_MODELS}


def start_watch(session: Session, params: dict, when: datetime | None = None, previous: dict | None = None) -> dict:
    """`params` with the watch started at `when` (default now): the moment and the current
    high-water marks. Other internal metadata of `previous` (e.g. the seed key) is kept."""
    meta = dict(((previous or {}).get(META_KEY)) or {})
    meta["since"] = (when or utcnow()).isoformat()
    meta["marks"] = high_water_marks(session)
    return {**public_params(params), META_KEY: meta}


def note_bulk_import(session: Session, collected_until: datetime | None = None) -> None:
    """Record that history was just imported in bulk (rows keeping their original `collected_at`).
    Rows collected before this moment (and before `collected_until`, the newest collection time
    in the import) never fire. The starter data does not need it: its own `starter_data` record
    is read directly."""
    from ..api.common import set_setting

    now = utcnow()
    set_setting(session, BULK_IMPORT_SETTING, {"imported_at": now.isoformat(),
                                               "data_collected_until": (collected_until or now).isoformat()})


def bulk_import_cut(session: Session) -> datetime | None:
    """Collection-time cut of the latest bulk import of history: the later of its import time
    and the newest collection time it carried (+1 s, the snapshot stores whole seconds)."""
    from ..api.common import get_setting

    times: list[datetime] = []
    for key in (STARTER_SETTING, BULK_IMPORT_SETTING):
        rec = get_setting(session, key)
        if not isinstance(rec, dict):
            continue
        for field_name, pad in (("imported_at", 0), ("data_collected_until", 1)):
            t = _parse_dt(rec.get(field_name))
            if t is not None:
                times.append(t + timedelta(seconds=pad))
    return max(times) if times else None


@dataclass
class Watch:
    """What a rule considers new: rows above its marks, collected after `cut`."""

    since: datetime
    marks: dict[str, int]
    cut: datetime            # max(since, latest bulk import cut)

    def mark(self, model) -> int:
        return int(self.marks.get(model.__tablename__, 0) or 0)

    def is_new(self, model, row_id: int | None, collected_at: datetime | None) -> bool:
        return (row_id is not None and row_id > self.mark(model)
                and collected_at is not None and collected_at > self.cut)

    def conds(self, model) -> list:
        """The same test as SQL conditions on `model`."""
        return [model.id > self.mark(model), model.collected_at > self.cut]


def watch_of(session: Session, rule: AlertRule) -> Watch:
    meta = (rule.params or {}).get(META_KEY) or {}
    marks = {str(k): int(v) for k, v in (meta.get("marks") or {}).items() if isinstance(v, (int, float))}
    since = rule_since(rule)
    cut = bulk_import_cut(session)
    return Watch(since=since, marks=marks, cut=max(since, cut) if cut else since)


# ---------------------------------------------------------------------------
# Text helpers (messages are factual and bilingual)
# ---------------------------------------------------------------------------

MONTHS = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}
COLOR_LABELS = {
    "water white": ("bianco acqua", "water white"), "extra white": ("extra bianco", "extra white"),
    "white": ("bianco", "white"), "extra light amber": ("ambra extra chiaro", "extra light amber"),
    "light amber": ("ambra chiaro", "light amber"), "amber": ("ambra", "amber"),
    "dark amber": ("ambra scuro", "dark amber"), "dark": ("scuro", "dark"),
}
DOC_TYPE_LABELS = {
    "regulation": ("regolamento", "regulation"), "directive": ("direttiva", "directive"),
    "decision": ("decisione", "decision"), "proposal": ("proposta della Commissione", "Commission proposal"),
    "antidumping": ("antidumping", "anti-dumping"), "tariff": ("dazi (atto presidenziale)", "tariffs (presidential document)"),
    "rule": ("norma definitiva", "final rule"), "proposed_rule": ("proposta di norma", "proposed rule"),
    "notice": ("avviso", "notice"), "food_safety_notification": ("allerta alimentare RASFF", "RASFF food alert"),
    "import_alert": ("allerta all'importazione", "import alert"), "agreement": ("accordo", "agreement"),
    "residue_alert": ("allerta residui", "residue alert"), "export_rule": ("regola per l'esportazione", "export rule"),
    "price_floor": ("prezzo minimo all'esportazione", "minimum export price"),
    "recommendation": ("raccomandazione", "recommendation"), "act": ("atto", "act"),
}
JURISDICTION_LABELS = {"EU": ("UE", "EU"), "US": ("USA", "US"), "IT": ("Italia", "Italy"), "AR": ("Argentina", "Argentina"),
                       "BR": ("Brasile", "Brazil"), "IN": ("India", "India"), "CN": ("Cina", "China")}
MEASURE_LABELS = {
    "mfn": ("dazio di base (paesi terzi)", "third-country duty"), "preference": ("dazio preferenziale", "preferential duty"),
    "trq_in": ("contingente tariffario", "tariff quota"), "trq_out": ("dazio fuori contingente", "out-of-quota duty"),
    "antidumping": ("dazio antidumping", "anti-dumping duty"), "surcharge": ("dazio aggiuntivo", "additional duty"),
    "other": ("altra misura", "other measure"),
}
QUOTA_STATUS = {"open": ("aperto", "open"), "critical": ("critico", "critical"), "exhausted": ("esaurito", "exhausted"),
                "blocked": ("bloccato", "blocked")}
FLOW_LABELS = {"import": ("importazioni", "imports"), "export": ("esportazioni", "exports")}


def _li(pair: tuple[str, str] | None, lang: str, fallback: str = "") -> str:
    if not pair:
        return fallback
    return pair[0] if lang == "it" else pair[1]


def num(v: float | None, lang: str, digits: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".") if lang == "it" else s


def pct_text(v: float, lang: str, digits: int = 1) -> str:
    sign = "+" if v > 0 else "−" if v < 0 else ""
    return f"{sign}{num(abs(v), lang, digits)}%"


def tonnes(kg: float | None, lang: str) -> str:
    if kg is None:
        return "—"
    return f"{num(kg / 1000, lang, 1 if kg < 10_000 else 0)} t"


def date_text(d: date | datetime | str | None, lang: str) -> str:
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    return f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"


def period_text(label: str | None, lang: str) -> str:
    """'2026-08' -> 'agosto 2026' / 'August 2026'; '2025' -> '2025'; '2026-W44' -> 'settimana 44 del 2026'."""
    if not label:
        return "—"
    if m := re.fullmatch(r"(\d{4})-(\d{2})", label):
        return f"{MONTHS[lang][int(m[2]) - 1]} {m[1]}"
    if m := re.fullmatch(r"(\d{4})-W(\d{1,2})", label):
        return f"settimana {int(m[2])} del {m[1]}" if lang == "it" else f"week {int(m[2])} of {m[1]}"
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", label):
        return f"{m[2]}° trimestre {m[1]}" if lang == "it" else f"Q{m[2]} {m[1]}"
    return label


def at_period(label: str | None, lang: str) -> str:
    """Italian 'ad agosto 2026' / 'a luglio 2026' / 'nel 2025'; English 'in August 2026'."""
    txt = period_text(label, lang)
    if lang == "en":
        return f"in {txt}"
    if label and re.fullmatch(r"\d{4}", label):
        return f"nel {txt}"
    return f"ad {txt}" if txt[:1] in "aeiou" else f"a {txt}"


def _country(iso3: str | None, lang: str) -> str:
    from ..reference.countries import country_name

    if not iso3:
        return "—"
    if iso3 == "WLD":
        return "Mondo" if lang == "it" else "World"
    return country_name(iso3, lang) or iso3


def _variety(key: str | None, lang: str) -> str:
    from ..reference.varieties import LABELS

    return LABELS.get(key or "", {}).get(lang, key or "—")


def _price_type(key: str | None, lang: str) -> str:
    from ..api.meta import PRICE_TYPE_LABELS

    for k, v in PRICE_TYPE_LABELS.items():
        if k.value == key:
            return v[lang]
    return key or "—"


def _color(c: str | None, lang: str) -> str | None:
    if not c:
        return None
    return _li(COLOR_LABELS.get(c.strip().lower()), lang, c)


def _source_name(src: Source | None) -> str:
    if src is None:
        return "—"
    return src.publisher or src.name


def _report_source(src: Source | None, lang: str) -> str | None:
    """How a report source is named: its (Italian) descriptive name in Italian, its publisher
    (the official English name) in English."""
    if src is None:
        return None
    return src.name if lang == "it" else (src.publisher or src.name)


def _cap(text: str) -> str:
    """First letter upper case, the rest untouched ("allerta alimentare RASFF" -> "Allerta alimentare RASFF")."""
    return text[:1].upper() + text[1:]


def _fresh_at_collection(published: date | datetime | None, collected: datetime | None, kind: str) -> bool:
    """False for a document collected more than RECENCY_DAYS after its publication (an archive
    backfill). Unknown dates pass."""
    if published is None or collected is None:
        return True
    pub = published.date() if isinstance(published, datetime) else published
    return (collected.date() - pub).days <= RECENCY_DAYS[kind]


def _parse_dt(v) -> datetime | None:
    """Naive UTC datetime (the database convention) from a datetime or an ISO string."""
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v))
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Plain-language description of a rule
# ---------------------------------------------------------------------------


def _list_text(items: list[str], lang: str, conj: str | None = None) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conj = conj or (" o " if lang == "it" else " or ")
    return ", ".join(items[:-1]) + conj + items[-1]


def _price_type_phrase(key: str | None, lang: str) -> str:
    """'prezzo all'ingrosso (sfuso)' / 'wholesale (bulk) price' (labels that do not say "price" get it)."""
    label = _price_type(key, lang).lower()
    if lang == "en" and "price" not in label and "value" not in label:
        label += " price"
    return label


def _threshold_text(v, lang: str) -> str:
    return num(float(v or 0), lang, 1).rstrip("0").rstrip(",.")


def _area(iso3: str | None, lang: str) -> str:
    """Country name, with the EU aggregates written without brackets ('UE a 27' / 'EU-27')."""
    if iso3 in ("EU27", "EU28"):
        return f"UE a {iso3[2:]}" if lang == "it" else f"EU-{iso3[2:]}"
    return _country(iso3, lang)


def _trade_scope(p: dict, lang: str) -> str:
    """'UE a 27 dal resto del mondo' / 'Italia da Argentina' / 'Stati Uniti, totale mondo' ..."""
    rep = _area(p.get("reporter"), lang)
    partner = p.get("partner") or "WLD"
    imp = p.get("flow", "import") == "import"
    if p.get("reporter") in ("EU27", "EU28") and partner == "WLD":
        if lang == "it":
            return f"{rep} {'dal' if imp else 'verso il'} resto del mondo"
        return f"{rep} {'from' if imp else 'to'} outside the EU"
    if partner == "WLD":
        return f"{rep}, {'totale mondo' if lang == 'it' else 'world total'}"
    if lang == "it":
        return f"{rep} {'da' if imp else 'verso'} {_country(partner, lang)}"
    return f"{rep} {'from' if imp else 'to'} {_country(partner, lang)}"


def describe(session: Session, alert_type: str, params: dict, lang: str) -> str:
    """The rule in plain words, as the owner reads it in the rule list."""
    p = public_params(params)
    it = lang == "it"
    if alert_type == AlertType.PRICE_CHANGE.value:
        thr = _threshold_text(p.get("threshold_pct"), lang)
        d = p.get("direction", "any")
        move = ({"up": "sale di almeno il", "down": "scende di almeno il", "any": "cambia, in su o in giù, di almeno il"}[d]
                if it else {"up": "rises by at least", "down": "falls by at least", "any": "moves up or down by at least"}[d])
        mk = (_area(p["market"], lang) if p.get("market") else ("tutti i mercati" if it else "every market"))
        col = _color(p.get("color_grade"), lang) or ("tutti i colori" if it else "every colour")
        pt = _price_type_phrase(p.get("price_type"), lang)
        var = _variety(p.get("variety"), lang).lower()
        if it:
            return (f"Avvisa quando il {pt} del miele {var} di origine {_country(p.get('origin'), lang)} "
                    f"({mk}; {col}) {move} {thr}% rispetto al mese precedente. Usa solo serie mensili, nella valuta "
                    "della fonte.")
        return (f"Alerts when the {pt} of {var} honey from {_country(p.get('origin'), lang)} ({mk}; {col}) {move} "
                f"{thr}% on the previous month. Monthly series only, in the source's own currency.")
    if alert_type == AlertType.NEW_REPORT.value:
        keys = p.get("source_keys") or []
        srcs = {s.key: s for s in session.scalars(select(Source).where(Source.key.in_(keys)))} if keys else {}
        names = [_report_source(srcs.get(k), lang) or k for k in keys]
        return (f"Avvisa quando viene pubblicato un nuovo report: {_list_text(names, lang)}."
                if it else f"Alerts when a new report is published: {_list_text(names, lang)}.")
    if alert_type == AlertType.NEWS_KEYWORD.value:
        parts = []
        if p.get("countries"):
            names = _list_text([_country(c, lang) for c in p["countries"]], lang)
            parts.append(f"riguarda {names}" if it else f"is about {names}")
        if p.get("keywords"):
            kws = _list_text([f"«{k}»" if it else f"“{k}”" for k in p["keywords"]], lang)
            parts.append(f"contiene {kws}" if it else f"contains {kws}")
        rel = int(p.get("min_relevance") or 0)
        if rel:
            parts.append(f"ha rilevanza almeno {rel}/100" if it else f"has a relevance of at least {rel}/100")
        joined = _list_text(parts, lang, " e " if it else " and ")
        return (f"Avvisa per ogni nuova notizia che {joined}. I duplicati della stessa notizia non contano."
                if it else f"Alerts on every new article that {joined}. Copies of the same story do not count.")
    if alert_type == AlertType.REGULATION.value:
        jur = [_li(JURISDICTION_LABELS.get(j), lang, j) for j in (p.get("jurisdictions") or [])]
        types = [_li(DOC_TYPE_LABELS.get(t), lang, t) for t in (p.get("doc_types") or [])]
        where = _list_text(jur, lang) if jur else ("tutte le giurisdizioni" if it else "every jurisdiction")
        what = _list_text(types, lang) if types else ("tutti i tipi" if it else "every type")
        cty = ""
        if p.get("countries"):
            names = _list_text([_country(c, lang) for c in p["countries"]], lang)
            cty = f", che riguarda {names}" if it else f", concerning {names}"
        if it:
            txt = f"Avvisa per ogni nuovo documento ufficiale ({where}; {what}){cty}."
            if p.get("include_tariffs"):
                txt += (f" Anche per ogni modifica dei dazi sul miele ({where}): nuove aliquote, contingenti esauriti "
                        "o riaperti, nuove misure, date di validità.")
            return txt
        txt = f"Alerts on every new official document ({where}; {what}){cty}."
        if p.get("include_tariffs"):
            txt += (f" Also on every change to honey import duties ({where}): new rates, quotas exhausted or "
                    "reopened, new measures, validity dates.")
        return txt
    if alert_type == AlertType.TRADE_CHANGE.value:
        thr = _threshold_text(p.get("threshold_pct"), lang)
        flow = _li(FLOW_LABELS.get(p.get("flow", "import")), lang)
        scope = _trade_scope(p, lang)
        monthly = p.get("freq", "M") == "M"
        if it:
            per = "allo stesso mese dell'anno prima" if monthly else "all'anno prima (solo anni completi)"
            d = {"up": "aumenta", "down": "cala", "any": "varia, in su o in giù,"}[p.get("direction", "any")]
            return (f"Avvisa quando il volume delle {flow} di miele ({scope}) {d} di almeno il {thr}% rispetto {per}. "
                    "Una fonte alla volta, mai sommate tra loro.")
        per = "the same month a year earlier" if monthly else "the previous year (full years only)"
        d = {"up": "rises", "down": "falls", "any": "moves up or down"}[p.get("direction", "any")]
        return (f"Alerts when the volume of honey {flow} ({scope}) {d} by at least {thr}% on {per}. "
                "One source at a time, never added together.")
    return ""


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    dedup_key: str
    title_it: str
    title_en: str
    body_it: str
    body_en: str
    severity: str = Severity.INFO.value
    link: str | None = None
    ref_type: str | None = None
    ref_id: int | None = None
    observed_at: datetime | None = None      # when the triggering data was collected
    published_at: str | None = None
    period_label: str | None = None
    source: dict | None = None
    source_url: str | None = None
    extra: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {
            "dedup_key": self.dedup_key, "title_it": self.title_it, "title_en": self.title_en,
            "body_it": self.body_it, "body_en": self.body_en, "severity": self.severity, "link": self.link,
            "ref_type": self.ref_type, "ref_id": self.ref_id,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "published_at": self.published_at, "period_label": self.period_label, "source": self.source,
            "source_url": self.source_url,
        }


@dataclass
class Evaluation:
    drafts: list[Draft] = field(default_factory=list)
    checked: list[dict] = field(default_factory=list)   # what the rule looked at (preview context)
    total_matches: int = 0


def _brief(src: Source | None) -> dict | None:
    from ..api.common import source_brief

    return source_brief(src)


def _sources(session: Session) -> dict[int, Source]:
    return {s.id: s for s in session.scalars(select(Source))}


def _rescan_start() -> datetime:
    return utcnow() - timedelta(days=RESCAN_DAYS)


# -- price_change -----------------------------------------------------------


def _price_rows(session: Session, p: dict) -> list[PriceObservation]:
    from ..api.prices import bulk_unit_value_clause

    M = PriceObservation
    # A value corrected by a person (reliability 'user', services/corrections.py) is not a move of the
    # source's price: the alert, which names the source, never fires on it.
    conds = [M.is_current.is_(True), M.is_demo.is_(False), bulk_unit_value_clause(M), M.frequency == "M",
             M.price_type == p["price_type"], M.origin_iso3 == p["origin"], M.variety == p["variety"],
             M.reliability != "user"]
    if p.get("market"):
        conds.append(M.market_iso3 == p["market"])
    if p.get("color_grade"):
        conds.append(M.color_grade == p["color_grade"])
    return list(session.scalars(select(M).where(*conds).order_by(M.period_start, M.id)))


def _series_label(s: dict, lang: str) -> str:
    """'Argentina → Stati Uniti · Millefiori · bianco' (market shown when it is another country;
    a variety the source does not give is left out)."""
    where = _country(s["origin_iso3"], lang)
    if s.get("market_iso3") and s["market_iso3"] != s["origin_iso3"]:
        where += f" → {_area(s['market_iso3'], lang)}"
    parts = [where]
    if s.get("variety") and s["variety"] != "unspecified":
        parts.append(_variety(s["variety"], lang))
    col = _color(s.get("color_grade"), lang)
    if col:
        parts.append(col)
    if s.get("organic"):
        parts.append("biologico" if lang == "it" else "organic")
    return " · ".join(parts)


def _crosses(pct: float, threshold: float, direction: str) -> bool:
    if direction == "up":
        return pct >= threshold
    if direction == "down":
        return pct <= -threshold
    return abs(pct) >= threshold


def _price_link(p: dict, s: dict) -> str:
    q = {"tipo": p["price_type"], "origini": s["origin_iso3"], "varieta": s["variety"]}
    if s.get("market_iso3"):
        q["mercato"] = s["market_iso3"]
    if s.get("color_grade"):
        q["colore"] = s["color_grade"]
    return f"/prezzi?{urlencode(q)}"


def _price_message(lg: str, p: dict, s: dict, last: dict, prev: dict, pct: float, threshold: float,
                   direction: str, src: Source | None) -> tuple[str, str]:
    """(title, body) of a price-change event in language `lg`."""
    ccy = s["currency"]
    lo, po = last.get("original") or {}, prev.get("original") or {}
    orig = ""
    if lo.get("unit") and lo.get("unit") != "kg" and po.get("unit") == lo.get("unit"):
        orig = (f" Valori come pubblicati: {num(lo['value'], lg)} e {num(po['value'], lg)} {lo['currency']}/{lo['unit']}."
                if lg == "it" else
                f" As published: {num(lo['value'], lg)} and {num(po['value'], lg)} {lo['currency']}/{lo['unit']}.")
    thr = _threshold_label(threshold, direction, lg)
    mk = _area(s["market_iso3"], lg) if s.get("market_iso3") else None
    pt = _cap(_price_type_phrase(p["price_type"], lg))
    title = f"{_series_label(s, lg)}: {pct_text(pct, lg)} {at_period(last['period_label'], lg)}"
    if lg == "it":
        body = (f"{pt}{f' (mercato {mk})' if mk else ''}: {num(last['value'], lg)} {ccy}/kg "
                f"{at_period(last['period_label'], lg)}, contro {num(prev['value'], lg)} {ccy}/kg "
                f"{at_period(prev['period_label'], lg)} ({pct_text(pct, lg)}).{orig} "
                f"Soglia della regola: {thr}. Fonte: {_source_name(src)}, pubblicato il "
                f"{date_text(last['published_at'], lg)}.")
    else:
        body = (f"{pt}{f' (market {mk})' if mk else ''}: {num(last['value'], lg)} {ccy}/kg "
                f"{at_period(last['period_label'], lg)}, against {num(prev['value'], lg)} {ccy}/kg "
                f"{at_period(prev['period_label'], lg)} ({pct_text(pct, lg)}).{orig} "
                f"Rule threshold: {thr}. Source: {_source_name(src)}, published "
                f"{date_text(last['published_at'], lg)}.")
    return title, body


def _month_label(r: PriceObservation) -> str:
    return f"{r.period_start.year}-{r.period_start.month:02d}"


def eval_price_change(session: Session, p: dict, watch: Watch | None) -> Evaluation:
    from ..api.prices import build_series, series_id, series_key, shift_label

    out = Evaluation()
    rows = _price_rows(session, p)
    if not rows:
        return out
    by_sid: dict[str, list[PriceObservation]] = {}
    for r in rows:
        by_sid.setdefault(series_id(series_key(r, "ORIGINAL")), []).append(r)
    M = PriceObservation
    threshold = float(p["threshold_pct"])
    direction = p.get("direction", "any")
    srcs = _sources(session)
    for s in build_series(session, rows, "ORIGINAL", "M"):
        pts = [pt for pt in s["points"] if pt["value"] is not None]
        if not pts:
            continue
        last = pts[-1]
        prev_label = shift_label(last["period_label"], "M", -1)
        prev = next((pt for pt in pts if pt["period_label"] == prev_label), None)
        check = {"label_it": _series_label(s, "it"), "label_en": _series_label(s, "en"),
                 "market_iso3": s["market_iso3"], "source": s["source"], "period_label": last["period_label"],
                 "previous_period_label": prev_label, "value": last["value"], "previous_value": prev["value"] if prev else None,
                 "currency": s["currency"], "unit": "kg", "pct": None, "fires": False, "reason": "no_previous",
                 "published_at": last["published_at"]}
        out.checked.append(check)
        if prev is None or not prev["value"]:
            continue
        pct = round((last["value"] - prev["value"]) / prev["value"] * 100, 2)
        check["pct"] = pct
        if not _crosses(pct, threshold, direction):
            check["reason"] = "below_threshold"
            continue
        # New when a row behind either month entered the database after the watch start.
        grp = by_sid.get(s["id"], [])
        behind = [r for r in grp if _month_label(r) in (last["period_label"], prev_label)]
        if watch is not None and not any(watch.is_new(M, r.id, r.collected_at) for r in behind):
            check["reason"] = "known_before_rule"
            continue
        check["fires"], check["reason"] = True, "fires"
        out.total_matches += 1
        observed = max((r.collected_at for r in behind), default=None)
        last_rows = [r for r in grp if _month_label(r) == last["period_label"]] or grp
        ref = max(last_rows, key=lambda r: (r.collected_at, r.id))
        src = srcs.get(ref.source_id)
        msg = {lg: _price_message(lg, p, s, last, prev, pct, threshold, direction, src) for lg in ("it", "en")}
        out.drafts.append(Draft(
            dedup_key=f"price:{s['id']}:{last['period_label']}",
            title_it=msg["it"][0], title_en=msg["en"][0], body_it=msg["it"][1], body_en=msg["en"][1],
            severity=Severity.WARNING.value if abs(pct) >= 2 * threshold else Severity.INFO.value,
            link=_price_link(p, s), ref_type="price", ref_id=ref.id, observed_at=observed,
            published_at=last["published_at"], period_label=last["period_label"], source=_brief(src),
            source_url=last["source_url"], extra={"pct": pct},
        ))
    return out


# -- new_report -------------------------------------------------------------


def eval_new_report(session: Session, p: dict, watch: Watch | None, today: date) -> Evaluation:
    """Every release of the chosen sources that is new for the rule, plus (look-back) the releases
    published in the 14 days before the watch start that were already in the database then. The
    preview lists the releases of the last 14 days."""
    out = Evaluation()
    keys = p.get("source_keys") or []
    if not keys:
        return out
    srcs = {s.id: s for s in session.scalars(select(Source).where(Source.key.in_(keys)))}
    if not srcs:
        return out
    ref_moment = watch.since if watch is not None else datetime.combine(today, datetime.min.time())
    lookback = (ref_moment - timedelta(days=REPORT_LOOKBACK_DAYS)).date()
    R = Report
    rows = session.scalars(select(R).where(R.source_id.in_(list(srcs)), R.is_demo.is_(False))
                           .order_by(R.published_at.desc().nulls_last(), R.id.desc())).all()
    latest_per_source: dict[int, Report] = {}
    for r in rows:
        latest_per_source.setdefault(r.source_id, r)
        # "Published in the last 14 days" needs a publication date: an undated document (e.g. an
        # annual report found on a page) is never assumed recent.
        recent = r.published_at is not None and r.published_at >= lookback
        if watch is None:
            fires = recent
        elif r.id <= watch.mark(R):
            fires = recent                      # look-back: known at the watch start, released just before
        else:
            fires = (watch.is_new(R, r.id, r.collected_at)
                     and _fresh_at_collection(r.published_at, r.collected_at, "report"))
        if not fires:
            continue
        out.total_matches += 1
        src = srcs.get(r.source_id)

        def body(lg: str, r=r, src=src) -> str:
            who = _source_name(src)
            if lg == "it":
                per = f" Periodo: {period_text(r.period_label, lg)}." if r.period_label else ""
                pub = (f"Pubblicato il {date_text(r.published_at, lg)} da {who}" if r.published_at
                       else f"Fonte: {who} (data di pubblicazione non indicata)")
                return (f"{_report_source(src, lg) or '—'}: «{r.title}».{per} {pub}; raccolto da Paladex il "
                        f"{date_text(r.collected_at, lg)}.")
            per = f" Period: {period_text(r.period_label, lg)}." if r.period_label else ""
            pub = (f"Published {date_text(r.published_at, lg)} by {who}" if r.published_at
                   else f"Source: {who} (publication date not given)")
            return f"“{r.title}”.{per} {pub}; collected by Paladex on {date_text(r.collected_at, lg)}."

        def title(lg: str, r=r) -> str:
            per = f" · {period_text(r.period_label, lg)}" if r.period_label else ""
            return f"{'Nuovo report' if lg == 'it' else 'New report'}: {r.title}{per}"

        out.drafts.append(Draft(
            dedup_key=f"report:{r.id}",
            title_it=title("it"),
            title_en=title("en"),
            body_it=body("it"), body_en=body("en"), link=r.url, ref_type="report", ref_id=r.id,
            observed_at=r.collected_at, published_at=r.published_at.isoformat() if r.published_at else None,
            period_label=r.period_label, source=_brief(src), source_url=r.url,
        ))
    for sid, src in srcs.items():
        r = latest_per_source.get(sid)
        out.checked.append({"source": _brief(src), "latest_title": r.title if r else None,
                            "latest_published_at": r.published_at.isoformat() if r and r.published_at else None,
                            "latest_period_label": r.period_label if r else None, "url": r.url if r else None})
    return out


# -- news_keyword -----------------------------------------------------------


def _keyword_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    from .news import fold

    out = []
    for k in keywords:
        f = fold(k.strip())
        if not f:
            continue
        # Words are matched from their start ("esport" finds "esportazioni"); scripts without spaces
        # between words (Chinese, Japanese) are matched anywhere.
        boundary = "" if any(ord(ch) >= 0x2E80 for ch in f) else r"(?<!\w)"
        out.append((k.strip(), re.compile(boundary + re.escape(f))))
    return out


def eval_news_keyword(session: Session, p: dict, watch: Watch | None, today: date) -> Evaluation:
    from .news import fold

    out = Evaluation()
    N = NewsArticle
    conds = [N.is_demo.is_(False), N.duplicate_of_id.is_(None)]
    if watch is not None:
        conds += [*watch.conds(N), N.collected_at >= _rescan_start()]
    else:       # preview: articles published in the last PREVIEW_WINDOW_DAYS
        start = datetime.combine(today - timedelta(days=PREVIEW_WINDOW_DAYS), datetime.min.time())
        conds.append(func.coalesce(N.published_at, N.collected_at) >= start)
    rel = int(p.get("min_relevance") or 0)
    if rel:
        conds.append(N.relevance_score >= rel)
    countries = set(p.get("countries") or [])
    patterns = _keyword_patterns(p.get("keywords") or [])
    srcs = _sources(session)
    rows = session.scalars(select(N).where(*conds).order_by(N.collected_at.desc(), N.id.desc())).all()
    for a in rows:
        if countries and not (countries & set(a.countries or [])):
            continue
        if watch is not None and not _fresh_at_collection(a.published_at, a.collected_at, "news"):
            continue
        found: list[str] = []
        in_ai_only = False
        if patterns:
            original = fold(" ".join(x for x in (a.title, a.snippet) if x))
            found = [k for k, rx in patterns if rx.search(original)]
            if not found:
                # AI translations / summaries (title_it, summary_en ...) let an article in another
                # language match; the message says so.
                ai_text = fold(" ".join(x for x in (a.title_it, a.title_en, a.summary_it, a.summary_en) if x))
                found = [k for k, rx in patterns if rx.search(ai_text)]
                in_ai_only = bool(found)
            if not found:
                continue
        out.total_matches += 1
        src = srcs.get(a.source_id)
        publisher = a.publisher or (src.publisher if src else None) or "—"
        ctys = [c for c in (a.countries or [])]

        def body(lg: str, a=a, found=found, publisher=publisher, ctys=ctys, in_ai_only=in_ai_only) -> str:
            pub = date_text(a.published_at, lg) if a.published_at else ("data non indicata" if lg == "it" else "date not given")
            names = ", ".join(_country(c, lg) for c in ctys) if ctys else "—"
            kw = ", ".join(found)
            if lg == "it":
                where = " (nella traduzione automatica IA, non nel testo originale)" if in_ai_only else ""
                return (f"{publisher}, {pub} (lingua: {a.language or '—'}). Paesi citati: {names}. Rilevanza "
                        f"{a.relevance_score}/100." + (f" Parole trovate: {kw}{where}." if kw else "") +
                        " Titolo originale della fonte.")
            where = " (in the AI translation, not in the original text)" if in_ai_only else ""
            return (f"{publisher}, {pub} (language: {a.language or '—'}). Countries mentioned: {names}. Relevance "
                    f"{a.relevance_score}/100." + (f" Words found: {kw}{where}." if kw else "") + " Original headline.")

        out.drafts.append(Draft(
            dedup_key=f"news:{a.id}", title_it=f"Notizia: {a.title}", title_en=f"News: {a.title}",
            body_it=body("it"), body_en=body("en"),
            severity=Severity.WARNING.value if a.relevance_score >= 80 else Severity.INFO.value,
            link=a.url, ref_type="news", ref_id=a.id, observed_at=a.collected_at,
            published_at=a.published_at.isoformat() if a.published_at else None, source=_brief(src), source_url=a.url,
        ))
    return out


# -- regulation -------------------------------------------------------------


def _measure_text(m: TariffMeasure, lg: str) -> str:
    parts = [_li(MEASURE_LABELS.get(m.measure_type), lg, m.measure_type)]
    if m.duty_text:
        parts.append(m.duty_text)
    if m.quota_order_number:
        parts.append(("contingente n. " if lg == "it" else "quota no. ") + m.quota_order_number)
    return " · ".join(parts)


def _tariff_changes(old: TariffMeasure, new: TariffMeasure, lg: str) -> list[str]:
    it = lg == "it"
    out = []
    if old.duty_text != new.duty_text or old.ad_valorem_pct != new.ad_valorem_pct or old.specific_amount != new.specific_amount:
        out.append(f"dazio da «{old.duty_text or '—'}» a «{new.duty_text or '—'}»" if it
                    else f"duty from “{old.duty_text or '—'}” to “{new.duty_text or '—'}”")
    if old.quota_status != new.quota_status:
        o, n = _li(QUOTA_STATUS.get(old.quota_status or ""), lg, old.quota_status or "—"), \
            _li(QUOTA_STATUS.get(new.quota_status or ""), lg, new.quota_status or "—")
        bal = ""
        if new.quota_balance_kg is not None:
            bal = (f" (saldo disponibile {tonnes(new.quota_balance_kg, lg)}" if it else f" (balance {tonnes(new.quota_balance_kg, lg)}")
            if new.quota_volume_kg:
                bal += (f" su {tonnes(new.quota_volume_kg, lg)}" if it else f" of {tonnes(new.quota_volume_kg, lg)}")
            bal += ")"
        out.append(f"stato del contingente da «{o}» a «{n}»{bal}" if it else f"quota status from “{o}” to “{n}”{bal}")
    if old.quota_volume_kg != new.quota_volume_kg:
        out.append(f"volume del contingente da {tonnes(old.quota_volume_kg, lg)} a {tonnes(new.quota_volume_kg, lg)}" if it
                    else f"quota volume from {tonnes(old.quota_volume_kg, lg)} to {tonnes(new.quota_volume_kg, lg)}")
    if old.valid_from != new.valid_from or old.valid_to != new.valid_to:
        def rng(m: TariffMeasure) -> str:
            a = date_text(m.valid_from, lg) if m.valid_from else "—"
            b = date_text(m.valid_to, lg) if m.valid_to else ("senza scadenza" if it else "open-ended")
            return f"{a} – {b}"
        out.append(f"validità da {rng(old)} a {rng(new)}" if it else f"validity from {rng(old)} to {rng(new)}")
    if old.measure_type != new.measure_type:
        out.append((f"tipo di misura da «{_li(MEASURE_LABELS.get(old.measure_type), lg, old.measure_type)}» a "
                    f"«{_li(MEASURE_LABELS.get(new.measure_type), lg, new.measure_type)}»") if it else
                   (f"measure type from “{_li(MEASURE_LABELS.get(old.measure_type), lg, old.measure_type)}” to "
                    f"“{_li(MEASURE_LABELS.get(new.measure_type), lg, new.measure_type)}”"))
    if old.legal_reference != new.legal_reference:
        out.append(f"base legale da {old.legal_reference or '—'} a {new.legal_reference or '—'}" if it
                    else f"legal basis from {old.legal_reference or '—'} to {new.legal_reference or '—'}")
    return out


def _significant_change(old: TariffMeasure, new: TariffMeasure) -> bool:
    return any(getattr(old, f) != getattr(new, f) for f in TARIFF_SIGNIFICANT)


def eval_regulation(session: Session, p: dict, watch: Watch | None, today: date) -> Evaluation:
    from .tariffs import GENERAL_ORIGINS

    out = Evaluation()
    juris = [j.upper() for j in (p.get("jurisdictions") or [])]
    types = list(p.get("doc_types") or [])
    countries = set(p.get("countries") or [])
    window = datetime.combine(today - timedelta(days=PREVIEW_WINDOW_DAYS), datetime.min.time())
    srcs = _sources(session)

    R = RegulationItem
    conds = [R.is_demo.is_(False)]
    if watch is not None:
        conds += [*watch.conds(R), R.collected_at >= _rescan_start()]
    else:
        # Preview: documents published in the last PREVIEW_WINDOW_DAYS (collection date when unknown).
        conds.append(or_(R.published_at >= window.date(), and_(R.published_at.is_(None), R.collected_at >= window)))
    if juris:
        conds.append(R.jurisdiction.in_(juris))
    if types:
        conds.append(R.doc_type.in_(types))
    for r in session.scalars(select(R).where(*conds).order_by(R.published_at.desc().nulls_last(), R.id.desc())):
        if countries and not (countries & set(r.countries or [])):
            continue
        if watch is not None and not _fresh_at_collection(r.published_at, r.collected_at, "regulation"):
            continue        # an archive backfill (e.g. a newly added source), not a new document
        out.total_matches += 1
        src = srcs.get(r.source_id)
        jl = {lg: _li(JURISDICTION_LABELS.get(r.jurisdiction), lg, r.jurisdiction) for lg in ("it", "en")}
        tl = {lg: _li(DOC_TYPE_LABELS.get(r.doc_type), lg, r.doc_type) for lg in ("it", "en")}

        def body(lg: str, r=r, src=src, jl=jl, tl=tl) -> str:
            ctys = ", ".join(_country(c, lg) for c in (r.countries or [])) or "—"
            if lg == "it":
                return (f"{_cap(tl[lg])} ({jl[lg]}), riferimento {r.reference}. Paesi citati: {ctys}. "
                        f"Pubblicato il {date_text(r.published_at, lg)}. Fonte: {_source_name(src)}.")
            return (f"{_cap(tl[lg])} ({jl[lg]}), reference {r.reference}. Countries mentioned: {ctys}. "
                    f"Published {date_text(r.published_at, lg)}. Source: {_source_name(src)}.")

        sev = Severity.WARNING.value if r.doc_type in ("antidumping", "import_alert", "tariff") else Severity.INFO.value
        out.drafts.append(Draft(
            dedup_key=f"reg:{r.id}", title_it=f"{jl['it']} · {_cap(tl['it'])}: {r.title}",
            title_en=f"{jl['en']} · {_cap(tl['en'])}: {r.title}", body_it=body("it"), body_en=body("en"),
            severity=sev, link=r.url, ref_type="regulation", ref_id=r.id, observed_at=r.collected_at,
            published_at=r.published_at.isoformat() if r.published_at else None, source=_brief(src), source_url=r.url,
        ))

    if p.get("include_tariffs"):
        T = TariffMeasure
        tconds = [T.is_demo.is_(False)]
        if watch is not None:
            tconds += [*watch.conds(T), T.collected_at >= _rescan_start()]
        else:
            tconds.append(T.collected_at >= window)
        if juris:
            tconds.append(T.jurisdiction.in_(juris))
        rows = session.scalars(select(T).where(*tconds).order_by(T.collected_at.desc(), T.id.desc())).all()
        prev_ids = [m.supersedes_id for m in rows if m.supersedes_id]
        olds = {m.id: m for m in session.scalars(select(T).where(T.id.in_(prev_ids)))} if prev_ids else {}
        # A brand-new measure counts only from a source that was already being read before the
        # rule started watching (the first read of a source lists every measure: not news).
        known_sources: set[int] = set()
        if watch is not None:
            known_sources = set(session.scalars(select(T.source_id).where(T.id <= watch.mark(T)).distinct()))
        for m in rows:
            if countries and m.origin_iso3 not in countries and m.origin_iso3 not in GENERAL_ORIGINS:
                continue
            old = olds.get(m.supersedes_id) if m.supersedes_id else None
            if old is not None and not _significant_change(old, m):
                continue          # e.g. a quota balance drawn down: kept in history, not an alert
            if old is None:
                if watch is not None and m.source_id not in known_sources:
                    continue
                # preview: only measures that started to apply in the window
                if watch is None and not (m.valid_from and m.valid_from >= window.date()):
                    continue
            out.total_matches += 1
            src = srcs.get(m.source_id)
            origin = {lg: (("tutte le origini" if lg == "it" else "every origin") if m.origin_iso3 in GENERAL_ORIGINS
                           else _country(m.origin_iso3, lg)) for lg in ("it", "en")}
            jl = {lg: _li(JURISDICTION_LABELS.get(m.jurisdiction), lg, m.jurisdiction) for lg in ("it", "en")}
            exhausted = m.quota_status == "exhausted" and (old is None or old.quota_status != "exhausted")

            def title(lg: str, m=m, old=old, origin=origin, jl=jl, exhausted=exhausted) -> str:
                if lg == "it":
                    if exhausted:
                        return f"Dazi {jl[lg]} sul miele ({origin[lg]}): contingente esaurito"
                    return (f"Dazi {jl[lg]} sul miele ({origin[lg]}): " +
                            ("misura modificata" if old is not None else "nuova misura"))
                if exhausted:
                    return f"{jl[lg]} honey duties ({origin[lg]}): quota exhausted"
                return f"{jl[lg]} honey duties ({origin[lg]}): " + ("measure changed" if old is not None else "new measure")

            def body(lg: str, m=m, old=old, src=src) -> str:
                it = lg == "it"
                head = _measure_text(m, lg)
                if old is not None:
                    changes = "; ".join(_tariff_changes(old, m, lg))
                    txt = (f"{head}. Cambiamenti: {changes}." if it else f"{head}. Changes: {changes}.")
                else:
                    txt = f"{head}."
                    if m.quota_status:
                        txt += (f" Stato del contingente: {_li(QUOTA_STATUS.get(m.quota_status), lg, m.quota_status)}."
                                if it else f" Quota status: {_li(QUOTA_STATUS.get(m.quota_status), lg, m.quota_status)}.")
                if m.legal_reference:
                    txt += (f" Base legale: {m.legal_reference}." if it else f" Legal basis: {m.legal_reference}.")
                txt += (f" Fonte: {_source_name(src)}, verificato il {date_text(m.as_of, lg)}." if it
                        else f" Source: {_source_name(src)}, checked on {date_text(m.as_of, lg)}.")
                return txt

            out.drafts.append(Draft(
                dedup_key=f"tariff:{m.id}", title_it=title("it"), title_en=title("en"), body_it=body("it"),
                body_en=body("en"),
                severity=Severity.WARNING.value if (exhausted or old is not None) else Severity.INFO.value,
                link=m.legal_url or m.consult_url or m.source_url, ref_type="tariff", ref_id=m.id,
                observed_at=m.collected_at, published_at=m.as_of.isoformat() if m.as_of else None,
                source=_brief(src), source_url=m.consult_url or m.source_url,
            ))
    return out


# -- trade_change -----------------------------------------------------------


def _trade_ref_id(session: Session, source_id: int | None, reporter: str, partner: str, flow: str,
                  period_start: str | None) -> int | None:
    if source_id is None or not period_start:
        return None
    T = TradeFlowObservation
    partners = [partner] if partner != "WLD" else ["WLD", "EXTRA_EU"]
    return session.scalar(select(T.id).where(
        T.source_id == source_id, T.reporter_iso3 == reporter, T.flow == flow, T.partner_iso3.in_(partners),
        T.period_start == date.fromisoformat(period_start[:10]), T.is_current.is_(True), T.is_demo.is_(False))
        .order_by(T.id.desc()).limit(1))


def _trade_what(p: dict, lg: str) -> str:
    flow_l = _li(FLOW_LABELS.get(p.get("flow", "import")), lg)
    return f"{_cap(flow_l)} di miele ({_trade_scope(p, lg)})" if lg == "it" else f"Honey {flow_l} ({_trade_scope(p, lg)})"


def _threshold_label(threshold: float, direction: str, lg: str) -> str:
    """'±20,0%' (any direction), '+20,0%' (up) or '−20,0%' (down)."""
    if direction == "any":
        return "±" + num(threshold, lg, 1) + "%"
    return pct_text(threshold if direction == "up" else -threshold, lg, 1)


def _trade_body(lg: str, p: dict, last: dict, prev: dict, pct: float, threshold: float, src: dict | None) -> str:
    prov = ""
    if last.get("data_status") == "provisional":
        prov = " (dato provvisorio)" if lg == "it" else " (provisional figure)"
    summed = ""
    if last.get("summed_from_partners"):
        summed = " Totale calcolato sommando i paesi partner." if lg == "it" else " Total summed from partner countries."
    if last.get("summed_from_months"):
        summed += " Anno completo sommando i 12 mesi." if lg == "it" else " Full year summed from its 12 months."
    name = (src or {}).get("publisher") or (src or {}).get("name") or "—"
    thr = _threshold_label(threshold, p.get("direction", "any"), lg)
    if lg == "it":
        return (f"{_trade_what(p, lg)} {at_period(last['period_label'], lg)}: {tonnes(last['net_weight_kg'], lg)}{prov}, "
                f"contro {tonnes(prev['net_weight_kg'], lg)} {at_period(prev['period_label'], lg)} "
                f"({pct_text(pct, lg)}).{summed} Soglia della regola: {thr}. Fonte: {name}, "
                f"pubblicato il {date_text(last.get('published_at'), lg)}.")
    return (f"{_trade_what(p, lg)} {at_period(last['period_label'], lg)}: {tonnes(last['net_weight_kg'], lg)}{prov}, "
            f"against {tonnes(prev['net_weight_kg'], lg)} {at_period(prev['period_label'], lg)} "
            f"({pct_text(pct, lg)}).{summed} Rule threshold: {thr}. Source: {name}, "
            f"published {date_text(last.get('published_at'), lg)}.")


def _new_trade_cells(session: Session, reporter: str, partner: str, flow: str, watch: Watch) -> set[tuple]:
    """Periods holding a trade row that is new for the rule: (source_id, 'M', year, month) for
    monthly rows, (source_id, 'MY', year) for any monthly row of a year, (source_id, 'A', year)."""
    from ..api.trade import _partner_filter

    T = TradeFlowObservation
    # a value corrected by a person is not new data from the source (services/corrections.py)
    conds = [T.is_current.is_(True), T.is_demo.is_(False), T.hs_code.like("0409%"), T.reporter_iso3 == reporter,
             T.flow == flow, T.frequency.in_(["A", "M"]), T.reliability != "user", *watch.conds(T),
             _partner_filter() if partner == "WLD" else T.partner_iso3 == partner]
    cells: set[tuple] = set()
    for sid, f, ps in session.execute(select(T.source_id, T.frequency, T.period_start).where(*conds).distinct()):
        if f == "M":
            cells.add((sid, "M", ps.year, ps.month))
            cells.add((sid, "MY", ps.year))
        else:
            cells.add((sid, "A", ps.year))
    return cells


def _trade_point_is_new(cells: set[tuple], sid: int | None, freq: str, point: dict) -> bool:
    label = point["period_label"] or ""
    if freq == "M":
        return (sid, "M", int(label[:4]), int(label[5:7])) in cells
    return (sid, "MY" if point.get("summed_from_months") else "A", int(label[:4])) in cells


def eval_trade_change(session: Session, p: dict, watch: Watch | None) -> Evaluation:
    from ..api.trade import Ctx, build_series

    out = Evaluation()
    reporter, partner, flow = p["reporter"], p.get("partner") or "WLD", p.get("flow", "import")
    freq = p.get("freq", "M")
    threshold, direction = float(p["threshold_pct"]), p.get("direction", "any")
    ctx = Ctx(session)
    data = build_series(ctx, reporter, flow, partner, freq)
    cells = _new_trade_cells(session, reporter, partner, flow, watch) if watch is not None else set()
    for s in data["series"]:
        if s.get("is_demo"):
            continue
        # A figure that is, or includes, a value corrected by a person (`correction`, services/corrections.py)
        # is never compared: the alert names the source, and the source did not publish it.
        pts = {pt["period_label"]: pt for pt in s["points"] if pt.get("net_weight_kg") and not pt.get("correction")}
        if not pts:
            continue
        last_label = max(pts)
        last = pts[last_label]
        prev_label = (f"{int(last_label[:4]) - 1}{last_label[4:]}")
        prev = pts.get(prev_label)
        src_brief = s["source"]
        check = {"source": src_brief, "period_label": last_label, "previous_period_label": prev_label,
                 "value_kg": last["net_weight_kg"], "previous_value_kg": prev["net_weight_kg"] if prev else None,
                 "pct": None, "fires": False, "reason": "no_previous", "published_at": last.get("published_at")}
        out.checked.append(check)
        if prev is None:
            continue
        pct = round((last["net_weight_kg"] - prev["net_weight_kg"]) / prev["net_weight_kg"] * 100, 2)
        check["pct"] = pct
        if not _crosses(pct, threshold, direction):
            check["reason"] = "below_threshold"
            continue
        sid = ctx.source_id(src_brief["key"]) if src_brief else None
        if watch is not None and not (_trade_point_is_new(cells, sid, freq, last)
                                      or _trade_point_is_new(cells, sid, freq, prev)):
            check["reason"] = "known_before_rule"
            continue
        check["fires"], check["reason"] = True, "fires"
        out.total_matches += 1
        observed = _parse_dt(last.get("collected_at"))

        out.drafts.append(Draft(
            dedup_key=f"trade:{(src_brief or {}).get('key')}:{reporter}:{partner}:{flow}:{freq}:{last_label}",
            title_it=f"{_trade_what(p, 'it')}: {pct_text(pct, 'it')} {at_period(last_label, 'it')} su un anno prima",
            title_en=f"{_trade_what(p, 'en')}: {pct_text(pct, 'en')} {at_period(last_label, 'en')} year on year",
            body_it=_trade_body("it", p, last, prev, pct, threshold, src_brief),
            body_en=_trade_body("en", p, last, prev, pct, threshold, src_brief),
            severity=Severity.WARNING.value if abs(pct) >= 2 * threshold else Severity.INFO.value,
            link="/commercio?" + urlencode({"reporter": reporter, "partner": partner, "flow": flow}),
            ref_type="trade", ref_id=_trade_ref_id(session, sid, reporter, partner, flow, last.get("period_start")),
            observed_at=observed, published_at=last.get("published_at"), period_label=last_label, source=src_brief,
            source_url=last.get("source_url"), extra={"pct": pct},
        ))
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def evaluate(session: Session, alert_type: str, params: dict, *, watch: Watch | None,
             today: date | None = None) -> Evaluation:
    """What a rule finds. `watch=None` is a preview on the current data (nothing is "known")."""
    today = today or date.today()
    p = public_params(params)
    if alert_type == AlertType.PRICE_CHANGE.value:
        return eval_price_change(session, p, watch)
    if alert_type == AlertType.NEW_REPORT.value:
        return eval_new_report(session, p, watch, today)
    if alert_type == AlertType.NEWS_KEYWORD.value:
        return eval_news_keyword(session, p, watch, today)
    if alert_type == AlertType.REGULATION.value:
        return eval_regulation(session, p, watch, today)
    if alert_type == AlertType.TRADE_CHANGE.value:
        return eval_trade_change(session, p, watch)
    raise ValueError(f"unknown alert type {alert_type!r}")


def _store(session: Session, rule: AlertRule, drafts: list[Draft]) -> int:
    existing = set(session.scalars(select(AlertEvent.dedup_key).where(AlertEvent.rule_id == rule.id)))
    n = 0
    now = utcnow()
    for d in drafts:
        key = d.dedup_key[:200]
        if key in existing:
            continue
        existing.add(key)
        session.add(AlertEvent(
            rule_id=rule.id, dedup_key=key, triggered_at=now, severity=d.severity,
            title_it=d.title_it[:500], title_en=d.title_en[:500], body_it=d.body_it, body_en=d.body_en,
            link=(d.link or None) and d.link[:500], ref_type=d.ref_type, ref_id=d.ref_id, read=False,
        ))
        n += 1
    return n


def evaluate_rule(session: Session, rule: AlertRule, today: date | None = None) -> int:
    """Evaluate one rule and store its new events. Returns the number of new events.

    The first evaluation of a rule is its baseline: what is in the database at that moment is
    known, not news (a rule seeded on a fresh install, before the first collection, would
    otherwise report the whole first download). Only `new_report` looks back 14 days."""
    if rule.last_checked_at is None:
        rule.params = start_watch(session, rule.params or {}, previous=rule.params)
    ev = evaluate(session, rule.alert_type, rule.params or {}, watch=watch_of(session, rule), today=today)
    n = _store(session, rule, ev.drafts)
    rule.last_checked_at = utcnow()
    session.flush()
    return n


def evaluate_all(session: Session, today: date | None = None) -> dict:
    """Run every enabled rule (called after each collection). One broken rule never stops the others."""
    ensure_default_rules(session)
    rules = session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True)).order_by(AlertRule.id)).all()
    new = 0
    failed: list[int] = []
    for rule in rules:
        # evaluate_rule only reads until its drafts are complete, then adds rows: an error while
        # reading leaves nothing half-written for this rule.
        try:
            new += evaluate_rule(session, rule, today=today)
        except Exception:  # a malformed rule must not block the others
            log.exception("alert rule %s failed", rule.id)
            failed.append(rule.id)
    session.flush()
    return {"rules": len(rules), "new_events": new, "failed": failed}


def preview(session: Session, alert_type: str, params: dict, rule: AlertRule | None = None,
            today: date | None = None) -> dict:
    """'Test now': what the rule finds on the current data, ignoring its watch start. Items the rule
    has already reported are flagged `already_sent`."""
    ev = evaluate(session, alert_type, params, watch=None, today=today)
    sent: set[str] = set()
    if rule is not None:
        sent = set(session.scalars(select(AlertEvent.dedup_key).where(AlertEvent.rule_id == rule.id)))
    items = [{**d.public(), "already_sent": d.dedup_key[:200] in sent} for d in ev.drafts[:MAX_PREVIEW_ITEMS]]
    return {
        "alert_type": alert_type,
        "total": len(ev.drafts),
        "items": items,
        "checked": ev.checked[:60],
        "window_days": PREVIEW_WINDOW_DAYS if alert_type in (AlertType.NEWS_KEYWORD.value, AlertType.REGULATION.value) else (
            REPORT_LOOKBACK_DAYS if alert_type == AlertType.NEW_REPORT.value else None),
        "description_it": describe(session, alert_type, params, "it"),
        "description_en": describe(session, alert_type, params, "en"),
    }
