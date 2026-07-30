"""
Shared Interface: Versionable.

A structural (Protocol) capability: "this object carries an
optimistic-concurrency version number." Satisfied by PurchaseInvoice
and Batch -- the two entities most likely to be read and written
concurrently once Infrastructure (Prompt 05) introduces the OCR worker
pool and the Review tab editing the same aggregate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Versionable(Protocol):
    """Anything carrying an optimistic-concurrency version number."""

    version: int

    def increment_version(self) -> None:
        """Advance this object's version after a persisted change."""


def has_conflicting_version(current: Versionable, expected_version: int) -> bool:
    """
    True if ``current.version`` no longer matches ``expected_version``,
    meaning another writer has already changed this aggregate since it
    was read. Infrastructure repositories (Prompt 05) call this before
    an update() to implement optimistic concurrency control.
    """
    return current.version != expected_version
