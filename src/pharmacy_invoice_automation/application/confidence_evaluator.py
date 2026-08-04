"""
Confidence Pipeline (Stage 05 requirement #11).

Every extracted field carries confidence metadata already (Domain's
value_objects.ocr_result.OCRResult.field_confidences); this module is
where the Application layer -- exactly as Stage 05 specifies -- decides
Auto Accept / Highlight / Manual Review from that data against
configurable configuration.ConfidenceThresholds. Domain never makes
this decision: it only carries the raw numbers.
"""

from __future__ import annotations

from pharmacy_invoice_automation.application.configuration import ConfidenceThresholds
from pharmacy_invoice_automation.application.dto import (
    FieldConfidenceDTO,
    InvoiceConfidenceReportDTO,
)
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult

_AUTO_ACCEPT = "auto_accept"
_HIGHLIGHT = "highlight"
_REQUIRES_REVIEW = "requires_review"


class ConfidenceEvaluator:
    """Turns raw OCR confidence figures into Auto Accept / Highlight / Manual Review decisions."""

    def __init__(self, thresholds: ConfidenceThresholds) -> None:
        self._thresholds = thresholds

    def evaluate(self, invoice_id: str, ocr_result: OCRResult) -> InvoiceConfidenceReportDTO:
        """
        Assess every field in ``ocr_result`` and produce the invoice's
        overall routing decision. A single field below the review
        threshold -- or the extraction itself needing review or having
        failed -- is enough to force ``overall_decision`` to
        "requires_review"; the invoice is never auto-accepted on the
        strength of its *other* fields alone (Stage 05: "Do NOT
        automatically approve uncertain data").
        """
        field_reports = tuple(
            FieldConfidenceDTO(
                field_name=field_name, confidence=confidence, decision=self._decide(confidence)
            )
            for field_name, confidence in ocr_result.field_confidences.items()
        )

        any_field_requires_review = any(
            report.decision == _REQUIRES_REVIEW for report in field_reports
        )
        overall_decision = (
            _REQUIRES_REVIEW
            if (
                any_field_requires_review
                or ocr_result.needs_manual_review
                or not ocr_result.succeeded
            )
            else _AUTO_ACCEPT
        )

        return InvoiceConfidenceReportDTO(
            invoice_id=invoice_id,
            overall_confidence=ocr_result.overall_confidence,
            field_confidences=field_reports,
            overall_decision=overall_decision,
        )

    def _decide(self, confidence: float) -> str:
        if confidence >= self._thresholds.auto_accept_at_or_above:
            return _AUTO_ACCEPT
        if confidence >= self._thresholds.review_at_or_above:
            return _HIGHLIGHT
        return _REQUIRES_REVIEW
