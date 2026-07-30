"""
Entity (child of the PurchaseInvoice aggregate): PurchaseItem.

One medicine line item on a purchase invoice. Never persisted or
referenced independently of its owning PurchaseInvoice -- there is no
separate PurchaseItemRepository (mirroring the prior InvoiceLine
design, renamed per Stage 04's updated terminology).

References its Batch by id (batch_id) rather than embedding
batch_number/expiry_date directly, now that Batch is its own aggregate
root (Stage 04).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.exceptions.invalid_invoice_error import (
    InvalidInvoiceError,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit


@dataclass(eq=False)
class PurchaseItem:
    """One medicine line item on a purchase invoice."""

    id: str
    medicine_name: str  # as extracted/entered; medicine_id assigned once resolved
    unit: Unit
    quantity: Quantity
    unit_price: Money
    medicine_id: str | None = None
    batch_id: str | None = None
    tax_type: TaxType | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidInvoiceError("PurchaseItem id cannot be empty.")
        if not self.medicine_name or not self.medicine_name.strip():
            raise InvalidInvoiceError("PurchaseItem medicine_name cannot be empty.")
        self.medicine_name = self.medicine_name.strip()

    def assign_medicine(self, medicine_id: str) -> None:
        """Record which catalog Medicine this item was resolved to."""
        if not medicine_id:
            raise InvalidInvoiceError("medicine_id cannot be empty.")
        self.medicine_id = medicine_id

    def assign_batch(self, batch_id: str) -> None:
        """Record which Batch this item's stock was received as."""
        if not batch_id:
            raise InvalidInvoiceError("batch_id cannot be empty.")
        self.batch_id = batch_id

    @property
    def line_total(self) -> Money:
        """
        The item's total before tax: quantity x unit price. Tax, when
        ``tax_type`` is set, is computed separately by
        services.tax_calculation_service.TaxCalculationService -- it is
        not folded into this figure.
        """
        return self.unit_price.multiply(self.quantity.amount)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PurchaseItem):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
