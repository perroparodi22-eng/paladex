"""Official national honey production and beehive statistics from South American agencies.

Research: docs/research/official_south_america.json. Everything here is checked against the live
sources (captures of 5 Nov 2026 in ``tests/fixtures/production_official/real_*``).

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
"""
from __future__ import annotations

import copy
import csv
import io
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..enums import DataStatus, Reliability, SourceKind
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


__all__ = [
    "BR_STATES",
    "IBGE_FIRST_YEAR",
    "RENAPA_PACKAGE_URL",
    "SIDRA_PROBE_URL",
    "ArMagypHivesCollector",
    "BrIbgeHoneyCollector",
    "CkanResource",
    "ClOdepaHivesCollector",
    "OdepaArticle",
    "OdepaTable",
    "SidraParse",
    "SidraRelease",
    "SidraRow",
    "check_sidra_totals",
    "find_odepa_articles",
    "parse_odepa_article",
    "parse_odepa_table",
    "parse_renapa_departments",
    "parse_renapa_package",
    "parse_renapa_provinces",
    "parse_sidra",
    "parse_sidra_probe",
    "pdf_pages_text",
    "pick_odepa_article",
    "sidra_url",
]
