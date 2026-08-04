"""
Entity: Medicine.

Represents a catalog medicine known to the pharmacy system, whether
prescription or over-the-counter. Identity is its ``id``; the
``medicine_code`` (e.g. "TH1") is a separate, system-generated business
identifier -- see services.medicine_validation_service.

References its Manufacturer by id (manufacturer_id), rather than
embedding a Manufacturer directly -- Manufacturer is its own aggregate
root with its own repository.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.value_objects.unit import Unit


@dataclass(eq=False)
class Medicine:
    """A catalog medicine."""

    id: str
    medicine_code: str
    name: str
    medicine_type: MedicineType
    unit: Unit
    manufacturer_id: str | None = None
    specification: str | None = None  # packaging description ("quy cach")
    retail_units_per_purchase_unit: int | None = None
    """
    How many Vien (retail tablets) make up one purchase unit for this
    medicine -- "hoc 1 lan, nho mai mai" (Part 3, PO-confirmed 2026-08):
    learned once (from an OCR reading or a reviewer's confirmation) and
    reused for every later invoice, never re-derived or re-guessed. None
    until known.
    """
    website_catalog_code: str | None = None
    """
    The real, unique site-side catalog identifier (SDK) of the exact
    catalog row a human -- or an automated narrow-then-confirm flow --
    has already confirmed for this Medicine on webnhathuoc.com. Same
    "hoc 1 lan, nho mai mai" pattern as retail_units_per_purchase_unit
    (PO-confirmed 2026-08): the site's own display NAME is not unique
    (the same name, e.g. "Naphacogyl", can appear on multiple distinct
    catalog rows for different manufacturers/packagings) -- the site's
    own SDK code is. None until a real selection has actually been
    confirmed.
    """

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Medicine id cannot be empty.")
        if not self.medicine_code or not self.medicine_code.strip():
            raise ValidationError("Medicine code cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValidationError("Medicine name cannot be empty.")
        self.medicine_code = self.medicine_code.strip()
        self.name = self.name.strip()
        if (
            self.retail_units_per_purchase_unit is not None
            and self.retail_units_per_purchase_unit <= 0
        ):
            raise ValidationError(
                f"retail_units_per_purchase_unit must be a positive integer, got "
                f"{self.retail_units_per_purchase_unit}."
            )
        if self.website_catalog_code is not None:
            self.website_catalog_code = self.website_catalog_code.strip()
            if not self.website_catalog_code:
                raise ValidationError("website_catalog_code cannot be blank if provided.")

    def assign_manufacturer(self, manufacturer_id: str) -> None:
        """Record which Manufacturer produces this medicine."""
        if not manufacturer_id:
            raise ValidationError("manufacturer_id cannot be empty.")
        self.manufacturer_id = manufacturer_id

    def assign_retail_units_per_purchase_unit(self, retail_units_per_purchase_unit: int) -> None:
        """Record how many Vien make up one purchase unit, once learned."""
        if retail_units_per_purchase_unit <= 0:
            raise ValidationError(
                f"retail_units_per_purchase_unit must be a positive integer, got "
                f"{retail_units_per_purchase_unit}."
            )
        self.retail_units_per_purchase_unit = retail_units_per_purchase_unit

    def assign_website_catalog_code(self, website_catalog_code: str) -> None:
        """Record the confirmed, unique site catalog code (SDK) for this Medicine, once known."""
        if not website_catalog_code or not website_catalog_code.strip():
            raise ValidationError("website_catalog_code cannot be empty.")
        self.website_catalog_code = website_catalog_code.strip()

    @property
    def is_ready_for_automation(self) -> bool:
        """
        True if this Medicine has every field the Create Medicine
        website workflow requires (code, name, medicine_type, unit) --
        see validators.medicine_validator.MedicineValidator for the
        full validation report this property summarizes.
        """
        return bool(self.medicine_code and self.name and self.medicine_type and self.unit)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Medicine):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
