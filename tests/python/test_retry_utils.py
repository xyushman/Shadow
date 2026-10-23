"""Unit tests for provider retry/backoff helpers (no network).

Run from project root:  python -m unittest tests.python.test_retry_utils -v
"""

import unittest

from core import retry_utils


class FakeResponse:
    def __init__(self, status_code=429, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeRateLimitError(Exception):
    def __init__(self, message="", response=None, status_code=None):
        super().__init__(message)
        self.response = response
        if status_code is not None:
            self.status_code = status_code


class RetryUtilsTests(unittest.TestCase):
    def test_is_rate_limit_error_by_status_code(self):
        exc = FakeRateLimitError("bad request", response=FakeResponse(429))
        self.assertTrue(retry_utils.is_rate_limit_error(exc))

    def test_is_rate_limit_error_by_message(self):
        exc = Exception("Error: rate limit exceeded")
        self.assertTrue(retry_utils.is_rate_limit_error(exc))

    def test_is_rate_limit_error_by_quota(self):
        exc = Exception("RESOURCE_EXHAUSTED: quota reached")
        self.assertTrue(retry_utils.is_rate_limit_error(exc))

    def test_not_rate_limit_error(self):
        exc = Exception("Connection timeout")
        self.assertFalse(retry_utils.is_rate_limit_error(exc))

    def test_retry_after_from_header(self):
        exc = FakeRateLimitError("rl", response=FakeResponse(429, headers={"retry-after": "12.5"}))
        self.assertAlmostEqual(retry_utils.retry_after_seconds(exc), 12.5)

    def test_retry_after_from_message_retry_in(self):
        exc = Exception("Please retry in 7.25s.")
        self.assertAlmostEqual(retry_utils.retry_after_seconds(exc), 7.25)

    def test_retry_after_from_message_retry_delay(self):
        exc = Exception("retry_delay { seconds: 9 }")
        self.assertAlmostEqual(retry_utils.retry_after_seconds(exc), 9.0)

    def test_backoff_increases(self):
        d1 = retry_utils.backoff_seconds(1, base=1.0, cap=30.0, jitter=False)
        d2 = retry_utils.backoff_seconds(2, base=1.0, cap=30.0, jitter=False)
        d3 = retry_utils.backoff_seconds(3, base=1.0, cap=30.0, jitter=False)
        self.assertEqual(d1, 1.0)
        self.assertEqual(d2, 2.0)
        self.assertEqual(d3, 4.0)

    def test_backoff_capped(self):
        d = retry_utils.backoff_seconds(10, base=1.0, cap=5.0, jitter=False)
        self.assertEqual(d, 5.0)

    def test_cooldown_uses_retry_after_and_clamps(self):
        exc = FakeRateLimitError("rl", response=FakeResponse(429, headers={"retry-after": "15"}))
        self.assertEqual(retry_utils.cooldown_seconds(exc, 1, minimum=1.0, maximum=300.0), 15.0)

    def test_cooldown_min_clamp(self):
        exc = Exception("other error")
        self.assertGreaterEqual(retry_utils.cooldown_seconds(exc, 1, minimum=5.0, maximum=60.0), 5.0)


if __name__ == "__main__":
    unittest.main()
