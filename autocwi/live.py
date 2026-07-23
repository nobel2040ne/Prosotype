"""Live captions: microphone -> true streaming ASR + prosody -> SSE events.

The default recognizer is a pair of sherpa-onnx 0.6B streaming Nemotron
profiles. A 160 ms stream produces immediate revisable words; a more accurate
1120 ms stream supplies provisional spoken-onset cues, corrects overlapping
drafts, and alone emits durable words. This uses extra local memory/CPU to
avoid choosing either latency or accuracy for every stage.

Word events share the CaptionSpec word shape (text/start/end/speaker/
loudness/pitch/loudness_db/pitch_hz/conf) plus an absolute `t` wall-clock
onset. Only committed word events are appended to ``live_events.jsonl`` and
need to be consumed by future haptic hardware. ``hypothesis`` and ``cue``
events are optional live-display extensions and may be replaced at any time.
Cues improve visual synchronization but are never written to the durable log
or intended for haptic actuation.

Everything runs locally: sounddevice (mic) -> sherpa-onnx -> parselmouth,
served to the browser over plain stdlib HTTP + Server-Sent Events. The former
pause-segmented Whisper path remains available with ``live --whisper MODEL``
for comparison and keeps its adaptive threshold/VAD filtering.
"""

from __future__ import annotations

import http.server
import difflib
import json
import math
import os
import queue
import re
import threading
import time
import warnings
import webbrowser
from collections import deque
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

SR = 16_000
BLOCK = 1024  # samples per audio block (~64 ms)


def _rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(x**2))), 1e-8))


# ---------------------------------------------------------------------------
# Audio sources: microphone or a wav file paced in real time (demo/testing)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AudioChunk:
    """Captured audio with its source-clock position.

    ``discontinuity`` is reserved for a real capture-device gap. Normal decoder
    backlog is losslessly batched and never converted into a discontinuity.

    ``samples`` always stays at the true captured level: prosody measures
    ``loudness_db`` from it, and that drives the CWI volume -> type-size
    channel. ``asr_samples`` is the optionally gained copy handed to the
    recognizer, so amplifying a quiet talker can never make a whisper render
    at the same size as a shout.
    """

    samples: np.ndarray
    source_start: float
    discontinuity: bool = False
    dropped_s: float = 0.0
    asr_samples: np.ndarray | None = None

    @property
    def source_end(self) -> float:
        return self.source_start + len(self.samples) / SR

    @property
    def recognizer_samples(self) -> np.ndarray:
        return self.samples if self.asr_samples is None else self.asr_samples


def coalesce_audio_chunks(chunks: Iterable[AudioChunk],
                          previous_end: float) -> AudioChunk:
    """Losslessly batch every queued capture block for decoder catch-up."""

    pending = list(chunks)
    if not pending:
        raise ValueError("at least one audio chunk is required")
    source_start = pending[0].source_start
    gap = max(0.0, source_start - previous_end)
    samples = np.concatenate([chunk.samples for chunk in pending]).astype(np.float32,
                                                                          copy=False)
    asr_samples = None
    if any(chunk.asr_samples is not None for chunk in pending):
        asr_samples = np.concatenate(
            [chunk.recognizer_samples for chunk in pending]
        ).astype(np.float32, copy=False)
    return AudioChunk(
        samples=samples,
        source_start=source_start,
        discontinuity=gap > 1.5 / SR or any(chunk.discontinuity for chunk in pending),
        dropped_s=gap + sum(chunk.dropped_s for chunk in pending),
        asr_samples=asr_samples,
    )


def list_input_devices() -> str:
    """Render the selectable capture devices for ``live --list-devices``."""

    import sounddevice as sd

    default = sd.default.device[0]
    lines = []
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        mark = " (default)" if index == default else ""
        lines.append(f"  {index}: {dev['name']}{mark}")
    return "\n".join(lines) or "  (no input devices found)"


def mic_blocks(stop: threading.Event, device: int | str | None = None):
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        raise SystemExit(
            f"microphone capture needs sounddevice ({e}) — pip install sounddevice"
        ) from e

    # The PortAudio callback must never block behind recognition. The consumer
    # drains and batches every pending block on each pass; because the selected
    # recognizers run faster than real time, transient backlog converges without
    # either dropping words or accumulating permanent delay.
    q: queue.Queue[AudioChunk] = queue.Queue()
    captured_samples = 0

    def cb(indata, frames, t, status):
        nonlocal captured_samples
        samples = indata[:, 0].copy()
        chunk = AudioChunk(samples, captured_samples / SR)
        captured_samples += len(samples)
        q.put_nowait(chunk)

    with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                        blocksize=BLOCK, latency="low", callback=cb,
                        device=device):
        try:
            name = sd.query_devices(device if device is not None
                                    else sd.default.device[0])["name"]
        except Exception:
            name = "default input"
        print(f"[live] microphone open: {name} — speak! (Ctrl-C to quit)")
        previous_end = 0.0
        while not stop.is_set():
            try:
                pending = [q.get(timeout=0.2)]
            except queue.Empty:
                continue
            while True:
                try:
                    pending.append(q.get_nowait())
                except queue.Empty:
                    break
            chunk = coalesce_audio_chunks(pending, previous_end)
            previous_end = chunk.source_end
            if chunk.discontinuity:
                print(f"[live] capture device lost {chunk.dropped_s:.2f}s — resyncing")
            yield chunk


def sample_clip_path() -> str:
    """The bundled CWI reference clip, for testing live mode without a mic.

    Its audio is dialogue at roughly -36 dBFS, so it also exercises the input
    gain and the stable-display path end to end.
    """

    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "assets" / "sample.mp4",
        root / "AE PROJECT" / "AE PROJECT" / "(Footage)" / "ASETS" / "Video"
             / "Cena_ref_CI_Template_v02a.mp4",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    raise SystemExit(
        "no bundled sample clip found — expected one of:\n  "
        + "\n  ".join(str(p) for p in candidates)
    )


def file_blocks(path: str | Path, realtime: bool = True, loop: bool = False,
                _clock=None, _sleep=None):
    """Yield file audio against a source clock without dropping late blocks.

    Deadline pacing is important: sleeping for every block *after* inference
    adds inference time to media time and guarantees steadily growing delay.

    ``loop`` restarts the clip when it ends, so a fixed sample plays as a
    continuous live feed. The source clock keeps advancing across loops and the
    first block of each new pass is marked as a discontinuity, so the captioner
    resets its stream and the browser clears the previous pass instead of
    stacking the same words on top of each other.
    """

    import librosa

    clock = _clock or time.monotonic
    sleep = _sleep or time.sleep
    with warnings.catch_warnings():
        # mp4/aac decodes through librosa's audioread fallback, which warns that
        # PySoundFile "failed" (it just cannot read compressed audio) — harmless.
        warnings.simplefilter("ignore")
        data, _ = librosa.load(str(path), sr=SR, mono=True)
    duration = len(data) / SR
    started = clock()
    base = 0.0
    first_pass = True
    while first_pass or loop:
        i = 0
        while i < len(data):
            source_start = base + i / SR
            if realtime:
                delay = started + source_start - clock()
                if delay > 0:
                    sleep(delay)
            blk = data[i:i + BLOCK].astype(np.float32)
            yield AudioChunk(blk, source_start,
                             discontinuity=(loop and i == 0 and not first_pass))
            i += len(blk)
        base += duration
        first_pass = False


