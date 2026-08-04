"""
Shared Interface: Identifiable.

A structural (Protocol) capability: "this object has a stable identity."
Satisfied automatically by every entity in this domain (Protocol
membership is structural, not inheritance-based) -- used wherever a
function needs to operate generically across any entity type by id,
without depending on any specific entity class.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Identifiable(Protocol):
    """Anything with a stable, string identity."""

    id: str


def ids_are_unique(entities: Sequence[Identifiable]) -> bool:
    """
    True if every entity in ``entities`` has a distinct id. Generic
    over any Identifiable -- used, for example, by
    validators.invoice_validator.InvoiceValidator to confirm a
    PurchaseInvoice's PurchaseItems do not share an id.

    Typed as Sequence rather than list: this parameter is read-only
    (never mutated), and list is invariant in its type parameter, so a
    list[Identifiable]-typed parameter would reject a concrete
    list[PurchaseItem] argument under strict type checking even though
    PurchaseItem structurally satisfies Identifiable. Sequence is
    covariant, so it accepts any such list without that false rejection.
    """
    seen_ids = [entity.id for entity in entities]
    return len(seen_ids) == len(set(seen_ids))
