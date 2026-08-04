"""
Domain Service: PricePolicy.

Encapsulates pricing-related business policy that spans more than one
entity: whether an invoice's stated grand total reconciles with its
computed item totals (absorbing rounding via a tolerance), and which
price source should win when more than one is available (e.g. an
OCR'd price vs. a Long Chau retail lookup).

Replaces the prior domain.rules.total_consistency_rule (folded in here
as one of PricePolicy's responsibilities, per Stage 04's Domain
Services pattern).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pharmacy_invoice_automation.domain.constants import (
    TOTAL_CONSISTENCY_RELATIVE_TOLERANCE,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money

_RETAIL_PRICE_MARKUP = Decimal("1.2")
_RETAIL_PRICE_ROUNDING_STEP = Decimal("1000")


class PricePolicy:
    """Business policy governing invoice totals and price-source selection."""

    def check_total_consistency(
        self, calculated_item_total_sum: Money, stated_grand_total: Money
    ) -> bool:
        """
        True if ``stated_grand_total`` is within
        domain.constants.TOTAL_CONSISTENCY_RELATIVE_TOLERANCE of
        ``calculated_item_total_sum``.
        """
        return calculated_item_total_sum.is_close_to(
            stated_grand_total, TOTAL_CONSISTENCY_RELATIVE_TOLERANCE
        )

    def resolve_unit_price(
        self, ocr_extracted_price: Money | None, catalog_lookup_price: Money | None
    ) -> Money | None:
        """
        Decide which price source wins when resolving a PurchaseItem's
        unit price (FR-09): the price actually printed on the invoice
        always takes precedence, since it is what the pharmacy actually
        paid -- a retail lookup price is only a fallback used when the
        invoice itself did not state one, and never overrides it.
        """
        if ocr_extracted_price is not None:
            return ocr_extracted_price
        return catalog_lookup_price

    def calculate_suggested_retail_price(self, purchase_price: Money) -> Money:
        """
        Suggested retail price = purchase price x 1.2, rounded to the
        nearest 1,000 VND (PO-confirmed, 2026-08). Replaces the
        originally-planned Long Chau price-lookup design for this figure
        (see CLAUDE.md Deviation D3) -- this is now a pure calculation,
        not an external lookup, and the operator retains final authority
        to edit it on the website regardless.
        """
        raw_amount = purchase_price.amount * _RETAIL_PRICE_MARKUP
        rounded_steps = (raw_amount / _RETAIL_PRICE_ROUNDING_STEP).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return Money(
            amount=rounded_steps * _RETAIL_PRICE_ROUNDING_STEP,
            currency=purchase_price.currency,
        )
