"""
Loader for the externalized, versioned Selector Registry JSON files
(config/selector_registry.*.json). No selector is ever hardcoded in
adapter code -- infrastructure.automation.playwright_adapter must look
up every Playwright locator through a SelectorRegistry returned here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VALID_STRATEGIES: frozenset[str] = frozenset(
    {
        "role",
        "css",
        "title",
        "label",
        "goto",
        "text",
        "placeholder",
        "text_ends_with",
        "text_exact",
        "text_starts_with",
    }
)
_VALID_STATUSES: frozenset[str] = frozenset(
    {"confirmed", "derived", "needs_verification", "not_applicable"}
)
_USABLE_STATUSES: frozenset[str] = frozenset({"confirmed", "derived"})


class SelectorRegistryError(Exception):
    """Raised when a Selector Registry file is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class SelectorEntry:
    """One logical UI element's locator, as defined in a Selector Registry JSON file."""

    key: str
    status: str
    strategy: str | None = None
    role: str | None = None
    name: str | None = None
    description: str | None = None
    exact: bool | None = None
    value: str | None = None
    scope: str | None = None
    scope_role: str | None = None
    scope_name: str | None = None
    filter_has_text: str | None = None
    nth: int | None = None
    source: str | None = None
    notes: str | None = None

    @property
    def is_usable(self) -> bool:
        """True if this entry has a real, evidenced locator an adapter may act on."""
        return self.status in _USABLE_STATUSES


@dataclass(frozen=True)
class ValueMappingEntry:
    """One Domain-value -> site-display-value mapping (e.g. Unit.code -> dropdown label)."""

    status: str
    label: str | None = None
    suggested_label: str | None = None
    source: str | None = None

    @property
    def is_confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass(frozen=True)
class SelectorRegistry:
    """A fully loaded and structurally validated Selector Registry for one target site."""

    site: str
    version: int
    base_url: str | None
    selectors: Mapping[str, SelectorEntry]
    value_mappings: Mapping[str, Mapping[str, ValueMappingEntry]]

    def get(self, key: str) -> SelectorEntry:
        """Look up a selector by its logical key, regardless of status."""
        try:
            return self.selectors[key]
        except KeyError:
            raise SelectorRegistryError(
                f"No selector registered under key '{key}' for site '{self.site}'."
            ) from None

    def require_usable(self, key: str) -> SelectorEntry:
        """
        Look up a selector, raising unless it is confirmed/derived. Automation
        code should call this (not ``get``) before acting on a locator, so a
        'needs_verification' placeholder can never silently drive the browser.
        """
        entry = self.get(key)
        if not entry.is_usable:
            raise SelectorRegistryError(
                f"Selector '{key}' for site '{self.site}' has status '{entry.status}' and is "
                "not yet usable -- it must be verified against the live site before automation "
                "code may rely on it."
            )
        return entry

    def get_value_mapping(self, group: str, domain_value: str) -> ValueMappingEntry:
        """Look up a value-mapping entry (e.g. a Unit code) within a named mapping group."""
        try:
            group_map = self.value_mappings[group]
        except KeyError:
            raise SelectorRegistryError(
                f"No value mapping group '{group}' for site '{self.site}'."
            ) from None
        try:
            return group_map[domain_value]
        except KeyError:
            raise SelectorRegistryError(
                f"No value mapping for '{domain_value}' in group '{group}' for site '{self.site}'."
            ) from None


