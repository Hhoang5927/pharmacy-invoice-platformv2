"""
Domain Event: SupplierCreated.

Raised when a new Supplier is added to the local catalog, per the
Create Supplier workflow (FR-07).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SupplierCreated(DomainEvent):
    """A new Supplier was added to the catalog."""

    supplier_id: str
    supplier_name: str
