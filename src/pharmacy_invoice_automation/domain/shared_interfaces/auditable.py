"""
Shared Interface: Auditable.

A structural (Protocol) capability: "this object knows how to record
that it was modified." Stronger than Timestamped -- it requires a
callable ``touch()`` method, not just a passive updated_at field.
Satisfied by PurchaseInvoice and Batch, whose ``touch()`` methods
update their own ``updated_at`` whenever a mutating method runs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Auditable(Protocol):
    """Anything that can record its own modification."""

    def touch(self) -> None:
        """Record that this object was just modified."""


def mark_modified(entity: Auditable) -> None:
    """
    Record a modification on any Auditable entity. Generic helper used
    by Domain Services (e.g. services.invoice_calculation_service)
    after recalculating a derived value, so the call site does not need
    to know which concrete entity type it is touching.
    """
    entity.touch()
