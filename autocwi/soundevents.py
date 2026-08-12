"""Non-speech sound detection for the caption non-speech lane.

The recognizers transcribe SPEECH; a Deaf/HoH viewer also needs to know when
the room laughs, applauds, when music plays or a phone rings. An AudioSet
tagger supplies per-window class probabilities; this is the model-free half
that turns them into stable caption events, so it stays unit-testable with a
synthetic classifier and never imports sherpa-onnx.

Two jobs. **Categorise** AudioSet's 527 leaves into four buckets, mapped as
data in `config.yaml` with a `suppress` list for the Speech classes the ASR
owns. **De-bounce** into segments: the tagger fires every ~0.5s, so each
category runs its own open/sustain/close machine — laughter can land on top of
running music, and each real sound produces exactly one start and one end.
"""

from __future__ import annotations

from typing import Callable, Iterable

import numpy as np

SR = 16_000

# Fixed iteration order; also the `category` Literal in schema.SoundEvent.
CATEGORIES = ("vocal", "reaction", "music", "environmental")


class SoundEventDetector:
    """Turn a windowed audio-tagging classifier into de-bounced sound events.

    Parameters
    ----------
    classify:
        ``samples -> [(display_label, prob), ...]`` for one window, sorted
        descending by ``prob`` (the AudioSet top-k). Injected so the model
        stays out of this module.
    categories:
        ``{category: [substring, ...]}`` from config; a class label is assigned
        to the first category whose substring it contains (case-insensitive).
    suppress:
        AudioSet labels to ignore outright (the Speech classes the ASR owns).
    window_s / hop_s:
        Classify the trailing ``window_s`` of audio once every ``hop_s``.
    min_conf:
        A category must reach this prob to OPEN a segment.
    end_conf:
        ...and stay above this to sustain it (hysteresis: end_conf < min_conf
        so a sound flickering around the open threshold is not chopped up).
    hold_s:
        Keep a segment open this long after it last cleared ``end_conf`` — a
        cough between two laughs should not split the laughter in two.
    min_gap_s:
        Refuse to re-open the same category within this long of closing it.
    """

    def __init__(
        self,
        classify: Callable[[np.ndarray], list[tuple[str, float]]],
        *,
        categories: dict[str, list[str]],
        suppress: Iterable[str] = (),
        window_s: float = 2.0,
        hop_s: float = 0.5,
        min_conf: float = 0.30,
        end_conf: float = 0.18,
        hold_s: float = 0.6,
        min_gap_s: float = 0.8,
        sample_rate: int = SR,
    ) -> None:
        self._classify = classify
        # Pre-lowercase the substring table and suppress set once.
        self._categories = {
            cat: [s.lower() for s in subs]
            for cat, subs in categories.items() if cat in CATEGORIES
        }
        self._suppress = {s.lower() for s in suppress}
        self._sr = sample_rate
        self._win_len = max(1, int(window_s * sample_rate))
        self._hop_len = max(1, int(hop_s * sample_rate))
        # Need a meaningful amount of audio before the first classify, or a
        # single opening block would be tagged against near-silence.
        self._min_len = max(self._hop_len, int(0.4 * sample_rate))
        self._min_conf = min_conf
        self._end_conf = min(end_conf, min_conf)
        self._hold_s = hold_s
        self._min_gap_s = min_gap_s

        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_end_t = 0.0
        self._since_hop = 0
        self._active: dict[str, dict] = {}      # category -> open segment
        self._last_close: dict[str, float] = {}  # category -> when it last closed

    # -- categorisation ----------------------------------------------------
    def _suppressed(self, label: str) -> bool:
        low = label.lower()
        return any(s in low for s in self._suppress)

    def categorize(self, label: str) -> str | None:
        """Public for tests: AudioSet display label -> coarse category or None."""
        if self._suppressed(label):
            return None
        low = label.lower()
        for cat, subs in self._categories.items():
            if any(s in low for s in subs):
                return cat
        return None

    def _category_scores(self, raw: list[tuple[str, float]]) -> dict[str, tuple[str, float]]:
        scores: dict[str, tuple[str, float]] = {}
        for label, prob in raw:
            cat = self.categorize(label)
            if cat is None:
                continue
            if cat not in scores or prob > scores[cat][1]:
                scores[cat] = (label, prob)
        return scores

    # -- streaming ---------------------------------------------------------
    def feed(self, samples: np.ndarray, source_end: float) -> list[dict]:
        """Add captured audio (TRUE level) ending at ``source_end`` seconds.

        Returns any ``start``/``end`` sound events crossed on this hop.
        """
        if len(samples):
            self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32)])
            if len(self._buf) > self._win_len:
                self._buf = self._buf[-self._win_len:]
            self._buf_end_t = source_end
            self._since_hop += len(samples)
        if self._since_hop < self._hop_len or len(self._buf) < self._min_len:
            return []
        self._since_hop = 0
        raw = self._classify(self._buf)
        return self._update(self._category_scores(raw), self._buf_end_t)

    def _update(self, scores: dict[str, tuple[str, float]], t: float) -> list[dict]:
        out: list[dict] = []
        for cat in CATEGORIES:
            hit = scores.get(cat)                       # (label, prob) | None
            seg = self._active.get(cat)
            if seg is not None:
                if hit is not None and hit[1] >= self._end_conf:
                    seg["end"] = t
                    seg["last_seen"] = t
                    if hit[1] > seg["conf"]:
                        seg["conf"] = hit[1]
                        seg["label"] = hit[0]           # keep the strongest label
                elif t - seg["last_seen"] >= self._hold_s:
                    out.append(self._emit(seg, "end"))
                    self._active.pop(cat, None)
                    self._last_close[cat] = seg["end"]
                    seg = None
            if seg is None and hit is not None and hit[1] >= self._min_conf:
                if t - self._last_close.get(cat, -1e9) >= self._min_gap_s:
                    seg = {"label": hit[0], "category": cat,
                           "start": t, "end": t, "conf": hit[1], "last_seen": t}
                    self._active[cat] = seg
                    out.append(self._emit(seg, "start"))
        return out

    def reset(self) -> None:
        """Drop all buffered audio and open segments (used after warm-up)."""
        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_end_t = 0.0
        self._since_hop = 0
        self._active.clear()
        self._last_close.clear()

    def finish(self) -> list[dict]:
        """Close every still-open segment (end of stream)."""
        out = [self._emit(seg, "end") for seg in self._active.values()]
        for cat, seg in list(self._active.items()):
            self._last_close[cat] = seg["end"]
        self._active.clear()
        return out

    @staticmethod
    def _emit(seg: dict, state: str) -> dict:
        return {
            "type": "sound",
            "state": state,                 # "start" -> chip appears; "end" -> durable
            "kind": "nonspeech",            # marks it for the durable log / haptics
            "label": seg["label"],
            "category": seg["category"],
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "conf": round(float(seg["conf"]), 3),
        }
