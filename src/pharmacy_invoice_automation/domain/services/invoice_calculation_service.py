"""
Domain Service: InvoiceCalculationService.

Computes derived, cross-item totals for a PurchaseInvoice, combining
the aggregate's own item-sum (PurchaseInvoice.calculate_item_total_sum,
an entity-level computation over its own children -- kept on the
entity itself to avoid an anemic PurchaseInvoice) with tax calculation
(via TaxCalculationService, a *different* domain concern the invoice
should not need to know about directly).
"""

from __future__ import annotations

from decimal import Decimal

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.services.tax_calculation_service import (
    TaxCalculationService,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money


class InvoiceCalculationService:
    """Computes derived totals for a PurchaseInvoice, including tax."""

    def __init__(self, tax_calculation_service: TaxCalculationService | None = None) -> None:
        self._tax_calculation_service = tax_calculation_service or TaxCalculationService()

    def calculate_grand_total_with_tax(self, invoice: PurchaseInvoice) -> Money:
        """
        Sum every item's (line_total + its computed tax, where the item
        has a tax_type) into one grand total. Items with no tax_type
        contribute only their line_total.
        """
        currency = invoice.items[0].unit_price.currency if invoice.items else "VND"
        total = Money(amount=Decimal("0"), currency=currency)
        for item in invoice.items:
            if item.tax_type is not None:
                total = total + self._tax_calculation_service.calculate_total_with_tax(
                    item.line_total, item.tax_type
                )
            else:
                total = total + item.line_total
        return total

    def calculate_reconciled_grand_total(
        self, invoice: PurchaseInvoice, excluded_supplement_total: Money | None = None
    ) -> Money:
        """
        ``calculate_grand_total_with_tax(invoice)``, minus the invoice's
        whole-invoice commercial discount (``commercial_discount_amount``
        -- "Giam Tru CKTM", PO-confirmed 2026-08), plus
        ``excluded_supplement_total`` back on top, when given. This is
        what pipeline.invoice_validation_step.InvoiceValidationStep
        reconciles against the invoice's OCR'd stated grand total --
        deliberately tax-INCLUSIVE on both sides (a real Vietnamese VAT
        invoice's own "Tong cong" is always tax-inclusive; comparing it
        against a tax-exclusive item sum was a real, separate bug, fixed
        together with Deviation D5's TaxType.EIGHT_PERCENT addition,
        since an invoice with 8% lines would otherwise still miscompute
        here even with the tax-inclusive comparison in place).

        ``excluded_supplement_total`` (Deviation D10 fix, PO-confirmed
        2026-08, final -- no exceptions): pipeline.party_matching_step.
        PartyMatchingStep permanently removes any line whose VAT isn't
        exactly 5% from ``invoice.items`` before this ever runs -- a
        deliberate, correct business rule, not an anomaly. The invoice's
        stated grand total was never adjusted for that removal (it is
        the ORIGINAL, full invoice total), so it must be reconciled
        against (remaining items, with tax, minus CKTM) PLUS the value
        of what was legitimately excluded -- not against the remaining
        items alone, which would under-count by exactly the excluded
        lines' value and falsely report "does not reconcile" for
        entirely expected, correct filtering.

        commercial_discount_amount itself is the CKTM row's PRE-TAX
        amount (see OCRResult.raw_commercial_discount_amount) -- its own
        VAT portion is not separately tracked (the row is deliberately
        never modeled as a PurchaseItem, so it has no tax_type), so this
        slightly under-deducts by that row's own tax amount. Left as-is
        rather than adding another OCR field for it: the residual is
        small relative to a whole invoice and is absorbed by
        PricePolicy's existing tolerance (see
        test_invoice_calculation_service.py's real-invoice-derived
        numbers) -- revisit only if a real invoice is found where it
        is not absorbed.

        CKTM is a deduction against the WHOLE invoice, never against
        any one item's own line_total, so it cannot be folded into any
        PurchaseItem.

        Raises ValidationError (via Money's own invariant) if the
        discount exceeds the grand total -- a genuine data anomaly, not
        silently clamped to zero.
        """
        calculated = self.calculate_grand_total_with_tax(invoice)
        if invoice.commercial_discount_amount is not None:
            discount = invoice.commercial_discount_amount
            if discount.currency != calculated.currency:
                raise ValidationError(
                    f"commercial_discount_amount currency ({discount.currency}) does not "
                    f"match the invoice's grand total currency ({calculated.currency})."
                )
            calculated = Money(
                amount=calculated.amount - discount.amount, currency=calculated.currency
            )
        if excluded_supplement_total is not None:
            if excluded_supplement_total.currency != calculated.currency:
                raise ValidationError(
                    f"excluded_supplement_total currency ({excluded_supplement_total.currency}) "
                    f"does not match the invoice's grand total currency "
                    f"({calculated.currency})."
                )
            calculated = calculated + excluded_supplement_total
        return calculated
