from core.url_utils import normalize_url


def test_relative_url_becomes_absolute() -> None:
    assert (
        normalize_url("book.html", "https://books.toscrape.com/catalogue/")
        == "https://books.toscrape.com/catalogue/book.html"
    )


def test_absolute_url_remains_absolute() -> None:
    assert (
        normalize_url(
            "https://books.toscrape.com/catalogue/book.html",
            "https://books.toscrape.com/catalogue/",
        )
        == "https://books.toscrape.com/catalogue/book.html"
    )


def test_empty_url_stays_safe() -> None:
    assert normalize_url("", "https://books.toscrape.com/catalogue/") == (
        "https://books.toscrape.com/catalogue/"
    )


def test_parent_path_resolves_correctly() -> None:
    assert (
        normalize_url(
            "../x.html",
            "https://books.toscrape.com/catalogue/page-2.html",
        )
        == "https://books.toscrape.com/x.html"
    )
