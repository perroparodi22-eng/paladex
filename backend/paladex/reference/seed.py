"""Idempotent seeding of reference tables (countries, sources, default alert rules)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import Reliability, SourceKind
from ..models import Country, Source
from .countries import countries

# Sources that are not tied to an automatic collector.
MANUAL_SOURCES = [
    {
        "key": "manual_quotes",
        "name": "Offerte fornitori (inserite a mano)",
        "name_en": "Supplier quotes (entered by hand)",
        "publisher": "Parodi Group",
        "kind": SourceKind.MANUAL,
        "reliability": Reliability.USER,
        "category": "quotes",
    },
    {
        "key": "demo",
        "name": "Dati dimostrativi (NON reali)",
        "name_en": "Demonstration data (NOT real)",
        "publisher": "Paladex",
        "kind": SourceKind.MANUAL,
        "reliability": Reliability.DEMO,
        "category": "demo",
        "terms_note": "Demonstration data generated for testing the interface. Never real market data.",
    },
]


def seed_reference_data(session: Session) -> None:
    existing = {c.iso3: c for c in session.scalars(select(Country))}
    for c in countries():
        row = existing.get(c["iso3"])
        if row is None:
            session.add(Country(**c))
        else:
            for k, v in c.items():
                setattr(row, k, v)

    from ..collectors.registry import all_collectors

    specs = [c.source_spec() for c in all_collectors()] + MANUAL_SOURCES
    have = {s.key: s for s in session.scalars(select(Source))}
    for spec in specs:
        spec = {k: (v.value if hasattr(v, "value") else v) for k, v in spec.items()}
        row = have.get(spec["key"])
        if row is None:
            session.add(Source(**spec))
        else:
            # keep user's enabled flag; refresh descriptive metadata
            for k, v in spec.items():
                if k != "enabled":
                    setattr(row, k, v)
    _retire(session, have)
    session.flush()


# News feeds that were registered for a few hours on 10 Nov 2026 and then replaced by better ones
# (Colombia, Paraguay, Venezuela). A computer started in between has their rows on the Fonti page
# with nothing behind them: a row that never ran and holds no article is removed, any other is
# switched off (its articles and run history stay).
RETIRED_SOURCES = ("news_co_elcampesino", "news_co_agronegocios", "news_py_valoragro", "news_py_ip",
                   "news_ve_elnacional_economia")


def _retire(session: Session, have: dict[str, Source]) -> None:
    from ..models import CollectionRun, NewsArticle, RawDocument

    for key in RETIRED_SOURCES:
        row = have.get(key)
        if row is None:
            continue
        used = any(session.scalars(select(m.id).where(m.source_id == row.id).limit(1)).first() is not None
                   for m in (NewsArticle, CollectionRun, RawDocument))
        if used:
            row.enabled = False
        else:
            session.delete(row)
