"""
Unit tests for domain.validators.invoice_validator.InvoiceValidator.

STRATEGY CHANGE (2026-08, PO decision, explicit Domain change): this
file used to focus on Part 3's additive per-item packaging-ratio check
-- a gate that kept an invoice out of ReadyForImport until every
item's retail_units_per_purchase_unit was resolved. That gate existed
only to protect the Vien retail-unit-conversion design automation used
to rely on; automation no longer converts through this ratio at all
(it verifies the site's own displayed unit against the invoice's own
item.unit directly instead -- see
infrastructure.automation.playwright_adapter.PlaywrightBrowserAutomationProvider.
_verify_unit_matches_invoice's own docstring), so keeping the gate
would incorrectly block real invoices on data automation no longer
needs. The check itself was removed from InvoiceValidator.validate();
TestPackagingRatioCheckRemoved below proves it no longer blocks.
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


class TestPackagingRatioCheckRemoved:
    """
    STRATEGY CHANGE (2026-08): a resolved packaging ratio is no longer
    required for an invoice to validate -- these tests replace the old
    TestPackagingRatioCheck class, which asserted the opposite.
    """

    def test_fully_resolved_item_has_no_issue(self, validator: InvoiceValidator) -> None:
        invoice = _make_invoice(_make_item())

        report = validator.validate(invoice).unwrap()

        assert report.is_valid

    def test_unresolved_packaging_ratio_is_no_longer_an_issue(
        self, validator: InvoiceValidator
    ) -> None:
        invoice = _make_invoice(_make_item(retail_units_per_purchase_unit=None))

        report = validator.validate(invoice).unwrap()

        assert report.is_valid
        assert not any("packaging ratio" in issue.lower() for issue in report.issues)

    def test_vien_item_resolved_to_one_has_no_issue(self, validator: InvoiceValidator) -> None:
        # PartyMatchingStep still resolves an already-Vien item's ratio
        # to 1 (no conversion needed, unrelated to this strategy
        # change) -- the validator must still accept that.
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
