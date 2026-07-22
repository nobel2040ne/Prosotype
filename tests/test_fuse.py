from autocwi.fuse import fuse
from autocwi.schema import DiarSegment, Media, ProsodyFeature, WordTiming

CONFIG = {
    "palette": ["#56B4E9", "#E69F00", "#33C489"],
    "normalization": {"low_percentile": 0, "high_percentile": 100, "min_voiced_frac": 0.2},
    "mapping": {
        "loudness_to": {"axis": "size", "min": 24, "max": 56},
        "pitch_to": {"axis": "wght", "min": 300, "max": 800, "invert": True},
        "speaker_to": "color",
    },
}


def build(loud_s1, loud_s2):
    """Two speakers, two words each, with given loudness_db values."""
    words, segments, features = [], [], []
    t = 0.0
    for spk, louds in (("S1", loud_s1), ("S2", loud_s2)):
        seg_start = t
        for i, db in enumerate(louds):
            words.append(WordTiming(text=f"{spk}w{i}", start=t, end=t + 0.4, conf=0.9))
            features.append(ProsodyFeature(loudness_db=db, pitch_hz=150 + 10 * i, voiced_frac=0.8))
            t += 0.5
        segments.append(DiarSegment(speaker=spk, start=seg_start, end=t))
    media = Media(path="x.mp4", duration=t, fps=None)
    return fuse(words, segments, features, media, CONFIG)


def test_normalization_is_per_speaker():
    # S1 is a loud speaker (-25..-15 dB), S2 quiet (-45..-35 dB).
    spec = build(loud_s1=[-25, -15], loud_s2=[-45, -35])
    by_spk = {}
    for w in spec.words:
        by_spk.setdefault(w.speaker, []).append(w.loudness)
    # Each speaker spans their OWN full range: both get 0.0 and 1.0.
    assert by_spk["S1"] == [0.0, 1.0]
    assert by_spk["S2"] == [0.0, 1.0]
    # Same raw dB, different normalized value across speakers:
    spec2 = build(loud_s1=[-35, -15], loud_s2=[-45, -35])
    vals = {w.text: w.loudness for w in spec2.words}
    assert vals["S1w0"] == 0.0 and vals["S2w1"] == 1.0  # both are -35 dB raw


def test_unvoiced_word_gets_neutral_pitch():
    words = [WordTiming(text="a", start=0, end=0.4, conf=0.9),
             WordTiming(text="b", start=0.5, end=0.9, conf=0.9),
             WordTiming(text="c", start=1.0, end=1.4, conf=0.9)]
    segments = [DiarSegment(speaker="S1", start=0, end=1.5)]
    features = [ProsodyFeature(loudness_db=-20, pitch_hz=100, voiced_frac=0.9),
                ProsodyFeature(loudness_db=-20, pitch_hz=50, voiced_frac=0.05),  # unvoiced
                ProsodyFeature(loudness_db=-20, pitch_hz=200, voiced_frac=0.9)]
    spec = fuse(words, segments, features, Media(path="x", duration=2), CONFIG)
    assert spec.words[1].pitch == 0.5
    assert spec.words[0].pitch == 0.0 and spec.words[2].pitch == 1.0


def test_degenerate_range_collapses_to_half():
    spec = build(loud_s1=[-20, -20], loud_s2=[-30, -25])
    assert [w.loudness for w in spec.words if w.speaker == "S1"] == [0.5, 0.5]


def test_deterministic_palette_by_first_appearance():
    spec = build(loud_s1=[-20, -10], loud_s2=[-30, -25])
    assert spec.speakers["S1"].color == "#56B4E9"
    assert spec.speakers["S2"].color == "#E69F00"


def test_raw_values_preserved():
    spec = build(loud_s1=[-25, -15], loud_s2=[-45, -35])
    assert spec.words[0].loudness_db == -25.0
    assert spec.words[0].pitch_hz == 150.0
