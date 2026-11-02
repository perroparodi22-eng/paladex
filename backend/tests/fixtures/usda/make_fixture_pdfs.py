"""Render the RECONSTRUCTED National Honey Report text layouts in this folder as PDFs.

    cd backend && source .venv/bin/activate
    uv pip install fpdf2            # dev-only dependency, not needed by the application
    python tests/fixtures/usda/make_fixture_pdfs.py

Each `fvmhoney_<date>.txt` holds a layout reconstructed from documentation (see README.md);
it is NOT a USDA publication. Every text line is drawn in Helvetica, a proportional font like
the real report's. Each column (text separated by 2+ spaces) starts at the x position of its
character column, so the PDF has space-aligned, unruled columns as described in
docs/research/usda.json. Headings are bold. A form feed (\\f) starts a new page.

The test suite reads the committed PDFs; this script only regenerates them.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

HERE = Path(__file__).resolve().parent
FONT_SIZE = 7.0          # pt
COLUMN_WIDTH = 4.6       # pt per character column of the text layout
LEADING = 10.0           # pt between baselines
MARGIN_X, MARGIN_TOP = 36.0, 48.0
BOLD = re.compile(
    r"^(NATIONAL HONEY REPORT|PRICES PAID|Prices paid|U\.S\. HONEY|Natural Honey|COLONY, HONEY|Temperature)"
)


def render(txt_path: Path, pdf_path: Path) -> None:
    pdf = FPDF(orientation="P", unit="pt", format="letter")
    pdf.set_auto_page_break(False)
    pdf.set_creation_date(datetime(2026, 11, 2, tzinfo=timezone.utc))
    pdf.set_title(f"RECONSTRUCTED TEST FIXTURE {txt_path.stem} - not a USDA publication")
    pdf.set_author("Paladex test suite (layout reconstructed from documentation)")
    pdf.set_subject("Reconstructed layout of the USDA AMS National Honey Report for parser tests")
    pages = txt_path.read_text(encoding="ascii").split("\f")
    for page_text in pages:
        pdf.add_page()
        y = MARGIN_TOP
        for raw in page_text.strip("\n").split("\n"):
            if raw.strip():
                pdf.set_font("Helvetica", "B" if BOLD.match(raw.strip()) else "", FONT_SIZE)
                # a "cell" = text separated from the next one by 2+ spaces; keep its column position
                for m in re.finditer(r"\S+(?: \S+)*", raw):
                    pdf.text(MARGIN_X + m.start() * COLUMN_WIDTH, y, m.group(0))
            y += LEADING
    pdf.output(str(pdf_path))


def main(argv: list[str]) -> None:
    targets = sorted(HERE.glob("fvmhoney_*.txt"))
    for txt in targets:
        out = txt.with_suffix(".pdf")
        render(txt, out)
        print(f"wrote {out.relative_to(HERE)} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
