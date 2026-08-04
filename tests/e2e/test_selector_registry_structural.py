"""
Structural (real Playwright, no live site) tests for the webnhathuoc.com
Selector Registry: every 'confirmed'/'derived' entry must compile into an
actual Playwright Locator against a real, headless Chromium instance.

This proves each entry's strategy/parameters are well-formed Playwright
locators -- a malformed CSS selector or an unsupported role raises here.
It intentionally never touches the live webnhathuoc.com site: no
credentials, no network dependency, and no DOM match is expected (the
fixture page is deliberately blank). See Technical Design Document Sec. 16
for the separate, live "selector smoke test" this does not replace.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, sync_playwright

from pharmacy_invoice_automation.infrastructure.automation.selector_registry import (
    SelectorEntry,
    SelectorRegistry,
    load_selector_registry,
)

pytestmark = pytest.mark.e2e

_BLANK_PAGE_HTML = "<html><body><div id='root'></div></body></html>"


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("Could not locate repository root from test file location.")


WEBNHATHUOC_REGISTRY_PATH = _repo_root() / "config" / "selector_registry.webnhathuoc.json"


def _build_locator(page: Page, entry: SelectorEntry) -> Locator:
    """
    Translate one SelectorEntry into a real Playwright Locator.

    This is a deliberately minimal, test-only translation used to prove
    structural validity. The production translation used by automation
    code belongs to PlaywrightBrowserAutomationProvider, which is a
    separate package not built here.
    """
    if entry.scope_role is not None:
        scope_kwargs: dict[str, Any] = {}
        if entry.scope_name is not None:
            scope_kwargs["name"] = entry.scope_name
        root: Page | Locator = page.get_by_role(entry.scope_role, **scope_kwargs)  # type: ignore[arg-type]
    elif entry.scope is not None:
        root = page.locator(entry.scope)
    else:
        root = page

    locator: Locator
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
        kwargs: dict[str, Any] = {}
        if entry.name is not None:
            kwargs["name"] = entry.name
        if entry.description is not None:
            kwargs["description"] = entry.description
        if entry.exact is not None:
            kwargs["exact"] = entry.exact
        locator = root.get_by_role(entry.role, **kwargs)  # type: ignore[arg-type]
    elif entry.strategy in ("text_ends_with", "text_exact", "text_starts_with"):
        # Like "css": entry.value is the real, confirmed CSS tag/class
        # this strategy scopes to (e.g. "b", "span.year",
        # "td.day:not(.old):not(.new)") -- the actual runtime regex
        # filter (end-anchored or full-match) is built from a per-call
        # parameter PlaywrightBrowserAutomationProvider._locate_parameterized
        # supplies, which this purely-structural, no-runtime-parameter
        # test has no equivalent of; only the base locator's own
        # syntactic validity is checked here.
        assert entry.value is not None
        locator = root.locator(entry.value)
    else:
        raise AssertionError(f"Unhandled strategy in test helper: {entry.strategy!r}")

    if entry.filter_has_text is not None:
        locator = locator.filter(has_text=entry.filter_has_text)
    if entry.nth is not None:
        locator = locator.nth(entry.nth)
    return locator


def _locatable_selector_params() -> list[Any]:
    # Evaluated at collection time so pytest can parametrize per key --
    # this is real file I/O against the actual registry, not a fixture.
    registry_data = load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)
    return [
        pytest.param(key, entry, id=key)
        for key, entry in registry_data.selectors.items()
        if entry.is_usable and entry.strategy != "goto"
    ]


@pytest.fixture(scope="module")
def registry() -> SelectorRegistry:
    return load_selector_registry(WEBNHATHUOC_REGISTRY_PATH)


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        pw_page = browser.new_page()
        pw_page.set_content(_BLANK_PAGE_HTML)
        yield pw_page
        browser.close()


class TestSelectorsCompileToRealPlaywrightLocators:
    @pytest.mark.parametrize(("key", "entry"), _locatable_selector_params())
    def test_locator_is_well_formed(self, page: Page, key: str, entry: SelectorEntry) -> None:
        locator = _build_locator(page, entry)
        # .count() forces Playwright to actually evaluate the locator
        # against the real DOM. A malformed CSS selector or an invalid
        # role raises here; a well-formed-but-non-matching locator
        # legitimately returns 0 against this inert blank page -- that is
        # the expected, correct result for a structural-only test.
        count = locator.count()
        assert count == 0

    def test_at_least_one_selector_was_exercised(self, registry: SelectorRegistry) -> None:
        exercised = [
            key
            for key, entry in registry.selectors.items()
            if entry.is_usable and entry.strategy != "goto"
        ]
        assert len(exercised) >= 20


class TestGotoEntries:
    def test_every_goto_entry_is_an_https_url(self, registry: SelectorRegistry) -> None:
        goto_entries = [entry for entry in registry.selectors.values() if entry.strategy == "goto"]
        assert goto_entries, "Expected at least one 'goto' entry (e.g. login.navigate)."
        for entry in goto_entries:
            assert entry.value is not None
            assert entry.value.startswith("https://")

    def test_page_can_actually_navigate_style_check(self, page: Page) -> None:
        # Not a live navigation (no network access to the real site in
        # this suite) -- confirms the fixture browser/page itself is a
        # real, working Playwright session, so the locator checks above
        # are running against genuine Playwright evaluation, not a stub.
        assert page.url is not None
