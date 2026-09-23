import logging
from collections.abc import Callable
from time import sleep as sleep_seconds, time as wall_time
from types import TracebackType
from typing import Self

from requests import HTTPError, Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


from core.retry import MAX_ATTEMPTS, status_retry_delay


logger = logging.getLogger(__name__)


class HTTPStatusError(HTTPError):
    """A final main-document response outside the successful 2xx range."""

    def __init__(
        self, requested_url: str, status_code: int, final_url: str | None = None,
        *, response: Response | None = None,
    ) -> None:
        self.requested_url = requested_url
        self.final_url = final_url
        self.status_code = status_code
        super().__init__(
            f"Fetch failed with HTTP {status_code} for {final_url or requested_url}",
            response=response,
        )


class HttpClient:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    def __init__(
        self, timeout: float = 10.0, *,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sleep = sleep if sleep is not None else sleep_seconds
        self._clock = clock if clock is not None else wall_time
        self.timeout = timeout
        self.last_status_code: int | None = None
        self.session = Session()

        # Transport failures only: status attempts are bounded separately below.
        retries = Retry(
            total=3,
            backoff_factor=1,
            status=0,
            status_forcelist=(),
            respect_retry_after_header=False,
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retries)

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def fetch(self, url: str, wait_for: str | None = None) -> str:
        logger.info("Fetching URL: %s", url)

        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                # Each status attempt restarts at the requested URL, including redirects.
                response = self.session.get(url, timeout=self.timeout)
                self.last_status_code = response.status_code
                if 200 <= response.status_code < 300:
                    break
                error = HTTPStatusError(url, response.status_code, response.url, response=response)
                delay = status_retry_delay(
                    response.status_code, attempt, response.headers.get("Retry-After"), self._clock(),
                )
                try:
                    response.close()
                except BaseException:
                    logger.exception("Failed to close response while handling a fetch error")
                    raise error
                if delay is None:
                    raise error
                self._sleep(delay)
        except Exception:
            logger.exception("Failed to fetch URL: %s", url)
            raise

        logger.info("Fetched URL successfully: %s", url)

        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            if response.apparent_encoding:
                return response.content.decode(response.apparent_encoding, errors="replace")
            return response.text
