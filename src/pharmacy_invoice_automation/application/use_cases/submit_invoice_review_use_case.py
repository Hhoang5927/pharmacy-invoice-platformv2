"""
Use Case: SubmitInvoiceReviewUseCase.

Applies a human reviewer's corrections to an invoice sitting in the
Human Review Queue (Stage 05 requirement #10) and, if the reviewer
approved it and it now passes Domain validation, advances it to
ReadyForImport. An invoice the reviewer did not approve, or one that
still has validation issues after correction, remains in UnderReview --
this use case never forces an invoice past a state Domain's own
validators say it is not ready for.

Per-item packaging-ratio confirmation (Part 3, PO-confirmed 2026-08):
``corrected_fields`` may also carry keys of the form
``"item.<purchase_item_id>.retail_units_per_purchase_unit"`` -- the
reviewer's answer to the "quy cach dong gia" gap
pipeline.party_matching_step.PartyMatchingStep raises when neither this
invoice's OCR nor the catalog Medicine already knows a line's Vien-per-
purchase-unit ratio (validators.invoice_validator.InvoiceValidator's
matching per-item check is what keeps such an invoice out of
ReadyForImport until this is supplied). Confirming it here also learns
it onto the resolved Medicine, "hoc 1 lan, nho mai mai" -- the whole
point being no reviewer is ever asked the same question twice.

Per-item classification confirmation (bug fix, PO-confirmed 2026-08,
final -- no exceptions): ``corrected_fields`` may also carry keys of
the form ``"item.<purchase_item_id>.medicine_type"``
(``"prescription"``/``"over_the_counter"``/``"otc"``) -- previously, if
the original processing pass could not classify a genuinely new
medicine (no explicit Rx/OTC text on the invoice, no prior
classification on file), ``item.medicine_id`` was left permanently
``None`` with NO way for a reviewer to ever unblock it: this use case
only ever applied corrections to fields already on the entity, it never
re-attempted medicine resolution/creation. This field lets the reviewer
supply the missing classification directly -- the reviewer's decision
always wins, never re-guessed -- and immediately (re-)resolves or
creates the medicine via
pipeline.party_matching_step.PartyMatchingStep.resolve_item_with_explicit_classification,
instead of just setting a field and leaving resolution stuck.

Per-item retail-unit override (bug fix, PO-confirmed 2026-08, final --
no exceptions): ``corrected_fields`` may also carry keys of the form
``"item.<purchase_item_id>.retail_unit_override"`` (one of the 39
known ``value_objects.unit.Unit`` codes, e.g. ``"lo"``, ``"chai"``,
``"tuyp"``, ``"ong"``) -- for a line whose ĐVT (purchase unit, e.g.
"Hop"/"Thung") is a box/carton that the invoice's own packaging note
says holds exactly ONE bottle/tube/vial (e.g. Coldi, "Thung x 160 hop x
1 lo x 15ml") -- distinct from ``retail_units_per_purchase_unit``,
which is for a REAL quantity conversion (e.g. 1 Hop = 100 Vien).
Immediately sets ``retail_units_per_purchase_unit=1`` (the purchase
unit IS one retail unit, nothing to convert -- never asks for a second,
fabricated number) and, for a genuinely NEW Medicine, makes it the
Medicine's own dispensing unit instead of defaulting to Vien -- never
applied retroactively to an already-existing Medicine.
"""

from __future__ import annotations

from datetime import date

from pharmacy_invoice_automation.application.commands import SubmitInvoiceReviewCommand
from pharmacy_invoice_automation.application.dto import PurchaseInvoiceDTO
from pharmacy_invoice_automation.application.pipeline.party_matching_step import (
    PartyMatchingStep,
)
from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.exceptions.invalid_invoice_error import (
    InvalidInvoiceError,
)
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

