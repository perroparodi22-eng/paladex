"""Corrections made by a person to stored figures (docs/ARCHITECTURE.md, "Corrections").

Someone who knows the market (the owner's father, on his own installation) finds a figure wrong,
says so in plain words, confirms the proposed change himself, and the corrected value then shows
everywhere with "corrected by <name> on <date>", the official value staying in the history.

Rules:

* Append-only. A ``value_correction`` is written as a NEW revision of the same series (same source,
  same ``series_key``) through ``services.ingest.add_revision``: the official row is kept with
  ``is_current = False``; the correction row has reliability ``user``, status ``user_entered``,
  every derived field recomputed exactly as the collectors do (price per kg with
  ``ingest.per_kg``, USD/EUR with ``fx.normalise_price`` / ``fx.normalise_trade``, trade unit value =
  value / weight) and ``extra.correction`` = who, when, why and the official value. A ``revert`` is
  another new revision with the official values restored; nothing is ever flipped back or deleted.
* The value is stored in the series' own unit and currency (a USD/lb series stays USD/lb): a value
  typed per kg or in euro is converted with the exact mass factors and, for a currency, the ECB rate
  of the figure's period (`fx.conversion_factor`, as at ingest). What was typed is kept in the event.
* Demonstration rows are never corrected.
* A correction is an event (models_corrections.CorrectionEvent) with a global id, exchanged
  between the owner's computers through git (services/corrections_sync.py). Applying an event is
  idempotent by event id. A received correction is applied only when this computer's official value
  is the one the author saw (``official_hash``); otherwise it is a ``conflict`` (or
  ``superseded_by_source`` when the source has since published another value), shown, never forced.
* When the source publishes a new value over a correction, the source wins (services/ingest.py):
  the event becomes ``superseded_by_source`` and a notice is raised (an alert event).

Event status (this computer): value_correction: applied | replaced (a newer correction of the same
figure) | superseded_by_source | confirmed_by_source (the source now publishes the corrected value) |
conflict | waiting (the figure is not on this computer yet; retried at each sync) | reverted.
revert: applied | waiting. flag_wrong and note: recorded | reverted.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AlertEvent,
    AppSetting,
    DataQualityIssue,
    PriceObservation,
    ProductionStat,
    Source,
    TradeFlowObservation,
    utcnow,
)
from ..models_corrections import CorrectionEvent
from ..reference.countries import country_name
from ..reference.varieties import variety_label
from . import fx, ingest

log = logging.getLogger(__name__)

FORMAT = "paladex-correction"
FORMAT_VERSION = 1
DEFAULT_AUTHOR = "Utente"
AUTHOR_SETTING = "corrections_author"
DEVICE_SETTING = "corrections_device_id"

# Tables a value can be corrected in (more can be added: a model, its value field and a normaliser).
TABLES: dict[str, type] = {
    "price_observations": PriceObservation,
    "trade_flows": TradeFlowObservation,
    "production_stats": ProductionStat,
}
TABLE_OF = {m: t for t, m in TABLES.items()}
KINDS = ("value_correction", "revert", "flag_wrong", "note")
# Alert / data-quality references understood by the alerts page (api/alerts.py _REF_MODELS).
REF_TYPE = {"price_observations": "price", "trade_flows": "trade"}
TRADE_FIELDS = ("net_weight_kg", "value")
MASS_UNITS = {"kg": 1.0, "t": 1000.0, "tonne": 1000.0, "tonnes": 1000.0}
UNIT_ALIASES = {
    "kgs": "kg", "kilo": "kg", "kili": "kg", "chilo": "kg", "chili": "kg", "kilogram": "kg", "kilogrammo": "kg",
    "lbs": "lb", "libbra": "lb", "libbre": "lb", "pound": "lb", "pounds": "lb",
    "ton": "t", "tons": "t", "tonnellata": "t", "tonnellate": "t", "tonne": "t", "tonnes": "t", "mt": "t",
    "quintale": "q", "quintali": "q", "qt": "q", "100 kg": "100kg", "grammi": "g", "gram": "g",
}
CURRENCY_ALIASES = {"€": "EUR", "EURO": "EUR", "EUROS": "EUR", "$": "USD", "US$": "USD", "DOLLARI": "USD",
                    "DOLLARO": "USD", "DOLLAR": "USD", "DOLLARS": "USD"}
# Statuses where an event is finished on this computer (no retry at the next sync).
FINAL_STATUSES = frozenset({"applied", "replaced", "superseded_by_source", "confirmed_by_source", "reverted",
                            "recorded"})
RETRY_STATUSES = frozenset({"waiting", "conflict"})
MAX_TEXT = 2000

PRICE_TYPE_WORDS = {
    "wholesale_bulk": {"it": "ingrosso", "en": "wholesale"},
    "producer": {"it": "al produttore", "en": "producer"},
    "import_unit_value": {"it": "valore unitario import", "en": "import unit value"},
    "export_unit_value": {"it": "valore unitario export", "en": "export unit value"},
    "retail": {"it": "dettaglio", "en": "retail"},
    "other": {"it": "altro", "en": "other"},
}
METRIC_WORDS = {
    "production": {"it": "produzione", "en": "production"},
    "colonies": {"it": "alveari", "en": "colonies"},
    "yield_per_colony": {"it": "resa per alveare", "en": "yield per colony"},
    "producer_price": {"it": "prezzo al produttore", "en": "producer price"},
    "stocks": {"it": "scorte", "en": "stocks"},
}
FLOW_WORDS = {"import": {"it": "import", "en": "imports"}, "export": {"it": "export", "en": "exports"}}


class CorrectionError(Exception):
    """A request that cannot be carried out. `code` is stable (the interface translates it)."""

    def __init__(self, code: str, message_it: str, message_en: str, status: int = 422, **extra):
        super().__init__(message_en)
        self.code, self.status = code, status
        self.message_it, self.message_en = message_it, message_en
        self.extra = extra

    def detail(self) -> dict:
        return {"code": self.code, "message_it": self.message_it, "message_en": self.message_en, **self.extra}


# ---------------------------------------------------------------------------
# Who and where
# ---------------------------------------------------------------------------


def _setting(session: Session, key: str):
    row = session.get(AppSetting, key)
    return None if row is None else row.value


def _set_setting(session: Session, key: str, value) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def author_name(session: Session) -> str:
    """The name shown on this computer's corrections: chosen on screen, else PALADEX_USER_NAME, else 'Utente'."""
    v = _setting(session, AUTHOR_SETTING)
    if isinstance(v, str) and v.strip():
        return v.strip()[:120]
    return ((get_settings().user_name or "").strip() or DEFAULT_AUTHOR)[:120]


