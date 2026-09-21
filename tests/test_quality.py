from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from core.config import ProfileLoader
from core.quality import QualityProcessor


def quality_profile(fields=None, **settings):
    profile = {
        "data_quality": True,
        "fields": fields or {
            "value": {"selector": "article::text", "required": False, "type": "string"},
        },
        "unique_key": [],
        "duplicate_policy": "keep_first",
        "include_provenance": False,
    }
    profile.update(settings)
    return profile


def field(field_type="string", required=False, **settings):
    return {"selector": "article::text", "type": field_type, "required": required, **settings}


def process_value(value, field_type, **settings):
    return QualityProcessor().process(
        [{"value": value}],
        quality_profile({"value": field(field_type, **settings)}),
    )


@pytest.mark.parametrize("field_type, value, expected", [
    ("string", "  hello  world \t", "hello  world"),
    ("string", "  line one\nline two  ", "line one\nline two"),
    ("string", "00123", "00123"),
    ("int", 0, 0),
    ("int", -7, -7),
    ("int", " +0012 ", 12),
    ("int", "\t-12\n", -12),
    ("float", 2, 2.0),
    ("float", -2.5, -2.5),
    ("float", "  +12.50  ", 12.5),
    ("float", "-.5", -0.5),
    ("float", "1.", 1.0),
    ("float", "  -1.25e+2 ", -125.0),
    ("float", "1E-2", 0.01),
    ("bool", True, True),
    ("bool", False, False),
    ("bool", 1, True),
    ("bool", 0, False),
    ("bool", " TrUe ", True),
    ("bool", " FALSE ", False),
    ("bool", "Yes", True),
    ("bool", " no ", False),
    ("bool", "1", True),
    ("bool", " 0 ", False),
    ("URL", "  https://Example.com/a?x=1#part ", "https://Example.com/a?x=1#part"),
    ("URL", "http://localhost:8080/path", "http://localhost:8080/path"),
    ("URL", "https://[::1]/", "https://[::1]/"),
    ("URL", "HTTPS://example.com/", "HTTPS://example.com/"),
    ("date", " 2024-02-29 ", "2024-02-29"),
    ("date", date(2024, 2, 29), "2024-02-29"),
    ("date", datetime(2024, 2, 29, 23, 59), "2024-02-29"),
    ("date", datetime(2024, 2, 29, 0, 1, tzinfo=timezone(timedelta(hours=14))), "2024-02-29"),
])
def test_supported_values_are_normalized(field_type, value, expected):
    result = process_value(value, field_type, required=True)

    assert result.clean_records == [{"value": expected}]
    assert type(result.clean_records[0]["value"]) is type(expected)
    assert result.rejected_records == []
    assert result.report.invalid_values == 0
    assert result.report.exported == 1


@pytest.mark.parametrize("field_type, value", [
    ("string", 123), ("string", False), ("string", 1.5),
    ("string", ["text"]), ("string", {"text": "value"}),
    ("int", True), ("int", False), ("int", 1.0),
    ("int", "1.0"), ("int", "1e2"), ("int", "1,234"),
    ("int", "$12"), ("int", "1_000"), ("int", "0x10"),
    ("int", "+ 1"), ("int", "1 2"), ("int", "\u0661"),
    ("float", True), ("float", False), ("float", "1,234.50"),
    ("float", "$12"), ("float", "1_000"), ("float", "1 2"),
    ("float", "1,5"), ("float", "0x10"), ("float", "1e"),
    ("float", "."), ("float", "+ 1"), ("float", []),
    ("float", "nan"), ("float", "NaN"), ("float", "Infinity"),
    ("float", "-inf"), ("float", "1e9999"),
    ("float", float("nan")), ("float", float("inf")),
    ("float", float("-inf")), ("float", 10 ** 400),
    ("bool", 2), ("bool", -1), ("bool", 0.0), ("bool", 1.0),
    ("bool", "on"), ("bool", "off"), ("bool", "t"),
    ("bool", "y"), ("bool", "2"), ("bool", "1.0"),
    ("URL", 123), ("URL", "/relative"), ("URL", "//example.com"),
    ("URL", "ftp://example.com"), ("URL", "mailto:a@example.com"),
    ("URL", "https://"), ("URL", "http:///path"),
    ("URL", "https://?query=x"), ("URL", "https://[broken"),
    ("URL", "https://example.com:bad"), ("URL", "https://example.com:99999"),
    ("URL", "https://exa mple.com"), ("URL", "https://example.com/a\tb"),
    ("date", "2023-02-29"), ("date", "2024-13-01"),
    ("date", "2024-2-01"), ("date", "20240201"),
    ("date", "2024-W05-1"), ("date", "02/01/2024"),
    ("date", "2024-02-01T00:00:00"), ("date", "2024-02-01 trailing"),
    ("date", 20240201),
])
def test_invalid_optional_values_become_null_and_are_counted(field_type, value):
    result = process_value(value, field_type)

    assert result.clean_records == [{"value": None}]
    assert result.rejected_records == []
    assert result.report.invalid_values == 1
    assert result.report.valid_before_deduplication == result.report.exported == 1


