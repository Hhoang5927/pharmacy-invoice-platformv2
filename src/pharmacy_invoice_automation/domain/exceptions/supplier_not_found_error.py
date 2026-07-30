"""Exception: SupplierNotFoundError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class SupplierNotFoundError(DomainError):
    """Raised when an operation requires a Supplier that does not exist."""

    def __init__(self, supplier_id: str) -> None:
        super().__init__(f"No supplier found with id '{supplier_id}'.")
        self.supplier_id = supplier_id
