"""
Repository Port: BatchRepository.

Persistence contract for the Batch entity -- a new aggregate root per
Stage 04, independently persisted (unlike the prior InvoiceLine-embedded
batch fields).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.entities.batch import Batch


class BatchRepository(ABC):
    """Abstract persistence contract for Batch."""

    @abstractmethod
    def add(self, batch: Batch) -> None:
        """Persist a newly created Batch."""

    @abstractmethod
    def get_by_id(self, batch_id: str) -> Batch | None:
        """Return the Batch with this id, or None if not found."""

    @abstractmethod
    def find_by_medicine_and_batch_number(
        self, medicine_id: str, batch_number: str
    ) -> Batch | None:
        """Return the Batch for this medicine with this batch_number, or None."""

    @abstractmethod
    def list_by_medicine(self, medicine_id: str) -> list[Batch]:
        """Return every Batch recorded for ``medicine_id``."""

    @abstractmethod
    def update(self, batch: Batch) -> None:
        """Persist changes to an existing Batch."""
