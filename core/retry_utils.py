"""Helpers for handling provider rate limits (HTTP 429).

Kept as small, pure functions so they can be unit tested without any network
access or provider SDK objects.
"""

from __future__ import annotations

import random
import re
from typing import Any, Optional

try:  # openai v1 exposes typed errors; fall back gracefully if absent.
    from openai import APIStatusError, RateLimitError
except Exception:  # pragma: no cover - openai is a hard dependency in practice
    APIStatusError = None  # type: ignore
    RateLimitError = None  # type: ignore

_RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
    "too many requests",
    "resource_exhausted",
    "429",
)

_RETRY_IN_RE = re.compile(r"retry in ([\d.]+)\s*s", re.IGNORECASE)
_RETRY_DELAY_RE = re.compile(r"retry_delay\s*\{[^}]*seconds:\s*([\d.]+)", re.IGNORECASE)


def error_status_code(exc: Any) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from an SDK exception."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    response_code = getattr(response, "status_code", None)
    if isinstance(response_code, int):
        return response_code
    return None


def is_rate_limit_error(exc: Any) -> bool:
    """Return True when *exc* represents a rate limit / quota exhaustion."""
    if RateLimitError is not None and isinstance(exc, RateLimitError):
        return True
    if error_status_code(exc) == 429:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


def retry_after_seconds(exc: Any) -> Optional[float]:
    """Parse a retry delay (seconds) from headers or the error message."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = None
        try:
            raw = headers.get("retry-after")
        except Exception:
            raw = None
        if raw is not None:
            try:
                return max(0.0, float(str(raw).strip()))
            except (TypeError, ValueError):
                pass

    message = str(exc)
    match = _RETRY_IN_RE.search(message) or _RETRY_DELAY_RE.search(message)
    if match:
        try:
            return max(0.0, float(match.group(1)))
        except (TypeError, ValueError):
            return None
    return None


def backoff_seconds(attempt: int, base: float = 1.0, cap: float = 30.0, jitter: bool = True) -> float:
    """Exponential backoff for the given 1-based attempt, with optional jitter."""
    exponent = max(0, attempt - 1)
    delay = min(cap, base * (2 ** exponent))
    if jitter:
        delay += random.uniform(0, delay * 0.25)
    return delay


def cooldown_seconds(exc: Any, attempt: int, minimum: float = 1.0, maximum: float = 300.0) -> float:
    """How long a key should be skipped after *exc*.

    Prefers the server-provided retry delay; otherwise falls back to exponential
    backoff. The result is clamped to ``[minimum, maximum]`` so a broken or
    missing value cannot cause an unbounded sleep or a tight retry loop.
    """
    parsed = retry_after_seconds(exc)
    if parsed is None:
        parsed = backoff_seconds(attempt, base=minimum, cap=maximum)
    return max(minimum, min(maximum, parsed))
