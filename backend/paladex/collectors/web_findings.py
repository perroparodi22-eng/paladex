"""Other sources (non-official): the newest figures found on the web, each verified by Paladex.

One keyless collector, ``web_findings`` (weekly). Official statistics often stop at 2024; this
collector keeps, per country, the newest 2025/2026 figures published anywhere on the web (official
publications that are not machine-readable, USDA FAS attaché reports, associations, the trade press,
news), clearly apart from the official data (table ``web_findings``, ``models_findings``). They never
feed the map, rankings, totals, comparisons, alerts or the official series.

Where the findings come from:

1. ``reference/web_findings_seed.json``: findings compiled by hand from web research, in the format
   ``{"compiled_on", "method", "findings": [{country_iso3, metric, period_label, period_start,
   period_end, value, unit, value_as_published, status, kind, is_official, publisher, source_url,
   source_title, published_at, language, quote, also_reported_by, notes}], "not_found":
   [{country_iso3, searched, result}]}``. ``not_found`` is shown in a country's empty state.
2. Optionally (off by default), a weekly AI web search for the countries that lack recent figures
   (``services.findings_ai``): the model must return the same format, with exact quotes and URLs.

The rule (``services.web_verify``): a finding is stored ONLY if Paladex itself opens ``source_url``
and finds the quote and the number of ``value_as_published`` in the page text. A finding that fails
is not stored and is listed in the run's warnings with the reason (page unreachable, the site refuses
automated access, quote not found, number not found). Blocks, captchas and logins are never worked
around. An excerpt of the page around the quote is archived (never the whole page).

Re-checks. A stored finding is checked again on its page at most once every ``RECHECK_DAYS`` days. If
the page later fails (gone, blocked, changed), the finding is KEPT, the failed check is noted in its
``verification`` and the run warns; nothing is ever deleted. A changed seed entry becomes a new
revision once verified; a seed entry withdrawn from the seed is retired (``is_current=False``, kept
in history).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..enums import Reliability, SourceKind
from ..models import AppSetting, Country, RawDocument, utcnow
from ..models_findings import (
    OFFICIAL_KINDS,
    FindingKind,
    FindingMetric,
    FindingStatus,
    WebFinding,
    current_finding,
    record_finding,
    retire_findings,
    value_hash,
)
from ..services import web_verify as wv
from .base import CollectContext, Collector, CollectorError, Offline, year_bounds

log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parents[1] / "reference" / "web_findings_seed.json"
RECHECK_DAYS = 30
AI_RESEARCH_DAYS = 27            # a country searched by the AI is not searched again before this
AI_MIN_YEAR = 2025               # the AI is asked for 2025/2026 figures: older periods are refused
MAX_AI_FINDINGS_PER_COUNTRY = 12
CHECKPOINT_EVERY = 10
ACCEPT = "text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8,*/*;q=0.5"
_ANY_STATUS = tuple(range(200, 600))
FOUND_BY_SEED = "seed"
FOUND_BY_AI = "ai_web_search"


def today() -> date:
    """Reference date (indirection so tests can pin it)."""
    return date.today()


# ---------------------------------------------------------------------------
# The seed
# ---------------------------------------------------------------------------

@dataclass
class Seed:
    findings: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
    compiled_on: str | None = None
    method: str | None = None
    error: str | None = None


def load_seed(path: Path | None = None) -> Seed:
    path = path or SEED_PATH
    if not path.exists():
        return Seed(error=f"seed file not found ({path.name}): no findings to verify")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Seed(error=f"seed file {path.name} is not readable JSON ({exc}); nothing changed")
    if not isinstance(data, dict) or not isinstance(data.get("findings", []), list):
        return Seed(error=f"seed file {path.name} has no 'findings' list; nothing changed")
    nf = data.get("not_found") or []
    return Seed(findings=data.get("findings") or [], not_found=nf if isinstance(nf, list) else [],
                compiled_on=str(data.get("compiled_on") or "") or None, method=str(data.get("method") or "") or None)


_seed_cache: dict[str, Any] = {}


def seed_summary(path: Path | None = None) -> Seed:
    """The seed as the API shows it (``not_found``, compiled_on), re-read when the file changes."""
    path = path or SEED_PATH
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return Seed()
    if _seed_cache.get("stamp") != stamp:
        seed = load_seed(path)
        _seed_cache.update(stamp=stamp, seed=seed if not seed.error else Seed())
    return _seed_cache["seed"]


# ---------------------------------------------------------------------------
# One finding: validation and identity
# ---------------------------------------------------------------------------

def _str(v: Any, limit: int) -> str | None:
    if v is None or isinstance(v, (dict, list, bool)):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:limit] if s else None


def _iso_date(v: Any) -> date | None | str:
    """date, None (absent) or 'bad' (present but not an ISO date)."""
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return "bad"


def parse_finding(raw: Any, valid_iso3: set[str], *, iso3: str | None = None,
                  min_year: int | None = None) -> tuple[dict | None, str | None]:
    """The model fields of one finding in the seed format, or (None, why it cannot be stored)."""
    if not isinstance(raw, dict):
        return None, "not an object"
    country = (_str(raw.get("country_iso3"), 3) or "").upper()
    if iso3 and country != iso3:
        return None, f"country {country or '?'} is not the one searched ({iso3})"
    if country not in valid_iso3:
        return None, f"unknown country {country or '?'}"
    metric, status, kind = (_str(raw.get(k), 30) for k in ("metric", "status", "kind"))
    if metric not in {m.value for m in FindingMetric}:
        return None, f"unknown metric {metric!r}"
    if status not in {s.value for s in FindingStatus}:
        return None, f"unknown status {status!r}"
    if kind not in {k.value for k in FindingKind}:
        return None, f"unknown kind {kind!r}"
    is_official = raw.get("is_official")
    if not isinstance(is_official, bool):
        return None, "is_official must be true or false"
    if is_official and kind not in OFFICIAL_KINDS:
        return None, f"a {kind} publisher cannot be marked official"
    label = _str(raw.get("period_label"), 40)
    if not label:
        return None, "no period_label"
    start, end = _iso_date(raw.get("period_start")), _iso_date(raw.get("period_end"))
    if "bad" in (start, end):
        return None, "period_start / period_end are not ISO dates"
    if start is None or end is None:
        if re.fullmatch(r"\d{4}", label):
            start, end = year_bounds(int(label))
        else:
            return None, f"period {label!r} has no period_start / period_end"
    if start > end:
        return None, "period_start is after period_end"
    if min_year and end.year < min_year:
        return None, f"period {label} is older than {min_year}"
    value = raw.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return None, "value must be a number (or null)"
    unit = _str(raw.get("unit"), 40)
    vap = _str(raw.get("value_as_published"), 160)
    if not unit:
        return None, "no unit"
    if not vap or not wv.published_numbers(vap):
        return None, "value_as_published must contain the figure as printed"
    quote = _str(raw.get("quote"), 2000)
    if not quote or len(wv.display_text(quote)) < wv.MIN_QUOTE_CHARS:
        return None, f"the quote is missing or shorter than {wv.MIN_QUOTE_CHARS} characters"
    url = _str(raw.get("source_url"), 1000)
    problem = wv.url_problem(url)
    if problem:
        return None, f"source_url not opened: {problem}"
    publisher = _str(raw.get("publisher"), 300)
    if not publisher:
        return None, "no publisher"
    published = _iso_date(raw.get("published_at"))
    if published == "bad":
        return None, "published_at is not an ISO date"
    also = raw.get("also_reported_by")
    if also is not None and not isinstance(also, list):
        return None, "also_reported_by must be a list"
    return {
        "country_iso3": country, "metric": metric, "period_label": label, "period_start": start, "period_end": end,
        "value": float(value) if value is not None else None, "unit": unit, "value_as_published": vap,
        "status": status, "kind": kind, "is_official": is_official, "publisher": publisher, "source_url": url,
        "source_title": _str(raw.get("source_title"), 500), "published_at": published,
        "language": (_str(raw.get("language"), 8) or "").lower() or None, "quote": quote,
        "also_reported_by": [a for a in also if isinstance(a, (str, dict))][:10] if also else None,
        "notes": _str(raw.get("notes"), 2000),
        # a range as published ("20 mil a 26 mil toneladas"): its bounds, when the seed gives them
        "range": {k: float(raw[k]) for k in ("value_low", "value_high")
                  if isinstance(raw.get(k), (int, float)) and not isinstance(raw.get(k), bool)} or None,
    }, None


def series_key(f: dict) -> str:
    """Identity of a finding: country, metric, period, unit and the page it is on."""
    unit = re.sub(r"\s+", " ", f["unit"].strip().lower())
    page = hashlib.sha1(f["source_url"].encode("utf-8")).hexdigest()[:16]
    return f"{f['country_iso3']}|{f['metric']}|{f['period_label']}|{unit}|{page}"[:400]


def _label(f: dict) -> str:
    return f"{f.get('country_iso3')} {f.get('metric')} {f.get('period_label')} ({f.get('publisher')})"


def _raw_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return "?"
    return " ".join(str(raw.get(k) or "?") for k in ("country_iso3", "metric", "period_label"))


# ---------------------------------------------------------------------------
# Opening pages (polite, cached for the run, failures never fatal)
# ---------------------------------------------------------------------------

class PageChecker:
    def __init__(self, ctx: CollectContext):
        self.ctx = ctx
        self._pages: dict[str, tuple] = {}
        self._online_confirmed = False

    def _open(self, url: str) -> tuple:
        """("page", PageText, status, final_url) or ("fail", reason, detail, status, final_url)."""
        if url in self._pages:
            return self._pages[url]
        try:
            doc = self.ctx.fetch(url, store=False, retries=1, accept_status=_ANY_STATUS, headers={"Accept": ACCEPT})
        except Offline as exc:
            if not self._online_confirmed:
                from .runner import is_online

                if not is_online():
                    raise                      # this PC is offline: the whole run is OFFLINE, nothing judged
                self._online_confirmed = True
            res: tuple = ("fail", wv.UNREACHABLE, f"page unreachable ({_short(exc)})", None, None)
        except CollectorError as exc:
            res = ("fail", wv.UNREACHABLE, f"page unreachable ({_short(exc)})", None, None)
        else:
            final = doc.url
            problem = wv.url_problem(final)
            failure = wv.http_failure(doc.status_code)
            if problem:
                res = ("fail", wv.BLOCKED, f"redirected to an address that is not opened ({problem})", doc.status_code, final)
            elif failure:
                reason, detail = failure
                page = wv.extract_text(doc.content, doc.content_type) if doc.status_code in (403, 429, 503) else None
                if page is not None and page.ok and wv.looks_blocked(page):
                    reason, detail = wv.BLOCKED, f"the site answered with an anti-bot page (HTTP {doc.status_code})"
                res = ("fail", reason, detail, doc.status_code, final)
            else:
                res = ("page", wv.extract_text(doc.content, doc.content_type), doc.status_code, final)
        self._pages[url] = res
        return res

    def verify(self, url: str, quote: str, value_as_published: str) -> wv.Verification:
        now = utcnow()
        problem = wv.url_problem(url)
        if problem:
            return wv.failed(wv.INVALID, f"not opened: {problem}", checked_at=now, url=url)
        res = self._open(url)
        if res[0] == "fail":
            _, reason, detail, status, final = res
            return wv.failed(reason, detail, checked_at=now, url=url, http_status=status, final_url=final)
        _, page, status, final = res
        return wv.check_text(page, quote, value_as_published, checked_at=now, url=url, final_url=final,
                             http_status=status)


def _short(exc: Exception) -> str:
    s = str(exc)
    return s if len(s) <= 160 else s[:157] + "..."


def _store_excerpt(ctx: CollectContext, f: dict, v: wv.Verification) -> int:
    """Archive the excerpt of the page around the quote (a small text file, never the whole page)."""
    pages = f", {v.pdf_pages[0]} of {v.pdf_pages[1]} pages read" if v.pdf_pages else ""
    body = "\n".join([
        "Paladex verification excerpt (only the part of the page around the quote, not the whole page)",
        f"URL: {f['source_url']}",
        f"Final URL: {v.final_url or f['source_url']}",
        f"Document: {v.doc_type}{pages}, {v.text_chars} characters of text",
        f"Quote: {f['quote']}",
        f"Value as published: {f['value_as_published']}",
        "",
        v.excerpt or "",
    ]).encode("utf-8")
    h = hashlib.sha256(body).hexdigest()
    existing = ctx.session.scalars(select(RawDocument).where(RawDocument.source_id == ctx.source.id,
                                                             RawDocument.content_hash == h)).first()
    if existing:
        return existing.id
    rel = Path(ctx.source.key) / f"{utcnow():%Y%m%d-%H%M%S}-{h[:12]}.txt"
    dest = ctx.settings.raw_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    title = f"Excerpt checked by Paladex: {f.get('source_title') or f['publisher']}"
    doc = RawDocument(source_id=ctx.source.id, url=f["source_url"][:1000], content_hash=h,
                      content_type="text/plain; charset=utf-8", path=str(rel), size_bytes=len(body),
                      title=title[:500], published_at=f.get("published_at"))
    ctx.session.add(doc)
    ctx.session.flush()
    return doc.id


# ---------------------------------------------------------------------------
# The collector
# ---------------------------------------------------------------------------

class WebFindingsCollector(Collector):
    key = "web_findings"
    name = "Altre fonti (non ufficiali): dati recenti trovati sul web e verificati da Paladex"
    name_en = "Other sources (non-official): recent figures found on the web, verified by Paladex"
    publisher = "Pagine web di editori diversi (ogni dato indica il proprio)"
    homepage = None  # type: ignore[assignment]  # every finding links its own page
    kind = SourceKind.HTML
    reliability = Reliability.AGGREGATOR
    category = "findings"
    language = None
    expected_update = "Controllo settimanale; ogni dato viene ricontrollato sulla sua pagina al massimo una volta al mese"
    expected_update_en = "Checked weekly; each figure is re-checked on its page at most once a month"
    expected_max_age_days = None
    terms_note = ("Dati trovati sul web (pubblicazioni ufficiali non in serie statistica, rapporti USDA FAS, associazioni, "
                  "stampa di settore, notizie): NON sono statistiche ufficiali e non vengono mai sommati ai dati ufficiali. "
                  "Ogni dato è salvato solo se Paladex apre la pagina citata e vi trova la frase citata e il numero; della "
                  "pagina viene archiviato solo un estratto. Le pagine che bloccano l'accesso automatico non vengono "
                  "aggirate. Ricerca web con IA facoltativa e disattivata in partenza (pagina Fonti).")
    schedule = {"trigger": "cron", "day_of_week": "sun", "hour": 9, "minute": 40}
    order = 95

    def collect(self, ctx: CollectContext) -> None:
        countries = {c.iso3: c for c in ctx.session.scalars(select(Country))}
        checker = PageChecker(ctx)
        seed = load_seed()
        seed_keys: set[str] = set()
        if seed.error:
            ctx.warn(seed.error)
        else:
            for i, raw in enumerate(seed.findings, 1):
                f, problem = parse_finding(raw, set(countries))
                if problem:
                    ctx.warn(f"Seed finding {i} ({_raw_label(raw)}): not stored, {problem}")
                    continue
                key = series_key(f)
                if key in seed_keys:
                    ctx.warn(f"Seed finding {i} ({_label(f)}): the same figure is listed twice; the first is kept")
                    continue
                seed_keys.add(key)
                self._process(ctx, checker, f, key, extra={"found_by": FOUND_BY_SEED, "seed_compiled_on": seed.compiled_on})
                if i % CHECKPOINT_EVERY == 0:
                    ctx.checkpoint()
            self._retire_withdrawn(ctx, seed_keys)
        ctx.checkpoint()
        self._recheck_stored(ctx, checker, skip=seed_keys)
        ctx.checkpoint()
        self._ai_search(ctx, checker, countries, seed)

    # -------------------------------------------------------------- one finding
    def _process(self, ctx: CollectContext, checker: PageChecker, f: dict, key: str, *, extra: dict) -> str:
        """Verify and store one finding. Returns new | revised | unchanged | fresh | kept | failed."""
        current = current_finding(ctx.session, ctx.source.id, key)
        same = current is not None and current.value_hash == value_hash(f)
        now = utcnow()
        if (same and not ctx.force and current.verified_at is not None
                and now - current.verified_at < timedelta(days=RECHECK_DAYS)):
            current.last_seen_at = now
            ctx.counters.count("unchanged")
            return "fresh"
        v = checker.verify(f["source_url"], f["quote"], f["value_as_published"])
        if not v.ok:
            if same:
                current.verification = wv.add_check(current.verification, v)
                current.last_seen_at = now
                ctx.counters.count("unchanged")
                ctx.warn(f"{_label(f)}: re-check on its page failed, finding kept as last verified "
                         f"({_date(current.verified_at)}): {v.detail}")
                return "kept"
            what = "changed figure not stored (the previous one stays)" if current is not None else "not stored"
            ctx.warn(f"{_label(f)}: {what}: {v.detail} [{f['source_url'][:200]}]")
            return "failed"
        raw_id = _store_excerpt(ctx, f, v)
        rng = f.get("range") or {}
        fields = {**{k: val for k, val in f.items() if k != "range"},
                  "verified_at": v.checked_at, "raw_document_id": raw_id,
                  "verification": wv.add_check(current.verification if same else None, v),
                  "extra": {**extra, **rng, "first_verified_at": v.record()["checked_at"]}}
        outcome, _row = record_finding(ctx.session, source_id=ctx.source.id, series_key=key, **fields)
        ctx.counters.count(outcome)
        ctx._track_period(f.get("published_at"), f["period_label"], f["period_start"])
        return outcome

    def _retire_withdrawn(self, ctx: CollectContext, seed_keys: set[str]) -> None:
        rows = ctx.session.scalars(select(WebFinding).where(
            WebFinding.source_id == ctx.source.id, WebFinding.is_current.is_(True), WebFinding.is_demo.is_(False))).all()
        gone = [r for r in rows if (r.extra or {}).get("found_by") == FOUND_BY_SEED and r.series_key not in seed_keys]
        keys = retire_findings(ctx.session, source_id=ctx.source.id, rows=gone)
        if keys:
            ctx.counters.revised += len(keys)
            ctx.warn(f"{len(keys)} finding(s) withdrawn from the seed are no longer shown (kept in history): "
                     + ", ".join(k.rsplit("|", 1)[0] for k in keys[:10]))

    def _recheck_stored(self, ctx: CollectContext, checker: PageChecker, *, skip: set[str]) -> None:
        """Monthly re-check of the stored findings the seed did not cover (AI findings, or every finding
        when the seed file is missing)."""
        due = utcnow() - timedelta(days=RECHECK_DAYS)
        rows = ctx.session.scalars(select(WebFinding).where(
            WebFinding.source_id == ctx.source.id, WebFinding.is_current.is_(True), WebFinding.is_demo.is_(False))).all()
        for r in rows:
            if r.series_key in skip or (not ctx.force and r.verified_at is not None and r.verified_at > due):
                continue
            f = {k: getattr(r, k) for k in ("country_iso3", "metric", "period_label", "publisher", "source_url",
                                            "quote", "value_as_published", "source_title", "published_at")}
            v = checker.verify(r.source_url, r.quote, r.value_as_published)
            r.verification = wv.add_check(r.verification, v)
            r.last_seen_at = utcnow()
            ctx.counters.count("unchanged")
            if v.ok:
                r.verified_at = v.checked_at
                r.raw_document_id = _store_excerpt(ctx, f, v)
            else:
                ctx.warn(f"{_label(f)}: re-check on its page failed, finding kept as last verified "
                         f"({_date(r.verified_at)}): {v.detail}")

    # -------------------------------------------------------------- AI web search (optional)
    def _ai_search(self, ctx: CollectContext, checker: PageChecker, countries: dict[str, Country], seed: Seed) -> None:
        from ..services import findings_ai as fa

        st = fa.ai_status(ctx.session, ctx.settings)
        if not st["enabled"]:
            return
        if st["unavailable"]:
            log.info("[%s] AI web search is on but cannot run (%s)", self.key, st["unavailable"])
            _save_ai_run(ctx, {"at": _now_iso(), "skipped": st["unavailable"], "model": st["model"]})
            return
        ref = today()
        model = st["model"]
        run: dict = {"at": _now_iso(), "provider": "anthropic", "model": model, "max_searches": st["max_searches"],
                     **fa.new_usage(), "countries": [], "proposed": 0, "stored": 0, "error": None}
        state = dict(_get(ctx, fa.AI_STATE_SETTING) or {})
        valid = set(countries)
        for iso3 in self._ai_candidates(ctx, countries, seed, state, ref):
            remaining = st["max_searches"] - run["searches"]
            if remaining <= 0:
                break
            c = countries[iso3]
            try:
                res = fa.search_country(ctx.client, ctx.settings, country_name=c.name_en, iso3=iso3, today=ref,
                                        max_uses=min(fa.SEARCHES_PER_COUNTRY, remaining))
            except fa.AiSearchError as exc:
                run["error"] = str(exc)[:300]
                ctx.warn(f"AI web search stopped at {c.name_en}: {exc}")
                break
            for k in ("requests", "searches", "input_tokens", "output_tokens", "cache_creation_input_tokens",
                      "cache_read_input_tokens"):
                run[k] += res.usage[k]
            run["cost_usd"] = round(run["cost_usd"] + res.usage["cost_usd"], 6)
            run["cost_known"] = run["cost_known"] and res.usage["cost_known"]
            stored = 0
            for raw in res.findings[:MAX_AI_FINDINGS_PER_COUNTRY]:
                run["proposed"] += 1
                f, problem = parse_finding(raw, valid, iso3=iso3, min_year=AI_MIN_YEAR)
                if problem:
                    ctx.warn(f"AI finding for {c.name_en} ({_raw_label(raw)}): not stored, {problem}")
                    continue
                key = series_key(f)
                if current_finding(ctx.session, ctx.source.id, key) is not None:
                    continue                    # already known (seed or an earlier search): never overwritten by the AI
                outcome = self._process(ctx, checker, f, key, extra={
                    "found_by": FOUND_BY_AI, "provider": "anthropic", "model": model, "searched_at": ref.isoformat(),
                    "search_queries": res.queries[:10]})
                if outcome in ("new", "revised"):
                    stored += 1
            run["stored"] += stored
            run["countries"].append({"iso3": iso3, "searches": res.usage["searches"], "proposed": len(res.findings),
                                     "stored": stored})
            state[iso3] = {"searched_at": ref.isoformat(), "proposed": len(res.findings), "stored": stored,
                           "searched": res.searched, "queries": res.queries[:10], "model": model,
                           "search_errors": res.search_errors[:5]}
            _set(ctx, fa.AI_STATE_SETTING, state)
            _save_ai_run(ctx, run)
            ctx.checkpoint()                    # the usage of what was already paid for is never lost
        _save_ai_run(ctx, run)

    @staticmethod
    def _ai_candidates(ctx: CollectContext, countries: dict[str, Country], seed: Seed, state: dict, ref: date) -> list[str]:
        """Countries without a verified finding for a period ending in the last year or later, priority
        countries first, then those the seed researched; none searched by the AI in the last weeks."""
        from ..reference.countries import PRIORITY_ISO3

        cut = date(ref.year - 1, 1, 1)
        W = WebFinding
        recent = set(ctx.session.scalars(select(W.country_iso3).where(
            W.is_current.is_(True), W.is_demo.is_(False), W.verified_at.is_not(None), W.period_end >= cut)).all())
        order: list[str] = []
        for iso3 in [*PRIORITY_ISO3, *[str((x or {}).get("country_iso3") or "").upper()
                                       for x in [*seed.findings, *seed.not_found] if isinstance(x, dict)]]:
            if iso3 in countries and iso3 not in order:
                order.append(iso3)
        out = []
        for iso3 in order:
            if iso3 in recent:
                continue
            last = _iso_date((state.get(iso3) or {}).get("searched_at"))
            if isinstance(last, date) and (ref - last).days < AI_RESEARCH_DAYS:
                continue
            out.append(iso3)
        return out


def _date(dt: datetime | None) -> str:
    return dt.date().isoformat() if dt else "never"


def _now_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat()


def _get(ctx: CollectContext, key: str):
    row = ctx.session.get(AppSetting, key)
    return None if row is None else row.value


def _set(ctx: CollectContext, key: str, value) -> None:
    value = json.loads(json.dumps(value, default=str))   # a new object: the JSON column sees the change
    row = ctx.session.get(AppSetting, key)
    if row is None:
        ctx.session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    ctx.session.flush()


def _save_ai_run(ctx: CollectContext, run: dict) -> None:
    """Record the usage of this run (replacing its own earlier entry), newest last, capped."""
    from ..services import findings_ai as fa

    runs = [r for r in (_get(ctx, fa.AI_USAGE_SETTING) or []) if isinstance(r, dict) and r.get("at") != run.get("at")]
    runs.append(run)
    _set(ctx, fa.AI_USAGE_SETTING, runs[-fa.USAGE_RUNS_KEPT:])