class InputGain:
    """Drive the recognizer's copy of the audio toward a usable level.

    A streaming transducer is trained on speech at conventional levels. Well
    below that it simply stops emitting non-blank tokens, so a quiet talker
    produces no captions at all — not because anything rejected the audio, but
    because there was too little signal to decode. This scales the recognizer
    copy only; ``AudioChunk.samples`` keeps the true captured level so the CWI
    volume -> type-size mapping still distinguishes a whisper from a shout.

    Gain is held (not reduced) during silence so room tone is never amplified
    into hiss, and it moves in bounded steps per second so the encoder never
    sees a level discontinuity mid-word.
    """

    def __init__(self, cfg: dict):
        gain_cfg = dict(cfg.get("live", {}).get("input_gain", {}) or {})
        self.enabled = bool(gain_cfg.get("enabled", True))
        self.target_dbfs = float(gain_cfg.get("target_dbfs", -26.0))
        self.min_gain_db = float(gain_cfg.get("min_gain_db", 0.0))
        self.max_gain_db = float(gain_cfg.get("max_gain_db", 30.0))
        self.floor_margin_db = float(gain_cfg.get("floor_margin_db", 8.0))
        self.absolute_floor_db = float(gain_cfg.get("absolute_floor_db", -72.0))
        self.attack_db_per_s = float(gain_cfg.get("attack_db_per_s", 24.0))
        self.release_db_per_s = float(gain_cfg.get("release_db_per_s", 6.0))
        self.acquire_db_per_s = float(gain_cfg.get("acquire_db_per_s", 60.0))
        self.acquired = False
        self.headroom_dbfs = float(gain_cfg.get("headroom_dbfs", -1.0))
        self.gain_db = float(gain_cfg.get("initial_gain_db", 0.0))
        history_s = float(gain_cfg.get("floor_window_s", 6.0))
        self.levels: deque[float] = deque(maxlen=max(8, int(history_s * SR / BLOCK)))
        self.floor_db = self.absolute_floor_db
        self.rms_db = self.absolute_floor_db
        self.peak_db = self.absolute_floor_db
        self.speech = False
        self.clipping = False

    def _update_floor(self, rms_db: float) -> None:
        self.levels.append(rms_db)
        if len(self.levels) >= 8:
            self.floor_db = float(np.percentile(self.levels, 20))
        else:
            self.floor_db = float(min(self.floor_db, rms_db))

    def process(self, chunk: AudioChunk) -> AudioChunk:
        raw = chunk.samples
        if not len(raw):
            return chunk
        # numpy scalars leak into the SSE payload otherwise: np.float64 is fine
        # because it subclasses float, but np.bool_ does not subclass bool and
        # json.dumps rejects it.
        self.rms_db = float(_rms_db(raw))
        self.peak_db = float(20 * np.log10(max(float(np.max(np.abs(raw))), 1e-8)))
        self.clipping = bool(self.peak_db > -0.5)
        self._update_floor(self.rms_db)
        if not self.enabled:
            self.speech = bool(self.rms_db > self.floor_db + self.floor_margin_db)
            self.gain_db = 0.0
            return chunk

        # Only speech-like blocks may move the gain. Silence holds it steady.
        self.speech = bool(self.rms_db > self.floor_db + self.floor_margin_db and
                           self.rms_db > self.absolute_floor_db)
        if self.speech:
            desired = float(np.clip(self.target_dbfs - self.rms_db,
                                    self.min_gain_db, self.max_gain_db))
            dt = len(raw) / SR
            # Shed gain quickly so a sudden loud passage cannot clip; add it
            # back slowly so the level does not audibly pump between words.
            if desired < self.gain_db:
                rate = self.attack_db_per_s
            elif not self.acquired:
                # Until the gain has converged once, ramp fast: at a slow
                # tracking rate the opening sentence is still under-gained and
                # gets dropped, which is the very failure this exists to fix.
                rate = self.acquire_db_per_s
            else:
                rate = self.release_db_per_s
            step = rate * dt
            self.gain_db += float(np.clip(desired - self.gain_db, -step, step))
            self.gain_db = float(np.clip(self.gain_db, self.min_gain_db, self.max_gain_db))
            if abs(desired - self.gain_db) < 1.0:
                self.acquired = True

        if self.gain_db <= 0.001:
            return chunk
        scaled = raw * (10.0 ** (self.gain_db / 20.0))
        ceiling = 10.0 ** (self.headroom_dbfs / 20.0)
        peak = float(np.max(np.abs(scaled))) if len(scaled) else 0.0
        if peak > ceiling:
            scaled = scaled * (ceiling / peak)
        return replace(chunk, asr_samples=scaled.astype(np.float32, copy=False))

    def status(self) -> str:
        """Coarse state used by both the console and the browser meter."""

        if self.clipping:
            return "clipping"
        if self.rms_db <= self.absolute_floor_db:
            return "no-signal"
        if self.speech:
            headroom = self.max_gain_db - self.gain_db
            if self.rms_db + self.gain_db < self.target_dbfs - 12.0 and headroom < 1.0:
                return "too-quiet"
            return "good"
        return "idle"

    def level_event(self, t: float) -> dict:
        return {
            "type": "level",
            "t": round(t, 3),
            "rms_db": round(self.rms_db, 1),
            "peak_db": round(self.peak_db, 1),
            "floor_db": round(self.floor_db, 1),
            "gain_db": round(self.gain_db, 1),
            "effective_db": round(self.rms_db + self.gain_db, 1),
            "target_db": round(self.target_dbfs, 1),
            "speech": self.speech,
            "status": self.status(),
        }


@dataclass(frozen=True)
class HypothesisWord:
    """A display word reconstructed from one or more recognizer tokens.

    ``pieces`` keeps the sub-word tokens the word was assembled from, as
    ``(text, start)`` pairs, for CWI 2.2.4 syllable variation. The transducer
    quantizes timestamps to its encoder frame, so short words emit every piece
    on one frame and carry no usable internal timing; drawn-out words — the
    only ones 2.2.4 applies to — do get distinct onsets.
    """

    text: str
    start: float
    end: float
    conf: float
    conf_available: bool = True
    pieces: tuple[tuple[str, float], ...] = ()

    def syllables(self) -> list[tuple[str, float]]:
        """Merge pieces sharing an encoder frame into distinct-onset groups."""

        groups: list[tuple[str, float]] = []
        for text, start in self.pieces:
            if groups and abs(start - groups[-1][1]) < 1e-6:
                groups[-1] = (groups[-1][0] + text, groups[-1][1])
            else:
                groups.append((text, start))
        return groups


def hypothesis_words(result, audio_duration: float) -> list[HypothesisWord]:
    """Collapse sherpa token pieces into timestamped display words.

    The English transducer uses leading spaces as word-boundary markers, e.g.
    ``[" THE", " YE", "LL", "OW"]``. Some revisions contain a standalone
    space token, so a boundary is kept even when that token has no letters.
    """

    tokens = list(getattr(result, "tokens", []) or [])
    stamps = list(getattr(result, "timestamps", []) or [])
    probs = list(getattr(result, "ys_probs", []) or [])
    if not tokens or len(stamps) != len(tokens):
        text = str(getattr(result, "text", "") or "").strip()
        parts = text.split()
        if not parts:
            return []
        span = max(audio_duration, 0.08 * len(parts)) / len(parts)
        return [
            HypothesisWord(p, i * span, max((i + 1) * span, i * span + 0.02), 0.5, False)
            for i, p in enumerate(parts)
        ]

    grouped: list[tuple[str, float, list[float], list[tuple[str, float]]]] = []
    text = ""
    start = 0.0
    word_probs: list[float] = []
    word_pieces: list[tuple[str, float]] = []
    pending_boundary = False

    def flush() -> None:
        nonlocal text, word_probs, word_pieces, pending_boundary
        clean = text.strip()
        if clean:
            grouped.append((clean, start, word_probs, word_pieces))
        text, word_probs, word_pieces, pending_boundary = "", [], [], False

    for i, (token, stamp) in enumerate(zip(tokens, stamps)):
        boundary = bool(token[:1].isspace())
        if boundary and text.strip():
            flush()
        if boundary:
            start = float(stamp)
            pending_boundary = True
        elif not text and not pending_boundary:
            start = float(stamp)
        piece = token.lstrip() if boundary else token
        text += piece
        if piece:
            word_pieces.append((piece, float(stamp)))
        if text:
            pending_boundary = False
        if i < len(probs):
            word_probs.append(float(probs[i]))
    flush()

    words: list[HypothesisWord] = []
    for i, (word, word_start, logps, pieces) in enumerate(grouped):
        if i + 1 < len(grouped):
            word_end = grouped[i + 1][1]
        else:
            # A trailing endpoint contains silence. Limit the last word span so
            # that its loudness is not diluted by that silence.
            word_end = min(audio_duration, word_start + 0.6)
        word_end = max(word_start + 0.02, word_end)
        conf = math.exp(sum(logps) / len(logps)) if logps else 0.5
        words.append(HypothesisWord(word, word_start, word_end,
                                    float(np.clip(conf, 0.0, 1.0)), bool(logps),
                                    tuple(pieces)))
    return words


def common_prefix_len(a: list[HypothesisWord], b: list[HypothesisWord]) -> int:
    """Return the case-insensitive common word prefix of two hypotheses."""

    n = 0
    for left, right in zip(a, b):
        if left.text.casefold() != right.text.casefold():
            break
        n += 1
    return n


def _normalized_token(text: str) -> str:
    return "".join(re.findall(r"[A-Z0-9']+", text.upper()))