@pytest.mark.parametrize("value, date_format, expected", [
    (" 29/02/2024 ", "%d/%m/%Y", "2024-02-29"),
    ("02/29/2024", "%m/%d/%Y", "2024-02-29"),
    ("2024.02.29", "%Y.%m.%d", "2024-02-29"),
    ("2024-02-29 23:59:01", "%Y-%m-%d %H:%M:%S", "2024-02-29"),
    (date(2024, 2, 29), "%d/%m/%Y", "2024-02-29"),
])
def test_configured_date_format(value, date_format, expected):
    result = process_value(value, "date", required=True, format=date_format)

    assert result.clean_records == [{"value": expected}]
    assert result.report.invalid_values == 0


@pytest.mark.parametrize("value", ["2024-02-29", "02/29/2024", "29/02/2023", "29/02/2024 extra"])
def test_configured_date_format_has_no_fallback(value):
    result = process_value(value, "date", required=True, format="%d/%m/%Y")

    assert result.clean_records == []
    assert result.rejected_records[0]["reasons"] == [
        {"code": "invalid_type", "field": "value", "expected_type": "date"},
    ]


@pytest.mark.parametrize("field_type", ["string", "int", "float", "bool", "URL", "date"])
@pytest.mark.parametrize("record", [{}, {"value": None}, {"value": ""}, {"value": " \t\n"}])
def test_optional_nulls_are_not_invalid_values(field_type, record):
    result = QualityProcessor().process([record], quality_profile({"value": field(field_type)}))

    assert result.clean_records == [{"value": None}]
    assert result.rejected_records == []
    assert result.report.invalid_values == 0


@pytest.mark.parametrize("record, code", [
    ({}, "missing_required"),
    ({"value": None}, "null_required"),
    ({"value": ""}, "null_required"),
    ({"value": " \t\n"}, "null_required"),
])
def test_required_missing_and_null_values_have_distinct_reasons(record, code):
    result = QualityProcessor().process(
        [record], quality_profile({"value": field(required=True)}),
    )

    assert result.clean_records == []
    assert result.rejected_records == [{
        "raw": record,
        "normalized": {"value": None},
        "reasons": [{"code": code, "field": "value"}],
        "_source_url": None,
        "_page": None,
    }]
    assert result.report.invalid_values == 0
    assert result.report.rejected == 1


def test_all_required_errors_are_collected_with_raw_and_normalized_data():
    profile = quality_profile({
        "missing": field(required=True),
        "blank": field(required=True),
        "price": field("float", required=True),
        "website": field("URL", required=True),
        "date": field("date", required=True),
        "title": field(),
        "optional": field("int"),
    })
    record = {
        "blank": " ", "price": "$12", "website": "/relative", "date": "yesterday",
        "title": "  Keep  spaces  ", "optional": "bad",
    }

    result = QualityProcessor().process([record], profile)
    rejected = result.rejected_records[0]

    assert rejected["raw"] == record
    assert rejected["normalized"] == {
        "missing": None, "blank": None, "price": None, "website": None,
        "date": None, "title": "Keep  spaces", "optional": None,
    }
    assert rejected["reasons"] == [
        {"code": "missing_required", "field": "missing"},
        {"code": "null_required", "field": "blank"},
        {"code": "invalid_type", "field": "price", "expected_type": "float"},
        {"code": "invalid_type", "field": "website", "expected_type": "URL"},
        {"code": "invalid_type", "field": "date", "expected_type": "date"},
    ]
    assert json.loads(json.dumps(rejected["reasons"])) == rejected["reasons"]
    assert result.report.invalid_values == 4
    assert result.report.rejected == 1


@pytest.mark.parametrize("include", [False, True])
def test_clean_provenance_is_opt_in_and_rejected_provenance_is_always_preserved(include):
    metadata = {"_source_url": "https://example.com/page2", "_page": 2}
    profile = quality_profile({"value": field(required=True)}, include_provenance=include)
    records = [{"value": " ok ", "_private": "omit", **metadata}, {"value": None, **metadata}]

    result = QualityProcessor().process(records, profile)

    assert result.clean_records == [{"value": "ok", **(metadata if include else {})}]
    assert result.rejected_records[0]["_source_url"] == metadata["_source_url"]
    assert result.rejected_records[0]["_page"] == 2


