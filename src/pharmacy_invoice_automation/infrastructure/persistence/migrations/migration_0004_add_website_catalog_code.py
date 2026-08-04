"""
Migration 0004: add website_catalog_code column to medicines.

"Hoc 1 lan, nho mai mai" for the site's own catalog identity
(PO-confirmed 2026-08, same pattern as
migration_0002_add_retail_units_per_purchase_unit): the site's display
NAME is not unique (e.g. "Naphacogyl" can appear on multiple distinct
catalog rows), but its own SDK code is -- once a real selection among
multiple same-named results is confirmed, that code is remembered here
so later invoices never need to disambiguate the same medicine again.
Nullable -- "not yet confirmed" is a real, valid state.
"""

from __future__ import annotations

import sqlite3

MIGRATION_ID = "0004_add_website_catalog_code"

_DDL_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE medicines
        ADD COLUMN website_catalog_code TEXT
            CHECK (website_catalog_code IS NULL OR length(trim(website_catalog_code)) > 0);
    """,
)


def apply(connection: sqlite3.Connection) -> None:
    """Execute every DDL statement for this migration."""
    for statement in _DDL_STATEMENTS:
        connection.execute(statement)
