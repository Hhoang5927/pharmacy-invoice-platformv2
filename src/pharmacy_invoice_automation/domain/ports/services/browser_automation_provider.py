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
from decimal import Decimal

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.supplier import Supplier


@dataclass(frozen=True)
class ManualFollowUpLineItem:
    """
    One PurchaseItem that fill_and_save_invoice could not resolve on-site
    by any automated means (Deviation D11, PO-confirmed 2026-08): every
    shortened-name search candidate was tried and create_medicine() either
    failed outright or still left the medicine unfindable. The invoice was
    still saved without this line -- ``line_position`` (1-based) matches
    where it would have been in the invoice's own item order, for the
    operator to locate and fill in by hand directly on the site.
    """

    line_position: int
    medicine_name: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class AutomationOutcome:
    """Result of one automation workflow step."""

    success: bool
    failure_reason: str | None = None
    # Deviation D11 (PO-confirmed 2026-08): non-empty only for a
    # fill_and_save_invoice call that saved the invoice with 1+ line(s)
    # skipped -- see ManualFollowUpLineItem. Defaults to empty so every
    # other existing AutomationOutcome(...) call site is unaffected.
    manual_followup_items: tuple[ManualFollowUpLineItem, ...] = ()


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
    def remove_default_supplier_tag(self) -> AutomationOutcome:
        """
        Remove the invoice form's default "Hang nhap le" supplier tag
        (bug fix, PO-confirmed 2026-08 -- a step already PO-confirmed as
        required, only ever recorded in the Selector Registry but never
        actually wired into any orchestration call until now). Must be
        called before search_supplier()/select_supplier()/create_supplier()
        on a freshly-opened invoice form -- while this default tag is
        still present, the "Nha cung cap" row's own accessible name/
        structure does not match what a supplier search expects.
        """

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
    def fill_and_save_invoice(
        self, invoice: PurchaseInvoice, dry_run: bool = False
    ) -> AutomationOutcome:
        """
        Fill every remaining field and save, per the Fill & Save Invoice
        workflow. ``dry_run`` (Composition Root Stage D, PO-confirmed
        2026-08): when True, every real fill/search/create step still
        runs exactly as normal, but the final save ("Ghi Phieu") is
        never clicked -- nothing is actually committed on the real
        site. Lets an operator preview a fully-filled real invoice form
        in a real browser before ever writing real business data.
        """
