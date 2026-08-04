"""
Logging infrastructure: per-category loggers, rotation, secret
redaction (Technical Design Document Section 11).

Not an implementation of any Domain port -- Domain's architecture
rules forbid it from performing logging at all, so there is nothing to
implement against. This is a standalone Infrastructure utility.
"""

from pharmacy_invoice_automation.infrastructure.logging.logger_factory import (
    CATEGORIES,
    LoggerFactory,
)
from pharmacy_invoice_automation.infrastructure.logging.redaction_filter import (
    RedactionFilter,
)

__all__ = ["LoggerFactory", "CATEGORIES", "RedactionFilter"]
