"""
Entity: Manufacturer.

Represents the actual manufacturer of a Medicine ("Nha san xuat") --
distinct from Supplier, which is the distributor who sold this
particular invoice's goods to the pharmacy. A single Manufacturer's
products may arrive via many different Suppliers over time.

New entity added per Stage 04. Given its own repository port
(ports.repositories.manufacturer_repository.ManufacturerRepository)
beyond Stage 04's explicit repository examples list, for DDD
consistency: every aggregate root with its own identity should be
independently persistable, and Stage 04 explicitly listed Manufacturer
as a full Entity, not a value object.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError


@dataclass(eq=False)
class Manufacturer:
    """A medicine manufacturer."""

    id: str
    name: str
    country: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Manufacturer id cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValidationError("Manufacturer name cannot be empty.")
        self.name = self.name.strip()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Manufacturer):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
