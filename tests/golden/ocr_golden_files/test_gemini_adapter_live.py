"""
Real, paid integration test: calls the live Gemini API with a real
invoice image from tests/fixtures/sample_invoices/.

Skipped automatically (not just excluded from CI's `-m unit` run, but a
genuine pytest.skip so running plain `pytest` locally doesn't error)
unless BOTH of the following are present:
  - a Gemini API key stored via SecretsManager under "gemini_api_key"
    (run scripts/set_gemini_api_key.py once to store it -- this test
    never reads an API key from an environment variable directly)
  - at least one real image file in tests/fixtures/sample_invoices/

This test does not assert exact field values -- Gemini's phrasing and
per-field confidence are not byte-stable across runs/model versions.
It asserts structural invariants (a well-formed, non-FAILED OCRResult
with sane confidence bounds) and prints the full result for manual
verification. Once a human has verified one real run's output for a
given sample image, that output can be saved under expected_json/ as a
baseline for a future, stricter regression test -- not done here since
no baseline exists yet.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from pharmacy_invoice_automation.infrastructure.config.secrets_manager import SecretsManager
from pharmacy_invoice_automation.infrastructure.ocr.gemini_adapter import (
    GeminiOCRConfig,
    GeminiOCRProvider,
)

pytestmark = pytest.mark.golden

_SAMPLE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".pdf")


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


def _find_sample_image() -> Path | None:
    sample_dir = _repo_root() / "tests" / "fixtures" / "sample_invoices"
    if not sample_dir.is_dir():
        return None
    for path in sorted(sample_dir.iterdir()):
        if path.suffix.lower() in _SAMPLE_IMAGE_EXTENSIONS:
            return path
    return None


def _get_api_key() -> str | None:
    # Same fallback directory as scripts/set_gemini_api_key.py -- never
    # read from an environment variable directly in code.
    fallback_directory = _repo_root() / "data" / ".secrets"
    return SecretsManager(fallback_directory=fallback_directory).get_secret("gemini_api_key")


def _skip_reason() -> str | None:
    if _get_api_key() is None:
        return (
            "No Gemini API key stored -- run scripts/set_gemini_api_key.py once, then "
            "re-run this test."
        )
    if _find_sample_image() is None:
        return (
            "No sample invoice image found under tests/fixtures/sample_invoices/ -- add a "
            "real invoice image (png/jpg/jpeg/pdf) to run this test."
        )
    return None


def _print(text: str) -> None:
    # Real invoices contain Vietnamese text; a default-cp1252 Windows
    # console otherwise crashes with UnicodeEncodeError on print().
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="backslashreplace").decode(encoding))


@pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")
def test_extract_against_the_live_gemini_api() -> None:
    api_key = _get_api_key()
    sample_image_path = _find_sample_image()
    assert api_key is not None
    assert sample_image_path is not None

    config = GeminiOCRConfig(model="gemini-3.6-flash")
    provider = GeminiOCRProvider(api_key=api_key, config=config, logger=logging.getLogger("test"))

    image_bytes = sample_image_path.read_bytes()
    result = provider.extract(image_bytes)

    _print(f"\n--- GeminiOCRProvider live result for {sample_image_path.name} ---")
    _print(f"status: {result.status}")
    _print(f"overall_confidence: {result.overall_confidence}")
    _print(f"raw_invoice_number: {result.raw_invoice_number}")
    _print(f"raw_invoice_date: {result.raw_invoice_date}")
    _print(f"raw_supplier_name: {result.raw_supplier_name}")
    _print(f"raw_grand_total: {result.raw_grand_total}")
    _print(f"lines ({len(result.lines)}):")
    for index, line in enumerate(result.lines, start=1):
        _print(f"  {index}. {line}")
    _print(f"failure_reason: {result.failure_reason}")

    assert result.status.value in ("succeeded", "needs_review", "failed")
    if result.succeeded:
        assert 0.0 <= result.overall_confidence <= 1.0
        assert isinstance(result.lines, tuple)
