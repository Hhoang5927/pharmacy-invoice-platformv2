"""
Structural/unit tests for composition_root.cli's Stage D pieces (PO-
confirmed 2026-08). PO explicitly acknowledged full end-to-end testing
against the real webnhathuoc.com is not possible here (that is the
PO's own real, live business system) -- these tests exercise the CLI
orchestration logic directly (_automate_one_invoice,
_resolve_supplier_on_site, _finish_automation_attempt, and
run_automate's no-work early return, which needs no browser at all)
against a hand-written FakeBrowserAutomationProvider test double (not a
mock of this project's own code) that implements the real
BrowserAutomationProvider port. Real SQLite via
register_infrastructure_services, real domain entities/repositories --
only the website itself is faked, exactly as
PurchaseInvoiceRepository/SupplierRepository etc. are real here too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pharmacy_invoice_automation.composition_root import cli
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.project import Project
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    AutomationOutcome,
    BrowserAutomationProvider,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer

pytestmark = pytest.mark.integration


@dataclass
class FakeBrowserAutomationProvider(BrowserAutomationProvider):
    """
    A real (hand-written), controllable stand-in for the Playwright
    adapter -- not a mock of this project's own orchestration code,
    just a fake website. Records every call so tests can assert what
    the orchestration in cli.py actually did, and lets each outcome be
    configured per test.
    """

    login_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    open_form_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    remove_default_supplier_tag_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    search_supplier_result: bool = True
    select_supplier_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    create_supplier_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    fill_and_save_outcome: AutomationOutcome = field(
        default_factory=lambda: AutomationOutcome(success=True)
    )
    search_supplier_raises: Exception | None = None
    fill_and_save_raises: Exception | None = None

    calls: list[tuple[str, object]] = field(default_factory=list)

    def is_session_valid(self) -> bool:
        return True

    def login(self) -> AutomationOutcome:
        self.calls.append(("login", None))
        return self.login_outcome

    def open_import_invoice_form(self) -> AutomationOutcome:
        self.calls.append(("open_import_invoice_form", None))
        return self.open_form_outcome

    def remove_default_supplier_tag(self) -> AutomationOutcome:
        self.calls.append(("remove_default_supplier_tag", None))
        return self.remove_default_supplier_tag_outcome

    def search_supplier(self, name: str) -> bool:
        self.calls.append(("search_supplier", name))
        if self.search_supplier_raises is not None:
            raise self.search_supplier_raises
        return self.search_supplier_result

    def select_supplier(self, name: str) -> AutomationOutcome:
        self.calls.append(("select_supplier", name))
        return self.select_supplier_outcome

    def create_supplier(self, supplier: Supplier) -> AutomationOutcome:
        self.calls.append(("create_supplier", supplier))
        return self.create_supplier_outcome

    def search_medicine(self, name: str) -> bool:
        self.calls.append(("search_medicine", name))
        return True

    def select_medicine(self, name: str) -> AutomationOutcome:
        self.calls.append(("select_medicine", name))
        return AutomationOutcome(success=True)

    def create_medicine(self, medicine: Medicine) -> AutomationOutcome:
        self.calls.append(("create_medicine", medicine))
        return AutomationOutcome(success=True)

    def fill_and_save_invoice(
        self, invoice: PurchaseInvoice, dry_run: bool = False
    ) -> AutomationOutcome:
        self.calls.append(("fill_and_save_invoice", dry_run))
        if self.fill_and_save_raises is not None:
            raise self.fill_and_save_raises
        return self.fill_and_save_outcome

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _scripted_input(*responses: str) -> Callable[[str], str]:
    queue = list(responses)

    def _input(prompt: str) -> str:
        return queue.pop(0)

    return _input


@pytest.fixture()
def container(tmp_path: Path) -> ServiceContainer:
    service_container = ServiceContainer()
    register_infrastructure_services(service_container, tmp_path / "app")
    return service_container


def _seed_ready_invoice(container: ServiceContainer) -> PurchaseInvoice:
    """A PurchaseInvoice sitting READY_FOR_IMPORT with a real supplier
    and one real matched, fully-resolved line item."""
    container.resolve(ProjectRepository).add(
        Project(id="proj-1", name="Test Project", root_folder="C:/tmp")
    )
    container.resolve(SupplierRepository).add(Supplier(id="sup-1", name="Nice Pharma Co"))
    container.resolve(MedicineRepository).add(
        Medicine(
            id="med-1",
            medicine_code="TH1",
            name="Paracetamol 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
    )
    item = PurchaseItem(
        id="item-1",
        medicine_name="Paracetamol 500mg",
        unit=Unit(code="hop"),
        quantity=Quantity(Decimal("5")),
        unit_price=Money(Decimal("10000")),
        medicine_id="med-1",
        tax_type=TaxType.REDUCED,
        retail_units_per_purchase_unit=10,
    )
    invoice = PurchaseInvoice(
        id="inv-1",
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
        status=InvoiceStatus.READY_FOR_IMPORT,
        supplier_id="sup-1",
        items=[item],
    )
    container.resolve(PurchaseInvoiceRepository).add(invoice)
    return invoice


class TestRunAutomateNoInvoices:
    def test_returns_empty_and_touches_no_browser(
        self, container: ServiceContainer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No READY_FOR_IMPORT invoices exist, so run_automate must
        # return before ever launching Playwright -- this asserts that
        # early-return path directly, no browser required.
        results = cli.run_automate(container, input_fn=_scripted_input())

        assert results == []
        assert "READY_FOR_IMPORT" in capsys.readouterr().out


class TestAutomateOneInvoiceConfirmationGate:
    def test_wrong_phrase_skips_without_calling_the_provider(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider()
        input_fn = _scripted_input("khong dung")

        result = cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=False)

        assert result.skipped is True
        assert result.outcome is None
        assert provider.calls == []
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT


class TestAutomateOneInvoiceSuccess:
    def test_confirmed_success_reaches_imported(self, container: ServiceContainer) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider()
        input_fn = _scripted_input(cli._AUTOMATION_CONFIRMATION_PHRASE)

        result = cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=False)

        assert result.skipped is False
        assert result.outcome is not None
        assert result.outcome.success is True
        assert result.final_status == InvoiceStatus.IMPORTED.value
        assert provider.call_names() == [
            "open_import_invoice_form",
            "remove_default_supplier_tag",
            "search_supplier",
            "select_supplier",
            "fill_and_save_invoice",
        ]
        assert provider.calls[-1] == ("fill_and_save_invoice", False)
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.IMPORTED


class TestAutomateOneInvoiceEarlyFailure:
    def test_open_form_failure_leaves_invoice_retry_safe(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(
            open_form_outcome=AutomationOutcome(success=False, failure_reason="page not found")
        )
        input_fn = _scripted_input(cli._AUTOMATION_CONFIRMATION_PHRASE)

        result = cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=False)

        assert result.outcome is not None
        assert result.outcome.success is False
        assert result.final_status == InvoiceStatus.READY_FOR_IMPORT.value
        # fill_and_save_invoice must never be reached once the earlier
        # open_import_invoice_form step already failed.
        assert "fill_and_save_invoice" not in provider.call_names()
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT


class TestAutomateOneInvoiceSupplierCreation:
    def test_supplier_not_found_on_site_creates_it_from_the_real_repository(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(search_supplier_result=False)
        input_fn = _scripted_input(cli._AUTOMATION_CONFIRMATION_PHRASE)

        cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=False)

        assert "create_supplier" in provider.call_names()
        assert "select_supplier" not in provider.call_names()
        created_supplier = next(
            payload for name, payload in provider.calls if name == "create_supplier"
        )
        assert isinstance(created_supplier, Supplier)
        assert created_supplier.id == "sup-1"


class TestAutomateOneInvoiceUnexpectedException:
    def test_exception_during_fill_is_caught_and_leaves_invoice_retry_safe(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(
            fill_and_save_raises=TimeoutError("page.click: Timeout 30000ms exceeded")
        )
        input_fn = _scripted_input(cli._AUTOMATION_CONFIRMATION_PHRASE)

        result = cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=False)

        assert result.outcome is not None
        assert result.outcome.success is False
        assert "Timeout" in (result.outcome.failure_reason or "")
        assert result.final_status == InvoiceStatus.READY_FOR_IMPORT.value
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT


class TestAutomateOneInvoiceDryRun:
    def test_dry_run_never_transitions_or_persists_status(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider()
        input_fn = _scripted_input(cli._AUTOMATION_CONFIRMATION_PHRASE)

        result = cli._automate_one_invoice(invoice, container, provider, input_fn, dry_run=True)

        assert result.dry_run is True
        assert result.final_status == InvoiceStatus.READY_FOR_IMPORT.value
        assert provider.calls[-1] == ("fill_and_save_invoice", True)
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        # Real status in the database was never touched by dry_run --
        # not even the intermediate IMPORT_IN_PROGRESS step.
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT


def _run_outcome(*, skipped: bool = False, success: bool | None = True) -> cli.AutomationRunOutcome:
    outcome = None if skipped else AutomationOutcome(success=bool(success))
    return cli.AutomationRunOutcome(
        invoice_id="inv-1",
        invoice_number="INV-001",
        skipped=skipped,
        dry_run=True,
        outcome=outcome,
        final_status=InvoiceStatus.READY_FOR_IMPORT.value,
    )


class TestShouldPauseForDryRunReview:
    """
    Bug fix (PO-confirmed 2026-08, after the first fully-successful
    --dry-run run): run_automate()'s own try/finally unconditionally
    closed the browser the instant it returned, so a dry-run pass never
    gave the PO a chance to look at the browser before it disappeared.
    _should_pause_for_dry_run_review is the pure decision logic
    extracted out of run_automate (which itself always launches a real
    Playwright browser and so is not directly unit-testable here,
    matching this file's own established pattern for
    _automate_one_invoice/_resolve_supplier_on_site/
    _finish_automation_attempt).

    BUG FIX #2 (2026-08, PO-confirmed after seeing the new
    _wait_for_row_settled safety check itself correctly catch a real
    problem and stop): originally only paused on an all-success pass --
    inverted here, since a FAILURE is exactly when the PO most needs to
    see the browser's real state before it disappears.
    """

    def test_never_pauses_for_a_real_non_dry_run(self) -> None:
        results = [_run_outcome(success=True)]
        assert cli._should_pause_for_dry_run_review(results, dry_run=False) is False

    def test_never_pauses_when_nothing_was_attempted(self) -> None:
        results = [_run_outcome(skipped=True), _run_outcome(skipped=True)]
        assert cli._should_pause_for_dry_run_review(results, dry_run=True) is False

    def test_never_pauses_on_empty_results(self) -> None:
        assert cli._should_pause_for_dry_run_review([], dry_run=True) is False

    def test_pauses_when_every_attempted_invoice_succeeded(self) -> None:
        results = [_run_outcome(success=True), _run_outcome(skipped=True)]
        assert cli._should_pause_for_dry_run_review(results, dry_run=True) is True

    def test_also_pauses_when_an_attempted_invoice_failed(self) -> None:
        results = [_run_outcome(success=True), _run_outcome(success=False)]
        assert cli._should_pause_for_dry_run_review(results, dry_run=True) is True


class TestDryRunReviewHadAFailure:
    """Picks the right pause message (success vs. failure) for _should_pause_for_dry_run_review's
    own prompt -- see run_automate's own call site."""

    def test_false_when_every_attempted_invoice_succeeded(self) -> None:
        results = [_run_outcome(success=True), _run_outcome(skipped=True)]
        assert cli._dry_run_review_had_a_failure(results) is False

    def test_true_when_any_attempted_invoice_failed(self) -> None:
        results = [_run_outcome(success=True), _run_outcome(success=False)]
        assert cli._dry_run_review_had_a_failure(results) is True

    def test_false_when_nothing_was_attempted(self) -> None:
        results = [_run_outcome(skipped=True)]
        assert cli._dry_run_review_had_a_failure(results) is False


