from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4 import FeatureNotFound


class Paginator:
    def get_next_url(
        self,
        html: str,
        current_url: str,
        next_selector: str,
    ) -> str | None:
        try:
            soup = BeautifulSoup(html, "lxml")
        except FeatureNotFound:
            soup = BeautifulSoup(html, "html.parser")

        next_element = soup.select_one(next_selector)
        if next_element is None:
            return None

        href = next_element.get("href")
        if not href:
            return None

        return urljoin(current_url, href)