def set_author_name(session: Session, name: str | None) -> str:
    clean = re.sub(r"\s+", " ", (name or "")).strip()
    if len(clean) > 120 or any(ord(ch) < 32 for ch in clean):
        raise CorrectionError("invalid_author", "Nome non valido (al massimo 120 caratteri).",
                              "Invalid name (120 characters at most).")
    _set_setting(session, AUTHOR_SETTING, clean or None)
    return author_name(session)


def device_id(session: Session) -> str:
    """A random id of this installation, created once (tells apart events made here from received ones)."""
    v = _setting(session, DEVICE_SETTING)
    if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{32}", v):
        return v
    new = uuid.uuid4().hex
    _set_setting(session, DEVICE_SETTING, new)
    session.flush()
    return new


def iso_utc(dt: datetime | None) -> str | None:
    """'2026-11-06T09:12:00.123456Z' (stored datetimes are naive UTC; microseconds kept, so an event's
    time reads back identical on every computer and orders events exactly)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None).isoformat(timespec="microseconds" if dt.microsecond else "seconds") + "Z"


def parse_utc(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Figures: identity, labels, main value
# ---------------------------------------------------------------------------


def main_field(table: str, field: str | None = None) -> str:
    if table == "price_observations":
        return "price_value"
    if table == "trade_flows":
        return field if field in TRADE_FIELDS else "net_weight_kg"
    return "value"


def unit_currency(table: str, row, field: str | None = None) -> tuple[str | None, str | None]:
    """(unit, currency) of the main value of a row as stored."""
    if table == "price_observations":
        return row.unit, row.currency
    if table == "trade_flows":
        return ("kg", None) if main_field(table, field) == "net_weight_kg" else (None, row.currency)
    return row.unit, None


def figure_country(table: str, row) -> str | None:
    if table == "price_observations":
        return row.origin_iso3 or row.market_iso3
    if table == "trade_flows":
        return row.reporter_iso3
    return row.country_iso3


def figure_label(table: str, row, lang: str = "it", field: str | None = None) -> str:
    """'Argentina · Millefiori · ingrosso (USA) · 2026-09' (no source name: that is next to it)."""
    parts: list[str] = []
    if table == "price_observations":
        parts.append(country_name(row.origin_iso3, lang) or row.origin_label or "—")
        if row.variety and row.variety != "unspecified":
            parts.append(variety_label(row.variety, lang))
        if row.color_grade:
            parts.append(row.color_grade)
        pt = PRICE_TYPE_WORDS.get(row.price_type, {}).get(lang, row.price_type)
        if row.market_iso3 and row.market_iso3 != row.origin_iso3:
            pt += f" ({country_name(row.market_iso3, lang) or row.market_iso3})"
        parts.append(pt)
    elif table == "trade_flows":
        parts.append(country_name(row.reporter_iso3, lang) or row.reporter_iso3)
        flow = FLOW_WORDS.get(row.flow, {}).get(lang, row.flow)
        partner = "mondo" if lang == "it" else "world"
        if row.partner_iso3 != "WLD":
            partner = country_name(row.partner_iso3, lang) or row.partner_iso3
        parts.append(f"{flow} → {partner}" if row.flow in ("export", "re_export") else f"{flow} ← {partner}")
        if main_field(table, field) == "value":
            parts.append("valore" if lang == "it" else "value")
        else:
            parts.append("quantità" if lang == "it" else "quantity")
    else:
        parts.append(country_name(row.country_iso3, lang) or row.country_iso3)
        parts.append(METRIC_WORDS.get(row.metric, {}).get(lang, row.metric))
        region = (row.extra or {}).get("region") if isinstance(getattr(row, "extra", None), dict) else None
        if region:
            parts.append(str(region))
    parts.append(row.period_label)
    return " · ".join(p for p in parts if p)


def figure_link(table: str, row) -> str:
    """In-app page where the figure is shown."""
    if table == "price_observations":
        q = f"/prezzi?tipo={row.price_type}"
        if row.origin_iso3:
            q += f"&origini={row.origin_iso3}"
        return q
    iso3 = figure_country(table, row)
    return f"/paesi/{iso3}" if iso3 else "/"


def fmt_num(v: float | None, lang: str = "it") -> str:
    """1.795 -> '1,795', 3.4 -> '3,40', 1.542214 -> '1,5422', 8035260.4 -> '8.035.260' (Italian)."""
    if v is None:
        return "—"
    if abs(v) >= 1000:
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.4f}".rstrip("0")
        s = s + "0" * max(0, 2 - len(s.split(".")[1])) if "." in s else s
    if lang == "it":
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def fmt_value(v: float | None, unit: str | None, currency: str | None, lang: str = "it") -> str:
    tail = f"{currency}/{unit}" if currency and unit else (currency or unit or "")
    return f"{fmt_num(v, lang)} {tail}".strip()


def fmt_day(dt: datetime | date | None, lang: str = "it") -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d/%m/%Y") if lang == "it" else dt.strftime("%Y-%m-%d")


def value_fields(model: type, row) -> dict:
    return {k: getattr(row, k) for k in ingest.VALUE_FIELDS[model]}


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# Corrected rows: what the API shows
# ---------------------------------------------------------------------------

PUBLIC_KEYS = ("event_id", "author", "created_at", "reason", "field", "official_value", "corrected_value", "unit",
               "currency", "official_per_kg")


def public_brief(corr: dict | None) -> dict | None:
    """The `correction` object of the API answers: who corrected the figure, when, why, and the
    official value it replaced (in the unit and currency of the table)."""
    if not isinstance(corr, dict) or not corr.get("event_id"):
        return None
    return {k: corr.get(k) for k in PUBLIC_KEYS}


def row_correction(row) -> dict | None:
    """`public_brief` of a row loaded with its `extra` (attached to a session or fully loaded);
    None for every row that is not a correction (reliability is read first: no extra load)."""
    if getattr(row, "reliability", None) != "user":
        return None
    try:
        extra = row.extra
    except Exception:  # noqa: BLE001 - detached row without its extra: the caller uses briefs_by_id
        return None
    return public_brief(extra.get("correction")) if isinstance(extra, dict) else None


def briefs_by_id(session: Session, model: type, ids) -> dict[int, dict]:
    """{row id: public_brief} for the corrected rows among `ids` (one query, by primary key)."""
    want = sorted({i for i in ids if i is not None})
    out: dict[int, dict] = {}
    for i in range(0, len(want), 500):
        for rid, extra in session.execute(select(model.id, model.extra).where(model.id.in_(want[i:i + 500]))):
            b = public_brief(extra.get("correction")) if isinstance(extra, dict) else None
            if b:
                out[rid] = b
    return out


def newest_brief(briefs) -> dict | None:
    have = [b for b in briefs if b]
    return max(have, key=lambda b: (b.get("created_at") or "", b.get("event_id") or "")) if have else None


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


def _model(table: str | None) -> type:
    model = TABLES.get(table or "")
    if model is None:
        raise CorrectionError("unsupported_table", "Questo tipo di dato non si può correggere.",
                              "This kind of figure cannot be corrected.", allowed=list(TABLES))
    return model


def _source_by_key(session: Session, key: str | None) -> Source | None:
    return session.scalars(select(Source).where(Source.key == key)).first() if key else None


def resolve_target(session: Session, table: str, *, row_id: int | None = None, source_key: str | None = None,
                   series_key: str | None = None):
    """(model, current row) of the figure named by a row id (any revision of its series) or by
    (source key, series key). Raises CorrectionError (404 not found, 409 demo / withdrawn)."""
    model = _model(table)
    if row_id is not None:
        row = session.get(model, row_id)
        if row is None:
            raise CorrectionError("not_found", "Dato non trovato.", "Figure not found.", status=404)
        source_id, skey, demo = row.source_id, row.series_key, bool(row.is_demo)
    else:
        src = _source_by_key(session, source_key)
        if src is None or not series_key:
            raise CorrectionError("not_found", "Dato non trovato.", "Figure not found.", status=404)
        source_id, skey, demo = src.id, series_key, False
    if demo:
        raise CorrectionError("demo_row", "I dati dimostrativi non si correggono.",
                              "Demonstration data cannot be corrected.", status=409)
    current = ingest.current_row(session, model, source_id, skey)
    if current is None:
        raise CorrectionError("withdrawn", "La fonte non pubblica più questo dato: non c'è un valore attuale da correggere.",
                              "The source no longer publishes this figure: there is no current value to correct.",
                              status=409)
    return model, current


def official_of(session: Session, model: type, current):
    """The official row behind the current one: itself, or the row a correction replaced."""
    corr = ingest.correction_of(current)
    if corr is None:
        return current
    official = session.get(model, corr.get("official_row_id")) if corr.get("official_row_id") else None
    return official or current


# ---------------------------------------------------------------------------
# Normalising a typed value into the table's unit and currency
# ---------------------------------------------------------------------------


def clean_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = str(unit).strip().lower().replace("/", "").replace("per ", "").strip()
    u = UNIT_ALIASES.get(u, u)
    return u or None


def clean_currency(currency: str | None) -> str | None:
    if currency is None:
        return None
    c = str(currency).strip().upper()
    c = CURRENCY_ALIASES.get(c, c)
    if not c:
        return None
    if not re.fullmatch(r"[A-Z]{3}", c):
        raise CorrectionError("invalid_currency", f"Valuta non riconosciuta: {currency}.", f"Unknown currency: {currency}.")
    return c


def _number(v, name: str) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.strip().replace(" ", "")
        if "," in v and "." in v:
            v = v.replace(".", "").replace(",", ".") if v.rfind(",") > v.rfind(".") else v.replace(",", "")
        else:
            v = v.replace(",", ".")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CorrectionError("invalid_value", f"Numero non valido ({name}).", f"Invalid number ({name}).") from None
    if not math.isfinite(f) or f < 0 or isinstance(v, bool):
        raise CorrectionError("invalid_value", f"Numero non valido ({name}).", f"Invalid number ({name}).")
    return f


def _fx_factor(session: Session, row, from_ccy: str, to_ccy: str) -> float:
    if from_ccy == to_ccy:
        return 1.0
    conv = fx.conversion_factor(session, from_ccy, to_ccy, period_start=row.period_start, period_end=row.period_end,
                                frequency=row.frequency)
    if conv is None:
        raise CorrectionError(
            "fx_unavailable",
            f"Manca il cambio {from_ccy}/{to_ccy} per questo periodo: inserire il valore in {to_ccy}.",
            f"No {from_ccy}/{to_ccy} exchange rate for this period: enter the value in {to_ccy}.",
            currency=to_ccy)
    return conv[0]


def normalize(session: Session, table: str, row, *, value, low=None, high=None, unit: str | None = None,
              currency: str | None = None, field: str | None = None) -> dict:
    """What a typed value becomes in `row`'s table: {"field", "fields" (the value columns to store),
    "main" (main value as stored), "entered" (as typed)}. Raises CorrectionError."""
    v = _number(value, "value")
    if v is None:
        raise CorrectionError("missing_value", "Serve il valore corretto.", "The corrected value is required.")
    lo, hi = _number(low, "low"), _number(high, "high")
    unit_in, ccy_in = clean_unit(unit), clean_currency(currency)
    entered = {"value": v, "low": lo, "high": hi, "unit": unit_in, "currency": ccy_in}
    if table == "price_observations":
        to_unit, to_ccy = row.unit, row.currency
        u = unit_in or to_unit
        if u != to_unit and (u not in ingest.KG_PER_UNIT or to_unit not in ingest.KG_PER_UNIT):
            raise CorrectionError("unit_mismatch", f"Unità non convertibile in {to_unit}.",
                                  f"Unit cannot be converted to {to_unit}.", unit=to_unit)
        factor = (ingest.KG_PER_UNIT[to_unit] / ingest.KG_PER_UNIT[u]) if u != to_unit else 1.0
        factor *= _fx_factor(session, row, ccy_in or to_ccy, to_ccy)
        conv = [None if x is None else round(x * factor, 6) for x in (v, lo, hi)]
        if conv[1] is not None and conv[2] is not None and conv[1] > conv[2]:
            raise CorrectionError("invalid_range", "Il minimo supera il massimo.", "The low is above the high.")
        fields = {"price_value": conv[0], "price_low": conv[1], "price_high": conv[2], "currency": to_ccy,
                  "unit": to_unit, "volume_kg": row.volume_kg, "data_status": "user_entered"}
        entered.update(unit=u, currency=ccy_in or to_ccy)
        return {"field": "price_value", "fields": fields, "main": conv[0], "entered": entered}
    if table == "trade_flows":
        f = field if field in TRADE_FIELDS else None
        if f is None:
            f = "net_weight_kg" if unit_in and (unit_in in ingest.KG_PER_UNIT) else "value" if ccy_in else None
        if f is None:
            raise CorrectionError("trade_field", "Indicare se si corregge la quantità (kg, t) o il valore (valuta).",
                                  "Say whether the quantity (kg, t) or the value (currency) is corrected.")
        kg, val = row.net_weight_kg, row.value
        if f == "net_weight_kg":
            u = unit_in or "kg"
            if u not in ingest.KG_PER_UNIT:
                raise CorrectionError("unit_mismatch", "Unità di peso non riconosciuta.", "Unknown unit of weight.", unit="kg")
            kg = round(v * ingest.KG_PER_UNIT[u], 3)
            main = kg
            entered.update(unit=u, currency=None)
        else:
            val = round(v * _fx_factor(session, row, ccy_in or row.currency, row.currency), 2)
            main = val
            entered.update(unit=None, currency=ccy_in or row.currency)
        fields = {"net_weight_kg": kg, "value": val, "currency": row.currency, "value_basis": row.value_basis,
                  "data_status": "user_entered"}
        return {"field": f, "fields": fields, "main": main, "entered": entered}
    # production_stats
    to_unit = row.unit
    u = unit_in or to_unit
    if u != to_unit:
        a, b = MASS_UNITS.get(u if u != "tonne" else "t"), MASS_UNITS.get((to_unit or "").lower())
        if a is None or b is None:
            raise CorrectionError("unit_mismatch", f"Unità non convertibile in {to_unit}.",
                                  f"Unit cannot be converted to {to_unit}.", unit=to_unit)
        v = v * a / b
    val = round(v, 6)
    entered.update(unit=u, currency=None)
    fields = {"value": val, "unit": to_unit, "flag_raw": None, "data_status": "user_entered"}
    return {"field": "value", "fields": fields, "main": val, "entered": entered}


# Value fields that describe the figure's status or context rather than its value: not compared when
# deciding whether two rows say the same thing (a correction carries no FAOSTAT flag).
_CONTEXT_FIELDS = {"data_status", "flag_raw", "volume_kg", "value_basis"}


def _same_values(model: type, a: dict, b: dict) -> bool:
    """The value fields of two rows are equal (status, flags and context fields aside)."""
    keys = [k for k in ingest.VALUE_FIELDS[model] if k not in _CONTEXT_FIELDS]
    return all(ingest._canon(a.get(k)) == ingest._canon(b.get(k)) for k in keys)


# ---------------------------------------------------------------------------
# Writing rows
# ---------------------------------------------------------------------------

_NOT_COPIED = {"id", "revision", "is_current", "supersedes_id", "value_hash", "collected_at", "last_seen_at",
               "source_id", "series_key", "is_demo"}


def _copy_columns(model: type, row) -> dict:
    return {c.key: getattr(row, c.key) for c in model.__table__.columns if c.key not in _NOT_COPIED}


def _base_extra(row) -> dict:
    extra = dict(row.extra) if isinstance(row.extra, dict) else {}
    extra.pop("correction", None)
    extra.pop("reverted_correction", None)
    return extra


def _recompute_derived(session: Session, model: type, row) -> None:
    """Derived columns, as the collectors compute them (collectors/base.py add_price / add_trade)."""
    if model is PriceObservation:
        fx.normalise_price(session, row)
    elif model is TradeFlowObservation:
        fx.normalise_trade(session, row)
    session.flush()


def _note_text(ev: CorrectionEvent, unit: str | None, ccy: str | None) -> str:
    """The row's `notes`, in plain words (Italian, then English)."""
    out = []
    for lang in ("it", "en"):
        corrected = fmt_value(ev.corrected_value, unit, ccy, lang)
        e = ev.entered or {}
        if e.get("value") is not None and (e.get("unit") != unit or (ccy and e.get("currency") != ccy)):
            typed = fmt_value(e["value"], e.get("unit"), e.get("currency"), lang)
            corrected += f" ({'inserito come' if lang == 'it' else 'entered as'} {typed})"
        official = fmt_value(ev.official_value, unit, ccy, lang)
        why = (f" {'Motivo' if lang == 'it' else 'Reason'}: {ev.reason}." if ev.reason else "")
        if lang == "it":
            out.append(f"Valore corretto da {ev.author} il {fmt_day(ev.created_at, 'it')}: {corrected} al posto del "
                       f"valore ufficiale {official} (conservato nello storico).{why}")
        else:
            out.append(f"Corrected by {ev.author} on {fmt_day(ev.created_at, 'en')}: {corrected} instead of the "
                       f"official value {official} (kept in the history).{why}")
    return "\n".join(out)


