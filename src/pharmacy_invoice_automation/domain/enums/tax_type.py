"""
Enum: TaxType.

Vietnamese VAT category applied when computing tax on a PurchaseItem,
via services.tax_calculation_service.TaxCalculationService. Distinct
from value_objects.tax_code.TaxCode, which identifies a *supplier's*
tax registration number, not a goods/VAT category.
"""

from __future__ import annotations

from enum import Enum


class TaxType(str, Enum):
    """VAT category for tax calculation purposes."""

    STANDARD = "standard"    # 10% -- most goods
    REDUCED = "reduced"      # 5% -- certain essential goods
    EXEMPT = "exempt"        # 0% -- some medical goods are VAT-exempt
    OTHER = "other"          # non-standard rate; flagged for manual confirmation
