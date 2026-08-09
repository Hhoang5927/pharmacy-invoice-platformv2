"""
Unit tests for infrastructure.config.settings_manager.SettingsManager's
TOML layering of AppSettings.medicine_code_prefix (PO decision,
2026-08): each pharmacy this system processes invoices for is a
separate, independent operation, so config/app_settings.default.toml's
[medicine].code_prefix must reach AppSettings.medicine_code_prefix, the
same layering every other setting already goes through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager
from pharmacy_invoice_automation.infrastructure.config.settings_manager import SettingsManager

pytestmark = pytest.mark.unit


@pytest.fixture()
def secrets_manager(tmp_path: Path) -> SecretsManager:
    return SecretsManager(tmp_path / ".secrets")


class TestMedicineCodePrefixLayering:
    def test_no_config_file_defaults_to_th(
        self, tmp_path: Path, secrets_manager: SecretsManager
    ) -> None:
        manager = SettingsManager(tmp_path / "does_not_exist.toml", secrets_manager)

        assert manager.load().medicine_code_prefix == "TH"

    def test_toml_medicine_code_prefix_overrides_the_default(
        self, tmp_path: Path, secrets_manager: SecretsManager
    ) -> None:
        config_path = tmp_path / "app_settings.toml"
        config_path.write_text('[medicine]\ncode_prefix = "DTN"\n', encoding="utf-8")
        manager = SettingsManager(config_path, secrets_manager)

        assert manager.load().medicine_code_prefix == "DTN"

    def test_env_var_overrides_the_toml_value(
        self, tmp_path: Path, secrets_manager: SecretsManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "app_settings.toml"
        config_path.write_text('[medicine]\ncode_prefix = "DTN"\n', encoding="utf-8")
        monkeypatch.setenv("PHARMACY_APP_MEDICINE_CODE_PREFIX", "NKA")
        manager = SettingsManager(config_path, secrets_manager)

        assert manager.load().medicine_code_prefix == "NKA"
