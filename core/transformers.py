class Transformer:
    RATING_MAP = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
    }

    def transform(self, records: list[dict]) -> list[dict]:
        transformed_records: list[dict] = []

        for record in records:
            transformed = dict(record)

            if "price" in transformed:
                transformed["price"] = self._transform_price(transformed["price"])
            if "rating" in transformed:
                transformed["rating"] = self._transform_rating(transformed["rating"])
            if "availability" in transformed:
                transformed["availability"] = self._transform_availability(
                    transformed["availability"]
                )

            transformed_records.append(transformed)

        return transformed_records

    def _transform_price(self, value: object) -> float | None:
        if value is None:
            return None

        cleaned = (
            str(value)
            .strip()
            .replace("Ã‚Â£", "")
            .replace("Â£", "")
            .replace("£", "")
        )
        if not cleaned:
            return None

        return float(cleaned)

    def _transform_rating(self, value: object) -> int | None:
        if value is None:
            return None

        for token in str(value).split():
            normalized = token.strip().lower()
            if normalized in self.RATING_MAP:
                return self.RATING_MAP[normalized]

        return None

    def _transform_availability(self, value: object) -> bool | None:
        if value is None:
            return None

        normalized = " ".join(str(value).split()).lower()
        if "in stock" in normalized:
            return True
        if "out of stock" in normalized:
            return False
        return None
