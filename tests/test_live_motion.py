"""Guards for the live CWI-motion port (config plumbing + page wiring).

The motion itself is time-based and lives in the browser, so these are
structural: the knobs resolve with defaults, the config exposes them, and the
rendered page carries the loop. Behavioural verification is the headless motion
harness / tuner (see the plan), not a unit test.
"""

import yaml

from autocwi.config import load_config
from autocwi.livepage import _live_sync_cfg, render_live


def test_live_sync_defaults():
    ls = _live_sync_cfg({})
    assert ls["enabled"] is True
    assert ls["sync_pop"] == 0.15
    assert ls["sync_elevation_em"] == 0.25
    assert ls["neighbor_push"] is True
    for k in ("rise_s", "peak_s", "fall_s", "swell_gain"):
        assert isinstance(ls[k], (int, float))


def test_live_sync_overrides_pass_through():
    ls = _live_sync_cfg({"enabled": False, "sync_pop": 0.2, "swell_gain": 0.0})
    assert ls["enabled"] is False
    assert ls["sync_pop"] == 0.2
    assert ls["swell_gain"] == 0.0
    # unspecified keys still fall back to defaults
    assert ls["sync_elevation_em"] == 0.25


def test_config_exposes_live_sync():
    cfg = load_config()
    ls = cfg["motion"]["live_sync"]
    assert ls["enabled"] is True
    assert "neighbor_push" in ls


def test_rendered_page_carries_motion_loop(tmp_path):
    cfg = yaml.safe_load(open("config.yaml"))
    html = open(render_live(cfg, tmp_path)).read()
    for token in ("registerMotion", "resolveLine", "motionTick", "syncEnv",
                  "\"live_sync\"", "dataset.moving"):
        assert token in html, token
    # the churn instrument's settled test must now exclude moving words
    assert 'dataset.moving !== "true"' in html