class TestResolveSupplierOnSite:
    def test_found_supplier_is_selected(self, container: ServiceContainer) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(search_supplier_result=True)

        outcome = cli._resolve_supplier_on_site(invoice, container, provider, "Nice Pharma Co")

        assert outcome.success is True
        assert provider.call_names() == [
            "remove_default_supplier_tag",
            "search_supplier",
            "select_supplier",
        ]

    def test_missing_supplier_id_fails_without_calling_the_provider(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        invoice.supplier_id = None
        provider = FakeBrowserAutomationProvider()

        outcome = cli._resolve_supplier_on_site(invoice, container, provider, "Nice Pharma Co")

        assert outcome.success is False
        assert provider.calls == []

    def test_search_supplier_exception_is_caught_as_a_failure(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(
            search_supplier_raises=RuntimeError("network blip")
        )

        outcome = cli._resolve_supplier_on_site(invoice, container, provider, "Nice Pharma Co")

        assert outcome.success is False
        assert "network blip" in (outcome.failure_reason or "")

    def test_default_tag_removal_runs_before_search_supplier(
        self, container: ServiceContainer
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, "forgot to wire it up"): while
        # the invoice form's default "Hang nhap le" supplier tag is
        # still present, the "Nha cung cap" row does not match what a
        # real supplier search expects -- this must run first, every
        # time, not just on the happy path.
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider()

        cli._resolve_supplier_on_site(invoice, container, provider, "Nice Pharma Co")

        assert provider.calls[0] == ("remove_default_supplier_tag", None)

    def test_default_tag_removal_failure_stops_before_search_supplier(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        provider = FakeBrowserAutomationProvider(
            remove_default_supplier_tag_outcome=AutomationOutcome(
                success=False, failure_reason="tag removal broke"
            )
        )

        outcome = cli._resolve_supplier_on_site(invoice, container, provider, "Nice Pharma Co")

        assert outcome.success is False
        assert outcome.failure_reason == "tag removal broke"
        assert provider.call_names() == ["remove_default_supplier_tag"]


class TestFinishAutomationAttempt:
    def test_success_transitions_to_imported(self, container: ServiceContainer) -> None:
        invoice = _seed_ready_invoice(container)
        invoice.transition_to(InvoiceStatus.IMPORT_IN_PROGRESS)
        repository = container.resolve(PurchaseInvoiceRepository)
        repository.update(invoice)

        result = cli._finish_automation_attempt(
            invoice, repository, AutomationOutcome(success=True), dry_run=False
        )

        assert result.final_status == InvoiceStatus.IMPORTED.value
        reloaded = repository.get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.IMPORTED

    def test_failure_returns_to_ready_for_import_via_import_failed(
        self, container: ServiceContainer
    ) -> None:
        invoice = _seed_ready_invoice(container)
        invoice.transition_to(InvoiceStatus.IMPORT_IN_PROGRESS)
        repository = container.resolve(PurchaseInvoiceRepository)
        repository.update(invoice)

        result = cli._finish_automation_attempt(
            invoice,
            repository,
            AutomationOutcome(success=False, failure_reason="save button missing"),
            dry_run=False,
        )

        assert result.final_status == InvoiceStatus.READY_FOR_IMPORT.value
        reloaded = repository.get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT
