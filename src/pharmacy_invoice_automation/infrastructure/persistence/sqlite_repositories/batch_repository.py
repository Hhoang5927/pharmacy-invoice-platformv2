"""
SqliteBatchRepository: implements domain.ports.repositories.BatchRepository
against SQLite.

Batch satisfies domain.shared_interfaces.Versionable -- update() enforces
optimistic concurrency: the in-memory entity's version must match what
is currently in the database, or an OptimisticConcurrencyError is
raised rather than silently overwriting a concurrent writer's change.
On a successful update, the entity's own increment_version() is called
so the caller's in-memory object reflects the newly-persisted version.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal

from pharmacy_invoice_automation.domain.entities.batch import Batch
from pharmacy_invoice_automation.domain.ports.repositories.batch_repository import (
    BatchRepository,
)
from pharmacy_invoice_automation.domain.value_objects.expiry_date import ExpiryDate
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.persistence_errors import (
    OptimisticConcurrencyError,
    RecordNotFoundError,
)

_COLUMNS = (
    "id, medicine_id, batch_number, expiry_date, quantity_received, "
    "manufacturer_id, version, created_at, updated_at"
)


class SqliteBatchRepository(BatchRepository):
    """SQLite-backed persistence for Batch, with optimistic concurrency on update()."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, batch: Batch) -> None:
        """Persist a newly created Batch."""
        self._connection.execute(
            f"INSERT INTO batches ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            self._to_row_params(batch),
        )

    def get_by_id(self, batch_id: str) -> Batch | None:
        """Return the Batch with this id, or None if not found."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM batches WHERE id = ?;", (batch_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_medicine_and_batch_number(
        self, medicine_id: str, batch_number: str
    ) -> Batch | None:
        """Return the Batch for this medicine with this batch_number, or None."""
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM batches WHERE medicine_id = ? AND batch_number = ?;",
            (medicine_id, batch_number),
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def list_by_medicine(self, medicine_id: str) -> list[Batch]:
        """Return every Batch recorded for ``medicine_id``."""
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM batches WHERE medicine_id = ?;", (medicine_id,)
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, batch: Batch) -> None:
        """
        Persist changes to an existing Batch, enforcing optimistic
        concurrency: raises OptimisticConcurrencyError if the row's
        current version does not match ``batch.version``.
        """
        current_row = self._connection.execute(
            "SELECT version FROM batches WHERE id = ?;", (batch.id,)
        ).fetchone()
        if current_row is None:
            raise RecordNotFoundError("Batch", batch.id)
        current_version = current_row["version"]
        if current_version != batch.version:
            raise OptimisticConcurrencyError("Batch", batch.id, batch.version, current_version)

        batch.increment_version()
        self._connection.execute(
            "UPDATE batches SET medicine_id = ?, batch_number = ?, expiry_date = ?, "
            "quantity_received = ?, manufacturer_id = ?, version = ?, updated_at = ? "
            "WHERE id = ?;",
            (
                batch.medicine_id,
                batch.batch_number,
                batch.expiry_date.value.isoformat(),
                str(batch.quantity_received.amount),
                batch.manufacturer_id,
                batch.version,
                batch.updated_at.isoformat(),
                batch.id,
            ),
        )

    @staticmethod
    def _to_row_params(batch: Batch) -> tuple[object, ...]:
        return (
            batch.id,
            batch.medicine_id,
            batch.batch_number,
            batch.expiry_date.value.isoformat(),
            str(batch.quantity_received.amount),
            batch.manufacturer_id,
            batch.version,
            batch.created_at.isoformat(),
            batch.updated_at.isoformat(),
        )

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> Batch:
        return Batch(
            id=row["id"],
            medicine_id=row["medicine_id"],
            batch_number=row["batch_number"],
            expiry_date=ExpiryDate(date.fromisoformat(row["expiry_date"])),
            quantity_received=Quantity(Decimal(row["quantity_received"])),
            manufacturer_id=row["manufacturer_id"],
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
