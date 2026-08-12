"""Haptic salience -> actuation. Actuate on flags, never on every word.

Two findings shape this, both in `docs/RESEARCH.md`: wrist vibration alongside
captions helps DHH viewers track speaker changes (Haptic-Captioning, CHI '23),
but *continuous* vibration is distracting (Tactile Emotions, CHI '25).

So direction rides on a WORD rather than streaming from the array. Driving
motors from raw DoA is the continuous vibration the research warns against; a
bearing attached to a speaker change is one event — "someone new, over there".

The bearing -> motor mapping lives here, not on the node, because a mapping
that only exists inside a device script cannot be tested offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A durable word may carry either flag; `speaker_change` outranks `emphasis`
# when both land on one word, because a turn boundary is the more informative
# event and firing both would read as one longer buzz rather than two cues.
FLAG_PRIORITY = ("speaker_change", "emphasis")


@dataclass(frozen=True)
class Cue:
    """One actuation. `direction_deg` is None when nothing measured a bearing."""

    flag: str
    intensity: float
    direction_deg: float | None = None


@dataclass
class MotorLayout:
    """Where the motors physically are, as bearings from the case's front.

    Defaults to an evenly spaced ring, which is what the enclosure will most
    likely hold, but the angles are explicit so an uneven layout (say three
    motors on a wristband) is expressible without changing code.
    """

    pins: list[int] = field(default_factory=list)
    angles: list[float] | None = None

    def __post_init__(self) -> None:
        if self.angles is None:
            step = 360 / max(1, len(self.pins))
            self.angles = [i * step for i in range(len(self.pins))]
        if len(self.angles) != len(self.pins):
            raise ValueError(
                f"{len(self.pins)} pins but {len(self.angles)} angles"
            )

    @property
    def spacing_deg(self) -> float:
        return 360 / max(1, len(self.pins))

    @property
    def can_encode_direction(self) -> bool:
        """One motor cannot express a bearing, however it is driven.

        Worth asserting rather than assuming: with a single motor the honest
        rendering is salience only, and pretending otherwise would make the
        device claim something it cannot say.
        """
        return len(self.pins) >= 2


def bearing_weights(layout: MotorLayout,
                    bearing: float | None) -> list[float]:
    """Per-motor intensity for a bearing, 0..1.

    Cross-fades between the two nearest motors so a four-motor ring reads as a
    continuous direction rather than as four separate buzzers. A bearing of
    None pulses every motor equally — the honest rendering of "this happened,
    direction unknown", and the same fallback the compass makes when it shows
    `awaiting array`.
    """
    if not layout.pins:
        return []
    if bearing is None or not layout.can_encode_direction:
        return [1.0] * len(layout.pins)
    step = layout.spacing_deg
    weights = []
    for angle in layout.angles:
        # Angular distance wrapped into +/-180, so 350deg is 10deg from front.
        distance = abs(((bearing - angle) + 180) % 360 - 180)
        weights.append(max(0.0, 1.0 - distance / step))
    return weights


def cue_for_word(word: dict, intensity: float = 0.8) -> Cue | None:
    """Decide whether a durable word actuates, and how.

    Returns None for the overwhelming majority of words, which is the point.
    The salience flags are computed upstream in `live.py` and gated there on
    stable/corrected attribution, so this makes no judgement of its own — it
    only refuses to fire on a word that carries no flag.
    """
    if not word.get("final", False):
        return None
    for flag in FLAG_PRIORITY:
        if word.get(flag):
            direction = word.get("direction_deg")
            return Cue(
                flag=flag,
                intensity=intensity,
                direction_deg=None if direction is None else float(direction),
            )
    return None


def layout_from_config(cfg: dict) -> MotorLayout:
    """Read `haptics.motors` from config.yaml.

    Accepts either a bare pin list or per-motor dicts carrying an angle, so a
    ring can be described as `[17, 27, 22, 23]` and an uneven layout as
    `[{gpio: 17, angle_deg: 0}, ...]`.
    """
    entries = (cfg.get("haptics", {}) or {}).get("motors", []) or []
    pins: list[int] = []
    angles: list[float] = []
    explicit = False
    for entry in entries:
        if isinstance(entry, dict):
            pins.append(int(entry["gpio"]))
            if "angle_deg" in entry:
                angles.append(float(entry["angle_deg"]))
                explicit = True
        else:
            pins.append(int(entry))
    return MotorLayout(pins=pins, angles=angles if explicit else None)
