"""
Port: EventDispatcher (Stage 05 requirement #14).

Abstract contract for dispatching Domain Events to interested
handlers. Application's use cases publish events (InvoiceCreated,
SupplierCreated, MedicineAdded, OCRCompleted) through this abstraction
without knowing or caring how they eventually reach a listener (a
Dashboard tab's live counters, a log line, a future notification).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


class EventDispatcher(ABC):
    """Abstract contract for publishing and subscribing to Domain Events."""

    @abstractmethod
    def subscribe(
        self, event_type: type[DomainEvent], handler: Callable[[DomainEvent], None]
    ) -> None:
        """Register ``handler`` to be called whenever an event of ``event_type`` is dispatched."""

    @abstractmethod
    def dispatch(self, event: DomainEvent) -> None:
        """Publish ``event`` to every handler subscribed to its exact type."""
