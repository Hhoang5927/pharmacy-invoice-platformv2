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
from decimal import Decimal

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
    retail_units_per_purchase_unit: int | None = None
    """
    The resolved Vien-per-purchase-unit conversion factor for this
    line, once pipeline.party_matching_step.PartyMatchingStep has
    resolved it (from this invoice's own OCR reading, from the
    catalog Medicine's remembered value, or from a reviewer's
    confirmation) -- what
    infrastructure.automation.playwright_adapter.PlaywrightBrowserAutomationProvider
    actually uses to convert quantity/price to Vien at fill time. Starts
    as whatever OCR read for THIS invoice (possibly None) when the item
    is first created; PartyMatchingStep may overwrite it with the
    catalog's remembered value. None here still means "unresolved," not
    "no conversion needed" -- an item whose own unit is already Vien is
    resolved to 1, not left None (see PartyMatchingStep).
    """
    confirmed_website_unit_ratio: Decimal | None = None
    """
    A reviewer's confirmed ratio between this invoice line's own unit
    (``unit``) and whatever unit the real webnhathuoc.com site actually
    displays for this medicine's row at automation time (PO decision,
    2026-08 -- "Coldi-B DNH": 1 Hop trên hóa đơn = 1 Lọ trên web,
    confirmed a genuine, correct site-vs-invoice naming difference, not
    a bug). Distinct from ``retail_units_per_purchase_unit``, which
    converts to Vien for retail pricing -- this instead unblocks
    infrastructure.automation.playwright_adapter's own
    ``_verify_unit_matches_invoice`` unit-name check, which cannot be
    resolved at OCR/review time (the site's real displayed unit is only
    knowable once automation actually reads that row). ``ratio`` means
    "1 invoice unit = ``ratio`` website units" -- e.g. ``Decimal("1")``
    for Coldi-B DNH's 1 Hop = 1 Lọ. Still None until a reviewer supplies
    it (via "item.<id>.confirmed_website_unit_ratio" in review, see
    SubmitInvoiceReviewUseCase) -- never guessed by automation itself.
    """

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidInvoiceError("PurchaseItem id cannot be empty.")
        if not self.medicine_name or not self.medicine_name.strip():
            raise InvalidInvoiceError("PurchaseItem medicine_name cannot be empty.")
        self.medicine_name = self.medicine_name.strip()
        if (
            self.retail_units_per_purchase_unit is not None
            and self.retail_units_per_purchase_unit <= 0
        ):
            raise InvalidInvoiceError(
                f"retail_units_per_purchase_unit must be a positive integer, got "
                f"{self.retail_units_per_purchase_unit}."
            )
        if self.confirmed_website_unit_ratio is not None and self.confirmed_website_unit_ratio <= 0:
            raise InvalidInvoiceError(
                f"confirmed_website_unit_ratio must be a positive number, got "
                f"{self.confirmed_website_unit_ratio}."
            )

    def assign_medicine(self, medicine_id: str) -> None:
        """Record which catalog Medicine this item was resolved to."""
        if not medicine_id:
            raise InvalidInvoiceError("medicine_id cannot be empty.")
        self.medicine_id = medicine_id

    def assign_retail_units_per_purchase_unit(self, retail_units_per_purchase_unit: int) -> None:
        """Record the resolved Vien-per-purchase-unit conversion factor for this line."""
        if retail_units_per_purchase_unit <= 0:
            raise InvalidInvoiceError(
                f"retail_units_per_purchase_unit must be a positive integer, got "
                f"{retail_units_per_purchase_unit}."
            )
        self.retail_units_per_purchase_unit = retail_units_per_purchase_unit

    def assign_confirmed_website_unit_ratio(self, confirmed_website_unit_ratio: Decimal) -> None:
        """Record a reviewer-confirmed invoice-unit-to-website-unit ratio for this line."""
        if confirmed_website_unit_ratio <= 0:
            raise InvalidInvoiceError(
                f"confirmed_website_unit_ratio must be a positive number, got "
                f"{confirmed_website_unit_ratio}."
            )
        self.confirmed_website_unit_ratio = confirmed_website_unit_ratio

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
