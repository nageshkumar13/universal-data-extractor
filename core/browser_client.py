import logging

from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)


class BrowserClient:
    """Fetch JavaScript-rendered HTML with a headless Chromium browser."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout_ms = timeout * 1000
        self.last_status_code: int | None = None

    def fetch(self, url: str, wait_for: str | None = None) -> str:
        logger.info("Fetching URL with browser: %s", url)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                self.last_status_code = response.status if response else None

                if wait_for:
                    page.wait_for_selector(wait_for, timeout=self.timeout_ms)

                html = page.content()
            finally:
                browser.close()

        logger.info("Fetched browser-rendered URL successfully: %s", url)
        return html
