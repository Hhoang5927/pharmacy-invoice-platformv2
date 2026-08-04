"""
InMemoryInvoiceImageRegistry: the default InvoiceImageRegistry
implementation.

A thread-safe, in-process dict-backed registry -- zero infrastructure
dependency, same rationale as events.InMemoryEventDispatcher. Fully
sufficient for same-process resume (e.g. resuming a paused batch
without closing the app); a durable, restart-surviving implementation
is Infrastructure's job in a later stage, substituted at the
Composition Root without any Application code changing.
"""

from __future__ import annotations

import threading

from pharmacy_invoice_automation.application.ports.invoice_image_registry import (
    InvoiceImageRegistry,
)


class InMemoryInvoiceImageRegistry(InvoiceImageRegistry):
    """Thread-safe, in-process InvoiceImageRegistry."""

    def __init__(self) -> None:
        self._paths_by_invoice_id: dict[str, str] = {}
        self._lock = threading.Lock()

    def record(self, invoice_id: str, image_path: str) -> None:
        """Record ``image_path`` as the source image for ``invoice_id``."""
        with self._lock:
            self._paths_by_invoice_id[invoice_id] = image_path

    def get_image_path(self, invoice_id: str) -> str | None:
        """Return the recorded image path for ``invoice_id``, or None if unknown."""
        with self._lock:
            return self._paths_by_invoice_id.get(invoice_id)
