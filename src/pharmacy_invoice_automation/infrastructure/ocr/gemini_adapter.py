"""
Implements OCRProvider against Google Gemini Vision.

Builds a schema-constrained request (versioned prompt +
response_json_schema, both externalized under prompt_templates/ -- never
inlined as string literals per project convention) from a preprocessed
invoice image, and maps Gemini's JSON response onto OCRResult/OCRLineItem
field-for-field. Every numeric/date value Gemini could not read
confidently is mapped to None rather than guessed, matching Domain's own
"never fabricate" philosophy (domain.value_objects.ocr_result module
docstring).

Retry policy note: this adapter raises TransientInfrastructureError once
per attempt and does not loop internally.
application.pipeline.invoice_extraction_step.InvoiceExtractionStep
already wraps its one call to OCRProvider.extract() in
configuration.RetryPolicy before the invoice ever leaves OcrInProgress
(see that module's own "Retry scope note") -- a second, independent
retry loop here would just double the effective attempt count against
configuration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRLineItem, OCRResult
from pharmacy_invoice_automation.infrastructure.ocr.ocr_errors import (
    wrap_gemini_error,
    wrap_malformed_response,
)

_PROMPT_PATH = Path(__file__).parent / "prompt_templates" / "invoice_extraction_prompt_v1.md"
_SCHEMA_PATH = Path(__file__).parent / "prompt_templates" / "invoice_extraction_schema_v1.json"

_MAGIC_BYTES_TO_MIME_TYPE: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF", "application/pdf"),
)


@dataclass(frozen=True)
class GeminiOCRConfig:
    """
    Tunable knobs for GeminiOCRProvider -- never hardcoded (TS-002 Sec.
    14: "AI Provider, Model, Temperature, ... Timeout, Confidence
    Threshold" are all configurable items).
    """

    model: str
    # Live-tested against the real Gemini API (2026-07-31): a real
    # structured-output OCR call on a real invoice PDF took ~27s -- 60s
    # leaves real margin instead of racing a 30s deadline.
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    review_confidence_threshold: float = 0.60


class GeminiOCRProvider(OCRProvider):
    """Extracts structured invoice data from an image via Google Gemini Vision."""

    def __init__(self, api_key: str, config: GeminiOCRConfig, logger: logging.Logger) -> None:
        self._client = genai.Client(api_key=api_key)
        self._config = config
        self._logger = logger
        self._prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")
        self._response_json_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def extract(self, image_bytes: bytes) -> OCRResult:
        mime_type = _detect_mime_type(image_bytes)
        if mime_type is None:
            return _failed_result(
                "Unrecognized image format -- expected PDF, PNG, or JPEG (TS-001 Sec. 6)."
            )

        # google-genai's own ContentListUnion documents list[str | Part]
        # as valid (text + inline image parts in one turn), but mypy's
        # list invariance can't match a mixed-type list literal against
        # that Union without a cast -- a known typing-only false positive.
        contents: list[str | types.Part] = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            self._prompt_text,
        ]
        try:
            response = self._client.models.generate_content(
                model=self._config.model,
                contents=contents,  # type: ignore[arg-type]
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=self._response_json_schema,
                    temperature=self._config.temperature,
                    http_options=types.HttpOptions(
                        timeout=int(self._config.timeout_seconds * 1000)
                    ),
                ),
            )
        except Exception as exc:  # noqa: BLE001 -- reclassified immediately below
            raise wrap_gemini_error("gemini.generate_content", exc) from exc

        return self._parse_response(response)

    def _parse_response(self, response: types.GenerateContentResponse) -> OCRResult:
        text = response.text
        if not text:
            raise wrap_malformed_response(
                "gemini.parse_response", "Gemini returned an empty response body."
            )

        try:
            payload: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            self._logger.warning("Gemini response was not valid JSON: %s", exc)
            raise wrap_malformed_response("gemini.parse_response", str(exc)) from exc

        try:
            return _build_ocr_result(payload, self._config.review_confidence_threshold)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            self._logger.warning("Gemini response did not match the expected schema: %s", exc)
            raise wrap_malformed_response("gemini.map_response", str(exc)) from exc


def _detect_mime_type(image_bytes: bytes) -> str | None:
    for magic, mime_type in _MAGIC_BYTES_TO_MIME_TYPE:
        if image_bytes.startswith(magic):
            return mime_type
    return None


def _build_ocr_result(payload: dict[str, Any], review_confidence_threshold: float) -> OCRResult:
    overall_confidence = float(payload["overall_confidence"])
    field_confidences = {
        key: float(value)
        for key, value in payload["field_confidences"].items()
        if value is not None
    }

    lines = tuple(_build_line_item(raw_line) for raw_line in payload["lines"])

    status = (
        OCRStatus.NEEDS_REVIEW
        if overall_confidence < review_confidence_threshold
        else OCRStatus.SUCCEEDED
    )

    return OCRResult(
        status=status,
        raw_invoice_number=payload["raw_invoice_number"],
        raw_invoice_date=_parse_date(payload["raw_invoice_date"]),
        raw_supplier_name=payload["raw_supplier_name"],
        raw_supplier_tax_code=payload["raw_supplier_tax_code"],
        raw_supplier_address=payload["raw_supplier_address"],
        raw_prescription_classification_text=payload["raw_prescription_classification_text"],
        raw_grand_total=_parse_decimal(payload["raw_grand_total"]),
        raw_commercial_discount_amount=_parse_decimal(
            payload["raw_commercial_discount_amount"]
        ),
        lines=lines,
        overall_confidence=overall_confidence,
        field_confidences=field_confidences,
    )


def _build_line_item(raw_line: dict[str, Any]) -> OCRLineItem:
    return OCRLineItem(
        raw_medicine_name=raw_line["raw_medicine_name"],
        raw_batch_number=raw_line["raw_batch_number"],
        raw_expiry_date=_parse_date(raw_line["raw_expiry_date"]),
        raw_unit_text=raw_line["raw_unit_text"],
        raw_quantity=_parse_decimal(raw_line["raw_quantity"]),
        raw_unit_price=_parse_decimal(raw_line["raw_unit_price"]),
        raw_line_total=_parse_decimal(raw_line["raw_line_total"]),
        raw_retail_units_per_purchase_unit=_parse_optional_int(
            raw_line["raw_retail_units_per_purchase_unit"]
        ),
        raw_vat_percentage=_parse_decimal(raw_line["raw_vat_percentage"]),
    )


def _parse_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        # An unparseable date is treated as "not confidently read," per
        # the project's "never guess" rule -- not as a schema failure
        # worth retrying the whole request over.
        return None


def _parse_decimal(raw_value: str | None) -> Decimal | None:
    if raw_value is None:
        return None
    try:
        return Decimal(raw_value)
    except InvalidOperation:
        return None


def _parse_optional_int(raw_value: int | None) -> int | None:
    # A non-positive value would fail Medicine/PurchaseItem's own
    # positive-integer validator later -- treated the same as "not
    # confidently read" here rather than propagating a value already
    # known to be invalid.
    if raw_value is None or raw_value <= 0:
        return None
    return raw_value


def _failed_result(reason: str) -> OCRResult:
    return OCRResult(
        status=OCRStatus.FAILED,
        raw_invoice_number=None,
        raw_invoice_date=None,
        raw_supplier_name=None,
        raw_supplier_tax_code=None,
        raw_supplier_address=None,
        raw_prescription_classification_text=None,
        raw_grand_total=None,
        lines=(),
        overall_confidence=0.0,
        failure_reason=reason,
    )