def conservative_verified_words(
    streaming: list[HypothesisWord], verified_text: str
) -> list[HypothesisWord]:
    """Align authoritative endpoint text onto the streaming word clock.

    Equal words and one-for-one corrections retain their original timings.
    Unequal replacement spans are divided across the verified words, pure
    insertions use the inter-word gap, and deleted streaming words disappear.
    This makes the durable transcript verifier-accurate while retaining real
    acoustic timing wherever the two recognizers agree. Close dialect spelling
    variants such as British ``dishonoured`` vs US ``dishonored`` stay as the
    streaming speaker produced them.
    """

    verified = verified_text.split()
    if not streaming or not verified:
        return streaming
    left = [_normalized_token(word.text) for word in streaming]
    right = [_normalized_token(word) for word in verified]
    output: list[HypothesisWord] = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)

    def corrected(source: HypothesisWord, token: str, token_norm: str) -> HypothesisWord:
        source_norm = _normalized_token(source.text)
        if source_norm != token_norm and not token_norm.startswith(source_norm):
            similarity = difflib.SequenceMatcher(
                a=source_norm, b=token_norm, autojunk=False
            ).ratio()
            if similarity >= 0.88:
                token = source.text
        # Sub-word onsets only describe the spelling they were decoded from, so
        # they survive a verifier pass only when the text is unchanged.
        pieces = source.pieces if token == source.text else ()
        return HypothesisWord(
            token, source.start, source.end, source.conf,
            source.conf_available, pieces,
        )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        source_count = i2 - i1
        verified_count = j2 - j1
        if tag == "delete":
            continue
        if source_count == verified_count:
            output.extend(
                corrected(streaming[source_i], verified[verified_i], right[verified_i])
                for source_i, verified_i in zip(range(i1, i2), range(j1, j2))
            )
            continue

        # A non-1:1 verifier correction has no native token timestamps. Anchor
        # it to the corresponding streaming span (or insertion gap) and divide
        # that small interval monotonically. These inferred slots are only
        # created once, at the phrase endpoint.
        if source_count:
            span_start = streaming[i1].start
            span_end = streaming[i2 - 1].end
            conf = float(np.mean([word.conf for word in streaming[i1:i2]]))
            conf_available = all(word.conf_available for word in streaming[i1:i2])
        else:
            previous_end = streaming[i1 - 1].end if i1 else 0.0
            next_start = streaming[i1].start if i1 < len(streaming) else previous_end
            span_start, span_end = previous_end, next_start
            if span_end - span_start < 0.02 * verified_count:
                span_end = span_start + 0.02 * verified_count
            neighbors = streaming[max(0, i1 - 1):min(len(streaming), i1 + 1)]
            conf = float(np.mean([word.conf for word in neighbors])) if neighbors else 0.5
            conf_available = False
        span_end = max(span_end, span_start + 0.02 * verified_count)
        step = (span_end - span_start) / max(verified_count, 1)
        for offset, verified_i in enumerate(range(j1, j2)):
            output.append(HypothesisWord(
                verified[verified_i],
                span_start + offset * step,
                span_start + (offset + 1) * step,
                conf,
                conf_available,
            ))
    return output


class EndpointVerifier:
    """Fast local whole-phrase recognizer used only for durable text."""

    def __init__(self, recognizer):
        self.recognizer = recognizer

    def transcribe(self, audio: np.ndarray) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(SR, np.asarray(audio, dtype=np.float32))
        self.recognizer.decode_stream(stream)
        return str(stream.result.text or "").strip()


class AdaptiveSpeechGate:
    """Track speech duration against the same adaptive noise-floor rule."""

    def __init__(self, live_cfg: dict):
        from collections import deque

        self.fixed_db = live_cfg["silence_db"]
        self.adaptive = live_cfg.get("adaptive_silence", True)
        self.levels = deque(maxlen=int(8 * SR / BLOCK))
        self.speech_s = 0.0

    def threshold(self) -> float:
        if not self.adaptive or len(self.levels) < 30:
            return self.fixed_db
        floor = float(np.percentile(self.levels, 20))
        return float(np.clip(floor + 12.0, -55.0, -30.0))

    def accept(self, block: np.ndarray) -> None:
        level = _rms_db(block)
        self.levels.append(level)
        if level > self.threshold():
            self.speech_s += len(block) / SR

    def reset_utterance(self) -> None:
        self.speech_s = 0.0


# ---------------------------------------------------------------------------
# Energy-based utterance segmentation
# ---------------------------------------------------------------------------

def utterances(blocks, live_cfg: dict):
    """Yield (audio, stream_t0) chunks split on pauses.

    The silence threshold adapts to the noise floor (20th percentile of recent
    block levels + 12 dB) so continuous backgrounds — movie scores, fan noise —
    still allow cuts at dialogue dips instead of always hitting the force-cut.
    """
    from collections import deque

    fixed_db = live_cfg["silence_db"]
    adaptive = live_cfg.get("adaptive_silence", True)
    min_silence = live_cfg["min_silence_s"]
    min_speech = live_cfg["min_speech_s"]
    max_utt = live_cfg["max_utterance_s"]
    preroll_blocks = int(0.3 * SR / BLOCK) + 1
    levels: deque[float] = deque(maxlen=int(8 * SR / BLOCK))  # ~8 s of history

    def threshold() -> float:
        if not adaptive or len(levels) < 30:
            return fixed_db
        floor = float(np.percentile(levels, 20))
        return float(np.clip(floor + 12.0, -55.0, -30.0))

    preroll: list[np.ndarray] = []
    buf: list[np.ndarray] = []
    in_speech = False
    silence_s = 0.0
    t_stream = 0.0
    utt_t0 = 0.0

    def flush():
        nonlocal buf, in_speech, silence_s
        audio = np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)
        speech_s = len(audio) / SR - silence_s
        buf, in_speech, silence_s = [], False, 0.0
        if speech_s >= min_speech:
            return audio, utt_t0
        return None

    def energy_blocks():
        for item in blocks:
            if isinstance(item, AudioChunk) and len(item.samples) > BLOCK:
                for offset in range(0, len(item.samples), BLOCK):
                    yield AudioChunk(
                        item.samples[offset:offset + BLOCK],
                        item.source_start + offset / SR,
                        item.discontinuity and offset == 0,
                        item.dropped_s if offset == 0 else 0.0,
                    )
            else:
                yield item

    for item in energy_blocks():
        if isinstance(item, AudioChunk):
            if item.discontinuity:
                # Never decode across a real capture-device discontinuity.
                preroll, buf, in_speech, silence_s = [], [], False, 0.0
                t_stream = item.source_start
            else:
                t_stream = max(t_stream, item.source_start)
            blk = item.samples
        else:
            blk = item
        level = _rms_db(blk)
        levels.append(level)
        silence_db = threshold()
        block_s = len(blk) / SR
        t_stream += block_s
        if not in_speech:
            preroll.append(blk)
            if len(preroll) > preroll_blocks:
                preroll.pop(0)
            if level > silence_db:
                in_speech = True
                buf = list(preroll)
                preroll = []
                utt_t0 = t_stream - len(buf) * BLOCK / SR
                silence_s = 0.0
        else:
            buf.append(blk)
            silence_s = 0.0 if level > silence_db else silence_s + block_s
            dur = len(buf) * BLOCK / SR
            if silence_s >= min_silence or dur >= max_utt:
                out = flush()
                if out:
                    yield out
    if in_speech:
        out = flush()
        if out:
            yield out


# ---------------------------------------------------------------------------
# Utterance -> word events (ASR + prosody)
# ---------------------------------------------------------------------------

def word_events(utts, model, lang: str, cfg: dict, speaker: str = "S1"):
    from collections import deque

    prosody_cfg = cfg["prosody"]
    cfg_lo, cfg_hi = cfg["live"]["db_range"]
    # Self-calibrating loudness: the running median of recent word levels is
    # the CWI baseline (5% type size); +15 dB reads as a shout (12%), -5 dB as
    # a whisper (3%). This adapts to any mic gain without configuration.
    hist: deque[float] = deque(maxlen=120)

    import parselmouth

    for audio, t0 in utts:
        t_infer = time.monotonic()
        segments, _ = model.transcribe(
            audio, language=lang, word_timestamps=True, beam_size=1,
            temperature=0.0, condition_on_previous_text=False,
            vad_filter=True,  # drop music/noise-only stretches inside the chunk
        )
        # Skip hallucination-prone segments (music beds make whisper invent
        # phrases like "thanks for watching" with high no-speech probability).
        words = [
            w
            for seg in segments
            if seg.no_speech_prob < 0.6 or seg.avg_logprob > -1.0
            for w in (seg.words or [])
            if w.word.strip() and w.probability >= 0.15
        ]
        if not words:
            continue

        snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SR)
        try:
            pitch = snd.to_pitch_cc(pitch_floor=prosody_cfg["pitch_floor_hz"],
                                    pitch_ceiling=prosody_cfg["pitch_ceiling_hz"])
            f0_t, f0_v = pitch.xs(), pitch.selected_array["frequency"]
        except parselmouth.PraatError:  # utterance too short for the analysis window
            f0_t, f0_v = np.zeros(0), np.zeros(0)

        latency = time.monotonic() - t_infer
        texts = []
        for w in words:
            i0, i1 = int(w.start * SR), min(int(w.end * SR), len(audio))
            span = audio[i0:i1]
            db = _rms_db(span) if len(span) else -80.0
            hist.append(db)
            if len(hist) >= 6:
                med = float(np.median(hist))
                lo_db, hi_db = med - 5.0, med + 15.0
            else:
                lo_db, hi_db = cfg_lo, cfg_hi
            mask = (f0_t >= w.start) & (f0_t <= w.end)
            voiced = f0_v[mask][f0_v[mask] > 0]
            pitch_hz = float(np.median(voiced)) if len(voiced) else 0.0
            voiced_frac = float(len(voiced) / max(mask.sum(), 1))
            yield {
                "text": w.word.strip(),
                "t": round(t0 + w.start, 3),          # absolute stream onset
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "speaker": speaker,
                "loudness": round(loudness, 4),
                "pitch": 0.5,                          # renderer uses raw Hz (domain_hz)
                "loudness_db": round(db, 2),
                "pitch_hz": round(pitch_hz, 2),
                "voiced_frac": round(voiced_frac, 3),
                "conf": round(min(max(w.probability, 0.0), 1.0), 3),
            }
            texts.append(w.word.strip())
        print(f"[live] +{latency:.1f}s  {' '.join(texts)}")


