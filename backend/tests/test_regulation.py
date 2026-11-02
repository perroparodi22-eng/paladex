"""Tests for the regulation collectors (paladex/collectors/regulation.py).

All fixtures in tests/fixtures/regulation/ are RECONSTRUCTED from documentation (see the README
there); the documents are illustrative, not real records.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from paladex.collectors import regulation as reg
from paladex.collectors.registry import get_collector
from paladex.models import AppSetting, RegulationItem, Source

FIX = Path(__file__).parent / "fixtures" / "regulation"
TODAY = date(2026, 11, 2)
BACKFILL_SINCE = TODAY - timedelta(days=reg.FR_BACKFILL_DAYS)

FR_DOCS = r"^https://www\.federalregister\.gov/api/v1/documents\.json\?"
CELLAR = r"^https://publications\.europa\.eu/webapi/rdf/sparql\?"
CELLAR_RELATED = CELLAR + r".*resource_legal_amends"
CELLAR_TITLE = CELLAR + r".*CONTAINS"


def fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


def fx_json(name: str):
    return json.loads(fx(name))


def _routes(base: dict, override: dict | None) -> dict:
    """Overrides first: the first matching route wins."""
    routes = dict(override or {})
    for k, v in base.items():
        routes.setdefault(k, v)
    return routes


def fr_routes(override: dict | None = None) -> dict:
    return _routes({
        reg.FR_AGENCIES_URL: fx("fr_agencies.json"),
        FR_DOCS + r".*[?&]page=2(&|$)": fx("fr_raw_honey_p2.json"),       # before the page-1 route
        FR_DOCS + r".*%22raw\+honey%22": fx("fr_raw_honey_p1.json"),
        FR_DOCS + r".*%22honey\+from\+the\+people%27s": fx("fr_china_honey.json"),
        FR_DOCS + r".*international-trade-commission": fx("fr_itc_honey.json"),
        FR_DOCS + r".*food-and-drug-administration": fx("fr_fda_honey.json"),
        FR_DOCS + r".*conditions%5Bterm%5D=tariff\+honey": fx("fr_pres_tariff_honey.json"),
        FR_DOCS + r".*conditions%5Bterm%5D=tariff&": fx("fr_pres_tariff_origins.json"),
    }, override)


def eu_routes(override: dict | None = None) -> dict:
    return _routes({
        CELLAR_RELATED: fx("cellar_related.json"),
        CELLAR_TITLE: fx("cellar_title.json"),
    }, override)


@pytest.fixture()
def pin_today(monkeypatch):
    def _pin(d: date):
        monkeypatch.setattr(reg, "today", lambda: d)
    _pin(TODAY)
    return _pin


def _items(s, key: str) -> dict[str, RegulationItem]:
    src = s.scalars(select(Source).where(Source.key == key)).one()
    return {r.reference: r for r in s.scalars(select(RegulationItem).where(RegulationItem.source_id == src.id))}


def _state(s, key: str) -> dict:
    row = s.get(AppSetting, f"collector_state:{key}")
    return row.value if row else {}


def _fr_doc(**over) -> reg.FrDocument:
    base = {"document_number": "2026-1", "title": "Notice", "type_label": "Notice", "abstract": None,
            "publication_date": date(2026, 1, 1), "effective_on": None,
            "url": "https://www.federalregister.gov/d/2026-1", "pdf_url": None, "agency_slugs": (),
            "agency_names": (), "action": None, "citation": None, "has_effective_on_key": True}
    base.update(over)
    return reg.FrDocument(**base)


def _query(qid: str) -> reg.FrQuery:
    return next(q for q in reg.FR_QUERIES if q.qid == qid)


# ---------------------------------------------------------------------------
# Registry / metadata
# ---------------------------------------------------------------------------


def test_collectors_registered_with_event_driven_metadata():
    fr, eu = get_collector("us_federal_register"), get_collector("eurlex_honey")
    assert fr is not None and eu is not None
    assert fr.category == eu.category == "regulation"
    assert fr.requires_key is None and eu.requires_key is None           # both keyless
    assert fr.expected_max_age_days == 60 and eu.expected_max_age_days == 180
    for c in (fr, eu):
        assert len(c.expected_update) <= 120 and "normal" in c.expected_update
    assert fr.schedule == {"trigger": "cron", "day_of_week": "mon-fri", "hour": 6, "minute": 40}
    assert eu.schedule["day_of_week"] == "mon"                           # weekly


# ---------------------------------------------------------------------------
# Federal Register: query building
# ---------------------------------------------------------------------------


def test_fr_search_params_keep_brackets_and_repeat_arrays():
    q = _query("itc_honey")
    params = reg.fr_search_params(q, date(2026, 10, 26))
    assert ("conditions[term]", "honey") in params
    assert ("conditions[publication_date][gte]", "2026-10-26") in params
    assert ("conditions[agencies][]", "international-trade-commission") in params
    assert ("per_page", "100") in params and ("order", "newest") in params
    assert [v for k, v in params if k == "fields[]"] == list(reg.FR_FIELDS)
    assert set(reg.FR_FIELDS) == {"document_number", "title", "type", "abstract", "publication_date", "effective_on",
                                  "html_url", "pdf_url", "agencies", "action", "citation"}
    url = str(httpx.Request("GET", reg.FR_SEARCH_URL, params=params).url)
    assert "conditions%5Bagencies%5D%5B%5D=international-trade-commission" in url
    assert parse_qsl(urlsplit(url).query) == params                     # lossless round trip

    pres = reg.fr_search_params(_query("pres_tariff_origins"), date(2026, 1, 1), fields=reg.FR_CORE_FIELDS)
    assert ("conditions[type][]", "PRESDOCU") in pres
    assert "effective_on" not in [v for k, v in pres if k == "fields[]"]
    china = reg.fr_search_params(_query("china_honey"), date(2026, 1, 1))
    assert ("conditions[term]", '"honey from the people\'s republic of china"') in china


def test_fr_saved_searches_cover_the_documented_queries():
    terms = {q.qid: q for q in reg.FR_QUERIES}
    assert terms["raw_honey"].term == '"raw honey"'
    assert terms["fda_honey"].agencies == ("food-and-drug-administration",)
    assert all(q.types == ("PRESDOCU",) for k, q in terms.items() if k.startswith("pres_"))
    assert len({q.state_key for q in reg.FR_QUERIES}) == len(reg.FR_QUERIES)
    # changing a query definition gives it a fresh state key (so it back-fills)
    changed = reg.FrQuery("raw_honey", "x", '"raw honey" drums')
    assert changed.state_key != terms["raw_honey"].state_key


def test_fr_since_backfill_then_last_run_minus_a_week():
    assert reg.fr_since(None, TODAY) == BACKFILL_SINCE == date(2023, 11, 3)
    assert reg.fr_since("2026-10-30", TODAY) == date(2026, 10, 23)
    assert reg.fr_since("2026-10-30", TODAY, force=True) == BACKFILL_SINCE
    assert reg.fr_since("garbage", TODAY) == BACKFILL_SINCE
    assert reg.fr_since("2027-01-01", TODAY) == TODAY - timedelta(days=7)  # clock skew never skips days


# ---------------------------------------------------------------------------
# Federal Register: parsing and drift
# ---------------------------------------------------------------------------


def test_parse_fr_search_reconstructed_page():
    page = reg.parse_fr_search(fx("fr_raw_honey_p1.json"))
    assert page.count == 4 and page.total_pages == 2
    assert page.next_page_url and "page=2" in page.next_page_url
    assert [d.document_number for d in page.documents] == ["2026-90101", "2026-90102"]
    assert len(page.problems) == 1 and "2026-90103" in page.problems[0]   # non-ISO date: skipped, reported
    brazil, omnibus = page.documents
    assert brazil.publication_date == date(2026, 6, 12) and brazil.effective_on == date(2026, 6, 12)
    assert brazil.url.startswith("https://www.federalregister.gov/documents/2026/06/12/2026-90101/")
    assert brazil.pdf_url == "https://www.govinfo.gov/content/pkg/FR-2026-06-12/pdf/2026-90101.pdf"
    assert brazil.agency_slugs == ("commerce-department", "international-trade-administration")
    assert brazil.citation == "91 FR 39001" and brazil.action == "Notice."
    assert "Commerce’s regulations" in omnibus.abstract                   # HTML entity decoded
    assert omnibus.effective_on is None and omnibus.has_effective_on_key


@pytest.mark.parametrize("body, needle", [
    (b"<html><body>Service unavailable</body></html>", "not JSON"),
    (b"[]", "JSON object"),
    (b'{"results": []}', "count"),
    (b'{"count": 2, "results": {"0": {}}}', "'results'"),
    (b'{"count": 1, "results": [{"doc_id": "2026-1", "title": "x"}]}', "document_number"),
    (b'{"count": 1, "results": [], "next_page_url": 5}', "next_page_url"),
])
def test_parse_fr_search_schema_drift_fails_loudly(body, needle):
    with pytest.raises(reg.SchemaDrift, match=needle):
        reg.parse_fr_search(body)


def test_parse_fr_search_error_object_and_empty_result():
    with pytest.raises(reg.SourceQueryError) as exc:
        reg.parse_fr_search(b'{"errors": {"conditions": {"agencies": ["not-an-agency is not a valid agency"]}}}')
    assert not isinstance(exc.value, reg.SchemaDrift)
    empty = reg.parse_fr_search(b'{"count": 0, "description": "No documents were found."}')
    assert empty.documents == [] and empty.next_page_url is None


def test_parse_fr_search_soft_problems_keep_the_document():
    body = json.dumps({"count": 1, "results": [{
        "document_number": "2026-9", "title": "<em>Raw Honey</em> From India", "type": "Uncategorized Document",
        "publication_date": "2026-01-05", "effective_on": "soon", "html_url": "http://insecure.example/x",
        "pdf_url": "https://www.govinfo.gov/x.pdf", "agencies": "ITA"}]}).encode()
    page = reg.parse_fr_search(body)
    (d,) = page.documents
    assert d.title == "Raw Honey From India"
    assert d.url == "https://www.govinfo.gov/x.pdf"         # https html_url missing -> official PDF
    assert d.effective_on is None
    assert len(page.problems) == 3                           # effective_on, unexpected type, agencies


def test_parse_fr_agencies():
    slugs = reg.parse_fr_agencies(fx("fr_agencies.json"))
    assert {"international-trade-commission", "food-and-drug-administration"} <= slugs
    assert reg.parse_fr_agencies(b'{"message": "moved"}') is None
    assert reg.parse_fr_agencies(b"not json") is None


# ---------------------------------------------------------------------------
# Federal Register: doc_type mapping, relevance, country detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("type_label, title, doc_type, status", [
    ("Presidential Document", "Further Modifying the Reciprocal Tariff Rates", "tariff", "published"),
    ("Notice", "Raw Honey From Brazil: Final Results of Antidumping Duty Administrative Review; 2023-2024",
     "antidumping", "published"),
    ("Notice", "Initiation of Antidumping and Countervailing Duty Administrative Reviews", "antidumping", "published"),
    ("Notice", "Honey From China: Anti-Dumping Duty Order", "antidumping", "published"),
    ("Notice", "Raw Honey From Argentina, Brazil, India, and Vietnam; Notice of Commission Determinations",
     "notice", "published"),
    ("Rule", "Food Labeling: Honey", "rule", "final"),
    ("Proposed Rule", "Food Standards: Honey", "proposed_rule", "proposed"),
    ("Uncategorized Document", "Honey", "notice", None),
    (None, "Honey", "notice", None),
])
def test_fr_doc_type_mapping(type_label, title, doc_type, status):
    d = _fr_doc(type_label=type_label, title=title)
    assert reg.fr_doc_type(d) == doc_type
    assert reg.fr_status(d) == status


def test_fr_relevance_filters():
    fda = _query("fda_honey")
    assert reg.fr_is_relevant(fda, _fr_doc(title="Proper Labeling of Honey", agency_slugs=("food-and-drug-administration",)))[0]
    assert reg.fr_is_relevant(fda, _fr_doc(title="Drugs for honey bees", agency_slugs=("food-and-drug-administration",))) == (False, "topic")
    assert reg.fr_is_relevant(fda, _fr_doc(title="Honey Order", agency_slugs=("agricultural-marketing-service",))) == (False, "agency")
    assert reg.fr_is_relevant(fda, _fr_doc(title="Honey labeling", agency_slugs=()))[0]   # no agencies: cannot check
    origins = _query("pres_tariff_origins")
    pres = {"type_label": "Presidential Document"}
    assert reg.fr_is_relevant(origins, _fr_doc(title="Imposing Duties on Imports From Brazil", **pres))[0]
    assert reg.fr_is_relevant(origins, _fr_doc(title="Further Modifying the Reciprocal Tariff Rates", **pres))[0]
    assert not reg.fr_is_relevant(origins, _fr_doc(title="Adjusting Imports of Lumber Into the United States", **pres))[0]
    assert reg.fr_is_relevant(origins, _fr_doc(title="Imports From Brazil", type_label="Notice")) == (False, "type")
    assert reg.fr_is_relevant(_query("raw_honey"), _fr_doc(title="Anything at all"))[0]


@pytest.mark.parametrize("text, exclude, expected", [
    ("Raw Honey From Argentina, Brazil, India, and Vietnam", (), ["ARG", "BRA", "IND", "VNM"]),
    ("Raw Honey From the Socialist Republic of Vietnam: Final Results", (), ["VNM"]),
    ("Honey From the People's Republic of China", (), ["CHN"]),
    ("entries for Moldova and Ukraine in the lists of third countries", (), ["MDA", "UKR"]),
    ("Republic of Türkiye and Viet Nam", (), ["TUR", "VNM"]),
    ("Honey from Paraguay and Cuba", (), ["PRY", "CUB"]),                     # explicit names, not keywords
    ("Indian tribes in New Mexico; smoked turkey; chile peppers", (), []),     # false friends
    ("The U.S. Department of Commerce and the United States", ("USA",), []),
    ("The U.S. Department of Commerce", (), ["USA"]),
    ("Indiana and Indianapolis", (), []),                                       # word boundaries
    ("", (), []),
])
def test_detect_countries(text, exclude, expected):
    assert reg.detect_countries(text, exclude=exclude) == expected


def test_honey_regex_excludes_the_insect():
    assert reg.HONEY_RE.search("Proper Labeling of Honey")
    assert reg.HONEY_RE.search("honey bee health and honey quality")         # second 'honey' counts
    for noise in ("honey bees", "Honey-Bee colonies", "honeybees", "Honey Bee Pests"):
        assert not reg.HONEY_RE.search(noise), noise


# ---------------------------------------------------------------------------
# Federal Register: end to end
# ---------------------------------------------------------------------------

FR_EXPECTED = {"2026-90101", "2026-90102", "2025-90104", "2025-90201", "2024-90301", "2026-90401", "2025-90402",
               "2025-90501", "2025-90502", "2026-90503"}


def test_fr_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("us_federal_register", fr_routes())
    assert res["status"] == "partial", res                       # the malformed row is reported
    assert res["new"] == len(FR_EXPECTED)
    assert any("2026-90103" in w for w in res["warnings"])
    with session_factory() as s:
        items = _items(s, "us_federal_register")
        assert set(items) == FR_EXPECTED                         # noise, other-agency and malformed rows dropped
        brazil = items["2026-90101"]
        assert (brazil.jurisdiction, brazil.doc_type, brazil.status) == ("US", "antidumping", "published")
        assert brazil.countries == ["BRA"]
        assert brazil.published_at == date(2026, 6, 12) and brazil.effective_date == date(2026, 6, 12)
        assert brazil.summary_en.startswith("The U.S. Department of Commerce (Commerce) determines")
        assert brazil.summary_is_ai is False and brazil.is_demo is False
        assert brazil.url.startswith("https://www.federalregister.gov/documents/2026/06/12/2026-90101/")
        omnibus = items["2026-90102"]
        assert omnibus.doc_type == "antidumping" and omnibus.countries is None
        assert items["2025-90104"].countries == ["VNM"]             # page 2 was followed
        assert items["2025-90201"].countries == ["CHN"]
        itc = items["2024-90301"]
        assert itc.doc_type == "notice" and itc.countries == ["ARG", "BRA", "IND", "VNM"] and itc.summary_en is None
        rule = items["2025-90402"]
        assert (rule.doc_type, rule.status, rule.effective_date) == ("rule", "final", date(2026, 1, 1))
        assert {items[n].doc_type for n in ("2025-90501", "2025-90502", "2026-90503")} == {"tariff"}
        assert items["2025-90502"].countries == ["BRA"]
        src = s.scalars(select(Source).where(Source.key == "us_federal_register")).one()
        assert src.latest_published_at == date(2026, 8, 5)
        state = _state(s, "us_federal_register")
        assert state["agencies_checked"] == TODAY.isoformat() and state["agencies_missing"] == []
        assert set(state["queries"]) == {q.state_key for q in reg.FR_QUERIES}
        assert set(state["queries"].values()) == {TODAY.isoformat()}


def test_fr_second_run_adds_nothing(run_with_routes, session_factory, pin_today):
    run_with_routes("us_federal_register", fr_routes())
    res = run_with_routes("us_federal_register", fr_routes())
    assert res["status"] == "no_change", res                    # same bytes: skipped, no repeated warnings
    assert res["new"] == 0
    forced = run_with_routes("us_federal_register", fr_routes(), force=True)
    assert forced["new"] == 0 and forced["seen"] >= len(FR_EXPECTED)    # re-parsed, de-duplicated
    with session_factory() as s:
        assert s.scalar(select(func.count(RegulationItem.id))) == len(FR_EXPECTED)


def test_fr_identical_bytes_from_another_search_are_still_ingested(run_with_routes, session_factory, pin_today):
    # The USITC search (runs earlier, drops off-agency results) and the presidential 'tariff honey'
    # search (keeps everything) get byte-identical responses: the archive de-duplicates by hash,
    # but the later search must still ingest the page on its first run.
    same = fx("fr_pres_tariff_honey.json")
    res = run_with_routes("us_federal_register", fr_routes({
        FR_DOCS + r".*international-trade-commission": same,
        FR_DOCS + r".*conditions%5Bterm%5D=tariff\+honey": same,
    }))
    assert any("USITC + honey" in w and "filter" in w for w in res["warnings"])
    with session_factory() as s:
        assert "2025-90501" in _items(s, "us_federal_register")


def test_fr_incremental_window_after_first_run(run_with_routes, pin_today, monkeypatch):
    seen: list[tuple[str, date]] = []
    real = reg.fr_search_params

    def spy(query, since, *a, **kw):
        seen.append((query.qid, since))
        return real(query, since, *a, **kw)

    monkeypatch.setattr(reg, "fr_search_params", spy)
    run_with_routes("us_federal_register", fr_routes())
    assert {s for _, s in seen} == {BACKFILL_SINCE}
    seen.clear()
    pin_today(date(2026, 11, 9))
    run_with_routes("us_federal_register", fr_routes())
    assert {q for q, _ in seen} == {q.qid for q in reg.FR_QUERIES}
    assert {s for _, s in seen} == {TODAY - timedelta(days=7)}   # last complete run minus a week


def test_fr_optional_fields_rejected_falls_back_to_defaults(run_with_routes, session_factory, pin_today):
    reject = {FR_DOCS + r"(?!.*[?&]page=2(&|$)).*fields%5B%5D=effective_on":
              (400, b'{"errors": {"fields": ["effective_on is not a valid field"]}}', "application/json")}
    res = run_with_routes("us_federal_register", fr_routes(reject))
    assert res["status"] == "partial", res
    assert sum("optional fields" in w for w in res["warnings"]) == 1      # warned once, then default fields
    with session_factory() as s:
        assert set(_items(s, "us_federal_register")) == FR_EXPECTED


def test_fr_missing_agency_slug_skips_that_search(run_with_routes, session_factory, pin_today):
    agencies = [a for a in fx_json("fr_agencies.json") if a["slug"] != "food-and-drug-administration"]
    res = run_with_routes("us_federal_register", fr_routes({reg.FR_AGENCIES_URL: json.dumps(agencies).encode()}))
    assert res["status"] == "partial"
    assert any("FDA + honey" in w and "food-and-drug-administration" in w for w in res["warnings"])
    with session_factory() as s:
        items = _items(s, "us_federal_register")
        assert "2026-90401" not in items and "2025-90402" not in items
        assert "2026-90101" in items
        state = _state(s, "us_federal_register")
        assert state["agencies_missing"] == ["food-and-drug-administration"]
        assert not any(k.startswith("fda_honey:") for k in state["queries"])     # not marked complete


def test_fr_unreadable_agency_list_is_only_a_warning(run_with_routes, session_factory, pin_today):
    res = run_with_routes("us_federal_register", fr_routes({reg.FR_AGENCIES_URL: (404, b"Not Found")}))
    assert res["status"] == "partial"
    assert any("agency list unreadable" in w for w in res["warnings"])
    with session_factory() as s:
        assert set(_items(s, "us_federal_register")) == FR_EXPECTED


def test_fr_schema_drift_fails_loudly_but_keeps_earlier_batches(run_with_routes, session_factory, pin_today):
    drift = {FR_DOCS + r".*food-and-drug-administration": b'{"data": [], "meta": {"total": 0}}'}
    res = run_with_routes("us_federal_register", fr_routes(drift))
    assert res["status"] == "failed"
    assert "Federal Register search" in res["error"] and "count" in res["error"]
    with session_factory() as s:
        items = _items(s, "us_federal_register")
        # searches that ran before the drift were checkpointed; nothing after it was stored
        assert {"2026-90101", "2025-90201", "2024-90301"} <= set(items)
        assert not ({"2026-90401", "2025-90501"} & set(items))


def test_fr_every_search_rejected_is_a_failure(run_with_routes, pin_today):
    res = run_with_routes("us_federal_register", fr_routes({FR_DOCS: (400, b'{"errors": "bad request"}')}))
    assert res["status"] == "failed"
    assert "Every Federal Register search failed" in res["error"]


def test_fr_foreign_next_page_url_stops_paging(run_with_routes, session_factory, pin_today):
    page = fx_json("fr_raw_honey_p1.json")
    page["next_page_url"] = "https://evil.example/api/v1/documents.json?page=2"
    res = run_with_routes("us_federal_register",
                          fr_routes({FR_DOCS + r".*%22raw\+honey%22": json.dumps(page).encode()}))
    assert any("unexpected next_page_url" in w for w in res["warnings"])
    with session_factory() as s:
        assert "2025-90104" not in _items(s, "us_federal_register")
        assert not any(k.startswith("raw_honey:") for k in _state(s, "us_federal_register")["queries"])


# ---------------------------------------------------------------------------
# EUR-Lex / CELLAR: query building and parsing
# ---------------------------------------------------------------------------


def test_build_sparql_queries():
    q = reg.build_title_query(date(2021, 11, 3))
    assert '"2021-11-03"^^xsd:date' in q and 'CONTAINS(LCASE(STR(?title)), "honey")' in q
    assert reg.LANG_ENG in q and "LIMIT 1000" in q and "^(2|3|5[0-9]{4}PC)" in q
    r = reg.build_related_query(reg.WATCHED_ACTS)
    for celex in ("32001L0110", "32024L1438", "32021R0405"):
        assert f'"{celex}" "{celex}"^^xsd:string' in r
    for rel in reg.RELATIONS:
        assert f"cdm:{rel}" in r
    for query in (q, r):
        assert query.count("{") == query.count("}") and query.startswith("PREFIX cdm:")


def test_eu_title_since():
    assert reg.eu_title_since(None, TODAY) == TODAY - timedelta(days=reg.EU_BACKFILL_DAYS)
    assert reg.eu_title_since("2026-10-26", TODAY) == date(2026, 10, 26) - timedelta(days=reg.EU_OVERLAP_DAYS)
    assert reg.eu_title_since("2026-10-26", TODAY, force=True) == TODAY - timedelta(days=reg.EU_BACKFILL_DAYS)
    assert reg.eu_title_since("2027-03-01", TODAY) == TODAY - timedelta(days=reg.EU_OVERLAP_DAYS)


def test_parse_sparql_json_reconstructed_result():
    res = reg.parse_sparql_json(fx("cellar_related.json"), reg.RELATED_VARS)
    assert res.vars[:4] == ["celex", "date", "title", "target"]
    assert len(res.rows) == 7 and res.problems == []
    no_title = next(r for r in res.rows if r["celex"] == "32026D9902")
    assert "title" not in no_title                                  # unbound OPTIONAL stays absent
    assert next(r for r in res.rows if r["celex"] == "32021R0405R(05)")["date"] == "2026-02-20"   # typed-literal


@pytest.mark.parametrize("body, needle", [
    (b"Virtuoso 37000 Error SP030: SPARQL compiler, line 3: syntax error", "not JSON"),
    (b'{"head": {}, "boolean": true}', "head.vars"),
    (b'{"head": {"vars": ["celex"]}, "results": {"rows": []}}', "results.bindings"),
    (b'{"head": {"vars": ["x"]}, "results": {"bindings": []}}', "missing from head.vars"),
    (b'{"head": {"vars": ["celex", "date", "title"]}, "results": {"bindings": [{"celex": "32024L1438"}]}}',
     "none of the 1 bindings"),
])
def test_parse_sparql_json_drift(body, needle):
    with pytest.raises(reg.SchemaDrift, match=needle):
        reg.parse_sparql_json(body, reg.TITLE_VARS)


def test_parse_sparql_json_skips_one_malformed_binding():
    body = json.dumps({"head": {"vars": ["celex", "date", "title"]}, "results": {"bindings": [
        {"celex": {"type": "literal", "value": "32024L1438"}, "date": {"type": "literal", "value": "2024-05-14"}},
        {"celex": {"type": "weird", "value": "x"}},
    ]}}).encode()
    res = reg.parse_sparql_json(body, reg.TITLE_VARS)
    assert len(res.rows) == 1 and len(res.problems) == 1 and "?celex" in res.problems[0]


@pytest.mark.parametrize("celex, doc_type, corrigendum", [
    ("32024L1438", "directive", False),
    ("32021R0405", "regulation", False),
    ("32022D0123", "decision", False),
    ("32023H0456", "recommendation", False),
    ("32021R0405R(05)", "regulation", True),
    ("52026PC9903", "proposal", False),
    ("22025D9907", "decision", False),
    ("22014A0529(01)", "agreement", False),
    ("92025E009906", None, False),          # parliamentary question: out of scope
    ("02001L0110-20240613", None, False),   # consolidated text: out of scope
    ("62019CJ0001", None, False),           # case law: out of scope
])
def test_celex_parsing_and_doc_type(celex, doc_type, corrigendum):
    info = reg.parse_celex(celex)
    assert info is not None and info.celex == celex
    assert reg.eu_doc_type(info) == doc_type
    assert info.is_corrigendum is corrigendum


def test_celex_rejects_garbage():
    for bad in ("not-a-celex", "", None, "3202L1438", "32024l1438 extra"):
        assert reg.parse_celex(bad) is None
    assert reg.eurlex_url("32024L1438") == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024L1438"


def test_group_eu_acts_merges_rows():
    res = reg.parse_sparql_json(fx("cellar_related.json"), reg.RELATED_VARS)
    acts, problems = reg.group_eu_acts(res.rows)
    assert len(problems) == 1 and "not-a-celex" in problems[0]
    canary = acts["32024L1438"]
    assert canary.title.startswith("Directive (EU) 2024/1438 of the European Parliament")   # most complete variant
    assert canary.targets == {"32001L0110"} and canary.in_force is True
    assert acts["32026R9901"].entry_into_force == date(2026, 3, 31)
    assert acts["32026D9902"].title is None
    reg.check_related_canary(acts)                                    # passes on the reconstructed result


def test_canaries_detect_vocabulary_drift():
    acts, _ = reg.group_eu_acts(reg.parse_sparql_json(fx("cellar_related.json"), reg.RELATED_VARS).rows)
    del acts["32024L1438"]
    with pytest.raises(reg.SchemaDrift, match="self-check"):
        reg.check_related_canary(acts)
    untitled, _ = reg.group_eu_acts([{"celex": "32024L1438", "date": "2024-05-14", "target": "32001L0110"}])
    with pytest.raises(reg.SchemaDrift, match="English title"):
        reg.check_related_canary(untitled)
    with pytest.raises(reg.SchemaDrift, match="title query"):
        reg.check_title_canary({}, since=date(2021, 11, 3))
    reg.check_title_canary({}, since=date(2026, 5, 6))                # window after 14 May 2024: not checked


def test_sparql_incomplete_header():
    assert reg.sparql_incomplete({"X-SQL-State": "S1TAT", "X-SQL-Message": "RC...: Returning incomplete results"})
    assert reg.sparql_incomplete({"x-sql-state": "s1tat"})
    assert not reg.sparql_incomplete({"content-type": "application/sparql-results+json"})


def test_eu_status():
    acts, _ = reg.group_eu_acts([
        {"celex": "52026PC9903", "date": "2026-09-15", "title": "Proposal ... honey"},
        {"celex": "32021R0405R(05)", "date": "2026-02-20", "title": "Corrigendum", "inforce": "true"},
        {"celex": "32014L0063", "date": "2014-05-15", "title": "Directive", "inforce": "true"},
        {"celex": "31974L0409", "date": "1974-07-22", "title": "Directive", "inforce": "false"},
        {"celex": "32025R9904", "date": "2025-04-03", "title": "Regulation"},
    ])
    assert {k: reg.eu_status(a) for k, a in acts.items()} == {
        "52026PC9903": "proposed", "32021R0405R(05)": "corrigendum", "32014L0063": "in_force",
        "31974L0409": "no_longer_in_force", "32025R9904": None,
    }


# ---------------------------------------------------------------------------
# EUR-Lex / CELLAR: end to end
# ---------------------------------------------------------------------------

EU_EXPECTED = {"32024L1438", "32014L0063", "32026R9901", "32021R0405R(05)", "52026PC9903", "32025R9904", "22025D9907"}


def test_eurlex_end_to_end(run_with_routes, session_factory, pin_today):
    res = run_with_routes("eurlex_honey", eu_routes())
    assert res["status"] == "partial", res                     # malformed CELEX + act without English title
    assert res["new"] == len(EU_EXPECTED)
    assert any("not-a-celex" in w for w in res["warnings"])
    assert any("32026D9902" in w and "English title" in w for w in res["warnings"])
    with session_factory() as s:
        items = _items(s, "eurlex_honey")
        assert set(items) == EU_EXPECTED                       # no question, no 'honeybees' act, no untitled act
        d = items["32024L1438"]
        assert (d.jurisdiction, d.doc_type, d.status) == ("EU", "directive", "in_force")
        assert d.published_at == date(2024, 5, 14) and d.effective_date is None
        assert d.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024L1438"
        assert d.summary_en is None and d.summary_is_ai is False   # no official abstract: never invented
        assert d.countries is None
        amend = items["32026R9901"]
        assert amend.doc_type == "regulation" and amend.countries == ["MDA", "UKR"]
        assert amend.effective_date == date(2026, 3, 31)
        assert items["32021R0405R(05)"].status == "corrigendum"
        assert (items["52026PC9903"].doc_type, items["52026PC9903"].status) == ("proposal", "proposed")
        assert items["52026PC9903"].countries == ["UKR"]
        assert (items["22025D9907"].doc_type, items["22025D9907"].countries) == ("decision", ["UKR"])
        assert items["32025R9904"].status is None
        assert _state(s, "eurlex_honey")["title_complete"] == TODAY.isoformat()


def test_eurlex_second_run_adds_nothing(run_with_routes, session_factory, pin_today):
    run_with_routes("eurlex_honey", eu_routes())
    res = run_with_routes("eurlex_honey", eu_routes())
    assert res["status"] == "no_change" and res["new"] == 0, res
    forced = run_with_routes("eurlex_honey", eu_routes(), force=True)
    assert forced["new"] == 0
    with session_factory() as s:
        assert len(_items(s, "eurlex_honey")) == len(EU_EXPECTED)


def test_eurlex_incremental_title_window(run_with_routes, pin_today, monkeypatch):
    seen: list[date] = []
    real = reg.build_title_query
    monkeypatch.setattr(reg, "build_title_query", lambda since, *a, **kw: seen.append(since) or real(since, *a, **kw))
    run_with_routes("eurlex_honey", eu_routes())
    pin_today(date(2026, 11, 9))
    run_with_routes("eurlex_honey", eu_routes())
    assert seen == [TODAY - timedelta(days=reg.EU_BACKFILL_DAYS), TODAY - timedelta(days=reg.EU_OVERLAP_DAYS)]


def test_eurlex_canary_missing_fails_loudly(run_with_routes, session_factory, pin_today):
    doc = fx_json("cellar_related.json")
    doc["results"]["bindings"] = [b for b in doc["results"]["bindings"] if b["celex"]["value"] != "32024L1438"]
    res = run_with_routes("eurlex_honey", eu_routes({CELLAR_RELATED: json.dumps(doc).encode()}))
    assert res["status"] == "failed"
    assert "self-check" in res["error"]
    with session_factory() as s:
        assert _items(s, "eurlex_honey") == {}                 # nothing stored from a doubtful query


def test_eurlex_sparql_drift_fails_loudly(run_with_routes, session_factory, pin_today):
    res = run_with_routes("eurlex_honey", eu_routes({CELLAR_TITLE: b'{"head": {"vars": ["celex"]}, "boolean": true}'}))
    assert res["status"] == "failed" and "SPARQL" in res["error"]
    with session_factory() as s:
        items = _items(s, "eurlex_honey")
        assert "32026R9901" in items                           # the related-acts batch was checkpointed
        assert "52026PC9903" not in items
        assert "title_complete" not in _state(s, "eurlex_honey")


def test_eurlex_http_error_on_one_query(run_with_routes, session_factory, pin_today):
    err = (400, b"Virtuoso 37000 Error SP030: SPARQL compiler, line 4: Undefined namespace prefix", "text/plain")
    res = run_with_routes("eurlex_honey", eu_routes({CELLAR_RELATED: err}))
    assert res["status"] == "failed"
    assert "HTTP 400" in res["error"] and "related acts" in res["error"]
    with session_factory() as s:
        items = _items(s, "eurlex_honey")
        assert {"52026PC9903", "32024L1438"} <= set(items)       # the title query still ran and was kept
