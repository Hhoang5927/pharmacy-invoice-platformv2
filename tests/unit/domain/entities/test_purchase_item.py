"""
Unit tests for domain.entities.purchase_item.PurchaseItem, focused on
Part 3's additive retail_units_per_purchase_unit field (the resolved
Vien-per-purchase-unit conversion factor
pipeline.party_matching_step.PartyMatchingStep sets and
infrastructure.automation.playwright_adapter reads at fill time) -- not
a full re-test of the whole entity.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.exceptions.invalid_invoice_error import (
    InvalidInvoiceError,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit


def _make_item(**overrides: object) -> PurchaseItem:
    defaults: dict[str, object] = {
        "id": "item-1",
        "medicine_name": "Paracetamol 500mg",
        "unit": Unit(code="hop"),
        "quantity": Quantity(Decimal("10")),
        "unit_price": Money(Decimal("100000")),
    }
    defaults.update(overrides)
    return PurchaseItem(**defaults)  # type: ignore[arg-type]


class TestRetailUnitsPerPurchaseUnitConstruction:
    def test_defaults_to_none(self) -> None:
        item = _make_item()
        assert item.retail_units_per_purchase_unit is None

    def test_accepts_a_positive_integer(self) -> None:
        item = _make_item(retail_units_per_purchase_unit=10)
        assert item.retail_units_per_purchase_unit == 10

    def test_rejects_zero(self) -> None:
        with pytest.raises(InvalidInvoiceError):
            _make_item(retail_units_per_purchase_unit=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(InvalidInvoiceError):
            _make_item(retail_units_per_purchase_unit=-3)


class TestAssignRetailUnitsPerPurchaseUnit:
    def test_sets_the_value(self) -> None:
        item = _make_item()

        item.assign_retail_units_per_purchase_unit(10)

        assert item.retail_units_per_purchase_unit == 10

    def test_overwrites_an_existing_value(self) -> None:
        item = _make_item(retail_units_per_purchase_unit=10)

        item.assign_retail_units_per_purchase_unit(20)

        assert item.retail_units_per_purchase_unit == 20

    def test_rejects_zero(self) -> None:
        item = _make_item()
        with pytest.raises(InvalidInvoiceError):
            item.assign_retail_units_per_purchase_unit(0)

    def test_rejects_negative(self) -> None:
        item = _make_item()
        with pytest.raises(InvalidInvoiceError):
            item.assign_retail_units_per_purchase_unit(-1)


class TestConfirmedWebsiteUnitRatioConstruction:
    def test_defaults_to_none(self) -> None:
        item = _make_item()
        assert item.confirmed_website_unit_ratio is None

    def test_accepts_a_positive_decimal(self) -> None:
        item = _make_item(confirmed_website_unit_ratio=Decimal("1"))
        assert item.confirmed_website_unit_ratio == Decimal("1")

    def test_rejects_zero(self) -> None:
        with pytest.raises(InvalidInvoiceError):
            _make_item(confirmed_website_unit_ratio=Decimal("0"))

    def test_rejects_negative(self) -> None:
        with pytest.raises(InvalidInvoiceError):
            _make_item(confirmed_website_unit_ratio=Decimal("-1"))


class TestAssignConfirmedWebsiteUnitRatio:
    def test_sets_the_value(self) -> None:
        item = _make_item()

        item.assign_confirmed_website_unit_ratio(Decimal("1"))

        assert item.confirmed_website_unit_ratio == Decimal("1")

    def test_overwrites_an_existing_value(self) -> None:
        item = _make_item(confirmed_website_unit_ratio=Decimal("1"))

        item.assign_confirmed_website_unit_ratio(Decimal("10"))

        assert item.confirmed_website_unit_ratio == Decimal("10")

    def test_rejects_zero(self) -> None:
        item = _make_item()
        with pytest.raises(InvalidInvoiceError):
            item.assign_confirmed_website_unit_ratio(Decimal("0"))

    def test_rejects_negative(self) -> None:
        item = _make_item()
        with pytest.raises(InvalidInvoiceError):
            item.assign_confirmed_website_unit_ratio(Decimal("-1"))
