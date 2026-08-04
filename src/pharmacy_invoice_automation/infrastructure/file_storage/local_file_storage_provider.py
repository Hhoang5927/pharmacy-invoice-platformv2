"""
LocalFileStorageProvider: implements domain.ports.services.FileStorageProvider
against the local filesystem.

Covers reading invoice images from a Project's folder(s) (FR-02) and
writing export files (FR-13). New subpackage under infrastructure/ --
Stage 04/05's original scaffolding did not anticipate a dedicated file
storage location, since Prompt 03's stub tree only foresaw ocr/,
automation/, persistence/, config/, logging/.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)


class LocalFileStorageProvider(FileStorageProvider):
    """Reads and writes files on the local filesystem."""

    def read_file(self, path: str) -> bytes:
        """Return the raw bytes of the file at ``path``."""
        return Path(path).read_bytes()

    def write_file(self, path: str, content: bytes) -> None:
        """Write ``content`` to ``path``, creating parent directories and overwriting as needed."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def delete_file(self, path: str) -> None:
        """Delete the file at ``path``. No-op if it does not exist."""
        target = Path(path)
        if target.exists():
            target.unlink()

    def exists(self, path: str) -> bool:
        """True if a file exists at ``path``."""
        return Path(path).is_file()

    def list_files(self, folder_path: str, extensions: Sequence[str]) -> list[str]:
        """
        Return every file path under ``folder_path`` (recursively) whose
        extension is in ``extensions``, sorted for deterministic
        ordering across runs (FR-02: batch processing order should not
        depend on filesystem-dependent directory iteration order).
        """
        folder = Path(folder_path)
        if not folder.is_dir():
            return []
        normalized_extensions = {ext.lower() for ext in extensions}
        matches = [
            str(path)
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in normalized_extensions
        ]
        return sorted(matches)
