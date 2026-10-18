"""Unit tests for answer modes / text answers (no network, no GUI).

Run from the project root:  python -m unittest discover -s tests/python -v
"""
import asyncio
import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class FakeWebSocket:
    class _State:
        name = "CONNECTED"

    def __init__(self):
        self.client_state = FakeWebSocket._State()
        self.messages = []

    async def send_text(self, text):
        self.messages.append(json.loads(text))

    def types(self):
        return [m["type"] for m in self.messages]

    def payload_for(self, msg_type):
        for m in self.messages:
            if m["type"] == msg_type:
                return m["payload"]
        return None


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def get_ai_answer(self, question, stream_callback=None, response_style=None):
        self.calls.append({"question": question, "response_style": response_style})
        if stream_callback:
            await stream_callback("hello ", "text")
            await stream_callback("world", "text")
        return "hello world", {"preset": {"model": "fake-model"}}

    async def switch_preset(self, preset_key):
        return True, {"current_preset": {"key": preset_key}}


def make_session(session_id="test-session"):
    from api.session_manager import InterviewSession

    session = InterviewSession(session_id)
    ws = FakeWebSocket()
    session.websocket = ws
    session.llm_manager = FakeLLM()
    return session, ws


class AskTextTests(unittest.TestCase):
    def test_ask_text_answers_with_text_source(self):
        session, ws = make_session("s1")

        asyncio.run(session.handle_ask_text({"text": "  Reverse a linked list  "}))

        self.assertIn("ai_processing_started", ws.types())
        started = ws.payload_for("ai_processing_started")
        self.assertEqual(started["source"], "text")
        self.assertEqual(started["question"], "Reverse a linked list")

        complete = ws.payload_for("ai_answer_complete")
        self.assertEqual(complete["answer"], "hello world")
        self.assertEqual(complete["source"], "text")
        self.assertEqual(complete["question"], "Reverse a linked list")
        self.assertEqual(session.last_question, "Reverse a linked list")

    def test_empty_text_is_rejected(self):
        session, ws = make_session("s2")

        asyncio.run(session.handle_ask_text({"text": "   "}))

        self.assertIn("error", ws.types())
        self.assertNotIn("ai_processing_started", ws.types())

    def test_response_style_is_forwarded(self):
        session, ws = make_session("s3")
        session.state["response_mode"] = "concise"

        asyncio.run(session.handle_ask_text({"text": "What is a closure?"}))

        self.assertEqual(session.llm_manager.calls[0]["response_style"], "concise")


class RegenerateTests(unittest.TestCase):
    def test_regenerate_reuses_last_question(self):
        session, ws = make_session("r")
        asyncio.run(session.handle_ask_text({"text": "What is a closure?"}))
        ws.messages.clear()

        asyncio.run(session.handle_regenerate({}))

        complete = ws.payload_for("ai_answer_complete")
        self.assertEqual(complete["source"], "regenerate")
        self.assertEqual(complete["question"], "What is a closure?")

    def test_regenerate_can_switch_preset(self):
        session, ws = make_session("r2")
        session.state["last"] = None
        asyncio.run(session.handle_regenerate({"question": "Q?", "preset_key": "gemini"}))

        self.assertIn("preset_switched", ws.types())
        complete = ws.payload_for("ai_answer_complete")
        self.assertEqual(complete["source"], "regenerate")


class AutoModeTests(unittest.TestCase):
    def test_transcript_skipped_when_auto_disabled(self):
        session, ws = make_session("a")
        session.state["auto_mode_enabled"] = False
        session.transcript_buffer = "Explain REST."

        asyncio.run(session._process_aggregated_transcript())

        self.assertEqual(ws.types(), [])
        self.assertEqual(session.last_question, "Explain REST.")

    def test_transcript_answered_when_auto_enabled(self):
        session, ws = make_session("a2")
        session.state["auto_mode_enabled"] = True
        session.transcript_buffer = "Explain REST."

        asyncio.run(session._process_aggregated_transcript())

        self.assertIn("ai_answer_complete", ws.types())
        self.assertEqual(ws.payload_for("ai_answer_complete")["source"], "voice")


class ConfigUpdateTests(unittest.TestCase):
    def test_config_update_applies_modes(self):
        session, ws = make_session("c")
        # no llm/websocket init needed for config
        asyncio.run(session.handle_config_update({
            "responseMode": "concise",
            "autoModeEnabled": False,
            "answerMode": "manual",
            "isMicMuted": True,
        }))

        self.assertEqual(session.state["response_mode"], "concise")
        self.assertFalse(session.state["auto_mode_enabled"])
        self.assertEqual(session.state["answer_mode"], "manual")
        self.assertTrue(session.state["is_muted"])
        self.assertEqual(ws.payload_for("config_updated")["response_mode"], "concise")


class FakeContextManager:
    def get_complete_context(self):
        return {"persistent": {}, "conversation_history": []}


class ResponseStylePromptTests(unittest.TestCase):
    def test_concise_directive_injected(self):
        from core.prompts import get_interview_answer_prompt, RESPONSE_STYLE_DIRECTIVES

        concise = get_interview_answer_prompt("Q", FakeContextManager(), response_style="concise")
        detailed = get_interview_answer_prompt("Q", FakeContextManager(), response_style="detailed")

        self.assertIn(RESPONSE_STYLE_DIRECTIVES["concise"][:20], concise)
        self.assertNotIn(RESPONSE_STYLE_DIRECTIVES["concise"][:20], detailed)
        self.assertIn(RESPONSE_STYLE_DIRECTIVES["detailed"][:20], detailed)

    def test_no_style_directive_when_unspecified(self):
        from core.prompts import get_interview_answer_prompt, RESPONSE_STYLE_DIRECTIVES

        prompt = get_interview_answer_prompt("Q", FakeContextManager())
        self.assertNotIn(RESPONSE_STYLE_DIRECTIVES["concise"][:20], prompt)
        self.assertNotIn(RESPONSE_STYLE_DIRECTIVES["detailed"][:20], prompt)


if __name__ == "__main__":
    unittest.main()
