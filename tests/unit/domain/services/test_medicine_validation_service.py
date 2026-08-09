"""
Unit tests for domain.services.medicine_validation_service
.MedicineValidationService.generate_next_medicine_code's own
``prefix`` parameter (PO decision, 2026-08): each pharmacy this system
processes invoices for is a separate, independent operation, so the
"TH" code prefix must be changeable per run without a code change.
"""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
    MedicineValidationService,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def service() -> MedicineValidationService:
    return MedicineValidationService()


class TestGenerateNextMedicineCode:
    def test_no_prefix_given_defaults_to_th(self, service: MedicineValidationService) -> None:
        result = service.generate_next_medicine_code(2)

        assert result.unwrap() == "TH3"

    def test_custom_prefix_is_used_verbatim(self, service: MedicineValidationService) -> None:
        result = service.generate_next_medicine_code(2, prefix="DTN")

        assert result.unwrap() == "DTN3"

    def test_empty_string_prefix_falls_back_to_th(
        self, service: MedicineValidationService
    ) -> None:
        """An empty string is falsy -- treated the same as not passing a prefix at all."""
        result = service.generate_next_medicine_code(0, prefix="")

        assert result.unwrap() == "TH1"

    def test_negative_sequence_still_fails_regardless_of_prefix(
        self, service: MedicineValidationService
    ) -> None:
        result = service.generate_next_medicine_code(-1, prefix="DTN")

        assert result.is_failure
