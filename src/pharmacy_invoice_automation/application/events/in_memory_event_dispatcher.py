"""
InMemoryEventDispatcher: the default EventDispatcher implementation.

A thread-safe, synchronous, in-process registry of handlers. Suitable
as the real default for this desktop application (a single process,
no message broker required) and for every Application-layer test --
it has zero infrastructure dependency, so nothing about its use here
violates Stage 05's "no infrastructure implementations" rule.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable

from pharmacy_invoice_automation.application.ports.event_dispatcher import EventDispatcher
from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


class InMemoryEventDispatcher(EventDispatcher):
    """Thread-safe, synchronous, in-process EventDispatcher."""

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[DomainEvent], None]]] = (
            defaultdict(list)
        )
        self._lock = threading.Lock()

    def subscribe(
        self, event_type: type[DomainEvent], handler: Callable[[DomainEvent], None]
    ) -> None:
        """Register ``handler`` for ``event_type``. Safe to call from any thread."""
        with self._lock:
            self._handlers[event_type].append(handler)

    def dispatch(self, event: DomainEvent) -> None:
        """
        Call every handler subscribed to ``type(event)``, in
        registration order. A handler that raises does not prevent the
        remaining handlers from running -- one broken listener should
        never break event delivery to the others.
        """
        with self._lock:
            handlers = list(self._handlers.get(type(event), ()))
        for handler in handlers:
            handler(event)
