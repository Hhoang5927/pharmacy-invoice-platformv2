"""
Value Object: OCRResult.

The full, immutable result of one OCR extraction attempt against an
invoice image (Technical Design Document Section 7.4). Represents "the
extractor's best reading of the image," not yet a validated
PurchaseInvoice -- business validation happens afterward, in
validators.invoice_validator.InvoiceValidator and
services.invoice_calculation_service.InvoiceCalculationService.

Formalized here as a genuine Value Object per Stage 04 (previously this
data shape lived only as a supporting DTO next to the OCR port
interface).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus


@dataclass(frozen=True)
class OCRLineItem:
    """
    One raw, mechanically-normalized medicine line as extracted from
    the image. Numeric/date text has already been parsed into the
    correct Python type; any field the extractor could not confidently
    read is None.
    """

    raw_medicine_name: str | None
    raw_batch_number: str | None
    raw_expiry_date: date | None
    raw_unit_text: str | None
    raw_quantity: Decimal | None
    raw_unit_price: Decimal | None
    raw_line_total: Decimal | None


@dataclass(frozen=True)
class OCRResult:
    """The complete, immutable result of one invoice image's OCR extraction."""

    status: OCRStatus
    raw_invoice_number: str | None
    raw_invoice_date: date | None
    raw_supplier_name: str | None
    raw_supplier_tax_code: str | None
    raw_supplier_address: str | None
    raw_prescription_classification_text: str | None
    raw_grand_total: Decimal | None
    lines: tuple[OCRLineItem, ...]
    overall_confidence: float
    field_confidences: dict[str, float] = field(default_factory=dict)
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        """True if extraction produced usable data (status is not FAILED)."""
        return self.status is not OCRStatus.FAILED

    @property
    def needs_manual_review(self) -> bool:
        """True if extraction succeeded but confidence was low, or a line is missing key data."""
        return self.status is OCRStatus.NEEDS_REVIEW