# ---------------------------------------------------------------------------
# True-streaming transducer -> revisable hypotheses + committed word events
# ---------------------------------------------------------------------------

class SpeakerTracker:
    """Online speaker attribution from voice embeddings.

    Live has no advance knowledge of the cast, so speakers are discovered as
    they talk: each analysis window is embedded and matched against running
    per-speaker centroids by cosine similarity; a voice that matches nothing
    becomes the next speaker, in palette order.

    ``embed`` is injected (samples -> L2-normalized vector or None) so the
    clustering is testable offline without the ONNX model.

    Two entry points with different trust levels: ``classify_span`` labels a
    committed word mid-stream but never creates speakers or moves centroids —
    a window there may straddle a turn boundary. ``label_words`` runs at the
    endpoint over the whole utterance with sliding windows and majority vote
    per word; only it may update the model of who sounds like whom.
    """

    def __init__(self, embed, similarity: float = 0.35, max_speakers: int = 6,
                 window_s: float = 1.0, hop_s: float = 0.25,
                 min_span_s: float = 0.4, change_below: float = 0.3,
                 merge_at: float = 0.5):
        self.embed = embed
        self.similarity = similarity
        self.max_speakers = max_speakers
        self.window_s = window_s
        self.hop_s = hop_s
        self.min_span_s = min_span_s
        self.change_below = change_below
        self.merge_at = merge_at
        self.centroids: list[np.ndarray] = []
        self.counts: list[int] = []
        # A centroid that later proves to be the same voice as another is
        # aliased to it rather than deleted, so speaker numbers already shown
        # on screen stay stable and that voice's future words use the survivor.
        self.alias: dict[int, int] = {}

    def _canon(self, index: int) -> int:
        while index in self.alias:
            index = self.alias[index]
        return index

    def _active(self) -> list[int]:
        return [i for i in range(len(self.centroids)) if i not in self.alias]

    def _assign(self, emb: np.ndarray, update: bool) -> int | None:
        active = self._active()
        if not active:
            if not update:
                return None
            self.centroids.append(emb.astype(np.float32).copy())
            self.counts.append(1)
            return 0
        sims = [float(np.dot(self.centroids[i], emb) /
                      (np.linalg.norm(self.centroids[i]) + 1e-9)) for i in active]
        best = active[int(np.argmax(sims))]
        if max(sims) >= self.similarity or not update or \
                len(active) >= self.max_speakers:
            if update:
                n = self.counts[best]
                self.centroids[best] = (self.centroids[best] * n + emb) / (n + 1)
                self.counts[best] += 1
            return best if (update or max(sims) >= self.similarity) else None
        self.centroids.append(emb.astype(np.float32).copy())
        self.counts.append(1)
        return len(self.centroids) - 1

    def _merge_converged(self) -> None:
        # Two identities the clustering created early can turn out to be one
        # voice once their centroids see more speech; fold them together.
        active = self._active()
        for i_pos, i in enumerate(active):
            for j in active[i_pos + 1:]:
                if j in self.alias:
                    continue
                ci, cj = self.centroids[i], self.centroids[j]
                sim = float(np.dot(ci, cj) /
                            (np.linalg.norm(ci) * np.linalg.norm(cj) + 1e-9))
                if sim >= self.merge_at:
                    ni, nj = self.counts[i], self.counts[j]
                    self.centroids[i] = (ci * ni + cj * nj) / (ni + nj)
                    self.counts[i] = ni + nj
                    self.alias[j] = i

    def classify_span(self, audio: np.ndarray, start_s: float,
                      end_s: float) -> str | None:
        """Provisional label for a committed word; verification corrects it."""

        if not self._active():
            # Before the first endpoint there is nothing to classify against;
            # skip the embedding entirely rather than pay it for a None.
            return None
        span = audio[max(0, int((end_s - self.window_s) * SR)):int(end_s * SR)]
        if len(span) < int(self.min_span_s * SR):
            return None
        emb = self.embed(span)
        if emb is None:
            return None
        index = self._assign(emb, update=False)
        return None if index is None else f"S{self._canon(index) + 1}"

    def label_words(self, audio: np.ndarray, words) -> list[str]:
        """Per-word labels for a finished utterance.

        Segment-then-cluster: adjacent sliding windows are compared to find
        change points (where the voice audibly switches), each contiguous
        segment is embedded WHOLE, and those long clean embeddings are what
        get clustered. Clustering raw short windows instead either invented
        phantom speakers or collapsed everyone into one, because windows that
        straddle a turn boundary belong to nobody.
        """

        if not words:
            return []
        t0, t1 = words[0].start, words[-1].end
        windows: list[tuple[float, np.ndarray]] = []
        t = t0
        while t + self.window_s <= t1 + 1e-9:
            emb = self.embed(audio[int(t * SR):int((t + self.window_s) * SR)])
            if emb is not None:
                windows.append((t + self.window_s / 2, emb))
            t += self.hop_s
        bounds = [t0]
        for (m1, e1), (m2, e2) in zip(windows, windows[1:]):
            if float(np.dot(e1, e2)) < self.change_below:
                bounds.append((m1 + m2) / 2)
        bounds.append(t1)
        cleaned = [bounds[0]]
        for b in bounds[1:]:
            if b - cleaned[-1] > 0.6:
                cleaned.append(b)
        if cleaned[-1] < t1:
            cleaned.append(t1)
        segments: list[tuple[float, float, int]] = []
        for a, b in zip(cleaned, cleaned[1:]):
            emb = self.embed(audio[int(a * SR):int(b * SR)])
            index = self._assign(emb, update=True) if emb is not None else None
            segments.append((a, b, 0 if index is None else index))
        self._merge_converged()
        labels = []
        for word in words:
            mid = (word.start + word.end) / 2
            index = segments[-1][2]
            for a, b, seg_index in segments:
                if a - 1e-9 <= mid <= b + 1e-9:
                    index = seg_index
                    break
            # Canonical AFTER merging, so an identity that just proved to be an
            # existing speaker already reports that speaker's label.
            labels.append(f"S{self._canon(index) + 1}")
        return labels


