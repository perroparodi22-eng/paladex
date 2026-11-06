"""Official national honey production statistics of European countries, read from each country's
own statistics office or ministry of agriculture.

FAOSTAT (``collectors/faostat.py``) publishes year Y about twelve months late and has gaps for several
EU producers (no 2024 for Greece, Hungary, Romania, Bulgaria, Poland, Portugal in the live database of
5 Nov 2026). The collectors here store the national figures as each country publishes them, beside
FAOSTAT and never merged with it. Every figure comes from the official publication itself (statistics
office or ministry), never from the press, aggregators or associations. Live checks of 5-6 Nov 2026;
the captures are in ``tests/fixtures/production_europe/`` (see the README there).

Collectors
----------
* ``es_mapa_honey``: Spain, MAPA (Ministerio de Agricultura, Pesca y Alimentación), S.G. de Análisis,
  Coordinación y Estadística, **Estadística de Miel y Cera** (a statistical operation of the Plan
  Estadístico Nacional 2025-2028, Implementing Regulation (EU) 2023/2745): one workbook per year
  (``mielycera-YY...xlsx``, 2015 as ``.xls``) listed on the statistic's page, with the provincial
  analysis of honey and wax production (tonnes) and of the number of hives, split by transhumant /
  stationary holdings ("colmenas movilistas / fijistas" until 2018: the footnote of 2019 marks the
  break of that split, not of the totals). 2025 (file of 24 Aug 2026): 29,349.594 t of honey (the
  "Indicadores económicos sector apícola 2025" PDF of Oct 2026 rounds it to 29.350 t), 2,751,777 hives.
* ``hu_ksh_honey``: Hungary, KSH (Központi Statisztikai Hivatal) STADAT table **19.1.1.34**
  "Production of milk, eggs, wool, feather and honey": honey production in tonnes (published rounded
  to the thousand tonnes), 2025 = 25,000 t (table updated 14 Oct 2026).
* ``bg_mzh_honey``: Bulgaria, MZH (Министерство на земеделието и храните), Agrostatistics department,
  annual bulletin **"Пчеларството в България през YYYY година"** (survey of beekeeping), PDF table 1:
  honey produced (t), bee colonies on 1 October, colonies harvested, holdings, average yield, for
  Bulgaria and its six NUTS 2 regions. 2025 (bulletin No 466, 27 Feb 2026): 9,649 t, 808,851 colonies.
* ``gr_elstat_honey``: Greece, ELSTAT (Ελληνική Στατιστική Αρχή), **Livestock Capital and Production**
  (SPK33), final results of the annual agricultural survey: table 7c (honey, tonnes) and table 4
  (beehives on 31 December, "local" and "European" hives) by region. Newest year 2024 (FAOSTAT stops at
  2023 for Greece): 25,595.792 t, 2,161,086 beehives.

What is stored (``ProductionStat``)
-----------------------------------
* National: metric ``production`` in **t** and ``colonies`` (``number``), annual, ``period_label`` the
  year. Regions use their own metrics ``production_by_region`` / ``colonies_by_region`` with the
  region in ``extra.region`` (and ``extra.region_code``) so that they are never read as the national
  figure. Regions are never summed into the national row: they are only checked against it (reported
  once per publication when they do not add up; the published total is kept).
* Every row: ``reliability`` official, ``data_status`` "published" (none of these publications marks a
  figure as provisional), the exact file or page in ``source_url`` (a URL a person can open), the
  archived answer in ``raw_document_id``, the value exactly as published in ``extra.value_as_published``
  and the publication date when the source gives one (see each section).

Not integrated (checked 5-6 Nov 2026)
-------------------------------------
* European Commission, DG AGRI: the "Honey market presentation" (January 2026, archived by
  ``ec_honey_market``) gives member-state production for 2023 and 2024 only, as a bar chart rounded to
  0.1 thousand t, with DE, DK and FR repeating 2021-22 figures: not newer than FAOSTAT and not a table.
  The Agri-food Data Portal API has no honey dataset (only the TAXUD import data already collected).
* Romania: INS (insse.ro), its TEMPO-Online database (statistici.insse.ro:8077, plain HTTP) and the
  ministry (madr.ro) reset every connection from the development network: not reachable, not checked.
* Italy: neither ISTAT nor ISMEA publishes a national honey production statistic; the 2025 national
  estimate (30,992 t) is the Osservatorio Nazionale Miele's survey, an association-run observatory, not
  an official statistic. The national beekeeping register (BDN, vetinfo.it) publishes its hive counts
  only in an interactive dashboard; dati.salute.gov.it answered 403 and dati.gov.it lists no apiary
  dataset.
* Germany: Destatis publishes no honey production statistic; the national figure is the Deutscher
  Imkerbund's survey; the BMEL statistics site (bmel-statistik.de, BLE) redirected to a maintenance
  page on 6 Nov 2026.
* France: FranceAgriMer's "Observatoire de la production de miel et de gelée royale" for 2025 (PDF of
  27 Aug 2026) is image-only (no text layer): figures cannot be read reliably without OCR.
* Poland: GUS publishes no honey statistic; the ministry-funded IO-PIB report "Stan pszczelarstwa w
  Polsce w 2025 roku" (inhort.pl) resets connections from the development network.
* Portugal: INE's agricultural statistics carry no national honey production indicator that could be
  found; DGAV publishes only the yearly hive-declaration notices, no results.
"""
from __future__ import annotations

import html as html_lib
import io
import logging
import math
import os
import re
import ssl
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from ..enums import DataStatus, Reliability, SourceKind
from ..models import utcnow
from .base import CollectContext, Collector, CollectorError, year_bounds
from .production_official import _has_rows, _load_state, _norm, _parse_iso_datetime, _save_state, _warn_once

log = logging.getLogger(__name__)


# ===========================================================================
# Shared helpers
# ===========================================================================


def _fold(s: Any) -> str:
    """Case- and space-insensitive key that keeps non-Latin letters (Cyrillic, Greek): `_norm` drops
    them. Accents are removed (NFKD) so "ΣΥΝΟΛΟ" and "Σύνολο" compare equal."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().casefold()


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _http_date(value: str | None) -> date | None:
    """A `Last-Modified` header as a date (None when absent or unreadable)."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, IndexError):
        return None


def _header(headers: dict[str, str], name: str) -> str | None:
    name = name.lower()
    return next((v for k, v in headers.items() if k.lower() == name), None)


def _refresh_due(state: dict, days: int) -> bool:
    pulled_at = _parse_iso_datetime(state.get("pulled_at"))
    return pulled_at is None or utcnow() - pulled_at >= timedelta(days=days)


def _workbook_rows(content: bytes, what: str) -> list[tuple[str, list[list[Any]]]]:
    """(sheet name, rows) of an .xlsx (openpyxl) or .xls (xlrd) workbook, told apart by its signature."""
    if content[:4] == b"PK\x03\x04":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - openpyxl/zipfile raise many types on a broken file
            raise CollectorError(f"{what}: the workbook cannot be read ({type(exc).__name__}: {exc}); nothing stored") from exc
        try:
            return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        finally:
            wb.close()
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=content)
        except Exception as exc:  # noqa: BLE001
            raise CollectorError(f"{what}: the .xls workbook cannot be read ({exc}); nothing stored") from exc
        return [(sh.name, [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]) for sh in book.sheets()]
    snippet = content[:80].decode("utf-8", errors="replace").strip()
    raise CollectorError(f"{what}: the download is not an Excel workbook (starts with {snippet!r}); nothing stored")


# ===========================================================================
# 1) Spain: MAPA, Estadística de Miel y Cera (one workbook per year)
# ===========================================================================

ES_PAGE_URL = "https://www.mapa.gob.es/es/estadistica/temas/estadisticas-agrarias/ganaderia/estadistica_de_miel_y_cera"
ES_FIRST_YEAR = 2015                 # first year kept (files go back to 2013)
ES_FULL_REFRESH_DAYS = 180           # re-read every year's file at least this often (in-place corrections)
ES_STATISTIC = "Estadística de Miel y Cera"
_ES_LINK = re.compile(r'href="([^"]*mielycera[^"]*?\.xlsx?)"', re.I)
_ES_PROD_TITLE = re.compile(r"analisis provincial de produccion \(toneladas\),\s*(\d{4})")
_ES_HIVE_TITLE = re.compile(r"analisis provincial del numero de colmenas,\s*(\d{4})")

# The 17 autonomous communities as labelled in every file 2013-2025 (`_norm`) -> (ISO 3166-2:ES, name).
ES_REGIONS: dict[str, tuple[str, str]] = {
    "galicia": ("ES-GA", "Galicia"), "p. de asturias": ("ES-AS", "Principado de Asturias"),
    "cantabria": ("ES-CB", "Cantabria"), "pais vasco": ("ES-PV", "País Vasco"),
    "navarra": ("ES-NC", "Comunidad Foral de Navarra"), "la rioja": ("ES-RI", "La Rioja"),
    "aragon": ("ES-AR", "Aragón"), "cataluna": ("ES-CT", "Cataluña"), "baleares": ("ES-IB", "Illes Balears"),
    "castilla y leon": ("ES-CL", "Castilla y León"), "madrid": ("ES-MD", "Comunidad de Madrid"),
    "castilla-la mancha": ("ES-CM", "Castilla-La Mancha"), "c. valenciana": ("ES-VC", "Comunitat Valenciana"),
    "r. de murcia": ("ES-MC", "Región de Murcia"), "extremadura": ("ES-EX", "Extremadura"),
    "andalucia": ("ES-AN", "Andalucía"), "canarias": ("ES-CN", "Canarias"),
}
ES_TOLERANCE = {"production": 0.01, "hives": 0.5}      # regions vs national total (t, hives): rounding only

