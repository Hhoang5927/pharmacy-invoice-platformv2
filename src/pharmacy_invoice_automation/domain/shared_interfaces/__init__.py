"""
Shared Interfaces: structural (Protocol-based) capabilities that cut
across entity types without requiring inheritance.

    Identifiable -- has a stable string id
    Timestamped  -- records created_at / updated_at
    Auditable    -- can record its own modification via touch()
    Versionable  -- carries an optimistic-concurrency version number

These are typing.Protocol, not abc.ABC: an entity satisfies one of
these simply by having matching attributes/methods, with no explicit
inheritance required (Python structural typing).
"""

from pharmacy_invoice_automation.domain.shared_interfaces.auditable import (
    Auditable,
    mark_modified,
)
from pharmacy_invoice_automation.domain.shared_interfaces.identifiable import (
    Identifiable,
    ids_are_unique,
)
from pharmacy_invoice_automation.domain.shared_interfaces.timestamped import (
    Timestamped,
    days_since_last_update,
)
from pharmacy_invoice_automation.domain.shared_interfaces.versionable import (
    Versionable,
    has_conflicting_version,
)

__all__ = [
    "Identifiable",
    "ids_are_unique",
    "Timestamped",
    "days_since_last_update",
    "Auditable",
    "mark_modified",
    "Versionable",
    "has_conflicting_version",
]
