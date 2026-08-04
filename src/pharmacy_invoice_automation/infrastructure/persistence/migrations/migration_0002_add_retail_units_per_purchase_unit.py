"""
Migration 0002: add retail_units_per_purchase_unit columns.

Part 3 ("Vien" unit-conversion, "hoc 1 lan, nho mai mai", PO-confirmed
2026-08): adds the catalog-remembered ratio to medicines, and the
per-line resolved ratio (learned from this invoice's OCR, from the
catalog, or from a reviewer's confirmation --
application.pipeline.party_matching_step.PartyMatchingStep) to
purchase_items. Both are nullable -- "not yet known" is a real, valid
state (routes to review; see domain.validators.invoice_validator).
"""

from __future__ import annotations

import sqlite3

MIGRATION_ID = "0002_add_retail_units_per_purchase_unit"

_DDL_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE medicines
        ADD COLUMN retail_units_per_purchase_unit INTEGER
            CHECK (retail_units_per_purchase_unit IS NULL OR retail_units_per_purchase_unit > 0);
    """,
    """
    ALTER TABLE purchase_items
        ADD COLUMN retail_units_per_purchase_unit INTEGER
            CHECK (retail_units_per_purchase_unit IS NULL OR retail_units_per_purchase_unit > 0);
    """,
)


def apply(connection: sqlite3.Connection) -> None:
    """Execute every DDL statement for this migration."""
    for statement in _DDL_STATEMENTS:
        connection.execute(statement)
