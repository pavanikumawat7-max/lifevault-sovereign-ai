#!/usr/bin/env python3
"""Generate a synthetic "personal documents" folder for demos.

Why this exists: a convincing demo needs documents whose *names* tell a
story -- passport, Aadhaar, address proof, insurance -- but putting real
identity documents on screen in a hackathon video is not recoverable. These
are entirely fabricated files with realistic names and plausible structure,
so retrieval, citations, fact extraction and the expiry dashboard all behave
exactly as they would on real paperwork.

Two deliberate choices:

  * **Every identifier is invalid by construction.** Aadhaar numbers here
    start with 0, which the UIDAI spec disallows, and passport/PAN/licence
    numbers carry a SYNTH prefix. Nothing generated here could be mistaken
    for, or used as, a real credential.
  * **Every page carries a footer saying it is synthetic.** Barely visible
    at demo zoom, but it means nobody can claim the demo faked real records.

Expiry dates are staggered relative to today so the 30 / 60 / 90 / 365-day
windows on the Expiry page each have something in them, and one document is
already expired.

    python scripts/generate_demo_personal_docs.py
    python scripts/generate_demo_personal_docs.py --output ~/MyDemoDocs
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

FOOTER = (
    "Synthetic document generated for a LifeVault demo. Not a real record; "
    "every identifier is deliberately invalid."
)


def _wrap(text: str, width: int = 95) -> list[str]:
    words, lines, current = text.split(), [], []
    for word in words:
        if len(" ".join(current + [word])) > width and current:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def make_pdf(path: Path, title: str, body_lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    text = pdf.beginText(54, height - 70)
    text.setFont("Helvetica-Bold", 15)
    text.textLine(title)
    text.textLine("")
    text.setFont("Helvetica", 10.5)
    for line in body_lines:
        for wrapped in _wrap(line):
            text.textLine(wrapped)
        text.textLine("")
    pdf.drawText(text)

    pdf.setFont("Helvetica-Oblique", 7)
    pdf.setFillGray(0.45)
    pdf.drawString(54, 38, FOOTER)
    pdf.save()


def build_documents(today: date) -> list[tuple[str, str, list[str]]]:
    """(filename, title, body lines) for each synthetic document.

    Dates are relative to `today` so the demo never goes stale: re-running
    this next month still produces something in every expiry window.
    """
    def iso(days: int) -> str:
        return (today + timedelta(days=days)).strftime("%B %d, %Y")

    return [
        # --- identity -------------------------------------------------
        (
            "passport_scan.pdf",
            "Republic of India - Passport (Synthetic Copy)",
            [
                "Passport Number: SYNTH-P0042198.",
                "Full Name: Demo Holder. Nationality: Indian.",
                f"Date of Issue: {iso(-2400)}. Date of Expiry: {iso(168)}.",
                "Place of Issue: Bengaluru. Type: P. Country Code: IND.",
                "This synthetic passport record exists only to demonstrate "
                "document retrieval and expiry tracking.",
            ],
        ),
        (
            "aadhaar_card.pdf",
            "Aadhaar - Unique Identification (Synthetic Copy)",
            [
                "Aadhaar Number: 0000 1111 2222.",
                "Note: this number begins with 0 and is therefore invalid by "
                "specification. It cannot correspond to any real Aadhaar.",
                "Name: Demo Holder. Year of Birth: 2003. Gender: F.",
                "Address: 14 Example Layout, Sample Nagar, Bengaluru 560001.",
                "Aadhaar is proof of identity, not of citizenship.",
            ],
        ),
        (
            "pan_card.pdf",
            "Income Tax Department - PAN (Synthetic Copy)",
            [
                "Permanent Account Number: SYNTHPAN9Z.",
                "Name: Demo Holder. Father's Name: Example Holder.",
                f"Date of Issue: {iso(-1800)}.",
                "PAN does not expire. Included so the demo corpus contains a "
                "document with no expiry date.",
            ],
        ),
        (
            "driving_licence.pdf",
            "Driving Licence - Karnataka (Synthetic Copy)",
            [
                "Licence Number: SYNTH-DL-2019-004417.",
                "Name: Demo Holder. Blood Group: O+.",
                f"Valid From: {iso(-2100)}. Valid Until: {iso(43)}.",
                "Class of Vehicle: LMV, MCWG.",
                "Address: 14 Example Layout, Sample Nagar, Bengaluru 560001.",
            ],
        ),
        (
            "birth_certificate.pdf",
            "Birth Certificate (Synthetic Copy)",
            [
                "Registration Number: SYNTH-BC-113402.",
                "Name: Demo Holder. Date of Birth: March 11, 2003.",
                "Place of Birth: Bengaluru, Karnataka.",
                "Issued by the Office of the Registrar of Births and Deaths.",
                "This certificate does not expire.",
            ],
        ),
        # --- address proof --------------------------------------------
        (
            "electricity_bill_address_proof.pdf",
            "BESCOM Electricity Bill - Address Proof",
            [
                "Consumer Number: SYNTH-EB-77310265.",
                "Billing Address: 14 Example Layout, Sample Nagar, "
                "Bengaluru 560001.",
                f"Bill Date: {iso(-22)}. Due Date: {iso(8)}.",
                "Units Consumed: 214. Amount Payable: Rs. 1,860.00.",
                "Commonly accepted as proof of address for KYC.",
            ],
        ),
        (
            "rental_agreement_expired.pdf",
            "Residential Rental Agreement (Synthetic Copy)",
            [
                "Agreement Number: SYNTH-RA-2023-0881.",
                "Tenant: Demo Holder. Landlord: Example Properties LLP.",
                "Premises: 14 Example Layout, Sample Nagar, Bengaluru 560001.",
                f"Agreement Start Date: {iso(-820)}. "
                f"Agreement Expiry Date: {iso(-90)}.",
                "Monthly Rent: Rs. 24,000.00. Security Deposit: Rs. 150,000.00.",
                "This agreement has already lapsed and needs renewal.",
            ],
        ),
        (
            "bank_statement_address_proof.pdf",
            "Savings Account Statement - Address Proof",
            [
                "Account Number: SYNTH-AC-0093 4417 2280.",
                "Branch: Sample Nagar, Bengaluru. IFSC: SYNT0000123.",
                "Registered Address: 14 Example Layout, Sample Nagar, "
                "Bengaluru 560001.",
                f"Statement Period: {iso(-60)} to {iso(-30)}.",
                "Closing Balance: Rs. 84,215.40.",
            ],
        ),
        # --- insurance and warranties ---------------------------------
        (
            "car_insurance_policy.pdf",
            "Private Car Insurance Policy (Synthetic Copy)",
            [
                "Policy Number: SYNTH-MOT-4471902.",
                "Insured: Demo Holder. Vehicle: Example Hatchback 2021.",
                "Registration: KA-01-SY-0000.",
                f"Policy Start Date: {iso(-343)}. "
                f"Policy Expiry Date: {iso(22)}.",
                "Own Damage Cover: Rs. 480,000.00. Third Party: Unlimited.",
                "Renewal is required before the expiry date to avoid a break "
                "in cover.",
            ],
        ),
        (
            "health_insurance_policy.pdf",
            "Family Health Insurance Policy (Synthetic Copy)",
            [
                "Policy Number: SYNTH-HLT-8820045.",
                "Primary Insured: Demo Holder. Sum Insured: Rs. 1,000,000.00.",
                f"Policy Start Date: {iso(-240)}. "
                f"Policy Expiry Date: {iso(125)}.",
                "Room Rent Limit: Single private room. Waiting Period: 30 days.",
                "Covers hospitalisation, day care procedures and pre-existing "
                "conditions after the waiting period.",
            ],
        ),
        (
            "laptop_warranty_hp.pdf",
            "HP Laptop Limited Hardware Warranty (Synthetic Copy)",
            [
                "Product: HP Pavilion 14. Serial Number: SYNTH-HP-5X29T.",
                f"Purchase Date: {iso(-297)}. "
                f"Warranty Expires: {iso(68)}.",
                "Coverage: hardware repair and replacement of manufacturing "
                "defects. Accidental damage is not covered.",
                "Retain the original invoice when raising a claim.",
            ],
        ),
        (
            "laptop_invoice_hp.pdf",
            "Invoice SYNTH-INV-HP-77120",
            [
                "Invoice Number: SYNTH-INV-HP-77120.",
                f"Invoice Date: {iso(-297)}.",
                "Item: HP Pavilion 14 laptop. Quantity: 1.",
                "Total: Rs. 68,990.00. Payment Status: Paid.",
                "Seller: Example Electronics Private Limited, Bengaluru.",
            ],
        ),
        # --- education ------------------------------------------------
        (
            "degree_certificate.pdf",
            "Bachelor of Engineering - Degree Certificate (Synthetic Copy)",
            [
                "Certificate Number: SYNTH-DEG-2025-11904.",
                "Name: Demo Holder. Branch: Artificial Intelligence and "
                "Data Science.",
                f"Date of Award: {iso(-120)}. Class: First Class with "
                "Distinction.",
                "Awarded by Example Institute of Technology, Bengaluru.",
            ],
        ),
        (
            "class_10_marks_card.pdf",
            "Secondary School Examination - Marks Card (Synthetic Copy)",
            [
                "Register Number: SYNTH-SSLC-448120.",
                "Name: Demo Holder. Year of Examination: 2019.",
                "Total Marks: 587 out of 625. Result: Pass with Distinction.",
                "Issued by the Example State Examination Board.",
            ],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "LifeVaultDemo",
        help="where to write the documents (default: ~/LifeVaultDemo)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete the output folder first",
    )
    args = parser.parse_args()

    output = args.output.expanduser()
    if args.clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    today = date.today()
    documents = build_documents(today)
    for filename, title, body in documents:
        make_pdf(output / filename, title, body)

    # One duplicate in a subfolder, so the "also found at" collapse has
    # something real to demonstrate on this corpus too.
    subfolder = output / "scanned copies"
    subfolder.mkdir(exist_ok=True)
    shutil.copy2(output / "passport_scan.pdf", subfolder / "passport_scan_copy.pdf")

    print(f"Generated {len(documents)} documents (+1 duplicate) in {output}")
    print("\nExpiry dates land in these windows, relative to today:")
    print("  ~22 days  car_insurance_policy.pdf        -> 30-day window")
    print("  ~43 days  driving_licence.pdf             -> 60-day window")
    print("  ~68 days  laptop_warranty_hp.pdf          -> 90-day window")
    print("  ~125 days health_insurance_policy.pdf     -> 1-year window")
    print("  ~168 days passport_scan.pdf               -> 1-year window")
    print("  already expired: rental_agreement_expired.pdf")
    print("\nNext:")
    print(f"  LIFEVAULT_USE_FIXTURES=false python scripts/index_folder.py {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
