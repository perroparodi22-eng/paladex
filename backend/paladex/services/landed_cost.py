"""Landed cost of a supplier quote ("costo sbarcato") and its market reference context (Milestone 7a).

Inputs: the quote as the user typed it (price per kg or per lb in any currency, Incoterm, freight,
insurance, itemised extra costs, an optional duty % of their own), the destination (ITA = EU customs,
USA), the official duty layers stored in ``tariff_measures`` and the ECB reference rates in ``fx_rates``.

Rules (docs/DEVELOPING.md):

* **Nothing is assumed.** A cost the Incoterm leaves to the buyer that the user did not enter is
  "non indicato": the total is computed without it and the result is flagged incomplete
  (``kind="missing"``). Insurance has no default rate.
* **Only what the Incoterm does not include is added** (``INCOTERM_RULES``): e.g. CFR adds insurance
  but not freight, DDP adds no duty.
* **The duty comes from the current official measures** for the origin and the destination:

  - EU (destination ITA): a preference, a tariff quota's in-quota rate or the third-country (MFN)
    duty, ad valorem on the customs value (CIF at the EU border). When a tariff quota exists, the
    in-quota AND the out-of-quota alternatives are both returned: nothing is chosen silently. An
    exhausted / blocked quota (or a zero balance) makes the in-quota alternative unavailable.
  - US: the general column-1 rate (1.9 ¢/kg, specific) or a special-programme rate of the origin.
    Anti-dumping orders (``services.tariffs.US_AD_CASES``) and Chapter 99 headings flagged
    ``needs_review`` become explicit warnings with official links; their rates are never applied.
  - A duty % typed by the user replaces the automatic duty and is labelled as theirs.
  - Layers are not summed into a "total duty" unless they are unambiguous stacking layers
    (a surcharge / anti-dumping measure with a published rate and no review flag).

* **FX** uses the ECB reference rate of the quote's date received (or today, ``fx_mode="today"``),
  at most 14 days back (``services.fx.rate_per_eur``). Without a rate the amount has no conversion.
* **Provenance on every line**: the quote (date received), the ECB rate and its date, the tariff
  measure with the date it was last confirmed and its official links.

Amounts are per kg in EUR and USD; per 300 kg drum and per 20 t container are multiples, with the
drum and container weights returned as explicit assumptions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import PriceObservation, Source, SupplierQuote, TariffMeasure
from .fx import rate_per_eur
from .tariffs import (
    AD_CASE_BY_ORIGIN,
    ALL_ORIGINS,
    ERGA_OMNES,
    TARIFF_ORIGINS,
    MeasureType,
    hts_url,
    taric_url,
)

LB_KG = 0.45359237              # exact (international avoirdupois pound)
DRUM_KG = 300.0                 # Parodi standard drum
CONTAINER_KG = 20_000.0         # Parodi standard container load (net honey)
INCOTERMS = ("EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP")
DESTINATIONS = {"ITA": "EU", "USA": "US"}
COST_KINDS = ("origin", "port", "broker", "inland", "bank", "other")
COST_BASES = ("per_container", "per_kg", "total", "pct_goods")
FREIGHT_BASES = ("per_container", "per_kg", "total")
FX_MODES = ("received", "today")

EU_LINE_MANUKA = "0409000010"
EU_LINE_OTHER = "0409000090"
EU_HEADING = "0409000000"


@dataclass(frozen=True)
class IncotermRule:
    """What the quoted price already includes."""

    origin_costs: bool      # export clearance and delivery to the carrier / port of loading
    freight: bool           # main carriage to the destination
    insurance: bool         # cargo insurance (CIF: minimum cover)
    duty: bool              # import duty at destination


INCOTERM_RULES: dict[str, IncotermRule] = {
    "EXW": IncotermRule(False, False, False, False),
    "FCA": IncotermRule(True, False, False, False),
    "FOB": IncotermRule(True, False, False, False),
    "CFR": IncotermRule(True, True, False, False),
    "CIF": IncotermRule(True, True, True, False),
    "DAP": IncotermRule(True, True, True, False),
    "DDP": IncotermRule(True, True, True, True),
}
_NOTHING_INCLUDED = IncotermRule(False, False, False, False)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class CostItem:
    kind: str
    amount: float
    basis: str
    currency: str | None = None
    note: str | None = None


@dataclass
class QuoteInput:
    origin_iso3: str
    variety: str
    price: float                       # as quoted, per `price_unit`
    currency: str
    date_received: date
    price_unit: str = "kg"
    incoterm: str | None = None
    incoterm_place: str | None = None
    quantity_kg: float | None = None
    shipping_cost: float | None = None
    shipping_cost_currency: str | None = None
    shipping_cost_basis: str | None = None
    insurance_pct: float | None = None
    duty_pct: float | None = None
    other_costs: float | None = None   # legacy single field: a total for the quoted quantity
    other_costs_currency: str | None = None
    cost_items: list[CostItem] = field(default_factory=list)
    destination: str = "ITA"
    is_demo: bool = False

    @property
    def price_per_kg(self) -> float:
        return self.price / LB_KG if self.price_unit == "lb" else self.price


def _items(raw) -> list[CostItem]:
    out = []
    for it in raw or []:
        if isinstance(it, CostItem):
            out.append(it)
        elif isinstance(it, dict) and it.get("amount") is not None:
            out.append(CostItem(kind=it.get("kind") or "other", amount=float(it["amount"]),
                                basis=it.get("basis") or "total", currency=it.get("currency"), note=it.get("note")))
    return out


def input_from_model(m: SupplierQuote) -> QuoteInput:
    unit = m.price_unit or "kg"
    price = m.price_quoted if (unit == "lb" and m.price_quoted is not None) else (
        m.price_per_kg * LB_KG if unit == "lb" else m.price_per_kg)
    return QuoteInput(
        origin_iso3=m.origin_iso3, variety=m.variety, price=price, price_unit=unit, currency=m.currency,
        date_received=m.date_received, incoterm=m.incoterm, incoterm_place=m.incoterm_place, quantity_kg=m.quantity_kg,
        shipping_cost=m.shipping_cost, shipping_cost_currency=m.shipping_cost_currency,
        shipping_cost_basis=m.shipping_cost_basis, insurance_pct=m.insurance_pct, duty_pct=m.duty_pct,
        other_costs=m.other_costs, other_costs_currency=m.other_costs_currency, cost_items=_items(m.cost_items),
        destination=m.destination or "ITA", is_demo=bool(m.is_demo),
    )


def input_from_dict(d: dict) -> QuoteInput:
    keys = QuoteInput.__dataclass_fields__.keys()
    vals = {k: d[k] for k in keys if k in d and d[k] is not None}
    vals["cost_items"] = _items(d.get("cost_items"))
    return QuoteInput(**vals)


# ---------------------------------------------------------------------------
# Amounts and FX
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Amt:
    """One amount in EUR and USD (None: no conversion available)."""

    eur: float | None
    usd: float | None

    def __add__(self, other: Amt) -> Amt:
        return Amt(_add(self.eur, other.eur), _add(self.usd, other.usd))

    def scale(self, k: float) -> Amt:
        return Amt(None if self.eur is None else self.eur * k, None if self.usd is None else self.usd * k)

    def as_dict(self) -> dict:
        return {"eur": _r(self.eur), "usd": _r(self.usd)}


ZERO = Amt(0.0, 0.0)


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _r(v: float | None, n: int = 6) -> float | None:
    return None if v is None else round(v, n)


class Fx:
    """ECB reference rates on one date, with the rates actually used recorded for display."""

    def __init__(self, session: Session, on: date):
        self.session = session
        self.on = on
        self._cache: dict[str, tuple[float, date] | None] = {}

    def rate(self, ccy: str) -> tuple[float, date] | None:
        ccy = (ccy or "").upper()
        if ccy == "EUR":
            return 1.0, self.on
        if ccy not in self._cache:
            self._cache[ccy] = rate_per_eur(self.session, ccy, self.on)
        return self._cache[ccy]

    def amt(self, amount: float, ccy: str) -> Amt:
        ccy = (ccy or "").upper()
        a, u = self.rate(ccy), self.rate("USD")
        eur = amount if ccy == "EUR" else (amount / a[0] if a else None)
        usd = amount if ccy == "USD" else (eur * u[0] if eur is not None and u else None)
        return Amt(eur, usd)

    def line_fx(self, ccy: str | None) -> dict | None:
        """The rate used for an amount in `ccy` (shown next to the line)."""
        ccy = (ccy or "").upper()
        if not ccy or ccy == "EUR":
            return None
        r = self.rate(ccy)
        if r is None:
            return {"currency": ccy, "missing": True}
        return {"currency": ccy, "per_eur": r[0], "rate_date": r[1].isoformat(), "missing": False}

    def summary(self, needed: set[str]) -> dict:
        needed = {c.upper() for c in needed if c} | {"USD"}
        rates, missing = [], []
        for c in sorted(needed - {"EUR"}):
            r = self.rate(c)
            if r is None:
                missing.append(c)
            else:
                rates.append({"currency": c, "per_eur": r[0], "rate_date": r[1].isoformat()})
        return {"date": self.on.isoformat(), "rates": rates, "missing": missing}


# ---------------------------------------------------------------------------
# Tariff context
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Data shared by many calculations in one request (the list computes every quote)."""

    session: Session
    measures_real: list[TariffMeasure]
    measures_demo: list[TariffMeasure]
    sources: dict[int, Source]
    _fx: dict[date, Fx] = field(default_factory=dict)

    def fx(self, on: date) -> Fx:
        if on not in self._fx:
            self._fx[on] = Fx(self.session, on)
        return self._fx[on]

    def measures(self, is_demo: bool) -> list[TariffMeasure]:
        # A real quote is priced with real duty rows only; a demo quote may also see demo rows.
        return self.measures_real + self.measures_demo if is_demo else self.measures_real

    def source_key(self, m: TariffMeasure) -> str | None:
        s = self.sources.get(m.source_id)
        return s.key if s else None


