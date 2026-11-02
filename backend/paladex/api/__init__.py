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
