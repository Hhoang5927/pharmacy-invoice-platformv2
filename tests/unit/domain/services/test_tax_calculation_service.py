"""
Unit tests for domain.services.tax_calculation_service.TaxCalculationService,
focused on Deviation D5's fix (PO-confirmed 2026-08): TaxType.EIGHT_PERCENT
now computes a real 8% tax instead of silently defaulting to 0% via OTHER.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.services.tax_calculation_service import (
    TaxCalculationService,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money

pytestmark = pytest.mark.unit


@pytest.fixture()
def service() -> TaxCalculationService:
    return TaxCalculationService()


class TestEightPercentTax:
    def test_calculates_a_real_8_percent_tax_amount(
        self, service: TaxCalculationService
    ) -> None:
        # Real Traphaco invoice.pdf line ("Slaska New"): pre-tax amount
        # 76,364 at TS 8% -> printed VAT amount 6,109.
        base = Money(Decimal("76364"))

        tax = service.calculate_tax_amount(base, TaxType.EIGHT_PERCENT)

        assert tax.amount == Decimal("6109")

    def test_total_with_tax_adds_the_8_percent_amount(
        self, service: TaxCalculationService
    ) -> None:
        base = Money(Decimal("76364"))

        total = service.calculate_total_with_tax(base, TaxType.EIGHT_PERCENT)

        assert total.amount == Decimal("82473")

    def test_other_still_defaults_to_zero_unlike_eight_percent(
        self, service: TaxCalculationService
    ) -> None:
        # OTHER is still the genuine "unknown/unusual rate" fallback --
        # this fix must not have quietly changed OTHER's own behavior.
        base = Money(Decimal("76364"))

        total = service.calculate_total_with_tax(base, TaxType.OTHER)

        assert total.amount == base.amount