def load_context(session: Session, include_demo: bool = False) -> Context:
    T = TariffMeasure
    rows = session.scalars(select(T).where(T.is_current.is_(True))).all()
    real = [m for m in rows if not m.is_demo]
    demo = [m for m in rows if m.is_demo] if include_demo else []
    return Context(session=session, measures_real=real, measures_demo=demo,
                   sources={s.id: s for s in session.scalars(select(Source))})


def _serialize(ctx: Context, m: TariffMeasure) -> dict:
    from ..api.regulations import serialize_measure  # same shape as /regulations/duties rows

    return serialize_measure(m, ctx.sources.get(m.source_id))


def _valid_on(m: TariffMeasure, on: date) -> bool:
    return (m.valid_from is None or m.valid_from <= on) and (m.valid_to is None or m.valid_to >= on)


def _needs_review(m: TariffMeasure) -> bool:
    return bool((m.extra or {}).get("needs_review"))


def _excluded(m: TariffMeasure) -> list[str]:
    return list((m.extra or {}).get("excluded_origins") or [])


def _eu_line(variety: str) -> str:
    return EU_LINE_MANUKA if variety == "manuka" else EU_LINE_OTHER


def _per_kg_specific(m: TariffMeasure) -> float | None:
    if m.specific_amount is None:
        return None
    unit = (m.specific_unit or "kg").lower().replace(" ", "")
    div = {"kg": 1.0, "100kg": 100.0, "t": 1000.0, "1000kg": 1000.0}.get(unit)
    return None if div is None else m.specific_amount / div