class StreamingCaptioner:
    """Turn online recognizer revisions into stable CaptionSpec-shaped words."""

    def __init__(self, recognizer, cfg: dict, speaker: str = "S1",
                 draft_only: bool = False, verifier: EndpointVerifier | None = None,
                 speaker_tracker: SpeakerTracker | None = None):
        from collections import deque

        self.recognizer = recognizer
        self.cfg = cfg
        self.speaker = speaker
        self.draft_only = draft_only
        self.verifier = verifier
        self.speaker_tracker = speaker_tracker
        self.stream = recognizer.create_stream()
        self.stream_base = 0.0
        self.total_samples = 0
        self.audio_blocks: list[np.ndarray] = []
        self.previous: list[HypothesisWord] = []
        self.committed: list[HypothesisWord] = []
        self.last_partial_key: tuple = ()
        self.utterance = 0
        self.db_history: deque[float] = deque(maxlen=120)
        self.prosody_cache: dict[tuple[str, int], tuple[float, float, float]] = {}
        self._last_final_speaker: str | None = None

    @property
    def audio(self) -> np.ndarray:
        if not self.audio_blocks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self.audio_blocks)

    def _prosody(self, word: HypothesisWord, audio: np.ndarray) -> tuple[float, float, float]:
        i0 = max(0, int(word.start * SR))
        i1 = min(len(audio), max(i0 + 1, int(word.end * SR)))
        span = audio[i0:i1]
        db = _rms_db(span) if len(span) else -80.0

        # Pitch benefits from a small context pad while loudness stays confined
        # to the recognized word itself.
        p0, p1 = max(0, i0 - int(0.04 * SR)), min(len(audio), i1 + int(0.04 * SR))
        pitch_hz = 0.0
        voiced_frac = 0.0
        if p1 - p0 >= int(0.04 * SR):
            import parselmouth

            try:
                snd = parselmouth.Sound(audio[p0:p1].astype(np.float64),
                                        sampling_frequency=SR)
                pitch = snd.to_pitch_cc(
                    pitch_floor=self.cfg["prosody"]["pitch_floor_hz"],
                    pitch_ceiling=self.cfg["prosody"]["pitch_ceiling_hz"],
                )
                values = pitch.selected_array["frequency"]
                voiced = values[values > 0]
                if len(voiced):
                    pitch_hz = float(np.median(voiced))
                voiced_frac = float(len(voiced) / max(len(values), 1))
            except parselmouth.PraatError:
                pass
        return db, pitch_hz, voiced_frac

    def _syllable_stops(self, word: HypothesisWord) -> list[dict] | None:
        """CWI 2.2.4 stops: how far the colour has advanced through the word.

        Each stop is ``{"t": fraction of the word's span, "c": fraction of its
        characters}``. Returns None unless the word is drawn out enough to
        qualify and the recognizer gave it distinct sub-word onsets.
        """

        fill_cfg = self.cfg.get("motion", {}).get("syllable_fill", {}) or {}
        if not fill_cfg.get("enabled", True):
            return None
        duration = word.end - word.start
        if duration < float(fill_cfg.get("min_duration_s", 0.32)):
            return None
        groups = word.syllables()
        if len(groups) < int(fill_cfg.get("min_syllables", 2)):
            return None
        total_chars = sum(len(text) for text, _ in groups)
        if not total_chars:
            return None
        stops: list[dict] = []
        chars = 0
        for text, start in groups:
            stops.append({
                "t": round(float(np.clip((start - word.start) / duration, 0.0, 1.0)), 4),
                "c": round(chars / total_chars, 4),
            })
            chars += len(text)
        stops.append({"t": 1.0, "c": 1.0})
        # A leading stop that already sits at t>0 would hold the word white past
        # its own onset, breaking the 2.2.2 contract that colour starts at onset.
        stops[0]["t"] = 0.0
        return stops

    def _word_event(self, word: HypothesisWord, audio: np.ndarray,
                    final: bool, speaker: str | None = None) -> dict:
        # Hypotheses are revised frequently. Re-running pitch analysis for the
        # same word on every decoder tick wastes enough CPU to create its own
        # backlog, and it also makes the displayed typography wobble.
        #
        # THE INVARIANT: a word that has been shown must stop changing. Every
        # field below is therefore frozen per time SLOT, not per text — the
        # verifier respells words, so a text-keyed cache misses precisely when
        # it matters. Measured before this: 42/59 slots reported a different
        # `loudness` at verification than at commit, and 13/59 a different
        # `pitch_hz`, which the renderer faithfully turned into resizing text.
        slot = round(word.start * 20)
        slot_key = ("§slot", self.utterance, slot)
        frozen = self.prosody_cache.get(slot_key)
        if frozen is None:
            # Endpoint retiming can move a word by a few tens of ms, which
            # would otherwise miss its own frozen entry and let it re-style.
            for delta in (-1, 1, -2, 2):
                frozen = self.prosody_cache.get(("§slot", self.utterance, slot + delta))
                if frozen is not None:
                    break
        prosody_key = (word.text.casefold(), round(word.start * 100))
        features = self.prosody_cache.get(prosody_key)
        if frozen is not None:
            features = frozen[:3]
        elif features is None or final:
            # `final` re-measures legitimately: the audio buffer is longer by
            # then, so the word's own span is better covered.
            features = self._prosody(word, audio)
            self.prosody_cache[prosody_key] = features
        db, pitch_hz, voiced_frac = features
        syllables = self._syllable_stops(word)
        if final:
            self.db_history.append(db)
        cfg_lo, cfg_hi = self.cfg["live"]["db_range"]
        med = float(np.median(self.db_history)) if self.db_history else 0.0
        if len(self.db_history) >= 6:
            # Percentiles of this speaker's own words, not a fixed offset from
            # the median. A `median - 5 dB` floor was catastrophically tight:
            # ordinary connected speech runs ~26 dB below its median at the
            # 10th percentile, so 35% of words clipped to loudness 0 and
            # rendered at CWI whisper size (3%) beside normal ones. Clipping
            # happens BEFORE the display smoothing, so no amount of hysteresis
            # could repair it.
            lo_pct, hi_pct = self.cfg["live"].get("db_percentiles", [15, 95])
            lo_db = float(np.percentile(self.db_history, lo_pct))
            hi_db = float(np.percentile(self.db_history, hi_pct))
            # A monotone passage must not amplify millimetre differences into
            # full whisper..shout swings.
            min_span = float(self.cfg["live"].get("db_min_span", 18.0))
            if hi_db - lo_db < min_span:
                mid = (hi_db + lo_db) / 2
                lo_db, hi_db = mid - min_span / 2, mid + min_span / 2
        else:
            lo_db, hi_db = cfg_lo, cfg_hi

        # Haptic salience flags. DHH haptics research (Haptic-Captioning
        # CHI'23; Tactile Emotions CHI'25) found continuous vibration
        # distracting: actuate selectively on speaker changes and strong
        # prosody, with a user-adjustable threshold. Durable words carry the
        # selection so the future haptic module never needs analysis code.
        salience: dict = {}
        if final:
            spoken_by = speaker or self.speaker
            if self._last_final_speaker is not None and \
                    spoken_by != self._last_final_speaker:
                salience["speaker_change"] = True
            self._last_final_speaker = spoken_by
            emphasis_db = self.cfg.get("haptics", {}).get("emphasis_db", 6.0)
            if len(self.db_history) >= 6 and db - med >= emphasis_db:
                salience["emphasis"] = True
        # Pivot the scale on the speaker's median so it lands on the CWI
        # baseline (2.3.5: normal speaking volume = 5% of frame height).
        # A plain lo..hi normalization put the MEDIAN word at mid-scale, which
        # renders at 6.5% — every ordinary word reading as slightly shouted,
        # and the size ratio blowing out to 3x on screen.
        mapping = self.cfg["mapping"]["loudness_to"]
        pivot = ((mapping.get("baseline", 5) - mapping["min"]) /
                 max(1e-6, mapping["max"] - mapping["min"]))
        if len(self.db_history) >= 6 and lo_db < med < hi_db:
            if db <= med:
                loudness = pivot * (db - lo_db) / max(1e-6, med - lo_db)
            else:
                loudness = pivot + (1 - pivot) * (db - med) / max(1e-6, hi_db - med)
        else:
            loudness = (db - lo_db) / max(1e-6, hi_db - lo_db)
        loudness = float(np.clip(loudness, 0.0, 1.0))
        if frozen is not None:
            loudness = frozen[3]
        elif len(self.db_history) >= 6:
            # Freeze only once the scale is calibrated. The first few words of
            # a session normalize against the cold-start `db_range` and are
            # genuinely wrong, so they are allowed exactly one correction.
            self.prosody_cache[slot_key] = (db, pitch_hz, voiced_frac, loudness)
        return {
            "type": "word",
            "final": final,
            "utterance": self.utterance,
            "text": word.text,
            "t": round(self.stream_base + word.start, 3),
            "start": round(word.start, 3),
            "end": round(word.end, 3),
            "speaker": speaker or self.speaker,
            # False means "this is a fallback, not an identification". The page
            # leaves such a word white rather than colouring it and flipping
            # the hue later, which is a mutation on text already read.
            "speaker_known": speaker is not None,
            "loudness": round(loudness, 4),
            "pitch": 0.5,
            "loudness_db": round(db, 2),
            "pitch_hz": round(pitch_hz, 2),
            "voiced_frac": round(voiced_frac, 3),
            "conf": round(word.conf, 3),
            "conf_available": word.conf_available,
            **({"syllables": syllables} if syllables else {}),
            **salience,
        }

    def _process_result(self, endpoint: bool = False):
        audio = self.audio
        result = self.recognizer.get_result_all(self.stream)
        current = hypothesis_words(result, len(audio) / SR)

        if self.draft_only:
            # The low-latency recognizer is a revisable white read-ahead layer.
            # Only the accurate recognizer is allowed to create durable words.
            commit_to = 0
        elif endpoint:
            # A streaming transducer only produces text when it has acoustic
            # evidence; an extra RMS gate deleted valid quiet/program audio.
            commit_to = len(current)
        else:
            stable = common_prefix_len(self.previous, current)
            # Hold the newest word: without a following word its end time and
            # spelling are the parts most likely to change.
            # The hold-back is deliberate and measured: releasing the trailing
            # word early (tried with a 0.6 s trailing-silence rule) saved no
            # time — it fired at the same moment as the endpoint — and it
            # committed truncated spellings, because a trailing word's pieces
            # are not fully flushed until the endpoint. A lone word reaches
            # the screen through the fast-mode white read-ahead instead.
            commit_to = min(stable, max(0, len(current) - 1))
            commit_to = max(len(self.committed), commit_to)

        committed_now = current[len(self.committed):commit_to]

        def provisional_speaker(word):
            # Mid-stream classification only: it never invents a speaker or
            # moves a centroid, because a window here can straddle a turn
            # boundary. The endpoint pass owns learning; it corrects these.
            if self.speaker_tracker is None:
                return None
            return self.speaker_tracker.classify_span(audio, word.start, word.end)

        if self.verifier is None:
            for word in committed_now:
                yield self._word_event(word, audio, final=True,
                                       speaker=provisional_speaker(word))
        elif not endpoint:
            # Stable streaming words may be rendered immediately, but remain
            # provisional until the whole-phrase verifier sees the endpoint.
            for word in committed_now:
                event = self._word_event(word, audio, final=False,
                                         speaker=provisional_speaker(word))
                event.update(type="commit", provisional=True, verified=False)
                yield event
        if commit_to > len(self.committed):
            self.committed = current[:commit_to]

        if self.verifier is not None and endpoint and current:
            verified_text = self.verifier.transcribe(audio)
            verified = conservative_verified_words(current, verified_text)
            speakers = (self.speaker_tracker.label_words(audio, verified)
                        if self.speaker_tracker is not None else None)
            final_events = [self._word_event(word, audio, final=True,
                                             speaker=speakers[i] if speakers else None)
                            for i, word in enumerate(verified)]
            for event in final_events:
                # The endpoint pass is authoritative even when it produced no
                # label (no tracker configured = one speaker, which is known).
                event.update(verified=True, provisional=False, speaker_known=True)
            yield {
                "type": "verification",
                "utterance": self.utterance,
                "text": verified_text,
                "words": final_events,
            }
            yield from final_events

        pending = current[len(self.committed):]
        partial_events = [self._word_event(w, audio, final=False) for w in pending]
        partial_key = tuple((w["text"], w["start"], w["end"]) for w in partial_events)
        if partial_key != self.last_partial_key or committed_now or endpoint:
            yield {
                "type": "hypothesis",
                "utterance": self.utterance,
                "endpoint": endpoint,
                "words": partial_events,
            }
            self.last_partial_key = partial_key
        self.previous = current

    def accept(self, item: np.ndarray | AudioChunk):
        if isinstance(item, AudioChunk):
            if item.discontinuity:
                source_sample = int(round(item.source_start * SR))
                self.total_samples = source_sample
                self._reset_stream(base=item.source_start)
                # Clear stale white hypotheses immediately. Colored committed
                # words remain durable, but no delayed partial survives a jump.
                yield {
                    "type": "hypothesis",
                    "utterance": self.utterance,
                    "endpoint": True,
                    "resync": True,
                    "dropped_s": round(item.dropped_s, 3),
                    "words": [],
                }
            block = item.samples
            asr_block = item.recognizer_samples
        else:
            block = asr_block = item
        block = np.asarray(block, dtype=np.float32)
        asr_block = np.asarray(asr_block, dtype=np.float32)
        # Prosody reads audio_blocks, so it must see the true captured level;
        # only the recognizer gets the gained copy.
        self.audio_blocks.append(block)
        self.total_samples += len(block)
        self.stream.accept_waveform(SR, asr_block)
        decoded = False
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
            decoded = True
        if decoded:
            yield from self._process_result(endpoint=False)
        if self.recognizer.is_endpoint(self.stream):
            yield from self._process_result(endpoint=True)
            self._reset_stream()

    def finish(self):
        # Flush the neural encoder and commit the final word even if the file
        # ends without enough trailing silence for endpoint detection.
        tail = np.zeros(int(0.8 * SR), dtype=np.float32)
        self.audio_blocks.append(tail)
        self.total_samples += len(tail)
        self.stream.accept_waveform(SR, tail)
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        yield from self._process_result(endpoint=True)

    def _reset_stream(self, base: float | None = None) -> None:
        self.stream_base = self.total_samples / SR if base is None else base
        self.stream = self.recognizer.create_stream()
        self.audio_blocks = []
        self.previous = []
        self.committed = []
        self.last_partial_key = ()
        self.utterance += 1
        self.prosody_cache = {}


