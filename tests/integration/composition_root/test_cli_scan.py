"""
Real (but free -- no Gemini API calls) tests for composition_root.cli's
scan command helpers, covering paths test_scan_command.py's paid,
real-API test does not exercise: no images found, no API key
configured, and supplier-name resolution. Real SQLite/SecretsManager,
isolated per test via a temp app_root -- only the actual OCR network
call is out of scope here (see tests/golden/composition_root/test_scan_command.py
for that).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pharmacy_invoice_automation.composition_root import cli
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer

pytestmark = pytest.mark.integration


@pytest.fixture()
def container(tmp_path: Path) -> ServiceContainer:
    service_container = ServiceContainer()
    register_infrastructure_services(service_container, tmp_path / "app")
    return service_container


class TestRunScanEdgeCases:
    def test_no_images_found_prints_a_clear_message_and_returns_empty(
        self, container: ServiceContainer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        empty_folder = tmp_path / "empty"
        empty_folder.mkdir()

        results = cli.run_scan(container, empty_folder, project_name="Test")

        assert results == []
        assert "Không tìm thấy" in capsys.readouterr().out

    def test_missing_api_key_prints_a_clear_message_and_returns_empty(
        self, container: ServiceContainer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A real file so list_files() finds it -- never actually read/
        # processed, since build_process_invoice_use_case's OCRProvider
        # factory raises before any image touches the pipeline.
        image_folder = tmp_path / "invoices"
        image_folder.mkdir()
        (image_folder / "fake.png").write_bytes(b"not a real image")

        results = cli.run_scan(container, image_folder, project_name="Test")

        assert results == []
        assert "gemini_api_key" in capsys.readouterr().out


class TestResolveSupplierName:
    def test_none_supplier_id_is_reported_as_undetermined(
        self, container: ServiceContainer
    ) -> None:
        assert cli._resolve_supplier_name(None, container) == "(chưa xác định)"  # noqa: SLF001

    def test_unknown_supplier_id_is_reported_clearly(self, container: ServiceContainer) -> None:
        result = cli._resolve_supplier_name("does-not-exist", container)  # noqa: SLF001
        assert "does-not-exist" in result

    def test_known_supplier_id_resolves_to_its_real_name(
        self, container: ServiceContainer
    ) -> None:
        supplier = Supplier(id="sup-1", name="Cong ty Duoc ABC")
        container.resolve(SupplierRepository).add(supplier)

        assert cli._resolve_supplier_name("sup-1", container) == "Cong ty Duoc ABC"  # noqa: SLF001
