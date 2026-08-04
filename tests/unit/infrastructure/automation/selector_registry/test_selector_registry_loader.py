"""
Unit tests for infrastructure.automation.selector_registry.selector_registry_loader.

No Playwright, no live site -- pure JSON/dataclass validation. The real
config/selector_registry.webnhathuoc.json is loaded from disk (not mocked)
so these tests fail the moment that file drifts out of structural shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharmacy_invoice_automation.infrastructure.automation.selector_registry import (
    SelectorEntry,
    SelectorRegistryError,
    ValueMappingEntry,
    load_selector_registry,
)

pytestmark = pytest.mark.unit


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


WEBNHATHUOC_REGISTRY_PATH = _repo_root() / "config" / "selector_registry.webnhathuoc.json"

# Logical keys the future PlaywrightBrowserAutomationProvider needs for the
# workflows this task covers (đăng nhập, mở phiếu nhập, tạo/chọn nhà cung
# cấp, tạo/chọn thuốc, điền dòng hàng, lưu phiếu). Confirmed vs.
# needs_verification status is asserted separately below.
REQUIRED_LOGICAL_KEYS = {
    "login.navigate",
    "login.open_login_dialog_button",
    "login.username_field",
    "login.password_field",
    "login.submit_button",
    "login.close_notification_popup",
    "login.session_indicator",
    "open_import_invoice.menu_button",
    "open_import_invoice.submenu_link",
    "supplier.add_new_trigger",
    "supplier.default_tag_remove_button",
    "supplier.dialog_root",
    "supplier.name_field",
    "supplier.phone_field",
    "supplier.address_field",
    "supplier.tax_code_field",
    "supplier.barcode_field",
    "supplier.note_field",
    "supplier.submit_button",
    "supplier.creation_confirmation_close_button",
    "supplier.search_input",
    "supplier.search_result_option",
    "medicine.add_new_trigger",
    "medicine.group_dialog_root",
    "medicine.group_name_field",
    "medicine.group_code_field",
    "medicine.group_submit_button",
    "medicine.group_select_existing",
    "medicine.category_dropdown",
    "medicine.code_field",
    "medicine.create_dialog_close_button",
    "medicine.unit_dropdown",
    "medicine.name_field",
    "medicine.submit_button",
    "medicine.autocomplete_suggestion_unconfirmed",
    "medicine.search_input",
    "medicine.search_result_option",
    "medicine.search_result_option_by_code",
    "medicine.purchase_price_field",
    "medicine.retail_price_field",
    "medicine.conversion_factor_field",
    "invoice.number_field",
    "invoice.date_field",
    "invoice_line.add_row_button",
    "invoice_line.quantity_field",
    "invoice_line.unit_price_field",
    "invoice_line.vat_field",
    "invoice_line.discount_field",
    "invoice_line.subsequent_row_medicine_search_input",
    "invoice_line.select_row_for_batch_button",
    "invoice_line.batch_number_field",
    "invoice_line.expiry_date_field",
    "invoice_line.confirm_row_button",
    "invoice.save_button",
    "invoice.save_success_indicator",
    "invoice.edit_link",
    "invoice_line.edit_medicine_button",
    "invoice_line.edit_dialog_close_button",
}

CONFIRMED_FROM_RECORDINGS = {
    "login.navigate",
    "login.open_login_dialog_button",
    "login.username_field",
    "login.password_field",
    "login.submit_button",
    "login.close_notification_popup",
    "open_import_invoice.menu_button",
    "open_import_invoice.submenu_link",
    "supplier.add_new_trigger",
    "supplier.default_tag_remove_button",
    "supplier.dialog_root",
    "supplier.name_field",
    "supplier.phone_field",
    "supplier.address_field",
    "supplier.tax_code_field",
    "supplier.submit_button",
    "supplier.search_input",
    "supplier.search_result_option",
    "medicine.add_new_trigger",
    "medicine.group_dialog_root",
    "medicine.group_name_field",
    "medicine.group_code_field",
    "medicine.group_submit_button",
    "medicine.group_select_existing",
    "medicine.category_dropdown",
    "medicine.code_field",
    "medicine.create_dialog_close_button",
    "medicine.unit_dropdown",
    "medicine.name_field",
    "medicine.submit_button",
    "medicine.search_input",
    "medicine.search_result_option",
    "medicine.purchase_price_field",
    "medicine.retail_price_field",
    "medicine.conversion_factor_field",
    "invoice.number_field",
    "invoice.date_field",
    "invoice_line.add_row_button",
    "invoice_line.quantity_field",
    "invoice_line.unit_price_field",
    "invoice_line.vat_field",
    "invoice_line.discount_field",
    "invoice_line.subsequent_row_medicine_search_input",
    "invoice_line.select_row_for_batch_button",
    "invoice_line.batch_number_field",
    "invoice_line.expiry_date_field",
    "invoice_line.confirm_row_button",
    "invoice.save_button",
    "invoice.edit_link",
    "invoice_line.edit_dialog_close_button",
}

# 'derived' (not 'confirmed') on purpose -- inferred from a confirmed
# pattern or partial/indirect evidence, not a direct recorded action.
DERIVED_FROM_INFERENCE = {
    "supplier.barcode_field",
    "supplier.note_field",
    "supplier.creation_confirmation_close_button",
    "invoice.save_success_indicator",
    "invoice_line.edit_medicine_button",
    "medicine.search_result_option_by_code",
}

# Genuinely unresolved -- flagged for the PO, not guessed.
STILL_NEEDS_VERIFICATION = {
    "login.session_indicator",
    "medicine.autocomplete_suggestion_unconfirmed",
}


@pytest.fixture(scope="module")
def registry():
    return load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)


class TestLoadRealWebnhathuocRegistry:
    def test_loads_without_error(self, registry) -> None:
        assert registry.site == "webnhathuoc.com"
        assert registry.version >= 1
        assert registry.base_url == "https://webnhathuoc.com/home/"

    def test_every_required_logical_key_is_registered(self, registry) -> None:
        missing = REQUIRED_LOGICAL_KEYS - registry.selectors.keys()
        assert not missing, f"Selector Registry is missing required keys: {sorted(missing)}"

    def test_every_recording_confirmed_key_has_confirmed_status(self, registry) -> None:
        for key in CONFIRMED_FROM_RECORDINGS:
            entry = registry.get(key)
            assert entry.status == "confirmed", (
                f"'{key}' was evidenced directly by a reference recording and should be "
                f"status='confirmed', found '{entry.status}'."
            )

    def test_every_usable_entry_has_a_strategy_and_sufficient_params(self, registry) -> None:
        for key, entry in registry.selectors.items():
            if not entry.is_usable:
                continue
            assert entry.strategy is not None, key
            if entry.strategy == "role":
                assert entry.role, f"{key}: role strategy needs a non-empty 'role'."
                # Disambiguation can come from the element's own name/description,
                # OR from how its scope is built (role-scoped parent, or a
                # filter_has_text refinement on the base locator).
                has_disambiguation = (
                    entry.name or entry.description or entry.scope_role or entry.filter_has_text
                )
                assert has_disambiguation, (
                    f"{key}: role strategy needs a 'name'/'description', or a scoping "
                    "mechanism, to disambiguate."
                )
            elif entry.strategy in (
                "css",
                "title",
                "label",
                "goto",
                "text",
                "placeholder",
                "text_ends_with",
                "text_exact",
                "text_starts_with",
            ):
                assert entry.value, f"{key}: '{entry.strategy}' strategy needs a non-empty 'value'."

    def test_derived_entries_have_derived_status(self, registry) -> None:
        for key in DERIVED_FROM_INFERENCE:
            entry = registry.get(key)
            assert entry.status == "derived", (
                f"'{key}' is inferred rather than directly recorded and should be "
                f"status='derived', found '{entry.status}'."
            )

    def test_flagged_ambiguous_entries_remain_needs_verification(self, registry) -> None:
        for key in STILL_NEEDS_VERIFICATION:
            entry = registry.get(key)
            assert entry.status == "needs_verification", (
                f"'{key}' is a known-ambiguous point that should not be silently "
                f"resolved -- expected status='needs_verification', found '{entry.status}'."
            )

    def test_needs_verification_entries_are_rejected_by_require_usable(self, registry) -> None:
        entry = registry.get("login.session_indicator")
        assert entry.status == "needs_verification"
        assert entry.is_usable is False
        with pytest.raises(SelectorRegistryError, match="not yet usable"):
            registry.require_usable("login.session_indicator")

    def test_require_usable_returns_confirmed_entry(self, registry) -> None:
        entry = registry.require_usable("login.submit_button")
        assert entry.role == "button"
        assert entry.name == "Đăng Nhập"

    def test_get_raises_for_unknown_key(self, registry) -> None:
        with pytest.raises(SelectorRegistryError, match="No selector registered"):
            registry.get("does.not.exist")

    def test_supplier_field_order_matches_po_confirmed_order(self, registry) -> None:
        # Tên nhà cung cấp -> Số điện thoại -> Địa chỉ -> Mã số thuế -> Mã vạch -> Ghi chú
        ordered_keys = [
            "supplier.name_field",
            "supplier.phone_field",
            "supplier.address_field",
            "supplier.tax_code_field",
            "supplier.barcode_field",
            "supplier.note_field",
        ]
        for row_index, key in enumerate(ordered_keys, start=1):
            entry = registry.get(key)
            assert f"tr:nth-child({row_index})" in (entry.value or ""), (
                f"{key} should target dialog row {row_index}, got: {entry.value!r}"
            )

    def test_barcode_field_is_flagged_never_filled(self, registry) -> None:
        entry = registry.get("supplier.barcode_field")
        assert "never" in (entry.notes or "").lower()

    def test_medicine_group_display_labels_match_medicine_type_business_rule(
        self, registry
    ) -> None:
        prescription = registry.get_value_mapping("medicine_group_display_label", "prescription")
        otc = registry.get_value_mapping("medicine_group_display_label", "over_the_counter")
        assert prescription.is_confirmed
        assert prescription.label == "Thuốc kê đơn"
        assert otc.is_confirmed
        assert otc.label == "Thuốc không kê đơn"

    def test_unit_display_label_mapping_covers_every_currently_valid_domain_unit_code(
        self, registry
    ) -> None:
        # Domain.Unit (domain/value_objects/unit.py _KNOWN_CODES) currently
        # accepts exactly these 7 codes -- not the 39 codes mentioned in the
        # task brief (see the accompanying report). Read as a literal here,
        # not imported from Domain: as of this writing,
        # domain.exceptions.domain_error itself fails to import (a
        # separate, pre-existing scaffold gap -- see report), which would
        # make importing Unit fail for reasons unrelated to this package.
        known_unit_codes = {"vien", "tuyp", "hop", "chai", "goi", "ong", "other"}

        mapped_codes = registry.value_mappings["unit_display_label"].keys()
        assert known_unit_codes <= mapped_codes, (
            "Every Unit code Domain currently accepts must have a mapping entry "
            f"(even if unverified): missing {known_unit_codes - mapped_codes}"
        )

    def test_no_unit_display_label_is_falsely_marked_confirmed(self, registry) -> None:
        # The reference recording selected the unit dropdown by raw option
        # value, never by visible label text -- so no label is actually
        # confirmed yet. This test fails loudly if someone marks one
        # 'confirmed' without real evidence.
        for code, mapping_entry in registry.value_mappings["unit_display_label"].items():
            assert not mapping_entry.is_confirmed, (
                f"unit_display_label.{code} is marked confirmed but no recording ever "
                "captured a real display label -- verify against the live site first."
            )

    def test_get_value_mapping_raises_for_unknown_group(self, registry) -> None:
        with pytest.raises(SelectorRegistryError, match="No value mapping group"):
            registry.get_value_mapping("does_not_exist", "vien")

    def test_get_value_mapping_raises_for_unknown_value(self, registry) -> None:
        with pytest.raises(SelectorRegistryError, match="No value mapping"):
            registry.get_value_mapping("unit_display_label", "not_a_real_code")

    def test_medicine_group_select_option_value_is_not_falsely_confirmed(self, registry) -> None:
        # medicine.group_select_existing's only recorded value ('number:396866')
        # was never matched against the dropdown's visible option text, so
        # neither MedicineType may be marked confirmed yet.
        prescription = registry.get_value_mapping(
            "medicine_group_select_option_value", "prescription"
        )
        otc = registry.get_value_mapping("medicine_group_select_option_value", "over_the_counter")
        assert prescription.is_confirmed is False
        assert otc.is_confirmed is False

    def test_batch_number_field_is_shared_across_every_row(self, registry) -> None:
        # PO's point 3 hypothesis, confirmed exactly: unlike Price/VAT/Quantity,
        # this id never takes a row-number suffix in any of the 3 observed rows.
        entry = registry.get("invoice_line.batch_number_field")
        assert entry.status == "confirmed"
        assert entry.value == "#txtBatchNumber"

    def test_vat_field_is_a_plain_textbox_not_a_dropdown(self, registry) -> None:
        entry = registry.get("invoice_line.vat_field")
        assert entry.strategy == "css"
        assert entry.value == "#tbxVATId"

    def test_confirm_row_button_uses_the_recorded_label_not_the_old_placeholder_guess(
        self, registry
    ) -> None:
        entry = registry.get("invoice_line.confirm_row_button")
        assert entry.status == "confirmed"
        assert entry.name == "Cập nhật"

    def test_supplier_search_result_option_uses_substring_matching_not_exact(
        self, registry
    ) -> None:
        # Confirmed via one recorded example string, but must not require
        # an exact match against runtime-supplied names.
        supplier_entry = registry.get("supplier.search_result_option")
        assert supplier_entry.exact is False

    def test_medicine_search_result_option_uses_end_anchored_matching(self, registry) -> None:
        # Bug fix (PO-confirmed 2026-08, via a real DOM snapshot --
        # CRITICAL, substring-collision selection bug): plain substring
        # matching (the old mechanism, mirroring
        # supplier.search_result_option's own) matched "Coldi-B DNH"
        # when searching "Coldi" -- neither substring nor full-exact
        # matching works here (a real, unpredictable numeric code
        # prefix precedes the medicine name), so this entry now uses a
        # dedicated 'text_ends_with' strategy instead, scoped to the
        # real, confirmed <b> tag the medicine name actually lives in.
        medicine_entry = registry.get("medicine.search_result_option")
        assert medicine_entry.strategy == "text_ends_with"
        assert medicine_entry.value == "b"

    def test_role_scoped_entries_use_the_new_scope_role_mechanism(self, registry) -> None:
        for key in ("invoice_line.expiry_date_field",):
            entry = registry.get(key)
            assert entry.scope_role is not None, f"{key} should use scope_role."
            assert entry.scope_name is not None, f"{key} should use scope_name."

    def test_supplier_search_input_uses_a_stable_css_id_not_a_dynamic_accessible_name(
        self, registry
    ) -> None:
        # Bug fix (PO-confirmed 2026-08, final -- root-caused the real
        # --dry-run timeout): REPLACES the prior scope_role="row"/
        # scope_name="Nha cung cap:  LS Tong no: S" approach entirely --
        # that scope_name embedded the supplier's own outstanding debt
        # figure, a value that differs per supplier/session, so it only
        # ever matched by coincidence. #supplierSearchBoxId is
        # PO-verified unique (Console querySelectorAll count===1) and
        # has no dependency on any dynamic text at all.
        entry = registry.get("supplier.search_input")
        assert entry.strategy == "css"
        assert entry.value == "#supplierSearchBoxId input[type=search]"
        assert entry.scope_role is None
        assert entry.scope_name is None

    def test_supplier_add_new_trigger_is_scoped_to_the_receipt_note_view(self, registry) -> None:
        # Bug fix (PO-confirmed 2026-08, final): scoping history --
        # unscoped/page-wide (fragile DOM-sequencing luck) -> briefly
        # "#supplierSearchBoxId" (wrong, excluded the real sibling
        # element, caught by a live --dry-run timeout) -> now
        # "#receiptNoteViewId", per a REAL Playwright strict-mode-
        # violation error from a live --dry-run run, which enumerated
        # its own two disambiguating candidates directly (not a
        # DOM-snapshot guess).
        entry = registry.get("supplier.add_new_trigger")
        assert entry.scope == "#receiptNoteViewId"

    def test_login_popup_close_uses_filter_has_text(self, registry) -> None:
        entry = registry.get("login.close_notification_popup")
        assert entry.strategy == "css"
        assert entry.value == "a"
        assert entry.filter_has_text == "Đóng"


class TestSelectorEntryUsability:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("confirmed", True),
            ("derived", True),
            ("needs_verification", False),
            ("not_applicable", False),
        ],
    )
    def test_is_usable(self, status: str, expected: bool) -> None:
        entry = SelectorEntry(key="k", status=status, strategy="css", value="#x")
        assert entry.is_usable is expected


class TestValueMappingEntry:
    def test_is_confirmed_true_only_for_confirmed_status(self) -> None:
        assert ValueMappingEntry(status="confirmed", label="Viên").is_confirmed is True
        assert ValueMappingEntry(status="needs_verification").is_confirmed is False


class TestLoaderValidation:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SelectorRegistryError, match="not found"):
            load_selector_registry(tmp_path / "does_not_exist.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(SelectorRegistryError, match="not valid JSON"):
            load_selector_registry(bad_file)

    def test_non_object_top_level_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(SelectorRegistryError, match="JSON object at the top level"):
            load_selector_registry(bad_file)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"site": "x"}), encoding="utf-8")
        with pytest.raises(SelectorRegistryError, match="missing required field"):
            load_selector_registry(bad_file)

    def test_unknown_status_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {"foo": {"status": "totally_made_up"}},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SelectorRegistryError, match="expected one of"):
            load_selector_registry(bad_file)

    def test_usable_entry_without_strategy_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {"foo": {"status": "confirmed"}},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SelectorRegistryError, match="no strategy"):
            load_selector_registry(bad_file)

    def test_needs_verification_entry_without_strategy_is_allowed(self, tmp_path: Path) -> None:
        good_file = tmp_path / "good.json"
        good_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {"foo": {"status": "needs_verification"}},
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(good_file)
        assert loaded.get("foo").is_usable is False

    def test_unknown_strategy_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {
                        "foo": {"status": "confirmed", "strategy": "xpath", "value": "//div"}
                    },
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SelectorRegistryError, match="expected one of"):
            load_selector_registry(bad_file)

    def test_value_mappings_defaults_to_empty_when_absent(self, tmp_path: Path) -> None:
        minimal_file = tmp_path / "minimal.json"
        minimal_file.write_text(
            json.dumps({"site": "x", "version": 1, "selectors": {}}), encoding="utf-8"
        )
        loaded = load_selector_registry(minimal_file)
        assert loaded.value_mappings == {}

    def test_value_mapping_description_key_is_not_treated_as_a_value_entry(
        self, tmp_path: Path
    ) -> None:
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {},
                    "value_mappings": {
                        "some_group": {
                            "description": "just a human-readable note, not a value entry",
                            "real_value": {"status": "confirmed", "label": "Hello"},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(registry_file)
        assert "description" not in loaded.value_mappings["some_group"]
        assert loaded.value_mappings["some_group"]["real_value"].label == "Hello"


class TestSchemaExtensionForNewStrategies:
    """
    Covers the strategy/field additions made to support real evidence from
    05_full_flow_existing_supplier_medicine.py: "text" (get_by_text),
    "placeholder" (get_by_placeholder), and role-based/filtered scoping
    (scope_role/scope_name, filter_has_text) alongside the existing plain
    CSS 'scope'.
    """

    def test_text_strategy_is_accepted(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {
                        "foo": {"status": "confirmed", "strategy": "text", "value": "Hello"}
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(registry_file)
        entry = loaded.get("foo")
        assert entry.is_usable is True
        assert entry.strategy == "text"
        assert entry.value == "Hello"

    def test_placeholder_strategy_is_accepted(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {
                        "foo": {
                            "status": "confirmed",
                            "strategy": "placeholder",
                            "value": "dd/mm/yyyy",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(registry_file)
        assert loaded.get("foo").is_usable is True

    def test_scope_role_and_scope_name_round_trip(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {
                        "foo": {
                            "status": "confirmed",
                            "strategy": "role",
                            "role": "combobox",
                            "scope_role": "row",
                            "scope_name": "Some Row",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(registry_file)
        entry = loaded.get("foo")
        assert entry.scope_role == "row"
        assert entry.scope_name == "Some Row"

    def test_filter_has_text_round_trips(self, tmp_path: Path) -> None:
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(
            json.dumps(
                {
                    "site": "x",
                    "version": 1,
                    "selectors": {
                        "foo": {
                            "status": "confirmed",
                            "strategy": "css",
                            "value": "a",
                            "filter_has_text": "Đóng",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = load_selector_registry(registry_file)
        assert loaded.get("foo").filter_has_text == "Đóng"

    def test_scope_role_scope_name_and_filter_has_text_default_to_none(self) -> None:
        entry = SelectorEntry(key="k", status="confirmed", strategy="css", value="#x")
        assert entry.scope_role is None
        assert entry.scope_name is None
        assert entry.filter_has_text is None
