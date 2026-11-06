"""Test fixtures: every test gets a fresh SQLite database in a temp dir.

Collectors are tested offline against files in tests/fixtures/ using respx to mock HTTP.

    def test_x(db, run_with_routes):
        res = run_with_routes("usda_honey", {
            "https://www.ams.usda.gov/mnreports/fvmhoney.pdf": fixture_bytes("usda/fvmhoney.pdf"),
        })
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
import pytest
import respx

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADEX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PALADEX_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("PALADEX_LLM_PROVIDER", "none")
    # Corrections are never exchanged with the real repository's origin from a test (test_corrections.py
    # turns it on against a temporary bare repository).
    monkeypatch.setenv("PALADEX_CORRECTIONS_SYNC", "false")
    for k in ("PALADEX_COMTRADE_API_KEY", "PALADEX_USDA_MMN_API_KEY", "PALADEX_USDA_NASS_API_KEY",
              "PALADEX_ANTHROPIC_API_KEY", "PALADEX_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from paladex import config, db as dbmod

    config.get_settings.cache_clear()
    settings = config.get_settings()
    dbmod.init_db(settings.database_url)
    with dbmod.session_scope() as s:
        yield s
    dbmod._engine.dispose()
    dbmod._engine = None
    config.get_settings.cache_clear()


@pytest.fixture()
def session_factory(db):
    from paladex.db import session_scope

    return session_scope


@pytest.fixture()
def api(db):
    from fastapi.testclient import TestClient

    from paladex.main import create_app

    # The address the owner's browser uses (the app answers loopback host names only).
    return TestClient(create_app(start_scheduler=False), base_url="http://127.0.0.1:8765")


@pytest.fixture()
def run_with_routes(db, monkeypatch):
    """Run a collector with mocked HTTP. `routes` maps a URL (exact, or a regex string starting
    with '^') to bytes | (status, bytes) | (status, bytes, content_type). A key may also be a
    `(method, url)` tuple, e.g. `("POST", "https://...")`, to mock a non-GET request."""
    from paladex.collectors import base, runner

    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    # Unrouted URLs raise ConnectError: by default that means "this PC is offline" (OFFLINE run).
    # A test checking a host-specific failure patches `runner.is_online` to return True.
    monkeypatch.setattr(runner, "is_online", lambda *a, **k: False)

    def _run(key: str, routes: dict, force: bool = False):
        from paladex.collectors.runner import run_collector

        with respx.mock(assert_all_called=False) as mock:
            for url, spec in routes.items():
                method, url = url if isinstance(url, tuple) else ("GET", url)
                if isinstance(spec, bytes):
                    spec = (200, spec)
                status, body, *ctype = spec
                headers = {"content-type": ctype[0]} if ctype else {}
                if url.startswith("^"):
                    route = mock.route(method=method, url__regex=url)
                else:
                    route = mock.route(method=method, url__startswith=url)
                route.mock(return_value=httpx.Response(status, content=body, headers=headers))
            mock.route().mock(side_effect=httpx.ConnectError("blocked in tests"))
            with httpx.Client(follow_redirects=True) as client:
                return run_collector(key, trigger="test", force=force, client=client)

    return _run
