"""Official national honey production and beehive statistics from the agencies of origin countries
(South America, Canada, Mexico, Turkey).

Research: docs/research/official_south_america.json, official_north_america_oceania.json and
official_asia_turkey.json. Everything here is checked against the live sources (captures of 4-5 Nov
2026 in ``tests/fixtures/production_official/real_*``). Canada, Mexico and Turkey: see the sections
"Canada, Mexico, Turkey" at the end of this docstring.

Collectors
----------
* ``br_ibge_honey``: Brazil, IBGE **Pesquisa da Pecuária Municipal (PPM)**, SIDRA table 74,
  classification 80 category 2687 "Mel de abelha": honey production (variable 106, published in
  kg) and value of production (variable 215, thousand reais, nominal), for Brazil (N1) and each
  of the 27 federative units (N3), every year from ``IBGE_FIRST_YEAR`` (2015) to the latest
  edition. Read from the official SIDRA values API (``apisidra.ibge.gov.br/values``), one request.
* ``ar_magyp_hives``: Argentina, SAGyP (ex MAGyP) Coordinación Apícola, **RENAPA** (Registro
  Nacional de Productores Apícolas): the register extracts published as CSV on the ministry's
  CKAN portal (datos.magyp.gob.ar, licence CC BY 4.0). One row per register snapshot: registered
  hives in Argentina, with producers, apiaries and the provincial split kept in ``extra``.
* ``cl_odepa_hives``: Chile, Odepa (Ministry of Agriculture) "Cifras apícolas nacionales desde los
  registros administrativos del SIPEC" (first edition 19 Oct 2026), built on SAG's SIPEC Apícola
  register: the "Total nacional" row of the table "Número de colmenas por región, período
  2019-2025" (hives declared each October), read from the article PDF's text layer. A PDF, but the
  table reads unambiguously: a title, a header of consecutive years, one line per region and a
  complete total row; anything else fails loudly. Only the published total is stored as data; the
  regional rows go to ``extra`` (and are dropped, with a warning, if a row has blank cells, which
  the text layer cannot place in their columns). In the first edition the regions add up to the
  total except in 2020 (+3 hives) and 2025 (+6): reported once per edition, the published total is
  kept as is.

What is stored (``ProductionStat``)
-----------------------------------
* Brazil, national: metric ``production`` in **t** (kg ÷ 1000, an exact conversion; the kg figure
  as published is kept in ``extra.value_as_published``) and ``production_value`` in ``1000 BRL``
  ("Mil Reais", as published, nominal). ``country_iso3`` BRA, annual.
* Brazil, states: the same two figures under the metrics ``production_by_region`` and
  ``production_value_by_region``, ``country_iso3`` BRA, the state in ``extra.region`` (with
  ``region_code`` (IBGE), ``region_abbr`` (UF) and ``macro_region``). They use their own metrics on
  purpose: the shared production views (``/api/harvest/production``, the map, the assistant) read
  metric ``production`` per country and source, so a state row stored as ``production`` would be
  shown as Brazil's national figure. National and state rows are never summed by this collector;
  the state rows are only checked against the national total (equal to the kg for every year
  2015-2025, live check of 5 Nov 2026).
* Chile: metric ``colonies`` (``number``), ``country_iso3`` CHL, one row per year, period = October
  of that year (the FRADA declaration month), label "YYYY", ``published_at`` = the article's
  ``article:published_time``, ``source_url`` = the PDF; registered (declared) hives, not a survey.
* Argentina: metric ``colonies`` (``number``), ``country_iso3`` ARG, ``frequency`` "irregular",
  period = the register's ``fecha_actualizacion`` (a single day). RENAPA publishes no national
  total row: the value is the **sum of the provincial rows** of the "por provincia" file, and the
  run fails (nothing stored) unless the "por departamento" file gives exactly the same hive and
  apiary totals. These are hives **registered** in an administrative register, not a survey count
  of hives in production; FAOSTAT's "Bees" figure for Argentina is a different, imputed number and
  both are shown side by side, never merged.
* Every row: ``reliability`` official, ``data_status`` "published" (no source publishes a
  provisional/final flag), the exact API or file URL in ``source_url``, the archived answer in
  ``raw_document_id``, and the publication date when the source gives one (see below).
  Revisions by the publisher become new revisions (``services.ingest``): IBGE revised 2024 in the
  2025 edition (FAOSTAT carries 67,313.99 t, i.e. the 67,313,986 kg IBGE first published per its
  2025 release as quoted in docs/research; SIDRA gives 68,235,733 kg now).

Change detection and politeness
-------------------------------
* IBGE: every run asks SIDRA for the national figures of the latest year only (``p/last 1``, about
  1 KB). The full table (about 195 KB) is pulled only when that answer changes (a new edition or a
  revision of the latest year), on the first run, when forced, or every ``IBGE_FULL_REFRESH_DAYS``
  (to catch silent corrections of earlier years). The PPM is released once a year, at the end of
  September (PPM 2025 on 30 Sep 2026 according to docs/research; not visible in the API).
* RENAPA: every run reads the CKAN ``package_show`` metadata (about 9 KB); the CSV files are
  downloaded only when a resource's URL or ``last_modified`` changed.
* Odepa: every run reads the ministry's apiculture page (about 150 KB) for the newest "Cifras
  apícolas" article; the article page and its PDF (about 1.5 MB) are downloaded only for a new
  edition, when forced, or every ``ODEPA_REFRESH_DAYS``. Odepa's certificate chains to "emSign Root
  CA - G1", which is in the standard (certifi/Mozilla) trust store httpx uses.

Schema drift fails loudly (``CollectorError``, nothing stored): SIDRA header labels, variable
names, the honey category, a unit other than "Quilogramas" / "Mil Reais", an unexpected
territorial level; RENAPA resources missing from the package, CSV columns missing, a malformed
count, several update dates in one file, totals that disagree between the two files; Odepa: no
article listed (first run), no link to the PDF, no "colmenas por región" table, a header that is not
a run of consecutive years, an incomplete "Total nacional" row, an unexpected line inside the table.

Publication dates
-----------------
* IBGE: the SIDRA values API carries no release date. IBGE publishes the release dates on pages
  behind a Cloudflare browser check (sidra.ibge.gov.br, www.ibge.gov.br, the SIDRA API help page:
  not worked around) and on ``servicodados.ibge.gov.br`` (agregados v3 ``/periodos`` gives a
  modification date per period), which the development network could not reach (connection reset).
  ``published_at`` is therefore left empty rather than guessed; the period and collection date are
  always shown. Reading ``/periodos`` is a possible improvement once that host is reachable.
* RENAPA: ``published_at`` = the CKAN ``last_modified`` date of the "por provincia" resource.
* Odepa: ``published_at`` = the article's ``article:published_time`` (2026-10-19 for the first edition).

Routes checked and NOT used (5 Nov 2026)
----------------------------------------
* Brazil: IBGE agregados v3 (``servicodados.ibge.gov.br``): unreachable from the development
  network (connection reset), and not needed (the SIDRA values API returns the same table).
* Argentina, honey production: no official machine-readable series exists. The SAGyP "Síntesis
  Apícola" / "Informe Apícola" bulletins are PDF narratives; the datos.gob.ar time-series API has no
  production or hive series (only INDEC honey export values, which the trade collectors cover); the
  SSPMI "Indicadores de Apícola" CSV (economia.gob.ar, listed on datos.gob.ar) could not be reached
  (connection reset), so its contents are unverified: to check from the owner's PC. FAOSTAT's
  Argentine production figures for 2019-2024 are FAO estimates.
* Uruguay (MGAP/DIGEGRA register of hive owners, RNPC; DIEA yearbook): no official machine-readable
  current series. RNPC results are published only as PDF reports attached to news items (latest
  found: "Informe de datos del RNPC 2022", 16 Feb 2023); the DIEA yearbook is one PDF on
  ``descargas.mgap.gub.uy`` (unreachable from the development network); the national open-data
  catalogue (catalogodatos.gub.uy) has no apiculture dataset; recent totals (e.g. 585,000 hives,
  Aug 2026) appear only in the press. Skipped.
* Chile, honey production: no official statistic is published (INE's 2021 agricultural census is
  a one-off; Odepa's season articles are narrative texts). Odepa's "Boletín Interactivo Apícola"
  is a Power BI dashboard (no data download), Odepa's WordPress API refuses unauthenticated access,
  datos.gob.cl has no apiculture dataset, and SAG's SIPEC Apícola needs a login. The hive register
  figures are collected by ``cl_odepa_hives``; the article's beekeeper table is kept only as its
  total row (its regional rows have blank cells).

Canada, Mexico, Turkey (live checks of 5 Nov 2026)
--------------------------------------------------
* ``ca_statcan_honey``: Statistics Canada table **32-10-0353-01** "Production and value of honey"
  (survey 3419, compiled from provincial apiculture data; NB and PEI by a StatCan mail survey), read
  from the keyless Web Data Service: ``getCubeMetadata`` (POST, ~7 KB) as the release check, then
  ``getDataFromCubePidCoordAndLatestNPeriods`` (POST, one request, ~110 KB) for Canada and the 9
  provinces in the table (no Newfoundland and Labrador, also excluded from "Canada") x beekeepers,
  colonies, production, value, from ``STATCAN_FIRST_YEAR``. Metrics: ``production`` in **t**
  (published in thousands of pounds; x 0.45359237 / 1000, exact by definition of the pound; the
  published figure is kept in ``extra.value_as_published``), ``production_value`` in ``1000 CAD`` as
  published (nominal; excludes inventory sales except in Quebec), ``colonies`` (number; may include
  pollination colonies) with the number of beekeepers in ``extra.beekeepers``; provinces under
  ``production_by_region``, ``production_value_by_region`` and ``colonies_by_region`` (province in
  ``extra.region``). The "Average yield per colony" estimate is terminated ('..' for every year since
  2014): not stored, and not recomputed. ``published_at`` = the WDS ``releaseTime`` of each point;
  symbol "p" (preliminary) -> data_status provisional, "r" (revised) kept in ``flag_raw``. StatCan
  revises the previous year with each December release: FAOSTAT's 35,460 t for 2024 equals 78,176
  thousand lb, presumably StatCan's first (December 2024) estimate (not verifiable from the WDS, which
  keeps no vintages); the current table gives 74,249 thousand lb (33,678.8 t, released again
  29 Apr 2026). 2018-2023 agree with FAOSTAT to the tonne (checked in the live run).
* ``mx_siap_honey``: SIAP (SADER) "Cierre de la producción pecuaria", product "Miel" (code 1910080),
  report "Producción, precio y valor": the page's own xajax service (``nube.agricultura.gob.mx/
  cierre_pecuario/``, function ``reporte2``, national level, one ~8 KB answer per year; called as a
  GET, which the service answers byte for byte like the page's POST). One row per state plus "Total".
  Metrics: ``production`` (t, as published), ``production_value`` (``1000 MXN``, "miles de pesos",
  nominal) for "Total"; the states under ``production_by_region`` / ``production_value_by_region``
  (state in ``extra.region``, ISO 3166-2 suffix and INEGI code). The price ("pesos por kilogramo",
  the average price paid to producers) is stored as a **producer** ``PriceObservation`` (MXN/kg,
  national average only; each state's price is kept in ``extra.price_mxn_per_kg`` of its rows).
  The states add up to "Total" exactly every year 2015-2025, and "Total" price = value / volume.
  FAOSTAT carries SIAP's figures (2024: 57,430.36 t = SIAP 57,430.360 t; 2020 differs by 8 kg).
  The service gives no publication date: ``published_at`` is empty.
* ``tr_tuik_honey``: TÜİK "Hayvansal Üretim İstatistikleri" (annual bulletin, 10 Feb 2026 for 2025),
  statistical table "Arıcılık" (an .xls: years 1991-2025; honey and wax in t; new and old hives;
  villages / holdings practising apiculture), compiled from the Ministry of Agriculture and Forestry's
  administrative records. Read through the public JSON API of TÜİK's data portal
  (``veriportali.tuik.gov.tr/api/tr/press`` -> the latest bulletin id -> ``/api/tr/press/{id}`` ->
  the table's download URL); the API answers 404 unless the request carries
  ``X-Requested-With: XMLHttpRequest`` (as the portal's own web app does). Metrics: ``production``
  (t) and ``colonies`` = new + old hives (TÜİK publishes the two columns, no total; both kept in
  ``extra`` with holdings and wax), from ``TUIK_FIRST_YEAR``; ``published_at`` = the bulletin date.
  FAOSTAT carries TÜİK's figures (2024: 95,492.31 t and 8,961,975 hives = TÜİK 95,492.311 t and
  8,717,162 + 244,813 hives). Needs the ``xlrd`` package for the .xls table.

Change detection: StatCan, the metadata ``releaseTime`` (the data are re-read on a new release or
every ``STATCAN_FULL_REFRESH_DAYS``); SIAP, the year list plus the latest year's report (every year is
re-read when that answer changes or every ``SIAP_FULL_REFRESH_DAYS``); TÜİK, the press list (the
bulletin and its table are read for a new issue or every ``TUIK_REFRESH_DAYS``).

Routes checked and NOT used (5 Nov 2026):

* Canada: the full-table CSV zip (``getFullTableDownloadCSV``) carries the whole history since 1924;
  the coordinate query returns the same figures for the years kept.
* Mexico: SIAP's open-data bulk files (``nube.agricultura.gob.mx/datosAbiertos``, one file per year
  with every species and municipality) are much larger than the state table needed; the year-end
  close query gives the published state table directly. Hive inventory (colmenas) is not in the
  close report; not collected.
* Turkey: TÜİK's SDMX REST service (``nsiws.tuik.gov.tr/rest``) answers 401 without a token, and a
  token needs an API key created after SMS verification of a Turkish mobile number (or requested by
  e-mail); the portal's anonymous dataflow list (510 dataflows) has no honey or hive dataflow; the
  MEDAS database (``biruni.tuik.gov.tr/medas``, provincial livestock figures) is a stateful ZK web
  application with no file or API access. Provincial honey figures are therefore not collected.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select

from ..enums import DataStatus, PriceType, Reliability, SourceKind, Variety
from ..models import AppSetting, ProductionStat, utcnow
from .base import CollectContext, Collector, CollectorError, month_bounds, year_bounds

log = logging.getLogger(__name__)

JSON_HEADERS = {"Accept": "application/json"}


def today() -> date:
    """Reference date (indirection so tests can pin it)."""
    return date.today()


# ===========================================================================
# Shared helpers
# ===========================================================================


def _state_key(source_key: str) -> str:
    return f"collector_state:{source_key}"


def _load_state(ctx: CollectContext) -> dict:
    """Per-collector bookkeeping in `app_settings` (commits and rolls back with the data)."""
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    return copy.deepcopy(row.value) if row is not None and isinstance(row.value, dict) else {}


def _save_state(ctx: CollectContext, state: dict) -> None:
    row = ctx.session.get(AppSetting, _state_key(ctx.source.key))
    if row is None:
        ctx.session.add(AppSetting(key=_state_key(ctx.source.key), value=copy.deepcopy(state)))
    else:
        row.value = copy.deepcopy(state)        # a new object, so SQLAlchemy sees the JSON change
    ctx.session.flush()


def _warn_once(ctx: CollectContext, state: dict, token: str, message: str) -> None:
    """`ctx.warn` the first time `token` is met (remembered in the collector state), then only log:
    a condition that cannot change by itself must not mark every run partial."""
    warned = state.setdefault("warned", [])
    if token in warned:
        log.info("[%s] %s", ctx.source.key, message)
        return
    warned.append(token)
    ctx.warn(message)


def _has_rows(ctx: CollectContext) -> bool:
    P = ProductionStat
    return ctx.session.scalar(select(P.id).where(P.source_id == ctx.source.id).limit(1)) is not None


def _norm(s: Any) -> str:
    """Accent- and case-insensitive comparison key ("Produção" == "producao")."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", s).strip()


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")      # pragma: no cover - latin-1 never fails


