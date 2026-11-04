from datetime import date

from sqlalchemy import select

from paladex.enums import PriceType
from paladex.models import FxRate, PriceObservation, Source
from paladex.reference.countries import lookup_iso3
from paladex.reference.varieties import detect_color_grade, normalize_variety
from paladex.services import fx, ingest

ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<gesmes:subject>Reference rates</gesmes:subject>
<Cube>
<Cube time="2026-10-30"><Cube currency="USD" rate="1.1000"/><Cube currency="CNY" rate="7.80"/></Cube>
<Cube time="2026-10-29"><Cube currency="USD" rate="1.0900"/><Cube currency="CNY" rate="7.75"/></Cube>
</Cube></gesmes:Envelope>"""


def test_country_lookup():
    assert lookup_iso3("Viet Nam") == "VNM"
    assert lookup_iso3("Ucraina") == "UKR"
    assert lookup_iso3(842) == "USA"          # Comtrade USA code
    assert lookup_iso3("0") == "WLD"
    assert lookup_iso3("EL") == "GRC"         # Eurostat Greece
    assert lookup_iso3("Türkiye") == "TUR"
    assert lookup_iso3("Atlantis") is None


def test_variety_normalisation():
    assert normalize_variety("Millefiori")[0] == "polyflora"
    assert normalize_variety("Organic multifloral") == ("organic_polyflora", True)
    assert normalize_variety("Acacia (Robinia)")[0] == "acacia"
    assert normalize_variety("Miel de azahar")[0] == "orange_blossom"
    assert normalize_variety("")[0] == "unspecified"
    assert normalize_variety("Rosemary")[0] == "other"
    assert detect_color_grade("Extra Light Amber") == "extra light amber"
    assert detect_color_grade("miel de la pampa") is None
    assert detect_color_grade("ELA") == "extra light amber"


def test_ecb_and_fx(run_with_routes, session_factory):
    res = run_with_routes("ecb_fx", {"https://www.ecb.europa.eu/stats/eurofxref/": ECB_XML})
    assert res["status"] == "success", res
    assert res["new"] == 4
    with session_factory() as s:
        assert s.scalar(select(FxRate.per_eur).where(FxRate.currency == "USD", FxRate.rate_date == date(2026, 10, 30))) == 1.1
        # USD -> EUR on a weekend uses the last rate before it
        v, d = fx.convert(s, 11.0, "USD", "EUR", date(2026, 11, 1))
        assert round(v, 4) == 10.0 and d == date(2026, 10, 30)
        assert fx.convert(s, 1.0, "USD", "EUR", date(2020, 1, 1)) is None  # never guess
    # second run: nothing new
    res2 = run_with_routes("ecb_fx", {"https://www.ecb.europa.eu/stats/eurofxref/": ECB_XML})
    assert res2["status"] == "no_change"


def test_revisions_are_append_only(db):
    src = db.scalars(select(Source).where(Source.key == "ecb_fx")).one()
    common = dict(source_id=src.id, series_key="x", price_type=PriceType.WHOLESALE_BULK.value, variety="acacia",
                  currency="EUR", unit="kg", price_per_kg=5.0, period_start=date(2026, 1, 1),
                  period_end=date(2026, 1, 31), period_label="2026-01", frequency="M",
                  data_status="published", reliability="official")
    o1, r1 = ingest.record(db, PriceObservation, price_value=5.0, **common)
    o2, _ = ingest.record(db, PriceObservation, price_value=5.0, **common)
    o3, r3 = ingest.record(db, PriceObservation, price_value=5.5, **common)
    assert (o1, o2, o3) == ("new", "unchanged", "revised")
    rows = db.scalars(select(PriceObservation).order_by(PriceObservation.id)).all()
    assert len(rows) == 2
    assert rows[0].is_current is False and rows[0].price_value == 5.0
    assert rows[1].is_current is True and rows[1].revision == 2 and rows[1].supersedes_id == rows[0].id


def test_per_kg_units():
    assert round(ingest.per_kg(2.0, "lb"), 4) == 4.4092
    assert ingest.per_kg(3000, "t") == 3.0
    assert ingest.per_kg(500, "q") == 5.0


def test_offline_marks_run(run_with_routes):
    res = run_with_routes("ecb_fx", {})
    assert res["status"] == "offline"


def test_api_sources_and_demo(api):
    r = api.get("/api/sources").json()
    assert any(s["key"] == "ecb_fx" for s in r["sources"])
    assert api.post("/api/demo/seed").json()["inserted"] > 100
    assert api.get("/api/settings").json()["show_demo"] is True
    assert api.delete("/api/demo").json()["deleted"] > 100


def test_migration_adds_missing_columns(tmp_path):
    """An older database file without a newer column is upgraded in place, data kept."""
    import sqlite3

    from sqlalchemy import create_engine, inspect

    from paladex import db as dbmod

    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE regulations (id INTEGER PRIMARY KEY, source_id INTEGER, jurisdiction VARCHAR(10), "
                "doc_type VARCHAR(40), reference VARCHAR(200), title VARCHAR(1000), status VARCHAR(40), "
                "published_at DATE, effective_date DATE, url VARCHAR(1000), countries JSON, summary_en TEXT, "
                "summary_it TEXT, summary_is_ai BOOLEAN, collected_at DATETIME, is_demo BOOLEAN)")
    con.execute("INSERT INTO regulations (id, source_id, jurisdiction, doc_type, reference, title, url) "
                "VALUES (1, 1, 'EU', 'directive', 'X', 'T', 'u')")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{path}")
    from paladex import models  # noqa: F401

    added = dbmod.migrate_add_missing_columns(engine)
    assert "regulations.extra" in added
    assert "extra" in {c["name"] for c in inspect(engine).get_columns("regulations")}
    with engine.connect() as c:
        from sqlalchemy import text

        assert c.execute(text("SELECT title FROM regulations WHERE id=1")).scalar() == "T"
    assert dbmod.migrate_add_missing_columns(engine) == []   # idempotent


def test_api_keys_in_urls_never_reach_the_log(caplog):
    """httpx logs every request URL at INFO; with the app's logging set-up the NASS `key=` value
    must be redacted (ARCHITECTURE §6: keys are stripped)."""
    import logging

    import httpx

    import paladex.main  # noqa: F401  (the app's logging configuration)

    caplog.set_level(logging.INFO)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"{}"))) as client:
        client.get("https://quickstats.nass.usda.gov/api/api_GET/", params={"key": "SECRET123", "commodity_desc": "HONEY"})
    assert "quickstats.nass.usda.gov" in caplog.text
    assert "SECRET123" not in caplog.text and "key=REDACTED" in caplog.text
