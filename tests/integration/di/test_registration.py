"""
Integration tests for infrastructure.di.registration.register_infrastructure_services
(Composition Root Stage A, PO-confirmed 2026-08).

Real SQLite database, real SecretsManager (Fernet-fallback, pointed at
an isolated temp directory -- never the real project's data/.secrets),
real migrations, real Playwright browser for the BrowserAutomationProvider
success path. No mocks for anything this module itself wires.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.domain.ports.repositories.batch_repository import (
    BatchRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.manufacturer_repository import (
    ManufacturerRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    BrowserAutomationProvider,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.infrastructure.automation.playwright_adapter import (
    PlaywrightBrowserAutomationProvider,
)
from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager
from pharmacy_invoice_automation.infrastructure.config.settings_manager import SettingsManager
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer
from pharmacy_invoice_automation.infrastructure.file_storage.workspace_manager import (
    WorkspaceManager,
)
from pharmacy_invoice_automation.infrastructure.logging.logger_factory import LoggerFactory
from pharmacy_invoice_automation.infrastructure.ocr.gemini_adapter import GeminiOCRProvider
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)

pytestmark = pytest.mark.integration


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


_REAL_SELECTOR_REGISTRY_PATH = (
    _repo_root() / "config" / "selector_registry.webnhathuoc.json"
)


@pytest.fixture()
def container_and_workspace(tmp_path: Path) -> tuple[ServiceContainer, WorkspaceManager]:
    # tmp_path as app_root: SecretsManager/SettingsManager/SqliteConnectionManager
    # all derive their storage from it, so this is fully isolated from the
    # real project's data/.secrets and data/project.sqlite3 -- no TOML file
    # is created either, so AppSettings falls back to its own built-in
    # defaults (SettingsManager._load_from_toml() returns {} for a missing file).
    container = ServiceContainer()
    workspace = register_infrastructure_services(container, tmp_path)
    return container, workspace


class TestEagerlyRegisteredServices:
    def test_every_repository_resolves_to_its_real_sqlite_implementation(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        assert type(container.resolve(ProjectRepository)).__name__ == "SqliteProjectRepository"
        assert type(container.resolve(SupplierRepository)).__name__ == "SqliteSupplierRepository"
        assert type(container.resolve(MedicineRepository)).__name__ == "SqliteMedicineRepository"
        assert type(container.resolve(BatchRepository)).__name__ == "SqliteBatchRepository"
        assert (
            type(container.resolve(ManufacturerRepository)).__name__
            == "SqliteManufacturerRepository"
        )
        assert (
            type(container.resolve(PurchaseInvoiceRepository)).__name__
            == "SqlitePurchaseInvoiceRepository"
        )

    def test_transaction_coordinator_resolves_to_sqlite_unit_of_work(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        assert type(container.resolve(TransactionCoordinator)).__name__ == "SqliteUnitOfWork"

    def test_file_storage_provider_resolves_to_local_implementation(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        assert (
            type(container.resolve(FileStorageProvider)).__name__ == "LocalFileStorageProvider"
        )

    def test_config_and_logging_services_are_registered(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, workspace = container_and_workspace
        assert isinstance(container.resolve(LoggerFactory), LoggerFactory)
        assert isinstance(container.resolve(SecretsManager), SecretsManager)
        assert isinstance(container.resolve(SettingsManager), SettingsManager)
        assert isinstance(container.resolve(SqliteConnectionManager), SqliteConnectionManager)
        assert container.resolve(WorkspaceManager) is workspace

    def test_migrations_were_actually_applied(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        # Real proof the database is ready, not just that a connection
        # object exists: query a table only present once migrations run.
        container, _ = container_and_workspace
        connection = container.resolve(SqliteConnectionManager).connection
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='medicines';"
        ).fetchall()
        assert len(rows) == 1


class TestSecretsManagerFallbackDirectoryMatchesTheSetupScripts:
    def test_a_secret_stored_the_way_the_real_scripts_store_it_is_visible_through_registration(
        self, tmp_path: Path
    ) -> None:
        """
        Regression test for a real bug (2026-08): registration.py used
        to construct SecretsManager(workspace.data_directory) --
        app_root/data -- while scripts/set_gemini_api_key.py and
        scripts/set_website_credentials.py both construct
        SecretsManager(app_root / "data" / ".secrets"). Two genuinely
        different directories, so a key saved by the real script was
        silently invisible to the app. This test builds its own
        SecretsManager EXACTLY the way the scripts do -- completely
        independent of registration.py's own construction -- and
        proves register_infrastructure_services' SecretsManager reads
        the same value back. Fails again if the two ever diverge.
        """
        script_style_secrets_manager = SecretsManager(tmp_path / "data" / ".secrets")
        script_style_secrets_manager.set_secret("gemini_api_key", "key-set-like-the-real-script")

        container = ServiceContainer()
        register_infrastructure_services(container, tmp_path)

        assert (
            container.resolve(SecretsManager).get_secret("gemini_api_key")
            == "key-set-like-the-real-script"
        )


class TestOcrProviderFactory:
    def test_raises_a_clear_error_when_no_api_key_is_stored(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        with pytest.raises(RuntimeError, match="gemini_api_key"):
            container.resolve(OCRProvider)

    def test_returns_a_real_gemini_provider_once_a_key_is_stored(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        container.resolve(SecretsManager).set_secret("gemini_api_key", "fake-key-for-di-test")

        provider = container.resolve(OCRProvider)

        assert isinstance(provider, GeminiOCRProvider)

    def test_factory_re_checks_on_every_resolve_not_cached_as_missing(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        # First resolve fails (no key yet) -- proves a factory (not a
        # pre-baked failure) is registered, and a later resolve after
        # the key is set succeeds without re-registering anything.
        container, _ = container_and_workspace
        with pytest.raises(RuntimeError):
            container.resolve(OCRProvider)

        container.resolve(SecretsManager).set_secret("gemini_api_key", "fake-key-for-di-test")

        assert isinstance(container.resolve(OCRProvider), GeminiOCRProvider)


class TestBrowserAutomationProviderFactory:
    def test_raises_a_clear_error_when_no_page_is_registered(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        with pytest.raises(RuntimeError, match="Page"):
            container.resolve(BrowserAutomationProvider)

    def test_raises_a_clear_error_when_credentials_are_not_configured(
        self, container_and_workspace: tuple[ServiceContainer, WorkspaceManager]
    ) -> None:
        container, _ = container_and_workspace
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            container.register_instance(Page, page)

            with pytest.raises(RuntimeError, match="credentials"):
                container.resolve(BrowserAutomationProvider)

            browser.close()

    def test_returns_a_real_provider_once_page_and_credentials_are_present(
        self, tmp_path: Path
    ) -> None:
        # Uses the REAL project's selector registry (the temp app_root's
        # default path -- app_root/config/selector_registry.webnhathuoc.json
        # -- does not exist, since tmp_path has no config/ directory at
        # all) -- selector_registry_path overrides it explicitly, the
        # same override mechanism config_file_path already offers.
        container = ServiceContainer()
        register_infrastructure_services(
            container, tmp_path, selector_registry_path=_REAL_SELECTOR_REGISTRY_PATH
        )
        container.resolve(SecretsManager).set_secret("webnhathuoc_username", "test-user")
        container.resolve(SecretsManager).set_secret("webnhathuoc_password", "test-pass")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            container.register_instance(Page, page)

            provider = container.resolve(BrowserAutomationProvider)

            assert isinstance(provider, PlaywrightBrowserAutomationProvider)

            browser.close()