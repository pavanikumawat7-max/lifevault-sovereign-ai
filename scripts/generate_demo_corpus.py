#!/usr/bin/env python3
"""Generate a deterministic, entirely synthetic LifeVault demo corpus."""
from __future__ import annotations

import random
import shutil
from pathlib import Path

from docx import Document
from faker import Faker
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo-data" / "synthetic"
fake = Faker()
Faker.seed(20260926)
random.seed(20260926)


def make_pdf(path: Path, title: str, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    _, height = letter
    for page_index, paragraph in enumerate(paragraphs, start=1):
        text = pdf.beginText(54, height - 54)
        text.setFont("Helvetica-Bold", 14)
        text.textLine(title)
        text.setFont("Helvetica", 10)
        text.textLine(f"Synthetic document - page {page_index}")
        for line in _wrap(paragraph, 92):
            if text.getY() < 54:
                pdf.drawText(text)
                pdf.showPage()
                text = pdf.beginText(54, height - 54)
                text.setFont("Helvetica", 10)
            text.textLine(line)
        pdf.drawText(text)
        if page_index < len(paragraphs):
            pdf.showPage()
    pdf.save()


def make_docx(path: Path, title: str, body: str) -> None:
    doc = Document()
    doc.add_heading(title, 0)
    doc.add_paragraph("Synthetic data for the LifeVault demo.")
    doc.add_paragraph(body)
    doc.save(path)


def make_order_image(path: Path) -> None:
    image = Image.new("RGB", (1100, 700), "white")
    draw = ImageDraw.Draw(image)
    lines = [
        "Synthetic order confirmation",
        "Order: DEMO-48291",
        "Item: Dell UltraSharp 27 Monitor",
        "Total: $429.00",
        "Delivery: October 2, 2026",
        "This image contains no real personal information.",
    ]
    for index, line in enumerate(lines):
        draw.text((70, 70 + index * 85), line, fill="black")
    image.save(path)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if len(" ".join(current + [word])) > width and current:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    folder_a = OUTPUT / "folder_A"
    folder_b = OUTPUT / "folder_B"
    screenshots = OUTPUT / "screenshots"
    docx_dir = OUTPUT / "docx"
    for directory in (folder_a, folder_b, screenshots, docx_dir):
        directory.mkdir(parents=True, exist_ok=True)

    dell = [
        "Dell Limited Hardware Warranty. Product: Dell XPS 15. "
        "Service tag: SYNTH-XPS-2026. Purchase date: June 12, 2026. "
        "Warranty expires June 12, 2027. Coverage includes synthetic "
        "hardware repair terms for demonstration only.",
        "Support instructions: retain invoice INV-DELL-10482 and contact "
        "the fictional support desk before the expiration date.",
    ]
    make_pdf(folder_a / "dell_warranty.pdf", "Dell Warranty", dell)
    shutil.copy2(folder_a / "dell_warranty.pdf", folder_b / "dell_warranty_copy.pdf")
    make_pdf(
        folder_a / "dell_invoice.pdf",
        "Dell Invoice INV-DELL-10482",
        ["Invoice date June 12, 2026. Dell XPS 15 laptop. Quantity 1. "
         "Synthetic total $1,749.00. Payment status paid."],
    )
    make_pdf(
        folder_b / "old_expired_warranty.pdf",
        "Expired Appliance Warranty",
        ["Synthetic refrigerator warranty purchased March 3, 2019. "
         "Warranty expired March 3, 2021. Contract OLD-DEMO-319."],
    )

    categories = ["insurance", "utilities", "travel", "education", "home", "medical"]
    for index in range(100):
        category = categories[index % len(categories)]
        title = f"Synthetic {category.title()} Record {index + 1:03d}"
        body = (
            f"Reference DEMO-{index + 1:04d}. Date {fake.date_between('-5y', 'today')}. "
            f"Provider {fake.company()}. {fake.paragraph(nb_sentences=12)} "
            "All names, addresses, amounts, and identifiers are synthetic."
        )
        make_pdf(folder_a / f"record_{index + 1:03d}.pdf", title, [body])

    for index in range(5):
        make_docx(
            docx_dir / f"synthetic_note_{index + 1}.docx",
            f"Synthetic Note {index + 1}",
            fake.paragraph(nb_sentences=10),
        )
    make_order_image(screenshots / "order_email.png")
    count = sum(1 for path in OUTPUT.rglob("*") if path.is_file())
    print(f"Generated {count} files in {OUTPUT}")


if __name__ == "__main__":
    main()