def _write_correction_row(session: Session, model: type, ev: CorrectionEvent, current, official):
    table = TABLE_OF[model]
    fields = _copy_columns(model, official)
    fields.update(ev.normalized or {})
    fields["data_status"] = "user_entered"
    fields["reliability"] = "user"
    unit, ccy = unit_currency(table, official, ev.target_field)
    corr = {
        "event_id": ev.event_id, "author": ev.author, "created_at": iso_utc(ev.created_at), "reason": ev.reason,
        "field": ev.target_field, "official_value": ev.official_value, "corrected_value": ev.corrected_value,
        "unit": unit, "currency": ccy, "official_row_id": official.id, "official_hash": official.value_hash,
        "entered": ev.entered,
    }
    if model is PriceObservation:
        fields["price_per_kg"] = round(ingest.per_kg(fields["price_value"], fields["unit"]), 6)
        corr["official_per_kg"] = {"native": official.price_per_kg, "USD": official.usd_per_kg,
                                   "EUR": official.eur_per_kg, "currency": official.currency}
    elif model is TradeFlowObservation:
        kg, val = fields.get("net_weight_kg"), fields.get("value")
        fields["unit_value_per_kg"] = round(val / kg, 4) if val and kg else None
    fields["extra"] = {**_base_extra(official), "correction": corr}
    fields["notes"] = _note_text(ev, unit, ccy)
    row = ingest.add_revision(session, model, current, **fields)
    _recompute_derived(session, model, row)
    return row


