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
    raw_retail_units_per_purchase_unit: int | None = None
    """
    How many retail units (Vien) make up one purchase unit (e.g. Hop/Vi),
    ONLY when the invoice itself states this unambiguously (e.g. "Hop 10
    vi x 10 vien" = 100) -- None whenever the text is absent, or present
    but insufficient to compute a definite count (e.g. "(1 vi)" alone
    does not say how many Vien are in that Vi). See
    infrastructure.ocr.prompt_templates.invoice_extraction_prompt_v1's
    packaging-ratio rule for the exact extraction contract.
    """
    raw_vat_percentage: Decimal | None = None
    """
    The VAT/tax percentage printed for this line (e.g. Decimal("5") for
    "5%"), ONLY when the invoice prints a VAT column/value for this
    line -- None whenever it is absent, never computed or assumed
    (Part 3.1, PO-confirmed 2026-08). Classified into a
    enums.tax_type.TaxType downstream, via TaxType.from_raw_percentage,
    once actually read.
    """


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
    raw_commercial_discount_amount: Decimal | None = None
    """
    The whole-invoice commercial discount ("Giam Tru CKTM" / "Chiet khau
    thuong mai" / "Giam tru...", PO-confirmed 2026-08), when the invoice
    prints it as its own summary row rather than as a real medicine
    line -- e.g. Traphaco invoices print a row like "Giam Tru CKTM TS 5%
    (CKT: 28,198)" with its own pre-tax amount in the same "Thanh tien"
    column every real line uses. This is the pre-tax amount from that
    column (the same meaning as OCRLineItem.raw_line_total), NEVER the
    tax-inclusive parenthetical annotation some suppliers also print,
    and NEVER computed/inferred from a grand-total mismatch. None
    whenever the invoice does not state this distinctly. This row is
    NOT one of ``lines`` -- see
    infrastructure.ocr.prompt_templates.invoice_extraction_prompt_v1's
    extraction rule for how it is told apart from a real medicine line.
    """

    @property
    def succeeded(self) -> bool:
        """True if extraction produced usable data (status is not FAILED)."""
        return self.status is not OCRStatus.FAILED

    @property
    def needs_manual_review(self) -> bool:
        """True if extraction succeeded but confidence was low, or a line is missing key data."""
        return self.status is OCRStatus.NEEDS_REVIEW
