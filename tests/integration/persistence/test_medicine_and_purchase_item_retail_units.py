"""
Real-SQLite tests for Part 3's persisted columns: medicines.
retail_units_per_purchase_unit (the catalog-remembered ratio) and
purchase_items.retail_units_per_purchase_unit (the per-line resolved
ratio) -- added by migrations.migration_0002_add_retail_units_per_purchase_unit.
Exercises the real migration runner and real SQLite repositories
against a real (temp-file) database, not mocks.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.migrations.migration_runner import (
    MigrationRunner,
)
from pharmacy_invoice_automation.infrastructure.persistence.sqlite_repositories import (
    SqliteMedicineRepository,
    SqlitePurchaseInvoiceRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def connection_manager(tmp_path: Path) -> SqliteConnectionManager:
    manager = SqliteConnectionManager(tmp_path / "test.db")
    applied = MigrationRunner(manager.connection).run_pending_migrations()
    assert "0002_add_retail_units_per_purchase_unit" in applied
    return manager


class TestMigrationIsIdempotent:
    def test_running_migrations_twice_does_not_reapply(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        second_pass = MigrationRunner(connection_manager.connection).run_pending_migrations()
        assert second_pass == []


class TestMedicineRetailUnitsPersistence:
    def test_none_round_trips_as_none(self, connection_manager: SqliteConnectionManager) -> None:
        repository = SqliteMedicineRepository(connection_manager)
        medicine = Medicine(
            id="med-1",
            medicine_code="TH1",
            name="Paracetamol 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )

        repository.add(medicine)
        reloaded = repository.get_by_id("med-1")

        assert reloaded is not None
        assert reloaded.retail_units_per_purchase_unit is None

    def test_a_value_round_trips_through_add_and_get(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        repository = SqliteMedicineRepository(connection_manager)
        medicine = Medicine(
            id="med-1",
            medicine_code="TH1",
            name="Paracetamol 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
            retail_units_per_purchase_unit=100,
        )

        repository.add(medicine)
        reloaded = repository.get_by_id("med-1")

        assert reloaded is not None
        assert reloaded.retail_units_per_purchase_unit == 100

    def test_update_persists_a_newly_learned_value(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        repository = SqliteMedicineRepository(connection_manager)
        medicine = Medicine(
            id="med-1",
            medicine_code="TH1",
            name="Paracetamol 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        repository.add(medicine)

        medicine.assign_retail_units_per_purchase_unit(100)
        repository.update(medicine)
        reloaded = repository.get_by_id("med-1")

        assert reloaded is not None
        assert reloaded.retail_units_per_purchase_unit == 100

    def test_a_non_positive_value_is_rejected_at_the_database_check_constraint(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        # Domain's own validator already refuses this (see
        # test_medicine.py) -- this proves the database's CHECK
        # constraint is a real, independent second line of defense, not
        # just a comment.
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection_manager.connection.execute(
                "INSERT INTO medicines "
                "(id, medicine_code, name, medicine_type, unit_code, "
                "retail_units_per_purchase_unit) VALUES (?, ?, ?, ?, ?, ?);",
                ("med-2", "TH2", "Bad Medicine", "over_the_counter", "vien", -1),
            )


class TestPurchaseItemRetailUnitsPersistence:
    def _seed_project_and_medicine(self, connection_manager: SqliteConnectionManager) -> None:
        connection_manager.connection.execute(
            "INSERT INTO projects (id, name, root_folder, created_at) VALUES (?, ?, ?, ?);",
            ("proj-1", "Test Project", "C:/tmp", date.today().isoformat()),
        )
        SqliteMedicineRepository(connection_manager).add(
            Medicine(
                id="med-1",
                medicine_code="TH1",
                name="Paracetamol 500mg",
                medicine_type=MedicineType.OVER_THE_COUNTER,
                unit=Unit(code="vien"),
            )
        )

    def test_resolved_ratio_round_trips_through_add_and_get(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        self._seed_project_and_medicine(connection_manager)
        repository = SqlitePurchaseInvoiceRepository(connection_manager)
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
            status=InvoiceStatus.PENDING,
        )
        invoice.add_item(
            PurchaseItem(
                id="item-1",
                medicine_name="Paracetamol 500mg",
                unit=Unit(code="hop"),
                quantity=Quantity(Decimal("10")),
                unit_price=Money(Decimal("100000")),
                medicine_id="med-1",
                retail_units_per_purchase_unit=100,
            )
        )

        repository.add(invoice)
        reloaded = repository.get_by_id("inv-1")

        assert reloaded is not None
        assert reloaded.items[0].retail_units_per_purchase_unit == 100

    def test_unresolved_ratio_round_trips_as_none(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        self._seed_project_and_medicine(connection_manager)
        repository = SqlitePurchaseInvoiceRepository(connection_manager)
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
            status=InvoiceStatus.PENDING,
        )
        invoice.add_item(
            PurchaseItem(
                id="item-1",
                medicine_name="Paracetamol 500mg",
                unit=Unit(code="hop"),
                quantity=Quantity(Decimal("10")),
                unit_price=Money(Decimal("100000")),
                medicine_id="med-1",
            )
        )

        repository.add(invoice)
        reloaded = repository.get_by_id("inv-1")

        assert reloaded is not None
        assert reloaded.items[0].retail_units_per_purchase_unit is None
