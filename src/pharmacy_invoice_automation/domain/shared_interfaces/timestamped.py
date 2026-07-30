"""
Shared Interface: Timestamped.

A structural (Protocol) capability: "this object records when it was
created and last updated." Satisfied by entities exposing both
``created_at`` and ``updated_at`` (currently PurchaseInvoice and Batch,
the two entities whose lifecycle genuinely benefits from an updated_at,
since they are mutated repeatedly during OCR, review, and automation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Timestamped(Protocol):
    """Anything that records its creation and last-update time."""

    created_at: datetime
    updated_at: datetime


def days_since_last_update(entity: Timestamped) -> float:
    """
    Number of days since ``entity`` was last updated. Generic over any
    Timestamped -- used, for example, by services.purchase_policy to
    flag a PurchaseInvoice that has sat in UNDER_REVIEW for an unusually
    long time.
    """
    delta = datetime.now(timezone.utc) - entity.updated_at
    return delta.total_seconds() / 86400
