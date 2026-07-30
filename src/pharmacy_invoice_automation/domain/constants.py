"""
Domain Constants.

Centralizes business-rule constants referenced by more than one
domain.rules validator, so they are declared once rather than
duplicated as magic literals across multiple files.

Note: this file did not appear as a separate entry in the
Implementation Specification's file-by-file listing (that document
was written before "Domain Constants" was called out as its own
deliverable, in Stage 04). Adding it is a minimal, transparent
extension of the already-approved domain.rules design -- every constant
below was already implied by name in the Technical Design Document and
Implementation Specification's descriptions of those rules; this file
just gives them one canonical home instead of scattering them as
literals inside each rule file.
"""

from __future__ import annotations

from decimal import Decimal

from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.unit_type import UnitType

# --- Medicine code sequencing ---
# Business Rules: "Ma thuoc: TH1, TH2, TH3... Sinh tu dong va khong trung."
MEDICINE_CODE_PREFIX: str = "TH"
MEDICINE_CODE_FIRST_SEQUENCE_NUMBER: int = 1

# --- Total consistency tolerance (domain.rules.total_consistency_rule) ---
# Sum of invoice line totals is allowed to differ from the OCR'd grand
# total by up to this fraction before being flagged for manual review,
# to absorb minor rounding differences without over-flagging.
TOTAL_CONSISTENCY_RELATIVE_TOLERANCE: Decimal = Decimal("0.01")  # 1%

# --- Unit text mapping (domain.rules.unit_mapping_rule) ---
# Business Rules: "Neu quy cach la vien -> Chon vien. Neu quy cach la
# tuyp -> Chon tuyp." Maps OCR-extracted, lowercased/stripped unit text
# to the system UnitType. Extend this mapping as new packaging types
# are encountered -- never hardcode a new unit string elsewhere.
UNIT_TEXT_TO_UNIT_TYPE: dict[str, UnitType] = {
    "vien": UnitType.VIEN,
    "viên": UnitType.VIEN,
    "tuyp": UnitType.TUYP,
    "tuýp": UnitType.TUYP,
    "hop": UnitType.HOP,
    "hộp": UnitType.HOP,
    "chai": UnitType.CHAI,
    "goi": UnitType.GOI,
    "gói": UnitType.GOI,
    "ong": UnitType.ONG,
    "ống": UnitType.ONG,
}

# --- Invoice status state machine ---
# Technical Design Document Section 12.4.
VALID_STATUS_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.PENDING: frozenset({InvoiceStatus.OCR_IN_PROGRESS}),
    InvoiceStatus.OCR_IN_PROGRESS: frozenset(
        {InvoiceStatus.OCR_DONE, InvoiceStatus.OCR_FAILED}
    ),
    InvoiceStatus.OCR_FAILED: frozenset({InvoiceStatus.OCR_IN_PROGRESS}),
    InvoiceStatus.OCR_DONE: frozenset({InvoiceStatus.UNDER_REVIEW}),
    InvoiceStatus.UNDER_REVIEW: frozenset({InvoiceStatus.READY_FOR_IMPORT}),
    InvoiceStatus.READY_FOR_IMPORT: frozenset({InvoiceStatus.IMPORT_IN_PROGRESS}),
    InvoiceStatus.IMPORT_IN_PROGRESS: frozenset(
        {InvoiceStatus.IMPORTED, InvoiceStatus.IMPORT_FAILED}
    ),
    InvoiceStatus.IMPORT_FAILED: frozenset({InvoiceStatus.READY_FOR_IMPORT}),
    InvoiceStatus.IMPORTED: frozenset(),  # terminal -- never re-entered (FR-15)
}

# --- Default currency (domain.value_objects.money.Money) ---
DEFAULT_CURRENCY: str = "VND"
