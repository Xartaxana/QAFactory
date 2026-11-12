"""A canned Playwright-for-Python sample (t-2045 N2b): the chain form of `assertion_probes_ast.python.forms` row PY-pw-expect.
Not collected as a test file (the name has no `test_` prefix); the tests read it as bytes and plan mutations of it."""
from playwright.sync_api import Page, expect


def test_visible(page: Page):
    expect(page.locator("#x")).to_be_visible()


def test_not_restored(page: Page):
    expect(page.locator("#x"), message="author words").not_to_be_visible()


async def test_await_kept(page: Page):
    await expect(page.locator("#x"), "second positional").to_have_text("hi")


def test_chain_multiline(page: Page):
    expect(
        page.locator("#x")
    ).to_have_text(
        "hi"
    )
