"""Exception: DuplicateSupplierError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class DuplicateSupplierError(DomainError):
    """Raised when a supplier with the same name or tax code already exists."""

    def __init__(self, supplier_name: str) -> None:
        super().__init__(f"A supplier named '{supplier_name}' already exists.")
        self.supplier_name = supplier_name
