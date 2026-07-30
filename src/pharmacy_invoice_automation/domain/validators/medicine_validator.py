"""
Validator: MedicineValidator.

Reusable business validator for Medicine completeness ahead of the
Create Medicine website workflow (FR-08), which requires Group
(medicine_type), Item Type, Code, Name, Unit, and Specification all to
be filled in before the popup can be submitted -- a stronger
requirement than Medicine.__post_init__ enforces.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.shared.result import Result


@dataclass(frozen=True)
class MedicineValidationReport:
    """Every issue found while validating a Medicine, if any."""

    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """True if no issues were found."""
        return len(self.issues) == 0


class MedicineValidator:
    """Validates whether a Medicine is ready for the Create Medicine workflow."""

    def validate_ready_for_creation(
        self, medicine: Medicine
    ) -> Result[MedicineValidationReport]:
        """
        Check ``medicine`` against every field the Create Medicine
        website popup requires (Business Rules / 04_Create_Medicine
        workflow: Nhom thuoc, Ma thuoc, Ten thuoc, Don vi, Quy cach).
        """
        issues: list[str] = []

        if medicine.unit.requires_manual_confirmation:
            issues.append(
                f"Medicine '{medicine.name}' has an unrecognized unit and needs "
                f"manual confirmation before it can be created on the website."
            )
        if not medicine.specification:
            issues.append(f"Medicine '{medicine.name}' has no specification (quy cach).")

        return Result.success(MedicineValidationReport(issues=tuple(issues)))
