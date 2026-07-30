"""
Value Object: Address.

Represents a Supplier's address (Business Rules / Create Supplier
workflow: "Dia chi" is a required field). Kept deliberately simple --
a single validated free-text line plus an optional city -- since
Vietnamese business addresses on these invoices are not consistently
broken into strict administrative subdivisions (province/district/ward)
in the source data, and inventing that structure would go beyond what
any governing document actually specifies.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError


@dataclass(frozen=True)
class Address:
    """An immutable, validated address."""

    full_address: str
    city: str | None = None

    def __post_init__(self) -> None:
        if not self.full_address or not self.full_address.strip():
            raise ValidationError("Address full_address cannot be empty.")
        object.__setattr__(self, "full_address", self.full_address.strip())
        if self.city is not None:
            object.__setattr__(self, "city", self.city.strip() or None)

    def __str__(self) -> str:
        if self.city:
            return f"{self.full_address}, {self.city}"
        return self.full_address
