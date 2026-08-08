"""
Infrastructure exceptions wrapping raw Playwright errors.

A genuinely transient failure (timeout, navigation interrupted, a closed
target) is raised as application.exceptions.TransientInfrastructureError,
per that type's own documented intent: "Infrastructure ... will import and
raise this type instead of a concrete SDK/library exception" so
application.configuration.RetryPolicy recognizes it as retryable. Every
other failure -- a selector that is not yet verified, a page that did not
reach the expected state, a post-fill value mismatch -- is a permanent
AutomationError and must never be retried.
"""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from pharmacy_invoice_automation.application.exceptions import TransientInfrastructureError

# Substrings from Playwright's own error messages that indicate a
# transient, environment-level failure rather than a permanent one (a
# genuinely broken selector or an unexpected page state). Kept narrow and
# explicit rather than "retry on any PlaywrightError" -- a broken selector
# should fail fast, not be retried into a slow, misleading timeout loop.
_TRANSIENT_MESSAGE_MARKERS: tuple[str, ...] = (
    "net::",
    "NS_ERROR_",
    "Navigation",
    "navigation",
    "Target page, context or browser has been closed",
    "Target closed",
    "Connection closed",
)


class AutomationError(Exception):
    """Base class for a permanent (non-retryable) automation failure."""


class SelectorNotUsableError(AutomationError):
    """
    Raised when automation code needs a SelectorRegistry entry that is not
    'confirmed'/'derived' yet. Distinct from a locator simply not matching
    anything on the page -- this means the entry was never verified
    against the live site and must not be relied on at all.
    """


class VerificationFailedError(AutomationError):
    """
    Raised when a value read back from the page after entry does not
    match the approved source value, per the Automation business rule
    that every entered value is verified against its source and a
    verification failure stops processing -- it is never silently
    continued past.
    """


class UnitMismatchError(VerificationFailedError):
    """
    Raised specifically by
    infrastructure.automation.playwright_adapter.PlaywrightBrowserAutomationProvider._verify_unit_matches_invoice
    when this invoice line's own unit does not match the site's real
    displayed unit for that row AND no reviewer-confirmed
    domain.entities.purchase_item.PurchaseItem.confirmed_website_unit_ratio
    exists yet to resolve it (PO decision, 2026-08 -- "Coldi-B DNH" 1
    Hop = 1 Lọ proved this is not always a bug, just an unconfirmed
    naming difference). A VerificationFailedError subclass -- still a
    permanent, non-retryable failure -- but distinguished so
    composition_root.cli.run_automate can print a specific, actionable
    message pointing the operator at the review step, instead of the
    generic "unexpected error" wording used for genuinely unclassified
    failures.
    """

    def __init__(
        self,
        *,
        medicine_name: str,
        purchase_item_id: str,
        invoice_unit_label: str,
        website_unit_label: str,
    ) -> None:
        self.medicine_name = medicine_name
        self.purchase_item_id = purchase_item_id
        self.invoice_unit_label = invoice_unit_label
        self.website_unit_label = website_unit_label
        super().__init__(
            f"Đơn vị trên web ('{website_unit_label}') khác với đơn vị trên hóa đơn "
            f"('{invoice_unit_label}') cho thuốc '{medicine_name}' -- cần xác nhận thủ công "
            "trước khi điền số lượng/giá. Không tự động quy đổi hay đoán."
        )


def wrap_playwright_error(action: str, exc: BaseException) -> Exception:
    """
    Classify a raw Playwright exception into the vocabulary Application's
    RetryPolicy understands. Never returns the raw Playwright exception
    type -- automation code must not let a concrete SDK exception leak
    past this module's boundary.
    """
    if isinstance(exc, PlaywrightTimeoutError):
        return TransientInfrastructureError(f"{action}: Playwright timeout -- {exc}")
    if isinstance(exc, PlaywrightError):
        message = str(exc)
        if any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS):
            return TransientInfrastructureError(f"{action}: {message}")
        return AutomationError(f"{action}: {message}")
    return AutomationError(f"{action}: {exc}")
