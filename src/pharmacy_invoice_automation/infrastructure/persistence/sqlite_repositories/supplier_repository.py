"""
SqliteSupplierRepository: implements
domain.ports.repositories.SupplierRepository against SQLite.

Reconstructs Supplier's nested value objects (TaxCode, Address) from
their flattened columns on read; Address is split into address_full /
address_city columns since that value object has two fields.
"""

from __future__ import annotations

import sqlite3

from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.value_objects.address import Address
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)

_COLUMNS = "id, name, tax_code, address_full, address_city, phone"


class SqliteSupplierRepository(SupplierRepository):
    """SQLite-backed persistence for Supplier."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, supplier: Supplier) -> None:
        """Persist a newly created Supplier."""
        self._connection.execute(
            f"INSERT INTO suppliers ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?);",
            self._to_row_params(supplier),
        )

    def get_by_id(self, supplier_id: str) -> Supplier | None:
        """Return the Supplier with this id, or None if not found."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM suppliers WHERE id = ?;", (supplier_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_name(self, name: str) -> Supplier | None:
        """Return the Supplier with this exact (case-insensitive) name, or None."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM suppliers WHERE name = ? COLLATE NOCASE;", (name,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_tax_code(self, tax_code: TaxCode) -> Supplier | None:
        """Return the Supplier with this tax code, or None."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM suppliers WHERE tax_code = ?;", (tax_code.value,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def list_all(self) -> list[Supplier]:
        """Return every known Supplier."""
        rows = self._connection.execute(f"SELECT {_COLUMNS} FROM suppliers;").fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, supplier: Supplier) -> None:
        """Persist changes to an existing Supplier."""
        self._connection.execute(
            "UPDATE suppliers SET name = ?, tax_code = ?, address_full = ?, "
            "address_city = ?, phone = ? WHERE id = ?;",
            (
                supplier.name,
                supplier.tax_code.value if supplier.tax_code else None,
                supplier.address.full_address if supplier.address else None,
                supplier.address.city if supplier.address else None,
                supplier.phone,
                supplier.id,
            ),
        )

    @staticmethod
    def _to_row_params(supplier: Supplier) -> tuple[object, ...]:
        return (
            supplier.id,
            supplier.name,
            supplier.tax_code.value if supplier.tax_code else None,
            supplier.address.full_address if supplier.address else None,
            supplier.address.city if supplier.address else None,
            supplier.phone,
        )

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> Supplier:
        return Supplier(
            id=row["id"],
            name=row["name"],
            tax_code=TaxCode(row["tax_code"]) if row["tax_code"] else None,
            address=(
                Address(full_address=row["address_full"], city=row["address_city"])
                if row["address_full"]
                else None
            ),
            phone=row["phone"],
        )
