"""Guards for the live CWI-motion port (config plumbing).

The motion itself is time-based and lives in the browser. Its knobs must resolve
with the right defaults and be exposed on the config; behavioural verification of
the rendered loop is the render-core Node suite and scripts/live_render_probe.py,
not a source-string check here.
"""

from autocwi.config import load_config
from autocwi.livepage import _live_sync_cfg


def test_live_sync_defaults():
    ls = _live_sync_cfg({})
    assert ls["enabled"] is True
    assert ls["sync_pop"] == 0.10
    assert ls["sync_elevation_em"] == 0.20
    assert ls["neighbor_push"] is False
    assert ls["display_on_create"] is True
    # cc parity: read-ahead words appear calm; the only motion is the §2.2.3
    # pop at the colour turn, so the per-character slide-in defaults OFF.
    assert ls["character_entry_enabled"] is False
    assert ls["character_entry_duration_s"] == 0.24
    assert ls["character_entry_stagger_s"] == 0.018
    assert ls["character_wave_enabled"] is True
    assert ls["character_wave_lift_em"] > 0
    assert ls["character_wave_pop"] > 0
    assert ls["character_wave_crouch_em"] == 0
    assert 0 < ls["character_wave_spatial_smoothing"] < 1
    assert 0 < ls["fast_speech_motion_gain"] < 1
    assert (
        ls["weight_attack_fraction"]
        < ls["size_attack_fraction"]
        < ls["width_attack_fraction"]
    )
    assert ls["weight_release_fraction"] < ls["width_release_fraction"] < 1
    assert 0 < ls["slow_delivery_curve_delay"] < 0.1
    for k in (
        "rise_s", "peak_s", "fall_s",
        "clock_smoothing", "clock_reset_threshold_s",
    ):
        assert isinstance(ls[k], (int, float))


def test_live_sync_overrides_pass_through():
    ls = _live_sync_cfg({"enabled": False, "sync_pop": 0.2, "swell_gain": 0.0})
    assert ls["enabled"] is False
    assert ls["sync_pop"] == 0.2
    # Old configs remain loadable, but loudness-dependent synchronization is
    # intentionally ignored: CWI §2.2.3 amplitude is constant.
    assert "swell_gain" not in ls
    # unspecified keys still fall back to defaults
    assert ls["sync_elevation_em"] == 0.20


def test_config_exposes_live_sync():
    cfg = load_config()
    ls = cfg["motion"]["live_sync"]
    assert ls["enabled"] is True
    assert "neighbor_push" in ls
    assert ls["display_on_create"] is True
    assert ls["delivery_enabled"] is True
    assert ls["delivery_contour_lift_em"] > 0
    assert ls["delivery_flow_duration_ms"] > 0
    delivery = cfg["live"]["delivery"]
    assert delivery["enabled"] is True
    assert delivery["profile"]["contour_threshold"] >= 0.45
    assert delivery["contour_min_voiced_frames"] >= 5
    assert delivery["profile"]["gentle_texture_min"] >= 0.6
