"""
Logging filter: RedactionFilter.

Strips or masks any field known to be sensitive (API keys, passwords,
session tokens) before a record is ever written to any sink. Applied
centrally by logger_factory, not left to the discipline of each call
site (Technical Design Document Section 11.3).
"""

from __future__ import annotations

import logging
import re

# Matches "key<sep>value" pairs embedded in free-text log messages,
# where the key looks sensitive. Captures the key and separator so the
# VALUE can be replaced while the key label is kept for readability --
# masking only the label (e.g. "password" -> "[REDACTED-KEY]") while
# leaving "=hunter2" untouched would still leak the actual secret.
_SENSITIVE_PAIR_PATTERN = re.compile(
    r"(?P<key>[\w.-]*(?:api[_-]?key|password|secret|token|credential)[\w.-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>\S+)",
    re.IGNORECASE,
)

# Matches a sensitive substring anywhere in a structured field name (e.g.
# both "password" and "gemini_api_key" match) -- used for redacting
# extra={} keyword values passed directly to a log call, where the key
# and value are already separate, not embedded in free text.
_SENSITIVE_KEY_SUBSTRING = re.compile(
    r"(api[_-]?key|password|secret|token|credential)", re.IGNORECASE
)

_REDACTED_VALUE = "***REDACTED***"


class RedactionFilter(logging.Filter):
    """Masks sensitive values in both the log message and its extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive content on ``record`` in place, then allow it through."""
        record.msg = self._redact_text(str(record.msg))
        if record.args:
            record.args = tuple(
                self._redact_text(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
        for key, value in list(vars(record).items()):
            if _SENSITIVE_KEY_SUBSTRING.search(key) and isinstance(value, str):
                setattr(record, key, _REDACTED_VALUE)
        return True

    @staticmethod
    def _redact_text(text: str) -> str:
        return _SENSITIVE_PAIR_PATTERN.sub(
            lambda m: f"{m.group('key')}{m.group('sep')}{_REDACTED_VALUE}", text
        )


