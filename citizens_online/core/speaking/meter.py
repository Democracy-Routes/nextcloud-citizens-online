# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Speaking time, measured from audio activity.

Spec §12 is explicit: speaking time comes from the media, never from counting
transcript words. Each participant's browser sends its own microphone, so the
PCM that already flows to the transcriber is also the cleanest possible signal
of who is speaking — one stream, one person, no diarization.

The detector is a plain energy gate with hysteresis over 20 ms frames. It has
no dependencies, costs microseconds per frame, and keeps working when
transcription is switched off entirely.
"""

import array
import math
from dataclasses import dataclass, field

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2  # s16le mono

# Speech must clear the noise floor by this much (in dBFS) to count.
MARGIN_DB = 9.0
# An absolute floor, so a silent room cannot "adapt" its way into hearing speech.
ABSOLUTE_FLOOR_DB = -55.0
# Consecutive frames needed to open and to close the gate. Opening fast keeps
# turn starts accurate; closing slowly stops a breath mid-sentence from
# splitting one turn into three.
FRAMES_TO_OPEN = 3  # 60 ms
FRAMES_TO_CLOSE = 25  # 500 ms


def _dbfs(frame: bytes) -> float:
    if len(frame) < 2:
        return -120.0
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) // 2 * 2])
    if not samples:
        return -120.0
    total = 0
    for s in samples:
        total += s * s
    rms = math.sqrt(total / len(samples))
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(rms / 32768.0)


@dataclass
class SpeechMeter:
    """Accumulates speaking time for one participant's stream.

    Fed the same PCM the transcriber sees. `speaking_ms` and the turn counters
    are what the policy engine and the live dashboard read.
    """

    speaking_ms: int = 0
    turn_count: int = 0
    longest_turn_ms: int = 0
    current_turn_ms: int = 0
    last_spoke_offset_ms: int = 0
    offset_ms: int = 0
    speaking: bool = False

    _noise_db: float = -60.0
    _open_run: int = 0
    _close_run: int = 0
    _buffer: bytearray = field(default_factory=bytearray)

    def feed(self, pcm: bytes) -> None:
        """Consume 16 kHz mono s16le audio. Safe to call with any chunk size."""
        self._buffer.extend(pcm)
        while len(self._buffer) >= FRAME_BYTES:
            frame = bytes(self._buffer[:FRAME_BYTES])
            del self._buffer[:FRAME_BYTES]
            self._frame(frame)

    def _frame(self, frame: bytes) -> None:
        self.offset_ms += FRAME_MS
        level = _dbfs(frame)
        threshold = max(self._noise_db + MARGIN_DB, ABSOLUTE_FLOOR_DB)
        loud = level > threshold

        if loud:
            self._open_run += 1
            self._close_run = 0
        else:
            self._close_run += 1
            self._open_run = 0
            # adapt the noise floor only while quiet, and only downward quickly
            self._noise_db = min(self._noise_db * 0.98 + level * 0.02, level + 3.0)

        if not self.speaking and self._open_run >= FRAMES_TO_OPEN:
            self.speaking = True
            self.turn_count += 1
            # count the frames that opened the gate, they were speech too
            self.current_turn_ms = FRAMES_TO_OPEN * FRAME_MS
            self.speaking_ms += self.current_turn_ms
        elif self.speaking and self._close_run >= FRAMES_TO_CLOSE:
            self.speaking = False
            # the trailing silence that closed the gate was not speech
            self.current_turn_ms = max(0, self.current_turn_ms - FRAMES_TO_CLOSE * FRAME_MS)
            self.speaking_ms = max(0, self.speaking_ms - FRAMES_TO_CLOSE * FRAME_MS)
            self.longest_turn_ms = max(self.longest_turn_ms, self.current_turn_ms)
            self.current_turn_ms = 0
        elif self.speaking:
            self.current_turn_ms += FRAME_MS
            self.speaking_ms += FRAME_MS
            self.last_spoke_offset_ms = self.offset_ms

    def snapshot(self) -> dict:
        return {
            "speaking_ms": self.speaking_ms,
            "turn_count": self.turn_count,
            "longest_turn_ms": max(self.longest_turn_ms, self.current_turn_ms),
            "current_turn_ms": self.current_turn_ms if self.speaking else 0,
            "speaking": self.speaking,
            "offset_ms": self.offset_ms,
        }
