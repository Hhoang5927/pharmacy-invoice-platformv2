"""
SecretsManager: secret storage (API keys, website credentials), never
stored in plaintext (Technical Design Document Section 15.1).

Primary storage: the OS-level credential store, via the ``keyring``
package (Windows Credential Manager on the real target platform).
Fallback (used automatically if ``keyring`` is unavailable or fails
for any reason): a Fernet-encrypted local file. The fallback's
encryption key is itself stored in a separate file with restrictive
permissions applied -- a materially weaker guarantee than a real OS
keychain, which is exactly why keyring is preferred whenever available;
this fallback exists so the application still functions (and is still
testable) in an environment where keyring cannot be used.

Environment note: ``keyring`` is not installable in this sandboxed
environment (no network access). The fallback path is what is actually
exercised and tested here; the keyring path is written correctly for
the real target environment but could not be executed in this sandbox.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_SERVICE_NAME = "pharmacy_invoice_automation"


class SecretsManager:
    """Keyring-primary, Fernet-fallback secret storage."""

    def __init__(self, fallback_directory: Path) -> None:
        self._fallback_directory = fallback_directory
        self._fallback_directory.mkdir(parents=True, exist_ok=True)
        self._key_path = self._fallback_directory / ".secret.key"
        self._secrets_path = self._fallback_directory / "secrets.enc.json"

    def get_secret(self, key: str) -> str | None:
        """Return the current value of ``key``, or None if unset."""
        value = self._get_from_keyring(key)
        if value is not None:
            return value
        return self._get_from_fallback(key)

    def set_secret(self, key: str, value: str) -> None:
        """Store ``value`` under ``key``, preferring the OS keyring."""
        if self._set_in_keyring(key, value):
            return
        self._set_in_fallback(key, value)

    # --- Keyring path (untestable in this sandbox; correct for target platform) ---

    def _get_from_keyring(self, key: str) -> str | None:
        try:
            import keyring  # deferred: keyring is an optional dependency, not always installed
        except ImportError:
            return None
        try:
            return keyring.get_password(_SERVICE_NAME, key)
        except Exception:
            # Any keyring backend failure (no backend available, locked
            # keychain, etc.) falls back rather than raising -- a
            # missing secret must never crash the caller.
            return None

    def _set_in_keyring(self, key: str, value: str) -> bool:
        try:
            import keyring  # deferred: optional dependency
        except ImportError:
            return False
        try:
            keyring.set_password(_SERVICE_NAME, key, value)
            return True
        except Exception:
            return False

    # --- Fernet-encrypted-file fallback (exercised and tested in this sandbox) ---

    def _get_fernet(self) -> Fernet:
        if not self._key_path.exists():
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
            self._restrict_permissions(self._key_path)
        return Fernet(self._key_path.read_bytes())

    def _get_from_fallback(self, key: str) -> str | None:
        if not self._secrets_path.exists():
            return None
        fernet = self._get_fernet()
        encrypted_by_key: dict[str, str] = json.loads(self._secrets_path.read_text("utf-8"))
        encrypted_value = encrypted_by_key.get(key)
        if encrypted_value is None:
            return None
        try:
            return fernet.decrypt(encrypted_value.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None

    def _set_in_fallback(self, key: str, value: str) -> None:
        fernet = self._get_fernet()
        encrypted_by_key: dict[str, str] = {}
        if self._secrets_path.exists():
            encrypted_by_key = json.loads(self._secrets_path.read_text("utf-8"))
        encrypted_by_key[key] = fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._secrets_path.write_text(json.dumps(encrypted_by_key), encoding="utf-8")
        self._restrict_permissions(self._secrets_path)

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # best-effort on platforms where this is not meaningful (e.g. Windows)
