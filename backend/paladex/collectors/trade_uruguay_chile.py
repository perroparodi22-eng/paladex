"""Official honey exports of Uruguay and Chile (government primary sources): two collectors.

* ``uy_honey_exports``: Uruguay, **Uruguay XXI – Sistema de Información Estadística (SIE)**, the
  government export agency's query tool built on Dirección Nacional de Aduanas (DNA) data and
  refreshed every 48 hours. Monthly exports of NCM 0409 (natural honey) by destination country,
  FOB value in USD, for the SIE's own five-year comparison window (2022-2026 in Nov 2026). One
  trade row per destination-month, plus the published total as partner ``WLD``.
  **The SIE publishes values only, no weights**: the rows carry no net weight and no export unit
  value is derived (a weight is never guessed).

* ``cl_honey_exports``: Chile, **Servicio Nacional de Aduanas – Base de datos Operaciones de
  Salida** (open data, Ley 20.285: aggregated DUS export declarations, no exporter fields). Monthly
  exports of SACH 0409.0010 (organic natural honey) and 0409.0090 (other natural honey) by
  destination country: FOB US$ (adjusted, ``FOBUS_AJUSTADO_IVV``), net kg (the declared quantity in
  KN, kilo neto, the statistical unit of heading 04.09) and gross kg. One trade row per
  destination-month (both lines summed, the split kept in ``extra``) and, when at least 1 t was
  shipped, a derived **export unit value** (FOB USD / net kg) with origin CHL and the destination as
  market. Backfill: the whole calendar years covering the last 36 months (2023-01..2026-09 in Nov
  2026); one yearly file per year (~20-27 MB, only the honey rows are archived), each re-read only
  when its URL or HTTP validators change.

Routes rejected (checked live on 2026-11-05 from the development sandbox; see the README of the
fixtures and docs/DATA_SOURCES.md):

* Uruguay DNA open data (``ftp://ftp.aduanas.gub.uy/DUA Diarios XML/``): declaration-level DUA XML,
  with weights, but FTP only. The host has no HTTP(S) service and FTP is not reachable from here;
  the collector framework (httpx) does not speak FTP either. It is the upgrade path for weights.
* Uruguay BCU / INE: INE yearbook table 7.1.14 (source BCU) gives monthly totals with net kg but no
  destinations, once a year; BCU's own site serves an incomplete TLS certificate chain.
* Uruguay XXI monthly PDF reports: no honey line.
* Chile ODEPA (republishes Aduana's figures): incomplete TLS certificate chain; it duplicates Aduana.
* Chile Aduana statistics workbooks ("Exportación por país y código arancelario", monthly xlsx):
  FOB and **gross** kg only ("Peso en Kilos Brutos"). Used only as a fallback for a year whose DUS
  base file is a RAR archive (2025 in Nov 2026), which Python cannot open without an external tool:
  those rows carry the official FOB value, gross weight in ``extra`` and **no net weight**, so no
  unit value. Checked on the real 2026 files: the DUS base reproduces these workbooks exactly
  (FOB and gross kg by destination, month and line).

Privacy. The SIE pages embed the full autocomplete list of exporting companies and persons. This
collector never queries by company, never archives a whole SIE page: only the result caption and
table (destination or month totals) are archived. The company view ("Por Empresa", names and FOB
values only) is read by ``companies_official.uy_sie_honey_exporters``. The Chilean base has no
exporter fields.

Revisions. Every changed figure is a new revision (``services.ingest``); a destination-month the
source no longer reports is withdrawn (kept in the history, never deleted). A change of status
(provisional to published) is a revision too.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import html as html_lib
import io
import json
import logging
import re
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, TradeFlow, Variety
from ..models import AppSetting, PriceObservation, TradeFlowObservation, utcnow
from ..reference.countries import COMTRADE_CODE_OVERRIDES, lookup_iso3
from .base import CollectContext, Collector, CollectorError, month_bounds
from .trade_official import (
    MIN_UNIT_VALUE_WEIGHT_KG,
    month_label,
    resolve_country_name,
    shift_month,
)

log = logging.getLogger(__name__)

Month = tuple[int, int]


def today() -> date:
    """Reference date (indirection so tests can pin it)."""
    return date.today()


# ===========================================================================
# Shared helpers
# ===========================================================================


def _midx(ym: Month) -> int:
    return ym[0] * 12 + ym[1] - 1


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _state_key(source_key: str) -> str:
    return f"collector_state:{source_key}"


def _load_state(ctx: CollectContext) -> dict:
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    return copy.deepcopy(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_state(ctx: CollectContext, state: dict) -> None:
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    if row is None:
        ctx.session.add(AppSetting(key=_state_key(ctx.source.key), value=copy.deepcopy(state)))
    else:
        row.value = copy.deepcopy(state)          # a new object, so SQLAlchemy sees the JSON change
    ctx.session.flush()


def _warn_once(ctx: CollectContext, state: dict, token: str, message: str) -> None:
    """`ctx.warn` the first time `token` is met (remembered in the state), then only log: a
    condition that cannot change by itself must not mark every run partial."""
    warned = state.setdefault("warned", [])
    if token in warned:
        log.info("[%s] %s", ctx.source.key, message)
        return
    warned.append(token)
    ctx.warn(message)


def _has_rows(ctx: CollectContext) -> bool:
    T = TradeFlowObservation
    return ctx.session.scalar(select(T.id).where(T.source_id == ctx.source.id).limit(1)) is not None


def _retire_absent(ctx: CollectContext, *, prefix: str, months: Iterable[str], present: set[str],
                   protected_partners: set[str] = frozenset(),
                   price_key: Callable[[str, str], str] | None = None) -> list[str]:
    """Withdraw the current trade rows (and their unit values) of `months` that a fresh answer no
    longer contains; rows of `protected_partners` (not read this time) are left alone. They stay in
    the history: only `is_current` is cleared (ingest.retire)."""
    months = sorted(set(months))
    if not months:
        return []
    T = TradeFlowObservation
    rows = ctx.session.execute(select(T.series_key, T.partner_iso3, T.period_label).where(
        T.source_id == ctx.source.id, T.is_current.is_(True), T.is_demo.is_(False),
        T.period_label.in_(months), T.series_key.startswith(prefix),
    )).all()
    gone = []
    for key, partner, label in rows:
        if key in present or partner in protected_partners:
            continue
        ctx.retire(T, key)
        if price_key is not None:
            ctx.retire(PriceObservation, price_key(partner, label))
        gone.append(f"{partner} {label}")
    return sorted(gone)


def _http_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, IndexError):
        return None


# Spanish country names as Uruguay XXI and Chile's Aduana publish them (the shared resolver knows
# EN/IT/PT names). Matched on the WHOLE name only: "Islas Virgenes (Estados Unidos de América)" must
# never become the United States.
_ES_NAMES_RAW: dict[str, str] = {
    "Estados Unidos de América": "USA", "Estados Unidos": "USA", "Alemania": "DEU", "España": "ESP",
    "Francia": "FRA", "Italia": "ITA", "Países Bajos": "NLD", "Holanda": "NLD", "Bélgica": "BEL",
    "Reino Unido": "GBR", "Irlanda": "IRL", "Portugal": "PRT", "Suiza": "CHE", "Austria": "AUT",
    "República Checa": "CZE", "Chequia": "CZE", "República Eslovaca": "SVK", "Eslovaquia": "SVK",
    "Polonia": "POL", "Dinamarca": "DNK", "Suecia": "SWE", "Noruega": "NOR", "Finlandia": "FIN",
    "Islandia": "ISL", "Grecia": "GRC", "Hungría": "HUN", "Rumania": "ROU", "Rumanía": "ROU",
    "Bulgaria": "BGR", "Croacia": "HRV", "Eslovenia": "SVN", "Estonia": "EST", "Letonia": "LVA",
    "Lituania": "LTU", "Luxemburgo": "LUX", "Malta": "MLT", "Chipre": "CYP", "Ucrania": "UKR",
    "Rusia": "RUS", "Federación de Rusia": "RUS", "Belarus": "BLR", "Bielorrusia": "BLR",
    "Turquía": "TUR", "República de Serbia": "SRB", "Serbia": "SRB", "Montenegro": "MNE",
    "Bosnia y Herzegovina": "BIH", "Albania": "ALB", "Macedonia del Norte": "MKD", "Moldova": "MDA",
    "Moldavia": "MDA", "Georgia": "GEO", "Armenia": "ARM", "Azerbaiyán": "AZE", "Kazajstán": "KAZ",
    "Kasajstán": "KAZ", "Uzbekistán": "UZB", "Canadá": "CAN", "México": "MEX", "Brasil": "BRA",
    "Argentina": "ARG", "Uruguay": "URY", "Paraguay": "PRY", "Bolivia": "BOL", "Perú": "PER",
    "Colombia": "COL", "Ecuador": "ECU", "Venezuela": "VEN", "Chile": "CHL", "Panamá": "PAN",
    "Costa Rica": "CRI", "Guatemala": "GTM", "Honduras": "HND", "El Salvador": "SLV",
    "Nicaragua": "NIC", "República Dominicana": "DOM", "Cuba": "CUB", "Jamaica": "JAM",
    "Trinidad y Tobago": "TTO", "China": "CHN", "Hong Kong": "HKG",
    "Hong Kong (Región administrativa especial de China)": "HKG", "Macao": "MAC", "Taiwán": "TWN",
    "Taiwán (Formosa)": "TWN", "Japón": "JPN", "Corea del Sur": "KOR", "República de Corea": "KOR",
    "Corea, República de": "KOR", "Singapur": "SGP", "Malasia": "MYS", "Tailandia": "THA",
    "Thailandia": "THA", "Vietnam": "VNM", "Viet Nam": "VNM", "Indonesia": "IDN", "Filipinas": "PHL",
    "India": "IND", "Pakistán": "PAK", "Bangladesh": "BGD", "Sri Lanka": "LKA",
    "Arabia Saudita": "SAU", "Emiratos Árabes Unidos": "ARE", "Kuwait": "KWT", "Qatar": "QAT",
    "Catar": "QAT", "Omán": "OMN", "Bahrein": "BHR", "Baréin": "BHR", "Israel": "ISR",
    "Jordania": "JOR", "Líbano": "LBN", "Irán": "IRN", "Iraq": "IRQ", "Irak": "IRQ", "Siria": "SYR",
    "Egipto": "EGY", "Marruecos": "MAR", "Argelia": "DZA", "Túnez": "TUN", "Sudáfrica": "ZAF",
    "Nigeria": "NGA", "Kenia": "KEN", "Ghana": "GHA", "Australia": "AUS", "Nueva Zelanda": "NZL",
    "Nueva Zelandia": "NZL", "Mongolia": "MNG",
}
_ES_NAMES: dict[str, str] = {_norm(k): v for k, v in _ES_NAMES_RAW.items()}


def resolve_es_country(name: Any) -> str | None:
    """ISO3 of a country name as the Spanish-language sources publish it, else None."""
    if not isinstance(name, str) or not name.strip():
        return None
    iso = _ES_NAMES.get(_norm(name))
    return iso or resolve_country_name(name)


def _iso_from_numeric(code: Any) -> str | None:
    """ISO3 of an ISO 3166-1 numeric code ("840", 276...). Comtrade's own non-ISO codes and 0
    (lookup_iso3 reads 0 as World) are not ISO country codes: None."""
    s = str(code or "").strip()
    if not s.isdigit():
        return None
    n = int(s)
    if n == 0 or n in COMTRADE_CODE_OVERRIDES:
        return None
    iso = lookup_iso3(n)
    return iso if iso and iso != "WLD" else None


# ===========================================================================
# 1) Uruguay: Uruguay XXI, Sistema de Información Estadística (SIE)
# ===========================================================================

SIE_BASE = "https://herramientas.uruguayxxi.gub.uy/sistema_de_estadistica/"
SIE_QUERY_URL = f"{SIE_BASE}filtros.php"
SIE_NCM = "0409"
# Bumped when the parsing changes, so answers already seen are read again once.
SIE_PARSER_VERSION = 1
SIE_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
              "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
SIE_MONTH_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9,
                  "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12}
SIE_TOTAL_LABEL = "total detalle"
# Two USD amounts published with 2 decimals agree when they differ by at most this (rounding).
SIE_TOLERANCE_USD = 1.0
SIE_RUNNING_YEAR_NOTE = ("Uruguay XXI shows the running year as a year-to-date column ('{label}'); its months "
                         "are provisional until the year is closed")

_SIE_NUMBER_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?")
_SIE_YEAR_RE = re.compile(r"(\d{4})\s*(?:\(\s*([A-Za-zÁÉÍÓÚáéíóú]+)\.?\s*-\s*([A-Za-zÁÉÍÓÚáéíóú]+)\.?\s*\))?")
_SIE_H3_RE = re.compile(r"<h3[^>]*>\s*Sistema de Informaci[oó]n Estad[ií]stica\s*</h3>", re.IGNORECASE)


@dataclass(frozen=True)
class SieYearColumn:
    year: int
    first_month: int
    last_month: int
    annotated: bool                 # the header states the months covered: "2026 (ene - oct)"
    label: str


@dataclass
class SieTable:
    caption: str
    flow_text: str                  # "Exportaciones"
    ncm: str | None
    country: str | None             # "pais: <name>" in the caption
    first_year: int
    last_year: int
    columns: list[SieYearColumn]
    rows: list[tuple[str, list[float | None]]]
    total: list[float | None]
    fragment: bytes                 # caption + table, verbatim: what is archived
    problems: list[str] = field(default_factory=list)


def parse_sie_number(cell: Any) -> float | None:
    """'1.662.275,70' -> 1662275.7, '0' -> 0.0; anything else -> None (never guessed)."""
    s = str(cell or "").strip()
    if not s or not _SIE_NUMBER_RE.fullmatch(s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def _cell_text(fragment: str) -> str:
    return html_lib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_sie_year_column(text: str) -> SieYearColumn | None:
    m = _SIE_YEAR_RE.fullmatch(text.strip())
    if not m:
        return None
    year = int(m.group(1))
    if m.group(2):
        first, last = SIE_MONTH_ABBR.get(_norm(m.group(2))), SIE_MONTH_ABBR.get(_norm(m.group(3)))
        if first is None or last is None or first > last:
            return None
        return SieYearColumn(year, first, last, True, text.strip())
    return SieYearColumn(year, 1, 12, False, text.strip())


def parse_sie_table(content: bytes, what: str) -> SieTable:
    """Parse one SIE result page (or the archived extract of one): the caption and the table.

    Fails loudly (CollectorError) when the result block, the caption or the table cannot be found,
    when the caption is not an export query filtered on NCM 0409, when the year columns do not match
    the caption's period, or when a row has the wrong number of cells."""
    text = content.decode("utf-8", errors="replace")
    h3 = _SIE_H3_RE.search(text)
    if h3 is None:
        raise CollectorError(f"Uruguay XXI SIE {what}: no result block ('Sistema de Información Estadística') "
                             "in the answer (page layout changed or maintenance page?)")
    cap = re.search(r"<h5[^>]*>(.*?)</h5>", text[h3.end():], re.DOTALL | re.IGNORECASE)
    tstart = text.find("<table", h3.end())
    tend = text.find("</table>", tstart)
    if cap is None or tstart < 0 or tend < 0:
        raise CollectorError(f"Uruguay XXI SIE {what}: caption or result table missing (format changed?)")
    caption = _cell_text(cap.group(1))
    fragment = text[h3.start():tend + len("</table>")].encode("utf-8")
    m_flow = re.match(r"(Exportaciones|Importaciones)\b", caption)
    m_ncm = re.search(r"NCM:\s*'([^']*)'", caption)
    m_country = re.search(r"pa[ií]s:\s*(.+?),\s*Per[ií]odo", caption, re.IGNORECASE)
    m_period = re.search(r"Per[ií]odo:\s*(\d{4})\s*-\s*(\d{4})", caption, re.IGNORECASE)
    if not m_flow or m_flow.group(1) != "Exportaciones":
        raise CollectorError(f"Uruguay XXI SIE {what}: the caption {caption!r} is not an export query; nothing stored")
    if not m_ncm or re.sub(r"\D", "", m_ncm.group(1)) != SIE_NCM:
        raise CollectorError(f"Uruguay XXI SIE {what}: the caption {caption!r} is not filtered on NCM {SIE_NCM} "
                             "(the filter was ignored?); nothing stored")
    if not m_period:
        raise CollectorError(f"Uruguay XXI SIE {what}: no period in the caption {caption!r} (format changed?)")
    y0, y1 = int(m_period.group(1)), int(m_period.group(2))
    table = text[tstart:tend]
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL | re.IGNORECASE)
    if not rows_html:
        raise CollectorError(f"Uruguay XXI SIE {what}: the result table has no rows (format changed?)")
    header = [_cell_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", rows_html[0], re.DOTALL | re.IGNORECASE)]
    columns: list[SieYearColumn] = []
    for h in header[1:]:
        col = parse_sie_year_column(h)
        if col is None:
            raise CollectorError(f"Uruguay XXI SIE {what}: unreadable year column {h!r} (format changed?)")
        columns.append(col)
    if [c.year for c in columns] != list(range(y0, y1 + 1)):
        raise CollectorError(f"Uruguay XXI SIE {what}: year columns {[c.label for c in columns]} do not match the "
                             f"period {y0}-{y1} of the caption (format changed?)")
    out = SieTable(caption=caption, flow_text=m_flow.group(1), ncm=m_ncm.group(1),
                   country=m_country.group(1).strip() if m_country else None, first_year=y0, last_year=y1,
                   columns=columns, rows=[], total=[], fragment=fragment)
    total = None
    for r in rows_html[1:]:
        cells = [_cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL | re.IGNORECASE)]
        if not cells:
            continue
        if len(cells) != len(columns) + 1:
            raise CollectorError(f"Uruguay XXI SIE {what}: row {cells[:2]} has {len(cells) - 1} values for "
                                 f"{len(columns)} years (format changed?)")
        values = [parse_sie_number(c) for c in cells[1:]]
        for k, (col, raw, v) in enumerate(zip(columns, cells[1:], values)):
            if v is None:
                out.problems.append(f"Uruguay XXI SIE {what}: unreadable value {raw!r} for {cells[0]!r} {col.year}; skipped")
            elif v < 0:                     # exports are never negative: not read as a flow
                out.problems.append(f"Uruguay XXI SIE {what}: negative value {raw!r} for {cells[0]!r} {col.year}; skipped")
                values[k] = None
        if _norm(cells[0]) == SIE_TOTAL_LABEL:
            total = values
        else:
            out.rows.append((cells[0], values))
    if total is None:
        raise CollectorError(f"Uruguay XXI SIE {what}: no 'Total Detalle' row (format changed?)")
    out.total = total
    # The published total must be the sum of the rows (2-decimal amounts): else the table is not
    # what we think it is, and none of its columns is trusted.
    for i, col in enumerate(columns):
        vals = [v[i] for _, v in out.rows]
        if total[i] is None or any(v is None for v in vals):
            continue
        if abs(sum(vals) - total[i]) > SIE_TOLERANCE_USD:
            out.problems.append(f"Uruguay XXI SIE {what}: the rows of {col.year} add up to {sum(vals):.2f}, the "
                                f"published total is {total[i]:.2f}; that year is not stored from this table")
            total[i] = None
    return out


