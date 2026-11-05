"""Data-quality checks.

`run_checks(session)` looks at what has been collected and records problems as
`DataQualityIssue` rows, so the "Fonti" page can say plainly what to trust and what to verify.
It never changes or deletes collected data: it only describes it.

Checks (each issue has a stable `dedup_key`, so re-running updates instead of duplicating):

* STALE              enabled source whose newest data is older than 1.5x its expected cycle
                     (warning), or 3x (critical)
* COLLECTION_FAILED  the last update failed (warning) / the last 3 failed (critical).
                     OFFLINE and SKIPPED runs are not failures and are ignored here.
* MISSING (key)      a source is skipped because its free API key is not configured (info,
                     with plain-language instructions for the .env file)
* OUTLIER            a price point deviating > 35 % from the median of the previous 6 points
                     of the same series, or with robust z-score > 4 (and > 10 % deviation)
* DISCREPANCY        same origin + variety + price type + market + period (and the same tariff
                     line: an HTS-10 line is never compared with the heading total) reported by
                     >= 2 sources that differ by > 15 % (both values are listed, neither
                     discarded); customs unit values only from bulk-size (>= 10 t) consignments
* MISSING (gaps)     monthly price series with missing months in the last 12 months, between
                     the first and last point of that window (info)
* PARSE_WARNING      suspicious HS 0409 trade rows: unit value outside 0.3-30 USD/kg (upper
                     bound raised for premium origins, e.g. New Zealand manuka 150, Australia
                     100; the origin is the partner of imports and the reporter of exports), or
                     zero weight with a value (warning)

Issues that are no longer detected are resolved automatically (`resolved_at`); if they come
back they are reopened. Demonstration rows (`is_demo`) and the demo source are ignored.
"""
from __future__ import annotations

import hashlib
import logging
import math
import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import QualityIssueType, RunStatus, Severity
from ..models import (
    AppSetting,
    CollectionRun,
    DataQualityIssue,
    PriceObservation,
    Source,
    TradeFlowObservation,
    utcnow,
)
from ..reference.countries import country_name
from ..reference.varieties import variety_label

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (documented in the module docstring and shown in issue details)
# ---------------------------------------------------------------------------
STALE_WARNING_FACTOR = 1.5
STALE_CRITICAL_FACTOR = 3.0
FAILED_CRITICAL_STREAK = 3
OUTLIER_WINDOW = 6            # previous points used as reference
OUTLIER_MIN_HISTORY = 3       # need at least this many previous points to judge
OUTLIER_MAX_REL_DEV = 0.35    # > 35 % from the median of the window (quotations)
# Customs unit values move a lot from lot to lot (mix of qualities, partial months): a wider band,
# and only bulk-size consignments are judged (small lots are not bulk prices; see api.prices).
OUTLIER_MAX_REL_DEV_UNIT_VALUE = 0.60
UNIT_VALUE_TYPES = ("import_unit_value", "export_unit_value")
BULK_MIN_KG = 10_000.0
# Weekly surveillance data (TAXUD) is provisional and noisy: not judged point by point.
OUTLIER_SKIP_FREQUENCIES = ("W",)
OUTLIER_ROBUST_Z = 4.0        # robust z-score (median / MAD)
OUTLIER_Z_MIN_REL_DEV = 0.10  # ... but only if the move is also > 10 % (flat series otherwise flag every move)
DISCREPANCY_REL_DIFF = 0.15
MISSING_WINDOW_MONTHS = 12
TRADE_UV_MIN_USD = 0.3
TRADE_UV_MAX_USD = 30.0
# Premium origins (manuka / jarrah, mostly retail-packed): official lanes are regularly 30-80 USD/kg.
TRADE_UV_MAX_USD_BY_ORIGIN: dict[str, float] = {"NZL": 150.0, "AUS": 100.0}
HONEY_HS_PREFIX = "0409"

# Every dedup_key written here starts with one of these; only these are auto-resolved, so
# issues recorded by other modules are never touched.
OWNED_PREFIXES = ("stale:", "collect:", "key:", "outlier:", "discrepancy:", "missing:", "trade:")

LAST_RUN_SETTING = "quality_last_run"

_lock = threading.Lock()