def _write_revert_row(session: Session, model: type, ev: CorrectionEvent, target: CorrectionEvent, current, official):
    """A new revision with the official values restored (a copy of the official row)."""
    fields = _copy_columns(model, official)
    fields["collected_at"] = official.collected_at       # when the restored values were really collected
    fields["extra"] = {**_base_extra(official), "reverted_correction": {
        "event_id": target.event_id, "revert_event_id": ev.event_id, "author": ev.author,
        "reverted_at": iso_utc(ev.created_at), "corrected_by": target.author}}
    return ingest.add_revision(session, model, current, **fields)


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------


def _notice(session: Session, ev: CorrectionEvent, key: str, *, severity: str, title_it: str, title_en: str,
            body_it: str, body_en: str, link: str | None, ref_row_id: int | None) -> None:
    dedup = f"correction:{ev.event_id}:{key}"[:200]
    if session.scalars(select(AlertEvent.id).where(AlertEvent.rule_id.is_(None), AlertEvent.dedup_key == dedup)).first():
        return
    session.add(AlertEvent(rule_id=None, dedup_key=dedup, triggered_at=utcnow(), severity=severity,
                           title_it=title_it[:500], title_en=title_en[:500], body_it=body_it, body_en=body_en,
                           link=link, ref_type=REF_TYPE.get(ev.target_table or "") if ref_row_id else None,
                           ref_id=ref_row_id))


