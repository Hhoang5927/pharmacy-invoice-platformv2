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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from playwright.sync_api import Locator, Page, expect

from pharmacy_invoice_automation.application.exceptions import TransientInfrastructureError
from pharmacy_invoice_automation.domain.constants import TAX_RATE_BY_TYPE
from pharmacy_invoice_automation.domain.entities.batch import Batch
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
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
    ManualFollowUpLineItem,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
    AutomationError,
    MedicineUnresolvableError,
    SelectorNotUsableError,
    UnitMismatchError,
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

    # Bug fix (2026-08, PO-confirmed via a real run -- CRITICAL, a false
    # "not found" here silently misroutes _resolve_supplier_on_site into
    # create_supplier() for a supplier that already exists): this used to
    # call Locator.count() -- which never waits, it just reads the DOM at
    # that exact instant -- immediately after typing, with no wait/poll
    # at all. The exact same "site needs real, non-instant settle time"
    # class of bug already fixed for the medicine search loop
    # (_poll_until_matched), just never applied here. Switching to
    # _type_into_search_box's real per-character typing (measurably
    # slower than the old .fill()) turned this from a latent gap into a
    # reliably-reproducing one -- PO reported the supplier's name typed
    # but never actually selected (no chip/selected state), followed by
    # "create_supplier succeeded" in the log, exactly what
    # _resolve_supplier_on_site's own search_supplier-false fallback
    # produces. Now polls the same way the medicine loop does.
    def search_supplier(self, name: str) -> bool:
        try:
            self._type_into_search_box("supplier.search_input", name)
            result_entry = self._registry.require_usable("supplier.search_result_option")
            return self._poll_until_matched(
                lambda: self._locate_parameterized(result_entry, name).count() > 0,
                label=f"search_supplier '{name}'",
            )
        except SelectorRegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error("search_supplier", exc) from exc

    def select_supplier(self, name: str) -> AutomationOutcome:
        def _do() -> None:
            self._type_into_search_box("supplier.search_input", name)
            result_entry = self._registry.require_usable("supplier.search_result_option")
            if not self._poll_until_matched(
                lambda: self._locate_parameterized(result_entry, name).count() > 0,
                label=f"select_supplier '{name}'",
            ):
                raise VerificationFailedError(
                    f"select_supplier: no matching 'supplier.search_result_option' ever "
                    f"appeared for '{name}' after typing -- refusing to click a result that "
                    "was never confirmed present (this method is only ever called after "
                    "search_supplier() itself already confirmed a match, so this would mean "
                    "the result disappeared again)."
                )
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
    # the web vs. the full packaging description as printed on the
    # invoice) into one field -- this strips the packaging part for web
    # search/display use ONLY, right before it is sent to the page; the
    # original field is never touched. PO also confirmed the earlier
    # suspicion that medicine.add_new_trigger itself was broken/misrouted
    # was wrong --
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

        BUG FIX #2 (2026-08, PO-confirmed via a real run -- found during
        a full-file audit for the same class of bug after it hit
        search_supplier(), see that method's own comment): this still
        checked the result count exactly ONCE, after a single fixed
        wait, rather than polling (_poll_until_matched) the way the
        candidate loop (_fill_and_check_medicine_result) and
        search_supplier() both already do. Switched to
        _type_into_search_box's real per-character typing made typing
        itself measurably slower, and this was the last remaining
        "type, then a single non-retrying check" spot for medicine.
        """
        search_name = self._strip_packaging_description(name)
        try:
            self._type_into_search_box("medicine.search_input", search_name)
            result_entry = self._registry.require_usable("medicine.search_result_option")
            return self._poll_until_matched(
                lambda: self._locate_parameterized(result_entry, search_name).count() > 0,
                label=f"search_medicine '{search_name}'",
            )
        except SelectorRegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error("search_medicine", exc) from exc

    def select_medicine(self, name: str) -> AutomationOutcome:
        # Bug fix (2026-08, found during the same audit as search_medicine's
        # own #2 above): used to type then click immediately, relying
        # solely on Locator.click()'s own generic implicit auto-wait --
        # unlike search_supplier()/select_supplier(), it never explicitly
        # confirmed the result existed first. Now polls
        # (_poll_until_matched) and raises a clear VerificationFailedError
        # if the result never appears, matching select_supplier()'s own
        # pattern -- consistent behavior/error reporting across every
        # search-as-you-type box in this file, not an implicit generic
        # Playwright timeout for this one.
        def _do() -> None:
            search_name = self._strip_packaging_description(name)
            self._type_into_search_box("medicine.search_input", search_name)
            result_entry = self._registry.require_usable("medicine.search_result_option")
            if not self._poll_until_matched(
                lambda: self._locate_parameterized(result_entry, search_name).count() > 0,
                label=f"select_medicine '{search_name}'",
            ):
                raise VerificationFailedError(
                    f"select_medicine: no matching 'medicine.search_result_option' ever "
                    f"appeared for '{search_name}' after typing -- refusing to click a result "
                    "that was never confirmed present."
                )
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
        STRATEGY CHANGE (2026-08, PO decision -- REPLACES the Vien
        retail-unit-conversion design entirely, see
        _verify_unit_matches_invoice's own docstring for the full
        mechanism): Vien conversion (_convert_to_retail_units, now
        removed) is no longer used anywhere in this method. Phase 1
        below fills each item's own ORIGINAL invoice quantity/unit_price
        verbatim -- no multiplication/division by any packaging ratio --
        but only after verifying, for real, that the site's own
        currently-displayed unit for this row genuinely matches
        item.unit; a mismatch stops this line (and so this whole
        invoice, per the existing "one invoice, all-or-nothing" outcome
        contract) with a clear reason instead of ever guessing a
        conversion. _update_retail_prices_after_save similarly now
        feeds item.unit_price directly into PricePolicy, unconverted.

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

        Phase 1 (search + unit verification + quantity/price/VAT), once
        per line, in invoice order: search+select this line's medicine
        (see _search_and_select_medicine_for_line), verify the site's
        own displayed unit matches item.unit (see
        _verify_unit_matches_invoice), fill the shared quantity/price/
        VAT set with the invoice's own original values, then click
        invoice_line.add_row_button to confirm this line and advance --
        revealing a fresh set for the next one.

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

        # Deviation D11 (PO-confirmed 2026-08): populated by _do() below when
        # one or more lines are skipped -- read back after _run_outcome
        # returns, since _run_outcome's own Callable[[], None] contract
        # (shared by every other method in this file) has no return value
        # to carry this through.
        manual_followups: list[ManualFollowUpLineItem] = []

        def _do() -> None:
            self._fill("invoice.number_field", invoice.invoice_number)
            self._fill_invoice_date_and_verify(invoice.invoice_date)
            supplier = self._resolve_invoice_supplier(invoice)

            # Deviation D11 (PO-confirmed 2026-08): site rows are no longer
            # guaranteed 1:1 with invoice.items position -- a line whose
            # medicine is genuinely unresolvable is skipped (no row ever
            # created for it) rather than aborting the whole invoice.
            # site_positions maps invoice.items index -> 1-based site row
            # position, tracking only rows that actually got created, so
            # every downstream row-indexed step (Phase 2 batch fill, the
            # post-save retail-price edit) addresses the real site row
            # instead of the Python-list position.
            site_positions: dict[int, int] = {}
            site_row_count = 0
            for index, item in enumerate(invoice.items):
                # Deviation D11: both _search_and_select_medicine_for_line's
                # own "is this the very first row on a fresh form" check and
                # _verify_unit_matches_invoice's row lookup need the site's
                # own actually-committed row count (site_row_count, before
                # this item's own increment below) -- NOT the raw
                # invoice.items list position, which can now run ahead of
                # the real site once an earlier line has been skipped.
                try:
                    self._search_and_select_medicine_for_line(item, site_row_count, supplier)
                except MedicineUnresolvableError as exc:
                    self._logger.error(
                        "fill_and_save_invoice: line %d (%s) could not be resolved on-site "
                        "by any automated means (%s) -- skipping this line, invoice will "
                        "still be saved without it.",
                        index + 1,
                        item.medicine_name,
                        exc,
                    )
                    manual_followups.append(
                        ManualFollowUpLineItem(
                            line_position=index + 1,
                            medicine_name=item.medicine_name,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                        )
                    )
                    continue
                self._verify_unit_matches_invoice(item, site_row_count)
                quantity_to_fill, unit_price_to_fill = self._quantity_and_price_for_fill(item)
                self._fill("invoice_line.quantity_field", str(quantity_to_fill))
                self._fill("invoice_line.unit_price_field", str(unit_price_to_fill))
                if item.tax_type is not None:
                    self._fill("invoice_line.vat_field", self._format_tax_percentage(item.tax_type))
                self._click("invoice_line.add_row_button")
                site_row_count += 1
                self._wait_for_row_settled(site_row_count + 1)
                site_positions[index] = site_row_count

            if invoice.items and not site_positions:
                raise AutomationError(
                    "fill_and_save_invoice: every line item failed medicine resolution -- "
                    "nothing to save."
                )

            for index, item in enumerate(invoice.items):
                if index not in site_positions or item.batch_id is None:
                    continue
                self._click_batch_edit_button_for_row(site_positions[index])
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
            # edit flow AFTER the first save. Nothing to update on a
            # genuinely empty invoice or one where every line was skipped
            # (the latter already raised above, but an empty invoice.items
            # reaches here with site_positions also empty and is not itself
            # an error).
            if site_positions:
                self._update_retail_prices_after_save(invoice, site_positions)
                self._click("invoice.save_button")
                self._verify_saved()

        outcome = self._run_outcome("fill_and_save_invoice", _do)
        if outcome.success and manual_followups:
            return replace(outcome, manual_followup_items=tuple(manual_followups))
        return outcome

    @staticmethod
    def _format_tax_percentage(tax_type: TaxType) -> str:
        """
        BUG FIX (2026-08, PO-confirmed via a real DB row -- CRITICAL,
        found while investigating a "VAT never appears on the real
        site" report): the Phase 1 loop used to fill
        invoice_line.vat_field with ``item.tax_type.value`` directly --
        but that is the Domain enum's own string label (e.g.
        ``"reduced"``), never a percentage number. invoice_line.vat_field's
        own registry notes confirm it is "a plain text input filled
        with a percentage number (e.g. '5')", not a dropdown -- so the
        real site almost certainly rejected/cleared the literal text
        "reduced", exactly matching what was observed (VAT reads empty
        on the real site despite this fill genuinely running --
        item.tax_type was NOT None on the real invoice row that
        triggered this investigation).

        Converts via the already-established
        domain.constants.TAX_RATE_BY_TYPE (the SAME mapping
        domain.services.tax_calculation_service.TaxCalculationService
        already uses for tax math) -- never a new/invented mapping.
        TAX_RATE_BY_TYPE stores a fraction (e.g. Decimal("0.05")); this
        multiplies by 100 and formats without a forced decimal point
        ("5", not "5.00" or "5E+1") -- every current rate is an exact
        whole percentage, but this also degrades safely to a real
        fractional string (e.g. "8.5") rather than silently rounding,
        should a future rate ever not be one.
        """
        percentage = TAX_RATE_BY_TYPE[tax_type.value] * 100
        formatted = format(percentage, "f")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted

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

        if not self._fill_and_check_medicine_result_tolerant(search_key, search_name):
            # Deviation D11 (PO-confirmed 2026-08): both failure modes below
            # mean this line's medicine has genuinely exhausted every
            # automated resolution option -- raised as MedicineUnresolvableError
            # (not a plain AutomationError) so fill_and_save_invoice's
            # per-line loop can skip only this one line and keep going,
            # instead of aborting the whole invoice. Deliberately scoped to
            # just this block -- the ambiguous-match human-selection path
            # below (_disambiguate_via_human_selection) still raises a plain
            # VerificationFailedError and still hard-aborts, unchanged.
            try:
                self._create_medicine_for_line(item)
            except AutomationError as exc:
                raise MedicineUnresolvableError(
                    f"Medicine '{item.medicine_name}' could not be created on-site: {exc}"
                ) from exc
            if not self._fill_and_check_medicine_result_tolerant(search_key, search_name):
                raise MedicineUnresolvableError(
                    f"Medicine '{item.medicine_name}' (searched as '{search_name}') still has "
                    "no matching search result immediately after create_medicine() -- cannot "
                    "select it for this invoice line."
                )

        result_entry = self._registry.require_usable("medicine.search_result_option")
        self._log_medicine_result_position(result_entry, search_name)
        matches = self._locate_parameterized(result_entry, search_name)
        if matches.count() > 1:
            self._disambiguate_via_human_selection(search_key, matches, item, supplier)
            return

        self._click_parameterized("medicine.search_result_option", search_name)
        self._page.wait_for_timeout(self._MEDICINE_SELECTION_SETTLE_MS)

    def _log_medicine_result_position(self, entry: SelectorEntry, runtime_text: str) -> None:
        """
        DIAG (2026-08, PO's own real observation during a live run:
        typing "Coldi" showed the dropdown in a different row order than
        prior runs -- "Coldi" moved from row 3-4 to row 1 -- and PO
        suspected this reordering might explain a click failure).

        By design, _locate_parameterized's 'text_ends_with' strategy is
        a pure CONTENT filter (Locator.filter(has_text=...)) applied to
        every currently-matching element -- it is never indexed by
        position, so a row's on-screen/DOM order should have no effect
        on which element gets clicked. This method exists only to make
        that verifiable from a real run's own log rather than asserted
        from code-reading alone: it records the 0-based index (current
        DOM order) of whichever result(s) end with ``runtime_text``
        among ALL results present at this exact moment, purely for
        later correlation against any selection failure. Read-only --
        never used to decide what gets clicked; the real click a few
        lines below still goes through the exact same content-filtered
        Locator it always has.
        """
        if entry.value is None:
            return
        root = self._resolve_scope(entry)
        all_texts = root.locator(entry.value).all_inner_texts()
        pattern = re.compile(re.escape(runtime_text) + r"$", re.IGNORECASE)
        matched_indexes = [i for i, text in enumerate(all_texts) if pattern.search(text)]
        self._logger.info(
            "DIAG vi tri ket qua thuoc '%s': index (0-based)=%s trong tong %d ket qua "
            "hien co.",
            runtime_text,
            matched_indexes,
            len(all_texts),
        )

    def _verify_unit_matches_invoice(self, item: PurchaseItem, index: int) -> None:
        """
        STRATEGY CHANGE (2026-08, PO decision -- REPLACES Vien retail-
        unit conversion entirely): the site's own purchase unit for a
        just-selected medicine is not guaranteed to match this
        invoice's own stated unit (item.unit) -- Naphacogyl's real
        catalog entry surfaced exactly this: the site already had "Hop"
        while a different invoice's own reading assumed something else.
        Converting through an assumed/looked-up packaging ratio (the
        old Vien-conversion design) risked silently entering a WRONG
        quantity/price if that assumption was ever wrong -- unacceptable
        per the Automation business rule that automation never invents
        or guesses a value. The new rule instead: read the site's own
        displayed unit for this row FOR REAL, right after selecting the
        medicine and before filling anything else, and only proceed
        with the invoice's own original (unconverted) quantity/price if
        it genuinely matches. A mismatch stops here with a clear reason
        -- never silently converted, never silently ignored.

        invoice_line.unit_display (2026-08, PO direct DOM inspection,
        real snapshot of invoice 00001567's Naphacogyl line -- see that
        entry's own registry notes): a standard native <select
        ng-model="gridItem.SelectedUnitId">, NOT page-wide-unique --
        one per row, same ng-repeat structure already established for
        invoice_line.select_row_for_batch_button's own trigger. ``index``
        (this item's 0-based position in invoice.items, matching
        _click_batch_edit_button_for_row's own 1-based
        position - 1) scopes it via _line_item_rows().nth(index), the
        exact same row-scoping mechanism already used there -- the
        currently-active (not-yet-committed) row's own <tbody> already
        exists by this point (the table always carries one "trailing"
        not-yet-settled tbody ahead of the committed count, per
        _wait_for_row_settled's own "+1 trailing empty row" comment),
        so this is safe to read before add_row_button is ever clicked
        for this line. Reads the currently-selected <option>'s own text
        ('option:checked') -- deliberately NOT Locator.input_value(),
        which for a <select> returns the raw internal option value
        (e.g. 'number:1111713'), never the display label ('Hộp') this
        compares against.

        Both this selector and the expected display text
        (value_mappings.unit_display_label) must be 'confirmed' before
        this method will trust anything it reads -- 'hop' is confirmed
        from this same real snapshot, but any OTHER unit code (e.g.
        'vien') is still 'needs_verification' against the real
        registry, so a line using one of those still raises a clean
        SelectorNotUsableError rather than guessing, exactly like
        invoice.commercial_discount_field's own still-unconfirmed gate
        elsewhere in this method.

        Reviewer-confirmed override (PO decision, 2026-08 -- "Coldi-B
        DNH": 1 Hop trên hóa đơn = 1 Lọ trên web is a genuine, correct
        naming difference, not a bug): when
        item.confirmed_website_unit_ratio is already set, a reviewer
        has already confirmed this exact line's invoice-unit-to-
        website-unit ratio (see SubmitInvoiceReviewUseCase's own
        "item.<id>.confirmed_website_unit_ratio" field), so the site's
        displayed unit LABEL no longer needs to match item.unit's own
        label -- this method trusts the confirmed ratio and returns
        immediately, without even reading the site's displayed unit.
        fill_and_save_invoice applies the ratio to quantity/price
        itself. Only reached the FIRST time a line's site unit turns
        out to differ (no ratio confirmed yet) does this still raise --
        now UnitMismatchError instead of a generic
        VerificationFailedError, so composition_root.cli.run_automate
        can print a specific, actionable message pointing the operator
        at the review step instead of a generic "unexpected error."
        """
        if item.confirmed_website_unit_ratio is not None:
            return
        entry = self._registry.require_usable("invoice_line.unit_display")
        mapping_entry = self._registry.get_value_mapping("unit_display_label", item.unit.code)
        if not mapping_entry.is_confirmed or mapping_entry.label is None:
            raise SelectorNotUsableError(
                f"value_mappings.unit_display_label.{item.unit.code} is not confirmed yet "
                f"(status={mapping_entry.status}) -- refusing to guess whether the site's "
                f"displayed unit matches invoice item '{item.medicine_name}''s own unit "
                f"('{item.unit.code}')."
            )
        assert entry.value is not None
        select_locator = self._line_item_rows().nth(index).locator(entry.value)
        displayed_unit = select_locator.locator("option:checked").inner_text().strip()
        if displayed_unit != mapping_entry.label:
            raise UnitMismatchError(
                medicine_name=item.medicine_name,
                purchase_item_id=item.id,
                invoice_unit_label=mapping_entry.label,
                website_unit_label=displayed_unit,
            )

    def _quantity_and_price_for_fill(self, item: PurchaseItem) -> tuple[Decimal, Decimal]:
        """
        This line's own invoice quantity/price, verbatim, UNLESS a
        reviewer has confirmed a website-unit ratio for it (see
        _verify_unit_matches_invoice's own docstring) -- in which case
        quantity is scaled by that ratio and unit price scaled
        inversely, so the line's total value (quantity x unit price)
        is preserved. "1 invoice unit = ratio website units," so N
        invoice units of quantity becomes N x ratio website units, each
        at 1/ratio the invoice's own per-unit price -- e.g. Coldi-B
        DNH's ratio of 1 leaves both figures unchanged, matching "1 Hop
        = 1 Lọ" being a pure naming difference, not a real quantity
        conversion.
        """
        if item.confirmed_website_unit_ratio is None:
            return item.quantity.amount, item.unit_price.amount
        ratio = item.confirmed_website_unit_ratio
        return item.quantity.amount * ratio, item.unit_price.amount / ratio

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
        code = self._read_selected_medicine_code()
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
    # TEMPORARY DIAGNOSTIC (2026-08): kept per PO's own explicit request,
    # to self-confirm the corrected locating method below (medicine.drug_search_box
    # + filter-by-chip-presence) before removing this. Logs the raw
    # per-tick values, throttled to avoid flooding.
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
        TWO SEPARATE, SEQUENTIAL expect() calls -- fixed by polling both
        together every tick across the FULL configured timeout (see git
        history of this method for the full incident). PO then RULED
        OUT this theory entirely via a second real dry-run (correct
        browser window, waited the full 180s, still failed) and a
        temporary diagnostic log proved aria-expanded flipped correctly
        every time while the chip locator matched 0 elements FOREVER --
        a pure locator bug, not a timing one.

        BUG FIX #2 (2026-08, PO-confirmed via real DOM inspection of the
        actual line-item table -- CRITICAL, wrong anchor entirely): the
        chip was never actually a sibling of the search input at all --
        that assumption was copied from the SUPPLIER field's structure
        (a page-wide-unique widget) without verifying the MEDICINE
        line-item table's own structure, which is different: each row's
        widget lives inside its own 'medicine.drug_search_box'
        (#drugSearchBoxId) container, rendered only while that row is
        being edited (ng-if="gridItem.IsEditingItem") -- and PO confirmed
        this id is NOT page-wide-unique either (can repeat across
        concurrently-editing rows, count observed as high as 2). Fixed
        by filtering that container set down to whichever ONE element
        actually contains the chip (_selected_match_container_locator),
        never assuming a fixed position/count -- see that method and
        medicine.drug_search_box's own registry notes for the full
        evidence trail.

        Raises VerificationFailedError -- never silently continues, never
        guesses a row -- if both conditions are never observed true
        together within the timeout, OR immediately if more than one
        drug_search_box element simultaneously contains a chip (an
        unexpected state this project refuses to resolve by guessing
        which one is "this" row's).
        """
        entry = self._registry.require_usable(search_key)
        input_locator = self._locate(entry)
        deadline = time.monotonic() + (self._config.human_disambiguation_timeout_ms / 1000)
        next_diagnostic_log_at = time.monotonic()
        while True:
            aria_expanded = self._safe_get_attribute(input_locator, "aria-expanded")
            matching_container_count = self._safe_locator_count(
                self._selected_match_container_locator()
            )
            if matching_container_count > 1:
                raise VerificationFailedError(
                    "Part 3: found "
                    f"{matching_container_count} 'medicine.drug_search_box' elements "
                    "simultaneously containing a selected-match chip -- cannot tell which one "
                    "is this line's own row. Refusing to guess -- this is an unexpected state, "
                    "not a normal 'still waiting' one."
                )
            if aria_expanded == "false" and matching_container_count == 1:
                return
            now = time.monotonic()
            if now >= next_diagnostic_log_at:
                self._logger.info(
                    "Part 3 DIAGNOSTIC: aria-expanded=%r, drug_search_box elements containing "
                    "a chip=%r",
                    aria_expanded,
                    matching_container_count,
                )
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

    @staticmethod
    def _safe_get_attribute(locator: Locator, name: str) -> str | None:
        """Non-raising attribute read for the poll loop -- a transient Playwright error
        (e.g. the element briefly detached mid-digest) is treated as "value unknown yet",
        not a hard failure."""
        try:
            return locator.get_attribute(name)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _safe_locator_count(locator: Locator) -> int:
        """Non-raising count read for the poll loop -- same "transient error means keep
        polling" contract as _safe_get_attribute."""
        try:
            return locator.count()
        except Exception:  # noqa: BLE001
            return 0

    def _selected_match_container_locator(self) -> Locator:
        """
        Locates the ONE medicine.drug_search_box (#drugSearchBoxId)
        element that currently contains a medicine.selected_match_chip.
        NOT scoped by row position/index -- PO confirmed
        #drugSearchBoxId repeats across concurrently-editing rows (not
        page-wide-unique, and its own count is not stable), and there is
        no reliable way for this method to predict which numeric
        position corresponds to "this" row's own widget. Filtering by
        which container actually HAS a chip instead is robust to that:
        whichever row a human just finished selecting for is the one
        that will match, regardless of how many other rows happen to be
        open/edited at the same moment.
        """
        drug_search_box_entry = self._registry.require_usable("medicine.drug_search_box")
        chip_entry = self._registry.require_usable("medicine.selected_match_chip")
        assert drug_search_box_entry.strategy == "css" and drug_search_box_entry.value is not None
        assert chip_entry.strategy == "css" and chip_entry.value is not None
        return self._page.locator(drug_search_box_entry.value).filter(
            has=self._page.locator(chip_entry.value)
        )

    def _read_selected_medicine_code(self) -> str:
        """
        Reads the real site's own SDK code back from the now-confirmed
        selected-match chip's own nested code-label element
        (medicine.selected_match_chip_code_label -- deliberately NOT the
        chip's own inner_text(), which also contains its close button's
        '×'), whose text is '{code} - {tên thuốc}' (PO-confirmed real
        snapshot -- same shape medicine.search_result_option_by_code
        already relies on) -- the part before the first ' - '. Located
        via _selected_match_container_locator (filter-by-content), not
        relative to any specific row's search input -- see that method's
        own docstring for why a position/index-based approach was
        rejected.
        """
        chip_entry = self._registry.require_usable("medicine.selected_match_chip")
        code_label_entry = self._registry.require_usable("medicine.selected_match_chip_code_label")
        assert chip_entry.strategy == "css" and chip_entry.value is not None
        assert code_label_entry.strategy == "css" and code_label_entry.value is not None
        container = self._selected_match_container_locator()
        container_count = container.count()
        if container_count != 1:
            raise VerificationFailedError(
                "Part 3: expected exactly 1 'medicine.drug_search_box' element containing a "
                f"selected-match chip when reading back its code, found {container_count}. "
                "Refusing to guess which one is this line's own row."
            )
        chip_text = container.locator(chip_entry.value).locator(code_label_entry.value)
        chip_text_value = chip_text.inner_text().strip()
        code = chip_text_value.split(" - ", 1)[0].strip()
        if not code:
            raise VerificationFailedError(
                f"Part 3: could not parse a website catalog code from the selected chip's own "
                f"text ('{chip_text_value}')."
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

    # BUG FIX round 2 (2026-08, PO-confirmed via real hands-on testing,
    # AFTER a full 8000ms/33-check poll proved both 'Coldi-B DNH' and
    # word-truncated 'Coldi-B' genuinely matched=False -- not a timing
    # issue): the real boundary PO separately confirmed by hand is
    # MID-WORD, not at a word boundary -- typing 'Coldi-' (stopping
    # right at the hyphen, before the trailing 'B') produced a real
    # dropdown match; word-level truncation alone can never reach that
    # string. Floor for the character-by-character fallback below --
    # short enough to reach real mid-word thresholds like 'Coldi-' (6
    # chars), long enough to avoid a near-empty query surfacing
    # unrelated noise.
    _MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH = 4

    @classmethod
    def _medicine_search_fill_candidates(cls, search_name: str) -> list[str]:
        """
        BUG FIX (2026-08, PO-confirmed via real hands-on testing): the
        real site's search-as-you-type is apparently sensitive to the
        LENGTH of the typed string in a not-fully-understood way --
        typing the FULL 'Coldi-B DNH' (11 chars) produced NO dropdown
        at all, while typing just 'Coldi-B' (7 chars) did, correctly
        showing 'Coldi-B DNH' among the results. Not treated as a
        one-off special case for this specific name -- any sufficiently
        long medicine name could plausibly hit the same real, unknown
        threshold. Returns the full name first, then progressively
        SHORTER word-truncated prefixes (dropping one trailing word at
        a time, e.g. 'Coldi-B DNH' -> 'Coldi-B').

        Round 2 (see _MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH's own
        comment): word-level truncation alone was proven, by a real
        33-check/8000ms poll, insufficient for some names -- the real
        threshold can sit MID-WORD (e.g. 'Coldi-', not 'Coldi-B'). Once
        word-level truncation is exhausted, continues shortening the
        final (shortest) word-level candidate one CHARACTER at a time
        down to _MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH. This is
        safe regardless of how short it gets: the candidates returned
        here only ever decide what gets TYPED to make a dropdown
        appear -- which row is actually SELECTED is always resolved
        separately, by an end-anchored match against the full,
        untruncated search_name (see _fill_medicine_search_until_matched
        and text_ends_with's own comment), never against whichever
        candidate happened to trigger the dropdown.
        """
        words = search_name.split()
        candidates = [search_name]
        for word_count in range(len(words) - 1, 0, -1):
            candidates.append(" ".join(words[:word_count]))
        shortest = candidates[-1]
        for length in range(
            len(shortest) - 1, cls._MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH - 1, -1
        ):
            candidates.append(shortest[:length])
        return candidates

    # Bug fix (2026-08, PO-confirmed via real diagnostic logging, THEN a
    # real hands-on live-site experiment that found the true root cause):
    # a real run's own per-candidate DIAG log proved "Coldi-B" -- a
    # candidate PO separately, manually confirmed DOES produce a real
    # match when typed into an EMPTY box -- was genuinely tried (not
    # skipped) but still read back matched=False. Two distinct gaps,
    # both closed together:
    # (1) ROOT CAUSE (PO's own live experiment): typing "Coldi-" character
    # by character on the real site worked; PASTING the identical text
    # did not; typing "Coldi-b" then Backspacing the 'b' worked. The site
    # only reacts to genuine keyboard events, not to a box's value being
    # set programmatically. Playwright's .fill() (and .clear()) do
    # exactly that -- set the value directly, the same mechanism as a
    # paste, no keydown/keyup at all -- so a candidate could look
    # correctly typed in the DOM afterward while never having triggered a
    # real search. Every candidate now goes through _type_into_search_box
    # (see its own docstring) instead -- select-all+Backspace to clear,
    # then press_sequentially, a real per-character keystroke simulation.
    # (2) is_match() was checked exactly ONCE, at a single fixed offset
    # (_MEDICINE_SELECTION_SETTLE_MS after the fill) -- a real async
    # response landing even slightly after that one offset would read as
    # a false "not matched" despite the candidate being genuinely valid,
    # exactly the failure the DIAG log caught. _poll_until_matched now
    # checks repeatedly across that same total budget (see its own
    # docstring) instead of gambling on one instant.
    #
    # Merge note (2026-08, resolving feature/medicine-disambiguation-parts-2-3
    # into main): that branch independently fixed the exact same race
    # condition via a different, since-superseded mechanism (a plain
    # .fill() + expect().not_to_have_count(0, timeout=5_000) poll,
    # _MEDICINE_SEARCH_CANDIDATE_TIMEOUT_MS). Dropped in favor of the
    # version above -- _type_into_search_box's real keystroke simulation
    # is a deeper fix (.fill() was proven, via the real hands-on test
    # above, to not reliably trigger the site's own search-as-you-type at
    # all, not just to be checked too early), and _poll_until_matched's
    # shared _SEARCH_RESULT_POLL_BUDGET_MS (8s, PO-decided generous
    # ceiling) already exceeds that branch's 5s. Its other real,
    # non-redundant contribution -- proving the poll genuinely waits out
    # a settle delay for a FALLBACK (shortened) candidate specifically,
    # not just the first full-name search -- is preserved as
    # test_waits_through_a_real_settle_delay_before_the_fallback_dropdown_appears
    # in TestMedicineSearchLengthFallback below, ported onto
    # medicine_search_settle_delay_ms (this file's own later, more
    # realistic per-keyup debounce simulation, added after that branch
    # diverged) instead of its own simpler search_dropdown_delay_ms.
    def _fill_medicine_search_until_matched(
        self, search_key: str, search_name: str, match_locator: Locator
    ) -> bool:
        """
        Fills ``search_key`` with progressively shorter candidates (see
        _medicine_search_fill_candidates's own docstring) until
        ``match_locator`` reports at least one real result against the
        resulting dropdown, or every candidate has been tried. Whichever
        candidate last succeeds is left typed into the box -- the
        caller's own subsequent lookup/click against the FULL,
        untruncated ``search_name`` (never the possibly-truncated
        candidate that merely triggered the dropdown) is what actually
        determines which row is correct, so a truncated search
        surfacing multiple unrelated candidates is still resolved to
        the exact right one (or correctly flagged ambiguous) -- never a
        guess based on the truncated text alone.

        BUG FIX (2026-08, PO-confirmed via real hands-on testing --
        CRITICAL, race condition): PO directly observed the automation
        correctly typing the shorter fallback candidate ("Coldi-B"),
        but no dropdown ever appeared -- even though PO's own SLOWER,
        manual typing of the exact same text did produce one. Root
        cause: this originally waited a FIXED _MEDICINE_SELECTION_SETTLE_MS
        then checked ONCE -- Playwright's fill() sets the whole string
        virtually instantly (a single 'input' event), unlike a human
        typing character by character, and the site's own search-as-
        you-type (Angular digest cycle and/or debounce) can genuinely
        need more real, non-instant time than one fixed wait gives it --
        the same root-cause class already fixed for _wait_for_row_settled
        and Part 3's combined poll. Each candidate now gets its own real
        poll (Playwright's own expect().not_to_have_count(0), up to
        _MEDICINE_SEARCH_CANDIDATE_TIMEOUT_MS) instead of a fixed wait
        followed by a single immediate check.
        """
        for candidate in self._medicine_search_fill_candidates(search_name):
            self._type_into_search_box(search_key, candidate)
            matched = self._poll_until_matched(
                lambda: match_locator.count() > 0,
                label=f"candidate '{candidate}' (goc '{search_name}')",
            )
            # Per-candidate proof, not just the aggregate click log: golden
            # tests assert on this exact "matched=True/False" line to prove
            # the poll genuinely fired for each candidate actually tried
            # (see TestFullSupplierAndThreeMedicineFlow's own comment) --
            # kept as real test evidence, not incidental debug noise.
            self._logger.info(
                "DIAG: candidate rut ngan '%s' (goc: '%s') -> matched=%s",
                candidate,
                search_name,
                matched,
            )
            if matched:
                return True
        return False

    _MEDICINE_SELECTION_POLL_INTERVAL_MS = 250

    # Strategy decision (2026-08, PO-confirmed -- ends a 4-5 round chain
    # of chasing individually-different real timings for this same
    # symptom: "Coldi-B", then "search_supplier", then "search_medicine/
    # select_medicine", then "Coldi immediately after a heavy Naphacogyl
    # disambiguation" -- each fixed a real, distinct gap, yet a new one
    # kept surfacing). PO's own explicit call: this is real network
    # traffic to a real, live production server -- there is no fixed
    # number that is provably "exactly enough" for every real response
    # time, and chasing an ever-more-precise one has already cost
    # several rounds without ever reaching a number PO can trust for
    # good. Two independent pieces of real evidence back this: (1) the
    # site's own widget carries a `refresh-delay="500"` attribute
    # (observed directly in an earlier real DOM snapshot), meaning the
    # SITE ITSELF documents that its own results can take real,
    # variable time to refresh; (2) switching from Playwright's instant
    # .fill() to real per-character typing (_type_into_search_box,
    # required -- proven correct for "Coldi-B DNH", see that method's
    # own comment) means the total time until a real response comes
    # back is now genuinely coupled to real network/server conditions
    # at the moment of each run, not a locally-controlled constant the
    # way .fill() used to make it feel.
    #
    # New governing principle from here on: GENEROUS on wait time,
    # STRICT on verification. This budget is deliberately large (8s,
    # roughly 3x the previous 2.5s) -- but nothing about is_match()'s
    # own contract changes: a candidate is never accepted without a
    # real matched=True, and a candidate that never matches within this
    # full budget still fails cleanly (AutomationError/
    # VerificationFailedError, exactly as before) -- never a silent
    # guess either way. A generous ceiling that is only ever paid when
    # something is genuinely slow or absent (the poll always returns the
    # instant a real match appears, per _poll_until_matched's own
    # contract) is a safe trade -- it can never cause a WRONG
    # selection, only a slower-to-fail one in the genuinely-absent case.
    #
    # Do not "optimize" this number further without new real evidence
    # (an actual observed real-run timeout that still failed at 8s, or a
    # real complaint about total run time). It is deliberately generous,
    # not precisely measured -- searching for a more "exact" value here
    # is the same unproductive chase this comment exists to end.
    #
    # Scoped ONLY to _poll_until_matched (the real "is the search result
    # here yet" wait) -- deliberately NOT the same constant as
    # _MEDICINE_SELECTION_SETTLE_MS (2.5s), which is a DIFFERENT, already
    # decided concern: a fixed wait for Angular to finish binding a row's
    # own display AFTER a click that already succeeded (see that
    # constant's own comment) -- inflating that one too would add real,
    # multiplied-per-line wait time to every already-successful
    # selection for no evidenced benefit, unlike this one which is only
    # ever paid in the slow/absent case.
    _SEARCH_RESULT_POLL_BUDGET_MS = 8_000

    def _poll_until_matched(self, is_match: Callable[[], bool], *, label: str = "") -> bool:
        """
        Polls ``is_match()`` every _MEDICINE_SELECTION_POLL_INTERVAL_MS
        until it reports True, or a total of
        _SEARCH_RESULT_POLL_BUDGET_MS has elapsed -- see that constant's
        own comment for why it is deliberately generous rather than
        precisely tuned. No confirmed "search settled" selector exists
        yet to poll against directly the way _wait_for_row_settled polls
        a real <tbody> count, so this samples is_match() repeatedly
        across the budget instead of checking once at a fixed offset. A
        single fixed-offset check is a real race: the DIAG log this fix
        originally responded to proved a genuinely-valid candidate
        ('Coldi-B') can still read matched=False if the site's async
        response lands even slightly after that one check. Returns as
        soon as a match appears (never waits out the rest of the budget
        once found), and returns False only after the full budget has
        been sampled with no match -- verification itself never gets
        looser just because the budget got wider.

        DIAG instrumentation (2026-08, PO-confirmed via a real run --
        "Coldi" read matched=False through this SAME, already-polling
        method, immediately after a heavy "Naphacogyl" human-
        disambiguation had just succeeded through the identical code
        path): logs the REAL elapsed time and check COUNT this call
        actually consumed, not just the final True/False -- needed to
        tell apart "the full budget genuinely ran out, still nothing"
        (a real settle-time/budget question) from "far fewer checks ran
        than the interval implies" (each individual is_match() call
        itself was slow -- e.g. the page still busy right after a heavy
        prior operation -- eating the budget in a couple of long checks
        instead of many fast ones). ``label`` identifies which call
        site/candidate this poll belongs to, since multiple call sites
        now share this one method.
        """
        elapsed_ms = 0
        attempts = 0
        tag = f" [{label}]" if label else ""
        while True:
            attempts += 1
            if is_match():
                self._logger.info(
                    "DIAG poll%s: matched=True after %dms elapsed, %d check(s).",
                    tag,
                    elapsed_ms,
                    attempts,
                )
                return True
            if elapsed_ms >= self._SEARCH_RESULT_POLL_BUDGET_MS:
                self._logger.info(
                    "DIAG poll%s: matched=False, gave up after the full %dms budget, "
                    "%d check(s) total.",
                    tag,
                    elapsed_ms,
                    attempts,
                )
                return False
            step_ms = min(
                self._MEDICINE_SELECTION_POLL_INTERVAL_MS,
                self._SEARCH_RESULT_POLL_BUDGET_MS - elapsed_ms,
            )
            self._page.wait_for_timeout(step_ms)
            elapsed_ms += step_ms

    def _fill_and_check_medicine_result(self, search_key: str, search_name: str) -> bool:
        """Fill one line's own search box and report whether a name-anchored match exists,
        retrying with shorter prefixes if the full name alone finds nothing."""
        result_entry = self._registry.require_usable("medicine.search_result_option")
        match_locator = self._locate_parameterized(result_entry, search_name)
        return self._fill_medicine_search_until_matched(search_key, search_name, match_locator)

    def _fill_and_check_medicine_result_tolerant(self, search_key: str, search_name: str) -> bool:
        """
        PO decision (2026-08, real "Coldi" incident, explicit speed-over-
        caution tradeoff): a genuine Playwright TECHNICAL failure while
        searching (TransientInfrastructureError -- e.g. a real timeout
        somewhere in the search box's own type/poll sequence, distinct
        from a normal zero-result poll which _fill_and_check_medicine_result
        already reports as a plain `False`) is now treated identically to
        a zero-result search: both fall straight through to
        _search_and_select_medicine_for_line's own create_medicine()
        fallback immediately, no pause to ask. PO has explicitly accepted
        the resulting real duplicate-catalog-entry risk (periodic manual
        catalog audit instead of blocking automation on it) -- see this
        task's own report. Distinct from _create_medicine_for_line's own
        failure handling, which is unchanged: only create_medicine()
        itself failing still reaches MedicineUnresolvableError.
        """
        try:
            return self._fill_and_check_medicine_result(search_key, search_name)
        except TransientInfrastructureError:
            return False

    def _fill_and_check_medicine_result_by_code(
        self, search_key: str, search_name: str, website_catalog_code: str
    ) -> bool:
        """Fill one line's own search box (by name) and report whether a code-anchored match
        exists, retrying with shorter prefixes if the full name alone finds nothing."""
        result_entry = self._registry.require_usable("medicine.search_result_option_by_code")
        match_locator = self._locate_parameterized(result_entry, website_catalog_code)
        return self._fill_medicine_search_until_matched(search_key, search_name, match_locator)

    def _create_medicine_for_line(self, item: PurchaseItem) -> None:
        """
        Create a catalog entry for a line's medicine that a real,
        zero-result search just proved does not exist on-site yet.
        item.medicine_id is trusted as already-resolved (same as
        item.batch_id for _resolve_batch -- resolved upstream by the
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
        # Bug fix (2026-08, PO-confirmed, real "Coldi" incident): D11's
        # per-line safety net only ever caught AutomationError here, but
        # wrap_playwright_error classifies EVERY Playwright timeout --
        # including create_medicine()'s own medicine.add_new_trigger click
        # not becoming clickable in time -- as TransientInfrastructureError
        # regardless of which action timed out, and create_medicine()'s own
        # _run_outcome deliberately re-raises that type (so a genuinely
        # transient failure elsewhere still reaches Application's
        # RetryPolicy). With no retry actually wired up around
        # fill_and_save_invoice at the call site (composition_root.cli.
        # run_automate), that exception was escaping this method uncaught
        # and _search_and_select_medicine_for_line's own
        # "except AutomationError" below, hard-aborting the whole invoice
        # instead of skipping just this one line -- exactly the gap this
        # incident exposed. Converting it to AutomationError here reuses
        # the exact same "create_medicine failed" path as an
        # outcome.success=False failure below, so both failure modes reach
        # MedicineUnresolvableError identically.
        try:
            outcome = self.create_medicine(medicine)
        except TransientInfrastructureError as exc:
            raise AutomationError(
                f"create_medicine failed for '{item.medicine_name}': {exc}"
            ) from exc
        if not outcome.success:
            raise AutomationError(
                f"create_medicine failed for '{item.medicine_name}': {outcome.failure_reason}"
            )

    # --- internal: suggested retail price (post-save edit flow) ---------------

    def _update_retail_prices_after_save(
        self, invoice: PurchaseInvoice, site_positions: Mapping[int, int]
    ) -> None:
        """
        ``site_positions`` (Deviation D11, PO-confirmed 2026-08): maps
        invoice.items index -> 1-based site row position, as built by
        fill_and_save_invoice's own Phase 1 loop. Only items present in
        this mapping actually have a row on-site to edit -- a line skipped
        for genuine medicine-resolution failure has none, so it is skipped
        here too rather than indexing into a row that was never created.
        PO amendment (2026-08): medicine.retail_price_field ("Gia ban
        le") is confirmed to belong to the medicine edit dialog, reached
        via Sua -> Chinh sua thuoc, only AFTER the invoice has been saved
        once (05_full_flow...py:146-151) -- not inline in the per-line
        fill loop. Applied to EVERY line, including already-existing
        medicines: the purchase price (and so the suggested retail
        price) can differ invoice to invoice, and the operator still
        reviews/edits the value in the browser before the final save,
        per the "reference only, never authoritative" retail-price rule.

        STRATEGY CHANGE (2026-08, PO decision -- REPLACES Vien retail-
        unit conversion entirely, see _verify_unit_matches_invoice's own
        docstring for the full reasoning): previously this fed a
        converted per-Vien purchase price into PricePolicy, since "Gia
        ban le" was assumed to always price one Vien. Vien conversion
        (_convert_to_retail_units) is now removed -- fill_and_save_invoice's
        Phase 1 already verified the site's own unit genuinely matches
        item.unit before this method ever runs, so item.unit_price (the
        invoice's own original, unconverted purchase price) is fed
        directly into PricePolicy.calculate_suggested_retail_price --
        no formula change there, only a different (now-verified, no
        longer converted) input.

        BUG FIX (2026-08, PO-confirmed via a real DOM snapshot of row
        2's own "Chỉnh sửa thuốc" button -- CRITICAL, matches the real
        symptom exactly: row 1's retail price always correct, row 2+
        always missing/wrong): invoice_line.edit_medicine_button's per-
        item PAGE-WIDE nth (the prior _click_at_index call this method
        used) was never independently confirmed for any row past index
        0, and PO's real inspection now shows why it cannot be trusted
        -- the button has no id and no per-row suffix, "cấu trúc giống
        hệt nhau cho mọi dòng," so a page-wide nth(index) has no
        guarantee of landing on the Nth row's own button rather than
        some other identically-shaped element elsewhere on the page.
        Now scoped via _click_edit_medicine_button_for_row (see its own
        docstring), the exact same _line_item_rows().nth() mechanism
        invoice_line.select_row_for_batch_button already uses.
        """
        self._click("invoice.edit_link")
        for index, item in enumerate(invoice.items):
            if index not in site_positions:
                continue
            self._click_edit_medicine_button_for_row(site_positions[index])
            suggested_retail_price = self._price_policy.calculate_suggested_retail_price(
                item.unit_price
            )
            self._fill("medicine.retail_price_field", str(suggested_retail_price.amount))
            self._click("invoice_line.edit_dialog_close_button")

    def _click_edit_medicine_button_for_row(self, position: int) -> None:
        """
        Click the "Chỉnh sửa thuốc" trigger for the row at 1-based
        ``position`` (PO-confirmed 2026-08 via a real DOM snapshot of
        row 2's own button -- see _update_retail_prices_after_save's
        own docstring for the full bug this fixes). Like
        invoice_line.select_row_for_batch_button, this trigger has NO
        distinguishing id or per-row suffix of its own -- structurally
        identical on every row -- and is only distinguishable by which
        <tbody> it lives in (ng-repeat="gridItem in
        viewModel.NoteItems"), so this mirrors
        _click_batch_edit_button_for_row's exact mechanism: scoped to
        _line_item_rows() (invoice_line.table_root), never a page-wide
        lookup.
        """
        entry = self._registry.require_usable("invoice_line.edit_medicine_button")
        if entry.strategy != "title" or entry.value is None:
            raise SelectorNotUsableError(
                "'invoice_line.edit_medicine_button' has strategy "
                f"{entry.strategy!r}, not 'title' -- row-scoped lookup only applies to a "
                "title-based selector."
            )
        try:
            self._line_item_rows().nth(position - 1).get_by_title(entry.value).click()
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(
                f"click:invoice_line.edit_medicine_button[row {position}]", exc
            ) from exc

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
    # ever had at most 1 stray <tbody> (the supplier dialog). Originally
    # scoped via "#tblMain" (medicine.add_new_trigger's own registry
    # notes claimed "#tblMain is the invoice line-item table").
    #
    # BUG FIX #2 (2026-08, PO-confirmed via direct real DOM inspection
    # while chasing an unrelated medicine.selected_match_chip bug): that
    # claim was WRONG -- #tblMain is actually the "Thêm mới thuốc"
    # (create-medicine) DIALOG's own inner table (has "Nhóm thuốc"/"Mã
    # thuốc" fields), a long-standing mislabeling. Every real dry-run
    # had coincidentally passed anyway (PO: "tình cờ đúng ngữ cảnh" --
    # #tblMain being a real, LARGER container that also happened to
    # wrap the true line-item table as a descendant).
    #
    # RESOLVED (2026-08, PO-confirmed via a real Console query comparing
    # the two real tables on the live page that both happen to have a
    # "Mặt hàng"-prefixed column header): the real line-item table has
    # NO id and NO distinguishing class of its own -- PO's own words,
    # "không phải chọn nhầm ID -- là không có ID đúng nào tồn tại cho
    # bảng này" (its class, 'table table-condensed table-responsive
    # display dataTable no-footer', is a generic Bootstrap/DataTable
    # combination PO suspects is reused elsewhere too, same pattern as
    # itemSearchId/drugSearchBoxId). Content-based anchoring via
    # invoice_line.table_root (its own column header's accessible name,
    # 'Mã-Tên' -- see that registry entry's own notes for the full real
    # comparison against the transaction-history dialog's decoy table,
    # which shares the 'Mặt hàng' prefix but not '[Mã-Tên]') replaces
    # the id/class-based scope entirely.
    def _line_items_table_locator(self) -> Locator:
        header_entry = self._registry.require_usable("invoice_line.table_root")
        assert header_entry.strategy == "role" and header_entry.role is not None
        header_locator = self._page.get_by_role(
            header_entry.role,  # type: ignore[arg-type]
            name=header_entry.name,
            exact=bool(header_entry.exact),
        )
        return self._page.locator("table").filter(has=header_locator)

    def _line_item_rows(self) -> Locator:
        return self._line_items_table_locator().locator("tbody")

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
        Scoped to _line_item_rows() (invoice_line.table_root), not a
        page-wide 'tbody' -- see that method's own comment for why
        (real dry-run evidence of stray tbody elements elsewhere on the
        live page, and the #tblMain mislabeling that scope replaced).

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

    def _wait_for_row_settled(self, expected_tbody_count: int) -> None:
        """
        Bug fix (2026-08, PO-confirmed via real hands-on inspection --
        CRITICAL, silent data loss, see fill_and_save_invoice's own
        docstring for the full incident). Clicking
        invoice_line.add_row_button does not, by itself, prove the
        just-filled row actually became a genuine, separate settled row
        -- Playwright only sees a normal, successful click either way.
        table_structure.html already confirmed the real, distinguishing
        fact this leans on: each SETTLED row is genuinely its own real
        <tbody> (ng-repeat="gridItem in viewModel.NoteItems") -- so
        _line_item_rows().count() is real, already-established evidence
        of how many such <tbody> elements actually exist, not a new,
        unconfirmed selector.

        BUG FIX (2026-08, PO-confirmed via a real --dry-run run): this
        originally counted page.locator("tbody") PAGE-WIDE, which a
        real dry-run run showed returning 24 matches for a 3-item real
        invoice -- other real tables elsewhere on the live page (never
        modeled by this project's local fixture, which only ever had 1
        stray tbody at most). Now scoped via _line_item_rows() (see its
        own comment for the full anchor history -- #tblMain, then
        invoice_line.table_root's content-based fix).

        BUG FIX #2 (2026-08, PO-confirmed via direct real hands-on
        browser inspection, live during a --dry-run: "1 dòng Naphacogyl
        đã được điền, 1 dòng mới chưa điền gì" -- CRITICAL, this
        method's own expected count was off by one): clicking
        invoice_line.add_row_button does TWO things, not one -- it
        commits the just-filled line into its OWN new <tbody> (as
        already understood), AND it ALSO immediately spawns a SECOND,
        separate, still-empty <tbody> for the next line -- "thêm dòng
        nghĩa là giữ dòng cũ, thêm 1 dòng mới" (PO's own words). PO
        verified directly via a real DOM query (tBodies.length) at the
        exact moment this second, empty <tbody> first appears: 2 real
        <tbody> elements, not 1. Previously this method's caller passed
        the number of lines FILLED so far (index + 1) as
        expected_tbody_count -- always one short of the real total,
        which had been silently tolerated only because
        _ROW_SETTLE_TIMEOUT_MS's own poll would keep retrying past the
        transient moment .to_have_count() briefly saw the "off by one"
        (real) count match by coincidence on a fast page, not because
        the expectation was actually correct. fill_and_save_invoice now
        passes index + 2 -- the number of lines filled so far, PLUS the
        one fresh, still-empty <tbody> this very click also creates.
        Confirmed against a real 3-line invoice, PO checking the real
        tbody count after each of the 3 add_row_button clicks in turn:
        2, then 3, then 4 -- the "+1 trailing empty row" holds uniformly
        after every click, not just the first.

        Uses Playwright's own expect().to_have_count() -- polls the
        real DOM until it matches or the timeout elapses -- rather than
        checking .count() once immediately (which would defeat the
        entire point: PO's own manual, slow re-selection is what proved
        this genuinely needs real, non-instant time to settle) or a
        fixed sleep (wastes time when the site is fast, and is still
        just a guess at "long enough" when it is not).

        Raises VerificationFailedError -- never silently continues --
        if the count never reaches ``expected_tbody_count`` in time:
        per the PO's own explicit instruction, an unverifiable row must
        stop the run with a clear diagnostic rather than silently
        proceeding to overwrite it with the next line's data.
        """
        try:
            expect(self._line_item_rows()).to_have_count(
                expected_tbody_count, timeout=self._ROW_SETTLE_TIMEOUT_MS
            )
        except AssertionError as exc:
            actual = self._line_item_rows().count()
            raise VerificationFailedError(
                f"Row <tbody> count did not reach {expected_tbody_count} within "
                f"{self._ROW_SETTLE_TIMEOUT_MS}ms after clicking invoice_line.add_row_button "
                f"-- expected {expected_tbody_count} real <tbody> row(s) (every line filled so "
                "far, PLUS the one fresh, still-empty row this click also creates), found "
                f"{actual}. Refusing to continue to the next line: proceeding without this "
                "settling first risks filling the next line's fields into a row that has not "
                "actually finished being created yet."
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

    def _type_into_search_box(self, key: str, value: str) -> None:
        """
        Bug fix (2026-08, PO-confirmed via a real, hands-on live-site
        experiment -- CRITICAL, and the real explanation behind the
        Coldi-B race this project previously chased as a settle-timing
        issue): PO proved the real site's own search-as-you-type ONLY
        reacts to genuine keyboard events landing on the box -- typing
        "Coldi-" character by character produced real results; PASTING
        (Ctrl+V) the exact same text produced NONE; typing "Coldi-b"
        then pressing Backspace to remove the trailing 'b' DID work.
        Playwright's .fill()/.clear() set the element's value directly
        -- the same mechanism as a paste, no keydown/keyup involved at
        all -- so they can silently fail to trigger a real search even
        though the DOM ends up looking identical afterward. Used for
        every real search-as-you-type box (medicine.search_input,
        invoice_line.subsequent_row_medicine_search_input,
        supplier.search_input) instead of _fill: selects any existing
        content and Backspaces it (both real key presses -- a no-op,
        harmless press on an already-empty box), then
        press_sequentially's real keydown/keypress/input/keyup per
        character, exactly what a human typing does. Plain form fields
        (name/phone/address/quantity/etc.) are NOT search-as-you-type
        widgets and PO's experiment never touched them -- left on _fill,
        since switching those to keystroke-by-keystroke typing would
        only add risk and real time with no evidenced benefit.
        """
        entry = self._registry.require_usable(key)
        try:
            locator = self._locate(entry)
            locator.click()
            locator.press("Control+A")
            locator.press("Backspace")
            locator.press_sequentially(value)
        except Exception as exc:  # noqa: BLE001
            raise wrap_playwright_error(f"type:{key}", exc) from exc

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
