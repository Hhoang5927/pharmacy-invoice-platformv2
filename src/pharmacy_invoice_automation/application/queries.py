"""
Queries (Stage 05 requirement #3): immutable read-side requests,
handled by query_handlers.py. Kept separate from Commands per CQRS --
a Query never changes state and always returns a DTO, never a Domain
entity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GetInvoiceStatusQuery:
    """Request the current status/details of one invoice."""

    invoice_id: str


@dataclass(frozen=True)
class GetBatchProgressQuery:
    """Request the current progress snapshot of a project's batch run."""

    project_id: str


@dataclass(frozen=True)
class GetReviewQueueQuery:
    """Request every invoice currently awaiting human review for a project."""

    project_id: str
