"""
Domain Events: immutable records of significant occurrences.

See domain.events.domain_event.DomainEvent for the placement rationale
(events are defined here; dispatch lives in composition_root/event_bus.py).
"""

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent
from pharmacy_invoice_automation.domain.events.invoice_failed import InvoiceFailed
from pharmacy_invoice_automation.domain.events.invoice_imported import InvoiceImported
from pharmacy_invoice_automation.domain.events.invoice_ocr_completed import (
    InvoiceOcrCompleted,
)

__all__ = ["DomainEvent", "InvoiceOcrCompleted", "InvoiceImported", "InvoiceFailed"]
