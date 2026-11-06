"""GET /api/overview — the homepage "morning terminal".

Covers: empty database (first launch), demo data, demo filtering, the rule-based briefing
(content + provenance), a stored briefing, stale vs current labelling, trade ranking
bases, news selection, country activity, alerts and quality counts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from paladex.collectors.base import month_bounds, year_bounds
from paladex.models import (
    AlertEvent,
    Briefing,
    CollectionRun,
    DataQualityIssue,
    NewsArticle,
    PriceObservation,
    Report,
    Source,
    TradeFlowObservation,
    utcnow,
)
from paladex.services import ingest

TODAY = date.today()
BLOCKS = ("status", "briefing", "prices", "news", "reports", "trade", "countries", "alerts", "quality")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_source(db, key: str, category: str, *, expected: int | None = 45, publisher: str = "Test Publisher",
                reliability: str = "official", latest_published: date | None = None, last_run_status: str | None = None,
                name: str | None = None) -> Source:
    s = Source(key=key, name=name or f"Source {key}", publisher=publisher, homepage="https://example.org",
               kind="api", reliability=reliability, category=category, expected_max_age_days=expected,
               latest_published_at=latest_published, last_run_status=last_run_status,
               last_run_at=utcnow() - timedelta(hours=2) if last_run_status else None)
    db.add(s)
    db.flush()
    return s


def month_start(months_back: int) -> date:
    return (TODAY.replace(day=1) - relativedelta(months=months_back))


def add_price_series(db, src: Source, origin: str, variety: str, values: list[float], *, last_months_back: int = 1,
                     published_lag_days: int = 10, price_type: str = "wholesale_bulk", currency: str = "USD",
                     url: str = "https://example.org/report.pdf", terms: str | None = None,
                     market: str = "USA") -> None:
    """`values` oldest -> newest, monthly, the newest one `last_months_back` months ago."""
    n = len(values)
    for i, v in enumerate(values):
        start = month_start(last_months_back + (n - 1 - i))
        _, end = month_bounds(start.year, start.month)
        ingest.record(
            db, PriceObservation, source_id=src.id,
            series_key=f"{price_type}|{origin}|{variety}|{currency}|{terms}|{start:%Y-%m}",
            price_type=price_type, origin_iso3=origin, origin_label=origin, market_iso3=market, variety=variety,
            terms=terms, price_value=v, currency=currency, unit="kg", price_per_kg=v,
            usd_per_kg=v if currency == "USD" else None, eur_per_kg=round(v / 1.1, 4),
            period_start=start, period_end=end, period_label=f"{start:%Y-%m}", frequency="M",
            published_at=end + timedelta(days=published_lag_days), source_url=url,
            data_status="published", reliability=src.reliability,
        )


def add_trade(db, src: Source, reporter: str, partner: str, year: int, kg: float, *, flow: str = "import",
              usd: float | None = None) -> None:
    start, end = year_bounds(year)
    ingest.record(
        db, TradeFlowObservation, source_id=src.id, series_key=f"{reporter}|{partner}|{flow}|{year}",
        hs_code="0409", reporter_iso3=reporter, partner_iso3=partner, flow=flow, net_weight_kg=kg,
        value=usd if usd is not None else kg * 3, currency="USD", usd_value=usd if usd is not None else kg * 3,
        period_start=start, period_end=end, period_label=str(year), frequency="A",
        published_at=date(year + 1, 6, 30), source_url="https://example.org/trade",
        data_status="published", reliability=src.reliability,
    )


def add_news(db, src: Source, title: str, *, hours_ago: float = 12, relevance: int = 80, countries=None,
             language: str = "en", title_it: str | None = None, summary_it: str | None = None,
             duplicate_of: int | None = None, is_demo: bool = False) -> NewsArticle:
    url = f"https://news.example.org/{abs(hash(title))}"
    a = NewsArticle(source_id=src.id, url=url, canonical_url=url, title=title, title_norm=title.lower(),
                    publisher="Honey Times", language=language, published_at=utcnow() - timedelta(hours=hours_ago),
                    countries=countries or [], relevance_score=relevance, title_it=title_it, summary_it=summary_it,
                    ai_processed_at=utcnow() if (title_it or summary_it) else None,
                    duplicate_of_id=duplicate_of, is_demo=is_demo)
    db.add(a)
    db.flush()
    return a


def get(api, lang: str = "it") -> dict:
    r = api.get("/api/overview", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# empty database (first launch)
# ---------------------------------------------------------------------------


def test_empty_db_every_block_is_present_and_honest(api):
    d = get(api)
    for b in BLOCKS:
        assert b in d, b
    assert d["today"] == TODAY.isoformat()
    assert d["prices"]["items"] == [] and d["prices"]["updated_at"] is None
    assert d["news"]["items"] == [] and d["reports"]["items"] == []
    assert d["trade"]["available"] is False and d["trade"]["importers"] is None
    assert d["countries"]["items"] == []
    assert d["alerts"] == {"unread": 0, "items": [], "updated_at": None, "link": "/avvisi"}
    assert d["quality"]["open"] == 0

    br = d["briefing"]
    assert br["generator"] == "rules" and br["is_ai"] is False
    assert br["bullets"] == [] and br["has_any_data"] is False
    assert "Nessun dato" in br["empty_message"]
    assert [r["key"] for r in br["rules"]] == ["prices", "reports", "trade", "news"]

    st = d["status"]
    assert st["never_collected"] is True and st["last_check_at"] is None
    assert st["counts"]["total"] >= 1 and st["counts"]["never"] == st["counts"]["total"]
    # demo and manual sources are never counted as data sources
    assert all(s["key"] not in ("demo", "manual_quotes") for s in st["sources"])
    assert d["show_demo"] is False and d["demo_rows_present"] is False


def test_language_switch_and_validation(api):
    en = get(api, "en")
    assert en["lang"] == "en"
    assert en["briefing"]["empty_message"].startswith("No data")
    assert api.get("/api/overview", params={"lang": "fr"}).status_code == 422


def test_providers_name_the_sources_that_would_fill_a_block(api, db):
    make_source(db, "t_prices", "prices", name="Listino di prova")
    make_source(db, "t_news", "news")
    db.commit()
    db_sources = {s.key: s.category for s in db.scalars(select(Source))}
    d = get(api)
    # other collectors may be registered too: check membership and categories, not exact lists
    price_keys = [p["key"] for p in d["prices"]["providers"]]
    news_keys = [p["key"] for p in d["news"]["providers"]]
    assert "t_prices" in price_keys and "t_news" not in price_keys
    assert "t_news" in news_keys
    assert all(db_sources[k] == "prices" for k in price_keys)
    assert all(db_sources[k] == "news" for k in news_keys)
    assert all(p["key"] not in ("demo", "manual_quotes") for blk in ("prices", "news", "trade", "reports")
               for p in d[blk]["providers"])


# ---------------------------------------------------------------------------
# demo data
# ---------------------------------------------------------------------------


def test_demo_data_fills_blocks_and_is_labelled(api):
    assert api.post("/api/demo/seed").status_code == 200
    d = get(api)
    assert d["show_demo"] is True and d["demo_rows_present"] is True

    tiles = d["prices"]["items"]
    assert len(tiles) == 8
    # one wholesale series per priority origin, in priority order
    assert [t["origin_iso3"] for t in tiles] == ["ARG", "UKR", "CHN", "BRA", "VNM", "IND", "HUN", "ITA"]
    assert tiles[0]["variety"] == "polyflora" and tiles[-1]["variety"] == "acacia"
    for t in tiles:
        assert t["is_demo"] is True and t["data_status"] == "demo" and t["source"]["key"] == "demo"
        assert t["price_type"] == "wholesale_bulk"
        assert t["usd_per_kg"] is not None and t["eur_per_kg"] is not None
        assert t["mom_pct"] is not None and t["yoy_pct"] is not None
        assert len(t["spark"]) == 13 and t["spark"][-1]["period_label"] == t["period_label"]
        assert t["freshness"]["status"] == "current"
        assert t["link"].startswith("/prezzi?origin=")
    assert d["prices"]["mixed_price_types"] is False

    tr = d["trade"]
    assert tr["available"] is True and tr["frequency"] == "A"
    imp = tr["importers"]
    assert imp["basis"] == "sum_partners" and imp["period_label"] == str(TODAY.year - 1)
    assert [i["iso3"] for i in imp["items"]][0] == "USA"
    assert imp["items"][0]["partners_count"] == 2 and imp["items"][0]["yoy_pct"] is not None
    # no export declarations in the demo set -> main origins rebuilt from importers' declarations
    exp = tr["exporters"]
    assert exp["basis"] == "mirror_imports" and exp["reporters_count"] == 3
    assert {i["iso3"] for i in exp["items"]} <= {"ARG", "IND", "UKR", "MEX", "HUN"}

    bullets = d["briefing"]["bullets"]
    assert bullets and all(b["is_demo"] for b in bullets)
    assert d["briefing"]["is_demo"] is True
    assert {b["kind"] for b in bullets} <= {"price", "trade"}
    assert d["countries"]["items"] and all(c["link"] == f"/paesi/{c['iso3']}" for c in d["countries"]["items"])


def test_demo_rows_hidden_when_demo_display_is_off(api):
    api.post("/api/demo/seed")
    api.put("/api/settings", json={"show_demo": False})
    d = get(api)
    assert d["show_demo"] is False and d["demo_rows_present"] is True
    assert d["prices"]["items"] == []
    assert d["trade"]["available"] is False
    assert d["briefing"]["bullets"] == [] and d["briefing"]["has_any_data"] is False
    assert d["countries"]["items"] == []


def test_real_rows_shown_with_demo_off_and_never_mixed_with_demo(api, db):
    src = make_source(db, "t_prices", "prices")
    add_price_series(db, src, "ARG", "polyflora", [3.0, 3.1, 3.2])
    db.commit()
    api.post("/api/demo/seed")
    api.put("/api/settings", json={"show_demo": False})
    tiles = get(api)["prices"]["items"]
    assert len(tiles) == 1 and tiles[0]["is_demo"] is False and tiles[0]["source"]["key"] == "t_prices"


# ---------------------------------------------------------------------------
# rule-based briefing
# ---------------------------------------------------------------------------


@pytest.fixture()
def market(db):
    """A small, fully known real (non-demo) dataset."""
    prices = make_source(db, "t_prices", "prices", publisher="USDA AMS", latest_published=TODAY - timedelta(days=5))
    trade = make_source(db, "t_trade", "trade", publisher="UN Comtrade", expected=400)
    news = make_source(db, "t_news", "news", publisher="Feed", reliability="aggregator", expected=3)
    # ARG polyflora: +5% m/m (3.00 -> 3.15), 13 months of history (y/y available)
    add_price_series(db, prices, "ARG", "polyflora", [2.80] + [3.00] * 11 + [3.15])
    # UKR sunflower: +1% m/m -> below the 3% threshold, no bullet
    add_price_series(db, prices, "UKR", "sunflower", [2.00, 2.02])
    # CHN polyflora: big move but stale (newest period ~10 months ago) -> not "news"
    add_price_series(db, prices, "CHN", "polyflora", [1.50, 1.80], last_months_back=10)
    db.add(Report(source_id=prices.id, report_key="r-new", title="National Honey Report — October",
                  period_label=f"{TODAY.year}-10", published_at=TODAY - timedelta(days=3),
                  url="https://example.org/honey-oct.pdf"))
    db.add(Report(source_id=prices.id, report_key="r-old", title="National Honey Report — March",
                  published_at=TODAY - timedelta(days=200), url="https://example.org/honey-mar.pdf"))
    y = TODAY.year - 1
    add_trade(db, trade, "USA", "ARG", y - 1, 50_000_000)
    add_trade(db, trade, "USA", "ARG", y, 40_000_000)       # -20% -> bullet
    add_trade(db, trade, "USA", "IND", y - 1, 30_000_000)
    add_trade(db, trade, "USA", "IND", y, 31_000_000)       # +3.3% -> no bullet
    add_trade(db, trade, "DEU", "UKR", y - 1, 20_000_000)
    add_trade(db, trade, "DEU", "UKR", y, 26_000_000)       # +30% -> bullet
    top = add_news(db, news, "Argentina honey exports surge", hours_ago=20, relevance=85, countries=["ARG"],
                   title_it="Le esportazioni di miele argentino in forte crescita", summary_it="Sintesi IA.")
    add_news(db, news, "Argentina honey exports surge (copy)", hours_ago=10, relevance=90, countries=["ARG"],
             duplicate_of=top.id)
    add_news(db, news, "Bee festival in a small town", hours_ago=5, relevance=20)
    add_news(db, news, "Old but relevant story", hours_ago=24 * 10, relevance=95, countries=["UKR"])
    db.commit()
    return {"prices": prices, "trade": trade, "news": news, "top_news": top}


def test_rule_based_briefing_content_and_provenance(api, market):
    br = get(api)["briefing"]
    assert br["generator"] == "rules" and br["is_ai"] is False and br["stored"] is False
    kinds = [b["kind"] for b in br["bullets"]]
    assert kinds == ["price", "report", "trade", "trade", "news"]
    counts = {r["key"]: r["count"] for r in br["rules"]}
    assert counts == {"prices": 1, "reports": 1, "trade": 2, "news": 1}

    price = br["bullets"][0]
    assert "Argentina" in price["text"] and "in rialzo del 5,0%" in price["text"] and "3,15 USD/kg" in price["text"]
    assert price["source"]["key"] == "t_prices" and price["publisher"] == "USDA AMS"
    assert price["url"] == "https://example.org/report.pdf" and price["date"] and price["period_label"]
    assert price["change_pct"] == pytest.approx(5.0)
    assert price["link"] == "/prezzi?origin=ARG&price_type=wholesale_bulk&variety=polyflora"

    report = br["bullets"][1]
    assert "National Honey Report — October" in report["text"]
    assert report["url"] == "https://example.org/honey-oct.pdf"
    assert report["date"] == (TODAY - timedelta(days=3)).isoformat()

    trade = br["bullets"][2:4]
    # biggest tonnage change first: USA -10 000 t, then Germany +6 000 t
    assert trade[0]["text"].startswith("Stati Uniti — importazioni") and "−20,0%" in trade[0]["text"]
    assert "origine Argentina" in trade[0]["text"] and "40.000 t" in trade[0]["text"]
    assert trade[1]["text"].startswith("Germania") and "+30,0%" in trade[1]["text"]
    assert all(t["source"]["key"] == "t_trade" and t["link"] == "/commercio" for t in trade)

    news = br["bullets"][4]
    assert news["text"] == "Le esportazioni di miele argentino in forte crescita"
    assert news["is_ai"] is True                     # machine-translated title is flagged
    assert news["publisher"] == "Honey Times" and news["url"].startswith("https://news.example.org/")


def test_briefing_bullets_carry_the_figures_of_their_sentence(api, market):
    # The interface's simple view rewrites each change in plain words from these fields (never by
    # re-reading the sentence): the same figure, period and source as the sentence.
    br = get(api)["briefing"]
    price = br["bullets"][0]
    assert price["origin_iso3"] == "ARG" and price["variety"] == "polyflora" and price["price_type"] == "wholesale_bulk"
    assert price["value_per_kg"] == pytest.approx(3.15) and price["currency"] == "USD"
    assert price["market_iso3"] is None or isinstance(price["market_iso3"], str)
    assert price["prev_period_label"] and price["prev_period_label"] < price["period_label"]
    trade = br["bullets"][2]
    assert (trade["flow"], trade["reporter_iso3"], trade["partner_iso3"]) == ("import", "USA", "ARG")
    assert trade["net_weight_kg"] == pytest.approx(40_000_000)
    assert trade["prev_period_label"] == str(TODAY.year - 2) and trade["period_label"] == str(TODAY.year - 1)


def test_price_tiles_name_the_missing_month_and_the_source_gap(api, db):
    # USDA, Nov 2026: no report between Sep 2025 and Aug 2026, so the latest month has neither the
    # month before nor the same month a year earlier. The tile says so, and gives the newest earlier
    # figure of the same series with its own date.
    usda = make_source(db, "t_usda", "prices", publisher="USDA AMS")
    add_price_series(db, usda, "ARG", "polyflora", [3.0, 3.2], last_months_back=14)   # ends 14 months ago
    add_price_series(db, usda, "ARG", "polyflora", [3.6], last_months_back=1)
    db.commit()
    tile = next(t for t in get(api)["prices"]["items"] if t["origin_iso3"] == "ARG")
    assert tile["mom_pct"] is None and tile["yoy_pct"] is None
    assert tile["earlier_pct"] == pytest.approx(12.5) and tile["earlier_period_label"] == f"{month_start(14):%Y-%m}"
    assert tile["mom_missing"] == {"period_label": f"{month_start(2):%Y-%m}", "source_has_period": False}
    assert tile["yoy_missing"] == {"period_label": f"{month_start(13):%Y-%m}", "source_has_period": False}
    # the source published that month for another origin: the gap is this figure's, not the source's
    add_price_series(db, usda, "BRA", "polyflora", [2.0], last_months_back=2)
    db.commit()
    tile = next(t for t in get(api)["prices"]["items"] if t["origin_iso3"] == "ARG")
    assert tile["mom_missing"]["source_has_period"] is True


def test_a_corrected_price_keeps_its_tile_and_names_its_row(api, db):
    # A value corrected by a person (reliability 'user') must not send its series down the ranking:
    # the tile stays, shows the corrected value with its "corrected by" and the row to correct again.
    usda = make_source(db, "t_usda", "prices", publisher="USDA AMS")
    add_price_series(db, usda, "BRA", "polyflora", [4.0, 4.2, 4.4], last_months_back=1)
    add_price_series(db, usda, "BRA", "polyflora", [5.0, 5.1], last_months_back=1, terms="secchio 25 kg")
    db.commit()
    tile = next(t for t in get(api)["prices"]["items"] if t["origin_iso3"] == "BRA")
    assert tile["terms"] is None and tile["row_id"]
    res = api.post("/api/corrections", json={"kind": "value_correction", "target": {"table": "price_observations",
                   "row_id": tile["row_id"]}, "value": 4.5, "reason": "offerta ricevuta"})
    assert res.status_code == 201, res.text
    tile2 = next(t for t in get(api)["prices"]["items"] if t["origin_iso3"] == "BRA")
    assert tile2["terms"] is None and tile2["price_value"] == pytest.approx(4.5)
    assert tile2["correction"]["official_value"] == pytest.approx(4.4) and tile2["row_id"] != tile["row_id"]


def test_rule_based_briefing_in_english(api, market):
    br = get(api, "en")["briefing"]
    price = br["bullets"][0]
    assert "up 5.0% month on month" in price["text"] and "3.15 USD/kg" in price["text"]
    news = br["bullets"][-1]
    assert news["text"] == "Argentina honey exports surge" and news["is_ai"] is False


def test_briefing_says_so_when_nothing_qualifies(api, db):
    src = make_source(db, "t_prices", "prices")
    add_price_series(db, src, "ARG", "polyflora", [3.00, 3.01])   # +0.3%
    db.commit()
    br = get(api)["briefing"]
    assert br["bullets"] == [] and br["has_any_data"] is True
    assert br["empty_message"].startswith("Nessuna novità rilevante")


def test_stored_briefing_for_today_is_used_with_its_generator(api, db):
    db.add(Briefing(briefing_date=TODAY, language="it", generator="claude-sonnet-5-5", content={
        "bullets": [{"kind": "price", "text": "Prezzi argentini in aumento.", "publisher": "USDA AMS",
                     "date": "2026-10-15", "url": "https://example.org/x"}, "Seconda osservazione."]}))
    db.add(Briefing(briefing_date=TODAY - timedelta(days=1), language="en", generator="claude", content={"bullets": []}))
    db.commit()
    br = get(api)["briefing"]
    assert br["generator"] == "claude-sonnet-5-5" and br["is_ai"] is True and br["stored"] is True
    assert [b["text"] for b in br["bullets"]] == ["Prezzi argentini in aumento.", "Seconda osservazione."]
    assert all(b["is_ai"] for b in br["bullets"])
    assert br["bullets"][0]["url"] == "https://example.org/x" and br["bullets"][0]["publisher"] == "USDA AMS"
    # yesterday's English briefing is not today's: English falls back to the rules
    assert get(api, "en")["briefing"]["generator"] == "rules"


# ---------------------------------------------------------------------------
# freshness: stale vs current
# ---------------------------------------------------------------------------


def test_stale_vs_current_labelling(api, db):
    fresh = make_source(db, "t_fresh", "prices", expected=30, latest_published=TODAY - timedelta(days=10),
                        last_run_status="success")
    stale = make_source(db, "t_stale", "prices", expected=30, latest_published=TODAY - timedelta(days=100),
                        last_run_status="no_change")
    make_source(db, "t_broken", "trade", expected=30, latest_published=TODAY - timedelta(days=40),
                last_run_status="failed")
    # newest point published 10 days ago -> current; newest point published long ago -> stale
    add_price_series(db, fresh, "ARG", "polyflora", [3.0, 3.1], last_months_back=1, published_lag_days=0)
    add_price_series(db, stale, "UKR", "sunflower", [2.0, 2.1], last_months_back=8, published_lag_days=0)
    db.commit()
    d = get(api)
    c = d["status"]["counts"]
    assert c["current"] >= 1 and c["stale"] >= 1 and c["aging"] >= 1 and c["failed"] == 1
    by_key = {s["key"]: s for s in d["status"]["sources"]}
    assert by_key["t_fresh"]["freshness"]["status"] == "current"
    assert by_key["t_stale"]["freshness"]["status"] == "stale"
    assert d["status"]["sources"][0]["key"] == "t_broken"      # failures listed first
    tiles = {t["origin_iso3"]: t for t in d["prices"]["items"]}
    assert tiles["ARG"]["freshness"]["status"] == "current"
    assert tiles["UKR"]["freshness"]["status"] == "stale"
    assert tiles["UKR"]["freshness"]["age_days"] > 200
    # a stale series is still shown (labelled), but its old move is not briefing "news"
    assert all(b.get("origin_iso3") != "UKR" for b in d["briefing"]["bullets"])


def test_offline_hint_from_last_run(api, db):
    src = make_source(db, "t_prices", "prices", last_run_status="offline")
    db.add(CollectionRun(source_id=src.id, status="success", started_at=utcnow() - timedelta(days=1),
                         finished_at=utcnow() - timedelta(days=1)))
    db.add(CollectionRun(source_id=src.id, status="offline", started_at=utcnow() - timedelta(minutes=5),
                         finished_at=utcnow() - timedelta(minutes=5)))
    db.commit()
    st = get(api)["status"]
    assert st["offline"] is True and st["counts"]["offline"] == 1 and st["last_check_at"] is not None
    assert st["never_collected"] is False


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------


def test_trade_uses_world_rows_when_present(api, db):
    src = make_source(db, "t_trade", "trade")
    y = TODAY.year - 1
    for rep, kg_prev, kg in (("USA", 200e6, 220e6), ("DEU", 90e6, 81e6), ("JPN", 40e6, 40e6)):
        add_trade(db, src, rep, "WLD", y - 1, kg_prev)
        add_trade(db, src, rep, "WLD", y, kg)
    add_trade(db, src, "USA", "ARG", y, 999e6)          # partner rows must not be added to WLD totals
    add_trade(db, src, "EU27", "WLD", y, 500e6)         # aggregates are not countries
    add_trade(db, src, "ARG", "WLD", y, 70e6, flow="export")
    db.commit()
    tr = get(api)["trade"]
    imp = tr["importers"]
    assert imp["basis"] == "world_rows"
    assert [(i["iso3"], i["net_weight_kg"]) for i in imp["items"]] == [("USA", 220e6), ("DEU", 81e6), ("JPN", 40e6)]
    assert imp["items"][0]["yoy_pct"] == pytest.approx(10.0) and imp["items"][1]["yoy_pct"] == pytest.approx(-10.0)
    assert imp["items"][0]["partners_count"] is None
    assert tr["exporters"]["basis"] == "world_rows" and tr["exporters"]["items"][0]["iso3"] == "ARG"
    assert imp["source"]["key"] == "t_trade" and imp["period_label"] == str(y)


def test_trade_skips_partial_latest_year(api, db):
    src = make_source(db, "t_trade", "trade")
    y = TODAY.year - 1
    for rep in ("USA", "DEU", "JPN", "FRA", "GBR"):
        add_trade(db, src, rep, "WLD", y - 1, 10e6)
    add_trade(db, src, "USA", "WLD", y, 12e6)           # only 1 of 5 reporters so far
    db.commit()
    imp = get(api)["trade"]["importers"]
    assert imp["period_label"] == str(y - 1) and imp["partial_latest"] is True and len(imp["items"]) == 5


def test_news_block_selection(api, market):
    nb = get(api)["news"]
    titles = [n["original_title"] for n in nb["items"]]
    assert "Argentina honey exports surge" in titles
    assert "Old but relevant story" in titles                  # within the 30-day window
    assert "Argentina honey exports surge (copy)" not in titles  # duplicates excluded
    assert "Bee festival in a small town" not in titles          # below the relevance threshold
    first = next(n for n in nb["items"] if n["original_title"] == "Argentina honey exports surge")
    assert first["title"].startswith("Le esportazioni") and first["title_is_ai"] is True
    assert first["summary"] == "Sintesi IA." and first["summary_is_ai"] is True
    assert first["countries"] == ["ARG"] and first["source"]["key"] == "t_news"
    assert nb["total_stored"] == 3 and nb["updated_at"] is not None


def test_reports_block(api, market):
    rb = get(api)["reports"]
    assert [r["title"] for r in rb["items"]] == ["National Honey Report — October", "National Honey Report — March"]
    assert rb["items"][0]["is_new"] is True and rb["items"][1]["is_new"] is False
    assert rb["new_count"] == 1 and rb["items"][0]["source"]["publisher"] == "USDA AMS"


def test_country_activity(api, market):
    items = {c["iso3"]: c for c in get(api)["countries"]["items"]}
    arg = items["ARG"]
    kinds = [r["kind"] for r in arg["reasons"]]
    assert "news" in kinds and "price" in kinds and "trade" in kinds
    assert arg["components"]["news"] == 1                      # the duplicate is not counted
    assert arg["score"] == 4 + 10 + 8                          # 1 news x4, 5% x2, new trade data
    assert list(items)[0] == "ARG"                             # highest score first
    assert "UKR" in items                                     # small price move + new trade data
    assert items["UKR"]["components"]["news"] == 0            # its news is older than 7 days


def test_alerts_and_quality(api, db):
    db.add(AlertEvent(dedup_key="a1", severity="info", title_it="Nuovo report", title_en="New report", read=False))
    db.add(AlertEvent(dedup_key="a2", severity="critical", title_it="Prezzo +10%", title_en="Price +10%",
                      link="/prezzi", read=False))
    db.add(AlertEvent(dedup_key="a3", severity="warning", title_it="Letto", title_en="Read", read=True))
    db.add(DataQualityIssue(dedup_key="q1", issue_type="stale", severity="warning", message_it="x", message_en="x"))
    db.add(DataQualityIssue(dedup_key="q2", issue_type="outlier", severity="critical", message_it="y", message_en="y"))
    db.add(DataQualityIssue(dedup_key="q3", issue_type="stale", severity="warning", message_it="z", message_en="z",
                            resolved_at=datetime(2026, 1, 1)))
    db.commit()
    d = get(api, "en")
    assert d["alerts"]["unread"] == 2
    assert [a["title"] for a in d["alerts"]["items"]] == ["Price +10%", "New report"]   # critical first
    assert d["quality"]["open"] == 2
    assert d["quality"]["by_severity"] == {"info": 0, "warning": 1, "critical": 1}


def test_price_tiles_prefer_wholesale_and_label_other_types(api, db):
    src = make_source(db, "t_prices", "prices")
    add_price_series(db, src, "ARG", "polyflora", [3.0, 3.1])
    add_price_series(db, src, "ARG", "polyflora", [2.5, 2.6], price_type="import_unit_value")
    add_price_series(db, src, "UKR", "sunflower", [2.0, 2.1], price_type="import_unit_value")
    add_price_series(db, src, "ITA", "acacia", [9.0, 9.4], currency="EUR")
    db.commit()
    p = get(api)["prices"]
    got = [(t["origin_iso3"], t["price_type"]) for t in p["items"]]
    assert got[:2] == [("ARG", "wholesale_bulk"), ("ITA", "wholesale_bulk")]
    assert set(got[2:]) == {("ARG", "import_unit_value"), ("UKR", "import_unit_value")}
    assert p["mixed_price_types"] is True
    ita = next(t for t in p["items"] if t["origin_iso3"] == "ITA")
    # changes are computed in the series' own currency; USD is not invented when FX is missing
    assert ita["currency"] == "EUR" and ita["usd_per_kg"] is None and ita["mom_pct"] == pytest.approx(4.44, abs=0.01)


def test_old_trade_figures_are_not_briefing_news(api, db):
    src = make_source(db, "t_trade", "trade")
    y = TODAY.year - 1
    add_trade(db, src, "USA", "ARG", y - 1, 50_000_000)
    add_trade(db, src, "USA", "ARG", y, 30_000_000)       # -40%, but received two months ago
    for row in db.scalars(select(TradeFlowObservation)):
        row.collected_at = utcnow() - timedelta(days=60)
    db.commit()
    d = get(api)
    assert d["briefing"]["bullets"] == []
    assert {r["key"]: r["count"] for r in d["briefing"]["rules"]}["trade"] == 0
    assert d["trade"]["importers"]["items"][0]["yoy_pct"] == pytest.approx(-40.0)   # still shown in its block


def test_briefing_caps_bullets_per_rule(api, db):
    src = make_source(db, "t_prices", "prices")
    for origin in ("ARG", "UKR", "CHN", "BRA", "VNM"):
        add_price_series(db, src, origin, "polyflora", [3.0, 3.3])        # +10% each
    db.commit()
    bullets = get(api)["briefing"]["bullets"]
    assert [b["kind"] for b in bullets] == ["price"] * 3


@pytest.mark.parametrize("months_back", [1, 5, 30])
def test_yoy_available_whatever_the_publication_lag(api, db, months_back):
    src = make_source(db, "t_prices", "prices")
    add_price_series(db, src, "ARG", "polyflora", [2.0] + [2.2] * 11 + [2.5], last_months_back=months_back)
    db.commit()
    tile = get(api)["prices"]["items"][0]
    assert tile["yoy_pct"] == pytest.approx(25.0) and tile["mom_pct"] == pytest.approx(13.64, abs=0.01)
    assert len(tile["spark"]) == 13


# ---------------------------------------------------------------------------
# series identity (terms, frequency) and query count
# ---------------------------------------------------------------------------


def _price_row(db, src: Source, *, origin: str, variety: str, start: date, freq: str, value: float,
               terms: str | None = None, price_type: str = "import_unit_value") -> None:
    if freq == "A":
        start, end = year_bounds(start.year)
        label = str(start.year)
    else:
        _, end = month_bounds(start.year, start.month)
        label = f"{start:%Y-%m}"
    ingest.record(
        db, PriceObservation, source_id=src.id, series_key=f"{price_type}|{origin}|{variety}|{freq}|{terms}|{label}",
        price_type=price_type, origin_iso3=origin, origin_label=origin, market_iso3="USA", variety=variety,
        terms=terms, price_value=value, currency="USD", unit="kg", price_per_kg=value, usd_per_kg=value,
        eur_per_kg=round(value / 1.1, 4), period_start=start, period_end=end, period_label=label, frequency=freq,
        published_at=end + timedelta(days=30), source_url="https://example.org/x", data_status="published",
        reliability=src.reliability,
    )


def test_two_packagings_of_one_variety_are_two_series_not_a_price_move(api, db):
    onm = make_source(db, "t_onm", "prices", publisher="Osservatorio")
    # drums and tins of the same honey, both flat for three months
    add_price_series(db, onm, "ITA", "polyflora", [4.25] * 3, currency="EUR", market="ITA",
                     terms="fusto 300 kg; mercato all'ingrosso")
    add_price_series(db, onm, "ITA", "polyflora", [6.25] * 3, currency="EUR", market="ITA",
                     terms="secchio 25 kg; mercato all'ingrosso")
    db.commit()
    d = get(api)
    tiles = [t for t in d["prices"]["items"] if t["origin_iso3"] == "ITA"]
    assert len(tiles) == 2 and d["prices"]["series_available"] == 2
    assert sorted(t["price_per_kg"] for t in tiles) == [4.25, 6.25]
    for t in tiles:
        assert t["mom_pct"] == 0.0
        assert [p["value"] for p in t["spark"]] == [t["price_per_kg"]] * 3        # no zig-zag
    # the two tiles are told apart by their packaging
    assert {t["label_hint"] for t in tiles} == {"fusto 300 kg", "secchio 25 kg"}
    assert len({t["label"] for t in tiles}) == 2
    assert all(b["kind"] != "price" for b in d["briefing"]["bullets"])
    assert {r["key"]: r["count"] for r in d["briefing"]["rules"]}["prices"] == 0
    assert all(c["components"]["price_mom_pct"] in (None, 0.0) for c in d["countries"]["items"])


def test_two_honeys_of_one_variety_bucket_are_never_a_price_move(api, db):
    """Review 2026-11-05: CCIAA Cuneo lists 'Millefiori di Alta Montagna' (6.75) and 'Rododendro' (8.00) both as
    variety 'other', flat for months. The briefing said 'Italy · Other — up 18.5% month on month' (8.00 against
    6.75: two different honeys). Changes and the sparkline follow the source's own variety text."""
    cuneo = make_source(db, "t_cuneo", "prices", publisher="CCIAA Cuneo")
    terms = "secchio da 25 kg; franco partenza dal magazzino; IVA compresa"
    for months_back in (3, 2, 1):
        start = month_start(months_back)
        _, end = month_bounds(start.year, start.month)
        for raw, v in (("Millefiori di Alta Montagna", 6.75), ("Rododendro", 8.0)):
            ingest.record(
                db, PriceObservation, source_id=cuneo.id, series_key=f"wholesale_bulk|{raw}|{start:%Y-%m}",
                price_type="wholesale_bulk", origin_iso3="ITA", origin_label="Italia", market_iso3="ITA",
                market_location="Cuneo", variety="other", variety_raw=raw, terms=terms, price_value=v,
                currency="EUR", unit="kg", price_per_kg=v, eur_per_kg=v, usd_per_kg=round(v * 1.1, 4),
                period_start=start, period_end=end, period_label=f"{start:%Y-%m}", frequency="M",
                published_at=end + timedelta(days=10), source_url="https://example.org/listino.pdf",
                data_status="published", reliability=cuneo.reliability)
    db.commit()
    d = get(api, "en")
    tile = next(t for t in d["prices"]["items"] if t["origin_iso3"] == "ITA")
    assert tile["variety_raw"] == "Rododendro" and tile["price_per_kg"] == 8.0
    assert tile["mom_pct"] == 0.0
    assert [p["value"] for p in tile["spark"]] == [8.0, 8.0, 8.0]          # no zig-zag between the two honeys
    assert all(b["kind"] != "price" for b in d["briefing"]["bullets"])
    assert all(c["components"]["price_mom_pct"] in (None, 0.0) for c in d["countries"]["items"])