class DualStreamingCaptioner:
    """Fuse immediate draft hypotheses/cues with accurate durable words."""

    def __init__(self, draft_recognizer, accurate_recognizer, cfg: dict,
                 verifier: EndpointVerifier | None = None,
                 speaker_tracker: "SpeakerTracker | None" = None):
        self.draft = StreamingCaptioner(draft_recognizer, cfg, draft_only=True)
        self.accurate = StreamingCaptioner(
            accurate_recognizer, cfg, verifier=verifier,
            speaker_tracker=speaker_tracker,
        )
        self.draft_words: list[dict] = []
        self.accurate_words: list[dict] = []
        self.cued_slots: set[tuple[int, int]] = set()
        self.last_merged_key: tuple = ()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asr")
        self.closed = False

    @staticmethod
    def _absolute_end(word: dict) -> float:
        return word["t"] + word["end"] - word["start"]

    def _merged_hypothesis(self, endpoint: bool = False,
                           resync: bool = False, dropped_s: float = 0.0):
        frontier = self.accurate.stream_base
        if self.accurate.committed:
            frontier = self.accurate.stream_base + self.accurate.committed[-1].end

        # Source tags are display-only: the accurate stream's tail revises far
        # less than the 160 ms draft, so the page's `fast` mode can render
        # accurate partials as read-ahead without the draft's churn.
        merged = [{**word, "src": "accurate"} for word in self.accurate_words]
        for draft in self.draft_words:
            if draft["t"] < frontier - 0.04:
                continue
            # The two profiles endpoint independently. After one resets, the
            # same acoustic word can be timestamped up to one second apart
            # (e.g. accurate "finally" and draft "Finally"). Prefer the
            # accurate spelling instead of displaying a duplicate tail word.
            if any(
                draft["text"].casefold() == word["text"].casefold()
                and abs(draft["t"] - word["t"]) < 1.0
                for word in self.accurate_words
            ):
                continue
            if any(abs(draft["t"] - word["t"]) < 0.22 for word in self.accurate_words):
                continue
            merged.append({**draft, "src": "draft"})
        merged.sort(key=lambda word: (word["t"], word["start"]))
        key = tuple((word["text"], word["t"], word["end"]) for word in merged)
        if key == self.last_merged_key and not endpoint and not resync:
            return None
        self.last_merged_key = key
        event = {
            "type": "hypothesis",
            "utterance": self.accurate.utterance,
            "endpoint": endpoint,
            "words": merged,
        }
        if resync:
            event.update(resync=True, dropped_s=round(dropped_s, 3))
        return event

    def _provisional_cues(self, words: list[dict], utterance: int) -> list[dict]:
        """Emit accurate-profile words once for display-only color/pop timing."""

        cues = []
        for word in words:
            slot = (utterance, round(word["t"] * 20))  # 50 ms slot identity
            if slot in self.cued_slots:
                continue
            self.cued_slots.add(slot)
            cue = dict(word)
            cue.update(type="cue", final=False, provisional=True,
                       utterance=utterance)
            cues.append(cue)
        return cues

    def _handle_draft_events(self, events):
        for event in events:
            if event["type"] != "hypothesis":
                continue
            self.draft_words = event["words"]
            merged = self._merged_hypothesis(
                # The draft endpoint is not authoritative; only the accurate
                # stream may declare a phrase locked.
                endpoint=False,
                resync=event.get("resync", False),
                dropped_s=event.get("dropped_s", 0.0),
            )
            if merged:
                yield merged

    def _handle_accurate_events(self, events):
        changed = False
        endpoint = False
        resync = False
        dropped_s = 0.0
        cues = []
        verifications = []
        durable = []
        for event in events:
            if event["type"] == "hypothesis":
                self.accurate_words = event["words"]
                cues.extend(self._provisional_cues(
                    event["words"], event["utterance"]
                ))
                endpoint = event.get("endpoint", False)
                resync = event.get("resync", False)
                dropped_s = event.get("dropped_s", 0.0)
                changed = True
            elif event["type"] == "verification":
                verifications.append(event)
                changed = True
            else:
                durable.append(event)
                changed = True
        # Endpoint verification must reach the browser before the following
        # empty hypothesis clears the last provisional word nodes.
        yield from verifications
        if changed:
            merged = self._merged_hypothesis(endpoint, resync, dropped_s)
            if merged:
                yield merged
        # Publish the display snapshot before its cues so the browser always
        # has a stable word node to animate. Durable words retain ASR order.
        yield from cues
        yield from durable

    def accept(self, item):
        # The ONNX calls release the GIL. Run both profiles concurrently across
        # the M1 cores and publish whichever stream completes first; this keeps
        # the draft immediate without putting its CPU time in front of finals.
        futures = {
            self.executor.submit(lambda: list(self.accurate.accept(item))): "accurate",
            self.executor.submit(lambda: list(self.draft.accept(item))): "draft",
        }
        pending = set(futures)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda f: futures[f] != "accurate"):
                events = future.result()
                if futures[future] == "accurate":
                    yield from self._handle_accurate_events(events)
                else:
                    yield from self._handle_draft_events(events)

    def finish(self):
        draft_future = self.executor.submit(lambda: list(self.draft.finish()))
        accurate_future = self.executor.submit(lambda: list(self.accurate.finish()))
        yield from self._handle_draft_events(draft_future.result())
        changed = False
        for event in accurate_future.result():
            if event["type"] == "hypothesis":
                self.accurate_words = event["words"]
                changed = True
            else:
                yield event
                changed = True
        if changed:
            merged = self._merged_hypothesis(endpoint=True)
            if merged:
                yield merged
        self.close()

    def close(self):
        if not self.closed:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.closed = True


