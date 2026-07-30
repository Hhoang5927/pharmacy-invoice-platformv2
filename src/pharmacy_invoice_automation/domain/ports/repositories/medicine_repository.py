"""
Repository Port: MedicineRepository.

Persistence contract for the Medicine entity. Renamed from
"IMedicineRepository" per Stage 04's updated naming.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.entities.medicine import Medicine


class MedicineRepository(ABC):
    """Abstract persistence contract for Medicine."""

    @abstractmethod
    def add(self, medicine: Medicine) -> None:
        """Persist a newly created Medicine."""

    @abstractmethod
    def get_by_id(self, medicine_id: str) -> Medicine | None:
        """Return the Medicine with this id, or None if not found."""

    @abstractmethod
    def find_by_name(self, name: str) -> Medicine | None:
        """Return the Medicine with this exact (case-insensitive) name, or None."""

    @abstractmethod
    def find_by_code(self, medicine_code: str) -> Medicine | None:
        """Return the Medicine with this system medicine_code, or None."""

    @abstractmethod
    def get_highest_code_sequence_number(self) -> int:
        """
        Return the highest numeric suffix currently in use across every
        TH<N> medicine_code (0 if none exist yet). Used together with
        services.medicine_validation_service.MedicineValidationService
        .generate_next_medicine_code.
        """

    @abstractmethod
    def list_all(self) -> list[Medicine]:
        """Return every known Medicine."""

    @abstractmethod
    def update(self, medicine: Medicine) -> None:
        """Persist changes to an existing Medicine."""
