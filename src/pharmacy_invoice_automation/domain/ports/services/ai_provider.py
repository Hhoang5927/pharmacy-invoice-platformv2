"""
Service Port: AIProvider.

Abstract, general-purpose text AI contract -- new per Stage 04,
distinct from OCRProvider (which is specifically vision-based invoice
extraction). Intended for future text-classification fallback use
cases this system can already anticipate, e.g. resolving a
prescription/OTC classification via a language model when neither the
invoice text nor the local catalog can determine it
(services.medicine_validation_service.MedicineValidationService
currently fails outright in that case; a future Infrastructure
implementation of this port could be wired in as a further fallback
before asking the pharmacist).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Abstract contract for general-purpose text AI capabilities."""

    @abstractmethod
    def classify_text(self, text: str, candidate_labels: list[str]) -> str:
        """
        Return whichever of ``candidate_labels`` best matches ``text``.
        Implementations should raise for a permanent failure (e.g. no
        usable response) rather than returning an arbitrary label.
        """

    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        """Return a free-text completion for ``prompt``."""
