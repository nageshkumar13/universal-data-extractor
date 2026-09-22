from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import pytest

import core.exporter as exporter_module
from core.exporter import Exporter
from core.quality import QualityProcessor


@pytest.fixture
def audit_result():
    profile = {
        "data_quality": True,
        "fields": {
            "id": {"selector": "article::text", "required": True, "type": "int"},
            "website": {"selector": "a::attr(href)", "required": True, "type": "URL"},
            "title": {"selector": "h2::text", "required": False, "type": "string"},
        },
        "unique_key": [], "duplicate_policy": "keep_first", "include_provenance": False,
    }
    return QualityProcessor().process([
        {"id": "1", "website": "https://example.com", "title": "Valid"},
        {"id": "bad", "website": "/relative", "title": "Cr\u00e8me br\u00fbl\u00e9e \u6771\u4eac",
         "_source_url": "https://example.com/page2", "_page": 2},
    ], profile)


def test_audit_artifacts_preserve_structure_unicode_counts_and_input(tmp_path, audit_result):
    original = deepcopy(audit_result)
    anchor = tmp_path / "client outputs" / "menu.csv"

    paths = Exporter().write_quality_artifacts(audit_result, anchor)

    assert paths == (anchor.with_suffix(".quality.json"), anchor.with_suffix(".rejected.json"))
    assert json.loads(paths[0].read_text(encoding="utf-8")) == {
        "extracted": 2, "valid_before_deduplication": 1, "rejected": 1,
        "invalid_values": 2, "duplicates_found": 0, "duplicates_removed": 0,
        "unkeyed_records": 0, "exported": 1,
    }
    assert json.loads(paths[1].read_text(encoding="utf-8")) == audit_result.rejected_records
    rejected = json.loads(paths[1].read_text(encoding="utf-8"))[0]
    assert len(rejected["reasons"]) == 2
    assert rejected["_source_url"] == "https://example.com/page2"
    assert rejected["_page"] == 2
    assert any(ord(character) > 127 for character in rejected["raw"]["title"])
    assert rejected["raw"]["title"].encode("utf-8") in paths[1].read_bytes()
    assert b"\\u" not in paths[1].read_bytes()
    assert audit_result == original
    assert set(anchor.parent.iterdir()) == set(paths)


def test_audit_json_is_stable_and_uses_existing_text_newline_convention(tmp_path, audit_result):
    exporter = Exporter()
    paths = exporter.write_quality_artifacts(audit_result, tmp_path / "menu.csv")
    first_bytes = [path.read_bytes() for path in paths]

    exporter.write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert [path.read_bytes() for path in paths] == first_bytes
    for path, data in zip(paths, (asdict(audit_result.report), audit_result.rejected_records)):
        expected = json.dumps(data, indent=4, ensure_ascii=False, allow_nan=False) + "\n"
        assert path.read_bytes() == expected.replace("\n", os.linesep).encode("utf-8")


@pytest.mark.parametrize("failed_write", [1, 2])
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_partial_json_write_preserves_previous_target_and_cleans_temp(
    tmp_path, audit_result, monkeypatch, failed_write, error_type,
):
    paths = (tmp_path / "menu.quality.json", tmp_path / "menu.rejected.json")
    for path in paths:
        path.write_text('{"previous": true}', encoding="utf-8")
    previous = [path.read_bytes() for path in paths]
    original_dump = exporter_module.json.dump
    calls = []
    error = error_type("audit write failed")

    def dump(data, handle, **kwargs):
        calls.append(Path(handle.name))
        assert Path(handle.name).parent == tmp_path
        assert paths[len(calls) - 1].read_bytes() == previous[len(calls) - 1]
        if len(calls) == failed_write:
            handle.write('{"partial":')
            raise error
        return original_dump(data, handle, **kwargs)

    monkeypatch.setattr(exporter_module.json, "dump", dump)

    with pytest.raises(error_type) as caught:
        Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert caught.value is error
    assert len(calls) == failed_write
    assert paths[failed_write - 1].read_bytes() == previous[failed_write - 1]
    if failed_write == 1:
        assert paths[1].read_bytes() == previous[1]
    else:
        assert json.loads(paths[0].read_text(encoding="utf-8")) == asdict(audit_result.report)
    assert set(tmp_path.iterdir()) == set(paths)


@pytest.mark.parametrize("failed_replace", [1, 2])
def test_replace_failure_preserves_previous_target_and_cleans_temp(
    tmp_path, audit_result, monkeypatch, failed_replace,
):
    paths = (tmp_path / "menu.quality.json", tmp_path / "menu.rejected.json")
    for path in paths:
        path.write_text("[]", encoding="utf-8")
    original_replace = Path.replace
    calls = []
    error = PermissionError("target locked")

    def replace(source, target):
        calls.append(target)
        assert source.parent == target.parent == tmp_path
        # Complete, readable JSON exists before the target is replaced.
        json.loads(source.read_text(encoding="utf-8"))
        if len(calls) == failed_replace:
            raise error
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace)

    with pytest.raises(PermissionError) as caught:
        Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert caught.value is error
    assert len(calls) == failed_replace
    assert paths[failed_replace - 1].read_text(encoding="utf-8") == "[]"
    assert set(tmp_path.iterdir()) == set(paths)


