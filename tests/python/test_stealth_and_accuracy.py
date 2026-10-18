"""Unit tests for stealth helpers (pure logic, no GUI is created).

Run from the project root:  python -m unittest discover -s tests/python -v
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# The codebase prints emoji liberally; some consoles default to cp1252 and
# raise UnicodeEncodeError mid-print. Tests should not depend on the console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class PeekSecondsTests(unittest.TestCase):
    """STEALTH_PEEK_SECONDS parsing — Alt+Z peek auto-hide window."""

    def setUp(self):
        import window_manager
        self.wm = window_manager
        self._saved_env = os.environ.get("STEALTH_PEEK_SECONDS")
        self._saved_file = window_manager._ENV_FILE_VALUES.pop("STEALTH_PEEK_SECONDS", None)

    def tearDown(self):
        import window_manager
        if self._saved_env is None:
            os.environ.pop("STEALTH_PEEK_SECONDS", None)
        else:
            os.environ["STEALTH_PEEK_SECONDS"] = self._saved_env
        if self._saved_file is not None:
            window_manager._ENV_FILE_VALUES["STEALTH_PEEK_SECONDS"] = self._saved_file

    def test_default_is_10_seconds(self):
        os.environ.pop("STEALTH_PEEK_SECONDS", None)
        self.assertEqual(self.wm.get_peek_seconds(), 10.0)

    def test_env_override(self):
        os.environ["STEALTH_PEEK_SECONDS"] = "3.5"
        self.assertEqual(self.wm.get_peek_seconds(), 3.5)

    def test_zero_disables_auto_hide(self):
        os.environ["STEALTH_PEEK_SECONDS"] = "0"
        self.assertEqual(self.wm.get_peek_seconds(), 0.0)

    def test_malformed_falls_back_to_default(self):
        os.environ["STEALTH_PEEK_SECONDS"] = "not-a-number"
        self.assertEqual(self.wm.get_peek_seconds(), 10.0)

    def test_negative_clamped_to_zero(self):
        os.environ["STEALTH_PEEK_SECONDS"] = "-5"
        self.assertEqual(self.wm.get_peek_seconds(), 0.0)


class ScreenshotDedupeTests(unittest.TestCase):
    """dedupe_screenshots — identical frames must only be analysed once."""

    def test_drops_exact_duplicates_preserving_order(self):
        from services.vision_service import dedupe_screenshots
        shots = ["a", "b", "a", "c", "b"]
        self.assertEqual(dedupe_screenshots(shots), ["a", "b", "c"])

    def test_empty_input(self):
        from services.vision_service import dedupe_screenshots
        self.assertEqual(dedupe_screenshots([]), [])

    def test_distinct_payloads_kept(self):
        from services.vision_service import dedupe_screenshots
        shots = ["data:image/jpeg;base64,AAA", "data:image/jpeg;base64,AAB"]
        self.assertEqual(len(dedupe_screenshots(shots)), 2)


class AnswerFeedbackTests(unittest.TestCase):
    """Ground-truth loop — Alt+G/Alt+B notes flow into the prompt context."""

    def setUp(self):
        from services.context_manager import PersistentContextManager
        self.ctx = PersistentContextManager()

    def test_good_note_recorded(self):
        self.ctx.add_answer_feedback("good", "I led the migration")
        self.assertEqual(len(self.ctx.feedback_notes), 1)
        self.assertIn("GOOD", self.ctx.feedback_notes[0])
        self.assertIn("I led the migration", self.ctx.feedback_notes[0])

    def test_bad_note_recorded(self):
        self.ctx.add_answer_feedback("bad", "")
        self.assertIn("MISSED", self.ctx.feedback_notes[0])

    def test_notes_capped_at_five(self):
        for i in range(8):
            self.ctx.add_answer_feedback("bad", f"answer {i}")
        self.assertEqual(len(self.ctx.feedback_notes), 5)
        self.assertIn("answer 7", self.ctx.feedback_notes[-1])
        self.assertNotIn("answer 2", self.ctx.feedback_notes[0])

    def test_feedback_exposed_in_complete_context(self):
        self.ctx.add_answer_feedback("bad", "x")
        context = self.ctx.get_complete_context()
        self.assertIn("feedback_notes", context)
        self.assertEqual(len(context["feedback_notes"]), 1)


class OwnWindowLookupTests(unittest.TestCase):
    """PID-filtered window resolution must never return another process's window."""

    def test_bogus_title_returns_none(self):
        import window_manager
        self.assertIsNone(window_manager._find_own_window("___no_such_window_title___"))

    def test_owned_window_not_yet_created_returns_none(self):
        import window_manager
        self.assertIsNone(window_manager._find_own_window("Shadow"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
