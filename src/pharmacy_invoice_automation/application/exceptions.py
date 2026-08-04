"""
Application Exceptions (Stage 05 requirement #16).

Distinct from domain.exceptions: Domain exceptions represent business
invariant violations (a supplier name is empty, an invalid status
transition). Application exceptions represent orchestration-level
failures -- a pipeline step could not complete, a batch could not
continue, or an external dependency failed transiently. All are
grouped in one module, matching how domain.exceptions groups its
hierarchy under one clear base type.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for every Application-layer exception."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TransientInfrastructureError(ApplicationError):
    """
    Raised by an Infrastructure adapter (implementing a Domain service
    port) when it hits a failure that is worth retrying -- a network
    timeout, an HTTP 5xx, a rate limit. configuration.RetryPolicy
    treats this exception type (and only this type, or a subclass of
    it) as retryable; every other exception is treated as permanent.

    This type is defined here, in Application, rather than in
    Infrastructure, precisely so Application's retry logic can depend
    on it without importing anything infrastructure-specific --
    Infrastructure (built in a later stage) will import and raise this
    type instead of a concrete SDK/library exception.
    """


class InvoiceProcessingError(ApplicationError):
    """
    Raised when a single invoice's processing pipeline
    (use_cases.process_invoice_use_case) cannot proceed at all -- as
    opposed to producing a UseCaseResult.failure(), which is the normal
    path for an expected, recoverable outcome (e.g. "needs review").
    Reserved for the rare case where even a `UseCaseResult.failure`
    cannot be safely constructed, such as a torn/partial write detected
    mid-transaction.
    """

    def __init__(self, invoice_id: str, message: str) -> None:
        super().__init__(f"Invoice '{invoice_id}': {message}")
        self.invoice_id = invoice_id


class BatchProcessingError(ApplicationError):
    """
    Raised when an entire batch run cannot continue -- as opposed to
    one invoice within it failing, which batch_orchestrator.BatchOrchestrator
    isolates and records without raising. Reserved for failures that
    invalidate the whole run, e.g. the batch's Project cannot be found.
    """

    def __init__(self, project_id: str, message: str) -> None:
        super().__init__(f"Batch for project '{project_id}': {message}")
        self.project_id = project_id
