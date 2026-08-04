"""
Use Case: ProcessInvoiceUseCase.

Runs one invoice through the full pipeline: OCR extraction -> AI-assisted
matching -> Domain validation -> confidence-based routing -> persistence.
Composes the four pipeline.* Step collaborators (see pipeline/__init__.py
for why they are Steps here, not four separate top-level use cases) and
is itself the one place their sequence, error handling, and job-state
bookkeeping is written -- exactly once.
"""

from __future__ import annotations

import time

from pharmacy_invoice_automation.application.commands import ProcessInvoiceCommand
from pharmacy_invoice_automation.application.configuration import ConfidenceThresholds
from pharmacy_invoice_automation.application.confidence_evaluator import ConfidenceEvaluator
from pharmacy_invoice_automation.application.dto import (
    InvoiceConfidenceReportDTO,
    PurchaseInvoiceDTO,
)
from pharmacy_invoice_automation.application.job_state import InvoiceJob, JobState
from pharmacy_invoice_automation.application.pipeline.invoice_extraction_step import (
    InvoiceExtractionStep,
)
from pharmacy_invoice_automation.application.pipeline.invoice_persistence_step import (
    InvoicePersistenceStep,
)
from pharmacy_invoice_automation.application.pipeline.invoice_validation_step import (
    InvoiceValidationStep,
)
from pharmacy_invoice_automation.application.pipeline.party_matching_step import (
    PartyMatchingStep,
)
from pharmacy_invoice_automation.application.ports.event_dispatcher import EventDispatcher
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.events.invoice_created import InvoiceCreated
from pharmacy_invoice_automation.domain.events.medicine_added import MedicineAdded
from pharmacy_invoice_automation.domain.events.ocr_completed import OCRCompleted
from pharmacy_invoice_automation.domain.events.supplier_created import SupplierCreated


class ProcessInvoiceUseCase:
    """Processes one invoice through extraction, matching, validation, and persistence."""

    def __init__(
        self,
        extraction_step: InvoiceExtractionStep,
        party_matching_step: PartyMatchingStep,
        validation_step: InvoiceValidationStep,
        persistence_step: InvoicePersistenceStep,
        event_dispatcher: EventDispatcher,
        confidence_thresholds: ConfidenceThresholds,
    ) -> None:
        self._extraction_step = extraction_step
        self._party_matching_step = party_matching_step
        self._validation_step = validation_step
        self._persistence_step = persistence_step
        self._event_dispatcher = event_dispatcher
        self._confidence_evaluator = ConfidenceEvaluator(confidence_thresholds)

    def execute(
        self,
        command: ProcessInvoiceCommand,
        invoice: PurchaseInvoice,
        job: InvoiceJob,
        is_new_invoice: bool,
    ) -> UseCaseResult[PurchaseInvoiceDTO]:
        """
        Run ``invoice`` through the full pipeline. ``job`` is updated in
        place to reflect progress; the caller (batch_orchestrator or a
        single-invoice driver) is responsible for constructing it and
        for deciding what happens next based on the returned result
        (e.g. whether to retry).
        """
        started_at = time.monotonic()
        job.transition_to(JobState.OCR_PROCESSING)

        if is_new_invoice:
            self._event_dispatcher.dispatch(
                InvoiceCreated(invoice_id=invoice.id, project_id=invoice.project_id)
            )

        extraction = self._extraction_step.execute(invoice, command.image_bytes)
        issues: list[str] = list(extraction.issues)

        self._event_dispatcher.dispatch(
            OCRCompleted(
                invoice_id=invoice.id,
                status=extraction.ocr_result.status,
                overall_confidence=extraction.ocr_result.overall_confidence,
            )
        )

        if not extraction.ocr_result.succeeded:
            job.record_attempt(error="OCR extraction failed")
            job.transition_to(JobState.FAILED)
            return UseCaseResult.failure(
                errors=tuple(issues) or ("OCR extraction failed.",),
                statistics={"elapsed_seconds": time.monotonic() - started_at},
            )

        job.transition_to(JobState.AI_EXTRACTING)
        confidence_report = self._confidence_evaluator.evaluate(invoice.id, extraction.ocr_result)

        matching = self._party_matching_step.execute(invoice, extraction.ocr_result)
        issues.extend(matching.issues)

        job.transition_to(JobState.VALIDATING)
        validation_issues = self._validation_step.execute(
            invoice, extraction.ocr_result, matching.excluded_supplement_total
        )
        issues.extend(validation_issues)

        needs_review = self._needs_review(confidence_report, issues)
        # Domain's state machine (domain.constants.VALID_STATUS_TRANSITIONS)
        # requires every invoice to pass through UnderReview before
        # ReadyForImport -- there is no direct OcrDone -> ReadyForImport
        # transition, by design (every invoice has a review checkpoint).
        # An auto-accepted invoice passes through it and is immediately
        # advanced further within this same call; one needing review
        # simply stays here until a human acts via SubmitInvoiceReviewUseCase.
        invoice.transition_to(InvoiceStatus.UNDER_REVIEW)
        if not needs_review:
            invoice.transition_to(InvoiceStatus.READY_FOR_IMPORT)

        self._persistence_step.execute(
            invoice=invoice,
            new_suppliers=matching.new_suppliers,
            new_medicines=matching.new_medicines,
            is_new_invoice=is_new_invoice,
        )

        for supplier in matching.new_suppliers:
            self._event_dispatcher.dispatch(
                SupplierCreated(supplier_id=supplier.id, supplier_name=supplier.name)
            )
        for medicine in matching.new_medicines:
            self._event_dispatcher.dispatch(
                MedicineAdded(medicine_id=medicine.id, medicine_code=medicine.medicine_code)
            )

        elapsed_seconds = time.monotonic() - started_at
        job.record_attempt()
        job.transition_to(JobState.NEEDS_REVIEW if needs_review else JobState.COMPLETED)

        return UseCaseResult.success(
            value=PurchaseInvoiceDTO.from_domain(invoice),
            warnings=tuple(issues) + matching.notes,
            statistics={
                "elapsed_seconds": elapsed_seconds,
                "new_suppliers": len(matching.new_suppliers),
                "new_medicines": len(matching.new_medicines),
            },
            confidence=confidence_report.overall_confidence,
        )

    @staticmethod
    def _needs_review(confidence_report: InvoiceConfidenceReportDTO, issues: list[str]) -> bool:
        """
        An invoice needs human review if the Confidence Pipeline says so,
        or if validation/matching surfaced any issue at all -- Stage 05:
        "Do NOT automatically approve uncertain data."
        """
        return confidence_report.overall_decision == "requires_review" or bool(issues)
