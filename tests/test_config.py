from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import yaml

import pytest

from core.config import InvalidProfileError
from core.config import ProfileLoader


def test_profile_loader_accepts_browser_engine() -> None:
    loader = ProfileLoader()

    loader.validate(
        {
            "site_name": "Example",
            "engine": "browser",
            "start_url": "https://example.com",
            "wait_for": "article.result",
            "fields": {"title": "h1::text"},
        }
    )


def test_profile_loader_rejects_empty_wait_for_selector() -> None:
    loader = ProfileLoader()

    with pytest.raises(InvalidProfileError, match="Invalid wait_for"):
        loader.validate(
            {
                "site_name": "Example",
                "engine": "browser",
                "start_url": "https://example.com",
                "wait_for": "  ",
                "fields": {"title": "h1::text"},
            }
        )


@pytest.fixture
def profile():
    return {
        "site_name": "Example",
        "engine": "static",
        "start_url": "https://example.com",
        "fields": {"title": "article h2::text"},
    }


def load_profile(tmp_path, profile):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return ProfileLoader().load(path)


@pytest.mark.parametrize("filename", ["books.yaml", "jobs.yaml", "quotes_js.yaml"])
def test_existing_profiles_load_unchanged(filename):
    path = Path(__file__).resolve().parents[1] / "profiles" / filename
    expected = yaml.safe_load(path.read_text(encoding="utf-8"))

    loaded = ProfileLoader().load(path)

    assert loaded == expected
    assert list(loaded["fields"]) == list(expected["fields"])
    assert all(isinstance(value, str) for value in loaded["fields"].values())


@pytest.mark.parametrize("quality", [None, False])
def test_legacy_simple_mapping_is_unchanged(tmp_path, profile, quality):
    if quality is not None:
        profile["data_quality"] = quality
    profile["fields"]["title"] = "  article h2::text  "

    assert load_profile(tmp_path, profile) == profile


@pytest.mark.parametrize("policy", ["keep_first", "report_only"])
def test_quality_schema_loads_with_defaults_and_preserves_order(tmp_path, profile, policy):
    profile.update({
        "data_quality": True,
        "include_provenance": True,
        "duplicate_policy": policy,
        "unique_key": ["website", "title"],
        "fields": {
            "title": "article h2::text",
            "price": {"selector": "article .price::text", "required": True, "type": "float"},
            "website": {"selector": "article a::attr(href)", "type": "URL"},
            "listed": {"selector": "article time::text", "type": "date", "format": "%m/%d/%Y"},
            "note": {"selector": "article .note::text"},
        },
    })
    original = deepcopy(profile)
    ProfileLoader().validate(profile)
    assert profile == original

    loaded = load_profile(tmp_path, profile)

    assert list(loaded["fields"]) == list(profile["fields"])
    assert loaded["unique_key"] == ["website", "title"]
    assert loaded["duplicate_policy"] == policy
    assert loaded["include_provenance"] is True
    assert loaded["fields"]["title"] == {
        "selector": "article h2::text", "required": False, "type": "string",
    }
    assert loaded["fields"]["note"] == {
        "selector": "article .note::text", "required": False, "type": "string",
    }
    assert loaded["fields"]["price"] == profile["fields"]["price"]
    assert loaded["fields"]["website"]["required"] is False
    assert loaded["fields"]["listed"]["format"] == "%m/%d/%Y"
    ProfileLoader().validate(loaded)


def test_quality_shorthand_and_top_level_defaults(tmp_path, profile):
    profile["data_quality"] = True

    loaded = load_profile(tmp_path, profile)

    assert loaded["fields"]["title"] == {
        "selector": "article h2::text", "required": False, "type": "string",
    }
    assert loaded["unique_key"] == []
    assert loaded["duplicate_policy"] == "keep_first"
    assert loaded["include_provenance"] is False


@pytest.mark.parametrize("field_type", ["string", "int", "float", "bool", "URL", "date"])
def test_supported_field_types_are_not_converted(tmp_path, profile, field_type):
    profile["data_quality"] = True
    profile["fields"]["title"] = {"selector": "article h2::text", "type": field_type}

    assert load_profile(tmp_path, profile)["fields"]["title"]["type"] == field_type


