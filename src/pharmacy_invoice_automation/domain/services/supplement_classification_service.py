"""
Domain Service: SupplementClassificationService.

Identifies purchase-invoice line items that are functional foods /
dietary supplements (thuc pham chuc nang) rather than an officially
registered medicine -- kept as a Domain Service rather than a method on
PurchaseItem, matching services.medicine_validation_service's own
rationale: this encodes a business classification rule, not an entity
invariant.

Business rule (Product Owner-confirmed, 2026-08 -- REPLACES the prior
medicine-name-keyword heuristic entirely, per an explicit correction):
VAT is the ONLY classification criterion.

- VAT = 5% (TaxType.REDUCED) -- a genuine, officially registered
  medicine. Kept.
- VAT != 5% (10%, 0%, or any other rate) -- no official medicine
  registration. Automatically excluded from the invoice, logged as an
  informational note, never blocks approval or forces manual review --
  see application.pipeline.party_matching_step, which already
  distinguishes blocking ``issues`` from informational ``notes`` for
  exactly this kind of routine, automatic decision.
- VAT could not be read at all (None) -- this is NOT "assume
  supplement" and NOT "assume medicine." Routed to the Human Review
  Queue via a blocking ``issue``, the same pattern every other
  genuinely uncertain case in this pipeline already follows (Stage 05:
  "Do NOT automatically approve uncertain data").
"""

from __future__ import annotations

from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.shared.result import Result

_REGISTERED_MEDICINE_TAX_TYPE = TaxType.REDUCED  # 5% -- the registered-medicine VAT rate


class SupplementClassificationService:
    """Recognizes supplement/non-medicine line items purely from VAT category."""

    def is_supplement(self, tax_type: TaxType | None) -> Result[bool]:
        """
        Result.success(True) if ``tax_type`` is present and is not the
        5% registered-medicine rate (no official medicine registration
        -- treat as supplement/non-medicine).

        Result.success(False) if ``tax_type`` is exactly the 5% rate
        (a genuine, registered medicine).

        Result.failure(...) if ``tax_type`` is None -- VAT was not
        read for this line. Never guessed as either outcome; the
        caller is expected to route this to human review, not to
        silently keep or silently exclude the line.
        """
        if tax_type is None:
            return Result.failure(
                "VAT not read for this line; cannot determine whether it is a "
                "registered medicine (requires 5% VAT) or not. Needs manual confirmation."
            )
        return Result.success(tax_type is not _REGISTERED_MEDICINE_TAX_TYPE)
