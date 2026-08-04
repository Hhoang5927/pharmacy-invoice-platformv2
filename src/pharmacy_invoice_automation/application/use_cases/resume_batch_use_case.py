"""
Use Case: ResumeBatchUseCase.

Resumes a previously paused, stopped, or interrupted batch (FR-15).
Deliberately does not duplicate BatchOrchestrator's processing loop --
it only reconstructs which invoices still need work from persisted
state, wraps each in a fresh InvoiceJob, and hands them to the exact
same BatchOrchestrator.run() that ImportInvoiceBatchUseCase uses.

Only Pending and OcrFailed invoices are resumed through this pipeline.
This is narrower than "every non-terminal status" might suggest, and
deliberately so:

- Imported is never resumed (FR-15's core guarantee).
- UnderReview is left for a human via SubmitInvoiceReviewUseCase, not
  silently re-run.
- OcrDone, ReadyForImport, and ImportFailed are NOT resumed here: by
  the time an invoice reaches OcrDone, its PurchaseItems already exist
  on the aggregate. Re-running the full pipeline from raw image bytes
  would call PurchaseInvoice.add_item() again with freshly-generated
  ids and silently duplicate every line. ReadyForImport and
  ImportFailed both sit *past* this stage's pipeline boundary (Stage
  05's own workflow ends at "Database Save" -- website-automation
  retries belong to a later stage's use case, not this one).
"""

from __future__ import annotations

from pharmacy_invoice_automation.application.batch_orchestrator import BatchOrchestrator
from pharmacy_invoice_automation.application.commands import ResumeBatchCommand
from pharmacy_invoice_automation.application.dto import BatchProgressDTO
from pharmacy_invoice_automation.application.job_state import InvoiceJob
from pharmacy_invoice_automation.application.ports.invoice_image_registry import (
    InvoiceImageRegistry,
)
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)

_RESUMABLE_STATUSES = (InvoiceStatus.PENDING, InvoiceStatus.OCR_FAILED)


class ResumeBatchUseCase:
    """Resumes a batch by re-queuing every Pending or OcrFailed invoice."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        file_storage_provider: FileStorageProvider,
        invoice_image_registry: InvoiceImageRegistry,
        batch_orchestrator: BatchOrchestrator,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._file_storage_provider = file_storage_provider
        self._invoice_image_registry = invoice_image_registry
        self._batch_orchestrator = batch_orchestrator

    def execute(self, command: ResumeBatchCommand) -> UseCaseResult[BatchProgressDTO]:
        """Re-queue every resumable invoice in ``command.project_id`` and resume processing."""
        all_invoices = self._purchase_invoice_repository.list_by_project(command.project_id)
        resumable = [inv for inv in all_invoices if inv.status in _RESUMABLE_STATUSES]

        if not resumable:
            return UseCaseResult.failure(
                errors=(f"No resumable invoices found for project '{command.project_id}'.",)
            )

        jobs = []
        skipped: list[str] = []
        for invoice in resumable:
            image_path = self._invoice_image_registry.get_image_path(invoice.id)
            if image_path is None:
                skipped.append(invoice.id)
                continue
            image_bytes = self._file_storage_provider.read_file(image_path)
            jobs.append((invoice, InvoiceJob(invoice_id=invoice.id), image_bytes, False))

        progress = self._batch_orchestrator.run(
            project_id=command.project_id, jobs=jobs, total_invoices=len(all_invoices)
        )
        return UseCaseResult.success(
            value=progress.to_dto(),
            warnings=tuple(
                f"Invoice '{invoice_id}': source image path unknown, skipped."
                for invoice_id in skipped
            ),
        )
