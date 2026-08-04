"""
Pipeline Step: InvoiceExtractionStep.

Calls domain.ports.services.OCRProvider to extract structured data from
one invoice image, then applies that data onto the PurchaseInvoice
aggregate: parsing each raw field through Domain's own value objects
(Unit, Quantity, Money, ExpiryDate), so every invariant those value
objects already enforce is honored -- this step never bypasses them.

A line whose OCR data is too incomplete to build a valid PurchaseItem
(missing quantity, price, or medicine name) is skipped rather than
faked with a placeholder value, and recorded as an issue -- consistent
with Domain's own "never guess business data" philosophy.

Retry scope note: transient-failure retries for the OCR call happen
entirely inside this step, wrapped tightly around the one call to
domain.ports.services.OCRProvider.extract() that can actually raise
configuration.RetryPolicy-classified TransientInfrastructureError.
This is deliberate, not incidental: PurchaseInvoice.transition_to()
enforces a strictly linear state machine with only two retry cycles
(OcrFailed -> OcrInProgress and ImportFailed -> ReadyForImport) --
there is no path back from OcrDone to OcrInProgress. Retrying at the
batch_orchestrator.BatchOrchestrator level (re-running this whole Step
sequence after the invoice had already reached OcrDone) would attempt
an invalid transition. Scoping the retry to before any status
transition past OcrInProgress succeeds avoids that entirely: every
retry attempt happens while the invoice is still simply "OcrInProgress",
which is a stable, re-enterable state for as many attempts as
configuration.RetryPolicy allows.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from pharmacy_invoice_automation.application.configuration import RetryPolicy
from pharmacy_invoice_automation.application.exceptions import TransientInfrastructureError
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit


@dataclass(frozen=True)
class ExtractionOutcome:
    """Result of running one invoice image through OCR extraction."""

    ocr_result: OCRResult
    issues: tuple[str, ...]


class InvoiceExtractionStep:
    """Extracts structured data from an invoice image and applies it to the aggregate."""

    def __init__(self, ocr_provider: OCRProvider, retry_policy: RetryPolicy) -> None:
        self._ocr_provider = ocr_provider
        self._retry_policy = retry_policy

    def execute(self, invoice: PurchaseInvoice, image_bytes: bytes) -> ExtractionOutcome:
        """
        Run OCR extraction (retrying transient failures per
        ``self._retry_policy`` before the invoice ever leaves
        OcrInProgress) and, on success, populate ``invoice`` with every
        PurchaseItem line that could be confidently built. Transitions
        ``invoice`` to OCR_DONE or OCR_FAILED exactly once, after
        retries (if any) are resolved one way or the other.
        """
        invoice.transition_to(InvoiceStatus.OCR_IN_PROGRESS)
        ocr_result = self._extract_with_retry(image_bytes)

        issues: list[str] = []
        if ocr_result.succeeded:
            issues.extend(self._apply_header_fields(invoice, ocr_result))
            issues.extend(self._apply_lines(invoice, ocr_result))
            invoice.transition_to(InvoiceStatus.OCR_DONE)
        else:
            issues.append(
                ocr_result.failure_reason or "OCR extraction failed with no reason given."
            )
            invoice.transition_to(InvoiceStatus.OCR_FAILED)

        invoice.ocr_confidence = ocr_result.overall_confidence
        invoice.touch()

        return ExtractionOutcome(ocr_result=ocr_result, issues=tuple(issues))

    def _extract_with_retry(self, image_bytes: bytes) -> OCRResult:
        last_error: TransientInfrastructureError | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                return self._ocr_provider.extract(image_bytes)
            except TransientInfrastructureError as error:
                last_error = error
                if attempt < self._retry_policy.max_attempts:
                    time.sleep(self._retry_policy.compute_backoff_seconds(attempt + 1))

        return OCRResult(
            status=OCRStatus.FAILED,
            raw_invoice_number=None,
            raw_invoice_date=None,
            raw_supplier_name=None,
            raw_supplier_tax_code=None,
            raw_supplier_address=None,
            raw_prescription_classification_text=None,
            raw_grand_total=None,
            lines=(),
            overall_confidence=0.0,
            failure_reason=(
                f"OCR extraction failed after {self._retry_policy.max_attempts} attempt(s): "
                f"{last_error}"
            ),
        )

    def _apply_header_fields(self, invoice: PurchaseInvoice, ocr_result: OCRResult) -> list[str]:
        """
        Replace the invoice's provisional invoice_number/invoice_date
        (set at discovery time, before anything was known about the
        image) with what OCR actually found, when it found something.
        """
        issues: list[str] = []
        if ocr_result.raw_invoice_number and ocr_result.raw_invoice_number.strip():
            invoice.invoice_number = ocr_result.raw_invoice_number.strip()
        else:
            issues.append("No invoice number extracted; keeping placeholder, needs manual entry.")

        if ocr_result.raw_invoice_date is not None:
            invoice.invoice_date = ocr_result.raw_invoice_date
        else:
            issues.append("No invoice date extracted; keeping placeholder, needs manual entry.")

        if ocr_result.raw_commercial_discount_amount is not None:
            invoice.commercial_discount_amount = Money(ocr_result.raw_commercial_discount_amount)

        return issues

    def _apply_lines(self, invoice: PurchaseInvoice, ocr_result: OCRResult) -> list[str]:
        issues: list[str] = []
        for index, raw_line in enumerate(ocr_result.lines):
            if not raw_line.raw_medicine_name:
                issues.append(f"Line {index + 1}: no medicine name extracted; skipped.")
                continue
            if raw_line.raw_quantity is None or raw_line.raw_unit_price is None:
                issues.append(
                    f"Line {index + 1} ('{raw_line.raw_medicine_name}'): missing quantity "
                    f"or unit price; skipped, needs manual entry."
                )
                continue
            try:
                unit = Unit.from_raw_text(raw_line.raw_unit_text or "")
                tax_type = (
                    TaxType.from_raw_percentage(raw_line.raw_vat_percentage)
                    if raw_line.raw_vat_percentage is not None
                    else None
                )
                item = PurchaseItem(
                    id=str(uuid.uuid4()),
                    medicine_name=raw_line.raw_medicine_name,
                    unit=unit,
                    quantity=Quantity(raw_line.raw_quantity),
                    unit_price=Money(raw_line.raw_unit_price),
                    retail_units_per_purchase_unit=raw_line.raw_retail_units_per_purchase_unit,
                    tax_type=tax_type,
                )
            except ValidationError as error:
                issues.append(f"Line {index + 1} ('{raw_line.raw_medicine_name}'): {error.message}")
                continue
            invoice.add_item(item)
            if unit.requires_manual_confirmation:
                issues.append(
                    f"Line {index + 1} ('{raw_line.raw_medicine_name}'): unrecognized unit "
                    f"'{raw_line.raw_unit_text}', needs manual confirmation."
                )
        return issues