def _load_json(content: bytes, what: str) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        snippet = content[:120].decode("utf-8", errors="replace").strip()
        raise CollectorError(f"{what}: the answer is not valid JSON ({exc}); starts with {snippet!r}") from exc


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())          # Python 3.11+ reads a trailing "Z"
    except ValueError:
        return None


# ===========================================================================
# 1) Brazil: IBGE SIDRA, Pesquisa da Pecuária Municipal, table 74
# ===========================================================================

SIDRA_VALUES = "https://apisidra.ibge.gov.br/values"
SIDRA_TABLE_PAGE = "https://sidra.ibge.gov.br/tabela/74"
IBGE_TABLE = "74"
IBGE_VAR_QUANTITY = "106"            # Produção de origem animal (honey: kg)
IBGE_VAR_VALUE = "215"               # Valor da produção (Mil Reais)
IBGE_CLASSIFICATION = "80"           # Tipo de produto de origem animal
IBGE_HONEY_CATEGORY = "2687"         # Mel de abelha (live check 5 Nov 2026; 2682 is milk, 2684 wool)
IBGE_HONEY_NAME = "Mel de abelha"
IBGE_FIRST_YEAR = 2015               # first year kept (the series goes back to 1974)
IBGE_FULL_REFRESH_DAYS = 90          # re-read the whole table at least this often
IBGE_SURVEY = "Pesquisa da Pecuária Municipal (PPM)"

# Per variable: the name SIDRA prints, the only unit accepted, and the metrics used.
IBGE_VARIABLES: dict[str, dict[str, str]] = {
    IBGE_VAR_QUANTITY: {"name": "Produção de origem animal", "unit": "Quilogramas",
                        "metric": "production", "region_metric": "production_by_region"},
    IBGE_VAR_VALUE: {"name": "Valor da produção", "unit": "Mil Reais",
                     "metric": "production_value", "region_metric": "production_value_by_region"},
}
# Dimension labels of the header row (D1 depends on the levels requested, so it is not checked).
IBGE_HEADER_LABELS = {"V": "Valor", "D2N": "Variável", "D3N": "Ano", "D4N": "Tipo de produto de origem animal"}
IBGE_ROW_KEYS = ("NC", "NN", "MC", "MN", "V", "D1C", "D1N", "D2C", "D2N", "D3C", "D3N", "D4C", "D4N")
IBGE_LEVEL_BRAZIL, IBGE_LEVEL_STATE = "1", "3"