def parse_sie_options(content: bytes, select_id: str) -> dict[str, str]:
    """{value: label} of a <select id=...> of the SIE page ("pais": ISO numeric code -> Spanish name)."""
    text = content.decode("utf-8", errors="replace")
    m = re.search(rf'<select[^>]*\bid="{re.escape(select_id)}"[^>]*>(.*?)</select>', text, re.DOTALL | re.IGNORECASE)
    if m is None:
        return {}
    out: dict[str, str] = {}
    for value, label in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.DOTALL | re.IGNORECASE):
        value, label = value.strip(), _cell_text(label)
        if value and label:
            out[value] = label
    return out


def sie_extract(content: bytes, *, with_countries: bool = False) -> bytes:
    """What is archived of an SIE page: the result caption and table, verbatim, and (for the
    destination list) the country selector. Never the rest: the page also embeds the autocomplete
    list of every exporting company and person."""
    text = content.decode("utf-8", errors="replace")
    parts: list[str] = []
    if with_countries:
        m = re.search(r'<select[^>]*\bid="pais"[^>]*>.*?</select>', text, re.DOTALL | re.IGNORECASE)
        if m:
            parts.append(m.group(0))
    h3 = _SIE_H3_RE.search(text)
    if h3:
        tend = text.find("</table>", h3.end())
        if tend > 0:
            parts.append(text[h3.start():tend + len("</table>")])
    return "\n".join(parts).encode("utf-8")


