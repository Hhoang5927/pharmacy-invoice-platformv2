"""
SqlitePurchaseInvoiceRepository: implements
domain.ports.repositories.PurchaseInvoiceRepository against SQLite.

Persists the PurchaseInvoice aggregate (PurchaseInvoice + PurchaseItem)
together, as one unit -- there is no separate PurchaseItemRepository
(Implementation Specification Section 5). On update(), every existing
purchase_items row for the invoice is deleted and every current item on
the entity is re-inserted, rather than diffing old vs. new item lists:
simpler and just as correct at this application's scale (at most a few
hundred items per invoice), and it cannot go subtly wrong the way a
partial diff/merge could.

PurchaseInvoice satisfies domain.shared_interfaces.Versionable --
update() enforces optimistic concurrency exactly like
SqliteBatchRepository, for the same reason: this aggregate can be read
by the Review tab while the OCR worker pool is still touching others,
and a stale write must never silently overwrite a newer one.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.persistence_errors import (
    OptimisticConcurrencyError,
    RecordNotFoundError,
)

_INVOICE_COLUMNS = (
    "id, project_id, invoice_number, invoice_date, status, supplier_id, "
    "ocr_confidence, commercial_discount_amount, commercial_discount_amount_currency, "
    "version, created_at, updated_at"
)
_ITEM_COLUMNS = (
    "id, invoice_id, medicine_name, unit_code, quantity, unit_price, "
    "unit_price_currency, medicine_id, batch_id, tax_type, retail_units_per_purchase_unit"
)


class SqlitePurchaseInvoiceRepository(PurchaseInvoiceRepository):
    """SQLite-backed persistence for the PurchaseInvoice aggregate."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, invoice: PurchaseInvoice) -> None:
        """Persist a newly created PurchaseInvoice (with its PurchaseItems)."""
        self._connection.execute(
            f"INSERT INTO purchase_invoices ({_INVOICE_COLUMNS}) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            self._invoice_row_params(invoice),
        )
        self._insert_items(invoice)

    def get_by_id(self, invoice_id: str) -> PurchaseInvoice | None:
        """Return the PurchaseInvoice with this id, or None if not found."""
        row = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM purchase_invoices WHERE id = ?;", (invoice_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def find_by_invoice_number(self, invoice_number: str) -> PurchaseInvoice | None:
        """Return the PurchaseInvoice with this invoice_number, or None."""
        row = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM purchase_invoices WHERE invoice_number = ?;",
            (invoice_number,),
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def list_by_project(self, project_id: str) -> list[PurchaseInvoice]:
        """Return every PurchaseInvoice belonging to ``project_id``."""
        rows = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM purchase_invoices WHERE project_id = ?;",
            (project_id,),
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def list_by_status(self, status: InvoiceStatus) -> list[PurchaseInvoice]:
        """Return every PurchaseInvoice currently in ``status``."""
        rows = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM purchase_invoices WHERE status = ?;",
            (status.value,),
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def search(
        self,
        *,
        invoice_number: str | None = None,
        supplier_name: str | None = None,
        medicine_name: str | None = None,
        invoice_date: date | None = None,
    ) -> list[PurchaseInvoice]:
        """Search invoices by any combination of the given criteria (FR-12)."""
        clauses: list[str] = []
        params: list[object] = []

        if invoice_number is not None:
            clauses.append("purchase_invoices.invoice_number LIKE ?")
            params.append(f"%{invoice_number}%")
        if invoice_date is not None:
            clauses.append("purchase_invoices.invoice_date = ?")
            params.append(invoice_date.isoformat())
        if supplier_name is not None:
            clauses.append(
                "purchase_invoices.supplier_id IN "
                "(SELECT id FROM suppliers WHERE name LIKE ?)"
            )
            params.append(f"%{supplier_name}%")
        if medicine_name is not None:
            clauses.append(
                "purchase_invoices.id IN "
                "(SELECT invoice_id FROM purchase_items WHERE medicine_name LIKE ?)"
            )
            params.append(f"%{medicine_name}%")

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT {_INVOICE_COLUMNS} FROM purchase_invoices {where_clause};", params
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, invoice: PurchaseInvoice) -> None:
        """
        Persist changes to an existing PurchaseInvoice (including its
        items), enforcing optimistic concurrency.
        """
        current_row = self._connection.execute(
            "SELECT version FROM purchase_invoices WHERE id = ?;", (invoice.id,)
        ).fetchone()
        if current_row is None:
            raise RecordNotFoundError("PurchaseInvoice", invoice.id)
        current_version = current_row["version"]
        if current_version != invoice.version:
            raise OptimisticConcurrencyError(
                "PurchaseInvoice", invoice.id, invoice.version, current_version
            )

        invoice.increment_version()
        self._connection.execute(
            "UPDATE purchase_invoices SET invoice_number = ?, invoice_date = ?, status = ?, "
            "supplier_id = ?, ocr_confidence = ?, commercial_discount_amount = ?, "
            "commercial_discount_amount_currency = ?, version = ?, updated_at = ? WHERE id = ?;",
            (
                invoice.invoice_number,
                invoice.invoice_date.isoformat(),
                invoice.status.value,
                invoice.supplier_id,
                invoice.ocr_confidence,
                str(invoice.commercial_discount_amount.amount)
                if invoice.commercial_discount_amount is not None
                else None,
                invoice.commercial_discount_amount.currency
                if invoice.commercial_discount_amount is not None
                else None,
                invoice.version,
                invoice.updated_at.isoformat(),
                invoice.id,
            ),
        )
        self._connection.execute(
            "DELETE FROM purchase_items WHERE invoice_id = ?;", (invoice.id,)
        )
        self._insert_items(invoice)

    def _insert_items(self, invoice: PurchaseInvoice) -> None:
        for item in invoice.items:
            self._connection.execute(
                f"INSERT INTO purchase_items ({_ITEM_COLUMNS}) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                self._item_row_params(invoice.id, item),
            )

    @staticmethod
    def _invoice_row_params(invoice: PurchaseInvoice) -> tuple[object, ...]:
        return (
            invoice.id,
            invoice.project_id,
            invoice.invoice_number,
            invoice.invoice_date.isoformat(),
            invoice.status.value,
            invoice.supplier_id,
            invoice.ocr_confidence,
            str(invoice.commercial_discount_amount.amount)
            if invoice.commercial_discount_amount is not None
            else None,
            invoice.commercial_discount_amount.currency
            if invoice.commercial_discount_amount is not None
            else None,
            invoice.version,
            invoice.created_at.isoformat(),
            invoice.updated_at.isoformat(),
        )

    @staticmethod
    def _item_row_params(invoice_id: str, item: PurchaseItem) -> tuple[object, ...]:
        return (
            item.id,
            invoice_id,
            item.medicine_name,
            item.unit.code,
            str(item.quantity.amount),
            str(item.unit_price.amount),
            item.unit_price.currency,
            item.medicine_id,
            item.batch_id,
            item.tax_type.value if item.tax_type else None,
            item.retail_units_per_purchase_unit,
        )

    def _to_entity(self, row: sqlite3.Row) -> PurchaseInvoice:
        item_rows = self._connection.execute(
            f"SELECT {_ITEM_COLUMNS} FROM purchase_items WHERE invoice_id = ?;", (row["id"],)
        ).fetchall()

        invoice = PurchaseInvoice(
            id=row["id"],
            project_id=row["project_id"],
            invoice_number=row["invoice_number"],
            invoice_date=date.fromisoformat(row["invoice_date"]),
            status=InvoiceStatus(row["status"]),
            supplier_id=row["supplier_id"],
            ocr_confidence=row["ocr_confidence"],
            commercial_discount_amount=(
                Money(
                    Decimal(row["commercial_discount_amount"]),
                    row["commercial_discount_amount_currency"],
                )
                if row["commercial_discount_amount"] is not None
                else None
            ),
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for item_row in item_rows:
            # Appending directly, not via invoice.add_item(): add_item()
            # calls touch(), which would incorrectly bump updated_at
            # merely from loading a record that hasn't actually changed.
            invoice.items.append(self._item_to_entity(item_row))
        return invoice

    @staticmethod
    def _item_to_entity(row: sqlite3.Row) -> PurchaseItem:
        return PurchaseItem(
            id=row["id"],
            medicine_name=row["medicine_name"],
            unit=Unit(row["unit_code"]),
            quantity=Quantity(Decimal(row["quantity"])),
            unit_price=Money(Decimal(row["unit_price"]), row["unit_price_currency"]),
            medicine_id=row["medicine_id"],
            batch_id=row["batch_id"],
            tax_type=TaxType(row["tax_type"]) if row["tax_type"] else None,
            retail_units_per_purchase_unit=row["retail_units_per_purchase_unit"],
        )
