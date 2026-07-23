"""Tests for non-speech sound detection — fully offline, no model loads.

The detector takes an injected classifier callable (as SpeakerTracker takes an
embed callable), so the debounce/categorisation logic is exercised with a
scripted classifier and synthetic audio, never a real ONNX model.
"""

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from autocwi.config import load_config
from autocwi.live import _is_durable_record
from autocwi.schema import CaptionSpec, SoundEvent
from autocwi.soundevents import CATEGORIES, SoundEventDetector

SR = 16_000
HOP_S = 0.5


def _categories():
    """The category map straight from config.yaml (guards the shipped config)."""
    cfg = yaml.safe_load(open("config.yaml"))
    return cfg["live"]["sound_events"]


def _detector(script, **kw):
    """A detector driven by a scripted classifier.

    ``script`` is a list of ``[(label, prob), ...]`` returned one per hop; after
    it is exhausted the classifier returns Speech (suppressed → silence).
    """
    se = _categories()
    it = iter(script)

    def classify(_samples):
        try:
            return next(it)
        except StopIteration:
            return [("Speech", 0.95)]

    params = dict(categories=se["categories"], suppress=se["suppress"],
                  window_s=2.0, hop_s=HOP_S, min_conf=0.35, end_conf=0.20,
                  hold_s=0.6, min_gap_s=0.8)
    params.update(kw)
    return SoundEventDetector(classify, **params)


def _run(detector, n_hops):
    """Feed ``n_hops`` hops of near-silent audio; collect emitted events."""
    hop = int(HOP_S * SR)
    out = []
    t = 0.0
    for _ in range(n_hops):
        t += HOP_S
        for ev in detector.feed(np.zeros(hop, dtype=np.float32), t):
            out.append(ev)
    out.extend(detector.finish())
    return out


# --- categorisation --------------------------------------------------------

def test_categorize_maps_audioset_labels_to_buckets():
    d = _detector([])
    assert d.categorize("Laughter") == "vocal"
    assert d.categorize("Giggle") == "vocal"
    assert d.categorize("Applause") == "reaction"
    assert d.categorize("Cheering") == "reaction"
    assert d.categorize("Music") == "music"
    assert d.categorize("Singing") == "music"
    assert d.categorize("Telephone") == "environmental"
    assert d.categorize("Doorbell") == "environmental"


def test_speech_classes_are_suppressed():
    d = _detector([])
    assert d.categorize("Speech") is None
    assert d.categorize("Conversation") is None
    assert d.categorize("Narration, monologue") is None
    # an unknown / uncategorised class is also None, not an error
    assert d.categorize("Rustle") is None


def test_all_category_names_are_valid_schema_literals():
    se = _categories()
    assert set(se["categories"]) <= set(CATEGORIES)
    for cat in se["categories"]:
        # each bucket must be a value SoundEvent accepts
        SoundEvent(label="x", category=cat, start=0.0, end=0.1, conf=0.5)


# --- debounce state machine ------------------------------------------------

def test_single_sound_emits_one_start_and_one_end():
    d = _detector([
        [("Silence", 0.9)],                 # nothing
        [("Laughter", 0.6)],                # open
        [("Laughter", 0.5)],                # sustain
        [("Laughter", 0.3)],                # sustain (>= end_conf 0.2)
        [("Speech", 0.9)],                  # gone -> hold
        [("Speech", 0.9)],                  # hold elapses -> close
    ])
    evs = _run(d, 8)
    starts = [e for e in evs if e["state"] == "start"]
    ends = [e for e in evs if e["state"] == "end"]
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0]["category"] == "vocal"
    assert starts[0]["label"] == "Laughter"
    assert ends[0]["end"] >= ends[0]["start"]
    # durable/haptic marker present
    assert ends[0]["kind"] == "nonspeech" and ends[0]["type"] == "sound"


def test_hysteresis_does_not_chop_a_dipping_sound():
    # After opening at >= min_conf, a dip that stays >= end_conf must sustain
    # the SAME segment, not close and reopen.
    d = _detector([
        [("Applause", 0.5)],                # open
        [("Applause", 0.25)],               # dip, still >= end_conf
        [("Applause", 0.28)],               # recover
        [("Applause", 0.6)],
    ])
    evs = _run(d, 6)
    assert sum(e["state"] == "start" for e in evs) == 1
    assert sum(e["state"] == "end" for e in evs) == 1


