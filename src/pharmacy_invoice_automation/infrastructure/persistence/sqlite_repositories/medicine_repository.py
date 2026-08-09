"""
SqliteMedicineRepository: implements
domain.ports.repositories.MedicineRepository against SQLite.

get_highest_code_sequence_number parses the numeric suffix off every
existing "<prefix><N>" medicine_code in SQL-returned rows (Python-side,
not in SQL, since SQLite has no reliable way to extract-and-cast an
arbitrary numeric substring safely) -- used by
services.medicine_validation_service.MedicineValidationService to
generate the next unique code.
"""

from __future__ import annotations

import sqlite3

from pharmacy_invoice_automation.domain.constants import MEDICINE_CODE_PREFIX
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)

_COLUMNS = (
    "id, medicine_code, name, medicine_type, unit_code, manufacturer_id, specification, "
    "retail_units_per_purchase_unit, website_catalog_code"
)


class SqliteMedicineRepository(MedicineRepository):
    """SQLite-backed persistence for Medicine."""

    def __init__(
        self,
        connection_manager: SqliteConnectionManager,
        medicine_code_prefix: str = MEDICINE_CODE_PREFIX,
    ) -> None:
        self._connection_manager = connection_manager
        # PO decision (2026-08): each pharmacy this system processes
        # invoices for is a separate, independent operation, so the code
        # prefix must be changeable between runs (AppSettings
        # .medicine_code_prefix, config/app_settings.default.toml)
        # without a code change -- defaults to the same domain-level
        # MEDICINE_CODE_PREFIX ("TH") every existing caller/test already
        # relies on.
        self._medicine_code_prefix = medicine_code_prefix

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, medicine: Medicine) -> None:
        """Persist a newly created Medicine."""
        self._connection.execute(
            f"INSERT INTO medicines ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            self._to_row_params(medicine),
        )

    def get_by_id(self, medicine_id: str) -> Medicine | None:
        """Return the Medicine with this id, or None if not found."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM medicines WHERE id = ?;", (medicine_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_name(self, name: str) -> Medicine | None:
        """Return the Medicine with this exact (case-insensitive) name, or None."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM medicines WHERE name = ? COLLATE NOCASE;", (name,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_code(self, medicine_code: str) -> Medicine | None:
        """Return the Medicine with this system medicine_code, or None."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM medicines WHERE medicine_code = ?;", (medicine_code,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def get_highest_code_sequence_number(self) -> int:
        """
        Return the highest numeric suffix across every
        '<medicine_code_prefix><N>' medicine_code (0 if none).
        """
        rows = self._connection.execute("SELECT medicine_code FROM medicines;").fetchall()
        highest = 0
        prefix_len = len(self._medicine_code_prefix)
        for row in rows:
            code = row["medicine_code"]
            if code.startswith(self._medicine_code_prefix):
                try:
                    highest = max(highest, int(code[prefix_len:]))
                except ValueError:
                    continue
        return highest

    def list_all(self) -> list[Medicine]:
        """Return every known Medicine."""
        rows = self._connection.execute(f"SELECT {_COLUMNS} FROM medicines;").fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, medicine: Medicine) -> None:
        """Persist changes to an existing Medicine."""
        self._connection.execute(
            "UPDATE medicines SET medicine_code = ?, name = ?, medicine_type = ?, "
            "unit_code = ?, manufacturer_id = ?, specification = ?, "
            "retail_units_per_purchase_unit = ?, website_catalog_code = ? WHERE id = ?;",
            (
                medicine.medicine_code,
                medicine.name,
                medicine.medicine_type.value,
                medicine.unit.code,
                medicine.manufacturer_id,
                medicine.specification,
                medicine.retail_units_per_purchase_unit,
                medicine.website_catalog_code,
                medicine.id,
            ),
        )

    @staticmethod
    def _to_row_params(medicine: Medicine) -> tuple[object, ...]:
        return (
            medicine.id,
            medicine.medicine_code,
            medicine.name,
            medicine.medicine_type.value,
            medicine.unit.code,
            medicine.manufacturer_id,
            medicine.specification,
            medicine.retail_units_per_purchase_unit,
            medicine.website_catalog_code,
        )

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> Medicine:
        return Medicine(
            id=row["id"],
            medicine_code=row["medicine_code"],
            name=row["name"],
            medicine_type=MedicineType(row["medicine_type"]),
            unit=Unit(row["unit_code"]),
            manufacturer_id=row["manufacturer_id"],
            specification=row["specification"],
            retail_units_per_purchase_unit=row["retail_units_per_purchase_unit"],
            website_catalog_code=row["website_catalog_code"],
        )
