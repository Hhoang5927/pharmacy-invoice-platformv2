"""
Unit tests for domain.services.supplement_classification_service.

Part 3.1 (PO-confirmed 2026-08): VAT is now the ONLY classification
criterion, entirely replacing the prior medicine-name-keyword
heuristic (see supplement_classification_service.py's own docstring
for the full rule and why it changed).
"""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.services.supplement_classification_service import (
    SupplementClassificationService,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def service() -> SupplementClassificationService:
    return SupplementClassificationService()


class TestIsSupplement:
    def test_reduced_vat_5_percent_is_a_registered_medicine_not_a_supplement(
        self, service: SupplementClassificationService
    ) -> None:
        result = service.is_supplement(TaxType.REDUCED)

        assert result.is_success is True
        assert result.unwrap() is False

    @pytest.mark.parametrize(
        "tax_type",
        [TaxType.STANDARD, TaxType.EXEMPT, TaxType.OTHER],
    )
    def test_any_non_5_percent_vat_is_treated_as_supplement(
        self, service: SupplementClassificationService, tax_type: TaxType
    ) -> None:
        result = service.is_supplement(tax_type)

        assert result.is_success is True
        assert result.unwrap() is True

    def test_unreadable_vat_is_neither_kept_nor_excluded_but_a_failure(
        self, service: SupplementClassificationService
    ) -> None:
        # None here means "VAT could not be read" -- must route to human
        # review, never be silently treated as either outcome.
        result = service.is_supplement(None)

        assert result.is_failure is True
        assert result.failure_reason is not None
