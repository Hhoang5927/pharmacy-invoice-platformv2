"""
Domain Constants.

Centralizes business-rule constants referenced by more than one
domain module, so they are declared once rather than duplicated as
magic literals across multiple files.
"""

from __future__ import annotations

from decimal import Decimal

from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus

# --- Medicine code sequencing ---
# Business Rules: "Ma thuoc: TH1, TH2, TH3... Sinh tu dong va khong trung."
# Consumed by services.medicine_validation_service.MedicineValidationService.
MEDICINE_CODE_PREFIX: str = "TH"
MEDICINE_CODE_FIRST_SEQUENCE_NUMBER: int = 1

# --- Total consistency tolerance ---
# Consumed by services.price_policy.PricePolicy.check_total_consistency.
# Sum of invoice item totals is allowed to differ from the OCR'd grand
# total by up to this fraction before being flagged for manual review,
# to absorb minor rounding differences without over-flagging.
TOTAL_CONSISTENCY_RELATIVE_TOLERANCE: Decimal = Decimal("0.01")  # 1%

# --- Vietnamese VAT rates by TaxType ---
# Consumed by services.tax_calculation_service.TaxCalculationService.
TAX_RATE_BY_TYPE: dict[str, Decimal] = {
    "standard": Decimal("0.10"),
    "reduced": Decimal("0.05"),
    "exempt": Decimal("0.00"),
    "eight_percent": Decimal("0.08"),  # Deviation D5 fix (PO-confirmed 2026-08)
    "other": Decimal("0.00"),  # unknown rate -- treated as 0 until manually confirmed
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

# --- Default currency (value_objects.money.Money) ---
DEFAULT_CURRENCY: str = "VND"
