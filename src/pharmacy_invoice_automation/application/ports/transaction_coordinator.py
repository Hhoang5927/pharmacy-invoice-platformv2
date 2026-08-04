"""
Port: TransactionCoordinator (Stage 05 requirement #13).

Abstract contract: "either the entire invoice succeeds, or the entire
invoice fails" -- no partial persistence of an invoice, its newly
created supplier, or its newly created medicines.

This is an abstraction Application depends on and Infrastructure (a
later stage) implements against a real SQLite transaction. Until that
implementation exists, this contract still fully documents the
boundary every persistence-touching pipeline step must respect, and
Application's own code (pipeline.invoice_persistence_step) is already
written against it -- nothing in Application changes when a real
implementation is wired in later.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

TResult = TypeVar("TResult")


class TransactionCoordinator(ABC):
    """Abstract contract for running a unit of work atomically."""

    @abstractmethod
    def run_in_transaction(self, unit_of_work: Callable[[], TResult]) -> TResult:
        """
        Execute ``unit_of_work`` atomically: if it raises, every
        persistence operation performed inside it must be rolled back;
        if it returns normally, every operation performed inside it
        must be durably committed together.
        """
