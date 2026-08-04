"""
DTOs (Stage 05 requirement #4): immutable data-transfer shapes crossing
the Application boundary outward. Domain entities and value objects
are never exposed directly to a caller (the eventual Presentation
layer, or any other consumer) -- every one of these is built from a
Domain object via its own ``from_domain`` factory, flattening Domain's
richer types (Money, Quantity, Unit, ExpiryDate, ...) into plain,
UI/serialization-friendly primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus


@dataclass(frozen=True)
class PurchaseItemDTO:
    """Read-only, presentation-friendly view of a PurchaseItem."""

    id: str
    medicine_name: str
    unit_code: str
    unit_requires_confirmation: bool
    quantity: str
    unit_price: str
    line_total: str
    medicine_id: str | None
    batch_id: str | None
    tax_type: str | None

    @staticmethod
    def from_domain(item: PurchaseItem) -> "PurchaseItemDTO":
        """Build a PurchaseItemDTO from a Domain PurchaseItem entity."""
        return PurchaseItemDTO(
            id=item.id,
            medicine_name=item.medicine_name,
            unit_code=item.unit.code,
            unit_requires_confirmation=item.unit.requires_manual_confirmation,
            quantity=str(item.quantity),
            unit_price=str(item.unit_price),
            line_total=str(item.line_total),
            medicine_id=item.medicine_id,
            batch_id=item.batch_id,
            tax_type=item.tax_type.value if item.tax_type else None,
        )


@dataclass(frozen=True)
class PurchaseInvoiceDTO:
    """Read-only, presentation-friendly view of a PurchaseInvoice aggregate."""

    id: str
    project_id: str
    invoice_number: str
    invoice_date: date
    status: str
    supplier_id: str | None
    items: tuple[PurchaseItemDTO, ...]
    item_total_sum: str
    ocr_confidence: float | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_domain(invoice: PurchaseInvoice) -> "PurchaseInvoiceDTO":
        """Build a PurchaseInvoiceDTO from a Domain PurchaseInvoice aggregate."""
        return PurchaseInvoiceDTO(
            id=invoice.id,
            project_id=invoice.project_id,
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            status=invoice.status.value,
            supplier_id=invoice.supplier_id,
            items=tuple(PurchaseItemDTO.from_domain(item) for item in invoice.items),
            item_total_sum=str(invoice.calculate_item_total_sum()),
            ocr_confidence=invoice.ocr_confidence,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )

    @property
    def needs_review(self) -> bool:
        """True if this invoice is currently sitting in the Human Review Queue."""
        return self.status == InvoiceStatus.UNDER_REVIEW.value


@dataclass(frozen=True)
class FieldConfidenceDTO:
    """One extracted field's confidence figure and routing decision."""

    field_name: str
    confidence: float
    decision: str  # "auto_accept" | "highlight" | "requires_review"


@dataclass(frozen=True)
class InvoiceConfidenceReportDTO:
    """
    The Confidence Pipeline's full assessment of one invoice
    (Stage 05 requirement #11), produced by confidence_evaluator.ConfidenceEvaluator.
    """

    invoice_id: str
    overall_confidence: float
    field_confidences: tuple[FieldConfidenceDTO, ...]
    overall_decision: str  # "auto_accept" | "requires_review"


@dataclass(frozen=True)
class ReviewQueueItemDTO:
    """One entry in the Human Review Queue (Stage 05 requirement #10)."""

    invoice: PurchaseInvoiceDTO
    confidence_report: InvoiceConfidenceReportDTO | None
    validation_issues: tuple[str, ...]


@dataclass(frozen=True)
class BatchProgressDTO:
    """Read-only snapshot of a batch run's progress (Stage 05 requirement #9)."""

    project_id: str
    workflow_state: str
    total_invoices: int
    completed_count: int
    failed_count: int
    needs_review_count: int
    remaining_count: int
    started_at: datetime | None
    estimated_completion_at: datetime | None
