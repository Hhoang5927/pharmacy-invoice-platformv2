"""
Value Object: Quantity.

A validated, strictly positive quantity of dispensing units on an
invoice line.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError


@dataclass(frozen=True)
class Quantity:
    """An immutable, validated strictly-positive quantity."""

    amount: Decimal

    def __post_init__(self) -> None:
        amount = self.amount if isinstance(self.amount, Decimal) else Decimal(str(self.amount))
        if amount <= 0:
            raise ValidationError(f"Quantity must be strictly positive, got {amount}.")
        object.__setattr__(self, "amount", amount)

    def __str__(self) -> str:
        return str(self.amount)
