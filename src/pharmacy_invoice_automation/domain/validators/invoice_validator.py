"""
Validator: InvoiceValidator.

Reusable business validator for PurchaseInvoice completeness --
distinct from the invariants PurchaseInvoice.__post_init__ already
enforces at construction time. This validator answers a different
question: "is this invoice, as it stands right now, ready to advance
toward ReadyForImport?" (FR-05 review gate).
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.shared_interfaces.identifiable import ids_are_unique
from pharmacy_invoice_automation.shared.result import Result


@dataclass(frozen=True)
class InvoiceValidationReport:
    """Every issue found while validating a PurchaseInvoice, if any."""

    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """True if no issues were found."""
        return len(self.issues) == 0


class InvoiceValidator:
    """Validates whether a PurchaseInvoice is complete enough to proceed."""

    def validate(self, invoice: PurchaseInvoice) -> Result[InvoiceValidationReport]:
        """
        Check ``invoice`` for every completeness requirement FR-05
        implies before review can hand it off for import: at least one
        item, a resolved supplier, and no duplicate item ids.

        STRATEGY CHANGE (2026-08, PO decision, explicit Domain change --
        approved despite Domain otherwise being frozen/under audit):
        this used to also require every item's
        ``retail_units_per_purchase_unit`` to be resolved, since
        automation (infrastructure.automation.playwright_adapter)
        converted quantity/price through that ratio before filling
        anything on-site. Automation no longer does that at all -- it
        now verifies the site's own displayed unit against the
        invoice's own ``item.unit`` directly, for real, right before
        filling (see PlaywrightBrowserAutomationProvider.
        _verify_unit_matches_invoice's own docstring). That gate
        existed ONLY to protect the now-abandoned conversion design;
        keeping it would incorrectly block real invoices on data
        automation no longer needs, so it is removed here rather than
        left stale. ``retail_units_per_purchase_unit`` itself is left
        alone everywhere else (Medicine/PurchaseItem fields, learn-once
        pipeline in pipeline.party_matching_step.PartyMatchingStep) --
        this is the removal of a now-incorrect BLOCKING requirement,
        not a removal of the underlying data/feature.
        """
        issues: list[str] = []

        if not invoice.items:
            issues.append("Invoice has no purchase items.")

        if not invoice.supplier_id:
            issues.append("Invoice has no resolved supplier.")

        if not ids_are_unique(invoice.items):
            issues.append("Invoice has two or more purchase items sharing the same id.")

        for item in invoice.items:
            if item.medicine_id is None:
                issues.append(
                    f"Purchase item '{item.medicine_name}' has not been resolved to a "
                    f"catalog medicine."
                )
            if item.unit.requires_manual_confirmation:
                issues.append(
                    f"Purchase item '{item.medicine_name}' has an unrecognized unit "
                    f"and needs manual confirmation."
                )

        return Result.success(InvoiceValidationReport(issues=tuple(issues)))
