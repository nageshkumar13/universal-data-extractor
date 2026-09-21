from pathlib import Path
from typing import Any

import yaml


InvalidProfileError = ValueError


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Keep safe YAML construction while rejecting ambiguous mappings."""

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)

        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in keys:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"Duplicate YAML key: {key!r}",
                        key_node.start_mark,
                    )
                keys.add(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc

        return super().construct_mapping(node, deep=deep)


class ProfileLoader:
    REQUIRED_KEYS = ("site_name", "engine", "start_url", "fields")
    VALID_ENGINES = ("static", "browser")
    FIELD_PROPERTIES = ("selector", "required", "type", "format")
    FIELD_TYPES = ("string", "int", "float", "bool", "URL", "date")
    QUALITY_SETTINGS = ("unique_key", "duplicate_policy", "include_provenance")

    def load(self, path: str | Path) -> dict[str, Any]:
        profile_path = Path(path)

        try:
            content = profile_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidProfileError(
                f"Unable to read profile: {profile_path}"
            ) from exc

        try:
            profile = yaml.load(content, Loader=_UniqueKeySafeLoader)
        except yaml.YAMLError as exc:
            raise InvalidProfileError(
                f"Invalid YAML in profile: {profile_path}\n{exc}"
            ) from exc

        if not isinstance(profile, dict):
            raise InvalidProfileError("Profile must be a YAML mapping.")

        self.validate(profile)
        if profile.get("data_quality", False):
            profile["fields"] = {
                name: {
                    "required": False,
                    "type": "string",
                    **(
                        {"selector": definition}
                        if isinstance(definition, str)
                        else definition
                    ),
                }
                for name, definition in profile["fields"].items()
            }
            profile.setdefault("unique_key", [])
            profile.setdefault("duplicate_policy", "keep_first")
            profile.setdefault("include_provenance", False)
        return profile

    def validate(self, profile: dict[str, Any]) -> None:
        for key in self.REQUIRED_KEYS:
            if key not in profile:
                raise InvalidProfileError(f"Missing required key: {key}")

        engine = profile["engine"]
        if engine not in self.VALID_ENGINES:
            raise InvalidProfileError(
                "Invalid engine.\n\nExpected one of:\nstatic\nbrowser\n\nReceived:\n"
                f"{engine}"
            )

        wait_for = profile.get("wait_for")
        if wait_for is not None and (
            not isinstance(wait_for, str) or not wait_for.strip()
        ):
            raise InvalidProfileError(
                "Invalid wait_for. Expected a non-empty CSS selector."
            )

        start_url = profile["start_url"]
        if not isinstance(start_url, str) or not start_url.startswith(
            ("http://", "https://")
        ):
            raise InvalidProfileError(
                "Invalid start_url. Expected a URL starting with http:// or https://"
            )

        fields = profile["fields"]
        if not isinstance(fields, dict):
            raise InvalidProfileError("Invalid fields. Expected a dictionary.")

        quality = profile.get("data_quality", False)
        if not isinstance(quality, bool):
            raise InvalidProfileError("Invalid data_quality. Expected a boolean.")

        for setting in self.QUALITY_SETTINGS:
            if setting in profile and not quality:
                raise InvalidProfileError(f"{setting} requires data_quality: true.")

        for name, definition in fields.items():
            if not isinstance(name, str) or not name.strip():
                raise InvalidProfileError("Output field names must be non-empty strings.")
            if name.startswith("_"):
                raise InvalidProfileError(f"Reserved output field name: {name!r}.")

            if isinstance(definition, str):
                self._validate_selector(name, definition)
                continue
            if not isinstance(definition, dict):
                raise InvalidProfileError(
                    f"Invalid field {name!r}. Expected a selector string or mapping."
                )
            if not quality:
                raise InvalidProfileError(
                    f"Extended field {name!r} requires data_quality: true."
                )

            for property_name in definition:
                if property_name not in self.FIELD_PROPERTIES:
                    raise InvalidProfileError(
                        f"Unknown property {property_name!r} in field {name!r}."
                    )
            self._validate_selector(name, definition.get("selector"))

            if not isinstance(definition.get("required", False), bool):
                raise InvalidProfileError(
                    f"Invalid required for field {name!r}. Expected a boolean."
                )
            field_type = definition.get("type", "string")
            if field_type not in self.FIELD_TYPES:
                raise InvalidProfileError(
                    f"Unsupported type {field_type!r} for field {name!r}. "
                    f"Expected one of: {', '.join(self.FIELD_TYPES)}."
                )
            if "format" in definition:
                if field_type != "date":
                    raise InvalidProfileError(
                        f"format is allowed only for type date in field {name!r}."
                    )
                date_format = definition["format"]
                if not isinstance(date_format, str) or not date_format.strip():
                    raise InvalidProfileError(
                        f"Invalid format for field {name!r}. "
                        "Expected a non-empty string."
                    )

        if quality:
            if not isinstance(profile.get("include_provenance", False), bool):
                raise InvalidProfileError(
                    "Invalid include_provenance. Expected a boolean."
                )
            if profile.get("duplicate_policy", "keep_first") not in (
                "keep_first", "report_only",
            ):
                raise InvalidProfileError(
                    "Invalid duplicate_policy. Expected keep_first or report_only."
                )

            unique_key = profile.get("unique_key", [])
            if not isinstance(unique_key, list):
                raise InvalidProfileError(
                    "Invalid unique_key. Expected a list of output-field names."
                )
            for name in unique_key:
                if not isinstance(name, str) or name not in fields:
                    raise InvalidProfileError(
                        f"Invalid unique_key field {name!r}. "
                        "Must reference a configured output field."
                    )

    @staticmethod
    def _validate_selector(name: str, selector: object) -> None:
        if not isinstance(selector, str) or not selector.strip():
            raise InvalidProfileError(
                f"Invalid selector for field {name!r}. Expected a non-empty string."
            )