def _source_name(session: Session, key: str | None, lang: str) -> str:
    src = _source_by_key(session, key)
    if src is None:
        return key or "—"
    return src.name if lang == "it" else (src.name_en or src.name)


def on_source_superseded(session: Session, model: type, correction_row, new_row, corr: dict) -> None:
    """Called by ingest.record when the source publishes a value over a correction: the source wins."""
    ev = get_event(session, corr.get("event_id"))
    table = TABLE_OF[model]
    new_vals = value_fields(model, new_row)
    confirmed = _same_values(model, new_vals, value_fields(model, correction_row))
    field = corr.get("field") or main_field(table)
    unit, ccy = unit_currency(table, new_row, field)
    new_main = getattr(new_row, main_field(table, field))
    if ev is not None:
        ev.status = "confirmed_by_source" if confirmed else "superseded_by_source"
        ev.status_detail = {"official_row_id": new_row.id, "new_official_value": new_main, "unit": unit,
                            "currency": ccy, "at": iso_utc(utcnow())}
    author = corr.get("author") or "?"
    label_it, label_en = figure_label(table, new_row, "it", field), figure_label(table, new_row, "en", field)
    src_it, src_en = _source_name(session, ev.source_key if ev else None, "it"), _source_name(session, ev.source_key if ev else None, "en")
    when = parse_utc(corr.get("created_at"))
    corrected = fmt_value(corr.get("corrected_value"), unit, ccy)
    if confirmed:
        t_it = f"La fonte ora pubblica il valore corretto da {author}"
        t_en = f"The source now publishes the value corrected by {author}"
        b_it = (f"{label_it}: {src_it} pubblica ora {fmt_value(new_main, unit, ccy)}, il valore inserito da {author} "
                f"il {fmt_day(when, 'it')}. Il dato mostrato è di nuovo quello ufficiale della fonte.")
        b_en = (f"{label_en}: {src_en} now publishes {fmt_value(new_main, unit, ccy, 'en')}, the value entered by "
                f"{author} on {fmt_day(when, 'en')}. The figure shown is the source's official one again.")
    else:
        t_it = f"La fonte ha pubblicato un nuovo valore dopo la correzione di {author}"
        t_en = f"The source published a new value after the correction by {author}"
        b_it = (f"{label_it}: {src_it} pubblica ora {fmt_value(new_main, unit, ccy)}. La correzione di {author} del "
                f"{fmt_day(when, 'it')} ({corrected}, motivo: {corr.get('reason') or '—'}) resta nello storico; "
                f"il dato mostrato è il nuovo valore della fonte. Se è ancora sbagliato, si può correggere di nuovo.")
        b_en = (f"{label_en}: {src_en} now publishes {fmt_value(new_main, unit, ccy, 'en')}. The correction by "
                f"{author} of {fmt_day(when, 'en')} ({fmt_value(corr.get('corrected_value'), unit, ccy, 'en')}, reason: "
                f"{corr.get('reason') or '—'}) stays in the history; the figure shown is the source's new value. "
                f"If it is still wrong, it can be corrected again.")
    try:
        _notice(session, ev or _FakeEvent(corr.get("event_id"), table), "source", severity="warning",
                title_it=t_it, title_en=t_en, body_it=b_it, body_en=b_en,
                link=figure_link(table, new_row), ref_row_id=new_row.id)
    except Exception:  # pragma: no cover - a notice never stops a collection
        log.exception("correction notice not recorded")


def on_source_withdrawn(session: Session, model: type, correction_row, corr: dict) -> None:
    """Called by ingest.retire when the source withdraws a series whose current value is a correction."""
    ev = get_event(session, corr.get("event_id"))
    if ev is not None and ev.status == "applied":
        ev.status = "superseded_by_source"
        ev.status_detail = {"withdrawn": True, "at": iso_utc(utcnow())}


class _FakeEvent:
    """Stand-in when a corrected row's event is unknown here (never expected; keeps notices working)."""

    def __init__(self, event_id: str | None, table: str):
        self.event_id, self.target_table = event_id or "unknown", table


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def get_event(session: Session, event_id: str | None) -> CorrectionEvent | None:
    if not event_id:
        return None
    return session.scalars(select(CorrectionEvent).where(CorrectionEvent.event_id == event_id)).first()


def _clean_text(text: str | None, name: str = "reason") -> str | None:
    if text is None:
        return None
    t = str(text).replace("\r\n", "\n").strip()
    if len(t) > MAX_TEXT:
        raise CorrectionError("text_too_long", f"Testo troppo lungo (al massimo {MAX_TEXT} caratteri).",
                              f"Text too long ({MAX_TEXT} characters at most).", field=name)
    return t or None


def _new_event(session: Session, kind: str, *, after: datetime | None = None, **cols) -> CorrectionEvent:
    """A new local event. `after`: the time of what it replaces or undoes; the new event is always
    later (even with another computer's clock ahead), so every computer applies them in the same order."""
    now = utcnow()
    if after is not None and now <= after:
        now = after + timedelta(microseconds=1)
    ev = CorrectionEvent(event_id=str(uuid.uuid4()), created_at=now,
                         author=author_name(session), device_id=device_id(session), kind=kind, origin="local",
                         status="new", sync_status="pending_sync", **cols)
    session.add(ev)
    return ev


def _target_columns(table: str, official, field: str | None = None) -> dict:
    unit, ccy = unit_currency(table, official, field)
    return {"target_table": table, "series_key": official.series_key, "period_label": official.period_label,
            "target_unit": unit, "target_currency": ccy, "target_field": main_field(table, field),
            "country_iso3": figure_country(table, official), "label": figure_label(table, official, "it", field),
            "official_hash": official.value_hash, "official_before": _jsonable(value_fields(TABLES[table], official)),
            "official_value": getattr(official, main_field(table, field)), "target_row_id": official.id}


