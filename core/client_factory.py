from typing import Protocol

from core.browser_client import BrowserClient
from core.http_client import HttpClient


class PageClient(Protocol):
    def fetch(self, url: str, wait_for: str | None = None) -> str:
        """Return the rendered HTML for a URL."""


def create_client(engine: str) -> PageClient:
    if engine == "static":
        return HttpClient()
    if engine == "browser":
        return BrowserClient()
    raise ValueError(f"Unsupported engine: {engine}")
