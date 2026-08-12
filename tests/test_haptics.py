"""Haptic salience -> actuation. Offline: pure mapping, no GPIO, no device.

The rule under test throughout is the standing one for this module: **actuate
on flags, never on every word.** Continuous vibration measured as distracting
(Tactile Emotions, CHI '25), so a test that lets an unflagged word through is
testing the wrong thing.
"""

from collections import deque

import numpy as np
import pytest

from autocwi.config import load_config
from autocwi.live import HypothesisWord, SpeakerAttribution, StreamingCaptioner
from autocwi.haptics import (
    Cue,
    MotorLayout,
    bearing_weights,
    cue_for_word,
    layout_from_config,
)


def _word(**kw) -> dict:
    base = {"type": "word", "text": "hello", "final": True}
    base.update(kw)
    return base


# --- what actuates -------------------------------------------------------


def test_an_ordinary_word_does_not_actuate():
    """The overwhelming majority of words must return nothing."""
    assert cue_for_word(_word()) is None


def test_a_speaker_change_actuates():
    cue = cue_for_word(_word(speaker_change=True))
    assert cue is not None and cue.flag == "speaker_change"


def test_emphasis_actuates():
    assert cue_for_word(_word(emphasis=True)).flag == "emphasis"


def test_speaker_change_outranks_emphasis_on_one_word():
    """Firing both would read as one longer buzz, not as two cues, and the turn
    boundary is the more informative event."""
    cue = cue_for_word(_word(speaker_change=True, emphasis=True))
    assert cue.flag == "speaker_change"


def test_a_provisional_word_never_actuates():
    """Only durable words carry settled attribution. A pulse cannot be taken
    back, so a revisable word must not fire one."""
    assert cue_for_word(_word(speaker_change=True, final=False)) is None


def test_direction_rides_on_the_word_when_it_has_one():
    cue = cue_for_word(_word(speaker_change=True, direction_deg=137.0))
    assert cue.direction_deg == pytest.approx(137.0)


def test_a_word_without_direction_produces_a_cue_with_no_bearing():
    """`never fabricate direction` — no array, or no reading over that word,
    must reach the motors as absent rather than as 0 degrees (front)."""
    assert cue_for_word(_word(emphasis=True)).direction_deg is None


# --- where it actuates ---------------------------------------------------


RING4 = MotorLayout(pins=[17, 27, 22, 23])          # 0, 90, 180, 270


def test_a_bearing_on_a_motor_drives_only_that_motor():
    assert bearing_weights(RING4, 90.0) == [0.0, 1.0, 0.0, 0.0]


def test_a_bearing_between_two_motors_cross_fades():
    """Four motors must read as a continuous direction, not four buzzers."""
    assert bearing_weights(RING4, 45.0) == [0.5, 0.5, 0.0, 0.0]


def test_the_ring_wraps_through_zero():
    """350deg is 10deg counter-clockwise of front, so it is mostly the front
    motor and a little of the one at 270 — not a jump to the far side."""
    front, right, back, left = bearing_weights(RING4, 350.0)
    assert front == pytest.approx(0.889, abs=1e-3)
    assert left == pytest.approx(0.111, abs=1e-3)
    assert right == 0.0 and back == 0.0


@pytest.mark.parametrize("bearing", [0.0, 90.0, 180.0, 270.0, 359.9, 45.0])
def test_total_energy_is_constant_around_the_ring(bearing):
    """A cue must not feel stronger when it happens to point at a motor."""
    assert sum(bearing_weights(RING4, bearing)) == pytest.approx(1.0, abs=1e-9)


def test_no_bearing_pulses_the_whole_ring():
    assert bearing_weights(RING4, None) == [1.0, 1.0, 1.0, 1.0]


def test_one_motor_cannot_encode_direction_and_says_so():
    """A single coin motor has no way to express a bearing. It must fall back
    to the whole-ring pulse rather than silently implying a direction."""
    single = MotorLayout(pins=[17])
    assert single.can_encode_direction is False
    assert bearing_weights(single, 137.0) == [1.0]


def test_two_motors_give_left_and_right():
    pair = MotorLayout(pins=[17, 27])               # 0 and 180
    assert pair.can_encode_direction is True
    assert bearing_weights(pair, 0.0) == [1.0, 0.0]
    assert bearing_weights(pair, 180.0) == [0.0, 1.0]


def test_no_motors_configured_is_not_an_error():
    """`--no-motors` and a headless run must both be fine."""
    assert bearing_weights(MotorLayout(pins=[]), 90.0) == []


# --- configuration -------------------------------------------------------


