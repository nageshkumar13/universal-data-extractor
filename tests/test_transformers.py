from core.transformers import Transformer

POUND = "\u00a3"


def test_price_becomes_float() -> None:
    transformer = Transformer()

    transformed = transformer.transform([
        {
            "price": f"{POUND}51.77",
        }
    ])

    assert transformed[0]["price"] == 51.77


def test_rating_becomes_integer() -> None:
    transformer = Transformer()

    transformed = transformer.transform([
        {
            "rating": "star-rating Three",
        }
    ])

    assert transformed[0]["rating"] == 3


def test_availability_in_stock_becomes_true() -> None:
    transformer = Transformer()

    transformed = transformer.transform([
        {
            "availability": "In stock",
        }
    ])

    assert transformed[0]["availability"] is True


def test_availability_out_of_stock_becomes_false() -> None:
    transformer = Transformer()

    transformed = transformer.transform([
        {
            "availability": "Out of stock",
        }
    ])

    assert transformed[0]["availability"] is False


def test_full_transform_returns_normalized_values_and_types() -> None:
    transformer = Transformer()
    records = [
        {
            "title": "A Light in the Attic",
            "price": f"{POUND}51.77",
            "rating": "star-rating Three",
            "availability": "In stock",
            "product_url": "https://example.com/book.html",
        }
    ]

    transformed = transformer.transform(records)

    assert transformed == [
        {
            "title": "A Light in the Attic",
            "price": 51.77,
            "rating": 3,
            "availability": True,
            "product_url": "https://example.com/book.html",
        }
    ]
    assert isinstance(transformed[0]["price"], float)
    assert isinstance(transformed[0]["rating"], int)
    assert isinstance(transformed[0]["availability"], bool)
