"""Rebuild the PDF fixtures of the origin-country notice watchers (SENASA Lista EAR, DGFT notifications).

    cd backend && python tests/fixtures/official_watchers/build_fixtures.py

Everything produced here is RECONSTRUCTED, ILLUSTRATIVE test data (see README.md). The layouts follow
the documented shape of the real documents; every number, date and identifier is invented, and every
PDF says so on its first lines. Never read these files as real notices or market data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

HERE = Path(__file__).parent
BANNER = "ILLUSTRATIVE TEST FIXTURE - NOT A REAL DOCUMENT (reconstructed layout, invented values)"


def write_pdf(name: str, lines: list[str]) -> None:
    pdf = FPDF()
    pdf.set_creation_date(datetime(2026, 1, 1, tzinfo=timezone.utc))
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for line in lines:
        pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(HERE / name))


EAR_HEADER = "Producto | Analito | Valor hallado | LMR | Fecha de muestreo | Identificación"

# SENASA "Lista EAR" (residue-limit exceedances), by product. N° 91 names honey twice; N° 90 does not.
EAR_91 = [
    "SENASA - Dirección Nacional de Inocuidad y Calidad Agroalimentaria",
    "LISTA EAR AÑO 2026 N° 91 - POR PRODUCTO",
    BANNER,
    "Fecha de publicación: 15/10/2026",
    EAR_HEADER,
    "Miel | Oxitetraciclina | 18 µg/kg | No permitido | 02/09/2026 | RENAPA 99-000001",
    "Carne bovina | Ivermectina | 120 µg/kg | 100 µg/kg | 04/09/2026 | Establecimiento 9999",
    "Miel | Fenol | 25 µg/kg | 10 µg/kg | 09/09/2026 | RENAPA 99-000002",
    "Riñón equino | Cadmio | 1,9 mg/kg | 1,0 mg/kg | 11/09/2026 | Establecimiento 9998",
]
EAR_90 = [
    "SENASA - Dirección Nacional de Inocuidad y Calidad Agroalimentaria",
    "LISTA EAR AÑO 2026 N° 90 - POR PRODUCTO",
    BANNER,
    "Fecha de publicación: 10/09/2026",
    EAR_HEADER,
    "Carne aviar | Enrofloxacina | 140 µg/kg | 100 µg/kg | 05/08/2026 | Establecimiento 9997",
    "Leche | Aflatoxina M1 | 0,09 µg/kg | 0,05 µg/kg | 12/08/2026 | Establecimiento 9996",
]

GAZETTE_HEAD = [
    BANNER,
    "To be published in the Gazette of India, Extraordinary, Part II, Section 3, Sub-section (ii)",
    "Government of India",
    "Ministry of Commerce & Industry",
    "Department of Commerce",
    "Directorate General of Foreign Trade",
]
POWERS = ("In exercise of powers conferred by Section 3 read with Section 5 of the Foreign Trade (Development & "
          "Regulation) Act, 1992, as amended, read with Paragraph 1.02 and 2.01 of the Foreign Trade Policy 2023, ")

# MEP extension: one price, one validity date (written twice), immediate effect.
DGFT_91 = GAZETTE_HEAD + [
    "Notification No. 91/2026-27",
    "New Delhi, Dated: 28th October, 2026",
    "Subject: Extension of Minimum Export Price (MEP) on export of Natural Honey - reg.",
    "S.O. 9991(E): " + POWERS + "the Central Government hereby extends the Minimum Export Price (MEP) of US$ 1,111 "
    "per MT FOB on export of Natural Honey under ITC (HS) Code 04090000 up to 30th June, 2027.",
    "2. Effect of this Notification: The MEP on export of Natural Honey is extended till 30.06.2027. This "
    "notification comes into force with immediate effect.",
    "(Name withheld in fixture)",
    "Director General of Foreign Trade",
]

# MEP revision: two prices ("from ... to ..."), a validity date and an explicit effective date.
DGFT_93 = GAZETTE_HEAD + [
    "Notification No. 93/2025-26",
    "New Delhi, Dated: 28th November, 2025",
    "Subject: Revision of Minimum Export Price (MEP) on Natural Honey - reg.",
    "S.O. 9993(E): " + POWERS + "the Central Government hereby revises the Minimum Export Price (MEP) on export of "
    "Natural Honey under ITC (HS) Code 04090000 from US$ 1,234 per MT to US$ 1,111 per MT FOB, valid up to "
    "31.03.2026.",
    "2. Effect of this Notification: The MEP on Natural Honey is revised from US$ 1,234 per MT to US$ 1,111 per MT "
    "with effect from 01.12.2025.",
    "(Name withheld in fixture)",
    "Director General of Foreign Trade",
]

# Export-policy change without a price.
DGFT_94 = GAZETTE_HEAD + [
    "Notification No. 94/2026-27",
    "New Delhi, Dated: 2nd November, 2026",
    "Subject: Amendment in Export Policy of Natural Honey under ITC (HS) Code 04090000 - reg.",
    "S.O. 9994(E): " + POWERS + "the Central Government hereby amends the export policy of Natural Honey under ITC "
    "(HS) Code 04090000 from 'Free' to 'Free subject to registration of export contracts with the designated "
    "agency'.",
    "2. Effect of this Notification: Export of Natural Honey is Free subject to registration of export contracts. "
    "This notification comes into force with immediate effect.",
    "(Name withheld in fixture)",
    "Director General of Foreign Trade",
]


if __name__ == "__main__":
    write_pdf("ear_91-26_producto.pdf", EAR_91)
    write_pdf("ear_90-26_producto.pdf", EAR_90)
    write_pdf("dgft_notif_91_2026-27.pdf", DGFT_91)
    write_pdf("dgft_notif_93_2025-26.pdf", DGFT_93)
    write_pdf("dgft_notif_94_2026-27.pdf", DGFT_94)
    print("PDF fixtures written to", HERE)
