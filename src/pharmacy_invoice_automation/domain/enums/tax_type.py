"""
Enum: TaxType.

Vietnamese VAT category applied when computing tax on a PurchaseItem,
via services.tax_calculation_service.TaxCalculationService. Distinct
from value_objects.tax_code.TaxCode, which identifies a *supplier's*
tax registration number, not a goods/VAT category.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum


class TaxType(str, Enum):
    """VAT category for tax calculation purposes."""

    STANDARD = "standard"          # 10% -- most goods
    REDUCED = "reduced"            # 5% -- certain essential goods
    EXEMPT = "exempt"              # 0% -- some medical goods are VAT-exempt
    EIGHT_PERCENT = "eight_percent"
    """
    8% -- resolves Deviation D5 (PO-confirmed 2026-08): NOT the same
    kind of category as REDUCED. REDUCED (5%) is a permanent rate for a
    fixed set of essential goods; 8% is Vietnam's STANDARD (10%) rate
    temporarily cut by 2 points under economic-stimulus decrees
    (Nghi dinh 44/2023, 72/2024 and successors) -- named by its rate,
    not folded into REDUCED, to avoid implying it is the same kind of
    thing. Previously misclassified as OTHER (defaulting to a 0% rate)
    before this fix -- see domain.constants.TAX_RATE_BY_TYPE.
    """
    OTHER = "other"          # non-standard rate; flagged for manual confirmation

    @classmethod
    def from_raw_percentage(cls, percentage: Decimal) -> TaxType:
        """
        Map an OCR-extracted VAT percentage (e.g. ``Decimal("5")`` for
        "5%") to its TaxType category (Part 3.1, PO-confirmed 2026-08).
        Falls back to OTHER for any percentage that isn't exactly one
        of the four known rates -- never raises, so an unusual rate
        never blocks the line over this one field. Callers are
        responsible for handling a ``None`` percentage (VAT not read)
        themselves -- this method only classifies a percentage that was
        actually read.
        """
        if percentage == Decimal("5"):
            return cls.REDUCED
        if percentage == Decimal("10"):
            return cls.STANDARD
        if percentage == Decimal("0"):
            return cls.EXEMPT
        if percentage == Decimal("8"):
            return cls.EIGHT_PERCENT
        return cls.OTHER
