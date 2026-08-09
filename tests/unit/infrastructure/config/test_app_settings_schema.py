"""
Unit tests for infrastructure.config.app_settings_schema.AppSettings
.medicine_code_prefix (PO decision, 2026-08): each pharmacy this system
processes invoices for is a separate, independent operation, so the
"TH" medicine-code prefix must be configurable, defaulting to "TH"
when left unset.
"""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.infrastructure.config.app_settings_schema import AppSettings

pytestmark = pytest.mark.unit


class TestMedicineCodePrefix:
    def test_defaults_to_th(self) -> None:
        assert AppSettings().medicine_code_prefix == "TH"

    def test_a_custom_value_is_accepted(self) -> None:
        assert AppSettings(medicine_code_prefix="DTN").medicine_code_prefix == "DTN"

    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="medicine_code_prefix"):
            AppSettings(medicine_code_prefix="")

    def test_whitespace_only_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="medicine_code_prefix"):
            AppSettings(medicine_code_prefix="   ")