def _is_free(m: TariffMeasure) -> bool:
    return bool(m.duty_text) and m.duty_text.strip().lower() in ("free", "esente")


def _duty_of(m: TariffMeasure, customs_value: Amt, fx: Fx) -> Amt | None:
    """Duty per kg of one measure: ad valorem on the customs value plus any specific amount.
    None when the published expression could not be reduced to numbers."""
    if m.ad_valorem_pct is None and m.specific_amount is None:
        return ZERO if _is_free(m) else None
    out = ZERO
    if m.ad_valorem_pct is not None:
        out = out + customs_value.scale(m.ad_valorem_pct / 100)
    spec = _per_kg_specific(m)
    if m.specific_amount is not None:
        if spec is None:
            return None
        out = out + fx.amt(spec, m.specific_currency or ("USD" if m.jurisdiction == "US" else "EUR"))
    return out


def _rate(m: TariffMeasure | None, pct: float | None = None) -> dict:
    if m is None:
        return {"ad_valorem_pct": pct, "specific_amount": None, "specific_unit": None, "specific_currency": None,
                "duty_text": None}
    return {"ad_valorem_pct": m.ad_valorem_pct, "specific_amount": m.specific_amount, "specific_unit": m.specific_unit,
            "specific_currency": m.specific_currency, "duty_text": m.duty_text}


# ---------------------------------------------------------------------------
# Duty resolution
# ---------------------------------------------------------------------------


@dataclass
class DutyPlan:
    """The duty alternatives for one quote (before amounts), with what the UI must show."""

    jurisdiction: str
    alternatives: list[dict]           # {"kind", "measure", "role", "available", "reason", "notes"}
    stack: list[TariffMeasure]         # unambiguous extra layers applied in every alternative
    review: list[TariffMeasure]        # published but not applied (scope / conditions to verify)
    not_applied: list[TariffMeasure]   # other layers kept for reference
    has_data: bool
    origin_covered: bool
    general_us: TariffMeasure | None = None


