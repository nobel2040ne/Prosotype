"""Deterministic acoustic conditions applied to the standard eval set.

These are CONDITIONS, not a second benchmark: the same FLEURS audio degraded in
reproducible ways so a robustness regression shows up as a number on the one
standard set. Every transform is seeded by the caller.
"""

from __future__ import annotations

import numpy as np

SR = 16_000


def add_noise(audio: np.ndarray, snr_db: float,
              rng: np.random.Generator) -> np.ndarray:
    signal_rms = max(float(np.sqrt(np.mean(audio**2))), 1e-6)
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    noise *= signal_rms / (10 ** (snr_db / 20)) / max(
        float(np.sqrt(np.mean(noise**2))), 1e-6
    )
    return np.clip(audio + noise, -1.0, 1.0).astype(np.float32)


def room_noise(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Deterministic small-room echoes plus 14 dB SNR background noise."""

    impulse = np.zeros(int(0.22 * SR), dtype=np.float32)
    impulse[[0, int(.055 * SR), int(.12 * SR), int(.20 * SR)]] = [
        1.0, 0.34, 0.18, 0.08,
    ]
    reverberant = np.convolve(audio, impulse, mode="full")[:len(audio)]
    peak = max(float(np.max(np.abs(reverberant))), 1e-6)
    reverberant = reverberant * min(1.0, 0.92 / peak)
    return add_noise(reverberant.astype(np.float32), 14.0, rng)


def quiet_noise(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Speech attenuated 22 dB over an absolute -68 dBFS device floor.

    This is a LEVEL test -- can the pipeline recover a quiet talker on a quiet
    device -- which is `InputGain`'s job and is what the name has always
    claimed.

    **The floor was -52 dBFS until 2026-08-05 and that made it an SNR test at
    roughly 0 dB, i.e. impossible by construction.** MEASURED on FLEURS ko:
    speech frames sit at a p90 of -28 to -31 dBFS, so 22 dB down puts them at
    -50 to -53 dBFS -- at or BELOW a -52 dBFS noise floor, an effective SNR of
    **-1.4 to +1.8 dB**. Gain cannot rescue that, because it lifts the noise
    equally: instrumented, `InputGain` correctly reached 25.8 dB and the
    recognizer still scored **73.65% CER** where the same audio clean scores
    10.54% and at a true 14 dB SNR (`room_noise`) scores 15.94%. That number
    was read as "Korean collapses on a quiet mic" and it was an artifact of
    this line.
    `attenuated()` below already guarded against exactly this and says so; the
    two conditions were simply written with different care. -68 dBFS keeps the
    quietest speech ~15 dB clear of the floor, so the condition measures level
    handling again rather than re-testing `room_noise`.

    Re-measure English (`--lang en --stress`) after touching this: the stress
    matrix totals on both languages move.
    """

    quiet = audio * (10 ** (-22 / 20))
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    noise *= 10 ** (-68 / 20) / max(float(np.sqrt(np.mean(noise**2))), 1e-6)
    return np.clip(quiet + noise, -1.0, 1.0).astype(np.float32)


def attenuated(db: float):
    """Speech at `db` over a fixed -78 dBFS device floor.

    The floor stays well below the quietest condition or the sweep stops
    measuring level handling and becomes an SNR test: at -40 dB over a -60 dBFS
    floor the speech and the noise are the same size and no gain recovers it.
    """

    def transform(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        quiet = audio * (10 ** (db / 20))
        noise = rng.standard_normal(len(audio)).astype(np.float32)
        noise *= 10 ** (-78 / 20) / max(
            float(np.sqrt(np.mean(noise**2))), 1e-6
        )
        return np.clip(quiet + noise, -1.0, 1.0).astype(np.float32)

    return transform


def time_stretch(rate: float):
    def transform(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        import librosa

        return librosa.effects.time_stretch(y=audio, rate=rate).astype(np.float32)

    return transform


def clean(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return audio


def build(stress: bool = False, quiet_sweep: bool = False) -> list[tuple]:
    """Return [(label, transform)] for the requested condition set."""

    if quiet_sweep:
        return [(f"attenuated-{db}db", attenuated(db))
                for db in (0, -10, -20, -30, -40)]
    conditions = [("clean", clean)]
    if stress:
        conditions.extend([
            ("room-noise-14db", room_noise),
            ("quiet-device", quiet_noise),
            ("fast-1.15x", time_stretch(1.15)),
        ])
    return conditions
