"""
SettingsManager: layered configuration loading (Technical Design
Document Section 10.1).

Layering order, lowest to highest priority:
    built-in defaults (AppSettings' own field defaults)
    -> config/app_settings.default.toml
    -> environment variables (PHARMACY_APP_<FIELD_NAME>, uppercased)
    -> runtime UI-set overrides (applied later, via update_setting())

Secrets (API keys, credentials) are never read from or written to the
TOML file or environment variables here -- they only ever go through
secrets_manager.SecretsManager, kept as a separate, explicit path so a
secret can never accidentally end up in a plaintext config file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from pharmacy_invoice_automation.infrastructure.config.app_settings_schema import AppSettings
from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager

# Maps "toml.section.key" -> AppSettings field name, since the TOML file
# groups settings into readable sections ([ocr], [automation], ...) while
# AppSettings itself is a flat dataclass.
_TOML_KEY_TO_FIELD: dict[str, str] = {
    "ocr.gemini_model": "gemini_model",
    "ocr.concurrency_limit": "ocr_concurrency_limit",
    "ocr.retry_count": "ocr_retry_count",
    "ocr.timeout_seconds": "ocr_timeout_seconds",
    "automation.headless": "automation_headless",
    "automation.timeout_seconds": "automation_timeout_seconds",
    "automation.retry_count": "automation_retry_count",
    "automation.navigation_timeout_seconds": "automation_navigation_timeout_seconds",
    "price_lookup.cache_ttl_hours": "price_cache_ttl_hours",
    "logging.level": "log_level",
    "logging.retention_days": "log_retention_days",
    "paths.default_working_folder": "default_working_folder",
    "paths.database_path": "database_path",
}

_ENV_VAR_PREFIX = "PHARMACY_APP_"


class SettingsManager:
    """Loads AppSettings from defaults/config/env vars; delegates secrets to SecretsManager."""

    def __init__(self, config_file_path: Path, secrets_manager: SecretsManager) -> None:
        self._config_file_path = config_file_path
        self._secrets_manager = secrets_manager
        self._current_settings: AppSettings | None = None

    def load(self) -> AppSettings:
        """Build and cache the fully-layered AppSettings, validating the final result."""
        overrides: dict[str, Any] = {}
        overrides.update(self._load_from_toml())
        overrides.update(self._load_from_env())
        self._current_settings = AppSettings(**overrides)
        return self._current_settings

    def get_setting(self, field_name: str) -> Any:
        """Return the current value of ``field_name``, loading settings first if needed."""
        settings = self._current_settings or self.load()
        if not hasattr(settings, field_name):
            raise AttributeError(f"AppSettings has no field named {field_name!r}.")
        return getattr(settings, field_name)

    def update_setting(self, field_name: str, value: Any) -> AppSettings:
        """
        Apply a runtime (e.g. Settings Tab) override for ``field_name``,
        re-validating the whole settings object. Does not persist the
        change to the TOML file -- that is a separate, explicit save
        operation, not implicit in every update.
        """
        settings = self._current_settings or self.load()
        self._current_settings = replace(settings, **{field_name: value})
        return self._current_settings

    def get_secret(self, key: str) -> str | None:
        """Delegate to SecretsManager -- secrets never flow through TOML or env vars here."""
        return self._secrets_manager.get_secret(key)

    def set_secret(self, key: str, value: str) -> None:
        """Delegate to SecretsManager."""
        self._secrets_manager.set_secret(key, value)

    def _load_from_toml(self) -> dict[str, Any]:
        if not self._config_file_path.exists():
            return {}
        with self._config_file_path.open("rb") as fh:
            raw = tomllib.load(fh)

        overrides: dict[str, Any] = {}
        for toml_key, field_name in _TOML_KEY_TO_FIELD.items():
            section, _, key = toml_key.partition(".")
            section_data = raw.get(section, {})
            if key in section_data:
                overrides[field_name] = section_data[key]
        return overrides

    def _load_from_env(self) -> dict[str, Any]:
        field_types = {f.name: f.type for f in fields(AppSettings)}
        overrides: dict[str, Any] = {}
        for field_name, field_type in field_types.items():
            env_var_name = f"{_ENV_VAR_PREFIX}{field_name.upper()}"
            raw_value = os.environ.get(env_var_name)
            if raw_value is None:
                continue
            overrides[field_name] = self._coerce(raw_value, field_type)
        return overrides

    @staticmethod
    def _coerce(raw_value: str, field_type: Any) -> Any:
        if field_type in (bool, "bool"):
            return raw_value.strip().lower() in ("1", "true", "yes", "on")
        if field_type in (int, "int"):
            return int(raw_value)
        if field_type in (float, "float"):
            return float(raw_value)
        return raw_value
