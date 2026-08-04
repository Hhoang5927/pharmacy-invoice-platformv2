"""Exception: InvalidBusinessRuleError."""

from __future__ import annotations

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError


class InvalidBusinessRuleError(DomainError):
    """
    Raised when an operation would violate a named business rule --
    for example, an invalid Invoice status transition (see
    domain.entities.invoice.Invoice.transition_to).
    """

    def __init__(self, rule_name: str, message: str) -> None:
        super().__init__(f"Business rule '{rule_name}' violated: {message}")
        self.rule_name = rule_name
