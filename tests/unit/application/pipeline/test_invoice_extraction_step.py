"""
Unit tests for application.pipeline.invoice_extraction_step.InvoiceExtractionStep,
focused on Part 3's carry-through of OCRLineItem.raw_retail_units_per_purchase_unit
and Part 3.1's raw_vat_percentage -> TaxType mapping onto the
newly-built PurchaseItem. Not a full re-test of the whole step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from pharmacy_invoice_automation.application.configuration import RetryPolicy
from pharmacy_invoice_automation.application.pipeline.invoice_extraction_step import (
    InvoiceExtractionStep,
)
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.ocr_status import OCRStatus
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.domain.value_objects.ocr_result import OCRLineItem, OCRResult

pytestmark = pytest.mark.unit


@dataclass
class _StubOCRProvider(OCRProvider):
    result: OCRResult

    def extract(self, image_bytes: bytes) -> OCRResult:
        return self.result


def _make_line(**overrides: object) -> OCRLineItem:
    defaults: dict[str, object] = {
        "raw_medicine_name": "Paracetamol 500mg",
        "raw_batch_number": None,
        "raw_expiry_date": None,
        "raw_unit_text": "hop",
        "raw_quantity": Decimal("10"),
        "raw_unit_price": Decimal("100000"),
        "raw_line_total": None,
    }
    defaults.update(overrides)
    return OCRLineItem(**defaults)  # type: ignore[arg-type]


def _make_result(*lines: OCRLineItem, **overrides: object) -> OCRResult:
    defaults: dict[str, object] = {
        "status": OCRStatus.SUCCEEDED,
        "raw_invoice_number": "INV-001",
        "raw_invoice_date": date.today(),
        "raw_supplier_name": "Cong ty Duoc ABC",
        "raw_supplier_tax_code": None,
        "raw_supplier_address": None,
        "raw_prescription_classification_text": None,
        "raw_grand_total": None,
        "lines": lines,
        "overall_confidence": 0.95,
    }
    defaults.update(overrides)
    return OCRResult(**defaults)  # type: ignore[arg-type]


def _make_invoice() -> PurchaseInvoice:
    return PurchaseInvoice(
        id="inv-1", project_id="proj-1", invoice_number="PENDING", invoice_date=date.today()
    )


class TestPackagingRatioCarryThrough:
    def test_ocr_reading_is_copied_onto_the_new_item(self) -> None:
        line = _make_line(raw_retail_units_per_purchase_unit=100)
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(_make_result(line)), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        step.execute(invoice, image_bytes=b"fake")

        assert invoice.items[0].retail_units_per_purchase_unit == 100

    def test_absent_ocr_reading_leaves_the_field_none(self) -> None:
        line = _make_line(raw_retail_units_per_purchase_unit=None)
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(_make_result(line)), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        step.execute(invoice, image_bytes=b"fake")

        assert invoice.items[0].retail_units_per_purchase_unit is None


class TestVatPercentageMapping:
    """Part 3.1 (PO-confirmed 2026-08): raw_vat_percentage -> TaxType."""

    @pytest.mark.parametrize(
        ("raw_vat_percentage", "expected_tax_type"),
        [
            (Decimal("5"), TaxType.REDUCED),
            (Decimal("5.00"), TaxType.REDUCED),
            (Decimal("10"), TaxType.STANDARD),
            (Decimal("0"), TaxType.EXEMPT),
            (Decimal("8"), TaxType.EIGHT_PERCENT),  # Deviation D5 fix (PO-confirmed 2026-08)
        ],
    )
    def test_read_vat_percentage_maps_to_the_right_tax_type(
        self, raw_vat_percentage: Decimal, expected_tax_type: TaxType
    ) -> None:
        line = _make_line(raw_vat_percentage=raw_vat_percentage)
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(_make_result(line)), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        step.execute(invoice, image_bytes=b"fake")

        assert invoice.items[0].tax_type is expected_tax_type

    def test_unread_vat_leaves_tax_type_none_not_a_guess(self) -> None:
        line = _make_line(raw_vat_percentage=None)
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(_make_result(line)), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        step.execute(invoice, image_bytes=b"fake")

        assert invoice.items[0].tax_type is None


class TestCommercialDiscountCarryThrough:
    """
    Revised understanding (supersedes the earlier, retracted approach of
    treating 'Giam Tru CKTM' as a per-item discount): it is a deduction
    against the WHOLE invoice, carried on OCRResult itself (never as an
    OCRLineItem), and must land on PurchaseInvoice.commercial_discount_amount
    -- never on any PurchaseItem, and never as an entry in invoice.items.
    """

    def test_read_discount_is_copied_onto_the_invoice(self) -> None:
        line = _make_line()
        result = _make_result(line, raw_commercial_discount_amount=Decimal("26855"))
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(result), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        step.execute(invoice, image_bytes=b"fake")

        assert invoice.commercial_discount_amount is not None
        assert invoice.commercial_discount_amount.amount == Decimal("26855")
        # The one real medicine line is still the only PurchaseItem --
        # the discount never becomes (or is folded into) a line item.
        assert len(invoice.items) == 1
        assert invoice.items[0].medicine_name == "Paracetamol 500mg"

    def test_absent_discount_leaves_the_field_none(self) -> None:
        line = _make_line()
        result = _make_result(line, raw_commercial_discount_amount=None)
        step = InvoiceExtractionStep(
            ocr_provider=_StubOCRProvider(result), retry_policy=RetryPolicy()
        )
        invoice = _make_invoice()

        outcome = step.execute(invoice, image_bytes=b"fake")

        assert invoice.commercial_discount_amount is None
        # Most invoices have no CKTM row at all -- that must not be
        # reported as an extraction issue.
        assert not any("discount" in issue.lower() for issue in outcome.issues)
