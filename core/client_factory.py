from types import TracebackType
from typing import Protocol, Self

from core.browser_client import BrowserClient
from core.http_client import HttpClient


class PageClient(Protocol):
    def __enter__(self) -> Self:
        """Open the client for a run."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client without suppressing exceptions."""

    def close(self) -> None:
        """Release client resources."""

    def fetch(self, url: str, wait_for: str | None = None) -> str:
        """Return the rendered HTML for a URL."""


def create_client(engine: str) -> PageClient:
    if engine == "static":
        return HttpClient()
    if engine == "browser":
        return BrowserClient()
    raise ValueError(f"Unsupported engine: {engine}")
