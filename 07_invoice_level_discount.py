import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://webnhathuoc.com/home/")
    page.get_by_role("button", name="Đăng nhập").nth(1).click()
    page.get_by_role("textbox", name="Nhập tài khoản đăng nhập của").click()
    page.get_by_role("textbox", name="Nhập tài khoản đăng nhập của").fill("0988979958f")
    page.get_by_role("textbox", name="Nhập mật khẩu đăng nhập của b").click()
    page.get_by_role("textbox", name="Nhập mật khẩu đăng nhập của b").fill("Nhathuoc@0123")
    page.get_by_role("button", name="Đăng Nhập").click()
    page.locator("a").filter(has_text="Đóng").click()
    page.get_by_role("link", name="Nhập hàng").click()
    page.locator(".close.ui-select-match-close").click()
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").click()
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").press("CapsLock")
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").fill("TRAPHACO")
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").press("CapsLock")
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").fill("TRAPHACO ")
    page.get_by_role("row", name="Nhà cung cấp:  LS Tổng nợ: S").get_by_role("combobox").click()
    page.locator("#tbxVATId").press("ArrowRight")
    page.locator("#tbxVATId").fill("5")
    page.locator("div:nth-child(4) > .input-group > .form-control").fill("5")

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
