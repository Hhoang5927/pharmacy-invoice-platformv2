"""
Enum: OCRStatus.

Status of a single OCR extraction attempt, carried on
value_objects.ocr_result.OCRResult. Distinct from InvoiceStatus, which
tracks the invoice's overall pipeline position -- OCRStatus concerns
only the extraction step itself.
"""

from __future__ import annotations

from enum import Enum


class OCRStatus(str, Enum):
    """Outcome of a single OCR extraction attempt."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"  # succeeded, but confidence was low
