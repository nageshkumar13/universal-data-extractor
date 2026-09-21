"""Isolated, opt-in validation and within-call duplicate handling."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
import math
import re
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class QualityReport:
    extracted: int
    valid_before_deduplication: int
    rejected: int
    invalid_values: int
    duplicates_found: int
    duplicates_removed: int
    unkeyed_records: int
    exported: int

    def enforce_invariants(self) -> None:
        """Raise even under python -O if record accounting is inconsistent."""
        if self.extracted != self.valid_before_deduplication + self.rejected:
            raise RuntimeError(
                "Quality count invariant failed: extracted != "
                f"valid_before_deduplication + rejected ({self!r})"
            )
        if self.exported != self.valid_before_deduplication - self.duplicates_removed:
            raise RuntimeError(
                "Quality count invariant failed: exported != "
                f"valid_before_deduplication - duplicates_removed ({self!r})"
            )


@dataclass
class QualityResult:
    clean_records: list[dict[str, Any]]
    rejected_records: list[dict[str, Any]]
    report: QualityReport


class QualityProcessor:
    def process(
        self, records: list[dict[str, Any]], profile: dict[str, Any]
    ) -> QualityResult:
        """Process a validated, expanded quality profile without mutating inputs.

        invalid_values counts all non-null conversion failures, including those
        on rejected or subsequently deduplicated records. exported is the number
        of returned clean records; this processor performs no file export.
        """
        if profile.get("data_quality") is not True:
            raise ValueError("QualityProcessor requires data_quality: true.")

        fields = profile["fields"]
        unique_key = profile["unique_key"]
        clean_records = []
        rejected_records = []
        seen = set()
        valid_count = invalid_values = duplicates_found = duplicates_removed = 0
        unkeyed_records = 0

        for record in records:
            raw = deepcopy(record)
            normalized = {}
            reasons = []
            for name, definition in fields.items():
                value = record.get(name)
                if isinstance(value, str):
                    value = value.strip()
                    if not value:
                        value = None

                if value is None:
                    normalized[name] = None
                    if definition["required"]:
                        reasons.append({
                            "code": "null_required" if name in record else "missing_required",
                            "field": name,
                        })
                    continue

                try:
                    normalized[name] = self._convert(value, definition)
                except (ValueError, TypeError, OverflowError):
                    normalized[name] = None
                    invalid_values += 1
                    if definition["required"]:
                        reasons.append({
                            "code": "invalid_type",
                            "field": name,
                            "expected_type": definition["type"],
                        })

            if reasons:
                rejected_records.append({
                    "raw": raw,
                    "normalized": normalized,
                    "reasons": reasons,
                    "_source_url": deepcopy(record.get("_source_url")),
                    "_page": deepcopy(record.get("_page")),
                })
                continue

            valid_count += 1
            if unique_key:
                key = tuple(normalized[name] for name in unique_key)
                if any(value is None for value in key):
                    unkeyed_records += 1
                elif key in seen:
                    duplicates_found += 1
                    if profile["duplicate_policy"] == "keep_first":
                        duplicates_removed += 1
                        continue
                else:
                    seen.add(key)

            if profile["include_provenance"]:
                for name in ("_source_url", "_page"):
                    if name in record:
                        normalized[name] = deepcopy(record[name])
            clean_records.append(normalized)

        report = QualityReport(
            extracted=len(records),
            valid_before_deduplication=valid_count,
            rejected=len(rejected_records),
            invalid_values=invalid_values,
            duplicates_found=duplicates_found,
            duplicates_removed=duplicates_removed,
            unkeyed_records=unkeyed_records,
            exported=len(clean_records),
        )
        report.enforce_invariants()
        return QualityResult(clean_records, rejected_records, report)

    @staticmethod
    def _convert(value: Any, definition: dict[str, Any]) -> Any:
        field_type = definition["type"]
        if field_type == "string":
            if isinstance(value, str):
                return value
        elif field_type == "int":
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value):
                return int(value)
        elif field_type == "float":
            if isinstance(value, str):
                if not re.fullmatch(
                    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                    value,
                ):
                    raise ValueError("Expected a decimal or scientific-notation number.")
            elif not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("Expected a number.")
            number = float(value)
            if math.isfinite(number):
                return number
        elif field_type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                tokens = {
                    "true": True, "yes": True, "1": True,
                    "false": False, "no": False, "0": False,
                }
                if value.lower() in tokens:
                    return tokens[value.lower()]
        elif field_type == "URL":
            if isinstance(value, str) and not any(
                character.isspace() or ord(character) < 32 or ord(character) == 127
                for character in value
            ):
                parsed = urlsplit(value)
                if parsed.scheme in ("http", "https") and parsed.hostname:
                    # Accessing port also rejects malformed or out-of-range ports.
                    parsed.port
                    return value
        elif field_type == "date":
            if isinstance(value, datetime):
                return value.date().isoformat()
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, str):
                if "format" in definition:
                    return datetime.strptime(value, definition["format"]).date().isoformat()
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    return date.fromisoformat(value).isoformat()

        raise ValueError(f"Invalid value for type {field_type}.")
