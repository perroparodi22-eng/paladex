"""FAOSTAT collector (honey production, beehives, producer prices, trade).

Fixtures are RECONSTRUCTED from documentation (see tests/fixtures/faostat/README.md); values are
illustrative. The bulk ZIPs are built at test time from the committed CSV files.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from paladex.api.common import get_setting
from paladex.collectors import faostat as fs
from paladex.collectors.base import CollectorError
from paladex.enums import DataStatus, PriceType
from paladex.models import (
    PriceObservation,
    ProductionStat,
    RawDocument,
    TradeFlowObservation,
)

FIX = Path(__file__).parent / "fixtures" / "faostat"
BULK = "https://bulks-faostat.fao.org/production/"
CATALOGUE = BULK + "datasets_E.json"
QCL_ZIP = BULK + "Production_Crops_Livestock_E_All_Data_(Normalized).zip"
PP_ZIP = BULK + "Prices_E_All_Data_(Normalized).zip"
TCL_ZIP = BULK + "Trade_CropsLivestock_E_All_Data_(Normalized).zip"
API = "https://faostatservices.fao.org/api/v1"
NAMES = {"QCL": "Production_Crops_Livestock", "PP": "Prices", "TCL": "Trade_CropsLivestock"}
USER, PASSWORD = "analyst@example.org", "s3cret-pass-XYZ"


def table(dataset: str) -> bytes:
    return (FIX / "bulk" / f"{NAMES[dataset]}_E_All_Data_(Normalized).csv").read_bytes()


def make_zip(dataset: str, csv_bytes: bytes | None = None, *, member: str | None = None) -> bytes:
    """A bulk ZIP as FAOSTAT ships it: the normalized table plus a small code list."""
    name = NAMES[dataset]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member or f"{name}_E_All_Data_(Normalized).csv", table(dataset) if csv_bytes is None else csv_bytes)
        zf.writestr(f"{name}_E_Flags.csv", (FIX / "bulk" / "Flags.csv").read_bytes())
    return buf.getvalue()


def catalogue(**date_updates: str) -> bytes:
    doc = json.loads((FIX / "datasets_E.json").read_bytes())
    for ds in doc["Datasets"]["Dataset"]:
        if ds["DatasetCode"] in date_updates:
            ds["DateUpdate"] = date_updates[ds["DatasetCode"]]
    return json.dumps(doc).encode()


def bulk_routes(cat: bytes | None = None, **zips: bytes) -> dict:
    routes = {CATALOGUE: cat or (FIX / "datasets_E.json").read_bytes(),
              QCL_ZIP: make_zip("QCL"), PP_ZIP: make_zip("PP"), TCL_ZIP: make_zip("TCL")}
    routes.update({{"QCL": QCL_ZIP, "PP": PP_ZIP, "TCL": TCL_ZIP}[k]: v for k, v in zips.items()})
    return routes


def A(name: str) -> bytes:
    return (FIX / "api" / name).read_bytes()


def api_routes(**over) -> dict:
    routes = {
        CATALOGUE: (FIX / "datasets_E.json").read_bytes(),
        ("POST", API + "/auth/login"): A("login.json"),
        API + "/en/data/QCL?item=1182&element=2510&": A("QCL_production.json"),
        API + "/en/data/QCL?item=1181&element=2111&": A("QCL_bees.json"),
        # PP.json holds exactly API_PAGE_SIZE (3) rows, so page 2 is requested: it is empty.
        r"^https://faostatservices\.fao\.org/api/v1/en/data/PP\?.*&page_number=1$": A("PP.json"),
        r"^https://faostatservices\.fao\.org/api/v1/en/data/PP\?.*&page_number=2$": A("empty.json"),
        r"^https://faostatservices\.fao\.org/api/v1/en/data/TCL\?.*&page_number=1$": A("TCL_page1.json"),
        r"^https://faostatservices\.fao\.org/api/v1/en/data/TCL\?.*&page_number=2$": A("TCL_page2.json"),
        API + "/en/dimensions/TM/": A("TM_dimensions.json"),
        API + "/en/codes/element/TM": A("TM_element_codes.json"),
        API + "/en/data/TM?reporterarea=106&": A("TM_reporter_106.json"),
        API + "/en/data/TM?reporterarea=9&": A("empty.json"),
    }
    routes.update(over)
    return routes


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Pin today, force the keyless bulk path (even if a developer .env holds an account) and start
    with an empty token cache."""
    from paladex import config

    monkeypatch.setenv("PALADEX_FAOSTAT_USERNAME", "")
    monkeypatch.setenv("PALADEX_FAOSTAT_PASSWORD", "")
    config.get_settings.cache_clear()
    monkeypatch.setattr(fs, "_today", lambda: date(2026, 11, 2))
    fs._TOKEN_CACHE.clear()
    yield
    fs._TOKEN_CACHE.clear()


