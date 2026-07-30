"""
Base class: DomainEvent.

A Domain Event is an immutable record that something significant has
already happened within the domain. Domain Events are pure data: they
carry no behavior and depend on nothing outside the standard library.

Placement note: the Implementation Specification described an
EventBus living in composition_root/event_bus.py, publishing events
named InvoiceOcrCompleted / InvoiceImported / InvoiceFailed, but did
not previously give those event *types* a home of their own -- Stage 04
now explicitly asks for "Domain Events" as a Domain Layer deliverable.
This is resolved the same way DDD conventionally draws this line: the
event *definitions* (pure data, what happened) belong in the Domain
layer and are defined here; the event *dispatch mechanism* (how
listeners are notified -- threading, Qt signal bridging) remains a
cross-cutting, mechanical concern and stays in composition_root, exactly
as already specified. Nothing about the EventBus's design changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for every Domain Event."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
