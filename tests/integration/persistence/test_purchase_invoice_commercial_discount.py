"""
Real-SQLite tests for migrations.migration_0003_add_commercial_discount_amount's
persisted columns (purchase_invoices.commercial_discount_amount/_currency).
Exercises the real migration runner and real SqlitePurchaseInvoiceRepository
against a real (temp-file) database, not mocks -- mirrors
test_medicine_and_purchase_item_retail_units.py's pattern for Part 3's
retail_units_per_purchase_unit columns.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.migrations.migration_runner import (
    MigrationRunner,
)
from pharmacy_invoice_automation.infrastructure.persistence.sqlite_repositories import (
    SqlitePurchaseInvoiceRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def connection_manager(tmp_path: Path) -> SqliteConnectionManager:
    manager = SqliteConnectionManager(tmp_path / "test.db")
    applied = MigrationRunner(manager.connection).run_pending_migrations()
    assert "0003_add_commercial_discount_amount" in applied
    manager.connection.execute(
        "INSERT INTO projects (id, name, root_folder, created_at) VALUES (?, ?, ?, ?);",
        ("proj-1", "Test Project", "C:/tmp", date.today().isoformat()),
    )
    return manager


class TestCommercialDiscountAmountPersistence:
    def test_none_round_trips_as_none_through_add_and_get(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        repository = SqlitePurchaseInvoiceRepository(connection_manager)
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
        )

        repository.add(invoice)
        reloaded = repository.get_by_id("inv-1")

        assert reloaded is not None
        assert reloaded.commercial_discount_amount is None

    def test_a_value_round_trips_through_add_and_get(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        repository = SqlitePurchaseInvoiceRepository(connection_manager)
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
            commercial_discount_amount=Money(Decimal("26855")),
        )

        repository.add(invoice)
        reloaded = repository.get_by_id("inv-1")

        assert reloaded is not None
        assert reloaded.commercial_discount_amount == Money(Decimal("26855"))

    def test_update_persists_a_newly_learned_discount(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        repository = SqlitePurchaseInvoiceRepository(connection_manager)
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
        )
        repository.add(invoice)

        invoice.commercial_discount_amount = Money(Decimal("28198"))
        repository.update(invoice)
        reloaded = repository.get_by_id("inv-1")

        assert reloaded is not None
        assert reloaded.commercial_discount_amount == Money(Decimal("28198"))
