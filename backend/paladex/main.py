"""FastAPI application: JSON API under /api and the built frontend at /."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .api import build_router
from .collectors import base as _collector_base  # noqa: F401 - installs the httpx log filter that redacts API keys in URLs
from .config import get_settings
from .db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


def create_app(start_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="Parodi Group — Honey Intelligence", version="0.1.0",
                  lifespan=lifespan if start_scheduler else None)
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
