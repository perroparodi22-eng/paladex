"""AI assistant (services/assistant.py, api/assistant.py) and daily AI briefing (services/briefing.py).

Covers: question understanding (countries incl. adjectives, varieties, price types, time words,
sources, offers), validation of entities suggested by the model, retrieval per question type on
fixture rows (prices never mixed, stale series left out, comparable periods, trade ranking, news,
reports, duties grouped by quota, events in a window, supplier offers only when asked), the number
post-check (formatting tolerant, invented figures rejected), citation validation, the no-AI path,
a mocked Anthropic call (respx) with sentence dropping and whole-answer rejection, privacy of
supplier offers, and the briefing generation in the format the overview reads.

Fixture values are illustrative (dates relative to today); they imitate the shape of real rows.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import pytest
import respx
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select

from paladex import config
from paladex.collectors.base import month_bounds, year_bounds
from paladex.models import (
    Briefing,
    FxRate,
    NewsArticle,
    PriceObservation,
    ProductionStat,
    RegulationItem,
    Report,
    Source,
    SupplierQuote,
    TariffMeasure,
    TradeFlowObservation,
    utcnow,
)
from paladex.services import assistant as A
from paladex.services import briefing as B
from paladex.services import ingest, llm

TODAY = date.today()


# ---------------------------------------------------------------------------
# fixture rows
# ---------------------------------------------------------------------------


def src(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def month_start(back: int) -> date:
    return TODAY.replace(day=1) - relativedelta(months=back)


def add_prices(db, key: str, origin: str, values: list[float], *, price_type: str = "wholesale_bulk",
               market: str = "USA", variety: str = "polyflora", currency: str = "USD", last_back: int = 1,
               status: str = "published", color: str | None = None, terms: str | None = None,
               published: bool = True, url: str = "https://example.org/prices") -> None:
    """Monthly values oldest -> newest; the newest one `last_back` months ago."""
    s = src(db, key)
    n = len(values)
    for i, v in enumerate(values):
        start = month_start(last_back + n - 1 - i)
        _, end = month_bounds(start.year, start.month)
        ingest.record(
            db, PriceObservation, source_id=s.id,
            series_key=f"{price_type}|{origin}|{market}|{variety}|{color}|{start:%Y-%m}",
            price_type=price_type, origin_iso3=origin, origin_label=origin, market_iso3=market, variety=variety,
            color_grade=color, terms=terms, price_value=v, currency=currency, unit="kg", price_per_kg=v,
            usd_per_kg=v if currency == "USD" else None, eur_per_kg=round(v / 1.12, 4) if currency != "EUR" else v,
            period_start=start, period_end=end, period_label=f"{start:%Y-%m}", frequency="M",
            published_at=end + timedelta(days=12) if published else None, source_url=url,
            data_status=status, reliability=s.reliability,
        )


def add_monthly_trade(db, reporter: str, partner: str, year: int, months: int, kg_per_month: float,
                      *, flow: str = "import", key: str = "eurostat_comext", eur_per_kg: float = 2.2) -> None:
    s = src(db, key)
    for m in range(1, months + 1):
        start, end = month_bounds(year, m)
        ingest.record(
            db, TradeFlowObservation, source_id=s.id, series_key=f"{reporter}|{partner}|{flow}|{year}-{m:02d}",
            hs_code="0409", reporter_iso3=reporter, partner_iso3=partner, flow=flow, net_weight_kg=kg_per_month,
            value=kg_per_month * eur_per_kg, currency="EUR", period_start=start, period_end=end,
            period_label=f"{year}-{m:02d}", frequency="M", published_at=date(year, m, 28) + timedelta(days=45),
            source_url="https://ec.europa.eu/eurostat/comext", data_status="provisional", reliability="official",
        )


def add_annual_trade(db, reporter: str, partner: str, year: int, kg: float, *, flow: str = "export",
                     key: str = "un_comtrade") -> None:
    s = src(db, key)
    start, end = year_bounds(year)
    ingest.record(
        db, TradeFlowObservation, source_id=s.id, series_key=f"{reporter}|{partner}|{flow}|{year}",
        hs_code="0409", reporter_iso3=reporter, partner_iso3=partner, flow=flow, net_weight_kg=kg,
        value=kg * 2.4, currency="USD", usd_value=kg * 2.4, period_start=start, period_end=end,
        period_label=str(year), frequency="A", published_at=date(year + 1, 5, 2),
        source_url="https://comtradeapi.un.org/", data_status="published", reliability="official",
    )


def add_news(db, title: str, *, countries: list[str] | None = None, days_ago: float = 1, relevance: int = 70,
             snippet: str | None = None, key: str = "news_apimondia") -> NewsArticle:
    s = src(db, key)
    url = f"https://news.example.org/{abs(hash(title))}"
    a = NewsArticle(source_id=s.id, url=url, canonical_url=url, title=title, title_norm=title.lower(),
                    publisher="Honey Times", language="en", published_at=utcnow() - timedelta(days=days_ago),
                    countries=countries or [], relevance_score=relevance, snippet=snippet)
    db.add(a)
    db.flush()
    return a


def add_report(db, title: str, *, days_ago: int, narrative: str | None, key: str = "usda_honey_report",
               period: str | None = None) -> Report:
    s = src(db, key)
    r = Report(source_id=s.id, report_key=title, title=title, period_label=period,
               published_at=TODAY - timedelta(days=days_ago), url=f"https://example.org/{abs(hash(title))}.pdf",
               narrative=narrative)
    db.add(r)
    db.flush()
    return r


def add_measure(db, key: str, **kw) -> TariffMeasure:
    defaults = {"hs_code": "0409000000", "as_of": TODAY, "data_status": "published", "reliability": "official",
                "value_hash": key, "is_current": True, "revision": 1, "jurisdiction": "EU"}
    m = TariffMeasure(source_id=src(db, "eu_tariff_xi").id, series_key=key, **{**defaults, **kw})
    db.add(m)
    db.flush()
    return m


def add_quote(db, supplier: str, origin: str, price: float, **kw) -> SupplierQuote:
    q = SupplierQuote(supplier_name=supplier, origin_iso3=origin, variety=kw.pop("variety", "polyflora"),
                      price_per_kg=price, currency=kw.pop("currency", "USD"), incoterm=kw.pop("incoterm", "CIF"),
                      date_received=kw.pop("date_received", TODAY - timedelta(days=2)),
                      notes=kw.pop("notes", None), quantity_kg=kw.pop("quantity_kg", 20000), **kw)
    db.add(q)
    db.flush()
    return q


@pytest.fixture()
def market(db):
    """A small market: USDA wholesale + Eurostat unit values (ARG, UKR), a stale FAOSTAT producer price,
    Comtrade exports, FAOSTAT production, news, an AD notice, EU duties, ECB rates."""
    add_prices(db, "usda_honey_report", "ARG", [3.50, 3.55, 3.60, 3.58, 3.62, 3.70, 3.72, 3.75, 3.80, 3.85, 3.84,
                                                3.88, 3.90, 4.05], color="white",
               terms="bulk honey, paid to importers, duty paid, containers included")
    add_prices(db, "eurostat_comext", "ARG", [2.10, 2.12, 2.15, 2.18, 2.20, 2.22, 2.25, 2.28, 2.30, 2.31, 2.33, 2.36,
                                              2.40, 2.50], price_type="import_unit_value", market="EU27",
               variety="unspecified", currency="EUR", status="provisional", terms="CIF")
    add_prices(db, "eurostat_comext", "UKR", [2.60, 2.62, 2.64, 2.66, 2.70, 2.72, 2.75, 2.80, 2.85, 2.90, 2.92, 2.95,
                                              3.10, 2.97], price_type="import_unit_value", market="EU27",
               variety="unspecified", currency="EUR", status="provisional", terms="CIF")
    # a 2014 producer price: far too old to say anything about today
    s = src(db, "faostat")
    ingest.record(db, PriceObservation, source_id=s.id, series_key="producer|ARG|2014", price_type="producer",
                  origin_iso3="ARG", market_iso3="ARG", variety="unspecified", price_value=2698.1, currency="USD",
                  unit="t", price_per_kg=2.6981, usd_per_kg=2.6981, period_start=date(2014, 1, 1),
                  period_end=date(2014, 12, 31), period_label="2014", frequency="A", published_at=TODAY - timedelta(days=30),
                  source_url="https://faostat.example/prices.zip", data_status="published", reliability="official")
    add_annual_trade(db, "ARG", "WLD", TODAY.year - 2, 78_375_000)
    add_annual_trade(db, "ARG", "WLD", TODAY.year - 1, 81_820_000)
    fao = src(db, "faostat")
    for y, t in ((TODAY.year - 3, 69_701), (TODAY.year - 2, 69_298)):
        ingest.record(db, ProductionStat, source_id=fao.id, series_key=f"prod|ARG|{y}", country_iso3="ARG",
                      metric="production", value=t, unit="t", period_start=date(y, 1, 1), period_end=date(y, 12, 31),
                      period_label=str(y), frequency="A", published_at=date(y + 1, 12, 31),
                      source_url="https://faostat.example/production.zip",
                      data_status="estimate" if y == TODAY.year - 2 else "published", reliability="official")
    add_news(db, "China honey exports rise as packers seek new buyers", countries=["CHN"], days_ago=2,
             snippet="Chinese exporters shipped 12,500 tonnes in September, customs data show.")
    add_news(db, "Argentina: beekeepers expect a smaller harvest", countries=["ARG"], days_ago=3, relevance=65)
    add_news(db, "Old story about Chinese honey", countries=["CHN"], days_ago=90)
    db.add(RegulationItem(source_id=src(db, "us_federal_register").id, jurisdiction="US", doc_type="antidumping",
                          reference="2026-18701", title="Raw Honey From Argentina: Preliminary Results of Antidumping "
                          "Duty Administrative Review", status="published", published_at=TODAY - timedelta(days=20),
                          url="https://www.federalregister.gov/d/2026-18701", countries=["ARG"]))
    add_measure(db, "eu|mfn", origin_iso3="ERGA_OMNES", measure_type="mfn", measure_code="103", duty_text="17.30 %",
                ad_valorem_pct=17.3, legal_reference="R2658/87", legal_url="https://eur-lex.europa.eu/eli/reg/1987/2658")
    for o in ("ARG", "BRA"):
        add_measure(db, f"eu|trq|{o}", origin_iso3=o, measure_type="trq_in", measure_code="143", duty_text="0.00 %",
                    ad_valorem_pct=0.0, quota_order_number="090881", quota_volume_kg=1_722_960,
                    quota_balance_kg=1_304_730, quota_status="open", valid_from=date(TODAY.year, 5, 1),
                    valid_to=date(TODAY.year, 12, 31), extra={"quota": {"shared_by_group": True}})
    add_measure(db, "eu|trq|UKR", origin_iso3="UKR", measure_type="trq_in", measure_code="143", duty_text="0.00 %",
                ad_valorem_pct=0.0, quota_order_number="096701", quota_volume_kg=35_000_000, quota_balance_kg=0,
                quota_status="exhausted", valid_from=date(TODAY.year, 1, 1), valid_to=date(TODAY.year, 12, 31))
    for back, rate in ((0, 1.1267), (3, 1.1250), (31, 1.1204), (366, 1.1491)):
        db.add(FxRate(rate_date=TODAY - timedelta(days=back), currency="USD", per_eur=rate))
    db.commit()
    return db


def ask(db, question: str, lang: str = "it", **kw) -> dict:
    return A.answer(db, question, lang, save=False, **kw)


def facts_of(ans: dict, kind: str) -> list[dict]:
    return [f for f in ans["facts"] if f["kind"] == kind]


# ---------------------------------------------------------------------------
# understanding the question
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, expect", [
    ("Cosa sta succedendo ai prezzi del miele argentino?", {"countries": ["ARG"], "mode": "country", "topic": "prices"}),
    ("What is happening to Argentine honey prices?", {"countries": ["ARG"], "mode": "country", "topic": "prices"}),
    ("Confronta Argentina e Ucraina", {"countries": ["ARG", "UKR"], "mode": "compare"}),
    ("Compare Argentina and Ukraine", {"countries": ["ARG", "UKR"], "mode": "compare"}),
    ("Quali paesi hanno aumentato le esportazioni quest'anno?",
     {"countries": [], "mode": "trade_ranking", "flow": "export", "direction": "increase", "year": TODAY.year}),
    ("Ultime notizie sul mercato cinese", {"countries": ["CHN"], "mode": "country", "topic": "news"}),
    ("Cosa è successo questa settimana nel mercato mondiale?", {"countries": [], "mode": "events", "days": 7}),
    ("Quali sviluppi recenti possono influire sui nostri costi di acquisto?", {"countries": [], "mode": "costs"}),
    ("Riassumi l'ultimo report USDA", {"countries": [], "mode": "report", "source": "usda_honey_report"}),
    ("Summarize the latest USDA report", {"countries": [], "mode": "report", "source": "usda_honey_report"}),
    ("Confronta queste tre offerte", {"countries": [], "mode": "quotes"}),
    ("Compare these three offers", {"countries": [], "mode": "quotes"}),
    ("prezzo del miele di acacia ungherese all'ingrosso",
     {"countries": ["HUN"], "varieties": ["acacia"], "price_types": ["wholesale_bulk"]}),
    ("miele spagnolo nel 2024", {"countries": ["ESP"], "year": 2024}),
    ("valori unitari all'import dalla Cina", {"countries": ["CHN"], "price_types": ["import_unit_value"]}),
    ("Ci sono novità sui dazi USA per il miele brasiliano?", {"countries": ["BRA"], "jurisdictions": ["US"]}),
    ("honey in India and Mexico in the last 3 months", {"countries": ["IND", "MEX"], "days": 90}),
    ("Quali paesi hanno ridotto le importazioni nel 2025?", {"flow": "import", "direction": "decrease", "year": 2025}),
    ("Quanto costa il miele millefiori bio?", {"varieties": ["organic_polyflora"], "mode": "prices"}),
])
def test_parse_question(text, expect):
    q = A.parse_question(text, "it")
    if "countries" in expect:
        assert q.countries == expect["countries"], q.countries
    for key in ("mode", "flow", "direction", "varieties", "price_types", "jurisdictions"):
        if key in expect:
            assert getattr(q, key) == expect[key], (key, getattr(q, key))
    if "topic" in expect:
        assert expect["topic"] in q.topics
    if "year" in expect:
        assert q.period is not None and q.period.kind == "year" and q.period.year == expect["year"]
    if "days" in expect:
        assert q.period is not None and q.period.days == expect["days"]
    if "source" in expect:
        assert expect["source"] in q.source_keys


def test_entities_from_the_model_are_validated(monkeypatch):
    q = A.parse_question("qualcosa di poco chiaro", "it")
    assert A._understood_nothing(q)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "countries": ["arg", "XXX", "WLD", 7], "varieties": ["acacia", "unicorn"], "price_types": ["wholesale_bulk", "bogus"],
        "topics": ["prices", "hack"], "flow": "sideways", "period_days": 99999, "year": 1700})
    q = A.llm_entities(q)
    assert q.countries == ["ARG"] and q.varieties == ["acacia"] and q.price_types == ["wholesale_bulk"]
    assert q.topics == {"prices"} and q.flow is None and q.period is None and q.llm_entities


# ---------------------------------------------------------------------------
# retrieval
# ---------------------------------------------------------------------------


def test_prices_of_an_origin_one_series_per_fact_with_provenance(market):
    ans = ask(market, "Cosa sta succedendo ai prezzi del miele argentino?")
    prices = facts_of(ans, "price")
    assert {p["price_type"] for p in prices} == {"wholesale_bulk", "import_unit_value"}
    for f in ans["facts"]:
        assert f["source"] and f["status"] in A.STATUS_LABELS and f["status_label"]
        assert f["url"], f
    wholesale = next(p for p in prices if p["price_type"] == "wholesale_bulk")
    assert "prezzo all'ingrosso (sfuso), mercato: Stati Uniti" in wholesale["text"]
    assert "4,05 USD/kg" in wholesale["text"] and wholesale["period_label"] == f"{month_start(1):%Y-%m}"
    # m/m and y/y on the same series: 4.05 vs 3.90 (+3.85 %) and vs 3.55 twelve months earlier (+14.08 %)
    assert "+3,9% sul mese precedente" in wholesale["text"] and "+14,1% sullo stesso periodo" in wholesale["text"]
    assert wholesale["status"] == "verified_official"
    eu = next(p for p in prices if p["price_type"] == "import_unit_value")
    assert eu["status"] == "provisional" and "mercato: Unione Europea (CIF)" in eu["text"]
    assert "Non specificata" not in eu["text"]            # an unspecified variety is not shown as one
    assert all("2014" not in p["text"] for p in prices), "a 2014 producer price says nothing about today"
    assert facts_of(ans, "regulation") and "Stati Uniti — antidumping" in facts_of(ans, "regulation")[0]["text"]
    assert [f["title"] for f in facts_of(ans, "news")] == ["Argentina: beekeepers expect a smaller harvest"]
    assert not facts_of(ans, "quote")


def test_compare_reads_the_latest_common_period(market):
    ans = ask(market, "Confronta Argentina e Ucraina")
    eu = [f for f in facts_of(ans, "price") if f["price_type"] == "import_unit_value"]
    by_country = {f["country"]: f for f in eu}
    assert set(by_country) == {"ARG", "UKR"}
    assert by_country["ARG"]["period_label"] == by_country["UKR"]["period_label"] == f"{month_start(1):%Y-%m}"
    assert "2,50 EUR/kg" in by_country["ARG"]["text"] and "2,97 EUR/kg" in by_country["UKR"]["text"]
    duties = facts_of(ans, "duty")
    assert any("096701 (Ucraina)" in d["text"] and "esaurito" in d["text"] for d in duties)
    assert any("17,3%" in d["text"] for d in duties)
    trade = facts_of(ans, "trade")
    assert any("Argentina — esportazioni totali di miele" in t["text"] and "81.820 t" in t["text"] for t in trade)
    prod = facts_of(ans, "production")
    assert prod and prod[0]["status"] == "estimate" and "69.298 t" in prod[0]["text"]


def test_trade_ranking_by_change_in_tonnes(db):
    y = TODAY.year - 1
    for partner, prev, cur in (("ARG", 1_000_000, 1_200_000), ("CHN", 3_000_000, 3_500_000),
                               ("UKR", 2_000_000, 1_500_000), ("THA", 20_000, 80_000)):
        add_monthly_trade(db, "EU27", partner, y - 1, 6, prev)
        add_monthly_trade(db, "EU27", partner, y, 6, cur)
    db.commit()
    ans = ask(db, f"Quali paesi hanno aumentato le esportazioni nel {y}?")
    assert ans["understood"]["mode"] == "trade_ranking"
    trade = facts_of(ans, "trade")
    assert [t["country"] for t in trade] == ["CHN", "ARG"], "ranked by tonnes gained; falls and small flows left out"
    assert "gen–giu" in trade[0]["text"] and "21.000 t" in trade[0]["text"] and "18.000 t" in trade[0]["text"]
    assert any("2 origini su 3 (oltre 500 t)" in n for n in ans["notes"])
    down = ask(db, f"Quali paesi hanno ridotto le esportazioni nel {y}?")
    assert [t["country"] for t in facts_of(down, "trade")] == ["UKR"]


def test_news_of_a_country_and_honest_empty_result(market):
    ans = ask(market, "Ultime notizie sul mercato cinese")
    news = facts_of(ans, "news")
    assert [n["title"] for n in news] == ["China honey exports rise as packers seek new buyers"]
    assert news[0]["status"] == "press" and news[0]["status_label"] == "Notizia (non verificata)"
    assert "estratto della fonte" in news[0]["text"] and "12,500 tonnes" in news[0]["text"]
    news_section = next(s for s in ans["sections"] if s["key"] == "news")
    assert news_section["title"] == "Notizie"
    empty = ask(market, "Ultime notizie sul Messico")
    assert not facts_of(empty, "news")
    assert any("Nessuna notizia su Messico negli ultimi 30 giorni" in n for n in empty["notes"])


def test_report_summary_quotes_the_latest_commentary_only(market):
    add_report(market, "National Honey Report – old", days_ago=700, narrative="Old commentary about 2024 colonies.")
    latest = add_report(market, "National Honey Report – latest", days_ago=5, narrative=None, period=f"{month_start(1):%Y-%m}")
    market.commit()
    ans = ask(market, "Riassumi l'ultimo report USDA")
    reports = facts_of(ans, "report")
    assert [r["title"] for r in reports] == [latest.title]
    assert not facts_of(ans, "report_text"), "a two-year-old commentary is not passed off as the latest"
    assert any("non contiene un testo di commento" in n for n in ans["notes"])
    assert any("troppo vecchio" in n for n in ans["notes"])
    with_text = add_report(market, "National Honey Report – newest", days_ago=1,
                           narrative="Demand for imported white honey was steady; offers from Argentina at 1.80 $/lb.")
    market.commit()
    ans = ask(market, "Summarize the latest USDA report", "en")
    assert facts_of(ans, "report")[0]["title"] == with_text.title
    text = facts_of(ans, "report_text")[0]
    assert "the source's own text" in text["text"] and "1.80 $/lb" in text["text"]


def test_duties_group_a_shared_quota_and_costs_question(market):
    ans = ask(market, "Quali sviluppi recenti possono influire sui nostri costi di acquisto?")
    assert ans["understood"]["mode"] == "costs"
    duties = facts_of(ans, "duty")
    shared = [d for d in duties if "090881" in d["text"]]
    assert len(shared) == 1 and "(Argentina, Brasile)" in shared[0]["text"]
    assert "residuo 1.305 t su 1.723 t (24% utilizzato), stato: aperto (contingente condiviso con altri paesi)" in shared[0]["text"]
    fx = facts_of(ans, "fx")
    assert fx and "1 EUR = 1,1267 USD" in fx[0]["text"] and "+0,6% in un mese" in fx[0]["text"]
    assert all(f["country"] != "ITA" for f in facts_of(ans, "price")), "domestic Italian prices are not purchase costs"


def test_events_of_the_week_only_what_was_published_in_it(market):
    add_report(market, "National Honey Report – this week", days_ago=2, narrative=None)
    # collected now but about a period of 20 months ago and without a publication date: not this week's news
    add_prices(market, "cciaa_cuneo_miele", "ITA", [7.0, 7.0], market="ITA", variety="dandelion", currency="EUR",
               last_back=20, published=False)
    add_prices(market, "eurostat_comext", "CHN", [1.10, 1.12], price_type="import_unit_value", market="EU27",
               variety="unspecified", currency="EUR", status="provisional")
    market.commit()
    ans = ask(market, "Cosa è successo questa settimana nel mercato mondiale?")
    assert ans["understood"]["mode"] == "events"
    assert [r["title"] for r in facts_of(ans, "report")] == ["National Honey Report – this week"]
    assert all(f["country"] != "ITA" for f in facts_of(ans, "price"))
    assert [n["title"] for n in facts_of(ans, "news")] == ["China honey exports rise as packers seek new buyers",
                                                           "Argentina: beekeepers expect a smaller harvest"]


def test_supplier_offers_only_for_questions_about_offers(market):
    add_quote(market, "Apicultores del Sur SA", "ARG", 3.20, notes="sconto se paghiamo in anticipo")
    add_quote(market, "Kyiv Honey LLC", "UKR", 3.05)
    add_quote(market, "Mel do Brasil Ltda", "BRA", 3.40, valid_until=TODAY - timedelta(days=1))   # expired
    market.commit()
    plain = ask(market, "Confronta Argentina e Ucraina")
    assert not facts_of(plain, "quote") and not plain["private_data_used"]
    ans = ask(market, "Confronta queste tre offerte")
    quotes = facts_of(ans, "quote")
    assert [q["title"].split(" — ")[0] for q in quotes] == ["Kyiv Honey LLC", "Apicultores del Sur SA"]
    assert all(q["private"] and q["status"] == "user" for q in quotes)
    assert any("Confronto le 2 offerte valide più recenti" in n for n in ans["notes"])
    assert ans["sections"][0]["key"] == "quotes" and ans["sections"][0]["title"] == "Le vostre offerte"
    assert "3,20 USD/kg CIF" in quotes[1]["text"] and "sconto" not in quotes[1]["text"]
    picked = ask(market, "Confronta", quote_ids=[quotes[1]["quote_id"]])
    assert picked["understood"]["mode"] == "quotes"
    assert [q["quote_id"] for q in facts_of(picked, "quote")] == [quotes[1]["quote_id"]]


def test_landed_cost_of_an_offer_comes_from_the_calculator(market):
    q = add_quote(market, "Apicultores del Sur SA", "ARG", 3.20, incoterm="CIF", insurance_pct=None)
    for back in (0, 1, 2, 3):
        market.add(FxRate(rate_date=q.date_received - timedelta(days=back), currency="EUR", per_eur=1.0))
    market.commit()
    from paladex.services import landed_cost as lc

    expected = lc.calculate(market, lc.input_from_model(q))["headline"]
    text = A.landed_cost_text(market, q, "it")
    if expected["eur_per_kg_min"] is None:
        assert text is None
    else:
        assert text.startswith("costo sbarcato calcolato da Paladex: ") and A._num(expected["eur_per_kg_min"], "it") in text


# ---------------------------------------------------------------------------
# post-check: numbers and citations
# ---------------------------------------------------------------------------

BASIS = ("Importazioni UE di miele da Argentina, gen–ago 2026: 20.773 t (valore unitario medio 2,22 EUR/kg); "
         "gen–ago 2025: 12.960 t (+60,3%). Prezzo 3,957 USD/kg; 1.234,5 t; quota 1.722.960 kg; 12 %.")


@pytest.mark.parametrize("sentence", [
    "EU imports from Argentina reached 20,773 t in Jan–Aug 2026, up 60.3%.",
    "Le importazioni sono state 20.773 t (+60,3%), a 2,22 EUR/kg.",
    "The unit value was 2.22 EUR/kg.",
    "Il prezzo era 3,96 USD/kg.",                 # rounded to fewer decimals
    "Volume 1,234.5 t.",                          # English vs Italian separators
    "Volume 1 234,5 t.",                          # thin-space thousands
    "The quota is 1,722,960 kg; 12% of it.",
    "Gen–ago 2025: 12.960 t.",
])
def test_post_check_accepts_numbers_of_the_context(sentence):
    assert A.unsupported_numbers(sentence, BASIS) == []


@pytest.mark.parametrize("sentence, bad", [
    ("Le importazioni sono salite a 21.500 t.", ["21.500"]),
    ("The unit value was 2.50 EUR/kg.", ["2.50"]),
    ("Il valore era 222 EUR/kg.", ["222"]),        # a decimal shift is not a formatting difference
    ("Up 61% on the year.", ["61"]),               # rounding to an integer changes the figure
    ("Prices will reach 4 USD/kg in 2027.", ["4", "2027"]),
])
def test_post_check_rejects_invented_numbers(sentence, bad):
    assert A.unsupported_numbers(sentence, BASIS) == bad


def test_extract_citations():
    assert A.extract_citations("Prezzo 3,96 USD/kg [2][5].") == ("Prezzo 3,96 USD/kg.", [2, 5])
    assert A.extract_citations("Up [2, 3; 7] and [4-6]") == ("Up and", [2, 3, 7, 4, 5, 6])
    assert A.extract_citations("Nessuna citazione.") == ("Nessuna citazione.", [])


def test_check_sentences_validates_citations_and_numbers():
    fs = A.FactSet()
    fs.add(A.Fact(kind="price", title="ARG", text="Argentina: 3,91 USD/kg, set 2026.", status="verified_official"))
    fs.add(A.Fact(kind="quote", title="Offer", text="Supplier X (Offerta A): 3,20 USD/kg.", status="user", private=True))
    items = [
        {"text": "Il miele argentino vale 3,91 USD/kg.", "refs": [1]},          # ok
        {"text": "Il miele argentino vale 3,91 USD/kg [1]."},                  # citation in the text: ok
        {"text": "Il miele argentino vale 4,10 USD/kg.", "refs": [1]},          # invented number
        {"text": "Il miele argentino vale 3,91 USD/kg.", "refs": [9]},          # citation of a block that does not exist
        {"text": "Il miele argentino vale 3,91 USD/kg.", "refs": [1, 9]},       # one bad citation is enough
        {"text": "Il miele argentino vale 3,91 USD/kg."},                       # no citation in a fact section
        {"text": "L'offerta A costa 3,20 USD/kg.", "refs": [2]},               # private block, not allowed here
        "Una frase senza numeri [1].",
    ]
    kept, dropped = A.check_sentences(items, fs, require_refs=True, allow_private=False)
    assert [k["text"] for k in kept] == ["Il miele argentino vale 3,91 USD/kg."] * 2 + ["Una frase senza numeri."]
    assert [d["reason"] for d in dropped] == ["invented_number", "bad_citation", "bad_citation", "no_citation",
                                              "bad_citation"]
    assert dropped[0]["numbers"] == ["4,10"]
    # analysis: citations optional, still no new numbers
    kept, dropped = A.check_sentences(["Il mercato appare sostenuto.", "Prezzi su del 7%."], fs, require_refs=False)
    assert [k["text"] for k in kept] == ["Il mercato appare sostenuto."] and dropped[0]["reason"] == "invented_number"


# ---------------------------------------------------------------------------
# without AI (no provider configured)
# ---------------------------------------------------------------------------


def test_no_ai_answer_through_the_api_and_history(api, market):
    r = api.post("/api/assistant/ask", json={"question": "Cosa sta succedendo ai prezzi del miele argentino?", "lang": "it"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ai_used"] is False and d["ai"]["enabled"] is False
    assert d["intro"].startswith("Ecco i dati disponibili nel database su: Argentina")
    assert d["how_to_enable"]["lines"][0] == "PALADEX_LLM_PROVIDER=anthropic"
    ids = {f["id"] for f in d["facts"]}
    assert d["sections"] and all(ref in ids for s in d["sections"] for it in s["items"] for ref in it["refs"])
    assert all(not s["ai"] for s in d["sections"])
    assert [s["key"] for s in d["sections"]] == [k for k in A.PLAIN_SECTIONS if k in {s["key"] for s in d["sections"]}]
    hist = api.get("/api/assistant/history").json()
    assert hist["items"][0]["question"].startswith("Cosa sta succedendo") and hist["items"][0]["id"] == d["id"]
    full = api.get(f"/api/assistant/history/{d['id']}").json()
    assert full["intro"] == d["intro"] and full["facts"] == d["facts"]
    assert api.get("/api/assistant/history/nope").status_code == 404
    st = api.get("/api/assistant/status").json()
    assert st["llm_enabled"] is False and st["provider"] is None and st["history_count"] == 1
    assert api.delete("/api/assistant/history").json() == {"deleted": 1}
    assert api.get("/api/assistant/history").json()["items"] == []
    assert api.post("/api/assistant/ask", json={"question": "   "}).status_code == 422
    en = api.post("/api/assistant/ask", json={"question": "Compare Argentina and Ukraine", "lang": "en"}).json()
    assert en["intro"].startswith("Here are the data available in the database on: Argentina · Ukraine")
    assert en["sections"][0]["title"] == "Verified facts"


def test_no_data_at_all_is_said_plainly(db):
    ans = ask(db, "Cosa sta succedendo ai prezzi del miele argentino?")
    assert ans["facts"] == [] and ans["insufficient"] and ans["sections"] == []
    assert ans["intro"] == "Non ho trovato nel database dati sufficienti per rispondere."
    assert any("Nessun prezzo recente nel database per Argentina" in n for n in ans["notes"])


def test_briefing_without_ai_does_nothing(api, market):
    res = B.generate_daily(market)
    assert res["enabled"] is False and res["skipped"] == "llm_disabled"
    assert market.scalar(select(func.count()).select_from(Briefing)) == 0
    r = api.post("/api/assistant/briefing/regenerate", json={}).json()
    assert r["enabled"] is False and r["briefing"] is None
    assert api.get("/api/overview").json()["briefing"]["generator"] == "rules"


# ---------------------------------------------------------------------------
# with AI (Anthropic, mocked with respx)
# ---------------------------------------------------------------------------


@pytest.fixture()
def llm_on(db, monkeypatch):
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("PALADEX_ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("PALADEX_ANTHROPIC_MODEL", "claude-test-model")
    config.get_settings.cache_clear()
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    yield
    config.get_settings.cache_clear()


def _context(request: httpx.Request) -> tuple[dict, list[dict]]:
    body = json.loads(request.content)
    user = body["messages"][0]["content"]
    return body, json.loads(user[user.index("\n[") + 1:])


def _reply(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                                     "stop_reason": "end_turn"})


def test_ai_answer_is_post_checked(market, llm_on):
    seen: dict = {}

    def model(request: httpx.Request) -> httpx.Response:
        body, ctx = _context(request)
        seen.update(body=body, ctx=ctx, headers=request.headers)
        eu = next(b for b in ctx if b["type"] == "price" and "Unione Europea" in b["text"])
        num = eu["text"].split(": ")[1].split(" EUR/kg")[0]          # "2,50"
        return _reply({"sections": [
            {"key": "verified", "sentences": [
                {"text": f"Il valore unitario all'import UE del miele argentino è {num} EUR/kg, dato provvisorio.",
                 "refs": [eu["id"]]},
                {"text": "Il prezzo salirà a 2,95 EUR/kg.", "refs": [eu["id"]]}]},          # invented: dropped
            {"key": "historical", "sentences": [{"text": "Una frase che cita un blocco inesistente.", "refs": [999]}]},
            {"key": "analysis", "sentences": [{"text": "Il miele argentino resta competitivo per un importatore."}]},
            {"key": "forecast", "sentences": [{"text": "I prezzi potrebbero restare sostenuti, con molta incertezza."}]},
            {"key": "verified", "sentences": [f"Dato provvisorio: {num} EUR/kg [{eu['id']}]."]},
        ], "insufficient_note": None})

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        ans = ask(market, "Cosa sta succedendo ai prezzi del miele argentino?")
    assert route.call_count == 1
    assert seen["headers"]["x-api-key"] == "sk-test-key" and seen["body"]["model"] == "claude-test-model"
    assert "Usa ESCLUSIVAMENTE i blocchi del CONTESTO" in seen["body"]["system"]
    assert ans["ai_used"] is True and ans["ai"] == {"enabled": True, "provider": "anthropic", "model": "claude-test-model"}
    assert ans["intro"].startswith("Risposta redatta dall'IA solo con i")
    keys = [s["key"] for s in ans["sections"]]
    assert keys == ["verified", "analysis", "forecast"]
    verified = ans["sections"][0]
    assert verified["title"] == "Fatti verificati" and verified["ai"] and not verified["analysis"]
    assert len(verified["items"]) == 2 and all(it["refs"] for it in verified["items"])
    assert ans["sections"][1]["title"] == "Analisi (IA)" and ans["sections"][1]["analysis"]
    assert ans["sections"][2]["title"] == "Previsioni (IA, incerte)"
    assert ans["checks"]["dropped"] == 2 and {d["reason"] for d in ans["checks"]["dropped_items"]} == {
        "invented_number", "bad_citation"}
    assert any("2 frasi della risposta dell'IA sono state rimosse" in w for w in ans["warnings"])
    assert "how_to_enable" not in ans


def test_ai_answer_rejected_when_most_of_it_is_invented(market, llm_on):
    def model(request: httpx.Request) -> httpx.Response:
        _, ctx = _context(request)
        ref = ctx[0]["id"]
        return _reply({"sections": [{"key": "verified", "sentences": [
            {"text": "Il prezzo è 9,99 USD/kg.", "refs": [ref]}, {"text": "Le esportazioni sono 123.456 t.", "refs": [ref]},
            {"text": "Una frase corretta senza numeri.", "refs": [ref]}]}]})

    with respx.mock() as mock:
        mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        ans = ask(market, "Confronta Argentina e Ucraina")
    assert ans["ai_used"] is False and ans["checks"]["rejected"] is True
    assert any("La risposta dell'IA è stata scartata" in w for w in ans["warnings"])
    assert ans["sections"] and all(not s["ai"] for s in ans["sections"])
    assert ans["intro"].startswith("Ecco i dati disponibili nel database")


def test_ai_unavailable_falls_back_to_the_data(market, llm_on):
    with respx.mock() as mock:
        mock.post(llm.ANTHROPIC_URL).mock(return_value=httpx.Response(500, json={"error": {"message": "overloaded"}}))
        ans = ask(market, "Confronta Argentina e Ucraina")
    assert ans["ai_used"] is False and ans["sections"]
    assert any("Il servizio di IA non ha risposto" in w for w in ans["warnings"])


def test_supplier_offers_never_reach_the_model_unless_asked(market, llm_on):
    add_quote(market, "Apicultores del Sur SA", "ARG", 3.20, notes="sconto riservato")
    market.commit()
    bodies: list[str] = []

    def model(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        _, ctx = _context(request)
        return _reply({"sections": [{"key": "verified", "sentences": [{"text": "Dati disponibili.", "refs": [ctx[0]["id"]]}]}]})

    with respx.mock() as mock:
        mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        plain = ask(market, "Cosa sta succedendo ai prezzi del miele argentino?")
        offers = ask(market, "Confronta queste offerte")
    assert "Apicultores" not in bodies[0] and "Offerta A" not in bodies[0] and not plain["sent_private_to_ai"]
    assert "Offerta A" in bodies[1] and "Apicultores" not in bodies[1] and "sconto" not in bodies[1]
    assert offers["sent_private_to_ai"] is True and offers["ai_used"] is True


# ---------------------------------------------------------------------------
# daily AI briefing
# ---------------------------------------------------------------------------


def _briefing_market(db):
    """Facts the overview's rules pick up: a monthly price move, a new report with commentary, news."""
    add_prices(db, "usda_honey_report", "ARG", [3.50, 3.60, 3.65, 3.62, 3.70, 3.75, 3.80, 3.82, 3.85, 3.90, 3.95, 3.92,
                                                3.90, 4.10], color="white", last_back=1,
               url="https://example.org/usda-latest.pdf")
    add_report(db, "National Honey Report – latest", days_ago=3, period=f"{month_start(1):%Y-%m}",
               narrative="Demand for imported light honey was steady. Offers from Argentina firmed.")
    add_news(db, "Argentina: beekeepers expect a smaller harvest", countries=["ARG"], days_ago=1, relevance=75,
             snippet="Producers in Buenos Aires province expect 20% less honey.")
    db.add(RegulationItem(source_id=src(db, "rasff_honey").id, jurisdiction="EU", doc_type="food_safety_notification",
                          reference="2026.9001", title="Residues of veterinary drugs in honey from Ukraine",
                          status="alert", published_at=TODAY - timedelta(days=2), url="https://rasff.example/2026.9001",
                          countries=["UKR"]))
    db.commit()


