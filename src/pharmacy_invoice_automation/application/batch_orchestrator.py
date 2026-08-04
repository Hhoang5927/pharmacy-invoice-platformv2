"""
Workflow Orchestrator (Stage 05 requirement #5) and Batch Processing
(requirement #6).

Coordinates the batch-level pipeline:

    Import Folder -> Discover Invoices -> [ per invoice: OCR -> AI
    Extraction -> Domain Validation -> Medicine Matching -> Human
    Review (if required) -> Database Save ] -> Export

Per-invoice work, INCLUDING every Domain Event that work produces AND
every transient-failure retry (see
pipeline.invoice_extraction_step.InvoiceExtractionStep's docstring for
why retries are scoped there rather than here), is delegated entirely
to use_cases.process_invoice_use_case.ProcessInvoiceUseCase. This class
owns only the batch-level concerns: iterating jobs, isolating a
failing invoice from the rest of the batch, tracking
batch_progress.BatchProgress, and supporting pause/resume/stop.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from pharmacy_invoice_automation.application.batch_progress import BatchProgress
from pharmacy_invoice_automation.application.commands import ProcessInvoiceCommand
from pharmacy_invoice_automation.application.configuration import BatchOptions
from pharmacy_invoice_automation.application.job_state import InvoiceJob, JobState
from pharmacy_invoice_automation.application.use_cases.process_invoice_use_case import (
    ProcessInvoiceUseCase,
)
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.workflow_state import WorkflowState


class BatchOrchestrator:
    """
    Drives a batch of invoices through ProcessInvoiceUseCase, one at a
    time, isolating failures and supporting pause/resume/stop.

    A single instance is created per running (or resumable) batch and
    tracked by project_id so query_handlers can report live progress
    without needing to touch persistence for a batch that is currently
    in memory.
    """

    def __init__(
        self,
        process_invoice_use_case: ProcessInvoiceUseCase,
        batch_options: BatchOptions,
    ) -> None:
        self._process_invoice_use_case = process_invoice_use_case
        self._batch_options = batch_options
        self._active_progress: dict[str, BatchProgress] = {}
        self._control: dict[str, WorkflowState] = {}

    def get_progress(self, project_id: str) -> BatchProgress | None:
        """Return the live, in-memory BatchProgress for ``project_id``, if a batch is active."""
        return self._active_progress.get(project_id)

    def request_pause(self, project_id: str) -> None:
        """Ask a running batch to pause after its current invoice finishes."""
        self._control[project_id] = WorkflowState.PAUSED

    def request_stop(self, project_id: str) -> None:
        """Ask a running batch to stop after its current invoice finishes."""
        self._control[project_id] = WorkflowState.STOPPED

    def run(
        self,
        project_id: str,
        jobs: Iterable[tuple[PurchaseInvoice, InvoiceJob, bytes, bool]],
        total_invoices: int,
    ) -> BatchProgress:
        """
        Process every job in ``jobs`` sequentially: (invoice, job,
        image_bytes, is_new_invoice) tuples, in the order given by the
        caller (use_cases.import_invoice_batch_use_case or
        use_cases.resume_batch_use_case). A failing invoice is recorded
        and the batch continues (Stage 05: "never stop the whole batch
        because of one invoice") unless
        configuration.BatchOptions.continue_on_invoice_failure is False.
        """
        progress = self._active_progress.setdefault(
            project_id, BatchProgress(project_id=project_id, total_invoices=total_invoices)
        )
        progress.start()
        self._control.pop(project_id, None)

        for invoice, job, image_bytes, is_new_invoice in jobs:
            control = self._control.get(project_id)
            if control is WorkflowState.STOPPED:
                progress.stop()
                break
            if control is WorkflowState.PAUSED:
                progress.pause()
                break

            job.transition_to(JobState.QUEUED)
            self._process_one(invoice, job, image_bytes, is_new_invoice, progress)

            if job.state is JobState.FAILED and not self._batch_options.continue_on_invoice_failure:
                progress.stop()
                break

        return progress

    def _process_one(
        self,
        invoice: PurchaseInvoice,
        job: InvoiceJob,
        image_bytes: bytes,
        is_new_invoice: bool,
        progress: BatchProgress,
    ) -> None:
        started_at = time.monotonic()
        command = ProcessInvoiceCommand(invoice_id=invoice.id, image_bytes=image_bytes)

        result = self._process_invoice_use_case.execute(command, invoice, job, is_new_invoice)
        elapsed = time.monotonic() - started_at

        if not result.is_success:
            progress.record_failed(elapsed)
            return

        if job.state is JobState.NEEDS_REVIEW:
            progress.record_needs_review(elapsed)
        else:
            progress.record_completed(elapsed)
