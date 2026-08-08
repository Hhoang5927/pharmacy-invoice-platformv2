"""
Unit tests for use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase,
focused on Part 3's per-item packaging-ratio reviewer confirmation
("item.<id>.retail_units_per_purchase_unit" corrected_fields keys) --
the "hoc 1 lan, nho mai mai" mechanism's final step: a reviewer's
answer both unblocks this invoice and is learned onto the resolved
Medicine for every future invoice. Baseline approve/reject flows are
covered lightly, for context, not exhaustively.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TypeVar

import pytest

from pharmacy_invoice_automation.application.commands import SubmitInvoiceReviewCommand
from pharmacy_invoice_automation.application.pipeline.party_matching_step import (
    PartyMatchingStep,
)
from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.application.use_cases.submit_invoice_review_use_case import (
    SubmitInvoiceReviewUseCase,
)
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
    MedicineValidationService,
)
from pharmacy_invoice_automation.domain.services.purchase_policy import PurchasePolicy
from pharmacy_invoice_automation.domain.services.supplement_classification_service import (
    SupplementClassificationService,
)
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit

_T = TypeVar("_T")


@dataclass
class _FakePurchaseInvoiceRepository(PurchaseInvoiceRepository):
    invoices: dict[str, PurchaseInvoice] = field(default_factory=dict)

    def add(self, invoice: PurchaseInvoice) -> None:
        self.invoices[invoice.id] = invoice

    def get_by_id(self, invoice_id: str) -> PurchaseInvoice | None:
        return self.invoices.get(invoice_id)

    def find_by_invoice_number(self, invoice_number: str) -> PurchaseInvoice | None:
        return next(
            (i for i in self.invoices.values() if i.invoice_number == invoice_number), None
        )

    def list_by_project(self, project_id: str) -> list[PurchaseInvoice]:
        return [i for i in self.invoices.values() if i.project_id == project_id]

    def list_by_status(self, status: InvoiceStatus) -> list[PurchaseInvoice]:
        return [i for i in self.invoices.values() if i.status is status]

    def search(
        self,
        *,
        invoice_number: str | None = None,
        supplier_name: str | None = None,
        medicine_name: str | None = None,
        invoice_date: date | None = None,
    ) -> list[PurchaseInvoice]:
        return list(self.invoices.values())

    def update(self, invoice: PurchaseInvoice) -> None:
        self.invoices[invoice.id] = invoice


@dataclass
class _FakeMedicineRepository(MedicineRepository):
    medicines: dict[str, Medicine] = field(default_factory=dict)
    update_calls: list[str] = field(default_factory=list)
    add_calls: list[str] = field(default_factory=list)

    def add(self, medicine: Medicine) -> None:
        self.add_calls.append(medicine.id)
        self.medicines[medicine.id] = medicine

    def get_by_id(self, medicine_id: str) -> Medicine | None:
        return self.medicines.get(medicine_id)

    def find_by_name(self, name: str) -> Medicine | None:
        return next((m for m in self.medicines.values() if m.name.lower() == name.lower()), None)

    def find_by_code(self, medicine_code: str) -> Medicine | None:
        return next((m for m in self.medicines.values() if m.medicine_code == medicine_code), None)

    def get_highest_code_sequence_number(self) -> int:
        return 0

    def list_all(self) -> list[Medicine]:
        return list(self.medicines.values())

    def update(self, medicine: Medicine) -> None:
        self.update_calls.append(medicine.id)
        self.medicines[medicine.id] = medicine


@dataclass
class _FakeSupplierRepository(SupplierRepository):
    suppliers: list[Supplier] = field(default_factory=list)

    def add(self, supplier: Supplier) -> None:
        self.suppliers.append(supplier)

    def get_by_id(self, supplier_id: str) -> Supplier | None:
        return next((s for s in self.suppliers if s.id == supplier_id), None)

    def find_by_name(self, name: str) -> Supplier | None:
        return next((s for s in self.suppliers if s.name.lower() == name.lower()), None)

    def find_by_tax_code(self, tax_code: TaxCode) -> Supplier | None:
        return next((s for s in self.suppliers if s.tax_code == tax_code), None)

    def list_all(self) -> list[Supplier]:
        return list(self.suppliers)

    def update(self, supplier: Supplier) -> None:
        pass


class _SynchronousTransactionCoordinator(TransactionCoordinator):
    def run_in_transaction(self, unit_of_work: Callable[[], _T]) -> _T:
        return unit_of_work()


def _make_medicine(**overrides: object) -> Medicine:
    defaults: dict[str, object] = {
        "id": "med-1",
        "medicine_code": "TH1",
        "name": "Amoxicillin 500mg",
        "medicine_type": MedicineType.OVER_THE_COUNTER,
        "unit": Unit(code="vien"),
    }
    defaults.update(overrides)
    return Medicine(**defaults)  # type: ignore[arg-type]


def _make_item(**overrides: object) -> PurchaseItem:
    defaults: dict[str, object] = {
        "id": "item-1",
        "medicine_name": "Amoxicillin 500mg",
        "unit": Unit(code="hop"),
        "quantity": Quantity(Decimal("10")),
        "unit_price": Money(Decimal("100000")),
        "medicine_id": "med-1",
    }
    defaults.update(overrides)
    return PurchaseItem(**defaults)  # type: ignore[arg-type]


def _make_invoice(*items: PurchaseItem) -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        id="inv-1",
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
        supplier_id="sup-1",
        status=InvoiceStatus.UNDER_REVIEW,
    )
    for item in items:
        invoice.add_item(item)
    return invoice


@pytest.fixture()
def repositories() -> tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository]:
    return _FakePurchaseInvoiceRepository(), _FakeMedicineRepository()


@pytest.fixture()
def use_case(
    repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
) -> SubmitInvoiceReviewUseCase:
    invoice_repository, medicine_repository = repositories
    party_matching_step = PartyMatchingStep(
        purchase_policy=PurchasePolicy(),
        medicine_validation_service=MedicineValidationService(),
        supplement_classification_service=SupplementClassificationService(),
        supplier_repository=_FakeSupplierRepository(),
        medicine_repository=medicine_repository,
        ai_provider=None,
        allow_ai_fallback_classification=False,
    )
    return SubmitInvoiceReviewUseCase(
        purchase_invoice_repository=invoice_repository,
        medicine_repository=medicine_repository,
        invoice_validator=InvoiceValidator(),
        transaction_coordinator=_SynchronousTransactionCoordinator(),
        party_matching_step=party_matching_step,
    )


class TestPackagingRatioConfirmation:
    """
    STRATEGY CHANGE (2026-08, PO decision, explicit Domain change):
    InvoiceValidator no longer requires retail_units_per_purchase_unit
    to be resolved at all (see that validator's own docstring) -- a
    packaging-ratio correction is no longer needed to unblock an
    invoice. The reviewer-correction mechanism itself
    ("item.<id>.retail_units_per_purchase_unit") is untouched and still
    applies/learns exactly as before, for whatever legitimately still
    uses this data (Medicine catalog metadata) -- these tests prove
    both halves: the correction still works, AND its absence no longer
    blocks the invoice.
    """

    def test_confirming_the_ratio_still_applies_and_the_invoice_succeeds(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine())
        item = _make_item()
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.retail_units_per_purchase_unit": "100"},
                reviewer_approved=True,
            )
        )

        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT
        assert item.retail_units_per_purchase_unit == 100

    def test_confirmation_is_learned_onto_the_medicine_for_next_time(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine = _make_medicine()
        medicine_repository.add(medicine)
        item = _make_item()
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.retail_units_per_purchase_unit": "100"},
                reviewer_approved=True,
            )
        )

        assert medicine.retail_units_per_purchase_unit == 100
        assert "med-1" in medicine_repository.update_calls

    def test_does_not_overwrite_a_medicine_that_already_has_a_value(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine = _make_medicine(retail_units_per_purchase_unit=50)
        medicine_repository.add(medicine)
        item = _make_item()
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.retail_units_per_purchase_unit": "100"},
                reviewer_approved=True,
            )
        )

        # This line still gets the reviewer's answer...
        assert item.retail_units_per_purchase_unit == 100
        # ...but the catalog's already-known value is never silently overwritten.
        assert medicine.retail_units_per_purchase_unit == 50

    def test_non_numeric_correction_is_ignored_and_no_longer_blocks_the_invoice(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine())
        item = _make_item()
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.retail_units_per_purchase_unit": "not-a-number"},
                reviewer_approved=True,
            )
        )

        # The bad correction itself is still ignored, not a crash --
        # but nothing about it being unresolved blocks the invoice
        # anymore (InvoiceValidator no longer checks this at all).
        assert item.retail_units_per_purchase_unit is None
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT

    def test_no_confirmation_at_all_no_longer_blocks_the_invoice(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine())
        item = _make_item()
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1", corrected_fields={}, reviewer_approved=True
            )
        )

        assert item.retail_units_per_purchase_unit is None
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT


class TestMedicineTypeCorrection:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions): a genuinely
    new medicine the original processing pass could not classify (no
    explicit Rx/OTC text on the invoice, no prior classification on
    file) previously left item.medicine_id permanently None with no way
    to unblock it -- "item.<id>.medicine_type" lets the reviewer supply
    the missing classification directly, which now immediately
    (re-)resolves/creates the medicine instead of just setting a field.
    Mirrors the real invoice.pdf regression this fixes (Naphacogyl /
    Dươc Phẩm Nam Hà, 00001567): a brand-new medicine, empty catalog,
    no Rx/OTC column on the invoice at all.
    """

    def test_creates_and_resolves_a_brand_new_medicine(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        # unit="vien" sidesteps the (separately-tested) packaging-ratio
        # gap entirely, so this test isolates just the classification
        # mechanism: does it get all the way to READY_FOR_IMPORT.
        item = _make_item(medicine_id=None, medicine_name="Naphacogyl", unit=Unit(code="vien"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "prescription"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id is not None
        created = medicine_repository.get_by_id(item.medicine_id)
        assert created is not None
        assert created.name == "Naphacogyl"
        assert created.medicine_type is MedicineType.PRESCRIPTION
        assert item.medicine_id in medicine_repository.add_calls
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT

    def test_otc_alias_is_accepted(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        item = _make_item(medicine_id=None)
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "otc"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id is not None
        created = medicine_repository.get_by_id(item.medicine_id)
        assert created is not None
        assert created.medicine_type is MedicineType.OVER_THE_COUNTER

    def test_learns_an_already_confirmed_packaging_ratio_onto_the_new_medicine(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        # Exactly the real Naphacogyl scenario: a PRIOR review submission
        # already confirmed retail_units_per_purchase_unit=20 (persisted
        # on the item), but medicine_id was still None going into this
        # submission -- this one only supplies the missing classification.
        invoice_repository, medicine_repository = repositories
        item = _make_item(medicine_id=None, retail_units_per_purchase_unit=20)
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "prescription"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id is not None
        created = medicine_repository.get_by_id(item.medicine_id)
        assert created is not None
        assert created.retail_units_per_purchase_unit == 20

    def test_resolves_to_an_existing_medicine_instead_of_duplicating(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        existing = _make_medicine(id="med-existing", name="Naphacogyl")
        medicine_repository.add(existing)
        medicine_repository.add_calls.clear()  # only the fixture's own add() above, not ours
        item = _make_item(medicine_id=None, medicine_name="Naphacogyl")
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                # Ignored: an exact-name match already exists, so no
                # classification decision is even needed here.
                corrected_fields={f"item.{item.id}.medicine_type": "over_the_counter"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id == "med-existing"
        assert medicine_repository.add_calls == []

    def test_unrecognized_value_is_ignored_not_a_crash(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id=None)
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "not-a-real-value"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id is None
        assert result.is_success is False
        assert invoice.status is InvoiceStatus.UNDER_REVIEW

    def test_already_resolved_item_is_never_reclassified(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine(medicine_type=MedicineType.OVER_THE_COUNTER))
        item = _make_item(medicine_id="med-1")  # already resolved
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "prescription"},
                reviewer_approved=True,
            )
        )

        assert item.medicine_id == "med-1"
        assert medicine_repository.get_by_id("med-1").medicine_type is MedicineType.OVER_THE_COUNTER

    def test_two_items_sharing_an_unclassified_name_do_not_create_duplicates(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        first = _make_item(id="item-1", medicine_id=None, medicine_name="Coldi")
        second = _make_item(id="item-2", medicine_id=None, medicine_name="Coldi")
        invoice = _make_invoice(first, second)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={
                    f"item.{first.id}.medicine_type": "over_the_counter",
                    f"item.{second.id}.medicine_type": "over_the_counter",
                },
                reviewer_approved=True,
            )
        )

        assert first.medicine_id is not None
        assert first.medicine_id == second.medicine_id
        assert len(medicine_repository.add_calls) == 1

    def test_two_different_unclassified_medicines_get_different_codes(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        # Bug fix (found while testing this feature, PO-confirmed
        # 2026-08): mirrors the real invoice.pdf regression (Coldi AND
        # Coldi-B DNH both needing classification in one submission) --
        # neither is persisted until _save()'s transaction runs, so
        # naively regenerating the "next" medicine_code per item would
        # hand out the same code twice.
        invoice_repository, medicine_repository = repositories
        first = _make_item(id="item-1", medicine_id=None, medicine_name="Coldi")
        second = _make_item(id="item-2", medicine_id=None, medicine_name="Coldi-B DNH")
        invoice = _make_invoice(first, second)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={
                    f"item.{first.id}.medicine_type": "over_the_counter",
                    f"item.{second.id}.medicine_type": "over_the_counter",
                },
                reviewer_approved=True,
            )
        )

        assert first.medicine_id is not None
        assert second.medicine_id is not None
        assert first.medicine_id != second.medicine_id
        first_medicine = medicine_repository.get_by_id(first.medicine_id)
        second_medicine = medicine_repository.get_by_id(second.medicine_id)
        assert first_medicine is not None
        assert second_medicine is not None
        assert first_medicine.medicine_code != second_medicine.medicine_code


class TestRetailUnitOverride:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions): mirrors the
    real invoice.pdf regression this fixes (Coldi/Coldi-B DNH, Duoc
    Pham Nam Ha 00001567) -- ĐVT is "Hop" but the invoice's own
    packaging note says it holds exactly one "lo" (bottle). A reviewer
    supplies both item.<id>.medicine_type (still needed -- no explicit
    Rx/OTC text on this invoice layout) AND
    item.<id>.retail_unit_override="lo" in the same submission.
    """

    def test_full_flow_unblocks_a_liquid_medicine_all_the_way_to_ready_for_import(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        item = _make_item(medicine_id=None, medicine_name="Coldi", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={
                    f"item.{item.id}.medicine_type": "over_the_counter",
                    f"item.{item.id}.retail_unit_override": "lo",
                },
                reviewer_approved=True,
            )
        )

        assert item.medicine_id is not None
        created = medicine_repository.get_by_id(item.medicine_id)
        assert created is not None
        assert created.name == "Coldi"
        assert created.unit.code == "lo"
        assert created.retail_units_per_purchase_unit == 1
        assert item.retail_units_per_purchase_unit == 1
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT

    def test_without_the_override_the_invoice_still_succeeds_but_the_medicine_defaults_to_vien(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        # STRATEGY CHANGE (2026-08, PO decision, explicit Domain change):
        # InvoiceValidator no longer requires retail_units_per_purchase_unit
        # to be resolved at all (see that validator's own docstring) --
        # retail_unit_override is no longer needed to UNBLOCK this
        # invoice (this test used to assert the opposite: that omitting
        # it left the invoice blocked on the packaging-ratio gap). It
        # still matters for a genuinely NEW Medicine's own catalog unit
        # though: without it, "hop" (not an atomic dispensing form)
        # still defaults to Vien, exactly as before this change.
        invoice_repository, medicine_repository = repositories
        item = _make_item(medicine_id=None, medicine_name="Coldi", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.medicine_type": "over_the_counter"},
                reviewer_approved=True,
            )
        )

        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT
        assert item.medicine_id is not None
        created = medicine_repository.get_by_id(item.medicine_id)
        assert created is not None
        assert created.unit.code == "vien"
        assert item.retail_units_per_purchase_unit is None

    def test_override_learns_onto_an_already_resolved_medicine_without_changing_its_unit(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine = _make_medicine(name="Coldi", unit=Unit(code="hop"))
        medicine_repository.add(medicine)
        item = _make_item(medicine_id="med-1", medicine_name="Coldi", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.retail_unit_override": "lo"},
                reviewer_approved=False,
            )
        )

        assert item.retail_units_per_purchase_unit == 1
        assert medicine.retail_units_per_purchase_unit == 1
        # Already-established Medicine keeps its own (pre-existing) unit.
        assert medicine.unit.code == "hop"

    def test_unrecognized_unit_code_is_ignored_not_a_crash(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id=None, medicine_name="Coldi", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={
                    f"item.{item.id}.medicine_type": "over_the_counter",
                    f"item.{item.id}.retail_unit_override": "not-a-real-unit",
                },
                reviewer_approved=True,
            )
        )

        # The bad override itself is still ignored, not a crash -- but
        # (STRATEGY CHANGE, 2026-08) it being unresolved no longer
        # blocks the invoice (InvoiceValidator no longer checks this).
        assert item.retail_units_per_purchase_unit is None
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT


class TestConfirmedWebsiteUnitRatio:
    """
    PO decision (2026-08): "Coldi-B DNH" 1 Hop trên hóa đơn = 1 Lọ trên
    web is a genuine, correct site-vs-invoice naming difference (not a
    bug) that infrastructure.automation.playwright_adapter's own
    _verify_unit_matches_invoice can only discover at automation time.
    A reviewer confirms the ratio here so a later automate run can
    trust it instead of raising UnitMismatchError again.
    """

    def test_confirms_ratio_directly_onto_the_item(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id="med-1", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.confirmed_website_unit_ratio": "1"},
                reviewer_approved=True,
            )
        )

        assert item.confirmed_website_unit_ratio == Decimal("1")
        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT

    def test_non_integer_ratio_is_accepted(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id="med-1", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.confirmed_website_unit_ratio": "10"},
                reviewer_approved=False,
            )
        )

        assert item.confirmed_website_unit_ratio == Decimal("10")

    def test_non_numeric_ratio_is_ignored_not_a_crash(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id="med-1", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.confirmed_website_unit_ratio": "not-a-number"},
                reviewer_approved=True,
            )
        )

        assert item.confirmed_website_unit_ratio is None
        assert result.is_success

    def test_zero_or_negative_ratio_is_ignored_not_a_crash(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, _ = repositories
        item = _make_item(medicine_id="med-1", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.confirmed_website_unit_ratio": "0"},
                reviewer_approved=False,
            )
        )

        assert item.confirmed_website_unit_ratio is None

    def test_ratio_is_not_learned_onto_the_resolved_medicine(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine = _make_medicine(name="Coldi-B DNH", unit=Unit(code="hop"))
        medicine_repository.add(medicine)
        item = _make_item(medicine_id="med-1", medicine_name="Coldi-B DNH", unit=Unit(code="hop"))
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1",
                corrected_fields={f"item.{item.id}.confirmed_website_unit_ratio": "1"},
                reviewer_approved=False,
            )
        )

        assert item.confirmed_website_unit_ratio == Decimal("1")
        assert not medicine_repository.update_calls


class TestBaselineApproveRejectFlows:
    def test_reviewer_rejecting_keeps_the_invoice_in_review(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine())
        item = _make_item(retail_units_per_purchase_unit=100)
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1", corrected_fields={}, reviewer_approved=False
            )
        )

        assert result.is_success
        assert invoice.status is InvoiceStatus.UNDER_REVIEW

    def test_fully_resolved_and_approved_invoice_advances_to_ready_for_import(
        self,
        use_case: SubmitInvoiceReviewUseCase,
        repositories: tuple[_FakePurchaseInvoiceRepository, _FakeMedicineRepository],
    ) -> None:
        invoice_repository, medicine_repository = repositories
        medicine_repository.add(_make_medicine())
        item = _make_item(retail_units_per_purchase_unit=100)
        invoice = _make_invoice(item)
        invoice_repository.add(invoice)

        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="inv-1", corrected_fields={}, reviewer_approved=True
            )
        )

        assert result.is_success
        assert invoice.status is InvoiceStatus.READY_FOR_IMPORT

    def test_unknown_invoice_id_fails_cleanly(self, use_case: SubmitInvoiceReviewUseCase) -> None:
        result = use_case.execute(
            SubmitInvoiceReviewCommand(
                invoice_id="does-not-exist", corrected_fields={}, reviewer_approved=True
            )
        )

        assert result.is_success is False