def test_a_bare_pin_list_becomes_an_even_ring():
    layout = layout_from_config({"haptics": {"motors": [17, 27, 22, 23]}})
    assert layout.pins == [17, 27, 22, 23]
    assert layout.angles == [0, 90, 180, 270]


def test_explicit_angles_allow_an_uneven_layout():
    """Three motors on a wristband are not 120deg apart; the config must be
    able to say so."""
    layout = layout_from_config({"haptics": {"motors": [
        {"gpio": 17, "angle_deg": 0},
        {"gpio": 27, "angle_deg": 60},
        {"gpio": 22, "angle_deg": 300},
    ]}})
    assert layout.angles == [0, 60, 300]


def test_missing_haptics_config_yields_no_motors():
    assert layout_from_config({}).pins == []


def test_mismatched_pins_and_angles_are_refused():
    with pytest.raises(ValueError):
        MotorLayout(pins=[17, 27], angles=[0.0])


def test_cue_is_immutable():
    """A cue in flight must not be edited by whatever is about to send it."""
    with pytest.raises(Exception):
        Cue(flag="emphasis", intensity=0.5).intensity = 0.9


# --- direction on the durable word ---------------------------------------
# The bearing rides on the word rather than streaming to the motors. These pin
# the two halves of `never fabricate direction`: present with an array,
# ABSENT without one.

def _captioner(direction_source=None) -> StreamingCaptioner:
    """Build a captioner without loading a recognizer.

    `__new__` is the established pattern in this suite for exercising
    `_word_event` offline; it skips `__init__`, so every attribute the method
    touches is set explicitly here.
    """
    c = StreamingCaptioner.__new__(StreamingCaptioner)
    c.cfg = load_config()
    c.db_history = deque([-30.0] * 8, maxlen=120)
    c.prosody_cache = {}
    c.speaker = "S1"
    c.utterance = 0
    c.stream_base = 0.0
    c._last_final_speaker = None
    c._word_slots = []
    c._final_word_events = {}
    if direction_source is not None:
        c.direction_source = direction_source
    return c


AUDIO = np.full(16_000, 0.03, dtype=np.float32)
STABLE = SpeakerAttribution("S1", "stable", 0.95, 0.0, 1)


def test_a_local_mic_produces_no_direction_on_the_word():
    """No array means no bearing — not a default of 0 degrees, which is front
    and would be a claim about the room that nothing measured."""
    word = _captioner()._word_event(
        HypothesisWord("hello", 0.0, 0.3, 0.9), AUDIO, True, STABLE
    )
    assert "direction_deg" not in word


def test_an_attached_array_puts_its_bearing_on_the_word():
    word = _captioner(lambda: 137.4)._word_event(
        HypothesisWord("hello", 0.0, 0.3, 0.9), AUDIO, True, STABLE
    )
    assert word["direction_deg"] == pytest.approx(137.4)


def test_an_expired_array_reading_drops_off_the_word():
    """`NodeLink.direction_deg` returns None once its reading goes stale, so a
    node that stopped reporting must stop attributing bearings — the same rule
    the compass follows when it falls back to `awaiting array`."""
    word = _captioner(lambda: None)._word_event(
        HypothesisWord("hello", 0.0, 0.3, 0.9), AUDIO, True, STABLE
    )
    assert "direction_deg" not in word


def test_a_provisional_word_carries_no_direction():
    """Only durable words drive haptics, so only they need a bearing."""
    word = _captioner(lambda: 90.0)._word_event(
        HypothesisWord("hello", 0.0, 0.3, 0.9), AUDIO, False, STABLE
    )
    assert "direction_deg" not in word


def test_the_word_to_cue_path_fires_only_on_flagged_words():
    """End to end over the real event shape: three words, one flagged.

    This is the rule the whole module exists to keep — actuate on flags, never
    on every word — checked on what `_word_event` actually emits rather than on
    a hand-written dict.
    """
    captioner = _captioner(lambda: 45.0)
    words = [
        captioner._word_event(
            HypothesisWord(text, start, start + 0.3, 0.9), AUDIO, True, STABLE
        )
        for text, start in [("one", 0.0), ("two", 0.3), ("three", 0.6)]
    ]
    # Nothing here is loud enough or a turn boundary, so nothing actuates.
    assert [cue_for_word(w) for w in words] == [None, None, None]

    words[1]["speaker_change"] = True
    cues = [c for c in (cue_for_word(w) for w in words) if c is not None]
    assert len(cues) == 1
    assert cues[0].flag == "speaker_change"
    assert cues[0].direction_deg == pytest.approx(45.0)
