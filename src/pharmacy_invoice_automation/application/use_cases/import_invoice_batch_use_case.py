"""
Use Case: ImportInvoiceBatchUseCase.

Discovers every invoice image in a folder (FR-02), creates a Project
and one provisional PurchaseInvoice per image (Pending status, per
domain.constants.VALID_STATUS_TRANSITIONS), then hands the whole batch
to batch_orchestrator.BatchOrchestrator to run through the pipeline.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

from pharmacy_invoice_automation.application.batch_orchestrator import BatchOrchestrator
from pharmacy_invoice_automation.application.commands import ImportFolderCommand
from pharmacy_invoice_automation.application.dto import BatchProgressDTO
from pharmacy_invoice_automation.application.job_state import InvoiceJob
from pharmacy_invoice_automation.application.ports.invoice_image_registry import (
    InvoiceImageRegistry,
)
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.domain.entities.project import Project
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)

_INVOICE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

# One in-flight job tuple: (invoice, job, image_bytes, is_new_invoice) --
# matches the shape batch_orchestrator.BatchOrchestrator.run expects.
JobTuple = tuple[PurchaseInvoice, InvoiceJob, bytes, bool]


class ImportInvoiceBatchUseCase:
    """Discovers invoice images in a folder and runs the whole batch through the pipeline."""

    def __init__(
        self,
        project_repository: ProjectRepository,
        file_storage_provider: FileStorageProvider,
        invoice_image_registry: InvoiceImageRegistry,
        batch_orchestrator: BatchOrchestrator,
    ) -> None:
        self._project_repository = project_repository
        self._file_storage_provider = file_storage_provider
        self._invoice_image_registry = invoice_image_registry
        self._batch_orchestrator = batch_orchestrator

    def execute(self, command: ImportFolderCommand) -> UseCaseResult[BatchProgressDTO]:
        """Create a Project for ``command.root_folder`` and process every image found in it."""
        image_paths = self._file_storage_provider.list_files(
            command.root_folder, list(_INVOICE_IMAGE_EXTENSIONS)
        )
        if not image_paths:
            return UseCaseResult.failure(
                errors=(f"No invoice images found under '{command.root_folder}'.",)
            )

        project = Project(
            id=str(uuid.uuid4()), name=command.project_name, root_folder=command.root_folder
        )
        self._project_repository.add(project)

        jobs = list(self._build_jobs(project, image_paths))
        progress = self._batch_orchestrator.run(
            project_id=project.id, jobs=jobs, total_invoices=len(jobs)
        )

        return UseCaseResult.success(
            value=progress.to_dto(),
            statistics={"discovered_images": len(image_paths)},
        )

    def _build_jobs(self, project: Project, image_paths: list[str]) -> Iterator[JobTuple]:
        for image_path in image_paths:
            invoice = PurchaseInvoice(
                id=str(uuid.uuid4()),
                project_id=project.id,
                invoice_number=f"PENDING-{uuid.uuid4().hex[:8]}",
                invoice_date=date.today(),
            )
            job = InvoiceJob(invoice_id=invoice.id)
            self._invoice_image_registry.record(invoice.id, image_path)
            image_bytes = self._file_storage_provider.read_file(image_path)
            yield invoice, job, image_bytes, True