# Free API keys: where to get them. The variable name in `.env` is always PALADEX_<ATTR>.
KEY_HELP: dict[str, dict[str, str]] = {
    "comtrade_api_key": {
        "service": "UN Comtrade",
        "signup_url": "https://comtradedeveloper.un.org",
        "it": "Chiave gratuita UN Comtrade: registrati sul portale sviluppatori e sottoscrivi il piano gratuito «comtrade - v1».",
        "en": "Free UN Comtrade key: sign up on the developer portal and subscribe to the free 'comtrade - v1' product.",
    },
    "usda_mmn_api_key": {
        "service": "USDA AMS MyMarketNews",
        "signup_url": "https://mymarketnews.ams.usda.gov/mymarketnews-api",
        "it": "Chiave gratuita USDA MyMarketNews: crea un account e copia la chiave dal tuo profilo.",
        "en": "Free USDA MyMarketNews key: create an account and copy the key from your profile.",
    },
    "usda_nass_api_key": {
        "service": "USDA NASS Quick Stats",
        "signup_url": "https://quickstats.nass.usda.gov/api",
        "it": "Chiave gratuita USDA NASS Quick Stats: inserisci la tua e-mail e la chiave arriva per posta elettronica.",
        "en": "Free USDA NASS Quick Stats key: enter your e-mail address and the key is e-mailed to you.",
    },
    "data_gov_api_key": {
        "service": "api.data.gov (USDA FAS GATS)",
        "signup_url": "https://api.data.gov/signup/",
        "it": "Chiave gratuita api.data.gov: compila il modulo (nome ed e-mail) e la chiave arriva per posta elettronica.",
        "en": "Free api.data.gov key: fill in the form (name and e-mail) and the key is e-mailed to you.",
    },
    "census_api_key": {
        "service": "US Census Bureau API",
        "signup_url": "https://api.census.gov/data/key_signup.html",
        "it": "Chiave gratuita US Census (facoltativa): inserisci nome ed e-mail e la chiave arriva per posta elettronica.",
        "en": "Free US Census key (optional): enter your name and e-mail address and the key is e-mailed to you.",
    },
    "anthropic_api_key": {
        "service": "Anthropic (Claude)",
        "signup_url": "https://console.anthropic.com",
        "it": "Chiave Anthropic per i riassunti IA (servizio a pagamento).",
        "en": "Anthropic key for AI summaries (paid service).",
    },
    "openai_api_key": {
        "service": "OpenAI",
        "signup_url": "https://platform.openai.com/api-keys",
        "it": "Chiave OpenAI per i riassunti IA (servizio a pagamento).",
        "en": "OpenAI key for AI summaries (paid service).",
    },
}


def env_var_for(setting_attr: str) -> str:
    """Name of the line to fill in `.env` for a Settings attribute (pydantic env_prefix)."""
    return f"PALADEX_{setting_attr.upper()}"


