"""
Value Object: Money.

Represents a currency amount with validated invariants and
currency-aware arithmetic. Defaults to Vietnamese Dong (VND), the
currency used throughout this system's target website and reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

_VND_QUANTIZE = Decimal("1")  # VND has no minor subunit in practical use


@dataclass(frozen=True)
class Money:
    """An immutable, validated monetary amount."""

    amount: Decimal
    currency: str = "VND"

    def __post_init__(self) -> None:
        amount = self.amount if isinstance(self.amount, Decimal) else Decimal(str(self.amount))
        if amount < 0:
            raise ValidationError(f"Money amount cannot be negative: {amount}")
        if not self.currency:
            raise ValidationError("Money currency cannot be empty.")
        if self.currency == "VND":
            amount = amount.quantize(_VND_QUANTIZE, rounding=ROUND_HALF_UP)
        object.__setattr__(self, "amount", amount)

    def _check_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValidationError(
                f"Cannot combine Money in different currencies: "
                f"{self.currency} vs {other.currency}"
            )

    def __add__(self, other: "Money") -> "Money":
        self._check_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount <= other.amount

    def multiply(self, factor: Decimal) -> "Money":
        """Multiply this amount by a scalar factor (e.g. a Quantity's amount)."""
        return Money(self.amount * factor, self.currency)

    def is_close_to(self, other: "Money", relative_tolerance: Decimal) -> bool:
        """
        True if ``other`` is within ``relative_tolerance`` (a fraction,
        e.g. Decimal("0.01") for 1%) of this amount. Used by
        domain.rules.total_consistency_rule.
        """
        self._check_same_currency(other)
        if self.amount == 0:
            return other.amount == 0
        difference = abs(self.amount - other.amount)
        return difference <= (self.amount * relative_tolerance)

    def __str__(self) -> str:
        return f"{self.amount:,} {self.currency}"
