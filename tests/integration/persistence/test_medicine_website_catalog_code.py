"""
Real-SQLite tests for the website_catalog_code column added by
migrations.migration_0004_add_website_catalog_code -- "hoc 1 lan, nho
mai mai" for the site's own catalog identity (PO-confirmed 2026-08),
same pattern as test_medicine_and_purchase_item_retail_units.py's
retail_units_per_purchase_unit coverage. Exercises the real migration
runner and real SqliteMedicineRepository against a real (temp-file)
database, not mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
from pharmacy_invoice_automation.domain.value_objects.unit import Unit
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.migrations.migration_runner import (
    MigrationRunner,
)
from pharmacy_invoice_automation.infrastructure.persistence.sqlite_repositories import (
    SqliteMedicineRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def connection_manager(tmp_path: Path) -> SqliteConnectionManager:
    manager = SqliteConnectionManager(tmp_path / "test.db")
    applied = MigrationRunner(manager.connection).run_pending_migrations()
    assert "0004_add_website_catalog_code" in applied
    return manager


class TestWebsiteCatalogCodePersistence:
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
        assert reloaded.website_catalog_code is None

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
            website_catalog_code="893115102724",
        )

        repository.add(medicine)
        reloaded = repository.get_by_id("med-1")

        assert reloaded is not None
        assert reloaded.website_catalog_code == "893115102724"

    def test_update_persists_a_newly_confirmed_code(
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

        medicine.assign_website_catalog_code("893115102724")
        repository.update(medicine)
        reloaded = repository.get_by_id("med-1")

        assert reloaded is not None
        assert reloaded.website_catalog_code == "893115102724"

    def test_a_blank_value_is_rejected_at_the_database_check_constraint(
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
                "website_catalog_code) VALUES (?, ?, ?, ?, ?, ?);",
                ("med-2", "TH2", "Bad Medicine", "over_the_counter", "vien", "   "),
            )