# IBGE federative-unit codes -> (UF abbreviation, name). The first digit is the IBGE macro-region.
BR_STATES: dict[str, tuple[str, str]] = {
    "11": ("RO", "Rondônia"), "12": ("AC", "Acre"), "13": ("AM", "Amazonas"), "14": ("RR", "Roraima"),
    "15": ("PA", "Pará"), "16": ("AP", "Amapá"), "17": ("TO", "Tocantins"),
    "21": ("MA", "Maranhão"), "22": ("PI", "Piauí"), "23": ("CE", "Ceará"), "24": ("RN", "Rio Grande do Norte"),
    "25": ("PB", "Paraíba"), "26": ("PE", "Pernambuco"), "27": ("AL", "Alagoas"), "28": ("SE", "Sergipe"),
    "29": ("BA", "Bahia"),
    "31": ("MG", "Minas Gerais"), "32": ("ES", "Espírito Santo"), "33": ("RJ", "Rio de Janeiro"),
    "35": ("SP", "São Paulo"),
    "41": ("PR", "Paraná"), "42": ("SC", "Santa Catarina"), "43": ("RS", "Rio Grande do Sul"),
    "50": ("MS", "Mato Grosso do Sul"), "51": ("MT", "Mato Grosso"), "52": ("GO", "Goiás"),
    "53": ("DF", "Distrito Federal"),
}
BR_MACRO_REGIONS = {"1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}

# SIDRA's special cells. "-" is a published zero; the others carry no value.
SIDRA_ZERO = "-"
SIDRA_SYMBOLS = {
    "-": "numeric zero (not a rounding)", "..": "not applicable", "...": "not available",
    "X": "withheld to avoid identifying respondents",
}
_SIDRA_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def sidra_url(first_year: int, last_year: int) -> str:
    """The honey query: Brazil (n1) and every state (n3), both variables, years first..last."""
    return (f"{SIDRA_VALUES}/t/{IBGE_TABLE}/n1/all/n3/all/v/{IBGE_VAR_QUANTITY},{IBGE_VAR_VALUE}"
            f"/p/{first_year}-{last_year}/c{IBGE_CLASSIFICATION}/{IBGE_HONEY_CATEGORY}")


# The cheap release check: national figures of the latest year only (about 1 KB).
SIDRA_PROBE_URL = (f"{SIDRA_VALUES}/t/{IBGE_TABLE}/n1/all/v/{IBGE_VAR_QUANTITY},{IBGE_VAR_VALUE}"
                   f"/p/last%201/c{IBGE_CLASSIFICATION}/{IBGE_HONEY_CATEGORY}")


@dataclass(frozen=True)
class SidraRow:
    level: str                  # "1" Brasil, "3" Unidade da Federação
    level_name: str
    loc_code: str               # "1" for Brazil, the IBGE code of the state otherwise
    loc_name: str
    variable: str               # "106" | "215"
    variable_name: str
    year: int
    unit_code: str
    unit_name: str
    raw: str                    # the cell exactly as published
    value: float | None         # None for a symbol without value ("...", "X"...)

    @property
    def symbol(self) -> str | None:
        return self.raw if self.raw in SIDRA_SYMBOLS else None


@dataclass
class SidraParse:
    rows: list[SidraRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def years(self) -> list[int]:
        return sorted({r.year for r in self.rows})


def _sidra_value(raw: str) -> tuple[float | None, bool]:
    """(value, readable). A number or the zero symbol "-" gives a value; the other symbols give
    (None, True); anything else is unreadable (None, False)."""
    if raw == SIDRA_ZERO:
        return 0.0, True
    if raw in SIDRA_SYMBOLS:
        return None, True
    if _SIDRA_NUMBER.fullmatch(raw):
        v = float(raw)
        return (v, True) if math.isfinite(v) else (None, False)
    return None, False


def parse_sidra(content: bytes, *, first_year: int | None = None, last_year: int | None = None) -> SidraParse:
    """Rows of a SIDRA table-74 honey answer. Fails loudly (CollectorError) on schema drift: not a
    header-first JSON array, changed dimension labels, another category than "Mel de abelha",
    another variable or a renamed one, an unexpected territorial level, a unit other than the one
    expected for the variable, a year that is not a year. Unreadable cells and years outside
    first..last are reported in `problems` and skipped."""
    doc = _load_json(content, "IBGE SIDRA")
    if not isinstance(doc, list) or not doc or not isinstance(doc[0], dict):
        raise CollectorError("IBGE SIDRA: expected a JSON array whose first element is the header row "
                             f"(got {str(doc)[:150]!r}); nothing stored")
    header = doc[0]
    missing = [k for k in IBGE_ROW_KEYS if k not in header]
    if missing:
        raise CollectorError(f"IBGE SIDRA schema drift: header row without {missing} (keys: {sorted(header)}); "
                             "nothing stored")
    changed = {k: header.get(k) for k, label in IBGE_HEADER_LABELS.items() if _norm(header.get(k)) != _norm(label)}
    if changed:
        raise CollectorError(f"IBGE SIDRA schema drift: dimension labels {changed} differ from {IBGE_HEADER_LABELS}; "
                             "nothing stored")
    out = SidraParse()
    for i, rec in enumerate(doc[1:], start=1):
        if not isinstance(rec, dict) or any(k not in rec for k in IBGE_ROW_KEYS):
            raise CollectorError(f"IBGE SIDRA schema drift: row {i} does not have the header's keys ({str(rec)[:150]!r})")
        cat, cat_name = str(rec["D4C"]).strip(), str(rec["D4N"]).strip()
        if cat != IBGE_HONEY_CATEGORY or _norm(cat_name) != _norm(IBGE_HONEY_NAME):
            raise CollectorError(f"IBGE SIDRA: row {i} is category {cat} {cat_name!r}, not {IBGE_HONEY_CATEGORY} "
                                 f"{IBGE_HONEY_NAME!r} (classification 80 changed?); nothing stored")
        var, var_name = str(rec["D2C"]).strip(), str(rec["D2N"]).strip()
        spec = IBGE_VARIABLES.get(var)
        if spec is None or _norm(var_name) != _norm(spec["name"]):
            raise CollectorError(f"IBGE SIDRA schema drift: row {i} is variable {var} {var_name!r} (expected "
                                 f"{ {k: v['name'] for k, v in IBGE_VARIABLES.items()} }); nothing stored")
        level = str(rec["NC"]).strip()
        if level not in (IBGE_LEVEL_BRAZIL, IBGE_LEVEL_STATE):
            raise CollectorError(f"IBGE SIDRA schema drift: row {i} has territorial level {level} {rec['NN']!r} "
                                 "(expected 1 Brasil or 3 Unidade da Federação); nothing stored")
        year_raw = str(rec["D3C"]).strip()
        if not re.fullmatch(r"\d{4}", year_raw):
            raise CollectorError(f"IBGE SIDRA schema drift: row {i} has period {year_raw!r}, not a year; nothing stored")
        year = int(year_raw)
        loc_name = str(rec["D1N"]).strip()
        if (first_year is not None and year < first_year) or (last_year is not None and year > last_year):
            out.problems.append(f"IBGE SIDRA: {loc_name} {year} is outside the requested years; skipped")
            continue
        raw = str(rec["V"]).strip()
        value, readable = _sidra_value(raw)
        if not readable:
            out.problems.append(f"IBGE SIDRA: unreadable value {raw!r} for {loc_name} {year} ({var_name}); skipped")
            continue
        unit_name = str(rec["MN"]).strip()
        if value is not None and _norm(unit_name) != _norm(spec["unit"]):
            raise CollectorError(f"IBGE SIDRA unit drift: {var_name} {year} {loc_name} is in {unit_name!r}, expected "
                                 f"{spec['unit']!r}; nothing stored")
        out.rows.append(SidraRow(
            level=level, level_name=str(rec["NN"]).strip(), loc_code=str(rec["D1C"]).strip(), loc_name=loc_name,
            variable=var, variable_name=var_name, year=year, unit_code=str(rec["MC"]).strip(), unit_name=unit_name,
            raw=raw, value=value,
        ))
    return out


@dataclass(frozen=True)
class SidraRelease:
    latest_year: int
    signature: str              # latest year plus its national figures as published


def parse_sidra_probe(content: bytes) -> SidraRelease:
    """The latest year and its national figures (the `p/last 1` answer)."""
    parsed = parse_sidra(content)
    national = [r for r in parsed.rows if r.level == IBGE_LEVEL_BRAZIL]
    if not national:
        raise CollectorError("IBGE SIDRA release check: no national honey figure in the answer (table changed?); "
                             "nothing stored")
    latest = max(r.year for r in national)
    cells = sorted(f"{r.variable}={r.raw}" for r in national if r.year == latest)
    return SidraRelease(latest_year=latest, signature=f"{latest}|{'|'.join(cells)}")


def check_sidra_totals(parsed: SidraParse) -> list[str]:
    """Consistency of the states with the national figure, year by year (warnings, never fixes):
    every state present, kg summing exactly to the national kg, values within rounding (one
    unit of the published thousand reais per state)."""
    msgs: list[str] = []
    by_key: dict[tuple[str, int], dict[str, SidraRow]] = {}
    national: dict[tuple[str, int], SidraRow] = {}
    for r in parsed.rows:
        if r.level == IBGE_LEVEL_BRAZIL:
            national[(r.variable, r.year)] = r
        else:
            by_key.setdefault((r.variable, r.year), {})[r.loc_code] = r
    for (var, year) in sorted(set(national) | set(by_key)):
        nat = national.get((var, year))
        states = by_key.get((var, year), {})
        name = IBGE_VARIABLES[var]["name"]
        if nat is None:
            msgs.append(f"IBGE SIDRA: no national figure for {name} {year} (states only)")
            continue
        missing = sorted(set(BR_STATES) - set(states))
        if missing:
            msgs.append(f"IBGE SIDRA: {name} {year}: no row for state(s) "
                        f"{', '.join(BR_STATES[c][0] for c in missing)}")
            continue
        if nat.value is None or any(s.value is None for s in states.values()):
            continue
        total = sum(s.value for s in states.values())
        tolerance = 0.0 if var == IBGE_VAR_QUANTITY else float(len(states))
        if abs(total - nat.value) > tolerance + 1e-9:
            msgs.append(f"IBGE SIDRA: {name} {year}: the states add up to {total:,.0f} {nat.unit_name}, the national "
                        f"figure is {nat.value:,.0f}; both kept as published")
    return msgs


class BrIbgeHoneyCollector(Collector):
    key = "br_ibge_honey"
    name = "Brasile – IBGE PPM (SIDRA tab. 74): produzione e valore del miele, Brasile e stati"
    publisher = "IBGE – Instituto Brasileiro de Geografia e Estatística, Pesquisa da Pecuária Municipal (PPM)"
    homepage = SIDRA_TABLE_PAGE
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "BRA"
    language = "pt"
    # Source.expected_update is String(120)
    expected_update = "Annuale (PPM: anno Y pubblicato a fine settembre Y+1); controllo mensile"
    expected_update_en = "Annual (PPM: year Y released at the end of September Y+1); checked monthly"
    # One release a year (end of September) plus about a month of slack.
    expected_max_age_days = 400
    terms_note = (
        "Fonte: IBGE – Pesquisa da Pecuária Municipal (PPM), SIDRA tabela 74 (Mel de abelha). Public IBGE "
        "statistics, free reuse citing the source. Production is published in kg and stored in tonnes (kg ÷ 1000, "
        "exact; the kg figure is kept with each row); the value of production is in thousand reais at current "
        "prices, as published. Brazil and each state are separate rows (states under their own metrics), never "
        "summed. SIDRA gives no release date, so none is shown. IBGE revises earlier years with each annual "
        "edition: every change is kept as a revision."
    )
    # Monthly; each run is one ~1 KB request unless a new edition (late September) appears.
    schedule = {"trigger": "cron", "day": 9, "hour": 6, "minute": 40}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        release = self._probe(ctx)
        have_rows = _has_rows(ctx)
        pulled_at = _parse_iso_datetime(state.get("pulled_at"))
        recent = pulled_at is not None and utcnow() - pulled_at < timedelta(days=IBGE_FULL_REFRESH_DAYS)
        if have_rows and not ctx.force and recent and state.get("release") == release.signature:
            log.info("[%s] SIDRA table 74 unchanged (latest year %s); nothing to pull", self.key, release.latest_year)
            return
        last_year = max(today().year, release.latest_year)
        url = sidra_url(IBGE_FIRST_YEAR, last_year)
        title = (f"IBGE SIDRA tabela 74 (PPM), Mel de abelha: produção (kg) e valor (Mil Reais), Brasil e UFs, "
                 f"{IBGE_FIRST_YEAR}-{last_year}")
        doc = ctx.fetch(url, headers=JSON_HEADERS, accept_status=(200, 400), store=False)
        if doc.status_code == 400:
            raise CollectorError(f"IBGE SIDRA rejected the honey query (HTTP 400: {doc.text.strip()[:200]!r}); "
                                 "nothing stored")
        raw_id, unchanged = ctx.store_raw(url, doc.content, doc.content_type, title=title)
        if unchanged and have_rows and not ctx.force:
            log.info("[%s] same SIDRA answer as already stored", self.key)
        else:
            parsed = parse_sidra(doc.content, first_year=IBGE_FIRST_YEAR, last_year=last_year)
            for p in parsed.problems:
                ctx.warn(p)
            if not any(r.level == IBGE_LEVEL_BRAZIL and r.value is not None for r in parsed.rows):
                raise CollectorError(f"IBGE SIDRA returned no national honey figure for {IBGE_FIRST_YEAR}-{last_year}; "
                                     "nothing stored")
            for msg in check_sidra_totals(parsed):
                ctx.warn(msg)
            self._store(ctx, state, parsed, url, raw_id)
        state.update({
            "release": release.signature, "latest_year": release.latest_year,
            "pulled_at": utcnow().isoformat(timespec="seconds"), "query": url,
        })
        _save_state(ctx, state)
        ctx.checkpoint()

    def _probe(self, ctx: CollectContext) -> SidraRelease:
        doc = ctx.fetch(SIDRA_PROBE_URL, headers=JSON_HEADERS, accept_status=(200, 400), store=False)
        if doc.status_code == 400:
            raise CollectorError(f"IBGE SIDRA rejected the release check (HTTP 400: {doc.text.strip()[:200]!r})")
        return parse_sidra_probe(doc.content)

    def _store(self, ctx: CollectContext, state: dict, parsed: SidraParse, url: str, raw_id: int) -> None:
        skipped = 0
        for r in parsed.rows:
            if r.value is None:
                skipped += 1
                continue
            spec = IBGE_VARIABLES[r.variable]
            national = r.level == IBGE_LEVEL_BRAZIL
            extra: dict[str, Any] = {
                "sidra_table": IBGE_TABLE, "survey": IBGE_SURVEY,
                "variable_code": r.variable, "variable": r.variable_name,
                "classification": IBGE_CLASSIFICATION, "category_code": IBGE_HONEY_CATEGORY, "category": IBGE_HONEY_NAME,
                "territorial_level": r.level_name, "locality_code": r.loc_code, "locality": r.loc_name,
                "value_as_published": r.raw, "unit_as_published": r.unit_name, "unit_code": r.unit_code,
                "web_table": SIDRA_TABLE_PAGE,
            }
            if r.raw == SIDRA_ZERO:
                extra["symbol"] = f"'-' = {SIDRA_SYMBOLS[SIDRA_ZERO]} (IBGE convention)"
            if national:
                loc, place = "BRA", "Brazil"
                metric = spec["metric"]
            else:
                abbr_name = BR_STATES.get(r.loc_code)
                if abbr_name is None or _norm(abbr_name[1]) != _norm(r.loc_name):
                    _warn_once(ctx, state, f"state:{r.loc_code}:{r.loc_name}",
                               f"IBGE SIDRA: state {r.loc_code} {r.loc_name!r} is not in Paladex's list of the 27 "
                               "federative units; stored under its published name")
                    abbr_name = None
                abbr = abbr_name[0] if abbr_name else None
                loc, place = f"BR-{abbr or r.loc_code}", r.loc_name
                metric = spec["region_metric"]
                extra.update({"region": r.loc_name, "region_code": r.loc_code, "region_abbr": abbr,
                              "macro_region": BR_MACRO_REGIONS.get(r.loc_code[:1])})
            if r.variable == IBGE_VAR_QUANTITY:
                value, unit = round(r.value / 1000.0, 3), "t"
                extra["conversion"] = "kg / 1000 = t (exact)"
                what = (f"honey production, {place}: {r.raw} kg as published, stored in tonnes (kg / 1000, exact)")
            else:
                value, unit = r.value, "1000 BRL"
                what = (f"value of honey production, {place}: {r.raw} thousand reais as published "
                        "(current prices, nominal)")
            ps, pe = year_bounds(r.year)
            ctx.add_production(
                series_key=f"ibge_ppm|t{IBGE_TABLE}|{loc}|{metric}|{r.year}", country_iso3="BRA", metric=metric,
                value=value, unit=unit, period_start=ps, period_end=pe, period_label=str(r.year), frequency="A",
                data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, source_url=url,
                raw_document_id=raw_id or None, extra=extra,
                notes=f"IBGE {IBGE_SURVEY}, SIDRA table {IBGE_TABLE} '{IBGE_HONEY_NAME}': {what}.",
            )
        if skipped:
            ctx.warn(f"IBGE SIDRA: {skipped} cell(s) published without a value ('...', '..' or 'X') were not stored")


# ===========================================================================
# 2) Argentina: SAGyP RENAPA register (CKAN, CSV)
# ===========================================================================

RENAPA_PACKAGE_ID = "registro-nacional-de-productores-apicolas"
RENAPA_PACKAGE_URL = f"https://datos.magyp.gob.ar/api/3/action/package_show?id={RENAPA_PACKAGE_ID}"
RENAPA_DATASET_PAGE = f"https://datos.magyp.gob.ar/dataset/{RENAPA_PACKAGE_ID}"
# CKAN resource ids (stable across uploads; the file URL changes with each upload), with the
# name fragment used as a fallback when an id changes.
RENAPA_PROVINCE_RESOURCE = ("fcf61106-a82c-4ce7-9997-a7f0f40345b5", "por provincia")
RENAPA_DEPARTMENT_RESOURCE = ("68c49b26-6953-4656-8a32-dae497315e11", "por departamento")
RENAPA_PROVINCE_COLUMNS = ("provincia", "productores", "apiarios", "colmenas")
RENAPA_DEPARTMENT_COLUMNS = ("fecha_actualizacion", "provincia", "departamento", "apiarios", "colmenas")
RENAPA_MIN_PROVINCES = 15            # a sane extract lists most of the 24 jurisdictions


@dataclass(frozen=True)
class CkanResource:
    id: str
    name: str
    url: str
    format: str
    last_modified: datetime | None

    @property
    def signature(self) -> str:
        return f"{self.id}|{self.url}|{self.last_modified.isoformat() if self.last_modified else ''}"


@dataclass(frozen=True)
class RenapaPackage:
    title: str
    license: str | None
    metadata_modified: str | None
    province: CkanResource
    department: CkanResource


def _pick_resource(resources: list[dict], rid: str, fragment: str) -> CkanResource | None:
    def build(r: dict) -> CkanResource:
        return CkanResource(id=str(r.get("id") or ""), name=str(r.get("name") or ""), url=str(r.get("url") or ""),
                            format=str(r.get("format") or ""), last_modified=_parse_iso_datetime(r.get("last_modified")))
    for r in resources:
        if isinstance(r, dict) and str(r.get("id") or "").endswith(rid):
            return build(r)
    for r in resources:
        if (isinstance(r, dict) and fragment in _norm(r.get("name")) and _norm(r.get("format")) == "csv"
                and str(r.get("url") or "").startswith("http")):
            return build(r)
    return None


def parse_renapa_package(content: bytes) -> RenapaPackage:
    """The two RENAPA CSV resources of the CKAN `package_show` answer. Fails loudly when the
    package or one of the files is missing."""
    doc = _load_json(content, "RENAPA (CKAN package_show)")
    if not isinstance(doc, dict) or doc.get("success") is not True or not isinstance(doc.get("result"), dict):
        raise CollectorError(f"RENAPA: CKAN did not return the package ({str(doc)[:200]!r})")
    pkg = doc["result"]
    resources = pkg.get("resources") if isinstance(pkg.get("resources"), list) else []
    prov = _pick_resource(resources, *RENAPA_PROVINCE_RESOURCE)
    dept = _pick_resource(resources, *RENAPA_DEPARTMENT_RESOURCE)
    if prov is None or dept is None:
        names = [r.get("name") for r in resources if isinstance(r, dict)]
        raise CollectorError(f"RENAPA schema drift: the 'por provincia' and 'por departamento' CSV files are no longer "
                             f"both in the package (resources: {names}); nothing stored")
    for res in (prov, dept):
        if not res.url.startswith("http"):
            raise CollectorError(f"RENAPA: resource {res.name!r} has no download URL; nothing stored")
    return RenapaPackage(title=str(pkg.get("title") or ""), license=pkg.get("license_title") or pkg.get("license_id"),
                         metadata_modified=pkg.get("metadata_modified"), province=prov, department=dept)


def _csv_rows(content: bytes, required: tuple[str, ...], what: str) -> tuple[list[str], list[dict[str, str]]]:
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text))
    header = [(h or "").strip() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in header]
    if missing:
        raise CollectorError(f"RENAPA schema drift: {what} has no column {missing} (columns: {header}); nothing stored")
    rows = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(row.values()):
            continue                                    # blank line
        rows.append(row)
    if not rows:
        raise CollectorError(f"RENAPA: {what} has no data rows; nothing stored")
    return header, rows


def _count(value: str, what: str) -> int:
    if not re.fullmatch(r"\d+", value or ""):
        raise CollectorError(f"RENAPA: {what} is {value!r}, not a whole number; nothing stored "
                             "(a register total cannot be built from an unreadable row)")
    return int(value)


@dataclass(frozen=True)
class RenapaProvince:
    code: str | None
    name: str
    producers: int
    apiaries: int
    hives: int


def parse_renapa_provinces(content: bytes) -> list[RenapaProvince]:
    """Rows of the "Productores, apiarios y colmenas - por provincia" CSV."""
    header, rows = _csv_rows(content, RENAPA_PROVINCE_COLUMNS, "the 'por provincia' file")
    id_col = next((h for h in header if re.fullmatch(r"provi\w*_id", h)), None)    # 'provincia_id' (docs: 'provinicia_id')
    out = []
    for i, r in enumerate(rows, start=2):
        name = r["provincia"]
        if not name:
            raise CollectorError(f"RENAPA: line {i} of the 'por provincia' file has no province name; nothing stored")
        out.append(RenapaProvince(
            code=(r.get(id_col) or None) if id_col else None, name=name,
            producers=_count(r["productores"], f"'productores' of {name}"),
            apiaries=_count(r["apiarios"], f"'apiarios' of {name}"),
            hives=_count(r["colmenas"], f"'colmenas' of {name}"),
        ))
    if len({p.name for p in out}) != len(out):
        raise CollectorError("RENAPA: a province appears twice in the 'por provincia' file; nothing stored")
    if len(out) < RENAPA_MIN_PROVINCES:
        raise CollectorError(f"RENAPA: the 'por provincia' file lists only {len(out)} provinces; nothing stored")
    return out


@dataclass(frozen=True)
class RenapaDepartments:
    updated: date               # fecha_actualizacion: the day of the register snapshot
    rows: int
    apiaries: int
    hives: int


def parse_renapa_departments(content: bytes) -> RenapaDepartments:
    """Totals and update date of the "Apiarios y colmenas - por departamento" CSV."""
    _header, rows = _csv_rows(content, RENAPA_DEPARTMENT_COLUMNS, "the 'por departamento' file")
    dates = {r["fecha_actualizacion"] for r in rows}
    if len(dates) != 1:
        raise CollectorError(f"RENAPA: the 'por departamento' file has {len(dates)} update dates "
                             f"({sorted(dates)[:5]}); not a single snapshot, nothing stored")
    raw_date = dates.pop()
    try:
        updated = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise CollectorError(f"RENAPA: unreadable fecha_actualizacion {raw_date!r}; nothing stored") from exc
    apiaries = sum(_count(r["apiarios"], f"'apiarios' of {r['departamento']} ({r['provincia']})") for r in rows)
    hives = sum(_count(r["colmenas"], f"'colmenas' of {r['departamento']} ({r['provincia']})") for r in rows)
    return RenapaDepartments(updated=updated, rows=len(rows), apiaries=apiaries, hives=hives)


