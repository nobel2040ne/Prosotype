"""Per-word prosody: RMS loudness (librosa) + F0 (parselmouth / Praat).

Analysis is restricted to ASR word spans, so no separate VAD is needed."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .schema import ProsodyFeature, WordTiming

SILENCE_DB = -80.0  # floor for empty/silent spans


def prosody(
    wav_path: str | Path,
    words: list[WordTiming],
    pitch_floor_hz: float = 75.0,
    pitch_ceiling_hz: float = 500.0,
) -> list[ProsodyFeature]:
    import librosa
    import parselmouth

    y, sr = librosa.load(str(wav_path), sr=None, mono=True)

    snd = parselmouth.Sound(str(wav_path))
    # Cross-correlation method: better for intonation analysis than ac (Praat docs).
    pitch = snd.to_pitch_cc(pitch_floor=pitch_floor_hz, pitch_ceiling=pitch_ceiling_hz)
    f0_times = pitch.xs()
    f0_values = pitch.selected_array["frequency"]  # 0.0 where unvoiced

    features: list[ProsodyFeature] = []
    for w in words:
        i0, i1 = int(w.start * sr), min(int(w.end * sr), len(y))
        span = y[i0:i1]
        if len(span) == 0:
            features.append(ProsodyFeature(loudness_db=SILENCE_DB, pitch_hz=0.0, voiced_frac=0.0))
            continue

        rms_frames = librosa.feature.rms(y=span)[0]
        rms = float(np.mean(rms_frames))
        loudness_db = 20 * np.log10(max(rms, 1e-8))

        mask = (f0_times >= w.start) & (f0_times <= w.end)
        f0_span = f0_values[mask]
        voiced = f0_span[f0_span > 0]
        pitch_hz = float(np.median(voiced)) if len(voiced) else 0.0
        voiced_frac = float(len(voiced) / len(f0_span)) if len(f0_span) else 0.0

        features.append(
            ProsodyFeature(
                loudness_db=round(max(loudness_db, SILENCE_DB), 2),
                pitch_hz=round(pitch_hz, 2),
                voiced_frac=round(voiced_frac, 3),
            )
        )
    return features
