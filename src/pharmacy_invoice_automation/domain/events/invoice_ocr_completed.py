"""
Domain Event: InvoiceOcrCompleted.

Represents that an invoice's OCR processing has finished, whether it
succeeded or failed. Published (via composition_root's EventBus, per
Implementation Specification Section 3) so the Dashboard tab can update
its live counters without polling.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class InvoiceOcrCompleted(DomainEvent):
    """OCR processing finished for a given invoice."""

    invoice_id: str
    resulting_status: InvoiceStatus
    confidence: float | None = None