def test_annual_row_is_not_a_point_of_the_monthly_series(api, db):
    src = make_source(db, "t_comtrade", "prices")
    jan = TODAY.replace(month=1, day=1)
    year_before = jan - relativedelta(years=1)
    # the annual figure for last year is stored first: it shares 1 January with the monthly row
    _price_row(db, src, origin="ARG", variety="unspecified", start=year_before, freq="A", value=9.0)
    _price_row(db, src, origin="ARG", variety="unspecified", start=year_before, freq="M", value=2.0)
    _price_row(db, src, origin="ARG", variety="unspecified", start=jan, freq="M", value=2.5)
    db.commit()
    tiles = {t["frequency"]: t for t in get(api, "en")["prices"]["items"]}
    assert set(tiles) == {"A", "M"}
    assert tiles["M"]["yoy_pct"] == pytest.approx(25.0) and tiles["M"]["yoy_period_label"] == f"{year_before:%Y-%m}"
    assert [p["value"] for p in tiles["M"]["spark"]] == [2.0, 2.5]
    assert tiles["A"]["yoy_pct"] is None and tiles["A"]["mom_pct"] is None
    assert {tiles["A"]["label_hint"], tiles["M"]["label_hint"]} == {"annual", "monthly"}


def test_long_stale_series_history_is_loaded_in_one_query(db):
    from sqlalchemy import event

    from paladex.api.overview import Ctx, series_changes

    src = make_source(db, "t_fao", "production")
    y = TODAY.year - 3                                   # newest annual point far outside the bulk window
    origins = ["ARG", "UKR", "CHN", "BRA", "VNM", "IND", "HUN", "ITA", "MEX", "URY"]
    varieties = ["polyflora", "acacia", "sunflower", "clover", "eucalyptus"]
    for o in origins:
        for v in varieties:
            _price_row(db, src, origin=o, variety=v, start=date(y - 1, 1, 1), freq="A", value=2.0, price_type="producer")
            _price_row(db, src, origin=o, variety=v, start=date(y, 1, 1), freq="A", value=2.2, price_type="producer")
    db.commit()

    statements: list[str] = []
    engine = db.get_bind()

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    ctx = Ctx(db, "en")
    event.listen(engine, "before_cursor_execute", count)
    try:
        series = ctx.price_series()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(series) == 50
    assert len(statements) <= 4                          # not one query per stale series
    for s in series:
        assert [p.period_label for p in s.points] == [str(y - 1), str(y)]
        assert series_changes(s)["yoy_pct"] == pytest.approx(10.0)