def test_processor_does_not_invent_missing_clean_provenance():
    result = QualityProcessor().process(
        [{"value": "ok", "_page": 3}], quality_profile(include_provenance=True),
    )

    assert result.clean_records == [{"value": "ok", "_page": 3}]


@pytest.mark.parametrize("policy, retained, removed", [
    ("keep_first", ["first"], 2),
    ("report_only", ["first", "second", "third"], 0),
])
def test_duplicates_use_normalized_keys_and_preserve_order(policy, retained, removed):
    profile = quality_profile(
        {"id": field("int"), "label": field()},
        unique_key=["id"], duplicate_policy=policy, include_provenance=True,
    )
    records = [
        {"id": " 01 ", "label": "first", "_page": 1},
        {"id": 1, "label": "second", "_page": 2},
        {"id": "+1", "label": "third", "_page": 3},
    ]

    result = QualityProcessor().process(records, profile)

    assert [row["label"] for row in result.clean_records] == retained
    assert result.clean_records[0] == {"id": 1, "label": "first", "_page": 1}
    assert result.rejected_records == []
    assert result.report.duplicates_found == 2
    assert result.report.duplicates_removed == removed
    assert result.report.valid_before_deduplication == 3


def test_composite_keys_compare_tuples_not_concatenated_values():
    profile = quality_profile({"a": field(), "b": field()}, unique_key=["a", "b"])
    records = [
        {"a": "ab", "b": "c"}, {"a": "a", "b": "bc"},
        {"a": "ab", "b": "d"}, {"a": " ab ", "b": "c"},
    ]

    result = QualityProcessor().process(records, profile)

    assert result.clean_records == records[:3]
    assert result.report.duplicates_found == result.report.duplicates_removed == 1


@pytest.mark.parametrize("policy", ["keep_first", "report_only"])
def test_null_key_components_are_kept_and_counted(policy):
    profile = quality_profile(
        {"a": field(), "b": field("int")}, unique_key=["a", "b"], duplicate_policy=policy,
    )
    records = [
        {"a": "same"}, {"a": "same", "b": None},
        {"a": "same", "b": " "}, {"a": "same", "b": "invalid"},
        {"a": None, "b": 1},
    ]

    result = QualityProcessor().process(records, profile)

    assert len(result.clean_records) == 5
    assert result.report.unkeyed_records == 5
    assert result.report.invalid_values == 1
    assert result.report.duplicates_found == result.report.duplicates_removed == 0


def test_required_null_keys_are_rejected_not_counted_as_unkeyed():
    result = QualityProcessor().process(
        [{"id": None}, {}], quality_profile({"id": field(required=True)}, unique_key=["id"]),
    )

    assert result.report.rejected == 2
    assert result.report.unkeyed_records == result.report.duplicates_found == 0


def test_empty_unique_key_disables_all_duplicate_detection():
    records = [{"value": "same"}, {"value": "same"}, {"value": None}, {}]

    result = QualityProcessor().process(records, quality_profile())

    assert len(result.clean_records) == 4
    assert result.report.duplicates_found == result.report.duplicates_removed == 0
    assert result.report.unkeyed_records == 0


def test_deduplication_occurs_only_after_validation():
    profile = quality_profile({"id": field(), "value": field("int", required=True)}, unique_key=["id"])
    records = [
        {"id": "same", "value": "bad"}, {"id": "same", "value": 1},
        {"id": "same", "value": "bad"}, {"id": "same", "value": 2},
    ]

    result = QualityProcessor().process(records, profile)

    assert result.clean_records == [{"id": "same", "value": 1}]
    assert [row["raw"] for row in result.rejected_records] == [records[0], records[2]]
    assert result.report.rejected == 2
    assert result.report.duplicates_found == result.report.duplicates_removed == 1


def test_duplicate_state_is_limited_to_one_process_call():
    processor = QualityProcessor()
    profile = quality_profile(unique_key=["value"])
    records = [{"value": "same"}, {"value": "same"}]

    first = processor.process(records, profile)
    second = processor.process(records, profile)

    assert first == second
    assert first.report.exported == 1
    assert first.report.duplicates_removed == 1


