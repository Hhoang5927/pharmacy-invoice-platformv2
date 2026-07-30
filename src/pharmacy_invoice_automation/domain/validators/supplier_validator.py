"""
Validator: SupplierValidator.

Reusable business validator for Supplier completeness ahead of the
Create Supplier website workflow (FR-07), which requires Name,
Address, Phone, and Tax Code all to be filled in before the popup can
be submitted -- a stronger requirement than Supplier.__post_init__
enforces (which only requires id and name).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.shared.result import Result


@dataclass(frozen=True)
class SupplierValidationReport:
    """Every issue found while validating a Supplier, if any."""

    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """True if no issues were found."""
        return len(self.issues) == 0


class SupplierValidator:
    """Validates whether a Supplier is ready for the Create Supplier workflow."""

    def validate_ready_for_creation(
        self, supplier: Supplier
    ) -> Result[SupplierValidationReport]:
        """
        Check ``supplier`` against every field the Create Supplier
        website popup requires (Business Rules / 03_Create_Supplier
        workflow: Ten, Dia chi, Dien thoai, Ma so thue).
        """
        issues: list[str] = []

        if not supplier.address:
            issues.append("Supplier has no address.")
        if not supplier.phone:
            issues.append("Supplier has no phone number.")
        if not supplier.tax_code:
            issues.append("Supplier has no tax code.")

        return Result.success(SupplierValidationReport(issues=tuple(issues)))