class ArMagypHivesCollector(Collector):
    key = "ar_magyp_hives"
    name = "Argentina – SAGyP RENAPA: alveari registrati (registro nazionale dei produttori apistici)"
    publisher = "Secretaría de Agricultura, Ganadería y Pesca (SAGyP) – Coordinación Apícola, RENAPA"
    homepage = RENAPA_DATASET_PAGE
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "ARG"
    language = "es"
    expected_update = "Irregolare: estratti del registro RENAPA pubblicati alcune volte l'anno; controllo mensile"
    expected_update_en = "Irregular: RENAPA register extracts published a few times a year; checked monthly"
    expected_max_age_days = 400
    terms_note = (
        "Fuente: SAGyP – Coordinación Apícola, Registro Nacional de Productores Apícolas (RENAPA), "
        "datos.magyp.gob.ar, licence CC BY 4.0 (attribution). Hives REGISTERED in an administrative register "
        "(a snapshot on the stated day), not a survey of hives in production. No national total row is "
        "published: the value is the sum of the provincial rows, stored only when the provincial and "
        "departmental files give the same total. Argentina publishes no honey production series as data."
    )
    # Monthly: one ~9 KB metadata request; the files only when a new extract is published.
    schedule = {"trigger": "cron", "day": 11, "hour": 7, "minute": 25}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        meta = ctx.fetch(RENAPA_PACKAGE_URL, headers=JSON_HEADERS, store=False)
        pkg = parse_renapa_package(meta.content)
        signature = f"{pkg.province.signature}||{pkg.department.signature}"
        have_rows = _has_rows(ctx)
        if have_rows and not ctx.force and state.get("signature") == signature:
            log.info("[%s] RENAPA extract unchanged (%s)", self.key, pkg.province.last_modified)
            return
        prov_doc = ctx.fetch(pkg.province.url, title=f"RENAPA – {pkg.province.name} ({pkg.province.url.rsplit('/', 1)[-1]})",
                             published_at=pkg.province.last_modified.date() if pkg.province.last_modified else None)
        dept_doc = ctx.fetch(pkg.department.url,
                             title=f"RENAPA – {pkg.department.name} ({pkg.department.url.rsplit('/', 1)[-1]})",
                             published_at=pkg.department.last_modified.date() if pkg.department.last_modified else None)
        if prov_doc.unchanged and dept_doc.unchanged and have_rows and not ctx.force:
            log.info("[%s] RENAPA files identical to the ones already stored", self.key)
        else:
            provinces = parse_renapa_provinces(prov_doc.content)
            depts = parse_renapa_departments(dept_doc.content)
            self._store(ctx, pkg, provinces, depts, prov_doc.raw_document_id, dept_doc.raw_document_id)
        state.update({"signature": signature, "province_url": pkg.province.url, "department_url": pkg.department.url,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, pkg: RenapaPackage, provinces: list[RenapaProvince],
               depts: RenapaDepartments, prov_raw: int, dept_raw: int) -> None:
        hives = sum(p.hives for p in provinces)
        apiaries = sum(p.apiaries for p in provinces)
        producers = sum(p.producers for p in provinces)
        if (hives, apiaries) != (depts.hives, depts.apiaries):
            raise CollectorError(
                f"RENAPA: the two files of the extract disagree (por provincia: {hives:,} hives / {apiaries:,} apiaries; "
                f"por departamento: {depts.hives:,} / {depts.apiaries:,}); no national total stored")
        snap = depts.updated
        published = pkg.province.last_modified.date() if pkg.province.last_modified else None
        extra = {
            "register": "RENAPA – Registro Nacional de Productores Apícolas", "snapshot_date": snap.isoformat(),
            "producers": producers, "apiaries": apiaries, "hives": hives,
            "total_method": (f"sum of the {len(provinces)} rows of the 'por provincia' file (no national total is "
                             f"published); the 'por departamento' file ({depts.rows} rows) gives the same totals"),
            "provinces": [{"code": p.code, "name": p.name, "producers": p.producers, "apiaries": p.apiaries,
                           "hives": p.hives} for p in sorted(provinces, key=lambda p: -p.hives)],
            "province_basis": "province of the producer's registered domicile (RENAPA 'por provincia' file)",
            "department_file": {"url": pkg.department.url, "rows": depts.rows, "apiaries": depts.apiaries,
                                "hives": depts.hives, "raw_document_id": dept_raw or None,
                                "last_modified": pkg.department.last_modified.isoformat() if pkg.department.last_modified else None},
            "ckan_package": RENAPA_PACKAGE_URL, "ckan_resource_ids": [pkg.province.id, pkg.department.id],
            "dataset_page": RENAPA_DATASET_PAGE, "license": pkg.license,
        }
        ctx.add_production(
            series_key=f"renapa|ARG|colonies|{snap.isoformat()}", country_iso3="ARG", metric="colonies",
            value=float(hives), unit="number", period_start=snap, period_end=snap, period_label=snap.isoformat(),
            frequency="irregular", data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL,
            published_at=published, source_url=pkg.province.url, raw_document_id=prov_raw or None, extra=extra,
            notes=(f"SAGyP RENAPA register on {snap.isoformat()}: {hives:,} registered hives ({producers:,} producers, "
                   f"{apiaries:,} apiaries). Sum of the provincial rows (no national total is published); the "
                   "departmental file gives the same total. Registered hives, not a survey count."),
        )


# ===========================================================================
# 3) Chile: ODEPA "Cifras apícolas nacionales" (SAG SIPEC Apícola register), PDF table
# ===========================================================================

ODEPA_APICULTURA_URL = "https://www.odepa.gob.cl/rubros/apicultura"
# The article series on the ministry's apiculture page (first edition: "...-sipec-2025", 19 Oct 2026).
ODEPA_ARTICLE_RE = re.compile(r"https://www\.odepa\.gob\.cl/publicaciones/articulos/cifras-apicolas-nacionales[a-z0-9-]*")
ODEPA_PDF_RE = re.compile(r"https://bibliotecadigital\.odepa\.gob\.cl/bitstreams/[0-9a-f-]{36}/download")
ODEPA_HIVES_TABLE = re.compile(r"^tabla \d+\. numero de colmenas por region\b")
ODEPA_BEEKEEPERS_TABLE = re.compile(r"^tabla \d+\. numero de apicultores por region\b")
ODEPA_TOTAL_ROW = "total nacional"
ODEPA_MIN_REGIONS = 10               # Chile has 16 regions
ODEPA_REFRESH_DAYS = 180             # re-read the article and its PDF at least this often
ODEPA_DECLARATION_MONTH = 10         # FRADA: hives are declared every October
_CL_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})*")          # Chilean thousands separator: 1.084.923
_SPANISH_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
                   "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def find_odepa_articles(html: str) -> list[str]:
    """URLs of the "Cifras apícolas nacionales" articles listed on the apiculture page (page order,
    newest first on the live page), each once."""
    out: list[str] = []
    for m in ODEPA_ARTICLE_RE.finditer(html):
        url = m.group(0).rstrip("/")
        if url not in out:
            out.append(url)
    return out


def pick_odepa_article(urls: list[str]) -> str:
    """The newest edition: the highest year in the URL (".../cifras-apicolas-nacionales-sipec-2025"),
    else the first one listed."""
    def year(u: str) -> int:
        found = re.findall(r"(?<!\d)(20\d\d)(?!\d)", u)
        return int(found[-1]) if found else 0
    return max(urls, key=lambda u: (year(u), -urls.index(u)))


@dataclass(frozen=True)
class OdepaArticle:
    url: str
    title: str
    published: date | None
    pdf_url: str


def parse_odepa_article(html: str, url: str) -> OdepaArticle:
    """Title, publication date (``article:published_time``, else the page's <time datetime>, else
    "Fecha de publicación: 19 octubre, 2026") and the link to the full article (PDF)."""
    pdfs = ODEPA_PDF_RE.findall(html)
    if not pdfs:
        raise CollectorError(f"ODEPA: no link to the full article (bibliotecadigital bitstream) on {url}; "
                             "page changed? nothing stored")
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, flags=re.S) or re.search(r"<title>(.*?)</title>", html, flags=re.S)
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    title = title.replace("&#8211;", "–").replace("&amp;", "&")
    published = None
    for pattern in (r'<meta property="article:published_time" content="(\d{4}-\d{2}-\d{2})',
                    r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})'):
        found = re.search(pattern, html)
        if found:
            published = date.fromisoformat(found.group(1))
            break
    if published is None:
        found = re.search(r"Fecha de publicaci[oó]n:\s*(\d{1,2})\s+([A-Za-zé]+),?\s+(\d{4})", html)
        if found and _norm(found.group(2)) in _SPANISH_MONTHS:
            published = date(int(found.group(3)), _SPANISH_MONTHS[_norm(found.group(2))], int(found.group(1)))
    return OdepaArticle(url=url, title=title or url, published=published, pdf_url=pdfs[0])


def pdf_pages_text(content: bytes) -> list[str]:
    """The text layer of every page of a PDF (pdfplumber)."""
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many types on a broken file
        raise CollectorError(f"ODEPA: the article PDF cannot be read ({type(exc).__name__}: {exc}); nothing stored") from exc


@dataclass
class OdepaTable:
    title: str
    years: list[int]
    total: list[int]                                   # the published "Total nacional" row
    regions: dict[str, list[int]] = field(default_factory=dict)       # complete rows only
    incomplete: list[str] = field(default_factory=list)               # rows with blank cells (not placeable)

    def region_sums(self) -> list[int] | None:
        if self.incomplete or not self.regions:
            return None
        return [sum(v[i] for v in self.regions.values()) for i in range(len(self.years))]


def _cl_int(token: str) -> int:
    return int(token.replace(".", ""))


def parse_odepa_table(lines: list[str], title_re: re.Pattern, what: str) -> OdepaTable:
    """A "Tabla N. Número de ... por región, período YYYY-YYYY" table from the text layer:
    the title line, a "Región YYYY YYYY ..." header, one line per region (name, then one number per
    year) and the "Total nacional" row. Fails loudly unless the title, a header of consecutive years
    and a complete total row are found. A region line with fewer numbers than years (blank cells)
    cannot be placed column by column from the text and is listed in `incomplete`, never guessed."""
    start = next((i for i, line in enumerate(lines) if title_re.search(_norm(line))), None)
    if start is None:
        raise CollectorError(f"ODEPA schema drift: no table of {what} by region in the article PDF; nothing stored")
    title = lines[start].strip()
    header_idx = next((i for i in range(start + 1, min(start + 4, len(lines)))
                       if re.fullmatch(r"region(\s+\d{4})+", _norm(lines[i]))), None)
    if header_idx is None:
        raise CollectorError(f"ODEPA schema drift: the {what} table has no 'Región YYYY ...' header; nothing stored")
    years = [int(y) for y in _norm(lines[header_idx]).split()[1:]]
    if years != list(range(years[0], years[0] + len(years))):
        raise CollectorError(f"ODEPA schema drift: the {what} table's years {years} are not consecutive; nothing stored")
    table = OdepaTable(title=title, years=years, total=[])
    for line in lines[header_idx + 1:]:
        tokens = line.split()
        nums: list[str] = []
        while tokens and _CL_NUMBER.fullmatch(tokens[-1]):
            nums.insert(0, tokens.pop())
        name = " ".join(tokens).strip()
        if _norm(name) == ODEPA_TOTAL_ROW:
            if len(nums) != len(years):
                raise CollectorError(f"ODEPA: the {what} 'Total nacional' row has {len(nums)} values for "
                                     f"{len(years)} years; nothing stored")
            table.total = [_cl_int(n) for n in nums]
            break
        if not name or not nums or _norm(name).startswith(("fuente", "tabla", "grafico")):
            raise CollectorError(f"ODEPA schema drift: unexpected line {line!r} inside the {what} table; nothing stored")
        if len(nums) == len(years):
            table.regions[name] = [_cl_int(n) for n in nums]
        else:
            table.incomplete.append(name)
    if not table.total:
        raise CollectorError(f"ODEPA schema drift: the {what} table has no 'Total nacional' row; nothing stored")
    if len(table.regions) + len(table.incomplete) < ODEPA_MIN_REGIONS:
        raise CollectorError(f"ODEPA: the {what} table lists only {len(table.regions) + len(table.incomplete)} "
                             "regions; nothing stored")
    return table


