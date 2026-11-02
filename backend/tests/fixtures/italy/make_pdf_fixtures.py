"""Regenerate the RECONSTRUCTED PDF fixtures of this folder (see README.md).

The real PDFs could not be downloaded (hosts unreachable from the build environment), so
these files imitate the documented layouts. They are test inputs only; the numbers are
illustrative unless README.md says otherwise.

    python3 make_pdf_fixtures.py        # needs `pip install reportlab` (not a Paladex dependency)
"""
from __future__ import annotations

from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1          # reproducible bytes (no creation timestamp / random id)
HERE = Path(__file__).parent
STYLES = getSampleStyleSheet()
MONTHS = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _cuneo_averages(path: Path, year: int, rows: list[list[str]], ruled: bool) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=24, rightMargin=24)
    data = [["Prodotto", *MONTHS, "Media"], *rows]
    widths = [190] + [44] * 12 + [50]
    table = Table(data, colWidths=widths)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]
    if ruled:
        style.append(("GRID", (0, 0), (-1, -1), 0.5, colors.black))
    table.setStyle(TableStyle(style))
    doc.build([
        Paragraph("Camera di Commercio di Cuneo - Listino dei Prezzi all'Ingrosso", STYLES["Title"]),
        Paragraph(f"Miele - medie {year}", STYLES["Heading2"]),
        Paragraph("Prezzi medi mensili e media annua in euro al kg (€/kg)", STYLES["Normal"]),
        Spacer(1, 10),
        table,
    ])


def cuneo_averages() -> None:
    # 2025: annual means close to the approximate 2025 averages quoted in docs/research/italy.json
    # (acacia 8,09, millefiori 5,83, castagno 5,80, tiglio 6,59, alta montagna 7,67); the monthly
    # values are illustrative. Blank cells = month without a quotation.
    rows_2025 = [
        ["Acacia (fusto da 3 q.li)", "8,00", "8,00", "8,00", "8,00", "8,00", "8,10", "8,20", "8,20", "8,20", "8,10", "8,10", "8,10", "8,09"],
        ["Millefiori (fusto da 3 q.li)", "5,90", "5,90", "5,90", "5,90", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,75", "5,75", "5,83"],
        ["Castagno (fusto da 3 q.li)", "", "", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80", "5,80"],
        ["Tiglio (fusto da 3 q.li)", "6,60", "6,60", "6,60", "6,60", "6,60", "6,60", "6,60", "6,60", "6,55", "6,55", "6,60", "6,60", "6,59"],
        ["Millefiori di alta montagna (secchio da 25 kg)", "", "", "", "", "", "", "", "", "7,67", "7,67", "7,67", "7,67", "7,67"],
    ]
    _cuneo_averages(HERE / "cuneo_medie_2025.pdf", 2025, rows_2025, ruled=True)
    rows_2024 = [
        ["Acacia (fusto da 3 q.li)", "7,90", "7,90", "", "8,00", "8,00", "8,00", "8,10", "8,10", "8,10", "8,10", "8,10", "8,10", "8,04"],
        ["Millefiori (fusto da 3 q.li)", "6,00", "6,00", "6,00", "", "", "", "5,90", "5,90", "5,90", "5,90", "5,90", "5,90", "5,94"],
    ]
    _cuneo_averages(HERE / "cuneo_medie_2024_unruled.pdf", 2024, rows_2024, ruled=False)


def _grid(data: list[list[str]], widths: list[int]) -> Table:
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    return t


def onm_annual() -> None:
    """Reconstructed 'Report annuale' with the two tables described in the research
    (wholesale prices by variety, drums of 300 kg; import prices by country of origin).
    All numbers are illustrative."""
    doc = SimpleDocTemplate(str(HERE / "onm_report_annuale_2024.pdf"), pagesize=A4)
    s = STYLES
    story = [
        Paragraph("Osservatorio Nazionale Miele", s["Title"]),
        Paragraph("Report annuale - Monitoraggio produzione e mercato del miele - Stagione 2024", s["Heading2"]),
        Paragraph("Il mercato del miele all'ingrosso nel 2024 ha mostrato prezzi stabili per i mieli "
                  "monoflora e in calo per il millefiori, sotto la pressione delle importazioni.", s["Normal"]),
        PageBreak(),
        Paragraph("Prezzi all'ingrosso dei principali mieli convenzionali in fusti da 300 kg", s["Heading3"]),
        Paragraph("Euro al kg, IVA inclusa, franco produttore", s["Normal"]),
        _grid([["Varietà", "Min", "Max", "Media"],
               ["Acacia", "8,50", "10,50", "9,40"],
               ["Agrumi", "5,50", "6,50", "6,00"],
               ["Castagno", "6,00", "7,00", "6,50"],
               ["Millefiori", "4,50", "5,50", "5,00"],
               ["Tiglio", "6,00", "7,20", "6,60"],
               ["Sulla", "5,50", "6,50", "6,00"],
               ["Media", "6,00", "7,20", "6,58"]], [160, 70, 70, 70]),
        Spacer(1, 16),
        Paragraph("Prezzi all'ingrosso del millefiori per area: Nord, Centro, Sud", s["Heading3"]),
        _grid([["Area", "Min", "Max", "Media"],
               ["Nord", "4,80", "5,60", "5,20"],
               ["Centro", "4,60", "5,40", "5,00"],
               ["Sud", "4,30", "5,20", "4,75"]], [160, 70, 70, 70]),
        PageBreak(),
        Paragraph("Prezzi del miele d'importazione per paese di origine", s["Heading3"]),
        Paragraph("Euro al kg, prodotto sdoganato in fusti", s["Normal"]),
        _grid([["Paese di origine", "Min", "Max", "Media"],
               ["Argentina", "2,60", "3,10", "2,85"],
               ["Ucraina", "2,20", "2,70", "2,45"],
               ["Cina", "1,40", "1,90", "1,65"],
               ["Ungheria", "3,80", "4,60", "4,20"],
               ["Moldavia", "2,40", "2,90", "2,65"],
               ["Altri paesi", "2,00", "3,50", "2,70"]], [160, 70, 70, 70]),
    ]
    doc.build(story)


def _siena(path: Path, header: str, honey: list[tuple[str, str, str, str]]) -> None:
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


def siena() -> None:
    # 'Miele millefiori' 6,00-7,00 and 'Miele selezionato' 6,50-10,00 are the values quoted in
    # docs/research/italy.json for list n. 14 del 08.04.2026; the rest of the list is illustrative.
    honey = [("Miele millefiori", "kg", "6,00", "7,00"), ("Miele selezionato", "kg", "6,50", "10,00")]
    _siena(HERE / "siena_listino_n14_2026.pdf", ("u. misura", "da Euro", "a Euro"), honey)
    # Same list with renamed price columns: the parser must refuse it (schema drift).
    _siena(HERE / "siena_listino_drift.pdf", ("u. misura", "Prezzo", "Var. %"), honey)


if __name__ == "__main__":
    cuneo_averages()
    onm_annual()
    siena()
    print("PDF fixtures written to", HERE)
