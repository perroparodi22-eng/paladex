"""FE-9: source metadata shown on the Sources and Trade pages is bilingual.

`expected_update` (Italian, the default UI language) and `expected_update_en` (English) are both set
by every collector, so English no longer leaks into the Italian UI ("Monthly (issue dated near the
end of the month)") nor Italian into the English one ("Settimanale (listino del mercoledì)").
"""
from __future__ import annotations

import re

import pytest

from paladex.collectors.registry import all_collectors

# Words that only appear in a publication rhythm written in the other language.
ENGLISH_WORDS = re.compile(r"\b(monthly|weekly|daily|annual|yearly|every|checked|irregular|month|week|year|news|the|and)\b", re.I)
ITALIAN_WORDS = re.compile(r"\b(mensile|settimanale|giornaliero|annuale|ogni|controllo|controllato|irregolar[ei]|mese|settimana|anno|notizie|il|la|di|e)\b", re.I)


def _prose(text: str) -> str:
    """Drop quoted search queries («…», "…"): they are in the language of the search, by design."""
    return re.sub(r"«[^»]*»|\"[^\"]*\"", " ", text)


SPECS = [c.source_spec() for c in all_collectors()]


@pytest.mark.parametrize("spec", SPECS, ids=[s["key"] for s in SPECS])
def test_every_collector_states_its_rhythm_in_italian_and_english(spec):
    it, en = spec["expected_update"], spec["expected_update_en"]
    assert it and en, f"{spec['key']}: expected_update and expected_update_en must both be set"
    assert it != en
    assert not ENGLISH_WORDS.search(_prose(it)), f"{spec['key']}: English in the Italian text: {it!r}"
    assert not ITALIAN_WORDS.search(_prose(en)), f"{spec['key']}: Italian in the English text: {en!r}"
    assert len(it) <= 120 or "«" in it      # Source.expected_update is String(120) (search queries aside)


def test_sources_api_returns_both_languages(api):
    rows = {s["key"]: s for s in api.get("/api/sources").json()["sources"]}
    usda = rows["usda_honey_report"]
    assert usda["expected_update"].startswith("Mensile")
    assert usda["expected_update_en"].startswith("Monthly")
    siena = rows["cciaa_siena_miele"]
    assert siena["expected_update"] == "Settimanale (listino del mercoledì)"
    assert siena["expected_update_en"] == "Weekly (Wednesday price list)"


# --- English source names (name_en) -----------------------------------------------------------------
# Collectors being written in parallel set their own; every other module must give one.
_NEW_MODULES = ("production_official", "trade_origins", "companies_official")


@pytest.mark.parametrize("c", [c for c in all_collectors() if type(c).__module__.rsplit(".", 1)[-1] not in _NEW_MODULES],
                         ids=lambda c: c.key)
def test_every_collector_has_an_english_name(c):
    spec = c.source_spec()
    assert "name_en" in spec
    en = spec["name_en"] or spec["name"]           # "" only when the name is already English
    assert en and not ITALIAN_WORDS.search(_prose(en).replace("Comext", "")), (c.key, en)


def test_source_name_en_is_stored_migrated_and_sent(db, api, tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from paladex.db import migrate_add_missing_columns

    old = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE sources (id INTEGER PRIMARY KEY, key VARCHAR(60), name VARCHAR(200))"))
    assert "sources.name_en" in migrate_add_missing_columns(old)
    assert "name_en" in {c["name"] for c in inspect(old).get_columns("sources")}

    by_key = {s["key"]: s for s in api.get("/api/sources").json()["sources"]}
    assert by_key["cciaa_cuneo_miele"]["name_en"] == "Chamber of Commerce of Cuneo — wholesale honey prices"
    assert by_key["ec_honey_market"]["name_en"].startswith("European Commission — DG Agriculture")
    assert by_key["news_gn_it_prezzo_miele"]["name_en"] == "Google News · honey price (Italian)"
    assert by_key["news_bee_culture"]["name_en"] is None   # already English: the name is shown
