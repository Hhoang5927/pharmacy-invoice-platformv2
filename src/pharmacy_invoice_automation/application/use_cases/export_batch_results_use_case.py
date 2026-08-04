"""
Use Case: ExportBatchResultsUseCase.

Exports a project's invoices to a file (FR-13: JSON / Excel / Log).
Writes through domain.ports.services.FileStorageProvider only -- never
touches the filesystem directly, keeping this use case testable
against a fake and free of any concrete infrastructure dependency.

Only the JSON format is actually serialized here; "excel" and "log"
are recognized as valid ``export_format`` values but their real
serialization is an Infrastructure-adapter concern (a later stage) --
producing an .xlsx file or a formatted log stream needs libraries this
layer must not import. Requesting either now returns a clear failure
rather than a silently wrong file, which is preferable to a fake stub
that would look like it worked.
"""

from __future__ import annotations

import json

from pharmacy_invoice_automation.application.commands import ExportBatchResultsCommand
from pharmacy_invoice_automation.application.dto import PurchaseInvoiceDTO
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)

_SUPPORTED_FORMATS = ("json",)


class ExportBatchResultsUseCase:
    """Exports a project's invoices to a file in the requested format."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        file_storage_provider: FileStorageProvider,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._file_storage_provider = file_storage_provider

    def execute(self, command: ExportBatchResultsCommand) -> UseCaseResult[str]:
        """Write every invoice in ``command.project_id`` to ``command.destination_path``."""
        if command.export_format not in _SUPPORTED_FORMATS:
            return UseCaseResult.failure(
                errors=(
                    f"Export format '{command.export_format}' is not yet implemented in the "
                    f"Application layer; only {_SUPPORTED_FORMATS} are available until "
                    f"Infrastructure provides the corresponding adapter.",
                )
            )

        invoices = self._purchase_invoice_repository.list_by_project(command.project_id)
        dtos = [PurchaseInvoiceDTO.from_domain(invoice) for invoice in invoices]
        payload = json.dumps([self._dto_to_json(dto) for dto in dtos], indent=2, default=str)

        self._file_storage_provider.write_file(command.destination_path, payload.encode("utf-8"))

        return UseCaseResult.success(
            value=command.destination_path,
            statistics={"exported_invoice_count": len(dtos)},
        )

    @staticmethod
    def _dto_to_json(dto: PurchaseInvoiceDTO) -> dict[str, object]:
        return {
            "id": dto.id,
            "project_id": dto.project_id,
            "invoice_number": dto.invoice_number,
            "invoice_date": dto.invoice_date.isoformat(),
            "status": dto.status,
            "supplier_id": dto.supplier_id,
            "item_total_sum": dto.item_total_sum,
            "ocr_confidence": dto.ocr_confidence,
            "items": [
                {
                    "id": item.id,
                    "medicine_name": item.medicine_name,
                    "unit_code": item.unit_code,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                    "medicine_id": item.medicine_id,
                    "batch_id": item.batch_id,
                    "tax_type": item.tax_type,
                }
                for item in dto.items
            ],
        }
