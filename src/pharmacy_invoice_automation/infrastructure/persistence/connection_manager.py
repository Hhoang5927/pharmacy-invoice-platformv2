"""
SqliteConnectionManager: owns the single sqlite3.Connection this
desktop application uses for its whole run (Technical Design Document
Section 12: SQLite as the single source of truth).

Applies the PRAGMAs every repository and the unit of work depend on:
``foreign_keys = ON`` (referential integrity is enforced, not just
declared) and ``journal_mode = WAL`` (readers -- e.g. the Dashboard
tab's queries -- are not blocked by an in-progress write, matching the
two-speed concurrency model of Technical Design Document Section 14.1).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SqliteConnectionManager:
    """Owns and configures the application's single SQLite connection."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """
        The shared connection, opened and configured on first access.
        Every repository and the SqliteUnitOfWork are constructed with
        a reference to this same manager, so they all share exactly
        one connection -- required for SqliteUnitOfWork's transactions
        to actually span multiple repositories' writes.
        """
        if self._connection is None:
            self._connection = self._open()
        return self._connection

    def _open(self) -> sqlite3.Connection:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self._database_path), isolation_level="")
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.row_factory = sqlite3.Row
        return connection

    def close(self) -> None:
        """Close the connection, if open. Safe to call more than once."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
