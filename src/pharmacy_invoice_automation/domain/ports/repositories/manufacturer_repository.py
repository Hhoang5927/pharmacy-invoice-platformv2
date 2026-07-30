"""
Repository Port: ManufacturerRepository.

Persistence contract for the Manufacturer entity. Added beyond Stage
04's explicit Repository Ports examples list (PurchaseInvoiceRepository,
MedicineRepository, SupplierRepository, BatchRepository) for DDD
consistency: Manufacturer was explicitly listed as a full Entity, and
every independently-identified aggregate root should be independently
persistable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.entities.manufacturer import Manufacturer


class ManufacturerRepository(ABC):
    """Abstract persistence contract for Manufacturer."""

    @abstractmethod
    def add(self, manufacturer: Manufacturer) -> None:
        """Persist a newly created Manufacturer."""

    @abstractmethod
    def get_by_id(self, manufacturer_id: str) -> Manufacturer | None:
        """Return the Manufacturer with this id, or None if not found."""

    @abstractmethod
    def find_by_name(self, name: str) -> Manufacturer | None:
        """Return the Manufacturer with this exact (case-insensitive) name, or None."""

    @abstractmethod
    def list_all(self) -> list[Manufacturer]:
        """Return every known Manufacturer."""

    @abstractmethod
    def update(self, manufacturer: Manufacturer) -> None:
        """Persist changes to an existing Manufacturer."""
