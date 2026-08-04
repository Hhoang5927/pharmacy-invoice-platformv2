"""Exception: DuplicateMedicineError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class DuplicateMedicineError(DomainError):
    """Raised when a medicine with the same name or code already exists."""

    def __init__(self, medicine_name: str) -> None:
        super().__init__(f"A medicine named '{medicine_name}' already exists.")
        self.medicine_name = medicine_name
