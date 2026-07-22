"""Fusion: words + diarization + prosody -> validated CaptionSpec.

Loudness and pitch are normalized WITHIN each speaker (percentile range from
config), so the mapping reflects that speaker's own dynamic range rather than
absolute differences between voices. Raw dB/Hz values are kept alongside.
"""

from __future__ import annotations

import numpy as np

from .schema import (
    AxisMapping,
    CaptionSpec,
    DiarSegment,
    Mapping,
    Media,
    ProsodyFeature,
    Speaker,
    Word,
    WordTiming,
)


def assign_speakers(words: list[WordTiming], segments: list[DiarSegment]) -> list[str]:
    """Assign each word the speaker whose segments overlap it most.

    Words with zero overlap (diarization gap) snap to the segment whose span is
    closest in time.
    """
    if not segments:
        return ["S1" for _ in words]

    labels: list[str] = []
    for w in words:
        overlap: dict[str, float] = {}
        for seg in segments:
            ov = min(w.end, seg.end) - max(w.start, seg.start)
            if ov > 0:
                overlap[seg.speaker] = overlap.get(seg.speaker, 0.0) + ov
        if overlap:
            labels.append(max(overlap, key=lambda s: overlap[s]))
        else:
            mid = (w.start + w.end) / 2
            nearest = min(
                segments,
                key=lambda seg: 0.0 if seg.start <= mid <= seg.end
                else min(abs(mid - seg.start), abs(mid - seg.end)),
            )
            labels.append(nearest.speaker)
    return labels


def _normalize_per_speaker(
    values: np.ndarray,
    speaker_labels: list[str],
    valid: np.ndarray,
    low_pct: float,
    high_pct: float,
) -> np.ndarray:
    """Map values to 0..1 using each speaker's own [low_pct, high_pct] range.

    Entries where `valid` is False are excluded from range estimation and get 0.5.
    Degenerate ranges (single valid word, flat values) also collapse to 0.5.
    """
    out = np.full(len(values), 0.5)
    for spk in set(speaker_labels):
        idx = np.array([i for i, s in enumerate(speaker_labels) if s == spk])
        vidx = idx[valid[idx]]
        if len(vidx) == 0:
            continue
        lo, hi = np.percentile(values[vidx], [low_pct, high_pct])
        if hi - lo < 1e-9:
            out[vidx] = 0.5
        else:
            out[vidx] = np.clip((values[vidx] - lo) / (hi - lo), 0.0, 1.0)
    return out


def fuse(
    words: list[WordTiming],
    segments: list[DiarSegment],
    features: list[ProsodyFeature],
    media: Media,
    config: dict,
) -> CaptionSpec:
    if len(features) != len(words):
        raise ValueError(
            f"prosody features ({len(features)}) not aligned with words ({len(words)})"
        )

    speaker_labels = assign_speakers(words, segments)

    norm_cfg = config["normalization"]
    low, high = norm_cfg["low_percentile"], norm_cfg["high_percentile"]
    min_voiced = norm_cfg["min_voiced_frac"]

    loud_raw = np.array([f.loudness_db for f in features])
    pitch_raw = np.array([f.pitch_hz for f in features])
    voiced = np.array([f.voiced_frac >= min_voiced and f.pitch_hz > 0 for f in features])

    loudness = _normalize_per_speaker(
        loud_raw, speaker_labels, np.ones(len(words), dtype=bool), low, high
    )
    pitch = _normalize_per_speaker(pitch_raw, speaker_labels, voiced, low, high)

    # Deterministic speaker -> color by order of first appearance.
    # CI Main colors first; CI Supporting colors take over for speakers 7+.
    palette = list(config["palette"]) + list(config.get("palette_support", []))
    speakers: dict[str, Speaker] = {}
    for spk in speaker_labels:
        if spk not in speakers:
            speakers[spk] = Speaker(color=palette[len(speakers) % len(palette)])

    spec_words = [
        Word(
            text=w.text,
            start=w.start,
            end=w.end,
            speaker=speaker_labels[i],
            loudness=round(float(loudness[i]), 4),
            pitch=round(float(pitch[i]), 4),
            loudness_db=round(float(loud_raw[i]), 2),
            pitch_hz=round(float(pitch_raw[i]), 2),
            voiced_frac=round(float(features[i].voiced_frac), 3),
            conf=w.conf,
        )
        for i, w in enumerate(words)
    ]

    m = config["mapping"]
    mapping = Mapping(
        loudness_to=AxisMapping(**m["loudness_to"]),
        pitch_to=AxisMapping(**m["pitch_to"]),
        speaker_to=m["speaker_to"],
    )

    return CaptionSpec(media=media, speakers=speakers, words=spec_words, mapping=mapping)
