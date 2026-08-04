"""
Value Object: ExpiryDate.

A validated medicine batch expiry date (Han su dung). Rejects only
dates that are implausibly far in the future (almost certainly a
garbled OCR read); a past expiry date is left representable
deliberately, since an invoice can legitimately reference an
already-expired batch received in error -- that is exactly the kind of
thing FR-05 human review should catch and flag, not something this
value object should silently refuse to hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

_MAX_YEARS_IN_FUTURE = 15


@dataclass(frozen=True)
class ExpiryDate:
    """An immutable, validated medicine batch expiry date."""

    value: date

    def __post_init__(self) -> None:
        latest_plausible = date.today() + timedelta(days=365 * _MAX_YEARS_IN_FUTURE)
        if self.value > latest_plausible:
            raise ValidationError(
                f"Expiry date {self.value.isoformat()} is implausibly far in the "
                f"future (more than {_MAX_YEARS_IN_FUTURE} years)."
            )

    @property
    def is_expired(self) -> bool:
        """True if this expiry date is in the past relative to today."""
        return self.value < date.today()

    def __str__(self) -> str:
        return self.value.isoformat()
