"""Tests for production-friendly startup configuration checks (no network)."""

import sys
import unittest
from unittest import mock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core import config as config_module


class ProductionConfigTests(unittest.TestCase):
    def test_placeholder_deepgram_key_is_reported(self):
        with mock.patch.object(config_module.settings, "DEEPGRAM_API_KEY",
                               "your_deepgram_api_key_here"):
            issues = config_module.config_issues()
        self.assertTrue(any("DEEPGRAM_API_KEY" in i for i in issues))

    def test_missing_deepgram_key_is_reported(self):
        with mock.patch.object(config_module.settings, "DEEPGRAM_API_KEY", ""):
            issues = config_module.config_issues()
        self.assertTrue(any("DEEPGRAM_API_KEY" in i for i in issues))

    def test_valid_deepgram_key_is_not_reported(self):
        with mock.patch.object(config_module.settings, "DEEPGRAM_API_KEY", "real-key-123"):
            issues = config_module.config_issues()
        self.assertFalse(any("DEEPGRAM_API_KEY" in i for i in issues))

    def test_missing_providers_file_is_reported(self):
        with mock.patch.object(config_module, "Path") as path_cls:
            path_cls.return_value.exists.return_value = False
            issues = config_module.config_issues()
        self.assertTrue(any("ai_providers.json" in i for i in issues))

    def test_startup_diagnostics_never_crashes(self):
        # Should simply print findings, whether or not there are issues.
        with mock.patch.object(config_module, "config_issues", return_value=[]):
            config_module.print_startup_diagnostics()
        with mock.patch.object(config_module, "config_issues",
                               return_value=["example issue"]):
            config_module.print_startup_diagnostics()


if __name__ == "__main__":
    unittest.main()
