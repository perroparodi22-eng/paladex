"""FastAPI application: JSON API under /api and the built frontend at /."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders

from . import scheduler
from .api import build_router
from .collectors import base as _collector_base  # noqa: F401 - installs the httpx log filter that redacts API keys in URLs
from .config import get_settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Names under which this computer reaches its own server (the server listens on 127.0.0.1 only).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host_name(value: str) -> str:
    """Host header -> lower-case name without port: '[::1]:8765' -> '::1', 'LocalHost.:8765' -> 'localhost'."""
    v = value.strip().lower()
    if v.startswith("["):
        v = v[1:v.index("]")] if "]" in v else ""
    elif v.count(":") == 1:
        v = v.split(":", 1)[0]
    return v.rstrip(".")


def _origin_name(value: str) -> str | None:
    """Origin header -> its host name, or None for 'null' and anything that is not http(s)."""
    try:
        u = urlsplit(value.strip())
        name = u.hostname
    except ValueError:
        return None
    return name.rstrip(".") if u.scheme in ("http", "https") and name else None


class LocalOnlyGuard:
    """Answer only the owner's own Paladex tab (ARCHITECTURE.md §6, "Security and privacy").

    * Host header: a loopback name only (400 otherwise). A web page elsewhere could point its own
      domain name at 127.0.0.1 ("DNS rebinding") and read the private data (supplier quotes,
      questions, keys status) through the owner's browser; its requests carry its own name.
    * /api requests a browser marks as sent by another site (``Sec-Fetch-Site: cross-site`` or
      ``same-site``), and requests that change something (POST, PUT, PATCH, DELETE) whose
      ``Origin`` is not this computer, are refused (403): a page elsewhere cannot make the owner's
      browser start a collection, load demo data or spend AI credits. The interface's own requests
      are same-origin (also through the Vite dev proxy); tools without a browser send neither header.
    * CORS stays closed: no Access-Control-* header is ever sent.
    * The pages cannot be framed by another site (clickjacking) and send no Referer elsewhere.
    """

    def __init__(self, app, extra_hosts: tuple[str, ...] = ()):
        self.app = app
        self.hosts = LOOPBACK_HOSTS | {h.strip().lower() for h in extra_hosts
                                       if h and h.strip() not in ("0.0.0.0", "::", "*")}

    def refusal(self, scope) -> tuple[int, str] | None:
        headers = Headers(scope=scope)
        if _host_name(headers.get("host", "")) not in self.hosts:
            return 400, "Indirizzo non valido: aprire Paladex da http://127.0.0.1 / Invalid host: open Paladex at http://127.0.0.1"
        method = scope.get("method", "GET") if scope["type"] == "http" else "WEBSOCKET"
        site = headers.get("sec-fetch-site", "").strip().lower()
        if scope.get("path", "").startswith("/api") and site in ("cross-site", "same-site"):
            return 403, "Richiesta da un altro sito rifiutata / Request from another site refused"
        origin = headers.get("origin")
        if method not in SAFE_METHODS and origin is not None and _origin_name(origin) not in self.hosts:
            return 403, "Richiesta da un altro sito rifiutata / Request from another site refused"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            refused = self.refusal(scope)
            if refused is not None:
                status, detail = refused
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
                return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        page = not scope.get("path", "").startswith("/api")     # the interface (archived files keep their own rules)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if page and headers.get("content-type", "").startswith("text/html"):
                    # The pages cannot be shown inside another site's frame (a hidden frame could
                    # make the owner click buttons there), and links send no address to other sites.
                    headers.setdefault("X-Frame-Options", "DENY")
                    headers.append("Content-Security-Policy", "frame-ancestors 'none'")
                    headers.setdefault("Referrer-Policy", "no-referrer")
            await send(message)

        await self.app(scope, receive, send_with_headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


def create_app(start_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="Parodi Group — Honey Intelligence", version="0.1.0",
                  lifespan=lifespan if start_scheduler else None)
    app.add_middleware(LocalOnlyGuard, extra_hosts=(get_settings().host,))
    app.include_router(build_router())

    dist = get_settings().frontend_dist
    if (dist / "index.html").exists():
        if (dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return HTMLResponse(
                "<h1>Paladex API is running</h1><p>The interface has not been built yet. "
                "Run <code>npm run build</code> in <code>frontend/</code> (the start script does this).</p>"
            )
    return app


app = create_app()
