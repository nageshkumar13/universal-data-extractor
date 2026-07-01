from urllib.parse import urljoin


def normalize_url(url: str, base_url: str) -> str:
    """Convert relative URLs to absolute URLs."""
    return urljoin(base_url, url)