def streaming_events(blocks, recognizer, cfg: dict, draft_recognizer=None,
                     verifier: EndpointVerifier | None = None,
                     gain: "InputGain | None" = None,
                     speaker_tracker: "SpeakerTracker | None" = None,
                     sound_detector=None):
    captioner = (DualStreamingCaptioner(
        draft_recognizer, recognizer, cfg, verifier=verifier,
        speaker_tracker=speaker_tracker,
    )
                 if draft_recognizer is not None else StreamingCaptioner(recognizer, cfg))
    gain = gain if gain is not None else InputGain(cfg)
    level_period_s = float(
        cfg.get("live", {}).get("input_gain", {}).get("level_event_period_s", 0.12)
    )
    next_level_at = 0.0
    try:
        for block in blocks:
            if isinstance(block, AudioChunk):
                block = gain.process(block)
                if block.source_start >= next_level_at:
                    next_level_at = block.source_start + level_period_s
                    yield gain.level_event(block.source_start)
                if sound_detector is not None:
                    # TRUE captured level (block.samples), never the gained ASR
                    # copy — the acoustic scene must not be speech-normalized.
                    yield from sound_detector.feed(block.samples, block.source_end)
            yield from captioner.accept(block)
        yield from captioner.finish()
        if sound_detector is not None:
            yield from sound_detector.finish()
    finally:
        if isinstance(captioner, DualStreamingCaptioner):
            captioner.close()


def load_streaming_recognizer(cfg: dict, model_dir: str | Path | None = None):
    """Load the configured local streaming model with no network fallback."""

    import sherpa_onnx

    model_dir = Path(model_dir or cfg["live"]["streaming_model_dir"])
    if not model_dir.is_absolute():
        model_dir = Path(__file__).resolve().parent.parent / model_dir
    file_cfg = cfg["live"].get("streaming_files", {})
    files = {
        "tokens": model_dir / file_cfg.get("tokens", "tokens.txt"),
        "encoder": model_dir / file_cfg.get("encoder", "encoder.int8.onnx"),
        "decoder": model_dir / file_cfg.get("decoder", "decoder.int8.onnx"),
        "joiner": model_dir / file_cfg.get("joiner", "joiner.int8.onnx"),
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "streaming model is missing — run: "
            ".venv/bin/python scripts/fetch_streaming_model.py\n  " + "\n  ".join(missing)
        )
    live_cfg = cfg["live"]
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        **{name: str(path) for name, path in files.items()},
        num_threads=live_cfg.get("num_threads", 2),
        provider="cpu",
        enable_endpoint_detection=True,
        # Rule 1 applies before any speech has been decoded. Keep it generous
        # so the recognizer is not reset on the very block where speech begins.
        rule1_min_trailing_silence=max(2.4, live_cfg.get("endpoint_silence_s", 0.8)),
        rule2_min_trailing_silence=live_cfg.get("endpoint_silence_s", 0.8),
        rule3_min_utterance_length=live_cfg.get("endpoint_max_s", 12.0),
        decoding_method=live_cfg.get("decoding_method", "greedy_search"),
    )


def load_speaker_tracker(cfg: dict) -> SpeakerTracker | None:
    """Build the live diarization tracker, or None if disabled/missing.

    Absence degrades to single-speaker S1 rather than failing: attribution is
    an enhancement, and live mode must still run before the one-time model
    download has happened.
    """

    dia = dict(cfg.get("live", {}).get("diarization", {}) or {})
    if not dia.get("enabled", False):
        return None
    model = Path(dia.get("model",
                         "assets/speaker-embedding-en/nemo_en_titanet_small.onnx"))
    if not model.is_absolute():
        model = Path(__file__).resolve().parent.parent / model
    if not model.is_file():
        print("[live] speaker model missing — run scripts/fetch_streaming_model.py"
              " (continuing single-speaker)")
        return None

    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model), num_threads=dia.get("num_threads", 2)))

    def embed(samples: np.ndarray) -> np.ndarray | None:
        if len(samples) < int(0.25 * SR):
            return None
        stream = extractor.create_stream()
        stream.accept_waveform(SR, samples)
        stream.input_finished()
        vec = np.asarray(extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else None

    return SpeakerTracker(
        embed,
        similarity=dia.get("similarity", 0.35),
        max_speakers=dia.get("max_speakers", 6),
        window_s=dia.get("window_s", 1.0),
        hop_s=dia.get("hop_s", 0.25),
        min_span_s=dia.get("min_span_s", 0.4),
        change_below=dia.get("change_below", 0.3),
        merge_at=dia.get("merge_at", 0.5),
    )


def load_sound_event_detector(cfg: dict):
    """Build the non-speech sound tagger, or None if disabled/missing.

    Like speaker attribution, absence is non-fatal: the non-speech lane is an
    enhancement, and live mode must still run before the one-time audio-tagging
    model download has happened.
    """

    from .soundevents import SoundEventDetector

    se = dict(cfg.get("live", {}).get("sound_events", {}) or {})
    if not se.get("enabled", False):
        return None
    root = Path(__file__).resolve().parent.parent
    model = Path(se.get("model", "assets/audio-tagging-en/model.int8.onnx"))
    labels = Path(se.get("labels", "assets/audio-tagging-en/class_labels_indices.csv"))
    model = model if model.is_absolute() else root / model
    labels = labels if labels.is_absolute() else root / labels
    if not model.is_file() or not labels.is_file():
        print("[live] audio-tagging model missing — run scripts/fetch_streaming_model.py"
              " (continuing without the non-speech lane)")
        return None

    import sherpa_onnx

    tagger = sherpa_onnx.AudioTagging(
        sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(
                zipformer=sherpa_onnx.OfflineZipformerAudioTaggingModelConfig(
                    model=str(model)),
                num_threads=se.get("num_threads", 2),
                provider="cpu",
            ),
            labels=str(labels),
            top_k=int(se.get("top_k", 5)),
        )
    )

    def classify(samples: np.ndarray) -> list[tuple[str, float]]:
        stream = tagger.create_stream()
        stream.accept_waveform(SR, samples)
        return [(r.name, float(r.prob)) for r in tagger.compute(stream)]

    return SoundEventDetector(
        classify,
        categories=se.get("categories", {}) or {},
        suppress=se.get("suppress", []) or [],
        window_s=se.get("window_s", 2.0),
        hop_s=se.get("hop_s", 0.5),
        min_conf=se.get("min_conf", 0.35),
        end_conf=se.get("end_conf", 0.20),
        hold_s=se.get("hold_s", 0.6),
        min_gap_s=se.get("min_gap_s", 0.8),
    )


def _is_durable_record(ev: dict) -> bool:
    """Which events are written to live_events.jsonl (durable text + haptics).

    Durable speech words, and each finalized non-speech sound (its `end` event,
    which carries the settled duration). Provisional/hypothesis/level/cue and a
    sound's transient `start` are display-only.
    """

    kind = ev.get("type", "word")
    if kind == "word":
        return ev.get("final", True)
    if kind == "sound":
        return ev.get("state") == "end"
    return False


def load_endpoint_verifier(cfg: dict) -> EndpointVerifier:
    """Load the configured offline phrase verifier with no network fallback."""

    import sherpa_onnx

    model_dir = Path(cfg["live"]["verifier_model_dir"])
    if not model_dir.is_absolute():
        model_dir = Path(__file__).resolve().parent.parent / model_dir
    files = {
        "tokens": model_dir / "tokens.txt",
        "encoder": model_dir / "encoder.int8.onnx",
        "decoder": model_dir / "decoder.int8.onnx",
        "joiner": model_dir / "joiner.int8.onnx",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "endpoint verifier is missing — run: "
            ".venv/bin/python scripts/fetch_streaming_model.py --offline-verifier\n  "
            + "\n  ".join(missing)
        )
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        **{name: str(path) for name, path in files.items()},
        num_threads=cfg["live"].get("verifier_num_threads", 4),
        provider="cpu",
        model_type="nemo_transducer",
        decoding_method=cfg["live"].get(
            "verifier_decoding_method", "modified_beam_search"
        ),
        max_active_paths=cfg["live"].get("verifier_max_active_paths", 4),
    )
    return EndpointVerifier(recognizer)


# ---------------------------------------------------------------------------
# SSE broadcast server
# ---------------------------------------------------------------------------

