"""
Unit tests for domain.enums.invoice_status.InvoiceStatus.is_terminal and
domain.constants.VALID_STATUS_TRANSITIONS, focused on
IMPORTED_NEEDS_MANUAL_LINE (Deviation D11, PO-confirmed 2026-08): a
fill_and_save_invoice run that saved the invoice with 1+ line(s) skipped
for a genuine medicine-resolution failure lands here instead of IMPORTED,
and must never be auto-reprocessed (re-running would create a duplicate
invoice on the real site).
"""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.domain.constants import VALID_STATUS_TRANSITIONS
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus

pytestmark = pytest.mark.unit


class TestImportedNeedsManualLineTerminality:
    def test_is_terminal(self) -> None:
        assert InvoiceStatus.IMPORTED_NEEDS_MANUAL_LINE.is_terminal is True

    def test_imported_is_still_terminal_too(self) -> None:
        # is_terminal used to be a single-value check -- confirm broadening
        # it to "in (...)" did not accidentally drop IMPORTED itself.
        assert InvoiceStatus.IMPORTED.is_terminal is True

    def test_no_outgoing_transitions_allowed(self) -> None:
        assert VALID_STATUS_TRANSITIONS[InvoiceStatus.IMPORTED_NEEDS_MANUAL_LINE] == frozenset()

    def test_reachable_from_import_in_progress(self) -> None:
        assert (
            InvoiceStatus.IMPORTED_NEEDS_MANUAL_LINE
            in VALID_STATUS_TRANSITIONS[InvoiceStatus.IMPORT_IN_PROGRESS]
        )

    def test_import_in_progress_can_still_reach_the_two_original_statuses(self) -> None:
        # Adding the new status must not have replaced the existing ones.
        allowed = VALID_STATUS_TRANSITIONS[InvoiceStatus.IMPORT_IN_PROGRESS]
        assert InvoiceStatus.IMPORTED in allowed
        assert InvoiceStatus.IMPORT_FAILED in allowed

    @pytest.mark.parametrize(
        "status",
        [s for s in InvoiceStatus if s is not InvoiceStatus.IMPORT_IN_PROGRESS],
    )
    def test_not_reachable_from_any_other_status(self, status: InvoiceStatus) -> None:
        assert InvoiceStatus.IMPORTED_NEEDS_MANUAL_LINE not in VALID_STATUS_TRANSITIONS.get(
            status, frozenset()
        )