_ITEM_FIELD_PREFIX = "item."
_PACKAGING_RATIO_FIELD_SUFFIX = ".retail_units_per_purchase_unit"
_MEDICINE_TYPE_FIELD_SUFFIX = ".medicine_type"
_RETAIL_UNIT_OVERRIDE_FIELD_SUFFIX = ".retail_unit_override"
_MEDICINE_TYPE_ALIASES: dict[str, MedicineType] = {
    "prescription": MedicineType.PRESCRIPTION,
    "over_the_counter": MedicineType.OVER_THE_COUNTER,
    "otc": MedicineType.OVER_THE_COUNTER,
}


def _parse_medicine_type(raw_value: str) -> MedicineType | None:
    """None (never guessed/defaulted) for anything not one of the recognized aliases."""
    return _MEDICINE_TYPE_ALIASES.get(raw_value.strip().lower())


def _parse_retail_unit_override(raw_value: str) -> Unit | None:
    """None (never guessed/defaulted) for anything not one of the 39 known Unit codes."""
    try:
        return Unit(code=raw_value.strip().lower())
    except ValidationError:
        return None


class SubmitInvoiceReviewUseCase:
    """Applies reviewer corrections, releasing an invoice for import once valid and approved."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        medicine_repository: MedicineRepository,
        invoice_validator: InvoiceValidator,
        transaction_coordinator: TransactionCoordinator,
        party_matching_step: PartyMatchingStep,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._medicine_repository = medicine_repository
        self._invoice_validator = invoice_validator
        self._transaction_coordinator = transaction_coordinator
        self._party_matching_step = party_matching_step

    def execute(
        self, command: SubmitInvoiceReviewCommand
    ) -> UseCaseResult[PurchaseInvoiceDTO]:
        """Apply ``command``'s corrections to the invoice it targets and re-validate it."""
        invoice = self._purchase_invoice_repository.get_by_id(command.invoice_id)
        if invoice is None:
            return UseCaseResult.failure(
                errors=(f"No invoice found with id '{command.invoice_id}'.",)
            )
        if invoice.status is not InvoiceStatus.UNDER_REVIEW:
            return UseCaseResult.failure(
                errors=(
                    f"Invoice '{command.invoice_id}' is not awaiting review "
                    f"(current status: {invoice.status.value}).",
                )
            )

        new_medicines, medicines_to_update = self._apply_corrections(
            invoice, command.corrected_fields
        )

        if not command.reviewer_approved:
            self._save(invoice, new_medicines, medicines_to_update)
            return UseCaseResult.success(
                value=PurchaseInvoiceDTO.from_domain(invoice),
                warnings=("Reviewer did not approve; invoice remains in review.",),
            )

        issues = self._invoice_validator.validate(invoice).unwrap().issues
        if issues:
            self._save(invoice, new_medicines, medicines_to_update)
            return UseCaseResult.failure(errors=issues)

        invoice.transition_to(InvoiceStatus.READY_FOR_IMPORT)
        self._save(invoice, new_medicines, medicines_to_update)
        return UseCaseResult.success(value=PurchaseInvoiceDTO.from_domain(invoice))

    def _apply_corrections(
        self, invoice: PurchaseInvoice, corrected_fields: dict[str, str]
    ) -> tuple[list[Medicine], list[Medicine]]:
        """Returns (new_medicines, existing_medicines_to_update) -- both need persisting."""
        invoice_number = corrected_fields.get("invoice_number", "").strip()
        if invoice_number:
            invoice.invoice_number = invoice_number

        invoice_date_text = corrected_fields.get("invoice_date", "").strip()
        if invoice_date_text:
            try:
                invoice.invoice_date = date.fromisoformat(invoice_date_text)
            except ValueError:
                pass  # left unchanged; re-validation surfaces anything materially wrong

        # Packaging-ratio and retail-unit-override corrections first:
        # resolve_item_with_explicit_classification (called below) reads
        # item.retail_units_per_purchase_unit directly off the entity to
        # learn it onto a newly-resolved Medicine, so it must already
        # reflect this submission's answer.
        medicines_to_update = self._apply_packaging_ratio_corrections(invoice, corrected_fields)
        retail_unit_overrides, override_medicine_updates = self._apply_retail_unit_overrides(
            invoice, corrected_fields
        )
        medicines_to_update.extend(override_medicine_updates)
        new_medicines, medicine_type_updates = self._apply_medicine_type_corrections(
            invoice, corrected_fields, retail_unit_overrides
        )
        medicines_to_update.extend(medicine_type_updates)

        invoice.touch()
        return new_medicines, medicines_to_update

    def _apply_packaging_ratio_corrections(
        self, invoice: PurchaseInvoice, corrected_fields: dict[str, str]
    ) -> list[Medicine]:
        """
        Apply any ``item.<id>.retail_units_per_purchase_unit`` reviewer
        corrections onto their PurchaseItem, and -- "hoc 1 lan, nho mai
        mai" -- also onto the resolved Medicine when it did not already
        have a value. Medicine updates are returned rather than
        persisted immediately: they must land in the same transaction
        as the invoice save (ports.transaction_coordinator.TransactionCoordinator's
        "no partial persistence" contract), which only ``_save`` opens.
        """
        items_by_id = {item.id: item for item in invoice.items}
        medicines_to_update: list[Medicine] = []
        for key, raw_value in corrected_fields.items():
            if not key.startswith(_ITEM_FIELD_PREFIX) or not key.endswith(
                _PACKAGING_RATIO_FIELD_SUFFIX
            ):
                continue
            item = items_by_id.get(
                key[len(_ITEM_FIELD_PREFIX) : -len(_PACKAGING_RATIO_FIELD_SUFFIX)]
            )
            if item is None:
                continue
            try:
                value = int(raw_value.strip())
                item.assign_retail_units_per_purchase_unit(value)
            except (ValueError, InvalidInvoiceError):
                continue  # left unchanged; re-validation surfaces anything materially wrong

            if item.medicine_id is None:
                continue
            medicine = self._medicine_repository.get_by_id(item.medicine_id)
            if medicine is not None and medicine.retail_units_per_purchase_unit is None:
                medicine.assign_retail_units_per_purchase_unit(value)
                medicines_to_update.append(medicine)
        return medicines_to_update

    def _apply_retail_unit_overrides(
        self, invoice: PurchaseInvoice, corrected_fields: dict[str, str]
    ) -> tuple[dict[str, Unit], list[Medicine]]:
        """
        Apply any ``item.<id>.retail_unit_override`` reviewer
        corrections (bug fix, PO-confirmed 2026-08, final -- no
        exceptions) -- see this module's own docstring for the full
        rationale. Mirrors _apply_packaging_ratio_corrections'
        shape (set the item field, learn onto an already-resolved
        Medicine that lacks one), but hardcodes the ratio to 1 (the
        purchase unit already IS the retail unit, never a second number
        to ask for) and additionally returns the parsed Unit per item
        id, for _apply_medicine_type_corrections to use as a genuinely
        NEW Medicine's own dispensing unit.

        Returns (overrides_by_item_id, existing_medicines_to_update).
        """
        items_by_id = {item.id: item for item in invoice.items}
        overrides: dict[str, Unit] = {}
        medicines_to_update: list[Medicine] = []
        for key, raw_value in corrected_fields.items():
            if not key.startswith(_ITEM_FIELD_PREFIX) or not key.endswith(
                _RETAIL_UNIT_OVERRIDE_FIELD_SUFFIX
            ):
                continue
            item = items_by_id.get(
                key[len(_ITEM_FIELD_PREFIX) : -len(_RETAIL_UNIT_OVERRIDE_FIELD_SUFFIX)]
            )
            if item is None:
                continue
            override_unit = _parse_retail_unit_override(raw_value)
            if override_unit is None:
                continue  # left unchanged; re-validation surfaces anything materially wrong
            item.assign_retail_units_per_purchase_unit(1)
            overrides[item.id] = override_unit

            if item.medicine_id is None:
                continue
            medicine = self._medicine_repository.get_by_id(item.medicine_id)
            if medicine is not None and medicine.retail_units_per_purchase_unit is None:
                medicine.assign_retail_units_per_purchase_unit(1)
                medicines_to_update.append(medicine)
        return overrides, medicines_to_update

    def _apply_medicine_type_corrections(
        self,
        invoice: PurchaseInvoice,
        corrected_fields: dict[str, str],
        retail_unit_overrides: dict[str, Unit],
    ) -> tuple[list[Medicine], list[Medicine]]:
        """
        Apply any ``item.<id>.medicine_type`` reviewer corrections (bug
        fix, PO-confirmed 2026-08, final -- no exceptions): unlike a
        packaging-ratio correction, this doesn't just set a field --
        item.medicine_id being None means the original pass could not
        classify a genuinely new medicine and never created one, so
        this immediately (re-)resolves/creates it via
        pipeline.party_matching_step.PartyMatchingStep.resolve_item_with_explicit_classification,
        using the reviewer's classification (never re-guessed). Already-
        resolved items (medicine_id already set) are left untouched --
        this is only for unblocking, never for retroactively
        reclassifying an existing resolution.

        Returns (new_medicines, updated_existing_medicines) -- both
        must be persisted by the caller (_save), in the same
        transaction as the invoice itself.
        """
        items_by_id = {item.id: item for item in invoice.items}
        new_medicines: list[Medicine] = []
        updated_medicines: list[Medicine] = []
        # Guards against creating two duplicate Medicine records when the
        # same not-yet-classified name appears on more than one item
        # within this single submission.
        new_medicines_by_normalized_name: dict[str, Medicine] = {}
        # Bug fix (found while testing this feature, PO-confirmed
        # 2026-08): none of these new medicines are actually persisted
        # until _save()'s own transaction runs, so
        # PartyMatchingStep.resolve_item_with_explicit_classification
        # needs to know how many it has already created earlier in this
        # SAME loop -- otherwise two DIFFERENT not-yet-classified names
        # corrected in one submission (e.g. Coldi AND Coldi-B DNH) would
        # both see the same "highest code so far" and collide.
        new_medicines_reserved_so_far = 0
        for key, raw_value in corrected_fields.items():
            if not key.startswith(_ITEM_FIELD_PREFIX) or not key.endswith(
                _MEDICINE_TYPE_FIELD_SUFFIX
            ):
                continue
            item = items_by_id.get(
                key[len(_ITEM_FIELD_PREFIX) : -len(_MEDICINE_TYPE_FIELD_SUFFIX)]
            )
            if item is None or item.medicine_id is not None:
                continue  # not on this invoice, or already resolved -- never re-guess
            medicine_type = _parse_medicine_type(raw_value)
            if medicine_type is None:
                continue  # left unchanged; re-validation surfaces anything materially wrong

            already_created = new_medicines_by_normalized_name.get(
                item.medicine_name.strip().lower()
            )
            if already_created is not None:
                item.assign_medicine(already_created.id)
                continue

            outcome = self._party_matching_step.resolve_item_with_explicit_classification(
                item,
                medicine_type,
                retail_unit_overrides.get(item.id),
                sequence_offset=new_medicines_reserved_so_far,
            )
            if outcome.newly_created_medicine is not None:
                new_medicines.append(outcome.newly_created_medicine)
                new_medicines_reserved_so_far += 1
                new_medicines_by_normalized_name[
                    outcome.newly_created_medicine.name.strip().lower()
                ] = outcome.newly_created_medicine
            if outcome.updated_existing_medicine is not None:
                updated_medicines.append(outcome.updated_existing_medicine)
        return new_medicines, updated_medicines

    def _save(
        self,
        invoice: PurchaseInvoice,
        new_medicines: list[Medicine],
        medicines_to_update: list[Medicine],
    ) -> None:
        def _do() -> None:
            for medicine in new_medicines:
                self._medicine_repository.add(medicine)
            for medicine in medicines_to_update:
                self._medicine_repository.update(medicine)
            self._purchase_invoice_repository.update(invoice)

        self._transaction_coordinator.run_in_transaction(_do)
