"""Exception: DuplicateInvoiceError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class DuplicateInvoiceError(DomainError):
    """Raised when a PurchaseInvoice with the same invoice_number already exists."""

    def __init__(self, invoice_number: str) -> None:
        super().__init__(f"A purchase invoice numbered '{invoice_number}' already exists.")
        self.invoice_number = invoice_number