def test_briefing_generated_by_ai_in_the_overview_format(api, db, llm_on):
    _briefing_market(db)
    calls: list[dict] = []

    def model(request: httpx.Request) -> httpx.Response:
        body, ctx = _context(request)
        calls.append(body)
        it = "Scrivi in italiano il briefing" in body["system"]
        by = {b["section"]: b for b in ctx}
        price = by["prices"]
        num = price["text"].split(": ")[1].split(" USD/kg")[0]
        return _reply({"sections": [
            {"key": "news", "bullets": [{"text": f"{'Notizia' if it else 'News'}: harvest outlook [{by['news']['id']}].",
                                         "refs": [by["news"]["id"]]}]},
            {"key": "reports", "bullets": [{"text": "New USDA report with market commentary.", "refs": [by["reports"]["id"]]}]},
            {"key": "prices", "bullets": [{"text": f"Argentine white wholesale price in the US: {num} USD/kg.",
                                           "refs": [price["id"]]},
                                          {"text": "It will reach 5,00 USD/kg next month.", "refs": [price["id"]]}]},
            {"key": "regulation", "bullets": [{"text": "RASFF alert on honey from Ukraine.", "refs": [by["regulation"]["id"]]}]},
            {"key": "implications", "bullets": [{"text": "Firmer Argentine prices may raise purchase costs.",
                                                 "refs": [price["id"]]}]},
        ]})

    with respx.mock(assert_all_called=True) as mock:
        mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        res = B.generate_daily(db)          # the scheduler's call: session only
    assert len(calls) == 2 and res["generator"] == "anthropic:claude-test-model"
    assert res["results"]["it"]["status"] == "generated" and res["results"]["en"]["status"] == "generated"
    assert res["results"]["it"]["checks"]["dropped"] == 1
    row = db.scalars(select(Briefing).where(Briefing.language == "it")).one()
    assert row.briefing_date == TODAY and row.generator == "anthropic:claude-test-model"
    c = row.content
    assert c["is_ai"] is True and [s["key"] for s in c["sections"]] == ["news", "reports", "prices", "regulation", "implications"]
    assert c["sections"][-1]["title"] == "Implicazioni per Parodi Group (analisi IA)" and c["sections"][-1]["is_analysis"]
    bullets = c["bullets"]
    assert all(b["is_ai"] and b["refs"] for b in bullets)
    price = next(b for b in bullets if b["section"] == "prices")
    assert price["kind"] == "price" and price["url"] == "https://example.org/usda-latest.pdf"
    assert price["source"]["key"] == "usda_honey_report" and price["period_label"] == f"{month_start(1):%Y-%m}"
    impl = bullets[-1]
    assert impl["text"].startswith("Analisi IA — ") and impl["source"] is None and impl["publisher"] == "Analisi IA sui dati citati"
    assert not any("5,00" in b["text"] for b in bullets)
    # the overview shows it instead of the rule-based summary, every point labelled AI
    ov = api.get("/api/overview", params={"lang": "it"}).json()["briefing"]
    assert ov["is_ai"] is True and ov["stored"] is True and ov["generator"] == "anthropic:claude-test-model"
    assert [b["text"] for b in ov["bullets"]] == [b["text"] for b in bullets] and all(b["is_ai"] for b in ov["bullets"])
    assert ov["bullets"][2]["publisher"] == price["publisher"] and ov["rules"] == []
    st = api.get("/api/assistant/briefing", params={"lang": "en"}).json()
    assert st["enabled"] and st["briefing"]["generator"] == "anthropic:claude-test-model"
    assert st["briefing"]["bullets"][-1]["text"].startswith("AI analysis — ")
    assert B.generate_daily(db)["results"]["it"]["status"] == "exists", "the 07:00 run does not overwrite a briefing"


