"""Audio mixer and diarized transcript regression tests (no devices/network)."""

import asyncio
import sys
import threading
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

from api.session_manager import InterviewSession
from services.audio_capture import NativeAudioCapture


class AudioMixerTests(unittest.TestCase):
    def _capture(self):
        cap = NativeAudioCapture.__new__(NativeAudioCapture)
        cap._lock = threading.Lock()
        return cap

    def test_pop_consumes_partial_chunks(self):
        cap = self._capture()
        buf = [np.arange(1024, dtype=np.float32)]

        first = cap._pop(buf, 480)
        self.assertEqual(first.size, 480)
        self.assertEqual(buf[0].size, 544)

        second = cap._pop(buf, 480)
        self.assertEqual(second.size, 480)
        self.assertEqual(buf[0].size, 64)
        self.assertTrue(np.array_equal(first[:64], second[:64]) is False)

    def test_pop_returns_available_samples_when_buffer_is_small(self):
        cap = self._capture()
        buf = [np.ones(100, dtype=np.float32)]

        out = cap._pop(buf, 480)
        self.assertEqual(out.size, 100)
        self.assertEqual(buf, [])


class TranscriptRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_voice_is_interviewer_second_is_candidate(self):
        session = InterviewSession("test-transcript")
        messages = []

        async def capture(_type, payload):
            messages.append((_type, payload))

        session._send_json = capture
        session.state["auto_mode_enabled"] = False

        await session.on_transcript({
            "speaker": 7, "transcript": "What is two sum?", "is_final": True,
        })
        await session.on_transcript({
            "speaker": 3, "transcript": "Use a hash map.", "is_final": True,
        })

        roles = [payload.get("role") for _type, payload in messages]
        self.assertEqual(roles, ["interviewer", "candidate"])
        self.assertEqual(session._role_for_speaker(7), "interviewer")
        self.assertEqual(session._role_for_speaker(3), "candidate")

    async def test_only_interviewer_speech_is_buffered(self):
        session = InterviewSession("test-buffer")
        session.state["auto_mode_enabled"] = False

        async def noop(_type, payload):
            return None

        session._send_json = noop
        await session.on_transcript({
            "speaker": 0, "transcript": "Explain REST.", "is_final": True,
        })
        await session.on_transcript({
            "speaker": 1, "transcript": "It is a style.", "is_final": True,
        })

        self.assertEqual(session.transcript_buffer, "")


if __name__ == "__main__":
    unittest.main()
