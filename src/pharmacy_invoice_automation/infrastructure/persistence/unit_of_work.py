"""
SqliteUnitOfWork: the real implementation of
application.ports.transaction_coordinator.TransactionCoordinator
(Stage 05 requirement #13; "either the entire invoice succeeds, or the
entire invoice fails").

Repositories never call commit/rollback themselves -- this is the only
component that does. Every write path in the Application layer already
goes through TransactionCoordinator.run_in_transaction (verified during
Stage 05: pipeline.invoice_persistence_step and
use_cases.submit_invoice_review_use_case both call it exclusively), so
repositories executing statements against the shared connection without
managing the transaction boundary themselves is correct, not an
oversight.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TypeVar

from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.persistence_errors import (
    DatabaseError,
)

TResult = TypeVar("TResult")


class SqliteUnitOfWork(TransactionCoordinator):
    """Runs a unit of work atomically against the shared SQLite connection."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    def run_in_transaction(self, unit_of_work: Callable[[], TResult]) -> TResult:
        """
        Execute ``unit_of_work``. On success, commit everything it did;
        on any exception, roll back everything it did and re-raise
        (wrapped as DatabaseError if it was a raw sqlite3.Error, so
        Application never has to import sqlite3 to catch it).
        """
        connection = self._connection_manager.connection
        try:
            result = unit_of_work()
        except sqlite3.Error as error:
            connection.rollback()
            raise DatabaseError(f"Transaction rolled back: {error}") from error
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
            return result
