"""
Domain Service: TaxCalculationService.

Computes VAT amounts for a PurchaseItem based on its TaxType. A Domain
Service, not a method on PurchaseItem itself, because the actual VAT
rate is a piece of tax-authority knowledge (domain.constants.TAX_RATE_BY_TYPE)
that does not belong to any single entity -- exactly the kind of
"business logic that does not naturally belong to a single entity"
Stage 04 asks Domain Services to hold.
"""

from __future__ import annotations

from decimal import Decimal

from pharmacy_invoice_automation.domain.constants import TAX_RATE_BY_TYPE
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.value_objects.money import Money


class TaxCalculationService:
    """Computes tax amounts for a given base amount and TaxType."""

    def calculate_tax_amount(self, base_amount: Money, tax_type: TaxType) -> Money:
        """Return the VAT amount owed on ``base_amount`` at ``tax_type``'s rate."""
        rate: Decimal = TAX_RATE_BY_TYPE[tax_type.value]
        return base_amount.multiply(rate)

    def calculate_total_with_tax(self, base_amount: Money, tax_type: TaxType) -> Money:
        """Return ``base_amount`` plus its computed tax at ``tax_type``'s rate."""
        return base_amount + self.calculate_tax_amount(base_amount, tax_type)
