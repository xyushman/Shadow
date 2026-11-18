"""Regression tests for response latency and friendly vision failures.

Run from project root: python -m unittest tests.python.test_latency_budgets -v
"""

import asyncio
import sys
import time
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.prompts import get_interview_answer_prompt
from services.vision_service import VisionService


class FakeContext:
    def __init__(self, history):
        self.history = history

    def ensure_context_available(self):
        return True

    def get_complete_context(self):
        return {
            'persistent': {'candidate_name': 'Test Candidate'},
            'conversation_history': self.history,
            'feedback_notes': [],
        }


class LatencyBudgetTests(unittest.TestCase):
    def test_history_answers_are_truncated(self):
        history = [{
            'interviewer_question': 'Explain REST',
            'candidate_response': 'It is an architectural style.',
            'ai_response': 'A' * 5000,
        }, {
            'interviewer_question': 'What does this code do?',
            'candidate_response': None,
            'ai_response': '[VISION ANALYSIS] ' + 'B' * 5000,
        }]

        prompt = get_interview_answer_prompt('Next question?', FakeContext(history))

        self.assertLess(len(prompt), 4000)
        self.assertEqual(prompt.count('[truncated]'), 2)
        self.assertIn('A' * 200, prompt)
        self.assertIn('[VISION ANALYSIS]', prompt)

    def test_compact_vision_prompt_is_small(self):
        prompt = VisionService().generate_coding_analysis_prompt(['Python', 'SQL'])

        self.assertLess(len(prompt), 1500)
        self.assertIn('Python', prompt)
        self.assertIn('MCQ', prompt)

    def test_expired_deadline_fails_fast_without_calling_provider(self):
        service = VisionService()

        def fail_if_called(*args, **kwargs):
            self.fail('provider should not be called after the deadline')

        service._vision_candidates = lambda *args, **kwargs: [('Gemini', 'gemini-3.8-flash')]
        service.get_vision_manager = fail_if_called

        analysis, info = asyncio.run(service.analyze_coding_problem(
            'Gemini', 'gemini-3.8-flash', ['data:image/jpeg;base64,abc'],
            deadline=time.monotonic() - 1,
        ))

        self.assertFalse(info['success'])
        self.assertEqual(info['error'], 'timeout')
        self.assertIn('timed out', analysis)

    def test_rate_limited_vision_gets_actionable_message(self):
        class FakeManager:
            provider_name = 'Gemini'
            model_name = 'gemini-3.8-flash'

            def has_available_key(self):
                return True

            async def analyze_screenshots(self, *args, **kwargs):
                return 'rate limited', {'success': False, 'rate_limited': True}

        service = VisionService()
        service._vision_candidates = lambda *args, **kwargs: [('Gemini', 'gemini-3.8-flash')]
        service.get_vision_manager = lambda *args, **kwargs: FakeManager()

        analysis, info = asyncio.run(service.analyze_coding_problem(
            'Gemini', 'gemini-3.8-flash', ['data:image/jpeg;base64,abc']
        ))

        self.assertFalse(info['success'])
        self.assertEqual(info['error'], 'rate_limited')
        self.assertIn('rate limited', analysis)


if __name__ == '__main__':
    unittest.main()
