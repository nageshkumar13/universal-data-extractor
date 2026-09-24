from copy import deepcopy
from pathlib import Path

import pytest
from soupsieve import SelectorSyntaxError

from core.cache import URLCache, run_identity
from core.config import ProfileLoader
from core.pagination import Paginator
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



def test_explicit_record_selector_ignores_outside_matches_regression():
    html = '<aside><h2>Outside</h2><p>999</p></aside><article><h2>One</h2><p>10</p></article><article><h2>Two</h2><p>20</p></article>'
    assert HTMLParser().extract(html, {"title": "h2::text", "price": "p::text"},
                                "https://example.com", record_selector="article") == [
        {"title": "One", "price": "10"}, {"title": "Two", "price": "20"},
    ]


@pytest.mark.parametrize("html, expected", [
    ('<article></article>', [{"price": "", "title": ""}]),
    ('<aside><h2>Outside</h2><p>999</p></aside><article><h2>One</h2><p>10</p></article><article><h2>Two</h2></article><article></article><article><h2>Four</h2><p>40</p></article><article></article>',
     [{"price": "10", "title": "One"}, {"price": "", "title": "Two"},
      {"price": "", "title": ""}, {"price": "40", "title": "Four"}, {"price": "", "title": ""}]),
])
def test_missing_and_all_missing_containers_preserve_cardinality_and_field_order(html, expected):
    records = HTMLParser().extract(html, {"price": "p::text", "title": "h2::text"},
                                   "https://example.com", "article")
    assert records == expected
    assert all(list(record) == ["price", "title"] for record in records)


def test_first_match_per_container_and_no_global_fallback():
    html = '<h2>Outside</h2><article><h2>First</h2><h2>Second</h2><p>10</p><p>20</p></article>'
    fields = {"title": "h2::text", "price": "p::text"}
    assert HTMLParser().extract(html, fields, "https://example.com", "article") == [
        {"title": "First", "price": "10"},
    ]
    assert HTMLParser().extract(html, fields, "https://example.com", ".absent") == []


@pytest.mark.parametrize("record_selector, fields", [
    ("[", {"title": "h2::text"}),
    ("article", {"title": "[::text"}),
])
def test_malformed_record_or_field_css_propagates(record_selector, fields):
    with pytest.raises(SelectorSyntaxError):
        HTMLParser().extract('<article><h2>Title</h2></article>', fields,
                             "https://example.com", record_selector)


def test_unsupported_field_extraction_syntax_still_raises():
    with pytest.raises(ValueError, match="Unsupported selector format"):
        HTMLParser().extract('<article>Title</article>', {"title": "article"},
                             "https://example.com", "article")


def test_nested_containers_are_each_processed_in_document_order():
    html = '<article data-id="outer"><h2>Outer</h2><article data-id="inner"><h2>Inner</h2></article></article><article data-id="last"><h2>Last</h2></article>'
    fields = {"id": "article::attr(data-id)", "title": "h2::text", "text": "article::text"}
    assert HTMLParser().extract(html, fields, "https://example.com", "article") == [
        {"id": "outer", "title": "Outer", "text": "Outer Inner"},
        {"id": "inner", "title": "Inner", "text": "Inner"},
        {"id": "last", "title": "Last", "text": "Last"},
    ]


def test_existing_exact_selector_self_and_descendant_text_attributes():
    html = '<a class="card featured" href="../item" data-id="  7  "> Own <span>nested   text</span> tail <img src="image.png" title="  Picture  "></a>'
    fields = {
        "url": "a.card::attr(href)", "text": "a.card::text",
        "id": "a.card::attr(data-id)", "classes": "a.card::attr(class)",
        "child": "a.card span::text", "image": "img::attr(src)",
        "caption": "img::attr(title)", "missing_attribute": "img::attr(alt)",
    }
    expected = [{"url": "https://example.com/item", "text": "Own nested text tail",
                 "id": "7", "classes": "card featured", "child": "nested text",
                 "image": "https://example.com/list/image.png", "caption": "Picture",
                 "missing_attribute": ""}]
    assert HTMLParser().extract(html, fields, "https://example.com/list/", "a.card") == expected


