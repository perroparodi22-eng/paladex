"""Honey companies found on the web, country by country (owner's request, 15 Nov 2026: "do the
business part per each country, you can get the first Google results, no need for them to update").

This is NOT the official company information of api/companies.py (customs figures, registers). It is
a fixed list written once from web searches: the name of a business, what it does with honey in one
plain sentence, and its own website. Rules it was built with, and that any addition must keep:

* a company is listed only with its OWN website (never a directory, a marketplace or a news page),
  and only when that site could be opened by Paladex's research and speaks of honey
  (`scripts/check_companies_web.py` re-checks every entry and says which no longer pass);
* no figures, no ranking, no "largest": the list is alphabetical and says it is incomplete;
* it is shown apart from the official lists, always labelled "non ufficiale", with the search date.

The file is `companies_web_seed.json` next to this module: {"searched_on", "entries": [{"iso3",
"name", "role", "city", "website", "source_url", "what_it", "what_en"}]}.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SEED_PATH = Path(__file__).with_name("companies_web_seed.json")
ROLES = ("exporter", "packer", "cooperative", "importer", "trader")
_FIELDS = ("name", "role", "city", "website", "source_url", "what_it", "what_en")


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        doc = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"searched_on": None, "by_country": {}}
    by_country: dict[str, list[dict]] = {}
    for e in doc.get("entries") or []:
        iso3 = str(e.get("iso3") or "").upper()
        name, site = str(e.get("name") or "").strip(), str(e.get("website") or "").strip()
        if len(iso3) != 3 or not name or not site.startswith(("http://", "https://")):
            continue        # an entry without its own website is not shown
        item = {k: e.get(k) for k in _FIELDS}
        item["name"], item["website"] = name, site
        item["role"] = item["role"] if item["role"] in ROLES else "trader"
        item["source_url"] = item.get("source_url") or site
        by_country.setdefault(iso3, []).append(item)
    for items in by_country.values():
        items.sort(key=lambda x: x["name"].casefold())      # alphabetical: never a ranking
    return {"searched_on": doc.get("searched_on"), "by_country": by_country}


def searched_on() -> str | None:
    return _load()["searched_on"]


def for_country(iso3: str) -> list[dict]:
    return [dict(x) for x in _load()["by_country"].get(iso3.upper(), [])]


def counts() -> dict[str, int]:
    return {k: len(v) for k, v in _load()["by_country"].items()}


def section(iso3: str) -> dict:
    """What the API returns for a country: the search date and the companies, alphabetical."""
    return {"searched_on": searched_on(), "companies": for_country(iso3)}
