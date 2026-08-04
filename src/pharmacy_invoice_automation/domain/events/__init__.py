"""
Domain Events: immutable records of significant occurrences.

Per Stage 04: InvoiceCreated, MedicineAdded, SupplierCreated,
OCRCompleted -- replacing the prior InvoiceOcrCompleted / InvoiceImported
/ InvoiceFailed set. See domain.events.domain_event.DomainEvent for the
placement rationale (events are defined here; dispatch lives in
composition_root/event_bus.py).
"""

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent
from pharmacy_invoice_automation.domain.events.invoice_created import InvoiceCreated
from pharmacy_invoice_automation.domain.events.medicine_added import MedicineAdded
from pharmacy_invoice_automation.domain.events.ocr_completed import OCRCompleted
from pharmacy_invoice_automation.domain.events.supplier_created import SupplierCreated

__all__ = ["DomainEvent", "InvoiceCreated", "MedicineAdded", "SupplierCreated", "OCRCompleted"]
