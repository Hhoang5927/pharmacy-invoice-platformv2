"""
Implements BrowserAutomationProvider against Playwright for
webnhathuoc.com: Login, Open Import Invoice, Create/Select Supplier,
Create/Select Medicine, Fill & Save Invoice.

No selector is ever hardcoded here -- every locator is looked up from a
SelectorRegistry (infrastructure.automation.selector_registry) by its
logical key, via SelectorRegistry.require_usable(). A key whose status is
still 'needs_verification' raises SelectorNotUsableError rather than
guessing at a locator, per the project's "never fabricate, never guess"
rule -- the corresponding port method then reports a clean
AutomationOutcome(success=False, ...) (or, for the two bool-returning
lookup methods, propagates the error) instead of silently doing the wrong
thing against the live site.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from playwright.sync_api import Locator, Page, expect

from pharmacy_invoice_automation.application.exceptions import TransientInfrastructureError
from pharmacy_invoice_automation.domain.entities.batch import Batch
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.ports.repositories.batch_repository import (
    BatchRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    AutomationOutcome,
    BrowserAutomationProvider,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.value_objects.money import Money
from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
    AutomationError,
    SelectorNotUsableError,
    VerificationFailedError,
    wrap_playwright_error,
)
from pharmacy_invoice_automation.infrastructure.automation.selector_registry import (
    SelectorEntry,
    SelectorRegistry,
    SelectorRegistryError,
)


@dataclass(frozen=True)
class PlaywrightAutomationConfig:
    """
    Tunable knobs for PlaywrightBrowserAutomationProvider. Never
    hardcoded in this module -- populated by the Composition Root from
    ISettingsProvider/secrets storage, per the Business Rules
    Configuration section (thresholds, timeouts, credentials must all be
    externally configurable).
    """

    username: str
    password: str
    default_timeout_ms: int = 15_000
    # Part 3 of the multi-result-disambiguation feature (2026-08,
    # PO-approved): how long a run pauses for a human to manually resolve
    # an ambiguous medicine-name search result ("vài phút", PO's own
    # words) before failing cleanly instead of hanging forever. Externally
    # configurable per the Business Rules Configuration section -- see
    # AppSettings.automation_human_disambiguation_timeout_seconds.
    human_disambiguation_timeout_ms: int = 180_000


class PlaywrightBrowserAutomationProvider(BrowserAutomationProvider):
    """Drives webnhathuoc.com via Playwright, using an externalized SelectorRegistry."""

    def __init__(
        self,
        page: Page,
        registry: SelectorRegistry,
        config: PlaywrightAutomationConfig,
        logger: logging.Logger,
        batch_repository: BatchRepository | None = None,
        price_policy: PricePolicy | None = None,
        medicine_repository: MedicineRepository | None = None,
        supplier_repository: SupplierRepository | None = None,
    ) -> None:
        self._page = page
        self._registry = registry
        self._config = config
        self._logger = logger
        self._batch_repository = batch_repository
        self._medicine_repository = medicine_repository
        self._supplier_repository = supplier_repository
        # PricePolicy is a pure, stateless Domain service (no ports, no
        # I/O) -- defaulting it here is not hiding a real dependency the
        # way batch_repository would be.
        self._price_policy = price_policy or PricePolicy()
        self._page.set_default_timeout(config.default_timeout_ms)

    # --- BrowserAutomationProvider: session -----------------------------

    def is_session_valid(self) -> bool:
        entry = self._registry.get("login.session_indicator")
        if not entry.is_usable:
            # Conservative default: unlike a search result, "unknown"
            # here safely means "force a fresh login" -- never "assume
            # authenticated" for a check we cannot actually perform.
            self._logger.warning(
                "login.session_indicator is not usable (status=%s) -- cannot verify session, "
                "assuming invalid.",
                entry.status,
            )
            return False
        try:
            return self._locate(entry).count() > 0
        except Exception as exc:  # noqa: BLE001 -- a session probe must never crash the caller
            self._logger.debug("is_session_valid check raised %s; assuming invalid.", exc)
            return False

    def login(self) -> AutomationOutcome:
        def _do() -> None:
            self._goto("login.navigate")
            self._click("login.open_login_dialog_button")
            self._fill("login.username_field", self._config.username)
            self._fill("login.password_field", self._config.password)
            self._click("login.submit_button")
            # PO-confirmed (2026-08): a "Đóng" popup (CSDL DQG notice)
            # does not always appear after login -- best-effort only.
            # BUG FIX (2026-08, PO-confirmed via a real --dry-run run):
            # this was previously silent either way (login()'s own
            # "login succeeded" log covers this whole _do, so it gave
            # no visibility into whether the popup click itself ever
            # ran) -- a real run showed the popup still visible on
            # screen with no error logged anywhere. Logged explicitly
            # now so the next real run's own log makes clear whether
            # this actually clicked or never found anything to click.
            #
            # BUG FIX #2 (2026-08, PO-confirmed via the very next real
            # --dry-run run): that log itself then confirmed "not
            # present, skipped" -- CONFIRMING this is a genuine timing
            # issue (the popup renders too slowly for
            # _click_if_present's short, generic _OPTIONAL_CLICK_TIMEOUT_MS
            # to catch), not a selector problem. Uses
            # _click_if_eventually_visible (see its own docstring) --
            # the same expect()-based real-DOM polling
            # _wait_for_row_settled already established for this exact
            # class of "genuinely needs real, non-instant time" problem
            # -- with its own longer, dedicated timeout instead.
            popup_was_closed = self._click_if_eventually_visible(
                "login.close_notification_popup", self._LOGIN_POPUP_VISIBLE_TIMEOUT_MS
            )
            self._logger.info(
                "login.close_notification_popup: %s",
                "clicked (popup was present)" if popup_was_closed else "not present, skipped",
            )

        return self._run_outcome("login", _do)

    # --- BrowserAutomationProvider: open import invoice ------------------

    def open_import_invoice_form(self) -> AutomationOutcome:
        """
        Root cause found and fixed (PO-confirmed 2026-08, via a real
        screenshot of the live "Nhập Xuất" -> "Nhập hàng" flow): clicking
        "Nhập hàng" already lands directly on a fresh, ready-to-use
        "PHIẾU NHẬP HÀNG" (import invoice) form -- there is no third
        click needed or correct here. The former third click,
        open_import_invoice.add_new_button (get_by_title("Thêm mới").nth(2)),
        was landing on the WRONG one of the form's own three "Thêm mới"
        buttons (PO enumerated all three from the real screenshot: (1)
        add supplier, (2) add another line, (3) add a new medicine) --
        it was hitting (3), "Thêm mới thuốc", which is exactly
        #add-product-dialog. See open_import_invoice.add_new_button's
        own registry notes for the full analysis (including why the
        original 02_open_import_invoice.py recording may have needed
        this click on a since-changed or account-specific list view,
        unlike the direct-to-form landing confirmed now).
        """

        def _do() -> None:
            self._click("open_import_invoice.menu_button")
            self._click("open_import_invoice.submenu_link")
            self._fail_if_stray_add_product_dialog_present()

        return self._run_outcome("open_import_invoice_form", _do)

    def _fail_if_stray_add_product_dialog_present(self) -> None:
        """
        Defensive check (PO-confirmed 2026-08): kept as a genuine second
        line of defense even after the real root cause (an incorrect
        third click, see open_import_invoice_form's own docstring) was
        found and removed -- a real --dry-run run found
        #add-product-dialog ("Them moi thuoc") already open right after
        opening a freshly-created import invoice form, before any other
        interaction, blocking every subsequent click via intercepted
        pointer events. Fails cleanly with a clear, actionable message
        here instead of leaving automation to hang on the opaque
        pointer-event-blocked Playwright timeout this previously
        surfaced as several steps later, at an unrelated click.

        Deliberately does NOT attempt to click any close/cancel control
        inside this dialog -- no real DOM evidence names which specific
        element that is, and guessing risks submitting a real,
        unintended medicine-creation dialog on the live site.
        """
        entry = self._registry.require_usable("open_import_invoice.stray_add_product_dialog")
        if self._locate(entry).count() > 0:
            raise AutomationError(
                "#add-product-dialog is already open right after opening a freshly-created "
                "import invoice form -- refusing to guess how to dismiss it (no confirmed "
                "close-button selector exists yet). Close it manually on the real site, or "
                "provide its close-button selector so this can be automated safely."
            )

    # --- BrowserAutomationProvider: supplier -----------------------------

    def remove_default_supplier_tag(self) -> AutomationOutcome:
        """
        Bug fix (PO-confirmed 2026-08, a "forgot to wire it up" gap, not
        a new decision): supplier.default_tag_remove_button was already
        PO-confirmed required and present in the Selector Registry, but
        no orchestration call ever actually clicked it.
        composition_root.cli._resolve_supplier_on_site() must call this
        BEFORE search_supplier()/select_supplier()/create_supplier() on
        a freshly-opened invoice form. Best-effort (_click_if_present)
        since it is not confirmed the default tag always appears on
        every invoice form.
        """

        def _do() -> None:
            self._click_if_present("supplier.default_tag_remove_button")

        return self._run_outcome("remove_default_supplier_tag", _do)

    def search_supplier(self, name: str) -> bool:
        entry = self._registry.require_usable("supplier.search_input")
        try:
            self._locate(entry).fill(name)
            result_entry = self._registry.require_usable("supplier.search_result_option")
            return self._locate_parameterized(result_entry, name).count() > 0
        except SelectorRegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error("search_supplier", exc) from exc

    def select_supplier(self, name: str) -> AutomationOutcome:
        def _do() -> None:
            self._fill("supplier.search_input", name)
            self._click_parameterized("supplier.search_result_option", name)

        return self._run_outcome("select_supplier", _do)

    def create_supplier(self, supplier: Supplier) -> AutomationOutcome:
        def _do() -> None:
            self._click("supplier.add_new_trigger")
            self._fill("supplier.name_field", supplier.name)
            self._fill("supplier.phone_field", supplier.phone or "")
            self._fill("supplier.address_field", str(supplier.address) if supplier.address else "")
            self._fill(
                "supplier.tax_code_field", str(supplier.tax_code) if supplier.tax_code else ""
            )
            # supplier.barcode_field is deliberately never filled -- it is
            # auto-generated by the site (PO-confirmed). supplier.note_field
            # has no corresponding data on the Supplier entity today, so it
            # is left blank rather than filled with an invented value.
            self._click("supplier.submit_button")
            # Both confirmed (05_full_flow...py:34-35) but not evidenced
            # as always appearing (05a_...py's shorter recording skipped
            # them) -- best-effort only, matching login's popup handling.
            self._click_if_present("medicine.create_dialog_close_button")
            self._click_if_present("supplier.creation_confirmation_close_button")

        return self._run_outcome("create_supplier", _do)

    # --- BrowserAutomationProvider: medicine -------------------------------

    # Bug fix (2026-08, PO-confirmed via 3 real screenshots, root-caused
    # by hand on the live site): typing the FULL OCR string, name plus
    # its trailing packaging description in parentheses (e.g.
    # "Naphacogyl (Thùng x 300 hộp x 2 vỉ x 10 viên)"), into the site's
    # own medicine search box returns ZERO dropdown results -- typing
    # just "naphacogyl" returns real results, including the correct,
    # already-catalogued match. PurchaseItem.medicine_name/Medicine.name
    # conflate two different purposes (the string to search/select on
    # the web vs. the packaging description _convert_to_retail_units
    # elsewhere derives its Vien-conversion factor from) into one field
    # -- this strips the packaging part for web search/display use ONLY,
    # right before it is sent to the page; the original field is never
    # touched. PO also confirmed the earlier suspicion that
    # medicine.add_new_trigger itself was broken/misrouted was wrong --
    # that button opens the correct "Thêm mới thuốc" form fine when
    # clicked with an empty search box, so no change is made there.
    _PACKAGING_SUFFIX_PATTERN = re.compile(r"\s*\(.*$")

    @classmethod
    def _strip_packaging_description(cls, name: str) -> str:
        """Web search/display only -- never mutates the Domain-level name."""
        return cls._PACKAGING_SUFFIX_PATTERN.sub("", name).strip()

    def search_medicine(self, name: str) -> bool:
        """
        Bug fix (2026-08, PO-confirmed via a real --dry-run run --
        investigated, root-caused): a real run failed at
        create_medicine()'s own click:medicine.add_new_trigger with
        "not visible" (Playwright found the exact right element --
        this is not a wrong-element or genuinely-absent case) after
        create_medicine() ran for "Naphacogyl", an item PO suspected
        was already created on-site in an earlier run. cli.py's own
        _resolve_medicine_on_site was verified, by reading it directly,
        to ALREADY correctly gate create_medicine() behind
        search_medicine() returning False -- not the unconditional-
        click bug PO's own hypothesis first suspected. The real gap:
        this method checked .count() > 0 IMMEDIATELY after fill(), with
        NO settle time at all -- the exact same "genuinely needs real,
        non-instant time" class of problem already fixed twice
        elsewhere in this file (_wait_for_row_settled,
        _MEDICINE_SELECTION_SETTLE_MS in
        _search_and_select_medicine_for_line) -- a false negative here
        (site's search-as-you-type had not finished when checked) would
        make an ALREADY-existing medicine look "not found", triggering
        an unnecessary create_medicine() call whose own
        medicine.add_new_trigger click then found a real but not-
        actually-meant-to-be-used element. Reuses
        _MEDICINE_SELECTION_SETTLE_MS (2.5s, a fixed wait -- same
        reasoning as that constant's own comment: no confirmed
        selector exists yet for "search results settled" to poll
        against instead).

        FOLLOW-UP (2026-08, PO-confirmed via 3 real screenshots): the
        true root cause of that same incident was actually
        "Naphacogyl"'s full OCR name (with its trailing packaging
        description) returning ZERO real search results, not a broken
        add_new_trigger -- see _strip_packaging_description. PO
        separately confirmed clicking add_new_trigger with an empty
        search box opens the correct "Thêm mới thuốc" form fine, so
        that button itself is not at fault. Left OPEN: whether
        add_new_trigger behaves differently after a search that typed
        something and found zero results (the state this incident was
        actually in) versus a box that was never typed into at all --
        this fix should make that state unreachable for any medicine
        that already exists on-site, but a genuinely new, not-yet-
        catalogued medicine will still reach a real zero-result search
        before create_medicine() runs, so this distinction may matter
        again the next time that happens -- not re-investigated here
        since it could no longer be reproduced against real evidence.
        """
        search_name = self._strip_packaging_description(name)
        entry = self._registry.require_usable("medicine.search_input")
        try:
            self._locate(entry).fill(search_name)
            self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)
            result_entry = self._registry.require_usable("medicine.search_result_option")
            return self._locate_parameterized(result_entry, search_name).count() > 0
        except SelectorRegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error("search_medicine", exc) from exc

    def select_medicine(self, name: str) -> AutomationOutcome:
        def _do() -> None:
            search_name = self._strip_packaging_description(name)
            self._fill("medicine.search_input", search_name)
            self._click_parameterized("medicine.search_result_option", search_name)

        return self._run_outcome("select_medicine", _do)

    def create_medicine(self, medicine: Medicine) -> AutomationOutcome:
        def _do() -> None:
            self._click("medicine.add_new_trigger")

            # Selecting an existing "Nhom thuoc" group is the PRIMARY path
            # (PO decision, 2026-08): only 2 fixed groups exist system-wide
            # (prescription / over-the-counter), and this long-active
            # account almost certainly already has both, so create-if-
            # missing is a rare fallback not worth optimizing. Reuses the
            # ALREADY-confirmed display text from
            # value_mappings.medicine_group_display_label (the exact
            # string typed when a group is created) rather than the
            # never-confirmed raw option value -- select_option(label=...)
            # matches by visible option text, so no dependency on that raw
            # value is needed. If this group genuinely doesn't exist yet,
            # this call fails cleanly rather than guessing at the
            # create-dialog flow's applicability.
            self._select_option_by_domain_value(
                "medicine.group_select_existing",
                "medicine_group_display_label",
                medicine.medicine_type.value,
            )

            self._fill("medicine.code_field", medicine.medicine_code)
            self._click("medicine.submit_button")
            self._click("medicine.create_dialog_close_button")
            self._select_option_by_domain_value(
                "medicine.unit_dropdown", "unit_display_label", medicine.unit.code
            )
            self._fill("medicine.name_field", self._strip_packaging_description(medicine.name))
            # medicine.purchase_price_field / medicine.retail_price_field
            # ("Gia nhap le" / "Gia ban le") are evidenced as part of THIS
            # dialog (05_full_flow...py), but the Medicine entity this
            # method receives has no price field (price lives on
            # PurchaseItem.unit_price, one layer up) -- see this task's
            # report for the flagged port-signature gap. Not filled here
            # to avoid referencing data this method does not actually
            # have; not silently invented either.
            self._click("medicine.submit_button")

        return self._run_outcome("create_medicine", _do)

    # --- BrowserAutomationProvider: fill & save ----------------------------

    def fill_and_save_invoice(
        self, invoice: PurchaseInvoice, dry_run: bool = False
    ) -> AutomationOutcome:
        """
        Two-phase model (06_multi_line_items.py, PO-confirmed 2026-08,
        REPLACING the prior single-phase-per-line loop): during active
        fill, quantity/price/VAT (invoice_line.quantity_field/
        unit_price_field/vat_field) are ONE SHARED set, temporarily
        bound to whichever row was just added/selected, not one per
        row -- so filling them for one row before moving to the next
        (the prior implementation's assumption) does not match the
        real flow. Once a row is committed it also gets its own
        persistent copy of these fields, addressable via a confirmed
        row-position formula (table_structure.html, 2026-08; see
        _row_id_suffix/_fill_row_specific_field) -- not currently
        needed by this method since Phase 1 only ever touches the
        active row's shared fields.

        Phase 1 (search + quantity/price/VAT), once per line, in
        invoice order: search+select this line's medicine (see
        _search_and_select_medicine_for_line), fill the shared
        quantity/price/VAT set, then click invoice_line.add_row_button
        to confirm this line and advance -- revealing a fresh set for
        the next one.

        Phase 2 (batch/expiry), only after every line from Phase 1 is
        confirmed, only for lines that actually have a Batch: click
        that specific row's batch/expiry trigger (see
        _click_batch_edit_button_for_row -- table_structure.html,
        PO-confirmed 2026-08: the trigger is visually IDENTICAL on
        every row, distinguishable only by which <tbody> it lives in),
        fill the shared batch/expiry set (it "attaches" itself to
        whichever row's trigger was just clicked), then click
        invoice_line.confirm_row_button.

        Composition Root Stage D (PO-confirmed 2026-08): ``dry_run``
        stops right before the FIRST "Ghi Phieu" click -- the real
        commit point (invoice.save_success_indicator only appears after
        it, and nothing before it is a genuine site-side save). Phases
        1 and 2 above, and the medicine search/select/fill they involve,
        still run for real either way; only the save itself, and the
        post-save retail-price-update flow that depends on it, are
        skipped when dry_run is True.

        Whole-invoice commercial discount (PO-confirmed 2026-08): when
        ``invoice.commercial_discount_amount`` is set (a CKTM-style
        deduction against the whole invoice, never any one item), this
        is filled into invoice.commercial_discount_field right before
        the first "Ghi Phieu" click -- after both phases above, but
        BEFORE the dry_run short-circuit, since it is a fill like Phases
        1/2, not the save itself. That selector is still
        'needs_verification' as of this writing, so today this always
        raises SelectorRegistryError (surfaced by _run_outcome as a
        clean AutomationOutcome(success=False, ...)) whenever a
        discount is actually present -- never silently skipped, per the
        project's "never guess, fail clean" rule. When
        commercial_discount_amount is None (no CKTM on this invoice),
        this step is skipped entirely and does not affect the flow.

        BUG FIX (2026-08, PO-confirmed via a real --dry-run run):
        invoice.number_field/invoice.date_field were registered
        ('confirmed', 05_full_flow...py:47-50) but never actually
        called here -- the exact same "forgot to wire it up" gap
        previously found for remove_default_supplier_tag. Filled once,
        for real, before Phase 1 -- matching the real recording's own
        order (right after supplier resolution, before the first
        medicine search). invoice.date_field's own registry notes still
        flag an open question (never independently confirmed) about
        whether this plain textbox fill is sufficient for the real site
        to register the date, versus requiring the calendar-widget
        interaction the same recording also shows nearby for a
        DIFFERENT field -- unresolved by this fix, left for the next
        real --dry-run run to confirm/refute, same as the
        login.close_notification_popup timing question.

        BUG FIX #3 (2026-08, PO-confirmed via the very next real
        --dry-run run, then FULLY RESOLVED across 2 more real
        investigations -- CRITICAL, WRONG DATE on a real invoice): that
        run confirmed the OPEN QUESTION above the hard way -- fill()
        produced a visibly WRONG date on the real site (e.g.
        "19/01/2024" instead of the invoice's real date), not merely a
        rejected/ignored one. PO then personally confirmed clicking the
        "Ngày hóa đơn" textbox directly does not even open its calendar
        -- it is display-only, bound to a separate bootstrap-datepicker
        triggered by invoice.date_calendar_trigger (a real, confirmed
        calendar-icon button). _fill_invoice_date_and_verify (see its
        own docstring) now navigates that calendar (year -> month ->
        day, see _select_invoice_date_via_calendar) instead of filling
        the textbox directly, and still reads the field back afterward,
        raising VerificationFailedError -- refusing to continue -- if
        it does not show exactly the expected date, so a wrong date can
        never silently reach a real "Ghi Phieu" save.

        BUG FIX #4 (2026-08, PO-confirmed via the same real --dry-run
        run): that run's own site error, "Hãy chọn thuốc để thêm vào
        phiếu" (rejecting add_row_button), on a line whose medicine-
        search-result click had already resolved and clicked with no
        Playwright-visible error, proved the same "genuinely needs
        real, non-instant time" class of problem BUG FIX #2 above
        already fixed for add_row_button -- ALSO applies to the medicine
        SELECTION step itself, one step earlier. See
        _search_and_select_medicine_for_line's own
        _MEDICINE_SELECTION_SETTLE_MS comment for why this is a fixed
        wait (PO's own explicit fallback), not a poll-until-certain
        check like _wait_for_row_settled's -- no confirmed selector
        exists yet for this row's own "Đơn vị" display to poll against.

        BUG FIX #2 (2026-08, PO-confirmed via real hands-on inspection
        of a live --dry-run run -- CRITICAL, silent data loss): PO's own
        manual (slow) re-selection of a search result populated
        invoice_line.unit_price_field's sibling "Đơn vị" display
        correctly, proving Angular needs a real, non-instant amount of
        time after a medicine-search-result click to finish binding
        that row's state -- automation was clicking
        invoice_line.add_row_button immediately after, with NO
        verification that the row actually settled first. PO's own
        hands-on inspection then found only 1 real row on a 3-item
        invoice where every step had logged "succeeded" -- table_structure.html's
        already-confirmed real fact (each SETTLED row is genuinely its
        own <tbody>; an actively-editing row shares the same shared,
        unsuffixed fields as every other not-yet-settled row) means
        clicking add_row_button before the just-filled row's own
        <tbody> exists yet does not "fail" in any way Playwright can
        see -- the NEXT line's fields simply get typed into that same
        still-active, not-yet-settled shared field set, silently
        overwriting the previous line's in-flight row instead of
        creating a new one. _wait_for_row_settled (see its own
        docstring) closes this gap: after each add_row_button click,
        real page.locator("tbody") count is polled (Playwright's own
        expect().to_have_count(), not a fixed sleep) until it reaches
        this line's expected row count, raising a clear
        VerificationFailedError -- never silently continuing -- if it
        never does.
        """

        def _do() -> None:
            self._fill("invoice.number_field", invoice.invoice_number)
            self._fill_invoice_date_and_verify(invoice.invoice_date)
            supplier = self._resolve_invoice_supplier(invoice)

            for index, item in enumerate(invoice.items):
                self._search_and_select_medicine_for_line(item, index, supplier)
                retail_quantity, retail_unit_price = self._convert_to_retail_units(item)
                self._fill("invoice_line.quantity_field", str(retail_quantity))
                self._fill("invoice_line.unit_price_field", str(retail_unit_price.amount))
                if item.tax_type is not None:
                    self._fill("invoice_line.vat_field", item.tax_type.value)
                self._click("invoice_line.add_row_button")
                self._wait_for_row_settled(index + 1)

            for index, item in enumerate(invoice.items):
                if item.batch_id is None:
                    continue
                self._click_batch_edit_button_for_row(index + 1)
                batch = self._resolve_batch(item.batch_id)
                self._fill("invoice_line.batch_number_field", batch.batch_number)
                self._fill("invoice_line.expiry_date_field", str(batch.expiry_date))
                self._click("invoice_line.confirm_row_button")

            if invoice.commercial_discount_amount is not None:
                self._fill(
                    "invoice.commercial_discount_field",
                    str(invoice.commercial_discount_amount.amount),
                )

            if dry_run:
                self._logger.info(
                    "fill_and_save_invoice: dry_run=True -- every field filled for real, "
                    "but 'Ghi Phieu' was never clicked. Nothing was saved."
                )
                return

            self._click("invoice.save_button")
            self._verify_saved()

            # "Gia ban le" is a Medicine-level price, not a per-line one --
            # confirmed (05_full_flow...py:146-151) only reachable via an
            # edit flow AFTER the first save. Nothing to update on an
            # empty invoice.
            if invoice.items:
                self._update_retail_prices_after_save(invoice)
                self._click("invoice.save_button")
                self._verify_saved()

        return self._run_outcome("fill_and_save_invoice", _do)

    # Bug fix (2026-08, PO-confirmed via a real --dry-run run): a real
    # "Hãy chọn thuốc để thêm vào phiếu" site error (rejecting
    # add_row_button) on a line whose medicine.search_result_option
    # click had already resolved and clicked without any Playwright
    # error, proved the site needs real, non-instant time to actually
    # process a medicine selection -- clicking add_row_button
    # immediately after can run before that finishes. No confirmed
    # selector exists yet for the invoice line's own "Đơn vị" display
    # (checked: every real recording's only "Đơn vị"-labeled field is
    # inside the SEPARATE medicine-creation dialog, "Đơn vị xuất lẻ",
    # not this row's own auto-populated display) -- a poll-until-
    # populated check like _wait_for_row_settled's would need that
    # selector first. Per the PO's own explicit fallback: a fixed wait
    # instead, until real DOM evidence for that selector exists to
    # upgrade this to a proper poll.
    _MEDICINE_SELECTION_SETTLE_MS = 2_500

    def _search_and_select_medicine_for_line(
        self, item: PurchaseItem, index: int, supplier: Supplier | None = None
    ) -> None:
        """
        Phase 1's medicine search+select (06_multi_line_items.py,
        PO-confirmed 2026-08): the FIRST line item on a fresh invoice
        uses a different search-input locator (medicine.search_input)
        than every line item after it
        (invoice_line.subsequent_row_medicine_search_input) -- both
        feed the same medicine.search_result_option result list. Not
        exposed as the public select_medicine()/search_medicine() port
        methods: those assume a single, page-level search input and
        have no way to express "which line item" -- this per-line
        variant is specific to fill_and_save_invoice's own loop.

        BUG FIX (2026-08, PO-confirmed, see _MEDICINE_SELECTION_SETTLE_MS's
        own comment): waits _MEDICINE_SELECTION_SETTLE_MS after the
        result click, a real Playwright wait (not a blocking Python
        sleep), before returning control to the caller to fill
        quantity/price/VAT and click add_row_button -- a STOPGAP, lower-
        confidence fix compared to _wait_for_row_settled's poll-until-
        certain approach, since no confirmed selector exists yet for
        this row's own "Đơn vị" display to poll against instead.

        MERGED (2026-08, PO-confirmed via direct real-time observation
        of a dry-run): resolving/creating a missing medicine used to be
        a SEPARATE pre-pass over every line item
        (composition_root.cli._resolve_medicine_on_site, now removed),
        run entirely BEFORE this method ever ran for any item -- typing
        all 3 line items' names into the search box back-to-back with
        no selection/commit in between. PO observed this directly during
        a real dry-run (search box cycling through all 3 names, no
        "fill_and_save_invoice" log line, before a real add_new_trigger
        failure) and confirmed the real site's own workflow is "resolve
        THIS medicine fully (search, create if missing, select), fill
        its qty/price/VAT, confirm the row -- only then move to the
        next medicine", never a separate probe-everything-first pass.
        This method now owns that whole per-line resolution: it fills
        THIS row's own search box exactly once (see the index-aware
        search_key above -- reusing the generic, non-index-aware
        search_medicine() port method here would have refilled the
        WRONG box for every item after the first, since that method
        only knows about the row-0 locator), and only falls back to
        create_medicine() -- via _create_medicine_for_line -- on a
        genuine zero-result search for THIS row, immediately re-
        checking the SAME box afterward before selecting. See
        _create_medicine_for_line's own docstring for the still-open
        question about timing between a creation and the site
        recognizing the new medicine as searchable.

        WEBSITE_CATALOG_CODE FAST PATH (2026-08, Part 1 of the multi-
        result-disambiguation feature, PO-approved): the site's display
        NAME is not unique -- PO confirmed "Naphacogyl" alone appears on
        >= 4 distinct real catalog rows -- so a plain name-suffix match
        can legitimately resolve to more than one row (Playwright's
        strict mode then refuses to click, rather than guessing). If
        this line's Medicine already has a confirmed
        website_catalog_code from a PRIOR real selection (see
        Medicine.website_catalog_code's own docstring), this method
        skips the ambiguous name-based match/create path entirely and
        selects that exact row by its unique code instead -- see
        _select_medicine_by_known_code.

        PARTS 2+3 (2026-08, PO-approved, PO-supplied real DOM evidence):
        when no website_catalog_code is known yet AND the name match is
        genuinely ambiguous (more than one real result row), this method
        never guesses or auto-clicks a row. It logs a best-effort
        suggestion per candidate row (Part 2: this row's own "Hãng sản
        xuất" compared against the invoice's Supplier -- see
        _log_manufacturer_suggestions/_extract_manufacturer), then pauses
        for a human to make the actual selection directly in the live
        browser and waits for it via two PO-confirmed real DOM signals
        (Part 3: see _wait_for_human_medicine_selection), reads the now-
        selected row's own SDK code back from the site's own "chip"
        element, and persists it onto Medicine.website_catalog_code so
        every later invoice for this Medicine takes the Part 1 fast path
        instead ("hoc 1 lan, nho mai mai" -- see
        _disambiguate_via_human_selection).
        """
        search_key = (
            "medicine.search_input"
            if index == 0
            else "invoice_line.subsequent_row_medicine_search_input"
        )
        search_name = self._strip_packaging_description(item.medicine_name)

        known_medicine = self._lookup_known_medicine(item)
        if known_medicine is not None and known_medicine.website_catalog_code is not None:
            self._select_medicine_by_known_code(
                search_key, search_name, known_medicine.website_catalog_code, item
            )
            return

        if not self._fill_and_check_medicine_result(search_key, search_name):
            self._create_medicine_for_line(item)
            if not self._fill_and_check_medicine_result(search_key, search_name):
                raise AutomationError(
                    f"Medicine '{item.medicine_name}' (searched as '{search_name}') still has "
                    "no matching search result immediately after create_medicine() -- cannot "
                    "select it for this invoice line."
                )

        result_entry = self._registry.require_usable("medicine.search_result_option")
        matches = self._locate_parameterized(result_entry, search_name)
        if matches.count() > 1:
            self._disambiguate_via_human_selection(search_key, matches, item, supplier)
            return

        self._click_parameterized("medicine.search_result_option", search_name)
        self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)

    def _resolve_invoice_supplier(self, invoice: PurchaseInvoice) -> Supplier | None:
        """
        Best-effort lookup for Part 2's manufacturer-vs-supplier
        suggestion -- returns None (never raises) if no repository is
        configured or the invoice has no resolved supplier_id yet, same
        "optional, informational only" contract as _lookup_known_medicine.
        """
        if self._supplier_repository is None or invoice.supplier_id is None:
            return None
        return self._supplier_repository.get_by_id(invoice.supplier_id)

    def _lookup_known_medicine(self, item: PurchaseItem) -> Medicine | None:
        """
        Best-effort lookup for the website_catalog_code fast path --
        returns None (never raises) if no repository is configured or
        item has no resolved medicine_id yet, since this is an
        optimization on top of the existing mandatory search+create
        flow, not a hard requirement the way _create_medicine_for_line's
        own lookup is.
        """
        if self._medicine_repository is None or item.medicine_id is None:
            return None
        return self._medicine_repository.get_by_id(item.medicine_id)

    def _select_medicine_by_known_code(
        self, search_key: str, search_name: str, website_catalog_code: str, item: PurchaseItem
    ) -> None:
        """
        Fill this row's own search box by NAME as usual (to trigger the
        site's own search-as-you-type -- typing a raw catalog code into
        a name search box is not something any real evidence confirms
        works), then select by the already-confirmed CODE instead of
        the ambiguous name. Never silently falls back to a name-based
        guess if the saved code finds nothing -- refuses cleanly
        instead, since a stale/wrong code silently resolving to a
        different row is exactly the failure mode this feature exists
        to prevent.
        """
        if not self._fill_and_check_medicine_result_by_code(
            search_key, search_name, website_catalog_code
        ):
            raise AutomationError(
                f"Medicine '{item.medicine_name}' has a saved website_catalog_code "
                f"'{website_catalog_code}' but no search result matched it -- refusing to "
                "guess a different row. If this medicine's real catalog entry changed, "
                "clear Medicine.website_catalog_code to re-disambiguate."
            )
        self._click_parameterized("medicine.search_result_option_by_code", website_catalog_code)
        self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)

    def _disambiguate_via_human_selection(
        self,
        search_key: str,
        matches: Locator,
        item: PurchaseItem,
        supplier: Supplier | None,
    ) -> None:
        """
        Parts 2+3 of the multi-result-disambiguation feature (2026-08,
        PO-approved, PO-supplied real DOM evidence for both parts).
        Never clicks any of ``matches`` itself -- an ambiguous name match
        is exactly the case this project's "never guess" rule exists
        for. Logs a per-row manufacturer suggestion (Part 2, purely
        informational -- the human may pick a different row than the
        suggestion, and this method does not second-guess that choice),
        then waits for the human to complete the real selection directly
        in the browser (Part 3), reads the now-confirmed SDK code back,
        and persists it onto Medicine.website_catalog_code so this exact
        ambiguity never has to be re-resolved for this Medicine again.
        """
        self._log_manufacturer_suggestions(matches, supplier)
        self._wait_for_human_medicine_selection(search_key)
        code = self._read_selected_medicine_code(search_key)
        self._persist_website_catalog_code(item, code)

    def _log_manufacturer_suggestions(self, matches: Locator, supplier: Supplier | None) -> None:
        """
        Part 2 (2026-08, PO-approved, PO-supplied real DOM evidence for
        medicine.search_result_info_item): reads each ambiguous result
        row's own "Hãng sản xuất" (manufacturer) and compares it,
        case-insensitively and best-effort (a simple two-way substring
        check -- Vietnamese company names on the site and on an invoice's
        resolved Supplier are not guaranteed to be byte-identical, e.g.
        "cổ phần" vs "CP"), against the invoice's own Supplier name.
        Purely a logged HINT for whoever performs the real selection --
        never clicks, never auto-selects, never blocks on the comparison
        itself.
        """
        info_item_entry = self._registry.require_usable("medicine.search_result_info_item")
        assert info_item_entry.strategy == "css" and info_item_entry.value is not None
        supplier_name = supplier.name.strip().lower() if supplier is not None else None
        count = matches.count()
        for position in range(count):
            row = matches.nth(position)
            row_text = row.inner_text()
            info_text = row.locator("xpath=..").locator(info_item_entry.value).inner_text()
            manufacturer = self._extract_manufacturer(info_text)
            if manufacturer is not None and supplier_name is not None:
                manufacturer_lower = manufacturer.lower()
                is_suggested = (
                    manufacturer_lower in supplier_name or supplier_name in manufacturer_lower
                )
            else:
                is_suggested = False
            if is_suggested:
                self._logger.info(
                    "Ambiguous medicine match %d/%d: '%s' -- manufacturer '%s' MATCHES "
                    "invoice supplier '%s'. Suggested, not auto-selected -- waiting for a "
                    "human to confirm the correct row in the browser.",
                    position + 1,
                    count,
                    row_text,
                    manufacturer,
                    supplier.name if supplier is not None else None,
                )
            else:
                self._logger.info(
                    "Ambiguous medicine match %d/%d: '%s' -- manufacturer '%s'.",
                    position + 1,
                    count,
                    row_text,
                    manufacturer,
                )

    @staticmethod
    def _extract_manufacturer(info_text: str) -> str | None:
        """
        Parses "Hãng sản xuất: X" out of a medicine.search_result_info_item's
        own text (see that registry entry's own 'source' for the two real
        DOM snapshots this is grounded in). Field count/order is NOT
        fixed across real rows (one real snapshot had 3 fields, another
        had 5 plus a <br>) -- located by the "Hãng sản xuất:" label text
        itself, never by position, so it is robust to that variation.
        Returns None if this row's info text has no such label at all
        (never invented).
        """
        marker = "Hãng sản xuất:"
        marker_index = info_text.find(marker)
        if marker_index == -1:
            return None
        remainder = info_text[marker_index + len(marker) :]
        # The next field starts after " - " (both confirmed real
        # snapshots use this exact separator) or a line break (the <br>
        # snapshot) -- whichever comes first ends this field's value.
        end_match = re.search(r"\s-\s|\r?\n", remainder)
        value = remainder[: end_match.start()] if end_match else remainder
        value = value.strip()
        return value or None

    _HUMAN_SELECTION_POLL_INTERVAL_MS = 200
    # TEMPORARY DIAGNOSTIC (2026-08): PO ruled out the race-condition
    # theory via a real dry-run -- clicked the correct --dry-run browser
    # window, waited the full 180s (a genuine timeout, not an early
    # false alarm), and it still failed. Next real suspect: the two
    # registry entries (medicine.selected_match_chip/its own
    # aria-expanded read) may simply not match the LIVE site's actual
    # DOM, even though they match this project's own local fixture.
    # Logs the raw per-tick values below (throttled to avoid flooding)
    # so the next real dry-run run tells us directly which of the two
    # conditions is really the problem, instead of guessing from a
    # static snapshot again. Remove this block once root-caused.
    _HUMAN_SELECTION_DIAGNOSTIC_LOG_INTERVAL_MS = 2_000

    def _wait_for_human_medicine_selection(self, search_key: str) -> None:
        """
        Part 3 (2026-08, PO-approved, PO-supplied real DOM evidence for
        medicine.selected_match_chip): waits for BOTH PO-confirmed
        "human has finished picking" signals -- this row's own search-box
        input's 'aria-expanded' attribute flipping to 'false', AND the
        selected-match chip becoming visible -- to be true AT THE SAME
        TIME, up to PlaywrightAutomationConfig.human_disambiguation_timeout_ms
        (a few minutes, per PO's own words -- externally configurable,
        see AppSettings.automation_human_disambiguation_timeout_seconds).

        BUG FIX (2026-08, PO-confirmed via a real dry-run -- CRITICAL,
        race condition): the original implementation checked these as
        TWO SEPARATE, SEQUENTIAL expect() calls -- aria-expanded first
        (its own full timeout budget), THEN the chip's visibility
        (a much shorter, independently-bounded follow-up wait). PO's own
        decisive, real click made the first check resolve almost
        instantly, but the run then failed within seconds on the SECOND
        check -- the exact same root-cause class already fixed for
        _wait_for_row_settled and the Phase 1 medicine-selection settle
        wait (_MEDICINE_SELECTION_SETTLE_MS's own docstring): AngularJS
        needs a real, non-instant digest cycle between updating
        aria-expanded and actually rendering the chip into the DOM, and
        a second check bounded by its own SHORT, independent timeout
        (rather than sharing the full remaining budget) can time out on
        exactly that real, human-paced gap even though the selection
        genuinely completed. Fixed the same way as those precedents:
        both conditions are polled TOGETHER, every tick, across the
        FULL configured timeout -- success requires observing both true
        in the SAME tick, never short-circuiting into a second,
        independently-bounded wait once the first condition alone is
        satisfied.

        Raises VerificationFailedError -- never silently continues, never
        guesses a row -- if both conditions are never observed true
        together within the timeout.
        """
        entry = self._registry.require_usable(search_key)
        input_locator = self._locate(entry)
        chip_locator = self._selected_match_chip_locator(input_locator)
        deadline = time.monotonic() + (self._config.human_disambiguation_timeout_ms / 1000)
        next_diagnostic_log_at = time.monotonic()
        while True:
            if self._human_medicine_selection_is_complete(input_locator, chip_locator):
                return
            now = time.monotonic()
            if now >= next_diagnostic_log_at:
                self._log_human_medicine_selection_diagnostic(input_locator, chip_locator)
                next_diagnostic_log_at = now + (
                    self._HUMAN_SELECTION_DIAGNOSTIC_LOG_INTERVAL_MS / 1000
                )
            if now >= deadline:
                raise VerificationFailedError(
                    "Part 3: timed out waiting "
                    f"{self._config.human_disambiguation_timeout_ms}ms for a human to "
                    "manually resolve an ambiguous medicine search result -- the search "
                    "box's own 'aria-expanded'='false' and the selected-match chip becoming "
                    "visible were never observed together. Refusing to guess a row -- "
                    "resolve the selection directly on the live site, or re-run once it is "
                    "done."
                )
            self._page.wait_for_timeout(self._HUMAN_SELECTION_POLL_INTERVAL_MS)

    def _log_human_medicine_selection_diagnostic(
        self, input_locator: Locator, chip_locator: Locator
    ) -> None:
        """TEMPORARY DIAGNOSTIC -- see _HUMAN_SELECTION_DIAGNOSTIC_LOG_INTERVAL_MS's own comment."""
        try:
            aria_expanded = input_locator.get_attribute("aria-expanded")
        except Exception as exc:  # noqa: BLE001
            aria_expanded = f"<error reading attribute: {exc}>"
        try:
            chip_count = chip_locator.count()
        except Exception as exc:  # noqa: BLE001
            chip_count = f"<error counting: {exc}>"  # type: ignore[assignment]
        try:
            chip_visible = chip_locator.is_visible() if chip_count == 1 else False
        except Exception as exc:  # noqa: BLE001
            chip_visible = f"<error checking visibility: {exc}>"  # type: ignore[assignment]
        self._logger.info(
            "Part 3 DIAGNOSTIC: aria-expanded=%r, chip_locator matched %r element(s), "
            "chip_visible=%r",
            aria_expanded,
            chip_count,
            chip_visible,
        )

    @staticmethod
    def _human_medicine_selection_is_complete(
        input_locator: Locator, chip_locator: Locator
    ) -> bool:
        """
        One atomic-enough tick of Part 3's combined poll -- both checks
        are plain, non-waiting Playwright reads (no auto-retry of their
        own), so there is no gap in which one could be re-evaluated
        against a DOM state the other has already moved past. A
        transient Playwright error (e.g. the input briefly detached
        mid-digest) is treated as "not complete yet, keep polling"
        rather than a hard failure -- this is exactly the kind of
        momentary DOM churn the whole combined-poll fix exists to
        tolerate.
        """
        try:
            return input_locator.get_attribute("aria-expanded") == "false" and (
                chip_locator.is_visible()
            )
        except Exception:  # noqa: BLE001
            return False

    def _selected_match_chip_locator(self, input_locator: Locator) -> Locator:
        """
        Locates medicine.selected_match_chip RELATIONALLY to an already-
        resolved row-aware search-input locator -- its own immediately
        preceding sibling matching that registry entry's css class --
        mirroring the PO-confirmed real snapshot's own immediate-sibling
        structure (chip directly followed by the input). Deliberately
        not a standalone page-wide lookup: with multiple line items,
        each row has its own such chip once selected, and only THIS
        row's is wanted.
        """
        chip_entry = self._registry.require_usable("medicine.selected_match_chip")
        assert chip_entry.strategy == "css" and chip_entry.value is not None
        class_name = chip_entry.value.lstrip(".")
        return input_locator.locator(
            f"xpath=preceding-sibling::*[contains(concat(' ', normalize-space(@class), ' '), "
            f"' {class_name} ')][1]"
        )

    def _read_selected_medicine_code(self, search_key: str) -> str:
        """
        Reads the real site's own SDK code back from the now-visible
        selected-match chip's own nested code-label element
        (medicine.selected_match_chip_code_label -- deliberately NOT the
        chip's own inner_text(), which also contains its close button's
        '×'), whose text is '{code} - {tên thuốc}' (PO-confirmed real
        snapshot -- same shape medicine.search_result_option_by_code
        already relies on) -- the part before the first ' - '.
        """
        entry = self._registry.require_usable(search_key)
        input_locator = self._locate(entry)
        chip_locator = self._selected_match_chip_locator(input_locator)
        code_label_entry = self._registry.require_usable("medicine.selected_match_chip_code_label")
        assert code_label_entry.strategy == "css" and code_label_entry.value is not None
        chip_text = chip_locator.locator(code_label_entry.value).inner_text().strip()
        code = chip_text.split(" - ", 1)[0].strip()
        if not code:
            raise VerificationFailedError(
                f"Part 3: could not parse a website catalog code from the selected chip's own "
                f"text ('{chip_text}')."
            )
        return code

    def _persist_website_catalog_code(self, item: PurchaseItem, code: str) -> None:
        """
        Saves the human-confirmed code onto Medicine.website_catalog_code
        ("hoc 1 lan, nho mai mai") so every later invoice for this exact
        Medicine takes Part 1's fast path instead of re-disambiguating.
        Best-effort, same "optimization on top of an already-completed
        real selection" contract as _lookup_known_medicine -- the human
        has already made the real, correct choice directly on the live
        site by this point, so a failure to persist here never undoes
        that; it only means this ambiguity is not remembered for next
        time.
        """
        if self._medicine_repository is None or item.medicine_id is None:
            self._logger.warning(
                "Part 3: human selection confirmed (code '%s') but cannot persist it -- "
                "no medicine_repository configured or item.medicine_id is not resolved.",
                code,
            )
            return
        medicine = self._medicine_repository.get_by_id(item.medicine_id)
        if medicine is None:
            self._logger.warning(
                "Part 3: human selection confirmed (code '%s') but Medicine '%s' was not "
                "found -- cannot persist website_catalog_code.",
                code,
                item.medicine_id,
            )
            return
        medicine.assign_website_catalog_code(code)
        self._medicine_repository.update(medicine)
        self._logger.info(
            "Part 3: persisted website_catalog_code='%s' onto Medicine '%s' -- future "
            "invoices for this medicine will skip disambiguation.",
            code,
            item.medicine_id,
        )

    def _fill_and_check_medicine_result(self, search_key: str, search_name: str) -> bool:
        """Fill one line's own search box once and report whether a name-anchored match exists."""
        self._fill(search_key, search_name)
        self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)
        result_entry = self._registry.require_usable("medicine.search_result_option")
        return self._locate_parameterized(result_entry, search_name).count() > 0

    def _fill_and_check_medicine_result_by_code(
        self, search_key: str, search_name: str, website_catalog_code: str
    ) -> bool:
        """Fill one line's own search box once (by name) and report whether a code-anchored
        match exists."""
        self._fill(search_key, search_name)
        self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)
        result_entry = self._registry.require_usable("medicine.search_result_option_by_code")
        return self._locate_parameterized(result_entry, website_catalog_code).count() > 0

    def _create_medicine_for_line(self, item: PurchaseItem) -> None:
        """
        Create a catalog entry for a line's medicine that a real,
        zero-result search just proved does not exist on-site yet.
        item.medicine_id is trusted as already-resolved (same as
        item.batch_id for _resolve_batch, item.retail_units_per_purchase_unit
        for _convert_to_retail_units -- both resolved upstream by the
        Application-layer pipeline, never guessed here).

        OPEN QUESTION, not resolved unilaterally: whether the real site
        makes a just-created medicine searchable immediately, or needs
        real settle time beyond create_medicine()'s own dialog
        interactions, is unconfirmed -- _search_and_select_medicine_for_line's
        own re-check after this call reuses _MEDICINE_SELECTION_SETTLE_MS
        for the same "no confirmed selector to poll instead" reason as
        everywhere else it's used, not because this specific timing has
        been verified against the real site yet.
        """
        if self._medicine_repository is None:
            raise AutomationError(
                f"Medicine '{item.medicine_name}' was not found on-site and needs to be "
                "created, but no MedicineRepository was injected into "
                "PlaywrightBrowserAutomationProvider."
            )
        if item.medicine_id is None:
            raise AutomationError(
                f"PurchaseItem '{item.medicine_name}' has no resolved medicine_id -- cannot "
                "look up the Medicine to create on-site."
            )
        medicine = self._medicine_repository.get_by_id(item.medicine_id)
        if medicine is None:
            raise AutomationError(
                f"Medicine '{item.medicine_id}' referenced by '{item.medicine_name}' was not "
                "found in the local database."
            )
        outcome = self.create_medicine(medicine)
        if not outcome.success:
            raise AutomationError(
                f"create_medicine failed for '{item.medicine_name}': {outcome.failure_reason}"
            )

    # --- internal: suggested retail price (post-save edit flow) ---------------

    def _update_retail_prices_after_save(self, invoice: PurchaseInvoice) -> None:
        """
        PO amendment (2026-08): medicine.retail_price_field ("Gia ban
        le") is confirmed to belong to the medicine edit dialog, reached
        via Sua -> Chinh sua thuoc, only AFTER the invoice has been saved
        once (05_full_flow...py:146-151) -- not inline in the per-line
        fill loop. Applied to EVERY line, including already-existing
        medicines: the purchase price (and so the suggested retail
        price) can differ invoice to invoice, and the operator still
        reviews/edits the value in the browser before the final save,
        per the "reference only, never authoritative" retail-price rule.

        Part 3 (Vien unit conversion, PO-confirmed 2026-08): the
        suggested retail price is calculated from the converted
        per-Vien purchase price, not the raw invoice unit_price --
        "Gia ban le" prices one Vien, so its suggestion must be based
        on what one Vien actually cost.

        invoice_line.edit_medicine_button's per-item nth is a reasonable
        but NOT independently confirmed extrapolation -- the recording
        only demonstrates index 0 (.first, one line item). See that
        entry's notes.
        """
        self._click("invoice.edit_link")
        for index, item in enumerate(invoice.items):
            self._click_at_index("invoice_line.edit_medicine_button", index)
            _, retail_unit_price = self._convert_to_retail_units(item)
            suggested_retail_price = self._price_policy.calculate_suggested_retail_price(
                retail_unit_price
            )
            self._fill("medicine.retail_price_field", str(suggested_retail_price.amount))
            self._click("invoice_line.edit_dialog_close_button")

    def _convert_to_retail_units(self, item: PurchaseItem) -> tuple[Decimal, Money]:
        """
        Convert ``item``'s purchase-denominated quantity/price to Vien
        (Part 3, PO-confirmed 2026-08): the site always retails by Vien
        regardless of the invoice's own purchase unit (Hop/Vi/...).
        ``item.retail_units_per_purchase_unit`` is resolved earlier in
        the pipeline (pipeline.party_matching_step.PartyMatchingStep,
        backed by domain.validators.invoice_validator.InvoiceValidator's
        matching gate) -- never computed or guessed here.
        """
        if item.retail_units_per_purchase_unit is None:
            raise AutomationError(
                f"PurchaseItem '{item.medicine_name}' has no resolved "
                f"retail_units_per_purchase_unit -- cannot convert its quantity/price to "
                f"Vien. This invoice should not have reached automation in this state."
            )
        factor = Decimal(item.retail_units_per_purchase_unit)
        retail_quantity = item.quantity.amount * factor
        retail_unit_price = Money(item.unit_price.amount / factor, item.unit_price.currency)
        return retail_quantity, retail_unit_price

    @staticmethod
    def _row_id_suffix(position: int) -> str:
        """
        Per-row DOM id suffix for the invoice line-items table
        (table_structure.html, PO-confirmed 2026-08, a real DOM
        snapshot of 5 stable rows -- REPLACES the abandoned
        tbody:nth-child(N) investigation entirely, per that entry's
        own notes). Each row is genuinely its own <tbody>
        (ng-repeat="gridItem in viewModel.NoteItems"); ``position`` is
        the row's 1-based position in invoice order. Row 1 has no
        suffix at all (empty string); row N (N >= 2) has suffix
        str(N - 1) -- confirmed for N=1..5 against the real snapshot.
        Used to address an ALREADY-COMMITTED row's own persistent
        Price/Quantity/VAT/Discount fields (e.g.
        f"{invoice_line.quantity_field's registered '#tbxQuantityId'}{suffix}")
        -- a DIFFERENT concept from Phase 1's shared, unsuffixed
        active-row fields (see fill_and_save_invoice's own docstring).
        """
        if position < 1:
            raise AutomationError(f"Row position must be >= 1, got {position}.")
        return "" if position == 1 else str(position - 1)

    # Bug fix (2026-08, PO-confirmed via a real --dry-run run):
    # page.locator("tbody") page-wide returned 24 matches for a 3-item
    # real invoice -- other real tables elsewhere on the live page, not
    # modeled at all by this project's local test fixture, which only
    # ever had at most 1 stray <tbody> (the supplier dialog). #tblMain
    # is real, already-confirmed evidence for exactly the right scope
    # (medicine.add_new_trigger's own registry notes: "#tblMain is the
    # invoice line-item table") -- not a new guess.
    _LINE_ITEMS_TABLE_SCOPE = "#tblMain"

    def _line_item_rows(self) -> Locator:
        return self._page.locator(f"{self._LINE_ITEMS_TABLE_SCOPE} tbody")

    def _click_batch_edit_button_for_row(self, position: int) -> None:
        """
        Click the batch/expiry ("Lo/Han") trigger for the row at
        1-based ``position`` (table_structure.html, PO-confirmed
        2026-08 -- REPLACES the abandoned tbody:nth-child(N) CSS-
        position approach entirely). Unlike Price/Quantity/VAT/
        Discount, this trigger has NO distinguishing id or text of its
        own -- it is visually IDENTICAL on every row (a calendar-icon
        button, ng-click="updateBatchExpiryDate") and is only
        distinguishable by which <tbody> it lives in, since each row
        is genuinely its own <tbody>
        (ng-repeat="gridItem in viewModel.NoteItems").

        Deliberately uses Playwright's Locator.nth() on a locator
        already filtered down to 'tbody' elements, NOT CSS
        ':nth-child(N)' -- :nth-child(N) counts ALL sibling elements
        regardless of tag (a <thead> sibling shifts the count), which
        was the root cause of the earlier, abandoned tbody:nth-child(N)
        investigation's failure. Locator.nth() counts only within the
        already-filtered 'tbody' set, so it is not affected by that.
        Scoped to _line_item_rows() (#tblMain), not a page-wide 'tbody'
        -- see that method's own comment for why (real dry-run evidence
        of stray tbody elements elsewhere on the live page).

        Clicking this reveals the SAME shared
        invoice_line.batch_number_field/expiry_date_field overlay,
        already "attached" to this row -- no further row selection is
        needed after this click.
        """
        entry = self._registry.require_usable("invoice_line.select_row_for_batch_button")
        if entry.strategy != "css" or entry.value is None:
            raise SelectorNotUsableError(
                "'invoice_line.select_row_for_batch_button' has strategy "
                f"{entry.strategy!r}, not a plain css selector -- row-scoped lookup only "
                "applies to a css selector."
            )
        try:
            self._line_item_rows().nth(position - 1).locator(entry.value).click()
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(
                f"click:invoice_line.select_row_for_batch_button[row {position}]", exc
            ) from exc

    _ROW_SETTLE_TIMEOUT_MS = 5_000

    def _wait_for_row_settled(self, expected_row_count: int) -> None:
        """
        Bug fix (2026-08, PO-confirmed via real hands-on inspection --
        CRITICAL, silent data loss, see fill_and_save_invoice's own
        docstring for the full incident). Clicking
        invoice_line.add_row_button does not, by itself, prove the
        just-filled row actually became a genuine, separate settled row
        -- Playwright only sees a normal, successful click either way.
        table_structure.html already confirmed the real, distinguishing
        fact this leans on: each SETTLED row is genuinely its own real
        <tbody> (ng-repeat="gridItem in viewModel.NoteItems"), while an
        actively-editing, not-yet-settled row shares the page's one
        unsuffixed field set with every other not-yet-settled row --
        so _line_item_rows().count() is real, already-established
        evidence of how many rows have actually settled, not a new,
        unconfirmed selector.

        BUG FIX (2026-08, PO-confirmed via a real --dry-run run): this
        originally counted page.locator("tbody") PAGE-WIDE, which a
        real dry-run run showed returning 24 matches for a 3-item real
        invoice -- other real tables elsewhere on the live page (never
        modeled by this project's local fixture, which only ever had 1
        stray tbody at most). Now scoped via _line_item_rows() (see its
        own comment for why #tblMain is the right, already-confirmed
        scope).

        Uses Playwright's own expect().to_have_count() -- polls the
        real DOM until it matches or the timeout elapses -- rather than
        checking .count() once immediately (which would defeat the
        entire point: PO's own manual, slow re-selection is what proved
        this genuinely needs real, non-instant time to settle) or a
        fixed sleep (wastes time when the site is fast, and is still
        just a guess at "long enough" when it is not).

        Raises VerificationFailedError -- never silently continues --
        if the count never reaches ``expected_row_count`` in time: per
        the PO's own explicit instruction, an unverifiable row must
        stop the run with a clear diagnostic rather than silently
        proceeding to overwrite it with the next line's data.
        """
        try:
            expect(self._line_item_rows()).to_have_count(
                expected_row_count, timeout=self._ROW_SETTLE_TIMEOUT_MS
            )
        except AssertionError as exc:
            actual = self._line_item_rows().count()
            raise VerificationFailedError(
                f"Row {expected_row_count} did not settle within "
                f"{self._ROW_SETTLE_TIMEOUT_MS}ms after clicking invoice_line.add_row_button "
                f"-- expected {expected_row_count} settled <tbody> row(s), found {actual}. "
                "Refusing to continue to the next line: filling its fields into the still-"
                "shared active-row fields before this row finishes settling would silently "
                "overwrite it instead of adding a new one."
            ) from exc

    _CALENDAR_VISIBLE_TIMEOUT_MS = 5_000

    def _verify_exactly_one_calendar_visible(self) -> None:
        """
        Bug fix (2026-08, PO's own explicit safety request, real DOM
        snapshot): invoice.date_calendar_dropdown is a single, page-
        shared bootstrap-datepicker instance that repositions itself to
        whichever bound field/trigger was last activated (PO-confirmed
        directly) -- normally only one is ever open at a time, but
        navigating an ambiguous (0 or >1 visible) calendar risks
        clicking a year/month/day meant for a different field. Checked
        right after clicking invoice.date_calendar_trigger, before any
        navigation. ':visible' is appended here (not baked into the
        registry entry's own value) since the dropdown element itself
        always exists in the DOM -- only visibility distinguishes an
        actually-open instance from a dormant one.
        """
        entry = self._registry.require_usable("invoice.date_calendar_dropdown")
        assert entry.strategy == "css" and entry.value is not None
        visible_locator = self._page.locator(f"{entry.value}:visible")
        try:
            expect(visible_locator).to_have_count(1, timeout=self._CALENDAR_VISIBLE_TIMEOUT_MS)
        except AssertionError as exc:
            actual = visible_locator.count()
            raise VerificationFailedError(
                f"Expected exactly 1 visible '{entry.value}' after clicking "
                f"invoice.date_calendar_trigger, found {actual}. Refusing to navigate an "
                "ambiguous or absent calendar -- it could belong to a different field, or "
                "not be open at all."
            ) from exc

    def _select_invoice_date_via_calendar(self, target_date: date) -> None:
        """
        Bug fix (2026-08, PO-confirmed via real hands-on testing --
        CRITICAL, WRONG DATE on a real invoice, RESOLVED). PO personally
        verified clicking directly into the "Ngày hóa đơn" textbox does
        NOT open its calendar -- a plain fill() was never going to work
        on this field; it is display-only, bound to a separate
        bootstrap-datepicker widget triggered by
        invoice.date_calendar_trigger (a dedicated calendar-icon
        button, real ng-click="onInvoiceDateClick" confirmed distinct
        from whatever backs the separate "Ngày:" field).

        Clicks invoice.date_calendar_switch TWICE unconditionally to
        jump straight to year-grid view (PO's own proposed strategy),
        then picks year -> month -> day by matching text -- regardless
        of how far the target date is from the currently-displayed
        month/year, avoiding the fragile, position-counting
        '«'-repeated-clicking approach the raw recordings used (which
        needed to know in advance how many months to step back).
        Selecting a year/month auto-returns bootstrap-datepicker to the
        next-finer view, per real, observed widget behavior.
        """
        self._click("invoice.date_calendar_trigger")
        self._verify_exactly_one_calendar_visible()
        self._click("invoice.date_calendar_switch")
        self._click("invoice.date_calendar_switch")
        self._click_parameterized("invoice.date_calendar_year_option", str(target_date.year))
        self._click_parameterized(
            "invoice.date_calendar_month_option", f"Th{target_date.month}"
        )
        self._click_parameterized("invoice.date_calendar_day_option", str(target_date.day))

    def _fill_invoice_date_and_verify(self, invoice_date: date) -> None:
        """
        Bug fix (2026-08, PO-confirmed across 3 real --dry-run
        investigations -- CRITICAL, WRONG DATE on a real invoice,
        RESOLVED). invoice.date_field's own registry notes have the
        full history: a plain fill() produced a visibly WRONG date on
        the real site, and PO then personally confirmed clicking the
        textbox itself does not even open its calendar. The correct
        mechanism -- click invoice.date_calendar_trigger, verify
        exactly one calendar is visible, then navigate year -> month ->
        day (see _select_invoice_date_via_calendar) -- is now used
        instead of fill().

        Still reads invoice.date_field back immediately afterward and
        raises VerificationFailedError if it does not show exactly the
        expected "%d/%m/%Y" string -- kept as PO's own explicit
        instruction: even a believed-correct mechanism should not be
        blindly trusted to silently reach a real "Ghi Phieu" save. Only
        the ACT step changed (calendar navigation instead of fill()),
        not this verification.
        """
        formatted_date = invoice_date.strftime("%d/%m/%Y")
        self._select_invoice_date_via_calendar(invoice_date)
        entry = self._registry.require_usable("invoice.date_field")
        actual = self._locate(entry).input_value()
        if actual != formatted_date:
            raise VerificationFailedError(
                f"invoice.date_field shows '{actual}' after selecting '{formatted_date}' "
                "via the calendar -- the site did not register this date correctly. "
                "Refusing to continue with a possibly-wrong invoice date -- re-verify the "
                "calendar navigation (year/month/day matching, or bootstrap-datepicker's "
                "own auto-advance-to-next-view behavior) against the live site."
            )

    def _click_at_index(self, key: str, index: int) -> None:
        """
        Like _click, but for a per-line repeating element whose registry
        entry deliberately carries no fixed 'nth' -- the caller supplies
        the runtime index instead (see invoice_line.edit_medicine_button).
        """
        entry = self._registry.require_usable(key)
        try:
            self._locate(entry).nth(index).click()
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"click:{key}[{index}]", exc) from exc

    _OPTIONAL_CLICK_TIMEOUT_MS = 2_000

    def _click_if_present(self, key: str) -> bool:
        """
        Best-effort click for an element PO-confirmed to not always
        appear at all (e.g. medicine.create_dialog_close_button,
        supplier.creation_confirmation_close_button,
        supplier.default_tag_remove_button -- genuinely either present
        already or never coming). Never raises: a genuinely-absent
        element is expected, not an error, so it is logged at debug
        level and skipped -- but a 'needs_verification' entry still
        raises (an unusable selector is always a real problem, optional
        or not).

        NOT used for login.close_notification_popup any more -- that
        one is confirmed to genuinely appear, just not always within
        this method's own short _OPTIONAL_CLICK_TIMEOUT_MS (see
        _click_if_eventually_visible, PO-confirmed 2026-08 via a real
        --dry-run run).

        Returns whether the click actually happened, so a caller that
        needs its own visible outcome logging (unlike callers that are
        content with the debug-level log above) can report it
        explicitly instead of staying silent.
        """
        entry = self._registry.require_usable(key)
        try:
            self._locate(entry).click(timeout=self._OPTIONAL_CLICK_TIMEOUT_MS)
            return True
        except SelectorRegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Optional element '%s' not present, skipping: %s", key, exc)
            return False

    _LOGIN_POPUP_VISIBLE_TIMEOUT_MS = 8_000

    def _click_if_eventually_visible(self, key: str, timeout_ms: int) -> bool:
        """
        Like _click_if_present, but for an element confirmed to
        genuinely appear -- just not always within an instant. Bug fix
        (2026-08, PO-confirmed via a real --dry-run run):
        login.close_notification_popup's own log line (added the
        previous fix specifically to make this visible) showed "not
        present, skipped" on a run where the popup was, in fact, still
        visible on screen moments later -- _click_if_present's plain
        click(timeout=_OPTIONAL_CLICK_TIMEOUT_MS) (2 seconds) is not
        long enough for this specific popup to render after
        login.submit_button's own click.

        Uses Playwright's own expect().to_be_visible() -- polls the
        real DOM until it matches or ``timeout_ms`` elapses, the same
        mechanism _wait_for_row_settled already established for this
        exact class of "genuinely needs real, non-instant time" problem
        -- rather than a single immediate check, or reusing
        _click_if_present's own short, generic timeout (tuned for
        elements that are either already there or never coming, not
        elements that need real time to render).

        Never raises for a genuinely-absent/never-rendered element --
        same "optional, best-effort" contract as _click_if_present.
        """
        entry = self._registry.require_usable(key)
        locator = self._locate(entry)
        try:
            expect(locator).to_be_visible(timeout=timeout_ms)
        except AssertionError:
            return False
        try:
            locator.click(timeout=self._OPTIONAL_CLICK_TIMEOUT_MS)
            return True
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("'%s' became visible but click failed: %s", key, exc)
            return False

    # --- internal: batch resolution -----------------------------------------

    def _resolve_batch(self, batch_id: str) -> Batch:
        if self._batch_repository is None:
            raise AutomationError(
                "fill_and_save_invoice needs batch_number/expiry_date but no BatchRepository "
                "was injected into PlaywrightBrowserAutomationProvider."
            )
        batch = self._batch_repository.get_by_id(batch_id)
        if batch is None:
            raise AutomationError(f"Batch '{batch_id}' referenced by a PurchaseItem was not found.")
        return batch

    def _verify_saved(self) -> None:
        entry = self._registry.require_usable("invoice.save_success_indicator")
        if self._locate(entry).count() == 0:
            raise VerificationFailedError(
                "invoice.save_success_indicator did not appear after clicking invoice.save_button."
            )

    # --- internal: action helpers -------------------------------------------

    def _run_outcome(self, action: str, do: Callable[[], None]) -> AutomationOutcome:
        try:
            do()
        except TransientInfrastructureError:
            # Let Application's RetryPolicy see and retry this -- never
            # swallow a transient failure into a false "permanent" result.
            raise
        except (SelectorRegistryError, AutomationError) as exc:
            self._logger.error("%s failed: %s", action, exc)
            return AutomationOutcome(success=False, failure_reason=str(exc))
        self._logger.info("%s succeeded.", action)
        return AutomationOutcome(success=True)

    def _goto(self, key: str) -> None:
        entry = self._registry.require_usable(key)
        if entry.strategy != "goto" or entry.value is None:
            raise SelectorNotUsableError(f"'{key}' is not a 'goto' entry with a URL.")
        try:
            self._page.goto(entry.value)
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"goto:{key}", exc) from exc

    def _click(self, key: str) -> None:
        entry = self._registry.require_usable(key)
        try:
            self._locate(entry).click()
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"click:{key}", exc) from exc

    def _fill(self, key: str, value: str) -> None:
        entry = self._registry.require_usable(key)
        try:
            self._locate(entry).fill(value)
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"fill:{key}", exc) from exc

    def _fill_row_specific_field(self, key: str, position: int, value: str) -> None:
        """
        Like _fill, but for an ALREADY-COMMITTED row's own persistent
        field, addressed via its registered base css id plus
        _row_id_suffix(position) (table_structure.html, PO-confirmed
        2026-08) -- e.g. invoice_line.quantity_field's registered
        '#tbxQuantityId' becomes '#tbxQuantityId3' for the 4th row.
        Only meaningful for a plain 'css' strategy entry with a bare id
        selector; not a general-purpose mechanism for every strategy.
        """
        entry = self._registry.require_usable(key)
        if entry.strategy != "css" or entry.value is None:
            raise SelectorNotUsableError(
                f"'{key}' has strategy {entry.strategy!r}, not a plain css id -- "
                "row-specific suffixing only applies to a bare css id selector."
            )
        computed_selector = f"{entry.value}{self._row_id_suffix(position)}"
        try:
            self._page.locator(computed_selector).fill(value)
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"fill:{key}[row {position}]", exc) from exc

    def _click_parameterized(self, key: str, runtime_text: str) -> None:
        entry = self._registry.require_usable(key)
        try:
            self._locate_parameterized(entry, runtime_text).click()
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"click:{key}", exc) from exc

    def _locate_parameterized(self, entry: SelectorEntry, runtime_text: str) -> Locator:
        """
        Like _locate, but for an entry whose registered 'value'/'name' is
        only a recorded EXAMPLE of the real, dynamic text a search result
        shows (see e.g. supplier.search_result_option's notes) --
        substitutes runtime_text for that recorded example instead of
        reusing it literally.
        """
        root = self._resolve_scope(entry)
        if entry.strategy == "text":
            locator = root.get_by_text(runtime_text, exact=bool(entry.exact))
        elif entry.strategy == "role":
            assert entry.role is not None
            locator = root.get_by_role(
                entry.role,  # type: ignore[arg-type]
                name=runtime_text,
                exact=bool(entry.exact),
            )
        elif entry.strategy == "text_ends_with":
            # Bug fix (2026-08, PO-confirmed via a real DOM snapshot --
            # CRITICAL, substring-collision selection bug): a real
            # medicine search returns a variable-length code prefix
            # ("893100160624 - ", the site's own catalog id, not known
            # in advance) before the medicine name, inside a <b> tag
            # sitting alongside a SEPARATE, ever-changing info span
            # (price/stock/SĐK) -- see this entry's own registry notes
            # for the full real snapshot. Neither a plain substring
            # match (matched "Coldi-B DNH" when searching "Coldi") nor
            # a full exact match (the code prefix is unknown) works --
            # only an END-anchored, case-insensitive match against the
            # <b> tag alone (entry.value is the real, confirmed CSS tag
            # for it) correctly distinguishes "...- Coldi" from
            # "...- Coldi-B DNH".
            assert entry.value is not None
            pattern = re.compile(re.escape(runtime_text) + r"$", re.IGNORECASE)
            locator = root.locator(entry.value).filter(has_text=pattern)
        elif entry.strategy == "text_starts_with":
            # Part 1 of the multi-result-disambiguation feature (2026-08,
            # PO-approved): reuses medicine.search_result_option's own
            # confirmed '<b>{code} - {tên thuốc}</b>' shape (see that
            # entry's registry notes for the real snapshot), but anchors
            # on the CODE at the start instead of the name at the end --
            # used only when a Medicine already has a confirmed
            # website_catalog_code from a prior real selection, to jump
            # straight to that exact row instead of re-disambiguating an
            # ambiguous name every time. Requires the confirmed '{code} -
            # ' separator right after the code (not a bare prefix match)
            # so one code can never accidentally match as a prefix of a
            # different, longer code.
            assert entry.value is not None
            pattern = re.compile(r"^" + re.escape(runtime_text) + r"\s*-\s*")
            locator = root.locator(entry.value).filter(has_text=pattern)
        elif entry.strategy == "text_exact":
            # Bug fix (2026-08, PO-confirmed via real DOM snapshots --
            # invoice.date_field's calendar widget): unlike
            # medicine.search_result_option's unpredictable-prefix
            # problem, year/month/day cells have no such prefix/suffix
            # to worry about -- a FULL, case-insensitive match (^...$)
            # is both possible and safest. entry.value is the real,
            # confirmed CSS tag/class for the cell (e.g. "span.year",
            # "td.day:not(.old):not(.new)" -- see this entry's own
            # registry notes).
            assert entry.value is not None
            exact_pattern = re.compile(rf"^{re.escape(runtime_text)}$", re.IGNORECASE)
            locator = root.locator(entry.value).filter(has_text=exact_pattern)
        else:
            raise SelectorNotUsableError(
                f"Selector '{entry.key}' has strategy {entry.strategy!r}, which does not "
                "support runtime text parameterization."
            )
        if entry.filter_has_text is not None and not self._has_scope(entry):
            locator = locator.filter(has_text=entry.filter_has_text)
        if entry.nth is not None:
            locator = locator.nth(entry.nth)
        return locator

    def _select_option_by_domain_value(
        self, key: str, mapping_group: str, domain_value: str
    ) -> None:
        entry = self._registry.require_usable(key)
        mapping_entry = self._registry.get_value_mapping(mapping_group, domain_value)
        if not mapping_entry.is_confirmed or mapping_entry.label is None:
            raise SelectorNotUsableError(
                f"value_mappings.{mapping_group}.{domain_value} is not confirmed yet "
                f"(status={mapping_entry.status}) -- refusing to guess a dropdown label."
            )
        try:
            self._locate(entry).select_option(label=mapping_entry.label)
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"select_option:{key}", exc) from exc

    # --- internal: locator translation --------------------------------------

    def _locate(self, entry: SelectorEntry) -> Locator:
        """
        Translate a SelectorEntry into a real Playwright Locator. The
        canonical translation for this project -- kept private to this
        adapter since it is the one place production code is allowed to
        turn registry data into live Playwright calls.
        """
        root: Page | Locator = self._resolve_scope(entry)

        if entry.strategy == "css":
            assert entry.value is not None
            locator = root.locator(entry.value)
        elif entry.strategy == "title":
            assert entry.value is not None
            locator = root.get_by_title(entry.value)
        elif entry.strategy == "label":
            assert entry.value is not None
            locator = root.get_by_label(entry.value)
        elif entry.strategy == "text":
            assert entry.value is not None
            locator = root.get_by_text(entry.value, exact=bool(entry.exact))
        elif entry.strategy == "placeholder":
            assert entry.value is not None
            locator = root.get_by_placeholder(entry.value, exact=bool(entry.exact))
        elif entry.strategy == "role":
            assert entry.role is not None
            kwargs: dict[str, object] = {}
            if entry.name is not None:
                kwargs["name"] = entry.name
            if entry.description is not None:
                kwargs["description"] = entry.description
            if entry.exact is not None:
                kwargs["exact"] = entry.exact
            locator = root.get_by_role(entry.role, **kwargs)  # type: ignore[arg-type]
        else:
            raise SelectorNotUsableError(
                f"Selector '{entry.key}' has strategy {entry.strategy!r}, which is not a "
                "locatable strategy."
            )

        if entry.filter_has_text is not None and not self._has_scope(entry):
            locator = locator.filter(has_text=entry.filter_has_text)
        if entry.nth is not None:
            locator = locator.nth(entry.nth)
        return locator

    @staticmethod
    def _has_scope(entry: SelectorEntry) -> bool:
        return entry.scope_role is not None or entry.scope is not None

    def _resolve_scope(self, entry: SelectorEntry) -> Page | Locator:
        """
        Build the root a selector is queried under: a plain CSS scope, a
        role-based scope (e.g. a specific table row), or the whole page.

        When both a scope and filter_has_text are set, the filter
        narrows the SCOPE itself -- matching how the real recordings
        actually chain these calls (e.g. medicine.search_input's
        page.get_by_role("cell").filter(has_text=...).get_by_role(...),
        where "Đóng" is text inside the CELL, not inside the combobox
        found within it). filter_has_text with no scope instead narrows
        the final located element directly (e.g.
        login.close_notification_popup, where the text IS on the
        element itself) -- see _locate/_locate_parameterized's own
        filter_has_text handling for that other half of this split.
        """
        if entry.scope_role is not None:
            kwargs: dict[str, object] = {}
            if entry.scope_name is not None:
                kwargs["name"] = entry.scope_name
            scope: Locator = self._page.get_by_role(entry.scope_role, **kwargs)  # type: ignore[arg-type]
        elif entry.scope is not None:
            scope = self._page.locator(entry.scope)
        else:
            return self._page

        if entry.filter_has_text is not None:
            scope = scope.filter(has_text=entry.filter_has_text)
        return scope
        return self._page
