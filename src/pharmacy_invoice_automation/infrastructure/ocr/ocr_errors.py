"""
Infrastructure exceptions wrapping raw Gemini SDK / network errors.

Per TS-002 Sec. 12, "Malformed Response" and "Invalid JSON" share the
same retry-then-give-up recovery path as "Provider Timeout" and "Rate
Limit" -- Gemini's output is non-deterministic, so asking again for the
same image may well produce a well-formed response. Both therefore raise
application.exceptions.TransientInfrastructureError, exactly like
infrastructure.automation.automation_errors raises it for a transient
browser failure, per that type's own documented intent ("Infrastructure
... will import and raise this type instead of a concrete SDK/library
exception"). Only a failure retrying cannot possibly fix -- an invalid
API key, a permission/content-policy rejection -- is a permanent
OCRError.

Retry itself is not implemented here: application.pipeline.
invoice_extraction_step.InvoiceExtractionStep already wraps its one call
to OCRProvider.extract() in configuration.RetryPolicy before the invoice
ever leaves OcrInProgress. gemini_adapter.GeminiOCRProvider raises once
per attempt; it does not loop.
"""

from __future__ import annotations

import httpx
from google.genai import errors as genai_errors

from pharmacy_invoice_automation.application.exceptions import TransientInfrastructureError

# HTTP status codes worth retrying: request timeout, conflict (rare,
# transient on Google's backends), rate limit, and every 5xx server error.
_TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


class OCRError(Exception):
    """Base class for a permanent (non-retryable) OCR extraction failure."""


def wrap_gemini_error(action: str, exc: BaseException) -> Exception:
    """Classify a raw Gemini SDK / transport exception for application.configuration.RetryPolicy."""
    if isinstance(exc, genai_errors.APIError):
        code = exc.code
        if code in _TRANSIENT_HTTP_STATUS_CODES:
            return TransientInfrastructureError(f"{action}: Gemini API error {code} -- {exc}")
        return OCRError(f"{action}: Gemini API error {code} -- {exc}")
    if isinstance(exc, httpx.HTTPError):
        # Covers httpx's timeout/connect/network exception hierarchy --
        # the google-genai SDK's synchronous client is httpx-based and
        # does not wrap these into its own error types.
        return TransientInfrastructureError(f"{action}: network transport failure -- {exc}")
    return OCRError(f"{action}: {exc}")


def wrap_malformed_response(action: str, reason: str) -> Exception:
    """
    A response that arrived successfully but could not be parsed/mapped
    onto OCRResult -- per TS-002 Sec. 12, retried the same as a
    transient network failure rather than failed immediately.
    """
    return TransientInfrastructureError(f"{action}: {reason}")
