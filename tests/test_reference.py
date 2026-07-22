"""The Python prosody mirror must stay bit-identical to the page's JavaScript.

`autocwi/ccprosody.py` re-implements the renderer's own `typeOf()` so that
`scripts/derive_reference_spec.py` can INVERT it — turning an emphasis measured
off a recording back into the `loudness`/`pitch_hz` that reproduce it. Two
implementations of one map is a standing invitation to drift, and drift here is
silent: the spec still validates, the page still renders, and every derived
word is simply wrong.

So the map is pinned to a grid captured from the JavaScript itself
(`scripts/dump_forward_map.py`, which needs Chrome and is never run by this
suite). These tests are the other half of that arrangement, and until now they
did not exist — the fixture was written and checked in, both `ccprosody.py` and
the README described the guard, and nothing ever loaded it.
"""
import json
from pathlib import Path

import pytest

from autocwi.ccprosody import forward, merged_expression
from autocwi.config import load_config

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "forward_map_golden.json"
REDUMP = ("re-run `.venv/bin/python scripts/dump_forward_map.py` "
          "to recapture it from the page")


@pytest.fixture(scope="module")
def golden():
    if not GOLDEN.exists():
        pytest.skip(f"{GOLDEN.name} missing; {REDUMP}")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_was_captured_under_the_current_config(golden):
    """Fail loudly on a stale fixture instead of comparing against old values.

    Every block the map reads is stored beside the grid. Changing, say,
    `expression.size_response` or the 2.3.6 size range without recapturing
    would otherwise leave the grid describing a map nobody uses any more, and
    the test below would keep passing against it.
    """
    cfg = load_config()
    stored = golden["config"]
    for block, want in (
        ("mapping", cfg["mapping"]),
        ("expression", merged_expression(cfg)),
        ("normalization",
         {"min_voiced_frac": cfg["normalization"]["min_voiced_frac"]}),
        ("closed_caption",
         {k: cfg["closed_caption"][k]
          for k in ("size_pct", "quiet_deformation", "emphasis_deadband")}),
    ):
        assert json.loads(json.dumps(stored[block])) == \
            json.loads(json.dumps(want)), f"config.{block} changed since capture; {REDUMP}"


def test_python_reproduces_every_point_the_javascript_produced(golden):
    """Exact, not approximate: this map is inverted, so error compounds."""
    cfg = load_config()
    ml, mp = golden["median_loudness"], golden["median_pitch"]
    assert len(golden["grid"]) >= 100, "grid too small to be meaningful"

    worst = 0.0
    for loudness, hz, emph_scale, emph_wght, rest_wght, wdth, rest_pct in golden["grid"]:
        got = forward(loudness, hz, ml, mp, cfg)
        # Weight/width/size are integers or exact config values on both sides.
        assert got["emphWght"] == emph_wght, (loudness, hz, REDUMP)
        assert got["restWght"] == rest_wght, (loudness, hz, REDUMP)
        assert got["wdth"] == wdth, (loudness, hz, REDUMP)
        assert got["restPct"] == pytest.approx(rest_pct, abs=1e-9), (loudness, hz)
        worst = max(worst, abs(got["emphScale"] - emph_scale))
    assert worst < 1e-9, f"emphScale drifted by {worst:g}; {REDUMP}"


def test_the_grid_actually_exercises_both_channels(golden):
    """A constant column would let the map break while every assertion passed.

    Both prosody channels have silently collapsed to one value before — twice
    in the derived specs — and a golden grid with no variation would pin
    nothing at all.
    """
    scales = {round(row[2], 6) for row in golden["grid"]}
    weights = {row[3] for row in golden["grid"]}
    assert len(scales) >= 5, "loudness -> size is not varying across the grid"
    assert len(weights) >= 5, "pitch -> weight is not varying across the grid"
