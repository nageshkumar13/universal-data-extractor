import logging
from collections.abc import Callable
from time import sleep as sleep_seconds, time as wall_time
from types import TracebackType
from typing import Self

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from core.http_client import HTTPStatusError
from core.retry import MAX_ATTEMPTS, status_retry_delay


logger = logging.getLogger(__name__)


class BrowserClient:
    """Fetch JavaScript-rendered HTML using a browser shared across a run."""

    def __init__(
        self, timeout: float = 30.0, *,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sleep = sleep if sleep is not None else sleep_seconds
        self._clock = clock if clock is not None else wall_time
        self.timeout_ms = timeout * 1000
        self.last_status_code: int | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> Self:
        if self._playwright is not None:
            raise RuntimeError("BrowserClient is already open.")

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._context.set_default_timeout(self.timeout_ms)
            self._context.set_default_navigation_timeout(self.timeout_ms)
        except BaseException:
            try:
                self.close()
            except BaseException:
                logger.exception("Failed to clean up browser resources after startup failure")
            raise

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
        else:
            try:
                self.close()
            except BaseException:
                logger.exception("Failed to clean up browser resources while handling an error")

    def close(self) -> None:
        """Release every resource once, then propagate the first cleanup error."""
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = None
        self._browser = None
        self._playwright = None

        first_error: BaseException | None = None
        for resource, method in (
            (context, "close"),
            (browser, "close"),
            (playwright, "stop"),
        ):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                    else:
                        logger.exception("Additional error during browser cleanup")

        if first_error is not None:
            raise first_error

    def fetch(self, url: str, wait_for: str | None = None) -> str:
        if self._context is None:
            raise RuntimeError(
                "BrowserClient must be opened with a with statement before fetching."
            )

        logger.info("Fetching URL with browser: %s", url)
        self.last_status_code = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            page = self._context.new_page()
            fetch_error: BaseException | None = None
            delay = None
            try:
                response = page.goto(url, wait_until="domcontentloaded")
                if response is None:
                    raise RuntimeError(f"Browser navigation returned no main-document response for {url}")
                self.last_status_code = response.status
                if not 200 <= response.status < 300:
                    fetch_error = HTTPStatusError(url, response.status, response.url)
                    delay = status_retry_delay(
                        response.status, attempt, response.headers.get("retry-after"), self._clock(),
                    )
                    if delay is None:
                        raise fetch_error
                else:
                    if wait_for:
                        page.wait_for_selector(wait_for)
                    html = page.content()
            except BaseException as error:
                fetch_error = error
                # No retry for navigation, selector, extraction or interruption errors.
                delay = None
                raise
            finally:
                try:
                    page.close()
                except BaseException:
                    if fetch_error is None:
                        raise
                    logger.exception("Failed to close page while handling a fetch error")
                    if delay is not None:
                        # Abort the pending retry: cleanup could not finish safely.
                        raise fetch_error

            if delay is not None:
                self._sleep(delay)
            else:
                logger.info("Fetched browser-rendered URL successfully: %s", url)
                return html
