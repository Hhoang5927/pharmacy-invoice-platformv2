"""
Loader for the externalized, versioned Selector Registry JSON files
(config/selector_registry.*.json). No selector is ever hardcoded in
adapter code.
"""

from pharmacy_invoice_automation.infrastructure.automation.selector_registry.selector_registry_loader import (  # noqa: E501
    SelectorEntry,
    SelectorRegistry,
    SelectorRegistryError,
    ValueMappingEntry,
    load_selector_registry,
)

__all__ = [
    "SelectorEntry",
    "SelectorRegistry",
    "SelectorRegistryError",
    "ValueMappingEntry",
    "load_selector_registry",
]
