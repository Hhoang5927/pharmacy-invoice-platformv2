"""
Service Port: FileStorageProvider.

Abstract file storage contract -- new per Stage 04. Covers reading
invoice images from the folder(s) a Project points at (FR-02) and
writing export files (FR-13), without the Domain layer knowing whether
storage is the local filesystem or something else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class FileStorageProvider(ABC):
    """Abstract contract for reading and writing files."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Return the raw bytes of the file at ``path``."""

    @abstractmethod
    def write_file(self, path: str, content: bytes) -> None:
        """Write ``content`` to ``path``, creating or overwriting it."""

    @abstractmethod
    def delete_file(self, path: str) -> None:
        """Delete the file at ``path``. No-op if it does not exist."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """True if a file exists at ``path``."""

    @abstractmethod
    def list_files(self, folder_path: str, extensions: list[str]) -> list[str]:
        """
        Return every file path under ``folder_path`` whose extension is
        in ``extensions`` (e.g. [".jpg", ".jpeg", ".png"] for FR-02
        invoice image discovery).
        """