def _eu_plan(ctx: Context, q: QuoteInput, on: date) -> DutyPlan:
    line = _eu_line(q.variety)
    rel = [m for m in ctx.measures(q.is_demo) if m.jurisdiction == "EU" and m.hs_code in (EU_HEADING, line)
           and _valid_on(m, on)]
    has_data = any(m.jurisdiction == "EU" for m in ctx.measures(q.is_demo))
    own = [m for m in rel if m.origin_iso3 == q.origin_iso3]
    gen = [m for m in rel if m.origin_iso3 == ERGA_OMNES and q.origin_iso3 not in _excluded(m)]
    review = [m for m in own + gen if _needs_review(m)]
    own_ok = [m for m in own if not _needs_review(m)]
    gen_ok = [m for m in gen if not _needs_review(m)]

    def of(rows, t):
        return [m for m in rows if m.measure_type == t]

    mfn = (of(own_ok, MeasureType.MFN) or of(gen_ok, MeasureType.MFN))[:1]
    prefs = of(own_ok, MeasureType.PREFERENCE)
    trq_in = of(own_ok, MeasureType.TRQ_IN)
    trq_out = of(own_ok, MeasureType.TRQ_OUT)
    stack = [m for m in own_ok + gen_ok if m.measure_type in (MeasureType.SURCHARGE, MeasureType.ANTIDUMPING)]
    not_applied = [m for m in own_ok + gen_ok if m.measure_type == MeasureType.OTHER]

    alts: list[dict] = []
    for m in trq_in:
        status = (m.quota_status or "").lower()
        reason = None
        if status in ("exhausted", "blocked"):
            reason = status
        elif m.quota_balance_kg is not None and m.quota_balance_kg <= 0:
            reason = "exhausted"
        notes = []
        if status == "critical":
            notes.append({"code": "quota_critical"})
        if reason is None and q.quantity_kg and m.quota_balance_kg is not None and q.quantity_kg > m.quota_balance_kg:
            notes.append({"code": "quota_balance_below_quantity", "params": {"balance_kg": m.quota_balance_kg}})
        alts.append({"kind": "trq_in", "measure": m, "role": "in_quota", "available": reason is None, "reason": reason,
                     "notes": notes})
    fallback = prefs or trq_out or mfn
    role = "out_of_quota" if trq_in else "applicable"
    for m in fallback:
        notes = []
        if m.measure_type == MeasureType.PREFERENCE and mfn:
            notes.append({"code": "proof_of_origin", "params": {"mfn": _rate(mfn[0])}})
        alts.append({"kind": m.measure_type, "measure": m, "role": role, "available": True, "reason": None,
                     "notes": notes})
    return DutyPlan("EU", alts, stack, review, not_applied, has_data, q.origin_iso3 in TARIFF_ORIGINS)


def _us_plan(ctx: Context, q: QuoteInput, on: date) -> DutyPlan:
    rel = [m for m in ctx.measures(q.is_demo) if m.jurisdiction == "US" and _valid_on(m, on)
           and m.origin_iso3 in (q.origin_iso3, ALL_ORIGINS)]
    has_data = any(m.jurisdiction == "US" for m in ctx.measures(q.is_demo))
    review = [m for m in rel if _needs_review(m)]
    ok = [m for m in rel if not _needs_review(m)]
    own = [m for m in ok if m.origin_iso3 == q.origin_iso3]
    general = next((m for m in ok if m.origin_iso3 == ALL_ORIGINS and m.measure_type == MeasureType.MFN), None)
    prefs = [m for m in own if m.measure_type == MeasureType.PREFERENCE]
    own_mfn = [m for m in own if m.measure_type == MeasureType.MFN]
    stack = [m for m in own if m.measure_type in (MeasureType.SURCHARGE, MeasureType.ANTIDUMPING)]
    not_applied = [m for m in ok if m.measure_type == MeasureType.OTHER]
    fallback = prefs or own_mfn or ([general] if general else [])
    alts = []
    for m in fallback:
        notes = []
        if m.measure_type == MeasureType.PREFERENCE:
            codes = (m.extra or {}).get("program_codes") or []
            notes.append({"code": "program_certification", "params": {"codes": codes, "general": _rate(general)}})
        alts.append({"kind": m.measure_type, "measure": m, "role": "applicable", "available": True, "reason": None,
                     "notes": notes})
    return DutyPlan("US", alts, stack, review, not_applied, has_data, True, general_us=general)


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


def _per_kg(amount: float, basis: str, qty: float | None, container_kg: float) -> tuple[float | None, dict]:
    """Amount per kg (in the amount's own currency) for a cost given per container / per kg / in total."""
    if basis == "per_kg":
        return amount, {"basis": basis}
    if basis == "per_container":
        if qty:
            n = max(1, math.ceil(qty / container_kg - 1e-9))
            return amount * n / qty, {"basis": basis, "containers": n, "quantity_kg": qty}
        return amount / container_kg, {"basis": basis, "containers": 1, "container_kg": container_kg}
    if basis == "total":
        if qty:
            return amount / qty, {"basis": basis, "quantity_kg": qty}
        return None, {"basis": basis}
    return None, {"basis": basis}


def _eu_members() -> frozenset[str]:
    from ..api.prices import EU27_MEMBERS

    return EU27_MEMBERS


