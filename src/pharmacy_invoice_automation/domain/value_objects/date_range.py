"""
Value Object: DateRange.

A validated, inclusive date interval. General-purpose -- intended for
date-range based searches and reports (FR-12 search, FR-16 reports),
which need more than a single exact date to filter on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError


@dataclass(frozen=True)
class DateRange:
    """An immutable, validated inclusive date range."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValidationError(
                f"DateRange start_date ({self.start_date.isoformat()}) cannot be "
                f"after end_date ({self.end_date.isoformat()})."
            )

    def contains(self, value: date) -> bool:
        """True if ``value`` falls within this range, inclusive of both ends."""
        return self.start_date <= value <= self.end_date

    def overlaps(self, other: "DateRange") -> bool:
        """True if this range shares at least one day with ``other``."""
        return self.start_date <= other.end_date and other.start_date <= self.end_date

    @property
    def day_count(self) -> int:
        """Number of days spanned by this range, inclusive of both ends."""
        return (self.end_date - self.start_date).days + 1

    def __str__(self) -> str:
        return f"{self.start_date.isoformat()} to {self.end_date.isoformat()}"
