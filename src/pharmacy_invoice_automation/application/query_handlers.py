"""
Query Handlers (Stage 05 requirement #3, read side of CQRS).

Each handler is a thin, read-only wrapper around a Domain repository,
returning only DTOs. Grouped in one module since each is small and
none has behavior worth its own file -- unlike the pipeline Steps or
Use Cases, there is no orchestration sequence here to separate out.
"""

from __future__ import annotations

from pharmacy_invoice_automation.application.batch_orchestrator import BatchOrchestrator
from pharmacy_invoice_automation.application.dto import (
    BatchProgressDTO,
    PurchaseInvoiceDTO,
    ReviewQueueItemDTO,
)
from pharmacy_invoice_automation.application.queries import (
    GetBatchProgressQuery,
    GetInvoiceStatusQuery,
    GetReviewQueueQuery,
)
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.workflow_state import WorkflowState
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator

_TERMINAL_FAILED_STATUSES = (InvoiceStatus.OCR_FAILED, InvoiceStatus.IMPORT_FAILED)
# Deviation D11 (PO-confirmed 2026-08): a genuinely saved-on-site invoice
# missing only a manually-completed line still counts as completed here,
# not "remaining" -- the automation pipeline has nothing left to do with it.
_TERMINAL_COMPLETED_STATUSES = (InvoiceStatus.IMPORTED, InvoiceStatus.IMPORTED_NEEDS_MANUAL_LINE)


class GetInvoiceStatusQueryHandler:
    """Handles GetInvoiceStatusQuery."""

    def __init__(self, purchase_invoice_repository: PurchaseInvoiceRepository) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository

    def handle(self, query: GetInvoiceStatusQuery) -> PurchaseInvoiceDTO | None:
        """Return the current status/details of one invoice, or None if it does not exist."""
        invoice = self._purchase_invoice_repository.get_by_id(query.invoice_id)
        return PurchaseInvoiceDTO.from_domain(invoice) if invoice is not None else None


class GetBatchProgressQueryHandler:
    """Handles GetBatchProgressQuery."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        batch_orchestrator: BatchOrchestrator,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._batch_orchestrator = batch_orchestrator

    def handle(self, query: GetBatchProgressQuery) -> BatchProgressDTO:
        """
        Return the current progress of a project's batch run.

        Prefers the live, in-memory tracker if the batch is currently
        active in this process; otherwise reconstructs a snapshot from
        persisted invoice statuses (FR-15: progress must be recoverable
        after a restart, when no live tracker exists).
        """
        live_progress = self._batch_orchestrator.get_progress(query.project_id)
        if live_progress is not None:
            return live_progress.to_dto()
        return self._reconstruct_from_repository(query.project_id)

    def _reconstruct_from_repository(self, project_id: str) -> BatchProgressDTO:
        invoices = self._purchase_invoice_repository.list_by_project(project_id)
        completed = sum(1 for invoice in invoices if invoice.status in _TERMINAL_COMPLETED_STATUSES)
        failed = sum(1 for invoice in invoices if invoice.status in _TERMINAL_FAILED_STATUSES)
        needs_review = sum(
            1 for invoice in invoices if invoice.status is InvoiceStatus.UNDER_REVIEW
        )
        return BatchProgressDTO(
            project_id=project_id,
            workflow_state=WorkflowState.NOT_STARTED.value,
            total_invoices=len(invoices),
            completed_count=completed,
            failed_count=failed,
            needs_review_count=needs_review,
            remaining_count=max(len(invoices) - completed - failed - needs_review, 0),
            started_at=None,
            estimated_completion_at=None,
        )


class GetReviewQueueQueryHandler:
    """Handles GetReviewQueueQuery."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        invoice_validator: InvoiceValidator,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._invoice_validator = invoice_validator

    def handle(self, query: GetReviewQueueQuery) -> tuple[ReviewQueueItemDTO, ...]:
        """
        Return every invoice in ``query.project_id`` currently awaiting
        human review.

        ``confidence_report`` is always None here: per-field OCR
        confidence is only available at the moment
        use_cases.process_invoice_use_case.ProcessInvoiceUseCase actually
        runs (returned in its own UseCaseResult) -- it is not part of
        the persisted PurchaseInvoice aggregate (which only stores the
        overall ocr_confidence), so a query made afterward cannot
        reconstruct the original per-field breakdown. This is a known,
        deliberate limitation rather than an oversight: adding a
        per-field-confidence store would be a Domain entity change,
        which this stage may only make for a critical defect, and this
        is not one.
        """
        under_review = self._purchase_invoice_repository.list_by_status(
            InvoiceStatus.UNDER_REVIEW
        )
        matching_project = [
            invoice for invoice in under_review if invoice.project_id == query.project_id
        ]
        return tuple(
            ReviewQueueItemDTO(
                invoice=PurchaseInvoiceDTO.from_domain(invoice),
                confidence_report=None,
                validation_issues=self._invoice_validator.validate(invoice).unwrap().issues,
            )
            for invoice in matching_project
        )
