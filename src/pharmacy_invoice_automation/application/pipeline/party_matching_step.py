"""
Pipeline Step: PartyMatchingStep.

Resolves the invoice's supplier and every item's medicine against the
existing catalog, using Domain's own services.purchase_policy.PurchasePolicy
for the resolve-or-create decision and
services.medicine_validation_service.MedicineValidationService for
code sequencing and prescription/OTC classification.

Design note: supplier resolution and medicine resolution follow the
exact same "exists -> select, else -> create" shape (Business Rules).
Rather than a separate top-level "MatchMedicineUseCase" plus a
duplicate "MatchSupplierUseCase" nobody asked for, both are handled by
this one Step, avoiding two near-identical classes.

Blocking issues vs. informational notes: creating a new supplier or
medicine when none matched is the normal, automatic path Business
Rules describe ("Neu chua ton tai -> Tao moi") -- it must NOT force
every invoice with a first-time supplier or medicine into human review,
or the Human Review Queue would fill up with routine, correct work.
Only genuine problems (nothing could be resolved at all, or a
classification came from an AI guess rather than a matched rule) are
``issues`` (which use_cases.process_invoice_use_case.ProcessInvoiceUseCase
treats as review-forcing); routine creation is a ``note`` (surfaced to
the caller as an informational warning only).

Supplement/non-medicine exclusion by VAT (Product Owner-confirmed,
2026-08 -- REPLACES an earlier medicine-name-keyword heuristic entirely,
per an explicit correction; see
services.supplement_classification_service.SupplementClassificationService's
own docstring): a line item whose VAT is not the 5% registered-medicine
rate is removed from the invoice before any resolution/creation is
attempted -- no Medicine is ever created for it -- and recorded as a
``note``, the same routine-automatic-decision channel as a new
supplier/medicine creation, per the same reasoning: this is expected,
normal filtering, not a problem worth blocking the invoice or forcing
manual review over. A line whose VAT could not be read at all is a
different case entirely -- neither kept nor excluded, it becomes an
``issue`` (see below), since "unknown" must never be silently treated
as either outcome.

Deviation D10 fix (PO-confirmed 2026-08, final -- no exceptions): this
VAT!=5% exclusion is deliberate, correct behavior, not an anomaly -- so
it must never itself cause a false "does not reconcile" report
downstream. Before an excluded item is dropped, this step captures its
own tax-inclusive value (``PartyMatchingOutcome.excluded_supplement_total``,
summed across every excluded line, None if none were excluded) so
pipeline.invoice_validation_step.InvoiceValidationStep can account for
it: the invoice's OCR'd stated grand total still reflects the FULL,
original invoice (it was never adjusted for this exclusion), so
reconciliation must add this value back onto the remaining, tracked
items' total before comparing -- not compare the remaining-items total
directly against the untouched stated total.

Retail-unit-conversion "learn once, remember forever" (Part 3, PO-
confirmed 2026-08): invoices are usually denominated in a purchase unit
(Hop/Vi/Tui) but the site always retails by Vien (tablet). Every
resolved item's retail_units_per_purchase_unit is set here, in priority
order: (1) this invoice's own OCR reading, if present -- also learned
onto the Medicine catalog record when it did not already have one; (2)
else the Medicine's already-remembered value, if any; (3) else this is
a genuine gap -- an ``issue`` routes just this line to review, per the
same issues/notes distinction as everywhere else in this step. An item
whose own unit is already Vien needs no conversion and is resolved to
1 directly, never routed to review over a non-existent gap.

Root-cause fix alongside this (flagged for the record, not silently
folded in): a newly-created Medicine's ``unit`` is now always Vien --
the site's own "Don vi xuat le" (retail dispensing unit) dropdown,
which every recorded medicine-creation flow fills from this exact
field (see infrastructure.automation.playwright_adapter.create_medicine)
-- rather than the invoice line's purchase unit (Hop/Vi/...), which was
the previous, incorrect value flowing into this field. PurchaseItem.unit
(the purchase-side unit) is completely unaffected by this fix.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.ports.services.ai_provider import AIProvider
from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
    MedicineValidationService,
)
from pharmacy_invoice_automation.domain.services.purchase_policy import PurchasePolicy
from pharmacy_invoice_automation.domain.services.supplement_classification_service import (
    SupplementClassificationService,
)
from pharmacy_invoice_automation.domain.services.tax_calculation_service import (
    TaxCalculationService,
)
from pharmacy_invoice_automation.domain.value_objects.address import Address
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

_CLASSIFICATION_LABELS = ("prescription", "over_the_counter")
# The site's own retail dispensing unit defaults to Vien (Part 3, PO-
# confirmed 2026-08) for a purchase unit that genuinely needs tablet
# conversion (Hop/Vi/Tui/...).
_DEFAULT_RETAIL_DISPENSING_UNIT = Unit(code="vien")
# Purchase units that are already their own final dispensing form -- no
# Vien conversion is needed or even meaningful (a bottle/tube/vial of
# liquid/cream/injectable has no tablet count), so the ratio resolves
# to 1 and a newly-created Medicine's own retail unit stays exactly
# this purchase unit, instead of being forced to Vien (PO-confirmed
# 2026-08, final -- no exceptions). Deliberately excludes "goi"
# (sachet): a sachet CAN contain multiple tablets, so it still needs an
# OCR-stated or reviewer-confirmed ratio like any other multi-unit
# purchase pack.
_NO_CONVERSION_NEEDED_UNIT_CODES: frozenset[str] = frozenset(
    {_DEFAULT_RETAIL_DISPENSING_UNIT.code, "chai", "lo", "tuyp", "ong"}
)


@dataclass(frozen=True)
class PartyMatchingOutcome:
    """
    Every new Supplier/Medicine this step had to create, plus a
    genuine blocking ``issues`` list and a purely informational
    ``notes`` list -- see this module's docstring for the distinction.
    """

    new_suppliers: tuple[Supplier, ...]
    new_medicines: tuple[Medicine, ...]
    issues: tuple[str, ...]
    notes: tuple[str, ...]
    excluded_supplement_total: Money | None = None
    """
    Sum of every VAT!=5%-excluded line's own tax-inclusive value (Deviation
    D10 fix, PO-confirmed 2026-08), None if nothing was excluded. See this
    module's docstring for why pipeline.invoice_validation_step.InvoiceValidationStep
    needs this to reconcile correctly against the invoice's stated grand total.
    """


@dataclass(frozen=True)
class ItemMedicineResolutionOutcome:
    """
    Outcome of resolve_item_with_explicit_classification() -- resolving
    or creating ONE PurchaseItem's medicine using a classification a
    human reviewer supplied directly (bug fix, PO-confirmed 2026-08,
    final -- no exceptions), bypassing OCR/prior-classification
    auto-detection entirely. At most one of the two Medicine fields is
    ever set; both None means an existing medicine was matched with
    nothing new to persist (e.g. its packaging ratio was already
    known).
    """

    newly_created_medicine: Medicine | None
    """A brand-new Medicine the caller must persist via medicine_repository.add()."""
    updated_existing_medicine: Medicine | None
    """
    An already-persisted Medicine whose packaging ratio was just
    learned -- caller must medicine_repository.update() it.
    """
    issues: tuple[str, ...]
    notes: tuple[str, ...]


class PartyMatchingStep:
    """Resolves an invoice's supplier and medicines against the existing catalog."""

    def __init__(
        self,
        purchase_policy: PurchasePolicy,
        medicine_validation_service: MedicineValidationService,
        supplement_classification_service: SupplementClassificationService,
        supplier_repository: SupplierRepository,
        medicine_repository: MedicineRepository,
        ai_provider: AIProvider | None,
        allow_ai_fallback_classification: bool,
        tax_calculation_service: TaxCalculationService | None = None,
    ) -> None:
        self._purchase_policy = purchase_policy
        self._medicine_validation_service = medicine_validation_service
        self._supplement_classification_service = supplement_classification_service
        self._supplier_repository = supplier_repository
        self._medicine_repository = medicine_repository
        self._ai_provider = ai_provider
        self._allow_ai_fallback_classification = allow_ai_fallback_classification
        # Pure, stateless Domain service (no ports, no I/O) -- defaulting it
        # here is not hiding a real dependency, matching the same pattern
        # already used for PricePolicy in PlaywrightBrowserAutomationProvider.
        self._tax_calculation_service = tax_calculation_service or TaxCalculationService()

    def execute(self, invoice: PurchaseInvoice, ocr_result: OCRResult) -> PartyMatchingOutcome:
        """Resolve the invoice's supplier and every item's medicine, creating as needed."""
        issues: list[str] = []
        notes: list[str] = []
        new_suppliers = self._resolve_supplier(invoice, ocr_result, issues, notes)
        new_medicines, excluded_supplement_total = self._resolve_medicines(
            invoice, ocr_result, issues, notes
        )
        return PartyMatchingOutcome(
            new_suppliers=tuple(new_suppliers),
            new_medicines=tuple(new_medicines),
            issues=tuple(issues),
            notes=tuple(notes),
            excluded_supplement_total=excluded_supplement_total,
        )

    def _resolve_supplier(
        self,
        invoice: PurchaseInvoice,
        ocr_result: OCRResult,
        issues: list[str],
        notes: list[str],
    ) -> list[Supplier]:
        if not ocr_result.raw_supplier_name:
            issues.append("No supplier name extracted; supplier could not be resolved.")
            return []

        existing = self._supplier_repository.list_all()
        by_name = {s.name.strip().lower(): s for s in existing}
        by_tax_code = {s.tax_code.value: s for s in existing if s.tax_code is not None}

        resolution = self._purchase_policy.resolve_supplier(
            ocr_result.raw_supplier_name, ocr_result.raw_supplier_tax_code, by_name, by_tax_code
        )
        if resolution.is_failure:
            issues.append(resolution.failure_reason or "Supplier resolution failed.")
            return []

        outcome = resolution.unwrap()
        if not outcome.requires_creation:
            assert outcome.existing_supplier is not None
            invoice.assign_supplier(outcome.existing_supplier.id)
            return []

        new_supplier = Supplier(
            id=str(uuid.uuid4()),
            name=ocr_result.raw_supplier_name,
            tax_code=(
                TaxCode(ocr_result.raw_supplier_tax_code)
                if ocr_result.raw_supplier_tax_code
                else None
            ),
            address=(
                Address(ocr_result.raw_supplier_address)
                if ocr_result.raw_supplier_address
                else None
            ),
        )
        invoice.assign_supplier(new_supplier.id)
        notes.append(f"New supplier '{new_supplier.name}' created automatically.")
        return [new_supplier]

    def _resolve_medicines(
        self,
        invoice: PurchaseInvoice,
        ocr_result: OCRResult,
        issues: list[str],
        notes: list[str],
    ) -> tuple[list[Medicine], Money | None]:
        existing = self._medicine_repository.list_all()
        by_name = {m.name.strip().lower(): m for m in existing}
        # Real catalog lookup (bug fix, PO-confirmed 2026-08, final -- no
        # exceptions): previously this was always an empty dict passed to
        # _classify_new_medicine, so "a previous classification of the
        # same medicine name already in the local catalog" could never
        # actually be found.
        previously_classified_by_normalized_name = {
            name: medicine.medicine_type for name, medicine in by_name.items()
        }
        new_medicines: list[Medicine] = []
        excluded_supplement_total: Money | None = None
        # Bug fix (found while testing the review-flow fixes, PO-
        # confirmed 2026-08): new medicines are only actually persisted
        # later (InvoicePersistenceStep's medicine_repository.add(),
        # after this whole loop returns) -- so if 2+ NEW medicines are
        # created in this one invoice,
        # medicine_repository.get_highest_code_sequence_number() would
        # see the same "highest so far" DB state for every one of them
        # and hand out the SAME medicine_code, failing later on a UNIQUE
        # constraint. Tracking how many have been reserved so far in
        # THIS call, purely in memory, avoids querying the DB again.
        new_medicines_reserved_so_far = 0

        # Snapshot -- items excluded as supplements are removed from
        # invoice.items mid-loop.
        for item in list(invoice.items):
            supplement_check = self._supplement_classification_service.is_supplement(
                item.tax_type
            )
            if supplement_check.is_failure:
                issues.append(
                    supplement_check.failure_reason
                    or f"Could not classify '{item.medicine_name}' as supplement or not "
                    f"(VAT not read)."
                )
                continue
            if supplement_check.unwrap():
                assert item.tax_type is not None
                excluded_value = self._tax_calculation_service.calculate_total_with_tax(
                    item.line_total, item.tax_type
                )
                excluded_supplement_total = (
                    excluded_value
                    if excluded_supplement_total is None
                    else excluded_supplement_total + excluded_value
                )
                invoice.remove_item(item.id)
                notes.append(
                    f"Line '{item.medicine_name}' excluded automatically: VAT "
                    f"({item.tax_type.value}) is not the 5% registered-medicine rate, so "
                    f"no official medicine registration -- treated as supplement/non-"
                    f"medicine. No Medicine record was created for it."
                )
                continue

            resolution = self._purchase_policy.resolve_medicine(item.medicine_name, by_name)
            if resolution.is_failure:
                issues.append(resolution.failure_reason or "Medicine resolution failed.")
                continue

            outcome = resolution.unwrap()
            if not outcome.requires_creation:
                assert outcome.existing_medicine is not None
                item.assign_medicine(outcome.existing_medicine.id)
                self._resolve_packaging_ratio(
                    item, outcome.existing_medicine, issues, notes, persist=True
                )
                continue

            medicine_type = self._classify_new_medicine(
                item.medicine_name, ocr_result, previously_classified_by_normalized_name, issues
            )
            if medicine_type is None:
                issues.append(
                    f"Medicine '{item.medicine_name}' needs manual prescription/OTC "
                    f"classification before it can be created."
                )
                continue

            new_medicine = self._build_new_medicine(
                item, medicine_type, sequence_offset=new_medicines_reserved_so_far
            )
            new_medicines_reserved_so_far += 1
            item.assign_medicine(new_medicine.id)
            self._resolve_packaging_ratio(item, new_medicine, issues, notes, persist=False)
            new_medicines.append(new_medicine)
            # Keep this new medicine visible to any later item on the same invoice.
            by_name[new_medicine.name.strip().lower()] = new_medicine
            previously_classified_by_normalized_name[new_medicine.name.strip().lower()] = (
                new_medicine.medicine_type
            )
            notes.append(
                f"New medicine '{new_medicine.name}' ({new_medicine.medicine_code}) created."
            )

        return new_medicines, excluded_supplement_total

    def _build_new_medicine(
        self,
        item: PurchaseItem,
        medicine_type: MedicineType,
        retail_unit_override: Unit | None = None,
        *,
        sequence_offset: int = 0,
    ) -> Medicine:
        """
        Shared by both the auto-classified path (_resolve_medicines)
        and the reviewer-driven path
        (resolve_item_with_explicit_classification) -- exactly one way
        a brand-new Medicine gets built, regardless of where its
        classification came from.

        ``sequence_offset`` (bug fix, PO-confirmed 2026-08): the number
        of OTHER brand-new medicines already reserved a code earlier in
        this same caller's batch, but not yet persisted (new medicines
        are only actually written by
        pipeline.invoice_persistence_step.InvoicePersistenceStep or
        use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase's
        own transaction, both AFTER this returns) -- without this,
        creating 2+ new medicines in one invoice/review submission
        would see the same "highest code so far" from the database
        every time and collide on the same medicine_code.
        """
        highest_sequence = (
            self._medicine_repository.get_highest_code_sequence_number() + sequence_offset
        )
        code_result = self._medicine_validation_service.generate_next_medicine_code(
            highest_sequence
        )
        return Medicine(
            id=str(uuid.uuid4()),
            medicine_code=code_result.unwrap(),
            name=item.medicine_name,
            medicine_type=medicine_type,
            unit=self._resolve_new_medicine_unit(item.unit, retail_unit_override),
        )

    def _resolve_new_medicine_unit(
        self, purchase_unit: Unit, retail_unit_override: Unit | None = None
    ) -> Unit:
        """
        The retail dispensing unit for a brand-new Medicine, in
        priority order (bug fix, PO-confirmed 2026-08, final -- no
        exceptions):

        1. ``retail_unit_override`` -- a reviewer's explicit statement
           (via "item.<id>.retail_unit_override") that THIS invoice's
           purchase unit (e.g. "Hop"/"Thung"), despite its ĐVT text,
           is actually a complete retail-dispensable unit in disguise
           (a box/carton the invoice's own packaging note says holds
           exactly one bottle/tube/vial -- e.g. Coldi, "Thung x 160 hop
           x 1 lo x 15ml"). Only meaningful for a genuinely NEW
           Medicine -- an already-existing one's unit is never
           retroactively changed this way.
        2. ``purchase_unit`` itself, when it is already an atomic,
           final dispensing form on its own (Vien, or a purchase unit
           that is ITSELF chai/lo/tuyp/ong -- Part 3 + liquid/cream/
           injectable fix, PO-confirmed 2026-08).
        3. Otherwise (Hop/Vi/Tui/... genuinely needing tablet
           conversion), defaults to Vien, per the original Part 3 rule.
        """
        if retail_unit_override is not None:
            return retail_unit_override
        if purchase_unit.code in _NO_CONVERSION_NEEDED_UNIT_CODES:
            return purchase_unit
        return _DEFAULT_RETAIL_DISPENSING_UNIT

    def resolve_item_with_explicit_classification(
        self,
        item: PurchaseItem,
        medicine_type: MedicineType,
        retail_unit_override: Unit | None = None,
        *,
        sequence_offset: int = 0,
    ) -> ItemMedicineResolutionOutcome:
        """
        Resolve or create ``item``'s medicine using a MedicineType a
        human reviewer supplied directly (bug fix, PO-confirmed
        2026-08, final -- no exceptions:
        use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase
        calls this for an "item.<id>.medicine_type" correction), instead
        of this step's own OCR/prior-classification auto-detection in
        _classify_new_medicine. Used when the original processing pass
        could not classify a genuinely new medicine (no explicit
        Rx/OTC text on the invoice, no prior classification on file) --
        previously this left the item's medicine_id permanently None
        with no way for a reviewer to ever unblock it, since neither
        this step nor SubmitInvoiceReviewUseCase ever attempted
        resolution again.

        ``retail_unit_override`` (bug fix, PO-confirmed 2026-08, final
        -- no exceptions) is
        SubmitInvoiceReviewUseCase's already-parsed "item.<id>.
        retail_unit_override" reviewer correction, when given -- it has
        ALREADY set item.retail_units_per_purchase_unit=1 by the time
        this runs (that correction is applied before this one; see that
        use case's own docstring), so this method only needs to use it
        for _resolve_new_medicine_unit's sake, for a genuinely NEW
        Medicine. It is never applied to an already-existing Medicine.

        ``sequence_offset`` -- see _build_new_medicine's own docstring
        (bug fix found while testing this feature, PO-confirmed
        2026-08): the caller must pass how many OTHER brand-new
        medicines it has already had this method create earlier in the
        SAME review submission, so two different not-yet-classified
        medicine names corrected in one submission (e.g. Coldi AND
        Coldi-B DNH) don't collide on the same medicine_code -- neither
        is actually persisted until SubmitInvoiceReviewUseCase's own
        transaction runs, after every correction in the submission has
        been applied.

        The reviewer's classification always wins here -- never
        re-guessed, never second-guessed against OCR. Deliberately does
        NOT call medicine_repository.update()/add() itself (unlike this
        step's own persist=True path) -- the caller
        (SubmitInvoiceReviewUseCase) persists everything together in
        its own transaction, per Stage 05's "entire invoice succeeds or
        entire invoice fails" rule.
        """
        issues: list[str] = []
        notes: list[str] = []
        existing = self._medicine_repository.list_all()
        by_name = {m.name.strip().lower(): m for m in existing}

        resolution = self._purchase_policy.resolve_medicine(item.medicine_name, by_name)
        if resolution.is_failure:
            issues.append(resolution.failure_reason or "Medicine resolution failed.")
            return ItemMedicineResolutionOutcome(None, None, tuple(issues), tuple(notes))

        outcome = resolution.unwrap()
        if not outcome.requires_creation:
            assert outcome.existing_medicine is not None
            existing_medicine = outcome.existing_medicine
            had_ratio_before = existing_medicine.retail_units_per_purchase_unit is not None
            item.assign_medicine(existing_medicine.id)
            self._resolve_packaging_ratio(item, existing_medicine, issues, notes, persist=False)
            learned_now = (
                not had_ratio_before
                and existing_medicine.retail_units_per_purchase_unit is not None
            )
            return ItemMedicineResolutionOutcome(
                newly_created_medicine=None,
                updated_existing_medicine=existing_medicine if learned_now else None,
                issues=tuple(issues),
                notes=tuple(notes),
            )

        new_medicine = self._build_new_medicine(
            item, medicine_type, retail_unit_override, sequence_offset=sequence_offset
        )
        item.assign_medicine(new_medicine.id)
        self._resolve_packaging_ratio(item, new_medicine, issues, notes, persist=False)
        notes.append(
            f"New medicine '{new_medicine.name}' ({new_medicine.medicine_code}) created "
            f"during review (reviewer-confirmed classification: {medicine_type.value})."
        )
        return ItemMedicineResolutionOutcome(
            newly_created_medicine=new_medicine,
            updated_existing_medicine=None,
            issues=tuple(issues),
            notes=tuple(notes),
        )

    def _resolve_packaging_ratio(
        self,
        item: PurchaseItem,
        medicine: Medicine,
        issues: list[str],
        notes: list[str],
        *,
        persist: bool,
    ) -> None:
        """
        Resolve ``item``'s retail_units_per_purchase_unit in priority
        order: already an atomic/no-conversion-needed unit, else this
        invoice's own OCR reading, else the Medicine's already-
        remembered value, else a review-routing ``issue`` (see this
        module's docstring). ``persist`` is False for a newly-created
        Medicine not yet in the repository (its learned value reaches
        storage later, via
        pipeline.invoice_persistence_step.InvoicePersistenceStep's
        ``medicine_repository.add()``) and True for one already
        persisted, which needs an explicit ``update()`` here instead.
        """
        if item.unit.code in _NO_CONVERSION_NEEDED_UNIT_CODES:
            # Already the final dispensing form -- Vien, or a
            # liquid/cream/injectable container (chai/lo/tuyp/ong) never
            # subdivided further -- so there is no conversion to
            # perform or ask about (PO-confirmed 2026-08, final -- no
            # exceptions).
            item.assign_retail_units_per_purchase_unit(1)
            return

        if item.retail_units_per_purchase_unit is not None:
            if medicine.retail_units_per_purchase_unit is None:
                medicine.assign_retail_units_per_purchase_unit(
                    item.retail_units_per_purchase_unit
                )
                if persist:
                    self._medicine_repository.update(medicine)
                notes.append(
                    f"Packaging ratio for '{medicine.name}' learned from this invoice "
                    f"({item.retail_units_per_purchase_unit} vien per {item.unit.code}) "
                    f"and saved for future use."
                )
            return

        if medicine.retail_units_per_purchase_unit is not None:
            item.assign_retail_units_per_purchase_unit(medicine.retail_units_per_purchase_unit)
            return

        issues.append(
            f"Medicine '{medicine.name}': packaging ratio (so vien tren 1 don vi mua "
            f"'{item.unit.code}') is not known and this invoice does not state it -- "
            f"needs manual confirmation (xac nhan quy cach dong goi) before automation."
        )

    def _classify_new_medicine(
        self,
        medicine_name: str,
        ocr_result: OCRResult,
        previously_classified_by_normalized_name: dict[str, MedicineType],
        issues: list[str],
    ) -> MedicineType | None:
        classification = self._medicine_validation_service.classify_medicine_type(
            ocr_result.raw_prescription_classification_text,
            medicine_name,
            previously_classified_by_normalized_name,
        )
        if classification.is_success:
            return classification.unwrap()

        if self._allow_ai_fallback_classification and self._ai_provider is not None:
            label = self._ai_provider.classify_text(medicine_name, _CLASSIFICATION_LABELS)
            if label in _CLASSIFICATION_LABELS:
                # An AI-derived guess, not a matched business rule -- Stage 05:
                # "Do NOT automatically approve uncertain data." This stays a
                # blocking issue even though the medicine can now be created.
                issues.append(
                    f"Medicine '{medicine_name}' classified via AI fallback ('{label}'); "
                    f"flagged for reviewer confirmation, not auto-trusted."
                )
                return MedicineType(label)

        return None
