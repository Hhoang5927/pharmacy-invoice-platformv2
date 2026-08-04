"""
Real (no Gemini calls, no network) integration tests for
composition_root.cli.run_review() -- Composition Root Stage C (PO-
confirmed 2026-08). Real SQLite (via register_infrastructure_services
against a temp app_root), real domain entities persisted through real
repositories, real SubmitInvoiceReviewUseCase/InvoiceValidator --  only
the keyboard is simulated, via run_review's own injectable input_fn
(not a mock of any of this project's own code).
"""

from __future__ import annotations

from collections.abc import Callable
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
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer

pytestmark = pytest.mark.integration


def _scripted_input(*responses: str) -> Callable[[str], str]:
    """A real, deterministic stand-in for keyboard input -- not a mock of
    this project's own code, just a controlled stdin."""
    queue = list(responses)

    def _input(prompt: str) -> str:
        return queue.pop(0)

    return _input


@pytest.fixture()
def container(tmp_path: Path) -> ServiceContainer:
    service_container = ServiceContainer()
    register_infrastructure_services(service_container, tmp_path / "app")
    return service_container


def _seed_invoice_needing_packaging_ratio(container: ServiceContainer) -> PurchaseItem:
    """
    A PurchaseInvoice sitting UNDER_REVIEW for exactly one reason: its
    only item has no confirmed retail_units_per_purchase_unit (Part 3's
    "hoc 1 lan, nho mai mai" gap -- otherwise fully resolved: a real
    supplier, a real matched medicine, 5% VAT).
    """
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
    )
    invoice = PurchaseInvoice(
        id="inv-1",
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
        status=InvoiceStatus.UNDER_REVIEW,
        supplier_id="sup-1",
        items=[item],
    )
    container.resolve(PurchaseInvoiceRepository).add(invoice)
    return item


class TestNoInvoicesToReview:
    def test_prints_a_clear_message_and_returns_empty(
        self, container: ServiceContainer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        results = cli.run_review(container, input_fn=_scripted_input())

        assert results == []
        assert "Không có hóa đơn" in capsys.readouterr().out


class TestApprovingWithACorrection:
    def test_correcting_the_packaging_ratio_and_approving_advances_the_invoice(
        self, container: ServiceContainer
    ) -> None:
        _seed_invoice_needing_packaging_ratio(container)
        input_fn = _scripted_input(
            "s",  # choose: correct a field
            "item.item-1.retail_units_per_purchase_unit",  # field name
            "10",  # field value
            "a",  # now approve
        )

        results = cli.run_review(container, input_fn=input_fn)

        assert len(results) == 1
        assert results[0].is_success, results[0].errors
        assert results[0].value is not None
        assert results[0].value.status == InvoiceStatus.READY_FOR_IMPORT.value

        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.READY_FOR_IMPORT
        assert reloaded.items[0].retail_units_per_purchase_unit == 10

    def test_the_correction_is_learned_onto_the_medicine_for_next_time(
        self, container: ServiceContainer
    ) -> None:
        _seed_invoice_needing_packaging_ratio(container)
        input_fn = _scripted_input(
            "s", "item.item-1.retail_units_per_purchase_unit", "10", "a"
        )

        cli.run_review(container, input_fn=input_fn)

        medicine = container.resolve(MedicineRepository).get_by_id("med-1")
        assert medicine is not None
        assert medicine.retail_units_per_purchase_unit == 10


class TestRejecting:
    def test_rejecting_leaves_the_invoice_under_review(self, container: ServiceContainer) -> None:
        _seed_invoice_needing_packaging_ratio(container)
        input_fn = _scripted_input("r")

        results = cli.run_review(container, input_fn=input_fn)

        assert len(results) == 1
        assert results[0].is_success
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.UNDER_REVIEW


class TestSkipping:
    def test_empty_input_skips_without_calling_the_use_case(
        self, container: ServiceContainer
    ) -> None:
        _seed_invoice_needing_packaging_ratio(container)
        input_fn = _scripted_input("")

        results = cli.run_review(container, input_fn=input_fn)

        assert results == []
        reloaded = container.resolve(PurchaseInvoiceRepository).get_by_id("inv-1")
        assert reloaded is not None
        assert reloaded.status is InvoiceStatus.UNDER_REVIEW

    def test_invalid_choice_reprompts_instead_of_crashing(
        self, container: ServiceContainer
    ) -> None:
        _seed_invoice_needing_packaging_ratio(container)
        input_fn = _scripted_input("zz", "r")

        results = cli.run_review(container, input_fn=input_fn)

        assert len(results) == 1
