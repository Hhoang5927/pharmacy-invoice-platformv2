"""
Entity (aggregate root): Batch.

Represents a specific manufactured lot of a Medicine received on a
purchase invoice: its batch number, expiry date, and originating
Manufacturer. Promoted to a full, independently-persisted aggregate
root per Stage 04 (previously batch_number/expiry_date were plain
fields embedded directly on the invoice line) -- reflecting that a
batch is a real, independently-meaningful business concept (e.g. it can
be looked up and cross-referenced across multiple purchase items or
future recall/traceability workflows), not merely a detail of one line.

Satisfies shared_interfaces.Identifiable, Timestamped, Auditable, and
Versionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.value_objects.expiry_date import ExpiryDate
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity


@dataclass(eq=False)
class Batch:
    """A specific manufactured lot of a medicine."""

    id: str
    medicine_id: str
    batch_number: str
    expiry_date: ExpiryDate
    quantity_received: Quantity
    manufacturer_id: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Batch id cannot be empty.")
        if not self.medicine_id:
            raise ValidationError("Batch medicine_id cannot be empty.")
        if not self.batch_number or not self.batch_number.strip():
            raise ValidationError("Batch batch_number cannot be empty.")
        self.batch_number = self.batch_number.strip()

    def assign_manufacturer(self, manufacturer_id: str) -> None:
        """Record which Manufacturer produced this batch."""
        if not manufacturer_id:
            raise ValidationError("manufacturer_id cannot be empty.")
        self.manufacturer_id = manufacturer_id
        self.touch()

    def touch(self) -> None:
        """Record that this batch was just modified (Auditable)."""
        self.updated_at = datetime.now(timezone.utc)

    def increment_version(self) -> None:
        """Advance this batch's optimistic-concurrency version (Versionable)."""
        self.version += 1

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Batch):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