@pytest.mark.parametrize("definition, message", [
    ({"selector": "h2::text", "source": "title"}, "Unknown property 'source'"),
    ({"source": "title"}, "Unknown property 'source'"),
    ({"selector": "h2::text", "unknown": True}, "Unknown property 'unknown'"),
    ({"selector": "h2::text", "type": "integer"}, "Unsupported type"),
    ({"selector": "h2::text", "type": "boolean"}, "Unsupported type"),
    ({"selector": "h2::text", "type": "url"}, "Unsupported type"),
    ({"selector": "h2::text", "type": None}, "Unsupported type"),
    ({"selector": "h2::text", "type": []}, "Unsupported type"),
    ({"selector": "h2::text", "format": "%Y-%m-%d"}, "format is allowed only"),
    ({"selector": "h2::text", "type": "int", "format": "%Y"}, "format is allowed only"),
    ({"selector": "h2::text", "type": "date", "format": " "}, "Invalid format"),
    ({"selector": "h2::text", "type": "date", "format": None}, "Invalid format"),
    ({"selector": "h2::text", "type": "date", "format": 12}, "Invalid format"),
    ({}, "Invalid selector"),
    ({"selector": ""}, "Invalid selector"),
    ({"selector": "  "}, "Invalid selector"),
    ({"selector": None}, "Invalid selector"),
    ({"selector": ["h2::text"]}, "Invalid selector"),
    ({"selector": 1}, "Invalid selector"),
    (None, "Invalid field"),
    ([], "Invalid field"),
    (False, "Invalid field"),
])
def test_invalid_extended_field(tmp_path, profile, definition, message):
    profile["data_quality"] = True
    profile["fields"]["title"] = definition

    with pytest.raises(InvalidProfileError, match=message):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("selector", ["", " ", "\t\n"])