def test_records_and_profile_are_not_mutated_and_outputs_are_independent():
    # Nested metadata exercises ownership of values passed through unchanged.
    metadata = {
        "_source_url": {"urls": ["https://example.com"]},
        "_page": {"numbers": [1]},
    }
    records = [
        {"value": "  valid  ", **metadata},
        {"value": ["invalid"], "other": {"nested": [1]}, **metadata},
    ]
    profile = quality_profile({"value": field(required=True)}, include_provenance=True)
    original_records, original_profile = deepcopy(records), deepcopy(profile)

    result = QualityProcessor().process(records, profile)

    assert records == original_records
    assert profile == original_profile
    original_result = deepcopy(result)
    records[0]["_source_url"]["urls"].append("https://input.example.com")
    records[0]["_page"]["numbers"].append(2)
    records[1]["value"].append("input change")
    records[1]["other"]["nested"].append(2)
    assert result == original_result

    changed_records = deepcopy(records)
    result.clean_records[0]["_source_url"]["urls"].append("https://output.example.com")
    result.clean_records[0]["_page"]["numbers"].append(3)
    rejected = result.rejected_records[0]
    rejected["raw"]["value"].append("output change")
    rejected["raw"]["other"]["nested"].append(3)
    rejected["raw"]["_source_url"]["urls"].append("https://raw.example.com")
    rejected["raw"]["_page"]["numbers"].append(4)
    rejected["_source_url"]["urls"].append("https://rejected.example.com")
    rejected["_page"]["numbers"].append(5)
    rejected["normalized"]["value"] = "changed output"
    rejected["reasons"][0]["expected_type"] = "changed output"
    assert records == changed_records
    assert profile == original_profile


@pytest.mark.parametrize("policy, removed, exported", [("keep_first", 1, 3), ("report_only", 0, 4)])
def test_report_counts_and_invariants(policy, removed, exported):
    profile = quality_profile(
        {"id": field(), "amount": field("int", required=True), "flag": field("bool")},
        unique_key=["id"], duplicate_policy=policy,
    )
    records = [
        {"id": "a", "amount": "1", "flag": "yes"},
        {"id": " a ", "amount": 2, "flag": "bad"},
        {"id": None, "amount": 3, "flag": None},
        {"amount": 4, "flag": False},
        {"id": "a", "amount": "bad", "flag": "bad"},
        {"id": "b", "amount": None},
    ]

    result = QualityProcessor().process(records, profile)

    assert asdict(result.report) == {
        "extracted": 6, "valid_before_deduplication": 4, "rejected": 2,
        "invalid_values": 3, "duplicates_found": 1, "duplicates_removed": removed,
        "unkeyed_records": 2, "exported": exported,
    }
    assert result.report.extracted == result.report.valid_before_deduplication + result.report.rejected
    assert result.report.exported == result.report.valid_before_deduplication - result.report.duplicates_removed
    assert len(result.clean_records) == result.report.exported
    assert len(result.rejected_records) == result.report.rejected
    result.report.enforce_invariants()


@pytest.mark.parametrize("changes, message", [
    ({"extracted": 1}, "extracted !="),
    ({"exported": 1}, "exported !="),
])
def test_broken_report_invariants_raise_runtime_error(changes, message):
    report = QualityProcessor().process([], quality_profile()).report

    with pytest.raises(RuntimeError, match=message):
        replace(report, **changes).enforce_invariants()


def test_empty_input_returns_empty_records_and_zero_counts():
    result = QualityProcessor().process([], quality_profile())

    assert result.clean_records == result.rejected_records == []
    assert all(count == 0 for count in asdict(result.report).values())


@pytest.mark.parametrize("opt_in", [None, False])
def test_quality_processing_requires_opt_in(opt_in):
    profile = quality_profile()
    if opt_in is None:
        profile.pop("data_quality")
    else:
        profile["data_quality"] = opt_in

    with pytest.raises(ValueError, match="requires data_quality: true"):
        QualityProcessor().process([], profile)


def test_processor_accepts_the_committed_loader_contract(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        "site_name: Example\nengine: static\nstart_url: https://example.com\n"
        "data_quality: true\nfields:\n  title: 'h2::text'\n"
        "  count: {selector: '.count::text', type: int, required: true}\n",
        encoding="utf-8",
    )
    profile = ProfileLoader().load(path)

    result = QualityProcessor().process([{"title": "  hello  ", "count": "2"}], profile)

    assert result.clean_records == [{"title": "hello", "count": 2}]
    assert list(result.clean_records[0]) == ["title", "count"]


@pytest.mark.parametrize("value", [
    "https://exa mple.com",
    "https://example.com/a\tb",
    "https://example.com/a\nb",
    "https://example.com:bad",
    "https://example.com:99999",
    "https://example.com:-1",
    "https://[broken",
])
def test_invalid_required_urls_return_invalid_type_without_leaking_parse_errors(value):
    result = process_value(value, "URL", required=True)

    assert result.clean_records == []
    assert result.rejected_records == [{
        "raw": {"value": value},
        "normalized": {"value": None},
        "reasons": [{"code": "invalid_type", "field": "value", "expected_type": "URL"}],
        "_source_url": None,
        "_page": None,
    }]
    assert result.report.invalid_values == result.report.rejected == 1
    assert result.report.valid_before_deduplication == result.report.exported == 0
    result.report.enforce_invariants()
