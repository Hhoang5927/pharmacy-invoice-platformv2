"""
Enum: InvoiceStatus.

Represents an invoice's position in its lifecycle, from first
discovering an image on disk through to a successfully saved website
invoice (or a terminal failure at any stage). See
docs/architecture/Technical_Design_Document.md Section 12.4 for the
full state diagram this enum, together with
domain.constants.VALID_STATUS_TRANSITIONS, implements.
"""

from __future__ import annotations

from enum import Enum


class InvoiceStatus(str, Enum):
    """Lifecycle status of an Invoice aggregate."""

    PENDING = "pending"
    OCR_IN_PROGRESS = "ocr_in_progress"
    OCR_DONE = "ocr_done"
    OCR_FAILED = "ocr_failed"
    UNDER_REVIEW = "under_review"
    READY_FOR_IMPORT = "ready_for_import"
    IMPORT_IN_PROGRESS = "import_in_progress"
    IMPORTED = "imported"
    IMPORT_FAILED = "import_failed"

    @property
    def is_terminal(self) -> bool:
        """True only for the one status that should never be re-entered (FR-15)."""
        return self is InvoiceStatus.IMPORTED
