"""
Pipeline Step: InvoiceValidationStep.

Coordinates validation (Stage 05 requirement #12: "Application
orchestrates. Domain validates."). Every actual rule -- completeness,
total consistency -- is Domain's (validators.InvoiceValidator,
services.PricePolicy, services.InvoiceCalculationService); this step
only sequences those calls and aggregates their findings into one flat
list of issues for the caller to act on.
"""

from __future__ import annotations

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.services.invoice_calculation_service import (
    InvoiceCalculationService,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult


class InvoiceValidationStep:
    """Coordinates Domain-level validation of an invoice's completeness and totals."""

    def __init__(
        self,
        invoice_validator: InvoiceValidator,
        invoice_calculation_service: InvoiceCalculationService,
        price_policy: PricePolicy,
    ) -> None:
        self._invoice_validator = invoice_validator
        self._invoice_calculation_service = invoice_calculation_service
        self._price_policy = price_policy

    def execute(
        self,
        invoice: PurchaseInvoice,
        ocr_result: OCRResult,
        excluded_supplement_total: Money | None = None,
    ) -> tuple[str, ...]:
        """
        Return every completeness/consistency issue found, empty if
        there are none. ``excluded_supplement_total`` (Deviation D10
        fix, PO-confirmed 2026-08) is
        pipeline.party_matching_step.PartyMatchingOutcome's own field --
        the tax-inclusive value of every line already removed from
        ``invoice`` for having VAT != 5%, which the caller
        (use_cases.process_invoice_use_case.ProcessInvoiceUseCase) must
        pass through so this step's total-consistency check accounts
        for that deliberate, correct removal instead of misreading it
        as a mismatch.
        """
        issues: list[str] = list(self._invoice_validator.validate(invoice).unwrap().issues)

        if ocr_result.raw_grand_total is not None and (
            invoice.items or excluded_supplement_total is not None
        ):
            stated = Money(ocr_result.raw_grand_total, invoice.calculate_item_total_sum().currency)
            try:
                reconciled = self._invoice_calculation_service.calculate_reconciled_grand_total(
                    invoice, excluded_supplement_total
                )
            except ValidationError as error:
                grand_total = self._invoice_calculation_service.calculate_grand_total_with_tax(
                    invoice
                )
                issues.append(
                    f"Invoice's commercial discount ({invoice.commercial_discount_amount}) "
                    f"exceeds its calculated grand total ({grand_total}): {error.message}"
                )
            else:
                if not self._price_policy.check_total_consistency(reconciled, stated):
                    adjustment_notes = []
                    if invoice.commercial_discount_amount is not None:
                        adjustment_notes.append("deducting the invoice's commercial discount")
                    if excluded_supplement_total is not None:
                        adjustment_notes.append(
                            f"adding back {excluded_supplement_total} for line(s) correctly "
                            f"excluded because VAT != 5%"
                        )
                    adjustment_note = (
                        f" (after {', '.join(adjustment_notes)})" if adjustment_notes else ""
                    )
                    issues.append(
                        f"Stated grand total ({stated}) does not reconcile with the "
                        f"calculated grand total (with tax){adjustment_note} ({reconciled})."
                    )

        return tuple(issues)
