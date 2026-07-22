"""Prosody extraction on synthetic audio with known ground truth.

Slower than the other tests (loads librosa/parselmouth) but still fully
offline — no model downloads."""

import numpy as np
import pytest
import soundfile as sf

from autocwi.prosody import prosody
from autocwi.schema import WordTiming

SR = 16_000


@pytest.fixture(scope="module")
def tone_wav(tmp_path_factory):
    """0-1 s: 150 Hz tone at amp 0.1 | 1-2 s: 300 Hz tone at amp 0.5 | 2-3 s: silence."""
    t1 = np.linspace(0, 1, SR, endpoint=False)
    quiet_low = 0.1 * np.sin(2 * np.pi * 150 * t1)
    loud_high = 0.5 * np.sin(2 * np.pi * 300 * t1)
    silence = np.zeros(SR)
    y = np.concatenate([quiet_low, loud_high, silence])
    path = tmp_path_factory.mktemp("audio") / "tones.wav"
    sf.write(path, y, SR)
    return path


WORDS = [
    WordTiming(text="low", start=0.1, end=0.9, conf=1.0),
    WordTiming(text="high", start=1.1, end=1.9, conf=1.0),
    WordTiming(text="none", start=2.1, end=2.9, conf=1.0),
]


def test_pitch_recovered_within_tolerance(tone_wav):
    feats = prosody(tone_wav, WORDS)
    assert feats[0].pitch_hz == pytest.approx(150, rel=0.03)
    assert feats[1].pitch_hz == pytest.approx(300, rel=0.03)
    assert feats[2].pitch_hz == 0.0
    assert feats[2].voiced_frac == 0.0


def test_louder_tone_has_higher_db(tone_wav):
    feats = prosody(tone_wav, WORDS)
    # amp 0.5 vs 0.1 = 14 dB difference
    assert feats[1].loudness_db - feats[0].loudness_db == pytest.approx(14.0, abs=1.0)
    assert feats[2].loudness_db <= -60  # silence


def test_pure_tones_are_voiced(tone_wav):
    feats = prosody(tone_wav, WORDS)
    assert feats[0].voiced_frac > 0.8
    assert feats[1].voiced_frac > 0.8
