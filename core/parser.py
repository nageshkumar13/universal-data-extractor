from bs4 import BeautifulSoup
from bs4 import FeatureNotFound

from core.url_utils import normalize_url


class HTMLParser:
    def extract(
        self, html: str, fields: dict[str, str], base_url: str
    ) -> list[dict[str, str]]:
        soup = self._build_soup(html)
        record_selector = self._infer_record_selector(fields)
        records: list[dict[str, str]] = []

        for element in soup.select(record_selector):
            record: dict[str, str] = {}

            for field_name, selector in fields.items():
                css_selector, extract_type, attribute_name = self._parse_selector(selector)
                relative_selector = self._make_relative_selector(css_selector, record_selector)
                target = element if not relative_selector else element.select_one(relative_selector)

                if target is None:
                    value = ""
                elif extract_type == "text":
                    value = self._extract_text(target)
                else:
                    value = self._extract_attr(target, attribute_name, base_url)

                record[field_name] = value

            records.append(record)

        return records

    def _build_soup(self, html: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(html, "html.parser")

    def _infer_record_selector(self, fields: dict[str, str]) -> str:
        selectors = [self._parse_selector(selector)[0] for selector in fields.values()]
        token_groups = [selector.split() for selector in selectors]

        common_tokens: list[str] = []
        for tokens in zip(*token_groups):
            if all(token == tokens[0] for token in tokens):
                common_tokens.append(tokens[0])
            else:
                break

        if not common_tokens:
            raise ValueError("Unable to infer record selector from fields.")

        return " ".join(common_tokens)

    def _parse_selector(self, selector: str) -> tuple[str, str, str | None]:
        if selector.endswith("::text"):
            return selector.removesuffix("::text"), "text", None

        marker = "::attr("
        if marker in selector and selector.endswith(")"):
            css_selector, attribute_name = selector.rsplit(marker, 1)
            return css_selector, "attr", attribute_name[:-1]

        raise ValueError(f"Unsupported selector format: {selector}")

    def _make_relative_selector(self, selector: str, record_selector: str) -> str:
        prefix = f"{record_selector} "
        if selector == record_selector:
            return ""
        if selector.startswith(prefix):
            return selector[len(prefix) :]
        return selector

    def _extract_text(self, element: object) -> str:
        cleaned_text = " ".join(element.get_text(" ", strip=True).split())
        return cleaned_text.replace("Â£", "£")

    def _extract_attr(
        self, element: object, attribute_name: str | None, base_url: str
    ) -> str:
        if not attribute_name:
            return ""

        value = element.get(attribute_name, "")
        if isinstance(value, list):
            value = " ".join(value)
        else:
            value = str(value).strip()

        if attribute_name in {"href", "src"} and value:
            return normalize_url(value, base_url)

        return value