def calculate(session: Session, q: QuoteInput, *, fx_mode: str = "received", today: date | None = None,
              container_kg: float = CONTAINER_KG, drum_kg: float = DRUM_KG, ctx: Context | None = None) -> dict:
    """Landed cost of one quote. See the module docstring for the rules."""
    today = today or date.today()
    ctx = ctx or load_context(session, include_demo=q.is_demo)
    fx_on = today if fx_mode == "today" else q.date_received
    fx = ctx.fx(fx_on)
    destination = q.destination if q.destination in DESTINATIONS else "ITA"
    jurisdiction = DESTINATIONS[destination]
    incoterm = (q.incoterm or "").upper() or None
    rule = INCOTERM_RULES.get(incoterm) if incoterm else None
    eff = rule or _NOTHING_INCLUDED
    qty = q.quantity_kg if q.quantity_kg and q.quantity_kg > 0 else None
    flags: list[dict] = []
    currencies = {q.currency}

    def flag(code: str, kind: str = "missing", **params) -> None:
        flags.append({"code": code, "kind": kind, "params": params})

    quote_src = {"kind": "quote", "date": q.date_received.isoformat()}
    if rule is None:
        flag("incoterm_missing" if not incoterm else "incoterm_unknown", incoterm=incoterm)

    # --- goods -----------------------------------------------------------------------------
    price_kg = q.price_per_kg
    goods = fx.amt(price_kg, q.currency)
    lines: list[dict] = [{
        "key": "goods", "status": "ok", "per_kg": goods.as_dict(),
        "input": {"amount": q.price, "currency": q.currency, "unit": q.price_unit, "per_kg_original": _r(price_kg),
                  "incoterm": incoterm, "place": q.incoterm_place},
        "source": quote_src, "fx": fx.line_fx(q.currency),
    }]

    # --- itemised costs ---------------------------------------------------------------------
    def cost_line(it: CostItem, idx: int | None) -> tuple[dict, Amt | None]:
        key = it.kind if it.kind in COST_KINDS else "other"
        if it.basis == "pct_goods":
            amt = goods.scale(it.amount / 100)
            return ({"key": key, "index": idx, "status": "ok", "per_kg": amt.as_dict(),
                     "input": {"amount": it.amount, "basis": "pct_goods", "note": it.note},
                     "source": quote_src, "fx": None}, amt)
        ccy = (it.currency or q.currency).upper()
        currencies.add(ccy)
        v, detail = _per_kg(it.amount, it.basis, qty, container_kg)
        if v is None:
            flag("cost_no_quantity", kind=key)
            return ({"key": key, "index": idx, "status": "not_computable", "per_kg": None,
                     "input": {"amount": it.amount, "currency": ccy, "note": it.note, **detail},
                     "source": quote_src, "fx": fx.line_fx(ccy)}, None)
        amt = fx.amt(v, ccy)
        return ({"key": key, "index": idx, "status": "ok", "per_kg": amt.as_dict(),
                 "input": {"amount": it.amount, "currency": ccy, "note": it.note, "per_kg_original": _r(v), **detail},
                 "source": quote_src, "fx": fx.line_fx(ccy)}, amt)

    items = list(enumerate(q.cost_items))
    origin_items = [(i, it) for i, it in items if it.kind == "origin"]
    dest_items = [(i, it) for i, it in items if it.kind != "origin"]
    if q.other_costs is not None and q.other_costs > 0:
        dest_items.append((None, CostItem(kind="other", amount=q.other_costs, basis="total",
                                          currency=q.other_costs_currency or q.currency, note=None)))

    origin_total = ZERO
    for i, it in origin_items:
        ln, amt = cost_line(it, i)
        lines.append(ln)
        if amt is not None:
            origin_total = origin_total + amt
    if rule is not None and not rule.origin_costs and not origin_items:
        flag("origin_costs_missing", incoterm=incoterm)   # EXW: export clearance / transport to the port

    # --- freight -----------------------------------------------------------------------------
    freight = ZERO
    if eff.freight:
        fl = {"key": "freight", "status": "included", "per_kg": ZERO.as_dict(), "input": None,
              "source": quote_src, "fx": None}
        if q.shipping_cost:
            flag("freight_ignored", kind="info", incoterm=incoterm)
            fl["input"] = {"amount": q.shipping_cost, "currency": q.shipping_cost_currency,
                           "basis": q.shipping_cost_basis}
    elif q.shipping_cost is None:
        flag("freight_missing")
        fl = {"key": "freight", "status": "missing", "per_kg": None, "input": None, "source": None, "fx": None}
    else:
        ccy = (q.shipping_cost_currency or q.currency).upper()
        currencies.add(ccy)
        v, detail = _per_kg(q.shipping_cost, q.shipping_cost_basis or "per_container", qty, container_kg)
        if v is None:
            flag("freight_no_quantity")
            fl = {"key": "freight", "status": "not_computable", "per_kg": None,
                  "input": {"amount": q.shipping_cost, "currency": ccy, **detail}, "source": quote_src,
                  "fx": fx.line_fx(ccy)}
        else:
            freight = fx.amt(v, ccy)
            fl = {"key": "freight", "status": "ok", "per_kg": freight.as_dict(),
                  "input": {"amount": q.shipping_cost, "currency": ccy, "per_kg_original": _r(v), **detail},
                  "source": quote_src, "fx": fx.line_fx(ccy)}
    lines.append(fl)

    # --- insurance (% of the CIF value: premium = r x (goods + freight) / (1 - r)) ---------------
    insurance = ZERO
    if eff.insurance:
        lines.append({"key": "insurance", "status": "included", "per_kg": ZERO.as_dict(), "input": None,
                      "source": quote_src, "fx": None})
    elif q.insurance_pct is None:
        flag("insurance_missing")
        lines.append({"key": "insurance", "status": "missing", "per_kg": None, "input": None, "source": None,
                      "fx": None})
    else:
        r = q.insurance_pct / 100
        base = goods + origin_total + freight
        insurance = base.scale(r / (1 - r)) if r < 1 else Amt(None, None)
        lines.append({"key": "insurance", "status": "ok", "per_kg": insurance.as_dict(),
                      "input": {"pct": q.insurance_pct, "of": "cif"}, "source": quote_src, "fx": None})

    # --- customs value -------------------------------------------------------------------------
    if jurisdiction == "EU":
        if incoterm in ("DAP", "DDP"):
            customs = goods + origin_total
            basis = "price"
            if incoterm == "DAP":
                flag("dap_customs_value", kind="info")
        else:
            customs = goods + origin_total + freight + insurance
            basis = "cif"
    else:
        customs = goods + origin_total
        basis = "fob"
        if eff.freight:
            flag("us_value_includes_freight", kind="info", incoterm=incoterm)
    lines.append({"key": "customs_value", "status": "subtotal", "per_kg": customs.as_dict(),
                  "input": {"basis": basis, "jurisdiction": jurisdiction}, "source": None, "fx": None})

    # --- destination costs --------------------------------------------------------------------
    after: list[dict] = []
    dest_total = ZERO
    for i, it in dest_items:
        ln, amt = cost_line(it, i)
        after.append(ln)
        if amt is not None:
            dest_total = dest_total + amt

    # --- duty ------------------------------------------------------------------------------------
    plan = _eu_plan(ctx, q, today) if jurisdiction == "EU" else _us_plan(ctx, q, today)
    domestic = (jurisdiction == "US" and q.origin_iso3 == "USA") or \
        (jurisdiction == "EU" and q.origin_iso3 in _eu_members())
    stack_amt = ZERO
    stack_ok = True
    for m in plan.stack:
        a = _duty_of(m, customs, fx)
        if a is None:
            stack_ok = False
        else:
            stack_amt = stack_amt + a
        if m.specific_currency:
            currencies.add(m.specific_currency)

    def scenario(kind: str, role: str, duty: Amt | None, *, measure: TariffMeasure | None = None, available=True,
                 reason=None, notes=None, pct=None) -> dict:
        return {"key": f"{kind}:{measure.id}" if measure is not None else kind, "kind": kind, "role": role,
                "available": available, "unavailable_reason": reason,
                "rate": _rate(measure, pct), "measure": _serialize(ctx, measure) if measure is not None else None,
                "stack": [_serialize(ctx, m) for m in plan.stack] if measure is not None else [],
                "duty": duty.as_dict() if duty is not None else None, "notes": notes or []}

    scenarios: list[dict] = []
    if eff.duty:
        scenarios.append(scenario("included", "applicable", ZERO))
        if q.duty_pct is not None:
            flag("duty_override_ignored", kind="info", incoterm=incoterm)
    elif domestic:
        scenarios.append(scenario("domestic", "applicable", ZERO))
    elif q.duty_pct is not None:
        scenarios.append(scenario("override", "applicable", customs.scale(q.duty_pct / 100), pct=q.duty_pct))
        flag("duty_override", kind="info", pct=q.duty_pct)
    elif not plan.alternatives:
        scenarios.append(scenario("unknown", "applicable", None))
        flag("duty_unavailable", jurisdiction=jurisdiction, has_data=plan.has_data)
    else:
        for alt in plan.alternatives:
            m = alt["measure"]
            if m.specific_currency:
                currencies.add(m.specific_currency)
            d = _duty_of(m, customs, fx)
            if d is not None and plan.stack:
                d = d + stack_amt if stack_ok else None
            if d is None:
                flag("duty_not_computable", measure_code=m.measure_code, duty_text=m.duty_text)
            scenarios.append(scenario(alt["kind"], alt["role"], d, measure=m, available=alt["available"],
                                      reason=alt["reason"], notes=alt["notes"]))
        trq = [s for s in scenarios if s["kind"] == MeasureType.TRQ_IN]
        if trq and any(s["available"] for s in trq):
            flag("quota_alternatives", kind="info")
        for s in trq:
            if not s["available"]:
                flag("quota_unavailable", kind="warning", reason=s["unavailable_reason"],
                     order=(s["measure"]["quota"] or {}).get("order_number"))
            for n in s["notes"]:
                if n["code"] in ("quota_critical", "quota_balance_below_quantity"):
                    flag(n["code"], kind="warning", order=(s["measure"]["quota"] or {}).get("order_number"),
                         **(n.get("params") or {}))

    # --- warnings that are never turned into numbers ----------------------------------------------
    ad_case = None
    if jurisdiction == "US" and not domestic:
        case = AD_CASE_BY_ORIGIN.get(q.origin_iso3)
        if case is not None:
            ad_case = {"origin_iso3": case.origin_iso3, "case_number": case.case_number, "product": case.product,
                       "fr_search_url": case.fr_search_url}
            flag("us_antidumping", kind="warning", case_number=case.case_number)
        if plan.review:
            flag("us_additional_duty_review", kind="warning", count=len(plan.review))
        flag("us_fees_not_included", kind="info")
    if jurisdiction == "EU" and not domestic:
        if plan.review:
            flag("eu_review_measures", kind="info", count=len(plan.review))
        if not plan.origin_covered:
            flag("origin_not_covered", kind="warning")
        flag("vat_excluded", kind="info")

    # --- FX completeness ---------------------------------------------------------------------------
    fx_info = fx.summary(currencies)
    if fx_info["missing"]:
        flag("fx_missing", currencies=fx_info["missing"], date=fx_on.isoformat())
    ecb = next((s for s in ctx.sources.values() if s.key == "ecb_fx"), None)

    # --- totals --------------------------------------------------------------------------------
    base_total = goods + origin_total + freight + insurance + dest_total
    for s in scenarios:
        d = s["duty"]
        if d is None:
            s["total"] = None
            continue
        tot = base_total + Amt(d["eur"], d["usd"])
        s["total"] = {
            "per_kg": tot.as_dict(), "per_drum": tot.scale(drum_kg).as_dict(),
            "per_container": tot.scale(container_kg).as_dict(),
            "quantity": tot.scale(qty).as_dict() if qty else None,
        }

    avail = [s for s in scenarios if s["available"] and s["total"]]

    def bound(ccy: str, fn):
        vals = [s["total"]["per_kg"][ccy] for s in avail if s["total"]["per_kg"][ccy] is not None]
        return fn(vals) if vals else None

    duty_info = _duty_info(ctx, plan, q, today, jurisdiction, ad_case)
    return {
        "destination": destination,
        "jurisdiction": jurisdiction,
        "incoterm": incoterm,
        "incoterm_rule": rule.__dict__ if rule else None,
        "calc_date": today.isoformat(),
        "fx": {"mode": fx_mode, **fx_info, "source": _brief(ecb),
               "source_url": ecb.homepage if ecb else None},
        "assumptions": {"drum_kg": drum_kg, "container_kg": container_kg, "quantity_kg": qty,
                        "containers": max(1, math.ceil(qty / container_kg - 1e-9)) if qty else None},
        "lines": lines,
        "after_duty": after,
        "scenarios": scenarios,
        "headline": {
            "eur_per_kg_min": bound("eur", min), "eur_per_kg_max": bound("eur", max),
            "usd_per_kg_min": bound("usd", min), "usd_per_kg_max": bound("usd", max),
            "alternatives": len(avail) > 1,
            "complete": not any(f["kind"] == "missing" for f in flags),
            "missing": [f["code"] for f in flags if f["kind"] == "missing"],
            "warnings": [f["code"] for f in flags if f["kind"] == "warning"],
        },
        "flags": flags,
        "duty": duty_info,
    }


