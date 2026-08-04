"""
Migration 0001: initial schema.

Creates every table this Infrastructure phase needs, matching exactly
the 7 aggregates/entities Domain (Stage 04, frozen) defines: Project,
Supplier, Manufacturer, Medicine, Batch, PurchaseInvoice, PurchaseItem.

Money/Quantity-typed fields (unit_price, quantity, quantity_received)
are stored as TEXT, not REAL: SQLite has no native Decimal type, and
storing a REAL would silently lose the exact decimal precision Domain's
Money/Quantity value objects guarantee. TEXT round-trips exactly via
``str(Decimal(...))`` / ``Decimal(text)``.
"""

from __future__ import annotations

import sqlite3

MIGRATION_ID = "0001_initial_schema"

_DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_folder TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manufacturers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        country TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_manufacturers_name ON manufacturers(name);",
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        tax_code TEXT,
        address_full TEXT,
        address_city TEXT,
        phone TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);",
    "CREATE INDEX IF NOT EXISTS idx_suppliers_tax_code ON suppliers(tax_code);",
    """
    CREATE TABLE IF NOT EXISTS medicines (
        id TEXT PRIMARY KEY,
        medicine_code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        medicine_type TEXT NOT NULL,
        unit_code TEXT NOT NULL,
        manufacturer_id TEXT REFERENCES manufacturers(id),
        specification TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name);",
    "CREATE INDEX IF NOT EXISTS idx_medicines_code ON medicines(medicine_code);",
    """
    CREATE TABLE IF NOT EXISTS batches (
        id TEXT PRIMARY KEY,
        medicine_id TEXT NOT NULL REFERENCES medicines(id),
        batch_number TEXT NOT NULL,
        expiry_date TEXT NOT NULL,
        quantity_received TEXT NOT NULL,
        manufacturer_id TEXT REFERENCES manufacturers(id),
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_batches_medicine_id ON batches(medicine_id);",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_batches_medicine_batch_number
        ON batches(medicine_id, batch_number);
    """,
    """
    CREATE TABLE IF NOT EXISTS purchase_invoices (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        invoice_number TEXT NOT NULL,
        invoice_date TEXT NOT NULL,
        status TEXT NOT NULL,
        supplier_id TEXT REFERENCES suppliers(id),
        ocr_confidence REAL,
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_purchase_invoices_project_id ON purchase_invoices(project_id);",
    """
    CREATE INDEX IF NOT EXISTS idx_purchase_invoices_invoice_number
        ON purchase_invoices(invoice_number);
    """,
    "CREATE INDEX IF NOT EXISTS idx_purchase_invoices_status ON purchase_invoices(status);",
    """
    CREATE INDEX IF NOT EXISTS idx_purchase_invoices_invoice_date
        ON purchase_invoices(invoice_date);
    """,
    """
    CREATE TABLE IF NOT EXISTS purchase_items (
        id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE,
        medicine_name TEXT NOT NULL,
        unit_code TEXT NOT NULL,
        quantity TEXT NOT NULL,
        unit_price TEXT NOT NULL,
        unit_price_currency TEXT NOT NULL DEFAULT 'VND',
        medicine_id TEXT REFERENCES medicines(id),
        batch_id TEXT REFERENCES batches(id),
        tax_type TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_invoice_id ON purchase_items(invoice_id);",
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_medicine_name ON purchase_items(medicine_name);",
)


def apply(connection: sqlite3.Connection) -> None:
    """Execute every DDL statement for this migration."""
    for statement in _DDL_STATEMENTS:
        connection.execute(statement)
