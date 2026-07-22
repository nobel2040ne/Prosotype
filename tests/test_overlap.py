from autocwi.fuse import assign_speakers
from autocwi.schema import DiarSegment, WordTiming


def w(text, start, end):
    return WordTiming(text=text, start=start, end=end, conf=0.9)


SEGMENTS = [
    DiarSegment(speaker="S1", start=0.0, end=2.0),
    DiarSegment(speaker="S2", start=2.5, end=5.0),
    DiarSegment(speaker="S1", start=5.5, end=7.0),
]


def test_full_containment():
    assert assign_speakers([w("a", 0.5, 1.0), w("b", 3.0, 3.5)], SEGMENTS) == ["S1", "S2"]


def test_boundary_word_goes_to_max_overlap():
    # 1.8..2.7: 0.2s in S1, 0.2s of gap, 0.2s in S2 — tie broken... make it asymmetric.
    assert assign_speakers([w("a", 1.5, 2.6)], SEGMENTS) == ["S1"]  # 0.5s vs 0.1s
    assert assign_speakers([w("b", 1.9, 3.5)], SEGMENTS) == ["S2"]  # 0.1s vs 1.0s


def test_zero_overlap_snaps_to_nearest_segment():
    # word entirely inside the 2.0-2.5 diarization gap, midpoint 2.3 -> nearer S2
    assert assign_speakers([w("a", 2.2, 2.4)], SEGMENTS) == ["S2"]
    # midpoint 2.1 -> nearer S1
    assert assign_speakers([w("b", 2.05, 2.15)], SEGMENTS) == ["S1"]


def test_speaker_with_multiple_turns_accumulates_overlap():
    # word spans S2's turn and S1's second turn; S1 total overlap wins
    segs = [
        DiarSegment(speaker="S1", start=0.0, end=1.0),
        DiarSegment(speaker="S2", start=1.0, end=1.4),
        DiarSegment(speaker="S1", start=1.4, end=3.0),
    ]
    assert assign_speakers([w("a", 0.5, 2.0)], segs) == ["S1"]


def test_no_segments_defaults_to_s1():
    assert assign_speakers([w("a", 0.0, 1.0)], []) == ["S1"]