def create_event(session: Session, kind: str, *, table: str | None = None, row_id: int | None = None,
                 source_key: str | None = None, series_key: str | None = None, value=None, low=None, high=None,
                 unit: str | None = None, currency: str | None = None, field: str | None = None,
                 reason: str | None = None, text: str | None = None, country_iso3: str | None = None,
                 ai_interpretation: dict | None = None) -> CorrectionEvent:
    """Record (and apply) a person's correction, flag or note made on this computer. The event is
    queued for synchronisation (`sync_status = pending_sync`). Raises CorrectionError."""
    if kind not in ("value_correction", "flag_wrong", "note"):
        raise CorrectionError("invalid_kind", "Tipo di segnalazione non valido.", "Invalid kind.", allowed=list(KINDS[:1] + KINDS[2:]))
    reason = _clean_text(reason if kind != "note" else (text if text is not None else reason), "text" if kind == "note" else "reason")
    ai = ai_interpretation if isinstance(ai_interpretation, dict) else None
    if kind == "note":
        if not reason:
            raise CorrectionError("missing_text", "Scrivere il testo della nota.", "Write the text of the note.")
        cols: dict = {}
        if table or row_id is not None or series_key:
            model, current = resolve_target(session, table or "", row_id=row_id, source_key=source_key, series_key=series_key)
            cols = _target_columns(TABLE_OF[model], current)
            cols["source_key"] = session.get(Source, current.source_id).key
        iso3 = (country_iso3 or cols.get("country_iso3") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}|EU27|EU28", iso3):
            raise CorrectionError("missing_country", "Indicare il paese della nota.", "Say which country the note is about.")
        cols["country_iso3"] = iso3
        ev = _new_event(session, "note", reason=reason, ai_interpretation=ai, **cols)
        apply_event(session, ev)
        return ev

    model, current = resolve_target(session, table or "", row_id=row_id, source_key=source_key, series_key=series_key)
    tname = TABLE_OF[model]
    src = session.get(Source, current.source_id)
    if kind == "flag_wrong":
        cols = _target_columns(tname, current, field)
        ev = _new_event(session, "flag_wrong", source_key=src.key, reason=reason, ai_interpretation=ai, **cols)
        apply_event(session, ev)
        return ev

    official = official_of(session, model, current)
    norm = normalize(session, tname, official, value=value, low=low, high=high, unit=unit, currency=currency, field=field)
    if _same_values(model, {**value_fields(model, official), **norm["fields"]}, value_fields(model, official)):
        raise CorrectionError("same_as_official", "È lo stesso valore della fonte: non c'è niente da correggere.",
                              "That is the source's own value: there is nothing to correct.")
    if ingest.correction_of(current) is not None and _same_values(
            model, {**value_fields(model, official), **norm["fields"]}, value_fields(model, current)):
        raise CorrectionError("same_as_current", "Il dato ha già questo valore corretto.",
                              "The figure already has this corrected value.", status=409)
    cols = _target_columns(tname, official, norm["field"])
    cur = ingest.correction_of(current)
    ev = _new_event(session, "value_correction", after=parse_utc(cur.get("created_at")) if cur else None,
                    source_key=src.key, reason=reason, ai_interpretation=ai,
                    entered=norm["entered"], corrected_value=norm["main"],
                    normalized=_jsonable({k: norm["fields"][k] for k in ingest.VALUE_FIELDS[model]}), **cols)
    apply_event(session, ev)
    if ev.status != "applied":    # never expected for a figure just read here
        raise CorrectionError("not_applied", "La correzione non è stata applicata.", "The correction was not applied.",
                              status=409, status_detail=ev.status_detail)
    return ev


def create_revert(session: Session, event_id: str, reason: str | None = None) -> CorrectionEvent:
    """Undo an event (one click): a new event of kind `revert`, applied now."""
    target = get_event(session, event_id)
    if target is None:
        raise CorrectionError("not_found", "Correzione non trovata.", "Correction not found.", status=404)
    if target.kind == "revert":
        raise CorrectionError("not_revertible", "Un annullamento non si annulla: correggere di nuovo il dato.",
                              "An undo cannot be undone: correct the figure again.", status=409)
    ok = {"value_correction": ("applied",), "flag_wrong": ("recorded",), "note": ("recorded",)}[target.kind]
    if target.status not in ok:
        raise CorrectionError("not_revertible", "Non c'è niente da annullare: questa correzione non è in vigore.",
                              "There is nothing to undo: this correction is not in force.", status=409,
                              event_status=target.status)
    ev = _new_event(session, "revert", after=target.created_at, reverts_event_id=target.event_id,
                    reason=_clean_text(reason),
                    target_table=target.target_table, source_key=target.source_key, series_key=target.series_key,
                    period_label=target.period_label, target_unit=target.target_unit,
                    target_currency=target.target_currency, target_field=target.target_field,
                    country_iso3=target.country_iso3, label=target.label, official_hash=target.official_hash,
                    official_value=target.official_value)
    apply_event(session, ev)
    return ev


# ---------------------------------------------------------------------------
# Applying events (local and received)
# ---------------------------------------------------------------------------


def _set_status(ev: CorrectionEvent, status: str, detail: dict | None = None) -> str:
    ev.status = status
    ev.status_detail = detail
    return status


def apply_event(session: Session, ev: CorrectionEvent) -> str:
    """Apply one event to this computer's data; idempotent. Returns its status."""
    if ev.status in FINAL_STATUSES:
        return ev.status
    if ev.kind == "value_correction":
        status = _apply_value_correction(session, ev)
    elif ev.kind == "revert":
        status = _apply_revert(session, ev)
    elif ev.kind == "flag_wrong":
        status = _apply_flag(session, ev)
    else:
        status = _set_status(ev, "recorded")
    session.flush()
    return status


def _locate(session: Session, ev: CorrectionEvent):
    """(model, current row) of the event's figure here, or None (status set to waiting)."""
    model = TABLES.get(ev.target_table or "")
    src = _source_by_key(session, ev.source_key)
    if model is None or src is None or not ev.series_key:
        _set_status(ev, "waiting", {"reason": "source_missing" if model is not None else "table_unsupported"})
        return None
    current = ingest.current_row(session, model, src.id, ev.series_key)
    if current is None:
        _set_status(ev, "waiting", {"reason": "figure_missing"})
        return None
    return model, current


def _apply_value_correction(session: Session, ev: CorrectionEvent) -> str:
    found = _locate(session, ev)
    if found is None:
        return ev.status
    model, current = found
    table = TABLE_OF[model]
    cur = ingest.correction_of(current)
    other: CorrectionEvent | None = None
    if cur is not None:
        if cur.get("event_id") == ev.event_id:
            ev.applied_row_id = current.id
            return _set_status(ev, "applied")
        other = get_event(session, cur.get("event_id"))
        cur_at = parse_utc(cur.get("created_at"))
        if cur_at is not None and (cur_at, cur.get("event_id")) > (ev.created_at, ev.event_id):
            return _set_status(ev, "replaced", {"by_event_id": cur.get("event_id"), "by_author": cur.get("author")})
    official = official_of(session, model, current)
    if official.value_hash != ev.official_hash:
        field = ev.target_field
        now_val = getattr(official, main_field(table, field))
        detail = {"official_now": now_val, "official_before": ev.official_value, "official_row_id": official.id,
                  "unit": ev.target_unit, "currency": ev.target_currency}
        seen_before = session.scalars(select(model.id).where(
            model.series_key == ev.series_key, model.source_id == official.source_id,
            model.value_hash == ev.official_hash, model.reliability != "user")).first()
        if seen_before is not None:
            return _set_status(ev, "superseded_by_source", detail)
        if ev.status != "conflict":
            _conflict_notice(session, ev, now_val)
        return _set_status(ev, "conflict", detail)
    norm = {k: v for k, v in (ev.normalized or {}).items() if k in ingest.VALUE_FIELDS[model]}
    if set(norm) != set(ingest.VALUE_FIELDS[model]):
        return _set_status(ev, "conflict", {"reason": "invalid_event"})
    ev.normalized = norm
    row = _write_correction_row(session, model, ev, current, official)
    if other is not None and other.status == "applied":
        _set_status(other, "replaced", {"by_event_id": ev.event_id, "by_author": ev.author})
    ev.applied_row_id, ev.target_row_id = row.id, official.id
    return _set_status(ev, "applied")


