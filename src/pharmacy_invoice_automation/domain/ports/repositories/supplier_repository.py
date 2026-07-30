"""
Repository Port: SupplierRepository.

Persistence contract for the Supplier entity. Implemented against
SQLite in a future Infrastructure stage. Renamed from "ISupplierRepository"
per Stage 04's updated naming (no "I" prefix).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode


class SupplierRepository(ABC):
    """Abstract persistence contract for Supplier."""

    @abstractmethod
    def add(self, supplier: Supplier) -> None:
        """Persist a newly created Supplier."""

    @abstractmethod
    def get_by_id(self, supplier_id: str) -> Supplier | None:
        """Return the Supplier with this id, or None if not found."""

    @abstractmethod
    def find_by_name(self, name: str) -> Supplier | None:
        """Return the Supplier with this exact (case-insensitive) name, or None."""

    @abstractmethod
    def find_by_tax_code(self, tax_code: TaxCode) -> Supplier | None:
        """Return the Supplier with this tax code, or None."""

    @abstractmethod
    def list_all(self) -> list[Supplier]:
        """Return every known Supplier."""

    @abstractmethod
    def update(self, supplier: Supplier) -> None:
        """Persist changes to an existing Supplier."""
