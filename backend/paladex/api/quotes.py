"""Supplier quotes and landed cost ("Offerte fornitori", /api/quotes/...).

Quotes are the owner's private business data:

* they never leave this computer (no endpoint sends them anywhere; the LLM never sees them);
* the app never deletes them: there is no DELETE route, a quote is archived instead (and can be
  restored); demo quotes are removed only by the demo purge, like every other demo row;
* every edit keeps ``created_at`` and moves ``updated_at``.

Routes (static paths first, so they are not read as an id):

* ``GET  /quotes``                 list with status/origin/variety/supplier/text filters, counts, facets,
                                   and the landed cost of each quote (ECB rate of its date received)
* ``GET  /quotes/meta``            currencies with ECB rates, Incoterms, cost kinds, drum/container weights
* ``GET  /quotes/export``          CSV of the filtered list (Italian Excel: ';' and decimal comma)
* ``GET  /quotes/compare?ids=``    2-6 quotes ranked by landed EUR/kg, with differences to the cheapest
* ``POST /quotes/calculate``       landed cost of an unsaved quote (form preview, what-if in the drawer)
* ``POST /quotes``                 create; ``GET/PUT /quotes/{id}``; ``POST /quotes/{id}/archive|unarchive|duplicate``

Status: ``archived`` (set by the user) > ``expired`` (valid until < today) > ``expiring`` (valid until
within 7 days) > ``active`` (later, or no expiry given).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enums import DataStatus, Reliability, Variety
from ..models import Country, FxRate, SupplierQuote
from ..reference.countries import is_known_iso3
from ..reference.varieties import LABELS as VARIETY_LABELS
from ..services import landed_cost as lc
from .common import demo_clause, get_setting, iso

router = APIRouter(prefix="/quotes", tags=["quotes"])

STATUSES = ("active", "expiring", "expired", "archived")
EXPIRING_DAYS = 7
MAX_ITEMS = 1000
FX_RECENT_DAYS = 30
VARIETIES = {v.value for v in Variety}
_CCY = re.compile(r"^[A-Z]{3}$")


def today() -> date:
    """Calculation date (patched in tests)."""
    return date.today()


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


def _ccy(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    v = str(v).strip().upper()
    if not _CCY.match(v):
        raise ValueError("currency must be a 3-letter ISO code")
    return v


def _text(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class CostItemIn(BaseModel):
    kind: Literal["origin", "port", "broker", "inland", "bank", "other"]
    amount: float = Field(ge=0, le=1e9)
    basis: Literal["per_container", "per_kg", "total", "pct_goods"]
    currency: str | None = None
    note: str | None = Field(None, max_length=200)

    _c = field_validator("currency")(lambda cls, v: _ccy(v))
    _n = field_validator("note")(lambda cls, v: _text(v))

    @model_validator(mode="after")
    def _check(self):
        if self.basis == "pct_goods":
            if self.amount > 100:
                raise ValueError("a percentage cost must be between 0 and 100")
            self.currency = None
        elif self.currency is None:
            raise ValueError("currency is required for an amount")
        return self


class QuoteCalcIn(BaseModel):
    """What the landed-cost calculation needs (the supplier name is optional here)."""

    supplier_name: str | None = Field(None, max_length=200)
    origin_iso3: str
    variety: str
    variety_note: str | None = Field(None, max_length=200)
    price: float = Field(gt=0, le=1000)
    price_unit: Literal["kg", "lb"] = "kg"
    currency: str
    quantity_kg: float | None = Field(None, gt=0, le=10_000_000)
    packaging: str | None = Field(None, max_length=120)
    incoterm: Literal["EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"] | None = None
    incoterm_place: str | None = Field(None, max_length=120)
    shipping_cost: float | None = Field(None, ge=0, le=1e9)
    shipping_cost_currency: str | None = None
    shipping_cost_basis: Literal["per_container", "per_kg", "total"] | None = None
    insurance_pct: float | None = Field(None, ge=0, le=20)
    duty_pct: float | None = Field(None, ge=0, le=200)
    other_costs: float | None = Field(None, ge=0, le=1e9)
    other_costs_currency: str | None = None
    cost_items: list[CostItemIn] = Field(default_factory=list, max_length=12)
    destination: Literal["ITA", "USA"] = "ITA"
    date_received: date
    valid_until: date | None = None
    notes: str | None = Field(None, max_length=4000)

    _ccys = field_validator("currency", "shipping_cost_currency", "other_costs_currency")(lambda cls, v: _ccy(v))
    _texts = field_validator("supplier_name", "variety_note", "packaging", "incoterm_place", "notes")(
        lambda cls, v: _text(v))

    @field_validator("origin_iso3")
    @classmethod
    def _origin(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not is_known_iso3(v):
            raise ValueError("unknown country code")
        return v

    @field_validator("variety")
    @classmethod
    def _variety(cls, v: str) -> str:
        if v not in VARIETIES:
            raise ValueError("unknown variety")
        return v

    @model_validator(mode="after")
    def _check(self):
        if self.currency is None:
            raise ValueError("currency is required")
        if self.date_received > today():
            raise ValueError("date_received cannot be in the future")
        if self.valid_until is not None and self.valid_until < self.date_received:
            raise ValueError("valid_until cannot be before date_received")
        if self.shipping_cost is None:
            self.shipping_cost_currency = self.shipping_cost_basis = None
        else:
            if self.shipping_cost_currency is None:
                raise ValueError("shipping_cost_currency is required with a shipping cost")
            if self.shipping_cost_basis is None:
                raise ValueError("shipping_cost_basis is required with a shipping cost")
        if self.other_costs is None:
            self.other_costs_currency = None
        elif self.other_costs_currency is None:
            raise ValueError("other_costs_currency is required with other costs")
        return self


class QuoteIn(QuoteCalcIn):
    supplier_name: str = Field(min_length=1, max_length=200)

    @field_validator("supplier_name")
    @classmethod
    def _supplier(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("supplier name is required")
        return v


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def quote_status(m: SupplierQuote, on: date) -> str:
    if m.archived:
        return "archived"
    if m.valid_until is not None:
        if m.valid_until < on:
            return "expired"
        if (m.valid_until - on).days <= EXPIRING_DAYS:
            return "expiring"
    return "active"


def serialize_quote(m: SupplierQuote, on: date) -> dict:
    unit = m.price_unit or "kg"
    price = m.price_quoted if m.price_quoted is not None else (m.price_per_kg * lc.LB_KG if unit == "lb" else m.price_per_kg)
    return {
        "id": m.id,
        "supplier_name": m.supplier_name,
        "origin_iso3": m.origin_iso3,
        "variety": m.variety,
        "variety_note": m.variety_note,
        "price": round(price, 6),
        "price_unit": unit,
        "price_per_kg": round(m.price_per_kg, 6),
        "currency": m.currency,
        "quantity_kg": m.quantity_kg,
        "packaging": m.packaging,
        "incoterm": m.incoterm,
        "incoterm_place": m.incoterm_place,
        "shipping_cost": m.shipping_cost,
        "shipping_cost_currency": m.shipping_cost_currency,
        "shipping_cost_basis": m.shipping_cost_basis,
        "insurance_pct": m.insurance_pct,
        "duty_pct": m.duty_pct,
        "other_costs": m.other_costs,
        "other_costs_currency": m.other_costs_currency,
        "cost_items": m.cost_items or [],
        "destination": m.destination or "ITA",
        "date_received": iso(m.date_received),
        "valid_until": iso(m.valid_until),
        "days_to_expiry": (m.valid_until - on).days if m.valid_until else None,
        "notes": m.notes,
        "archived": bool(m.archived),
        "status": quote_status(m, on),
        "created_at": iso(m.created_at),
        "updated_at": iso(m.updated_at),
        "is_demo": bool(m.is_demo),
        "data_status": DataStatus.DEMO.value if m.is_demo else DataStatus.USER_ENTERED.value,
        "reliability": Reliability.DEMO.value if m.is_demo else Reliability.USER.value,
    }


def compact_landed(landed: dict) -> dict:
    """What the list and the comparison need from a landed-cost result."""
    return {
        "destination": landed["destination"],
        "headline": landed["headline"],
        "fx": {"date": landed["fx"]["date"], "rates": landed["fx"]["rates"], "missing": landed["fx"]["missing"]},
        "flags": [{"code": f["code"], "kind": f["kind"]} for f in landed["flags"]],
        "scenarios": [{
            "key": s["key"], "kind": s["kind"], "role": s["role"], "available": s["available"],
            "unavailable_reason": s["unavailable_reason"], "rate": s["rate"],
            "quota": (s["measure"] or {}).get("quota"),
            "total_per_kg": s["total"]["per_kg"] if s["total"] else None,
        } for s in landed["scenarios"]],
    }


def _apply(m: SupplierQuote, body: QuoteIn) -> None:
    m.supplier_name = body.supplier_name
    m.origin_iso3 = body.origin_iso3
    m.variety = body.variety
    m.variety_note = body.variety_note
    m.price_unit = body.price_unit
    m.price_quoted = body.price
    m.price_per_kg = body.price / lc.LB_KG if body.price_unit == "lb" else body.price
    m.currency = body.currency
    m.quantity_kg = body.quantity_kg
    m.packaging = body.packaging
    m.incoterm = body.incoterm
    m.incoterm_place = body.incoterm_place
    m.shipping_cost = body.shipping_cost
    m.shipping_cost_currency = body.shipping_cost_currency
    m.shipping_cost_basis = body.shipping_cost_basis
    m.insurance_pct = body.insurance_pct
    m.duty_pct = body.duty_pct
    m.other_costs = body.other_costs
    m.other_costs_currency = body.other_costs_currency
    m.cost_items = [i.model_dump() for i in body.cost_items] or None
    m.destination = body.destination
    m.date_received = body.date_received
    m.valid_until = body.valid_until
    m.notes = body.notes


def _get(db: Session, quote_id: int) -> SupplierQuote:
    m = db.scalars(select(SupplierQuote).where(SupplierQuote.id == quote_id, demo_clause(SupplierQuote, db))).first()
    if m is None:
        raise HTTPException(404, "quote not found")
    return m


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _split(v: str | None, upper: bool = False) -> list[str]:
    items = [x.strip() for x in (v or "").split(",") if x.strip()]
    return [x.upper() for x in items] if upper else items


def _filtered(db: Session, *, status: str | None, origin: str | None, variety: str | None, supplier: str | None,
              q: str | None, on: date) -> tuple[list[SupplierQuote], list[SupplierQuote]]:
    """(rows matching every filter, rows matching every filter except status)."""
    Q = SupplierQuote
    stmt = select(Q).where(demo_clause(Q, db))
    origins = _split(origin, upper=True)
    if origins:
        stmt = stmt.where(Q.origin_iso3.in_(origins))
    varieties = _split(variety)
    if varieties:
        stmt = stmt.where(Q.variety.in_(varieties))
    if supplier and supplier.strip():
        stmt = stmt.where(func.lower(Q.supplier_name) == supplier.strip().lower())
    if q and q.strip():
        pat = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(or_(*(c.ilike(pat, escape="\\") for c in (
            Q.supplier_name, Q.notes, Q.variety_note, Q.packaging, Q.incoterm_place))))
    rows = list(db.scalars(stmt.order_by(Q.date_received.desc(), Q.id.desc()).limit(MAX_ITEMS)))
    wanted = _split(status)
    if not wanted:
        wanted = ["active", "expiring", "expired"]
    elif "all" in wanted:
        wanted = list(STATUSES)
    bad = [s for s in wanted if s not in STATUSES]
    if bad:
        raise HTTPException(422, f"unknown status {bad[0]!r}")
    return [m for m in rows if quote_status(m, on) in wanted], rows


def _fx_mode(fx: str) -> str:
    if fx not in lc.FX_MODES:
        raise HTTPException(422, "fx must be 'received' or 'today'")
    return fx


def _container(kg: float | None) -> float:
    if kg is None:
        return lc.CONTAINER_KG
    if not (1000 <= kg <= 40_000):
        raise HTTPException(422, "container_kg must be between 1000 and 40000")
    return kg


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
def list_quotes(
    status: str | None = Query(None, description="active, expiring, expired, archived (comma-separated) or all; "
                                                  "default: every quote not archived"),
    origin: str | None = Query(None, description="ISO3 (comma-separated)"),
    variety: str | None = Query(None, description="variety key (comma-separated)"),
    supplier: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=200, description="text in supplier, notes, packaging, place"),
    db: Session = Depends(get_db),
):
    on = today()
    rows, unfiltered = _filtered(db, status=status, origin=origin, variety=variety, supplier=supplier, q=q, on=on)
    ctx = lc.load_context(db, include_demo=any(m.is_demo for m in rows))
    items = []
    for m in rows:
        landed = lc.calculate(db, lc.input_from_model(m), today=on, ctx=ctx)
        items.append({**serialize_quote(m, on), "landed": compact_landed(landed)})
    counts = {s: 0 for s in STATUSES}
    for m in unfiltered:
        counts[quote_status(m, on)] += 1
    every = list(db.scalars(select(SupplierQuote).where(demo_clause(SupplierQuote, db))))

    def facet(attr: str) -> list[dict]:
        c: dict[str, int] = {}
        for m in every:
            k = getattr(m, attr)
            c[k] = c.get(k, 0) + 1
        return [{"key": k, "count": n} for k, n in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]).lower()))]

    return {
        "items": items,
        "total": len(items),
        "counts": counts,
        "total_all": len(every),
        "facets": {"origins": facet("origin_iso3"), "varieties": facet("variety"), "suppliers": facet("supplier_name")},
        "today": on.isoformat(),
        "expiring_days": EXPIRING_DAYS,
    }


@router.get("/meta")
def quotes_meta(db: Session = Depends(get_db)):
    newest = db.scalar(select(func.max(FxRate.rate_date)))
    ccys: list[str] = []
    if newest is not None:
        ccys = list(db.scalars(select(FxRate.currency).where(FxRate.rate_date >= newest - timedelta(days=FX_RECENT_DAYS))
                               .distinct()))
    ordered = ["EUR", "USD"] + sorted(c for c in ccys if c not in ("EUR", "USD"))
    if "USD" not in ccys:
        ordered = ["EUR"] + [c for c in ordered if c not in ("EUR", "USD")]
    return {
        "currencies": ordered,
        "fx_newest": iso(newest),
        "incoterms": list(lc.INCOTERMS),
        "incoterm_rules": {k: v.__dict__ for k, v in lc.INCOTERM_RULES.items()},
        "cost_kinds": list(lc.COST_KINDS),
        "cost_bases": list(lc.COST_BASES),
        "freight_bases": list(lc.FREIGHT_BASES),
        "destinations": list(lc.DESTINATIONS),
        "drum_kg": lc.DRUM_KG,
        "container_kg": lc.CONTAINER_KG,
        "lb_kg": lc.LB_KG,
        "expiring_days": EXPIRING_DAYS,
        "today": today().isoformat(),
    }


# --- CSV ---------------------------------------------------------------------------------------

def _csv_safe(v: str) -> str:
    """Neutralise spreadsheet formulas in text typed by the user."""
    return "'" + v if v and v[0] in "=+-@\t\r" else v


_STATUS_LABELS = {
    "active": ("Attiva", "Active"), "expiring": ("In scadenza", "Expiring"),
    "expired": ("Scaduta", "Expired"), "archived": ("Archiviata", "Archived"),
}
_KIND_LABELS = {
    "origin": ("Costi in origine", "Origin costs"), "port": ("Porto / terminal", "Port / terminal"),
    "broker": ("Spedizioniere / doganalista", "Forwarder / customs broker"),
    "inland": ("Trasporto interno", "Inland transport"), "bank": ("Banca", "Bank"), "other": ("Altro", "Other"),
}
_BASIS_LABELS = {
    "per_container": ("per container", "per container"), "per_kg": ("per kg", "per kg"),
    "total": ("totale", "total"), "pct_goods": ("% della merce", "% of goods"),
}
_SCENARIO_LABELS = {
    "trq_in": ("Contingente {order}", "Tariff quota {order}"),
    "mfn": ("Dazio pieno (paesi terzi)", "Full duty (third countries)"),
    "preference": ("Preferenziale", "Preferential"),
    "trq_out": ("Fuori contingente", "Out of quota"),
    "override": ("Dazio inserito da te", "Duty entered by you"),
    "included": ("Incluso nel prezzo (DDP)", "Included in the price (DDP)"),
    "domestic": ("Nessun dazio (stesso mercato doganale)", "No duty (same customs area)"),
    "unknown": ("Dazio non disponibile", "Duty not available"),
    "surcharge": ("Dazio aggiuntivo", "Additional duty"),
    "antidumping": ("Antidumping", "Anti-dumping"),
}

CSV_COLUMNS = [
    ("id", "N.", "No."), ("supplier_name", "Fornitore", "Supplier"), ("origin", "Origine", "Origin"),
    ("variety", "Varietà", "Variety"), ("variety_note", "Dettaglio varietà", "Variety detail"),
    ("price", "Prezzo offerto", "Quoted price"), ("currency", "Valuta", "Currency"),
    ("price_unit", "Unità prezzo", "Price unit"), ("price_per_kg", "Prezzo per kg (valuta offerta)", "Price per kg (quote currency)"),
    ("incoterm", "Incoterm", "Incoterm"), ("incoterm_place", "Luogo Incoterm", "Incoterm place"),
    ("quantity_kg", "Quantità (kg)", "Quantity (kg)"), ("packaging", "Imballaggio", "Packaging"),
    ("shipping_cost", "Nolo", "Freight"), ("shipping_cost_currency", "Valuta nolo", "Freight currency"),
    ("shipping_cost_basis", "Base nolo", "Freight basis"), ("insurance_pct", "Assicurazione %", "Insurance %"),
    ("duty_pct", "Dazio % inserito", "Duty % entered"), ("costs", "Altri costi", "Other costs"),
    ("destination", "Destinazione", "Destination"), ("date_received", "Ricevuta il", "Received on"),
    ("valid_until", "Valida fino al", "Valid until"), ("status", "Stato", "Status"),
    ("eur_min", "Costo sbarcato EUR/kg (min)", "Landed cost EUR/kg (min)"),
    ("eur_max", "Costo sbarcato EUR/kg (max)", "Landed cost EUR/kg (max)"),
    ("usd_min", "Costo sbarcato USD/kg (min)", "Landed cost USD/kg (min)"),
    ("usd_max", "Costo sbarcato USD/kg (max)", "Landed cost USD/kg (max)"),
    ("duty", "Dazio considerato", "Duty considered"), ("complete", "Calcolo completo", "Calculation complete"),
    ("missing", "Elementi non indicati", "Items not given"), ("fx", "Cambio BCE usato", "ECB rate used"),
    ("notes", "Note", "Notes"), ("is_demo", "Dato dimostrativo", "Demo data"),
    ("created_at", "Creata il", "Created on"), ("updated_at", "Modificata il", "Last edited"),
]
_NUMERIC = {"price", "price_per_kg", "quantity_kg", "shipping_cost", "insurance_pct", "duty_pct",
            "eur_min", "eur_max", "usd_min", "usd_max"}
_MISSING_LABELS = {
    "incoterm_missing": ("Incoterm", "Incoterm"), "incoterm_unknown": ("Incoterm", "Incoterm"),
    "freight_missing": ("nolo", "freight"), "freight_no_quantity": ("quantità per il nolo", "quantity for freight"),
    "insurance_missing": ("assicurazione", "insurance"), "origin_costs_missing": ("costi in origine", "origin costs"),
    "fx_missing": ("cambio BCE", "ECB rate"), "duty_unavailable": ("dazio", "duty"),
    "duty_not_computable": ("dazio", "duty"), "cost_no_quantity": ("quantità per altri costi", "quantity for other costs"),
}


def _num(v: float | None, it: bool) -> str:
    if v is None:
        return ""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if it else s


def _pct_txt(v: float | None, it: bool) -> str:
    return "" if v is None else _num(round(v, 4), it) + " %"


def _scenario_text(s: dict, it: bool) -> str:
    i = 0 if it else 1
    label = _SCENARIO_LABELS.get(s["kind"], (s["kind"], s["kind"]))[i]
    label = label.format(order=(s.get("quota") or {}).get("order_number") or "")
    rate = s["rate"]
    parts = []
    if rate.get("ad_valorem_pct") is not None:
        parts.append(_pct_txt(rate["ad_valorem_pct"], it))
    if rate.get("specific_amount") is not None:
        parts.append(f"{_num(rate['specific_amount'], it)} {rate.get('specific_currency') or ''}/{rate.get('specific_unit') or ''}")
    if not parts and rate.get("duty_text"):
        parts.append(rate["duty_text"])
    txt = f"{label}: {' + '.join(parts)}" if parts else label
    if not s["available"]:
        txt += " (non disponibile)" if it else " (not available)"
    return txt


def _quotes_csv(items: list[tuple[SupplierQuote, dict]], countries: dict[str, Country], lang: str, on: date) -> str:
    it = lang == "it"
    i = 0 if it else 1
    sep = ";" if it else ","
    yes, no = ("Sì", "No") if it else ("Yes", "No")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
    w.writerow([c[1] if it else c[2] for c in CSV_COLUMNS])
    for m, landed in items:
        ser = serialize_quote(m, on)
        c = countries.get(m.origin_iso3)
        costs = []
        for ci in m.cost_items or []:
            kind = _KIND_LABELS.get(ci.get("kind"), ("Altro", "Other"))[i]
            basis = _BASIS_LABELS.get(ci.get("basis"), (ci.get("basis"), ci.get("basis")))[i]
            amount = _num(ci.get("amount"), it)
            costs.append(f"{kind}: {amount}{' %' if ci.get('basis') == 'pct_goods' else ' ' + (ci.get('currency') or '')} {basis}".strip())
        if m.other_costs:
            costs.append(f"{_KIND_LABELS['other'][i]}: {_num(m.other_costs, it)} {m.other_costs_currency or ''} "
                         f"{_BASIS_LABELS['total'][i]}")
        h = landed["headline"]
        missing = []
        for code in h["missing"]:
            lbl = _MISSING_LABELS.get(code, (code, code))[i]
            if lbl not in missing:
                missing.append(lbl)
        rates = landed["fx"]["rates"]
        fx = ", ".join(f"1 EUR = {_num(r['per_eur'], it)} {r['currency']} ({r['rate_date']})" for r in rates)
        rec = {
            **ser,
            "origin": (c.name_it if it else c.name_en) if c else m.origin_iso3,
            "variety": VARIETY_LABELS.get(m.variety, {}).get(lang, m.variety),
            "price_unit": "lb" if ser["price_unit"] == "lb" else "kg",
            "shipping_cost_basis": _BASIS_LABELS.get(m.shipping_cost_basis or "", ("", ""))[i],
            "costs": " | ".join(costs),
            "destination": ("Italia (UE)" if it else "Italy (EU)") if ser["destination"] == "ITA" else ("USA" if it else "USA"),
            "status": _STATUS_LABELS[ser["status"]][i],
            "eur_min": h["eur_per_kg_min"], "eur_max": h["eur_per_kg_max"],
            "usd_min": h["usd_per_kg_min"], "usd_max": h["usd_per_kg_max"],
            "duty": " | ".join(_scenario_text(s, it) for s in compact_landed(landed)["scenarios"]),
            "complete": yes if h["complete"] else no,
            "missing": ", ".join(missing),
            "fx": fx,
            "is_demo": ("SÌ — NON REALE" if it else "YES — NOT REAL") if m.is_demo else no,
            "created_at": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "",
            "updated_at": m.updated_at.strftime("%Y-%m-%d %H:%M") if m.updated_at else "",
        }
        line = []
        for key, _, _ in CSV_COLUMNS:
            v = rec.get(key)
            if key in _NUMERIC:
                line.append(_num(round(v, 4) if isinstance(v, float) and key.startswith(("eur", "usd")) else v, it))
            elif v is None:
                line.append("")
            else:
                line.append(_csv_safe(str(v)))
        w.writerow(line)
    return "﻿" + buf.getvalue()


@router.get("/export")
def export_quotes(
    status: str | None = Query(None),
    origin: str | None = Query(None),
    variety: str | None = Query(None),
    supplier: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=200),
    lang: str | None = Query(None, description="it | en"),
    db: Session = Depends(get_db),
):
    on = today()
    lang = lang if lang in ("it", "en") else get_setting(db, "language", "it")
    rows, _ = _filtered(db, status=status, origin=origin, variety=variety, supplier=supplier, q=q, on=on)
    ctx = lc.load_context(db, include_demo=any(m.is_demo for m in rows))
    items = [(m, lc.calculate(db, lc.input_from_model(m), today=on, ctx=ctx)) for m in rows]
    countries = {c.iso3: c for c in db.scalars(select(Country))}
    body = _quotes_csv(items, countries, lang or "it", on)
    stem = "offerte-fornitori" if lang == "it" else "supplier-quotes"
    name = f"paladex-{stem}-{datetime.now():%Y%m%d}.csv"
    return Response(content=body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- comparison -----------------------------------------------------------------------------------


@router.get("/compare")
def compare_quotes(
    ids: str = Query(..., description="2 to 6 quote ids, comma-separated"),
    basis: Literal["conservative", "best"] = Query("conservative", description=(
        "conservative: the highest available alternative of each quote (e.g. out of quota); best: the lowest")),
    fx: str = Query("received"),
    container_kg: float | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        wanted = list(dict.fromkeys(int(x) for x in _split(ids)))
    except ValueError:
        raise HTTPException(422, "ids must be integers") from None
    if not 2 <= len(wanted) <= 6:
        raise HTTPException(422, "compare between 2 and 6 quotes")
    fx = _fx_mode(fx)
    ckg = _container(container_kg)
    on = today()
    rows = [_get(db, i) for i in wanted]
    ctx = lc.load_context(db, include_demo=any(m.is_demo for m in rows))
    items = []
    for m in rows:
        landed = lc.calculate(db, lc.input_from_model(m), fx_mode=fx, today=on, ctx=ctx, container_kg=ckg)
        v_eur = lc.headline_value(landed, "eur", basis)
        v_usd = lc.headline_value(landed, "usd", basis)
        chosen = next((s for s in landed["scenarios"] if s["available"] and s["total"]
                       and s["total"]["per_kg"]["eur"] is not None and v_eur is not None
                       and abs(s["total"]["per_kg"]["eur"] - v_eur) < 1e-9), None)
        items.append({"quote": serialize_quote(m, on), "landed": compact_landed(landed),
                      "value_eur_per_kg": v_eur, "value_usd_per_kg": v_usd,
                      "scenario": {"kind": chosen["kind"], "rate": chosen["rate"],
                                   "quota": (chosen["measure"] or {}).get("quota")} if chosen else None})
    ranked = sorted(items, key=lambda x: (x["value_eur_per_kg"] is None, x["value_eur_per_kg"] or 0, x["quote"]["id"]))
    best = next((x for x in ranked if x["value_eur_per_kg"] is not None), None)
    for n, x in enumerate(ranked, 1):
        x["rank"] = n if x["value_eur_per_kg"] is not None else None
        if best is None or x["value_eur_per_kg"] is None:
            x["diff_eur_per_kg"] = x["diff_pct"] = x["diff_eur_per_container"] = x["diff_usd_per_kg"] = None
            continue
        d = x["value_eur_per_kg"] - best["value_eur_per_kg"]
        x["diff_eur_per_kg"] = round(d, 6)
        x["diff_pct"] = round(d / best["value_eur_per_kg"] * 100, 4) if best["value_eur_per_kg"] else None
        x["diff_eur_per_container"] = round(d * ckg, 2)
        x["diff_usd_per_kg"] = (round(x["value_usd_per_kg"] - best["value_usd_per_kg"], 6)
                                if x["value_usd_per_kg"] is not None and best["value_usd_per_kg"] is not None else None)
    return {
        "basis": basis, "fx_mode": fx, "container_kg": ckg, "drum_kg": lc.DRUM_KG,
        "items": ranked,
        "best_id": best["quote"]["id"] if best else None,
        "mixed_destinations": len({x["quote"]["destination"] for x in items}) > 1,
        "mixed_demo": len({x["quote"]["is_demo"] for x in items}) > 1,
        "incomplete": [x["quote"]["id"] for x in items if not x["landed"]["headline"]["complete"]],
    }


# --- calculation and CRUD -------------------------------------------------------------------------


def _enrich_ad_case(db: Session, landed: dict, origin: str) -> dict:
    if landed["duty"].get("ad_case"):
        from .regulations import _ad_documents, ad_case_block

        block = ad_case_block(origin, _ad_documents(db))
        if block is not None:
            landed["duty"]["ad_case"] = {**landed["duty"]["ad_case"], **block}
    return landed


@router.post("/calculate")
def calculate_quote(body: QuoteCalcIn, fx: str = Query("received"), container_kg: float | None = Query(None),
                    db: Session = Depends(get_db)):
    """Landed cost of an unsaved quote (the form preview and the what-if assumptions)."""
    q = lc.input_from_dict(body.model_dump())
    landed = lc.calculate(db, q, fx_mode=_fx_mode(fx), today=today(), container_kg=_container(container_kg))
    return _enrich_ad_case(db, landed, q.origin_iso3)


@router.post("", status_code=201)
def create_quote(body: QuoteIn, db: Session = Depends(get_db)):
    m = SupplierQuote(is_demo=False, archived=False)
    _apply(m, body)
    db.add(m)
    db.commit()
    db.refresh(m)
    return serialize_quote(m, today())


@router.get("/{quote_id}")
def get_quote(quote_id: int, fx: str = Query("received"), container_kg: float | None = Query(None),
              db: Session = Depends(get_db)):
    m = _get(db, quote_id)
    on = today()
    landed = lc.calculate(db, lc.input_from_model(m), fx_mode=_fx_mode(fx), today=on,
                          container_kg=_container(container_kg))
    return {
        "quote": serialize_quote(m, on),
        "landed": _enrich_ad_case(db, landed, m.origin_iso3),
        "market": lc.market_reference(db, m.origin_iso3, m.variety, today=on),
    }


@router.put("/{quote_id}")
def update_quote(quote_id: int, body: QuoteIn, db: Session = Depends(get_db)):
    m = _get(db, quote_id)
    _apply(m, body)
    db.commit()
    db.refresh(m)
    return serialize_quote(m, today())


def _set_archived(db: Session, quote_id: int, value: bool) -> dict:
    m = _get(db, quote_id)
    m.archived = value
    db.commit()
    db.refresh(m)
    return serialize_quote(m, today())


@router.post("/{quote_id}/archive")
def archive_quote(quote_id: int, db: Session = Depends(get_db)):
    return _set_archived(db, quote_id, True)


@router.post("/{quote_id}/unarchive")
def unarchive_quote(quote_id: int, db: Session = Depends(get_db)):
    return _set_archived(db, quote_id, False)


@router.post("/{quote_id}/duplicate", status_code=201)
def duplicate_quote(quote_id: int, db: Session = Depends(get_db)):
    """A copy to edit (e.g. a revised offer from the same supplier). It keeps every field, is never
    archived, and stays demo if the original was demo (demo data never becomes real)."""
    src = _get(db, quote_id)
    skip = {"id", "created_at", "updated_at", "archived"}
    copy = SupplierQuote(**{c.key: getattr(src, c.key) for c in SupplierQuote.__table__.columns if c.key not in skip})
    copy.archived = False
    copy.cost_items = [dict(i) for i in (src.cost_items or [])] or None
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return serialize_quote(copy, today())