@dataclass
class SieMonthly:
    values: dict[Month, float]          # storable months -> USD
    provisional: set[Month]
    skipped_years: set[int]             # columns not trusted (total mismatch)
    unsure: set[Month]                  # months in coverage that could not be read
    coverage_end: Month | None
    coverage_label: str | None


def sie_monthly(table: SieTable, what: str, ref: date) -> SieMonthly:
    """The storable months of a t=mes table: inside the period the SIE declares (a running year
    column says "2026 (ene - oct)"), never the current calendar month or a later one.

    The SIE leaves out a month row that is zero in all five years (seen live: a destination table
    with 9 month rows). Such a month is read as 0 only because the year totals, which
    `parse_sie_table` checks against the sum of the rows shown, confirm it; a year whose total does
    not match is not stored at all. Fails loudly on a row that is not a month (or a month twice), or
    when the newest column is the running year but does not state the months it covers."""
    months: dict[int, list[float | None]] = {}
    for label, values in table.rows:
        m = SIE_MONTHS.get(_norm(label))
        if m is None or m in months:
            raise CollectorError(f"Uruguay XXI SIE {what}: unexpected row {label!r} in a monthly table (format changed?)")
        months[m] = values
    zeros: list[float | None] = [0.0] * len(table.columns)
    out = SieMonthly(values={}, provisional=set(), skipped_years=set(), unsure=set(), coverage_end=None,
                     coverage_label=None)
    current = (ref.year, ref.month)
    for i, col in enumerate(table.columns):
        if not col.annotated and col.year >= ref.year:
            raise CollectorError(f"Uruguay XXI SIE {what}: the running year column {col.label!r} does not state the "
                                 "months it covers (expected e.g. '2026 (ene - oct)'); nothing stored")
        if table.total[i] is None:
            out.skipped_years.add(col.year)
        for m in range(col.first_month, col.last_month + 1):
            ym = (col.year, m)
            if _midx(ym) >= _midx(current):
                continue                    # not over yet: a partial month is never stored
            value = months.get(m, zeros)[i]
            if col.year in out.skipped_years or value is None:
                out.unsure.add(ym)
                continue
            out.values[ym] = value
            if col.annotated:
                out.provisional.add(ym)
            if out.coverage_end is None or _midx(ym) > _midx(out.coverage_end):
                out.coverage_end = ym
                out.coverage_label = col.label
    return out


def classify_sie_destination(code: str | None, name: str) -> tuple[str | None, str]:
    """(ISO3 or None, how). The SIE identifies destinations by ISO 3166-1 numeric code; the
    published Spanish name must agree when it can be read. how: "code+name", "code", "conflict"
    or "unknown" (not a country: free zones, special customs areas, unknown codes)."""
    by_code = _iso_from_numeric(code)
    by_name = resolve_es_country(name)
    if by_code and by_name and by_code != by_name:
        return None, "conflict"
    if by_code == "URY":
        return None, "unknown"              # the reporter itself is never its own export market
    if by_code:
        return by_code, "code+name" if by_name else "code"
    return None, "unknown"


