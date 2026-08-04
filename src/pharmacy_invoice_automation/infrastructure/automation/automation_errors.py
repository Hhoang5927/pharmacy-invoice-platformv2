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
