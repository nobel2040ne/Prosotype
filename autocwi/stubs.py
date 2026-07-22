"""Deterministic placeholder stages (--stub) so the pipeline runs end-to-end
without any model downloads. Useful for inspecting the CaptionSpec contract and
for smoke-testing the renderer."""

from __future__ import annotations

import numpy as np

from .schema import DiarSegment, ProsodyFeature, WordTiming

_SENTENCES = [
    ["the", "presentation", "looks", "great"],
    ["yes", "I", "can't", "wait", "to", "see", "it"],
]


def stub_transcribe(duration: float) -> list[WordTiming]:
    """Two 'utterances' of known words, evenly spread over the first and second
    half of the clip with a gap between them."""
    words: list[WordTiming] = []
    half = duration / 2
    for k, sentence in enumerate(_SENTENCES):
        t0, t1 = k * half + 0.3, (k + 1) * half - 0.3
        step = (t1 - t0) / len(sentence)
        for i, text in enumerate(sentence):
            words.append(
                WordTiming(
                    text=text,
                    start=round(t0 + i * step, 3),
                    end=round(t0 + (i + 0.85) * step, 3),
                    conf=0.9,
                )
            )
    return words


def stub_diarize(duration: float) -> list[DiarSegment]:
    half = duration / 2
    return [
        DiarSegment(speaker="S1", start=0.0, end=half),
        DiarSegment(speaker="S2", start=half, end=duration),
    ]


def stub_prosody(words: list[WordTiming], seed: int = 42) -> list[ProsodyFeature]:
    rng = np.random.default_rng(seed)
    features = []
    for i, _ in enumerate(words):
        features.append(
            ProsodyFeature(
                loudness_db=round(-30 + 10 * np.sin(i * 1.1) + rng.normal(0, 1.5), 2),
                pitch_hz=round(180 + 60 * np.cos(i * 0.9) + rng.normal(0, 8), 2),
                voiced_frac=round(float(np.clip(rng.normal(0.8, 0.1), 0, 1)), 3),
            )
        )
    return features
