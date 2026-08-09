"""
Real-SQLite tests for SqliteMedicineRepository's configurable
medicine_code_prefix (PO decision, 2026-08): each pharmacy this system
processes invoices for is a separate, independent operation with its
own catalog, so the "TH" prefix (Business Rules: "Ma thuoc: TH1, TH2,
TH3...") must be changeable per run without a code change. Exercises
the real migration runner and a real (temp-file) database, not mocks --
same pattern as test_medicine_website_catalog_code.py.
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
    MigrationRunner(manager.connection).run_pending_migrations()
    return manager


def _add_medicine(
    connection_manager: SqliteConnectionManager, medicine_id: str, medicine_code: str
) -> None:
    SqliteMedicineRepository(connection_manager).add(
        Medicine(
            id=medicine_id,
            medicine_code=medicine_code,
            name=f"Medicine {medicine_code}",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
    )


class TestMedicineCodePrefix:
    def test_default_constructor_still_parses_th_codes(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        """No prefix given -- backward-compatible default, same as every existing caller/test."""
        _add_medicine(connection_manager, "med-1", "TH1")
        _add_medicine(connection_manager, "med-2", "TH7")

        repository = SqliteMedicineRepository(connection_manager)

        assert repository.get_highest_code_sequence_number() == 7

    def test_custom_prefix_parses_its_own_codes(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        _add_medicine(connection_manager, "med-1", "DTN1")
        _add_medicine(connection_manager, "med-2", "DTN3")

        repository = SqliteMedicineRepository(connection_manager, medicine_code_prefix="DTN")

        assert repository.get_highest_code_sequence_number() == 3

    def test_custom_prefix_ignores_codes_under_a_different_prefix(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        """
        A DB reused across pharmacies (or migrated from one prefix to
        another) must not let an OLD prefix's codes affect the NEW
        prefix's own sequence -- each prefix's numbering is independent.
        """
        _add_medicine(connection_manager, "med-1", "TH99")
        _add_medicine(connection_manager, "med-2", "DTN2")

        repository = SqliteMedicineRepository(connection_manager, medicine_code_prefix="DTN")

        assert repository.get_highest_code_sequence_number() == 2

    def test_next_generated_code_uses_the_configured_prefix(
        self, connection_manager: SqliteConnectionManager
    ) -> None:
        """End-to-end: repository's own sequence feeds MedicineValidationService correctly."""
        from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
            MedicineValidationService,
        )

        _add_medicine(connection_manager, "med-1", "DTN5")
        repository = SqliteMedicineRepository(connection_manager, medicine_code_prefix="DTN")

        highest = repository.get_highest_code_sequence_number()
        code_result = MedicineValidationService().generate_next_medicine_code(
            highest, prefix="DTN"
        )

        assert code_result.unwrap() == "DTN6"
