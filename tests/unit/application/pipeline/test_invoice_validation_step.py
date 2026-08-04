"""
Unit tests for application.pipeline.invoice_validation_step.InvoiceValidationStep,
focused on two fixes landing together (deliberately, per an explicit PO
decision not to fix one and leave the other half-done):

1. CKTM-aware total consistency: "Giam Tru CKTM" is a whole-invoice
   deduction, carried on PurchaseInvoice.commercial_discount_amount, and
   must be subtracted before comparing against the OCR'd stated grand
   total.
2. Tax-inclusive comparison (a separate, pre-existing bug): a real VAT
   invoice's stated grand total is always tax-INCLUSIVE, so it must be
   compared against InvoiceCalculationService.calculate_reconciled_grand_total
   (tax-inclusive), never the tax-exclusive item sum -- fixed together
   with Deviation D5's TaxType.EIGHT_PERCENT addition, since an invoice
   with 8% lines would still miscompute here even with only the
   tax-inclusive comparison fixed.

Pre-existing completeness checks (delegated to InvoiceValidator) are
not re-tested here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from pharmacy_invoice_automation.application.pipeline.invoice_validation_step import (
    InvoiceValidationStep,
)
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.services.invoice_calculation_service import (
    InvoiceCalculationService,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRResult
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
        medicine_id="med-1",
        retail_units_per_purchase_unit=1,
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
        supplier_id="sup-1",
        commercial_discount_amount=commercial_discount_amount,
    )
    for item in items:
        invoice.add_item(item)
    return invoice


def _make_ocr_result(raw_grand_total: Decimal | None) -> OCRResult:
    return OCRResult(
        status=OCRStatus.SUCCEEDED,
        raw_invoice_number="INV-001",
        raw_invoice_date=date.today(),
        raw_supplier_name="Traphaco",
        raw_supplier_tax_code=None,
        raw_supplier_address=None,
        raw_prescription_classification_text=None,
        raw_grand_total=raw_grand_total,
        lines=(),
        overall_confidence=0.95,
    )


@pytest.fixture()
def step() -> InvoiceValidationStep:
    return InvoiceValidationStep(
        invoice_validator=InvoiceValidator(),
        invoice_calculation_service=InvoiceCalculationService(),
        price_policy=PricePolicy(),
    )


class TestTaxInclusiveComparison:
    """
    The separate, pre-existing bug: comparing a tax-exclusive item sum
    against a tax-inclusive stated grand total. Real Traphaco line
    amounts (Slaska New, TS 8%: 76364 -> +6109 tax = 82473; Tra gung,
    TS 5%: 57145 -> +2857 tax = 60002); no CKTM discount in this class.
    """

    def test_tax_inclusive_stated_total_reconciles(self, step: InvoiceValidationStep) -> None:
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
        )
        ocr_result = _make_ocr_result(Decimal("142475"))  # 82473 + 60002

        issues = step.execute(invoice, ocr_result)

        assert not any("does not reconcile" in issue for issue in issues)

    def test_the_old_tax_exclusive_comparison_would_have_falsely_flagged_the_same_invoice(
        self, step: InvoiceValidationStep
    ) -> None:
        # Sanity check on the fixture: proves the "reconciles" result
        # above is really due to the tax-inclusive fix, not
        # coincidental tolerance slack -- the pre-tax sum (133509) is
        # nowhere near the tax-inclusive stated total (142475).
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
        )

        assert invoice.calculate_item_total_sum().amount == Decimal("133509")
        assert abs(Decimal("133509") - Decimal("142475")) > Decimal("142475") * Decimal("0.01")


class TestTotalConsistencyWithCommercialDiscount:
    def test_stated_total_reconciles_once_discount_is_deducted(
        self, step: InvoiceValidationStep
    ) -> None:
        # 82473 + 60002 = 142475 with tax; minus a 26855 CKTM discount
        # (pre-tax) = 115620.
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
            commercial_discount_amount=Money(Decimal("26855")),
        )
        ocr_result = _make_ocr_result(Decimal("115620"))

        issues = step.execute(invoice, ocr_result)

        assert not any("does not reconcile" in issue for issue in issues)

    def test_without_the_discount_deduction_the_same_totals_would_have_falsely_mismatched(
        self, step: InvoiceValidationStep
    ) -> None:
        invoice_without_discount = _make_invoice(
            _make_item("2", "38182", TaxType.EIGHT_PERCENT),
            _make_item("5", "11429", TaxType.REDUCED),
        )
        ocr_result = _make_ocr_result(Decimal("115620"))

        issues = step.execute(invoice_without_discount, ocr_result)

        assert any("does not reconcile" in issue for issue in issues)

    def test_discount_exceeding_grand_total_is_reported_as_its_own_issue(
        self, step: InvoiceValidationStep
    ) -> None:
        invoice = _make_invoice(
            _make_item("1", "1000", TaxType.STANDARD),
            commercial_discount_amount=Money(Decimal("999999")),
        )
        ocr_result = _make_ocr_result(Decimal("0"))

        issues = step.execute(invoice, ocr_result)

        assert any("exceeds" in issue.lower() for issue in issues)

    def test_no_discount_and_matching_tax_inclusive_total_is_still_fine(
        self, step: InvoiceValidationStep
    ) -> None:
        invoice = _make_invoice(_make_item("2", "38182", TaxType.REDUCED))
        ocr_result = _make_ocr_result(Decimal("80182"))  # 76364 + 5% tax (3818, rounded)

        issues = step.execute(invoice, ocr_result)

        assert not any("does not reconcile" in issue for issue in issues)

    def test_no_stated_grand_total_skips_the_check_entirely(
        self, step: InvoiceValidationStep
    ) -> None:
        invoice = _make_invoice(
            _make_item("2", "38182", TaxType.STANDARD),
            commercial_discount_amount=Money(Decimal("999999")),
        )
        ocr_result = _make_ocr_result(None)

        issues = step.execute(invoice, ocr_result)

        assert not any("reconcile" in issue or "exceeds" in issue.lower() for issue in issues)


class TestExcludedSupplementTotalAdjustment:
    """
    Deviation D10 fix (PO-confirmed 2026-08, final -- no exceptions):
    pipeline.party_matching_step.PartyMatchingStep has already removed
    any VAT!=5% line from invoice.items by the time this step runs
    (ProcessInvoiceUseCase's real step order) -- correct, deliberate
    filtering, never itself a reason to report "does not reconcile."
    """

    def test_reconciles_once_the_excluded_lines_value_is_added_back(
        self, step: InvoiceValidationStep
    ) -> None:
        # Only the kept (TS 5%) line remains on invoice.items -- Slaska
        # New (TS 8%, 82473 with tax) has already been removed by
        # PartyMatchingStep. The stated total still reflects the WHOLE
        # original invoice, so it only reconciles once that value is
        # passed through and added back.
        invoice = _make_invoice(_make_item("5", "11429", TaxType.REDUCED))
        ocr_result = _make_ocr_result(Decimal("142475"))  # 60002 (kept) + 82473 (excluded)

        issues = step.execute(invoice, ocr_result, Money(Decimal("82473")))

        assert not any("does not reconcile" in issue for issue in issues)

    def test_without_the_adjustment_the_same_totals_would_have_falsely_mismatched(
        self, step: InvoiceValidationStep
    ) -> None:
        invoice = _make_invoice(_make_item("5", "11429", TaxType.REDUCED))
        ocr_result = _make_ocr_result(Decimal("142475"))

        issues = step.execute(invoice, ocr_result)  # no excluded_supplement_total passed

        assert any("does not reconcile" in issue for issue in issues)

    def test_runs_the_check_even_with_zero_remaining_items_if_something_was_excluded(
        self, step: InvoiceValidationStep
    ) -> None:
        # Every real line on this invoice happened to be VAT != 5% --
        # invoice.items is empty, but the check must still run against
        # excluded_supplement_total rather than being silently skipped.
        invoice = _make_invoice()
        ocr_result = _make_ocr_result(Decimal("82473"))

        issues = step.execute(invoice, ocr_result, Money(Decimal("82473")))

        assert not any("does not reconcile" in issue for issue in issues)

    def test_a_real_unexplained_mismatch_still_gets_reported(
        self, step: InvoiceValidationStep
    ) -> None:
        # A genuine data problem -- neither CKTM nor the VAT-based
        # exclusion explains this gap -- must still surface normally.
        invoice = _make_invoice(_make_item("5", "11429", TaxType.REDUCED))
        ocr_result = _make_ocr_result(Decimal("999999"))

        issues = step.execute(invoice, ocr_result, Money(Decimal("82473")))

        assert any("does not reconcile" in issue for issue in issues)