def test_empty_shorthand_selector_is_rejected(tmp_path, profile, quality, selector):
    profile["data_quality"] = quality
    profile["fields"]["title"] = selector

    with pytest.raises(InvalidProfileError, match="Invalid selector"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("setting", ["data_quality", "include_provenance", "required"])
@pytest.mark.parametrize("value", ["true", "false", 0, 1, None, [], {}])
def test_boolean_settings_require_booleans(tmp_path, profile, setting, value):
    profile["data_quality"] = True
    if setting == "required":
        profile["fields"]["title"] = {"selector": "h2::text", setting: value}
    else:
        profile[setting] = value

    with pytest.raises(InvalidProfileError, match=f"Invalid {setting}"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("quality", [None, False])
@pytest.mark.parametrize("settings", [
    {"fields": {"title": {"selector": "h2::text"}}},
    {"unique_key": []},
    {"duplicate_policy": "keep_first"},
    {"include_provenance": False},
])
def test_quality_features_require_explicit_opt_in(tmp_path, profile, quality, settings):
    if quality is not None:
        profile["data_quality"] = quality
    profile.update(settings)

    with pytest.raises(InvalidProfileError, match="requires data_quality: true"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("key", ["title", None, {}, ["unknown"], [None], [1], [[]]])
def test_invalid_unique_key(tmp_path, profile, key):
    profile.update(data_quality=True, unique_key=key)

    with pytest.raises(InvalidProfileError, match="Invalid unique_key"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("policy", ["last", "", None, True, [], {}])
def test_invalid_duplicate_policy(tmp_path, profile, policy):
    profile.update(data_quality=True, duplicate_policy=policy)

    with pytest.raises(InvalidProfileError, match="Invalid duplicate_policy"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("name", ["_source_url", "_page", "_custom"])
def test_reserved_output_names_are_rejected(tmp_path, profile, quality, name):
    profile["data_quality"] = quality
    profile["fields"][name] = "h2::text"

    with pytest.raises(InvalidProfileError, match="Reserved output field name"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("name", ["", "  ", 1, None])
def test_output_names_must_be_nonempty_strings(tmp_path, profile, name):
    profile["fields"] = {name: "h2::text"}

    with pytest.raises(InvalidProfileError, match="Output field names"):
        load_profile(tmp_path, profile)


@pytest.mark.parametrize("body, key", [
    ("fields: {title: 'h2::text'}\nengine: browser\n", "engine"),
    ("fields:\n  title: h2::text\n  title: h3::text\n", "title"),
    ("fields:\n  title:\n    selector: h2::text\n    selector: h3::text\n", "selector"),
    ("fields:\n  title:\n    selector: h2::text\n    required: true\n    required: false\n", "required"),
    ("fields:\n  title:\n    <<: {selector: 'h2::text'}\n    selector: h3::text\n", "selector"),
])
def test_duplicate_yaml_keys_are_rejected(tmp_path, body, key):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "site_name: Example\nengine: static\nstart_url: https://example.com\n"
        "data_quality: true\n" + body,
        encoding="utf-8",
    )

    with pytest.raises(InvalidProfileError, match=f"Duplicate YAML key: '{key}'"):
        ProfileLoader().load(path)


def test_yaml_aliases_without_duplicate_keys_remain_supported(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text(
        "site_name: Example\nengine: static\nstart_url: https://example.com\n"
        "data_quality: true\nfields:\n"
        "  first: &field {selector: 'article h2::text'}\n"
        "  second: *field\n",
        encoding="utf-8",
    )

    loaded = ProfileLoader().load(path)

    assert list(loaded["fields"]) == ["first", "second"]
    assert loaded["fields"]["first"] == loaded["fields"]["second"]
    loaded["fields"]["first"]["required"] = True
    assert loaded["fields"]["second"]["required"] is False


@pytest.mark.parametrize("body", [
    "fields: !!python/object/apply:builtins.list []",
    "fields: {[one, two]: value}",
    "fields: !!map []",
])
def test_invalid_or_unsafe_yaml_raises_configuration_error(tmp_path, body):
    path = tmp_path / "invalid.yaml"
    path.write_text(
        "site_name: Example\nengine: static\nstart_url: https://example.com\n" + body,
        encoding="utf-8",
    )

    with pytest.raises(InvalidProfileError, match="Invalid YAML"):
        ProfileLoader().load(path)


def test_invalid_profile_is_rejected_before_client_or_robots_creation(tmp_path, monkeypatch):
    import core.runner as runner_module

    path = tmp_path / "invalid.yaml"
    path.write_text(
        "site_name: Example\nengine: browser\nstart_url: https://example.com\n"
        "fields: {title: {selector: 'h2::text'}}\n",
        encoding="utf-8",
    )
    factory = Mock(side_effect=AssertionError("Client must not be created"))
    robots = Mock(side_effect=AssertionError("Robots must not be requested"))
    monkeypatch.setattr(runner_module, "create_client", factory)
    monkeypatch.setattr(runner_module, "RobotsChecker", robots)
    runner = runner_module.ScrapeRunner.__new__(runner_module.ScrapeRunner)
    runner.loader = ProfileLoader()
    runner.client = None

    with pytest.raises(InvalidProfileError, match="requires data_quality: true"):
        runner.run(path, tmp_path)

    factory.assert_not_called()
    robots.assert_not_called()



def test_record_selector_omission_does_not_enable_mode(tmp_path, profile):
    loaded = load_profile(tmp_path, profile)
    assert "record_selector" not in loaded
    assert loaded == profile


@pytest.mark.parametrize("selector", ["article.card", "  article[data-name='two  words'] > div  ", "["])
def test_record_selector_string_is_preserved_without_css_validation(tmp_path, profile, selector):
    profile["record_selector"] = selector
    assert load_profile(tmp_path, profile)["record_selector"] == selector


@pytest.mark.parametrize("selector", [1, True, False, [], {}, None, "", " ", "\t\n"])
def test_invalid_record_selector_rejected_on_load(tmp_path, profile, selector):
    profile["record_selector"] = selector
    with pytest.raises(InvalidProfileError, match="Invalid record_selector"):
        load_profile(tmp_path, profile)



def test_record_selector_validation_preserves_mapping_and_unknown_key_policy(profile, tmp_path):
    profile.update(record_selector="  article.card  ", client_notes={"labels": ["unchanged"]})
    before = deepcopy(profile)
    ProfileLoader().validate(profile)
    assert profile == before
    assert load_profile(tmp_path, profile) == before


@pytest.mark.parametrize("selector", [1.5, 0.0])
def test_record_selector_rejects_noninteger_numbers(profile, tmp_path, selector):
    profile["record_selector"] = selector
    with pytest.raises(InvalidProfileError, match="Invalid record_selector"):
        load_profile(tmp_path, profile)
