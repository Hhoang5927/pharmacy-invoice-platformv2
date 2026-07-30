"""
Service Port: BrowserAutomationProvider.

Abstract website automation contract. Implemented against Playwright
in a future Infrastructure stage. Renamed from "IBrowserAutomation" per
Stage 04's updated naming.

This port models only the *mechanics* of driving the website; the
*decision* of whether a supplier/medicine must be created vs. selected
is made by services.purchase_policy.PurchasePolicy before this port is
ever called.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.supplier import Supplier


@dataclass(frozen=True)
class AutomationOutcome:
    """Result of one automation workflow step."""

    success: bool
    failure_reason: str | None = None


class BrowserAutomationProvider(ABC):
    """Abstract contract for driving the target pharmacy website."""

    @abstractmethod
    def is_session_valid(self) -> bool:
        """True if the current browser session is still authenticated."""

    @abstractmethod
    def login(self) -> AutomationOutcome:
        """Log in, per the Login workflow specification."""

    @abstractmethod
    def open_import_invoice_form(self) -> AutomationOutcome:
        """Navigate to the invoice import form, per the Open Import Invoice workflow."""

    @abstractmethod
    def search_supplier(self, name: str) -> bool:
        """True if a supplier matching ``name`` exists on the website."""

    @abstractmethod
    def select_supplier(self, name: str) -> AutomationOutcome:
        """Select an existing supplier on the current invoice form."""

    @abstractmethod
    def create_supplier(self, supplier: Supplier) -> AutomationOutcome:
        """Create a new supplier via the website's popup, per the Create Supplier workflow."""

    @abstractmethod
    def search_medicine(self, name: str) -> bool:
        """True if a medicine matching ``name`` exists on the website."""

    @abstractmethod
    def select_medicine(self, name: str) -> AutomationOutcome:
        """Select an existing medicine on the current invoice form."""

    @abstractmethod
    def create_medicine(self, medicine: Medicine) -> AutomationOutcome:
        """Create a new medicine via the website's popup, per the Create Medicine workflow."""

    @abstractmethod
    def fill_and_save_invoice(self, invoice: PurchaseInvoice) -> AutomationOutcome:
        """Fill every remaining field and save, per the Fill & Save Invoice workflow."""
