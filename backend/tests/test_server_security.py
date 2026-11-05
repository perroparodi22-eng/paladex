"""The local server answers only the owner's own Paladex tab (main.LocalOnlyGuard).

* DNS rebinding: a page on another domain that points its name at 127.0.0.1 sends its own
  Host header; it must not read anything (supplier quotes are the most private data).
* Cross-site requests: a page elsewhere can make the browser send simple POSTs (a form, or
  fetch in no-cors mode) and GETs (an <img>); none may change anything or spend AI credits.
* The interface's own requests (same origin, also through the Vite dev proxy) and tools without a
  browser (CLI, crawler, curl) keep working. CORS stays closed.
"""
from __future__ import annotations

from datetime import date

import pytest

from paladex.main import _host_name, _origin_name
from paladex.models import PriceObservation, SupplierQuote

CROSS = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "LOCALHOST", "[::1]:8765", "localhost.:5173",
                                  "127.0.0.1"])
def test_loopback_host_names_are_served(api, host):
    assert api.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example:8765", "evil.example", "127.0.0.1.evil.example:8765",
                                  "localhost.evil.example", "192.168.1.20:8765", "", "127.0.0.1:8765:1"])
def test_other_host_names_are_refused_dns_rebinding(api, db, host):
    db.add(SupplierQuote(supplier_name="Private supplier", origin_iso3="ARG", variety="polyflora",
                         price_per_kg=3.1, currency="USD", date_received=date(2026, 11, 1)))
    db.commit()
    for path in ("/api/quotes", "/api/health", "/", "/assets/x.js"):
        res = api.get(path, headers={"Host": host})
        assert res.status_code == 400, (host, path)
        assert "Private supplier" not in res.text
    assert api.get("/api/quotes").status_code == 200 and "Private supplier" in api.get("/api/quotes").text


def test_cross_site_requests_change_nothing(api, db):
    # A form on another site posting to the bodiless endpoints, and an <img> GET.
    for method, path in (("POST", "/api/demo/seed"), ("POST", "/api/quality/run"), ("POST", "/api/collect"),
                         ("POST", "/api/news/1/translate?lang=it&force=true"),
                         ("POST", "/api/assistant/briefing/regenerate"), ("POST", "/api/alerts/events/read-all")):
        res = api.request(method, path, headers=CROSS, content=b"x=1")
        assert res.status_code == 403, (method, path, res.status_code)
        # Old browsers without Sec-Fetch-*: the Origin alone is enough to refuse.
        res = api.request(method, path, headers={"Origin": "https://evil.example"}, content=b"x=1")
        assert res.status_code == 403, (method, path)
        res = api.request(method, path, headers={"Origin": "null"}, content=b"x=1")   # sandboxed frame
        assert res.status_code == 403, (method, path)
    assert api.get("/api/settings", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # Another web application on this computer (same site, other port) is refused too.
    assert api.get("/api/quotes", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert db.query(PriceObservation).filter(PriceObservation.is_demo.is_(True)).count() == 0
    assert api.get("/api/settings").json()["show_demo"] is False


def test_the_interface_and_tools_keep_working(api, db):
    same = {"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}
    assert api.put("/api/settings", json={"language": "en"}, headers=same).json()["language"] == "en"
    # Vite dev server: the proxy rewrites Host to the backend, the browser's Origin is the dev server.
    dev = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}
    assert api.put("/api/settings", json={"language": "it"}, headers=dev).status_code == 200
    # DELETE without a body (api.del) from the interface.
    assert api.delete("/api/assistant/history", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    # Command-line tools and the online-copy crawler send no Origin and no Sec-Fetch-Site.
    assert api.post("/api/demo/seed").status_code == 200
    assert api.get("/api/meta").status_code == 200
    # The owner opening the app from a bookmark or a link elsewhere (top-level navigation).
    assert api.get("/api/health", headers={"Sec-Fetch-Site": "none"}).status_code == 200
    assert api.get("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}).status_code == 200


def test_cors_stays_closed(api):
    pre = api.options("/api/collect", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers
    res = api.get("/api/health", headers={"Origin": "https://evil.example"})
    assert res.status_code == 200 and "access-control-allow-origin" not in res.headers


def test_header_parsing():
    assert _host_name("[::1]:8765") == "::1" and _host_name("LocalHost.:1") == "localhost"
    assert _host_name("evil.example:8765") == "evil.example" and _host_name("[::1") == ""
    assert _origin_name("http://[::1]:8765") == "::1" and _origin_name("http://LOCALHOST:5173") == "localhost"
    assert _origin_name("null") is None and _origin_name("file://") is None and _origin_name("http://[x") is None


def test_pages_cannot_be_framed_by_another_site(api):
    page = api.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert page.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    data = api.get("/api/health")
    assert data.headers["x-content-type-options"] == "nosniff" and "x-frame-options" not in data.headers