@pytest.fixture()
def with_account(db, monkeypatch):
    from paladex import config

    monkeypatch.setenv("PALADEX_FAOSTAT_USERNAME", USER)
    monkeypatch.setenv("PALADEX_FAOSTAT_PASSWORD", PASSWORD)
    config.get_settings.cache_clear()
    monkeypatch.setattr(fs, "TM_REPORTERS", ("ITA", "ARG"))
    monkeypatch.setattr(fs, "API_PAGE_SIZE", 3)


@pytest.fixture()
def sent(monkeypatch):
    """Every request that leaves the httpx client."""
    requests: list[httpx.Request] = []
    original = httpx.Client.send

    def spy(self, request, *args, **kwargs):
        requests.append(request)
        return original(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", spy)
    return requests


def _prod(s, iso3: str, metric: str, year: int) -> ProductionStat | None:
    return s.scalars(select(ProductionStat).where(
        ProductionStat.country_iso3 == iso3, ProductionStat.metric == metric,
        ProductionStat.period_label == str(year), ProductionStat.is_current.is_(True))).first()


def _count(s, model) -> int:
    return s.scalar(select(func.count(model.id))) or 0


# =============================================================================================
# Pure helpers
# =============================================================================================


def test_parse_catalogue_shapes():
    cat = fs.parse_catalogue((FIX / "datasets_E.json").read_bytes())
    assert {"QCL", "PP", "TCL", "TM", "RL"} <= set(cat)
    assert cat["QCL"].date_update == "2025-12-31T00:00:00"
    assert cat["QCL"].published == date(2025, 12, 31)
    assert cat["TCL"].file_location == TCL_ZIP and cat["RL"].file_rows == 421850
    # a single dataset converted from XML is an object, not a list
    one = {"Datasets": {"Dataset": {"DatasetCode": "QCL", "DateUpdate": "2026-12-18T00:00:00", "FileLocation": QCL_ZIP}}}
    assert fs.parse_catalogue(json.dumps(one).encode())["QCL"].published == date(2026, 12, 18)
    # schema drift fails loudly
    for bad in (b"<html>", b'{"datasets": []}', b'{"Datasets": {"Dataset": []}}',
                json.dumps({"Datasets": {"Dataset": [{"DatasetCode": "QCL"}]}}).encode()):
        with pytest.raises(CollectorError):
            fs.parse_catalogue(bad)


def test_flag_mapping():
    assert fs.flag_status("A") == (DataStatus.PUBLISHED.value, True)
    assert fs.flag_status("X") == (DataStatus.PUBLISHED.value, True)       # international organisation
    assert fs.flag_status("") == (DataStatus.PUBLISHED.value, True)
    assert fs.flag_status("P") == (DataStatus.PROVISIONAL.value, True)
    for f in ("E", "I", "T", "Im", "*"):
        assert fs.flag_status(f) == (DataStatus.ESTIMATE.value, True), f
    assert fs.flag_status("M") == (None, True)                             # missing: skip the row
    assert fs.flag_status("Z") == (DataStatus.ESTIMATE.value, False)       # unknown: never "official"
    assert fs.least_firm("published", "estimate", "provisional") == "estimate"
    assert fs.least_firm("published", "provisional") == "provisional"
    assert fs.least_firm() == "published"


def test_area_resolution_china_and_aggregates():
    china = fs.resolve_area("41", "'156", "China, mainland")
    assert (china.iso3, china.outcome, china.canonical) == ("CHN", "ok", True)
    for code, name in (("351", "China"), ("265", "China (excluding intra-trade)"), ("5000", "World"),
                       ("5707", "European Union (27)"), ("57070", "EU (excluding intra-trade)"), ("5000>", "World > (List)")):
        assert fs.resolve_area(code, None, name).outcome == "aggregate", code
    assert fs.resolve_area("9", "'032", "Argentina").iso3 == "ARG"            # M49 with leading apostrophe
    assert fs.resolve_area("231", None, "United States of America").iso3 == "USA"   # API rows: FAO code
    smn = fs.resolve_area("186", "'891", "Serbia and Montenegro")            # predecessor, per research
    assert (smn.iso3, smn.canonical) == ("SRB", False)
    assert fs.resolve_area("178", "'232", "Eritrea").outcome == "unmapped"
    assert fs.resolve_area("106", "'032", "Italy").outcome == "conflict"      # M49 and FAO code disagree
    assert fs.resolve_area("", None, "Viet Nam").iso3 == "VNM"


def test_units_currency_and_elements():
    assert fs.parse_value("65286.000000") == 65286.0
    assert fs.parse_value("") is None and fs.parse_value(None) is None
    for bad in ("n.a.", "12,5", "nan"):
        with pytest.raises(ValueError):
            fs.parse_value(bad)
    assert fs.local_currency("UKR", 2022) == "UAH"
    assert fs.local_currency("UKR", 1995) is None              # before the hryvnia: never guessed
    assert fs.local_currency("ITA", 2001) is None and fs.local_currency("ITA", 2002) == "EUR"
    assert (fs.local_currency("BGR", 2025), fs.local_currency("BGR", 2026)) == ("BGN", "EUR")
    assert fs.local_currency("ZMB", 2022) is None
    assert fs.classify_trade_element("5622", "") == ("import", "value")
    assert fs.classify_trade_element("9999", "Export Quantity") == ("export", "quantity")
    assert fs.classify_trade_element("5110", "Area") is None


def test_build_records_conversions():
    issues = fs.Issues()

    def row(**kw):
        base = {"dataset": "TCL", "area_code": "106", "area": "Italy", "item_code": "1182", "element_code": "5610",
                "element": "Import quantity", "year": 2023, "unit": "t", "value": 25000.0, "value_raw": "25000",
                "flag": "A", "source_url": "u", "area_m49": "'380"}
        base.update(kw)
        return fs.FaoRow(**base)

    trade = fs.build_trade([row(), row(element_code="5622", element="Import value", unit="1000 USD", value=95000.0,
                                       flag="E")], "TCL", issues)
    assert len(trade) == 1
    t = trade[0]
    assert (t.reporter_iso3, t.partner_iso3, t.flow) == ("ITA", "WLD", "import")
    assert t.net_weight_kg == 25_000_000 and t.value_usd == 95_000_000
    assert t.status == DataStatus.ESTIMATE.value                  # least firm of the two flags
    prices = fs.build_prices([row(dataset="PP", element_code="5532", element="Producer Price (USD/tonne)",
                                  unit="USD", value=5100.0)], issues)
    assert (prices[0].currency, prices[0].value, prices[0].basis) == ("USD", 5100.0, "USD")
    prod = fs.build_production([row(dataset="QCL", element_code="5510", element="Production", value=23000.0),
                                row(dataset="QCL", item_code="1181", element_code="5111", element="Stocks",
                                    unit="1000 No", value=1.6)], issues)
    got = {p.metric: (p.value, p.unit) for p in prod}
    assert got == {"production": (23000.0, "t"), "colonies": (1600.0, "number")}


# =============================================================================================
# Bulk ZIP streaming
# =============================================================================================


def test_read_bulk_zip_filters_items(tmp_path):
    path = tmp_path / "qcl.zip"
    path.write_bytes(make_zip("QCL"))
    ex = fs.read_bulk_zip(path, {"1182", "1181"})
    assert ex.member == "Production_Crops_Livestock_E_All_Data_(Normalized).csv"
    assert ex.rows_read == 21 and len(ex.rows) == 19                     # wheat and beeswax dropped
    assert ex.encoding == "utf-8-sig" and "Area Code (M49)" in ex.header
    rows, bad = fs.bulk_rows(ex, "QCL", QCL_ZIP)
    assert len(bad) == 1 and "n.a." in bad[0]                             # Brazil: unreadable value
    arg = next(r for r in rows if r.area == "Argentina" and r.year == 2023 and r.item_code == "1182")
    assert (arg.value, arg.unit, arg.flag, arg.area_m49) == (72500.0, "t", "E", "'032")
    mexico = next(r for r in rows if r.area == "Mexico")
    assert mexico.value is None and mexico.flag == "M"
    # the archived extract is a deterministic ZIP holding only the kept rows
    blob = ex.to_zip_bytes()
    assert blob == ex.to_zip_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    assert "Natural honey" in text and "Wheat" not in text


def test_read_bulk_zip_latin1_and_drift(tmp_path):
    latin = (table("QCL").decode().replace('"Viet Nam"', '"Côte d\'Ivoire"')).encode("latin-1")
    p = tmp_path / "latin.zip"
    p.write_bytes(make_zip("QCL", latin))
    ex = fs.read_bulk_zip(p, {"1182"})
    assert ex.encoding == "latin-1" and any("Côte d'Ivoire" in r for r in ex.rows)

    drift = table("QCL").replace(b'"Item Code",', b'"Item Code (FAO)",', 1)
    p.write_bytes(make_zip("QCL", drift))
    with pytest.raises(CollectorError, match="missing column"):
        fs.read_bulk_zip(p, {"1182"})
    p.write_bytes(make_zip("QCL", member="something_else.csv"))
    with pytest.raises(CollectorError, match="Normalized"):
        fs.read_bulk_zip(p, {"1182"})
    p.write_bytes(b"<html>not a zip</html>")
    with pytest.raises(CollectorError, match="ZIP"):
        fs.read_bulk_zip(p, {"1182"})


def test_parse_api_rows_drift():
    payload = json.loads(A("QCL_production.json"))
    rows, bad = fs.parse_api_rows(payload, "QCL", "u")
    assert len(rows) == 4 and not bad and rows[0].value == 72500.0
    for r in payload["data"]:
        r.pop("Area Code")
    with pytest.raises(CollectorError, match="format changed"):
        fs.parse_api_rows(payload, "QCL", "u")
    with pytest.raises(CollectorError, match="no 'data' list"):
        fs.parse_api_rows({"message": "Please add at least one filter."}, "QCL", "u")


# =============================================================================================
# End to end: bulk path (default, no account)
# =============================================================================================


def test_bulk_end_to_end(run_with_routes, session_factory, sent):
    res = run_with_routes("faostat", bulk_routes())
    assert res["status"] == "partial", res                     # data stored, with warnings below
    warnings = " | ".join(res["warnings"])
    assert "Eritrea (178)" in warnings and "not in Paladex's country table" in warnings
    assert "unknown flag 'Z'" in warnings
    assert "'1000 EUR'" in warnings
    assert "n.a." in warnings and "non-positive price" in warnings
    hosts = {r.url.host for r in sent}
    assert hosts == {"bulks-faostat.fao.org"}                  # never the API without an account
    assert not any("Detailed" in str(r.url) for r in sent)     # TM ZIP (~410 MB) is skipped

    with session_factory() as s:
        # --- production / colonies
        assert _count(s, ProductionStat) == 12
        arg = _prod(s, "ARG", "production", 2023)
        assert (arg.value, arg.unit, arg.flag_raw, arg.data_status) == (72500.0, "t", "E", "estimate")
        assert arg.published_at == date(2025, 12, 31) and arg.source_url == QCL_ZIP
        assert arg.reliability == "official" and arg.frequency == "A"
        assert (arg.period_start, arg.period_end) == (date(2023, 1, 1), date(2023, 12, 31))
        assert arg.extra["fao_area_code"] == "9" and arg.extra["fao_m49"] == "032" and arg.extra["access"] == "bulk"
        assert _prod(s, "ARG", "production", 2022).data_status == "published"
        assert _prod(s, "ARG", "production", 1990) is None                 # before MIN_YEAR
        chn = _prod(s, "CHN", "production", 2023)
        assert chn.value == 480000.0 and chn.extra["fao_area_code"] == "41"   # mainland, never 351
        assert _prod(s, "CHN", "production", 2022).data_status == "estimate"  # imputed
        assert _prod(s, "ITA", "production", 2023).extra["fao_note"] == "Reconstructed fixture note"
        col = _prod(s, "ITA", "colonies", 2023)
        assert (col.value, col.unit, col.data_status, col.flag_raw) == (1600000.0, "number", "published", "X")
        assert _prod(s, "SRB", "production", 2005).extra["fao_area"] == "Serbia and Montenegro"
        assert _prod(s, "SRB", "production", 2023).data_status == "provisional"
        assert _prod(s, "VNM", "production", 2023).data_status == "estimate"  # unknown flag Z
        for missing in ("MEX", "BRA", "WLD", "EU27"):
            assert s.scalar(select(func.count(ProductionStat.id)).where(ProductionStat.country_iso3 == missing)) == 0

        # --- producer prices (USD/t -> per kg; LCU only as a fallback)
        prices = {(p.origin_iso3, p.period_label): p for p in s.scalars(select(PriceObservation))}
        assert set(prices) == {("ARG", "2023"), ("ITA", "2022"), ("ITA", "2023"), ("UKR", "2022"), ("CHN", "2023")}
        p = prices[("ARG", "2023")]
        assert p.price_type == PriceType.PRODUCER.value and p.variety == "unspecified"
        assert (p.price_value, p.currency, p.unit, p.price_per_kg, p.usd_per_kg) == (2450.0, "USD", "t", 2.45, 2.45)
        assert p.market_iso3 == "ARG" and p.frequency == "A" and p.published_at == date(2025, 8, 5)
        assert p.source_url == PP_ZIP and p.series_key == "producer|faostat|PP|ARG|2023"
        assert p.extra["price_basis"] == "USD" and p.extra["flag"] == "A"
        ukr = prices[("UKR", "2022")]
        assert (ukr.currency, ukr.price_per_kg, ukr.data_status) == ("UAH", 52.0, "estimate")
        assert ukr.extra["price_basis"] == "LCU" and "LCU" in ukr.notes
        assert prices[("ITA", "2023")].data_status == "estimate"
        assert prices[("CHN", "2023")].price_value == 3200.0              # 41, not the 351 aggregate

        # --- trade (TCL: reporter x World)
        trade = {(t.reporter_iso3, t.flow): t for t in s.scalars(select(TradeFlowObservation))}
        assert set(trade) == {("ARG", "export"), ("ITA", "import"), ("ITA", "export"), ("CHN", "export"),
                              ("UKR", "export")}
        a = trade[("ARG", "export")]
        assert (a.partner_iso3, a.net_weight_kg, a.value, a.currency) == ("WLD", 70_000_000, 165_000_000, "USD")
        assert a.unit_value_per_kg == round(165_000_000 / 70_000_000, 4) and a.hs_code == "0409"
        assert a.published_at == date(2025, 11, 14) and a.source_url == TCL_ZIP and a.frequency == "A"
        i = trade[("ITA", "import")]
        assert i.data_status == "estimate" and i.extra["flag_value"] == "E" and i.extra["flag_quantity"] == "A"
        assert trade[("CHN", "export")].net_weight_kg == 140_000_000          # mainland only
        u = trade[("UKR", "export")]
        assert u.net_weight_kg == 52_000_000 and u.value is None              # 1000 EUR refused, quantity kept

        # --- bookkeeping: DateUpdate per dataset, raw extracts archived
        assert get_setting(s, "faostat_dateupdate_QCL") == "2025-12-31T00:00:00"
        assert get_setting(s, "faostat_dateupdate_PP") == "2025-08-05T00:00:00"
        assert get_setting(s, "faostat_dateupdate_TCL") == "2025-11-14T00:00:00"
        assert get_setting(s, "faostat_dateupdate_TM") is None
        raw = s.get(RawDocument, arg.raw_document_id)
        assert raw.url == QCL_ZIP and raw.path.endswith(".zip") and raw.published_at == date(2025, 12, 31)
        from paladex.config import get_settings

        with zipfile.ZipFile(get_settings().raw_dir / raw.path) as zf:
            assert b"Wheat" not in zf.read(zf.namelist()[0])


def test_change_detection_downloads_only_changed_datasets(run_with_routes, session_factory, sent):
    assert run_with_routes("faostat", bulk_routes())["new"] > 0
    first = len(sent)

    # Same catalogue: nothing is downloaded (the ZIP URLs are not even routed here).
    res = run_with_routes("faostat", {CATALOGUE: (FIX / "datasets_E.json").read_bytes()})
    assert res["status"] == "no_change", res
    assert [str(r.url) for r in sent[first:]] == [CATALOGUE]

    # New QCL release with one revised value: only the QCL ZIP is fetched; history is kept.
    revised = table("QCL").replace(b'"2023","2023","t","72500.000000","E"', b'"2023","2023","t","73000.000000","A"')
    mark = len(sent)
    res = run_with_routes("faostat", {CATALOGUE: catalogue(QCL="2026-12-18T00:00:00"), QCL_ZIP: make_zip("QCL", revised)})
    assert res["revised"] == 1 and res["new"] == 0, res
    assert [str(r.url) for r in sent[mark:]] == [CATALOGUE, QCL_ZIP]
    with session_factory() as s:
        rows = s.scalars(select(ProductionStat).where(ProductionStat.series_key == "faostat|QCL|ARG|production|2023")
                         .order_by(ProductionStat.revision)).all()
        assert [(r.value, r.is_current, r.data_status) for r in rows] == [
            (72500.0, False, "estimate"), (73000.0, True, "published")]
        assert rows[1].published_at == date(2026, 12, 18) and rows[1].supersedes_id == rows[0].id
        assert get_setting(s, "faostat_dateupdate_QCL") == "2026-12-18T00:00:00"
        assert get_setting(s, "faostat_dateupdate_PP") == "2025-08-05T00:00:00"


def test_forced_rerun_is_idempotent(run_with_routes, session_factory):
    run_with_routes("faostat", bulk_routes())
    with session_factory() as s:
        before = (_count(s, ProductionStat), _count(s, PriceObservation), _count(s, TradeFlowObservation))
    res = run_with_routes("faostat", bulk_routes(), force=True)
    assert (res["new"], res["revised"]) == (0, 0), res
    assert res["seen"] == sum(before)
    with session_factory() as s:
        assert (_count(s, ProductionStat), _count(s, PriceObservation), _count(s, TradeFlowObservation)) == before


def test_schema_drift_fails_loudly_and_keeps_other_datasets(run_with_routes, session_factory, sent):
    drift = table("TCL").replace(b'"Item Code",', b'"Item Code (FAO)",', 1)
    res = run_with_routes("faostat", bulk_routes(TCL=make_zip("TCL", drift)))
    assert res["status"] == "failed"
    assert "TCL" in res["error"] and "missing column" in res["error"]
    with session_factory() as s:
        assert _count(s, ProductionStat) == 12 and _count(s, PriceObservation) == 5   # checkpointed before
        assert _count(s, TradeFlowObservation) == 0
        assert get_setting(s, "faostat_dateupdate_TCL") is None                      # retried next run
        assert get_setting(s, "faostat_dateupdate_QCL") == "2025-12-31T00:00:00"
    mark = len(sent)
    res = run_with_routes("faostat", bulk_routes())
    assert [str(r.url) for r in sent[mark:]] == [CATALOGUE, TCL_ZIP]
    assert res["new"] == 5


def test_whole_catalogue_drift_fails(run_with_routes):
    res = run_with_routes("faostat", {CATALOGUE: b'{"datasets": {"items": []}}'})
    assert res["status"] == "failed" and "catalogue format changed" in res["error"]


# =============================================================================================
# Token API path (optional account)
# =============================================================================================


def test_token_api_path(with_account, run_with_routes, session_factory, sent):
    res = run_with_routes("faostat", api_routes())
    assert res["status"] == "partial", res               # Eritrea (TM partner) is outside the country table
    assert not any("zip" in str(r.url).lower() for r in sent)           # no bulk ZIP with an account
    logins = [r for r in sent if r.url.path.endswith("/auth/login")]
    assert len(logins) == 1                                              # token cached for the run
    assert logins[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    api_calls = [r for r in sent if r.url.host == "faostatservices.fao.org" and "/auth/" not in r.url.path]
    assert api_calls and all(r.headers["authorization"] == "Bearer test-access-token-0001" for r in api_calls)
    assert all("authorization" not in r.headers for r in sent if r.url.host == "bulks-faostat.fao.org")
    qcl = next(r for r in api_calls if "/data/QCL" in r.url.path)
    assert "year=1991,1992," in str(qcl.url) and ",2025&" in str(qcl.url)   # first load: full window
    assert any("page_number=2" in str(r.url) for r in api_calls if "/data/TCL" in r.url.path)

    with session_factory() as s:
        docs = s.scalars(select(RawDocument)).all()
        for d in docs:                                     # credentials and tokens are never archived
            assert PASSWORD not in d.url and USER not in d.url and "test-access-token" not in d.url
        assert _prod(s, "ARG", "production", 2023).extra["access"] == "api"
        assert _prod(s, "CHN", "production", 2023).value == 480000.0
        assert _prod(s, "ARG", "colonies", 2023).value == 3_100_000
        assert s.scalar(select(func.count(ProductionStat.id)).where(ProductionStat.country_iso3 == "WLD")) == 0
        prices = {(p.origin_iso3, p.period_label): (p.currency, p.price_value) for p in s.scalars(select(PriceObservation))}
        assert prices == {("ARG", "2023"): ("USD", 2450.0), ("UKR", "2022"): ("UAH", 52000.0)}
        tcl = {(t.reporter_iso3, t.flow): t for t in s.scalars(select(TradeFlowObservation).where(
            TradeFlowObservation.partner_iso3 == "WLD"))}
        assert tcl[("ITA", "import")].value == 95_000_000                 # from page 2
        assert tcl[("ITA", "import")].source_url.startswith(API + "/en/data/TCL?item=1182&element=2610,2620,2910,2920&")
        assert "page_number" not in tcl[("ITA", "import")].source_url
        tm = {t.partner_iso3: t for t in s.scalars(select(TradeFlowObservation).where(
            TradeFlowObservation.series_key.like("faostat|TM|%")))}
        assert set(tm) == {"ARG", "UKR", "CHN"}                           # no 351 aggregate, no Eritrea
        assert (tm["ARG"].reporter_iso3, tm["ARG"].flow) == ("ITA", "import")
        assert (tm["ARG"].net_weight_kg, tm["ARG"].value) == (4_200_000, 12_600_000)
        assert tm["UKR"].data_status == "estimate" and tm["CHN"].extra["fao_partner_code"] == "41"
        assert tm["ARG"].series_key == "faostat|TM|import|ITA|ARG|2023"
        assert tm["ARG"].source_url.startswith(API + "/en/data/TM?reporterarea=106&item=1182&")
        for code in ("QCL", "PP", "TCL", "TM"):
            assert get_setting(s, f"faostat_dateupdate_{code}") is not None

    mark = len(sent)
    res = run_with_routes("faostat", api_routes())
    assert res["status"] == "no_change"
    assert [str(r.url) for r in sent[mark:]] == [CATALOGUE]             # unchanged: no login, no query


def test_token_api_relogin_once_on_401(with_account, db, session_factory, monkeypatch):
    from paladex.collectors import base
    from paladex.collectors.runner import run_collector

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    monkeypatch.setattr(fs, "DATASETS", ("QCL",))
    with respx.mock(assert_all_called=False) as mock:
        mock.get(CATALOGUE).mock(return_value=httpx.Response(200, content=(FIX / "datasets_E.json").read_bytes()))
        login = mock.post(API + "/auth/login").mock(return_value=httpx.Response(200, content=A("login.json")))
        prod = mock.get(url__startswith=API + "/en/data/QCL?item=1182").mock(side_effect=[
            httpx.Response(403, json={"message": "Authentication Failed"}),
            httpx.Response(200, content=A("QCL_production.json"))])
        mock.get(url__startswith=API + "/en/data/QCL?item=1181").mock(
            return_value=httpx.Response(200, content=A("QCL_bees.json")))
        mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
        with httpx.Client() as client:
            res = run_collector("faostat", trigger="test", client=client)
    assert res["status"] == "success", res
    assert login.call_count == 2 and prod.call_count == 2
    with session_factory() as s:
        assert _prod(s, "ARG", "production", 2023).value == 72500.0
        # the refused answer is not archived; the good one is
        assert s.scalar(select(func.count(RawDocument.id)).where(RawDocument.url.like("%/data/QCL?item=1182%"))) == 1


def test_login_refused_falls_back_to_bulk(with_account, run_with_routes, session_factory, sent):
    routes = bulk_routes()
    routes[("POST", API + "/auth/login")] = (400, A("login_refused.json"), "application/x-amz-json-1.1")
    res = run_with_routes("faostat", routes)
    assert res["status"] == "partial"
    fallback = [w for w in res["warnings"] if "public bulk downloads" in w]
    assert len(fallback) == 1 and "NotAuthorizedException" in fallback[0]
    assert all(PASSWORD not in w and USER not in w for w in res["warnings"])
    assert {str(r.url) for r in sent if r.url.host == "bulks-faostat.fao.org"} == {CATALOGUE, QCL_ZIP, PP_ZIP, TCL_ZIP}
    with session_factory() as s:
        assert _count(s, ProductionStat) == 12 and _count(s, TradeFlowObservation) == 5
        assert get_setting(s, "faostat_dateupdate_TM") is None              # TM retried when the API works


def test_api_ignoring_page_number_falls_back_to_bulk(with_account, run_with_routes, session_factory, sent):
    """Paging is unsettled (page_size/page_number vs limit/offset). If the API ignores page_number,
    page 2 repeats the full page 1: keeping one page would silently drop rows (here Italy's import
    value) and record DateUpdate, so they would never be fetched again. Fall back to bulk instead."""
    routes = api_routes(**{
        r"^https://faostatservices\.fao\.org/api/v1/en/data/TCL\?.*&page_number=2$": A("TCL_page1.json"),
    })
    routes[TCL_ZIP] = make_zip("TCL")
    res = run_with_routes("faostat", routes)
    assert res["status"] == "partial", res
    paging = [w for w in res["warnings"] if "page_number ignored" in w]
    assert len(paging) == 1 and "TCL" in paging[0] and "public bulk downloads" in paging[0], res["warnings"]
    assert TCL_ZIP in {str(r.url) for r in sent}
    with session_factory() as s:
        tcl = {(t.reporter_iso3, t.flow): t for t in s.scalars(select(TradeFlowObservation).where(
            TradeFlowObservation.series_key.like("faostat|TCL|%")))}
        ita = tcl[("ITA", "import")]
        assert (ita.net_weight_kg, ita.value) == (25_000_000, 95_000_000)   # complete: value not lost
        assert ita.extra["access"] == "bulk" and ita.source_url == TCL_ZIP
        assert get_setting(s, "faostat_dateupdate_TCL") == "2025-11-14T00:00:00"   # from the complete bulk load
        assert get_setting(s, "faostat_dateupdate_TM") is None                     # API dropped: TM retried
        assert _prod(s, "ARG", "production", 2023).extra["access"] == "api"         # earlier datasets kept


def test_tm_probe_mismatch_fails_only_tm(with_account, run_with_routes, session_factory):
    dims = json.loads(A("TM_dimensions.json"))
    dims["data"] = [d for d in dims["data"] if d["id"] != "partnerarea"]
    res = run_with_routes("faostat", api_routes(**{API + "/en/dimensions/TM/": json.dumps(dims).encode()}))
    assert res["status"] == "failed" and "TM" in res["error"] and "partner" in res["error"]
    with session_factory() as s:
        assert _prod(s, "ARG", "production", 2023) is not None               # QCL/PP/TCL kept
        assert s.scalar(select(func.count(TradeFlowObservation.id)).where(
            TradeFlowObservation.series_key.like("faostat|TM|%"))) == 0
        assert get_setting(s, "faostat_dateupdate_TCL") is not None
        assert get_setting(s, "faostat_dateupdate_TM") is None


def test_source_registered():
    from paladex.collectors.registry import get_collector

    c = get_collector("faostat")
    assert c is not None and c.requires_key is None
    assert c.schedule["trigger"] == "cron" and "day_of_week" in c.schedule          # weekly
    assert 400 <= c.expected_max_age_days <= 500 and len(c.expected_update) <= 120