def test_equivalent_but_nonidentical_selector_does_not_implicitly_match_self():
    html = '<a class="card" href="/item">Own <span>child</span></a>'
    fields = {"url": "a::attr(href)", "text": "a::text", "child": "span::text"}
    assert HTMLParser().extract(html, fields, "https://example.com", "a.card") == [
        {"url": "", "text": "", "child": "child"},
    ]


@pytest.mark.parametrize("selector", [None, "article"])
def test_legacy_missing_field_representation_matches_explicit_mode(selector):
    html = '<article><h2>One</h2><p>10</p></article><article></article>'
    fields = {"title": "article h2::text", "price": "article p::text"}
    assert HTMLParser().extract(html, fields, "https://example.com", selector) == [
        {"title": "One", "price": "10"}, {"title": "", "price": ""},
    ]


def test_legacy_common_ancestor_failure_is_unchanged():
    with pytest.raises(ValueError, match="Unable to infer record selector"):
        HTMLParser().extract('<article><h2>One</h2></article>',
                             {"title": "h2::text", "price": "p::text"}, "https://example.com")


LEGACY_PROFILE_CASES = [
    ("books.yaml", '<article class="product_pod"><h3><a href="one" title="Book One">Book</a></h3><p class="price_color">\u00a310.00</p><p class="star-rating Three"></p><p class="availability"> In stock </p></article><article class="product_pod"><h3><a href="two" title="Book Two">Book</a></h3><p class="price_color">\u00a320.00</p><p class="star-rating Two"></p><p class="availability">Available</p></article>',
     [{"title": "Book One", "price": "\u00a310.00", "rating": "star-rating Three", "availability": "In stock", "product_url": "https://books.toscrape.com/catalogue/one"},
      {"title": "Book Two", "price": "\u00a320.00", "rating": "star-rating Two", "availability": "Available", "product_url": "https://books.toscrape.com/catalogue/two"}]),
    ("jobs.yaml", ''.join(f'<div class="card-content"><h2 class="title is-5">Job {i}</h2><h3 class="subtitle is-6 company">Company {i}</h3><p class="location"> Town {i} </p><time datetime="2026-01-0{i}"></time><a class="card-footer-item" href="job-{i}">Apply</a></div>' for i in (1, 2)),
     [{"title": f"Job {i}", "company": f"Company {i}", "location": f"Town {i}", "date_posted": f"2026-01-0{i}", "apply_url": f"https://realpython.github.io/fake-jobs/job-{i}"} for i in (1, 2)]),
    ("quotes_js.yaml", ''.join(f'<div class="quote"><span class="text"> Quote {i} </span><span>by <small class="author">Author {i}</small></span><div class="tags">Tags: <a class="tag">tag-{i}</a></div></div>' for i in (1, 2)),
     [{"quote": f"Quote {i}", "author": f"Author {i}"} for i in (1, 2)]),
]


@pytest.mark.parametrize("filename, html, expected", LEGACY_PROFILE_CASES)
def test_bundled_profiles_keep_legacy_inference(filename, html, expected):
    profile = ProfileLoader().load(Path(__file__).resolve().parents[1] / "profiles" / filename)
    assert "record_selector" not in profile
    records = HTMLParser().extract(html, profile["fields"], profile["start_url"])
    assert records == expected
    assert all(list(record) == list(profile["fields"]) for record in records)