def _conflict_notice(session: Session, ev: CorrectionEvent, now_val) -> None:
    unit, ccy = ev.target_unit, ev.target_currency
    label = ev.label or ev.series_key
    _notice(
        session, ev, "conflict", severity="warning",
        title_it=f"Correzione di {ev.author} non applicata: il dato ufficiale qui è diverso",
        title_en=f"Correction by {ev.author} not applied: the official figure here is different",
        body_it=(f"{label}: {ev.author} ha corretto {fmt_value(ev.official_value, unit, ccy)} in "
                 f"{fmt_value(ev.corrected_value, unit, ccy)} il {fmt_day(ev.created_at, 'it')}, ma su questo computer il "
                 f"valore ufficiale è {fmt_value(now_val, unit, ccy)}. La correzione non è stata applicata: "
                 f"verificare e, se serve, correggere di nuovo."),
        body_en=(f"{label}: {ev.author} corrected {fmt_value(ev.official_value, unit, ccy, 'en')} to "
                 f"{fmt_value(ev.corrected_value, unit, ccy, 'en')} on {fmt_day(ev.created_at, 'en')}, but on this "
                 f"computer the official value is {fmt_value(now_val, unit, ccy, 'en')}. The correction was not "
                 f"applied: check it and correct the figure again if needed."),
        link=None, ref_row_id=None)


def _apply_revert(session: Session, ev: CorrectionEvent) -> str:
    target = get_event(session, ev.reverts_event_id)
    if target is None:
        return _set_status(ev, "waiting", {"reason": "event_missing"})
    if target.status == "new":            # received together with its undo: apply it first (history kept)
        apply_event(session, target)
    before = target.status
    detail: dict = {"reverted_status": before}
    if target.kind == "value_correction" and before == "applied":
        found = _locate(session, ev)
        if found is None:
            return ev.status
        model, current = found
        cur = ingest.correction_of(current)
        if cur is not None and cur.get("event_id") == target.event_id:
            official = official_of(session, model, current)
            row = _write_revert_row(session, model, ev, target, current, official)
            ev.applied_row_id, ev.target_row_id = row.id, current.id
        else:
            detail["nothing_to_undo"] = True
    elif target.kind == "flag_wrong" and target.issue_id:
        issue = session.get(DataQualityIssue, target.issue_id)
        if issue is not None and issue.resolved_at is None:
            issue.resolved_at = utcnow()
            issue.details = {**(issue.details or {}), "reverted_by": ev.author, "revert_event_id": ev.event_id}
    elif target.kind != "note":
        detail["nothing_to_undo"] = True
    _set_status(target, "reverted", {**(target.status_detail or {}), "reverted_by_event_id": ev.event_id,
                                     "reverted_by": ev.author, "status_before": before})
    return _set_status(ev, "applied", detail)


def _apply_flag(session: Session, ev: CorrectionEvent) -> str:
    model = TABLES.get(ev.target_table or "")
    src = _source_by_key(session, ev.source_key)
    row = ingest.current_row(session, model, src.id, ev.series_key) if (model is not None and src is not None
                                                                         and ev.series_key) else None
    unit, ccy = ev.target_unit, ev.target_currency
    label = ev.label or ev.series_key or "—"
    value = ev.official_value
    why_it = f" Motivo: {ev.reason}" if ev.reason else ""
    why_en = f" Reason: {ev.reason}" if ev.reason else ""
    src_it, src_en = _source_name(session, ev.source_key, "it"), _source_name(session, ev.source_key, "en")
    dedup = f"correction:flag:{ev.event_id}"
    issue = session.scalars(select(DataQualityIssue).where(DataQualityIssue.dedup_key == dedup)).first()
    if issue is None:
        now = utcnow()
        issue = DataQualityIssue(
            dedup_key=dedup, issue_type="user_flag", severity="warning",
            entity_type=ev.target_table, entity_id=row.id if row is not None else None,
            source_id=src.id if src is not None else None,
            message_it=(f"{ev.author} segnala come dubbio: {label}, {fmt_value(value, unit, ccy)} ({src_it}), "
                        f"il {fmt_day(ev.created_at, 'it')}.{why_it}"),
            message_en=(f"{ev.author} marked as doubtful: {label}, {fmt_value(value, unit, ccy, 'en')} ({src_en}), "
                        f"on {fmt_day(ev.created_at, 'en')}.{why_en}"),
            details={"event_id": ev.event_id, "author": ev.author, "created_at": iso_utc(ev.created_at),
                     "reason": ev.reason, "source_key": ev.source_key, "series_key": ev.series_key,
                     "period_label": ev.period_label, "value": value, "unit": unit, "currency": ccy,
                     "link": figure_link(ev.target_table, row) if row is not None else None},
            detected_at=now, last_seen_at=now)
        session.add(issue)
        session.flush()
    ev.issue_id = issue.id
    ev.applied_row_id = row.id if row is not None else None
    return _set_status(ev, "recorded")


def strip_from_snapshot(conn) -> int:
    """Remove the rows written for corrections from a database COPY (sqlite3 connection), giving the
    official rows their place back: the starter data shipped with the program (services/starter.py)
    never carries a person's corrections. Returns the rows removed."""
    removed = 0
    for table in TABLES:
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        if not {"reliability", "supersedes_id", "is_current"} <= cols:
            continue
        users = {rid: (sup, cur) for rid, sup, cur in conn.execute(
            f'SELECT id, supersedes_id, is_current FROM "{table}" WHERE reliability = \'user\'')}
        for rid, (sup, cur) in users.items():
            anc = sup
            while anc in users:                       # a correction of a correction: up to the official row
                anc = users[anc][0]
            conn.execute(f'UPDATE "{table}" SET supersedes_id = ? WHERE supersedes_id = ?', (anc, rid))
            if cur and anc is not None:
                conn.execute(f'UPDATE "{table}" SET is_current = 1 WHERE id = ?', (anc,))
        removed += conn.execute(f'DELETE FROM "{table}" WHERE reliability = \'user\'').rowcount or 0
    return removed


