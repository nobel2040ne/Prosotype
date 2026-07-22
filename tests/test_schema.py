import pytest
from pydantic import ValidationError

from autocwi.schema import (
    AxisMapping,
    CaptionSpec,
    Mapping,
    Media,
    Speaker,
    Word,
    load_model,
    save_model,
)


def make_spec(**overrides) -> CaptionSpec:
    fields = dict(
        media=Media(path="clip.mp4", duration=10.0, fps=30.0),
        speakers={"S1": Speaker(color="#56B4E9"), "S2": Speaker(color="#E69F00")},
        words=[
            Word(text="hello", start=0.4, end=0.7, speaker="S1", loudness=0.5,
                 pitch=0.5, loudness_db=-20.0, pitch_hz=180.0, conf=0.9),
            Word(text="hi", start=1.0, end=1.3, speaker="S2", loudness=1.0,
                 pitch=0.0, loudness_db=-15.0, pitch_hz=120.0, conf=0.8),
        ],
        mapping=Mapping(
            loudness_to=AxisMapping(axis="size", min=24, max=56),
            pitch_to=AxisMapping(axis="wght", min=300, max=800, invert=True),
        ),
    )
    fields.update(overrides)
    return CaptionSpec(**fields)


def test_valid_spec_has_version():
    assert make_spec().version == "1.0"


def test_round_trip(tmp_path):
    spec = make_spec()
    save_model(spec, tmp_path / "spec.json")
    loaded = load_model(CaptionSpec, tmp_path / "spec.json")
    assert loaded == spec


def test_unknown_speaker_rejected():
    with pytest.raises(ValidationError, match="unknown speakers"):
        make_spec(speakers={"S1": Speaker(color="#56B4E9")})


def test_bad_color_rejected():
    with pytest.raises(ValidationError, match="RRGGBB"):
        Speaker(color="blue")


def test_out_of_range_normalized_values_rejected():
    with pytest.raises(ValidationError):
        Word(text="x", start=0, end=1, speaker="S1", loudness=1.5, pitch=0.5,
             loudness_db=-20, pitch_hz=100, conf=0.9)


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        Word(text="x", start=1.0, end=1.0, speaker="S1", loudness=0.5, pitch=0.5,
             loudness_db=-20, pitch_hz=100, conf=0.9)
