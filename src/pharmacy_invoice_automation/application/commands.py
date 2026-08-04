"""
Commands (Stage 05 requirement #2): immutable requests that intend to
change state, one per use case. Plain data only -- all handling logic
lives in the corresponding class under use_cases/.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportFolderCommand:
    """Request to discover and begin processing every invoice image in a folder."""

    project_name: str
    root_folder: str


@dataclass(frozen=True)
class ProcessInvoiceCommand:
    """Request to run one invoice through the full processing pipeline."""

    invoice_id: str
    image_bytes: bytes


@dataclass(frozen=True)
class ResumeBatchCommand:
    """Request to resume a previously paused, stopped, or interrupted batch."""

    project_id: str


@dataclass(frozen=True)
class PauseBatchCommand:
    """Request to pause a running batch after its current invoice finishes."""

    project_id: str


@dataclass(frozen=True)
class StopBatchCommand:
    """Request to stop a running batch after its current invoice finishes."""

    project_id: str


@dataclass(frozen=True)
class SubmitInvoiceReviewCommand:
    """
    Request to apply a human reviewer's corrections to an invoice
    currently in the Review Queue, and advance it out of UNDER_REVIEW.

    ``corrected_fields`` is a flat mapping of field name to the
    reviewer-supplied replacement value (as a string, mirroring how a
    UI form would submit it); the use case is responsible for parsing
    and re-validating each one through Domain's own value objects.
    """

    invoice_id: str
    corrected_fields: dict[str, str]
    reviewer_approved: bool


@dataclass(frozen=True)
class ExportBatchResultsCommand:
    """Request to export a batch's results to a file."""

    project_id: str
    destination_path: str
    export_format: str  # "json" | "excel" | "log", per FR-13
