"""
Service Port: PriceLookupProvider.

Abstract retail price lookup contract. Implemented against the Long
Chau public website in a future Infrastructure stage. Renamed from
"IPriceLookupProvider" per Stage 04's updated naming.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.value_objects.money import Money


class PriceLookupProvider(ABC):
    """Abstract contract for looking up a medicine's retail price."""

    @abstractmethod
    def lookup_price(self, medicine_name: str) -> Money | None:
        """
        Return the current retail price for ``medicine_name``, or None
        if it could not be found (FR-09) -- callers should flag this
        for manual entry via services.price_policy.PricePolicy, never
        treat it as a hard failure.
        """
