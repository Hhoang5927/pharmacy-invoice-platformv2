"""
File storage infrastructure: LocalFileStorageProvider (implements
domain.ports.services.FileStorageProvider) and WorkspaceManager (owns
the application's standard data/logs/temp/exports directories).

New subpackage under infrastructure/ -- Prompt 03's original scaffold
did not anticipate a dedicated file-storage location.
"""

from pharmacy_invoice_automation.infrastructure.file_storage.local_file_storage_provider import (
    LocalFileStorageProvider,
)
from pharmacy_invoice_automation.infrastructure.file_storage.workspace_manager import (
    WorkspaceManager,
)

__all__ = ["LocalFileStorageProvider", "WorkspaceManager"]
