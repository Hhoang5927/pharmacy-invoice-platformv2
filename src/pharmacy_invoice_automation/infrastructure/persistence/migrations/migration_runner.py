"""
MigrationRunner: applies versioned schema migrations in order, exactly
once each, tracked in a schema_migrations table (Technical Design
Document Section 12.7).

Kept deliberately simple -- an explicit, ordered list of migration
modules, not a discovery/plugin framework, since this project has no
use yet for generic pluggability (Stage 06's own "Do NOT generate
unnecessary abstractions"). Adding the next migration means: write the
module, append it to ``_MIGRATIONS`` below.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import ModuleType

from pharmacy_invoice_automation.infrastructure.persistence.migrations import (
    migration_0001_initial_schema,
    migration_0002_add_retail_units_per_purchase_unit,
    migration_0003_add_commercial_discount_amount,
    migration_0004_add_website_catalog_code,
)

_MIGRATIONS: tuple[ModuleType, ...] = (
    migration_0001_initial_schema,
    migration_0002_add_retail_units_per_purchase_unit,
    migration_0003_add_commercial_discount_amount,
    migration_0004_add_website_catalog_code,
)

_TRACKING_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_id TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
"""


class MigrationRunner:
    """Applies every not-yet-applied migration, in order, exactly once."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def run_pending_migrations(self) -> list[str]:
        """
        Apply every migration in ``_MIGRATIONS`` not yet recorded in
        schema_migrations, in declared order. Returns the list of
        migration IDs actually applied during this call (empty if the
        schema was already fully up to date).
        """
        self._connection.execute(_TRACKING_TABLE_DDL)
        already_applied = self._get_applied_migration_ids()

        newly_applied: list[str] = []
        for migration in _MIGRATIONS:
            if migration.MIGRATION_ID in already_applied:
                continue
            migration.apply(self._connection)
            self._record_applied(migration.MIGRATION_ID)
            newly_applied.append(migration.MIGRATION_ID)
        self._connection.commit()
        return newly_applied

    def _get_applied_migration_ids(self) -> set[str]:
        cursor = self._connection.execute("SELECT migration_id FROM schema_migrations;")
        return {row[0] for row in cursor.fetchall()}

    def _record_applied(self, migration_id: str) -> None:
        self._connection.execute(
            "INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, ?);",
            (migration_id, datetime.now(timezone.utc).isoformat()),
        )
