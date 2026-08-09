"""
register_infrastructure_services: wires every concrete Infrastructure
adapter that actually exists into a ServiceContainer, registered
against the abstract port each one implements.

This is the Infrastructure-owned half of dependency injection --
registering what Infrastructure itself provides. Wiring Application use
cases and Presentation on top of these registrations remains the job
of a later Composition Root stage.

OCRProvider and BrowserAutomationProvider are registered as FACTORIES
(register_factory), not eager instances, and deliberately not at the
same unconditional point as the repositories/storage above:

- OCRProvider (GeminiOCRProvider) needs a Gemini API key that may not
  be configured yet (e.g. before scripts/set_gemini_api_key.py has
  ever been run) -- eagerly constructing genai.Client with a missing
  key would fail at STARTUP even for a run that never touches OCR at
  all (e.g. a review-only or automation-only session). The factory
  re-checks SecretsManager on every resolve() instead, raising a
  clear, actionable RuntimeError only when something actually needs
  OCR and the key is genuinely absent.
- BrowserAutomationProvider (PlaywrightBrowserAutomationProvider) needs
  a live playwright Page, which has a browser-session-scoped lifetime
  this container does not own or manage (launching/closing a browser
  is the caller's responsibility, e.g. Composition Root's automation
  stage) -- the factory expects the caller to have already registered
  a real Page (container.register_instance(Page, page)) before
  resolving BrowserAutomationProvider, and raises a clear,
  actionable RuntimeError if one is not present, or if website
  credentials are not configured.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

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
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.infrastructure.automation.playwright_adapter import (
    PlaywrightAutomationConfig,
    PlaywrightBrowserAutomationProvider,
)
from pharmacy_invoice_automation.infrastructure.automation.selector_registry import (
    load_selector_registry,
)
from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager
from pharmacy_invoice_automation.infrastructure.config.settings_manager import SettingsManager
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer
from pharmacy_invoice_automation.infrastructure.file_storage.local_file_storage_provider import (
    LocalFileStorageProvider,
)
from pharmacy_invoice_automation.infrastructure.file_storage.workspace_manager import (
    WorkspaceManager,
)
from pharmacy_invoice_automation.infrastructure.logging.logger_factory import LoggerFactory
from pharmacy_invoice_automation.infrastructure.ocr.gemini_adapter import (
    GeminiOCRConfig,
    GeminiOCRProvider,
)
from pharmacy_invoice_automation.infrastructure.persistence import sqlite_repositories
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)
from pharmacy_invoice_automation.infrastructure.persistence.migrations.migration_runner import (
    MigrationRunner,
)
from pharmacy_invoice_automation.infrastructure.persistence.unit_of_work import SqliteUnitOfWork

_GEMINI_API_KEY_SECRET = "gemini_api_key"
_WEBSITE_USERNAME_SECRET = "webnhathuoc_username"
_WEBSITE_PASSWORD_SECRET = "webnhathuoc_password"


def register_infrastructure_services(
    container: ServiceContainer,
    app_root: Path,
    config_file_path: Path | None = None,
    selector_registry_path: Path | None = None,
) -> WorkspaceManager:
    """
    Construct and register every Infrastructure adapter that actually
    exists, against the abstract port (Domain or Application) each one
    implements. Applies pending schema migrations as part of wiring up
    persistence, so the database is guaranteed ready before anything
    else resolves a repository. Returns the WorkspaceManager, since
    callers commonly need it directly (e.g. to resolve the default
    working folder) in addition to whatever the container now holds.
    """
    workspace = WorkspaceManager(app_root)
    workspace.ensure_directories_exist()

    logger_factory = LoggerFactory(workspace.logs_directory)
    container.register_instance(LoggerFactory, logger_factory)

    # Must match scripts/set_gemini_api_key.py and
    # scripts/set_website_credentials.py's own fallback_directory
    # exactly (data/.secrets, not bare data/ -- SecretsManager treats
    # this as the literal directory it reads/writes, no subfolder
    # implied) -- .gitignore's own "data/.secrets/" entry is the
    # canonical convention every secret-writing script already follows.
    secrets_manager = SecretsManager(workspace.data_directory / ".secrets")
    container.register_instance(SecretsManager, secrets_manager)
    resolved_config_path = config_file_path or (app_root / "config" / "app_settings.default.toml")
    settings_manager = SettingsManager(resolved_config_path, secrets_manager)
    settings = settings_manager.load()
    container.register_instance(SettingsManager, settings_manager)

    database_path = Path(settings.database_path)
    if not database_path.is_absolute():
        database_path = app_root / database_path
    connection_manager = SqliteConnectionManager(database_path)
    MigrationRunner(connection_manager.connection).run_pending_migrations()
    container.register_instance(SqliteConnectionManager, connection_manager)

    container.register_instance(TransactionCoordinator, SqliteUnitOfWork(connection_manager))

    container.register_instance(
        ProjectRepository, sqlite_repositories.SqliteProjectRepository(connection_manager)
    )
    container.register_instance(
        SupplierRepository, sqlite_repositories.SqliteSupplierRepository(connection_manager)
    )
    container.register_instance(
        MedicineRepository,
        sqlite_repositories.SqliteMedicineRepository(
            connection_manager, medicine_code_prefix=settings.medicine_code_prefix
        ),
    )
    container.register_instance(
        BatchRepository, sqlite_repositories.SqliteBatchRepository(connection_manager)
    )
    container.register_instance(
        ManufacturerRepository,
        sqlite_repositories.SqliteManufacturerRepository(connection_manager),
    )
    container.register_instance(
        PurchaseInvoiceRepository,
        sqlite_repositories.SqlitePurchaseInvoiceRepository(connection_manager),
    )

    container.register_instance(FileStorageProvider, LocalFileStorageProvider())
    container.register_instance(WorkspaceManager, workspace)

    def _build_ocr_provider() -> OCRProvider:
        api_key = secrets_manager.get_secret(_GEMINI_API_KEY_SECRET)
        if api_key is None:
            raise RuntimeError(
                f"No Gemini API key stored under {_GEMINI_API_KEY_SECRET!r} -- run "
                "scripts/set_gemini_api_key.py once before anything that needs OCR."
            )
        config = GeminiOCRConfig(
            model=settings.gemini_model, timeout_seconds=settings.ocr_timeout_seconds
        )
        return GeminiOCRProvider(
            api_key=api_key, config=config, logger=logger_factory.get_logger("ocr")
        )

    container.register_factory(OCRProvider, _build_ocr_provider)

    resolved_registry_path = selector_registry_path or (
        app_root / "config" / "selector_registry.webnhathuoc.json"
    )

    def _build_browser_automation_provider() -> BrowserAutomationProvider:
        if not container.is_registered(Page):
            raise RuntimeError(
                "No Playwright Page registered -- launch a browser and call "
                "container.register_instance(Page, page) before resolving "
                "BrowserAutomationProvider."
            )
        username = secrets_manager.get_secret(_WEBSITE_USERNAME_SECRET)
        password = secrets_manager.get_secret(_WEBSITE_PASSWORD_SECRET)
        if username is None or password is None:
            raise RuntimeError(
                f"Website credentials not configured -- store them via SecretsManager "
                f"under {_WEBSITE_USERNAME_SECRET!r}/{_WEBSITE_PASSWORD_SECRET!r} first."
            )
        page = container.resolve(Page)
        registry = load_selector_registry(resolved_registry_path)
        config = PlaywrightAutomationConfig(
            username=username,
            password=password,
            default_timeout_ms=int(settings.automation_timeout_seconds * 1000),
            human_disambiguation_timeout_ms=int(
                settings.automation_human_disambiguation_timeout_seconds * 1000
            ),
        )
        return PlaywrightBrowserAutomationProvider(
            page,
            registry,
            config,
            logger_factory.get_logger("automation"),
            batch_repository=container.resolve(BatchRepository),
            price_policy=PricePolicy(),
            medicine_repository=container.resolve(MedicineRepository),
            supplier_repository=container.resolve(SupplierRepository),
        )

    container.register_factory(BrowserAutomationProvider, _build_browser_automation_provider)

    return workspace
