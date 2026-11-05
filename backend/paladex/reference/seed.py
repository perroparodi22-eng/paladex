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
        "publisher": "Parodi Group",
        "kind": SourceKind.MANUAL,
        "reliability": Reliability.USER,
        "category": "quotes",
    },
    {
        "key": "demo",
        "name": "Dati dimostrativi (NON reali)",
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
    session.flush()