# www.mapa.gob.es sends its chain in an order OpenSSL cannot build: leaf -> "AC SERVIDORES SEGUROS
# TIPO2 G2R" -> the SELF-SIGNED new root "AC RAIZ FNMT-RCM SERVIDORES SEGUROS G2R" (not yet in the
# Mozilla/certifi store) ahead of the same root CROSS-SIGNED by "AC RAIZ FNMT-RCM" (in the store). Python
# then stops at the self-signed copy ("self-signed certificate in certificate chain"; browsers build
# the cross-signed path). The fix keeps full verification: this cross-certificate, signed by the
# Mozilla-trusted "AC RAIZ FNMT-RCM", is added to the store of the MAPA requests only, with partial-chain
# trust switched OFF so that it must itself verify up to that root (checked live: with the cross-cert
# alone, without the root, the handshake fails). Subject "C=ES, O=FNMT-RCM, CN=AC RAIZ FNMT-RCM
# SERVIDORES SEGUROS G2R", issuer "C=ES, O=FNMT-RCM, OU=AC RAIZ FNMT-RCM", valid 2025-12-16 to
# 2029-12-16, SHA-256 32:7E:C9:39:55:C9:14:52:61:B0:87:C6:FC:5E:AC:8A:71:26:2B:F2:56:8E:8D:36:F7:C2:FE:DB:D1:B1:07:7A
# (as served by www.mapa.gob.es on 5 Nov 2026; issuer certificate http://www.cert.fnmt.es/certs/ACRAIZFNMT.crt).
FNMT_G2R_CROSS_PEM = """-----BEGIN CERTIFICATE-----
MIIGfDCCBGSgAwIBAgIQDRmrUJXP01BpQWO7H0YTQTANBgkqhkiG9w0BAQwFADA7
MQswCQYDVQQGEwJFUzERMA8GA1UECgwIRk5NVC1SQ00xGTAXBgNVBAsMEEFDIFJB
SVogRk5NVC1SQ00wHhcNMjUxMjE2MTM1MDUwWhcNMjkxMjE2MTM1MDUwWjBSMQsw
CQYDVQQGEwJFUzERMA8GA1UECgwIRk5NVC1SQ00xMDAuBgNVBAMMJ0FDIFJBSVog
Rk5NVC1SQ00gU0VSVklET1JFUyBTRUdVUk9TIEcyUjCCAiIwDQYJKoZIhvcNAQEB
BQADggIPADCCAgoCggIBALQ5a+qwhJLRhbQIUIwPLu/7VIlvnpwiQdmDtH+x6dYH
fGFJq53a8p5U6upv8qCFPjKdeIf5FdCGlZb6ZQGn+OG2lG1t2hNUipNIAqfYWdqJ
zDGIkSDnCgubEsR85/CSB10E9bZB3FkQJpYgqEsfIz84C0DQNYToJz7qdObLPUrp
/BUZvFa/L0wnsx2/RirDmau83zlS6MYdQTZQDbmsy/0pi+sV8Cu+GYfYcr2DALC1
11t9RIZoQ59evDzcJsa4S/y5t3qEgMZs9UzNoGiix2fR/N0QP02cuUiW8DVLcNue
qG/ow949OxGwSkJc7dkaZDTeezRByG/02e/MBhrfgUodp9aoGxO/sbtpr6Ptvp+F
C5SwnTJtqAtxZl2LUPhNyN9eCeblrJ12rrLI7mzpwPTM9UiJa9pYOfegeXieDwoH
ufFHR2Hg3RQm/lo75BSvaman89NTva5tS1bx2Rwed2CEKoT8WrWETGBGKupbAp+c
9eE7z39Kx7MkooNqX2TbC5k3OIkcbbeBu7WByP7OSpM1bz4fuj2JgDsmyMtw4J4p
D8+w0k65j+Pmpz82+tbxuoEWw5MPFRQquMjQ+5b63zlguLtdy+2U4uEhGap0v0UO
m9ZIS1tTKGc2vJU4NHBM5nF91AUAwifsxQu2JUBkO9R6FFmL261K+jpLZETs2dpR
AgMBAAGjggFjMIIBXzAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB/zAd
BgNVHQ4EFgQUI4JUVDBhTKBOgbmDiPLKBfYZuJswHwYDVR0jBBgwFoAU933F/cTo
mht3ZKf1HaDMv4dgmm0wEQYDVR0gBAowCDAGBgRVHSAAMBMGA1UdJQQMMAoGCCsG
AQUFBwMBMIGVBggrBgEFBQcBAQSBiDCBhTBJBggrBgEFBQcwAYY9aHR0cDovL29j
c3Bmbm10cmNtY2EuY2VydC5mbm10LmVzL29jc3Bmbm10cmNtY2EvT2NzcFJlc3Bv
bmRlcjA4BggrBgEFBQcwAoYsaHR0cDovL3d3dy5jZXJ0LmZubXQuZXMvY2VydHMv
QUNSQUlaRk5NVC5jcnQwPAYDVR0fBDUwMzAxoC+gLYYraHR0cDovL3d3dy5jZXJ0
LmZubXQuZXMvY3Jscy9BUkxGTk1UUkNNLmNybDANBgkqhkiG9w0BAQwFAAOCAgEA
HsB/he46/txFsYNJSIxOXPIo4DdNDsPjsm4EqrxSlS6TI0DCzsKAQZHOQhrCp0Bn
9tltUggRnipC4a1sn679PPKj3Ze3/HQ6r3oiZpZlBtRt8rajePtXNxGlvs7RKv1g
Td0/b37Cmd8Ucw7427YdQAbjPXaakeE6Rmy58G51EExfTYR1TMYtqXIVTka/W5x8
zZhgogf4Uf+mu/sYeLbW/XxSKQ1XlPrDJok7WWKdMHFfPcbOH7eANRDXdHBxHbKx
ZZ+BU6RSxJQVRcS5xTc7xe207SrkOKGBT42MQCh+CmN+igROjB3SnG7quX9guwmh
TpGGHqD47M7C5ypu2Eq2M4+ShJb+06/f7veLV4GC5P+qBZHKhyfCUy7ENUjoFW4l
tS/aq3p8MYpNuzgqd0h/ff5qWxHCt4pjwkU2l2YM7rKpfA8TRwynGdOD1j7/ZGOe
ntzc0hnD5EmwbW4vl6C9azUZY84eLF6BQfiOBDeV5UHbwxIA8WVx0rqLAPeY7cFT
WFxYbHUD/L8sMWj/5rKJlexksvUD/qf/AUdM0eukvjA2mOHMBXNf1mdNC00d2pCK
KRXjKXY58+yBIVtCxlYQ/5a1T9pxGjvYVh+Wa/CQ+gzZpZvBw6FCtYFqRWYlyx1O
+aK/hD7Uw8BlmrBq87pNupkoZ1K0gduT3sfuxVpJvMU=
-----END CERTIFICATE-----
"""


def mapa_ssl_context() -> ssl.SSLContext:
    """The standard trust store (``SSL_CERT_FILE`` when set, as httpx does, else certifi) plus the FNMT
    cross-certificate above, with partial-chain trust off: full verification up to a trusted root."""
    import certifi

    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile or not os.path.isfile(cafile):
        cafile = certifi.where()
    context = ssl.create_default_context(cafile=cafile)
    context.load_verify_locations(cadata=FNMT_G2R_CROSS_PEM)
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    return context


@contextmanager
def _mapa_client(ctx: CollectContext) -> Iterator[None]:
    """Route this run's requests (all to www.mapa.gob.es) through a client that trusts the FNMT
    cross-certificate; same headers (User-Agent) and timeout as the shared client."""
    original = ctx.client
    client = httpx.Client(timeout=original.timeout, follow_redirects=True, headers=original.headers,
                          verify=mapa_ssl_context())
    ctx.client = client
    try:
        yield
    finally:
        ctx.client = original
        client.close()


def find_es_files(page_html: str, base_url: str = ES_PAGE_URL) -> dict[int, str]:
    """year -> absolute URL of the "Miel y cera" workbook of that year, from the statistic's page. The
    year is read from the file name ("mielycera-25-web...xlsx") or, for 2013-2014 ("mielycera.xls"),
    from the folder (".../2014/mielycera.xls"). Two different files for one year fail loudly."""
    out: dict[int, str] = {}
    for m in _ES_LINK.finditer(page_html):
        url = urljoin(base_url, html_lib.unescape(m.group(1)))
        name = url.rsplit("/", 1)[-1]
        found = re.search(r"mielycera-(\d{2})(?!\d)", name, re.I)
        if found:
            year = 2000 + int(found.group(1))
        else:
            folder = re.search(r"/(20\d\d)/[^/]+$", url)
            if not folder:
                log.info("MAPA: cannot tell the year of %s; ignored", url)
                continue
            year = int(folder.group(1))
        if year in out and out[year] != url:
            raise CollectorError(f"MAPA: two different 'Miel y cera' files for {year} on the page ({out[year]}, {url}); "
                                 "nothing stored")
        out[year] = url
    return dict(sorted(out.items()))