def _brief(s: Source | None) -> dict | None:
    if s is None:
        return None
    return {"key": s.key, "name": s.name, "publisher": s.publisher, "reliability": s.reliability, "homepage": s.homepage}


def _duty_info(ctx: Context, plan: DutyPlan, q: QuoteInput, today: date, jurisdiction: str, ad_case: dict | None) -> dict:
    used = [a["measure"] for a in plan.alternatives] + plan.stack
    dates = [m.as_of for m in used if m.as_of]
    src_key = "eu_tariff_xi" if jurisdiction == "EU" else "us_hts"
    src = next((s for s in ctx.sources.values() if s.key == src_key), None)
    out: dict[str, Any] = {
        "jurisdiction": jurisdiction,
        "on": today.isoformat(),
        "has_data": plan.has_data,
        "as_of": min(dates).isoformat() if dates else None,
        "as_of_latest": max(dates).isoformat() if dates else None,
        "applied": [_serialize(ctx, m) for m in used],
        "review": [_serialize(ctx, m) for m in plan.review],
        "not_applied": [_serialize(ctx, m) for m in plan.not_applied],
        "origin_covered": plan.origin_covered,
        "source": _brief(src),
        "links": ({"taric": taric_url(q.origin_iso3, today, _eu_line(q.variety))} if jurisdiction == "EU"
                  else {"hts": hts_url()}),
        "ad_case": ad_case,
        "us": None,
    }
    g = plan.general_us
    if jurisdiction == "US" and g is not None:
        ex = g.extra or {}
        out["us"] = {"special_text": ex.get("special_text"), "column2_text": ex.get("column2_text"),
                     "column2_note": ex.get("column2_note")}
    return out


