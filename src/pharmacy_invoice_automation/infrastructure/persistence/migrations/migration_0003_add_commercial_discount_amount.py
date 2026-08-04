"""
Migration 0003: add commercial_discount_amount columns to purchase_invoices.

Adds the whole-invoice commercial discount ("Giam Tru CKTM"/"Chiet khau
thuong mai", PO-confirmed 2026-08) as two nullable columns (amount +
currency, mirroring purchase_items.unit_price/unit_price_currency) --
"not stated on this invoice" is a real, valid state, not an error.
"""

from __future__ import annotations

import sqlite3

MIGRATION_ID = "0003_add_commercial_discount_amount"

_DDL_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE purchase_invoices
        ADD COLUMN commercial_discount_amount TEXT;
    """,
    """
    ALTER TABLE purchase_invoices
        ADD COLUMN commercial_discount_amount_currency TEXT;
    """,
)


def apply(connection: sqlite3.Connection) -> None:
    """Execute every DDL statement for this migration."""
    for statement in _DDL_STATEMENTS:
        connection.execute(statement)