# ---------------------------------------------------------------------------
# Formatting helpers (messages are read by a non-technical owner, IT and EN)
# ---------------------------------------------------------------------------
_MONTHS = {
    "it": ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
_FLOW_LABELS = {
    "import": {"it": "importazioni", "en": "imports"},
    "export": {"it": "esportazioni", "en": "exports"},
    "re_import": {"it": "reimportazioni", "en": "re-imports"},
    "re_export": {"it": "riesportazioni", "en": "re-exports"},
}


def _num(v: float | None, lang: str, digits: int = 2) -> str:
    """Thousands separators and half-up rounding of the shortest decimal form, exactly like the
    browser's Intl.NumberFormat, so a number in a message matches the same number on screen."""
    if v is None:
        return "—"
    q = Decimal(repr(float(v))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    s = f"{q:,.{digits}f}"
    if lang == "it":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s


def _pct(v: float, lang: str, signed: bool = True) -> str:
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ""
    return f"{sign}{_num(abs(v), lang, 1)}%"


def _date(d: date | datetime | None, lang: str) -> str:
    if d is None:
        return "—"
    return f"{d.day} {_MONTHS[lang][d.month - 1]} {d.year}"


def _month(d: date, lang: str) -> str:
    return f"{_MONTHS[lang][d.month - 1]} {d.year}"


def _period(label: str | None, lang: str) -> str:
    if not label:
        return "—"
    if len(label) == 7 and label[4] == "-" and label[:4].isdigit() and label[5:].isdigit():
        m = int(label[5:])
        if 1 <= m <= 12:
            return f"{_MONTHS[lang][m - 1]} {label[:4]}"
    return label


def _price_type_label(pt: str, lang: str) -> str:
    # local import: keeps services free of the api package at import time
    from ..api.meta import PRICE_TYPE_LABELS

    for k, v in PRICE_TYPE_LABELS.items():
        if k.value == pt:
            return v[lang].lower() if lang == "it" else v[lang]
    return pt


# USDA colour grades (English terms used by the source) -> Italian
_COLOR_IT = {
    "water white": "bianco acqua", "extra white": "extra bianco", "white": "bianco",
    "extra light amber": "ambra extra chiaro", "light amber": "ambra chiaro", "amber": "ambra",
    "dark amber": "ambra scuro", "dark": "scuro",
}


def _color(grade: str, lang: str) -> str:
    if lang == "it":
        return f"colore {_COLOR_IT.get(grade.lower(), grade)}"
    return f"{grade} colour"


def _country(iso3: str | None, lang: str) -> str:
    return country_name(iso3, lang) if iso3 else ("origine non indicata" if lang == "it" else "origin not stated")


def explain_error(error: str | None) -> dict[str, str]:
    """Translate a technical collection error into one plain sentence (IT / EN)."""
    e = (error or "").lower()
    if "api key" in e or "key not configured" in e:
        return {"it": "manca la chiave di accesso alla fonte.", "en": "the access key for the source is missing."}
    if e.startswith("interrupted"):
        return {"it": "l'aggiornamento è stato interrotto (applicazione chiusa durante la raccolta o database occupato).",
                "en": "the update was interrupted (the application was closed during the collection, or the database was busy)."}
    if any(w in e for w in ("certificate verify failed", "certificate_verify_failed", "[ssl", "sslerror",
                            "ssl handshake", "tls handshake")):
        return {"it": "non è stato possibile verificare il certificato di sicurezza del sito della fonte.",
                "en": "the security certificate of the source website could not be verified."}
    if any(w in e for w in ("name or service not known", "nodename nor servname", "getaddrinfo failed",
                            "no address associated", "name does not resolve")):
        return {"it": "l'indirizzo del sito della fonte non esiste più: la fonte potrebbe aver cambiato dominio.",
                "en": "the address of the source website no longer exists: the source may have changed its domain."}
    if "while the internet connection works" in e:
        return {"it": "il sito della fonte non risponde, mentre la connessione internet funziona.",
                "en": "the source website does not answer, while the internet connection works."}
    if "no internet" in e or "cannot reach" in e or "connecterror" in e or "name resolution" in e:
        return {"it": "non è stato possibile collegarsi al sito della fonte (connessione internet assente o sito irraggiungibile).",
                "en": "the source website could not be reached (no internet connection or site unreachable)."}
    if "timeout" in e or "timed out" in e:
        return {"it": "il sito della fonte non ha risposto in tempo.", "en": "the source website did not respond in time."}
    if "http 404" in e or "http 410" in e:
        return {"it": "il documento non si trova più all'indirizzo previsto: la fonte potrebbe aver cambiato il proprio sito.",
                "en": "the document is no longer at the expected address: the source may have changed its website."}
    if "http 401" in e or "http 403" in e:
        return {"it": "la fonte ha rifiutato l'accesso (chiave non valida o accesso bloccato).",
                "en": "the source refused access (invalid key or access blocked)."}
    if "http 429" in e:
        return {"it": "la fonte ha ricevuto troppe richieste e chiede di riprovare più tardi.",
                "en": "the source received too many requests and asks to try again later."}
    if "http 5" in e:
        return {"it": "il sito della fonte ha un problema temporaneo.", "en": "the source website has a temporary problem."}
    if any(w in e for w in ("pars", "format", "no rates", "contained no", "unexpected", "keyerror", "valueerror", "indexerror")):
        return {"it": "il formato del documento sembra cambiato e non è stato possibile leggerlo: serve un controllo tecnico.",
                "en": "the document format seems to have changed and it could not be read: a technical check is needed."}
    return {"it": "si è verificato un errore tecnico durante la lettura dei dati.",
            "en": "a technical error occurred while reading the data."}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    dedup_key: str
    issue_type: str
    severity: str
    message_it: str
    message_en: str
    source_id: int | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    details: dict | None = None


_SEVERITY_RANK = {Severity.CRITICAL.value: 0, Severity.WARNING.value: 1, Severity.INFO.value: 2}


def _is_demo_source(s: Source) -> bool:
    return s.key == "demo" or s.reliability == "demo" or s.category == "demo"


def _is_manual(s: Source) -> bool:
    return s.kind == "manual"


# --------------------------------------------------------------------- sources
def check_stale(sources: list[Source], today: date) -> list[Finding]:
    from ..api.common import source_reference_date   # the same reference date as the freshness badges

    out: list[Finding] = []
    for s in sources:
        if not s.enabled or _is_demo_source(s) or _is_manual(s) or not s.expected_max_age_days:
            continue
        ref = source_reference_date(s)
        if ref is None:
            continue  # never collected: covered by collection / key checks, not "stale"
        exp = s.expected_max_age_days
        age = (today - ref).days
        if age <= exp * STALE_WARNING_FACTOR:
            continue
        severity = Severity.CRITICAL if age > exp * STALE_CRITICAL_FACTOR else Severity.WARNING
        out.append(Finding(
            dedup_key=f"stale:{s.key}",
            issue_type=QualityIssueType.STALE.value,
            severity=severity.value,
            source_id=s.id,
            entity_type="source",
            entity_id=s.id,
            message_it=(f"«{s.name}»: il dato più recente è del {_date(ref, 'it')} ({age} giorni fa), "
                        f"mentre questa fonte di solito si aggiorna entro {exp} giorni. "
                        f"I suoi dati non vanno considerati attuali."),
            message_en=(f"“{s.name_en or s.name}”: the newest data is from {_date(ref, 'en')} ({age} days ago), "
                        f"while this source usually updates within {exp} days. "
                        f"Its data should not be treated as current."),
            details={"reference_date": ref.isoformat(), "age_days": age, "expected_max_age_days": exp,
                     "warning_after_days": math.floor(exp * STALE_WARNING_FACTOR),
                     "critical_after_days": math.floor(exp * STALE_CRITICAL_FACTOR),
                     "latest_period_label": s.latest_period_label, "source_key": s.key, "link": f"/fonti#{s.key}"},
        ))
    return out


_MEANINGFUL_RUNS = (RunStatus.SUCCESS.value, RunStatus.PARTIAL.value, RunStatus.NO_CHANGE.value, RunStatus.FAILED.value)


def check_collection(session: Session, sources: list[Source]) -> list[Finding]:
    """Failed updates. OFFLINE (no internet) and SKIPPED runs are neither failures nor successes."""
    out: list[Finding] = []
    for s in sources:
        if not s.enabled or _is_demo_source(s) or _is_manual(s):
            continue
        runs = session.execute(
            select(CollectionRun.id, CollectionRun.status, CollectionRun.error, CollectionRun.started_at)
            .where(CollectionRun.source_id == s.id, CollectionRun.status.in_(_MEANINGFUL_RUNS))
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(FAILED_CRITICAL_STREAK)
        ).all()
        streak = 0
        for r in runs:
            if r.status != RunStatus.FAILED.value:
                break
            streak += 1
        if streak == 0:
            continue
        last = runs[0]
        why = explain_error(last.error)
        if streak >= FAILED_CRITICAL_STREAK:
            severity = Severity.CRITICAL
            first = runs[streak - 1]
            it = (f"«{s.name}»: gli ultimi {streak} aggiornamenti non sono riusciti "
                  f"(dal {_date(first.started_at, 'it')} al {_date(last.started_at, 'it')}). Motivo: {why['it']} "
                  f"I dati raccolti in precedenza restano disponibili.")
            en = (f"“{s.name_en or s.name}”: the last {streak} updates failed "
                  f"({_date(first.started_at, 'en')} to {_date(last.started_at, 'en')}). Reason: {why['en']} "
                  f"Previously collected data remains available.")
        else:
            severity = Severity.WARNING
            it = (f"«{s.name}»: l'ultimo aggiornamento ({_date(last.started_at, 'it')}) non è riuscito. "
                  f"Motivo: {why['it']} I dati raccolti in precedenza restano disponibili.")
            en = (f"“{s.name_en or s.name}”: the last update ({_date(last.started_at, 'en')}) failed. "
                  f"Reason: {why['en']} Previously collected data remains available.")
        out.append(Finding(
            dedup_key=f"collect:{s.key}",
            issue_type=QualityIssueType.COLLECTION_FAILED.value,
            severity=severity.value,
            source_id=s.id,
            entity_type="collection_run",
            entity_id=last.id,
            message_it=it,
            message_en=en,
            details={"consecutive_failures": streak, "last_run_id": last.id,
                     "last_run_at": last.started_at.isoformat() if last.started_at else None,
                     "error": (last.error or "")[:2000], "source_key": s.key, "link": f"/fonti#{s.key}"},
        ))
    return out


def check_missing_keys(sources: list[Source]) -> list[Finding]:
    settings = get_settings()
    out: list[Finding] = []
    optional_keys = _optional_key_sources()
    for s in sources:
        if not s.enabled or not s.requires_key or _is_demo_source(s):
            continue
        if getattr(settings, s.requires_key, None):
            continue
        # A collector that works (reduced) without its key is only reported once it was skipped.
        if s.key in optional_keys and s.last_run_status != RunStatus.SKIPPED.value:
            continue
        env = env_var_for(s.requires_key)
        help_ = KEY_HELP.get(s.requires_key, {})
        url = help_.get("signup_url")
        where_it = f"registrati gratuitamente su {url}, poi " if url else ""
        where_en = f"sign up for free at {url}, then " if url else ""
        out.append(Finding(
            dedup_key=f"key:{s.key}",
            issue_type=QualityIssueType.MISSING.value,
            severity=Severity.INFO.value,
            source_id=s.id,
            entity_type="source",
            entity_id=s.id,
            message_it=(f"«{s.name}» non viene aggiornata perché manca la chiave di accesso gratuita. "
                        f"Per attivarla: {where_it}apri il file .env nella cartella dell'applicazione, "
                        f"incolla la chiave dopo {env}= e riavvia l'applicazione."),
            message_en=(f"“{s.name_en or s.name}” is not updated because its free access key is missing. "
                        f"To turn it on: {where_en}open the .env file in the application folder, "
                        f"paste the key after {env}= and restart the application."),
            details={"setting": s.requires_key, "env_var": env, "signup_url": url, "service": help_.get("service"),
                     "source_key": s.key, "link": f"/fonti#{s.key}"},
        ))
    return out


def _optional_key_sources() -> set[str]:
    try:
        from ..collectors.registry import all_collectors

        return {c.key for c in all_collectors() if getattr(c, "key_optional", False)}
    except Exception:  # pragma: no cover - registry problems are reported elsewhere
        log.exception("could not read collector registry")
        return set()


# ---------------------------------------------------------------------- prices
_PRICE_COLS = (
    PriceObservation.id, PriceObservation.source_id, PriceObservation.price_type, PriceObservation.origin_iso3,
    PriceObservation.market_iso3, PriceObservation.market_location, PriceObservation.variety,
    PriceObservation.color_grade, PriceObservation.organic, PriceObservation.terms, PriceObservation.currency,
    PriceObservation.frequency, PriceObservation.period_start, PriceObservation.period_end,
    PriceObservation.period_label, PriceObservation.price_per_kg, PriceObservation.usd_per_kg,
    PriceObservation.volume_kg,
)


def _load_prices(session: Session, skip_source_ids: set[int]) -> list[Any]:
    q = select(*_PRICE_COLS).where(PriceObservation.is_current.is_(True), PriceObservation.is_demo.is_(False))
    if skip_source_ids:
        q = q.where(PriceObservation.source_id.not_in(skip_source_ids))
    return list(session.execute(q).all())


def _identity(r) -> tuple:
    """Series identity = everything that defines "the same price" except the period."""
    return (r.source_id, r.price_type, r.origin_iso3, r.market_iso3, r.market_location, r.variety,
            r.color_grade, bool(r.organic), r.terms, r.currency, r.frequency)


def _identity_hash(ident: tuple) -> str:
    return hashlib.sha1(repr(ident).encode()).hexdigest()[:16]


def _price_link(origin: str | None, variety: str | None, price_type: str | None) -> str:
    from urllib.parse import urlencode

    params = {k: v for k, v in (("origin", origin), ("variety", variety), ("price_type", price_type)) if v}
    return "/prezzi" + (f"?{urlencode(params)}" if params else "")


def _series_label(r, src: Source | None, lang: str) -> str:
    parts = [_country(r.origin_iso3, lang), variety_label(r.variety, lang).lower() if lang == "it" else variety_label(r.variety, lang)]
    if r.color_grade:
        parts.append(_color(r.color_grade, lang))
    if r.organic:
        parts.append("biologico" if lang == "it" else "organic")
    parts.append(_price_type_label(r.price_type, lang))
    if r.market_iso3:
        parts.append(("mercato " if lang == "it" else "market ") + country_name(r.market_iso3, lang))
    name = (src.name if lang == "it" else (src.name_en or src.name)) if src else "?"
    q = ("«", "»") if lang == "it" else ("“", "”")
    return f"{q[0]}{name}{q[1]} {', '.join(parts)}"


def _series_details(r, src: Source | None) -> dict:
    return {"source_key": src.key if src else None, "price_type": r.price_type, "origin_iso3": r.origin_iso3,
            "market_iso3": r.market_iso3, "market_location": r.market_location, "variety": r.variety,
            "color_grade": r.color_grade, "organic": bool(r.organic), "terms": r.terms, "currency": r.currency,
            "frequency": r.frequency}


def check_outliers(rows: list[Any], src_by_id: dict[int, Source]) -> list[Finding]:
    """Judge only the LATEST period of each series: that is the figure the app shows as current,
    and the one worth checking against the source. Older swings are history (they stay visible in
    the charts) and would bury the actionable warnings under thousands of past ones."""
    series: dict[tuple, dict[date, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.price_per_kg is None or r.price_per_kg <= 0:
            continue
        if r.frequency in OUTLIER_SKIP_FREQUENCIES:
            continue
        if r.price_type in UNIT_VALUE_TYPES and r.volume_kg is not None and r.volume_kg < BULK_MIN_KG:
            continue
        series[_identity(r)][r.period_start].append(r)
    out: list[Finding] = []
    for by_period in series.values():
        periods = sorted(by_period)
        if len(periods) <= OUTLIER_MIN_HISTORY:
            continue
        # one reference value per period (a series may carry several quotes for the same period)
        medians = [statistics.median(p.price_per_kg for p in by_period[d]) for d in periods]
        for i in range(len(periods) - 1, len(periods)):
            window = medians[max(0, i - OUTLIER_WINDOW):i]
            med = statistics.median(window)
            if med <= 0:
                continue
            mad = statistics.median(abs(v - med) for v in window)
            for r in by_period[periods[i]]:
                x = r.price_per_kg
                rel = (x - med) / med
                if mad > 0:
                    z: float | None = 0.6745 * (x - med) / mad
                else:
                    z = math.inf if x != med else 0.0
                limit = OUTLIER_MAX_REL_DEV_UNIT_VALUE if r.price_type in UNIT_VALUE_TYPES else OUTLIER_MAX_REL_DEV
                by_rel = abs(rel) > limit
                by_z = z is not None and abs(z) > OUTLIER_ROBUST_Z and abs(rel) > OUTLIER_Z_MIN_REL_DEV
                if not (by_rel or by_z):
                    continue
                src = src_by_id.get(r.source_id)
                unit = f"{r.currency}/kg"
                n = len(window)
                out.append(Finding(
                    dedup_key=f"outlier:price:{r.id}",
                    issue_type=QualityIssueType.OUTLIER.value,
                    severity=Severity.WARNING.value,
                    source_id=r.source_id,
                    entity_type="price_observation",
                    entity_id=r.id,
                    message_it=(f"{_series_label(r, src, 'it')}, {_period(r.period_label, 'it')}: "
                                f"{_num(x, 'it')} {unit} contro una mediana di {_num(med, 'it')} {unit} "
                                f"nei {n} periodi precedenti ({_pct(rel * 100, 'it')}). "
                                f"Può essere un errore di lettura o un movimento reale: verificare sul documento originale."),
                    message_en=(f"{_series_label(r, src, 'en')}, {_period(r.period_label, 'en')}: "
                                f"{_num(x, 'en')} {unit} against a median of {_num(med, 'en')} {unit} "
                                f"over the previous {n} periods ({_pct(rel * 100, 'en')}). "
                                f"It may be a reading error or a real move: check the original document."),
                    details={"value": round(x, 6), "median": round(med, 6), "deviation_pct": round(rel * 100, 2),
                             "robust_z": None if z is None or math.isinf(z) else round(z, 2),
                             "flat_history": mad == 0, "period": r.period_label, "unit": unit,
                             "window": [{"period": by_period[periods[j]][0].period_label, "value": round(medians[j], 6)}
                                        for j in range(max(0, i - OUTLIER_WINDOW), i)],
                             "rule": "relative" if by_rel else "robust_z",
                             "series": _series_details(r, src),
                             "link": _price_link(r.origin_iso3, r.variety, r.price_type)},
                ))
    return out


def _group_label(origin: str | None, variety: str, color: str | None, organic: bool, pt: str, market: str | None,
                 lang: str) -> str:
    parts = [_country(origin, lang), variety_label(variety, lang).lower() if lang == "it" else variety_label(variety, lang)]
    if color:
        parts.append(_color(color, lang))
    if organic:
        parts.append("biologico" if lang == "it" else "organic")
    parts.append(_price_type_label(pt, lang))
    if market:
        parts.append(("mercato " if lang == "it" else "market ") + country_name(market, lang))
    return ", ".join(parts)


def check_discrepancies(rows: list[Any], src_by_id: dict[int, Source]) -> list[Finding]:
    from ..api.prices import customs_line

    groups: dict[tuple, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.origin_iso3 or r.price_per_kg is None or r.price_per_kg <= 0:
            continue
        # Small consignments are not bulk prices (as for outliers and on the price pages).
        if r.price_type in UNIT_VALUE_TYPES and r.volume_kg is not None and r.volume_kg < BULK_MIN_KG:
            continue
        # colour grade and organic are part of "the same thing": white vs amber honey are different products;
        # so is the tariff line: an HTS-10 line (retail-packed honey) is never compared with the HS 0409 total
        key = (r.origin_iso3, r.variety, r.color_grade, r.price_type, r.market_iso3, bool(r.organic), r.period_start,
               r.period_end, customs_line(r.terms))
        groups[key][r.source_id].append(r)
    out: list[Finding] = []
    for key, per_source in groups.items():
        if len(per_source) < 2:
            continue
        all_rows = [r for rs in per_source.values() for r in rs]
        currencies = {r.currency for r in all_rows}
        if all(r.usd_per_kg for r in all_rows):
            field, unit = "usd_per_kg", "USD/kg"
        elif len(currencies) == 1:
            field, unit = "price_per_kg", f"{next(iter(currencies))}/kg"
        else:
            # mixed currencies without FX conversion: compare only sources that have USD values
            field, unit = "usd_per_kg", "USD/kg"
        values: dict[int, float] = {}
        for sid, rs in per_source.items():
            vals = [getattr(r, field) for r in rs if getattr(r, field)]
            if vals:
                values[sid] = statistics.median(vals)
        if len(values) < 2:
            continue
        lo_sid = min(values, key=values.get)
        hi_sid = max(values, key=values.get)
        lo, hi = values[lo_sid], values[hi_sid]
        if lo <= 0:
            continue
        diff = (hi - lo) / lo
        if diff <= DISCREPANCY_REL_DIFF:
            continue
        origin, variety, color, pt, market, organic, p_start, p_end, line = key
        sample = per_source[lo_sid][0]
        ordered = sorted(values.items(), key=lambda kv: kv[1])
        listing = {lang: "; ".join(f"{src_by_id[sid].name if sid in src_by_id else sid} {_num(v, lang)} {unit}"
                                   for sid, v in ordered) for lang in ("it", "en")}
        what = {lang: _group_label(origin, variety, color, organic, pt, market, lang) + (f", HTS {line}" if line else "")
                for lang in ("it", "en")}
        period = _period(sample.period_label, "it"), _period(sample.period_label, "en")
        out.append(Finding(
            dedup_key=(f"discrepancy:{pt}:{origin}:{variety}:{color or '-'}:{market or '-'}:{int(organic)}:{p_start}:{p_end}"
                       + (f":{line}" if line else "")),
            issue_type=QualityIssueType.DISCREPANCY.value,
            severity=Severity.WARNING.value,
            source_id=None,
            entity_type="price_group",
            message_it=(f"Le fonti non concordano su {what['it']}, {period[0]}: {listing['it']} "
                        f"(differenza {_pct(diff * 100, 'it', signed=False)}). Entrambi i valori restano visibili: nessuno viene scartato."),
            message_en=(f"Sources disagree on {what['en']}, {period[1]}: {listing['en']} "
                        f"(difference {_pct(diff * 100, 'en', signed=False)}). Both values stay visible: neither is discarded."),
            details={"difference_pct": round(diff * 100, 2), "unit": unit, "period": sample.period_label,
                     "origin_iso3": origin, "variety": variety, "color_grade": color, "price_type": pt,
                     "market_iso3": market, "organic": organic,
                     "values": [{"source_key": src_by_id[sid].key if sid in src_by_id else None,
                                 "source_name": src_by_id[sid].name if sid in src_by_id else None,
                                 "source_name_en": src_by_id[sid].name_en if sid in src_by_id else None,
                                 "value": round(v, 6), "observation_ids": [r.id for r in per_source[sid]]}
                                for sid, v in ordered],
                     "source_keys": [src_by_id[sid].key for sid, _ in ordered if sid in src_by_id],
                     "link": _price_link(origin, variety, pt)},
        ))
    return out


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _month_from_index(i: int) -> date:
    return date(i // 12, i % 12 + 1, 1)


def check_missing_months(rows: list[Any], src_by_id: dict[int, Source], today: date) -> list[Finding]:
    window_start = _month_index(today) - MISSING_WINDOW_MONTHS
    window_end = _month_index(today)
    months: dict[tuple, set[int]] = defaultdict(set)
    sample: dict[tuple, Any] = {}
    for r in rows:
        if r.frequency != "M":
            continue
        mi = _month_index(r.period_start)
        if window_start <= mi <= window_end:
            ident = _identity(r)
            months[ident].add(mi)
            sample.setdefault(ident, r)
    out: list[Finding] = []
    for ident, present in months.items():
        first, last = min(present), max(present)
        missing = [i for i in range(first, last + 1) if i not in present]
        if not missing:
            continue
        r = sample[ident]
        # Customs unit values exist only in months with a shipment: a gap on an irregular lane
        # (Italy importing Serbian honey a few times a year) is no trade, not missing data. Only a
        # gap in an otherwise regular lane (a single missing month) is worth a note.
        if r.price_type in UNIT_VALUE_TYPES and len(missing) > 1:
            continue
        src = src_by_id.get(r.source_id)
        miss_it = ", ".join(_month(_month_from_index(i), "it") for i in missing)
        miss_en = ", ".join(_month(_month_from_index(i), "en") for i in missing)
        f_d, l_d = _month_from_index(first), _month_from_index(last)
        n = len(missing)
        out.append(Finding(
            dedup_key=f"missing:price:{_identity_hash(ident)}",
            issue_type=QualityIssueType.MISSING.value,
            severity=Severity.INFO.value,
            source_id=r.source_id,
            entity_type="price_series",
            message_it=(f"{_series_label(r, src, 'it')}: "
                        f"{'manca 1 mese' if n == 1 else f'mancano {n} mesi'} tra {_month(f_d, 'it')} e {_month(l_d, 'it')} "
                        f"({miss_it}). I mesi mancanti non vengono stimati: nei grafici restano vuoti."),
            message_en=(f"{_series_label(r, src, 'en')}: "
                        f"{n} month{'s' if n != 1 else ''} missing between {_month(f_d, 'en')} and {_month(l_d, 'en')} "
                        f"({miss_en}). Missing months are not estimated: charts leave them empty."),
            details={"missing_periods": [f"{_month_from_index(i):%Y-%m}" for i in missing],
                     "first_period": f"{f_d:%Y-%m}", "last_period": f"{l_d:%Y-%m}",
                     "series": _series_details(r, src),
                     "link": _price_link(r.origin_iso3, r.variety, r.price_type)},
        ))
    return out


# ----------------------------------------------------------------------- trade
def _trade_label(r, source_name: str, lang: str) -> str:
    flow = _FLOW_LABELS.get(r.flow, {}).get(lang, r.flow)
    inbound = r.flow in ("import", "re_import")
    reporter, partner = country_name(r.reporter_iso3, lang), country_name(r.partner_iso3, lang)
    if lang == "it":
        return f"«{source_name}» {flow} {reporter} {'da' if inbound else 'verso'} {partner}, {_period(r.period_label, 'it')}"
    return f"“{source_name}” {reporter} {flow} {'from' if inbound else 'to'} {partner}, {_period(r.period_label, 'en')}"


def _trade_origin(r) -> str | None:
    """Where the honey comes from: the partner of an import, the reporter of an export."""
    return r.partner_iso3 if r.flow in ("import", "re_import") else r.reporter_iso3


def check_trade(session: Session, src_by_id: dict[int, Source], skip_source_ids: set[int]) -> list[Finding]:
    T = TradeFlowObservation
    # Only rows that matter for a bulk buyer: monthly/annual (not provisional weekly cells), from the
    # last two years, and bulk-size (>= 10 t) for the unit-value range. Odd tiny lots are normal in
    # customs data and are already kept out of the price views.
    since = date.today().replace(day=1) - timedelta(days=731)
    q = select(T.id, T.source_id, T.hs_code, T.reporter_iso3, T.partner_iso3, T.flow, T.net_weight_kg, T.value,
               T.currency, T.usd_value, T.period_label).where(
        T.is_current.is_(True), T.is_demo.is_(False), T.hs_code.like(f"{HONEY_HS_PREFIX}%"),
        T.frequency.in_(("M", "A")), T.period_start >= since)
    if skip_source_ids:
        q = q.where(T.source_id.not_in(skip_source_ids))
    out: list[Finding] = []
    for r in session.execute(q):
        src = src_by_id.get(r.source_id)
        what = {lang: _trade_label(r, src.name if src else "?", lang) for lang in ("it", "en")}
        link_params = f"reporter={r.reporter_iso3}&partner={r.partner_iso3}&flow={r.flow}"
        base = {"reporter_iso3": r.reporter_iso3, "partner_iso3": r.partner_iso3, "flow": r.flow,
                "period": r.period_label, "hs_code": r.hs_code, "value": r.value, "currency": r.currency,
                "net_weight_kg": r.net_weight_kg, "source_key": src.key if src else None,
                "link": f"/commercio?{link_params}"}
        if r.value and r.value >= 50_000 and r.net_weight_kg == 0:
            out.append(Finding(
                dedup_key=f"trade:zero_weight:{r.id}",
                issue_type=QualityIssueType.PARSE_WARNING.value,
                severity=Severity.WARNING.value,
                source_id=r.source_id,
                entity_type="trade_flow",
                entity_id=r.id,
                message_it=(f"{what['it']}: valore {_num(r.value, 'it', 0)} {r.currency} "
                            f"con peso pari a zero. Il valore unitario non è calcolabile."),
                message_en=(f"{what['en']}: value {_num(r.value, 'en', 0)} {r.currency} "
                            f"with zero weight. The unit value cannot be computed."),
                details={**base, "rule": "zero_weight"},
            ))
            continue
        if not r.net_weight_kg or r.net_weight_kg < BULK_MIN_KG or r.value is None:
            continue
        usd = r.usd_value if r.usd_value is not None else (r.value if (r.currency or "").upper() == "USD" else None)
        if usd is None:
            continue  # no FX conversion available: never guess
        uv = usd / r.net_weight_kg
        uv_max = TRADE_UV_MAX_USD_BY_ORIGIN.get(_trade_origin(r) or "", TRADE_UV_MAX_USD)
        if TRADE_UV_MIN_USD <= uv <= uv_max:
            continue
        rng_it = f"{_num(TRADE_UV_MIN_USD, 'it')}–{_num(uv_max, 'it', 0)}"
        rng_en = f"{_num(TRADE_UV_MIN_USD, 'en')}–{_num(uv_max, 'en', 0)}"
        out.append(Finding(
            dedup_key=f"trade:unit_value:{r.id}",
            issue_type=QualityIssueType.PARSE_WARNING.value,
            severity=Severity.WARNING.value,
            source_id=r.source_id,
            entity_type="trade_flow",
            entity_id=r.id,
            message_it=(f"{what['it']}: valore unitario {_num(uv, 'it')} USD/kg, "
                        f"fuori dall'intervallo plausibile {rng_it} USD/kg per il miele (HS 0409). "
                        f"Valore {_num(usd, 'it', 0)} USD, peso {_num(r.net_weight_kg, 'it', 0)} kg."),
            message_en=(f"{what['en']}: unit value {_num(uv, 'en')} USD/kg, "
                        f"outside the plausible range {rng_en} USD/kg for honey (HS 0409). "
                        f"Value {_num(usd, 'en', 0)} USD, weight {_num(r.net_weight_kg, 'en', 0)} kg."),
            details={**base, "rule": "unit_value", "unit_value_usd_per_kg": round(uv, 4), "usd_value": usd,
                     "range_usd_per_kg": [TRADE_UV_MIN_USD, uv_max]},
        ))
    return out


# ---------------------------------------------------------------------- upsert
def _upsert(session: Session, findings: list[Finding], now: datetime) -> dict:
    by_key: dict[str, Finding] = {}
    for f in findings:
        prev = by_key.get(f.dedup_key)
        if prev is None or _SEVERITY_RANK.get(f.severity, 9) < _SEVERITY_RANK.get(prev.severity, 9):
            by_key[f.dedup_key] = f
    existing = {
        i.dedup_key: i for i in session.scalars(select(DataQualityIssue))
        if i.dedup_key.startswith(OWNED_PREFIXES)
    }
    stats = {"detected": len(by_key), "new": 0, "reopened": 0, "updated": 0, "resolved": 0}
    for key, f in by_key.items():
        row = existing.get(key)
        if row is None:
            session.add(DataQualityIssue(
                dedup_key=key, issue_type=f.issue_type, severity=f.severity, entity_type=f.entity_type,
                entity_id=f.entity_id, source_id=f.source_id, message_it=f.message_it, message_en=f.message_en,
                details=f.details, detected_at=now, last_seen_at=now, resolved_at=None,
            ))
            stats["new"] += 1
            continue
        if row.resolved_at is not None:
            row.resolved_at = None
            row.detected_at = now
            stats["reopened"] += 1
        else:
            stats["updated"] += 1
        row.issue_type = f.issue_type
        row.severity = f.severity
        row.entity_type = f.entity_type
        row.entity_id = f.entity_id
        row.source_id = f.source_id
        row.message_it = f.message_it
        row.message_en = f.message_en
        row.details = f.details
        row.last_seen_at = now
    for key, row in existing.items():
        if key not in by_key and row.resolved_at is None:
            row.resolved_at = now
            stats["resolved"] += 1
    session.flush()
    return stats


def run_checks(session: Session, today: date | None = None, now: datetime | None = None) -> dict:
    """Run every check, upsert issues, auto-resolve the ones no longer detected.

    The caller commits (``session_scope`` does it automatically)."""
    now = now or utcnow()
    today = today or now.date()
    with _lock:
        sources = list(session.scalars(select(Source)))
        src_by_id = {s.id: s for s in sources}
        skip_ids = {s.id for s in sources if _is_demo_source(s)}
        findings: list[Finding] = []
        findings += check_stale(sources, today)
        findings += check_collection(session, sources)
        findings += check_missing_keys(sources)
        prices = _load_prices(session, skip_ids)
        findings += check_outliers(prices, src_by_id)
        findings += check_discrepancies(prices, src_by_id)
        findings += check_missing_months(prices, src_by_id, today)
        findings += check_trade(session, src_by_id, skip_ids)
        stats = _upsert(session, findings, now)
        setting = session.get(AppSetting, LAST_RUN_SETTING)
        if setting is None:
            session.add(AppSetting(key=LAST_RUN_SETTING, value=now.isoformat()))
        else:
            setting.value = now.isoformat()
        session.flush()
    stats["open"] = session.scalar(
        select(func.count(DataQualityIssue.id)).where(DataQualityIssue.resolved_at.is_(None))
    ) or 0
    stats["checked_at"] = now.isoformat()
    stats["price_rows"] = len(prices)
    log.info("quality checks: %s", stats)
    return stats
