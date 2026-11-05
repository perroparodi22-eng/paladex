"""Official report releases (e.g. USDA National Honey Report, Oct 2026) with provenance, and
the archived original document as it was downloaded."""
from __future__ import annotations

import mimetypes
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..enums import DataStatus
from ..models import RawDocument, Report, Source
from .common import demo_clause, iso, show_demo, source_brief, sources_by_id

router = APIRouter(tags=["reports"])

NARRATIVE_EXCERPT_CHARS = 600

# Types a browser can show without running anything from the archived file.
_INLINE_TYPES = {"application/pdf", "text/plain", "text/csv", "application/json", "image/png", "image/jpeg", "image/gif"}
# Markup that could contain scripts: shown inline only inside a CSP sandbox (no scripts, opaque origin).
_SANDBOXED_TYPES = {"text/html", "application/xhtml+xml", "application/xml", "text/xml", "image/svg+xml",
                    "application/rss+xml", "application/atom+xml"}


def safe_raw_path(raw_dir: Path, rel: str | None) -> Path | None:
    """Resolve a RawDocument.path (relative to raw_dir) and refuse anything that escapes it."""
    if not rel or "\x00" in rel:
        return None
    p = Path(rel)
    if p.is_absolute() or p.drive:
        return None
    base = raw_dir.resolve()
    try:
        target = (base / p).resolve()
    except (OSError, RuntimeError):
        return None
    if target == base or not target.is_relative_to(base):
        return None
    return target


def _raw_brief(report: Report, doc: RawDocument | None) -> dict | None:
    if doc is None:
        return None
    return {
        "id": doc.id,
        "url": doc.url,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "fetched_at": iso(doc.fetched_at),
        "file_url": f"/api/reports/{report.id}/file",
    }


def serialize_report(r: Report, src: Source | None, doc: RawDocument | None, full: bool = False) -> dict:
    narrative = r.narrative or ""
    out = {
        "id": r.id,
        "report_key": r.report_key,
        "title": r.title,
        "period_label": r.period_label,
        "published_at": iso(r.published_at),
        "collected_at": iso(r.collected_at),
        "source": source_brief(src),
        "source_url": r.url,
        "reliability": src.reliability if src else None,
        "data_status": DataStatus.DEMO.value if r.is_demo else DataStatus.PUBLISHED.value,
        "is_demo": r.is_demo,
        "summary_it": r.summary_it,
        "summary_en": r.summary_en,
        "summary_is_ai": r.summary_is_ai,
        "has_narrative": bool(narrative),
        "narrative_excerpt": (narrative[:NARRATIVE_EXCERPT_CHARS].rstrip() + ("…" if len(narrative) > NARRATIVE_EXCERPT_CHARS else ""))
        if narrative else None,
        "raw_document": _raw_brief(r, doc),
    }
    if full:
        out["narrative"] = r.narrative
    return out


@router.get("/reports")
def list_reports(
    source: str | None = Query(None, description="source key"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    q: str | None = Query(None, description="text in title / summary / narrative"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Report).where(demo_clause(Report, db))
    if source:
        stmt = stmt.where(Report.source_id.in_(select(Source.id).where(Source.key == source)))
    if date_from:
        stmt = stmt.where(Report.published_at >= date_from)
    if date_to:
        stmt = stmt.where(Report.published_at <= date_to)
    if q and q.strip():
        pat = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(
            Report.title.ilike(pat, escape="\\") | Report.summary_it.ilike(pat, escape="\\")
            | Report.summary_en.ilike(pat, escape="\\") | Report.narrative.ilike(pat, escape="\\")
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Report.published_at.desc().nulls_last(), Report.collected_at.desc(), Report.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    srcs = sources_by_id(db)
    doc_ids = [r.raw_document_id for r in rows if r.raw_document_id]
    docs = {d.id: d for d in db.scalars(select(RawDocument).where(RawDocument.id.in_(doc_ids)))} if doc_ids else {}
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "reports": [serialize_report(r, srcs.get(r.source_id), docs.get(r.raw_document_id)) for r in rows],
    }


def _get_visible_report(db: Session, report_id: int) -> Report:
    r = db.get(Report, report_id)
    if r is None or (r.is_demo and not show_demo(db)):
        raise HTTPException(404, "Report not found")
    return r


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    r = _get_visible_report(db, report_id)
    doc = db.get(RawDocument, r.raw_document_id) if r.raw_document_id else None
    return serialize_report(r, db.get(Source, r.source_id), doc, full=True)


@router.get("/reports/{report_id}/file")
def report_file(report_id: int, db: Session = Depends(get_db)):
    """Serve the archived original exactly as downloaded (never regenerated)."""
    r = _get_visible_report(db, report_id)
    doc = db.get(RawDocument, r.raw_document_id) if r.raw_document_id else None
    path = safe_raw_path(get_settings().raw_dir, doc.path) if doc is not None else None
    if path is None or not path.is_file():
        # The owner clicked a document link: send them to the publisher's original rather than a bare
        # error (never to this same route, which would loop).
        if (r.url or "").lower().startswith(("https://", "http://")):
            return RedirectResponse(r.url, status_code=307)
        raise HTTPException(404, "No archived document for this report" if doc is None
                            else "Archived document not available")
    media_type = (doc.content_type or "").split(";")[0].strip().lower() or (
        mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    src = db.get(Source, r.source_id)
    filename = _download_name(src.key if src else "report", r.report_key, path.suffix)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if media_type in _INLINE_TYPES:
        disposition = "inline"
    elif media_type in _SANDBOXED_TYPES:
        disposition = "inline"
        headers["Content-Security-Policy"] = "sandbox"
    else:
        disposition = "attachment"
    return FileResponse(path, media_type=media_type, filename=filename, headers=headers,
                        content_disposition_type=disposition)


def _download_name(source_key: str, report_key: str, suffix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{source_key}-{report_key}").strip("-.") or "report"
    suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,6}", suffix or "") else ""
    return f"{stem[:120]}{suffix}"


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