def test_concurrent_categories_are_independent():
    # Laughter lands on top of running music; each is its own segment.
    d = _detector([
        [("Music", 0.7)],                   # music opens
        [("Music", 0.6), ("Laughter", 0.5)],  # laughter opens too
        [("Music", 0.6), ("Laughter", 0.4)],
        [("Music", 0.6)],                   # laughter gone
        [("Music", 0.6)],                   # ... holds then closes
    ])
    evs = _run(d, 10)
    cats_started = {e["category"] for e in evs if e["state"] == "start"}
    assert cats_started == {"music", "vocal"}
    # both eventually close
    cats_ended = {e["category"] for e in evs if e["state"] == "end"}
    assert cats_ended == {"music", "vocal"}


def test_min_gap_blocks_immediate_retrigger():
    # A laugh at t=0.5 last seen at t=0.5, closed at t=1.0; a re-detection at
    # t=1.5 is only 1.0 s past when the sound was last present (< min_gap 1.5),
    # so it must be refused rather than spawn a second chip.
    d = _detector([
        [("Laughter", 0.6)],                # t=0.5 open (last seen 0.5)
        [("Speech", 0.9)],                  # t=1.0 gone -> close (hold 0.1)
        [("Laughter", 0.6)],                # t=1.5 gap=1.0 < 1.5 -> blocked
    ], hold_s=0.1, min_gap_s=1.5)
    evs = _run(d, 3)
    assert sum(e["state"] == "start" for e in evs) == 1


def test_finish_closes_open_segments():
    d = _detector([[("Applause", 0.8)], [("Applause", 0.8)]])
    evs = _run(d, 3)
    assert any(e["state"] == "start" for e in evs)
    assert any(e["state"] == "end" for e in evs)  # emitted by finish()


def test_below_min_conf_never_opens():
    d = _detector([[("Laughter", 0.2)], [("Laughter", 0.25)]])
    evs = _run(d, 4)
    assert evs == []


# --- schema + durability ---------------------------------------------------

def test_sound_event_rejects_reversed_span():
    SoundEvent(label="Beep", category="environmental", start=1.0, end=1.0, conf=0.5)
    with pytest.raises(ValidationError):
        SoundEvent(label="Beep", category="environmental", start=2.0, end=1.0, conf=0.5)


def test_caption_spec_events_roundtrip(tmp_path):
    from autocwi.schema import (AxisMapping, Mapping, Media, Speaker, load_model,
                                save_model)
    spec = CaptionSpec(
        media=Media(path="c.mp4", duration=5.0),
        speakers={"S1": Speaker(color="#E5E517")},
        words=[],
        mapping=Mapping(loudness_to=AxisMapping(axis="size", min=3, max=12),
                        pitch_to=AxisMapping(axis="wght", min=100, max=1000, invert=True)),
        events=[SoundEvent(label="Applause", category="reaction",
                           start=1.0, end=2.4, conf=0.8)],
    )
    p = tmp_path / "spec.json"
    save_model(spec, p)
    back = load_model(CaptionSpec, p)
    assert len(back.events) == 1 and back.events[0].category == "reaction"


def test_spec_without_events_defaults_empty():
    from autocwi.schema import (AxisMapping, Mapping, Media, Speaker)
    spec = CaptionSpec(
        media=Media(path="c.mp4", duration=5.0),
        speakers={"S1": Speaker(color="#E5E517")},
        words=[],
        mapping=Mapping(loudness_to=AxisMapping(axis="size", min=3, max=12),
                        pitch_to=AxisMapping(axis="wght", min=100, max=1000, invert=True)),
    )
    assert spec.events == []


def test_is_durable_record_predicate():
    assert _is_durable_record({"type": "word", "final": True})
    assert not _is_durable_record({"type": "word", "final": False})
    assert _is_durable_record({"type": "sound", "state": "end"})
    assert not _is_durable_record({"type": "sound", "state": "start"})
    assert not _is_durable_record({"type": "hypothesis"})
    assert not _is_durable_record({"type": "level"})


def test_config_exposes_sound_events():
    cfg = load_config()
    se = cfg["live"]["sound_events"]
    assert se["enabled"] is True
    assert set(se["categories"]) == set(CATEGORIES)
