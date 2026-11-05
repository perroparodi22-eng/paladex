"""API router assembly. Section routers are optional so a half-built section never
prevents the app from starting."""
from __future__ import annotations

import importlib
import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

SECTION_MODULES = [
    "paladex.api.meta",
    "paladex.api.overview",
    "paladex.api.prices",
    "paladex.api.news",
    "paladex.api.trade",
    "paladex.api.countries",
    "paladex.api.reports",
    "paladex.api.quality",
    "paladex.api.search",
    "paladex.api.regulations",
    "paladex.api.quotes",        # Milestone 7: supplier quotes + landed cost
    "paladex.api.alerts",        # Milestone 7: alert rules and events
    "paladex.api.archive",       # Milestone 7: historical comparisons, revision history
    "paladex.api.assistant",     # Milestone 6: AI assistant + daily briefing
    "paladex.api.harvest",       # Milestone 5: production, weather anomalies
]


def build_router() -> APIRouter:
    api = APIRouter(prefix="/api")
    for name in SECTION_MODULES:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            raise
        api.include_router(mod.router)
    return api
