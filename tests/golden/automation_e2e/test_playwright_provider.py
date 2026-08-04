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
    unit_display_label entry (config/selector_registry.webnhathuoc.json)
    is genuinely 'needs_verification' (see
    TestUnverifiedFlowsFailCleanlyInsteadOfGuessing, which proves
    create_medicine() correctly stops there against the real registry) --
    this override exists purely so
    TestMedicineResolutionMergedIntoPerLineLoop can exercise the
    create-then-reselect handoff itself, same spirit as _local_registry's
    own test-only login.navigate/login.session_indicator overrides above.
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
        # The supplier-creation dialog's field table is the fixture's
        # one remaining real <tbody> outside of #invoice-rows-container
        # (needed elsewhere for supplier.name_field's exact CSS nth-
        # child path -- cannot be restructured away like the medicine-
        # search sections were). invoice_line.select_row_for_batch_button
        # scopes via a PAGE-WIDE page.locator("tbody"), so this stray
        # tbody would shift the count by 1; fill_and_save_invoice never
        # touches the supplier dialog, so removing it here is safe and
        # scoped to this test's own isolated Page instance only.
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

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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
    below proves the #tblMain-scoped fix.
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
        # The supplier-creation dialog's field table is the fixture's
        # one remaining real <tbody> outside of #invoice-rows-container.
        # _wait_for_row_settled scopes via a PAGE-WIDE
        # page.locator("tbody"), so this stray tbody would shift the
        # count by 1; fill_and_save_invoice never touches the supplier
        # dialog, so removing it here is safe and scoped to this test's
        # own isolated Page instance only.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_waits_for_a_delayed_row_to_settle_before_continuing(self, page: Page) -> None:
        # A 1-second real, configurable delay before the fixture appends
        # the settled <tbody> -- well under _wait_for_row_settled's own
        # 5-second timeout, but long enough that a naive "check .count()
        # once, immediately" implementation would have already failed.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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
        # Scoped to #tblMain (not a bare page-wide "tbody") -- the
        # invoice.date_field calendar widget's own real <table><tbody>
        # (day grid) is a second, unrelated, ALWAYS-present stray tbody
        # elsewhere on the page now (see _line_item_rows's own
        # #tblMain-scoping fix and its "why" for this exact class of
        # page-wide-count pitfall).
        assert page.locator("#tblMain tbody").count() == 1

    def test_fails_cleanly_when_a_row_never_settles(self, page: Page) -> None:
        # Simulates the real site rejecting the row outright (PO's real
        # "chưa nhập thông tin thuốc" error) -- no <tbody> is ever
        # appended. Must fail with a clear, actionable diagnostic, never
        # silently continue to the next line.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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
        assert "did not settle" in (outcome.failure_reason or "")
        assert "expected 1" in (outcome.failure_reason or "")
        # The second line's fields must never have been touched --
        # proof this stopped immediately rather than plowing ahead and
        # overwriting anything.
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|10000|"]

    def test_real_row_count_matches_after_filling_three_lines(self, page: Page) -> None:
        # The user's own explicit ask: don't just trust "no exception"
        # -- confirm the actual number of real rows on the page matches
        # how many lines were filled, for an invoice with >= 3 items.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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
        # Scoped to #tblMain -- see test_waits_for_a_delayed_row_to_settle_before_continuing's
        # own comment for why a bare page-wide "tbody" count is no
        # longer safe (the calendar widget's own real day-grid <tbody>
        # is a second, unrelated stray one now).
        assert page.locator("#tblMain tbody").count() == 3
        log_entries = page.locator("#line-fill-log li").all_text_contents()
        assert log_entries == ["5|10000|", "5|20000|", "5|5000|"]

    def test_ignores_stray_tbody_elements_outside_the_line_items_table(
        self, page: Page
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, via a real --dry-run run): a
        # real 3-item invoice found page.locator("tbody") returning 24
        # matches PAGE-WIDE (other real tables elsewhere on the live
        # page, never modeled by this local fixture). Injects a pile of
        # stray <tbody> elements OUTSIDE #tblMain here to prove
        # _wait_for_row_settled/_click_batch_edit_button_for_row (both
        # now scoped via _line_item_rows(), "#tblMain tbody") genuinely
        # ignore them -- not merely passing because the fixture never
        # had any stray tbody of its own.
        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
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
        # Page-wide count is inflated by the 20 stray tbody elements --
        # exactly the real symptom (24 page-wide vs. 3 real rows).
        assert page.locator("tbody").count() >= 21
        assert page.locator("#tblMain tbody").count() == 1


