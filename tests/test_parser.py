from core.parser import HTMLParser

POUND = "\u00a3"

HTML = f"""
<html>
  <body>
    <article class=\"product_pod\">
      <h3><a href=\"book-one/index.html\" title=\"Book One\">Book One</a></h3>
      <p class=\"price_color\">{POUND}10.00</p>
    </article>
    <article class=\"product_pod\">
      <h3><a href=\"book-two/index.html\" title=\"Book Two\">Book Two</a></h3>
      <p class=\"price_color\">{POUND}20.50</p>
    </article>
  </body>
</html>
"""

FIELDS = {
    "title": "article.product_pod h3 a::attr(title)",
    "price": "article.product_pod p.price_color::text",
    "product_url": "article.product_pod h3 a::attr(href)",
}


def test_parser_extracts_two_records() -> None:
    parser = HTMLParser()

    records = parser.extract(
        HTML,
        FIELDS,
        "https://books.toscrape.com/catalogue/page-1.html",
    )

    assert len(records) == 2


def test_parser_extracts_correct_titles() -> None:
    parser = HTMLParser()

    records = parser.extract(
        HTML,
        FIELDS,
        "https://books.toscrape.com/catalogue/page-1.html",
    )

    assert [record["title"] for record in records] == ["Book One", "Book Two"]


def test_parser_normalizes_relative_hrefs_to_absolute_urls() -> None:
    parser = HTMLParser()

    records = parser.extract(
        HTML,
        FIELDS,
        "https://books.toscrape.com/catalogue/page-1.html",
    )

    assert records[0]["product_url"] == (
        "https://books.toscrape.com/catalogue/book-one/index.html"
    )
    assert records[1]["product_url"] == (
        "https://books.toscrape.com/catalogue/book-two/index.html"
    )


def test_parser_extracts_price_text_correctly() -> None:
    parser = HTMLParser()

    records = parser.extract(
        HTML,
        FIELDS,
        "https://books.toscrape.com/catalogue/page-1.html",
    )

    assert records[0]["price"] == f"{POUND}10.00"
    assert records[1]["price"] == f"{POUND}20.50"
