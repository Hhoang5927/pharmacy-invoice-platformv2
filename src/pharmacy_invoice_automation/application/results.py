"""
Result Objects: the rich outcome every Application use case returns
(Stage 05 requirement #18).

Distinct from domain.shared.result.Result: Domain's Result is
deliberately minimal (success/failure/reason), sized for business-rule
outcomes consumed by other Domain code. UseCaseResult is deliberately
richer, because a use case's caller (eventually the Presentation layer)
needs more than pass/fail -- every warning worth surfacing, every error
that stopped things, run statistics, and a confidence figure, all in
one object. Having both is not duplication: they serve different
layers with different responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Generic, TypeVar

TValue = TypeVar("TValue")

# Statistics values are simple, JSON/UI-friendly primitives -- never a
# Domain entity or value object (DTOs and Results never expose those).
StatisticValue = float | int | str


@dataclass(frozen=True)
class UseCaseResult(Generic[TValue]):
    """
    The rich outcome of one Application use case invocation.

    ``errors``/``warnings`` are tuples and ``statistics`` is wrapped in
    a read-only MappingProxyType, so this object is genuinely immutable
    end to end, not just at the dataclass-field level.
    """

    is_success: bool
    value: TValue | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    statistics: MappingProxyType[str, StatisticValue]
    confidence: float | None

    @staticmethod
    def success(
        value: TValue,
        *,
        warnings: tuple[str, ...] = (),
        statistics: dict[str, StatisticValue] | None = None,
        confidence: float | None = None,
    ) -> "UseCaseResult[TValue]":
        """Build a successful result carrying ``value``."""
        return UseCaseResult(
            is_success=True,
            value=value,
            errors=(),
            warnings=warnings,
            statistics=MappingProxyType(dict(statistics or {})),
            confidence=confidence,
        )

    @staticmethod
    def failure(
        errors: tuple[str, ...],
        *,
        warnings: tuple[str, ...] = (),
        statistics: dict[str, StatisticValue] | None = None,
    ) -> "UseCaseResult[TValue]":
        """Build a failed result carrying every error that caused it."""
        return UseCaseResult(
            is_success=False,
            value=None,
            errors=errors,
            warnings=warnings,
            statistics=MappingProxyType(dict(statistics or {})),
            confidence=None,
        )

    @property
    def is_failure(self) -> bool:
        """True if this result represents a failure."""
        return not self.is_success
