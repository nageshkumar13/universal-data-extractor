from copy import deepcopy

import pytest

from core.retry import (
    MAX_ATTEMPTS, MAX_RETRIES, RETRYABLE_STATUSES, backoff_delay,
    parse_retry_after, status_retry_delay,
)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_has_three_retries_after_first_attempt(status):
    assert MAX_ATTEMPTS == 4
    assert MAX_RETRIES == 3
    assert status in RETRYABLE_STATUSES
    assert [status_retry_delay(status, attempt, None, 0) for attempt in range(1, 5)] == [1, 2, 4, None]


@pytest.mark.parametrize("status", [200, 299, 301, 302, 307, 308, 304, 400, 401, 403, 404, 408, 409, 413, 425, 501, 505])
def test_other_statuses_never_retry_even_with_retry_after(status):
    assert status_retry_delay(status, 1, "60", 0) is None


def test_backoff_is_capped_even_beyond_attempt_budget():
    assert [backoff_delay(n) for n in range(1, 9)] == [1, 2, 4, 8, 16, 30, 30, 30]
    assert backoff_delay(100000) == 30
    with pytest.raises(ValueError):
        backoff_delay(0)


@pytest.mark.parametrize("header, attempt, expected", [
    (None, 1, 1), ("10", 1, 10), (" 12 ", 2, 12), ("1", 3, 4),
    ("60", 1, 60), ("61", 1, None), ("9" * 5000, 1, None),
    ("garbage", 2, 2), ("-2", 2, 2), ("1.5", 2, 2), ("", 2, 2),
    ("0", 3, 4), ("Thu, 01 Jan 1970 00:00:00 GMT", 3, 4),
    ("Thu, 01 Jan 1970 00:01:00 GMT", 1, 60),
    ("Thu, 01 Jan 1970 00:01:01 GMT", 1, None),
    ("Thu, 01 Jan 1970 00:00:10 GMT", 1, 10),
])
def test_retry_after_rules_are_pure_and_deterministic(header, attempt, expected):
    inputs = {"status_code": 503, "attempt": attempt, "retry_after": header, "now": 0}
    before = deepcopy(inputs)
    assert status_retry_delay(**inputs) == expected
    assert status_retry_delay(**inputs) == expected
    assert inputs == before


def test_http_date_uses_supplied_wall_clock():
    assert parse_retry_after("Thu, 01 Jan 1970 00:01:00 GMT", now=55) == 5
    assert parse_retry_after("Thu, 01 Jan 1970 00:01:00 GMT", now=61) == 0
    assert status_retry_delay(429, 4, "60", 0) is None


@pytest.mark.parametrize("header", ["Thu, 01 Jan 1970 00:01:00 GMT", "Thu, 01 Jan 1970 05:31:00 +0530"])
def test_http_date_timezone_and_gmt_describe_the_same_instant(header):
    assert parse_retry_after(header, now=50) == 10
    assert status_retry_delay(503, 2, header, now=50) == 10
    assert status_retry_delay(503, 2, header, now=59) == 2
