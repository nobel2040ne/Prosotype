"""Pluggable ASR backends that all return the same timed-word shape.

Admission requirement is per-word `start`/`end`, not text -- every expressive
path here keys off word spans. That is why OpenAI's streaming models are absent:
their transcript payloads carry no timing field.

Each cloud backend splits into a PURE message parser (unit-tested offline against
recorded frames) and a thin socket layer (NOT covered by the offline suite).
Treat the cloud arms as unverified against the live APIs until someone runs them
with real keys.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR = 16_000


@dataclass
class TimedWord:
    """One recognized word with its acoustic span, in seconds."""

    text: str
    start: float
    end: float
    speaker: str | None = None


@dataclass
class Transcript:
    words: list[TimedWord] = field(default_factory=list)
    # Wall-clock seconds the backend took; for cloud arms this includes the
    # network round trip, which is the honest number for a live booth.
    elapsed_s: float = 0.0
    error: str = ""

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words).strip()


def collapse_revisions(events: list[dict]) -> list[TimedWord]:
    """Reduce SSE word events to one entry per semantic word.

    A word is re-emitted under the SAME `word_id` when endpoint text or later
    speaker evidence revises it -- that is the in-place correction contract, not
    a new word. Taking every `type: "word"` event duplicated whole phrases once
    diarization was enabled: sample.mp4 went 59 -> 64 words with "You know where
    1640 River?" appearing twice. Keep the LAST revision per id (most
    authoritative) in first-appearance order.
    """

    latest: dict[str, dict] = {}
    for index, event in enumerate(events):
        if event.get("type") != "word" or not event.get("text"):
            continue
        # An event with no id cannot be a revision of anything, so it keeps a
        # position-unique key rather than collapsing with its neighbours.
        key = str(event.get("word_id") or f"§anonymous-{index}")
        order = latest[key]["_order"] if key in latest else index
        latest[key] = {**event, "_order": order}

    return [
        TimedWord(
            text=str(event.get("text", "")),
            start=float(event.get("start", 0.0)),
            end=float(event.get("end", 0.0)),
            speaker=event.get("speaker"),
        )
        for event in sorted(latest.values(), key=lambda event: event["_order"])
    ]


# ---------------------------------------------------------------------------
# Local sherpa streaming (the incumbent)
# ---------------------------------------------------------------------------


class LocalBackend:
    """The shipped offline pipeline, driven exactly as live mode drives it."""

    name = "local"

    def __init__(self, cfg: dict, language: str = "en", diarize: bool = True):
        from autocwi.live import (
            _configure_live_language,
            load_endpoint_verifier,
            load_speaker_tracker,
            load_streaming_recognizer,
        )

        # The language overlay is not cosmetic: it swaps `streaming_model_dir`
        # to the Korean Zipformer and turns off the draft and verifier lanes,
        # which are English sidecars. Setting `live.lang` alone loads the
        # ENGLISH models and transcribes Korean as English nonsense.
        self.cfg = cfg = _configure_live_language(cfg, language)
        live_cfg = cfg["live"]
        self.accurate = load_streaming_recognizer(cfg)
        self.draft = (
            load_streaming_recognizer(cfg, live_cfg["draft_model_dir"])
            if live_cfg.get("draft_enabled", True) else None
        )
        self.verifier = (
            load_endpoint_verifier(cfg)
            if live_cfg.get("verifier_enabled", True) else None
        )
        # Without this the local arm reports one speaker while Speechmatics and
        # Soniox both return diarized words, which reads as a local regression
        # when it is really a missing component.
        self.speaker_tracker = load_speaker_tracker(cfg) if diarize else None

    def transcribe(self, audio: np.ndarray, sample_rate: int = SR) -> Transcript:
        import time

        from autocwi.live import (
            BLOCK,
            AudioChunk,
            DualStreamingCaptioner,
            InputGain,
        )

        captioner = DualStreamingCaptioner(
            self.draft, self.accurate, self.cfg, verifier=self.verifier,
            speaker_tracker=self.speaker_tracker,
        )
        gain = InputGain(self.cfg)
        started = time.perf_counter()
        events = []
        try:
            for offset in range(0, len(audio), BLOCK):
                chunk = gain.process(
                    AudioChunk(audio[offset:offset + BLOCK], offset / sample_rate)
                )
                events.extend(captioner.accept(chunk))
            events.extend(captioner.finish())
        finally:
            captioner.close()
        elapsed = time.perf_counter() - started

        return Transcript(words=collapse_revisions(events), elapsed_s=elapsed)


# ---------------------------------------------------------------------------
# Pure parsers -- the tested core of the cloud arms
# ---------------------------------------------------------------------------


def parse_speechmatics(messages: list[dict]) -> list[TimedWord]:
    """Collect words from Speechmatics `AddTranscript` messages.

    Only final `AddTranscript` is consumed; `AddPartialTranscript` is
    provisional and would double-count. Results carry `type` ("word" or
    "punctuation"), `start_time`, `end_time`, and `alternatives[0].content`.
    Punctuation is dropped: it has no acoustic span of its own and would
    pollute the onset-gap distribution the motion clock is measured on.
    """

    words: list[TimedWord] = []
    for message in messages:
        if message.get("message") != "AddTranscript":
            continue
        for result in message.get("results", []):
            if result.get("type") != "word":
                continue
            alternatives = result.get("alternatives") or []
            content = str(alternatives[0].get("content", "")) if alternatives else ""
            if not content:
                continue
            speaker = alternatives[0].get("speaker") if alternatives else None
            words.append(TimedWord(
                text=content,
                start=float(result.get("start_time", 0.0)),
                end=float(result.get("end_time", 0.0)),
                speaker=None if speaker in (None, "UU") else str(speaker),
            ))
    return words


def parse_soniox(messages: list[dict]) -> list[TimedWord]:
    """Assemble Soniox tokens into words.

    Soniox emits sub-word tokens with `start_ms`/`end_ms` and an `is_final`
    flag; only final tokens are kept, since non-final ones "may change,
    disappear, or be replaced". Word boundaries follow the leading-space
    convention -- the same one the Korean Zipformer export uses to preserve
    어절 boundaries -- so a token beginning with a space starts a new word and
    the word's span runs from its first token's start to its last token's end.
    """

    words: list[TimedWord] = []
    for message in messages:
        for token in message.get("tokens", []):
            if not token.get("is_final"):
                continue
            raw = str(token.get("text", ""))
            if not raw or not raw.strip():
                continue
            start = float(token.get("start_ms", 0)) / 1000.0
            end = float(token.get("end_ms", 0)) / 1000.0
            speaker = token.get("speaker")
            speaker = str(speaker) if speaker is not None else None
            starts_word = raw[:1].isspace() or not words
            if starts_word:
                words.append(TimedWord(raw.strip(), start, end, speaker))
            else:
                previous = words[-1]
                previous.text += raw.strip()
                previous.end = max(previous.end, end)
    return [word for word in words if word.text]


# ---------------------------------------------------------------------------
# Cloud transports (lazy, uncovered by the offline suite)
# ---------------------------------------------------------------------------


def _require_websockets():
    try:
        import websockets.sync.client as client
    except ImportError as exc:
        raise SystemExit(
            "cloud backends need the websockets package:\n"
            "  .venv/bin/pip install websockets"
        ) from exc
    return client


def _pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


class SpeechmaticsBackend:
    """Speechmatics realtime WebSocket.

    Chosen for the comparison because it is the only surveyed provider
    returning word timings, realtime diarization, and timed audio events on one
    stream. Audio events are requested but not scored here -- they are a
    separate lane (`autocwi/soundevents.py`).
    """

    name = "speechmatics"
    URL = "wss://eu2.rt.speechmatics.com/v2"

    def __init__(self, language: str = "en", url: str | None = None,
                 diarization: str = "speaker"):
        self.language = language
        self.url = url or os.environ.get("SPEECHMATICS_URL", self.URL)
        self.diarization = diarization
        self.key = os.environ.get("SPEECHMATICS_API_KEY", "").strip()
        if not self.key:
            raise SystemExit("SPEECHMATICS_API_KEY is not set")

    def _config(self) -> dict:
        return {
            "message": "StartRecognition",
            "audio_format": {"type": "raw", "encoding": "pcm_s16le",
                             "sample_rate": SR},
            "transcription_config": {
                "language": self.language,
                "enable_partials": False,
                "diarization": self.diarization,
                "operating_point": "enhanced",
            },
        }

    def transcribe(self, audio: np.ndarray, sample_rate: int = SR) -> Transcript:
        import time

        client = _require_websockets()
        started = time.perf_counter()
        messages: list[dict] = []
        try:
            with client.connect(
                self.url, additional_headers={"Authorization": f"Bearer {self.key}"}
            ) as socket:
                socket.send(json.dumps(self._config()))
                pcm = _pcm16(audio)
                # ~250 ms frames: large enough not to thrash the socket, small
                # enough that this still exercises the streaming path rather
                # than degenerating into a file upload.
                frame = SR // 4 * 2
                for offset in range(0, len(pcm), frame):
                    socket.send(pcm[offset:offset + frame])
                socket.send(json.dumps({
                    "message": "EndOfStream",
                    "last_seq_no": (len(pcm) + frame - 1) // frame,
                }))
                for raw in socket:
                    if isinstance(raw, bytes):
                        continue
                    message = json.loads(raw)
                    messages.append(message)
                    if message.get("message") in ("EndOfTranscript", "Error"):
                        break
        except Exception as exc:
            return Transcript(error=f"{type(exc).__name__}: {exc}",
                              elapsed_s=time.perf_counter() - started)
        return Transcript(words=parse_speechmatics(messages),
                          elapsed_s=time.perf_counter() - started)


class SonioxBackend:
    """Soniox realtime WebSocket.

    Its `is_final` flag maps directly onto this project's provisional/durable
    split, and timestamps are on by default.
    """

    name = "soniox"
    URL = "wss://stt-rt.soniox.com/transcribe-websocket"

    def __init__(self, language: str = "en", url: str | None = None,
                 model: str = "stt-rt-preview"):
        self.language = language
        self.url = url or os.environ.get("SONIOX_URL", self.URL)
        self.model = model
        self.key = os.environ.get("SONIOX_API_KEY", "").strip()
        if not self.key:
            raise SystemExit("SONIOX_API_KEY is not set")

    def _config(self) -> dict:
        return {
            "api_key": self.key,
            "model": self.model,
            "audio_format": "pcm_s16le",
            "sample_rate": SR,
            "num_channels": 1,
            "language_hints": [self.language],
            "enable_speaker_diarization": True,
        }

    def transcribe(self, audio: np.ndarray, sample_rate: int = SR) -> Transcript:
        import time

        client = _require_websockets()
        started = time.perf_counter()
        messages: list[dict] = []
        try:
            with client.connect(self.url) as socket:
                socket.send(json.dumps(self._config()))
                pcm = _pcm16(audio)
                frame = SR // 4 * 2
                for offset in range(0, len(pcm), frame):
                    socket.send(pcm[offset:offset + frame])
                socket.send("")  # empty string signals end of audio
                for raw in socket:
                    if isinstance(raw, bytes):
                        continue
                    message = json.loads(raw)
                    messages.append(message)
                    if message.get("finished") or message.get("error_code"):
                        break
        except Exception as exc:
            return Transcript(error=f"{type(exc).__name__}: {exc}",
                              elapsed_s=time.perf_counter() - started)
        return Transcript(words=parse_soniox(messages),
                          elapsed_s=time.perf_counter() - started)


BACKENDS = {
    "local": LocalBackend,
    "speechmatics": SpeechmaticsBackend,
    "soniox": SonioxBackend,
}