def test_briefing_rejected_by_the_post_check_is_not_stored(db, llm_on):
    _briefing_market(db)

    def model(request: httpx.Request) -> httpx.Response:
        _, ctx = _context(request)
        return _reply({"sections": [{"key": "prices", "bullets": [
            {"text": "Prices rose 12% to 9,99 USD/kg.", "refs": [ctx[0]["id"]]}]}]})

    with respx.mock() as mock:
        mock.post(llm.ANTHROPIC_URL).mock(side_effect=model)
        res = B.generate_daily(db, ["it"], force=True)
    assert res["results"]["it"]["status"] == "rejected"
    assert db.scalar(select(func.count()).select_from(Briefing)) == 0


def test_briefing_facts_follow_the_overview_rules(db):
    _briefing_market(db)
    r = B.build_facts(db, "it")
    sections = {f.meta["section"] for f in r.facts}
    assert {"news", "reports", "prices", "regulation"} <= sections
    price = next(f for f in r.facts if f.meta["section"] == "prices")
    assert price.kind == "price" and "mercato: Stati Uniti" in price.text and "4,10 USD/kg" in price.text
    report_text = next(f for f in r.facts if f.kind == "report_text")
    assert "Offers from Argentina firmed" in report_text.text
    assert not [f for f in r.facts if f.private], "the briefing never uses supplier offers"