class ClOdepaHivesCollector(Collector):
    key = "cl_odepa_hives"
    name = "Cile – ODEPA con registro SAG (SIPEC Apícola): alveari dichiarati, totale nazionale per anno"
    publisher = "ODEPA – Oficina de Estudios y Políticas Agrarias (Ministerio de Agricultura), dati SIPEC Apícola del SAG"
    homepage = ODEPA_APICULTURA_URL
    kind = SourceKind.PDF
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "CHL"
    language = "es"
    expected_update = "Articolo ODEPA «Cifras apícolas nacionales» (1ª edizione ott. 2026); dichiarazioni di ottobre; controllo mensile"
    expected_update_en = "ODEPA article «Cifras apícolas nacionales» (1st edition Oct 2026); October declarations; checked monthly"
    expected_max_age_days = 450
    terms_note = (
        "Fuente: Odepa, 'Cifras apícolas nacionales desde los registros administrativos del SIPEC' (with SAG's SIPEC "
        "Apícola register), Table 'Número de colmenas por región'. Free government publication. Hives DECLARED each "
        "October by active registered beekeepers (FRADA), cleaned by Odepa for 2019 onward; Odepa notes the register "
        "may not cover the whole sector. Read from the PDF table: only the published 'Total nacional' row is stored "
        "as data (the regional rows are kept with it). Chile publishes no official honey production series."
    )
    # Monthly: one request to the apiculture page; the article and its PDF only for a new edition.
    schedule = {"trigger": "cron", "day": 13, "hour": 7, "minute": 50}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        page = ctx.fetch(ODEPA_APICULTURA_URL, store=False)
        articles = find_odepa_articles(page.text)
        have_rows = _has_rows(ctx)
        if not articles:
            if have_rows:
                _warn_once(ctx, state, "no_article_listed",
                           "ODEPA: no 'Cifras apícolas nacionales' article is listed on the apiculture page any more; "
                           "the hive figures already stored are kept")
                _save_state(ctx, state)
                ctx.checkpoint()
                return
            raise CollectorError("ODEPA: no 'Cifras apícolas nacionales' article on the apiculture page (page changed?); "
                                 "nothing stored")
        article_url = pick_odepa_article(articles)
        pulled_at = _parse_iso_datetime(state.get("pulled_at"))
        recent = pulled_at is not None and utcnow() - pulled_at < timedelta(days=ODEPA_REFRESH_DAYS)
        if have_rows and not ctx.force and recent and state.get("article_url") == article_url:
            log.info("[%s] ODEPA article unchanged (%s)", self.key, article_url)
            return
        art_doc = ctx.fetch(article_url, store=False)
        article = parse_odepa_article(art_doc.text, article_url)
        pdf = ctx.fetch(article.pdf_url, title=f"Odepa – {article.title}", published_at=article.published)
        if pdf.unchanged and have_rows and not ctx.force:
            log.info("[%s] ODEPA article PDF identical to the one already stored", self.key)
        else:
            lines = [line.strip() for text in pdf_pages_text(pdf.content) for line in text.splitlines() if line.strip()]
            hives = parse_odepa_table(lines, ODEPA_HIVES_TABLE, "hives (colmenas)")
            try:
                beekeepers: OdepaTable | None = parse_odepa_table(lines, ODEPA_BEEKEEPERS_TABLE, "beekeepers (apicultores)")
            except CollectorError as exc:
                ctx.warn(f"{exc} (beekeeper totals not kept; hive figures unaffected)")
                beekeepers = None
            self._store(ctx, state, article, hives, beekeepers, pdf.raw_document_id)
        state.update({"article_url": article_url, "pdf_url": article.pdf_url,
                      "published": article.published.isoformat() if article.published else None,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, state: dict, article: OdepaArticle, hives: OdepaTable,
               beekeepers: OdepaTable | None, raw_id: int) -> None:
        # Properties of the published table, not parsing problems: reported once per edition.
        if hives.incomplete:
            _warn_once(ctx, state, f"incomplete:{article.pdf_url}",
                       f"ODEPA: region row(s) {hives.incomplete} of '{hives.title}' have blank cells that cannot be "
                       "placed from the text; the regional detail is not kept (national totals unaffected)")
        sums = hives.region_sums()
        if sums is not None:
            off = [f"{y}: regions {s:,} vs total {t:,}" for y, s, t in zip(hives.years, sums, hives.total) if s != t]
            if off:
                _warn_once(ctx, state, f"sums:{article.pdf_url}",
                           f"ODEPA: in '{hives.title}' the regions do not add up to the published 'Total nacional' "
                           f"({'; '.join(off)}); the published total is stored as is")
        bk_total = dict(zip(beekeepers.years, beekeepers.total)) if beekeepers else {}
        if article.published is None:
            ctx.warn(f"ODEPA: no publication date on {article.url}; rows are stored without one")
        for i, year in enumerate(hives.years):
            regions = {name: values[i] for name, values in hives.regions.items()} if not hives.incomplete else None
            start, end = month_bounds(year, ODEPA_DECLARATION_MONTH)
            extra = {
                "table": hives.title, "article": article.title, "article_url": article.url, "pdf_url": article.pdf_url,
                "row": "Total nacional", "value_as_published": f"{hives.total[i]:,}".replace(",", "."),
                "declaration": "FRADA declarations of October (SAG SIPEC Apícola), active registered beekeepers",
                "regions": regions, "regions_sum": sums[i] if sums else None,
                "beekeepers_total": bk_total.get(year),
                "caveat": ("Odepa: figures from the SIPEC Apícola register in force; they do not necessarily cover the "
                           "whole sector"),
            }
            ctx.add_production(
                series_key=f"odepa_sipec|CHL|colonies|{year}", country_iso3="CHL", metric="colonies",
                value=float(hives.total[i]), unit="number", period_start=start, period_end=end,
                period_label=str(year), frequency="A", data_status=DataStatus.PUBLISHED,
                reliability=Reliability.OFFICIAL, published_at=article.published, source_url=article.pdf_url,
                raw_document_id=raw_id or None, extra=extra,
                notes=(f"Odepa with SAG SIPEC Apícola data: {hives.total[i]:,} hives declared in October {year} by "
                       f"active registered beekeepers ('Total nacional' of '{hives.title}'). Registered hives, not a "
                       "survey count."),
            )


# ===========================================================================
# 4) Canada: Statistics Canada, table 32-10-0353-01 (Web Data Service)
# ===========================================================================

STATCAN_WDS = "https://www150.statcan.gc.ca/t1/wds/rest"
STATCAN_METADATA_URL = f"{STATCAN_WDS}/getCubeMetadata"
STATCAN_DATA_URL = f"{STATCAN_WDS}/getDataFromCubePidCoordAndLatestNPeriods"
STATCAN_PRODUCT_ID = 32100353
STATCAN_TABLE = "32-10-0353-01"
STATCAN_TABLE_TITLE = "Production and value of honey"
STATCAN_TABLE_PAGE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035301"
STATCAN_FIRST_YEAR = 2015            # first year kept (the table goes back to 1924)
STATCAN_FULL_REFRESH_DAYS = 90       # re-read the data at least this often (silent corrections)
STATCAN_MAX_COORDINATES = 300        # WDS limit per request
LB_IN_KG = 0.45359237                # the international pound, exact by definition

# Estimates kept: Paladex key -> (member name as published, unit-of-measure code, unit name).
# Unit codes from WDS getCodeSets (checked 5 Nov 2026): 223 Number, 254 Pounds, 81 Dollars.
STATCAN_ESTIMATES: dict[str, tuple[str, int, str]] = {
    "beekeepers": ("Beekeepers", 223, "Number"),
    "colonies": ("Colonies", 223, "Number"),
    "production": ("Production of natural honey, total", 254, "Pounds"),
    "value": ("Value of natural honey, total", 81, "Dollars"),
}
# Paladex metrics per estimate: (Canada, province). Beekeepers are kept in `extra` of the colony rows.
STATCAN_METRICS = {"production": ("production", "production_by_region"),
                   "value": ("production_value", "production_value_by_region"),
                   "colonies": ("colonies", "colonies_by_region")}
STATCAN_SCALARS = {0: "units", 1: "tens", 2: "hundreds", 3: "thousands", 4: "tens of thousands",
                   5: "hundreds of thousands", 6: "millions", 7: "tens of millions", 8: "hundreds of millions",
                   9: "billions"}
# WDS code sets: symbols (1 preliminary, 3 revised) and statuses ('..' etc. carry no value).
STATCAN_SYMBOLS = {0: None, 1: "p", 3: "r"}
STATCAN_STATUSES = {0: None, 1: "..", 2: "0s", 3: "A", 4: "B", 5: "C", 6: "D", 7: "E", 8: "F", 9: "...", 10: "<LOD"}
STATCAN_NO_VALUE = {1, 8, 9}         # not available, too unreliable to be published, not applicable
# Statistics Canada geography (SGC province code) -> (ISO 3166-2 suffix, English name).
CA_PROVINCES: dict[str, tuple[str, str]] = {
    "10": ("NL", "Newfoundland and Labrador"), "11": ("PE", "Prince Edward Island"), "12": ("NS", "Nova Scotia"),
    "13": ("NB", "New Brunswick"), "24": ("QC", "Quebec"), "35": ("ON", "Ontario"), "46": ("MB", "Manitoba"),
    "47": ("SK", "Saskatchewan"), "48": ("AB", "Alberta"), "59": ("BC", "British Columbia"), "60": ("YT", "Yukon"),
    "61": ("NT", "Northwest Territories"), "62": ("NU", "Nunavut"),
}


@dataclass(frozen=True)
class StatcanMember:
    member_id: int
    name: str
    code: str | None            # classificationCode (SGC code for a geography)
    geo_level: int | None
    uom_code: int | None
    terminated: bool


@dataclass(frozen=True)
class StatcanCube:
    release_time: str
    start_year: int
    end_year: int
    geos: dict[int, StatcanMember]                      # member id -> geography
    estimates: dict[str, StatcanMember]                 # Paladex key -> estimate member
    footnotes: dict[tuple[int, int], list[str]]         # (dimension, member id; 0 = every member) -> notes
    corrections: list[str]
    survey_codes: list[str]

    @property
    def national_id(self) -> int:
        return next(m.member_id for m in self.geos.values() if m.geo_level == 0)

    @property
    def signature(self) -> str:
        return f"{self.end_year}|{self.release_time}|{len(self.corrections)}"

    @property
    def terminated(self) -> list[str]:
        return [k for k, m in self.estimates.items() if m.terminated]

    def notes_for(self, geo_id: int, member_id: int) -> list[str]:
        out: list[str] = []
        for key in ((1, 0), (1, geo_id), (2, 0), (2, member_id)):
            for note in self.footnotes.get(key, []):
                if note not in out:
                    out.append(note)
        return out


def _year_of(value: Any) -> int | None:
    m = re.fullmatch(r"(\d{4})-01-01", str(value or ""))
    return int(m.group(1)) if m else None


def parse_statcan_metadata(content: bytes) -> StatcanCube:
    """The getCubeMetadata answer for table 32-10-0353-01. Fails loudly (CollectorError) when the
    table, its two dimensions, a kept estimate or its unit of measure changed."""
    doc = _load_json(content, "Statistics Canada getCubeMetadata")
    if not isinstance(doc, list) or not doc or not isinstance(doc[0], dict):
        raise CollectorError(f"Statistics Canada: unexpected getCubeMetadata answer {str(doc)[:200]!r}")
    first = doc[0]
    obj = first.get("object")
    if first.get("status") != "SUCCESS" or not isinstance(obj, dict):
        raise CollectorError(f"Statistics Canada: getCubeMetadata did not succeed ({str(first)[:200]!r})")
    if str(obj.get("productId")) != str(STATCAN_PRODUCT_ID) or _norm(obj.get("cubeTitleEn")) != _norm(STATCAN_TABLE_TITLE):
        raise CollectorError(f"Statistics Canada schema drift: table {obj.get('productId')} is "
                             f"{obj.get('cubeTitleEn')!r}, expected {STATCAN_PRODUCT_ID} {STATCAN_TABLE_TITLE!r}")
    dims = {d.get("dimensionPositionId"): d for d in obj.get("dimension") or [] if isinstance(d, dict)}
    if (set(dims) != {1, 2} or _norm(dims[1].get("dimensionNameEn")) != "geography"
            or _norm(dims[2].get("dimensionNameEn")) != "estimates"):
        raise CollectorError("Statistics Canada schema drift: the table's dimensions are "
                             f"{[(k, d.get('dimensionNameEn')) for k, d in sorted(dims.items())]}, expected "
                             "1 Geography and 2 Estimates; nothing stored")

    def members(dim: dict) -> list[StatcanMember]:
        out = []
        for m in dim.get("member") or []:
            if not isinstance(m, dict) or not isinstance(m.get("memberId"), int):
                continue
            out.append(StatcanMember(
                member_id=m["memberId"], name=str(m.get("memberNameEn") or "").strip(),
                code=str(m["classificationCode"]) if m.get("classificationCode") is not None else None,
                geo_level=m.get("geoLevel"), uom_code=m.get("memberUomCode"), terminated=bool(m.get("terminated")),
            ))
        return out

    geos = {m.member_id: m for m in members(dims[1])}
    national = [m for m in geos.values() if m.geo_level == 0]
    if len(national) != 1 or _norm(national[0].name) != "canada":
        raise CollectorError(f"Statistics Canada schema drift: no single 'Canada' member at geographic level 0 "
                             f"({[m.name for m in national]}); nothing stored")
    by_name = {_norm(m.name): m for m in members(dims[2])}
    estimates: dict[str, StatcanMember] = {}
    for key, (name, uom, unit) in STATCAN_ESTIMATES.items():
        m = by_name.get(_norm(name))
        if m is None:
            raise CollectorError(f"Statistics Canada schema drift: no estimate {name!r} in table {STATCAN_TABLE} "
                                 f"(estimates: {[x.name for x in by_name.values()]}); nothing stored")
        if m.uom_code != uom:
            raise CollectorError(f"Statistics Canada unit drift: {name!r} has unit code {m.uom_code}, expected {uom} "
                                 f"({unit}); nothing stored")
        estimates[key] = m
    start, end = _year_of(obj.get("cubeStartDate")), _year_of(obj.get("cubeEndDate"))
    if start is None or end is None:
        raise CollectorError(f"Statistics Canada schema drift: the table is not annual (start {obj.get('cubeStartDate')!r}, "
                             f"end {obj.get('cubeEndDate')!r}); nothing stored")
    footnotes: dict[tuple[int, int], list[str]] = {}
    for f in obj.get("footnote") or []:
        link = f.get("link") if isinstance(f, dict) else None
        if isinstance(link, dict) and f.get("footnotesEn"):
            footnotes.setdefault((link.get("dimensionPositionId"), link.get("memberId")), []).append(str(f["footnotesEn"]).strip())
    corrections = [f"{c.get('correctionDate')}: {c.get('correctionNoteEn')}" for c in obj.get("correction") or []
                   if isinstance(c, dict)]
    return StatcanCube(release_time=str(obj.get("releaseTime") or ""), start_year=start, end_year=end, geos=geos,
                       estimates=estimates, footnotes=footnotes, corrections=corrections,
                       survey_codes=[str(s) for s in obj.get("surveyCode") or []])


def statcan_request_body(cube: StatcanCube, first_year: int = STATCAN_FIRST_YEAR) -> list[dict]:
    """One coordinate per geography and kept estimate ("geo.estimate.0.0.0.0.0.0.0.0"), each with
    the latest N annual periods so that the first one is `first_year`."""
    latest_n = max(1, cube.end_year - first_year + 1)
    members = sorted(m.member_id for m in cube.estimates.values())
    body = [{"productId": STATCAN_PRODUCT_ID, "coordinate": f"{g}.{e}.0.0.0.0.0.0.0.0", "latestN": latest_n}
            for g in sorted(cube.geos) for e in members]
    if len(body) > STATCAN_MAX_COORDINATES:
        raise CollectorError(f"Statistics Canada: {len(body)} coordinates exceed the WDS limit of "
                             f"{STATCAN_MAX_COORDINATES} per request (table grew?)")
    return body


@dataclass(frozen=True)
class StatcanPoint:
    geo_id: int
    member_id: int
    estimate: str               # Paladex key (STATCAN_ESTIMATES)
    year: int
    raw: float | None           # the number as published, before the scalar factor
    scalar_code: int
    symbol: str | None          # "p" preliminary, "r" revised
    status: str | None          # ".." etc., or a quality letter
    release: datetime | None
    vector_id: int | None
    coordinate: str

    @property
    def value(self) -> float | None:
        """In the base unit (number, pounds, dollars)."""
        return None if self.raw is None else self.raw * 10 ** self.scalar_code

    @property
    def flag(self) -> str | None:
        return " ".join(x for x in (self.symbol, self.status) if x) or None


def parse_statcan_data(content: bytes, cube: StatcanCube) -> tuple[list[StatcanPoint], list[str]]:
    """Points of a getDataFromCubePidCoordAndLatestNPeriods answer, and problems (a coordinate the
    WDS refused, an unknown code). Fails loudly when the answer is not the requested table, a
    coordinate is not one Paladex asked for, or a period is not a year."""
    doc = _load_json(content, "Statistics Canada getDataFromCubePidCoordAndLatestNPeriods")
    if not isinstance(doc, list) or not doc:
        raise CollectorError(f"Statistics Canada: unexpected data answer {str(doc)[:200]!r}; nothing stored")
    key_of = {m.member_id: k for k, m in cube.estimates.items()}
    points: list[StatcanPoint] = []
    problems: list[str] = []
    for item in doc:
        obj = item.get("object") if isinstance(item, dict) else None
        if not isinstance(obj, dict):
            raise CollectorError(f"Statistics Canada: unexpected element {str(item)[:200]!r} in the data answer")
        coord = str(obj.get("coordinate") or "")
        if item.get("status") != "SUCCESS":
            problems.append(f"Statistics Canada: coordinate {coord or '?'} was refused ({item.get('status')}, "
                            f"responseStatusCode {obj.get('responseStatusCode')}); skipped")
            continue
        if str(obj.get("productId")) != str(STATCAN_PRODUCT_ID):
            raise CollectorError(f"Statistics Canada: data for table {obj.get('productId')}, not {STATCAN_PRODUCT_ID}")
        parts = coord.split(".")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise CollectorError(f"Statistics Canada schema drift: unreadable coordinate {coord!r}; nothing stored")
        geo_id, member_id = int(parts[0]), int(parts[1])
        if geo_id not in cube.geos or member_id not in key_of or any(p != "0" for p in parts[2:]):
            raise CollectorError(f"Statistics Canada: coordinate {coord} is not one Paladex asked for; nothing stored")
        for p in obj.get("vectorDataPoint") or []:
            year = _year_of(p.get("refPer"))
            if year is None:
                raise CollectorError(f"Statistics Canada schema drift: period {p.get('refPer')!r} of {coord} is not a "
                                     "year; nothing stored")
            symbol_code, status_code = p.get("symbolCode") or 0, p.get("statusCode") or 0
            scalar = p.get("scalarFactorCode") or 0
            value = p.get("value")
            if symbol_code not in STATCAN_SYMBOLS or status_code not in STATCAN_STATUSES or scalar not in STATCAN_SCALARS:
                problems.append(f"Statistics Canada: unknown symbol/status/scalar code {symbol_code}/{status_code}/"
                                f"{scalar} for {coord} {year}; kept with the raw codes")
            if status_code in STATCAN_NO_VALUE or value is None:
                raw = None
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                raw = float(value)
            else:
                problems.append(f"Statistics Canada: unreadable value {value!r} for {coord} {year}; skipped")
                continue
            points.append(StatcanPoint(
                geo_id=geo_id, member_id=member_id, estimate=key_of[member_id], year=year, raw=raw,
                scalar_code=int(scalar), symbol=STATCAN_SYMBOLS.get(symbol_code, str(symbol_code) or None),
                status=STATCAN_STATUSES.get(status_code, str(status_code)),
                release=_parse_iso_datetime(p.get("releaseTime")), vector_id=obj.get("vectorId"), coordinate=coord,
            ))
    if not points:
        raise CollectorError(f"Statistics Canada returned no data point ({'; '.join(problems)[:300]}); nothing stored")
    return points, problems


def check_statcan_totals(points: list[StatcanPoint], cube: StatcanCube) -> list[str]:
    """Provinces against Canada, per estimate and year (warnings, never fixes). Each figure is
    rounded to its published scale, so a difference up to one unit of that scale per province is
    rounding."""
    msgs: list[str] = []
    national_id = cube.national_id
    groups: dict[tuple[str, int], list[StatcanPoint]] = {}
    for p in points:
        groups.setdefault((p.estimate, p.year), []).append(p)
    for (est, year), items in sorted(groups.items()):
        nat = next((p for p in items if p.geo_id == national_id), None)
        provs = [p for p in items if p.geo_id != national_id]
        if nat is None or nat.value is None or not provs or any(p.value is None for p in provs):
            continue
        total = sum(p.value for p in provs)
        tolerance = sum(10 ** p.scalar_code for p in provs)
        if abs(total - nat.value) > tolerance + 1e-6:
            msgs.append(f"Statistics Canada: {STATCAN_ESTIMATES[est][0]} {year}: the provinces add up to {total:,.0f}, "
                        f"Canada is {nat.value:,.0f}; both kept as published")
    return msgs


class CaStatcanHoneyCollector(Collector):
    key = "ca_statcan_honey"
    name = "Canada – Statistics Canada (tab. 32-10-0353-01): produzione, valore e alveari, Canada e province"
    name_en = "Canada – Statistics Canada (table 32-10-0353-01): honey production, value and colonies, Canada and provinces"
    publisher = "Statistics Canada (survey 3419, compiled from provincial apiculture data)"
    homepage = STATCAN_TABLE_PAGE
    kind = SourceKind.API
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "CAN"
    language = "en"
    expected_update = "Annuale (anno Y pubblicato a dicembre Y, rivisto nell'edizione successiva); controllo mensile"
    expected_update_en = "Annual (year Y released in December Y, revised in the next edition); checked monthly"
    expected_max_age_days = 400
    terms_note = (
        "Source: Statistics Canada, Table 32-10-0353-01 'Production and value of honey' (Statistics Canada Open "
        "Licence: reuse with attribution). Production is published in thousands of pounds and stored in tonnes "
        "(1 lb = 0.45359237 kg, exact; the published figure is kept with each row); value in thousands of Canadian "
        "dollars, as published, excluding inventory sales except in Quebec; colonies and beekeepers as published "
        "(may include pollination colonies). Canada excludes Newfoundland and Labrador. Canada and each province are "
        "separate rows (provinces under their own metrics), never summed. StatCan revises the previous year each "
        "December: every change is kept as a revision."
    )
    # Monthly; each run is one ~7 KB metadata request unless the table was re-released (mid-December).
    schedule = {"trigger": "cron", "day": 20, "hour": 6, "minute": 55}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        meta = ctx.fetch(STATCAN_METADATA_URL, method="POST", json_body=[{"productId": STATCAN_PRODUCT_ID}],
                         headers=JSON_HEADERS, store=False)
        cube = parse_statcan_metadata(meta.content)
        have_rows = _has_rows(ctx)
        pulled_at = _parse_iso_datetime(state.get("pulled_at"))
        recent = pulled_at is not None and utcnow() - pulled_at < timedelta(days=STATCAN_FULL_REFRESH_DAYS)
        if have_rows and not ctx.force and recent and state.get("release") == cube.signature:
            log.info("[%s] table %s unchanged (released %s)", self.key, STATCAN_TABLE, cube.release_time)
            return
        for key in cube.terminated:
            _warn_once(ctx, state, f"terminated:{key}",
                       f"Statistics Canada: the estimate {STATCAN_ESTIMATES[key][0]!r} is marked terminated "
                       "(no longer updated); its published years are still read")
        body = statcan_request_body(cube)
        release = _parse_iso_datetime(cube.release_time)
        doc = ctx.fetch(STATCAN_DATA_URL, method="POST", json_body=body, headers=JSON_HEADERS,
                        title=(f"Statistics Canada {STATCAN_TABLE} '{STATCAN_TABLE_TITLE}': {len(body)} coordinates, "
                               f"latest {body[0]['latestN']} years to {cube.end_year} (release {cube.release_time})"),
                        published_at=release.date() if release else None)
        if doc.unchanged and have_rows and not ctx.force:
            log.info("[%s] same WDS answer as already stored", self.key)
        else:
            points, problems = parse_statcan_data(doc.content, cube)
            for msg in problems:
                ctx.warn(msg)
            for msg in check_statcan_totals(points, cube):      # a property of the table: reported once
                _warn_once(ctx, state, f"totals:{msg}", msg)
            self._store(ctx, state, cube, points, doc.raw_document_id)
        state.update({"release": cube.signature, "end_year": cube.end_year, "release_time": cube.release_time,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, state: dict, cube: StatcanCube, points: list[StatcanPoint],
               raw_id: int) -> None:
        grouped: dict[tuple[int, int], dict[str, StatcanPoint]] = {}
        for p in points:
            if p.year >= STATCAN_FIRST_YEAR:
                grouped.setdefault((p.geo_id, p.year), {})[p.estimate] = p
        national_id = cube.national_id
        skipped = 0
        for (geo_id, year), by_est in sorted(grouped.items()):
            geo = cube.geos[geo_id]
            national = geo_id == national_id
            region: dict[str, Any] = {}
            if national:
                loc, place = "CAN", "Canada"
            else:
                prov = CA_PROVINCES.get(geo.code or "")
                if prov is None or _norm(prov[1]) != _norm(geo.name):
                    _warn_once(ctx, state, f"province:{geo.code}:{geo.name}",
                               f"Statistics Canada: geography {geo.code} {geo.name!r} is not in Paladex's list of "
                               "provinces; stored under its published name")
                    prov = None
                loc, place = f"CA-{prov[0] if prov else (geo.code or geo_id)}", geo.name
                region = {"region": geo.name, "region_code": geo.code, "region_abbr": prov[0] if prov else None}
            beekeepers = by_est.get("beekeepers")
            for est in ("production", "value", "colonies"):
                p = by_est.get(est)
                if p is None:
                    continue
                if p.value is None:
                    skipped += 1
                    continue
                name, _uom, unit_name = STATCAN_ESTIMATES[est]
                metric = STATCAN_METRICS[est][0 if national else 1]
                scale = STATCAN_SCALARS.get(p.scalar_code, f"10^{p.scalar_code}")
                extra: dict[str, Any] = {
                    "table": STATCAN_TABLE, "table_title": STATCAN_TABLE_TITLE, "product_id": STATCAN_PRODUCT_ID,
                    "estimate": name, "geography": geo.name, "value_as_published": p.raw, "scalar": scale,
                    "unit_as_published": unit_name, "vector_id": p.vector_id, "coordinate": p.coordinate,
                    "release_time": p.release.isoformat() if p.release else None,
                    "symbol": p.symbol, "status": p.status, "footnotes": cube.notes_for(geo_id, p.member_id),
                    "api": {"endpoint": STATCAN_DATA_URL, "method": "POST"}, "survey_codes": cube.survey_codes,
                    **region,
                }
                if est == "production":
                    pounds = p.value
                    value, unit = round(pounds * LB_IN_KG / 1000.0, 3), "t"
                    extra["conversion"] = "pounds x 0.45359237 / 1000 = t (international pound, exact)"
                    what = f"honey production, {place}: {p.raw:,.0f} {scale} of pounds as published, stored in tonnes"
                elif est == "value":
                    value, unit = round(p.value / 1000.0, 3), "1000 CAD"
                    what = f"value of honey production, {place}: {p.raw:,.0f} {scale} of dollars as published (nominal)"
                else:
                    value, unit = p.value, "number"
                    what = f"colonies, {place}: {p.raw:,.0f} as published"
                    if beekeepers is not None and beekeepers.value is not None:
                        extra["beekeepers"] = beekeepers.value
                        extra["beekeepers_flag"] = beekeepers.flag
                ps, pe = year_bounds(year)
                ctx.add_production(
                    series_key=f"statcan|{STATCAN_TABLE}|{loc}|{metric}|{year}", country_iso3="CAN", metric=metric,
                    value=value, unit=unit, period_start=ps, period_end=pe, period_label=str(year), frequency="A",
                    data_status=DataStatus.PROVISIONAL if p.symbol == "p" else DataStatus.PUBLISHED,
                    reliability=Reliability.OFFICIAL, published_at=p.release.date() if p.release else None,
                    source_url=STATCAN_TABLE_PAGE, raw_document_id=raw_id or None, flag_raw=p.flag, extra=extra,
                    notes=f"Statistics Canada table {STATCAN_TABLE} '{STATCAN_TABLE_TITLE}': {what}.",
                )
        if skipped:
            ctx.warn(f"Statistics Canada: {skipped} cell(s) published without a value ('..', 'F' or '...') were not stored")


# ===========================================================================
# 5) Mexico: SIAP, "Cierre de la producción pecuaria" (xajax query service)
# ===========================================================================

SIAP_CIERRE_URL = "https://nube.agricultura.gob.mx/cierre_pecuario/"
SIAP_CLASSIFICATION = "1000101"      # the page's hidden 'idclasificacion'
SIAP_HONEY_CODE = "1910080"          # "Miel" in the 'Otros productos' list (1910090 is "Cera", wax)
SIAP_HONEY_NAME = "Miel"
SIAP_REPORT_TITLE = "Producción, precio y valor"
SIAP_FIRST_YEAR = 2015               # first year kept (the service goes back to 1980)
SIAP_FULL_REFRESH_DAYS = 90          # re-read every year at least this often (revisions of earlier years)
SIAP_MIN_STATES = 25                 # Mexico has 32 federal entities
SIAP_HEADERS = ("estado", "produccion (toneladas)", "precio (pesos por kilogramo)",
                "valor de la produccion (miles de pesos)")
# SIAP state names -> (ISO 3166-2:MX suffix, INEGI code).
MX_STATES: dict[str, tuple[str, str]] = {
    "Aguascalientes": ("AGU", "01"), "Baja California": ("BCN", "02"), "Baja California Sur": ("BCS", "03"),
    "Campeche": ("CAM", "04"), "Coahuila": ("COA", "05"), "Colima": ("COL", "06"), "Chiapas": ("CHP", "07"),
    "Chihuahua": ("CHH", "08"), "Ciudad de México": ("CMX", "09"), "Durango": ("DUR", "10"),
    "Guanajuato": ("GUA", "11"), "Guerrero": ("GRO", "12"), "Hidalgo": ("HID", "13"), "Jalisco": ("JAL", "14"),
    "México": ("MEX", "15"), "Michoacán": ("MIC", "16"), "Morelos": ("MOR", "17"), "Nayarit": ("NAY", "18"),
    "Nuevo León": ("NLE", "19"), "Oaxaca": ("OAX", "20"), "Puebla": ("PUE", "21"), "Querétaro": ("QUE", "22"),
    "Quintana Roo": ("ROO", "23"), "San Luis Potosí": ("SLP", "24"), "Sinaloa": ("SIN", "25"),
    "Sonora": ("SON", "26"), "Tabasco": ("TAB", "27"), "Tamaulipas": ("TAM", "28"), "Tlaxcala": ("TLA", "29"),
    "Veracruz": ("VER", "30"), "Yucatán": ("YUC", "31"), "Zacatecas": ("ZAC", "32"),
}
_MX_STATE_KEYS = {_norm(k): (k, v) for k, v in MX_STATES.items()}
_MX_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")


def siap_xajax_url(function: str, *args: Any) -> str:
    """A call of the page's xajax service as a GET URL (the service answers GET and POST alike;
    live check 5 Nov 2026: same bytes)."""
    return SIAP_CIERRE_URL + "?" + urlencode([("xajax", function), *(("xajaxargs[]", str(a)) for a in args)])


SIAP_YEARS_URL = siap_xajax_url("llenaAnio", "aniopec")


def siap_report_url(year: int) -> str:
    """The honey report, national level, exactly as the page's `reporte()` asks for it: year,
    species (no such field on the page, so the browser sends "undefined"), state, district,
    municipality, report type, classification, live animals, carcasses, other products (Miel),
    title."""
    return siap_xajax_url("reporte2", year, "undefined", 0, 0, 0, 0, SIAP_CLASSIFICATION, 0, 0, SIAP_HONEY_CODE,
                          SIAP_HONEY_NAME)


def _xajax_html(content: bytes, target: str, what: str) -> str:
    """The HTML an xajax answer assigns to element `target` (CDATA of `<cmd n="as" t=target>`)."""
    m = re.match(rb'<\?xml[^>]*encoding="([^"]+)"', content)
    try:
        text = content.decode(m.group(1).decode("ascii") if m else "iso-8859-1")
    except (LookupError, UnicodeDecodeError):
        text = content.decode("iso-8859-1")
    found = re.search(r'<cmd n="as" t="%s" p="innerHTML"><!\[CDATA\[(.*?)\]\]></cmd>' % re.escape(target), text, re.S)
    if not found:
        raise CollectorError(f"SIAP: the answer to {what} has no '{target}' content (service changed?); starts with "
                             f"{text[:150]!r}")
    return found.group(1)


def parse_siap_years(content: bytes) -> list[int]:
    """Years offered by the service (the `llenaAnio` answer)."""
    html_part = _xajax_html(content, "aniopec", "the year list")
    years = sorted({int(y) for y in re.findall(r'<option value="(\d{4})"', html_part)})
    if not years:
        raise CollectorError("SIAP: the year list is empty (service changed?); nothing stored")
    return years


@dataclass(frozen=True)
class SiapRow:
    name: str
    production_t: float | None
    price_mxn_kg: float | None
    value_kmxn: float | None
    raw: tuple[str, str, str]   # the three cells as published


@dataclass
class SiapReport:
    year: int
    states: list[SiapRow]
    total: SiapRow
    source_note: str | None
    problems: list[str] = field(default_factory=list)


def _mx_number(cell: str) -> float | None:
    s = cell.strip()
    return float(s.replace(",", "")) if _MX_NUMBER.fullmatch(s) else None


def parse_siap_report(content: bytes, year: int) -> SiapReport:
    """The "Miel – Producción, precio y valor" table of one year: one row per state and the
    "Total" row. Fails loudly (CollectorError) on another product, report or year, changed column
    headers or units, a missing or incomplete total row, too few states, a state listed twice."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_xajax_html(content, "Resultado", f"the honey report {year}"), "html.parser")
    titles = [_norm(d.get_text(" ", strip=True)) for d in soup.select("div.textoTablaTitulo")]
    if _norm(SIAP_HONEY_NAME) not in titles or _norm(SIAP_REPORT_TITLE) not in titles:
        raise CollectorError(f"SIAP: the report is {titles[:3]}, not '{SIAP_HONEY_NAME} – {SIAP_REPORT_TITLE}' "
                             "(product codes changed?); nothing stored")
    if str(year) not in titles:
        raise CollectorError(f"SIAP: asked for {year}, the report is for {[t for t in titles if t.isdigit()]}; nothing stored")
    table = soup.find("table", id="Resultados-reporte")
    rows = table.find_all("tr") if table else []
    if not rows:
        raise CollectorError(f"SIAP: no result table in the honey report {year}; nothing stored")
    header = [_norm(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
    if tuple(header) != SIAP_HEADERS:
        raise CollectorError(f"SIAP schema drift: the {year} columns are {header}, expected {list(SIAP_HEADERS)}; "
                             "nothing stored")
    states: list[SiapRow] = []
    total: SiapRow | None = None
    problems: list[str] = []
    for tr in rows[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if not cells:
            continue
        if len(cells) != 4:
            raise CollectorError(f"SIAP schema drift: row {cells} of the {year} table does not have 4 cells; nothing stored")
        name, raw = cells[0], (cells[1], cells[2], cells[3])
        nums = [_mx_number(c) for c in raw]
        row = SiapRow(name=name, production_t=nums[0], price_mxn_kg=nums[1], value_kmxn=nums[2], raw=raw)
        if _norm(name) == "total":
            if any(n is None for n in nums):
                raise CollectorError(f"SIAP: the {year} 'Total' row is incomplete ({list(raw)}); nothing stored")
            total = row
            continue
        for label, n, r in zip(("production", "price", "value"), nums, raw):
            if n is None:
                problems.append(f"SIAP {year}: unreadable {label} {r!r} for {name}; not stored")
        states.append(row)
    if total is None:
        raise CollectorError(f"SIAP: the {year} table has no 'Total' row; nothing stored")
    if len({_norm(s.name) for s in states}) != len(states):
        raise CollectorError(f"SIAP: a state appears twice in the {year} table; nothing stored")
    if len(states) < SIAP_MIN_STATES:
        raise CollectorError(f"SIAP: the {year} table lists only {len(states)} states; nothing stored")
    note = soup.find(string=re.compile(r"Fuente:"))
    return SiapReport(year=year, states=states, total=total, problems=problems,
                      source_note=re.sub(r"\s+", " ", str(note)).strip() if note else None)


def check_siap_report(report: SiapReport) -> list[str]:
    """States against the total, and the total price against value / production (warnings only).
    Published to the kg and the thousand-peso unit with three decimals, so the sums are exact up
    to float noise; the price is published with two decimals."""
    msgs: list[str] = []
    t = report.total
    for label, attr in (("production (t)", "production_t"), ("value (thousand MXN)", "value_kmxn")):
        vals = [getattr(s, attr) for s in report.states]
        if any(v is None for v in vals):
            continue
        total = sum(vals)
        if abs(total - getattr(t, attr)) > 0.001 * len(vals):
            msgs.append(f"SIAP {report.year}: the states add up to {total:,.3f} {label}, the published total is "
                        f"{getattr(t, attr):,.3f}; both kept as published")
    if t.production_t and abs(t.value_kmxn / t.production_t - t.price_mxn_kg) > 0.006:   # (1000 MXN / t = MXN / kg)
        msgs.append(f"SIAP {report.year}: the national price {t.price_mxn_kg} MXN/kg differs from value / production "
                    f"({t.value_kmxn / t.production_t:.4f}); kept as published")
    return msgs


class MxSiapHoneyCollector(Collector):
    key = "mx_siap_honey"
    name = "Messico – SIAP (chiusura della produzione zootecnica): miele, produzione, prezzo e valore, Messico e stati"
    name_en = "Mexico – SIAP (livestock production year-end close): honey production, price and value, Mexico and states"
    publisher = "SIAP – Servicio de Información Agroalimentaria y Pesquera (Secretaría de Agricultura y Desarrollo Rural)"
    homepage = SIAP_CIERRE_URL
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "MEX"
    language = "es"
    expected_update = "Annuale (chiusura SIAP dell'anno Y pubblicata nel corso di Y+1); controllo mensile"
    expected_update_en = "Annual (SIAP year-end close for year Y published during Y+1); checked monthly"
    expected_max_age_days = 450
    terms_note = (
        "Fuente: SADER – Servicio de Información Agroalimentaria y Pesquera (SIAP), 'Cierre de la producción pecuaria', "
        "product 'Miel', report 'Producción, precio y valor' (free government data, cite the source). Production in "
        "tonnes and value in thousand pesos, as published; the price (pesos per kg) is the average price paid to "
        "producers and is stored as a PRODUCER price, national average only (state prices are kept with the state "
        "rows). Mexico and each state are separate rows (states under their own metrics), never summed. The service "
        "gives no publication date. SIAP revises earlier years: every change is kept as a revision."
    )
    # Monthly: the year list (~2 KB) and the latest year's report (~8 KB); every year only when that
    # report changes or every SIAP_FULL_REFRESH_DAYS.
    schedule = {"trigger": "cron", "day": 16, "hour": 7, "minute": 35}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        years = [y for y in parse_siap_years(ctx.fetch(SIAP_YEARS_URL, store=False).content) if y >= SIAP_FIRST_YEAR]
        if not years:
            raise CollectorError(f"SIAP: no year from {SIAP_FIRST_YEAR} on in the year list; nothing stored")
        latest = max(years)
        docs = {latest: ctx.fetch(siap_report_url(latest), title=self._title(latest))}
        signature = f"{latest}|{hashlib.sha256(docs[latest].content).hexdigest()[:16]}"
        have_rows = _has_rows(ctx)
        pulled_at = _parse_iso_datetime(state.get("pulled_at"))
        recent = pulled_at is not None and utcnow() - pulled_at < timedelta(days=SIAP_FULL_REFRESH_DAYS)
        if have_rows and not ctx.force and recent and state.get("release") == signature:
            log.info("[%s] SIAP honey report unchanged (latest year %s)", self.key, latest)
            return
        stored = 0
        for year in sorted(years, reverse=True):
            url = siap_report_url(year)
            doc = docs.get(year) or ctx.fetch(url, title=self._title(year))
            if doc.unchanged and have_rows and not ctx.force:
                continue                                   # the same answer was stored on an earlier run
            try:
                report = parse_siap_report(doc.content, year)
            except CollectorError as exc:
                if year == latest:
                    raise
                ctx.warn(f"{exc} (year {year} skipped; the other years are stored)")
                continue
            for msg in report.problems:
                ctx.warn(msg)
            for msg in check_siap_report(report):               # a property of the table: reported once
                _warn_once(ctx, state, f"totals:{msg}", msg)
            self._store(ctx, state, report, url, doc.raw_document_id)
            ctx.checkpoint()
            stored += 1
        log.info("[%s] %d year(s) parsed", self.key, stored)
        state.update({"release": signature, "latest_year": latest, "years": years,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    @staticmethod
    def _title(year: int) -> str:
        return f"SIAP – Cierre de la producción pecuaria: {SIAP_HONEY_NAME}, {SIAP_REPORT_TITLE}, {year}"

    def _store(self, ctx: CollectContext, state: dict, report: SiapReport, url: str, raw_id: int) -> None:
        year = report.year
        ps, pe = year_bounds(year)
        common: dict[str, Any] = dict(
            period_start=ps, period_end=pe, period_label=str(year), frequency="A", data_status=DataStatus.PUBLISHED,
            reliability=Reliability.OFFICIAL, source_url=url, raw_document_id=raw_id or None)
        base = {"service": "SIAP Cierre de la producción pecuaria (xajax 'reporte2')", "product": SIAP_HONEY_NAME,
                "product_code": SIAP_HONEY_CODE, "report": SIAP_REPORT_TITLE, "source_note": report.source_note,
                "web_page": SIAP_CIERRE_URL}
        t = report.total
        nat = {**base, "row": "Total", "production_as_published": t.raw[0], "price_as_published": t.raw[1],
               "value_as_published": t.raw[2], "price_mxn_per_kg": t.price_mxn_kg}
        ctx.add_production(
            series_key=f"siap|cierre|MEX|production|{year}", country_iso3="MEX", metric="production",
            value=t.production_t, unit="t", extra={**nat, "unit_as_published": "toneladas"},
            notes=f"SIAP year-end close, honey (Miel), Mexico 'Total': {t.raw[0]} t as published.", **common)
        ctx.add_production(
            series_key=f"siap|cierre|MEX|production_value|{year}", country_iso3="MEX", metric="production_value",
            value=t.value_kmxn, unit="1000 MXN", extra={**nat, "unit_as_published": "miles de pesos"},
            notes=f"SIAP year-end close, honey (Miel), Mexico 'Total': value {t.raw[2]} thousand pesos (nominal).",
            **common)
        ctx.add_price(
            series_key=f"siap|cierre|MEX|{year}", price_type=PriceType.PRODUCER, variety=Variety.UNSPECIFIED.value,
            variety_raw="Miel (SIAP, all floral sources)", price_value=t.price_mxn_kg, currency="MXN", unit="kg",
            origin_iso3="MEX", origin_label="México", market_iso3="MEX", market_location="Mexico (national average)",
            terms="producer price (average price paid to producers), annual national average",
            notes=(f"SIAP year-end close, honey: national average price {t.raw[1]} pesos per kg (weighted by production: "
                   "value / volume). Producer price, not an export or wholesale price."),
            extra={**nat, "unit_as_published": "pesos por kilogramo", "production_t": t.production_t,
                   "value_thousand_mxn": t.value_kmxn},
            **common)
        for s in report.states:
            known = _MX_STATE_KEYS.get(_norm(s.name))
            if known is None:
                _warn_once(ctx, state, f"state:{s.name}", f"SIAP: state {s.name!r} is not in Paladex's list of the 32 "
                           "federal entities; stored under its published name")
            iso = known[1][0] if known else re.sub(r"[^a-z0-9]+", "_", _norm(s.name)).upper()
            region = {**base, "region": s.name, "region_abbr": known[1][0] if known else None,
                      "region_code": known[1][1] if known else None, "production_as_published": s.raw[0],
                      "price_as_published": s.raw[1], "value_as_published": s.raw[2], "price_mxn_per_kg": s.price_mxn_kg}
            if s.production_t is not None:
                ctx.add_production(
                    series_key=f"siap|cierre|MX-{iso}|production_by_region|{year}", country_iso3="MEX",
                    metric="production_by_region", value=s.production_t, unit="t",
                    extra={**region, "unit_as_published": "toneladas"},
                    notes=f"SIAP year-end close, honey (Miel), {s.name}: {s.raw[0]} t as published.", **common)
            if s.value_kmxn is not None:
                ctx.add_production(
                    series_key=f"siap|cierre|MX-{iso}|production_value_by_region|{year}", country_iso3="MEX",
                    metric="production_value_by_region", value=s.value_kmxn, unit="1000 MXN",
                    extra={**region, "unit_as_published": "miles de pesos"},
                    notes=f"SIAP year-end close, honey (Miel), {s.name}: value {s.raw[2]} thousand pesos (nominal).",
                    **common)


# ===========================================================================
# 6) Turkey: TÜİK animal production statistics, "Arıcılık" table (data portal, XLS)
# ===========================================================================

TUIK_PORTAL = "https://veriportali.tuik.gov.tr"
TUIK_PRESS_LIST_URL = f"{TUIK_PORTAL}/api/tr/press"
TUIK_BULLETIN_TITLE = "Hayvansal Üretim İstatistikleri"
TUIK_TABLE_TITLE = "Arıcılık"
# The portal's JSON API answers 404 ("Sayfa bulunamadı") without the header its own web app sends.
TUIK_API_HEADERS = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
TUIK_FIRST_YEAR = 2015               # first year kept (the table goes back to 1991)
TUIK_REFRESH_DAYS = 180              # re-read the bulletin and its table at least this often


def tuik_press_url(press_id: str) -> str:
    return f"{TUIK_PORTAL}/api/tr/press/{press_id}"


def tuik_press_page(press_id: str) -> str:
    return f"{TUIK_PORTAL}/tr/press/{press_id}"


def _tr_norm(s: Any) -> str:
    """`_norm` that keeps the Turkish dotless i ("Arıcılık" -> "aricilik")."""
    return _norm(str(s or "").replace("ı", "i").replace("İ", "I"))


def parse_tuik_press_list(content: bytes) -> str:
    """Id of the latest "Hayvansal Üretim İstatistikleri" bulletin in the portal's press list
    (one entry per bulletin series, the latest issue)."""
    doc = _load_json(content, "TÜİK press list")
    items = doc.get("data") if isinstance(doc, dict) and doc.get("isError") is False else None
    if not isinstance(items, list):
        raise CollectorError(f"TÜİK: unexpected press list answer {str(doc)[:200]!r}")
    found = [str(i.get("id")) for i in items if isinstance(i, dict) and _tr_norm(i.get("title")) == _tr_norm(TUIK_BULLETIN_TITLE)]
    if len(found) != 1 or not found[0].isdigit():
        raise CollectorError(f"TÜİK: {len(found)} '{TUIK_BULLETIN_TITLE}' entries in the press list (expected 1); "
                             "portal changed? nothing stored")
    return found[0]


@dataclass(frozen=True)
class TuikBulletin:
    press_id: str
    title: str
    period: str
    published: date | None
    table_url: str
    table_category: str | None


def parse_tuik_press(content: bytes, press_id: str) -> TuikBulletin:
    """The bulletin: title, period, release date and the download URL of its "Arıcılık" table."""
    doc = _load_json(content, f"TÜİK bulletin {press_id}")
    data = doc.get("data") if isinstance(doc, dict) and doc.get("isError") is False else None
    if not isinstance(data, dict):
        raise CollectorError(f"TÜİK: unexpected bulletin answer {str(doc)[:200]!r}")
    if _tr_norm(data.get("title")) != _tr_norm(TUIK_BULLETIN_TITLE):
        raise CollectorError(f"TÜİK: bulletin {press_id} is {data.get('title')!r}, not '{TUIK_BULLETIN_TITLE}'")
    tables = [t for t in data.get("statisticalTables") or [] if isinstance(t, dict)
              and _tr_norm(t.get("title")) == _tr_norm(TUIK_TABLE_TITLE)]
    if len(tables) != 1 or not str(tables[0].get("url") or "").startswith("/api/"):
        raise CollectorError(f"TÜİK: bulletin {press_id} has {len(tables)} '{TUIK_TABLE_TITLE}' statistical tables "
                             "with a download link (expected 1); nothing stored")
    released = _parse_iso_datetime(data.get("date"))
    return TuikBulletin(press_id=press_id, title=str(data.get("title")), period=str(data.get("period") or ""),
                        published=released.date() if released else None,
                        table_url=TUIK_PORTAL + str(tables[0]["url"]), table_category=tables[0].get("category"))


@dataclass(frozen=True)
class TuikApicultureYear:
    year: int
    holdings: int | None        # agricultural holdings practising apiculture (from 2013)
    new_hives: int | None       # "Yeni kovan" (modern, movable-frame hives)
    old_hives: int | None       # "Eski kovan" (traditional hives)
    honey_t: float | None
    wax_t: float | None
    raw_honey: Any


@dataclass
class TuikApiculture:
    title: str
    sheet: str
    years: list[TuikApicultureYear]
    source_note: str | None


# Columns of the table: Paladex key -> (header fragment, unit fragment), compared with `_tr_norm`.
TUIK_COLUMNS = {"holdings": ("aricilik yapan tarimsal isletme sayisi", "adet"), "new_hives": ("yeni kovan", "adet"),
                "old_hives": ("eski kovan", "adet"), "honey": ("bal", "ton"), "wax": ("bal mumu", "ton")}


def parse_tuik_apiculture_xls(content: bytes) -> TuikApiculture:
    """The "Arıcılık / Apiculture (Türkiye)" sheet: one row per year with holdings, new and old
    hives, honey and wax (t). Fails loudly when a column, its unit or the year rows are missing."""
    try:
        import xlrd
    except ImportError as exc:      # pragma: no cover - xlrd is in requirements.txt
        raise CollectorError("TÜİK: reading the .xls table needs the 'xlrd' package (requirements.txt); "
                             "run the launcher to install it") from exc
    try:
        book = xlrd.open_workbook(file_contents=content)
    except Exception as exc:  # noqa: BLE001 - xlrd raises several types on a broken file
        raise CollectorError(f"TÜİK: the '{TUIK_TABLE_TITLE}' table is not a readable .xls ({exc}); nothing stored") from exc
    sheet = book.sheet_by_index(0)
    rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    head = next((i for i, r in enumerate(rows) if r and _tr_norm(r[0]).startswith("yil")), None)
    if head is None or _tr_norm(rows[0][0] if rows[0] else "") != _tr_norm(TUIK_TABLE_TITLE):
        raise CollectorError(f"TÜİK schema drift: no '{TUIK_TABLE_TITLE}' title or 'Yıl' header in the table; nothing stored")
    header = [_tr_norm(c) for c in rows[head]]
    units_row = next((r for r in rows[head + 1:head + 4] if any("(ton" in _tr_norm(c) for c in r)), None)
    if units_row is None:
        raise CollectorError("TÜİK schema drift: no units row under the header; nothing stored")
    cols: dict[str, int] = {}
    for key, (label, unit) in TUIK_COLUMNS.items():
        idx = next((i for i, h in enumerate(header) if h == label or (key == "holdings" and h.startswith(label))), None)
        if idx is None or unit not in _tr_norm(units_row[idx]):
            raise CollectorError(f"TÜİK schema drift: column {label!r} with unit {unit!r} not found (header {header}, "
                                 f"units {[str(u) for u in units_row]}); nothing stored")
        cols[key] = idx

    def num(cell: Any) -> float | None:
        return float(cell) if isinstance(cell, (int, float)) and math.isfinite(cell) else None

    def count(cell: Any) -> int | None:
        v = num(cell)
        return int(round(v)) if v is not None else None

    years: list[TuikApicultureYear] = []
    source_note = None
    for r in rows[head + 1:]:
        y = num(r[0]) if r else None
        if y is None or not (1900 < y < 2100) or y != int(y):
            if years and r and str(r[0]).strip():
                source_note = source_note or str(r[0]).strip()
            continue
        years.append(TuikApicultureYear(
            year=int(y), holdings=count(r[cols["holdings"]]), new_hives=count(r[cols["new_hives"]]),
            old_hives=count(r[cols["old_hives"]]), honey_t=num(r[cols["honey"]]), wax_t=num(r[cols["wax"]]),
            raw_honey=r[cols["honey"]],
        ))
    if not years or len({y.year for y in years}) != len(years):
        raise CollectorError("TÜİK: the table has no year rows, or a year twice; nothing stored")
    return TuikApiculture(title=str(rows[0][0]).strip(), sheet=sheet.name, years=years, source_note=source_note)


class TrTuikHoneyCollector(Collector):
    key = "tr_tuik_honey"
    name = "Turchia – TÜİK (statistiche della produzione animale): produzione di miele e alveari, totale nazionale"
    name_en = "Turkey – TÜİK (animal production statistics): honey production and beehives, national total"
    publisher = "TÜİK – Türkiye İstatistik Kurumu (Turkish Statistical Institute), from Ministry of Agriculture records"
    homepage = TUIK_PORTAL
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "TUR"
    language = "tr"
    expected_update = "Annuale (bollettino TÜİK di febbraio sull'anno precedente); controllo mensile"
    expected_update_en = "Annual (TÜİK bulletin each February on the previous year); checked monthly"
    expected_max_age_days = 400
    terms_note = (
        "Kaynak: TÜİK, 'Hayvansal Üretim İstatistikleri' bulletin, statistical table 'Arıcılık' (free, cite TÜİK; "
        "compiled from the Ministry of Agriculture and Forestry's administrative records). Honey in tonnes as "
        "published. Hives: TÜİK publishes new (modern) and old (traditional) hives separately; the colonies figure is "
        "their sum, with both parts kept. Year-end counts. TÜİK states that these data are not revised."
    )
    # Monthly: one ~24 KB request to the press list; the bulletin and its table only for a new issue.
    schedule = {"trigger": "cron", "day": 18, "hour": 8, "minute": 10}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        listing = ctx.fetch(TUIK_PRESS_LIST_URL, headers=TUIK_API_HEADERS, store=False)
        press_id = parse_tuik_press_list(listing.content)
        have_rows = _has_rows(ctx)
        pulled_at = _parse_iso_datetime(state.get("pulled_at"))
        recent = pulled_at is not None and utcnow() - pulled_at < timedelta(days=TUIK_REFRESH_DAYS)
        if have_rows and not ctx.force and recent and state.get("press_id") == press_id:
            log.info("[%s] TÜİK bulletin unchanged (press %s)", self.key, press_id)
            return
        bulletin = parse_tuik_press(ctx.fetch(tuik_press_url(press_id), headers=TUIK_API_HEADERS, store=False).content,
                                    press_id)
        xls = ctx.fetch(bulletin.table_url, title=f"TÜİK – {bulletin.title}, {bulletin.period}: {TUIK_TABLE_TITLE} (xls)",
                        published_at=bulletin.published)
        if xls.unchanged and have_rows and not ctx.force:
            log.info("[%s] TÜİK table identical to the one already stored", self.key)
        else:
            self._store(ctx, bulletin, parse_tuik_apiculture_xls(xls.content), xls.raw_document_id)
        state.update({"press_id": press_id, "period": bulletin.period, "table_url": bulletin.table_url,
                      "published": bulletin.published.isoformat() if bulletin.published else None,
                      "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, bulletin: TuikBulletin, table: TuikApiculture, raw_id: int) -> None:
        if bulletin.published is None:
            ctx.warn(f"TÜİK: no release date in bulletin {bulletin.press_id}; rows are stored without one")
        base = {"bulletin": f"{bulletin.title}, {bulletin.period}", "bulletin_url": tuik_press_page(bulletin.press_id),
                "press_id": bulletin.press_id, "table": TUIK_TABLE_TITLE, "table_title": table.title,
                "sheet": table.sheet, "source_note": table.source_note}
        for y in table.years:
            if y.year < TUIK_FIRST_YEAR:
                continue
            ps, pe = year_bounds(y.year)
            common: dict[str, Any] = dict(
                country_iso3="TUR", period_start=ps, period_end=pe, period_label=str(y.year), frequency="A",
                data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, published_at=bulletin.published,
                source_url=bulletin.table_url, raw_document_id=raw_id or None)
            detail = {"holdings": y.holdings, "new_hives": y.new_hives, "old_hives": y.old_hives, "wax_t": y.wax_t}
            if y.honey_t is not None:
                ctx.add_production(
                    series_key=f"tuik|aricilik|TUR|production|{y.year}", metric="production",
                    value=round(y.honey_t, 3), unit="t",
                    extra={**base, **detail, "column": "Bal / Honey", "value_as_published": y.raw_honey,
                           "unit_as_published": "ton"},
                    notes=f"TÜİK '{TUIK_TABLE_TITLE}' table: honey (bal) {y.honey_t:,.3f} t in {y.year}.", **common)
            if y.new_hives is not None and y.old_hives is not None:
                hives = y.new_hives + y.old_hives
                ctx.add_production(
                    series_key=f"tuik|aricilik|TUR|colonies|{y.year}", metric="colonies", value=float(hives),
                    unit="number",
                    extra={**base, **detail, "total_method": ("new hives + old hives (Yeni kovan + Eski kovan); TÜİK "
                                                              "publishes the two columns, not a total")},
                    notes=(f"TÜİK '{TUIK_TABLE_TITLE}' table: {y.new_hives:,} new + {y.old_hives:,} old hives = "
                           f"{hives:,} hives at the end of {y.year}."),
                    **common)


__all__ = [
    "BR_STATES",
    "CA_PROVINCES",
    "IBGE_FIRST_YEAR",
    "MX_STATES",
    "RENAPA_PACKAGE_URL",
    "SIAP_YEARS_URL",
    "SIDRA_PROBE_URL",
    "STATCAN_DATA_URL",
    "STATCAN_METADATA_URL",
    "TUIK_PRESS_LIST_URL",
    "ArMagypHivesCollector",
    "BrIbgeHoneyCollector",
    "CaStatcanHoneyCollector",
    "CkanResource",
    "ClOdepaHivesCollector",
    "MxSiapHoneyCollector",
    "OdepaArticle",
    "OdepaTable",
    "SiapReport",
    "SiapRow",
    "SidraParse",
    "SidraRelease",
    "SidraRow",
    "StatcanCube",
    "StatcanPoint",
    "TrTuikHoneyCollector",
    "TuikApiculture",
    "TuikBulletin",
    "check_siap_report",
    "check_sidra_totals",
    "check_statcan_totals",
    "find_odepa_articles",
    "parse_odepa_article",
    "parse_odepa_table",
    "parse_renapa_departments",
    "parse_renapa_package",
    "parse_renapa_provinces",
    "parse_siap_report",
    "parse_siap_years",
    "parse_sidra",
    "parse_sidra_probe",
    "parse_statcan_data",
    "parse_statcan_metadata",
    "parse_tuik_apiculture_xls",
    "parse_tuik_press",
    "parse_tuik_press_list",
    "pdf_pages_text",
    "pick_odepa_article",
    "sidra_url",
    "siap_report_url",
    "statcan_request_body",
    "tuik_press_url",
]