@dataclass(frozen=True)
class EsRow:
    label: str                                   # as published (stripped)
    honey: tuple[float, float, float]            # transhumant/mobile, stationary/fixed, TOTAL
    wax: tuple[float, float, float]


@dataclass
class EsTable:
    kind: str                                    # "production" (t) | "hives" (number)
    year: int
    sheet: str
    title: str
    split: tuple[str, str]                       # labels of the two split columns, as published
    national: EsRow
    regions: dict[str, EsRow]                    # ISO 3166-2 code -> row
    region_labels: dict[str, str]                # ISO code -> label as published
    provinces: dict[str, list[EsRow]]            # ISO code -> the provinces listed above the region row
    footnotes: list[str] = field(default_factory=list)

    def region_total(self, part: str = "honey") -> float:
        return sum(getattr(r, part)[2] for r in self.regions.values())


@dataclass
class EsWorkbook:
    year: int
    production: EsTable
    hives: EsTable


def _clean_label(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def parse_es_sheet(rows: list[list[Any]], sheet: str, kind: str) -> EsTable:
    """One "MIEL Y CERA: Análisis provincial ..." sheet. Fails loudly on drift: no title with the year,
    no two-row header (Miel/Cera, ... TOTAL), a region or national row that is not numeric, not exactly
    the 17 autonomous communities, no ESPAÑA row, province rows not followed by their region."""
    title_re = _ES_PROD_TITLE if kind == "production" else _ES_HIVE_TITLE
    title_row = next((r for r in rows[:8] if r and title_re.search(_norm(r[0]))), None)
    if title_row is None:
        raise CollectorError(f"MAPA schema drift: sheet {sheet!r} has no '{kind}' title with a year; nothing stored")
    title = _clean_label(title_row[0])
    year = int(title_re.search(_norm(title_row[0])).group(1))
    head = next((i for i in range(len(rows) - 1) if rows[i] and _norm(rows[i][0]) == "provincias y"
                 and rows[i + 1] and _norm(rows[i + 1][0]) == "comunidades autonomas"), None)
    if head is None:
        raise CollectorError(f"MAPA schema drift: sheet {sheet!r} has no 'Provincias y / Comunidades Autónomas' header; "
                             "nothing stored")
    top, sub = (list(rows[head]) + [None] * 7)[:7], (list(rows[head + 1]) + [None] * 7)[:7]
    if _norm(top[1]) != "miel" or _norm(top[4]) != "cera" or _norm(sub[3]) != "total" or _norm(sub[6]) != "total":
        raise CollectorError(f"MAPA schema drift: sheet {sheet!r} header {top} / {sub} is not Miel (3 columns) + Cera "
                             "(3 columns) ending in TOTAL; nothing stored")
    split = (_clean_label(sub[1]), _clean_label(sub[2]))
    national: EsRow | None = None
    regions: dict[str, EsRow] = {}
    labels: dict[str, str] = {}
    provinces: dict[str, list[EsRow]] = {}
    pending: list[EsRow] = []
    footnotes: list[str] = []
    for r in rows[head + 2:]:
        cells = (list(r) + [None] * 7)[:7]
        label = _clean_label(cells[0])
        if not label:
            continue
        values = cells[1:7]
        numeric = all(_is_number(v) for v in values)
        key = _norm(label)
        if key in ("espana",) or key in ES_REGIONS:
            if not numeric:
                raise CollectorError(f"MAPA: row {label!r} of sheet {sheet!r} has non-numeric cells {values}; nothing stored")
            row = EsRow(label=label, honey=tuple(float(v) for v in values[:3]), wax=tuple(float(v) for v in values[3:]))
            if key == "espana":
                if national is not None:
                    raise CollectorError(f"MAPA: sheet {sheet!r} has two ESPAÑA rows; nothing stored")
                national = row
            else:
                code = ES_REGIONS[key][0]
                if code in regions:
                    raise CollectorError(f"MAPA: region {label!r} twice in sheet {sheet!r}; nothing stored")
                regions[code], labels[code], provinces[code] = row, label, pending
                pending = []
        elif numeric:
            pending.append(EsRow(label=label, honey=tuple(float(v) for v in values[:3]),
                                 wax=tuple(float(v) for v in values[3:])))
        elif all(v in (None, "") for v in values):
            footnotes.append(label)
        else:
            raise CollectorError(f"MAPA schema drift: unexpected row {label!r} {values} in sheet {sheet!r}; nothing stored")
    if national is None:
        raise CollectorError(f"MAPA schema drift: sheet {sheet!r} has no ESPAÑA row; nothing stored")
    if pending:
        raise CollectorError(f"MAPA schema drift: rows {[p.label for p in pending]} of sheet {sheet!r} are not followed "
                             "by their autonomous community; nothing stored")
    if len(regions) != len(ES_REGIONS):
        missing = sorted(name for k, (code, name) in ES_REGIONS.items() if code not in regions)
        raise CollectorError(f"MAPA schema drift: sheet {sheet!r} lists {len(regions)} autonomous communities "
                             f"(missing {missing}); nothing stored")
    return EsTable(kind=kind, year=year, sheet=sheet, title=title, split=split, national=national, regions=regions,
                   region_labels=labels, provinces=provinces, footnotes=footnotes)


def parse_es_workbook(content: bytes, expected_year: int | None = None) -> EsWorkbook:
    """Both sheets of a "Miel y cera" workbook (production and hives); their years must agree with
    each other and with the year of the link."""
    found: dict[str, EsTable] = {}
    for name, rows in _workbook_rows(content, "MAPA 'Miel y cera'"):
        head = " ".join(_norm(r[0]) for r in rows[:8] if r)
        kind = "production" if _ES_PROD_TITLE.search(head) else "hives" if _ES_HIVE_TITLE.search(head) else None
        if kind is None:
            continue
        if kind in found:
            raise CollectorError(f"MAPA: two '{kind}' sheets in the workbook; nothing stored")
        found[kind] = parse_es_sheet(rows, name, kind)
    if set(found) != {"production", "hives"}:
        raise CollectorError(f"MAPA schema drift: the workbook has {sorted(found) or 'none'} of the production and hives "
                             "sheets; nothing stored")
    years = {found["production"].year, found["hives"].year}
    if len(years) != 1 or (expected_year is not None and years != {expected_year}):
        raise CollectorError(f"MAPA: the workbook's sheets are for {sorted(years)}, the link for {expected_year}; "
                             "nothing stored")
    return EsWorkbook(year=years.pop(), production=found["production"], hives=found["hives"])


def check_es_workbook(wb: EsWorkbook) -> list[str]:
    """Regions vs the published ESPAÑA total (honey and wax), beyond rounding. Reported, never fixed."""
    out = []
    for table, unit in ((wb.production, "t"), (wb.hives, "hives")):
        tol = ES_TOLERANCE[table.kind]
        for part in ("honey", "wax"):
            total = getattr(table.national, part)[2]
            regions = table.region_total(part)
            if abs(regions - total) > tol:
                out.append(f"{wb.year} {table.kind} ({part}): the 17 communities add up to {regions:,.3f} {unit}, "
                           f"ESPAÑA is {total:,.3f} {unit}")
    return out


def es_published(last_modified: date | None, year: int) -> date | None:
    """The file's Last-Modified date when it can be the release date: the statistic of year Y comes out
    in Y+1 (2024: 2 Jul 2025, 2025: 24 Aug 2026). Files 2013-2023 all carry 2 Jun 2025 (a website
    migration), which is not their release date: then None, never guessed."""
    return last_modified if last_modified is not None and last_modified.year == year + 1 else None


class EsMapaHoneyCollector(Collector):
    key = "es_mapa_honey"
    name = "Spagna – MAPA (Estadística de Miel y Cera): produzione di miele e alveari, nazionale e per comunità autonoma"
    name_en = "Spain – MAPA (Honey and Wax Statistics): honey production and beehives, national and by region"
    publisher = "MAPA – Ministerio de Agricultura, Pesca y Alimentación, S.G. de Análisis, Coordinación y Estadística"
    homepage = ES_PAGE_URL
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "ESP"
    language = "es"
    expected_update = "Annuale (anno Y in estate Y+1: 2025 pubblicato il 24 ago 2026); controllo mensile"
    expected_update_en = "Annual (year Y in summer Y+1: 2025 published on 24 Aug 2026); checked monthly"
    expected_max_age_days = 450
    terms_note = (
        "Fuente: MAPA, 'Estadística de Miel y Cera' (Plan Estadístico Nacional; Implementing Regulation (EU) "
        "2023/2745). MAPA's legal notice (Ley 37/2007): the information may be reused without express authorisation "
        "provided the source is cited. Honey and wax in tonnes as published (computed from REGA hive counts and "
        "yields per hive); hives = the statistic's own hive count, not the REGA census of the 'Indicadores "
        "económicos' report. Values with many decimals are stored rounded to the kg (hives to 0.01, as published)."
    )
    # Monthly: one ~40 KB request to the statistic's page; workbooks only when a link changes.
    schedule = {"trigger": "cron", "day": 21, "hour": 7, "minute": 35}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        with _mapa_client(ctx):
            page = ctx.fetch(ES_PAGE_URL, store=False)
            files = {y: u for y, u in find_es_files(page.text, page.url).items() if y >= ES_FIRST_YEAR}
            have_rows = _has_rows(ctx)
            if not files:
                if have_rows:
                    _warn_once(ctx, state, "no_files", "MAPA: no 'Miel y cera' workbook is listed on the statistic's page "
                                                       "any more; the figures already stored are kept")
                    _save_state(ctx, state)
                    ctx.checkpoint()
                    return
                raise CollectorError("MAPA: no 'Miel y cera' workbook on the statistic's page (page changed?); nothing stored")
            known: dict[str, str] = dict(state.get("files") or {})
            for gone in sorted(set(known) - {str(y) for y in files}):
                _warn_once(ctx, state, f"gone:{gone}", f"MAPA: the {gone} workbook is no longer listed; its figures are kept")
            full = ctx.force or not have_rows or _refresh_due(state, ES_FULL_REFRESH_DAYS)
            todo = [y for y in files if full or known.get(str(y)) != files[y]]
            if not todo:
                log.info("[%s] MAPA: no new or changed workbook (%d listed)", self.key, len(files))
                return
            for year in todo:
                url = files[year]
                doc = ctx.fetch(url, title=f"MAPA – {ES_STATISTIC} {year} ({url.rsplit('/', 1)[-1]})")
                last_modified = _http_date(_header(doc.headers, "last-modified"))
                if doc.unchanged and have_rows and not ctx.force and known.get(str(year)) in (None, url):
                    log.info("[%s] MAPA %d: workbook identical to the one already stored", self.key, year)
                else:
                    wb = parse_es_workbook(doc.content, expected_year=year)
                    for msg in check_es_workbook(wb):
                        _warn_once(ctx, state, f"sums:{url}:{msg}", f"MAPA: {msg}; the published total is stored as is")
                    self._store(ctx, wb, url, doc.raw_document_id, last_modified)
                known[str(year)] = url
                state["files"] = known
                _save_state(ctx, state)
                ctx.checkpoint()
            if full:
                state["pulled_at"] = utcnow().isoformat(timespec="seconds")
            state["latest_year"] = max(files)
            _save_state(ctx, state)
            ctx.checkpoint()

    def _store(self, ctx: CollectContext, wb: EsWorkbook, url: str, raw_id: int, last_modified: date | None) -> None:
        year = wb.year
        ps, pe = year_bounds(year)
        published = es_published(last_modified, year)
        common: dict[str, Any] = dict(
            country_iso3="ESP", period_start=ps, period_end=pe, period_label=str(year), frequency="A",
            data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, published_at=published,
            source_url=url, raw_document_id=raw_id or None)
        base = {"statistic": f"MAPA – {ES_STATISTIC}", "page_url": ES_PAGE_URL, "file_url": url,
                "file_last_modified": last_modified.isoformat() if last_modified else None,
                "release_date_note": None if published else ("the file's Last-Modified date is not its release date "
                                                             "(website migration); left empty")}
        prod, hives = wb.production, wb.hives
        split_names = {"production": prod.split, "hives": hives.split}

        def split(row: EsRow, kind: str, digits: int) -> dict[str, float]:
            a, b = split_names[kind]
            return {a: round(row.honey[0], digits), b: round(row.honey[1], digits)}

        n, h = prod.national, hives.national
        ctx.add_production(
            series_key=f"mapa_mielycera|ESP|production|{year}", metric="production", value=round(n.honey[2], 3), unit="t",
            extra={**base, "sheet": prod.sheet, "table": prod.title, "row": n.label, "column": "Miel – TOTAL",
                   "value_as_published": n.honey[2], "unit_as_published": "toneladas", "split": split(n, "production", 3),
                   "wax_t": round(n.wax[2], 3), "hives": round(h.honey[2], 2), "footnotes": prod.footnotes or None},
            notes=(f"MAPA {ES_STATISTIC} {year}: honey production in Spain {n.honey[2]:,.3f} t (row ESPAÑA, Miel TOTAL "
                   f"of '{prod.title}'); stored rounded to the kg."),
            **common)
        ctx.add_production(
            series_key=f"mapa_mielycera|ESP|colonies|{year}", metric="colonies", value=round(h.honey[2], 2), unit="number",
            extra={**base, "sheet": hives.sheet, "table": hives.title, "row": h.label, "column": "Miel – TOTAL",
                   "value_as_published": h.honey[2], "split": split(h, "hives", 2), "hives_for_wax": round(h.wax[2], 2),
                   "footnotes": hives.footnotes or None},
            notes=(f"MAPA {ES_STATISTIC} {year}: {h.honey[2]:,.2f} hives counted for honey production (row ESPAÑA of "
                   f"'{hives.title}'), as published; not the REGA census of MAPA's 'Indicadores económicos' report."),
            **common)
        for table, metric, unit, digits in ((prod, "production_by_region", "t", 3), (hives, "colonies_by_region", "number", 2)):
            for code, row in table.regions.items():
                name = next(nm for c, nm in ES_REGIONS.values() if c == code)
                ctx.add_production(
                    series_key=f"mapa_mielycera|{code}|{metric}|{year}", metric=metric, value=round(row.honey[2], digits),
                    unit=unit,
                    extra={**base, "region": name, "region_code": code, "region_as_published": table.region_labels[code],
                           "sheet": table.sheet, "table": table.title, "value_as_published": row.honey[2],
                           "split": split(row, table.kind, digits),
                           ("wax_t" if table.kind == "production" else "hives_for_wax"): round(row.wax[2], digits),
                           "provinces": {p.label: round(p.honey[2], digits) for p in table.provinces[code]} or None},
                    notes=(f"MAPA {ES_STATISTIC} {year}, {name}: "
                           + (f"honey {row.honey[2]:,.3f} t." if table.kind == "production"
                              else f"{row.honey[2]:,.2f} hives counted for honey.")),
                    **common)


# ===========================================================================
# 2) Hungary: KSH STADAT table 19.1.1.34 (HTML table)
# ===========================================================================

KSH_TABLE_URL = "https://www.ksh.hu/stadat_files/mez/en/mez0034.html"
KSH_TABLE_ID = "19.1.1.34"
KSH_FIRST_YEAR = 2015
_EN_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"), 1)}


@dataclass(frozen=True)
class KshPoint:
    year: int
    raw: str                    # the cell as published ("25,000", "..")
    value: float | None
    revised: bool               # printed in green: "Revised datum"


@dataclass
class KshTable:
    title: str
    last_updated: date | None
    column: str
    unit: str
    points: list[KshPoint]


def _expand_header(cells) -> list[str]:
    out: list[str] = []
    for c in cells:
        out.extend([re.sub(r"\s+", " ", c.get_text(" ", strip=True))] * int(c.get("colspan") or 1))
    return out


def parse_ksh_table(page_html: str) -> KshTable:
    """The STADAT table page: title, "Last updated" date, and the "Honey" column (unit row "production,
    tonne"). Fails loudly when the table, the honey column, its unit or the year rows are missing."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.find("table", class_="stadat")
    if table is None or table.thead is None or table.tbody is None:
        raise CollectorError("KSH: no STADAT table on the page (page changed?); nothing stored")
    head_rows = table.thead.find_all("tr")
    if len(head_rows) < 2:
        raise CollectorError("KSH schema drift: the table header has fewer than two rows; nothing stored")
    first = head_rows[0].find_all("th")
    if not first or _norm(first[0].get_text()) != "year":
        raise CollectorError("KSH schema drift: the first column is not 'Year'; nothing stored")
    names = [re.sub(r"\s+", " ", th.get_text(" ", strip=True)) for th in first[1:]]   # sup footnote letters included
    units = _expand_header(head_rows[1].find_all("th"))
    honey = [i for i, nm in enumerate(names) if _norm(re.sub(r"\s+[a-z]$", "", nm)) == "honey"]
    if len(honey) != 1 or len(units) != len(names):
        raise CollectorError(f"KSH schema drift: columns {names} / units {units} (expected one 'Honey' column); "
                             "nothing stored")
    col = honey[0]
    if "tonne" not in _norm(units[col]):
        raise CollectorError(f"KSH schema drift: the honey column's unit is {units[col]!r}, not tonnes; nothing stored")
    points: list[KshPoint] = []
    for tr in table.tbody.find_all("tr"):
        th, tds = tr.find("th"), tr.find_all("td")
        year_txt = th.get_text(strip=True) if th else ""
        if not re.fullmatch(r"\d{4}", year_txt) or len(tds) != len(names):
            raise CollectorError(f"KSH schema drift: unexpected row {year_txt!r} with {len(tds)} cells; nothing stored")
        cell = tds[col]
        raw = cell.get_text(strip=True)
        if raw in ("..", "–", "-", ""):
            value = None
        elif re.fullmatch(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", raw):
            value = float(raw.replace(",", ""))
        else:
            raise CollectorError(f"KSH: unreadable honey value {raw!r} for {year_txt}; nothing stored")
        points.append(KshPoint(year=int(year_txt), raw=raw, value=value,
                               revised="green" in (cell.get("style") or "").replace(" ", "").lower()))
    if not points or len({p.year for p in points}) != len(points):
        raise CollectorError("KSH: the table has no year rows, or a year twice; nothing stored")
    title_tag = soup.find("h1") or soup.find("title")
    title = re.sub(r"\s+", " ", title_tag.get_text(" ", strip=True)) if title_tag else KSH_TABLE_ID
    updated = None
    li = soup.find(class_="last-update")
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", li.get_text(" ", strip=True)) if li else None
    if m and m.group(2).lower() in _EN_MONTHS:
        updated = date(int(m.group(3)), _EN_MONTHS[m.group(2).lower()], int(m.group(1)))
    return KshTable(title=title, last_updated=updated, column=f"{names[col]} ({units[col]})", unit=units[col],
                    points=points)


class HuKshHoneyCollector(Collector):
    key = "hu_ksh_honey"
    name = "Ungheria – KSH (STADAT 19.1.1.34): produzione di miele, totale nazionale"
    name_en = "Hungary – KSH (STADAT 19.1.1.34): honey production, national total"
    publisher = "KSH – Központi Statisztikai Hivatal (Hungarian Central Statistical Office)"
    homepage = KSH_TABLE_URL
    kind = SourceKind.HTML
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "HUN"
    language = "en"
    expected_update = "Annuale (tabella aggiornata in autunno: 2025 al 14 ott 2026); controllo mensile"
    expected_update_en = "Annual (table updated in the autumn: 2025 on 14 Oct 2026); checked monthly"
    expected_max_age_days = 450
    terms_note = (
        "Source: KSH, STADAT table 19.1.1.34 'Production of milk, eggs, wool, feather and honey' (public table, cite "
        "KSH). Honey production in tonnes as published: KSH rounds it to the thousand tonnes. Figures printed in green "
        "are 'revised data' (kept in extra.revised_marker). No hive counts in this table."
    )
    # Monthly: one ~40 KB request; parsed only when the page changes.
    schedule = {"trigger": "cron", "day": 21, "hour": 7, "minute": 50}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        doc = ctx.fetch(KSH_TABLE_URL, title=f"KSH STADAT {KSH_TABLE_ID} (honey production)")
        if doc.unchanged and _has_rows(ctx) and not ctx.force:
            log.info("[%s] KSH table unchanged", self.key)
            return
        table = parse_ksh_table(doc.text)
        if table.last_updated is None:
            ctx.warn("KSH: no 'Last updated' date on the table page; rows are stored without a publication date")
        kept = [p for p in table.points if p.year >= KSH_FIRST_YEAR and p.value is not None]
        if not kept:
            raise CollectorError(f"KSH: no honey figure from {KSH_FIRST_YEAR} in the table; nothing stored")
        for p in kept:
            ps, pe = year_bounds(p.year)
            ctx.add_production(
                series_key=f"ksh_stadat|{KSH_TABLE_ID}|HUN|production|{p.year}", country_iso3="HUN", metric="production",
                value=p.value, unit="t", period_start=ps, period_end=pe, period_label=str(p.year), frequency="A",
                data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, published_at=table.last_updated,
                source_url=KSH_TABLE_URL, raw_document_id=doc.raw_document_id or None,
                extra={"table": table.title, "table_id": KSH_TABLE_ID, "column": table.column,
                       "value_as_published": p.raw, "unit_as_published": "tonne", "revised_marker": p.revised,
                       "last_updated": table.last_updated.isoformat() if table.last_updated else None,
                       "rounding": "published rounded to the thousand tonnes"},
                notes=(f"KSH STADAT {KSH_TABLE_ID}: honey production {p.raw} tonnes in {p.year}"
                       + (" (marked as revised)" if p.revised else "") + "."))
        ctx.checkpoint()


# ===========================================================================
# 3) Bulgaria: MZH Agrostatistics, bulletin "Пчеларството в България през YYYY година" (PDF)
# ===========================================================================

MZH_BASE = "https://www.mzh.government.bg"
MZH_LIST_URL = f"{MZH_BASE}/bg/statistika-i-analizi/izsledvane-zhivotnovdstvo/danni/"
MZH_MAX_PAGES = 4                    # the bulletin (February) sits on page 1-3 of the list during the year
MZH_REFRESH_DAYS = 180
_MZH_LINK = re.compile(r'<a[^>]*href="(/media/filer_public/[^"]+\.pdf)"[^>]*>(.*?)</a>', re.S | re.I)
_MZH_TITLE = re.compile(r"пчеларството в българия през (\d{4})")
# NUTS 2 statistical regions as named in table 1 (`_fold`) -> (NUTS code, name).
BG_REGIONS: dict[str, tuple[str, str]] = {
    "северозападен": ("BG31", "Северозападен (North-West)"), "северен централен": ("BG32", "Северен централен (North-Central)"),
    "североизточен": ("BG33", "Североизточен (North-East)"), "югоизточен": ("BG34", "Югоизточен (South-East)"),
    "югозападен": ("BG41", "Югозападен (South-West)"), "южен централен": ("BG42", "Южен централен (South-Central)"),
}
_BG_INT = re.compile(r"-?\d{1,3}")
_BG_GROUP = re.compile(r"\d{3}(?:[.,]\d+)?%?")
_BG_NUMBER = re.compile(r"-?\d+(?:\.\d*)?%?")       # "101." occurs: a digit missing from the text layer


def mzh_list_url(page: int) -> str:
    return MZH_LIST_URL if page == 1 else f"{MZH_LIST_URL}?page={page}"


@dataclass(frozen=True)
class MzhBulletin:
    year: int
    url: str
    title: str
    published: date | None       # the upload date in the file path (/media/filer_public/2026/02/27/...)


def find_mzh_bulletins(page_html: str) -> list[MzhBulletin]:
    """The beekeeping bulletins listed on one page of the livestock data list, newest year first."""
    out: dict[int, MzhBulletin] = {}
    for m in _MZH_LINK.finditer(page_html):
        href = html_lib.unescape(m.group(1))
        title = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        found = _MZH_TITLE.search(_fold(title)) or re.search(r"beeshoney(20\d\d)", href, re.I)
        if not found or ("beeshoney" not in href.lower() and "пчелар" not in _fold(title)):
            continue
        year = int(found.group(1))
        d = re.search(r"/filer_public/(\d{4})/(\d{2})/(\d{2})/", href)
        published = date(int(d.group(1)), int(d.group(2)), int(d.group(3))) if d else None
        out.setdefault(year, MzhBulletin(year=year, url=urljoin(MZH_BASE, href), title=title, published=published))
    return [out[y] for y in sorted(out, reverse=True)]


def pdf_page_words(content: bytes, pages: int = 3) -> list[list[dict[str, Any]]]:
    """pdfplumber words (text, x0, x1, top, bottom) of the first `pages` pages."""
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return [[{k: w[k] for k in ("text", "x0", "x1", "top", "bottom")}
                     for w in page.extract_words(x_tolerance=1.5, keep_blank_chars=False)]
                    for page in pdf.pages[:pages]]
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many types on a broken file
        raise CollectorError(f"MZH: the bulletin PDF cannot be read ({type(exc).__name__}: {exc}); nothing stored") from exc


def word_lines(pages: list[list[dict[str, Any]]]) -> list[list[tuple[str, float, float]]]:
    """Lines of words (text, x0, x1), top to bottom, page after page. One table row's words differ in
    `top` by up to ~1.5 pt (labels are centred, digits are not) while rows are ~10 pt apart: words are
    clustered on their vertical middle with a 3 pt tolerance."""
    lines: list[list[tuple[str, float, float]]] = []
    for words in pages:
        current: list[dict[str, Any]] = []
        anchor = 0.0
        for w in sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2):
            mid = (w["top"] + w["bottom"]) / 2
            if current and mid - anchor > 3.0:
                lines.append([(x["text"], x["x0"], x["x1"]) for x in sorted(current, key=lambda x: x["x0"])])
                current = []
            if not current:
                anchor = mid
            current.append(w)
        if current:
            lines.append([(x["text"], x["x0"], x["x1"]) for x in sorted(current, key=lambda x: x["x0"])])
    return lines


def group_numbers(words: list[tuple[str, float, float]], max_gap: float = 6.0) -> list[str]:
    """Words of a line with thousands groups joined: "808" + "851" 2.2 pt apart is 808851 (the bulletin
    separates thousands with a thin space; columns are at least 25 pt apart)."""
    out: list[str] = []
    last_x1: float | None = None
    joinable = False
    for text, x0, x1 in words:
        if (joinable and last_x1 is not None and x0 - last_x1 < max_gap and _BG_GROUP.fullmatch(text)):
            out[-1] += text
            joinable = not re.search(r"[.,%]", text)
        else:
            out.append(text)
            joinable = bool(_BG_INT.fullmatch(text))
        last_x1 = x1
    return out


@dataclass(frozen=True)
class MzhRow:
    label: str
    holdings: int
    colonies: int                # bee colonies on 1 October
    harvested: int               # colonies from which honey was taken
    avg_colonies: float | None   # per holding (derived column; None when the text layer garbles it)
    honey_t: int
    yield_kg: float | None       # per harvested colony (derived column)
    raw: tuple[str, ...]


@dataclass
class MzhTables:
    year: int
    title: str
    national: MzhRow
    regions: dict[str, MzhRow]                     # NUTS code -> row
    zones: list[MzhRow]
    previous_colonies: int | None = None           # table 3: colonies on 1 Oct of the previous year
    previous_harvested: int | None = None
    wax_t: float | None = None


def _strip_margin(tokens: list[str]) -> list[str]:
    """Drop single capital letters: the vertical "АГРОСТАТИСТИКА" print in the page margin lands at the
    start of table lines ("Т Североизточен ...", "И Източник: ...")."""
    return [t for t in tokens if not (len(t) == 1 and t.isalpha() and t.isupper())]


def _split_label(tokens: list[str], n: int) -> tuple[str, list[str]] | None:
    if len(tokens) < n + 1 or not all(_BG_NUMBER.fullmatch(t) for t in tokens[-n:]):
        return None
    return " ".join(_strip_margin(tokens[:-n])), tokens[-n:]


def _derived(token: str) -> float | None:
    """An average/yield cell: a decimal number, else None (the raw cell stays in `MzhRow.raw`)."""
    return float(token) if re.fullmatch(r"\d+\.\d+", token) else None


# Captions located by their text: the "Таблица N" line itself can be garbled ("Табли1 ца 3", 2025 bulletin).
_MZH_TABLE1 = "стопанства, пчелни семейства и производство на пчелен мед"
_MZH_TABLE3 = "налични пчелни семейства по статистически райони"


def parse_mzh_bulletin(content: bytes) -> MzhTables:
    """The bulletin PDF: see `parse_mzh_words`."""
    return parse_mzh_words(pdf_page_words(content))


def parse_mzh_words(pages: list[list[dict[str, Any]]]) -> MzhTables:
    """Table 1 ("Стопанства, пчелни семейства и производство на пчелен мед по статистически райони") and
    the national row of table 3 (colonies of both years), from the words of the first pages. Fails
    loudly when the title year, table 1, the national row or any of the six regions is missing, or a
    row's numbers are not the six columns."""
    lines = word_lines(pages)
    texts = [" ".join(_strip_margin([w[0] for w in line])) for line in lines]
    title_year = next((int(m.group(1)) for t in texts if (m := _MZH_TITLE.search(_fold(t)))), None)
    if title_year is None:
        raise CollectorError("MZH schema drift: no 'Пчеларството в България през YYYY година' title; nothing stored")
    t1 = next((i for i, t in enumerate(texts) if _fold(t).startswith(_fold(_MZH_TABLE1))), None)
    if t1 is None:
        raise CollectorError("MZH schema drift: no table 1 'Стопанства, пчелни семейства и производство на пчелен мед' "
                             "in the bulletin; nothing stored")
    national: MzhRow | None = None
    regions: dict[str, MzhRow] = {}
    zones: list[MzhRow] = []
    for line in lines[t1 + 1:]:
        tokens = group_numbers(line)
        head = _strip_margin(tokens)
        if head and _fold(head[0]).startswith(("източник", "таблица")):
            break
        split = _split_label(tokens, 6)
        if split is None:
            continue
        label, nums = split
        try:
            row = MzhRow(label=label, holdings=int(nums[0]), colonies=int(nums[1]), harvested=int(nums[2]),
                         avg_colonies=_derived(nums[3]), honey_t=int(nums[4]), yield_kg=_derived(nums[5]),
                         raw=tuple(nums))
        except ValueError as exc:
            raise CollectorError(f"MZH: table 1 row {label!r} {nums} is not holdings/colonies/colonies harvested/"
                                 f"average/honey/yield; nothing stored") from exc
        key = _fold(label)
        if key == "българия" and national is None:
            national = row
        elif key in BG_REGIONS:
            regions[BG_REGIONS[key][0]] = row
        else:
            zones.append(row)                     # the two NUTS 1 zones (labels wrap over two lines)
    if national is None or len(regions) != len(BG_REGIONS):
        raise CollectorError(f"MZH schema drift: table 1 has {'a' if national else 'no'} national row and "
                             f"{len(regions)} of the 6 regions; nothing stored")
    out = MzhTables(year=title_year, title=next(t for t in texts if _MZH_TITLE.search(_fold(t))), national=national,
                    regions=regions, zones=zones)
    t3 = next((i for i, t in enumerate(texts) if _fold(t).startswith(_fold(_MZH_TABLE3))), None)
    if t3 is not None:
        for line in lines[t3 + 1:]:
            tokens = group_numbers(line)
            split = _split_label(tokens, 6)
            if split and _fold(split[0]) == "българия":
                nums = split[1]
                if nums[2].endswith("%") and nums[5].endswith("%") and int(nums[1]) == national.colonies:
                    out.previous_colonies, out.previous_harvested = int(nums[0]), int(nums[3])
                break
    wax = next((m for t in texts if (m := re.search(r"(\d+(?:[.,]\d+)?)\s*тона пчелен восък", _fold(t)))), None)
    out.wax_t = float(wax.group(1).replace(",", ".")) if wax else None
    return out


def check_mzh(t: MzhTables) -> list[str]:
    """The six regions against the national row (honey, colonies, holdings), and the printed averages
    against the counts. Reported, never fixed."""
    out = []
    for attr in ("honey_t", "colonies", "harvested", "holdings"):
        s = sum(getattr(r, attr) for r in t.regions.values())
        if s != getattr(t.national, attr):
            out.append(f"{t.year} {attr}: the six regions add up to {s:,}, Bulgaria is {getattr(t.national, attr):,}")
    n = t.national
    garbled = [r.label for r in (n, *t.regions.values()) if r.avg_colonies is None or r.yield_kg is None]
    if garbled:
        out.append(f"{t.year}: unreadable average/yield cell(s) in table 1 rows {garbled} (kept as published text)")
    if n.harvested and n.yield_kg is not None and abs(n.honey_t * 1000 / n.harvested - n.yield_kg) > 0.051:
        out.append(f"{t.year}: printed yield {n.yield_kg} kg vs {n.honey_t} t / {n.harvested:,} colonies")
    return out


class BgMzhHoneyCollector(Collector):
    key = "bg_mzh_honey"
    name = "Bulgaria – MZH Agrostatistica («Пчеларството в България»): produzione di miele e famiglie d'api"
    name_en = "Bulgaria – MZH Agrostatistics (beekeeping survey bulletin): honey production and bee colonies"
    publisher = "MZH – Министерство на земеделието и храните (Ministry of Agriculture and Food), отдел „Агростатистика“"
    homepage = MZH_LIST_URL
    kind = SourceKind.PDF
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "BGR"
    language = "bg"
    expected_update = "Annuale (bollettino di febbraio sull'anno precedente: 2025 il 27 feb 2026); controllo mensile"
    expected_update_en = "Annual (February bulletin on the previous year: 2025 on 27 Feb 2026); checked monthly"
    expected_max_age_days = 420
    terms_note = (
        "Източник: МЗХ, отдел 'Агростатистика', анкета 'Пчеларството в България' (official survey bulletin, free "
        "publication; cite MZH Agrostatistics). Read from table 1 of the PDF: honey in tonnes as published, bee "
        "colonies on 1 October, colonies harvested, holdings, average yield; six NUTS 2 regions. The bulletin's "
        "sales table (prices to processors, BGN/kg) is not stored."
    )
    # Monthly: 1-3 requests to the data list (~50 KB each); the PDF (~0.7 MB) only for a new bulletin.
    schedule = {"trigger": "cron", "day": 22, "hour": 8, "minute": 5}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        bulletins: list[MzhBulletin] = []
        for page in range(1, MZH_MAX_PAGES + 1):
            bulletins = find_mzh_bulletins(ctx.fetch(mzh_list_url(page), store=False).text)
            if bulletins:
                break
        have_rows = _has_rows(ctx)
        if not bulletins:
            if have_rows:
                _warn_once(ctx, state, "no_bulletin", f"MZH: no beekeeping bulletin on the first {MZH_MAX_PAGES} pages of "
                                                      "the livestock data list; the figures already stored are kept")
                _save_state(ctx, state)
                ctx.checkpoint()
                return
            raise CollectorError(f"MZH: no beekeeping bulletin on the first {MZH_MAX_PAGES} pages of the livestock data "
                                 "list (page changed?); nothing stored")
        newest = bulletins[0]
        if (have_rows and not ctx.force and not _refresh_due(state, MZH_REFRESH_DAYS)
                and state.get("url") == newest.url):
            log.info("[%s] MZH bulletin unchanged (%s)", self.key, newest.url)
            return
        for b in (bulletins if not have_rows or ctx.force else [newest]):
            pdf = ctx.fetch(b.url, title=f"MZH – {b.title}", published_at=b.published)
            if pdf.unchanged and have_rows and not ctx.force:
                log.info("[%s] MZH bulletin %d identical to the one already stored", self.key, b.year)
                continue
            tables = parse_mzh_bulletin(pdf.content)
            if tables.year != b.year:
                raise CollectorError(f"MZH: the bulletin listed for {b.year} is about {tables.year}; nothing stored")
            for msg in check_mzh(tables):
                _warn_once(ctx, state, f"check:{b.url}:{msg}", f"MZH: {msg}; the published figures are stored as is")
            self._store(ctx, b, tables, pdf.raw_document_id)
            ctx.checkpoint()
        state.update({"url": newest.url, "year": newest.year, "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, b: MzhBulletin, t: MzhTables, raw_id: int) -> None:
        def common(year: int) -> dict[str, Any]:
            ps, pe = year_bounds(year)
            return dict(country_iso3="BGR", period_start=ps, period_end=pe, period_label=str(year), frequency="A",
                        data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, published_at=b.published,
                        source_url=b.url, raw_document_id=raw_id or None)

        y = t.year
        base = {"bulletin": b.title, "bulletin_title": t.title, "bulletin_url": b.url, "list_url": MZH_LIST_URL}

        def detail(r: MzhRow) -> dict[str, Any]:
            return {"holdings": r.holdings, "colonies_1_october": r.colonies, "colonies_harvested": r.harvested,
                    "avg_colonies_per_holding": r.avg_colonies, "yield_kg_per_colony": r.yield_kg,
                    "honey_t": r.honey_t, "row_as_published": list(r.raw)}

        n = t.national
        ctx.add_production(
            series_key=f"mzh_bees|BGR|production|{y}", metric="production", value=float(n.honey_t), unit="t",
            extra={**base, **detail(n), "table": "Таблица 1", "row": "България", "value_as_published": n.raw[4],
                   "unit_as_published": "тона", "wax_t": t.wax_t},
            notes=(f"MZH Agrostatistics, beekeeping survey {y}: {n.honey_t:,} t of honey from {n.harvested:,} colonies "
                   f"harvested (table 1, row 'България')."),
            **common(y))
        ctx.add_production(
            series_key=f"mzh_bees|BGR|colonies|{y}", metric="colonies", value=float(n.colonies), unit="number",
            extra={**base, **detail(n), "table": "Таблица 1", "row": "България", "reference_date": f"{y}-10-01",
                   "value_as_published": n.raw[1]},
            notes=f"MZH Agrostatistics: {n.colonies:,} bee colonies on 1 October {y} (table 1, row 'България').",
            **common(y))
        if t.previous_colonies is not None:
            ctx.add_production(
                series_key=f"mzh_bees|BGR|colonies|{y - 1}", metric="colonies", value=float(t.previous_colonies),
                unit="number",
                extra={**base, "table": "Таблица 3", "row": "България", "reference_date": f"{y - 1}-10-01",
                       "colonies_harvested": t.previous_harvested},
                notes=(f"MZH Agrostatistics: {t.previous_colonies:,} bee colonies on 1 October {y - 1}, as given in the "
                       f"{y} bulletin (table 3)."),
                **common(y - 1))
        for code, r in t.regions.items():
            name = next(nm for c, nm in BG_REGIONS.values() if c == code)
            extra = {**base, **detail(r), "region": name, "region_code": code, "region_as_published": r.label,
                     "table": "Таблица 1"}
            ctx.add_production(series_key=f"mzh_bees|{code}|production_by_region|{y}", metric="production_by_region",
                               value=float(r.honey_t), unit="t", extra={**extra, "value_as_published": r.raw[4]},
                               notes=f"MZH Agrostatistics {y}, {r.label}: {r.honey_t:,} t of honey.", **common(y))
            ctx.add_production(series_key=f"mzh_bees|{code}|colonies_by_region|{y}", metric="colonies_by_region",
                               value=float(r.colonies), unit="number", extra={**extra, "value_as_published": r.raw[1]},
                               notes=f"MZH Agrostatistics, {r.label}: {r.colonies:,} bee colonies on 1 October {y}.",
                               **common(y))


# ===========================================================================
# 4) Greece: ELSTAT, Livestock Capital and Production (SPK33), tables 7c and 4 (xlsx)
# ===========================================================================

ELSTAT_PAGE_URL = "https://www.statistics.gr/en/statistics/-/publication/SPK33/-"
ELSTAT_REFRESH_DAYS = 180
_ELSTAT_LINK = re.compile(r'<a[^>]*href="([^"]*documentID=\d+[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
# The 13 regions (NUTS 2) by the English name printed in the last column (`_norm`) -> (code, name).
GR_REGIONS: dict[str, tuple[str, str]] = {
    "region of eastern macedonia and thrace": ("EL51", "Eastern Macedonia and Thrace"),
    "region of central macedonia": ("EL52", "Central Macedonia"), "region of western macedonia": ("EL53", "Western Macedonia"),
    "region of epirus": ("EL54", "Epirus"), "region of thessally": ("EL61", "Thessaly"), "region of thessaly": ("EL61", "Thessaly"),
    "region of ionian islands": ("EL62", "Ionian Islands"), "region of western greece": ("EL63", "Western Greece"),
    "region of central greece": ("EL64", "Central Greece"), "region of peloponnese": ("EL65", "Peloponnese"),
    "region of attica": ("EL30", "Attica"), "region of northern aegean": ("EL41", "North Aegean"),
    "region of southern aegean": ("EL42", "South Aegean"), "region of crete": ("EL43", "Crete"),
}


def find_elstat_tables(page_html: str) -> dict[str, tuple[str, str]]:
    """{"7c": (url, title), "04": (url, title)} from the SPK33 page (the newest reference year's tables)."""
    out: dict[str, tuple[str, str]] = {}
    for m in _ELSTAT_LINK.finditer(page_html):
        title = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        # the page writes "https://www.statistics.gr:443/...": the default port is dropped (httpx sends it without)
        url = re.sub(r"^(https://[^/:]+):443(?=/)", r"\1", html_lib.unescape(m.group(1)))
        n = _norm(title)
        if n.startswith("7c.") and "other primary livestock by-products" in n:
            out.setdefault("7c", (url, title))
        elif n.startswith("04.") and "beehives" in n:
            out.setdefault("04", (url, title))
    return out


@dataclass(frozen=True)
class GrRow:
    label_el: str
    label_en: str
    value: float                                   # honey t | beehives (local + European)
    parts: tuple[float, ...]


@dataclass
class GrTable:
    year: int
    title: str
    unit_note: str
    national: GrRow
    regions: dict[str, GrRow]
    reference_date: str | None = None


def _gr_rows(content: bytes, what: str) -> list[list[Any]]:
    sheets = _workbook_rows(content, what)
    return [list(r) for r in sheets[0][1]] if sheets else []


def _gr_title(rows: list[list[Any]], pattern: str, what: str) -> tuple[str, int]:
    for r in rows[:6]:
        for c in r:
            if isinstance(c, str) and re.search(pattern, _norm(c)):
                year = re.findall(r"(?<!\d)(20\d\d)(?!\d)", c)
                if year:
                    return re.sub(r"\s+", " ", c).strip(), int(year[-1])
    raise CollectorError(f"ELSTAT schema drift: no English '{what}' title with a year; nothing stored")


def _gr_data(rows: list[list[Any]], cols: list[int], what: str) -> tuple[GrRow, dict[str, GrRow]]:
    national = None
    regions: dict[str, GrRow] = {}
    for r in rows:
        if not r or not isinstance(r[0], str):
            continue
        en = next((c for c in reversed(r) if isinstance(c, str) and c.strip()), "")
        key_en = _norm(en)
        if key_en == "greece total" or _fold(r[0]) == _fold("Σύνολο Ελλάδας"):
            target = "national"
        elif key_en in GR_REGIONS:
            target = GR_REGIONS[key_en][0]
        else:
            continue
        parts = [r[c] if c < len(r) else None for c in cols]
        if not all(_is_number(p) for p in parts):
            raise CollectorError(f"ELSTAT: {what} row {r[0]!r} has non-numeric cells {parts}; nothing stored")
        row = GrRow(label_el=r[0].strip(), label_en=en.strip(), value=float(sum(parts)), parts=tuple(float(p) for p in parts))
        if target == "national":
            if national is not None:
                raise CollectorError(f"ELSTAT: two national rows in the {what} table; nothing stored")
            national = row
        else:
            regions[target] = row
    if national is None or len(regions) != 13:
        raise CollectorError(f"ELSTAT schema drift: the {what} table has {'a' if national else 'no'} national row and "
                             f"{len(regions)} of the 13 regions; nothing stored")
    return national, regions


def parse_elstat_honey(content: bytes) -> GrTable:
    """Table 7c: the 'Honey' column (tonnes) of 'Greece Total' and of the 13 regions."""
    rows = _gr_rows(content, "ELSTAT table 7c")
    title, year = _gr_title(rows, r"production of other primary livestock by-products", "Table 7c")
    unit_note = next((c for r in rows[:8] for c in r if isinstance(c, str) and "honey" in _norm(c) and "tons" in _norm(c)), None)
    if unit_note is None:
        raise CollectorError("ELSTAT schema drift: table 7c does not say honey is in tons; nothing stored")
    col = next((i for r in rows[:12] for i, c in enumerate(r) if isinstance(c, str) and _norm(c) == "honey"), None)
    if col is None:
        raise CollectorError("ELSTAT schema drift: table 7c has no 'Honey' column; nothing stored")
    national, regions = _gr_data(rows, [col], "honey (7c)")
    return GrTable(year=year, title=title, unit_note=unit_note.strip(), national=national, regions=regions)


def parse_elstat_beehives(content: bytes) -> GrTable:
    """Table 4: beehives on 31 December, 'Local' + 'European' (published separately, no total)."""
    rows = _gr_rows(content, "ELSTAT table 4")
    title, year = _gr_title(rows, r"table 4\. .*bee", "Table 4")
    hdr = next((r for r in rows[:12] if any(isinstance(c, str) and _norm(c) == "european" for c in r)), None)
    if hdr is None or not any(isinstance(c, str) and "beehive" in _norm(c) for r in rows[:12] for c in r):
        raise CollectorError("ELSTAT schema drift: table 4 has no 'Beehives' 'Local' / 'European' columns; nothing stored")
    cols = [i for i, c in enumerate(hdr) if isinstance(c, str) and _norm(c) in ("local", "european")]
    if len(cols) != 2:
        raise CollectorError(f"ELSTAT schema drift: table 4 beehive columns {hdr}; nothing stored")
    national, regions = _gr_data(rows, cols, "beehives (4)")
    ref = re.search(r"on (\d{1,2})(?:st|nd|rd|th)? december (\d{4})", _norm(title))
    return GrTable(year=year, title=title, unit_note="number of beehives", national=national, regions=regions,
                   reference_date=f"{ref.group(2)}-12-{int(ref.group(1)):02d}" if ref else None)


class GrElstatHoneyCollector(Collector):
    key = "gr_elstat_honey"
    name = "Grecia – ELSTAT (Patrimonio zootecnico e produzione): produzione di miele e alveari, nazionale e per regione"
    name_en = "Greece – ELSTAT (Livestock Capital and Production): honey production and beehives, national and by region"
    publisher = "ELSTAT – Ελληνική Στατιστική Αρχή (Hellenic Statistical Authority), annual agricultural survey"
    homepage = ELSTAT_PAGE_URL
    kind = SourceKind.BULK_FILE
    reliability = Reliability.OFFICIAL
    category = "production"
    country_iso3 = "GRC"
    language = "en"
    expected_update = "Annuale (risultati definitivi, anno Y circa due anni dopo: 2024 disponibile a nov 2026); controllo mensile"
    expected_update_en = "Annual (final results, year Y about two years later: 2024 available in Nov 2026); checked monthly"
    expected_max_age_days = 900
    terms_note = (
        "Source: ELSTAT, 'Livestock Capital and Production' (SPK33), final results of the annual agricultural statistical "
        "survey: table 7c (honey, tonnes) and table 4 (beehives on 31 December). Free reuse with citation of ELSTAT. "
        "Beehives = 'Local' + 'European' hives (published separately, no total; both kept). Values stored as published "
        "(honey rounded to the kg)."
    )
    # Monthly: one ~150 KB request to the publication page; the two tables only when their links change.
    schedule = {"trigger": "cron", "day": 22, "hour": 8, "minute": 20}
    order = 72

    def collect(self, ctx: CollectContext) -> None:
        state = _load_state(ctx)
        page = ctx.fetch(ELSTAT_PAGE_URL, store=False)
        links = find_elstat_tables(page.text)
        if "7c" not in links:
            raise CollectorError("ELSTAT: no table '7c. Production of other primary livestock by-products' on the SPK33 "
                                 "page (page changed?); nothing stored")
        signature = "|".join(links[k][0] for k in sorted(links))
        have_rows = _has_rows(ctx)
        if have_rows and not ctx.force and not _refresh_due(state, ELSTAT_REFRESH_DAYS) and state.get("links") == signature:
            log.info("[%s] ELSTAT tables unchanged", self.key)
            return
        honey_doc = ctx.fetch(links["7c"][0], title=f"ELSTAT SPK33 – {links['7c'][1]}")
        honey = parse_elstat_honey(honey_doc.content)
        hives = hives_doc = None
        if "04" in links:
            hives_doc = ctx.fetch(links["04"][0], title=f"ELSTAT SPK33 – {links['04'][1]}")
            hives = parse_elstat_beehives(hives_doc.content)
            if hives.year != honey.year:
                ctx.warn(f"ELSTAT: table 4 is for {hives.year}, table 7c for {honey.year}; beehives not stored this run")
                hives = None
        else:
            _warn_once(ctx, state, "no_table_4", "ELSTAT: no table '04. ... beehives' on the SPK33 page; honey only")
        for table, what in ((honey, "honey"), (hives, "beehives")):
            if table is None:
                continue
            s = sum(r.value for r in table.regions.values())
            if abs(s - table.national.value) > (0.01 if what == "honey" else 0.5):
                _warn_once(ctx, state, f"sums:{table.title}",
                           f"ELSTAT {table.year} {what}: the 13 regions add up to {s:,.3f}, Greece Total is "
                           f"{table.national.value:,.3f}; the published total is stored as is")
        self._store(ctx, honey, links["7c"][0], honey_doc.raw_document_id, metric="production")
        if hives is not None and hives_doc is not None:
            self._store(ctx, hives, links["04"][0], hives_doc.raw_document_id, metric="colonies")
        state.update({"links": signature, "year": honey.year, "pulled_at": utcnow().isoformat(timespec="seconds")})
        _save_state(ctx, state)
        ctx.checkpoint()

    def _store(self, ctx: CollectContext, t: GrTable, url: str, raw_id: int, *, metric: str) -> None:
        ps, pe = year_bounds(t.year)
        common: dict[str, Any] = dict(
            country_iso3="GRC", period_start=ps, period_end=pe, period_label=str(t.year), frequency="A",
            data_status=DataStatus.PUBLISHED, reliability=Reliability.OFFICIAL, published_at=None, source_url=url,
            raw_document_id=raw_id or None)
        honey = metric == "production"
        unit, digits = ("t", 3) if honey else ("number", 0)
        base = {"table": t.title, "publication": "ELSTAT SPK33 Livestock Capital and Production", "page_url": ELSTAT_PAGE_URL,
                "unit_as_published": t.unit_note, "reference_date": t.reference_date,
                "release_date_note": "ELSTAT's table files carry no release date; left empty"}

        def parts(r: GrRow) -> dict[str, Any]:
            return {"value_as_published": r.parts[0]} if honey else {"local_hives": r.parts[0], "european_hives": r.parts[1],
                                                                       "total_method": "Local + European beehives"}

        n = t.national
        ctx.add_production(
            series_key=f"elstat_spk33|GRC|{metric}|{t.year}", metric=metric, value=round(n.value, digits), unit=unit,
            extra={**base, "row": n.label_en, **parts(n)},
            notes=(f"ELSTAT '{t.title}': Greece Total "
                   + (f"{n.value:,.3f} t of honey." if honey
                      else f"{n.parts[0]:,.0f} local + {n.parts[1]:,.0f} European = {n.value:,.0f} beehives.")),
            **common)
        region_metric = f"{metric}_by_region"
        for code, r in t.regions.items():
            name = next(nm for c, nm in GR_REGIONS.values() if c == code)
            ctx.add_production(
                series_key=f"elstat_spk33|{code}|{region_metric}|{t.year}", metric=region_metric,
                value=round(r.value, digits), unit=unit,
                extra={**base, "region": name, "region_code": code, "region_as_published": r.label_en,
                       "region_el": r.label_el, **parts(r)},
                notes=f"ELSTAT '{t.title}', {r.label_en}: " + (f"{r.value:,.3f} t of honey." if honey
                                                              else f"{r.value:,.0f} beehives."),
                **common)


__all__ = [
    "BG_REGIONS",
    "ELSTAT_PAGE_URL",
    "ES_PAGE_URL",
    "ES_REGIONS",
    "FNMT_G2R_CROSS_PEM",
    "GR_REGIONS",
    "KSH_TABLE_URL",
    "MZH_LIST_URL",
    "BgMzhHoneyCollector",
    "EsMapaHoneyCollector",
    "EsRow",
    "EsTable",
    "EsWorkbook",
    "GrElstatHoneyCollector",
    "GrTable",
    "HuKshHoneyCollector",
    "KshTable",
    "MzhBulletin",
    "MzhTables",
    "check_es_workbook",
    "check_mzh",
    "es_published",
    "find_elstat_tables",
    "find_es_files",
    "find_mzh_bulletins",
    "group_numbers",
    "mapa_ssl_context",
    "mzh_list_url",
    "parse_elstat_beehives",
    "parse_elstat_honey",
    "parse_es_sheet",
    "parse_es_workbook",
    "parse_ksh_table",
    "parse_mzh_bulletin",
    "parse_mzh_words",
    "pdf_page_words",
    "word_lines",
]
