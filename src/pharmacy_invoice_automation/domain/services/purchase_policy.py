"""
Domain Service: PurchasePolicy.

The central business policy governing how a purchase invoice's
supplier and medicines are resolved against the existing catalog: if a
match exists, select it; if not, signal that a new one must be
created (Business Rules: "Neu Nha cung cap chua ton tai -> Tao moi.
Neu da ton tai -> Chon." / same rule for Thuoc).

Folds in what were previously three separate free-function rules
(domain.rules.supplier_resolution_rule, medicine_resolution_rule, and
the supplier/invoice halves of duplicate_detection_rule), now expressed
as methods on one cohesive Domain Service, per Stage 04's pattern.

As with the prior rule functions, this Service makes decisions only --
it never queries a repository itself. The caller (the future
Application layer) is responsible for fetching the existing catalog
data this Service's methods are compared against.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.shared.result import Result


@dataclass(frozen=True)
class SupplierResolution:
    """Outcome of resolving a supplier: either an existing one, or none found."""

    existing_supplier: Supplier | None

    @property
    def requires_creation(self) -> bool:
        """True if no matching supplier was found and one must be created."""
        return self.existing_supplier is None


@dataclass(frozen=True)
class MedicineResolution:
    """Outcome of resolving a medicine: either an existing one, or none found."""

    existing_medicine: Medicine | None

    @property
    def requires_creation(self) -> bool:
        """True if no matching medicine was found and one must be created."""
        return self.existing_medicine is None


class PurchasePolicy:
    """Business policy for resolving suppliers and medicines during purchase intake."""

    def resolve_supplier(
        self,
        candidate_name: str,
        candidate_tax_code: str | None,
        existing_suppliers_by_normalized_name: dict[str, Supplier],
        existing_suppliers_by_tax_code: dict[str, Supplier],
    ) -> Result[SupplierResolution]:
        """
        Resolve ``candidate_name`` / ``candidate_tax_code`` against
        suppliers already known to the caller. Matches by tax code
        first (a stronger identifier than a free-text name), falling
        back to an exact, case-insensitive name match.
        """
        if not candidate_name or not candidate_name.strip():
            return Result.failure("Candidate supplier name is empty.")

        if candidate_tax_code:
            matched = existing_suppliers_by_tax_code.get(candidate_tax_code.strip())
            if matched is not None:
                return Result.success(SupplierResolution(existing_supplier=matched))

        normalized_name = candidate_name.strip().lower()
        matched = existing_suppliers_by_normalized_name.get(normalized_name)
        return Result.success(SupplierResolution(existing_supplier=matched))

    def resolve_medicine(
        self,
        candidate_name: str,
        existing_medicines_by_normalized_name: dict[str, Medicine],
    ) -> Result[MedicineResolution]:
        """
        Resolve ``candidate_name`` against medicines already known to
        the caller. Matching is by exact, case-insensitive name -- OCR
        output rarely carries the system's own medicine_code.
        """
        if not candidate_name or not candidate_name.strip():
            return Result.failure("Candidate medicine name is empty.")

        normalized_name = candidate_name.strip().lower()
        matched = existing_medicines_by_normalized_name.get(normalized_name)
        return Result.success(MedicineResolution(existing_medicine=matched))

    def check_duplicate_supplier(
        self,
        candidate_name: str,
        candidate_tax_code: str | None,
        existing_supplier_normalized_names: set[str],
        existing_supplier_tax_codes: set[str],
    ) -> Result[bool]:
        """Result.success(True) if the supplier is a duplicate by name or tax code."""
        normalized_name = candidate_name.strip().lower()
        if normalized_name in existing_supplier_normalized_names:
            return Result.success(True)
        if candidate_tax_code and candidate_tax_code.strip() in existing_supplier_tax_codes:
            return Result.success(True)
        return Result.success(False)

    def check_duplicate_invoice_number(
        self, candidate_invoice_number: str, existing_invoice_numbers: set[str]
    ) -> Result[bool]:
        """Result.success(True) if the invoice number is already in use."""
        is_duplicate = candidate_invoice_number.strip() in existing_invoice_numbers
        return Result.success(is_duplicate)
