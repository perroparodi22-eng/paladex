"""Speed work on the heaviest answers, without changing them.

* memo.py: aggregates reused while the database is unchanged, rebuilt after ANY commit (also from
  another connection, as a collection run from the command line would be).
* /prices/series: a large view ships the points of its first lines only; with `ids` the requested
  ones, identical to the full answer; every series keeps its newest value (`last_value`).
* FastJSONResponse writes the same bytes FastAPI's default encoder would.
* init_db leaves planner statistics (sqlite_stat1) behind.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from enum import Enum

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text

from paladex.api import memo
from paladex.api import prices as prices_api
from paladex.api.common import FastJSONResponse
from paladex.config import get_settings

from test_api_countries_trade import make_source, trade
from test_api_prices import _ym, add_price, sources  # noqa: F401  (fixture)


def test_trade_facets_follow_every_commit_even_from_another_connection(api, db):
    src = make_source(db, "t_comtrade")
    trade(db, src, "DEU", "WLD", 2024, 1000.0)
    db.commit()
    first = api.get("/api/trade/facets").json()
    assert first["total_rows"] == 1
    assert api.get("/api/trade/facets").json() == first           # reused: same answer
    # a write through a plain sqlite3 connection (another process, e.g. a CLI collection)
    with sqlite3.connect(get_settings().db_path) as conn:
        conn.execute("UPDATE trade_flows SET net_weight_kg = 2000 WHERE reporter_iso3 = 'DEU'")
    trade(db, src, "FRA", "WLD", 2024, 500.0)
    db.commit()
    after = api.get("/api/trade/facets").json()
    assert after["total_rows"] == 2 and {r["iso3"] for r in after["reporters"]} == {"DEU", "FRA"}
    leaders = api.get("/api/trade/leaders", params={"flow": "import", "year": 2024}).json()
    deu = next(r for r in leaders["rows"] if r["iso3"] == "DEU")
    assert deu["net_weight_kg"] == 2000.0                          # the other connection's change is seen


def test_nothing_is_cached_while_the_session_holds_uncommitted_writes(db):
    calls = []
    db.execute(text("UPDATE app_settings SET value = value"))     # opens a write transaction
    db.add(make_source(db, "t_pending"))
    assert memo._writing(db)
    memo.cached(db, "t", (), lambda: calls.append(1))
    memo.cached(db, "t", (), lambda: calls.append(1))
    assert len(calls) == 2
    db.commit()
    memo.cached(db, "t", (), lambda: calls.append(1))
    memo.cached(db, "t", (), lambda: calls.append(1))
    assert len(calls) == 3


def test_large_price_view_ships_the_default_lines_and_ids_give_the_full_answer(api, db, sources, monkeypatch):
    usda, _ = sources
    origins = ["ARG", "UKR", "CHN", "BRA", "VNM", "IND", "HUN", "TUR", "URY"]
    for i, o in enumerate(origins):
        for m in range(1, 5):
            add_price(db, usda, period=_ym(m), value=2.0 + i / 10 + m / 100, origin=o, price_type="import_unit_value",
                      market="ITA", low=1.9 if o == "ARG" else None, high=2.6 if o == "ARG" else None)
    add_price(db, usda, period=_ym(1), value=3.0, origin="NZL", price_type="import_unit_value", market="ITA",
              currency="EUR", usd=None, terms="no fx")             # its only point has no USD conversion
    db.commit()
    params = {"price_type": "import_unit_value", "freq": "M", "currency": "USD"}
    small = api.get("/api/prices/series", params=params).json()     # 37 rows: every point
    assert small["points_scope"] == "all" and all(s["points"] for s in small["series"])
    memo.clear()
    monkeypatch.setattr(prices_api, "SERIES_ALL_POINTS_MAX_ROWS", 10)
    light = api.get("/api/prices/series", params=params).json()
    assert light["points_scope"] == "first"
    with_points = [s["id"] for s in light["series"] if not s["points_omitted"]]
    assert with_points == [s["id"] for s in light["series"][:prices_api.SERIES_DEFAULT_POINTS]]
    assert [s["id"] for s in light["series"]] == [s["id"] for s in small["series"]]
    full = {s["id"]: s for s in small["series"]}
    for s in light["series"]:
        f = full[s["id"]]
        assert s["last_value"] == f["last_value"]
        assert (s["n_points"], s["first_period"], s["last_period"], s["fx_missing_points"], s["has_range"]) == (
            f["n_points"], f["first_period"], f["last_period"], f["fx_missing_points"], f["has_range"])
        if not s["points_omitted"]:
            assert s == f
    no_fx = next(s for s in light["series"] if s["terms"] == "no fx")
    assert no_fx["points_omitted"] and no_fx["fx_missing_points"] == 1 and no_fx["last_value"] is None
    # every id asked for: the full answer, unchanged
    ids = ",".join(full)
    asked = api.get("/api/prices/series", params={**params, "ids": ids}).json()
    assert asked["points_scope"] == "ids"
    assert {k: v for k, v in asked.items() if k != "points_scope"} == {k: v for k, v in small.items() if k != "points_scope"}
    # one hidden series asked for by id
    hidden = next(s["id"] for s in light["series"] if s["points_omitted"])
    one = api.get("/api/prices/series", params={**params, "ids": hidden}).json()
    assert [s["id"] for s in one["series"] if not s["points_omitted"]] == [hidden]
    assert next(s for s in one["series"] if s["id"] == hidden) == full[hidden]


class _Kind(str, Enum):
    A = "a"


def test_fast_json_writes_the_same_bytes_as_fastapi():
    content = {"d": date(2026, 11, 5), "dt": datetime(2026, 11, 5, 21, 0, 1, 5), "s": {"x"}, "t": (1, 2.5, None),
               "e": _Kind.A, "nested": [{"àè": "€", "n": -0.0001, "b": True}], "k": {1: "one"}}
    assert FastJSONResponse(content).body == JSONResponse(jsonable_encoder(content)).body


def test_init_db_leaves_planner_statistics(db):
    names = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))}
    assert "sqlite_stat1" in names
