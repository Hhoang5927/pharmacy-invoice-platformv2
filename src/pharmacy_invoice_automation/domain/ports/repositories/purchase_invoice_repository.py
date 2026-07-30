"""
Repository Port: PurchaseInvoiceRepository.

Persistence contract for the PurchaseInvoice aggregate (PurchaseInvoice
+ PurchaseItem together -- there is no separate PurchaseItemRepository).
Renamed from "IInvoiceRepository" per Stage 04's updated naming.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus


class PurchaseInvoiceRepository(ABC):
    """Abstract persistence contract for the PurchaseInvoice aggregate."""

    @abstractmethod
    def add(self, invoice: PurchaseInvoice) -> None:
        """Persist a newly created PurchaseInvoice (with its PurchaseItems)."""

    @abstractmethod
    def get_by_id(self, invoice_id: str) -> PurchaseInvoice | None:
        """Return the PurchaseInvoice with this id, or None if not found."""

    @abstractmethod
    def find_by_invoice_number(self, invoice_number: str) -> PurchaseInvoice | None:
        """Return the PurchaseInvoice with this invoice_number, or None."""

    @abstractmethod
    def list_by_project(self, project_id: str) -> list[PurchaseInvoice]:
        """Return every PurchaseInvoice belonging to ``project_id``."""

    @abstractmethod
    def list_by_status(self, status: InvoiceStatus) -> list[PurchaseInvoice]:
        """Return every PurchaseInvoice currently in ``status``."""

    @abstractmethod
    def search(
        self,
        *,
        invoice_number: str | None = None,
        supplier_name: str | None = None,
        medicine_name: str | None = None,
        invoice_date: date | None = None,
    ) -> list[PurchaseInvoice]:
        """
        Search invoices by any combination of the given criteria
        (FR-12). Unspecified criteria are not filtered on.
        """

    @abstractmethod
    def update(self, invoice: PurchaseInvoice) -> None:
        """Persist changes to an existing PurchaseInvoice (including its items)."""
