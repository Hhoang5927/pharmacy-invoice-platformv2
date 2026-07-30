"""
Domain Event: OCRCompleted.

Raised when an invoice's OCR extraction attempt finishes, whether it
succeeded, failed, or needs manual review (value_objects.ocr_result.OCRResult).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.domain.events.domain_event import DomainEvent


@dataclass(frozen=True, kw_only=True)
class OCRCompleted(DomainEvent):
    """An OCR extraction attempt finished for a given invoice."""

    invoice_id: str
    status: OCRStatus
    overall_confidence: float