def headline_value(landed: dict, ccy: str = "eur", basis: str = "conservative") -> float | None:
    """One comparable figure: the highest available alternative ("conservative": e.g. out of quota)
    or the lowest ("best")."""
    h = landed["headline"]
    return h[f"{ccy}_per_kg_max"] if basis == "conservative" else h[f"{ccy}_per_kg_min"]


# ---------------------------------------------------------------------------
# Market reference context (separate price types, never mixed)
# ---------------------------------------------------------------------------

REFERENCE_SOURCES = {
    "eu_import": ("eurostat_comext",),
    "us_importer": ("usda_honey_report",),
    "it_wholesale": ("cciaa_cuneo_miele", "onm_informamiele"),
}


def _obs(r: PriceObservation, src: Source | None, today: date, **extra) -> dict:
    from ..api.common import freshness

    return {
        "id": r.id, "source": _brief(src), "price_type": r.price_type, "origin_iso3": r.origin_iso3,
        "market_iso3": r.market_iso3, "market_location": r.market_location, "variety": r.variety,
        "variety_raw": r.variety_raw, "color_grade": r.color_grade, "organic": bool(r.organic), "terms": r.terms,
        "price_low": r.price_low, "price_high": r.price_high, "price_value": r.price_value, "currency": r.currency,
        "unit": r.unit, "price_per_kg": r.price_per_kg, "eur_per_kg": r.eur_per_kg, "usd_per_kg": r.usd_per_kg,
        "fx_basis": r.fx_basis, "fx_date": r.fx_date.isoformat() if r.fx_date else None, "volume_kg": r.volume_kg,
        "period_label": r.period_label, "period_start": r.period_start.isoformat(),
        "period_end": r.period_end.isoformat(), "frequency": r.frequency,
        "published_at": r.published_at.isoformat() if r.published_at else None,
        "collected_at": r.collected_at.isoformat() if r.collected_at else None, "source_url": r.source_url,
        "data_status": r.data_status, "reliability": r.reliability, "is_demo": r.is_demo,
        "age_days": (today - r.period_end).days, "freshness": freshness(src, today) if src else None, **extra,
    }