class TestMedicineSelectionSettleWait:
    """
    Bug fix (2026-08, PO-confirmed via the same real --dry-run run that
    surfaced the "#tblMain" scoping bug above -- see
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
        import time

        real_registry = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
        config = PlaywrightAutomationConfig(username="u", password="p")
        real_provider = PlaywrightBrowserAutomationProvider(
            page, real_registry, config, logging.getLogger("test")
        )
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())

        started = time.monotonic()
        found = real_provider.search_medicine("Paracetamol 500mg")
        elapsed = time.monotonic() - started

        assert found is True
        assert elapsed >= 2.4


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
    string with the packaging description _convert_to_retail_units
    elsewhere derives its Vien-conversion factor from -- these tests
    prove PlaywrightBrowserAutomationProvider now strips that trailing
    parenthetical before it ever reaches the page (search_medicine's
    own docstring has the full incident writeup).
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
            "?auto_select_medicine_code=TH6&auto_select_medicine_after_ms=200"
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
        page.click("#save-invoice")  # reveals #edit-invoice-link, as after a real first save

        def _make_item(unit_price: str) -> PurchaseItem:
            # Purchase unit is "hop" (10 Vien/hop), unit_price is the
            # PURCHASE price -- _update_retail_prices_after_save must
            # convert to a per-Vien price (Part 3) before calling
            # PricePolicy, not use unit_price directly.
            return PurchaseItem(
                id=str(uuid.uuid4()),
                medicine_name="Some Medicine",
                unit=Unit(code="hop"),
                quantity=Quantity(Decimal("1")),
                unit_price=Money(Decimal(unit_price)),
                retail_units_per_purchase_unit=10,
            )

        invoice = PurchaseInvoice(
            id="inv-1",
            project_id="proj-1",
            invoice_number="INV-001",
            invoice_date=date.today(),
        )
        # Per-Vien price 10000 -> 12000.0 (exact); 12084 -> 14500.8 ->
        # rounds up to 15000 -- same two boundary cases as
        # tests/unit/domain/services/test_price_policy.py, proving this
        # call path uses the real PricePolicy, not a reimplementation.
        # Purchase-side unit_price is 10x the per-Vien price (10 Vien/hop).
        invoice.add_item(_make_item("100000"))
        invoice.add_item(_make_item("120840"))

        provider._update_retail_prices_after_save(invoice)  # noqa: SLF001

        log_entries = page.locator("#retail-price-log li").all_text_contents()
        assert log_entries == ["0:12000", "1:15000"]

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
        page.click("#save-invoice")
        page.evaluate(
            "document.getElementById('edit-invoice-link')"
            ".addEventListener('click', () => { window.editLinkClicks = "
            "(window.editLinkClicks || 0) + 1; })"
        )

        invoice = PurchaseInvoice(
            id="inv-1", project_id="proj-1", invoice_number="INV-001", invoice_date=date.today()
        )
        for _ in range(2):  # fixture provides exactly 2 "Chỉnh sửa thuốc" buttons
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


class TestConvertToRetailUnits:
    """
    Part 3 (Vien unit conversion, PO-confirmed 2026-08): pure
    quantity/price conversion math, exercised directly (same pattern as
    TestUpdateRetailPricesAfterSave calling a private method) since the
    per-line fill loop's own DOM fields are not yet in the fixture --
    that gap is the still-deferred row-scoping question (Decision 2,
    see invoice_line.unit_price_field's notes), intentionally untouched
    by this Part.
    """

    def test_converts_quantity_and_price_by_the_resolved_factor(
        self, provider: PlaywrightBrowserAutomationProvider
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        item = PurchaseItem(
            id="item-1",
            medicine_name="Some Medicine",
            unit=Unit(code="hop"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("100000")),
            retail_units_per_purchase_unit=10,
        )

        retail_quantity, retail_unit_price = provider._convert_to_retail_units(item)  # noqa: SLF001

        assert retail_quantity == Decimal("50")
        assert retail_unit_price.amount == Decimal("10000")
        assert retail_unit_price.currency == "VND"

    def test_an_already_vien_item_resolved_to_factor_1_is_unchanged(
        self, provider: PlaywrightBrowserAutomationProvider
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit

        item = PurchaseItem(
            id="item-1",
            medicine_name="Some Medicine",
            unit=Unit(code="vien"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("10000")),
            retail_units_per_purchase_unit=1,
        )

        retail_quantity, retail_unit_price = provider._convert_to_retail_units(item)  # noqa: SLF001

        assert retail_quantity == Decimal("5")
        assert retail_unit_price.amount == Decimal("10000")

    def test_missing_resolved_factor_raises_automation_error_not_a_guess(
        self, provider: PlaywrightBrowserAutomationProvider
    ) -> None:
        from decimal import Decimal

        from pharmacy_invoice_automation.domain.entities.purchase_item import PurchaseItem
        from pharmacy_invoice_automation.domain.value_objects.money import Money
        from pharmacy_invoice_automation.domain.value_objects.quantity import Quantity
        from pharmacy_invoice_automation.domain.value_objects.unit import Unit
        from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
            AutomationError,
        )

        item = PurchaseItem(
            id="item-1",
            medicine_name="Some Medicine",
            unit=Unit(code="hop"),
            quantity=Quantity(Decimal("5")),
            unit_price=Money(Decimal("100000")),
        )

        with pytest.raises(AutomationError):
            provider._convert_to_retail_units(item)  # noqa: SLF001


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
        # See TestTwoPhaseFillAndSaveInvoice's identical helper: the
        # supplier dialog's field table is the fixture's one remaining
        # real <tbody> outside of #invoice-rows-container, which would
        # otherwise shift the page-wide page.locator("tbody") count.
        page.evaluate("document.querySelector('#create-supplyer-dialog tbody').remove()")

    def test_attaches_batch_and_expiry_to_the_correct_row_for_all_5_rows(
        self, provider: PlaywrightBrowserAutomationProvider, page: Page
    ) -> None:
        page.goto(FIXTURE_HTML_PATH.resolve().as_uri())
        self._remove_supplier_dialog_tbody(page)
        for _ in range(5):
            page.click("#add-row-button")
        assert page.locator("#invoice-rows-container tbody").count() == 5

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
        # Only 2 rows exist -- position 5 must not silently resolve to
        # some other element (e.g. Playwright's .nth() clamping or
        # wrapping); it should fail to find a matching row at all. A
        # short custom timeout keeps this test fast rather than waiting
        # out the provider fixture's real 15s default.
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
