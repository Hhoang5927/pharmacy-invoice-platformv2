"""Unit tests for domain.services.price_policy.PricePolicy."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.value_objects.money import Money

pytestmark = pytest.mark.unit


@pytest.fixture()
def policy() -> PricePolicy:
    return PricePolicy()


class TestCalculateSuggestedRetailPrice:
    def test_already_rounded_to_nearest_thousand(self, policy: PricePolicy) -> None:
        # 10000 * 1.2 = 12000.0 -- already an exact multiple of 1000.
        result = policy.calculate_suggested_retail_price(Money(Decimal("10000")))

        assert result.amount == Decimal("12000")
        assert result.currency == "VND"

    def test_rounds_up_to_nearest_thousand(self, policy: PricePolicy) -> None:
        # 12084 * 1.2 = 14500.8 -- closer to 15000 than 14000.
        result = policy.calculate_suggested_retail_price(Money(Decimal("12084")))

        assert result.amount == Decimal("15000")

    def test_rounds_down_to_nearest_thousand(self, policy: PricePolicy) -> None:
        # 12083 * 1.2 = 14499.6 -- closer to 14000 than 15000.
        result = policy.calculate_suggested_retail_price(Money(Decimal("12083")))

        assert result.amount == Decimal("14000")

    def test_zero_purchase_price_yields_zero(self, policy: PricePolicy) -> None:
        result = policy.calculate_suggested_retail_price(Money(Decimal("0")))

        assert result.amount == Decimal("0")

    def test_preserves_currency(self, policy: PricePolicy) -> None:
        result = policy.calculate_suggested_retail_price(Money(Decimal("10000"), "VND"))

        assert result.currency == "VND"

    def test_result_is_a_new_money_not_a_mutation(self, policy: PricePolicy) -> None:
        purchase_price = Money(Decimal("10000"))
        result = policy.calculate_suggested_retail_price(purchase_price)

        assert result is not purchase_price
        assert purchase_price.amount == Decimal("10000")  # untouched

    @pytest.mark.parametrize(
        ("purchase_amount", "expected_suggested_amount"),
        [
            (Decimal("5000"), Decimal("6000")),  # 6000.0 -- exact
            (Decimal("1000"), Decimal("1000")),  # 1200.0 -> nearest 1000 = 1000
            (Decimal("50000"), Decimal("60000")),  # 60000.0 -- exact
        ],
    )
    def test_various_realistic_purchase_prices(
        self, policy: PricePolicy, purchase_amount: Decimal, expected_suggested_amount: Decimal
    ) -> None:
        result = policy.calculate_suggested_retail_price(Money(purchase_amount))

        assert result.amount == expected_suggested_amount

    def test_does_not_affect_existing_methods(self, policy: PricePolicy) -> None:
        # Additive-only change (per PO instruction) -- sanity check the
        # pre-existing methods on this frozen-adjacent service still work.
        assert policy.resolve_unit_price(Money(Decimal("100")), None) == Money(Decimal("100"))
        assert policy.check_total_consistency(Money(Decimal("100")), Money(Decimal("100"))) is True
