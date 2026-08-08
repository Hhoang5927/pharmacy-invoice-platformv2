"""
Real Playwright, real local-fixture tests for PlaywrightBrowserAutomationProvider.

Drives a real headless Chromium instance against a local static HTML
fixture (tests/golden/automation_e2e/fixtures_html/webnhathuoc_fixture.html)
that mirrors the *confirmed* selectors in
config/selector_registry.webnhathuoc.json -- never the live
webnhathuoc.com site (no credentials, no network dependency). This
exercises the real orchestration logic (click sequences, field fills,
AutomationOutcome construction, error classification) end to end, not
just the locator syntax already covered by
tests/e2e/test_selector_registry_structural.py.

login.navigate is the one entry that must differ from the real registry
(it points at the live site's URL) -- everything else is used exactly as
registered, so a passing create_supplier() test here is real evidence the
registry's confirmed supplier fields resolve to the right DOM elements in
the right order.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    AutomationOutcome,
)
from pharmacy_invoice_automation.domain.value_objects.address import Address
from pharmacy_invoice_automation.domain.value_objects.tax_code import TaxCode
from pharmacy_invoice_automation.infrastructure.automation.playwright_adapter import (
    PlaywrightAutomationConfig,
    PlaywrightBrowserAutomationProvider,
)
from pharmacy_invoice_automation.infrastructure.automation.selector_registry import (
    SelectorEntry,
    SelectorRegistry,
    ValueMappingEntry,
    load_selector_registry,
)

pytestmark = pytest.mark.e2e


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


WEBNHATHUOC_REGISTRY_PATH = _repo_root() / "config" / "selector_registry.webnhathuoc.json"
FIXTURE_HTML_PATH = Path(__file__).resolve().parent / "fixtures_html" / "webnhathuoc_fixture.html"


def _local_registry() -> SelectorRegistry:
    """
    The real registry with only 'login.navigate' repointed at the local
    HTML fixture, plus a test-only 'login.session_indicator' entry (the
    real one is 'needs_verification' -- deliberately not usable yet, so
    this test supplies its own to exercise that code path against a real
    element instead of only against the not-usable branch).
    """
    real = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
    selectors = dict(real.selectors)
    selectors["login.navigate"] = dataclasses.replace(
        selectors["login.navigate"], value=FIXTURE_HTML_PATH.resolve().as_uri()
    )
    selectors["login.session_indicator"] = SelectorEntry(
        key="login.session_indicator",
        status="confirmed",
        strategy="css",
        value="#session-indicator:not([hidden])",
    )
    return dataclasses.replace(real, selectors=selectors)


def _registry_with_confirmed_vien_label() -> SelectorRegistry:
    """
    The real registry with value_mappings.unit_display_label.vien marked
    'confirmed' -- TEST-ONLY, not a claim of real evidence. Every real
    unit_display_label entry EXCEPT "hop" (config/selector_registry.
    webnhathuoc.json) is genuinely 'needs_verification' (see
    TestUnverifiedFlowsFailCleanlyInsteadOfGuessing, which proves
    create_medicine() correctly stops there against the real registry
    for an unconfirmed code) -- "vien" specifically has two real
    consumers that both need it: medicine.unit_dropdown (this override's
    original purpose, TestMedicineResolutionMergedIntoPerLineLoop's
    create-then-reselect handoff) and, since the 2026-08 unit-
    verification strategy change,
    PlaywrightBrowserAutomationProvider._verify_unit_matches_invoice
    (every existing test item uses Unit(code="vien"), so any
    fill_and_save_invoice test reaching Phase 1 needs this override too
    -- see that method's own docstring). "hop" itself needs no override
    here: it is already 'confirmed' ("Hộp") in the real registry, from
    invoice_line.unit_display's own real DOM evidence -- see that
    entry's registry notes.
    """
    real = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
    unit_display_label = dict(real.value_mappings["unit_display_label"])
    unit_display_label["vien"] = ValueMappingEntry(status="confirmed", label="Viên")
    value_mappings = dict(real.value_mappings)
    value_mappings["unit_display_label"] = unit_display_label
    return dataclasses.replace(real, value_mappings=value_mappings)


@pytest.fixture()
def registry() -> SelectorRegistry:
    return _local_registry()


@pytest.fixture()
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        pw_page = browser.new_page()
        yield pw_page
        browser.close()


@pytest.fixture()
def provider(page: Page, registry: SelectorRegistry) -> PlaywrightBrowserAutomationProvider:
    config = PlaywrightAutomationConfig(username="test_user", password="test_pass")
    logger = logging.getLogger("test.playwright_provider")
    return PlaywrightBrowserAutomationProvider(page, registry, config, logger)


class TestLogin:
    def test_login_fills_fields_and_submits(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        outcome = provider.login()
        assert outcome == AutomationOutcome(success=True)
        assert page.locator("#username").input_value() == "test_user"
        assert page.locator("#password").input_value() == "test_pass"

    def test_is_session_valid_false_before_login(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        assert provider.is_session_valid() is False

    def test_is_session_valid_true_after_login(
        self, provider: PlaywrightBrowserAutomationProvider
    ) -> None:
        provider.login()
        assert provider.is_session_valid() is True

    def test_is_session_valid_false_when_not_usable_in_real_registry(self, page: Page) -> None:
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        # login.session_indicator is genuinely 'needs_verification' in the
        # real registry -- must default to False, never crash or guess True.
        assert real_provider.is_session_valid() is False


class TestLoginNotificationPopup:
    """
    Bug fix (PO-confirmed 2026-08, across two consecutive real --dry-run
    runs): the first run found the "Đóng" (CSDL DQG notice) popup still
    visible on screen after login, with no error anywhere in the log --
    login() now logs this step explicitly (see its own docstring/
    comment). The very next real run then showed that new log line
    itself say "not present, skipped" -- CONFIRMING a genuine timing
    issue (the popup renders too slowly for the old, short, generic
    _click_if_present timeout), not a selector problem. login() now
    uses _click_if_eventually_visible (expect().to_be_visible() with
    its own longer, dedicated timeout) instead.
    """

    @staticmethod
    def _registry_with_popup_query(query: str) -> SelectorRegistry:
        base = _local_registry()
        selectors = dict(base.selectors)
        selectors["login.navigate"] = dataclasses.replace(
            selectors["login.navigate"],
            value=f"{FIXTURE_HTML_PATH.resolve().as_uri()}?{query}",
        )
        return dataclasses.replace(base, selectors=selectors)

    def test_clicks_and_logs_when_popup_is_present(
        self, page: Page, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page,
            self._registry_with_popup_query("show_login_popup"),
            config,
            logging.getLogger("test.popup"),
        )
        caplog.set_level(logging.INFO)

        outcome = provider.login()

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.loginPopupCloseClicks || 0") == 1
        assert "login.close_notification_popup: clicked (popup was present)" in caplog.text

    def test_logs_skip_when_popup_is_absent(
        self,
        provider: PlaywrightBrowserAutomationProvider,
        page: Page,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # The default fixture registry (no "?show_login_popup" query
        # string) -- the popup stays hidden, matching PO's own
        # confirmation that it does not always appear.
        caplog.set_level(logging.INFO)

        outcome = provider.login()

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.loginPopupCloseClicks || 0") == 0
        assert "login.close_notification_popup: not present, skipped" in caplog.text

    def test_clicks_a_popup_that_appears_after_the_old_short_timeout(
        self, page: Page, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 3-second real delay -- beyond _click_if_present's old,
        # short _OPTIONAL_CLICK_TIMEOUT_MS (2s), well within
        # _click_if_eventually_visible's new
        # _LOGIN_POPUP_VISIBLE_TIMEOUT_MS (8s). A naive re-check of the
        # OLD behavior here would have logged "not present, skipped"
        # and left the popup open, exactly PO's real second-run report.
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page,
            self._registry_with_popup_query("show_login_popup_delay_ms=3000"),
            config,
            logging.getLogger("test.popup"),
        )
        caplog.set_level(logging.INFO)

        outcome = provider.login()

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.loginPopupCloseClicks || 0") == 1
        assert "login.close_notification_popup: clicked (popup was present)" in caplog.text


class TestOpenImportInvoiceForm:
    def test_clicks_menu_link_and_submenu_link_only(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # PO-confirmed 2026-08 (real screenshot of the live site): "Nhập
        # Xuất" -> "Nhập hàng" already lands directly on a fresh,
        # ready-to-use invoice form -- the former third click
        # (open_import_invoice.add_new_button) was landing on the wrong
        # one of the form's own three "Thêm mới" buttons and has been
        # removed entirely. See open_import_invoice_form()'s own
        # docstring and the registry entry's notes for the full analysis.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        outcome = provider.open_import_invoice_form()
        assert outcome == AutomationOutcome(success=True)

    def test_succeeds_when_add_product_dialog_is_absent(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # #add-product-dialog exists in the fixture but without the "in"
        # class by default (the normal case) -- the defensive check
        # (now a second line of defense, not the primary fix -- see
        # open_import_invoice_form()'s docstring) must not affect the
        # ordinary, working flow at all.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        assert "in" not in (page.locator("#add-product-dialog").get_attribute("class") or "")

        outcome = provider.open_import_invoice_form()

        assert outcome == AutomationOutcome(success=True)

    def test_fails_cleanly_when_add_product_dialog_is_already_open(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # Defensive check (PO-confirmed 2026-08): kept as a genuine
        # second line of defense even after the real root cause (the
        # incorrect third click, see open_import_invoice_form()'s own
        # docstring) was found and removed. Proves this still fails
        # cleanly, with a clear diagnostic, instead of hanging on an
        # opaque pointer-event-blocked timeout several steps later.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.evaluate(
            "document.getElementById('add-product-dialog').className = 'modal fade in'"
        )

        outcome = provider.open_import_invoice_form()

        assert outcome.success is False
        assert "add-product-dialog" in (outcome.failure_reason or "")


class TestCreateSupplier:
    def test_fills_every_confirmed_field_in_the_po_confirmed_order(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        supplier = Supplier(
            id="sup-1",
            name="Cong ty Duoc ABC",
            tax_code=TaxCode("0123456789"),
            address=Address(full_address="123 Le Loi", city="Ha Noi"),
            phone="0987654321",
        )

        outcome = provider.create_supplier(supplier)

        assert outcome == AutomationOutcome(success=True)
        dialog = page.locator("#create-supplyer-dialog")
        assert dialog.locator("[data-field='name']").input_value() == "Cong ty Duoc ABC"
        assert dialog.locator("[data-field='phone']").input_value() == "0987654321"
        assert dialog.locator("[data-field='address']").input_value() == "123 Le Loi, Ha Noi"
        assert dialog.locator("[data-field='tax_code']").input_value() == "0123456789"
        # Never filled -- auto-generated on the real site.
        assert dialog.locator("[data-field='barcode']").input_value() == ""
        # No corresponding data on Supplier today -- left blank, not invented.
        assert dialog.locator("[data-field='note']").input_value() == ""

    def test_missing_optional_fields_are_filled_blank_not_invented(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        supplier = Supplier(id="sup-2", name="Minimal Supplier")

        outcome = provider.create_supplier(supplier)

        assert outcome == AutomationOutcome(success=True)
        dialog = page.locator("#create-supplyer-dialog")
        assert dialog.locator("[data-field='phone']").input_value() == ""
        assert dialog.locator("[data-field='address']").input_value() == ""
        assert dialog.locator("[data-field='tax_code']").input_value() == ""


class TestUnverifiedFlowsFailCleanlyInsteadOfGuessing:
    def test_create_medicine_stops_at_the_unconfirmed_unit_value_mapping(self, page: Page) -> None:
        # Use the *real* registry here (not the local one) -- proves the
        # actual shipped registry's status values drive this behavior.
        # medicine.group_select_existing is now 'confirmed' (05_full_flow...py
        # evidence), so this flow gets further than it used to -- all the
        # way through the group/code/submit/close steps -- and now stops at
        # value_mappings.unit_display_label, which is still genuinely
        # unconfirmed (every recording selected the unit dropdown by raw
        # internal option value, never by visible label text).
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        # #tblMain's trigger only appears after the supplier step in the
        # fixture's own flow; inserted directly here since this test is
        # only concerned with the medicine step in isolation.
        page.evaluate(
            "document.getElementById('open-supplier-dialog').hidden = true;"
            "document.getElementById('tblMain').innerHTML = "
            '\'<button type="button" title="Thêm mới nếu chưa có" '
            'id="open-medicine-dialog" onclick="this.hidden=true">Thêm mới nếu chưa có'
            "</button>'"
        )

        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        medicine = Medicine(
            id="med-1",
            medicine_code="TH1",
            name="Paracetamol 500mg",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )

        outcome = real_provider.create_medicine(medicine)

        assert outcome.success is False
        assert "unit_display_label" in (outcome.failure_reason or "")
        # Proves Decision 1 (2026-08, PO): select-existing is really used
        # and really lands on the right option, by label -- not skipped,
        # not guessed. "Thuốc không kê đơn" is option value "2" in the
        # fixture; a real select_option(label=...) call must have picked
        # it for medicine_type=OVER_THE_COUNTER.
        group_select = page.get_by_label("Nhóm thuốc")
        assert group_select.input_value() == "2"

    def test_fill_and_save_invoice_stops_at_the_unconfirmed_unit_display_label(
        self, page: Page
    ) -> None:
        # STRATEGY CHANGE (2026-08, PO decision -- REPLACES Vien retail-
        # unit conversion): fill_and_save_invoice's Phase 1 now calls
        # _verify_unit_matches_invoice right after selecting each line's
        # medicine. Use the *real*, unmodified registry here (not
        # _registry_with_confirmed_vien_label's test-only override) --
        # invoice_line.unit_display ITSELF is now genuinely 'confirmed'
        # (real DOM evidence, see that entry's own registry notes), but
        # value_mappings.unit_display_label.vien is still genuinely
        # 'needs_verification' (only "hop" has real evidence so far) --
        # a vien-unit item must still stop cleanly right there instead
        # of ever guessing at the expected label text.
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        invoice.add_item(
            PurchaseItem(
                id="item-1",
                medicine_name="Paracetamol 500mg",
                unit=Unit(code="vien"),
                quantity=Quantity(Decimal("5")),
                unit_price=Money(Decimal("10000")),
            )
        )

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "unit_display_label.vien" in (outcome.failure_reason or "")
        # Never reached the quantity/price fill -- proof this stops
        # BEFORE any value is entered, not after a partial/guessed fill.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == []

    def test_remove_default_supplier_tag_clicks_the_real_element(self, page: Page) -> None:
        # Bug fix (PO-confirmed 2026-08, "forgot to wire it up"):
        # supplier.default_tag_remove_button was already confirmed but
        # never called by anything -- proves the real click actually
        # reaches the real element now that a public method exists for it.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        outcome = real_provider.remove_default_supplier_tag()

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.defaultSupplierTagRemoveClicks") == 1
        assert page.locator("#default-supplier-tag-remove").count() == 0

    def test_remove_default_supplier_tag_is_best_effort_when_absent(self, page: Page) -> None:
        # PO confirmed this tag as a required step when present, but not
        # confirmed to always appear -- must never fail cleanup over a
        # tag that simply isn't there.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.evaluate("document.getElementById('default-supplier-tag-remove').remove()")

        outcome = real_provider.remove_default_supplier_tag()

        assert outcome == AutomationOutcome(success=True)

    def test_search_supplier_finds_a_real_result_via_confirmed_selectors(self, page: Page) -> None:
        # supplier.search_input and supplier.search_result_option are both
        # now confirmed (05_full_flow...py evidence) -- this exercises the
        # real end-to-end search, including the runtime-name substitution
        # into search_result_option's locator (a recorded example string,
        # not a literal to reuse -- see that entry's notes).
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        assert real_provider.search_supplier("Cong ty Duoc ABC") is True
        assert real_provider.search_supplier("Nonexistent Supplier XYZ") is False
        assert page.locator("#supplier-search").input_value() == "Nonexistent Supplier XYZ"

    def test_supplier_search_input_fills_only_the_supplier_box_not_any_other_search_input(
        self, page: Page
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, final -- root-caused the real
        # --dry-run timeout): supplier.search_input is now
        # "#supplierSearchBoxId input[type=search]" (PO direct DOM
        # inspection, Console-verified count===1), REPLACING the prior
        # role=row scope keyed on a dynamic debt figure entirely. Proves
        # the fill lands on exactly the right input and never touches
        # the fixture's other search inputs (first-item/subsequent-row
        # medicine search boxes).
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        real_provider.search_supplier("Cong ty Duoc ABC")

        assert page.locator("#supplierSearchBoxId input[type=search]").input_value() == (
            "Cong ty Duoc ABC"
        )
        assert page.locator("#first-line-search").input_value() == ""
        assert page.locator("#subsequent-line-search").input_value() == ""

    def test_supplier_add_new_trigger_clicks_the_real_element_scoped_correctly(
        self, page: Page
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, final): supplier.add_new_trigger
        # is now scoped to "#receiptNoteViewId", per a REAL Playwright
        # strict-mode-violation error from a live --dry-run run (not a
        # DOM-snapshot guess) -- REPLACES two earlier, incorrect
        # attempts: unscoped/page-wide (relied on fragile DOM-sequencing
        # luck) and "#supplierSearchBoxId" (wrong -- excluded the real
        # sibling element entirely, caught by a live --dry-run timeout).
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        real_provider._click("supplier.add_new_trigger")  # noqa: SLF001

        assert page.locator("#create-supplyer-dialog").is_hidden() is False
        assert page.locator("#open-supplier-dialog").is_hidden() is True

    def test_supplier_add_new_trigger_does_not_collide_with_the_tblmain_trigger(
        self, page: Page
    ) -> None:
        # Real disambiguation proof, not just "no error was raised":
        # populates #tblMain (the addDrugGroup() button, same title
        # text) BEFORE clicking supplier.add_new_trigger, bypassing the
        # fixture's own deferred-injection timing entirely -- mirrors
        # the exact two-candidate ambiguity the real strict-mode error
        # showed, and proves #receiptNoteViewId's scope alone (not DOM
        # sequencing) is what keeps this resolving to the right element.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.evaluate(
            "document.getElementById('tblMain').innerHTML = "
            '\'<button type="button" title="Thêm mới nếu chưa có" '
            'id="open-medicine-dialog" onclick="this.hidden=true">Thêm mới nếu chưa có'
            "</button>'"
        )

        real_provider._click("supplier.add_new_trigger")  # noqa: SLF001

        assert page.locator("#create-supplyer-dialog").is_hidden() is False
        assert page.locator("#open-supplier-dialog").is_hidden() is True
        # The #tblMain button was never touched by this click.
        assert page.locator("#open-medicine-dialog").is_hidden() is False

    def test_medicine_add_new_trigger_is_unaffected_by_the_supplier_trigger_fix(
        self, page: Page
    ) -> None:
        # medicine.add_new_trigger ("#tblMain" + title match) was NOT
        # touched by the supplier.add_new_trigger scoping fix -- proves
        # it still resolves and clicks correctly on its own.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.evaluate(
            "document.getElementById('tblMain').innerHTML = "
            '\'<button type="button" title="Thêm mới nếu chưa có" '
            'id="open-medicine-dialog" onclick="this.hidden=true">Thêm mới nếu chưa có'
            "</button>'"
        )

        real_provider._click("medicine.add_new_trigger")  # noqa: SLF001

        assert page.locator("#open-medicine-dialog").is_hidden() is True

    def test_fill_and_save_invoice_succeeds_with_no_items_via_confirmed_save_button(
        self, page: Page
    ) -> None:
        # invoice.save_button is now confirmed ('Ghi Phiếu', 05_full_flow...py
        # evidence) -- with no items, the per-line loop never runs and the
        # method should now complete for real rather than stopping cleanly.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)

    def test_fill_and_save_invoice_fills_the_confirmed_commercial_discount_field(
        self, page: Page
    ) -> None:
        # invoice.commercial_discount_field is now 'confirmed' (PO direct
        # DOM inspection, 2026-08, input[ng-model="viewModel.Discount"])
        # -- PurchaseInvoice.commercial_discount_amount being set must
        # fill this real field (a Money/VND value, no % conversion) and
        # still complete the save successfully.
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.value_objects.money import Money

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
            commercial_discount_amount=Money(Decimal("26855")),
        )

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        assert page.locator('input[ng-model="viewModel.Discount"]').input_value() == "26855"

    def test_fill_and_save_invoice_leaves_the_discount_field_untouched_when_no_discount(
        self, page: Page
    ) -> None:
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        assert page.locator('input[ng-model="viewModel.Discount"]').input_value() == ""


class TestTwoPhaseFillAndSaveInvoice:
    """
    06_multi_line_items.py (5 line items, PO-confirmed 2026-08):
    REPLACES the prior single-phase-per-line model. Phase 1 (per line:
    search+select medicine, fill the shared quantity/price/VAT set,
    click invoice_line.add_row_button to confirm+advance) and Phase 2
    (batch/expiry, invoice_line.select_row_for_batch_button --
    table_structure.html resolved its row-scoping via real <tbody>
    elements, REPLACING the abandoned tbody:nth-child(N) approach) are
    both fully confirmed and exercised end to end here.
    """

    def _make_item(self, medicine_name: str, unit_price: str, **overrides: object):
        import uuid
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        defaults: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "medicine_name": medicine_name,
            "unit": Unit(code="vien"),
            "quantity": Quantity(Decimal("5")),
            "unit_price": Money(Decimal(unit_price)),
            "retail_units_per_purchase_unit": 1,
        }
        defaults.update(overrides)
        return PurchaseItem(**defaults)  # type: ignore[arg-type]

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        # The supplier-creation dialog's field table is a real <tbody>
        # outside #real-line-items-table (needed elsewhere for
        # supplier.name_field's exact CSS nth-child path -- cannot be
        # restructured away like the medicine-search sections were).
        # Only affects tests asserting a PAGE-WIDE page.locator("tbody")
        # count (e.g. test_ignores_stray_tbody_elements_outside_the_line_items_table's
        # own >= 21 check) -- _line_item_rows() itself is scoped via
        # invoice_line.table_root's content-based anchor and already
        # ignores this stray tbody on its own; removed here anyway to
        # keep page-wide counts exact, scoped to this test's own
        # isolated Page instance only.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_phase_1_searches_and_fills_every_line_via_confirmed_selectors(
        self, page: Page
    ) -> None:
        # Real registry, real fixture: item 1 must use medicine.search_input
        # (the "Đóng"-cell-scoped combobox, first line only), item 2 must
        # use invoice_line.subsequent_row_medicine_search_input (role=
        # combobox name="Select box" nth=1) -- both feed the same
        # medicine.search_result_option result list. Quantity/price/VAT
        # are the shared #tbxQuantityId/#tbxPriceId/#tbxVATId fields,
        # confirmed to work correctly per line via #line-fill-log.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        # The fixture's 3 title="Thêm mới" decoy spans near the top are
        # deliberately left in place (not hidden/removed) here -- proof
        # that invoice_line.add_row_button's ng-click-based selector
        # (see its own registry notes, PO-confirmed 2026-08) genuinely
        # disambiguates from real-shaped imposters, not merely their
        # absence.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        # Bug fix (2026-08): _wait_for_row_settled now polls a PAGE-WIDE
        # page.locator("tbody") count after every line, same as
        # invoice_line.select_row_for_batch_button already did -- so the
        # stray supplier-dialog <tbody> that Phase 2's own test already
        # had to remove now matters here too.
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))
        invoice.add_item(self._make_item("Amoxicillin 500mg", "20000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|10000|", "5|20000|"]

    def test_fills_invoice_number_and_date_before_phase_1(self, page: Page) -> None:
        # Bug fix (PO-confirmed 2026-08): invoice.number_field/date_field
        # were registered/confirmed but never actually called -- the same
        # "forgot to wire it up" gap as supplier.default_tag_remove_button.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="00001567",
            invoice_date=date(2026, 3, 5),
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        assert page.locator("#invoice-number-input").input_value() == "00001567"
        assert page.locator("#invoice-date-input").input_value() == "05/03/2026"

    def test_fails_cleanly_when_the_date_field_does_not_roundtrip(self, page: Page) -> None:
        # Bug fix (2026-08, PO-confirmed across multiple real --dry-run
        # investigations -- CRITICAL, WRONG DATE on a real invoice): a
        # real run produced a visibly WRONG date on the real site (e.g.
        # "19/01/2024" instead of the invoice's real date). The
        # fixture's "?corrupt_invoice_date" query models this exact
        # real misbehavior (now hooked into the calendar's own final
        # day-selection step, since nothing fills this field directly
        # any more) -- proves _fill_invoice_date_and_verify catches it
        # and refuses to continue, instead of silently letting a wrong
        # date reach a real "Ghi Phieu" save.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?corrupt_invoice_date")

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="00001567",
            invoice_date=date(2026, 3, 5),
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "did not register this date correctly" in (outcome.failure_reason or "")
        assert "05/03/2026" in (outcome.failure_reason or "")
        assert "19/01/2024" in (outcome.failure_reason or "")
        # Must never have reached the medicine line at all.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == []

    def test_phase_2_attaches_batch_and_expiry_to_the_correct_row_for_each_item(
        self, page: Page
    ) -> None:
        # table_structure.html (2026-08): invoice_line.select_row_for_batch_button
        # is now confirmed. Full end-to-end fill_and_save_invoice with 2
        # batched items -- proves Phase 2 attaches the shared batch/
        # expiry overlay to the RIGHT row each time, not just that it
        # runs without crashing.
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.batch import Batch
        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.value_objects.expiry_date import ExpiryDate
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity

        batches = {
            "batch-1": Batch(
                id="batch-1",
                medicine_id="med-1",
                batch_number="B111",
                expiry_date=ExpiryDate(date(2027, 1, 1)),
                quantity_received=Quantity(Decimal("5")),
            ),
            "batch-2": Batch(
                id="batch-2",
                medicine_id="med-2",
                batch_number="B222",
                expiry_date=ExpiryDate(date(2027, 6, 15)),
                quantity_received=Quantity(Decimal("5")),
            ),
        }

        class _StubBatchRepository:
            def get_by_id(self, batch_id: str) -> Batch:
                return batches[batch_id]

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page,
            real_registry,
            config,
            logging.getLogger("test"),
            batch_repository=_StubBatchRepository(),  # type: ignore[arg-type]
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000", batch_id="batch-1"))
        invoice.add_item(self._make_item("Amoxicillin 500mg", "20000", batch_id="batch-2"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        batch_log_entries = page.locator("#batch-fill-log li").all_text_contents()
        assert batch_log_entries == [
            "1|B111|2027-01-01",
            "2|B222|2027-06-15",
        ]


class TestUnitVerificationBeforeFill:
    """
    STRATEGY CHANGE (2026-08, PO decision -- REPLACES Vien retail-unit
    conversion entirely, see PlaywrightBrowserAutomationProvider.
    _verify_unit_matches_invoice's own docstring): the old design
    converted quantity/price through an assumed/looked-up
    retail_units_per_purchase_unit ratio before ever filling anything.
    The new design instead fills each item's own ORIGINAL invoice
    quantity/unit_price verbatim -- but only after reading the site's
    own currently-displayed unit for real and confirming it genuinely
    matches item.unit; a mismatch stops the line instead of ever
    guessing a conversion. Each row's own real <select
    ng-model="gridItem.SelectedUnitId"> (see unitSelectHtml's own
    comment in webnhathuoc_fixture.html) models the site's own real
    per-row unit dropdown, defaulting to "Viên" and overridable
    per-row via a "row{N}_unit_label" query param (1-based row number)
    to simulate that row's own select showing something else.
    """

    def _make_item(self, medicine_name: str, unit_price: str, **overrides: object):
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        defaults: dict[str, object] = {
            "id": "item-1",
            "medicine_name": medicine_name,
            "unit": Unit(code="vien"),
            "quantity": Quantity(Decimal("7")),
            "unit_price": Money(Decimal(unit_price)),
        }
        defaults.update(overrides)
        return PurchaseItem(**defaults)  # type: ignore[arg-type]

    @staticmethod
    def _make_invoice():
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        return PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_matching_unit_fills_the_original_invoice_values_verbatim_no_conversion(
        self, page: Page
    ) -> None:
        # item.unit is vien and the site displays "Viên" (the fixture's
        # own default) -- must match, and the RAW quantity (7, not
        # multiplied/divided by any ratio -- none is even set on this
        # item) and RAW unit_price (137500) must reach the page exactly
        # as the invoice states them.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "137500"))

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["7|137500|"]

    def test_mismatched_unit_stops_the_line_and_routes_to_review_never_guesses(
        self, page: Page
    ) -> None:
        # row1_unit_label="Hộp" simulates row 1's own real <select>
        # showing a DIFFERENT unit than this invoice's own (item.unit
        # stays vien, unmapped to "Hộp") -- the exact real shape of the
        # gap PO reported (Naphacogyl's real catalog entry already had
        # "Hop"). Must stop this line with a clear reason and never
        # touch quantity/price/VAT/add_row_button -- no silent
        # conversion, no silent skip.
        from urllib.parse import quote

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?row1_unit_label={quote('Hộp')}")
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "137500"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "Đơn vị trên web" in (outcome.failure_reason or "")
        assert "Hộp" in (outcome.failure_reason or "")
        assert "Viên" in (outcome.failure_reason or "")
        assert "Paracetamol 500mg" in (outcome.failure_reason or "")
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == []

    def test_second_line_mismatch_does_not_disturb_the_first_lines_already_filled_values(
        self, page: Page
    ) -> None:
        # Two items: the first genuinely matches (item.unit=vien, row
        # 1's own real <select> defaults to "Viên", no override needed)
        # and must be filled and committed for real before the second
        # is even attempted; the second is deliberately given
        # item.unit="hop" (confirmed expected label "Hộp") while row
        # 2's own select ALSO defaults to "Viên" (no row2_unit_label
        # override in this test's own URL) -- a genuine mismatch --
        # proving a later line's mismatch stops the WHOLE invoice (this
        # project's existing "one invoice, all-or-nothing" outcome
        # contract) without ever having guessed on the first.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000", id="item-1"))
        invoice.add_item(
            self._make_item(
                "Amoxicillin 500mg", "20000", id="item-2", unit=Unit(code="hop")
            )
        )

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "Amoxicillin 500mg" in (outcome.failure_reason or "")
        # The first line's own value WAS genuinely filled/committed
        # (real add_row_button click) before the second line's mismatch
        # stopped everything -- proves this is a real per-line check,
        # not a whole-invoice pre-check that would never have reached
        # filling the first line at all.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["7|10000|"]

    def test_hop_unit_matches_via_real_registry_fills_five_not_converted_hundred(
        self, page: Page
    ) -> None:
        # The exact real regression this whole strategy change fixes
        # (PO direct DB inspection, 2026-08): invoice 00001567's real
        # Naphacogyl line has unit="hop", quantity=5 -- and a
        # retail_units_per_purchase_unit=20 that automation no longer
        # reads at all. The OLD, now-removed Vien-conversion design
        # would have filled 5 * 20 = 100 on the real site, never what
        # the invoice actually says. Uses the REAL, completely
        # unmodified registry -- no test-only override needed anywhere,
        # since BOTH invoice_line.unit_display and value_mappings.
        # unit_display_label.hop are now genuinely 'confirmed' from
        # real DOM evidence (see invoice_line.unit_display's own
        # registry notes) -- the strongest possible proof this works
        # against real, confirmed data, not a test-only stand-in.
        from decimal import Decimal
        from urllib.parse import quote

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?row1_unit_label={quote('Hộp')}")
        self._remove_supplier_dialog_tbody(page)

        # medicine_name is "Paracetamol 500mg" (TH1, a single unambiguous
        # match), not the real invoice's own "Naphacogyl" -- the real
        # DB's Naphacogyl name matches 2 real catalog rows (TH6/TH7),
        # which would route through the SEPARATE Part 2/3 human-
        # disambiguation flow (already covered by its own tests) and
        # obscure what this test is actually proving. quantity=5 and
        # unit_price=21905 are still the real invoice's own values.
        invoice = self._make_invoice()
        invoice.add_item(
            PurchaseItem(
                id="item-1",
                medicine_name="Paracetamol 500mg",
                unit=Unit(code="hop"),
                quantity=Quantity(Decimal("5")),
                unit_price=Money(Decimal("21905")),
            )
        )

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|21905|"]


class TestVatPercentageFilling:
    """
    BUG FIX (2026-08, PO-confirmed via a real DB row, invoice
    '00001567' -- CRITICAL, root-caused a "VAT never appears on the
    real site despite fill_and_save_invoice logging 'succeeded'"
    report): Phase 1 used to fill invoice_line.vat_field with
    ``item.tax_type.value`` directly -- the Domain enum's own string
    label ("reduced", "standard", ...), never a percentage number.
    invoice_line.vat_field's own registry notes confirm it is a plain
    numeric text input (e.g. "5"), so the real site almost certainly
    rejected/cleared that literal text. Now converts via the
    already-established domain.constants.TAX_RATE_BY_TYPE (see
    PlaywrightBrowserAutomationProvider._format_tax_percentage's own
    docstring) -- these tests prove the real, correct number reaches
    the page for every TaxType, via the fixture's own #line-fill-log
    (records "quantity|price|vat" per committed line).
    """

    def _make_item(self, medicine_name: str, unit_price: str, **overrides: object):
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        defaults: dict[str, object] = {
            "id": "item-1",
            "medicine_name": medicine_name,
            "unit": Unit(code="vien"),
            "quantity": Quantity(Decimal("7")),
            "unit_price": Money(Decimal(unit_price)),
        }
        defaults.update(overrides)
        return PurchaseItem(**defaults)  # type: ignore[arg-type]

    @staticmethod
    def _make_invoice():
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        return PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_reduced_vat_fills_the_real_percentage_number_five(self, page: Page) -> None:
        # The exact real-world case that surfaced this bug: invoice
        # '00001567's own tax_type was 'reduced' on all 3 real items.
        from pharmacy_invoice_automation.domain.enums.tax_type import TaxType

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(
            self._make_item("Paracetamol 500mg", "10000", tax_type=TaxType.REDUCED)
        )

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["7|10000|5"]

    def test_every_tax_type_fills_its_own_correct_percentage_number(self, page: Page) -> None:
        # One invoice, one line per TaxType (standard/reduced/exempt/
        # eight_percent/other) -- proves the conversion is correct for
        # every case, not just the one real invoice happened to use.
        from pharmacy_invoice_automation.domain.enums.tax_type import TaxType

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(
            self._make_item(
                "Paracetamol 500mg", "10000", id="item-1", tax_type=TaxType.STANDARD
            )
        )
        invoice.add_item(
            self._make_item(
                "Amoxicillin 500mg", "20000", id="item-2", tax_type=TaxType.REDUCED
            )
        )
        invoice.add_item(
            self._make_item("Vitamin C 500mg", "5000", id="item-3", tax_type=TaxType.EXEMPT)
        )

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["7|10000|10", "7|20000|5", "7|5000|0"]

    def test_format_tax_percentage_covers_every_tax_type_directly(self) -> None:
        # Direct unit check (no fixture/browser needed) on the
        # conversion itself, for every TaxType including the two the
        # real-browser tests above don't exercise (eight_percent,
        # other) -- proves domain.constants.TAX_RATE_BY_TYPE is used
        # correctly end to end, not just for the specific rates those
        # tests happened to pick.
        from pharmacy_invoice_automation.domain.enums.tax_type import TaxType

        format_tax_percentage = (
            PlaywrightBrowserAutomationProvider._format_tax_percentage  # noqa: SLF001
        )

        assert format_tax_percentage(TaxType.STANDARD) == "10"
        assert format_tax_percentage(TaxType.REDUCED) == "5"
        assert format_tax_percentage(TaxType.EXEMPT) == "0"
        assert format_tax_percentage(TaxType.EIGHT_PERCENT) == "8"
        assert format_tax_percentage(TaxType.OTHER) == "0"


class TestInvoiceDateCalendarNavigation:
    """
    Bug fix (2026-08, PO-confirmed via real hands-on testing --
    CRITICAL, WRONG DATE on a real invoice, FULLY RESOLVED): PO
    personally confirmed clicking directly into "Ngày hóa đơn" does not
    open its calendar -- a separate calendar-icon button
    (invoice.date_calendar_trigger, ng-click="onInvoiceDateClick", real
    DOM snapshot copied verbatim) must be clicked instead, then a
    single, page-shared bootstrap-datepicker navigated year -> month ->
    day (see _select_invoice_date_via_calendar's own docstring). These
    tests prove the real calendar mechanism end to end, not just that
    _fill_invoice_date_and_verify's own roundtrip check passes.
    """

    def _make_item(self, medicine_name: str, unit_price: str, **overrides: object):
        import uuid
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        defaults: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "medicine_name": medicine_name,
            "unit": Unit(code="vien"),
            "quantity": Quantity(Decimal("5")),
            "unit_price": Money(Decimal(unit_price)),
            "retail_units_per_purchase_unit": 1,
        }
        defaults.update(overrides)
        return PurchaseItem(**defaults)  # type: ignore[arg-type]

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_navigates_back_multiple_years_to_the_correct_date(self, page: Page) -> None:
        # The user's own explicit ask: at least 1 case needing MULTIPLE
        # years back (fixture's default calendar display is "Tháng 8
        # 2026") -- proves year -> month -> day navigation genuinely
        # works, not just picking a day within the currently-displayed
        # month.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="00001567",
            invoice_date=date(2024, 1, 11),
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        assert page.locator("#invoice-date-input").input_value() == "11/01/2024"

    def test_excludes_old_and_new_overflow_days(self, page: Page) -> None:
        # Fixture's day grid deliberately has day "1" appear BOTH as a
        # real day (row 1) and as a ".new" overflow day (row 3) --
        # proves ":not(.old):not(.new)" genuinely disambiguates instead
        # of hitting a strict-mode violation or silently picking the
        # wrong one.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="00001567",
            invoice_date=date(2026, 8, 1),
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        assert page.locator("#invoice-date-input").input_value() == "01/08/2026"

    def test_fails_cleanly_when_more_than_one_calendar_is_visible(self, page: Page) -> None:
        # PO's own explicit safety request: refuse to navigate an
        # ambiguous calendar rather than risk picking a date meant for
        # a different (stray/duplicate) widget instance.
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?duplicate_calendar")
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="00001567",
            invoice_date=date(2024, 1, 11),
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "Expected exactly 1 visible" in (outcome.failure_reason or "")
        # Must never have reached the medicine line at all.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == []


class TestRowSettleVerification:
    """
    Bug fix (PO-confirmed 2026-08 -- CRITICAL, silent data loss found
    via real hands-on inspection of a live --dry-run run): clicking
    invoice_line.add_row_button never, by itself, proved the just-
    filled row actually became its own settled <tbody> -- a real
    invoice with 3 lines, every step logged "succeeded", ended up with
    only 1 real row on the actual site, because the next line's fields
    were typed into the still-shared, not-yet-settled active row
    fields before the previous one finished settling. See
    fill_and_save_invoice's and _wait_for_row_settled's own docstrings
    for the full incident. The fixture's #add-row-button handler models
    this real, non-instant settle delay via a configurable
    "row_settle_delay_ms"/"row_never_settles" query string (see its own
    comment) rather than always settling synchronously, so these tests
    genuinely exercise the new poll/verify logic instead of trivially
    passing against an instant DOM update.

    BUG FIX #2 (2026-08, PO-confirmed via the very next real --dry-run
    run after this safety check first shipped): that run's own error
    message ("expected 1... found 24") revealed the settle-check itself
    was counting <tbody> elements PAGE-WIDE, not scoped to the invoice
    line-items table -- test_ignores_stray_tbody_elements_outside_the_line_items_table
    below proves the fix, now scoped via invoice_line.table_root's
    content-based anchor (originally #tblMain -- see that entry's own
    registry notes for why that was later found to be wrong).
    """

    def _make_item(self, medicine_name: str, unit_price: str, **overrides: object):
        import uuid
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        defaults: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "medicine_name": medicine_name,
            "unit": Unit(code="vien"),
            "quantity": Quantity(Decimal("5")),
            "unit_price": Money(Decimal(unit_price)),
            "retail_units_per_purchase_unit": 1,
        }
        defaults.update(overrides)
        return PurchaseItem(**defaults)  # type: ignore[arg-type]

    def _make_invoice(self):
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        return PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        # The supplier-creation dialog's field table is a real <tbody>
        # outside #real-line-items-table -- _wait_for_row_settled itself
        # is scoped via invoice_line.table_root's content-based anchor
        # and already ignores it, but this test also asserts a
        # PAGE-WIDE page.locator("tbody") count in one place, which this
        # stray tbody would shift; fill_and_save_invoice never touches
        # the supplier dialog, so removing it here is safe and scoped to
        # this test's own isolated Page instance only.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_waits_for_a_delayed_row_to_settle_before_continuing(self, page: Page) -> None:
        # A 1-second real, configurable delay before the fixture appends
        # the settled <tbody> -- well under _wait_for_row_settled's own
        # 5-second timeout, but long enough that a naive "check .count()
        # once, immediately" implementation would have already failed.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?row_settle_delay_ms=1000")
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        # Scoped to #real-line-items-table (not a bare page-wide
        # "tbody") -- the invoice.date_field calendar widget's own real
        # <table><tbody> (day grid) is a second, unrelated, ALWAYS-present
        # stray tbody elsewhere on the page now (see _line_item_rows's
        # own invoice_line.table_root-scoping fix and its "why" for this
        # exact class of page-wide-count pitfall). 2, not 1 -- one real
        # <tbody> already exists before any click (see that element's
        # own comment), and this 1-item invoice's own add_row_button
        # click pushes exactly one more (see _wait_for_row_settled's
        # own "+1 trailing empty row" bug fix).
        assert page.locator("#real-line-items-table tbody").count() == 2

    def test_fails_cleanly_when_a_row_never_settles(self, page: Page) -> None:
        # Simulates the real site rejecting the row outright (PO's real
        # "chưa nhập thông tin thuốc" error) -- no <tbody> is ever
        # appended. Must fail with a clear, actionable diagnostic, never
        # silently continue to the next line.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?row_never_settles")
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))
        invoice.add_item(self._make_item("Amoxicillin 500mg", "20000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome.success is False
        assert "did not reach" in (outcome.failure_reason or "")
        assert "expected 2" in (outcome.failure_reason or "")
        # The second line's fields must never have been touched --
        # proof this stopped immediately rather than plowing ahead and
        # overwriting anything.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|10000|"]

    def test_real_row_count_matches_after_filling_three_lines(self, page: Page) -> None:
        # The user's own explicit ask: don't just trust "no exception"
        # -- confirm the actual number of real rows on the page matches
        # how many lines were filled, for an invoice with >= 3 items.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))
        invoice.add_item(self._make_item("Amoxicillin 500mg", "20000"))
        invoice.add_item(self._make_item("Vitamin C 500mg", "5000"))

        # dry_run=True: only Phase 1's row-settling is under test here --
        # the post-save "Gia ban le" edit flow needs one "Chỉnh sửa
        # thuốc" button per saved item, and the fixture only models 2
        # (matching every other test that needed it), not 3.
        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        # Scoped to #real-line-items-table -- see
        # test_waits_for_a_delayed_row_to_settle_before_continuing's own
        # comment for why a bare page-wide "tbody" count is no longer
        # safe (the calendar widget's own real day-grid <tbody> is a
        # second, unrelated stray one now). 4, not 3 -- see
        # #real-line-items-table's own "+1 trailing empty row" comment.
        assert page.locator("#real-line-items-table tbody").count() == 4
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|10000|", "5|20000|", "5|5000|"]

    def test_ignores_stray_tbody_elements_outside_the_line_items_table(
        self, page: Page
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, via a real --dry-run run): a
        # real 3-item invoice found page.locator("tbody") returning 24
        # matches PAGE-WIDE (other real tables elsewhere on the live
        # page, never modeled by this local fixture). Injects a pile of
        # stray <tbody> elements OUTSIDE #real-line-items-table here to
        # prove _wait_for_row_settled/_click_batch_edit_button_for_row
        # (both now scoped via _line_item_rows(), invoice_line.table_root's
        # content-based anchor -- originally #tblMain, later found wrong,
        # see that registry entry's own notes) genuinely ignore them --
        # not merely passing because the fixture never had any stray
        # tbody of its own.
        #
        # Also proves exclusion by CONTENT, not just "no columnheader at
        # all" -- the fixture's own permanent decoy
        # (#table-id-trans-details-by-object-note, PO-confirmed real:
        # the 'Lịch sử giao dịch' dialog's table, sharing the 'Mặt hàng'
        # column-header PREFIX but not '[Mã-Tên]') has its own real
        # <tbody> too, and must also be excluded.
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)
        page.evaluate(
            "for (let i = 0; i < 20; i++) {"
            "  const stray = document.createElement('table');"
            "  stray.appendChild(document.createElement('tbody'));"
            "  document.body.appendChild(stray);"
            "}"
        )

        invoice = self._make_invoice()
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))

        # dry_run=True: only Phase 1's row-settling is under test here.
        outcome = real_provider.fill_and_save_invoice(invoice, dry_run=True)

        assert outcome == AutomationOutcome(success=True)
        # Page-wide count is inflated by the 20 stray tbody elements
        # AND the permanent decoy table's own real tbody -- exactly the
        # real symptom (24 page-wide vs. 3 real rows).
        assert page.locator("tbody").count() >= 22
        # 2, not 1 -- see #real-line-items-table's own "+1 trailing
        # empty row" comment.
        assert page.locator("#real-line-items-table tbody").count() == 2
        assert page.locator("#table-id-trans-details-by-object-note tbody").count() == 1


class TestMedicineSelectionSettleWait:
    """
    Bug fix (2026-08, PO-confirmed via the same real --dry-run run that
    surfaced the line-items-table-scoping bug above -- see
    _search_and_select_medicine_for_line's own
    _MEDICINE_SELECTION_SETTLE_MS comment): a real site error, "Hãy
    chọn thuốc để thêm vào phiếu" (rejecting add_row_button), occurred
    on a line whose medicine-search-result click had already resolved
    and clicked with no Playwright-visible error -- the same class of
    "genuinely needs real, non-instant time" problem
    _wait_for_row_settled already fixed for add_row_button, one step
    earlier. No confirmed selector exists yet for the invoice line's
    own "Đơn vị" display to poll against instead, so this is a fixed
    wait (PO's own explicit fallback) -- this test proves the wait is
    real (a genuine elapsed-time measurement), not that it is
    sufficient on the real site (which still needs live confirmation).
    """

    def test_waits_a_real_fixed_delay_after_selecting_a_medicine(self, page: Page) -> None:
        import time
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        item = PurchaseItem(
            id="item-1",
            medicine_name="Paracetamol 500mg",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            retail_units_per_purchase_unit=1,
        )

        started = time.monotonic()
        real_provider._search_and_select_medicine_for_line(item, 0)  # noqa: SLF001
        elapsed = time.monotonic() - started

        # Configured wait is 2.5s -- allow a small margin for real
        # scheduling slack while still proving it is a genuine wait,
        # not a no-op.
        assert elapsed >= 2.4

    def test_search_medicine_also_waits_before_checking_the_result_count(
        self, page: Page
    ) -> None:
        # Bug fix (2026-08, PO-confirmed via a real --dry-run run --
        # investigated and root-caused via code reading): search_medicine()
        # was checking medicine.search_result_option's .count()
        # IMMEDIATELY after fill(), with no settle wait at all -- a
        # false negative here (site's search-as-you-type not yet
        # finished) makes an ALREADY-existing medicine look "not
        # found", triggering an unnecessary create_medicine() call
        # whose own medicine.add_new_trigger click then hit a real but
        # not-actually-meant-to-be-clicked element ("not visible").
        # cli.py's own _resolve_medicine_on_site was separately verified
        # (by reading it directly) to already correctly gate
        # create_medicine() behind search_medicine() returning False --
        # this was the real, root-cause gap, not an unconditional-click
        # bug in the orchestration logic.
        #
        # BUG FIX #2 (2026-08, found during the search_supplier()-
        # triggered full-file audit): the original fix here was a FIXED
        # wait_for_timeout, not a poll -- this test used to assert
        # `elapsed >= 2.4` to prove that fixed wait was real. Switched to
        # _poll_until_matched (see search_medicine's own comment), which
        # returns as soon as a match appears -- for this fixture's own
        # already-present "Paracetamol 500mg" row, that is now near-
        # instant, so `elapsed >= 2.4` would fail even though the fix is
        # correct. Re-proven instead via medicine_search_settle_delay_ms
        # (mirrors supplier_search_settle_delay_ms's own pattern): a
        # genuine, real async delay before the result appears, which an
        # unpolled single check would miss entirely.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?medicine_search_settle_delay_ms=1500"
        )

        found = real_provider.search_medicine("Paracetamol 500mg")

        assert found is True


class TestSelectMedicinePollsForRealSettleTime:
    """
    Bug fix (2026-08, found during the same full-file audit as
    search_medicine's own #2 fix above): select_medicine() used to type
    then click immediately, relying only on Locator.click()'s own
    generic implicit auto-wait -- never an explicit poll+verify the way
    select_supplier() already had. Now mirrors select_supplier() exactly:
    polls for the result first, raises a clear VerificationFailedError
    if it never appears, instead of leaving that to an opaque generic
    Playwright timeout.
    """

    def test_a_bare_count_check_right_after_typing_sees_nothing_yet(self, page: Page) -> None:
        # Control: proves medicine_search_settle_delay_ms genuinely
        # reproduces a real race, the same way the supplier-side control
        # test does.
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?medicine_search_settle_delay_ms=1500"
        )
        search_box = page.locator("#first-line-search")
        search_box.click()
        search_box.press_sequentially("Paracetamol 500mg")

        assert (
            page.locator("[data-medicine-result]", has_text="Paracetamol 500mg").count() == 0
        )

    def test_select_medicine_waits_out_the_real_settle_delay_and_still_selects_it(
        self, page: Page
    ) -> None:
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?medicine_search_settle_delay_ms=1500"
        )

        outcome = provider.select_medicine("Paracetamol 500mg")

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.medicineResultClickLog") == ["TH1"]

    def test_select_medicine_fails_cleanly_not_a_silent_guess_when_it_never_appears(
        self, page: Page
    ) -> None:
        # The settle delay (15s) comfortably exceeds
        # _SEARCH_RESULT_POLL_BUDGET_MS's own poll budget (8s, 2026-08
        # PO-decided generous ceiling -- see that constant's own comment
        # for why) -- proves a genuinely-never-(yet)-found result raises
        # a clear, caught VerificationFailedError (surfaced as
        # AutomationOutcome(success=False, ...) by _run_outcome) -- never
        # hangs, never clicks a stale/absent element.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?medicine_search_settle_delay_ms=15000"
        )

        outcome = provider.select_medicine("Paracetamol 500mg")

        assert outcome.success is False
        assert "no matching" in (outcome.failure_reason or "")


class TestMedicineSearchResultDisambiguation:
    """
    Bug fix (PO-confirmed 2026-08, via 2 consecutive real --dry-run
    runs + a real DOM snapshot -- CRITICAL, substring-collision
    selection bug): the IDENTICAL "Row 2 did not settle" failure at the
    IDENTICAL point (Naphacogyl -> Coldi) on both runs, despite both
    _wait_for_row_settled and _MEDICINE_SELECTION_SETTLE_MS already
    being in place, ruled out timing. PO then confirmed live: typing
    "Coldi" returns >= 4 real results (this account's search reaches
    the national drug database), including both "Coldi" and
    "Coldi-B DNH" -- the old exact=false substring match on the full
    result cell text matched BOTH. medicine.search_result_option now
    uses an END-anchored, case-insensitive match ("text_ends_with")
    against the real <b> tag PO's own DOM snapshot confirmed contains
    only "{code} - {tên thuốc}" (see the registry entry's own notes for
    the full incident and the real snapshot copied verbatim). The
    fixture's TH4/TH5 ("Coldi"/"Coldi-B DNH") reproduce this exact real
    substring-collision case.
    """

    def test_selects_coldi_not_coldi_b_dnh(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        outcome = provider.select_medicine("Coldi")

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.medicineResultClickLog") == ["TH4"]

    def test_selects_coldi_b_dnh_not_coldi(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        outcome = provider.select_medicine("Coldi-B DNH")

        assert outcome == AutomationOutcome(success=True)
        assert page.evaluate("window.medicineResultClickLog") == ["TH5"]

    def test_search_medicine_finds_both_real_entries_by_their_own_correct_query(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # search_medicine's own bool return (used to decide whether
        # create_medicine is needed) must resolve correctly for both
        # names -- not silently succeed against an ambiguous multi-
        # match count.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        assert provider.search_medicine("Coldi") is True
        assert provider.search_medicine("Coldi-B DNH") is True


class TestMedicineSearchStripsPackagingDescription:
    """
    Bug fix (2026-08, PO-confirmed via 3 real screenshots, root-caused
    by hand on the live site): typing the FULL OCR name, "Naphacogyl"
    plus its trailing packaging description in parentheses, "(Thùng x
    300 hộp x 2 vỉ x 10 viên)", into the real medicine search box
    returned ZERO dropdown results; typing just "naphacogyl" returned
    real results, including the already-catalogued correct match.
    PurchaseItem.medicine_name/Medicine.name conflate the web-search
    string with the full packaging description as printed on the
    invoice -- these tests prove PlaywrightBrowserAutomationProvider
    now strips that trailing parenthetical before it ever reaches the
    page (search_medicine's own docstring has the full incident
    writeup).
    """

    def test_search_medicine_strips_the_packaging_suffix_before_filling_the_box(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        found = provider.search_medicine("Paracetamol 500mg (Thùng x 300 hộp x 2 vỉ x 10 viên)")

        # The real regression: with the raw, unstripped string this
        # would never match "TH1 - Paracetamol 500mg"'s text_ends_with
        # filter and so would come back False (an already-existing
        # medicine wrongly looking "not found").
        assert found is True
        assert page.locator("#first-line-search").input_value() == "Paracetamol 500mg"

    def test_search_medicine_leaves_a_name_with_no_parentheses_unchanged(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        assert provider.search_medicine("Coldi") is True
        assert page.locator("#first-line-search").input_value() == "Coldi"

    def test_search_and_select_medicine_for_line_strips_packaging_for_the_first_row(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        item = PurchaseItem(
            id="item-1",
            medicine_name="Paracetamol 500mg (Thùng x 300 hộp x 2 vỉ x 10 viên)",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            retail_units_per_purchase_unit=1,
        )

        provider._search_and_select_medicine_for_line(item, 0)  # noqa: SLF001

        assert page.locator("#first-line-search").input_value() == "Paracetamol 500mg"
        assert page.evaluate("window.medicineResultClickLog") == ["TH1"]
        # The Domain-level field itself must never be touched by this
        # web-search-only stripping.
        assert item.medicine_name == "Paracetamol 500mg (Thùng x 300 hộp x 2 vỉ x 10 viên)"

    def test_search_and_select_medicine_for_line_strips_packaging_for_a_later_row(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        item = PurchaseItem(
            id="item-2",
            medicine_name="Coldi-B DNH (Hop x 10 vi x 10 vien)",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            retail_units_per_purchase_unit=1,
        )

        provider._search_and_select_medicine_for_line(item, 1)  # noqa: SLF001

        assert page.locator("#subsequent-line-search").input_value() == "Coldi-B DNH"
        assert page.evaluate("window.medicineResultClickLog") == ["TH5"]

    def test_strip_packaging_description_helper_edge_cases(self) -> None:
        strip = PlaywrightBrowserAutomationProvider._strip_packaging_description  # noqa: SLF001

        assert strip("Naphacogyl (Thùng x 300 hộp x 2 vỉ x 10 viên)") == "Naphacogyl"
        assert strip("Paracetamol 500mg") == "Paracetamol 500mg"
        assert strip("Coldi-B DNH  (Hop x 10 vi)") == "Coldi-B DNH"
        assert strip("Name (first) (second)") == "Name"
        assert strip("  Padded Name  ") == "Padded Name"

    def test_extract_manufacturer_handles_both_real_po_confirmed_snapshots(self) -> None:
        extract = PlaywrightBrowserAutomationProvider._extract_manufacturer  # noqa: SLF001

        # Real snapshot 1 (2026-08, PO-supplied): 3 fields, no <br>.
        # inner_text() renders each "<b>Label: </b>Value" pair as plain
        # text with the tags stripped, ' - ' still separating fields.
        snapshot_1 = "Giá nhập: .../- Hãng sản xuất: Công ty cổ phần dược phẩm Nam Hà - QCĐG: Lọ"
        assert extract(snapshot_1) == "Công ty cổ phần dược phẩm Nam Hà"

        # Real snapshot 2 (2026-08, PO-supplied): 5 fields, plus a <br>
        # right before "Hãng sản xuất" -- inner_text() renders that as a
        # line break, not a ' - ' separator.
        snapshot_2 = (
            "Giá nhập: 0/Lọ - Tồn: 0.00 (Lọ) - SĐK: 893100160624 - Hoạt chất: "
            "Oxymetazolin hydroclorid -\nHãng sản xuất: Công ty cổ phần dược phẩm Nam Hà - "
            "QCĐG: Lọ"
        )
        assert extract(snapshot_2) == "Công ty cổ phần dược phẩm Nam Hà"

        # No "Hãng sản xuất" label at all -- never invented.
        assert extract("Giá nhập: 100 - Tồn: 5 (Hộp)") is None

    def test_extract_manufacturer_ignores_the_final_field_with_no_trailing_separator(
        self,
    ) -> None:
        extract = PlaywrightBrowserAutomationProvider._extract_manufacturer  # noqa: SLF001

        assert extract("Hãng sản xuất: Công ty ABC") == "Công ty ABC"


class TestMedicineSearchLengthFallback:
    """
    Bug fix (2026-08, PO-confirmed via real hands-on testing -- CRITICAL,
    real search-as-you-type quirk, not an automation bug): typing the
    FULL "Coldi-B DNH" (11 chars) into the real site's search box
    produced NO dropdown at all, while typing just "Coldi-B" (7 chars)
    did, correctly showing "Coldi-B DNH" among the results -- a real,
    not-fully-understood length sensitivity. Not treated as a one-off
    fix for this specific name -- any sufficiently long medicine name
    could plausibly hit the same real threshold, so
    _fill_and_check_medicine_result/_fill_and_check_medicine_result_by_code
    now retry with progressively shorter, word-truncated prefixes (see
    _medicine_search_fill_candidates) whenever the full name alone
    finds nothing, before concluding the medicine does not exist yet.
    The fixture's own 'search_length_limit' query param (see that
    script block's own comment) models the real length sensitivity by
    the TYPED value's own length, not a hardcoded name, so these tests
    exercise the real fallback loop, not a special-cased stub.

    Round 2 (2026-08, PO-confirmed via a real 8000ms/33-check poll):
    word-level truncation alone was proven insufficient for some real
    names -- the true threshold can sit MID-WORD (e.g. "Coldi-", not
    "Coldi-B"), which a word-boundary-only pass can never reach.
    _medicine_search_fill_candidates now falls back further, to
    character-by-character truncation, once word-level candidates are
    exhausted (see that method's own comment).
    """

    @staticmethod
    def _make_item(medicine_name: str, medicine_id: str = "med-1"):
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-1",
            medicine_name=medicine_name,
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id=medicine_id,
            retail_units_per_purchase_unit=1,
        )

    def test_short_name_still_matches_on_the_first_try_no_fallback_needed(
        self, page: Page
    ) -> None:
        # A generous limit (30) never actually blocks "Paracetamol
        # 500mg" (16 chars) -- proves the new candidate-generation loop
        # does not change behavior for the ordinary, already-working
        # case: the FULL name is still tried FIRST, and still succeeds
        # immediately without ever needing a shorter candidate.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?search_length_limit=30")

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Paracetamol 500mg"), 0
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH1"]

    def test_long_name_falls_back_to_a_shorter_prefix_and_selects_the_right_row(
        self, page: Page
    ) -> None:
        # search_length_limit=9: "Coldi-B DNH" (11 chars, the FULL name)
        # exceeds it -- 0 results, exactly the real reported bug --
        # forcing a retry with the shorter, word-truncated "Coldi-B"
        # (7 chars, under the limit), which succeeds. TH4 ("Coldi")
        # also matches that shorter search, proving the FULL name's own
        # end-anchored match (never the truncated prefix) is still what
        # actually selects TH5, not TH4 -- the same disambiguation
        # safety net already proven for the un-truncated case.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?search_length_limit=9")

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Coldi-B DNH"), 0
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH5"]

    def test_word_boundary_still_insufficient_falls_back_to_character_truncation(
        self, page: Page
    ) -> None:
        # Round 2 (2026-08, PO-confirmed via a real 8000ms/33-check poll
        # that proved BOTH the full "Coldi-B DNH" (11 chars) AND the
        # word-truncated "Coldi-B" (7 chars) genuinely matched=False --
        # the real threshold sits MID-WORD, at "Coldi-" (6 chars), which
        # word-level truncation alone can never reach (a single word is
        # never split by _medicine_search_fill_candidates's word-level
        # pass). search_length_limit=6 models exactly that: both
        # word-level candidates (11 and 7 chars) exceed it, forcing the
        # new character-by-character fallback to kick in, which reaches
        # "Coldi-" (6 chars, <= the limit) on its first attempt.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?search_length_limit=6")

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Coldi-B DNH"), 0
        )

        # Even though "Coldi-" was what made the dropdown appear, the
        # actual row clicked is still resolved via an end-anchored match
        # against the FULL "Coldi-B DNH" -- proving selection safety is
        # independent of how short the triggering candidate got.
        assert page.evaluate("window.medicineResultClickLog") == ["TH5"]

    def test_character_truncation_never_goes_below_the_configured_minimum(self) -> None:
        # Direct unit check on the candidate generator itself (no live
        # page needed): for a name whose first word is long enough to
        # keep shortening, the shortest candidate produced must be
        # exactly _MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH chars, never
        # shorter -- an unbounded shrink would eventually search on a
        # near-empty string and surface unrelated noise.
        candidates = PlaywrightBrowserAutomationProvider._medicine_search_fill_candidates(  # noqa: SLF001
            "Coldi-B DNH"
        )

        min_len = (
            PlaywrightBrowserAutomationProvider._MEDICINE_SEARCH_MIN_CHAR_TRUNCATION_LENGTH  # noqa: SLF001
        )
        assert min(len(c) for c in candidates) == min_len
        assert candidates[-1] == "Coldi-B"[:min_len]
        # Word-level candidates ("Coldi-B DNH", "Coldi-B") still come
        # first, unchanged -- character-level ones are a pure addition
        # at the end, never a replacement.
        assert candidates[:2] == ["Coldi-B DNH", "Coldi-B"]

    def test_name_missing_even_after_every_fallback_still_creates_a_new_one(
        self, page: Page
    ) -> None:
        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        class _StubMedicineRepository:
            def __init__(self, medicine: Medicine) -> None:
                self._medicine = medicine

            def get_by_id(self, medicine_id: str) -> Medicine | None:
                return self._medicine if medicine_id == self._medicine.id else None

        medicine = Medicine(
            id="med-new",
            medicine_code="TH99",
            name="Xyzmycin Totally Unknown",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page,
            _registry_with_confirmed_vien_label(),
            config,
            logging.getLogger("test"),
            medicine_repository=_StubMedicineRepository(medicine),
        )
        # search_length_limit=30 -- generous, never the reason nothing
        # is found here (every truncated candidate, down to the first
        # single word "Xyzmycin", genuinely has no match in the
        # fixture's own static result set) -- proves the fallback loop
        # exhausts ALL of its candidates (not just the full name) before
        # correctly falling through to create_medicine(), still ending
        # with the newly-created row selected for this exact line.
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?search_length_limit=30")
        page.evaluate(
            "document.getElementById('open-supplier-dialog').hidden = true;"
            "document.getElementById('tblMain').innerHTML = "
            '\'<button type="button" title="Thêm mới nếu chưa có" '
            'id="open-medicine-dialog" onclick="this.hidden=true">Thêm mới nếu chưa có'
            "</button>'"
        )

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Xyzmycin Totally Unknown", medicine_id="med-new"), 0
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH99"]
        assert page.locator("#medicine-name-input").input_value() == "Xyzmycin Totally Unknown"


class TestMedicineSearchClearsEachCandidateBeforeTheNext:
    """
    Bug fix (2026-08, PO-confirmed via real diagnostic logging): a real
    run's own per-candidate DIAG log proved "Coldi-B" -- a candidate PO
    separately confirmed by hand DOES produce a real match when typed
    into an EMPTY box -- was genuinely tried by
    _fill_medicine_search_until_matched but still read back
    matched=False, right after a DIFFERENT, longer candidate ("Coldi-B
    DNH") had just been tried and failed in the same box. Two real gaps
    fixed together (see _fill_medicine_search_until_matched's own bug-fix
    comment): each retry now goes through _type_into_search_box, which
    real-keyboard-clears (select-all + Backspace) the box before typing
    the next candidate, and the post-type check is now a real poll
    (_poll_until_matched) across the existing settle budget instead of a
    single fixed-offset read.

    "Vitamin C 500mg" (TH3, already a real fixture row -- 3 words) is
    reused here rather than inventing a new one: with
    search_length_limit=8, its own 3-candidate cascade (full "Vitamin C
    500mg"=15 chars -> fails, "Vitamin C"=9 chars -> fails, "Vitamin"=7
    chars -> succeeds) reproduces the exact "the valid candidate is
    neither the first nor the only one tried" shape of the real Coldi-B
    incident, without needing a same-length coincidence.
    """

    @staticmethod
    def _make_item(medicine_name: str, medicine_id: str = "item-1"):
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-1",
            medicine_name=medicine_name,
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id=medicine_id,
            retail_units_per_purchase_unit=1,
        )

    @staticmethod
    def _per_candidate_final_values(value_log: list[str]) -> list[str]:
        """
        press_sequentially logs ONE 'input' event per keystroke (unlike
        the old single-shot .fill()), so the raw log is a long run of
        growing prefixes per candidate, separated by a real "" the
        select-all+Backspace clear produces. Reduces that down to just
        each candidate's own final (fully-typed) value, in order --
        the shape the old, simpler .fill()-based log used to have
        directly.
        """
        runs: list[list[str]] = []
        current: list[str] = []
        for value in value_log:
            if value == "":
                if current:
                    runs.append(current)
                    current = []
            else:
                current.append(value)
        if current:
            runs.append(current)
        return [run[-1] for run in runs]

    def test_each_retried_candidate_is_typed_from_an_empty_box_and_the_last_one_wins(
        self, page: Page
    ) -> None:
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?search_length_limit=8")

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Vitamin C 500mg"), 0
        )

        # The valid candidate ("Vitamin") is neither the first ("Vitamin C
        # 500mg") nor the second ("Vitamin C") tried -- yet TH3 (whose own
        # <b> text ends with the FULL, untruncated "Vitamin C 500mg") is
        # still the exact row that ends up clicked, never a wrong/earlier
        # one.
        assert page.evaluate("window.medicineResultClickLog") == ["TH3"]

        value_log = page.evaluate("window.searchInputValueLog")

        # 3 candidates were really typed, in the expected shrinking order
        # -- reducing the raw per-keystroke log down to each candidate's
        # own final, fully-typed value.
        assert self._per_candidate_final_values(value_log) == [
            "Vitamin C 500mg",
            "Vitamin C",
            "Vitamin",
        ]

        # Every single logged value across the WHOLE run -- every partial
        # keystroke of every candidate -- is a clean prefix of whichever
        # candidate was being typed at that moment. If the box had not
        # been genuinely emptied first, a later candidate's own prefixes
        # would instead start with the previous, longer candidate's
        # leftover text (e.g. "Vitamin C 500mgV"), which is NOT a prefix
        # of "Vitamin C" -- so this single check rules out any leftover
        # content across every candidate boundary, not just the final
        # value.
        candidates = ["Vitamin C 500mg", "Vitamin C", "Vitamin"]
        candidate_index = 0
        for value in value_log:
            if value == "":
                candidate_index += 1
                continue
            assert candidates[candidate_index].startswith(value), (
                f"'{value}' is not a clean prefix of candidate "
                f"'{candidates[candidate_index]}' -- the box was not fully cleared "
                "before this candidate was typed."
            )


class TestMedicineSearchRequiresRealKeyboardEvents:
    """
    Bug fix (2026-08, PO-confirmed via a real, hands-on live-site
    experiment -- CRITICAL, the true root cause behind the Coldi-B race
    _poll_until_matched/_type_into_search_box's own comments describe):
    PO tested directly on the live site -- typing "Coldi-" character by
    character produced real results; PASTING (Ctrl+V) the identical text
    produced none; typing "Coldi-b" then Backspacing the trailing 'b'
    worked. The site's search-as-you-type reacts ONLY to genuine keyboard
    events, never to a box's value merely changing. Playwright's
    .fill()/.clear() are a same-mechanism-as-paste: they set the value
    directly and dispatch 'input', but never dispatch keydown/keyup.

    The fixture's own require_real_keystrokes mode (see
    webnhathuoc_fixture.html's own comment) models this precisely: every
    medicine search result row is hidden until a real 'keyup' lands on
    the search box. These two tests prove the fix with a real,
    executable DOM demonstration, not just reasoning:
    (A) a bare Locator.fill() -- the exact primitive this project used to
        rely on -- never reveals any result under that mode.
    (B) the real provider (now using _type_into_search_box's real
        keystroke simulation) finds and selects the right row under that
        exact same mode.
    """

    @staticmethod
    def _make_item(medicine_name: str, medicine_id: str = "item-1"):
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-1",
            medicine_name=medicine_name,
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id=medicine_id,
            retail_units_per_purchase_unit=1,
        )

    def test_a_plain_fill_never_reveals_results_when_the_site_needs_real_keystrokes(
        self, page: Page
    ) -> None:
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?require_real_keystrokes=1")

        # The exact primitive this project's own _fill()/_clear() used to
        # rely on, applied directly -- no adapter code involved at all.
        page.locator("#first-line-search").fill("Vitamin")

        result_entry_locator = page.locator("[data-medicine-result]", has_text="Vitamin")
        assert result_entry_locator.count() == 0, (
            "A plain .fill() revealed a result under require_real_keystrokes -- the fixture "
            "no longer models the real site's own keyboard-only behavior PO confirmed by hand."
        )

    def test_the_real_provider_now_finds_and_selects_the_row_via_real_keystrokes(
        self, page: Page
    ) -> None:
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(f"{FIXTURE_HTML_PATH.resolve().as_uri()}?require_real_keystrokes=1")

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item("Vitamin C 500mg"), 0
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH3"]


class TestSupplierSearchPollsForRealSettleTime:
    """
    Regression (2026-08, PO-confirmed via a real run): after
    search_supplier()/select_supplier() were switched to
    _type_into_search_box (see TestMedicineSearchRequiresRealKeyboardEvents),
    PO reported "Naphacogyl" -- previously ALWAYS matched=True on the
    first try -- now read matched=False on the very first attempt, and
    the browser showed the supplier's NAME typed into the box but no
    "selected" chip/state, even though the log still said
    "create_supplier succeeded". Root-caused by reading
    _resolve_supplier_on_site (composition_root/cli.py): it calls
    search_supplier() first and only calls select_supplier() if that
    returned True -- otherwise it falls straight to create_supplier(),
    which opens the "add new supplier" dialog and fills a name field
    directly (exactly the "name typed, no selected state" symptom PO
    saw). search_supplier() itself never had any wait/poll at all -- it
    called Locator.count() (which never waits) immediately after typing,
    the exact same "single fixed-offset/no-wait check" class of bug
    already fixed for the medicine search loop
    (_poll_until_matched) -- just never applied to supplier search
    before. Typing character-by-character (_type_into_search_box) takes
    real, measurably longer wall-clock time than the old .fill(), which
    is what turned an already-latent gap into a reliably-reproducing one.
    A false "not found" here doesn't just risk creating a duplicate
    supplier -- it leaves the page in a real different state (an open
    create-supplier dialog) that the PO suspected could then desync the
    NEXT step (the first medicine search) -- see
    TestFullSupplierAndThreeMedicineFlow below for the full-chain proof
    that the fix prevents that too.

    Fixed by making search_supplier() poll (_poll_until_matched) instead
    of a single immediate count() check. The fixture's own
    supplier_search_settle_delay_ms (see webnhathuoc_fixture.html's own
    comment) models a real, non-instant settle delay after the last
    keystroke, the same way row_settle_delay_ms already models it for
    line-item rows.
    """

    def test_a_bare_count_check_right_after_typing_sees_nothing_yet(self, page: Page) -> None:
        # Control: proves the fixture genuinely reproduces a real race
        # (not a check that would trivially pass either way). Bypasses
        # the adapter entirely -- typing directly via Playwright's own
        # press_sequentially, then reading the DOM immediately, exactly
        # mirroring what an unpolled search_supplier() used to do.
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?supplier_search_settle_delay_ms=1500"
        )
        supplier_box = page.locator("#supplier-search")
        supplier_box.click()
        supplier_box.press_sequentially("Cong ty Duoc ABC")

        assert page.locator("#supplier-search-results span").count() == 0, (
            "The fixture's supplier_search_settle_delay_ms mode should hide the real result "
            "until the configured delay elapses -- an immediate check must see nothing yet."
        )

    def test_search_supplier_waits_out_the_real_settle_delay_and_still_finds_it(
        self, page: Page
    ) -> None:
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        # 1500ms settle delay, well inside _SEARCH_RESULT_POLL_BUDGET_MS's
        # 8000ms poll budget that _poll_until_matched now also governs
        # search_supplier() with.
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}?supplier_search_settle_delay_ms=1500"
        )

        assert provider.search_supplier("Cong ty Duoc ABC") is True


class TestFullSupplierAndThreeMedicineFlow:
    """
    PO explicitly asked for a full-chain test after the regression above
    (2026-08): "test thật lại với TOÀN BỘ luồng (nhà cung cấp + cả 3
    thuốc) ... vì lỗi lần này có dấu hiệu là hiệu ứng dây chuyền giữa 2
    bước, không phải lỗi cô lập 1 chỗ." Drives the REAL production
    orchestration function (composition_root.cli._automate_one_invoice --
    not a hand-reimplemented copy of its logic) against the real
    PlaywrightBrowserAutomationProvider and the real fixture, with
    supplier_search_settle_delay_ms set so the real settle-time gap that
    triggered the regression is actually exercised, then asserts BOTH
    halves of the chain: the supplier ends up genuinely SELECTED (not
    silently created instead), AND all 3 real medicine lines after it
    still resolve correctly -- proving no state corruption leaked from
    one step into the next.
    """

    @staticmethod
    def _build_invoice_and_container(tmp_path: Path):
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.entities.project import Project
        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.entities.supplier import Supplier
        from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
            MedicineRepository,
        )
        from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
            ProjectRepository,
        )
        from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (  # noqa: E501
            PurchaseInvoiceRepository,
        )
        from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
            SupplierRepository,
        )
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit
        from pharmacy_invoice_automation.infrastructure.di.registration import (
            register_infrastructure_services,
        )
        from pharmacy_invoice_automation.infrastructure.di.service_container import (
            ServiceContainer,
        )

        container = ServiceContainer()
        register_infrastructure_services(container, tmp_path / "app")
        container.resolve(ProjectRepository).add(
            Project(id="proj-1", name="Test Project", root_folder=str(tmp_path))
        )
        # Name must match the fixture's own real supplier-search-result
        # span text ("Cong ty Duoc ABC - 123 Le Loi") for supplier.
        # search_result_option's substring match to find it.
        container.resolve(SupplierRepository).add(Supplier(id="sup-1", name="Cong ty Duoc ABC"))

        # TH1/TH2/TH3's own real fixture rows -- each an unambiguous,
        # single-match medicine name, so this test proves the medicine
        # loop itself (already covered elsewhere) still works after the
        # supplier step, not a re-test of disambiguation.
        medicine_names = ["Paracetamol 500mg", "Amoxicillin 500mg", "Vitamin C 500mg"]
        medicine_repository = container.resolve(MedicineRepository)
        for i, name in enumerate(medicine_names, start=1):
            medicine_repository.add(
                Medicine(
                    id=f"med-{i}",
                    medicine_code=f"TH{i}",
                    name=name,
                    medicine_type=MedicineType.OVER_THE_COUNTER,
                    unit=Unit(code="vien"),
                )
            )
        items = [
            PurchaseItem(
                id=f"item-{i}",
                medicine_name=name,
                unit=Unit(code="vien"),
                quantity=Quantity(Decimal("5")),
                unit_price=Money(Decimal("10000")),
                medicine_id=f"med-{i}",
                retail_units_per_purchase_unit=1,
            )
            for i, name in enumerate(medicine_names, start=1)
        ]
        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
            status=InvoiceStatus.READY_FOR_IMPORT,
            supplier_id="sup-1",
            items=items,
        )
        container.resolve(PurchaseInvoiceRepository).add(invoice)
        return invoice, container

    def test_supplier_is_selected_not_created_and_all_three_medicines_still_resolve(
        self, page: Page, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pharmacy_invoice_automation.composition_root import cli

        invoice, container = self._build_invoice_and_container(tmp_path)
        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        # Both a real supplier-search settle delay AND a real medicine-
        # search settle delay, combined in ONE run -- stress-tests every
        # poll path this audit touched (search_supplier, search_medicine
        # via the per-line candidate loop) together, not in isolation,
        # per the explicit request that follow-up regressions kept
        # appearing one at a time when tested separately.
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?supplier_search_settle_delay_ms=1500&medicine_search_settle_delay_ms=1000"
        )

        def _confirm(_: str) -> str:
            return cli._AUTOMATION_CONFIRMATION_PHRASE  # noqa: SLF001

        with caplog.at_level(logging.INFO, logger="test"):
            result = cli._automate_one_invoice(  # noqa: SLF001
                invoice, container, provider, _confirm, dry_run=True
            )

        assert result.skipped is False
        assert result.outcome is not None
        assert result.outcome.success is True, result.outcome.failure_reason

        # The supplier was genuinely SELECTED, not routed to
        # create_supplier()'s own "add new supplier" dialog -- that
        # dialog must never have been opened.
        assert page.locator("#create-supplyer-dialog").is_hidden()
        assert page.locator("#supplier-search").input_value() == "Cong ty Duoc ABC"

        # All 3 real medicine lines after the supplier step still
        # resolved and clicked correctly, in order -- no state left over
        # from the supplier step corrupted the medicine search that
        # follows it.
        assert page.evaluate("window.medicineResultClickLog") == ["TH1", "TH2", "TH3"]

        # Per-medicine is_match() proof, not just the aggregate click
        # log: _fill_medicine_search_until_matched's own DIAG log records
        # matched=True/False for every candidate it actually tried. Every
        # one of the 3 real medicine names must show its FULL name
        # (single-candidate, well under any length-fallback threshold)
        # resolving matched=True -- never a silent matched=False that
        # merely happened to still end in the right click via some other
        # path.
        diag_lines = [
            record.getMessage() for record in caplog.records if record.getMessage().startswith(
                "DIAG: candidate"
            )
        ]
        for name in ["Paracetamol 500mg", "Amoxicillin 500mg", "Vitamin C 500mg"]:
            expected = f"DIAG: candidate rut ngan '{name}' (goc: '{name}') -> matched=True"
            assert expected in diag_lines, (
                f"expected a matched=True DIAG line for '{name}', got: {diag_lines}"
            )


class TestMedicineResolutionMergedIntoPerLineLoop:
    """
    Bug fix (2026-08, PO-confirmed via direct real-time observation of a
    dry-run): resolving/creating a missing medicine used to be a SEPARATE
    pre-pass over every line item (composition_root.cli._resolve_medicine_on_site,
    now removed), run entirely BEFORE any line was ever searched+selected --
    typing every item's name into the search box back-to-back with no
    selection/commit in between. PO observed this directly (search box
    cycling through all 3 line items' names, no "fill_and_save_invoice"
    log line, before a real add_new_trigger failure) and confirmed the
    real site's own workflow is "resolve THIS medicine fully (search,
    create if missing, select), fill its qty/price/VAT, confirm the row
    -- only then move to the next medicine."
    _search_and_select_medicine_for_line now owns that whole per-line
    resolution itself (see its own docstring) instead of a separate
    pre-pass: it fills THIS row's own index-aware search box exactly
    once, and only falls back to _create_medicine_for_line on a genuine
    zero-result search for THIS row, immediately re-checking the SAME box
    afterward before selecting -- one medicine fully committed before
    moving to the next.

    Uses _registry_with_confirmed_vien_label()'s TEST-ONLY override (see
    its own docstring) since the real registry's unit_display_label is
    genuinely unconfirmed and always stops create_medicine() early
    (TestUnverifiedFlowsFailCleanlyInsteadOfGuessing) -- this override
    exists purely to exercise the create-then-reselect handoff itself,
    not to claim real evidence for that still-open mapping.
    """

    def test_medicine_not_found_is_created_then_immediately_selected_for_its_own_line(
        self, page: Page
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        class _StubMedicineRepository:
            def __init__(self, medicine: Medicine) -> None:
                self._medicine = medicine

            def get_by_id(self, medicine_id: str) -> Medicine | None:
                return self._medicine if medicine_id == self._medicine.id else None

        medicine = Medicine(
            id="med-new",
            medicine_code="TH99",
            name="Xyzmycin 999",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page,
            _registry_with_confirmed_vien_label(),
            config,
            logging.getLogger("test"),
            medicine_repository=_StubMedicineRepository(medicine),
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        # #tblMain's trigger only appears after the supplier step in the
        # fixture's own flow; inserted directly here since this test is
        # only concerned with the medicine step in isolation (same setup
        # as TestUnverifiedFlowsFailCleanlyInsteadOfGuessing's own test).
        page.evaluate(
            "document.getElementById('open-supplier-dialog').hidden = true;"
            "document.getElementById('tblMain').innerHTML = "
            '\'<button type="button" title="Thêm mới nếu chưa có" '
            'id="open-medicine-dialog" onclick="this.hidden=true">Thêm mới nếu chưa có'
            "</button>'"
        )

        item = PurchaseItem(
            id="item-1",
            medicine_name="Xyzmycin 999",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id="med-new",
            retail_units_per_purchase_unit=1,
        )

        # No matching result exists yet -- must create it, then find and
        # click the SAME row it just created, not merely prove
        # create_medicine() was called (that would leave the actual bug
        # being fixed, the handoff to selection, unproven).
        provider._search_and_select_medicine_for_line(item, 0)  # noqa: SLF001

        assert page.evaluate("window.medicineResultClickLog") == ["TH99"]
        assert page.locator("#medicine-name-input").input_value() == "Xyzmycin 999"

    def test_medicine_still_missing_after_create_raises_instead_of_selecting_the_wrong_row(
        self, page: Page
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            AutomationError,
        )

        # No medicine_repository injected -- _create_medicine_for_line
        # must raise cleanly rather than silently selecting an unrelated
        # existing row (e.g. via a loose substring match).
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        item = PurchaseItem(
            id="item-1",
            medicine_name="Totally Unknown Drug",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id="med-unknown",
            retail_units_per_purchase_unit=1,
        )

        with pytest.raises(AutomationError, match="MedicineRepository"):
            provider._search_and_select_medicine_for_line(item, 0)  # noqa: SLF001


class TestMedicineSelectionByKnownWebsiteCatalogCode:
    """
    Part 1 of the multi-result-disambiguation feature (2026-08, PO-
    approved -- an addition to Domain, matching the already-built
    retail_units_per_purchase_unit "hoc 1 lan, nho mai mai" precedent).
    PO confirmed "Naphacogyl" alone appears on >= 4 distinct real
    catalog rows -- a plain name-suffix match cannot disambiguate that
    (Playwright refuses, in strict mode, to click a locator matching
    more than one element). Once a real selection has been confirmed
    once -- by Parts 2/3 (see TestMedicineDisambiguationByHumanSelection)
    or by a prior run -- and its exact website_catalog_code (SDK) saved
    onto Medicine, this class proves _search_and_select_medicine_for_line
    skips the ambiguous name match entirely and goes straight to the
    right row by that code -- the fixture's TH6/TH7 rows share the
    IDENTICAL name "Naphacogyl" on purpose, unlike TH4/TH5's differing
    suffixes, to model this exact real case.
    """

    def test_selects_the_exact_row_by_code_ignoring_the_ambiguous_name(self, page: Page) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        class _StubMedicineRepository:
            def __init__(self, medicine: Medicine) -> None:
                self._medicine = medicine

            def get_by_id(self, medicine_id: str) -> Medicine | None:
                return self._medicine if medicine_id == self._medicine.id else None

        # Confirmed in a PRIOR run (Parts 2/3, not built here) as TH7,
        # not TH6 -- both share the identical display name "Naphacogyl".
        medicine = Medicine(
            id="med-naphacogyl",
            medicine_code="TH7",
            name="Naphacogyl",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
            website_catalog_code="TH7",
        )
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        provider_with_code = PlaywrightBrowserAutomationProvider(
            page,
            real_registry,
            config,
            logging.getLogger("test"),
            medicine_repository=_StubMedicineRepository(medicine),
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        item = PurchaseItem(
            id="item-1",
            medicine_name="Naphacogyl",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id="med-naphacogyl",
            retail_units_per_purchase_unit=1,
        )

        provider_with_code._search_and_select_medicine_for_line(item, 0)  # noqa: SLF001

        # Proves the CORRECT one of the two identically-named rows was
        # picked -- not just that some click succeeded.
        assert page.evaluate("window.medicineResultClickLog") == ["TH7"]


class TestMedicineDisambiguationByHumanSelection:
    """
    Parts 2+3 of the multi-result-disambiguation feature (2026-08,
    PO-approved, PO-supplied real DOM evidence for both parts --
    superseding the old "an ambiguous name with no known code always
    fails cleanly via Playwright strict mode" behavior this class used
    to cover, back when Parts 2/3 were not yet built). Reuses TH6/TH7's
    identically-named "Naphacogyl" rows (see
    TestMedicineSelectionByKnownWebsiteCatalogCode's own docstring), now
    with a distinct "Hãng sản xuất" per row (medicine.search_result_info_item)
    so Part 2's suggestion logic has something real to compare against an
    invoice's Supplier. Never asserts that the suggested row is the one
    actually selected -- Part 2 is an informational hint only; the real,
    binding choice is always whatever a human (simulated here via the
    fixture's auto_select_medicine_code/auto_select_medicine_after_ms
    query params -- see that script block's own comment) actually clicks.
    """

    @staticmethod
    def _make_item():
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-1",
            medicine_name="Naphacogyl",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id="med-naphacogyl",
            retail_units_per_purchase_unit=1,
        )

    def test_waits_for_a_real_later_dom_change_then_persists_whichever_row_was_picked(
        self, page: Page
    ) -> None:
        from pharmacy_invoice_automation.domain.entities.medicine import Medicine
        from pharmacy_invoice_automation.domain.enums.medicine_type import MedicineType
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        class _StubMedicineRepository:
            def __init__(self, medicine: Medicine) -> None:
                self._medicine = medicine
                self.updated: list[Medicine] = []

            def get_by_id(self, medicine_id: str) -> Medicine | None:
                return self._medicine if medicine_id == self._medicine.id else None

            def update(self, medicine: Medicine) -> None:
                self.updated.append(medicine)

        medicine = Medicine(
            id="med-naphacogyl",
            medicine_code="TH-NAP",
            name="Naphacogyl",
            medicine_type=MedicineType.OVER_THE_COUNTER,
            unit=Unit(code="vien"),
        )
        medicine_repository = _StubMedicineRepository(medicine)
        # This row's own manufacturer does NOT match the supplier below
        # (TH6's does) -- proving Part 2's suggestion never overrides
        # whatever the human actually picked.
        supplier = Supplier(id="sup-1", name="Công ty cổ phần dược phẩm Nam Hà")
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=8_000
        )
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page,
            real_registry,
            config,
            logging.getLogger("test"),
            medicine_repository=medicine_repository,
        )
        # 3500ms is deliberately AFTER _wait_for_human_medicine_selection
        # has already started polling (_MEDICINE_SELECTION_SETTLE_MS's
        # own fixed 2500ms fill-settle wait runs first) -- proves this
        # genuinely polls for a later DOM change, not just checking once.
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH7&auto_select_medicine_after_ms=3500"
        )

        disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item(), 0, supplier
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH7"]
        assert len(medicine_repository.updated) == 1
        assert medicine_repository.updated[0].website_catalog_code == "TH7"

    def test_waits_through_the_real_gap_between_aria_expanded_and_the_chip_rendering(
        self, page: Page
    ) -> None:
        """
        BUG FIX (2026-08, PO-confirmed via a real dry-run -- CRITICAL,
        race condition): PO reported the run failing within seconds of
        a real, decisive click -- not a timeout issue, since PO's own
        180s budget was nowhere close to exhausted. Root cause: the
        original implementation checked aria-expanded='false' and the
        chip's visibility as two SEPARATE sequential waits, so a real
        (short) AngularJS digest-cycle gap between the two -- aria-
        expanded flips immediately, the chip renders slightly later --
        could fail the second, independently-and-more-tightly-bounded
        check even though the human selection had genuinely completed.
        chip_render_delay_ms models that exact real gap (aria-expanded
        flips on click; the chip is inserted 400ms later, on its own
        timer, independent of the click) -- proves the combined poll
        waits through it instead of failing early.

        auto_select_medicine_after_ms=1500 (2026-08, raised from the
        original 200 -- test-only timing fix, no production code
        touched): the fixture's auto-select timer is anchored to page
        load, wall-clock, not to when this test's own typing actually
        happens. Once search_medicine/select_medicine switched from
        Playwright's instant .fill() to real per-character typing
        (_type_into_search_box, see its own comment), 200ms was no
        longer reliably AFTER that typing finished -- a genuine race
        where the simulated click could land mid-typing, and a
        still-in-flight keystroke's own 'input' handler would flip
        aria-expanded back to 'true' right after the click had just set
        it 'false', with no further click ever following to fix it
        again (DIAG logs during the failure showed exactly this: chip
        present, aria-expanded stuck at 'true' for the full budget).
        1500ms is a generous margin comfortably after typing+polling+
        Part 2's suggestion logging finish, while still well inside
        this test's own 5000ms human_disambiguation_timeout_ms budget.
        """
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=5_000
        )
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=1500"
            "&chip_render_delay_ms=400"
        )

        disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item(), 0
        )

        assert page.evaluate("window.medicineResultClickLog") == ["TH6"]

    def test_logs_a_suggestion_for_the_row_whose_manufacturer_matches_the_supplier(
        self, page: Page, caplog: pytest.LogCaptureFixture
    ) -> None:
        supplier = Supplier(id="sup-1", name="Công ty cổ phần dược phẩm Nam Hà")
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=8_000
        )
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        logger_name = "test.medicine_disambiguation_suggestion"
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger(logger_name)
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=500"
        )

        with caplog.at_level(logging.INFO, logger=logger_name):
            disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
                self._make_item(), 0, supplier
            )

        messages = "\n".join(record.getMessage() for record in caplog.records)
        # TH6's own manufacturer is exactly the supplier's name; TH7's is
        # a different, unrelated company -- proves the suggestion picks
        # out the right row and does not flag the wrong one too.
        assert "MATCHES" in messages
        assert "Công ty cổ phần dược phẩm Nam Hà" in messages
        assert "Công ty TNHH Dược phẩm Trung ương 3" in messages

    def test_no_human_selection_within_the_timeout_fails_cleanly_not_a_silent_guess(
        self, page: Page
    ) -> None:
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            VerificationFailedError,
        )

        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=300
        )
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        # No auto_select_medicine_code -- nobody ever completes the pick.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        with pytest.raises(VerificationFailedError, match="Part 3"):
            disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
                self._make_item(), 0
            )

    def test_reads_the_right_chip_out_of_two_simultaneously_open_drug_search_boxes(
        self, page: Page
    ) -> None:
        """
        BUG FIX #2 (2026-08, PO-confirmed via real DOM inspection of the
        actual line-item table): medicine.drug_search_box
        (#drugSearchBoxId) is NOT page-wide-unique -- PO observed a real
        count of 2 with two rows simultaneously in edit mode, one
        already selected and one still empty. This fixture models
        EXACTLY that: two '#drugSearchBoxId' elements exist
        unconditionally (one per search input), and this test explicitly
        asserts there are 2 of them at read time, only one of which has
        a chip -- proving _selected_match_container_locator's
        filter-by-content approach picks the right one instead of
        assuming a fixed position/count.

        auto_select_medicine_after_ms=1500 -- same test-only timing fix
        as test_waits_through_the_real_gap_between_aria_expanded_and_
        the_chip_rendering's own comment (raised from 200; a keystroke
        still in flight when the simulated click fired could flip
        aria-expanded back to 'true' right after the click set it
        'false', with nothing left to correct it -- see that test's
        comment for the full DIAG-log evidence). No production code
        changed.
        """
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=5_000
        )
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH7&auto_select_medicine_after_ms=1500"
        )

        disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_item(), 0
        )

        assert page.evaluate("document.querySelectorAll('#drugSearchBoxId').length") == 2
        containing_chip = page.evaluate(
            "[...document.querySelectorAll('#drugSearchBoxId')]"
            ".filter(el => el.querySelector('.ui-select-match-item')).length"
        )
        assert containing_chip == 1
        assert page.evaluate("window.medicineResultClickLog") == ["TH7"]

    def test_more_than_one_chip_at_once_fails_cleanly_not_a_silent_guess(
        self, page: Page
    ) -> None:
        """
        Defensive case PO explicitly asked for: if _selected_match_container_locator
        ever finds MORE than one drug_search_box simultaneously containing
        a chip (an unexpected state -- not the normal "still waiting"
        one), it must raise a clear error instead of arbitrarily picking
        one. Simulated by injecting a second, decoy chip into the OTHER
        (normally empty) drug_search_box right as the real one appears.
        """
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            VerificationFailedError,
        )

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=3_000
        )
        disambiguation_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=200"
        )
        # Decoy: injects a second chip into subsequent-line-search's own
        # (otherwise empty) drug_search_box, simulating two rows
        # simultaneously showing a chip.
        #
        # BUG FIX (2026-08, discovered while speeding up
        # _fill_and_check_medicine_result's own settle check from a fixed
        # wait to a real poll -- see _poll_until_matched): this used to
        # fire the decoy from a bare setTimeout(..., 400), racing the REAL
        # auto-select's own 200ms timer purely on wall-clock time. That
        # only ever passed because the fixed 2500ms wait this test never
        # exercises directly (_MEDICINE_SELECTION_SETTLE_MS, formerly
        # always paid in full before _search_and_select_medicine_for_line
        # ever reached the disambiguation poll) incidentally burned enough
        # real time for BOTH timers to fire first. Once the settle check
        # became a real poll that returns as soon as it matches (already
        # true here -- both real fixture rows are present from page load),
        # _wait_for_human_medicine_selection's own poll started ticking
        # almost immediately -- well before the decoy's 400ms timer -- and
        # legitimately (correctly, per its own single-tick-success
        # contract) returned success on seeing only the real chip, never
        # observing the decoy at all. Not a production bug: this test's
        # own decoy was racing an unrelated fixed wait it was never
        # supposed to depend on. Fixed by making the decoy deterministic
        # instead of time-based -- attached directly to the SAME click
        # event the real auto-selection fires (chip_render_delay_ms is
        # unset/0 here, so the fixture's own real chip is inserted
        # synchronously inside that same click handler), so the decoy is
        # guaranteed to exist before the click's event dispatch even
        # returns -- before any Playwright-side poll can possibly read the
        # DOM -- regardless of how fast or slow the code under test is.
        page.evaluate(
            """
            () => {
              const target = document.querySelector('[data-medicine-result="TH6"]');
              target.addEventListener("click", () => {
                const decoyBox = document.getElementById("subsequent-line-search").parentNode;
                const chip = document.createElement("span");
                chip.className = "ui-select-match-item btn btn-default btn-xs";
                chip.innerHTML =
                  '<span class="close ui-select-match-close">&times;</span>' +
                  '<span><span class="ng-binding ng-scope">DECOY - Other Row</span></span>';
                decoyBox.insertBefore(chip, document.getElementById("subsequent-line-search"));
              });
            }
            """
        )

        with pytest.raises(VerificationFailedError, match="Part 3"):
            disambiguation_provider._search_and_select_medicine_for_line(  # noqa: SLF001
                self._make_item(), 0
            )


class TestMedicineSearchAfterHeavyDisambiguationStillPolls:
    """
    Investigation (2026-08, PO-confirmed via a real run): after the
    full-file poll audit above, "Coldi" -- going through the SAME
    already-polling candidate loop that had just correctly resolved
    "Naphacogyl" moments earlier in the SAME run -- still read back
    matched=False. Code-review finding (documented here, not just
    asserted): each _poll_until_matched call starts its own
    `elapsed_ms = 0` completely fresh -- nothing carries over from a
    PRECEDING call, so there was never a code-level "budget gets
    consumed/shrunk by prior work" bug. Whether a heavy disambiguation
    leaves the real PAGE ITSELF slower to answer the very next search
    (a real performance/network effect this local, synchronous fixture
    cannot fully replicate) was left an open question.

    STRATEGY DECISION (2026-08, PO-confirmed, ends the chase): rather
    than keep hunting an ever-more-precise timing number across this and
    future real-run reports, PO decided to make the poll budget
    generous by policy -- see `_SEARCH_RESULT_POLL_BUDGET_MS`'s own
    comment in playwright_adapter.py for the full reasoning (real
    network/server variance, a real `refresh-delay="500"` attribute
    already observed on the site's own widget, real per-character typing
    coupling total search time to real network conditions). Raised from
    2500ms to 8000ms. This class's own tests below still hold under the
    new budget -- they were written to prove the mechanism's
    budget-independence property, which does not change with the
    number, only their own settle-delay values needed adjusting to stay
    meaningfully near/over the NEW 8000ms budget instead of the old one.
    """

    @staticmethod
    def _make_naphacogyl_item() -> object:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-1",
            medicine_name="Naphacogyl",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            medicine_id="med-naphacogyl",
            retail_units_per_purchase_unit=1,
        )

    @staticmethod
    def _make_vitamin_c_item() -> object:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id="item-2",
            medicine_name="Vitamin C 500mg",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            retail_units_per_purchase_unit=1,
        )

    def test_a_second_medicine_needing_almost_the_full_budget_still_succeeds_right_after_a_heavy_disambiguation(  # noqa: E501
        self, page: Page, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Item 1 (Naphacogyl) goes through a REALISTIC heavy Part 2+3
        disambiguation: a real 3-SECOND wait for the simulated human
        pick (auto_select_medicine_after_ms=3000) plus the real
        aria-expanded/chip-render gap (chip_render_delay_ms=400) --
        several real seconds of DOM interaction + a real
        website_catalog_code persist, immediately before item 2's own
        search even starts. item 2 (Vitamin C 500mg) additionally needs
        a settle delay of 7000ms -- close to, but with a real 1000ms
        safety margin under, _SEARCH_RESULT_POLL_BUDGET_MS's own 8000ms
        poll budget (2026-08, PO-decided generous ceiling -- see that
        constant's own comment for the full reasoning; a much thinner
        100ms margin was tried first and found flaky -- Playwright's own
        wait_for_timeout scheduling has enough real jitter across ~30
        poll iterations that a thin margin is not reliable) -- to show a
        real, substantial settle delay right after that heavy prior work
        still succeeds.

        The settle-delay gate is installed dynamically via
        _INSTALL_SETTLE_DELAY_JS, AFTER item 1 already finished, not via
        the fixture's own page-load-only medicine_search_settle_delay_ms
        param: that param would ALSO gate item 1's own initial
        "Naphacogyl" search (both items share the same results
        table/inputs) -- a first attempt using it at 7000ms raced against
        auto_select_medicine_after_ms's fixed 3000ms timer (item 1's own
        rows were still hidden, waiting on the SAME 7000ms delay, when
        the auto-select tried to click TH6 at the 3000ms mark -- the
        target did not exist in the DOM yet, so the click silently
        no-opped and Part 3 timed out). Installing the gate only after
        item 1 completes avoids that entirely.

        This does NOT prove the REAL site's actual post-disambiguation
        delay is under 8000ms (this fixture cannot model true
        server/network latency) -- it proves the poll mechanism ITSELF
        is not starved/shortened by the preceding heavy operation, i.e.
        item 2 gets its own full, fresh budget regardless of what item 1
        just went through.
        """
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=8_000
        )
        provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=3000"
            "&chip_render_delay_ms=400"
        )

        provider._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_naphacogyl_item(), 0
        )
        assert page.evaluate("window.medicineResultClickLog") == ["TH6"]

        page.evaluate(self._INSTALL_SETTLE_DELAY_JS, 7000)

        with caplog.at_level(logging.INFO, logger="test"):
            provider._search_and_select_medicine_for_line(  # noqa: SLF001
                self._make_vitamin_c_item(), 1
            )

        assert page.evaluate("window.medicineResultClickLog") == ["TH6", "TH3"]

        # The elapsed-time DIAG instrumentation itself: item 2's own poll
        # genuinely ran close to (not instantly under) the 7000ms delay,
        # proving this was a real, non-trivial wait actually consumed by
        # THIS item's own call, not a leftover/cached signal from item 1.
        vitamin_c_diag = [
            record.getMessage()
            for record in caplog.records
            if "candidate 'Vitamin C 500mg'" in record.getMessage()
            and record.getMessage().startswith("DIAG poll")
        ]
        assert len(vitamin_c_diag) == 1
        assert "matched=True" in vitamin_c_diag[0]

    # Reused JS installs the exact same reveal-after-a-real-delay gate
    # webnhathuoc_fixture.html's own medicine_search_settle_delay_ms URL
    # param installs -- but at an arbitrary later moment via
    # page.evaluate, not only at page-load. Needed so item 2's search
    # can be gated WITHOUT also gating item 1's own initial "Naphacogyl"
    # search (both share the same results table/inputs, so a page-load
    # URL param would delay item 1's own disambiguation-triggering
    # search too, breaking the "item 1 heavy op already finished, THEN
    # item 2 hits the delay" scenario this test needs).
    _INSTALL_SETTLE_DELAY_JS = """
        (delayMs) => {
          const resultsTable = document.getElementById("medicine-search-results-table");
          const allRows = [...resultsTable.children];
          allRows.forEach((row) => row.remove());
          let timer = null;
          ["first-line-search", "subsequent-line-search"].forEach((inputId) => {
            const el = document.getElementById(inputId);
            if (!el) return;
            el.addEventListener("keyup", () => {
              if (timer) clearTimeout(timer);
              timer = setTimeout(() => {
                allRows.forEach((row) => resultsTable.appendChild(row));
              }, delayMs);
            });
          });
        }
        """

    def test_the_same_over_budget_delay_fails_identically_with_or_without_a_preceding_heavy_op(
        self, page: Page
    ) -> None:
        """
        Baseline/control: 20000ms -- well OVER _SEARCH_RESULT_POLL_BUDGET_MS's
        8000ms budget, with a large (12s) safety margin, not a thin one
        -- fails for Vitamin C 500mg whether or not a heavy Naphacogyl
        disambiguation ran immediately before it. Same threshold, same
        outcome, either way -- further evidence (on top of the code-
        review finding in this class's own docstring) that there is no
        "budget gets consumed by prior work" bug: the poll's budget is
        strictly a fixed, fresh-per-call constant, not something a
        preceding heavy operation can shrink or inflate.
        """
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        provider_alone = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.evaluate(self._INSTALL_SETTLE_DELAY_JS, 20_000)

        alone_result = provider_alone.search_medicine("Vitamin C 500mg")

        assert alone_result is False

        # Fresh page: the SAME heavy Naphacogyl disambiguation as the
        # test above, run to completion FIRST with no delay gate active
        # (so item 1's own search behaves normally) -- only THEN is the
        # identical 20000ms settle-delay gate installed, isolating it to
        # item 2's own search, on the very same page/box right after.
        real_registry_2 = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config_2 = PlaywrightAutomationConfig(
            username="u", password="p", human_disambiguation_timeout_ms=8_000
        )
        provider_after_heavy_op = PlaywrightBrowserAutomationProvider(
            page, real_registry_2, config_2, logging.getLogger("test")
        )
        page.goto(
            f"{FIXTURE_HTML_PATH.resolve().as_uri()}"
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=3000"
            "&chip_render_delay_ms=400"
        )

        provider_after_heavy_op._search_and_select_medicine_for_line(  # noqa: SLF001
            self._make_naphacogyl_item(), 0
        )
        assert page.evaluate("window.medicineResultClickLog") == ["TH6"]

        page.evaluate(self._INSTALL_SETTLE_DELAY_JS, 20_000)
        found = provider_after_heavy_op.search_medicine("Vitamin C 500mg")

        assert found is False


class TestUpdateRetailPricesAfterSave:
    """
    Part 2 amendment (2026-08, PO): "Giá bán lẻ" is a Medicine-level
    price, confirmed reachable only via Sửa -> Chỉnh sửa thuốc AFTER the
    invoice is first saved (05_full_flow...py:146-151) -- not inline in
    the per-line fill loop. Exercises the real PricePolicy calculation
    plus real Playwright clicks/fills against the confirmed
    invoice.edit_link / invoice_line.edit_medicine_button /
    invoice_line.edit_dialog_close_button locators, isolated from the
    broader per-line fill loop (still not fully testable end-to-end --
    see invoice_line.unit_price_field's notes on the unresolved
    row-scoping question, PO decision 2026-08).
    """

    def test_updates_every_item_using_the_real_price_policy_calculation(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        import uuid
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        # Row 1 is pre-seeded; row 2 needs a real #add-row-button click
        # (row-scoping fix, 2026-08 -- _update_retail_prices_after_save
        # now resolves each row's own "Chỉnh sửa thuốc" trigger via
        # _line_item_rows(), so a 2nd real <tbody> row must actually
        # exist, not just a 2nd flat, page-wide button).
        page.click("#add-row-button")
        page.click("#save-invoice")  # reveals #edit-invoice-link, as after a real first save

        def _make_item(unit_price: str) -> PurchaseItem:
            # STRATEGY CHANGE (2026-08): Vien conversion is gone --
            # _update_retail_prices_after_save now feeds this invoice's
            # own original unit_price directly into PricePolicy, no
            # per-Vien conversion beforehand.
            return PurchaseItem(
                id=str(uuid.uuid4()),
                medicine_name="Some Medicine",
                unit=Unit(code="hop"),
                quantity=Quantity(Decimal("1")),
                unit_price=Money(Decimal(unit_price)),
            )

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
        )
        # 100000 -> 120000.0 (exact); 120840 -> 145008.0 -> rounds to
        # 145000 -- same two boundary-rounding cases as
        # tests/unit/domain/services/test_price_policy.py, proving this
        # call path uses the real PricePolicy, not a reimplementation.
        invoice.add_item(_make_item("100000"))
        invoice.add_item(_make_item("120840"))

        provider._update_retail_prices_after_save(invoice)  # noqa: SLF001

        log_entries = page.locator("#retail-price-log li").all_text_contents()
        assert log_entries == ["1|120000", "2|145000"]

    def test_clicks_edit_link_exactly_once_not_once_per_item(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        import uuid
        from datetime import date
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        page.click("#add-row-button")  # row 2's own <tbody> (row 1 is pre-seeded)
        page.click("#save-invoice")
        page.evaluate(
            "document.getElementById('edit-invoice-link')"
            ".addEventListener('click', () => { window.editLinkClicks = "
            "(window.editLinkClicks || 0) + 1; })"
        )

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        for _ in range(2):  # 2 real rows: row 1 (pre-seeded) + row 2 (#add-row-button above)
            invoice.add_item(
                PurchaseItem(
                    id=str(uuid.uuid4()),
                    medicine_name="Some Medicine",
                    unit=Unit(code="hop"),
                    quantity=Quantity(Decimal("1")),
                    unit_price=Money(Decimal("10000")),
                    retail_units_per_purchase_unit=1,
                )
            )

        provider._update_retail_prices_after_save(invoice)  # noqa: SLF001

        assert page.evaluate("window.editLinkClicks") == 1
        assert page.locator("#retail-price-log li").count() == 2


class TestEditMedicineButtonRowScoping:
    """
    Bug fix (2026-08, PO-confirmed via a real DOM snapshot of row 2's
    own "Chỉnh sửa thuốc" button -- CRITICAL, matched a real production
    symptom exactly: row 1's own retail price always came out correct,
    row 2+ always missing/wrong): the button has no id and no per-row
    suffix of its own -- "cấu trúc giống hệt nhau cho mọi dòng" --  so
    the prior page-wide nth(index) lookup (_click_at_index, now
    removed) had no guarantee of landing on the right row.
    _click_edit_medicine_button_for_row now resolves it the exact same
    _line_item_rows().nth() way invoice_line.select_row_for_batch_button
    already does.

    Exercises a real 3-item fill_and_save_invoice() end to end (the
    same real Phase 1 search+select+fill path
    TestTwoPhaseFillAndSaveInvoice already proves), then confirms each
    row's own "Chỉnh sửa thuốc" click opened the dialog for the SAME
    medicine actually selected for THAT row -- checked via the
    medicine's own name/code text the fixture's dialog displayed
    (#retail-price-dialog-medicine-name, logged per entry), never just
    "some dialog opened" -- and that #edit-medicine-decoy-button (a
    real button sharing the exact same title, deliberately placed
    OUTSIDE the real line-items table) was never reached.
    """

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        # See TestTwoPhaseFillAndSaveInvoice's identical helper.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    @staticmethod
    def _make_item(medicine_name: str, unit_price: str):
        import uuid
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        return PurchaseItem(
            id=str(uuid.uuid4()),
            medicine_name=medicine_name,
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal(unit_price)),
            retail_units_per_purchase_unit=1,
        )

    def test_each_row_gets_its_own_medicines_dialog_never_a_decoy_or_a_different_row(
        self, page: Page
    ) -> None:
        from datetime import date

        from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice

        real_registry = _registry_with_confirmed_vien_label()
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        invoice.add_item(self._make_item("Paracetamol 500mg", "10000"))
        invoice.add_item(self._make_item("Amoxicillin 500mg", "20000"))
        invoice.add_item(self._make_item("Vitamin C 500mg", "30000"))

        outcome = real_provider.fill_and_save_invoice(invoice)

        assert outcome == AutomationOutcome(success=True)
        log_items = page.locator("#retail-price-log li").all()
        assert [entry.get_attribute("data-row") for entry in log_items] == ["1", "2", "3"]
        assert [entry.get_attribute("data-medicine-name") for entry in log_items] == [
            "TH1 - Paracetamol 500mg",
            "TH2 - Amoxicillin 500mg",
            "TH3 - Vitamin C 500mg",
        ]
        # The decoy (same title, OUTSIDE #real-line-items-table) must
        # never be reached by a correctly row-scoped lookup.
        assert page.locator("#edit-medicine-decoy-button").get_attribute("data-medicine-name") == (
            "DECOY-WRONG-ROW"
        )
        medicine_names = [entry.get_attribute("data-medicine-name") for entry in log_items]
        assert "DECOY-WRONG-ROW" not in medicine_names

    def test_unknown_row_position_times_out_not_a_silent_wrong_click(
        self, registry: SelectorRegistry, page: Page
    ) -> None:
        # Mirrors TestBatchEditButtonRowScoping's identical test for
        # invoice_line.select_row_for_batch_button: an out-of-range
        # position must fail to find a matching row, never silently
        # resolve to some other element (e.g. the decoy, or Playwright's
        # .nth() clamping/wrapping).
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        config = PlaywrightAutomationConfig(username="u", password="p", default_timeout_ms=500)
        short_timeout_provider = PlaywrightBrowserAutomationProvider(
            page, registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)

        with pytest.raises(TransientInfrastructureError):
            short_timeout_provider._click_edit_medicine_button_for_row(5)  # noqa: SLF001


class TestRowIdSuffixFormula:
    """
    table_structure.html (PO-confirmed 2026-08, real DOM snapshot of 5
    stable rows) -- REPLACES the abandoned tbody:nth-child(N)
    investigation entirely. Row 1 has no id suffix at all; row N
    (N >= 2) has suffix str(N - 1). Confirmed for positions 1-5,
    matching the snapshot exactly.
    """

    @pytest.mark.parametrize(
        ("position", "expected_suffix"),
        [(1, ""), (2, "1"), (3, "2"), (4, "3"), (5, "4")],
    )
    def test_row_id_suffix_matches_the_real_dom_snapshot(
        self,
        provider: PlaywrightBrowserAutomationProvider,
        position: int,
        expected_suffix: str,
    ) -> None:
        assert provider._row_id_suffix(position) == expected_suffix  # noqa: SLF001

    def test_position_below_1_raises_automation_error(
        self, provider: PlaywrightBrowserAutomationProvider
    ) -> None:
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            AutomationError,
        )

        with pytest.raises(AutomationError):
            provider._row_id_suffix(0)  # noqa: SLF001

    def test_fills_the_correct_distinct_element_for_each_of_5_real_rows(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # Real Playwright, real DOM: #tbxQuantityId (row 1, shared with
        # Phase 1's active field) plus #tbxQuantityId1..4 (rows 2-5) --
        # proves the formula against actual element resolution, not
        # just string arithmetic.
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        for position in range(1, 6):
            provider._fill_row_specific_field(  # noqa: SLF001
                "invoice_line.quantity_field", position, f"qty-for-row-{position}"
            )

        suffix_by_position = {1: "", 2: "1", 3: "2", 4: "3", 5: "4"}
        for position, suffix in suffix_by_position.items():
            assert (
                page.locator(f"#tbxQuantityId{suffix}").input_value()
                == f"qty-for-row-{position}"
            )

    def test_non_css_strategy_entry_is_rejected_not_silently_wrong(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        # invoice_line.vat_field is a plain css id (works); confirm a
        # non-css-strategy entry (e.g. medicine.search_input, role-
        # based) is refused rather than producing a nonsensical
        # computed selector.
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            SelectorNotUsableError,
        )

        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        with pytest.raises(SelectorNotUsableError):
            provider._fill_row_specific_field(  # noqa: SLF001
                "medicine.search_input", 2, "irrelevant"
            )


class TestBatchEditButtonRowScoping:
    """
    table_structure.html (PO-confirmed 2026-08, real DOM snapshot):
    invoice_line.select_row_for_batch_button's row is now resolved via
    page.locator("tbody").nth(position - 1) -- REPLACES the abandoned
    CSS ':nth-child(N)' approach entirely (:nth-child(N) counts ALL
    sibling elements regardless of tag, e.g. a <thead>, which was the
    confirmed root cause of that approach's failure; Playwright's
    Locator.nth() counts only within the already-'tbody'-filtered set).
    Exercises the real per-row calendar-icon trigger against 5 real
    rows, generated via #add-row-button's own click handler (the same
    mechanism Phase 1 uses in production), proving no bleed between
    rows even though the batch/expiry fields themselves are a shared,
    reused overlay.
    """

    @staticmethod
    def _remove_supplier_dialog_tbody(page: Page) -> None:
        # See TestRowSettleVerification's identical helper: the supplier
        # dialog's field table is a real <tbody> outside
        # #real-line-items-table, which would otherwise shift a
        # page-wide page.locator("tbody") count.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_attaches_batch_and_expiry_to_the_correct_row_for_all_5_rows(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)
        for _ in range(5):
            page.click("#add-row-button")
        # 6, not 5 -- one real <tbody> already exists before any click
        # (see #real-line-items-table's own "+1 trailing empty row"
        # comment); positions 1-5 (checked below) are still the first 5
        # of these 6, in order -- the 6th is the extra trailing row this
        # test's own loop never touches.
        assert page.locator("#real-line-items-table tbody").count() == 6

        for position in range(1, 6):
            provider._click_batch_edit_button_for_row(position)  # noqa: SLF001
            provider._fill("invoice_line.batch_number_field", f"BATCH-{position}")  # noqa: SLF001
            provider._fill(  # noqa: SLF001
                "invoice_line.expiry_date_field", f"2027-0{position}-01"
            )
            provider._click("invoice_line.confirm_row_button")  # noqa: SLF001

        log_entries = page.locator("#batch-fill-log li").all_text_contents()
        assert log_entries == [
            "1|BATCH-1|2027-01-01",
            "2|BATCH-2|2027-02-01",
            "3|BATCH-3|2027-03-01",
            "4|BATCH-4|2027-04-01",
            "5|BATCH-5|2027-05-01",
        ]

    def test_unknown_row_position_times_out_not_a_silent_wrong_click(
        self, registry: SelectorRegistry, page: Page
    ) -> None:
        # Only 3 rows exist (1 pre-seeded + 2 clicks -- see
        # #real-line-items-table's own "+1 trailing empty row" comment)
        # -- position 5 must not silently resolve to some other element
        # (e.g. Playwright's .nth() clamping or wrapping); it should
        # fail to find a matching row at all. A short custom timeout
        # keeps this test fast rather than waiting out the provider
        # fixture's real 15s default.
        from pharmacy_invoice_automation.application.exceptions import (
            TransientInfrastructureError,
        )

        config = PlaywrightAutomationConfig(username="u", password="p", default_timeout_ms=500)
        short_timeout_provider = PlaywrightBrowserAutomationProvider(
            page, registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)
        for _ in range(2):
            page.click("#add-row-button")

        with pytest.raises(TransientInfrastructureError):
            short_timeout_provider._click_batch_edit_button_for_row(5)  # noqa: SLF001