@pytest.mark.parametrize("record_selector, field, expected", [
    (".card", ".title::text", "Nested"),
    (".card", ".card .title::text", "Nested"),
    (".card", ".card-title::text", "Inside label"),
    (".card", ".card-extra::text", ""),
    ("article.card", "article.card > h2.title::text", "Direct"),
    (".card", ".card > h2.title + p.card-title::text", "Inside label"),
    (".card", ".card ~ h2::text", ""),
    (".card", "body > h2.title::text", ""),
    (".card", ".missing, .card > h2.title::text", "Direct"),
    (".card", ".card > h2.title, body > h2.title::text", "Direct"),
    ("article.card, aside.card", "article.card > h2.title, aside.card > h2.title::text", "Direct"),
    (".card", "article.card::attr(data-id)", ""),
    (".card", ".card::attr(data-id)", "own"),
    (".card", ".card::text", "Nested Direct Inside label"),
])
def test_explicit_selector_boundaries_and_existing_css_combinators(record_selector, field, expected):
    html = ('<body><h2 class="title">Outside before</h2><p class="card-title">Outside label</p>'
            '<article class="card" data-id="own"><section><h2 class="title">Nested</h2></section>'
            '<h2 class="title">Direct</h2><p class="card-title">Inside label</p></article>'
            '<h2 class="title">Outside after</h2><div class="card-extra">Outside prefix</div></body>')
    assert HTMLParser().extract(html, {"value": field}, "https://example.com", record_selector) == [
        {"value": expected},
    ]



@pytest.mark.parametrize("field", ["::text", "::attr(id)"])
def test_empty_css_is_not_an_implicit_self_selector(field):
    with pytest.raises(SelectorSyntaxError):
        HTMLParser().extract('<article id="own">Text</article>', {"value": field},
                             "https://example.com", "article")


def test_quotes_profile_extracts_only_available_fields_and_preserves_settings():
    profile = ProfileLoader().load(Path(__file__).resolve().parents[1] / "profiles/quotes_js.yaml")
    assert profile == {
        "site_name": "Quotes JavaScript",
        "engine": "browser",
        "start_url": "https://quotes.toscrape.com/js/",
        "wait_for": "div.quote",
        "max_pages": 3,
        "delay": 1.0,
        "fields": {
            "quote": "div.quote span.text::text",
            "author": "div.quote small.author::text",
        },
        "pagination": {"next_button": "li.next a"},
    }
    assert list(profile["fields"]) == ["quote", "author"]
    html = """
        <header><a href="/outside">Outside</a>
          <span class="text">Outside quote</span><small class="author">Outside author</small>
        </header>
        <div class="quote"><span class="text"> First   quote </span>
          <span>by <small class="author">First Author</small></span>
          <div class="tags">Tags: <a class="tag">first-tag</a></div>
        </div>
        <div class="quote"><span class="text">Second quote</span>
          <span>by <small class="author">Second Author</small></span>
          <div class="tags">Tags: <a class="tag">second-tag</a></div>
        </div>
        <ul><li class="next"><a href="/js/page/2/">Next</a></li></ul>
    """
    records = HTMLParser().extract(html, profile["fields"], profile["start_url"])
    assert records == [
        {"quote": "First quote", "author": "First Author"},
        {"quote": "Second quote", "author": "Second Author"},
    ]
    assert all(list(record) == ["quote", "author"] for record in records)
    assert Paginator().get_next_url(
        html, profile["start_url"], profile["pagination"]["next_button"],
    ) == "https://quotes.toscrape.com/js/page/2/"


def test_quotes_schema_change_cannot_reuse_old_completion(tmp_path):
    profile = ProfileLoader().load(Path(__file__).resolve().parents[1] / "profiles/quotes_js.yaml")
    previous_profile = deepcopy(profile)
    previous_profile["fields"]["author_url"] = "div.quote a::attr(href)"
    destination = tmp_path / "quotes_javascript.csv"
    old_key, old_fingerprint = run_identity(previous_profile, destination)
    new_key, new_fingerprint = run_identity(profile, destination)
    assert old_key == new_key
    assert old_fingerprint != new_fingerprint

    cache = URLCache(str(tmp_path / "cache.db"))
    cache.mark_complete(old_key, old_fingerprint, 3)
    assert cache.completed_pages(old_key, old_fingerprint) == 3
    assert cache.completed_pages(new_key, new_fingerprint) is None
