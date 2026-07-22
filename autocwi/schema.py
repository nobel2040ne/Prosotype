"""CaptionSpec: the versioned contract between analysis stages and any output.

The renderer (and the future haptic module) must consume ONLY these models —
never the upstream ASR/diarization/prosody objects. Intermediate per-stage
models (WordTiming, DiarSegment, ProsodyFeature) are also defined here so each
stage can be run and inspected independently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

SPEC_VERSION = "1.0"

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ---------------------------------------------------------------------------
# Intermediate stage outputs (out/words.json, out/segments.json, out/prosody.json)
# ---------------------------------------------------------------------------

class WordTiming(BaseModel):
    """One ASR word with timing and confidence."""

    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    conf: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> "WordTiming":
        if self.end <= self.start:
            raise ValueError(f"word {self.text!r}: end ({self.end}) must be > start ({self.start})")
        return self


class DiarSegment(BaseModel):
    """One diarization turn."""

    speaker: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def _end_after_start(self) -> "DiarSegment":
        if self.end <= self.start:
            raise ValueError(f"segment {self.speaker}: end must be > start")
        return self


class ProsodyFeature(BaseModel):
    """Raw prosody measurements for one word span."""

    loudness_db: float
    pitch_hz: float = Field(ge=0)  # 0.0 when no voiced frames were found
    voiced_frac: float = Field(ge=0, le=1)


class WordList(BaseModel):
    words: list[WordTiming]


class SegmentList(BaseModel):
    segments: list[DiarSegment]


class ProsodyList(BaseModel):
    """Prosody features, index-aligned with the word list they were computed from."""

    features: list[ProsodyFeature]


# ---------------------------------------------------------------------------
# CaptionSpec (out/spec.json) — the stable contract
# ---------------------------------------------------------------------------

class Media(BaseModel):
    path: str
    duration: float = Field(ge=0)
    fps: Optional[float] = None


class Speaker(BaseModel):
    color: str

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX_COLOR.match(v):
            raise ValueError(f"color must be #RRGGBB, got {v!r}")
        return v.upper()


class AxisMapping(BaseModel):
    axis: str  # "size" (font size) or a variable-font axis tag like "wght"
    min: float
    max: float
    invert: bool = False
    # Unit of the output range; default is px, "pct_video_height" follows the
    # CWI design system (type size as % of the frame height).
    unit: Optional[str] = None
    # When set, the renderer maps the RAW value (e.g. pitch_hz) over this
    # domain instead of the per-speaker-normalized 0..1 value — the CWI pitch
    # convention is absolute (80 Hz heavy .. 250 Hz thin).
    domain_hz: Optional[tuple[float, float]] = None
    # The value normal delivery sits at (CWI 2.3.5: 5% of frame height). Per-word
    # deviation is measured from here, so ordinary speech stays near baseline
    # instead of ranging over the whole whisper..shout interval.
    baseline: Optional[float] = None

    @model_validator(mode="after")
    def _range(self) -> "AxisMapping":
        if self.max <= self.min:
            raise ValueError(f"axis {self.axis}: max must be > min")
        if self.baseline is not None and not (self.min <= self.baseline <= self.max):
            raise ValueError(f"axis {self.axis}: baseline must lie within min..max")
        return self


class Mapping(BaseModel):
    loudness_to: AxisMapping
    pitch_to: AxisMapping
    speaker_to: Literal["color"] = "color"


class Motion(BaseModel):
    """One word's motion, MEASURED from a recording and replayed verbatim.

    The parametric envelopes in the renderer (rise/hold/decay, crouch, pulse)
    describe the *average* word: they were fitted to the median of every glyph
    curve in a reference recording, so by construction they give a word that
    does not move the same lift as one that does. Sampling them per word is
    therefore always approximately wrong. When a word's own curve was measured,
    it is stored here and the renderer replays it instead of evaluating a model.

    Uniform grid on purpose (``t0`` + ``dt``, not a list of (t, v) stops): the
    sampler is then an index plus one lerp, O(1) per word per frame, with no
    scan over the keyframes.

    Channels are stored RELATIVE to rest, so a renderer needs no knowledge of
    how the reference was typeset and every channel is exactly 0 (or 1) where
    the word is not moving:

    ``lift``   vertical rise in GLYPH HEIGHTS, + = raised, 0 = resting baseline.
               Glyph heights rather than em because that is the unit the video
               is measured in; the renderer converts with one calibrated
               constant (``closed_caption.glyph_height_em``).
    ``scale``  multiplier on the word's resting size, 1.0 = resting.
    ``dwght``  signed offset on the variable-font ``wght`` axis, 0 = resting.
               A delta, not an absolute, so the word rests at whatever weight
               the renderer's own type map gives it and cannot jump at t0.
    """

    t0: float          # spec time of sample 0, seconds
    dt: float = Field(gt=0)
    lift: list[float]
    scale: list[float]
    dwght: list[float]

    @model_validator(mode="after")
    def _same_length(self) -> "Motion":
        n = len(self.lift)
        if n < 2:
            raise ValueError("motion needs at least 2 samples")
        if len(self.scale) != n or len(self.dwght) != n:
            raise ValueError(
                f"motion channels must be the same length, got "
                f"lift={n} scale={len(self.scale)} dwght={len(self.dwght)}")
        return self


class Word(BaseModel):
    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    speaker: str
    loudness: float = Field(ge=0, le=1)  # normalized WITHIN this speaker
    pitch: float = Field(ge=0, le=1)     # normalized WITHIN this speaker
    loudness_db: float                   # raw, for debugging / haptics tuning
    pitch_hz: float = Field(ge=0)        # raw; 0.0 = unvoiced
    voiced_frac: Optional[float] = Field(default=None, ge=0, le=1)
    conf: float = Field(ge=0, le=1)
    # Optional, additive: force a caption-line break before this word, so an
    # authored spec keeps the grouping it was derived with. Renderers that do
    # not know the field simply ignore it, so no version bump.
    line_break: bool = False
    # Derived references only: was this word's emphasis actually measurable
    # from the recording, or is it the neutral default? Purely informational.
    emphasis_measured: Optional[bool] = None
    # Which pixel measurement supplied the word-level size curve. Tracks keep
    # the cleanest timing/shape; frame segmentation is the fallback for short
    # or strongly swollen words whose glyph tracks disappear.
    emphasis_source: Optional[Literal["track", "frames"]] = None
    # Whether this word belongs to a line that horizontally tracks past a
    # fixed playhead in its source recording. Derived references set this
    # explicitly so scrolling and static sections can coexist in one demo.
    tracking: Optional[bool] = None
    # Optional, additive: this word's motion as MEASURED from a recording. When
    # present the renderer replays it and does not evaluate its parametric
    # envelopes for this word — see `Motion`. Absent for live and synthetic
    # specs, which keep the model.
    motion: Optional[Motion] = None

    @model_validator(mode="after")
    def _end_after_start(self) -> "Word":
        if self.end <= self.start:
            raise ValueError(f"word {self.text!r}: end must be > start")
        return self


class CaptionSpec(BaseModel):
    version: str = SPEC_VERSION
    media: Media
    speakers: dict[str, Speaker]
    words: list[Word]
    mapping: Mapping

    @model_validator(mode="after")
    def _speakers_known(self) -> "CaptionSpec":
        unknown = {w.speaker for w in self.words} - set(self.speakers)
        if unknown:
            raise ValueError(f"words reference unknown speakers: {sorted(unknown)}")
        return self


# ---------------------------------------------------------------------------
# JSON I/O helpers shared by the per-stage CLI
# ---------------------------------------------------------------------------

def save_model(model: BaseModel, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")


def load_model(cls: type[BaseModel], path: str | Path):
    return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
