"""
Unit tests for domain.enums.tax_type.TaxType.from_raw_percentage
(Part 3.1, PO-confirmed 2026-08): maps an OCR-extracted VAT percentage
onto its TaxType category, so the VAT-based supplement/non-medicine
classification (services.supplement_classification_service.SupplementClassificationService)
can actually work from real invoice data instead of always seeing None.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.enums.tax_type import TaxType

pytestmark = pytest.mark.unit


class TestFromRawPercentage:
    def test_5_percent_maps_to_reduced(self) -> None:
        assert TaxType.from_raw_percentage(Decimal("5")) is TaxType.REDUCED

    def test_5_00_decimal_form_also_maps_to_reduced(self) -> None:
        # Decimal("5.00") == Decimal("5") -- value equality, not
        # representation equality -- so Gemini's exact string form
        # ("5" vs "5.00") must not matter.
        assert TaxType.from_raw_percentage(Decimal("5.00")) is TaxType.REDUCED

    def test_10_percent_maps_to_standard(self) -> None:
        assert TaxType.from_raw_percentage(Decimal("10")) is TaxType.STANDARD

    def test_0_percent_maps_to_exempt(self) -> None:
        assert TaxType.from_raw_percentage(Decimal("0")) is TaxType.EXEMPT

    @pytest.mark.parametrize("percentage", ["8", "8.00"])
    def test_8_percent_maps_to_eight_percent(self, percentage: str) -> None:
        # Deviation D5 fix (PO-confirmed 2026-08): 8% used to fall into
        # OTHER (silently defaulting to a 0% tax rate) -- it now gets
        # its own category with its own real rate.
        assert TaxType.from_raw_percentage(Decimal(percentage)) is TaxType.EIGHT_PERCENT

    @pytest.mark.parametrize("percentage", ["12", "3.5", "100"])
    def test_any_other_percentage_maps_to_other(self, percentage: str) -> None:
        assert TaxType.from_raw_percentage(Decimal(percentage)) is TaxType.OTHER

    def test_never_raises_for_an_unusual_value(self) -> None:
        # A wildly out-of-range percentage is still just OTHER, not an
        # exception -- an unusual invoice must never crash extraction
        # over this one field.
        assert TaxType.from_raw_percentage(Decimal("-1")) is TaxType.OTHER
