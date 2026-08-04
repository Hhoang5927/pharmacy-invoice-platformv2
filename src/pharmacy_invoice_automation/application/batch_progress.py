"""
Progress Tracking (Stage 05 requirement #9).

BatchProgress is a mutable, in-memory tracker updated by
batch_orchestrator.BatchOrchestrator as each InvoiceJob finishes. Like
job_state.InvoiceJob, it is a runtime orchestration concern, not a
persisted record -- durable counts can always be recomputed from
PurchaseInvoiceRepository.list_by_status() if a fresh in-memory tracker
is ever needed (e.g. after a restart), which is exactly what
use_cases.resume_batch_use_case.ResumeBatchUseCase does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pharmacy_invoice_automation.application.dto import BatchProgressDTO
from pharmacy_invoice_automation.domain.enums.workflow_state import WorkflowState


@dataclass
class BatchProgress:
    """Mutable progress tracker for one project's batch run."""

    project_id: str
    total_invoices: int
    workflow_state: WorkflowState = WorkflowState.NOT_STARTED
    completed_count: int = 0
    failed_count: int = 0
    needs_review_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    _average_seconds_per_invoice: float = field(default=0.0, repr=False)

    @property
    def processed_count(self) -> int:
        """Every invoice that has reached a terminal outcome so far."""
        return self.completed_count + self.failed_count + self.needs_review_count

    @property
    def remaining_count(self) -> int:
        """Invoices not yet reaching a terminal outcome."""
        return max(self.total_invoices - self.processed_count, 0)

    def start(self) -> None:
        """Mark the batch as running, recording its start time on first call."""
        self.workflow_state = WorkflowState.RUNNING
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

    def record_completed(self, elapsed_seconds: float) -> None:
        """Record one invoice completing successfully, updating the running average."""
        self.completed_count += 1
        self._update_average(elapsed_seconds)
        self._maybe_finish()

    def record_failed(self, elapsed_seconds: float) -> None:
        """Record one invoice failing permanently, updating the running average."""
        self.failed_count += 1
        self._update_average(elapsed_seconds)
        self._maybe_finish()

    def record_needs_review(self, elapsed_seconds: float) -> None:
        """Record one invoice being routed to the Human Review Queue."""
        self.needs_review_count += 1
        self._update_average(elapsed_seconds)
        self._maybe_finish()

    def pause(self) -> None:
        """Mark the batch as paused (Start/Pause/Resume/Stop UI control)."""
        if self.workflow_state is WorkflowState.RUNNING:
            self.workflow_state = WorkflowState.PAUSED

    def stop(self) -> None:
        """Mark the batch as stopped (Start/Pause/Resume/Stop UI control)."""
        self.workflow_state = WorkflowState.STOPPED
        self.finished_at = datetime.now(timezone.utc)

    def _update_average(self, elapsed_seconds: float) -> None:
        n = self.processed_count
        if n <= 1:
            self._average_seconds_per_invoice = elapsed_seconds
        else:
            self._average_seconds_per_invoice = (
                self._average_seconds_per_invoice * (n - 1) + elapsed_seconds
            ) / n

    def _maybe_finish(self) -> None:
        if self.remaining_count == 0:
            self.workflow_state = WorkflowState.COMPLETED
            self.finished_at = datetime.now(timezone.utc)

    @property
    def estimated_completion_at(self) -> datetime | None:
        """
        Estimated wall-clock completion time, projected from the
        running average seconds-per-invoice. None until at least one
        invoice has been processed (an estimate from zero data would
        be meaningless).
        """
        if self.processed_count == 0 or self.remaining_count == 0:
            return None
        remaining_seconds = self._average_seconds_per_invoice * self.remaining_count
        return datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)

    def to_dto(self) -> BatchProgressDTO:
        """Build the read-only DTO exposed by query_handlers.GetBatchProgressQueryHandler."""
        return BatchProgressDTO(
            project_id=self.project_id,
            workflow_state=self.workflow_state.value,
            total_invoices=self.total_invoices,
            completed_count=self.completed_count,
            failed_count=self.failed_count,
            needs_review_count=self.needs_review_count,
            remaining_count=self.remaining_count,
            started_at=self.started_at,
            estimated_completion_at=self.estimated_completion_at,
        )
