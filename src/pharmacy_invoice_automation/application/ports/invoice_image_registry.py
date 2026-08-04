"""
Port: InvoiceImageRegistry.

Abstract contract mapping an invoice_id to the path of the source
image it was created from. This mapping is deliberately kept out of
domain.entities.purchase_invoice.PurchaseInvoice: "which file on disk
this came from" is provenance/tracking metadata, not a business fact
about the invoice itself, so it does not belong on the Domain entity.

use_cases.import_invoice_batch_use_case.ImportInvoiceBatchUseCase
records the mapping when each invoice is first created;
use_cases.resume_batch_use_case.ResumeBatchUseCase reads it back to
re-locate the image for a PENDING or OcrFailed invoice being resumed.
A durable (survives-a-restart) implementation is Infrastructure's
responsibility in a later stage; this stage's responsibility is having
the right abstraction and the right call sites already wired to it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class InvoiceImageRegistry(ABC):
    """Abstract contract mapping an invoice id to its source image path."""

    @abstractmethod
    def record(self, invoice_id: str, image_path: str) -> None:
        """Record that ``invoice_id`` was created from the image at ``image_path``."""

    @abstractmethod
    def get_image_path(self, invoice_id: str) -> str | None:
        """Return the recorded image path for ``invoice_id``, or None if unknown."""