def test_cleanup_failure_does_not_mask_original_write_exception(tmp_path, audit_result, monkeypatch):
    error = OSError("original write failure")

    def fail_write(data, handle, **kwargs):
        handle.write("partial")
        raise error

    def fail_cleanup(path, **kwargs):
        raise PermissionError("temporary file locked")

    with monkeypatch.context() as patch:
        patch.setattr(exporter_module.json, "dump", fail_write)
        patch.setattr(Path, "unlink", fail_cleanup)
        with pytest.raises(OSError) as caught:
            Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert caught.value is error
    assert not (tmp_path / "menu.quality.json").exists()
    assert not (tmp_path / "menu.rejected.json").exists()
    temporary_files = list(tmp_path.iterdir())
    assert len(temporary_files) == 1
    assert temporary_files[0].suffix == ".tmp"
    temporary_files[0].unlink()


@pytest.mark.parametrize("value, expected", [
    (date(2024, 2, 29), "2024-02-29"),
    (datetime(2024, 2, 29, 12, 30, tzinfo=timezone.utc), "2024-02-29T12:30:00+00:00"),
])
def test_raw_native_dates_are_serialized_as_iso_without_mutation(tmp_path, audit_result, value, expected):
    audit_result.rejected_records[0]["raw"]["date"] = value
    original = deepcopy(audit_result)

    _, rejected_path = Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert json.loads(rejected_path.read_text(encoding="utf-8"))[0]["raw"]["date"] == expected
    assert audit_result == original


@pytest.mark.parametrize("value, error_type", [
    (float("nan"), ValueError), (float("inf"), ValueError),
    (float("-inf"), ValueError), (object(), TypeError),
])
def test_non_json_raw_values_fail_without_corrupting_previous_artifact(
    tmp_path, audit_result, value, error_type,
):
    rejected_path = tmp_path / "menu.rejected.json"
    rejected_path.write_text('["previous"]', encoding="utf-8")
    audit_result.rejected_records[0]["raw"]["unsupported"] = value

    with pytest.raises(error_type):
        Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert rejected_path.read_text(encoding="utf-8") == '["previous"]'
    assert set(tmp_path.iterdir()) == {tmp_path / "menu.quality.json", rejected_path}



@pytest.mark.parametrize("write_fails", [False, True])
def test_close_failure_preserves_the_first_error_and_previous_target(
    tmp_path, audit_result, monkeypatch, write_fails,
):
    target = tmp_path / "menu.quality.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    original_factory = exporter_module.NamedTemporaryFile
    write_error = OSError("write failed first")
    close_error = OSError("close failed")

    def temporary_file(**kwargs):
        file_handle = original_factory(**kwargs)
        original_close = file_handle.close

        def close():
            original_close()
            raise close_error

        file_handle.close = close
        return file_handle

    def fail_write(data, file_handle, **kwargs):
        file_handle.write("partial")
        raise write_error

    monkeypatch.setattr(exporter_module, "NamedTemporaryFile", temporary_file)
    if write_fails:
        monkeypatch.setattr(exporter_module.json, "dump", fail_write)

    with pytest.raises(OSError) as caught:
        Exporter().write_quality_artifacts(audit_result, tmp_path / "menu.csv")

    assert caught.value is (write_error if write_fails else close_error)
    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize("filename", ["example.csv", "menu.september.v2.csv"])
def test_audit_paths_preserve_dotted_parents_and_stems_without_touching_normal_exports(
    tmp_path, audit_result, filename,
):
    directory = tmp_path / "client.delivery" / "2026.09"
    directory.mkdir(parents=True)
    anchor = directory / filename
    normal_paths = [anchor.with_suffix(suffix) for suffix in (".csv", ".json", ".xlsx")]
    for path in normal_paths:
        path.write_bytes(b"existing normal export")

    paths = Exporter().write_quality_artifacts(audit_result, anchor)

    assert paths == (
        directory / f"{anchor.stem}.quality.json",
        directory / f"{anchor.stem}.rejected.json",
    )
    assert all(path.read_bytes() == b"existing normal export" for path in normal_paths)
    assert set(directory.iterdir()) == set(normal_paths + list(paths))



@pytest.mark.parametrize("name", ["menu.csv", "client exports/caf\u00e9 menu.v1.csv"])
def test_quality_path_helper_is_pure_and_preserves_names(tmp_path, monkeypatch, name):
    from unittest.mock import Mock
    from core.exporter import quality_artifact_paths

    anchor = tmp_path / name
    expected = (anchor.parent / (anchor.stem + ".quality.json"),
                anchor.parent / (anchor.stem + ".rejected.json"))
    before = list(tmp_path.rglob("*"))
    with monkeypatch.context() as patch:
        for method in ("open", "mkdir", "exists", "stat", "resolve"):
            patch.setattr(Path, method, Mock(side_effect=AssertionError("Helper must not access filesystem")))
        assert quality_artifact_paths(anchor) == expected
        assert quality_artifact_paths(anchor) == expected
    assert list(tmp_path.rglob("*")) == before


def test_audit_writer_uses_pure_path_api_without_changing_bytes(tmp_path, audit_result, monkeypatch):
    from unittest.mock import Mock

    anchor = tmp_path / "client exports" / "caf\u00e9 menu.csv"
    expected_paths = exporter_module.quality_artifact_paths(anchor)
    derive = Mock(wraps=exporter_module.quality_artifact_paths)
    monkeypatch.setattr(exporter_module, "quality_artifact_paths", derive)
    original = deepcopy(audit_result)
    paths = Exporter().write_quality_artifacts(audit_result, anchor)
    derive.assert_called_once_with(anchor)
    assert paths == expected_paths
    for path, data in zip(paths, (asdict(audit_result.report), audit_result.rejected_records)):
        expected = (json.dumps(data, indent=4, ensure_ascii=False, allow_nan=False) + "\n").replace("\n", os.linesep)
        assert path.read_bytes() == expected.encode("utf-8")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert exporter_module.quality_artifact_paths(anchor) == paths
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    assert audit_result == original
