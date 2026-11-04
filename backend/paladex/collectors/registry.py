"""Collector registry.

Each module listed in COLLECTOR_MODULES must define one or more `Collector` subclasses with
a unique `key`. A module that fails to import is reported (not fatal) so one broken source
never takes the whole application down.
"""
from __future__ import annotations

import importlib
import inspect
import logging

from .base import Collector

log = logging.getLogger(__name__)

COLLECTOR_MODULES: list[str] = [
    "paladex.collectors.fx_ecb",          # FX first: needed to normalise prices
    "paladex.collectors.usda",            # USDA AMS National Honey Report (+ NASS, MyMarketNews)
    "paladex.collectors.eu",              # European Commission / Eurostat Comext
    "paladex.collectors.italy",           # Osservatorio Nazionale Miele / Italian price lists
    "paladex.collectors.comtrade",        # UN Comtrade HS 0409
    "paladex.collectors.trade_official",  # national official trade stats: Brazil Comex Stat, US Census
    "paladex.collectors.faostat",         # FAOSTAT production / producer prices
    "paladex.collectors.news_gdelt",      # GDELT DOC 2.0 (multilingual news, commercial use allowed)
    "paladex.collectors.news_feeds",      # RSS / Atom news (Google News feeds are opt-in)
    "paladex.collectors.regulation",      # Federal Register, EUR-Lex... (official notices)
    "paladex.collectors.official_watchers",  # origin-country notices: MAPA (BR), SENASA/Boletín Oficial (AR), DGFT (IN)
    "paladex.collectors.tariffs",
    "paladex.collectors.weather",          # NASA POWER monthly weather anomalies per honey region
    "paladex.collectors.trade_south",      # Argentina INDEC, Uruguay customs/Uruguay XXI (official exports)
    "paladex.collectors.production_official",  # Statistics Canada, Mexico SIAP, Turkey TUIK, Brazil IBGE         # EU TARIC (UK XI mirror) and US HTS duties on honey by origin
]

IMPORT_ERRORS: dict[str, str] = {}
_cache: list[Collector] | None = None


def all_collectors(refresh: bool = False) -> list[Collector]:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    found: dict[str, Collector] = {}
    IMPORT_ERRORS.clear()
    for mod_name in COLLECTOR_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:
            if exc.name == mod_name:
                continue  # module not written yet
            IMPORT_ERRORS[mod_name] = repr(exc)
            log.exception("Collector module %s failed to import", mod_name)
            continue
        except Exception as exc:  # pragma: no cover - defensive
            IMPORT_ERRORS[mod_name] = repr(exc)
            log.exception("Collector module %s failed to import", mod_name)
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Collector) and obj is not Collector and not inspect.isabstract(obj) and obj.__module__ == mod.__name__:
                if obj.key in found:
                    raise RuntimeError(f"Duplicate collector key {obj.key!r}")
                found[obj.key] = obj()
    _cache = sorted(found.values(), key=lambda c: (c.order, c.key))
    return _cache


def get_collector(key: str) -> Collector | None:
    return next((c for c in all_collectors() if c.key == key), None)
