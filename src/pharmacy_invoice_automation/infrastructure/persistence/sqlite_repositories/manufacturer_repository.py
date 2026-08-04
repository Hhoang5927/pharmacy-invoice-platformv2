"""
SqliteManufacturerRepository: implements
domain.ports.repositories.ManufacturerRepository against SQLite.
"""

from __future__ import annotations

import sqlite3

from pharmacy_invoice_automation.domain.entities.manufacturer import Manufacturer
from pharmacy_invoice_automation.domain.ports.repositories.manufacturer_repository import (
    ManufacturerRepository,
)
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)


class SqliteManufacturerRepository(ManufacturerRepository):
    """SQLite-backed persistence for Manufacturer."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, manufacturer: Manufacturer) -> None:
        """Persist a newly created Manufacturer."""
        self._connection.execute(
            "INSERT INTO manufacturers (id, name, country) VALUES (?, ?, ?);",
            (manufacturer.id, manufacturer.name, manufacturer.country),
        )

    def get_by_id(self, manufacturer_id: str) -> Manufacturer | None:
        """Return the Manufacturer with this id, or None if not found."""
        row = self._connection.execute(
            "SELECT id, name, country FROM manufacturers WHERE id = ?;", (manufacturer_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_name(self, name: str) -> Manufacturer | None:
        """Return the Manufacturer with this exact (case-insensitive) name, or None."""
        row = self._connection.execute(
            "SELECT id, name, country FROM manufacturers WHERE name = ? COLLATE NOCASE;",
            (name,),
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def list_all(self) -> list[Manufacturer]:
        """Return every known Manufacturer."""
        rows = self._connection.execute("SELECT id, name, country FROM manufacturers;").fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, manufacturer: Manufacturer) -> None:
        """Persist changes to an existing Manufacturer."""
        self._connection.execute(
            "UPDATE manufacturers SET name = ?, country = ? WHERE id = ?;",
            (manufacturer.name, manufacturer.country, manufacturer.id),
        )

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> Manufacturer:
        return Manufacturer(id=row["id"], name=row["name"], country=row["country"])
