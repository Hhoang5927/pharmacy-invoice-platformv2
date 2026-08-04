"""
Unit tests for infrastructure.ocr.gemini_adapter.GeminiOCRProvider.

No real Gemini API call is made -- Client.models.generate_content is
replaced with a stub that returns a fabricated JSON response (or raises a
fabricated SDK/transport exception), so these tests are fast, free, and
safe to run in CI. The one real, paid integration test against the live
API lives in tests/golden/ocr_golden_files/test_gemini_adapter_live.py
and is skipped unless a real API key and sample image are both present.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx
import pytest
from google.genai import errors as genai_errors

from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.infrastructure.ocr.gemini_adapter import (
    GeminiOCRConfig,
    GeminiOCRProvider,
)
from pharmacy_invoice_automation.infrastructure.ocr.ocr_errors import (
    OCRError,
    wrap_gemini_error,
)

pytestmark = pytest.mark.unit

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _FakeResponse:
    """Duck-typed stand-in for google.genai.types.GenerateContentResponse."""

    def __init__(self, text: str | None) -> None:
        self.text = text


class _StubModels:
    def __init__(self, result: _FakeResponse | BaseException) -> None:
        self._result = result
        self.last_call_kwargs: dict[str, object] | None = None

    def generate_content(self, **kwargs: object) -> _FakeResponse:
        self.last_call_kwargs = kwargs
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _StubClient:
    def __init__(self, result: _FakeResponse | BaseException) -> None:
        self.models = _StubModels(result)


def _full_payload(
    overall_confidence: float = 0.95,
    raw_invoice_date: str | None = "2026-07-15",
    raw_expiry_date: str | None = "2027-01-01",
) -> dict:
    return {
        "raw_invoice_number": "HD-001234",
        "raw_invoice_date": raw_invoice_date,
        "raw_supplier_name": "Cong ty Duoc Pham ABC",
        "raw_supplier_tax_code": "0123456789",
        "raw_supplier_address": "123 Le Loi, Q1, TP.HCM",
        "raw_prescription_classification_text": "Thuoc khong ke don",
        "raw_grand_total": "1234567.00",
        "raw_commercial_discount_amount": "26855.00",
        "lines": [
            {
                "raw_medicine_name": "Paracetamol 500mg",
                "raw_batch_number": "B12345",
                "raw_expiry_date": raw_expiry_date,
                "raw_unit_text": "hop",
                "raw_quantity": "10",
                "raw_unit_price": "50000.50",
                "raw_line_total": "500005.00",
                "raw_retail_units_per_purchase_unit": 100,
                "raw_vat_percentage": "5.00",
            },
            {
                "raw_medicine_name": None,
                "raw_batch_number": None,
                "raw_expiry_date": None,
                "raw_unit_text": None,
                "raw_quantity": None,
                "raw_unit_price": None,
                "raw_line_total": None,
                "raw_retail_units_per_purchase_unit": None,
                "raw_vat_percentage": None,
            },
        ],
        "overall_confidence": overall_confidence,
        "field_confidences": {
            "invoice": 0.98,
            "supplier": 0.95,
            "medicine": 0.90,
            "batch": None,
            "totals": 0.99,
        },
    }


def _provider_with_stub(result: _FakeResponse | BaseException) -> GeminiOCRProvider:
    config = GeminiOCRConfig(model="gemini-3.6-flash")
    provider = GeminiOCRProvider(
        api_key="fake-key-for-tests", config=config, logger=logging.getLogger("test")
    )
    provider._client = _StubClient(result)  # type: ignore[assignment]
    return provider


class TestExtractSuccess:
    def test_maps_full_response_field_for_field(self) -> None:
        payload = _full_payload()
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC + b"rest-of-fake-png")

        assert result.status is OCRStatus.SUCCEEDED
        assert result.succeeded is True
        assert result.raw_invoice_number == "HD-001234"
        assert result.raw_invoice_date is not None
        assert result.raw_invoice_date.isoformat() == "2026-07-15"
        assert result.raw_supplier_name == "Cong ty Duoc Pham ABC"
        assert result.raw_grand_total == Decimal("1234567.00")
        assert result.raw_commercial_discount_amount == Decimal("26855.00")
        assert result.overall_confidence == 0.95
        assert result.field_confidences["invoice"] == 0.98
        assert "batch" not in result.field_confidences  # null -> omitted, not fabricated as 0.0

        assert len(result.lines) == 2
        first, second = result.lines
        assert first.raw_medicine_name == "Paracetamol 500mg"
        assert first.raw_batch_number == "B12345"
        assert first.raw_expiry_date is not None
        assert first.raw_expiry_date.isoformat() == "2027-01-01"
        assert first.raw_quantity == Decimal("10")
        assert first.raw_unit_price == Decimal("50000.50")
        assert first.raw_line_total == Decimal("500005.00")
        assert first.raw_retail_units_per_purchase_unit == 100
        assert first.raw_vat_percentage == Decimal("5.00")

        # Second line: every field genuinely unreadable -> None throughout,
        # never invented.
        assert second.raw_medicine_name is None
        assert second.raw_quantity is None
        assert second.raw_retail_units_per_purchase_unit is None
        assert second.raw_vat_percentage is None

    def test_absent_commercial_discount_maps_to_none(self) -> None:
        payload = _full_payload()
        payload["raw_commercial_discount_amount"] = None
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.raw_commercial_discount_amount is None

    def test_non_positive_packaging_ratio_maps_to_none_not_invalid_data(self) -> None:
        # Gemini should never emit <= 0 per the schema/prompt contract, but
        # if it somehow did, this must not be propagated as a value that
        # would later fail Medicine/PurchaseItem's own positive-integer
        # validator -- treated the same as "not confidently read."
        payload = _full_payload()
        payload["lines"][0]["raw_retail_units_per_purchase_unit"] = 0
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.lines[0].raw_retail_units_per_purchase_unit is None

    def test_decimal_precision_is_exact_not_float_rounded(self) -> None:
        payload = _full_payload()
        payload["raw_grand_total"] = "1234567.99"
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        # If this had round-tripped through float, 1234567.99 could drift.
        assert result.raw_grand_total == Decimal("1234567.99")
        assert str(result.raw_grand_total) == "1234567.99"

    def test_low_confidence_yields_needs_review_status(self) -> None:
        payload = _full_payload(overall_confidence=0.30)
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.status is OCRStatus.NEEDS_REVIEW
        assert result.needs_manual_review is True

    def test_high_confidence_yields_succeeded_status(self) -> None:
        payload = _full_payload(overall_confidence=0.99)
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.status is OCRStatus.SUCCEEDED
        assert result.needs_manual_review is False

    def test_confidence_exactly_at_threshold_is_not_flagged(self) -> None:
        # review_confidence_threshold defaults to 0.60 -- boundary itself
        # counts as acceptable (< threshold triggers review, not <=).
        payload = _full_payload(overall_confidence=0.60)
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.status is OCRStatus.SUCCEEDED

    def test_unparseable_date_maps_to_none_not_a_crash(self) -> None:
        payload = _full_payload(raw_invoice_date="not-a-real-date")
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        result = provider.extract(_PNG_MAGIC)

        assert result.status is OCRStatus.SUCCEEDED
        assert result.raw_invoice_date is None

    def test_pdf_and_jpeg_magic_bytes_are_both_accepted(self) -> None:
        payload = _full_payload()
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        pdf_result = provider.extract(b"%PDF-1.4 rest")
        assert pdf_result.status is OCRStatus.SUCCEEDED

        jpeg_result = provider.extract(b"\xff\xd8\xff\xe0 rest")
        assert jpeg_result.status is OCRStatus.SUCCEEDED


class TestExtractFailureHandling:
    def test_unrecognized_image_format_returns_failed_result_not_raise(self) -> None:
        provider = _provider_with_stub(_FakeResponse(json.dumps(_full_payload())))

        result = provider.extract(b"not-a-real-image-at-all")

        assert result.status is OCRStatus.FAILED
        assert result.succeeded is False
        assert result.failure_reason is not None
        assert "Unrecognized image format" in result.failure_reason

    def test_empty_response_text_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        provider = _provider_with_stub(_FakeResponse(text=None))

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)

    def test_invalid_json_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        provider = _provider_with_stub(_FakeResponse("{not valid json"))

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)

    def test_missing_required_key_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        payload = _full_payload()
        del payload["lines"]
        provider = _provider_with_stub(_FakeResponse(json.dumps(payload)))

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)

    def test_server_error_from_sdk_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        error = genai_errors.ServerError(code=503, response_json={"error": {"message": "busy"}})
        provider = _provider_with_stub(error)

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)

    def test_rate_limit_error_from_sdk_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        error = genai_errors.ClientError(
            code=429, response_json={"error": {"message": "slow down"}}
        )
        provider = _provider_with_stub(error)

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)

    def test_invalid_api_key_error_raises_permanent_ocr_error(self) -> None:
        error = genai_errors.ClientError(code=401, response_json={"error": {"message": "bad key"}})
        provider = _provider_with_stub(error)

        with pytest.raises(OCRError):
            provider.extract(_PNG_MAGIC)

    def test_httpx_timeout_raises_transient_infrastructure_error(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        provider = _provider_with_stub(httpx.ConnectTimeout("timed out"))

        with pytest.raises(TransientInfrastructureError):
            provider.extract(_PNG_MAGIC)


class TestGeminiOCRConfig:
    def test_defaults(self) -> None:
        config = GeminiOCRConfig(model="gemini-3.6-flash")
        assert config.timeout_seconds == 60.0
        assert config.temperature == 0.0
        assert config.review_confidence_threshold == 0.60


class TestWrapGeminiError:
    def test_server_error_is_transient(self) -> None:
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        error = genai_errors.ServerError(code=500, response_json={"error": {}})
        wrapped = wrap_gemini_error("test", error)
        assert isinstance(wrapped, TransientInfrastructureError)

    def test_client_error_403_is_permanent(self) -> None:
        error = genai_errors.ClientError(code=403, response_json={"error": {}})
        wrapped = wrap_gemini_error("test", error)
        assert isinstance(wrapped, OCRError)
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        assert not isinstance(wrapped, TransientInfrastructureError)

    def test_unclassified_exception_defaults_to_permanent(self) -> None:
        wrapped = wrap_gemini_error("test", ValueError("some local bug"))
        assert isinstance(wrapped, OCRError)
