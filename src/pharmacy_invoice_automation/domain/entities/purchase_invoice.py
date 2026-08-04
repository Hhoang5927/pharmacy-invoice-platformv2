"""
Entity (aggregate root): PurchaseInvoice.

Owns PurchaseItem as a child entity per DDD -- there is no separate
PurchaseItemRepository. Enforces the invoice status state machine
defined in domain.constants.VALID_STATUS_TRANSITIONS.

Renamed from "Invoice" per Stage 04's updated terminology; semantics
of the aggregate are otherwise unchanged. Satisfies
shared_interfaces.Identifiable, Timestamped, Auditable, and Versionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from pharmacy_invoice_automation.domain.constants import VALID_STATUS_TRANSITIONS
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.exceptions.invalid_business_rule_error import (
    InvalidBusinessRuleError,
)
from pharmacy_invoice_automation.domain.exceptions.invalid_invoice_error import (
    InvalidInvoiceError,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money


@dataclass(eq=False)
class PurchaseInvoice:
    """
    The PurchaseInvoice aggregate root: one purchase invoice and every
    medicine item on it.
    """

    id: str
    project_id: str
    invoice_number: str
    invoice_date: date
    status: InvoiceStatus = InvoiceStatus.PENDING
    supplier_id: str | None = None
    items: list[PurchaseItem] = field(default_factory=list)
    ocr_confidence: float | None = None
    commercial_discount_amount: Money | None = None
    """
    The whole-invoice commercial discount ("Giam Tru CKTM"/"Chiet khau
    thuong mai", PO-confirmed 2026-08) some suppliers print as their own
    summary row -- a deduction against the WHOLE invoice, not against
    any one PurchaseItem's line_total. Populated by
    pipeline.invoice_extraction_step.InvoiceExtractionStep from
    OCRResult.raw_commercial_discount_amount, when present. None means
    this invoice states no such discount -- never guessed. Deducted from
    calculate_item_total_sum() by
    services.invoice_calculation_service.InvoiceCalculationService when
    reconciling against the invoice's stated grand total (see
    calculate_reconciled_grand_total).
    """
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidInvoiceError("PurchaseInvoice id cannot be empty.")
        if not self.project_id:
            raise InvalidInvoiceError("PurchaseInvoice project_id cannot be empty.")
        if not self.invoice_number or not self.invoice_number.strip():
            raise InvalidInvoiceError("PurchaseInvoice invoice_number cannot be empty.")
        self.invoice_number = self.invoice_number.strip()

    # --- Aggregate mutation: items ------------------------------------

    def add_item(self, item: PurchaseItem) -> None:
        """Add a medicine item to this invoice."""
        if any(existing.id == item.id for existing in self.items):
            raise InvalidInvoiceError(
                f"PurchaseItem with id '{item.id}' already exists on this invoice."
            )
        self.items.append(item)
        self.touch()

    def remove_item(self, item_id: str) -> None:
        """Remove a medicine item by id. No-op if it is not present."""
        self.items = [item for item in self.items if item.id != item_id]
        self.touch()

    # --- Aggregate query: totals ---------------------------------------

    def calculate_item_total_sum(self) -> Money:
        """Sum of every item's line_total. An empty invoice sums to zero VND."""
        currency = self.items[0].unit_price.currency if self.items else "VND"
        total = Money(amount=Decimal("0"), currency=currency)
        for item in self.items:
            total = total + item.line_total
        return total

    # --- Aggregate mutation: supplier -----------------------------------

    def assign_supplier(self, supplier_id: str) -> None:
        """Record which Supplier this invoice was resolved to."""
        if not supplier_id:
            raise InvalidInvoiceError("supplier_id cannot be empty.")
        self.supplier_id = supplier_id
        self.touch()

    # --- Aggregate mutation: status --------------------------------------

    def transition_to(self, new_status: InvoiceStatus) -> None:
        """
        Move this invoice to ``new_status``, enforcing the state
        machine in domain.constants.VALID_STATUS_TRANSITIONS.

        Raises InvalidBusinessRuleError for any transition not on that
        map, including any transition out of the terminal Imported
        status (FR-15: an imported invoice is never reprocessed).
        """
        allowed = VALID_STATUS_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidBusinessRuleError(
                rule_name="invoice_status_transition",
                message=(
                    f"Cannot transition PurchaseInvoice from {self.status.value!r} "
                    f"to {new_status.value!r}."
                ),
            )
        self.status = new_status
        self.touch()

    # --- shared_interfaces.Auditable / Versionable ------------------------

    def touch(self) -> None:
        """Record that this invoice was just modified (Auditable)."""
        self.updated_at = datetime.now(timezone.utc)

    def increment_version(self) -> None:
        """Advance this invoice's optimistic-concurrency version (Versionable)."""
        self.version += 1

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PurchaseInvoice):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
