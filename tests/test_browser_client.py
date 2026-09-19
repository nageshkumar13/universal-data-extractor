from core import browser_client as browser_client_module
from core.browser_client import BrowserClient


class FakeResponse:
    status = 200


class FakePage:
    def __init__(self) -> None:
        self.goto_call: tuple[str, str, float] | None = None
        self.wait_call: tuple[str, float] | None = None

    def goto(self, url: str, wait_until: str, timeout: float) -> FakeResponse:
        self.goto_call = (url, wait_until, timeout)
        return FakeResponse()

    def wait_for_selector(self, selector: str, timeout: float) -> None:
        self.wait_call = (selector, timeout)

    def content(self) -> str:
        return "<html><article>Rendered</article></html>"


class FakeBrowser:
    def __init__(self) -> None:
        self.page = FakePage()
        self.closed = False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.headless: bool | None = None

    def launch(self, headless: bool) -> FakeBrowser:
        self.headless = headless
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium


class FakePlaywrightContext:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    def __enter__(self) -> FakePlaywright:
        return self.playwright

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def test_browser_client_waits_for_selector_and_returns_rendered_html(
    monkeypatch,
) -> None:
    browser = FakeBrowser()
    chromium = FakeChromium(browser)
    context = FakePlaywrightContext(FakePlaywright(chromium))
    monkeypatch.setattr(browser_client_module, "sync_playwright", lambda: context)

    client = BrowserClient(timeout=12.0)
    html = client.fetch("https://example.com/app", wait_for="article.result")

    assert html == "<html><article>Rendered</article></html>"
    assert client.last_status_code == 200
    assert chromium.headless is True
    assert browser.page.goto_call == (
        "https://example.com/app",
        "domcontentloaded",
        12000.0,
    )
    assert browser.page.wait_call == ("article.result", 12000.0)
    assert browser.closed is True
