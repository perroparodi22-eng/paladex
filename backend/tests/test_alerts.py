"""Alert center (Milestone 7b): rule evaluation, dedup, 'only new data', messages, API.

Data is inserted directly through the same append-only writers the collectors use
(`services.ingest.record`, `services.tariffs.record_measure`); the numbers are illustrative.
Dates of documents are relative to today, so the 14-day report look-back and the preview window
are tested against the real clock.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from paladex.enums import AlertType
from paladex.models import (
    AlertEvent,
    AlertRule,
    NewsArticle,
    PriceObservation,
    RegulationItem,
    Report,
    Source,
    TradeFlowObservation,
    utcnow,
)
from paladex.services import alerts as svc
from paladex.services import ingest
from paladex.services import tariffs as tsvc

TODAY = date.today()


def src(db, key: str) -> Source:
    return db.scalars(select(Source).where(Source.key == key)).one()


def month(label: str) -> tuple[date, date]:
    import calendar

    y, m = int(label[:4]), int(label[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def add_price(db, label: str, value: float, *, origin="ARG", variety="polyflora", color="white", unit="lb",
              currency="USD", price_type="wholesale_bulk", source="usda_honey_report", freq="M", volume=None,
              market="USA", start: date | None = None, end: date | None = None) -> PriceObservation:
    s, e = (start, end) if start else month(label)
    _, row = ingest.record(
        db, PriceObservation, source_id=src(db, source).id,
        series_key=f"{price_type}|t|{origin}|{variety}|{color}|{market}|{label}",
        price_type=price_type, variety=variety, origin_iso3=origin, market_iso3=market, color_grade=color,
        price_value=value, currency=currency, unit=unit, price_per_kg=ingest.per_kg(value, unit), volume_kg=volume,
        period_start=s, period_end=e, period_label=label, frequency=freq, data_status="published",
        reliability="official", published_at=e + timedelta(days=30), source_url="https://example.org/report.pdf",
    )
    db.flush()
    return row


def add_trade(db, label: str, kg: float, *, reporter="EU27", partner="EXTRA_EU", flow="import",
              source="eurostat_comext") -> TradeFlowObservation:
    s, e = month(label)
    _, row = ingest.record(
        db, TradeFlowObservation, source_id=src(db, source).id, series_key=f"t|{reporter}|{partner}|{flow}|{label}",
        reporter_iso3=reporter, partner_iso3=partner, flow=flow, net_weight_kg=kg, value=kg * 2.5, currency="EUR",
        value_basis="CIF", period_start=s, period_end=e, period_label=label, frequency="M",
        data_status="published", reliability="official", published_at=e + timedelta(days=45),
        source_url="https://ec.europa.eu/eurostat/comext",
    )
    db.flush()
    return row


def add_report(db, key: str, published: date, *, source="usda_honey_report", collected: datetime | None = None) -> Report:
    r = Report(source_id=src(db, source).id, report_key=key, title=f"National Honey Report – {published:%B %d, %Y}",
               period_label=f"{published.year}-{published.month:02d}", published_at=published,
               url=f"https://example.org/{key}.pdf", collected_at=collected or utcnow())
    db.add(r)
    db.flush()
    return r


def add_news(db, title: str, *, countries=("CHN",), relevance=70, snippet=None, duplicate_of=None,
             published: datetime | None = None, source="news_bee_culture") -> NewsArticle:
    n = db.scalar(select(func.count()).select_from(NewsArticle)) or 0
    a = NewsArticle(source_id=src(db, source).id, url=f"https://example.org/n{n}", canonical_url=f"https://example.org/n{n}",
                    title=title, title_norm=title.lower(), language="en", snippet=snippet,
                    published_at=published or utcnow() - timedelta(hours=3), collected_at=utcnow(),
                    countries=list(countries), topics=["trade"], relevance_score=relevance,
                    duplicate_of_id=duplicate_of.id if duplicate_of else None)
    db.add(a)
    db.flush()
    return a


def add_regulation(db, ref: str, *, jurisdiction="EU", doc_type="regulation", source="eurlex_honey",
                   published: date | None = None, countries=None) -> RegulationItem:
    r = RegulationItem(source_id=src(db, source).id, jurisdiction=jurisdiction, doc_type=doc_type, reference=ref,
                       title=f"Commission Implementing Regulation {ref} on honey", published_at=published or TODAY,
                       url=f"https://eur-lex.europa.eu/{ref}", countries=countries)
    db.add(r)
    db.flush()
    return r


def quota(db, *, status="open", balance=1_000_000.0, duty="0.00 %", origin="UKR"):
    return tsvc.record_measure(
        db, source_id=src(db, "eu_tariff_xi").id, series_key=f"EU|0409000000|{origin}|143|096701|UA",
        as_of=TODAY, jurisdiction="EU", origin_iso3=origin, hs_code="0409000000", measure_type="trq_in",
        measure_code="143", duty_text=duty, ad_valorem_pct=0.0, quota_order_number="096701",
        quota_volume_kg=6_000_000.0, quota_balance_kg=balance, quota_status=status, legal_reference="R2024/1392",
        consult_url="https://ec.europa.eu/taxation_customs/dds2/taric/measures.jsp", data_status="published",
        reliability="official",
    )


def make_rule(db, alert_type: str, params: dict, name: str = "Regola di prova") -> AlertRule:
    """A rule created now, with its baseline taken (as the API does on creation)."""
    rule = AlertRule(name=name, alert_type=alert_type, params=svc.start_watch(db, params, utcnow()), enabled=True,
                     created_at=utcnow())
    db.add(rule)
    db.flush()
    svc.evaluate_rule(db, rule)
    return rule


def events(db, rule: AlertRule | None = None) -> list[AlertEvent]:
    q = select(AlertEvent).order_by(AlertEvent.id)
    if rule is not None:
        q = q.where(AlertEvent.rule_id == rule.id)
    return list(db.scalars(q))


PRICE_RULE = {"price_type": "wholesale_bulk", "origin": "ARG", "variety": "polyflora", "market": None,
              "color_grade": None, "threshold_pct": 5, "direction": "up"}


# ---------------------------------------------------------------------------
# price_change
# ---------------------------------------------------------------------------


def test_price_change_fires_once_on_new_monthly_data_only(db):
    add_price(db, "2026-06", 1.40)
    add_price(db, "2026-07", 1.50)          # +7.1 %, but already known when the rule is created
    rule = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE)
    assert events(db, rule) == []

    add_price(db, "2026-08", 1.60)          # +6.7 % on July, collected after the rule
    svc.evaluate_all(db)
    evs = events(db, rule)
    assert len(evs) == 1
    e = evs[0]
    assert e.dedup_key.startswith("price:") and e.dedup_key.endswith(":2026-08")
    assert "+6,7%" in e.title_it and "agosto 2026" in e.title_it
    assert "+6.7%" in e.title_en and "August 2026" in e.title_en
    # value per kg in the source currency, the published per-lb figures, the previous month, the source
    assert "3,53 USD/kg" in e.body_it and "luglio 2026" in e.body_it and "1,60 e 1,50 USD/lb" in e.body_it
    assert "USDA" in e.body_it and "Soglia della regola: +5,0%" in e.body_it
    assert e.link.startswith("/prezzi?") and "origini=ARG" in e.link
    assert e.ref_type == "price" and e.ref_id

    # evaluated again: never repeated
    svc.evaluate_all(db)
    assert len(events(db, rule)) == 1


def test_price_change_direction_and_threshold(db):
    add_price(db, "2026-07", 1.50)
    up = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE, "su")
    down = make_rule(db, AlertType.PRICE_CHANGE, {**PRICE_RULE, "direction": "down"}, "giù")
    anyway = make_rule(db, AlertType.PRICE_CHANGE, {**PRICE_RULE, "direction": "any", "threshold_pct": 10}, "qualsiasi")
    add_price(db, "2026-08", 1.38)          # -8 %
    svc.evaluate_all(db)
    assert events(db, up) == []
    assert len(events(db, down)) == 1 and "−8,0%" in events(db, down)[0].title_it
    assert events(db, anyway) == []         # below 10 %


def test_price_change_never_uses_weekly_series_nor_small_consignments(db):
    weekly = {**PRICE_RULE, "price_type": "import_unit_value", "variety": "unspecified", "market": "EU27"}
    rule = make_rule(db, AlertType.PRICE_CHANGE, weekly)
    # weekly unit values: a huge week-on-week jump never fires
    add_price(db, "2026-W30", 3.0, price_type="import_unit_value", variety="unspecified", color=None, unit="kg",
              currency="EUR", source="ec_taxud_weekly", freq="W", market="EU27", volume=50_000,
              start=date(2026, 7, 20), end=date(2026, 7, 26))
    add_price(db, "2026-W31", 6.0, price_type="import_unit_value", variety="unspecified", color=None, unit="kg",
              currency="EUR", source="ec_taxud_weekly", freq="W", market="EU27", volume=50_000,
              start=date(2026, 7, 27), end=date(2026, 8, 2))
    # monthly unit values: July a bulk shipment, August only 4 t (below the 10 t bulk rule)
    add_price(db, "2026-07", 3.0, price_type="import_unit_value", variety="unspecified", color=None, unit="kg",
              currency="EUR", source="eurostat_comext", market="EU27", volume=400_000)
    add_price(db, "2026-08", 9.0, price_type="import_unit_value", variety="unspecified", color=None, unit="kg",
              currency="EUR", source="eurostat_comext", market="EU27", volume=4_000)
    svc.evaluate_all(db)
    assert events(db, rule) == []
    pv = svc.preview(db, AlertType.PRICE_CHANGE, weekly)
    assert pv["total"] == 0
    # only the monthly series is looked at, and its newest bulk month has no previous month
    assert [c["period_label"] for c in pv["checked"]] == ["2026-07"]
    assert pv["checked"][0]["reason"] == "no_previous"


def test_price_change_needs_the_exact_previous_month(db):
    add_price(db, "2026-05", 1.20)
    rule = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE)
    add_price(db, "2026-07", 1.60)          # June missing: no comparison is invented
    svc.evaluate_all(db)
    assert events(db, rule) == []


# ---------------------------------------------------------------------------
# new_report
# ---------------------------------------------------------------------------


def test_new_report_looks_back_14_days_on_creation_then_only_new(db):
    old_collected = utcnow() - timedelta(days=1)
    add_report(db, "recent", TODAY - timedelta(days=10), collected=old_collected)
    add_report(db, "old", TODAY - timedelta(days=40), collected=old_collected)
    rule = make_rule(db, AlertType.NEW_REPORT, {"source_keys": ["usda_honey_report"]})
    evs = events(db, rule)
    assert [e.dedup_key for e in evs] == [f"report:{db.scalars(select(Report).where(Report.report_key == 'recent')).one().id}"]
    assert evs[0].title_it == f"Nuovo report: National Honey Report – {(TODAY - timedelta(days=10)):%B %d, %Y} · " + \
        svc.period_text(f"{(TODAY - timedelta(days=10)):%Y-%m}", "it")
    assert "Pubblicato il" in evs[0].body_it and "USDA Agricultural Marketing Service" in evs[0].body_en
    assert "prezzi miele" not in evs[0].body_en and evs[0].link.endswith("recent.pdf")

    add_report(db, "new", TODAY)                              # a new release
    add_report(db, "backfill", TODAY - timedelta(days=200))   # an archive issue found today: history
    svc.evaluate_all(db)
    keys = {e.dedup_key for e in events(db, rule)}
    assert len(keys) == 2
    new_id = db.scalars(select(Report).where(Report.report_key == "new")).one().id
    assert f"report:{new_id}" in keys


# ---------------------------------------------------------------------------
# news_keyword
# ---------------------------------------------------------------------------


def test_news_keyword_matches_words_countries_relevance_and_skips_duplicates(db):
    params = {"keywords": ["export", "出口"], "countries": ["CHN"], "min_relevance": 60}
    add_news(db, "China honey exports fall in September")      # before the rule: not news for it
    rule = make_rule(db, AlertType.NEWS_KEYWORD, params)
    assert events(db, rule) == []

    hit = add_news(db, "Chinese honey exporters face new US duties")             # 'export' starts 'exporters'
    add_news(db, "China honey exporters: same story", duplicate_of=hit)          # duplicate
    add_news(db, "China honey harvest outlook", relevance=90)                     # no keyword
    add_news(db, "China honey exports", relevance=40)                             # not relevant enough
    add_news(db, "Brazil honey exports", countries=("BRA",))                      # other country
    add_news(db, "Reexport schemes", snippet="no word starts with the keyword")   # 'reexport' is not 'export…'
    cn = add_news(db, "中国蜂蜜出口增长")                                          # Chinese: matched anywhere
    add_news(db, "China honey exports surge", published=utcnow() - timedelta(days=60))  # old article found today
    svc.evaluate_all(db)
    evs = events(db, rule)
    assert {e.ref_id for e in evs} == {hit.id, cn.id}
    e = next(x for x in evs if x.ref_id == hit.id)
    assert e.title_it == "Notizia: Chinese honey exporters face new US duties"
    assert "Rilevanza 70/100" in e.body_it and "Parole trovate: export" in e.body_it and "Cina" in e.body_it


# ---------------------------------------------------------------------------
# regulation (+ duty measures)
# ---------------------------------------------------------------------------


def test_regulation_documents_and_meaningful_duty_changes(db):
    quota(db, status="open", balance=2_000_000)              # the tariff source was already being read
    add_regulation(db, "32026R0001")                          # known before the rule
    rule = make_rule(db, AlertType.REGULATION, {"jurisdictions": ["EU"], "doc_types": [], "countries": [],
                                                "include_tariffs": True})
    assert events(db, rule) == []

    reg = add_regulation(db, "32026R2228")
    add_regulation(db, "2026-12345", jurisdiction="US", doc_type="antidumping", source="us_federal_register")
    add_regulation(db, "31990R0001", published=TODAY - timedelta(days=400))      # archive backfill
    quota(db, status="open", balance=1_500_000)               # balance drawn down: history, not an alert
    _, exhausted = quota(db, status="exhausted", balance=0)   # quota exhausted: an alert
    svc.evaluate_all(db)
    evs = events(db, rule)
    by_key = {e.dedup_key: e for e in evs}
    assert set(by_key) == {f"reg:{reg.id}", f"tariff:{exhausted.id}"}
    t = by_key[f"tariff:{exhausted.id}"]
    assert t.title_it == "Dazi UE sul miele (Ucraina): contingente esaurito"
    assert "«aperto» a «esaurito»" in t.body_it and "R2024/1392" in t.body_it
    assert t.severity == "warning"
    d = by_key[f"reg:{reg.id}"]
    assert d.title_it.startswith("UE · Regolamento: ") and "32026R2228" in d.body_it


def test_regulation_country_filter(db):
    rule = make_rule(db, AlertType.REGULATION, {"jurisdictions": [], "doc_types": ["food_safety_notification"],
                                                "countries": ["CHN"], "include_tariffs": False})
    add_regulation(db, "2026.1", doc_type="food_safety_notification", source="rasff_honey", countries=["CHN"])
    add_regulation(db, "2026.2", doc_type="food_safety_notification", source="rasff_honey", countries=["NPL"])
    add_regulation(db, "32026R9", countries=["CHN"])          # another document type
    svc.evaluate_all(db)
    assert [e.title_en.split(": ", 1)[0] for e in events(db, rule)] == ["EU · RASFF food alert"]


# ---------------------------------------------------------------------------
# trade_change
# ---------------------------------------------------------------------------


def test_trade_change_monthly_year_on_year(db):
    add_trade(db, "2025-08", 10_000_000)
    params = {"reporter": "EU27", "partner": "WLD", "flow": "import", "threshold_pct": 20, "freq": "M",
              "direction": "any"}
    rule = make_rule(db, AlertType.TRADE_CHANGE, params)
    add_trade(db, "2026-07", 9_000_000)                      # no July 2025: not compared
    add_trade(db, "2026-08", 12_500_000)                     # +25 % on August 2025
    svc.evaluate_all(db)
    evs = events(db, rule)
    assert len(evs) == 1
    e = evs[0]
    assert e.title_it == "Importazioni di miele (UE a 27 dal resto del mondo): +25,0% ad agosto 2026 su un anno prima"
    assert e.title_en == "Honey imports (EU-27 from outside the EU): +25.0% in August 2026 year on year"
    assert "12.500 t" in e.body_it and "10.000 t" in e.body_it and "agosto 2025" in e.body_it
    assert e.link == "/commercio?reporter=EU27&partner=WLD&flow=import"
    assert e.ref_type == "trade" and e.ref_id


def test_trade_change_below_threshold_is_only_checked(db):
    add_trade(db, "2025-08", 10_000_000)
    add_trade(db, "2026-08", 11_000_000)
    pv = svc.preview(db, AlertType.TRADE_CHANGE, {"reporter": "EU27", "partner": "WLD", "flow": "import",
                                                  "threshold_pct": 20, "freq": "M", "direction": "any"})
    assert pv["total"] == 0
    assert pv["checked"][0]["pct"] == 10.0 and pv["checked"][0]["reason"] == "below_threshold"


# ---------------------------------------------------------------------------
# baseline, seeding, hook
# ---------------------------------------------------------------------------


def test_seeded_rules_take_a_baseline_and_never_flood(db):
    # a fresh install: data already collected (the first download), rules seeded afterwards
    add_price(db, "2026-07", 1.40)
    add_price(db, "2026-08", 1.80)
    add_trade(db, "2025-08", 10_000_000)
    add_trade(db, "2026-08", 20_000_000)
    add_regulation(db, "32026R7")
    res = svc.evaluate_all(db)
    assert res["rules"] == len(svc.DEFAULT_RULES)
    assert events(db) == []
    names = [r.name for r in db.scalars(select(AlertRule).order_by(AlertRule.id))]
    assert names == [d["name"] for d in svc.DEFAULT_RULES]


def test_rule_seeded_before_the_first_collection_does_not_report_it(db):
    svc.ensure_default_rules(db)              # e.g. the owner opened the page before any data arrived
    add_price(db, "2026-07", 1.40)
    add_price(db, "2026-08", 1.80)
    add_regulation(db, "32026R8")
    svc.evaluate_all(db)                      # first evaluation = baseline
    assert events(db) == []


# ---------------------------------------------------------------------------
# The watch rule: bulk imports of history (starter data) never flood the feed
# ---------------------------------------------------------------------------


def imported(db, row, collected: datetime):
    """What the starter import does: the row enters this database now, with its ORIGINAL collection time."""
    row.collected_at = collected
    if hasattr(row, "last_seen_at"):
        row.last_seen_at = collected
    db.flush()
    return row


def starter_merged(db, *, imported_at: datetime, collected_until: datetime) -> None:
    """The record services.starter writes after a merge (whole seconds, as it stores them)."""
    from paladex.api.common import set_setting

    set_setting(db, svc.STARTER_SETTING, {"imported_at": imported_at.isoformat(timespec="seconds"),
                                          "data_collected_until": collected_until.isoformat(timespec="seconds")})
    db.flush()


def watching_since(db, rule: AlertRule, when: datetime) -> None:
    rule.params = {**rule.params, "_meta": {**rule.params["_meta"], "since": when.isoformat()}}
    db.flush()


TRADE_RULE = {"reporter": "EU27", "partner": "WLD", "flow": "import", "threshold_pct": 20, "freq": "M", "direction": "any"}


def test_starter_data_merged_into_a_database_with_rules_never_floods(db):
    # The rules have been watching for 10 minutes when a newer snapshot, built on another computer,
    # is merged. Its rows enter the database now (ids above every mark) and keep their original
    # collection time, which is LATER than the rules' watch start: only the import record tells
    # them apart from rows collected here.
    now = utcnow()
    add_price(db, "2026-07", 1.40)
    add_trade(db, "2025-08", 10_000_000)
    quota(db, status="open", balance=2_000_000)
    svc.evaluate_all(db)                      # the example rules exist too
    for r in db.scalars(select(AlertRule)):
        watching_since(db, r, now - timedelta(minutes=10))
    rules = [make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE, "prezzo"),
             make_rule(db, AlertType.NEWS_KEYWORD, {"keywords": ["export"], "countries": ["CHN"], "min_relevance": 0}, "notizie"),
             make_rule(db, AlertType.REGULATION, {"jurisdictions": ["EU"], "doc_types": [], "countries": [],
                                                  "include_tariffs": True}, "normativa"),
             make_rule(db, AlertType.NEW_REPORT, {"source_keys": ["usda_honey_report"]}, "report"),
             make_rule(db, AlertType.TRADE_CHANGE, TRADE_RULE, "commercio")]
    for r in rules:
        watching_since(db, r, now - timedelta(minutes=10))

    collected = now - timedelta(minutes=5)          # on the computer that built the snapshot
    imported(db, add_price(db, "2026-08", 1.80), collected)                       # +28.6 %
    imported(db, add_news(db, "China honey exports surge"), collected)
    imported(db, add_regulation(db, "32026R5555"), collected)
    add_report(db, "snap", TODAY - timedelta(days=1), collected=collected)
    imported(db, add_trade(db, "2026-08", 15_000_000), collected)                  # +50 %
    _, exhausted = quota(db, status="exhausted", balance=0)
    imported(db, exhausted, collected)
    starter_merged(db, imported_at=now - timedelta(minutes=1), collected_until=collected)

    svc.evaluate_all(db)
    assert events(db) == []

    # The start-up collection on this computer then brings genuinely new data: it fires as usual.
    hit = add_news(db, "China honey exporters face new duties")
    add_price(db, "2026-09", 2.00)                                                 # +11.1 % on August
    svc.evaluate_all(db)
    by_rule = {r.name: [e.dedup_key for e in events(db, r)] for r in rules}
    assert by_rule["notizie"] == [f"news:{hit.id}"]
    assert len(by_rule["prezzo"]) == 1 and by_rule["prezzo"][0].endswith(":2026-09")
    assert by_rule["normativa"] == by_rule["report"] == by_rule["commercio"] == []


def test_rules_created_after_an_import_ignore_imported_rows_whatever_their_dates(db):
    # A fresh installation: the snapshot is merged first, then the example rules are seeded. Even
    # collection times later than this computer's clock (another computer's clock) never fire:
    # the imported rows are below the rules' marks.
    future = utcnow() + timedelta(hours=2)
    imported(db, add_price(db, "2026-07", 1.40), future)
    imported(db, add_price(db, "2026-08", 1.80), future)
    imported(db, add_news(db, "China honey exports surge", relevance=90), future)
    imported(db, add_regulation(db, "32026R6666"), future)
    imported(db, add_trade(db, "2025-08", 10_000_000), future)
    imported(db, add_trade(db, "2026-08", 15_000_000), future)
    svc.evaluate_all(db)                       # seeds the five examples and takes their baseline
    assert events(db) == []

    hit = add_news(db, "Chinese honey export prices fall", relevance=90)            # collected here, now
    svc.evaluate_all(db)
    assert [e.ref_id for e in events(db)] == [hit.id]


def test_undated_report_is_never_assumed_recent(db):
    def undated(key: str) -> Report:
        r = Report(source_id=src(db, "onm_informamiele").id, report_key=key, title=f"Report annuale ONM - {key}",
                   period_label="2025", published_at=None, url=f"https://example.org/{key}.pdf", collected_at=utcnow())
        db.add(r)
        db.flush()
        return r

    undated("stagione 2024")                          # held when the rule starts: no date, no look-back
    rule = make_rule(db, AlertType.NEW_REPORT, {"source_keys": ["onm_informamiele"]})
    assert events(db, rule) == []
    assert svc.preview(db, AlertType.NEW_REPORT, {"source_keys": ["onm_informamiele"]})["total"] == 0
    new = undated("stagione 2025")                    # appears on the source after the rule: new
    svc.evaluate_all(db)
    evs = events(db, rule)
    assert [e.ref_id for e in evs] == [new.id]
    assert "data di pubblicazione non indicata" in evs[0].body_it and "publication date not given" in evs[0].body_en


def test_report_look_back_only_counts_releases_held_when_the_rule_starts(db):
    held = add_report(db, "held", TODAY - timedelta(days=5), collected=utcnow() - timedelta(days=4))
    rule = make_rule(db, AlertType.NEW_REPORT, {"source_keys": ["usda_honey_report"]})
    assert [e.ref_id for e in events(db, rule)] == [held.id]          # the 14-day look-back

    # merged later from a snapshot: a release from before the rule existed is history, not news
    add_report(db, "late", TODAY - timedelta(days=3), collected=utcnow() - timedelta(days=2))
    new = add_report(db, "new", TODAY)                                 # a new release collected here
    svc.evaluate_all(db)
    assert [e.ref_id for e in events(db, rule)] == [held.id, new.id]


def test_other_bulk_imports_record_their_cut(db):
    rule = make_rule(db, AlertType.NEWS_KEYWORD, {"keywords": ["export"], "countries": [], "min_relevance": 0})
    watching_since(db, rule, utcnow() - timedelta(minutes=10))
    imported(db, add_news(db, "Honey exports from Vietnam"), utcnow() - timedelta(minutes=3))
    svc.note_bulk_import(db, collected_until=utcnow() - timedelta(minutes=3))
    svc.evaluate_all(db)
    assert events(db, rule) == []
    assert svc.bulk_import_cut(db) is not None


def test_concurrent_first_requests_seed_the_examples_once(db):
    """The bell, the rule list and the feed often arrive together on a fresh install."""
    import threading

    from paladex.db import session_factory

    db.commit()
    first = session_factory()()
    assert svc.ensure_default_rules(first) == len(svc.DEFAULT_RULES)     # holds SQLite's write lock
    result: dict = {}

    def other_request():
        s = session_factory()()
        try:
            result["n"] = svc.ensure_default_rules(s)
            s.commit()
        except Exception as exc:  # noqa: BLE001 - any failure is reported by the assertion below
            result["error"] = exc
        finally:
            s.close()

    th = threading.Thread(target=other_request)
    th.start()
    th.join(0.5)                       # it waits for the first transaction
    first.commit()
    first.close()
    th.join(20)
    assert result == {"n": 0}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AlertRule)) == len(svc.DEFAULT_RULES)


def test_post_collection_hook_evaluates_rules(db):
    from paladex.collectors import runner

    add_price(db, "2026-07", 1.40)
    rule = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE)
    add_price(db, "2026-08", 1.60)
    db.commit()
    runner.post_collection_hooks()
    db.expire_all()
    assert len(events(db, rule)) == 1


def test_describe_rules_in_plain_language(db):
    it = svc.describe(db, AlertType.PRICE_CHANGE, PRICE_RULE, "it")
    assert it.startswith("Avvisa quando il prezzo all'ingrosso (sfuso) del miele millefiori di origine Argentina")
    assert "sale di almeno il 5%" in it
    en = svc.describe(db, AlertType.PRICE_CHANGE, PRICE_RULE, "en")
    assert "wholesale (bulk) price of multifloral (polyflora) honey from Argentina" in en
    tr = svc.describe(db, AlertType.TRADE_CHANGE, {"reporter": "ITA", "partner": "ARG", "flow": "import",
                                                   "threshold_pct": 20, "freq": "A", "direction": "up"}, "it")
    assert "importazioni di miele (Italia da Argentina) aumenta di almeno il 20%" in tr
    assert "solo anni completi" in tr


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_seeds_examples_once_and_respects_deletion(api):
    rules = api.get("/api/alerts/rules").json()["rules"]
    assert len(rules) == 5 and all(r["is_example"] for r in rules)
    assert rules[0]["description_it"].startswith("Avvisa quando")
    first = rules[0]["id"]
    assert api.delete(f"/api/alerts/rules/{first}").status_code == 200
    again = api.get("/api/alerts/rules").json()["rules"]
    assert len(again) == 4 and first not in {r["id"] for r in again}


def test_api_rule_crud_and_validation(api):
    bad = api.post("/api/alerts/rules", json={"name": "x", "alert_type": "price_change",
                                              "params": {**PRICE_RULE, "price_type": "spot"}})
    assert bad.status_code == 422 and "Tipo di prezzo" in bad.json()["detail"]
    bad = api.post("/api/alerts/rules", json={"name": "x", "alert_type": "trade_change",
                                              "params": {"reporter": "XXX", "flow": "import", "threshold_pct": 10}})
    assert bad.status_code == 422
    bad = api.post("/api/alerts/rules", json={"name": "x", "alert_type": "news_keyword", "params": {}})
    assert bad.status_code == 422
    bad = api.post("/api/alerts/rules", json={"name": "x", "alert_type": "nonsense", "params": {}})
    assert bad.status_code == 422

    r = api.post("/api/alerts/rules", json={"name": "Ucraina", "alert_type": "news_keyword",
                                            "params": {"keywords": "quota, contingente", "countries": ["ukr"],
                                                       "min_relevance": 35}})
    assert r.status_code == 201, r.text
    rule = r.json()["rule"]
    assert rule["params"] == {"keywords": ["quota", "contingente"], "countries": ["UKR"], "min_relevance": 35}
    assert "_meta" not in rule["params"] and rule["last_checked_at"]

    up = api.put(f"/api/alerts/rules/{rule['id']}", json={"enabled": False, "name": "Ucraina (quote)"}).json()["rule"]
    assert up["enabled"] is False and up["name"] == "Ucraina (quote)"
    since = up["watching_since"]
    up = api.put(f"/api/alerts/rules/{rule['id']}", json={"enabled": True}).json()["rule"]
    assert up["watching_since"] > since          # switched back on: watches from now
    assert api.put("/api/alerts/rules/99999", json={"enabled": True}).status_code == 404


def test_api_events_feed_read_state_and_count(api, db):
    rule = make_rule(db, AlertType.PRICE_CHANGE, PRICE_RULE)
    add_price(db, "2026-06", 1.40, color="white")
    add_price(db, "2026-07", 1.60, color="white")
    add_price(db, "2026-06", 1.30, color="light amber")
    add_price(db, "2026-07", 1.50, color="light amber")
    svc.evaluate_all(db)
    db.commit()

    count = api.get("/api/alerts/unread-count").json()
    assert count["unread"] == 2 and count["unread_warning"] == 2      # +14 % / +15 %: over twice the threshold
    feed = api.get("/api/alerts/events").json()
    assert feed["total"] == 2 and feed["unread"] == 2
    item = feed["items"][0]
    assert item["rule_name"] == rule.name and item["alert_type"] == "price_change"
    assert item["link_internal"] is True and item["source"]["key"] == "usda_honey_report"
    assert item["source_url"] == "https://example.org/report.pdf" and item["period_label"] == "2026-07"

    assert api.put(f"/api/alerts/events/{item['id']}", json={"read": True}).json()["read"] is True
    feed = api.get("/api/alerts/events").json()
    assert [i["read"] for i in feed["items"]] == [False, True]          # unread first
    assert api.get("/api/alerts/events", params={"status": "unread"}).json()["total"] == 1
    assert api.post("/api/alerts/events/read-all", json={}).json()["marked"] == 1
    assert api.get("/api/alerts/unread-count").json()["unread"] == 0

    deleted = api.delete(f"/api/alerts/rules/{rule.id}").json()
    assert deleted["events_deleted"] == 2
    assert api.get("/api/alerts/events").json()["total"] == 0


def test_api_preview_and_test_rule(api, db):
    add_price(db, "2026-07", 1.40)
    add_price(db, "2026-08", 1.60)
    db.commit()
    pv = api.post("/api/alerts/preview", json={"alert_type": "price_change", "params": PRICE_RULE}).json()
    assert pv["total"] == 1 and pv["items"][0]["already_sent"] is False
    assert pv["items"][0]["title_it"].startswith("Argentina → Stati Uniti · Millefiori · bianco: +14,3%")
    assert pv["items"][0]["title_en"].startswith("Argentina → United States · Multifloral (polyflora) · white: +14.3%")
    assert pv["description_it"].startswith("Avvisa quando")

    rules = api.get("/api/alerts/rules").json()["rules"]
    example = next(r for r in rules if r["alert_type"] == "price_change")
    tested = api.post(f"/api/alerts/rules/{example['id']}/test").json()
    assert tested["total"] == 1                # what the data shows now, even though it was not news for the rule
    assert api.get("/api/alerts/events").json()["total"] == 0


def test_api_options_offer_only_what_has_data(api, db):
    add_price(db, "2026-07", 1.40)
    add_price(db, "2026-W30", 3.0, price_type="import_unit_value", variety="unspecified", color=None, unit="kg",
              currency="EUR", source="ec_taxud_weekly", freq="W", market="EU27", start=date(2026, 7, 20),
              end=date(2026, 7, 26))
    add_trade(db, "2026-08", 1_000_000)
    add_report(db, "r1", TODAY)
    db.commit()
    o = api.get("/api/alerts/options").json()
    assert [(p["price_type"], p["origin"], p["variety"]) for p in o["price"]] == [("wholesale_bulk", "ARG", "polyflora")]
    assert [s["key"] for s in o["report_sources"]] == ["usda_honey_report"]
    eu = next(r for r in o["trade"] if r["iso3"] == "EU27")
    assert eu["flows"]["import"]["partners"] == ["WLD"] and eu["flows"]["import"]["freqs"] == ["M"]
    assert len(o["examples"]) == 5


def test_api_evaluate_now(api, db):
    rule = make_rule(db, AlertType.NEW_REPORT, {"source_keys": ["usda_honey_report"]})
    add_report(db, "fresh", TODAY)
    db.commit()
    res = api.post("/api/alerts/evaluate").json()
    # This first call also seeds the example rules. 'Nuovo National Honey Report USDA' looks back
    # 14 days when it starts watching, so it reports the same release too: one event per rule.
    assert res["new_events"] == 2 and res["failed"] == []
    assert api.get("/api/alerts/events", params={"rule_id": rule.id}).json()["total"] == 1
    example = next(r for r in api.get("/api/alerts/rules").json()["rules"]
                   if r["is_example"] and r["alert_type"] == "new_report")
    assert api.get("/api/alerts/events", params={"rule_id": example["id"]}).json()["total"] == 1
    assert api.post("/api/alerts/evaluate").json()["new_events"] == 0      # never repeated
