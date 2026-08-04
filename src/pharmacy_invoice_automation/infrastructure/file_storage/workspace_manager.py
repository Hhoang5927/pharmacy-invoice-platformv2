"""
WorkspaceManager: resolves and maintains the application's standard
working directories -- data, logs, temp, and exports -- relative to a
single base directory (the project root in development; the
application's installation/data directory in a packaged build).

Distinct from LocalFileStorageProvider: that class implements Domain's
FileStorageProvider port (generic read/write/list against arbitrary
paths); this class owns no port and is a plain Infrastructure utility
for "where do our own working files live," consumed directly by other
Infrastructure adapters (e.g. the SQLite connection manager asking
WorkspaceManager for the data directory) and, later, the Composition Root.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path


class WorkspaceManager:
    """Owns the application's standard working directories."""

    def __init__(self, base_directory: Path) -> None:
        self._base_directory = base_directory

    @property
    def data_directory(self) -> Path:
        """Durable application data (the SQLite database file lives here)."""
        return self._base_directory / "data"

    @property
    def logs_directory(self) -> Path:
        """Rotating log files."""
        return self._base_directory / "logs"

    @property
    def temp_directory(self) -> Path:
        """Transient working files (e.g. preprocessed images), safe to clear at any time."""
        return self._base_directory / "temp"

    @property
    def exports_directory(self) -> Path:
        """Default destination for FR-13 exports (JSON/Excel/Log), unless the user picks another."""
        return self._base_directory / "data" / "exports"

    def ensure_directories_exist(self) -> None:
        """Create every standard directory if it does not already exist."""
        for directory in (
            self.data_directory,
            self.logs_directory,
            self.temp_directory,
            self.exports_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def create_temp_file_path(self, suffix: str = "") -> Path:
        """
        Return a unique, not-yet-existing path inside temp_directory.
        Does not create the file itself -- the caller writes to it.
        """
        self.temp_directory.mkdir(parents=True, exist_ok=True)
        return self.temp_directory / f"{uuid.uuid4().hex}{suffix}"

    def cleanup_temp_files(self, older_than_seconds: float | None = None) -> int:
        """
        Delete files in temp_directory, optionally only those last
        modified more than ``older_than_seconds`` ago. Returns the
        number of files deleted. Never raises for a file that
        disappears between listing and deletion (e.g. a concurrent
        cleanup or in-progress write) -- cleanup is best-effort.
        """
        if not self.temp_directory.is_dir():
            return 0
        cutoff = time.time() - older_than_seconds if older_than_seconds is not None else None
        deleted_count = 0
        for path in self.temp_directory.iterdir():
            if not path.is_file():
                continue
            if cutoff is not None and path.stat().st_mtime > cutoff:
                continue
            try:
                path.unlink()
                deleted_count += 1
            except FileNotFoundError:
                continue
        return deleted_count

    @staticmethod
    def system_temp_directory() -> Path:
        """The OS-provided temp directory, for cases needing isolation from our own temp/."""
        return Path(tempfile.gettempdir())
