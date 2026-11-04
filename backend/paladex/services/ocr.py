"""Optional OCR for scanned official PDFs (Tesseract).

Some official notices are published as a scanned page with no text layer (the DGFT minimum
export price notifications, for example). Their terms can only be read by OCR. This module
renders the PDF pages with pdfplumber (pypdfium2, already a dependency) and runs the
``tesseract`` command-line program on each page.

Tesseract is an OPTIONAL system program, not a Python dependency:

* Linux: ``apt install tesseract-ocr`` (English data is included); macOS: ``brew install tesseract``;
  Windows: the UB Mannheim installer. ``PALADEX_TESSERACT_CMD`` may name the executable when it
  is not on the PATH.
* Without it, ``available()`` is None and callers store the notice without its terms, with a
  warning that says how to enable OCR.

OCR text can misread characters (superscript ordinals such as the "st" of "31st" come out as
"31*", "318", "3154" ...). Callers must therefore treat it as weaker than a text layer: read
it at two resolutions (``ocr_pdf(..., dpi=...)``) and keep only the values on which both
readings agree, and record that the value came from OCR.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
from functools import lru_cache

log = logging.getLogger(__name__)

DEFAULT_DPI = 300
SECOND_DPI = 400          # the second, independent reading used for cross-checks
MAX_PAGES = 3
TIMEOUT_S = 120
# "6": one uniform block of text. On the one-column notices this reads a table row by row, so a
# price split over two lines of a cell ("of US$" / "2000 F.O.B per Metric Ton") stays together;
# the default automatic layout ("3") moved the row label between them on real DGFT scans.
PAGE_SEGMENTATION = "6"


class OcrError(Exception):
    """Tesseract is installed but failed on this document."""


@lru_cache(maxsize=1)
def _find() -> str | None:
    cmd = os.environ.get("PALADEX_TESSERACT_CMD") or "tesseract"
    return shutil.which(cmd)


def available() -> str | None:
    """Path of the tesseract executable, or None when OCR is not installed."""
    return _find()


@lru_cache(maxsize=1)
def engine_version() -> str | None:
    """"tesseract 5.3.4" (first line of ``tesseract --version``), or None."""
    exe = available()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or out.stderr).decode("utf-8", errors="replace").strip().splitlines()
    return first[0].strip() if first else None


def ocr_pdf(content: bytes, *, dpi: int = DEFAULT_DPI, max_pages: int = MAX_PAGES, lang: str = "eng") -> str:
    """OCR text of the first `max_pages` pages, rendered at `dpi` in grey scale. Tesseract runs
    single-threaded (``OMP_THREAD_LIMIT=1``): faster on small pages and safe next to other work.

    Raises ``OcrError`` when Tesseract is missing, the PDF cannot be rendered or Tesseract fails."""
    exe = available()
    if not exe:
        raise OcrError("Tesseract OCR is not installed")
    try:
        import pdfplumber

        pages: list[bytes] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:max_pages]:
                img = page.to_image(resolution=dpi).original.convert("L")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                pages.append(buf.getvalue())
    except Exception as exc:  # noqa: BLE001 - pdfminer/pypdfium2 raise many types on damaged files
        raise OcrError(f"the PDF could not be rendered for OCR: {exc}") from exc
    texts: list[str] = []
    for i, png in enumerate(pages, 1):
        try:
            out = subprocess.run([exe, "stdin", "stdout", "-l", lang, "--psm", PAGE_SEGMENTATION], input=png,
                                 capture_output=True, timeout=TIMEOUT_S, check=False,
                                 env={**os.environ, "OMP_THREAD_LIMIT": "1"})
        except (OSError, subprocess.SubprocessError) as exc:
            raise OcrError(f"tesseract failed on page {i}: {exc}") from exc
        if out.returncode != 0:
            raise OcrError(f"tesseract failed on page {i} (exit {out.returncode}): "
                           f"{out.stderr.decode('utf-8', errors='replace')[:200]}")
        texts.append(out.stdout.decode("utf-8", errors="replace"))
    return "\n".join(texts)
