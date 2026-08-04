"""
Job State Machine (Stage 05 requirement #7).

JobState tracks one invoice's progress through the Application-layer
*orchestration* pipeline -- it is a runtime, in-memory concern owned by
batch_orchestrator.BatchOrchestrator, not a persisted business fact.

This is deliberately distinct from domain.enums.InvoiceStatus, which
tracks the invoice's persisted *business* lifecycle (Pending,
OcrDone, UnderReview, ReadyForImport, ...) and is enforced by
PurchaseInvoice.transition_to() using domain.constants.VALID_STATUS_TRANSITIONS.
Keeping them separate avoids Application either duplicating that
Domain state machine or reaching into Domain to add orchestration-only
states (Queued, AiExtracting, Cancelled) that are not business facts
Domain has any reason to know about -- exactly what Stage 05 means by
"Application Layer MUST NOT contain business rules."

The two are kept in sync at well-defined points in the pipeline (see
pipeline/*.py), not on every transition -- JobState changes far more
often (once per pipeline stage) than InvoiceStatus does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class JobState(str, Enum):
    """Orchestration-level state of one invoice moving through the pipeline."""

    PENDING = "pending"
    QUEUED = "queued"
    OCR_PROCESSING = "ocr_processing"
    AI_EXTRACTING = "ai_extracting"
    VALIDATING = "validating"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True for states from which the batch orchestrator takes no further action."""
        return self in (JobState.COMPLETED, JobState.CANCELLED)


# Valid orchestration-state transitions. Mirrors the *pattern* Domain
# uses for InvoiceStatus (a transition map plus an enforcing method),
# without being the same state machine or living in Domain.
_VALID_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.QUEUED: frozenset({JobState.OCR_PROCESSING, JobState.CANCELLED}),
    JobState.OCR_PROCESSING: frozenset({JobState.AI_EXTRACTING, JobState.FAILED}),
    JobState.AI_EXTRACTING: frozenset({JobState.VALIDATING, JobState.FAILED}),
    JobState.VALIDATING: frozenset(
        {JobState.NEEDS_REVIEW, JobState.COMPLETED, JobState.FAILED}
    ),
    JobState.NEEDS_REVIEW: frozenset({JobState.VALIDATING, JobState.CANCELLED}),
    JobState.FAILED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),  # terminal
    JobState.CANCELLED: frozenset(),  # terminal
}


class InvalidJobTransitionError(Exception):
    """Raised when an InvoiceJob's state is moved along a transition not on the map above."""

    def __init__(self, current: JobState, attempted: JobState) -> None:
        super().__init__(
            f"Cannot move an InvoiceJob from {current.value!r} to {attempted.value!r}."
        )
        self.current = current
        self.attempted = attempted


@dataclass
class InvoiceJob:
    """
    An in-memory orchestration record for one invoice's journey through
    the batch pipeline: its current JobState, how many attempts have
    been made, and its timing. Not persisted -- the durable business
    record is the PurchaseInvoice aggregate itself.
    """

    invoice_id: str
    state: JobState = JobState.PENDING
    attempt_count: int = 0
    last_error: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def transition_to(self, new_state: JobState) -> None:
        """Move this job to ``new_state``, enforcing the valid-transition map."""
        allowed = _VALID_JOB_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidJobTransitionError(self.state, new_state)
        self.state = new_state
        now = datetime.now(timezone.utc)
        if new_state is JobState.QUEUED:
            self.queued_at = now
            self.finished_at = None  # a fresh attempt is beginning (e.g. after a retry)
        elif new_state is JobState.OCR_PROCESSING and self.started_at is None:
            self.started_at = now
        if new_state.is_terminal or new_state is JobState.FAILED:
            self.finished_at = now

    def record_attempt(self, error: str | None = None) -> None:
        """Record that a processing attempt just occurred, and its error, if any."""
        self.attempt_count += 1
        self.last_error = error
