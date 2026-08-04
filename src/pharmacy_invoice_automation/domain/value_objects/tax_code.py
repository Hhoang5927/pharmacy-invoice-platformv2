"""
Value Object: TaxCode.

A validated Vietnamese supplier tax code (Ma so thue). Accepts the
standard 10-digit form or the 13-character branch form
(10 digits + '-' + 3 digits).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

_TAX_CODE_PATTERN = re.compile(r"^\d{10}(-\d{3})?$")


@dataclass(frozen=True)
class TaxCode:
    """An immutable, validated Vietnamese tax code."""

    value: str

    def __post_init__(self) -> None:
        cleaned = self.value.strip()
        if not _TAX_CODE_PATTERN.match(cleaned):
            raise ValidationError(
                f"'{self.value}' is not a valid Vietnamese tax code "
                f"(expected 10 digits, optionally followed by '-' and 3 digits)."
            )
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value
