"""
Domain Event: InvoiceFailed.

Represents that an invoice failed at some stage of the pipeline. Per
the "never skip silently, always continue" business rule, every
failure is represented by an event like this rather than being
dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class InvoiceFailed(DomainEvent):
    """An invoice failed at a specific pipeline stage."""

    invoice_id: str
    stage: str  # e.g. "ocr", "validation", "import"
    reason: str
