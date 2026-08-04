"""
Real, paid integration test: composition_root.cli.run_scan() end to
end, against the live Gemini API and the real sample invoice
(tests/fixtures/sample_invoices/invoice.pdf) -- Composition Root Stage
B (PO-confirmed 2026-08).

Skipped automatically (a genuine pytest.skip, not just excluded from
CI's `-m unit` run) unless BOTH a stored Gemini API key and the sample
image are present -- same convention as
tests/golden/ocr_golden_files/test_gemini_adapter_live.py.

Fully isolated: a temp app_root (its own SQLite database, its own
SecretsManager fallback directory) with the real project's Gemini API
key copied in -- never touches the real project's data/project.sqlite3
or data/.secrets.

Does not assert exact OCR field values (Gemini's phrasing/confidence
are not byte-stable across runs -- see test_gemini_adapter_live.py's
own docstring for the same reasoning). Asserts the structural
invariants Part 3.1's VAT-based classification promises: the "Slaska
New" line (8% VAT, real invoice.pdf) must not survive into the
persisted invoice, and its exclusion must be traceable in the
returned UseCaseResult's warnings -- if this ever prints/finds
something materially different, the printed output (captured by pytest
regardless of outcome) is there for manual inspection, not silently
papered over by a loose assertion.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pharmacy_invoice_automation.composition_root import cli
from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager
from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer

pytestmark = pytest.mark.golden


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


_SAMPLE_INVOICE_PATH = _repo_root() / "tests" / "fixtures" / "sample_invoices" / "invoice.pdf"


def _get_real_api_key() -> str | None:
    fallback_directory = _repo_root() / "data" / ".secrets"
    return SecretsManager(fallback_directory=fallback_directory).get_secret("gemini_api_key")


def _skip_reason() -> str | None:
    if _get_real_api_key() is None:
        return (
            "No Gemini API key stored -- run scripts/set_gemini_api_key.py once, then "
            "re-run this test."
        )
    if not _SAMPLE_INVOICE_PATH.is_file():
        return f"Sample invoice not found at '{_SAMPLE_INVOICE_PATH}'."
    return None


@pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")
def test_run_scan_processes_the_real_sample_invoice(tmp_path: Path) -> None:
    image_folder = tmp_path / "invoices"
    image_folder.mkdir()
    shutil.copy(_SAMPLE_INVOICE_PATH, image_folder / "invoice.pdf")

    app_root = tmp_path / "app"
    container = ServiceContainer()
    register_infrastructure_services(container, app_root)
    # Real key, copied into this test's own isolated SecretsManager --
    # never reads/writes the real project's data/.secrets directly.
    container.resolve(SecretsManager).set_secret("gemini_api_key", _get_real_api_key())

    results = cli.run_scan(container, image_folder, project_name="Golden Test Project")

    assert len(results) == 1
    result = results[0]
    assert result.is_success, f"Expected success, got errors: {result.errors}"
    invoice = result.value
    assert invoice is not None

    item_names = [item.medicine_name for item in invoice.items]
    assert not any("Slaska" in name for name in item_names), (
        f"'Slaska New' (8% VAT) must have been excluded, but items were: {item_names}"
    )
    assert any("Slaska" in warning and "VAT" in warning.upper() for warning in result.warnings), (
        f"Expected a VAT-exclusion warning mentioning 'Slaska', got: {result.warnings}"
    )
    # At least one genuine medicine line (5% VAT) must have survived --
    # proves this isn't accidentally excluding everything.
    assert len(invoice.items) >= 1