class Broadcaster:
    """Bounded SSE fan-out with durable replay on browser reconnect.

    A stalled tab is disconnected instead of accumulating an unbounded queue.
    EventSource reconnects with ``Last-Event-ID`` and receives the retained
    committed/verified transcript plus the most recent hypothesis snapshot.
    """

    def __init__(self, max_queue: int = 256, history_limit: int = 1024):
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._max_queue = max_queue
        self._next_id = 1
        self._history: deque[tuple[int, bytes]] = deque(maxlen=history_limit)
        self._latest_hypothesis: tuple[int, bytes] | None = None

    def register(self, last_event_id: int | None = None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._max_queue)
        after = max(0, last_event_id or 0)
        with self._lock:
            replay = [(event_id, chunk) for event_id, chunk in self._history
                      if event_id > after]
            if (self._latest_hypothesis is not None and
                    self._latest_hypothesis[0] > after):
                replay.append(self._latest_hypothesis)
            replay = sorted(dict(replay).items())[-self._max_queue:]
            for _, chunk in replay:
                q.put_nowait(chunk)
            self._clients.add(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, obj: dict) -> None:
        with self._lock:
            event_id = self._next_id
            self._next_id += 1
            data = (f"id: {event_id}\n"
                    f"data: {json.dumps(obj, ensure_ascii=False)}\n\n").encode()
            event_type = obj.get("type", "word")
            durable = event_type in {"commit", "verification"} or (
                event_type == "word" and obj.get("final", True)
            ) or (event_type == "sound" and obj.get("state") == "end")
            if durable:
                self._history.append((event_id, data))
            elif event_type == "hypothesis":
                self._latest_hypothesis = (event_id, data)
            clients = list(self._clients)
            for q in clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    # Force a clean EventSource reconnect. The browser's last
                    # acknowledged id lets the retained transcript fill the gap.
                    self._clients.discard(q)
                    try:
                        while True:
                            q.get_nowait()
                    except queue.Empty:
                        pass
                    q.put_nowait(None)


def make_handler(page_path: Path, broadcaster: Broadcaster):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                # Browsers close long-lived EventSource sockets during reload
                # and shutdown; this is a normal client lifecycle, not a
                # production server error worth a traceback.
                pass

        def log_message(self, *a):  # keep the console for caption output
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html", "/live.html"):
                body = page_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    last_event_id = int(self.headers.get("Last-Event-ID", "0"))
                except ValueError:
                    last_event_id = 0
                q = broadcaster.register(last_event_id)
                try:
                    self.wfile.write(b"retry: 500\n: connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            chunk = q.get(timeout=15)
                        except queue.Empty:
                            chunk = b": keepalive\n\n"
                        if chunk is None:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    broadcaster.unregister(q)
            else:
                self.send_error(404)

    return Handler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_live_stack(cfg: dict):
    """Load the four live models and warm them up before capture starts.

    Measured: the pool saves little (~0.7 s of 8.3 s — the ONNX session
    constructors hold the GIL, so loads mostly serialize), and that is fine.
    The point is what happens around it: the first-inference initialization
    (~1.3 s) is paid here on silence instead of on the user's first spoken
    words, and the server/page come up BEFORE this runs, with a boot status,
    so "listening" on screen marks the moment speech actually starts being
    captured.
    """

    live_cfg = cfg["live"]
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="load") as pool:
        accurate = pool.submit(load_streaming_recognizer, cfg)
        draft = pool.submit(
            load_streaming_recognizer, cfg,
            live_cfg.get("draft_model_dir", live_cfg["streaming_model_dir"]))
        verifier = pool.submit(load_endpoint_verifier, cfg)
        tracker = pool.submit(load_speaker_tracker, cfg)
        detector = pool.submit(load_sound_event_detector, cfg)
        accurate, draft = accurate.result(), draft.result()
        verifier, tracker = verifier.result(), tracker.result()
        detector = detector.result()
    warm = np.zeros(SR // 2, dtype=np.float32)
    for recognizer in (accurate, draft):
        stream = recognizer.create_stream()
        stream.accept_waveform(SR, warm)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
    verifier.transcribe(warm)
    if tracker is not None:
        tracker.embed(np.zeros(SR, dtype=np.float32))
    if detector is not None:
        # Pay first-inference init here on silence; then drop the warm buffer so
        # the real stream is not classified against 2 s of leading zeros.
        detector.feed(np.zeros(2 * SR, dtype=np.float32), 0.0)
        detector.reset()
    return accurate, draft, verifier, tracker, detector


def _start_server(page: Path, port: int, open_browser: bool):
    broadcaster = Broadcaster()
    handler = make_handler(page, broadcaster)
    server = None
    for p in range(port, port + 10):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", p), handler)
            port = p
            break
        except OSError:
            print(f"[live] port {p} busy, trying {p + 1}")
    if server is None:
        raise SystemExit(f"no free port in {port}..{port + 9} — pass --port")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"[live] serving {url}")
    if open_browser:
        webbrowser.open(url)
    return server, broadcaster


def run_live(args, cfg: dict, device: str) -> None:
    live_cfg = cfg["live"]
    if getattr(args, "list_devices", False):
        print("[live] input devices:\n" + list_input_devices())
        return
    lang = getattr(args, "lang", None) or live_cfg["lang"]
    port = getattr(args, "port", None) or live_cfg["port"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # CLI overrides sit on top of config.yaml so a booth operator can pin the
    # gain without editing the tracked configuration.
    gain_cfg = dict(live_cfg.get("input_gain", {}) or {})
    if getattr(args, "no_gain", False):
        gain_cfg["enabled"] = False
    if getattr(args, "gain", None) is not None:
        gain_cfg.update(enabled=True, initial_gain_db=args.gain,
                        min_gain_db=args.gain, max_gain_db=args.gain)
    cfg = {**cfg, "live": {**live_cfg, "input_gain": gain_cfg}}
    live_cfg = cfg["live"]

    from .livepage import render_live
    page = Path(render_live(cfg, out))

    stop = threading.Event()
    realtime = not os.environ.get("AUTOCWI_FAST")
    mic_device = getattr(args, "device", None)
    if mic_device is not None and str(mic_device).lstrip("-").isdigit():
        mic_device = int(mic_device)
    source_file = getattr(args, "file", None)
    if getattr(args, "sample", False) and not source_file:
        source_file = sample_clip_path()
        print(f"[live] streaming bundled sample: {Path(source_file).name}")
    # --once processes to EOF and exits; a loop would never reach EOF.
    loop = getattr(args, "loop", False) and not getattr(args, "once", False)
    if loop and source_file:
        print("[live] looping clip — Ctrl-C to quit")
    blocks = (
        file_blocks(source_file, realtime=realtime, loop=loop)
        if source_file
        else mic_blocks(stop, device=mic_device)
    )
    whisper_model = getattr(args, "whisper", None)
    if whisper_model:
        from faster_whisper import WhisperModel

        ct2_device = "cuda" if device == "cuda" else "cpu"
        model = WhisperModel(whisper_model, device=ct2_device,
                             compute_type="float16" if ct2_device == "cuda" else "int8")
        print(f"[live] legacy whisper-{whisper_model} ready (lang={lang})")
        events = word_events(utterances(blocks, live_cfg), model, lang, cfg)
    else:
        if lang != "en":
            raise SystemExit(
                "the bundled streaming model is English-only; use --lang en"
            )
        headless = bool(getattr(args, "once", False))
        server = broadcaster = None
        if not headless:
            # Page first, models second: the browser shows "loading models"
            # progress instead of a dead tab, and capture starts only after
            # warm-up — so "listening" on screen means actually listening.
            server, broadcaster = _start_server(
                page, port, not getattr(args, "no_open", False))
            broadcaster.publish({"type": "boot", "stage": "loading models"})
        t_load = time.perf_counter()
        model, draft_model, verifier, tracker, detector = _load_live_stack(cfg)
        print(f"[live] local ASR ready in {time.perf_counter() - t_load:.1f}s: "
              "160ms draft + 1120ms accurate stream + Parakeet endpoint "
              "verifier (lang=en, CPU)"
              + (" + speaker attribution" if tracker else "")
              + (" + non-speech sound lane" if detector else ""))
        if broadcaster is not None:
            broadcaster.publish({"type": "boot", "stage": "listening"})
        events = streaming_events(
            blocks, model, cfg, draft_model, verifier=verifier,
            speaker_tracker=tracker, sound_detector=detector,
        )
    events_path = out / "live_events.jsonl"

    if getattr(args, "once", False):  # headless: process source to EOF, no server
        with open(events_path, "w", encoding="utf-8") as f:
            n = 0
            for ev in events:
                if _is_durable_record(ev):
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    n += 1
        print(f"[live] {n} durable events -> {events_path}")
        return

    if server is None:  # legacy whisper path still starts its server here
        server, broadcaster = _start_server(
            page, port, not getattr(args, "no_open", False))

    try:
        with open(events_path, "w", encoding="utf-8") as f:
            for ev in events:
                broadcaster.publish(ev)
                if _is_durable_record(ev):
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    f.flush()
        print("[live] audio source finished — server still running (Ctrl-C to quit)")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        print("\n[live] stopped")