class UyHoneyExportsCollector(Collector):
    key = "uy_honey_exports"
    name = "Uruguay – Uruguay XXI (SIE, dati Dirección Nacional de Aduanas): esportazioni di miele (NCM 0409)"
    publisher = "Uruguay XXI – Instituto de Promoción de Inversiones, Exportaciones e Imagen País (data: DNA, MEF)"
    homepage = SIE_BASE
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "URY"
    language = "es"
    expected_update = "Controllo settimanale: il SIE si aggiorna ogni 48 ore; i mesi dell'anno in corso restano provvisori"
    expected_update_en = "Checked weekly: the SIE is updated every 48 hours; months of the running year stay provisional"
    expected_max_age_days = 40
    terms_note = ("Fuente: Uruguay XXI – Sistema de Información Estadística (SIE), built on Dirección Nacional de "
                  "Aduanas data and updated every 48 hours. Public web tool, no reuse terms published; this collector "
                  "reads the honey (NCM 0409) totals by destination and month (the company view is a separate "
                  "source, uy_sie_honey_exporters) and archives "
                  "only the result tables. Values in US$ FOB. The SIE publishes no weights: no net weight and no unit "
                  "value are stored. Months of the running year (shown 'YYYY (ene - mmm)') are provisional; the "
                  "current month is never stored. Destinations that are not countries (free zones, special customs "
                  "areas) are not stored as partners; the published total (World) includes them.")
    # Weekly, at night in Montevideo (07:15 in Rome = 03:15 in Uruguay). Each check is one request
    # (~1.8 MB page); the destinations (~20 requests) are re-read only when a stored month changed.
    schedule = {"trigger": "cron", "day_of_week": "wed", "hour": 7, "minute": 15}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        ref = today()
        total_doc, total, year = self._query_total(ctx, ref.year)
        monthly = sie_monthly(total, "monthly total", ref)
        for p in total.problems:
            ctx.warn(p)
        if not monthly.values:
            ctx.warn(f"Uruguay XXI SIE returned no honey export month to store for {total.first_year}-{total.last_year}")
            return
        signature = self._signature(monthly)
        if (not ctx.force and _has_rows(ctx) and state.get("backfill_done") and state.get("signature") == signature
                and state.get("parser_version") == SIE_PARSER_VERSION):
            log.info("[%s] SIE honey totals unchanged (%s); destinations not re-read", self.key, monthly.coverage_label)
            return
        raw_total, _ = ctx.store_raw(total_doc.url, sie_extract(total_doc.content),
                                     "text/html", title=f"Uruguay XXI SIE honey exports (NCM 0409) by month, {total.caption}")
        common_query = {"t": "mes", "a": year, "ncm": SIE_NCM}
        present: set[str] = set()
        for ym, value in sorted(monthly.values.items()):
            present.add(self._store(ctx, "WLD", ym, value, monthly, raw_total, total_doc.url,
                                    {"destination_name": "Total", "query": {**common_query, "pa": ""},
                                     "sie_caption": total.caption}))
        ctx.checkpoint()

        # Destinations: the annual table gives the list (and a cross-check per year).
        pais_doc = self._fetch(ctx, "pais", year)
        by_dest = parse_sie_table(pais_doc.content, "destinations")
        for p in by_dest.problems:
            ctx.warn(p)
        options = parse_sie_options(pais_doc.content, "pais")
        if not options:
            raise CollectorError("Uruguay XXI SIE: the country selector (select#pais) is missing from the page; the "
                                 "destinations cannot be queried (format changed?)")
        ctx.store_raw(pais_doc.url, sie_extract(pais_doc.content, with_countries=True), "text/html",
                      title=f"Uruguay XXI SIE honey exports (NCM 0409) by destination, {by_dest.caption}")
        by_name = {_norm(label): code for code, label in options.items()}
        unsure: set[Month] = set(monthly.unsure)
        protected: set[str] = set()
        destinations: dict[str, str] = {}
        for name, annual in by_dest.rows:
            if not any(v for v in annual):
                continue
            code = by_name.get(_norm(name))
            iso, how = classify_sie_destination(code, name)
            if iso is None:
                self._report_unmapped(ctx, state, name, code, how)
                continue
            if iso in destinations:
                ctx.warn(f"Uruguay XXI SIE: destinations {destinations[iso]!r} and {name!r} both map to {iso}; "
                         f"{name!r} skipped")
                continue
            destinations[iso] = name
            ok = self._pull_destination(ctx, state, year, iso, how, name, code, annual, by_dest, monthly, present, ref)
            if not ok:
                protected.add(iso)
            ctx.checkpoint()

        months = [month_label(ym) for ym in monthly.values if ym not in unsure]
        gone = _retire_absent(ctx, prefix="uyxxi|URY|", months=months, present=present, protected_partners=protected)
        if gone:
            ctx.warn(f"Uruguay XXI SIE no longer reports honey exports for {', '.join(gone[:20])}"
                     f"{' ...' if len(gone) > 20 else ''}: those rows are withdrawn (kept in the history)")
        state.update({
            "signature": signature, "coverage": monthly.coverage_label,
            "latest_month": month_label(monthly.coverage_end) if monthly.coverage_end else None,
            "year_queried": year, "backfill_done": True, "parser_version": SIE_PARSER_VERSION,
            "pulled_at": utcnow().isoformat(timespec="seconds"), "destinations": sorted(destinations),
        })
        _save_state(ctx, state)
        ctx.checkpoint()

    # ------------------------------------------------------------------ queries
    @staticmethod
    def _params(mode: str, year: int, pais: str = "") -> dict:
        # The SIE's own order (script.js `buscar`): t, pr, e, a, pa, cat, ncm. `e` (company) stays empty.
        return {"t": mode, "pr": "", "e": "", "a": str(year), "pa": pais, "cat": "Todos", "ncm": SIE_NCM}

    def _fetch(self, ctx: CollectContext, mode: str, year: int, pais: str = ""):
        # store=False: a whole page holds the autocomplete list of companies and persons; only the
        # result extract is archived (sie_extract).
        return ctx.fetch(SIE_QUERY_URL, params=self._params(mode, year, pais), headers={"Accept": "text/html"},
                         store=False)

    def _query_total(self, ctx: CollectContext, year: int):
        doc = self._fetch(ctx, "mes", year)
        years = [int(v) for v in parse_sie_options(doc.content, "anio") if v.isdigit()]
        if years and year not in years:
            # The new year is not offered yet (early January): ask for the newest year it offers.
            year = max(years)
            doc = self._fetch(ctx, "mes", year)
        table = parse_sie_table(doc.content, "monthly total")
        if table.country:
            raise CollectorError(f"Uruguay XXI SIE: the total query came back for one country ({table.country!r}); "
                                 "nothing stored")
        if table.last_year != year:
            raise CollectorError(f"Uruguay XXI SIE: asked for the window ending {year}, got {table.first_year}-"
                                 f"{table.last_year}; nothing stored")
        return doc, table, year

    @staticmethod
    def _signature(monthly: SieMonthly) -> str:
        payload = {month_label(k): round(v, 2) for k, v in sorted(monthly.values.items())}
        payload["_coverage"] = monthly.coverage_label
        payload["_provisional"] = sorted(month_label(k) for k in monthly.provisional)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _report_unmapped(self, ctx: CollectContext, state: dict, name: str, code: str | None, how: str) -> None:
        state.setdefault("unknown_partners", {})[name] = code
        if how == "conflict":
            msg = (f"Uruguay XXI SIE destination {name!r} has ISO numeric code {code} for "
                   f"{_iso_from_numeric(code)}, but its name reads as {resolve_es_country(name)}; skipped until checked")
        elif code is None:
            msg = (f"Uruguay XXI SIE destination {name!r} is not in the page's country selector, so it cannot be "
                   "queried; its rows are skipped (the World total includes them)")
        else:
            msg = (f"Uruguay XXI SIE destination {name!r} (code {code}) is not a country Paladex can map (free zone, "
                   "special customs area or unknown code); its rows are skipped (the World total includes them)")
        _warn_once(ctx, state, f"partner:{name}:{code}", msg)

    def _pull_destination(self, ctx: CollectContext, state: dict, year: int, iso: str, how: str, name: str,
                          code: str | None, annual: list[float | None], by_dest: SieTable, total: SieMonthly,
                          present: set[str], ref: date) -> bool:
        """Read and store one destination. False when it could not be read completely (its rows the
        answer did not confirm are then left as they are: never withdrawn on a partial reading)."""
        doc = self._fetch(ctx, "mes", year, code or "")
        table = parse_sie_table(doc.content, f"destination {name}")
        if table.country is None or _norm(table.country) != _norm(name):
            raise CollectorError(f"Uruguay XXI SIE: asked for destination {name!r} (code {code}), the answer is for "
                                 f"{table.country or 'all destinations'}; nothing more stored")
        for p in table.problems:
            ctx.warn(p)
        monthly = sie_monthly(table, f"destination {name}", ref)
        # Cross-check: the year totals of this table and of the destination list must agree.
        for i, col in enumerate(table.columns):
            j = next((k for k, c in enumerate(by_dest.columns) if c.year == col.year), None)
            a = annual[j] if j is not None else None
            t = table.total[i]
            if a is not None and t is not None and abs(a - t) > SIE_TOLERANCE_USD:
                ctx.warn(f"Uruguay XXI SIE: {name} {col.year} totals {t:.2f} (by month) and {a:.2f} (by destination) "
                         "differ (data updated meanwhile?); this destination is not updated this run")
                return False
        raw_id, _ = ctx.store_raw(doc.url, sie_extract(doc.content), "text/html",
                                  title=f"Uruguay XXI SIE honey exports (NCM 0409) to {name}, {table.caption}")
        for ym, value in sorted(monthly.values.items()):
            if ym not in total.values:
                continue                    # outside the months stored for the total (coverage)
            if value <= 0:
                continue                    # no shipment that month: no flow row
            present.add(self._store(ctx, iso, ym, value, monthly, raw_id, doc.url, {
                "destination_name": name, "sie_country_code": code, "mapped_by": how,
                "query": {"t": "mes", "a": year, "pa": code, "ncm": SIE_NCM}, "sie_caption": table.caption}))
        return not (monthly.unsure & set(total.values))

    def _store(self, ctx: CollectContext, iso: str, ym: Month, value: float, monthly: SieMonthly, raw_id: int,
               url: str, extra: dict) -> str:
        p_start, p_end = month_bounds(*ym)
        label = month_label(ym)
        provisional = ym in monthly.provisional
        status = DataStatus.PROVISIONAL if provisional else DataStatus.PUBLISHED
        extra = {"ncm": SIE_NCM, **extra, "weight_published": False,
                 "status_reason": SIE_RUNNING_YEAR_NOTE.format(label=monthly.coverage_label) if provisional else None,
                 "web_ui": SIE_BASE}
        series = f"uyxxi|URY|{iso}|export|0409|{label}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="URY", partner_iso3=iso, flow=TradeFlow.EXPORT.value,
            currency="USD", value=round(value, 2), net_weight_kg=None, value_basis="FOB",
            period_start=p_start, period_end=p_end, period_label=label, frequency="M", published_at=None,
            source_url=url, raw_document_id=raw_id or None, data_status=status, reliability=Reliability.OFFICIAL,
            notes=("Esportazioni uruguaiane di miele naturale NCM 0409 (Uruguay XXI, Sistema de Información "
                   "Estadística, dati della Dirección Nacional de Aduanas): valore FOB in USD. Il SIE non pubblica "
                   "il peso: nessun valore unitario."
                   + (" Totale pubblicato (tutte le destinazioni)." if iso == "WLD" else "")),
            extra=extra,
        )
        return series


# ===========================================================================
# 2) Chile: Servicio Nacional de Aduanas, export statistics and open data
# ===========================================================================

CL_SITE = "https://www.aduana.cl"
CL_DUS_PAGE_URL = f"{CL_SITE}/base-de-datos-operaciones-de-salida/aduana/2024-11-12/153724.html"
CL_STATS_PAGE_URL = f"{CL_SITE}/exportacion-por-pais-y-codigo-arancelario/aduana/2018-12-14/101258.html"
CL_HONEY_PREFIX = "0409"
# Arancel Aduanero Nacional 2022 (aduana.cl, Sección I, capítulo 4): 04.09 Miel natural,
# 0409.0010 "- Orgánica", 0409.0090 "- Las demás"; statistical unit KN-06 (kilo neto).
CL_SACH_LINES = {"04090010": "Orgánica (organic)", "04090090": "Las demás (other)"}
# "Si Ud. requiere obtener información estadística únicamente de las exportaciones, debe filtrar
# ... los siguientes tipos de operación" (Base de datos Operaciones de Salida page, Nov 2026).
CL_EXPORT_OPERATION_TYPES = (200, 201, 202, 203, 204, 205, 206, 207, 210, 211, 212, 213, 216)
CL_NET_KG_UNIT = 6                      # COD_UNIDAD_MEDIDA 6 = KN, KILO NETO (tablas de códigos)
CL_REQUIRED_COLUMNS = ("PERIODO", "MES", "COD_TIPO_OPERACION", "COD_PAIS_DESTINO", "ITEM_SA",
                       "FOBUS_AJUSTADO_IVV", "PESO_BRUTO_KG", "CANTIDAD_MERCANCIA", "COD_UNIDAD_MEDIDA")
CL_BACKFILL_MONTHS = 36                 # whole calendar years covering the last 36 months (see cl_window_start)
CL_MAX_CSV_BYTES = 400 * 1024 * 1024    # a yearly file is ~26 MB; anything far larger is not this file
CL_PARSER_VERSION = 1
# Destinations seen for honey 2023-2026 (code of Anexo 51-9 -> ISO3, name in the code table). A
# CROSS-CHECK: the published name must agree, else the destination is skipped with a warning.
CL_COUNTRY_CODES: dict[int, tuple[str, str]] = {
    563: ("DEU", "Alemania"), 225: ("USA", "Estados Unidos de América"), 505: ("FRA", "Francia"),
    517: ("ESP", "España"), 515: ("NLD", "Holanda"), 510: ("GBR", "Reino Unido"), 514: ("BEL", "Bélgica"),
    506: ("IRL", "Irlanda"), 501: ("PRT", "Portugal"), 504: ("ITA", "Italia"), 508: ("CHE", "Suiza"),
    544: ("CZE", "República Checa"), 545: ("SVK", "República Eslovaca"), 336: ("CHN", "China"),
    331: ("JPN", "Japón"), 341: ("ARE", "Emiratos Arabes Unidos"), 303: ("KWT", "Kuwait"),
    342: ("HKG", "Hong Kong (Región administrativa especial de China)"), 202: ("COL", "Colombia"),
    219: ("PER", "Perú"),
}
_RAR_MAGIC = b"Rar!\x1a\x07"
_ZIP_MAGIC = b"PK\x03\x04"


