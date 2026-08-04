"""
Generic Result / Outcome type.

Used across the Domain layer (domain.rules) and, later, the
Application layer, to model expected business outcomes -- such as "no
matching supplier was found" or "these totals do not reconcile" -- as
data rather than as exceptions. Exceptions remain reserved for true
invariant violations (see domain.exceptions).

Scope note (Stage 04): this module is the one deliberate exception to
Stage 04's "src/domain/** only" restriction. It was always specified,
across the Technical Design Document, Implementation Blueprint (Phase 1
deliverables), and Implementation Specification, as being delivered
alongside -- and as a hard dependency of -- every domain rule's return
type. It contains zero pharmacy-domain knowledge: a fully generic,
reusable Result type. Leaving it unimplemented would make domain.rules
fail to import, directly contradicting this stage's own "Domain
compiles independently" success criterion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, cast

TValue = TypeVar("TValue")


@dataclass(frozen=True)
class Result(Generic[TValue]):
    """
    An immutable outcome of an operation that either succeeds with a
    value of type ``TValue`` or fails with a human-readable reason.

    Callers should check ``is_success`` / ``is_failure`` before reading
    ``value`` or ``failure_reason`` -- use the ``success`` / ``failure``
    factory methods to construct one rather than the constructor
    directly.
    """

    is_success: bool
    value: TValue | None
    failure_reason: str | None

    @staticmethod
    def success(value: TValue) -> Result[TValue]:
        """Build a successful Result carrying ``value``."""
        return Result(is_success=True, value=value, failure_reason=None)

    @staticmethod
    def failure(reason: str) -> Result[TValue]:
        """Build a failed Result carrying a human-readable ``reason``."""
        return Result(is_success=False, value=None, failure_reason=reason)

    @property
    def is_failure(self) -> bool:
        """True if this Result represents a failure."""
        return not self.is_success

    def unwrap(self) -> TValue:
        """
        Return the success value.

        Raises ``ValueError`` if this Result is a failure. Intended for
        call sites that have already checked ``is_success`` and want
        the value without a redundant None-check.
        """
        if not self.is_success:
            raise ValueError(f"Cannot unwrap a failed Result: {self.failure_reason!r}")
        return cast(TValue, self.value)
