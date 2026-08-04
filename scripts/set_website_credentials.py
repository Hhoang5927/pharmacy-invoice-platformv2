"""
One-time developer script: interactively prompts for the webnhathuoc.com
login username/password and stores both via
infrastructure.config.secrets_manager.SecretsManager (OS keyring, with a
Fernet-encrypted local-file fallback).

The password is never printed, never logged, and never written to any
file this script itself creates in plaintext -- SecretsManager's
fallback path always encrypts it before touching disk (see
secrets_manager.py). Run this yourself, once, from a real terminal so
the credentials are only ever typed by you, not passed through any AI
assistant or committed to git:

    python scripts/set_website_credentials.py

Required before Composition Root Stage D (browser automation) can run --
infrastructure.di.registration.register_infrastructure_services's
BrowserAutomationProvider factory reads these same two secret keys
('webnhathuoc_username' / 'webnhathuoc_password') and raises a clear
error if either is missing.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pharmacy_invoice_automation.infrastructure.config.secrets_manager import (  # noqa: E402
    SecretsManager,
)

_USERNAME_SECRET_KEY = "webnhathuoc_username"
_PASSWORD_SECRET_KEY = "webnhathuoc_password"
_FALLBACK_DIRECTORY = _REPO_ROOT / "data" / ".secrets"


def _prompt_and_store(manager: SecretsManager, secret_key: str, label: str, hidden: bool) -> None:
    if manager.get_secret(secret_key) is not None:
        answer = input(f"A {label} is already stored. Overwrite it? [y/N] ").strip().lower()
        if answer != "y":
            print(f"Left the existing {label} unchanged.")
            return

    if hidden:
        value = getpass.getpass(f"Enter {label} (input hidden): ").strip()
    else:
        value = input(f"Enter {label}: ").strip()

    if not value:
        print(f"No {label} entered -- nothing was saved.", file=sys.stderr)
        raise SystemExit(1)

    manager.set_secret(secret_key, value)
    print(f"{label} saved via SecretsManager (key name: {secret_key!r}).")


def main() -> None:
    manager = SecretsManager(fallback_directory=_FALLBACK_DIRECTORY)

    _prompt_and_store(manager, _USERNAME_SECRET_KEY, "webnhathuoc.com username", hidden=False)
    _prompt_and_store(manager, _PASSWORD_SECRET_KEY, "webnhathuoc.com password", hidden=True)

    print(
        "Website credentials saved. Neither value was printed, logged, or written "
        "to any file this script controls."
    )


if __name__ == "__main__":
    main()