def cl_window_start(latest: Month) -> Month:
    """First month stored: January of the year 36 months back (2023-01 for a latest month 2026-09).
    Each yearly file is downloaded whole anyway, and whole years compare with annual sources."""
    return shift_month(latest, -(CL_BACKFILL_MONTHS - 1))[0], 1


class ClUnreadable(Exception):
    """The yearly DUS base file is in a format Paladex cannot open (RAR)."""


@dataclass(frozen=True)
class ClLink:
    text: str
    url: str


def _links(html_text: str, base: str) -> list[ClLink]:
    out = []
    for href, inner in re.findall(r'<a\s[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.DOTALL | re.IGNORECASE):
        out.append(ClLink(_cell_text(inner), urljoin(base, html_lib.unescape(href.strip()))))
    return out


@dataclass
class ClDusListing:
    years: dict[int, str]               # year -> data file URL
    code_table_url: str
    operation_types: tuple[int, ...] | None


def parse_cl_dus_listing(content: bytes, base: str = CL_DUS_PAGE_URL) -> ClDusListing:
    """The 'Base de datos Operaciones de Salida' page: one link per year (text = the year), the
    code tables, and the export operation types Aduana says to keep. Fails loudly when the year
    links or the code table link are gone."""
    text = content.decode("utf-8", errors="replace")
    years: dict[int, str] = {}
    code_table = None
    for link in _links(text, base):
        path = urlsplit(link.url).path.lower()
        if "/docs/" not in path:
            continue
        if re.fullmatch(r"\d{4}", link.text):
            years.setdefault(int(link.text), link.url)
        elif "tablas_de_codigos" in path or "tabla_de_codigos" in path:
            code_table = link.url
    if not years:
        raise CollectorError("Aduana Chile: no yearly file link on the 'Base de datos Operaciones de Salida' page "
                             "(page layout changed?); nothing stored")
    if not code_table:
        raise CollectorError("Aduana Chile: the code table link (tablas de códigos) is missing from the 'Base de datos "
                             "Operaciones de Salida' page (page layout changed?); nothing stored")
    ops = None
    m = re.search(r"tipos de operaci[oó]n:\s*([\d,\sy]+)", _cell_text(text), re.IGNORECASE)
    if m:
        found = tuple(int(x) for x in re.findall(r"\d{3}", m.group(1)))
        ops = found or None
    return ClDusListing(years=years, code_table_url=code_table, operation_types=ops)


def parse_cl_stats_listing(content: bytes, base: str = CL_STATS_PAGE_URL) -> dict[tuple[str, int], str]:
    """The 'Exportación por país y código arancelario' page: monthly workbooks per year, one for the
    FOB amount ("monto") and one for the gross weight ("peso"). {("monto"|"peso", year): url}."""
    text = content.decode("utf-8", errors="replace")
    out: dict[tuple[str, int], str] = {}
    for link in _links(text, base):
        if not re.fullmatch(r"\d{4}", link.text):
            continue
        name = urlsplit(link.url).path.lower().rsplit("/", 1)[-1]
        for kind in ("monto", "peso"):
            if kind in name and name.endswith((".xlsx", ".xls")):
                out.setdefault((kind, int(link.text)), link.url)
    if not out:
        raise CollectorError("Aduana Chile: no monthly workbook link on the 'Exportación por país y código arancelario' "
                             "page (page layout changed?)")
    return out


def parse_cl_country_table(content: bytes) -> dict[int, str]:
    """Sheet 'Países' of the code tables (Anexo 51-9): {COD_PAIS: NOMBRE_PAIS}. Fails loudly when
    the sheet or its header is gone."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise CollectorError(f"Aduana Chile: the code tables are not a readable workbook ({exc})") from exc
    sheet = next((ws for ws in wb.worksheets if _norm(ws.title) == "paises"), None)
    if sheet is None:
        raise CollectorError(f"Aduana Chile: no 'Países' sheet in the code tables (sheets: {wb.sheetnames})")
    out: dict[int, str] = {}
    header_seen = False
    for row in sheet.iter_rows(values_only=True):
        cells = [c for c in row if c is not None]
        if not header_seen:
            header_seen = any(_norm(c) == "cod pais" for c in cells)
            continue
        code = next((c for c in row if isinstance(c, int)), None)
        if code is None:
            continue
        name = next((c for c in row[row.index(code) + 1:] if isinstance(c, str) and c.strip()), None)
        if name:
            out[code] = name.strip()
    if not header_seen or not out:
        raise CollectorError("Aduana Chile: the 'Países' sheet has no COD_PAIS / NOMBRE_PAIS table (format changed?)")
    return out


def classify_cl_destination(code: int, names: dict[int, str]) -> tuple[str | None, str, str | None]:
    """(ISO3 or None, how, published name). Codes of Anexo 51-9 are Chilean, not ISO: the name in
    the code table is resolved, and must agree with CL_COUNTRY_CODES when the code is listed there.
    how: "table+name", "name", "conflict" or "unknown" (territories, free zones, ships' stores...)."""
    name = names.get(code)
    by_name = resolve_es_country(name) if name else None
    entry = CL_COUNTRY_CODES.get(code)
    if entry is not None:
        iso, expected = entry
        if by_name == iso or (by_name is None and name is not None and _norm(name) == _norm(expected)):
            return iso, "table+name", name
        return None, "conflict", name
    if by_name and by_name != "CHL":         # 997 "Chile": the reporter is never its own export market
        return by_name, "name", name
    return None, "unknown", name


def parse_cl_number(cell: Any) -> float | None:
    """'29501,08' -> 29501.08, '613' -> 613.0, '1.234,5' -> 1234.5. A dot without a comma
    ('1.234') is ambiguous (thousands or decimals) and is not read."""
    s = str(cell or "").strip().strip('"').strip()
    if re.fullmatch(r"-?\d+", s):
        return float(s)
    if re.fullmatch(r"-?\d+,\d+", s):
        return float(s.replace(",", "."))
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+,\d+", s):
        return float(s.replace(".", "").replace(",", "."))
    return None


@dataclass
class ClDusRow:
    month: int
    op_type: int
    dest_code: int
    sach: str
    fob_usd: float | None
    fob_legal_usd: float | None
    gross_kg: float | None
    quantity: float | None
    unit: int | None


@dataclass
class ClDusFile:
    year: int
    rows: list[ClDusRow]
    months_in_file: set[int]            # months present in the whole file (all products)
    extract: bytes                      # header + honey lines, verbatim
    member: str | None                  # name inside a ZIP
    problems: list[str] = field(default_factory=list)
    other_years: int = 0


def _dus_text(content: bytes, url: str) -> tuple[str, str | None]:
    """The CSV text of a yearly file (plain CSV, or a ZIP holding one CSV). RAR -> ClUnreadable."""
    if content[:6] == _RAR_MAGIC:
        raise ClUnreadable(f"{url} is a RAR archive")
    member = None
    if content[:4] == _ZIP_MAGIC:
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise CollectorError(f"Aduana Chile: {url} is not a readable ZIP ({exc})") from exc
        csvs = [i for i in zf.infolist() if i.filename.lower().endswith((".csv", ".txt"))]
        if len(csvs) != 1:
            raise CollectorError(f"Aduana Chile: {url} holds {[i.filename for i in zf.infolist()]}, not one CSV file "
                                 "(format changed?)")
        info = csvs[0]
        if info.file_size > CL_MAX_CSV_BYTES:
            raise CollectorError(f"Aduana Chile: {info.filename} in {url} would be {info.file_size} bytes; refused")
        member = info.filename
        content = zf.read(info)
        if content[:6] == _RAR_MAGIC:
            raise ClUnreadable(f"{url} holds a RAR archive")
    elif len(content) > CL_MAX_CSV_BYTES:
        raise CollectorError(f"Aduana Chile: {url} is {len(content)} bytes; refused")
    # latin-1 maps every byte to one character: the honey lines are re-encoded byte for byte.
    return content.decode("latin-1"), member


def _cl_num(fields: list[str], idx: dict[str, int], col: str) -> float | None:
    return parse_cl_number(fields[idx[col]]) if col in idx else None


def _cl_int(fields: list[str], idx: dict[str, int], col: str) -> int | None:
    v = fields[idx[col]].strip().strip('"') if col in idx else ""
    return int(v) if v.isdigit() else None


def parse_cl_dus(content: bytes, *, year: int, url: str) -> ClDusFile:
    """Parse a yearly 'Base de datos Operaciones de Salida' file (CSV, or ZIP with one CSV; ';'
    separated, values quoted or not, decimal comma). Keeps the rows of SACH 0409*.

    Fails loudly when a required column is missing. Rows of another year are counted and ignored.
    A honey row with an unreadable number is kept with that number as None (its destination-month
    is then not stored)."""
    text, member = _dus_text(content, url)
    # Split on "\n" only (str.splitlines would also split on characters such as U+0085, which latin-1
    # decodes from a single byte); each line keeps its own ending for the verbatim extract.
    lines = [ln for ln in re.split(r"(?<=\n)", text) if ln]
    if not lines or not lines[0].strip():
        raise CollectorError(f"Aduana Chile: {url} is empty")
    header = [h.strip().strip('"').strip().upper()
              for h in next(csv.reader([lines[0].rstrip("\r\n")], delimiter=";"))]
    missing = [c for c in CL_REQUIRED_COLUMNS if c not in header]
    if missing:
        raise CollectorError(f"Aduana Chile schema drift: column(s) {missing} missing from {url} (columns: "
                             f"{header[:25]}); nothing stored")
    idx = {h: i for i, h in enumerate(header)}
    i_year, i_month, i_item = idx["PERIODO"], idx["MES"], idx["ITEM_SA"]
    out = ClDusFile(year=year, rows=[], months_in_file=set(), extract=b"", member=member)
    keep = [lines[0]]
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cheap = line.split(";")
        if len(cheap) < len(header):
            out.problems.append(f"Aduana Chile {url} line {n}: {len(cheap)} fields for {len(header)} columns; skipped")
            continue
        y, m = cheap[i_year].strip().strip('"'), cheap[i_month].strip().strip('"')
        if not (y.isdigit() and m.isdigit()) or not 1 <= int(m) <= 12:
            out.problems.append(f"Aduana Chile {url} line {n}: unreadable PERIODO/MES {y!r}/{m!r}; skipped")
            continue
        if int(y) != year:
            out.other_years += 1
            continue
        out.months_in_file.add(int(m))
        if CL_HONEY_PREFIX not in cheap[i_item]:
            continue
        fields = next(csv.reader([line.rstrip("\r\n")], delimiter=";"))
        item = fields[i_item].strip()
        if not (len(item) == 8 and item.isdigit() and item.startswith(CL_HONEY_PREFIX)):
            continue
        keep.append(line)
        op, dest = _cl_int(fields, idx, "COD_TIPO_OPERACION"), _cl_int(fields, idx, "COD_PAIS_DESTINO")
        if op is None or dest is None:
            out.problems.append(f"Aduana Chile {url} line {n}: unreadable operation type or destination; skipped")
            continue
        out.rows.append(ClDusRow(
            month=int(m), op_type=op, dest_code=dest, sach=item, fob_usd=_cl_num(fields, idx, "FOBUS_AJUSTADO_IVV"),
            fob_legal_usd=_cl_num(fields, idx, "FOB_US_DUSLEG"), gross_kg=_cl_num(fields, idx, "PESO_BRUTO_KG"),
            quantity=_cl_num(fields, idx, "CANTIDAD_MERCANCIA"), unit=_cl_int(fields, idx, "COD_UNIDAD_MEDIDA")))
    out.extract = "".join(keep).encode("latin-1")
    return out


@dataclass
class ClStatsBook:
    kind: str                           # "monto" (FOB US$) | "peso" (gross kg)
    year: int
    months: list[int]
    values: dict[tuple[str, str], dict[int, float]]     # (country name, SACH code) -> {month: value}
    problems: list[str] = field(default_factory=list)


_ES_MONTH_NAMES = dict(SIE_MONTHS)


def parse_cl_stats_book(content: bytes, *, kind: str, year: int, url: str) -> ClStatsBook:
    """A monthly 'Exportación por país y código arancelario' workbook: a country row followed by its
    8-digit tariff-code rows, one column per month ("Enero - 2025"...), then the cumulative column.

    Fails loudly when the header row, the month columns of `year`, or the measure ("Monto FOB en
    dólares" for monto, "Peso en Kilos Brutos" for peso) are not what is expected."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise CollectorError(f"Aduana Chile: {url} is not a readable workbook ({exc})") from exc
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hi = next((i for i, r in enumerate(rows) if any(_norm(c) == "pais codigo arancelario" for c in r if isinstance(c, str))), None)
    if hi is None:
        raise CollectorError(f"Aduana Chile: no 'País / Código Arancelario' header in {url} (format changed?)")
    label_col = next(j for j, c in enumerate(rows[hi]) if isinstance(c, str) and _norm(c) == "pais codigo arancelario")
    measure = " ".join(_norm(c) for r in rows[max(0, hi - 2):hi + 1] for c in r if isinstance(c, str))
    expected = "monto fob" if kind == "monto" else "peso en kilos brutos"
    if expected not in measure:
        raise CollectorError(f"Aduana Chile: {url} does not state '{expected}' above its header (found {measure[:120]!r}); "
                             "nothing stored")
    month_cols: dict[int, int] = {}
    for j, c in enumerate(rows[hi]):
        m = re.fullmatch(r"\s*([A-Za-zÁÉÍÓÚáéíóú]+)\s*-\s*(\d{4})\s*", c) if isinstance(c, str) else None
        if m and SIE_MONTHS.get(_norm(m.group(1))) and int(m.group(2)) == year:
            month_cols[j] = SIE_MONTHS[_norm(m.group(1))]
    if not month_cols or len(set(month_cols.values())) != len(month_cols):
        raise CollectorError(f"Aduana Chile: no month columns of {year} in {url} (header: {rows[hi][:6]}...)")
    out = ClStatsBook(kind=kind, year=year, months=sorted(month_cols.values()), values={})
    country = None
    for r in rows[hi + 1:]:
        label = r[label_col] if len(r) > label_col else None
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip()
        if re.fullmatch(r"\d{8}", label):
            if country is None or not label.startswith(CL_HONEY_PREFIX):
                continue
            vals: dict[int, float] = {}
            for j, m in month_cols.items():
                v = r[j] if len(r) > j else None
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    out.problems.append(f"Aduana Chile {url}: unreadable {kind} {v!r} for {country} {label} month {m}; skipped")
                    continue
                vals[m] = float(v)
            out.values[(country, label)] = vals
        elif _norm(label).startswith(("total", "fuente")):
            country = None
        else:
            country = label
    return out


@dataclass
class _ClAgg:
    iso3: str
    month: int
    names: list[str] = field(default_factory=list)
    codes: list[int] = field(default_factory=list)
    fob: float = 0.0
    fob_legal: float | None = 0.0
    gross: float | None = 0.0
    net: float | None = 0.0
    net_ok: bool = True
    lines: dict[str, dict] = field(default_factory=dict)
    op_types: set[int] = field(default_factory=set)
    rows: int = 0


class ClHoneyExportsCollector(Collector):
    key = "cl_honey_exports"
    name = "Cile – Servicio Nacional de Aduanas: esportazioni di miele (SACH 0409) per destinazione"
    publisher = "Servicio Nacional de Aduanas de Chile"
    homepage = CL_DUS_PAGE_URL
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "trade"
    country_iso3 = "CHL"
    language = "es"
    expected_update = "Mensile, 3-7 settimane dopo il mese (file annuali Aduana aggiornati ogni mese); controllo settimanale"
    expected_update_en = "Monthly, 3 to 7 weeks after the month (Aduana's yearly files, updated monthly); checked weekly"
    expected_max_age_days = 50
    terms_note = ("Fuente: Servicio Nacional de Aduanas de Chile – Base de datos Operaciones de Salida (open data, Ley "
                  "20.285; aggregated DUS declarations, no exporter fields). FOB US$ adjusted (FOBUS_AJUSTADO_IVV), net "
                  "kg = quantity declared in KN (kilo neto, the statistical unit of 04.09), gross kg in 'extra'; export "
                  "operation types as Aduana instructs. SACH 0409.0010 (organic) and 0409.0090 (other) are summed; the "
                  "split is kept. A year whose file is a RAR archive is read from Aduana's monthly statistics workbooks "
                  "instead: same FOB, gross weight only, so no net weight and no unit value. The publication date is "
                  "the file's date on aduana.cl. Export unit values are derived (FOB / net kg), not market quotations.")
    # Weekly, at night in Chile (07:50 in Rome). A check is the listing page plus a HEAD per file;
    # a yearly file (~20-27 MB) is downloaded only when it changed.
    schedule = {"trigger": "cron", "day_of_week": "tue", "hour": 7, "minute": 50}

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        page = ctx.fetch(CL_DUS_PAGE_URL, headers={"Accept": "text/html"}, store=False)
        listing = parse_cl_dus_listing(page.content)
        ops = self._operation_types(ctx, state, listing)
        newest = max(listing.years)
        reparse = ctx.force or state.get("parser_version") != CL_PARSER_VERSION or not _has_rows(ctx)
        self._names: dict[int, str] | None = None
        self._stats_links: dict[tuple[str, int], str] | None = None
        latest = self._parse_month(state.get("latest_month"))
        # Newest year first: its file sets the latest month, hence the 36-month window.
        years = [newest]
        processed: set[int] = set()
        while years:
            year = years.pop(0)
            if year in processed or year not in listing.years:
                continue
            processed.add(year)
            got = self._process_year(ctx, state, listing, ops, year, latest, reparse)
            if got is not None and (latest is None or _midx(got) > _midx(latest)):
                latest = got
            if year == newest:
                if latest is None:
                    ctx.warn(f"Aduana Chile: the {year} file holds no month; nothing stored")
                    break
                start = cl_window_start(latest)
                years += [y for y in range(latest[0] - 1, start[0] - 1, -1) if y in listing.years]
                missing = [y for y in range(start[0], latest[0] + 1) if y not in listing.years]
                if missing:
                    ctx.warn(f"Aduana Chile: no yearly file listed for {missing}; those months are not stored")
            _save_state(ctx, state)
            ctx.checkpoint()
        if latest is not None:
            state["latest_month"] = month_label(latest)
        state.update({"backfill_done": True, "parser_version": CL_PARSER_VERSION,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    @staticmethod
    def _parse_month(value: Any) -> Month | None:
        m = re.fullmatch(r"(\d{4})-(\d{2})", str(value or ""))
        return (int(m.group(1)), int(m.group(2))) if m else None

    def _operation_types(self, ctx: CollectContext, state: dict, listing: ClDusListing) -> frozenset[int]:
        if listing.operation_types is None:
            _warn_once(ctx, state, "ops:unreadable",
                       "Aduana Chile: the list of export operation types is no longer readable on the page; the "
                       f"known list {list(CL_EXPORT_OPERATION_TYPES)} is used")
            return frozenset(CL_EXPORT_OPERATION_TYPES)
        if tuple(sorted(listing.operation_types)) != tuple(sorted(CL_EXPORT_OPERATION_TYPES)):
            _warn_once(ctx, state, "ops:" + ",".join(map(str, sorted(listing.operation_types))),
                       f"Aduana Chile now lists export operation types {list(listing.operation_types)} (was "
                       f"{list(CL_EXPORT_OPERATION_TYPES)}): the page's list is used")
        return frozenset(listing.operation_types)

    # ------------------------------------------------------------------ files
    def _validators(self, ctx: CollectContext, url: str) -> dict | None:
        """ETag / Last-Modified / length of a file, from a HEAD request (None when HEAD fails)."""
        try:
            doc = ctx.fetch(url, method="HEAD", store=False)
        except CollectorError as exc:
            log.info("[%s] HEAD %s failed (%s); the file is downloaded", self.key, url, exc)
            return None
        return self._headers(doc.headers)

    @staticmethod
    def _headers(headers: dict) -> dict:
        h = {k.lower(): v for k, v in headers.items()}
        return {"etag": h.get("etag"), "last_modified": h.get("last-modified"), "length": h.get("content-length")}

    def _unchanged(self, ctx: CollectContext, state: dict, url: str, reparse: bool) -> bool:
        known = state.get("files", {}).get(url)
        if reparse or not known:
            return False
        now = self._validators(ctx, url)
        if now is None or not (now.get("etag") or now.get("last_modified")):
            return False
        return all(now.get(k) == known.get(k) for k in ("etag", "last_modified", "length"))

    def _remember(self, state: dict, url: str, headers: dict) -> None:
        state.setdefault("files", {})[url] = self._headers(headers)

    def _country_names(self, ctx: CollectContext, listing: ClDusListing) -> dict[int, str]:
        if self._names is None:
            doc = ctx.fetch(listing.code_table_url, title="Aduana Chile – tablas de códigos (DUS open data)")
            self._names = parse_cl_country_table(doc.content)
        return self._names

    # ------------------------------------------------------------------ years
    def _process_year(self, ctx: CollectContext, state: dict, listing: ClDusListing, ops: frozenset[int], year: int,
                      latest: Month | None, reparse: bool) -> Month | None:
        """Store one year. Returns the newest month of its file (None when nothing was read)."""
        url = listing.years[year]
        ystate = state.setdefault("years", {}).setdefault(str(year), {})
        ext = urlsplit(url).path.lower().rsplit(".", 1)[-1]
        if ext not in ("csv", "zip", "txt"):
            return self._fallback_year(ctx, state, year, f"the {year} file of the DUS base is a .{ext} archive", latest,
                                       reparse)
        if ystate.get("url") == url and ystate.get("family") == "dus" and self._unchanged(ctx, state, url, reparse):
            log.info("[%s] %s unchanged since the last run", self.key, url)
            return self._parse_month(ystate.get("latest_month"))
        doc = ctx.fetch(url, store=False)
        try:
            parsed = parse_cl_dus(doc.content, year=year, url=url)
        except ClUnreadable as exc:
            return self._fallback_year(ctx, state, year, str(exc), latest, reparse)
        for p in parsed.problems[:20]:
            ctx.warn(p)
        if not parsed.months_in_file:
            ctx.warn(f"Aduana Chile: {url} holds no row of {year}")
            return None
        file_date = _http_date(self._headers(doc.headers).get("last_modified"))
        if file_date is None:
            _warn_once(ctx, state, f"no_date:{year}", f"Aduana Chile: {url} has no Last-Modified date; rows are stored "
                                                     "without publication date")
        title = (f"Aduana Chile – Base de datos Operaciones de Salida {year}: rows of SACH 0409* "
                 f"(extract of {url.rsplit('/', 1)[-1]}{' / ' + parsed.member if parsed.member else ''})")
        raw_id, unchanged = ctx.store_raw(url, parsed.extract, "text/csv", title=title, published_at=file_date)
        newest = (year, max(parsed.months_in_file))
        ref = latest if latest is not None and _midx(latest) > _midx(newest) else newest
        window_start = cl_window_start(ref)
        if not unchanged or reparse:
            self._store_dus(ctx, state, listing, ops, parsed, url, raw_id, file_date, window_start)
        else:
            log.info("[%s] %s: same honey rows as already stored", self.key, url)
        self._remember(state, url, doc.headers)
        ystate.update({"url": url, "family": "dus", "latest_month": month_label(newest),
                       "months_in_file": sorted(parsed.months_in_file)})
        return newest

    def _store_dus(self, ctx: CollectContext, state: dict, listing: ClDusListing, ops: frozenset[int],
                   parsed: ClDusFile, url: str, raw_id: int, file_date: date | None, window_start: Month) -> None:
        names = self._country_names(ctx, listing)
        year = parsed.year
        aggs: dict[tuple[str, int], _ClAgg] = {}
        bad: set[tuple[int, int]] = set()            # (dest_code, month) with an unusable row
        unsure_months: set[int] = set()
        excluded_ops: dict[int, int] = defaultdict(int)
        for row in parsed.rows:
            if row.op_type not in ops:
                excluded_ops[row.op_type] += 1
                continue
            if row.fob_usd is None or row.fob_usd < 0:
                ctx.warn(f"Aduana Chile {year}-{row.month:02d}: unreadable FOB on a honey row for destination "
                         f"{row.dest_code}; that destination-month is not stored")
                bad.add((row.dest_code, row.month))
                unsure_months.add(row.month)
                continue
            iso, how, name = classify_cl_destination(row.dest_code, names)
            if iso is None:
                unsure_months.add(row.month)
                self._report_unmapped(ctx, state, row.dest_code, name, how)
                continue
            agg = aggs.get((iso, row.month))
            if agg is None:
                agg = aggs[(iso, row.month)] = _ClAgg(iso, row.month)
            if name and name not in agg.names:
                agg.names.append(name)
            if row.dest_code not in agg.codes:
                agg.codes.append(row.dest_code)
            agg.fob += row.fob_usd
            agg.fob_legal = None if agg.fob_legal is None or row.fob_legal_usd is None else agg.fob_legal + row.fob_legal_usd
            agg.gross = None if agg.gross is None or row.gross_kg is None else agg.gross + row.gross_kg
            if row.unit == CL_NET_KG_UNIT and row.quantity is not None and row.quantity >= 0 and agg.net is not None:
                agg.net += row.quantity
            else:
                agg.net, agg.net_ok = None, False
            line = agg.lines.setdefault(row.sach, {"sach": row.sach, "label": CL_SACH_LINES.get(row.sach),
                                                   "fob_usd": 0.0, "net_kg": 0.0, "gross_kg": 0.0})
            line["fob_usd"] += row.fob_usd
            line["net_kg"] = (line["net_kg"] + row.quantity
                              if line["net_kg"] is not None and row.unit == CL_NET_KG_UNIT and row.quantity is not None
                              else None)
            line["gross_kg"] = line["gross_kg"] + row.gross_kg if line["gross_kg"] is not None and row.gross_kg is not None else None
            agg.op_types.add(row.op_type)
            agg.rows += 1
        for (iso, month), agg in aggs.items():
            if not agg.net_ok:
                _warn_once(ctx, state, f"net:{iso}:{year}-{month:02d}",
                           f"Aduana Chile {year}-{month:02d} {iso}: a honey row is not declared in KN (net kg) or its "
                           "quantity is unreadable; stored without net weight")
        present: set[str] = set()
        dus_months = set(state.get("dus_months", []))
        for (iso, month), agg in sorted(aggs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            if _midx((year, month)) < _midx(window_start):
                continue
            if any((c, month) in bad for c in agg.codes):
                continue
            present.add(self._store(ctx, agg, year, url, raw_id, file_date, family="dus", extra_file={
                "dataset": "Base de datos Operaciones de Salida (DUS)", "file": url, "zip_member": parsed.member,
                "fob_field": "FOBUS_AJUSTADO_IVV", "quantity_unit": "KN (kilo neto)",
                "excluded_operation_types": dict(excluded_ops) or None}))
        months = [m for m in parsed.months_in_file if _midx((year, m)) >= _midx(window_start) and m not in unsure_months]
        labels = [month_label((year, m)) for m in months]
        dus_months.update(labels)
        state["dus_months"] = sorted(dus_months)
        gone = _retire_absent(ctx, prefix="aduana_cl|CHL|", months=labels, present=present,
                              price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|aduana_cl|{p}|CHL|0409|{lab}")
        if gone:
            ctx.warn(f"Aduana Chile no longer reports honey exports for {', '.join(gone)}: those rows are withdrawn "
                     "(kept in the history)")

    def _report_unmapped(self, ctx: CollectContext, state: dict, code: int, name: str | None, how: str) -> None:
        state.setdefault("unknown_partners", {})[str(code)] = name
        if how == "conflict":
            iso, expected = CL_COUNTRY_CODES[code]
            msg = (f"Aduana Chile destination code {code} is named {name!r} in the code table, but "
                   f"CL_COUNTRY_CODES says {expected!r} ({iso}); its rows are skipped until checked")
        else:
            msg = (f"Aduana Chile destination code {code} ({name or 'not in the code table'}) is not a country Paladex "
                   "can map (territory, free zone, ships' stores...); its rows are skipped")
        _warn_once(ctx, state, f"partner:{code}:{name}", msg)

    # ------------------------------------------------------------- fallback
    def _fallback_year(self, ctx: CollectContext, state: dict, year: int, reason: str, latest: Month | None,
                       reparse: bool) -> Month | None:
        """A year whose DUS base cannot be opened: the monthly statistics workbooks (FOB and gross kg)
        for the months not already stored from the DUS base."""
        _warn_once(ctx, state, f"fallback:{year}",
                   f"Aduana Chile: {reason}, which Paladex cannot open; {year} is read from the monthly statistics "
                   "workbooks instead (FOB and gross weight only: no net weight, no unit value)")
        if self._stats_links is None:
            page = ctx.fetch(CL_STATS_PAGE_URL, headers={"Accept": "text/html"}, store=False)
            self._stats_links = parse_cl_stats_listing(page.content)
        monto, peso = self._stats_links.get(("monto", year)), self._stats_links.get(("peso", year))
        if not monto or not peso:
            ctx.warn(f"Aduana Chile: no monthly statistics workbook for {year} either; {year} is not stored")
            return None
        ystate = state.setdefault("years", {}).setdefault(str(year), {})
        if (ystate.get("family") == "stats" and ystate.get("url") == monto and ystate.get("peso_url") == peso
                and self._unchanged(ctx, state, monto, reparse) and self._unchanged(ctx, state, peso, reparse)):
            log.info("[%s] %s workbooks unchanged", self.key, year)
            return self._parse_month(ystate.get("latest_month"))
        docs = {}
        for kind, url in (("monto", monto), ("peso", peso)):
            docs[kind] = ctx.fetch(url, store=False)
        books = {kind: parse_cl_stats_book(docs[kind].content, kind=kind, year=year, url=docs[kind].url)
                 for kind in ("monto", "peso")}
        for b in books.values():
            for p in b.problems[:10]:
                ctx.warn(p)
        file_date = _http_date(self._headers(docs["monto"].headers).get("last_modified"))
        raw = {kind: ctx.store_raw(docs[kind].url, docs[kind].content, docs[kind].content_type,
                                   title=f"Aduana Chile – exportación por país y código arancelario {year} ({kind})",
                                   published_at=file_date)
               for kind in ("monto", "peso")}
        months_in_book = books["monto"].months
        if not months_in_book:
            return None
        newest = (year, max(months_in_book))
        ref = latest if latest is not None and _midx(latest) > _midx(newest) else newest
        window_start = cl_window_start(ref)
        dus_months = set(state.get("dus_months", []))
        aggs: dict[tuple[str, int], _ClAgg] = {}
        unsure: set[int] = set()
        for (country, code), months in books["monto"].values.items():
            iso = resolve_es_country(country)
            gross_row = books["peso"].values.get((country, code), {})
            for m, fob in months.items():
                if fob <= 0:
                    continue
                if iso is None:
                    unsure.add(m)
                    _warn_once(ctx, state, f"partner:stats:{country}",
                               f"Aduana Chile statistics: destination {country!r} has no ISO3 mapping; its rows are "
                               "skipped until it is added to trade_uruguay_chile._ES_NAMES_RAW")
                    continue
                agg = aggs.get((iso, m))
                if agg is None:
                    agg = aggs[(iso, m)] = _ClAgg(iso, m, net=None, net_ok=False, fob_legal=None)
                if country not in agg.names:
                    agg.names.append(country)
                agg.fob += fob
                g = gross_row.get(m)
                agg.gross = None if agg.gross is None or g is None else agg.gross + g
                agg.lines[code] = {"sach": code, "label": CL_SACH_LINES.get(code), "fob_usd": fob, "net_kg": None,
                                   "gross_kg": g}
                agg.rows += 1
        present: set[str] = set()
        for (iso, m), agg in sorted(aggs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            label = month_label((year, m))
            if label in dus_months or _midx((year, m)) < _midx(window_start):
                continue
            present.add(self._store(ctx, agg, year, monto, raw["monto"][0], file_date, family="stats", extra_file={
                "dataset": "Exportación por país y código arancelario (monthly statistics)", "file": monto,
                "gross_weight_file": peso, "fallback_reason": reason,
                "weight_note": "the statistics give gross kg only ('Peso en Kilos Brutos'): no net weight, no unit value"}))
        labels = [month_label((year, m)) for m in months_in_book
                  if m not in unsure and month_label((year, m)) not in dus_months and _midx((year, m)) >= _midx(window_start)]
        gone = _retire_absent(ctx, prefix="aduana_cl|CHL|", months=labels, present=present,
                              price_key=lambda p, lab: f"{PriceType.EXPORT_UNIT_VALUE.value}|aduana_cl|{p}|CHL|0409|{lab}")
        if gone:
            ctx.warn(f"Aduana Chile statistics no longer report honey exports for {', '.join(gone)}: those rows are "
                     "withdrawn (kept in the history)")
        for kind, url in (("monto", monto), ("peso", peso)):
            self._remember(state, url, docs[kind].headers)
        ystate.update({"url": monto, "peso_url": peso, "family": "stats", "latest_month": month_label(newest)})
        return newest

    # ------------------------------------------------------------------ rows
    def _store(self, ctx: CollectContext, agg: _ClAgg, year: int, url: str, raw_id: int, file_date: date | None,
               *, family: str, extra_file: dict) -> str:
        label = month_label((year, agg.month))
        p_start, p_end = month_bounds(year, agg.month)
        net = round(agg.net, 3) if agg.net is not None and agg.net_ok else None
        lines = []
        for code in sorted(agg.lines):
            ln = agg.lines[code]
            ln_net = ln.get("net_kg")
            lines.append({**ln, "fob_usd": round(ln["fob_usd"], 2),
                          "net_kg": round(ln_net, 3) if ln_net is not None else None,
                          "gross_kg": round(ln["gross_kg"], 3) if ln.get("gross_kg") is not None else None,
                          "unit_value_usd_per_kg": (round(ln["fob_usd"] / ln_net, 4)
                                                    if ln_net and ln_net >= MIN_UNIT_VALUE_WEIGHT_KG else None)})
        extra = {
            "sach_lines": lines, "destination_name": agg.names[0] if agg.names else None,
            "destination_codes": agg.codes or None,
            "gross_weight_kg": round(agg.gross, 3) if agg.gross is not None else None,
            "fob_legalised_usd": round(agg.fob_legal, 2) if agg.fob_legal is not None else None,
            "operation_types": sorted(agg.op_types) or None, "rows": agg.rows, "family": family, **extra_file,
        }
        common = dict(period_start=p_start, period_end=p_end, period_label=label, frequency="M",
                      published_at=file_date, source_url=url, raw_document_id=raw_id or None,
                      data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL)
        series = f"aduana_cl|CHL|{agg.iso3}|export|0409|{label}"
        ctx.add_trade(
            series_key=series, hs_code="0409", reporter_iso3="CHL", partner_iso3=agg.iso3, flow=TradeFlow.EXPORT.value,
            currency="USD", value=round(agg.fob, 2), net_weight_kg=net, value_basis="FOB", extra=extra,
            notes=("Esportazioni cilene di miele naturale SACH 0409 (Servicio Nacional de Aduanas): valore FOB in USD"
                   + (" e peso netto (quantità dichiarata in kg netti, unità KN); peso lordo e dettaglio biologico/altro "
                      "in 'extra'." if family == "dus" else
                      "; il file di quest'anno è disponibile solo come statistica con peso lordo: nessun peso netto, "
                      "nessun valore unitario (peso lordo in 'extra').")),
            **common,
        )
        price_series = f"aduana_cl|{agg.iso3}|CHL|0409|{label}"
        if net is not None and net >= MIN_UNIT_VALUE_WEIGHT_KG and agg.fob > 0:
            destination = agg.names[0] if agg.names else agg.iso3
            ctx.add_price(
                series_key=price_series, price_type=PriceType.EXPORT_UNIT_VALUE, variety=Variety.UNSPECIFIED.value,
                price_value=round(agg.fob / net, 4), currency="USD", unit="kg", origin_iso3="CHL", origin_label="Chile",
                market_iso3=agg.iso3, market_location=destination, terms="FOB",
                variety_raw="SACH 0409 natural honey (0409.0010 organic + 0409.0090 other)", volume_kg=net,
                notes=("Valore unitario all'esportazione = valore FOB / peso netto (Servicio Nacional de Aduanas, "
                       "SACH 0409). Dato doganale derivato, non una quotazione di mercato."),
                extra={"fob_usd": round(agg.fob, 2), "net_kg": net, "sach_lines": lines,
                       "gross_weight_kg": extra["gross_weight_kg"], "file": url},
                **common,
            )
        else:
            # A revision can push a flow below 1 t (or lose its net weight): the earlier unit value goes.
            ctx.retire(PriceObservation, f"{PriceType.EXPORT_UNIT_VALUE.value}|{price_series}")
        return series


__all__ = [
    "CL_COUNTRY_CODES",
    "ClHoneyExportsCollector",
    "UyHoneyExportsCollector",
    "cl_window_start",
    "classify_cl_destination",
    "classify_sie_destination",
    "parse_cl_country_table",
    "parse_cl_dus",
    "parse_cl_dus_listing",
    "parse_cl_number",
    "parse_cl_stats_book",
    "parse_cl_stats_listing",
    "parse_sie_number",
    "parse_sie_options",
    "parse_sie_table",
    "resolve_es_country",
    "sie_extract",
    "sie_monthly",
]
