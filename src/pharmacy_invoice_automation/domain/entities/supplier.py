"""
Entity: Supplier.

Represents a pharmacy purchase invoice's supplier. Identity is its
``id``; two Supplier instances with the same id represent the same
supplier even if other fields differ (e.g. one is a stale in-memory
copy) -- see the identity-based __eq__/__hash__ below (Entity Pattern).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.value_objects.address import Address
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode


@dataclass(eq=False)
class Supplier:
    """A pharmacy purchase invoice supplier."""

    id: str
    name: str
    tax_code: TaxCode | None = None
    address: Address | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Supplier id cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValidationError("Supplier name cannot be empty.")
        self.name = self.name.strip()

    def update_contact_info(
        self, *, address: Address | None = None, phone: str | None = None
    ) -> None:
        """Update address and/or phone, leaving unspecified fields unchanged."""
        if address is not None:
            self.address = address
        if phone is not None:
            self.phone = phone

    @property
    def is_ready_for_automation(self) -> bool:
        """
        True if this Supplier has every field the Create Supplier
        website workflow requires (name, address, phone, tax_code) --
        see validators.supplier_validator.SupplierValidator for the
        full validation report this property summarizes.
        """
        return bool(self.name and self.address and self.phone and self.tax_code)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Supplier):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
