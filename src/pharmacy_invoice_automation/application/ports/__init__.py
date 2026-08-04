"""
Application-owned abstractions: TransactionCoordinator, EventDispatcher,
InvoiceImageRegistry.

Scope note: in this project's established convention, abstract ports
live under domain.ports (see Implementation Specification Section 3).
All three genuinely belong to that convention -- a Unit-of-Work-style
transaction boundary, a Domain Event dispatcher, and a persistence
lookup are not orchestration logic. They are defined here instead, in
Application, only because Stage 05's scope restricts writes to
src/application/** (domain/ is read-only this stage). A future stage
may relocate these to domain.ports without changing their contracts,
if that consolidation is ever wanted.
"""

from pharmacy_invoice_automation.application.ports.event_dispatcher import EventDispatcher
from pharmacy_invoice_automation.application.ports.invoice_image_registry import (
    InvoiceImageRegistry,
)
from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)

__all__ = ["TransactionCoordinator", "EventDispatcher", "InvoiceImageRegistry"]