# ---------------------------------------------------------------------------
# Exchange format (one JSON file per event)
# ---------------------------------------------------------------------------

_EXPORTED = ("event_id", "kind", "author", "device_id", "reverts_event_id", "reason", "ai_interpretation")
_TARGET = ("target_table", "source_key", "series_key", "period_label", "target_unit", "target_currency",
           "target_field", "country_iso3", "label", "official_hash", "official_before", "official_value")
_CORRECTION = ("entered", "corrected_value", "normalized")


def event_path(ev: CorrectionEvent) -> str:
    return f"events/{ev.created_at.year:04d}/{ev.event_id}.json"


def to_document(ev: CorrectionEvent) -> dict:
    """The event as exchanged between computers (no local state)."""
    doc = {"format": FORMAT, "version": FORMAT_VERSION, "created_at": iso_utc(ev.created_at)}
    doc.update({k: getattr(ev, k) for k in _EXPORTED})
    doc["target"] = {k: getattr(ev, k) for k in _TARGET}
    doc["correction"] = {k: getattr(ev, k) for k in _CORRECTION}
    return doc


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def _str(v, n: int) -> str | None:
    return v[:n] if isinstance(v, str) and v else None


def _num_or_none(v) -> float | None:
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _plain_dict(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    out = {}
    for k, x in v.items():
        if isinstance(k, str) and (x is None or isinstance(x, (str, int, float, bool))):
            out[k[:60]] = x[:300] if isinstance(x, str) else x
    return out


def from_document(doc: dict) -> CorrectionEvent | None:
    """A received event (validated; None when the document is not a valid event)."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("version"), int):
        return None
    eid, kind = doc.get("event_id"), doc.get("kind")
    created = parse_utc(doc.get("created_at"))
    if not (isinstance(eid, str) and _UUID.fullmatch(eid)) or kind not in KINDS or created is None:
        return None
    rev = doc.get("reverts_event_id")
    if kind == "revert" and not (isinstance(rev, str) and _UUID.fullmatch(rev)):
        return None
    t = doc.get("target") if isinstance(doc.get("target"), dict) else {}
    c = doc.get("correction") if isinstance(doc.get("correction"), dict) else {}
    table = t.get("target_table")
    if kind in ("value_correction", "flag_wrong") and table not in TABLES:
        return None
    if kind == "value_correction" and not (isinstance(c.get("normalized"), dict) and t.get("official_hash")):
        return None
    device = doc.get("device_id")
    ai = doc.get("ai_interpretation")
    return CorrectionEvent(
        event_id=eid, created_at=created, kind=kind, author=_str(doc.get("author"), 120) or DEFAULT_AUTHOR,
        device_id=_str(device, 64) or "unknown", reverts_event_id=rev if kind == "revert" else None,
        reason=_str(doc.get("reason"), MAX_TEXT), ai_interpretation=ai if isinstance(ai, dict) else None,
        target_table=table if table in TABLES else None, source_key=_str(t.get("source_key"), 60),
        series_key=_str(t.get("series_key"), 300), period_label=_str(t.get("period_label"), 40),
        target_unit=_str(t.get("target_unit"), 30), target_currency=_str(t.get("target_currency"), 3),
        target_field=_str(t.get("target_field"), 30), country_iso3=_str(t.get("country_iso3"), 10),
        label=_str(t.get("label"), 300), official_hash=_str(t.get("official_hash"), 64),
        official_before=_plain_dict(t.get("official_before")), official_value=_num_or_none(t.get("official_value")),
        entered=_plain_dict(c.get("entered")), corrected_value=_num_or_none(c.get("corrected_value")),
        normalized=_plain_dict(c.get("normalized")),
        origin="remote", status="new", sync_status="received", synced_at=utcnow(),
    )


def _apply_order(ev: CorrectionEvent) -> tuple:
    """Oldest first (the same microsecond time on every computer); on a tie, an undo after what it
    undoes, then the event id: the same order everywhere."""
    return (ev.created_at, ev.kind == "revert", ev.event_id)


def import_documents(session: Session, docs: list[dict]) -> dict:
    """Store and apply received events (oldest first), then retry received events still waiting or
    in conflict. Idempotent: an event id already here is skipped. Returns counts."""
    known = set(session.scalars(select(CorrectionEvent.event_id)))
    new: list[CorrectionEvent] = []
    invalid = 0
    for doc in docs:
        ev = from_document(doc)
        if ev is None:
            invalid += 1
            continue
        if ev.event_id in known:
            continue
        known.add(ev.event_id)
        new.append(ev)
    new.sort(key=_apply_order)
    for ev in new:
        session.add(ev)
    session.flush()
    retry = list(session.scalars(select(CorrectionEvent).where(
        CorrectionEvent.status.in_(sorted(RETRY_STATUSES | {"new"})))))
    retry.sort(key=_apply_order)
    statuses: dict[str, int] = {}
    for ev in retry:
        st = apply_event(session, ev)
        if ev in new:
            statuses[st] = statuses.get(st, 0) + 1
    return {"received": len(new), "invalid": invalid, "applied": statuses}


# ---------------------------------------------------------------------------
# Serialisation (API)
# ---------------------------------------------------------------------------


def serialize(ev: CorrectionEvent, *, this_device: str | None = None) -> dict:
    return {
        "event_id": ev.event_id,
        "kind": ev.kind,
        "created_at": iso_utc(ev.created_at),
        "author": ev.author,
        "made_here": this_device is not None and ev.device_id == this_device,
        "origin": ev.origin,
        "target": None if not ev.target_table and not ev.country_iso3 else {
            "table": ev.target_table, "source_key": ev.source_key, "series_key": ev.series_key,
            "period_label": ev.period_label, "unit": ev.target_unit, "currency": ev.target_currency,
            "field": ev.target_field, "country_iso3": ev.country_iso3, "label": ev.label,
            "row_id": ev.target_row_id,
        },
        "official_value": ev.official_value,
        "corrected_value": ev.corrected_value,
        "entered": ev.entered,
        "normalized": ev.normalized,
        "reverts_event_id": ev.reverts_event_id,
        "reason": ev.reason if ev.kind != "note" else None,
        "text": ev.reason if ev.kind == "note" else None,
        "ai_interpretation": ev.ai_interpretation,
        "status": ev.status,
        "status_detail": ev.status_detail,
        "applied_row_id": ev.applied_row_id,
        "issue_id": ev.issue_id,
        "revertible": (ev.kind == "value_correction" and ev.status == "applied")
                      or (ev.kind in ("flag_wrong", "note") and ev.status == "recorded"),
        "sync": {"state": ev.sync_status, "synced_at": iso_utc(ev.synced_at), "error": ev.sync_error},
    }
