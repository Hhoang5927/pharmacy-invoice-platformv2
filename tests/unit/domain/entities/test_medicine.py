"""
Unit tests for domain.entities.medicine.Medicine, focused on Part 3's
additive retail_units_per_purchase_unit field ("hoc 1 lan, nho mai
mai" packaging-ratio memory) -- not a full re-test of the whole entity.
"""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit


def _make_medicine(**overrides: object) -> Medicine:
    defaults: dict[str, object] = {
        "id": "med-1",
        "medicine_code": "TH1",
        "name": "Paracetamol 500mg",
        "medicine_type": MedicineType.OVER_THE_COUNTER,
        "unit": Unit(code="vien"),
    }
    defaults.update(overrides)
    return Medicine(**defaults)  # type: ignore[arg-type]


class TestRetailUnitsPerPurchaseUnitConstruction:
    def test_defaults_to_none(self) -> None:
        medicine = _make_medicine()
        assert medicine.retail_units_per_purchase_unit is None

    def test_accepts_a_positive_integer(self) -> None:
        medicine = _make_medicine(retail_units_per_purchase_unit=100)
        assert medicine.retail_units_per_purchase_unit == 100

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            _make_medicine(retail_units_per_purchase_unit=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            _make_medicine(retail_units_per_purchase_unit=-5)


class TestAssignRetailUnitsPerPurchaseUnit:
    def test_sets_the_value(self) -> None:
        medicine = _make_medicine()

        medicine.assign_retail_units_per_purchase_unit(100)

        assert medicine.retail_units_per_purchase_unit == 100

    def test_overwrites_an_existing_value(self) -> None:
        medicine = _make_medicine(retail_units_per_purchase_unit=10)

        medicine.assign_retail_units_per_purchase_unit(20)

        assert medicine.retail_units_per_purchase_unit == 20

    def test_rejects_zero(self) -> None:
        medicine = _make_medicine()
        with pytest.raises(ValidationError):
            medicine.assign_retail_units_per_purchase_unit(0)

    def test_rejects_negative(self) -> None:
        medicine = _make_medicine()
        with pytest.raises(ValidationError):
            medicine.assign_retail_units_per_purchase_unit(-1)


class TestWebsiteCatalogCodeConstruction:
    def test_defaults_to_none(self) -> None:
        medicine = _make_medicine()
        assert medicine.website_catalog_code is None

    def test_accepts_a_code(self) -> None:
        medicine = _make_medicine(website_catalog_code="893115102724")
        assert medicine.website_catalog_code == "893115102724"

    def test_strips_whitespace(self) -> None:
        medicine = _make_medicine(website_catalog_code="  893115102724  ")
        assert medicine.website_catalog_code == "893115102724"

    def test_rejects_blank_string(self) -> None:
        with pytest.raises(ValidationError):
            _make_medicine(website_catalog_code="   ")


class TestAssignWebsiteCatalogCode:
    def test_sets_the_value(self) -> None:
        medicine = _make_medicine()

        medicine.assign_website_catalog_code("893115102724")

        assert medicine.website_catalog_code == "893115102724"

    def test_overwrites_an_existing_value(self) -> None:
        medicine = _make_medicine(website_catalog_code="893100160624")

        medicine.assign_website_catalog_code("893110391924")

        assert medicine.website_catalog_code == "893110391924"

    def test_strips_whitespace(self) -> None:
        medicine = _make_medicine()

        medicine.assign_website_catalog_code("  893115102724  ")

        assert medicine.website_catalog_code == "893115102724"

    def test_rejects_empty_string(self) -> None:
        medicine = _make_medicine()
        with pytest.raises(ValidationError):
            medicine.assign_website_catalog_code("")

    def test_rejects_blank_string(self) -> None:
        medicine = _make_medicine()
        with pytest.raises(ValidationError):
            medicine.assign_website_catalog_code("   ")
