"""Native Windows audio capture.

Replaces the browser's getUserMedia + getDisplayMedia capture path with a
pure-backend pipeline:

  * microphone   -> default WASAPI input device
  * system audio -> default WASAPI loopback device (renders what the machine
                    is playing, with no capture flag, no picker and no
                    permission prompt)

Both sources are downmixed to mono, resampled to 48 kHz, mixed with the same
`* 0.7` attenuation the AudioWorklet used, batched to 1024 samples (~21.3 ms)
and handed straight to the Deepgram manager. Because nothing crosses the
browser media pipeline any longer, the interview runs with zero permission
prompts and without Chrome's "sharing your screen" badge.
"""

import asyncio
import threading
import time

import numpy as np

try:
    import pyaudiowpatch as _pyaudio
except Exception:  # pragma: no cover - optional dependency
    _pyaudio = None

TARGET_RATE = 48000
BATCH_SAMPLES = 1024
MIX_GAIN = 0.7
TICK_SECONDS = 0.01
ZERO = np.zeros(0, dtype=np.float32)


def probe_native_audio():
    """Reports whether native (prompt-free) capture is possible."""
    if _pyaudio is None:
        return {"available": False, "reason": "pyaudiowpatch not installed"}
    pa = _pyaudio.PyAudio()
    try:
        try:
            pa.get_default_wasapi_loopback()
        except Exception:
            return {
                "available": False,
                "reason": "No WASAPI loopback device (no output device)",
            }
        try:
            pa.get_default_input_device_info()
        except Exception:
            return {"available": False, "reason": "No microphone device"}
        return {"available": True, "reason": "native loopback audio ready"}
    finally:
        pa.terminate()


