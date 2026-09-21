import logging
from types import TracebackType
from typing import Self

from requests import HTTPError, Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.last_status_code: int | None = None
        self.session = Session()

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
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
            response = self.session.get(url, timeout=self.timeout)
            self.last_status_code = response.status_code
            if not 200 <= response.status_code < 300:
                raise HTTPStatusError(url, response.status_code, response.url, response=response)
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
