"""
Base exception: DomainError.

Every exception raised by the Domain layer derives from this, so
calling code can catch broadly (``except DomainError``) or narrowly
(``except DuplicateSupplierError``) as needed. Domain exceptions are
reserved for true invariant violations; expected business outcomes are
modeled as ``shared.result.Result`` instead (see domain.rules).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every Domain-layer exception."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