class _LinearResampler:
    """Stateful linear-interpolation resampler.

    Keeps its buffer and fractional read position across calls so chunk
    boundaries never introduce a discontinuity. Buffers are hard-capped so a
    stalled consumer cannot grow memory without limit (live streaming, so the
    audio is worthless once it is late anyway).
    """

    MAX_BUFFER = 8192

    def __init__(self, src_rate, dst_rate=TARGET_RATE):
        self.ratio = 1.0 if src_rate == dst_rate else src_rate / float(dst_rate)
        self.pos = 0.0
        self.buf = ZERO
        self.dropped = False

    def process(self, chunk):
        if chunk.size == 0:
            return ZERO
        if self.ratio == 1.0:
            return chunk
        self.buf = chunk if self.buf.size == 0 else np.concatenate([self.buf, chunk])
        if self.buf.size > self.MAX_BUFFER:
            # Pathological drift (device stopped but callbacks continue):
            # reset rather than queue stale audio forever.
            self.buf = self.buf[-4096:]
            self.pos = 0.0
            self.dropped = True
            return ZERO
        if self.pos + 1 >= self.buf.size:
            return ZERO
        n_out = int((self.buf.size - 1 - self.pos) // self.ratio) + 1
        idx = self.pos + np.arange(n_out, dtype=np.float64) * self.ratio
        i0 = idx.astype(np.intp)
        frac = idx - i0
        out = (self.buf[i0] * (1.0 - frac) + self.buf[i0 + 1] * frac).astype(np.float32)
        self.pos += n_out * self.ratio
        drop = int(self.pos)
        if drop > 0:
            self.buf = self.buf[drop:]
            self.pos -= drop
        return out


class NativeAudioCapture:
    """Captures mic + system audio natively and streams it to ``send_audio``."""

    def __init__(self, send_audio, get_state, loop=None, on_error=None):
        self.send_audio = send_audio
        self.get_state = get_state
        self.loop = loop
        self.on_error = on_error
        self._running = False
        self._threads = []
        self._streams = []
        self._pa = None
        self._lock = threading.Lock()
        self._mic_buf = []
        self._sys_buf = []
        self.chunks_sent = 0
        self.last_error = None

    # --- lifecycle -------------------------------------------------------

    def start(self, mic_index=None):
        if _pyaudio is None:
            raise RuntimeError("pyaudiowpatch is not installed")
        if self._running:
            return
        self._running = True
        self._pa = _pyaudio.PyAudio()
        try:
            self._open_source("mic", mic_index)
            self._open_source("system", None)
        except Exception:
            self.stop()
            raise
        # One mixer thread handles both sources. Two independent threads would
        # send mic and loopback as separate Deepgram streams instead of mixing
        # the interviewer and candidate into one diarized conversation.
        t = threading.Thread(
            target=self._mixer_loop, daemon=True, name="nyx-audio-mixer",
        )
        t.start()
        self._threads.append(t)
        print("Native audio capture started (no browser permission required).")

    def stop(self):
        if not self._running and self._pa is None:
            return
        self._running = False
        for s in list(self._streams):
            try:
                if hasattr(s, 'stop_stream'):
                    s.stop_stream()
                elif hasattr(s, 'stop'):
                    s.stop()
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
        self._streams.clear()
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        for t in self._threads:
            t.join(timeout=1.5)
        self._threads.clear()
        with self._lock:
            self._mic_buf.clear()
            self._sys_buf.clear()
        print(f"Native audio capture stopped ({self.chunks_sent} chunks sent).")

    # --- device / stream setup ------------------------------------------

    def _open_source(self, kind, mic_index):
        pa = self._pa
        if kind == "mic":
            if mic_index is not None:
                try:
                    info = pa.get_device_info_by_index(int(mic_index))
                    if info.get("maxInputChannels", 0) <= 0 or info.get("isLoopbackDevice"):
                        raise ValueError("not an input device")
                except Exception:
                    info = pa.get_default_input_device_info()
            else:
                info = pa.get_default_input_device_info()
            label = info.get("name", "microphone")
        else:
            info = pa.get_default_wasapi_loopback()
            label = info.get("name", "system audio (loopback)")

        channels = max(1, int(info.get("maxInputChannels", 1)))
        rate = int(round(info.get("defaultSampleRate", TARGET_RATE))) or TARGET_RATE
        dev_index = int(info["index"])

        buffer = self._mic_buf if kind == "mic" else self._sys_buf
        resampler = _LinearResampler(rate)
        first = threading.Event()
        first.set()

        def callback(data, frame_count, time_info, status):
            try:
                arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            except Exception:
                return (b"", _pyaudio.paContinue)
            if arr.size:
                if channels > 1:
                    arr = arr[: (arr.size // channels) * channels].reshape(-1, channels).mean(axis=1)
                arr = resampler.process(arr.astype(np.float32))
                if arr.size:
                    with self._lock:
                        buffer.append(arr)
            return (b"", _pyaudio.paContinue)

        stream = self._pa.open(
            format=_pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=dev_index,
            frames_per_buffer=1024,
            stream_callback=callback,
        )
        if hasattr(stream, 'start_stream'):
            stream.start_stream()
        elif hasattr(stream, 'start'):
            stream.start()
        else:
            raise AttributeError("Stream has no start/start_stream")
        self._streams.append(stream)
        print(f"  - {kind}: {label} @ {rate}Hz ({channels}ch -> mono @ {TARGET_RATE}Hz)")

    # --- mixing ----------------------------------------------------------

    def _pop(self, buf, want):
        """Take up to ``want`` samples from the front of ``buf``.

        The previous implementation returned silence whenever the first queued
        callback chunk was larger than the tick size (1024 > 480), so no audio
        ever reached Deepgram. Consume partial chunks instead.
        """
        if want <= 0:
            return ZERO
        with self._lock:
            out = ZERO
            while out.size < want and buf:
                chunk = buf[0]
                take = min(want - out.size, chunk.size)
                piece = chunk[:take]
                out = piece.copy() if out.size == 0 else np.concatenate([out, piece])
                if take >= chunk.size:
                    buf.pop(0)
                else:
                    buf[0] = chunk[take:]
            return out

    def _mixer_loop(self):
        rate = int(TICK_SECONDS * TARGET_RATE)
        acc = ZERO
        while self._running:
            time.sleep(TICK_SECONDS)
            mic = self._pop(self._mic_buf, rate)
            system = self._pop(self._sys_buf, rate)
            if mic.size < rate:
                mic = np.concatenate([mic, np.zeros(rate - mic.size, dtype=np.float32)])
            if system.size < rate:
                system = np.concatenate([system, np.zeros(rate - system.size, dtype=np.float32)])

            state = {}
            if self.get_state is not None:
                try:
                    state = self.get_state() or {}
                except Exception:
                    state = {}
            # Muting the microphone must not mute the interviewer's loopback.
            if state.get("is_muted"):
                mic = ZERO

            mixed = mic + system
            acc = mixed if acc.size == 0 else np.concatenate([acc, mixed])
            while acc.size >= BATCH_SAMPLES:
                self._emit(acc[:BATCH_SAMPLES])
                acc = acc[BATCH_SAMPLES:]

    def _emit(self, samples):
        if not self._running:
            return
        state = {}
        if self.get_state is not None:
            try:
                state = self.get_state() or {}
            except Exception:
                state = {}
        if state.get("is_universally_muted"):
            return
        mixed = np.clip(samples * MIX_GAIN, -1.0, 1.0)
        pcm = (mixed * 0x7FFF).astype(np.int16)
        payload = pcm.tobytes()
        if self.loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.send_audio(payload), self.loop)
            fut.add_done_callback(self._on_sent)
            self.chunks_sent += 1
        except Exception as exc:
            self.last_error = exc

    def _on_sent(self, fut):
        try:
            exc = fut.exception()
        except Exception:
            return
        if exc is not None and self.on_error is not None:
            try:
                self.on_error(exc)
            except Exception:
                pass
