"""
Infrastructure exceptions wrapping raw sqlite3 errors before they cross
into the Application layer (Technical Design Document Section 13.1:
"Infrastructure layer wraps every external error... with enough
context before it crosses back into the Application layer").
"""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class for every persistence-layer exception."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RecordNotFoundError(DatabaseError):
    """Raised when update() is called for a record id that does not exist."""

    def __init__(self, entity_name: str, record_id: str) -> None:
        super().__init__(f"No {entity_name} found with id '{record_id}' to update.")
        self.entity_name = entity_name
        self.record_id = record_id


class OptimisticConcurrencyError(DatabaseError):
    """
    Raised when update() is called with a stale in-memory version: some
    other writer already persisted a change to this record since it was
    last read. Relevant only for aggregates satisfying
    domain.shared_interfaces.Versionable (PurchaseInvoice, Batch).
    """

    def __init__(
        self, entity_name: str, record_id: str, expected_version: int, actual_version: int
    ) -> None:
        super().__init__(
            f"{entity_name} '{record_id}' has version {actual_version} in the database, "
            f"but the caller expected version {expected_version} -- it was modified by "
            f"another writer since it was last read."
        )
        self.entity_name = entity_name
        self.record_id = record_id
        self.expected_version = expected_version
        self.actual_version = actual_version
