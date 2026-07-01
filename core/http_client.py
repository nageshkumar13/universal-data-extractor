import logging

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


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

    def fetch(self, url: str) -> str:
        logger.info("Fetching URL: %s", url)

        try:
            response = self.session.get(url, timeout=self.timeout)
            self.last_status_code = response.status_code
            response.raise_for_status()
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