def _latest(session: Session, conds: list, freq: str | None = None) -> list[PriceObservation]:
    P = PriceObservation
    base = [P.is_current.is_(True), P.is_demo.is_(False), *conds]
    if freq:
        base.append(P.frequency == freq)
    newest = session.scalar(select(func.max(P.period_start)).where(*base))
    if newest is None:
        return []
    return list(session.scalars(select(P).where(*base, P.period_start == newest)
                                .order_by(P.market_iso3, P.color_grade, P.id)))


def market_reference(session: Session, origin_iso3: str, variety: str, today: date | None = None) -> dict:
    """Latest published reference prices for a quote's origin and variety, one block per price type:

    * ``eu_import``: Eurostat Comext import unit value (CIF, EUR/kg, all honey CN 0409) from the
      origin into Italy and into the EU27 (customs statistic, not a quote);
    * ``us_importer``: USDA National Honey Report prices paid to US importers for the origin (USD/lb as
      published: duty paid, ex-dock), the quote's variety when published, otherwise the origin's rows
      with ``variety_match=False``;
    * ``it_wholesale``: Italian-origin honey of the same variety on Italian price lists (CCIAA Cuneo
      monthly, Osservatorio Nazionale Miele annual; VAT included, drums).

    Each row keeps its source, period and publication date. Nothing is averaged across blocks."""
    today = today or date.today()
    P = PriceObservation
    srcs = {s.key: s for s in session.scalars(select(Source))}
    by_id = {s.id: s for s in srcs.values()}

    def ids(block: str) -> list[int]:
        return [srcs[k].id for k in REFERENCE_SOURCES[block] if k in srcs]

    eu_rows: list[dict] = []
    if origin_iso3 not in _eu_members():
        for market in ("ITA", "EU27"):
            for r in _latest(session, [P.source_id.in_(ids("eu_import")), P.price_type == "import_unit_value",
                                       P.origin_iso3 == origin_iso3, P.market_iso3 == market], freq="M"):
                eu_rows.append(_obs(r, by_id.get(r.source_id), today))

    us_rows: list[dict] = []
    match = True
    us_conds = [P.source_id.in_(ids("us_importer")), P.price_type == "wholesale_bulk", P.origin_iso3 == origin_iso3,
                P.market_iso3 == "USA"]
    rows = _latest(session, [*us_conds, P.variety == variety], freq="M")
    if not rows:
        match = False
        rows = _latest(session, us_conds, freq="M")
    us_rows = [_obs(r, by_id.get(r.source_id), today, variety_match=match and r.variety == variety) for r in rows]

    it_rows: list[dict] = []
    for key in REFERENCE_SOURCES["it_wholesale"]:
        if key not in srcs:
            continue
        conds = [P.source_id == srcs[key].id, P.price_type == "wholesale_bulk", P.market_iso3 == "ITA",
                 P.origin_iso3 == "ITA", P.variety == variety]
        rows = _latest(session, conds, freq="M") or _latest(session, conds, freq="A")
        it_rows += [_obs(r, by_id.get(r.source_id), today) for r in rows]

    return {
        "origin_iso3": origin_iso3,
        "variety": variety,
        "blocks": [
            {"key": "eu_import", "price_type": "import_unit_value", "rows": eu_rows,
             "not_applicable": origin_iso3 in _eu_members()},
            {"key": "us_importer", "price_type": "wholesale_bulk", "rows": us_rows, "variety_match": match,
             "not_applicable": origin_iso3 == "USA"},
            {"key": "it_wholesale", "price_type": "wholesale_bulk", "rows": it_rows, "not_applicable": False},
        ],
    }
