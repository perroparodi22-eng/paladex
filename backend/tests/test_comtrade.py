"""UN Comtrade collector (HS 0409). Fixtures are RECONSTRUCTED from documentation (see
tests/fixtures/comtrade/README.md); values are illustrative."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from paladex.collectors import comtrade as ct
from paladex.collectors.base import CollectorError
from paladex.enums import PriceType
from paladex.models import (
    CollectionRun,
    PriceObservation,
    RawDocument,
    TradeFlowObservation,
    utcnow,
)

FIXTURES = Path(__file__).parent / "fixtures" / "comtrade"
API = r"^https://comtradeapi\.un\.org"
REF = API + r"/files/v1/app/reference/partnerAreas\.json"
SECRET = "test-secret-key-0123456789"


def F(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def preview(freq: str, reporter: int, period: str, flow: str) -> str:
    return (API + rf"/public/v1/preview/C/{freq}/HS\?reporterCode={reporter}&period={period}"
            rf"&cmdCode=0409&flowCode={flow}&partner2Code=0&customsCode=C00&motCode=0&maxRecords=500&")


def keyed(freq: str, reporters: str, periods: str, flow: str) -> str:
    return API + rf"/data/v1/get/C/{freq}/HS\?reporterCode={reporters}&period={periods}&cmdCode=0409&flowCode={flow}&"


def getda(freq: str, *, is_keyed: bool = False) -> str:
    return API + rf"/{'data' if is_keyed else 'public'}/v1/getDa/C/{freq}/HS\?"


@pytest.fixture()
def small_panel(monkeypatch):
    """A small, deterministic panel: Italy imports, Argentina exports, 2025 + Italy monthly.
    Also forces the keyless path even if a developer .env holds a real key."""
    from paladex import config

    monkeypatch.setenv("PALADEX_COMTRADE_API_KEY", "")
    config.get_settings.cache_clear()
    monkeypatch.setattr(ct, "_today", lambda: date(2026, 11, 2))
    monkeypatch.setattr(ct, "IMPORT_MARKETS", {"ITA": 380})
    monkeypatch.setattr(ct, "EXPORT_ORIGINS", {"ARG": 32})
    monkeypatch.setattr(ct, "ANNUAL_YEARS", 1)
    monkeypatch.setattr(ct, "MONTHLY_MONTHS_KEYLESS", 4)        # 202610, 202609, 202608, 202607
    monkeypatch.setattr(ct, "KEYLESS_MONTHLY_MARKETS", ("ITA",))


@pytest.fixture()
def sent(monkeypatch):
    """Record every request that leaves the httpx client (to check headers and URLs)."""
    requests: list[httpx.Request] = []
    original = httpx.Client.send

    def spy(self, request, *args, **kwargs):
        requests.append(request)
        return original(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", spy)
    return requests


@pytest.fixture()
def with_key(monkeypatch):
    from paladex import config

    monkeypatch.setenv("PALADEX_COMTRADE_API_KEY", SECRET)
    config.get_settings.cache_clear()
    yield SECRET
    config.get_settings.cache_clear()


def keyless_routes(**overrides) -> dict:
    routes = {
        REF: F("partner_areas.json"),
        getda("A") + r"reporterCode=32,380&period=2025$": F("getda_A.json"),
        getda("M") + r"reporterCode=380&period=202607,202608,202609,202610$": F("getda_M.json"),
        preview("A", 380, "2025", "M"): F("preview_A_M_380_2025.json"),
        preview("A", 32, "2025", "X"): F("preview_A_X_32_2025.json"),
        preview("M", 380, "202607", "M"): F("preview_M_M_380_202607.json"),
        preview("M", 380, "202608", "M"): F("preview_M_M_380_202608.json"),
        preview("M", 380, "202609", "M"): F("empty.json"),
        preview("M", 380, "202610", "M"): F("empty.json"),
    }
    routes.update(overrides)
    return routes


def trade(s, **where) -> list[TradeFlowObservation]:
    q = select(TradeFlowObservation).where(TradeFlowObservation.is_current.is_(True))
    for k, v in where.items():
        q = q.where(getattr(TradeFlowObservation, k) == v)
    return s.scalars(q.order_by(TradeFlowObservation.id)).all()


def prices(s, **where) -> list[PriceObservation]:
    q = select(PriceObservation).where(PriceObservation.is_current.is_(True))
    for k, v in where.items():
        q = q.where(getattr(PriceObservation, k) == v)
    return s.scalars(q.order_by(PriceObservation.id)).all()


def data_calls(requests) -> list[httpx.Request]:
    return [r for r in requests if "/preview/" in r.url.path or "/v1/get/" in r.url.path]


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_registered_with_optional_key():
    from paladex.collectors.registry import get_collector

    c = get_collector("un_comtrade")
    assert c is not None and c.requires_key == "comtrade_api_key" and c.key_optional is True
    assert c.category == "trade" and c.reliability == "official"
    assert len(c.expected_update) <= 120 and len(c.name) <= 200      # Source column sizes
    assert all(len(f"M{code}") <= 5 for code in range(1000))       # partner_iso3 is String(5)


@pytest.mark.parametrize("code,iso_raw,expected", [
    (0, "W00", ("WLD", True)),
    (842, None, ("USA", True)),       # Comtrade USA code, not ISO 840
    (251, None, ("FRA", True)),       # France 251, not 250
    (699, None, ("IND", True)),       # India 699, not 356
    (757, None, ("CHE", True)),       # Switzerland 757, not 756
    (579, None, ("NOR", True)),       # Norway 579, not 578
    (490, "S19", ("TWN", True)),      # 'Other Asia, nes' = Taiwan
    (32, "ARG", ("ARG", True)),
    (894, "ZMB", ("ZMB", True)),      # row ISO wins even outside our country table
    (97, "EUR", (None, True)),        # EU aggregate -> skip
    (899, "_X ", ("M899", False)),    # unknown residual area
])
def test_resolve_partner_quirks(code, iso_raw, expected):
    assert ct.resolve_partner(code, iso_raw, None) == expected


def test_partner_reference_enriches_mapping():
    ref = ct.parse_partner_reference(F("partner_areas.json"))   # file starts with a UTF-8 BOM
    assert ref[894].iso3 == "ZMB" and ref[97].is_group and ref[472].is_group
    assert ref[899].iso3 is None and ref[899].desc == "Areas, nes"
    assert ct.resolve_partner(894, None, ref) == ("ZMB", True)     # ISO from the reference file
    assert ct.resolve_partner(472, None, ref) == (None, True)      # isGroup -> skipped
    assert ct.resolve_partner(894, None, None) == ("M894", False)  # without the reference: unknown
    with pytest.raises(CollectorError):
        ct.parse_partner_reference(b"<html>nope</html>")


def test_parse_envelope_errors():
    with pytest.raises(CollectorError):
        ct.parse_envelope(b"<html>Service Unavailable</html>")
    with pytest.raises(CollectorError):
        ct.parse_envelope(b'{"statusCode": 401, "message": "Access denied"}')
    with pytest.raises(CollectorError):
        ct.parse_envelope(b'{"data": null, "error": "Invalid period"}')
    assert ct.parse_envelope(F("empty.json")).rows == []


def test_periods_and_value_basis():
    assert ct.parse_period("2025").label == "2025"
    p = ct.parse_period(202602, "M")
    assert (p.label, p.start, p.end) == ("2026-02", date(2026, 2, 1), date(2026, 2, 28))
    assert ct.parse_period("202613") is None and ct.parse_period("2025", "M") is None
    assert ct.monthly_periods(date(2026, 1, 15), 3) == ["202512", "202511", "202510"]
    assert ct.annual_periods(date(2026, 11, 2), 3) == ["2025", "2024", "2023"]
    assert ct.value_basis("M", 100.0, 100.0, None) == "CIF"
    assert ct.value_basis("M", 100.0, None, 100.0) == "FOB"      # an importer valuing FOB
    assert ct.value_basis("X", 100.0, None, None) == "FOB"       # convention when fields absent
    assert ct.value_basis("M", 100.0, 120.0, 90.0) == "primary"  # cannot tell
    assert ct.redact_url("https://x.org/a?b=1,2&subscription-key=SECRET") == "https://x.org/a?b=1,2"


def test_parse_records_rows():
    ref = ct.parse_partner_reference(F("partner_areas.json"))
    res = ct.parse_records(F("preview_A_M_380_2025.json"), ref)
    by_partner = {r.partner_iso3: r for r in res.records}
    assert set(by_partner) == {"WLD", "HUN", "UKR", "ARG", "FRA", "CHN", "TWN", "NZL", "ZMB", "M899", "SRB", "ESP",
                               "DEU"}
    assert res.skipped_aggregates == 1 and res.skipped_breakdown == 1
    assert len(res.malformed) == 1 and "non-numeric" in res.malformed[0]
    assert res.unknown_partners == {899: "Areas, nes"}
    assert by_partner["SRB"].weight_estimated and by_partner["SRB"].data_status == "estimate"  # 'isnetWgtEstimated'
    assert by_partner["DEU"].value_basis == "CIF"                                              # 'CIFValue'
    assert by_partner["ESP"].net_weight_kg is None
    assert ct.unit_value(by_partner["ARG"]) == 3.1
    assert ct.unit_value(by_partner["NZL"]) is None       # 400 kg < MIN_UNIT_VALUE_KG
    assert ct.unit_value(by_partner["WLD"]) is None
    assert ct.unit_value(by_partner["M899"]) is None
    # reporter mapped from the code when reporterISO is null
    monthly = ct.parse_records(F("preview_M_M_380_202607.json"), ref)
    assert {r.reporter_iso3 for r in monthly.records} == {"ITA"}
    assert {r.period.label for r in monthly.records} == {"2026-07"}


def test_plan_batches_groups_and_chunks():
    needed = {"2024": {"ITA", "USA"}, "2025": {"ITA", "USA"}, "2023": {"ITA"}}
    assert ct.plan_batches(needed, 6, 12) == [(("ITA",), ("2023",)), (("ITA", "USA"), ("2024", "2025"))]
    many = {f"{y}{m:02d}": {"A", "B", "C"} for y in (2025, 2026) for m in range(1, 13)}
    batches = ct.plan_batches(many, 2, 12)
    assert len(batches) == 4 and all(len(p) == 12 and len(r) <= 2 for r, p in batches)


# ---------------------------------------------------------------------------
# End to end: keyless public preview
# ---------------------------------------------------------------------------


def test_keyless_end_to_end(run_with_routes, session_factory, small_panel, sent):
    res = run_with_routes("un_comtrade", keyless_routes())
    assert res["status"] == "partial", res          # partial = warnings (unknown partner, bad row, sub-total)
    assert len(res["warnings"]) == 3, res["warnings"]
    assert any("M899" in w for w in res["warnings"])
    assert res["new"] == 25 + 18                     # 25 trade rows + 18 unit values

    calls = data_calls(sent)
    assert all(r.url.host == "comtradeapi.un.org" and "/public/v1/preview/" in r.url.path for r in calls)
    assert all(ct.KEY_HEADER not in r.headers for r in sent)
    # getDa says Sept/Oct 2026 are not published yet -> not requested
    periods = sorted(r.url.params["period"] for r in calls)
    assert periods == ["2025", "2025", "202607", "202608"]

    with session_factory() as s:
        ita = {t.partner_iso3: t for t in trade(s, reporter_iso3="ITA", frequency="A")}
        assert "EUR" not in ita and None not in ita and "ROU" not in ita and "BGR" not in ita
        w = ita["WLD"]
        assert w.flow == "import" and w.value_basis == "CIF" and w.currency == "USD" and w.hs_code == "0409"
        assert (w.period_label, w.period_start, w.period_end) == ("2025", date(2025, 1, 1), date(2025, 12, 31))
        assert w.published_at == date(2026, 9, 14)              # lastReleased from getDa
        assert w.source_url.startswith("https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=380&period=2025")
        assert w.reliability == "official" and w.raw_document_id
        assert ita["FRA"].extra["partner_code"] == 251 and ita["TWN"].extra["partner_code"] == 490
        assert ita["ZMB"].value == 15000.0
        assert ita["M899"].extra["partner_unmapped"] is True
        assert ita["SRB"].data_status == "estimate" and ita["SRB"].extra["is_net_wgt_estimated"] is True
        assert ita["ESP"].net_weight_kg is None and ita["ESP"].unit_value_per_kg is None

        # unit values: import -> market = reporter, origin = partner; never wholesale
        uv = {p.origin_iso3: p for p in prices(s, price_type=PriceType.IMPORT_UNIT_VALUE.value, frequency="A")}
        assert set(uv) == {"HUN", "UKR", "ARG", "FRA", "CHN", "TWN", "ZMB", "SRB", "DEU"}
        arg = uv["ARG"]
        assert (arg.market_iso3, arg.price_value, arg.currency, arg.unit) == ("ITA", 3.1, "USD", "kg")
        assert arg.variety == "unspecified" and arg.volume_kg == 2_400_000.0 and arg.terms.startswith("CIF")
        assert arg.published_at == date(2026, 9, 14) and arg.source_url == ita["ARG"].source_url
        assert uv["SRB"].data_status == "estimate"
        assert not prices(s, price_type=PriceType.WHOLESALE_BULK.value)

        # exports: origin = reporter, market = partner, FOB
        ex = {p.market_iso3: p for p in prices(s, price_type=PriceType.EXPORT_UNIT_VALUE.value)}
        assert set(ex) == {"USA", "DEU", "ITA", "JPN", "FRA"}
        assert ex["USA"].origin_iso3 == "ARG" and ex["USA"].price_value == 3.0 and ex["USA"].terms.startswith("FOB")
        assert trade(s, reporter_iso3="ARG", partner_iso3="USA")[0].value_basis == "FOB"

        # monthly
        monthly = trade(s, reporter_iso3="ITA", frequency="M")
        assert {t.period_label for t in monthly} == {"2026-07", "2026-08"}
        assert {t.published_at for t in monthly} == {date(2026, 10, 9), date(2026, 10, 23)}


def test_keyless_second_run_is_idempotent(run_with_routes, session_factory, small_panel, sent):
    run_with_routes("un_comtrade", keyless_routes())
    first = len(data_calls(sent))
    # Same releases as before -> getDa says nothing changed -> no data call at all.
    res2 = run_with_routes("un_comtrade", keyless_routes())
    assert res2["status"] == "no_change", res2
    assert res2["new"] == 0 and res2["revised"] == 0
    assert len(data_calls(sent)) == first
    # Forced re-pull: every row is seen again, nothing new, nothing revised.
    res3 = run_with_routes("un_comtrade", keyless_routes(), force=True)
    assert res3["new"] == 0 and res3["revised"] == 0 and res3["seen"] == 43
    with session_factory() as s:
        assert len(s.scalars(select(TradeFlowObservation)).all()) == 25
        assert len(s.scalars(select(PriceObservation)).all()) == 18


def test_revised_value_creates_revision(run_with_routes, session_factory, small_panel):
    run_with_routes("un_comtrade", keyless_routes())
    # UN Comtrade re-releases Italy 2025 with a revised Argentina value.
    doc = json.loads(F("preview_A_M_380_2025.json"))
    for row in doc["data"]:
        if row["partnerCode"] == 32:
            row["primaryValue"] = row["cifvalue"] = 7_680_000.0
    da = json.loads(F("getda_A.json"))
    for row in da["data"]:
        row["lastReleased"] = (utcnow() + timedelta(days=1)).isoformat(timespec="seconds")
    res = run_with_routes("un_comtrade", keyless_routes(**{
        getda("A") + r"reporterCode=32,380&period=2025$": json.dumps(da).encode(),
        preview("A", 380, "2025", "M"): json.dumps(doc).encode(),
    }))
    assert res["revised"] == 2 and res["new"] == 0, res        # trade row + its unit value
    with session_factory() as s:
        rows = s.scalars(select(TradeFlowObservation).where(
            TradeFlowObservation.series_key == "0409|A|import|ITA|ARG|2025").order_by(TradeFlowObservation.id)).all()
        assert [(r.value, r.is_current, r.revision) for r in rows] == [(7_440_000.0, False, 1), (7_680_000.0, True, 2)]
        assert rows[1].supersedes_id == rows[0].id
        uv = prices(s, price_type=PriceType.IMPORT_UNIT_VALUE.value, origin_iso3="ARG", frequency="A")
        assert len(uv) == 1 and uv[0].price_value == 3.2 and uv[0].revision == 2


def test_getda_failure_falls_back(run_with_routes, session_factory, small_panel, sent):
    res = run_with_routes("un_comtrade", keyless_routes(**{
        getda("A") + r"reporterCode=32,380&period=2025$": (500, b"Internal Server Error"),
        getda("M") + r"reporterCode=380&period=202607,202608,202609,202610$": F("empty.json"),
    }))
    assert res["status"] == "partial" and res["new"] == 43, res
    # without availability every missing period is fetched (incl. Sept/Oct, still empty)
    assert len(data_calls(sent)) == 6
    with session_factory() as s:
        assert {t.published_at for t in trade(s)} == {None}


def test_quota_stops_gracefully(run_with_routes, session_factory, small_panel, monkeypatch, sent):
    monkeypatch.setattr(ct, "IMPORT_MARKETS", {"ITA": 380, "DEU": 276})
    body = b'{"statusCode": 429, "message": "Rate limit is exceeded. Try again in 1 seconds."}'
    da = json.loads(F("getda_A.json"))
    da["data"].append({**da["data"][0], "reporterCode": 276, "reporterISO": "DEU"})   # Germany 2025 published
    res = run_with_routes("un_comtrade", keyless_routes(**{
        getda("A") + r"reporterCode=32,276,380&period=2025$": json.dumps(da).encode(),
        preview("A", 276, "2025", "M"): (429, body, "application/json"),
    }))
    assert res["status"] == "partial", res
    assert any("HTTP 429" in w and "Stopped early" in w for w in res["warnings"])
    assert not any("/preview/" in r.url.path and r.url.params["reporterCode"] == "32" for r in sent)
    with session_factory() as s:
        assert len(trade(s, reporter_iso3="ITA", frequency="A")) == 13   # kept
        assert trade(s, reporter_iso3="ARG") == []                          # never reached


def test_all_responses_unusable_fails(run_with_routes, small_panel):
    junk = b"<html><body>Service temporarily unavailable</body></html>"
    res = run_with_routes("un_comtrade", {API: junk})
    assert res["status"] == "failed"
    assert "requests failed" in res["error"]


# ---------------------------------------------------------------------------
# End to end: free API key
# ---------------------------------------------------------------------------


def keyed_routes() -> dict:
    return {
        REF: F("partner_areas.json"),
        getda("A", is_keyed=True): F("keyed_getda_A.json"),
        getda("M", is_keyed=True): F("keyed_getda_M.json"),
        keyed("A", "380,842", "2024,2025", "M"): F("keyed_A_M_380-842_2024-2025.json"),
        keyed("A", "32", "2024,2025", "X"): F("keyed_A_X_32_2024-2025.json"),
        keyed("M", "380,842", "202609", "M"): F("keyed_M_M_380-842_202609.json"),
    }


@pytest.fixture()
def keyed_panel(monkeypatch):
    monkeypatch.setattr(ct, "_today", lambda: date(2026, 11, 2))
    monkeypatch.setattr(ct, "IMPORT_MARKETS", {"ITA": 380, "USA": 842})
    monkeypatch.setattr(ct, "EXPORT_ORIGINS", {"ARG": 32})
    monkeypatch.setattr(ct, "ANNUAL_YEARS", 2)
    monkeypatch.setattr(ct, "MONTHLY_MONTHS_KEYED", 2)        # 202610, 202609


def test_keyed_end_to_end(run_with_routes, session_factory, keyed_panel, with_key, sent):
    res = run_with_routes("un_comtrade", keyed_routes())
    assert res["status"] == "success", res
    calls = data_calls(sent)
    # three batched calls cover 2 reporters x 2 years, 1 exporter x 2 years, 2 reporters x 1 month
    assert len(calls) == 3
    assert {r.url.params["reporterCode"] for r in calls} == {"380,842", "32"}
    assert not any("/public/" in r.url.path for r in sent if "getDa" in r.url.path or "preview" in r.url.path)
    for r in sent:
        assert SECRET not in str(r.url)
        if "/data/v1/" in r.url.path:
            assert r.headers[ct.KEY_HEADER] == SECRET
        else:
            assert ct.KEY_HEADER not in r.headers           # reference file: no key needed
    with session_factory() as s:
        rows = trade(s)
        assert len(rows) == 16 + 6 + 5
        assert all(SECRET not in (t.source_url or "") for t in rows)
        assert all(SECRET not in (p.source_url or "") for p in prices(s))
        assert all(SECRET not in d.url for d in s.scalars(select(RawDocument)).all())
        run = s.scalars(select(CollectionRun).order_by(CollectionRun.id.desc())).first()
        assert SECRET not in json.dumps(run.warnings or []) + (run.error or "")
        usa = {t.partner_iso3: t for t in trade(s, reporter_iso3="USA", period_label="2025")}
        assert set(usa) == {"WLD", "IND", "ARG", "VNM", "BRA"}           # 699 -> IND without ISO
        assert usa["IND"].source_url.startswith(
            "https://comtradeapi.un.org/data/v1/get/C/A/HS?reporterCode=380,842&period=2024,2025")
        assert usa["IND"].published_at == date(2026, 9, 14)
        uv = prices(s, price_type=PriceType.IMPORT_UNIT_VALUE.value, market_iso3="USA", origin_iso3="IND",
                    period_label="2024")
        assert len(uv) == 1 and uv[0].price_value == 2.8
        assert {t.period_label for t in trade(s, frequency="M")} == {"2026-09"}


def test_keyed_truncation_splits_batch(run_with_routes, session_factory, keyed_panel, with_key, monkeypatch, sent):
    monkeypatch.setattr(ct, "EXPORT_ORIGINS", {})
    monkeypatch.setattr(ct, "MONTHLY_MONTHS_KEYED", 0)
    monkeypatch.setattr(ct, "KEYED_MAX_RECORDS", 6)
    full = json.loads(F("keyed_A_M_380-842_2024-2025.json"))

    def subset(reporter: int, periods: tuple[str, ...]) -> bytes:
        rows = [r for r in full["data"] if r["reporterCode"] == reporter and r["period"] in periods]
        return json.dumps({"count": len(rows), "data": rows, "error": ""}).encode()

    res = run_with_routes("un_comtrade", {
        REF: F("partner_areas.json"),
        getda("A", is_keyed=True): F("keyed_getda_A.json"),
        keyed("A", "380,842", "2024,2025", "M"): F("keyed_A_M_380-842_2024-2025.json"),   # 16 rows >= 6
        keyed("A", "380", "2024,2025", "M"): subset(380, ("2024", "2025")),               # 6 rows -> split again
        keyed("A", "380", "2024", "M"): subset(380, ("2024",)),
        keyed("A", "380", "2025", "M"): subset(380, ("2025",)),
        keyed("A", "842", "2024,2025", "M"): subset(842, ("2024", "2025")),                # 10 rows -> split
        keyed("A", "842", "2024", "M"): subset(842, ("2024",)),
        keyed("A", "842", "2025", "M"): subset(842, ("2025",)),
    })
    assert res["status"] == "success", res
    assert len(data_calls(sent)) == 7
    with session_factory() as s:
        assert len(trade(s)) == 16


def test_rejected_key_falls_back_to_keyless(run_with_routes, session_factory, small_panel, with_key, sent):
    denied = b'{"statusCode": 401, "message": "Access denied due to invalid subscription key."}'
    res = run_with_routes("un_comtrade", keyless_routes(**{API + r"/data/v1/": (401, denied, "application/json")}))
    assert res["status"] == "partial", res
    assert any("rejected the configured API key" in w for w in res["warnings"])
    assert SECRET not in json.dumps(res)
    assert any("/public/v1/preview/" in r.url.path for r in sent)
    preview_calls = [r for r in sent if "/public/" in r.url.path]
    assert all(ct.KEY_HEADER not in r.headers for r in preview_calls)
    with session_factory() as s:
        assert len(trade(s)) == 25
