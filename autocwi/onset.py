"""Low-latency phoneme onset hints for live captions.

The authoritative recognizers intentionally remain word/subword models.  They
are accurate, but a drawn-out first phone can precede their first token by more
than a second. This optional sidecar publishes a conservative, monotonic phone
prefix (for example ``H`` -> ``He`` -> ``Hel``) and duration updates while the
sound is held. The browser later revises that same word node from the normal
Nemotron/Parakeet stream; the hint never owns durable transcript text.

The current checkpoint is a proof-of-behaviour model, not a new transcript
model.  It is deliberately isolated behind this small interface so a
cache-aware character/phone CTC export can replace it without touching the
caption renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


SR = 16_000

# A phone cannot determine English spelling in general ("phone", "hour",
# "knife").
PHONE_GRAPHEMES = {
    "aa": "A",
    "ae": "A",
    "ah": "A",
    "ao": "O",
    "aw": "O",
    "ax": "A",
    "ax-h": "A",
    "axr": "A",
    "ay": "I",
    "b": "B",
    "ch": "Ch",
    "d": "D",
    "dh": "Th",
    "eh": "E",
    "er": "E",
    "ey": "A",
    "f": "F",
    "g": "G",
    "hh": "H",
    "hv": "H",
    "ih": "I",
    "ix": "I",
    "iy": "E",
    "jh": "J",
    "k": "K",
    "l": "L",
    "m": "M",
    "n": "N",
    "ng": "N",
    "ow": "O",
    "oy": "O",
    "p": "P",
    "r": "R",
    "s": "S",
    "sh": "Sh",
    "t": "T",
    "th": "Th",
    "uh": "U",
    "uw": "U",
    "ux": "U",
    "v": "V",
    "w": "W",
    "y": "Y",
    "z": "Z",
    "zh": "Zh",
}

_NON_SPEECH_PHONES = {
    "bcl",
    "dcl",
    "epi",
    "gcl",
    "kcl",
    "pau",
    "pcl",
    "q",
    "tcl",
}


def _rms_db(samples: np.ndarray) -> float:
    if not len(samples):
        return -160.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return float(20.0 * np.log10(max(rms, 1e-8)))


@dataclass(frozen=True)
class PhoneCandidate:
    phone: str
    grapheme: str
    confidence: float


class PhonemeOnsetDetector:
    """Emit a monotonic speculative prefix at the start of a speech turn."""

    def __init__(self, cfg: dict, model_dir: str | Path):
        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        onset_cfg = dict(cfg.get("live", {}).get("onset_prefix", {}) or {})
        self.model_dir = Path(model_dir)
        self.hop_samples = max(
            1, int(round(float(onset_cfg.get("hop_s", 0.08)) * SR))
        )
        self.min_audio_samples = max(
            self.hop_samples,
            int(round(float(onset_cfg.get("min_audio_s", 0.22)) * SR)),
        )
        self.right_context_samples = max(
            0,
            int(
                round(
                    float(onset_cfg.get("synthetic_right_context_s", 0.24)) * SR
                )
            ),
        )
        self.max_audio_samples = max(
            self.min_audio_samples,
            int(round(float(onset_cfg.get("max_analysis_s", 3.0)) * SR)),
        )
        self.activation_db = float(onset_cfg.get("activation_db", -50.0))
        self.silence_db = float(onset_cfg.get("silence_db", -54.0))
        self.reset_samples = max(
            self.hop_samples,
            int(round(float(onset_cfg.get("reset_s", 0.45)) * SR)),
        )
        self.min_confidence = float(onset_cfg.get("min_confidence", 0.60))
        self.max_prefix_chars = max(
            1, int(onset_cfg.get("max_prefix_chars", 8))
        )
        self.prefix_stability_updates = max(
            1, int(onset_cfg.get("prefix_stability_updates", 2))
        )
        self.sustain_update_samples = max(
            self.hop_samples,
            int(round(float(onset_cfg.get("sustain_update_s", 0.12)) * SR)),
        )

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(
            str(self.model_dir), local_files_only=True
        )
        self.model = AutoModelForCTC.from_pretrained(
            str(self.model_dir), local_files_only=True
        ).eval()
        self.pad_id = int(self.processor.tokenizer.pad_token_id)

        self._preroll = np.zeros(0, dtype=np.float32)
        self._audio = np.zeros(0, dtype=np.float32)
        self._active = False
        self._suppressed = False
        self._silence_samples = 0
        self._next_decode_samples = self.min_audio_samples
        self._source_start = 0.0
        self._display_candidates: list[PhoneCandidate] = []
        self._candidate_signature: tuple[str, ...] = ()
        self._candidate_hits = 0
        self._text_revision = -1
        self._timing_revision = -1
        self._last_emit_source_end = -1e9

    def warm(self) -> None:
        """Pay framework/kernel initialization before capture begins."""

        warm = np.zeros(
            self.min_audio_samples + self.right_context_samples,
            dtype=np.float32,
        )
        self._decode_candidates(warm)
        self.reset()

    def reset(self) -> None:
        self._preroll = np.zeros(0, dtype=np.float32)
        self._audio = np.zeros(0, dtype=np.float32)
        self._active = False
        self._suppressed = False
        self._silence_samples = 0
        self._next_decode_samples = self.min_audio_samples
        self._display_candidates = []
        self._candidate_signature = ()
        self._candidate_hits = 0
        self._text_revision = -1
        self._timing_revision = -1
        self._last_emit_source_end = -1e9

    def _remember_preroll(self, samples: np.ndarray) -> None:
        keep = max(self.min_audio_samples // 2, self.hop_samples)
        self._preroll = np.concatenate((self._preroll, samples))[-keep:]

    def _decode_candidates(self, samples: np.ndarray) -> list[PhoneCandidate]:
        torch = self.torch
        if self.right_context_samples:
            samples = np.concatenate(
                (
                    samples,
                    np.zeros(self.right_context_samples, dtype=np.float32),
                )
            )
        values = self.processor(
            samples,
            sampling_rate=SR,
            return_tensors="pt",
        ).input_values
        with torch.inference_mode():
            logits = self.model(values).logits[0]
            probabilities = logits.softmax(dim=-1)
            ids = logits.argmax(dim=-1)
            confidences = probabilities.gather(1, ids[:, None]).squeeze(1)

        candidates: list[PhoneCandidate] = []
        previous = None
        for token_id, confidence in zip(ids.tolist(), confidences.tolist()):
            if token_id == previous:
                continue
            previous = token_id
            if token_id == self.pad_id:
                continue
            phone = str(self.processor.tokenizer.convert_ids_to_tokens(token_id))
            if phone in _NON_SPEECH_PHONES:
                continue
            grapheme = PHONE_GRAPHEMES.get(phone)
            if grapheme is None:
                continue
            candidates.append(PhoneCandidate(phone, grapheme, float(confidence)))
            if sum(len(item.grapheme) for item in candidates) >= self.max_prefix_chars:
                break
        return candidates

    def _decode_candidate(self, samples: np.ndarray) -> PhoneCandidate | None:
        """Compatibility wrapper for older local probes."""

        candidates = self._decode_candidates(samples)
        return candidates[0] if candidates else None

    @staticmethod
    def _prefix_text(candidates: list[PhoneCandidate]) -> str:
        raw = "".join(candidate.grapheme for candidate in candidates)
        return raw[:1].upper() + raw[1:].lower()

    def _word_event(
        self,
        *,
        source_end: float,
        utterance: int,
        level_db: float,
    ) -> dict:
        self._timing_revision += 1
        self._last_emit_source_end = source_end
        held_s = max(0.0, source_end - self._source_start)
        confidence = min(
            (candidate.confidence for candidate in self._display_candidates),
            default=0.0,
        )
        return {
            "type": "word",
            "final": False,
            "provisional": True,
            "verified": False,
            "utterance": int(utterance),
            "word_id": f"u{int(utterance)}:w0",
            "text": self._prefix_text(self._display_candidates),
            # Only first paint owns motion. These later timing/text revisions
            # reuse that node and therefore cannot replay its geometry.
            "t": round(source_end, 3),
            "start": 0.0,
            "end": round(max(0.14, held_s), 3),
            "onset_acoustic_t": round(self._source_start, 3),
            "speaker": "S1",
            "speaker_known": False,
            "speaker_status": "unknown",
            "speaker_confidence": 0.0,
            "speaker_revision_id": 0,
            "loudness": 0.5,
            "pitch": 0.5,
            "loudness_db": round(level_db, 2),
            "pitch_hz": 0.0,
            "voiced_frac": 0.0,
            "conf": round(confidence, 3),
            "conf_available": True,
            "text_revision_id": self._text_revision,
            "timing_revision_id": self._timing_revision,
            "src": "onset",
            "onset_phone": self._display_candidates[-1].phone,
            "phone_prefix": [
                candidate.phone for candidate in self._display_candidates
            ],
            "sustain_active": True,
            "sustain_s": round(held_s, 3),
        }

    def feed(
        self,
        samples: np.ndarray,
        source_start: float,
        utterance: int,
        *,
        discontinuity: bool = False,
    ) -> list[dict]:
        """Consume gained recognizer audio and return zero or one SSE event."""

        samples = np.asarray(samples, dtype=np.float32)
        if discontinuity:
            self.reset()
        if not len(samples):
            return []

        level_db = _rms_db(samples)
        if not self._active:
            if level_db < self.activation_db:
                self._remember_preroll(samples)
                return []
            self._active = True
            preroll_s = len(self._preroll) / SR
            self._source_start = max(0.0, float(source_start) - preroll_s)
            self._audio = np.concatenate((self._preroll, samples))
            self._preroll = np.zeros(0, dtype=np.float32)
        elif len(self._audio) < self.max_audio_samples:
            remaining = self.max_audio_samples - len(self._audio)
            self._audio = np.concatenate((self._audio, samples[:remaining]))

        if level_db < self.silence_db:
            self._silence_samples += len(samples)
        else:
            self._silence_samples = 0
        if self._silence_samples >= self.reset_samples:
            self.reset()
            return []

        if self._suppressed:
            return []
        source_end = float(source_start) + len(samples) / SR
        if len(self._audio) >= self.max_audio_samples and not self._display_candidates:
            self._suppressed = True
            return []
        extended = False
        should_decode = (
            len(self._audio) >= self._next_decode_samples
            and len(self._audio) < self.max_audio_samples
        )
        if should_decode:
            self._next_decode_samples = len(self._audio) + self.hop_samples
            candidates: list[PhoneCandidate] = []
            for candidate in self._decode_candidates(self._audio):
                # A weak middle phone is an unknown boundary, not permission to
                # concatenate a confident later phone onto the visible prefix.
                if candidate.confidence < self.min_confidence:
                    break
                candidates.append(candidate)
            display_text = self._prefix_text(self._display_candidates).lower()
            candidate_text = self._prefix_text(candidates).lower()
            compatible = (
                not self._display_candidates
                or candidate_text.startswith(display_text)
            )
            if candidates and compatible:
                target_count = min(len(candidates), len(self._display_candidates) + 1)
                signature = tuple(
                    candidate.phone for candidate in candidates[:target_count]
                )
                if not self._display_candidates:
                    # Even if CTC already sees several phones, expose only the
                    # first now so speech can visibly build H -> He -> Hel.
                    self._display_candidates = candidates[:1]
                    self._text_revision += 1
                    extended = True
                elif target_count > len(self._display_candidates):
                    if signature == self._candidate_signature:
                        self._candidate_hits += 1
                    else:
                        self._candidate_signature = signature
                        self._candidate_hits = 1
                    if self._candidate_hits >= self.prefix_stability_updates:
                        self._display_candidates = candidates[:target_count]
                        self._text_revision += 1
                        self._candidate_signature = ()
                        self._candidate_hits = 0
                        extended = True

        sustain_due = (
            bool(self._display_candidates)
            and source_end - self._last_emit_source_end
            >= self.sustain_update_samples / SR
        )
        if not extended and not sustain_due:
            return []
        word = self._word_event(
            source_end=source_end,
            utterance=utterance,
            level_db=level_db,
        )
        return [
            {
                "type": "hypothesis",
                "utterance": int(utterance),
                "endpoint": False,
                "onset": True,
                "words": [word],
            }
        ]


def load_phoneme_onset_detector(cfg: dict) -> PhonemeOnsetDetector | None:
    """Load the optional local onset checkpoint, degrading cleanly if absent."""

    onset_cfg = dict(cfg.get("live", {}).get("onset_prefix", {}) or {})
    if not onset_cfg.get("enabled", False):
        return None
    model_dir = Path(
        onset_cfg.get("model_dir", "assets/phoneme-onset-en")
    )
    if not model_dir.is_absolute():
        model_dir = Path(__file__).resolve().parent.parent / model_dir
    required = {
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
    }
    missing = sorted(name for name in required if not (model_dir / name).is_file())
    if missing:
        print(
            "[live] onset-prefix model missing; continuing without it — run "
            ".venv/bin/python scripts/fetch_streaming_model.py --onset-only"
        )
        return None
    try:
        return PhonemeOnsetDetector(cfg, model_dir)
    except (ImportError, OSError, ValueError) as exc:
        print(f"[live] onset-prefix unavailable ({exc}); continuing without it")
        return None
