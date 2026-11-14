"""Honey companies found on the web (reference/companies_web.py): a fixed, non-official list shown
apart from the official company information. Owner's request of 15 Nov 2026."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import pytest

from paladex.reference import companies_web as cw

NOT_OWN_SITE = ("alibaba.", "made-in-china.", "tridge.", "volza.", "europages.", "kompass.", "linkedin.", "facebook.",
                "instagram.", "wikipedia.", "indiamart.", "tradeindia.", "exportersindia.", "go4worldbusiness.")


@pytest.fixture()
def seed(tmp_path, monkeypatch):
    def write(entries, searched_on="2026-11-15"):
        p = tmp_path / "seed.json"
        p.write_text(json.dumps({"searched_on": searched_on, "entries": entries}), encoding="utf-8")
        monkeypatch.setattr(cw, "SEED_PATH", p)
        cw._load.cache_clear()
    yield write
    cw._load.cache_clear()


def _e(**over):
    return {"iso3": "ARG", "name": "Zeta Miel", "role": "exporter", "city": "Rosario", "website": "https://zeta.example",
            "source_url": "https://zeta.example/about", "what_it": "Esporta miele in fusti.", "what_en": "Exports honey in drums.", **over}


def test_the_shipped_list_keeps_its_rules():
    """Every company has its own website, a role, both descriptions without figures, and the lists
    are alphabetical (never a ranking)."""
    doc = json.loads(cw.SEED_PATH.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["searched_on"])
    assert len(doc["entries"]) >= 10
    for e in doc["entries"]:
        host = urlparse(e["website"]).hostname or ""
        assert e["website"].startswith(("http://", "https://")) and host, e
        assert not any(bad in host for bad in NOT_OWN_SITE), e["website"]
        assert (urlparse(e["source_url"]).hostname or "") == host, e          # checked on the company's own site
        assert e["role"] in cw.ROLES and re.fullmatch(r"[A-Z]{3}", e["iso3"]) and e["name"].strip(), e
        for text in (e["what_it"], e["what_en"]):
            assert text and len(text) < 260, e
            assert not re.search(r"\d", text), f"no figures in the description: {e['name']}: {text}"
            assert not re.search(r"\b(largest|leading|leader|biggest|number one|il più grande|leader di|maggiore|principale)\b", text, re.I), text
        assert "parodi" not in e["name"].casefold()
    cw._load.cache_clear()
    for iso3, n in cw.counts().items():
        names = [c["name"] for c in cw.for_country(iso3)]
        assert names == sorted(names, key=str.casefold) and len(names) == n


def test_entries_without_an_own_website_are_not_shown_and_lists_are_alphabetical(seed):
    seed([_e(), _e(name="alfa Honey", website="https://alfa.example", role="grande"), _e(name="No Site", website=""),
          _e(name="Bad", website="ftp://x"), _e(iso3="deu", name="Honig GmbH", website="https://honig.example", source_url=None)])
    assert cw.counts() == {"ARG": 2, "DEU": 1}
    assert [c["name"] for c in cw.for_country("arg")] == ["alfa Honey", "Zeta Miel"]
    assert cw.for_country("ARG")[0]["role"] == "trader"                       # an unknown role is never invented
    assert cw.for_country("DEU")[0]["source_url"] == "https://honig.example"
    assert cw.section("ITA") == {"searched_on": "2026-11-15", "companies": []}


def test_a_missing_or_broken_file_shows_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "SEED_PATH", tmp_path / "missing.json")
    cw._load.cache_clear()
    try:
        assert cw.counts() == {} and cw.searched_on() is None and cw.for_country("ARG") == []
    finally:
        cw._load.cache_clear()


def test_api_serves_the_web_list_apart_from_the_official_lists(api, seed):
    seed([_e(), _e(iso3="PRY", name="Miel del Chaco", website="https://chaco.example")])
    over = api.get("/api/companies").json()
    assert over["web_searched_on"] == "2026-11-15"
    by = {c["iso3"]: c for c in over["countries"]}
    assert by["ARG"]["web_companies"] == 1
    # a country with no research entry is listed for its web companies, its official status unchanged
    assert by["PRY"]["web_companies"] == 1 and by["PRY"]["status"] == "unverified" and by["PRY"]["companies"] == {}
    arg = api.get("/api/companies/ARG").json()
    assert arg["web"]["searched_on"] == "2026-11-15"
    assert [c["name"] for c in arg["web"]["companies"]] == ["Zeta Miel"]
    assert arg["web"]["companies"][0]["website"] == "https://zeta.example"
    assert all("Zeta" not in json.dumps(l) for l in arg["lists"])            # never mixed with official records
    assert api.get("/api/companies/ITA").json()["web"]["companies"] == []
