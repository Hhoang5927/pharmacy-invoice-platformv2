"""Exception: ValidationError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class ValidationError(DomainError):
    """
    General-purpose exception for a construction-time invariant
    violation on any entity or value object other than PurchaseInvoice
    itself (which raises the more specific InvalidInvoiceError) -- e.g.
    an empty Supplier name, an invalid Address, or a malformed Unit.
    """
