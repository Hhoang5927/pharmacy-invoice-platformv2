"""
Unit tests for application.pipeline.party_matching_step.PartyMatchingStep,
focused on the VAT-based supplement/non-medicine exclusion behavior
(Part 3.1, PO-confirmed 2026-08: VAT is the ONLY criterion, replacing
an earlier medicine-name-keyword heuristic): a line whose VAT is not
the 5% registered-medicine rate is removed from invoice.items, recorded
as a note (never an issue), and never gets a Medicine created for it; a
line whose VAT could not be read at all is neither kept nor excluded --
it becomes an issue (routes to human review).

Uses real Domain services (PurchasePolicy, MedicineValidationService,
SupplementClassificationService are concrete, not ports) and small
in-memory fakes for the two repository ports.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from pharmacy_invoice_automation.application.pipeline.party_matching_step import (
    PartyMatchingStep,
)
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
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
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit


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


@dataclass
class _FakeMedicineRepository(MedicineRepository):
    medicines: list[Medicine] = field(default_factory=list)
    update_calls: list[str] = field(default_factory=list)

    def add(self, medicine: Medicine) -> None:
        self.medicines.append(medicine)

    def get_by_id(self, medicine_id: str) -> Medicine | None:
        return next((m for m in self.medicines if m.id == medicine_id), None)

    def find_by_name(self, name: str) -> Medicine | None:
        return next((m for m in self.medicines if m.name.lower() == name.lower()), None)

    def find_by_code(self, medicine_code: str) -> Medicine | None:
        return next((m for m in self.medicines if m.medicine_code == medicine_code), None)

    def get_highest_code_sequence_number(self) -> int:
        return 0

    def list_all(self) -> list[Medicine]:
        return list(self.medicines)

    def update(self, medicine: Medicine) -> None:
        self.update_calls.append(medicine.id)


def _make_item(medicine_name: str, **overrides: object) -> PurchaseItem:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "medicine_name": medicine_name,
        "unit": Unit(code="hop"),
        "quantity": Quantity(Decimal("1")),
        "unit_price": Money(Decimal("10000")),
        # 5% VAT -- a registered medicine, per the VAT-based
        # classification rule -- so tests unrelated to that rule are
        # not incidentally caught by it. Override explicitly to
        # exercise the classification itself.
        "tax_type": TaxType.REDUCED,
    }
    defaults.update(overrides)
    return PurchaseItem(**defaults)  # type: ignore[arg-type]


def _make_invoice(*items: PurchaseItem) -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        id=str(uuid.uuid4()),
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
    )
    for item in items:
        invoice.add_item(item)
    return invoice


def _make_ocr_result(supplier_name: str = "Cong ty Duoc ABC") -> OCRResult:
    from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus

    return OCRResult(
        status=OCRStatus.SUCCEEDED,
        raw_invoice_number="INV-001",
        raw_invoice_date=date.today(),
        raw_supplier_name=supplier_name,
        raw_supplier_tax_code=None,
        raw_supplier_address=None,
        raw_prescription_classification_text="Thuoc khong ke don",
        raw_grand_total=None,
        lines=(),
        overall_confidence=0.95,
    )


@pytest.fixture()
def step() -> tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]:
    supplier_repository = _FakeSupplierRepository()
    medicine_repository = _FakeMedicineRepository()
    party_matching_step = PartyMatchingStep(
        purchase_policy=PurchasePolicy(),
        medicine_validation_service=MedicineValidationService(),
        supplement_classification_service=SupplementClassificationService(),
        supplier_repository=supplier_repository,
        medicine_repository=medicine_repository,
        ai_provider=None,
        allow_ai_fallback_classification=False,
    )
    return party_matching_step, supplier_repository, medicine_repository


class TestSupplementExclusion:
    def test_non_5_percent_vat_line_is_removed_from_invoice_items(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        supplement_item = _make_item("Vitamin C 1000mg", tax_type=TaxType.STANDARD)
        invoice = _make_invoice(supplement_item)

        party_matching_step.execute(invoice, _make_ocr_result())

        assert supplement_item not in invoice.items
        assert len(invoice.items) == 0

    def test_exclusion_is_a_note_not_an_issue(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        invoice = _make_invoice(_make_item("Some Supplement XYZ", tax_type=TaxType.STANDARD))

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        # A new-supplier note is also expected here (the fake repository
        # starts empty) -- the assertion is specifically that the
        # VAT-based exclusion itself landed in notes, not issues.
        assert outcome.issues == ()
        assert any("vat" in note.lower() for note in outcome.notes)

    def test_no_medicine_is_created_for_a_non_5_percent_vat_line(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        invoice = _make_invoice(_make_item("Omega 3", tax_type=TaxType.EXEMPT))

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.new_medicines == ()
        assert medicine_repository.medicines == []

    @pytest.mark.parametrize("tax_type", [TaxType.STANDARD, TaxType.EXEMPT, TaxType.OTHER])
    def test_every_non_5_percent_vat_rate_is_excluded(
        self,
        step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository],
        tax_type: TaxType,
    ) -> None:
        party_matching_step, _, _ = step
        invoice = _make_invoice(_make_item("Some Product", tax_type=tax_type))

        party_matching_step.execute(invoice, _make_ocr_result())

        assert len(invoice.items) == 0

    def test_mixed_invoice_only_excludes_the_non_5_percent_vat_line(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        medicine_item = _make_item("Paracetamol 500mg", tax_type=TaxType.REDUCED)
        supplement_item = _make_item("Vitamin C", tax_type=TaxType.STANDARD)
        invoice = _make_invoice(medicine_item, supplement_item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert medicine_item in invoice.items
        assert supplement_item not in invoice.items
        assert len(outcome.new_medicines) == 1
        assert outcome.new_medicines[0].name == "Paracetamol 500mg"
        assert medicine_item.medicine_id is not None


class TestExcludedSupplementTotal:
    """
    Deviation D10 fix (PO-confirmed 2026-08, final -- no exceptions):
    the VAT!=5% exclusion is deliberate and correct, so its value must
    be captured (not just discarded) so
    pipeline.invoice_validation_step.InvoiceValidationStep can account
    for it when reconciling against the invoice's stated grand total.
    """

    def test_none_when_nothing_is_excluded(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        invoice = _make_invoice(_make_item("Paracetamol 500mg", tax_type=TaxType.REDUCED))

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.excluded_supplement_total is None

    def test_captures_the_tax_inclusive_value_of_one_excluded_line(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        # Real Traphaco invoice.pdf line ("Slaska New"): pre-tax 76364 @
        # TS 8% -> tax-inclusive 82473.
        party_matching_step, _, _ = step
        excluded_item = _make_item(
            "Slaska New",
            tax_type=TaxType.EIGHT_PERCENT,
            quantity=Quantity(Decimal("2")),
            unit_price=Money(Decimal("38182")),
        )
        invoice = _make_invoice(excluded_item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.excluded_supplement_total is not None
        assert outcome.excluded_supplement_total.amount == Decimal("82473")

    def test_sums_across_multiple_excluded_lines(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        first = _make_item(
            "Slaska New",
            tax_type=TaxType.EIGHT_PERCENT,
            quantity=Quantity(Decimal("2")),
            unit_price=Money(Decimal("38182")),
        )
        second = _make_item("Vitamin C", tax_type=TaxType.STANDARD)  # 10000 + 10% = 11000
        invoice = _make_invoice(first, second)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.excluded_supplement_total is not None
        assert outcome.excluded_supplement_total.amount == Decimal("82473") + Decimal("11000")

    def test_a_kept_medicine_line_does_not_contribute_to_the_excluded_total(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        kept = _make_item("Paracetamol 500mg", tax_type=TaxType.REDUCED)
        excluded = _make_item("Vitamin C", tax_type=TaxType.STANDARD)  # 10000 + 10% = 11000
        invoice = _make_invoice(kept, excluded)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.excluded_supplement_total is not None
        assert outcome.excluded_supplement_total.amount == Decimal("11000")


class TestUnreadableVatRoutesToReview:
    def test_unreadable_vat_is_neither_kept_nor_excluded(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Paracetamol 500mg", tax_type=None)
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        # Not excluded (still on the invoice)...
        assert item in invoice.items
        # ...but not resolved to a medicine either.
        assert item.medicine_id is None
        assert outcome.new_medicines == ()

    def test_unreadable_vat_is_an_issue_not_a_note(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        invoice = _make_invoice(_make_item("Paracetamol 500mg", tax_type=None))

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert any("vat" in issue.lower() for issue in outcome.issues)

    def test_only_the_unresolved_line_is_affected_in_a_mixed_invoice(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        resolved_item = _make_item("Amoxicillin 500mg", tax_type=TaxType.REDUCED)
        unresolved_item = _make_item("Paracetamol 500mg", tax_type=None)
        invoice = _make_invoice(resolved_item, unresolved_item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert resolved_item.medicine_id is not None
        assert unresolved_item.medicine_id is None
        assert len(outcome.new_medicines) == 1


class TestOrdinaryMedicineStillWorksAfterTheChange:
    def test_new_medicine_is_still_created_normally(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        item = _make_item("Amoxicillin 500mg")
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item in invoice.items
        assert len(outcome.new_medicines) == 1
        assert any("New medicine" in note for note in outcome.notes)
        assert item.medicine_id == outcome.new_medicines[0].id

    def test_existing_medicine_is_matched_not_recreated(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Amoxicillin 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="hop"),
        )
        medicine_repository.add(existing)
        item = _make_item("Amoxicillin 500mg")
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.new_medicines == ()
        assert item.medicine_id == existing.id

    def test_two_new_medicines_in_one_invoice_get_different_codes(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        # Bug fix (found while testing the review-flow fixes, PO-
        # confirmed 2026-08): neither new medicine is actually persisted
        # until InvoicePersistenceStep runs, well after this whole loop
        # returns -- get_highest_code_sequence_number() would otherwise
        # see the same DB state for both and hand out the same code.
        party_matching_step, _, _ = step
        first = _make_item("Amoxicillin 500mg")
        second = _make_item("Paracetamol 500mg")
        invoice = _make_invoice(first, second)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert len(outcome.new_medicines) == 2
        codes = {medicine.medicine_code for medicine in outcome.new_medicines}
        assert len(codes) == 2

    def test_new_medicine_uses_the_configured_code_prefix(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        """
        PO decision (2026-08): each pharmacy this system processes
        invoices for is a separate, independent operation, so the "TH"
        code prefix must be changeable per run (AppSettings
        .medicine_code_prefix) without a code change.
        """
        _, supplier_repository, medicine_repository = step
        party_matching_step = PartyMatchingStep(
            purchase_policy=PurchasePolicy(),
            medicine_validation_service=MedicineValidationService(),
            supplement_classification_service=SupplementClassificationService(),
            supplier_repository=supplier_repository,
            medicine_repository=medicine_repository,
            ai_provider=None,
            allow_ai_fallback_classification=False,
            medicine_code_prefix="DTN",
        )
        item = _make_item("Amoxicillin 500mg")
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert len(outcome.new_medicines) == 1
        assert outcome.new_medicines[0].medicine_code == "DTN1"


class TestPackagingRatioResolution:
    """
    Part 3 ("hoc 1 lan, nho mai mai", PO-confirmed 2026-08): every
    resolved item's retail_units_per_purchase_unit is set in priority
    order -- this invoice's own OCR reading, else the Medicine's
    already-remembered value, else a review-routing issue -- and a
    newly-created Medicine's unit is always Vien (not the invoice
    line's purchase unit).
    """

    def test_new_medicines_unit_is_always_vien_not_the_purchase_unit(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Amoxicillin 500mg", unit=Unit(code="hop"))
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.new_medicines[0].unit.code == "vien"

    def test_ocr_reading_is_used_for_this_line_and_learned_onto_a_new_medicine(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Amoxicillin 500mg", retail_units_per_purchase_unit=100)
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit == 100
        assert outcome.new_medicines[0].retail_units_per_purchase_unit == 100
        assert any("packaging ratio" in note.lower() for note in outcome.notes)

    def test_ocr_reading_is_learned_onto_an_existing_medicine_that_lacked_one(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Amoxicillin 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        medicine_repository.add(existing)
        item = _make_item("Amoxicillin 500mg", retail_units_per_purchase_unit=100)
        invoice = _make_invoice(item)

        party_matching_step.execute(invoice, _make_ocr_result())

        assert existing.retail_units_per_purchase_unit == 100

    def test_ocr_reading_this_invoice_is_used_even_when_it_differs_from_the_stored_value(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Amoxicillin 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
            retail_units_per_purchase_unit=50,
        )
        medicine_repository.add(existing)
        item = _make_item("Amoxicillin 500mg", retail_units_per_purchase_unit=100)
        invoice = _make_invoice(item)

        party_matching_step.execute(invoice, _make_ocr_result())

        # Used for this line as OCR read it...
        assert item.retail_units_per_purchase_unit == 100
        # ...but the already-known catalog value is never silently overwritten.
        assert existing.retail_units_per_purchase_unit == 50

    def test_falls_back_to_the_catalogs_remembered_value_when_ocr_has_none(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Amoxicillin 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
            retail_units_per_purchase_unit=50,
        )
        medicine_repository.add(existing)
        item = _make_item("Amoxicillin 500mg", retail_units_per_purchase_unit=None)
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit == 50
        assert outcome.issues == ()

    def test_neither_ocr_nor_catalog_known_is_left_unresolved_not_routed_to_review(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        # STRATEGY CHANGE (2026-08, PO decision): automation no longer
        # converts through retail_units_per_purchase_unit at all (it
        # verifies the site's own displayed unit directly instead), so
        # an unresolved packaging ratio no longer blocks automation via
        # a forced review issue -- it is simply left None.
        party_matching_step, _, _ = step
        item = _make_item("Amoxicillin 500mg", retail_units_per_purchase_unit=None)
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit is None
        assert outcome.issues == ()

    def test_an_item_already_denominated_in_vien_needs_no_conversion(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item(
            "Amoxicillin 500mg", unit=Unit(code="vien"), retail_units_per_purchase_unit=None
        )
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit == 1
        assert outcome.issues == ()


class TestAtomicDispensingUnitsNoConversionNeeded:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions): a purchase
    unit that is already its own final dispensing form -- a
    liquid/cream/injectable container (chai/lo/tuyp/ong), never
    subdivided further -- needs no Vien conversion, and a newly-created
    Medicine for it keeps that same unit rather than being forced
    through Vien. Deliberately excludes "goi" (sachet): a sachet CAN
    contain multiple tablets, so it still needs an OCR-stated or
    reviewer-confirmed ratio like any other multi-unit purchase pack.
    Mirrors the real invoice.pdf regression this fixes (Coldi/Coldi-B
    DNH, Duoc Pham Nam Ha 00001567).
    """

    @pytest.mark.parametrize("unit_code", ["chai", "lo", "tuyp", "ong"])
    def test_ratio_auto_resolves_to_1_with_no_issue(
        self,
        step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository],
        unit_code: str,
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item(
            "Coldi", unit=Unit(code=unit_code), retail_units_per_purchase_unit=None
        )
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit == 1
        assert outcome.issues == ()

    @pytest.mark.parametrize("unit_code", ["chai", "lo", "tuyp", "ong"])
    def test_new_medicines_unit_stays_the_purchase_unit_not_vien(
        self,
        step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository],
        unit_code: str,
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Coldi", unit=Unit(code=unit_code))
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert outcome.new_medicines[0].unit.code == unit_code

    def test_goi_is_not_treated_as_atomic_and_stays_unresolved_without_blocking(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        # STRATEGY CHANGE (2026-08): same reasoning as
        # test_neither_ocr_nor_catalog_known_is_left_unresolved_not_routed_to_review
        # -- "goi" still correctly falls outside _NO_CONVERSION_NEEDED_UNIT_CODES
        # (a sachet can contain multiple tablets), but an unresolved
        # ratio no longer blocks automation.
        party_matching_step, _, _ = step
        item = _make_item(
            "Some Sachet Product", unit=Unit(code="goi"), retail_units_per_purchase_unit=None
        )
        invoice = _make_invoice(item)

        outcome = party_matching_step.execute(invoice, _make_ocr_result())

        assert item.retail_units_per_purchase_unit is None
        assert outcome.issues == ()


class TestResolveItemWithExplicitClassification:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions): a genuinely
    new medicine the original processing pass could not classify (no
    explicit Rx/OTC text on the invoice, no prior classification on
    file) previously left item.medicine_id permanently None with no way
    to unblock it. This method lets
    use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase
    supply a reviewer-confirmed classification directly and immediately
    (re-)resolve/create the medicine -- exercised here directly
    (skipping the review use case's own plumbing, already covered by
    its own tests).
    """

    def test_creates_a_new_medicine_with_the_reviewer_supplied_classification(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        item = _make_item("Naphacogyl", unit=Unit(code="vien"))

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.PRESCRIPTION
        )

        assert outcome.newly_created_medicine is not None
        assert outcome.newly_created_medicine.medicine_type is MedicineType.PRESCRIPTION
        assert item.medicine_id == outcome.newly_created_medicine.id
        # Caller (SubmitInvoiceReviewUseCase) is responsible for persisting it.
        assert medicine_repository.medicines == []

    def test_resolves_to_an_existing_medicine_by_name_instead_of_creating(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Naphacogyl",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        medicine_repository.add(existing)
        item = _make_item("Naphacogyl")

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.PRESCRIPTION
        )

        assert outcome.newly_created_medicine is None
        assert item.medicine_id == existing.id

    def test_learns_an_already_set_packaging_ratio_onto_the_new_medicine(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item(
            "Naphacogyl", unit=Unit(code="hop"), retail_units_per_purchase_unit=20
        )

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.PRESCRIPTION
        )

        assert outcome.newly_created_medicine is not None
        assert outcome.newly_created_medicine.retail_units_per_purchase_unit == 20

    def test_new_medicines_unit_follows_the_same_atomic_unit_rule(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Coldi", unit=Unit(code="chai"))

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.OVER_THE_COUNTER
        )

        assert outcome.newly_created_medicine is not None
        assert outcome.newly_created_medicine.unit.code == "chai"
        assert item.retail_units_per_purchase_unit == 1

    def test_does_not_call_medicine_repository_directly_leaves_persistence_to_the_caller(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Naphacogyl",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="hop"),
        )
        medicine_repository.add(existing)
        item = _make_item(
            "Naphacogyl", unit=Unit(code="hop"), retail_units_per_purchase_unit=20
        )

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.PRESCRIPTION
        )

        assert outcome.updated_existing_medicine is existing
        assert existing.retail_units_per_purchase_unit == 20
        # Mutated in memory, but NOT written through by this method itself.
        assert "existing-med-1" not in medicine_repository.update_calls


class TestRetailUnitOverride:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions): for a line
    whose ĐVT (purchase unit, e.g. "Hop"/"Thung") is a box/carton that
    the invoice's own packaging note says holds exactly ONE bottle/
    tube/vial (e.g. Coldi, "Thung x 160 hop x 1 lo x 15ml") -- distinct
    from the chai/lo/tuyp/ong-IS-the-ĐVT case
    (TestAtomicDispensingUnitsNoConversionNeeded), where the ĐVT itself
    already reads as one of those units and no reviewer input is
    needed at all. Here the ĐVT is genuinely "Hop", so nothing
    auto-detects this -- a reviewer must say so explicitly via
    use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase's
    "item.<id>.retail_unit_override" -- exercised here directly,
    mirroring the real invoice.pdf regression this fixes (Coldi/Coldi-B
    DNH, Duoc Pham Nam Ha 00001567).
    """

    def test_override_becomes_the_new_medicines_own_unit_not_vien(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        # As SubmitInvoiceReviewUseCase._apply_retail_unit_overrides
        # would have already done before calling this.
        item = _make_item("Coldi", unit=Unit(code="hop"), retail_units_per_purchase_unit=1)

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.OVER_THE_COUNTER, Unit(code="lo")
        )

        assert outcome.newly_created_medicine is not None
        assert outcome.newly_created_medicine.unit.code == "lo"
        assert outcome.newly_created_medicine.retail_units_per_purchase_unit == 1
        assert item.medicine_id == outcome.newly_created_medicine.id

    def test_override_is_never_applied_to_an_existing_medicine(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, medicine_repository = step
        existing = Medicine(
            id="existing-med-1",
            medicine_code="TH1",
            name="Coldi",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="hop"),
        )
        medicine_repository.add(existing)
        item = _make_item("Coldi", unit=Unit(code="hop"), retail_units_per_purchase_unit=1)

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.OVER_THE_COUNTER, Unit(code="lo")
        )

        assert outcome.newly_created_medicine is None
        assert item.medicine_id == existing.id
        # The already-established Medicine keeps its own unit -- the
        # override is only for a genuinely NEW Medicine.
        assert existing.unit.code == "hop"

    def test_no_override_falls_back_to_the_atomic_unit_then_vien_rule(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        item = _make_item("Amoxicillin 500mg", unit=Unit(code="hop"))

        outcome = party_matching_step.resolve_item_with_explicit_classification(
            item, MedicineType.OVER_THE_COUNTER
        )

        assert outcome.newly_created_medicine is not None
        assert outcome.newly_created_medicine.unit.code == "vien"


class TestPreviouslyClassifiedCatalogLookup:
    """
    Bug fix (PO-confirmed 2026-08, final -- no exceptions):
    _classify_new_medicine used to always receive a hard-coded empty
    dict for "a previous classification of the same medicine name
    already in the local catalog," so that resolution path could never
    actually succeed. Verified directly against the private method
    (white-box): the public execute() path cannot observe this
    independently of PurchasePolicy.resolve_medicine's own exact-name
    match (which already finds a same-name catalog entry first), so
    this is the only way to prove the dict itself is now real, wired
    data instead of a permanent placeholder.
    """

    def test_a_populated_catalog_classification_is_actually_used(
        self, step: tuple[PartyMatchingStep, _FakeSupplierRepository, _FakeMedicineRepository]
    ) -> None:
        party_matching_step, _, _ = step
        # No Rx/OTC text on the invoice (e.g. the real Duoc Pham Nam Ha
        # 00001567 layout) -- classification can only succeed via the
        # previously-classified-by-name path.
        from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus

        ocr_result = OCRResult(
            status=OCRStatus.SUCCEEDED,
            raw_invoice_number="INV-001",
            raw_invoice_date=date.today(),
            raw_supplier_name="Cong ty Duoc ABC",
            raw_supplier_tax_code=None,
            raw_supplier_address=None,
            raw_prescription_classification_text=None,
            raw_grand_total=None,
            lines=(),
            overall_confidence=0.95,
        )

        classification = party_matching_step._classify_new_medicine(  # noqa: SLF001
            "Naphacogyl",
            ocr_result,
            {"naphacogyl": MedicineType.PRESCRIPTION},
            [],
        )

        assert classification is MedicineType.PRESCRIPTION