def test_expected_sources_list_official_first(api):
    """Empty-state 'expected source' lists name government/official sources before third parties."""
    body = api.get("/api/overview").json()
    from paladex.db import session_scope
    from paladex.models import Source

    with session_scope() as s:
        rel = {x.key: x.reliability for x in s.query(Source).all()}
    rank = {"official": 0, "industry": 1, "trade_press": 2, "aggregator": 3}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("providers", "expected_sources") and isinstance(v, list) and v and isinstance(v[0], dict):
                    enabled = [p for p in v if p.get("enabled", True)]
                    ranks = [rank.get(rel.get(p["key"]), 9) for p in enabled]
                    assert ranks == sorted(ranks), (k, [p["key"] for p in enabled])
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(body)


def test_weekly_customs_values_are_not_reported_as_monthly_moves(api):
    """Real TAXUD weekly cells swing +200 % week to week: never a 'move in a month' in the summary."""
    from datetime import date, timedelta

    from sqlalchemy import select

    from paladex.db import session_scope
    from paladex.models import PriceObservation, Source
    from paladex.services import ingest

    with session_scope() as s:
        src = s.scalars(select(Source).where(Source.key == "ec_taxud_weekly")).one()
        start = date.today() - timedelta(days=date.today().weekday()) - timedelta(days=14)
        for i, v in enumerate((1.5, 4.5)):
            ps = start + timedelta(days=7 * i)
            ingest.record(s, PriceObservation, source_id=src.id, series_key=f"w|{i}", price_type="import_unit_value",
                          origin_iso3="TUR", market_iso3="DEU", variety="unspecified", price_value=v, price_per_kg=v,
                          eur_per_kg=v, usd_per_kg=v, volume_kg=50_000.0, currency="EUR", unit="kg", frequency="W",
                          period_start=ps, period_end=ps + timedelta(days=6), period_label=f"2026-W{40 + i}",
                          data_status="provisional", reliability="official")
    body = api.get("/api/overview").json()
    text = str(body["briefing"]) + str(body["countries"])
    assert "200" not in text or "TUR" not in text


