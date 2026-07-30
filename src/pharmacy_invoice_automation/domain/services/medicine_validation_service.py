"""
Domain Service: MedicineValidationService.

Cross-entity medicine business logic that does not belong to the
Medicine entity itself, because it needs data about *other* medicines
(the wider catalog) to make a decision -- exactly the kind of "business
logic that does not naturally belong to a single entity" Stage 04 asks
Domain Services to hold.

Folds in what were previously two separate free-function rules
(domain.rules.prescription_classification_rule and
domain.rules.medicine_code_sequence_rule), now expressed as methods on
one cohesive Domain Service, per Stage 04's pattern.

Distinct from validators.medicine_validator.MedicineValidator: the
Validator checks one Medicine's own field completeness; this Service
makes decisions that require comparing against the rest of the catalog.
"""

from __future__ import annotations

from pharmacy_invoice_automation.domain.constants import (
    MEDICINE_CODE_FIRST_SEQUENCE_NUMBER,
    MEDICINE_CODE_PREFIX,
)
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.shared.result import Result

_EXPLICIT_TEXT_TO_TYPE: dict[str, MedicineType] = {
    "thuoc ke don": MedicineType.PRESCRIPTION,
    "thuốc kê đơn": MedicineType.PRESCRIPTION,
    "thuoc khong ke don": MedicineType.OVER_THE_COUNTER,
    "thuốc không kê đơn": MedicineType.OVER_THE_COUNTER,
}


class MedicineValidationService:
    """Cross-catalog medicine business logic."""

    def classify_medicine_type(
        self,
        explicit_classification_text: str | None,
        medicine_name: str,
        previously_classified_by_normalized_name: dict[str, MedicineType],
    ) -> Result[MedicineType]:
        """
        Classify a medicine as prescription or over-the-counter.

        Resolution order:
          1. An explicit classification extracted from the invoice text.
          2. A previous classification of the same medicine name already
             in the local catalog.
          3. Failure -- the caller must flag this item for manual
             classification during review; this method never guesses.
        """
        if explicit_classification_text:
            normalized_text = explicit_classification_text.strip().lower()
            matched = _EXPLICIT_TEXT_TO_TYPE.get(normalized_text)
            if matched is not None:
                return Result.success(matched)

        normalized_name = medicine_name.strip().lower()
        previous = previously_classified_by_normalized_name.get(normalized_name)
        if previous is not None:
            return Result.success(previous)

        return Result.failure(
            f"Cannot determine prescription classification for '{medicine_name}'; "
            f"not stated on the invoice and no prior classification on file."
        )

    def generate_next_medicine_code(self, highest_existing_sequence_number: int) -> Result[str]:
        """
        Given the highest sequence number already in use across the
        catalog (0 if none), return the next unique medicine code, e.g.
        ``generate_next_medicine_code(2)`` returns ``Result.success("TH3")``.

        The caller is responsible for determining
        ``highest_existing_sequence_number`` via
        MedicineRepository.get_highest_code_sequence_number() before
        calling this method.
        """
        if highest_existing_sequence_number < 0:
            return Result.failure(
                "highest_existing_sequence_number cannot be negative: "
                f"{highest_existing_sequence_number}"
            )
        next_number = max(
            highest_existing_sequence_number + 1, MEDICINE_CODE_FIRST_SEQUENCE_NUMBER
        )
        return Result.success(f"{MEDICINE_CODE_PREFIX}{next_number}")

    def is_duplicate(
        self, candidate_name: str, existing_medicine_normalized_names: set[str]
    ) -> Result[bool]:
        """Result.success(True) if a medicine with this name already exists."""
        is_dup = candidate_name.strip().lower() in existing_medicine_normalized_names
        return Result.success(is_dup)