def load_selector_registry(path: str | Path) -> SelectorRegistry:
    """
    Load, structurally validate, and return the Selector Registry at ``path``.

    Raises SelectorRegistryError for anything from a missing/unreadable file to
    a malformed entry -- never returns a partially-valid registry.
    """
    registry_path = Path(path)
    if not registry_path.is_file():
        raise SelectorRegistryError(f"Selector Registry file not found: {registry_path}")

    try:
        raw_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SelectorRegistryError(
            f"Could not read Selector Registry file {registry_path}: {exc}"
        ) from exc

    try:
        raw: Any = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path} must contain a JSON object at the top level."
        )

    for required_field in ("site", "version", "selectors"):
        if required_field not in raw:
            raise SelectorRegistryError(
                f"Selector Registry file {registry_path} is missing required field "
                f"'{required_field}'."
            )

    site = raw["site"]
    version = raw["version"]
    if not isinstance(site, str) or not site:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: 'site' must be a non-empty string."
        )
    if not isinstance(version, int) or isinstance(version, bool):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: 'version' must be an integer."
        )

    raw_selectors = raw["selectors"]
    if not isinstance(raw_selectors, dict):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: 'selectors' must be a JSON object."
        )

    selectors: dict[str, SelectorEntry] = {
        key: _parse_selector_entry(registry_path, key, raw_entry)
        for key, raw_entry in raw_selectors.items()
    }

    raw_value_mappings = raw.get("value_mappings", {})
    if not isinstance(raw_value_mappings, dict):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: 'value_mappings' must be a JSON object."
        )

    value_mappings: dict[str, dict[str, ValueMappingEntry]] = {}
    for group_name, raw_group in raw_value_mappings.items():
        if not isinstance(raw_group, dict):
            raise SelectorRegistryError(
                f"Selector Registry file {registry_path}: value_mappings.{group_name} must be "
                "a JSON object."
            )
        value_mappings[group_name] = {
            value_key: _parse_value_mapping_entry(
                registry_path, group_name, value_key, raw_value_entry
            )
            for value_key, raw_value_entry in raw_group.items()
            if value_key != "description"
        }

    return SelectorRegistry(
        site=site,
        version=version,
        base_url=raw.get("base_url"),
        selectors=selectors,
        value_mappings=value_mappings,
    )


def _parse_selector_entry(registry_path: Path, key: str, raw_entry: Any) -> SelectorEntry:
    if not isinstance(raw_entry, dict):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: selectors.{key} must be a JSON object."
        )

    status = raw_entry.get("status")
    if status not in _VALID_STATUSES:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: selectors.{key}.status is '{status}', "
            f"expected one of {sorted(_VALID_STATUSES)}."
        )

    strategy = raw_entry.get("strategy")
    if strategy is not None and strategy not in _VALID_STRATEGIES:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: selectors.{key}.strategy is '{strategy}', "
            f"expected one of {sorted(_VALID_STRATEGIES)} or null."
        )

    if status in _USABLE_STATUSES and strategy is None:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: selectors.{key} has status '{status}' "
            "but no strategy -- a usable selector must specify how to locate its element."
        )

    return SelectorEntry(
        key=key,
        status=status,
        strategy=strategy,
        role=raw_entry.get("role"),
        name=raw_entry.get("name"),
        description=raw_entry.get("description"),
        exact=raw_entry.get("exact"),
        value=raw_entry.get("value"),
        scope=raw_entry.get("scope"),
        scope_role=raw_entry.get("scope_role"),
        scope_name=raw_entry.get("scope_name"),
        filter_has_text=raw_entry.get("filter_has_text"),
        nth=raw_entry.get("nth"),
        source=raw_entry.get("source"),
        notes=raw_entry.get("notes"),
    )


def _parse_value_mapping_entry(
    registry_path: Path, group_name: str, value_key: str, raw_entry: Any
) -> ValueMappingEntry:
    if not isinstance(raw_entry, dict):
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: value_mappings.{group_name}.{value_key} "
            "must be a JSON object."
        )

    status = raw_entry.get("status")
    if status not in _VALID_STATUSES:
        raise SelectorRegistryError(
            f"Selector Registry file {registry_path}: "
            f"value_mappings.{group_name}.{value_key}.status is '{status}', expected one of "
            f"{sorted(_VALID_STATUSES)}."
        )

    return ValueMappingEntry(
        status=status,
        label=raw_entry.get("label"),
        suggested_label=raw_entry.get("suggested_label"),
        source=raw_entry.get("source"),
    )
