"""
Configuration Objects (Stage 05 requirement #17): immutable settings
that shape orchestration behavior without being hardcoded into it.

Grouped in one module since each is a small, self-contained value
object with no behavior beyond its own settings -- separating them into
three files would fragment one cohesive "tunable knobs" concern for no
benefit.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.application.exceptions import (
    TransientInfrastructureError,
)


@dataclass(frozen=True)
class RetryPolicy:
    """
    Governs whether and how a failed operation is retried.

    Only ``TransientInfrastructureError`` (or a subclass) is ever
    retried -- every Domain exception (ValidationError,
    InvalidBusinessRuleError, a *NotFoundError, a Duplicate*Error) is a
    business-rule or validation outcome, never retried, per Stage 05's
    explicit "Never retry validation failures."
    """

    max_attempts: int = 3
    base_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}.")
        if self.base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds cannot be negative.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1.")

    def is_retryable(self, error: Exception) -> bool:
        """True only for a TransientInfrastructureError (or subclass)."""
        return isinstance(error, TransientInfrastructureError)

    def compute_backoff_seconds(self, attempt_number: int) -> float:
        """
        Exponential backoff delay before ``attempt_number`` (1-indexed;
        the delay before the *first* retry, i.e. attempt_number=2, is
        just ``base_backoff_seconds``).
        """
        if attempt_number < 2:
            return 0.0
        return self.base_backoff_seconds * (self.backoff_multiplier ** (attempt_number - 2))


@dataclass(frozen=True)
class ConfidenceThresholds:
    """
    Governs the Confidence Pipeline's Auto Accept / Highlight / Manual
    Review decision (Stage 05 requirement #11) for one extracted field.

    A field's confidence >= ``auto_accept_at_or_above`` is auto-accepted.
    A field's confidence >= ``review_at_or_above`` (but below
    auto-accept) is highlighted but does not block processing. Below
    ``review_at_or_above``, the field requires manual review before the
    invoice may proceed.
    """

    auto_accept_at_or_above: float = 0.90
    review_at_or_above: float = 0.60

    def __post_init__(self) -> None:
        if not (0.0 <= self.review_at_or_above <= self.auto_accept_at_or_above <= 1.0):
            raise ValueError(
                "Thresholds must satisfy "
                "0 <= review_at_or_above <= auto_accept_at_or_above <= 1, got "
                f"review_at_or_above={self.review_at_or_above}, "
                f"auto_accept_at_or_above={self.auto_accept_at_or_above}."
            )


@dataclass(frozen=True)
class BatchOptions:
    """
    Governs how a batch run behaves end to end.

    ``continue_on_invoice_failure`` defaults to True per Stage 05's
    explicit "never stop the whole batch because of one invoice."
    ``allow_ai_fallback_classification`` gates whether
    pipeline.party_matching_step may fall back to
    domain.ports.services.AIProvider when Domain's own classification
    rule cannot determine a medicine's prescription/OTC status.
    """

    continue_on_invoice_failure: bool = True
    allow_ai_fallback_classification: bool = True
    retry_policy: RetryPolicy = RetryPolicy()
    confidence_thresholds: ConfidenceThresholds = ConfidenceThresholds()
