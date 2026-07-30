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

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
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
        total = Money(amount=0, currency=currency)
        for item in invoice.items:
            if item.tax_type is not None:
                total = total + self._tax_calculation_service.calculate_total_with_tax(
                    item.line_total, item.tax_type
                )
            else:
                total = total + item.line_total
        return total
