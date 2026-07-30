"""
Domain Event: InvoiceImported.

Represents that an invoice was successfully saved on the target
website.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class InvoiceImported(DomainEvent):
    """An invoice was successfully saved on the target website."""

    invoice_id: str
    invoice_number: str
