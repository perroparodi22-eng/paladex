"""Regenerate the one RECONSTRUCTED PDF fixture still used (see README.md).

Since 4 Nov 2026 the Italian sources are reachable and the other PDF fixtures of this folder
are REAL captures (real_*.pdf). Only `siena_listino_drift.pdf` remains synthetic: a weekly
list whose price columns were renamed, used to check that the parser refuses a changed layout.
The numbers in it are test data.

    python3 make_pdf_fixtures.py        # needs `pip install reportlab` (not a Paladex dependency)
"""
from __future__ import annotations

from pathlib import Path

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

rl_config.invariant = 1          # reproducible bytes (no creation timestamp / random id)
HERE = Path(__file__).parent


def _siena(path: Path, header: tuple[str, str, str], honey: list[tuple[str, str, str, str]]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800

    def line(*cols: tuple[int, str], size: int = 9) -> None:
        nonlocal y
        c.setFont("Helvetica", size)
        for x, text in cols:
            c.drawString(x, y, text)
        y -= 16

    line((40, "CAMERA DI COMMERCIO INDUSTRIA ARTIGIANATO E AGRICOLTURA DI AREZZO-SIENA"), size=10)
    line((40, "Ufficio Prezzi - Sede di Siena"))
    line((40, "LISTINO PREZZI ALL'INGROSSO DELLA PROVINCIA DI SIENA"), size=10)
    line((40, "Listino n. 14 del 08.04.2026"))
    y -= 8
    line((40, "Prodotto"), (300, header[0]), (380, header[1]), (460, header[2]))
    line((40, "CEREALI"))
    line((40, "Grano duro nazionale fino"), (300, "t"), (380, "300,00"), (460, "310,00"))
    line((40, "Orzo nazionale"), (300, "t"), (380, "190,00"), (460, "200,00"))
    line((40, "OLIO"))
    line((40, "Olio extravergine di oliva"), (300, "kg"), (380, "9,50"), (460, "10,50"))
    line((40, "PRODOTTI VARI"))
    for label, unit, lo, hi in honey:
        line((40, label), (300, unit), (380, lo), (460, hi))
    line((40, "Uova fresche categoria A"), (300, "n."), (380, "0,25"), (460, "0,32"))
    c.showPage()
    c.save()


def siena_drift() -> None:
    # A weekly list with renamed price columns: the parser must refuse it (schema drift).
    honey = [("Miele millefiori", "kg", "6,00", "7,00"), ("Miele selezionato", "kg", "6,50", "10,00")]
    _siena(HERE / "siena_listino_drift.pdf", ("u. misura", "Prezzo", "Var. %"), honey)


if __name__ == "__main__":
    siena_drift()
    print("PDF fixture written to", HERE)
