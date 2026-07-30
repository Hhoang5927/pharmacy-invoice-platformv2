"""
Domain Event: MedicineAdded.

Raised when a new Medicine is added to the local catalog (either
because the pharmacist created it during review, or because automation
created it on the target website and the local catalog was updated to
match).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class MedicineAdded(DomainEvent):
    """A new Medicine was added to the catalog."""

    medicine_id: str
    medicine_code: str
