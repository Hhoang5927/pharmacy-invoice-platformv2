"""
Unit tests for domain.validators.invoice_validator.InvoiceValidator,
focused on Part 3's additive per-item packaging-ratio check -- the gate
that keeps an invoice out of ReadyForImport until every item's
retail_units_per_purchase_unit is resolved (by
pipeline.party_matching_step.PartyMatchingStep or a reviewer via
use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase).
Pre-existing checks are covered lightly, for context, not exhaustively.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

pytestmark = pytest.mark.unit


def _make_item(**overrides: object) -> PurchaseItem:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "medicine_name": "Paracetamol 500mg",
        "unit": Unit(code="hop"),
        "quantity": Quantity(Decimal("10")),
        "unit_price": Money(Decimal("100000")),
        "medicine_id": "med-1",
        "retail_units_per_purchase_unit": 10,
    }
    defaults.update(overrides)
    return PurchaseItem(**defaults)  # type: ignore[arg-type]


def _make_invoice(*items: PurchaseItem, supplier_id: str | None = "sup-1") -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        id=str(uuid.uuid4()),
        project_id="proj-1",
        invoice_number="INV-001",
        invoice_date=date.today(),
        supplier_id=supplier_id,
    )
    for item in items:
        invoice.add_item(item)
    return invoice


@pytest.fixture()
def validator() -> InvoiceValidator:
    return InvoiceValidator()


class TestPackagingRatioCheck:
    def test_fully_resolved_item_has_no_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice(_make_item())

        report = validator.validate(invoice).unwrap()

        assert report.is_valid

    def test_unresolved_packaging_ratio_is_an_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice(_make_item(retail_units_per_purchase_unit=None))

        report = validator.validate(invoice).unwrap()

        assert not report.is_valid
        assert any("packaging ratio" in issue.lower() for issue in report.issues)

    def test_vien_item_resolved_to_one_has_no_issue(self, validator: InvoiceValidator) -> None:
        # PartyMatchingStep resolves an already-Vien item's ratio to 1
        # (no conversion needed) -- the validator must accept that, not
        # treat 1 as somehow suspicious.
        invoice = _make_invoice(
            _make_item(unit=Unit(code="vien"), retail_units_per_purchase_unit=1)
        )

        report = validator.validate(invoice).unwrap()

        assert report.is_valid


class TestPreExistingChecksStillWork:
    def test_no_items_is_an_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice()

        report = validator.validate(invoice).unwrap()

        assert not report.is_valid
        assert any("no purchase items" in issue.lower() for issue in report.issues)

    def test_no_supplier_is_an_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice(_make_item(), supplier_id=None)

        report = validator.validate(invoice).unwrap()

        assert not report.is_valid
        assert any("supplier" in issue.lower() for issue in report.issues)

    def test_unresolved_medicine_id_is_an_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice(_make_item(medicine_id=None))

        report = validator.validate(invoice).unwrap()

        assert not report.is_valid
        assert any("catalog medicine" in issue.lower() for issue in report.issues)
