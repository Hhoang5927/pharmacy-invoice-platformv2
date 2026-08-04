"""
Unit tests for domain.services.invoice_calculation_service.InvoiceCalculationService,
focused on calculate_reconciled_grand_total -- the CKTM-aware, tax-
INCLUSIVE total InvoiceValidationStep reconciles against an invoice's
OCR'd stated grand total (revised understanding: "Giam Tru CKTM" is a
whole-invoice deduction, never a per-item one; and a real VAT invoice's
own grand total is always tax-inclusive, so this must compare against
calculate_grand_total_with_tax(), not the tax-exclusive item sum --
fixed together with Deviation D5's TaxType.EIGHT_PERCENT).
calculate_grand_total_with_tax's own basic behavior is pre-existing and
not re-tested here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.services.invoice_calculation_service import (
    InvoiceCalculationService,
)
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit


def _make_item(quantity: str, unit_price: str, tax_type: TaxType | None = None) -> PurchaseItem:
    return PurchaseItem(
        id=str(uuid.uuid4()),
        medicine_name="Paracetamol 500mg",
        unit=Unit(code="hop"),
        quantity=Quantity(Decimal(quantity)),
        unit_price=Money(Decimal(unit_price)),
        tax_type=tax_type,
    )


def _make_invoice(
    *items: PurchaseItem, commercial_discount_amount: Money | None = None
) -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        id=str(uuid.uuid4()),
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
        commercial_discount_amount=commercial_discount_amount,
    )
    for item in items:
        invoice.add_item(item)
    return invoice


@pytest.fixture()
def service() -> InvoiceCalculationService:
    return InvoiceCalculationService()


class TestCalculateReconciledGrandTotal:
    def test_no_discount_returns_the_plain_grand_total_with_tax(
        self, service: InvoiceCalculationService
    ) -> None:
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
        )

        reconciled = service.calculate_reconciled_grand_total(invoice)

        assert reconciled == service.calculate_grand_total_with_tax(invoice)

    def test_discount_is_deducted_from_the_grand_total_with_tax_not_the_pretax_sum(
        self, service: InvoiceCalculationService
    ) -> None:
        # Real Traphaco invoice.pdf line amounts: Slaska New (TS 8%,
        # 76364 -> +6109 tax = 82473) + Tra gung (TS 5%, 57145 -> +2857
        # tax = 60002) = 142475 with tax, minus a 26855 CKTM discount
        # (that row's own tax portion is not separately tracked -- see
        # calculate_reconciled_grand_total's docstring).
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
            commercial_discount_amount=Money(Decimal("26855")),
        )

        reconciled = service.calculate_reconciled_grand_total(invoice)

        assert reconciled.amount == Decimal("115620")
        # Sanity check on the fixture: proves this is genuinely
        # different from the old (buggy) tax-exclusive calculation --
        # not a coincidental match.
        assert reconciled.amount != (invoice.calculate_item_total_sum().amount - Decimal("26855"))

    def test_discount_exceeding_the_grand_total_raises_not_silently_clamped(
        self, service: InvoiceCalculationService
    ) -> None:
        invoice = _make_invoice(
            _make_item("1", "1000", TaxType.STANDARD),
            commercial_discount_amount=Money(Decimal("999999")),
        )

        with pytest.raises(ValidationError):
            service.calculate_reconciled_grand_total(invoice)

    def test_mismatched_discount_currency_raises(
        self, service: InvoiceCalculationService
    ) -> None:
        invoice = _make_invoice(
            _make_item("1", "1000", TaxType.STANDARD),
            commercial_discount_amount=Money(Decimal("100"), currency="USD"),
        )

        with pytest.raises(ValidationError):
            service.calculate_reconciled_grand_total(invoice)


class TestExcludedSupplementTotalAdjustment:
    """
    Deviation D10 fix (PO-confirmed 2026-08, final -- no exceptions):
    pipeline.party_matching_step.PartyMatchingStep permanently removes
    any VAT!=5% line before this ever runs -- correct, deliberate
    filtering, not an anomaly. The invoice's OCR'd stated grand total
    still reflects the ORIGINAL, full invoice, so the excluded lines'
    own tax-inclusive value must be added back onto the remaining
    (post-discount) total before comparing, not left out.
    """

    def test_excluded_total_is_added_back_on_top(
        self, service: InvoiceCalculationService
    ) -> None:
        # Real Traphaco invoice.pdf: Tra gung (TS 5%, kept) = 60002 with
        # tax; Slaska New (TS 8%, excluded by PartyMatchingStep before
        # this ever runs) = 82473 with tax, no longer a PurchaseItem at
        # all -- only representable via excluded_supplement_total.
        invoice = _make_invoice(_make_item("5", "11429", TaxType.REDUCED))

        reconciled = service.calculate_reconciled_grand_total(
            invoice, excluded_supplement_total=Money(Decimal("82473"))
        )

        assert reconciled.amount == Decimal("60002") + Decimal("82473")

    def test_excluded_total_combines_with_a_commercial_discount(
        self, service: InvoiceCalculationService
    ) -> None:
        # Full real invoice.pdf reconstruction: kept items (Tra gung,
        # Boganic, Loratadin, all TS 5%) with tax = 270002, minus 26855
        # CKTM discount = 243147, plus 82473 for the excluded Slaska New
        # line = 325620. The real stated grand total is 324275 -- a
        # ~1345 VND (~0.41%) gap, comfortably inside PricePolicy's 1%
        # tolerance, matching calculate_reconciled_grand_total's own
        # documented residual (CKTM's own tax portion isn't separately
        # tracked -- see that method's docstring).
        invoice = _make_invoice(
            _make_item("5", "11429", TaxType.REDUCED),  # Tra gung: 57145 -> 60002
            _make_item("2", "76190", TaxType.REDUCED),  # Boganic: 152380 -> 159999
            _make_item("5", "9524", TaxType.REDUCED),  # Loratadin: 47620 -> 50001
            commercial_discount_amount=Money(Decimal("26855")),
        )

        reconciled = service.calculate_reconciled_grand_total(
            invoice, excluded_supplement_total=Money(Decimal("82473"))
        )

        assert reconciled.amount == Decimal("325620")
        real_stated_grand_total = Decimal("324275")
        gap = abs(reconciled.amount - real_stated_grand_total)
        assert gap <= real_stated_grand_total * Decimal("0.01")  # within 1% tolerance

    def test_no_excluded_total_leaves_behavior_unchanged(
        self, service: InvoiceCalculationService
    ) -> None:
        invoice = _make_invoice(_make_item("5", "11429", TaxType.REDUCED))

        with_none = service.calculate_reconciled_grand_total(
            invoice, excluded_supplement_total=None
        )
        without_arg = service.calculate_reconciled_grand_total(invoice)

        assert with_none == without_arg

    def test_mismatched_excluded_total_currency_raises(
        self, service: InvoiceCalculationService
    ) -> None:
        invoice = _make_invoice(_make_item("1", "1000", TaxType.REDUCED))

        with pytest.raises(ValidationError):
            service.calculate_reconciled_grand_total(
                invoice, excluded_supplement_total=Money(Decimal("100"), currency="USD")
            )
