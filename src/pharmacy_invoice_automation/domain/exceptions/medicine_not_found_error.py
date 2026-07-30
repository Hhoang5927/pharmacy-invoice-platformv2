"""
Exception: MedicineNotFoundError.

Added alongside SupplierNotFoundError for symmetry: any operation that
can fail to find a Supplier by id can equally fail to find a Medicine
by id.
"""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class MedicineNotFoundError(DomainError):
    """Raised when an operation requires a Medicine that does not exist."""

    def __init__(self, medicine_id: str) -> None:
        super().__init__(f"No medicine found with id '{medicine_id}'.")
        self.medicine_id = medicine_id
