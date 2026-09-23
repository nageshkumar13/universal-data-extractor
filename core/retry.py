"""Pure policy for final HTTP statuses; transport retries belong to the adapter."""

from datetime import timezone
from email.utils import parsedate_to_datetime
import re


RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4  # Includes the initial request.
MAX_RETRIES = MAX_ATTEMPTS - 1


def backoff_delay(retry_number: int) -> float:
    """Retry 1 follows the first failed attempt; cap even beyond our budget."""
    if retry_number < 1:
        raise ValueError("retry_number must be at least 1")
    return float(2 ** (retry_number - 1)) if retry_number <= 5 else 30.0


def parse_retry_after(value: str | None, now: float) -> float | None:
    """Return nonnegative seconds, or None for a malformed header. No I/O."""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        # float also handles huge digit strings without Python's int digit limit.
        return float(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - now)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def status_retry_delay(
    status_code: int, attempt: int, retry_after: str | None, now: float,
) -> float | None:
    """Return a delay, or None to stop; never shorten a server's long wait."""
    if status_code not in RETRYABLE_STATUSES or attempt >= MAX_ATTEMPTS:
        return None
    backoff = backoff_delay(attempt)
    server_delay = parse_retry_after(retry_after, now)
    if server_delay is not None and server_delay > 60:
        return None
    return max(backoff, server_delay or 0.0)
