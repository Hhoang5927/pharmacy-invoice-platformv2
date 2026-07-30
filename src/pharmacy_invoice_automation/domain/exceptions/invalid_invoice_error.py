"""Exception: InvalidInvoiceError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class InvalidInvoiceError(DomainError):
    """
    Raised specifically for a PurchaseInvoice or PurchaseItem invariant
    violation -- e.g. a negative quantity, a negative price, or a line
    referencing no medicine. Renamed from the prior
    "InvalidInvoiceDataError" per Stage 04's updated terminology.
    """
