"""
One-time developer script: interactively prompts for the Gemini API key
and stores it via infrastructure.config.secrets_manager.SecretsManager
(OS keyring, with a Fernet-encrypted local-file fallback).

The key is never printed, never logged, and never written to any file
this script itself creates in plaintext -- SecretsManager's fallback
path always encrypts it before touching disk (see secrets_manager.py).
Run this yourself, once, from a real terminal so the key is only ever
typed by you, not passed through any AI assistant or committed to git:

    python scripts/set_gemini_api_key.py

Get a key first at https://ai.google.dev/gemini-api/docs/api-key.
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

_SECRET_KEY = "gemini_api_key"
_FALLBACK_DIRECTORY = _REPO_ROOT / "data" / ".secrets"


def main() -> None:
    manager = SecretsManager(fallback_directory=_FALLBACK_DIRECTORY)

    if manager.get_secret(_SECRET_KEY) is not None:
        answer = input("A Gemini API key is already stored. Overwrite it? [y/N] ").strip().lower()
        if answer != "y":
            print("Left the existing key unchanged.")
            return

    api_key = getpass.getpass("Enter your Gemini API key (input hidden): ").strip()
    if not api_key:
        print("No key entered -- nothing was saved.", file=sys.stderr)
        raise SystemExit(1)

    manager.set_secret(_SECRET_KEY, api_key)
    print(
        f"Gemini API key saved via SecretsManager (key name: {_SECRET_KEY!r}). "
        "It was not printed, logged, or written to any file this script controls."
    )


if __name__ == "__main__":
    main()