def test_briefing_wording_and_labels():
    """Review 2026-11-05: 'in rialzo del 84,5%', 'rispetto a 2023', a raw '2026-W44' and a terms hint cut in the
    middle of a word ('(imports for consumpti')."""
    from paladex.api import overview as ov

    assert ov._of_pct("84,5%", "it") == "dell'" and ov._of_pct("11,0%", "it") == "dell'"
    assert ov._of_pct("1,2%", "it") == "dell'" and ov._of_pct("18,5%", "it") == "del " and ov._of_pct("8%", "en") == ""
    assert ov._vs_period("2023", "it") == "rispetto al 2023" and ov._vs_period("2025-08", "it") == "rispetto ad ago 2025"
    assert ov._vs_period("2025-09", "it") == "rispetto a set 2025" and ov._vs_period("2023", "en") == "vs 2023"
    assert ov.fmt_period("2026-W44", "it") == "settimana 44 del 2026" and ov.fmt_period("2026-W44", "en") == "week 44 of 2026"
    census = "US customs value / net kg (imports for consumption; excludes freight, insurance & duty), HS 0409 total"
    assert ov._term_parts(census) == [
        "US customs value / net kg (imports for consumption; excludes freight, insurance & duty)", "HS 0409 total"]
    assert ov._short("a" * 10 + " " + "b" * 50) == "a" * 10 + "…"
