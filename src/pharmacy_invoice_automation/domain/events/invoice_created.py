"""
Domain Event: InvoiceCreated.

Raised when a new PurchaseInvoice is first created (a Pending record
established for a discovered invoice image), before OCR has run.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class InvoiceCreated(DomainEvent):
    """A new PurchaseInvoice record was created."""

    invoice_id: str
    project_id: str
