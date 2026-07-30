"""
Service Port: OCRProvider.

Abstract OCR extraction contract. Implemented against Google Gemini
Vision in a future Infrastructure stage. Renamed from "IOcrProvider"
per Stage 04's updated naming; now returns the formal
value_objects.ocr_result.OCRResult Value Object directly, rather than a
separate port-adjacent DTO.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult


class OCRProvider(ABC):
    """Abstract contract for extracting structured data from an invoice image."""

    @abstractmethod
    def extract(self, image_bytes: bytes) -> OCRResult:
        """
        Extract structured invoice data from a preprocessed invoice
        image, returning an OCRResult whose ``status`` reflects
        success, failure, or a need for manual review. Implementations
        are responsible for their own retry policy on transient
        failures; this method should raise only for a permanent,
        non-retryable failure.
        """
