"""The `cc` prosody map, in Python — and its inverse.

`typeOf()` in ``ccpage.py`` turns a word's ``loudness``/``pitch_hz`` into the
size envelope and weight it wears while spoken. To DERIVE a reference spec from
a recording we need the other direction: given the emphasis measured on screen,
what prosody reproduces it?

The map is continuous here (unlike live mode, `cc` does not use
``expression.size_steps``/``weight_step``/``hysteresis``), so it inverts by
bisection. It is monotone, with one flat interval where the deadband pins
ordinary words to exactly 1.

DRIFT WARNING. This mirrors JavaScript that lives in another file. Everything
below is checked against ``tests/fixtures/forward_map_golden.json``, a grid
captured FROM THE JS by ``scripts/dump_forward_map.py`` and stored with the
config it was captured under — so editing ``mapping``/``expression`` fails the
test with an instruction to re-dump rather than diverging silently. Keep the
two implementations line-for-line comparable.
"""
from __future__ import annotations

import math

MEDIAN_PITCH_NONE = None


def _clamp(v, lo, hi):
    return min(hi, max(lo, v))


def _clamp01(f):
    return min(1.0, max(0.0, f))


def _lerp(a, b, f):
    return a + (b - a) * f


def pitch_axis(m, hz, fallback_domain):
    d = m.get("domain_hz") or fallback_domain
    f = _clamp01((hz - d[0]) / (d[1] - d[0]))
    if m.get("invert"):
        f = 1 - f
    return _lerp(m["min"], m["max"], f)


def toward_baseline(value, baseline, response, lo, hi):
    extent = hi - baseline if value >= baseline else baseline - lo
    if not extent > 0:
        return baseline
    d = _clamp((value - baseline) / extent, -1.0, 1.0)
    return baseline + math.copysign(abs(d) ** (1.0 / response) * extent, d) if d else baseline


# The axis keys `cc` may override; anything else comes from `expression`.
# Every `expression` key the page lets `closed_caption` override. ANCHORS
# BELONG HERE TOO: 2.3.8 pins a 160-200 Hz voice to Regular 400, and with
# `anchor_wght` missing from this list a `closed_caption.anchor_wght` was read
# by nobody -- the setting looked applied and did nothing.
CC_AXIS_OVERRIDES = ("size_response", "weight_response", "width_response",
                     "wght_range", "wdth_range", "anchor_wght", "anchor_wdth")


def merged_expression(cfg):
    """`expression` with any `closed_caption` axis overrides applied.

    One helper so every caller agrees. `ccpage.render_cc` performs the same
    merge for the page; a caller that reads `cfg["expression"]` directly gets
    live mode's calmer values and silently under-drives the effect -- which is
    exactly how the derived weights came out capped at live's 500.
    """
    ex = dict(cfg["expression"])
    for key in CC_AXIS_OVERRIDES:
        if key in cfg.get("closed_caption", {}):
            ex[key] = cfg["closed_caption"][key]
    return ex


def forward(loudness, pitch_hz, median_loudness, median_pitch, cfg,
            voiced_frac=0.9):
    """Mirror of the JS ``typeOf``. Returns restPct/emphScale/restWght/emphWght/wdth."""
    mapping = cfg["mapping"]
    cc = cfg["closed_caption"]
    ex = merged_expression(cfg)
    sm = mapping["loudness_to"]

    anchor_pct = cc.get("size_pct") or sm["baseline"]
    # CWI's size anchors are RATIOS around its baseline, written as absolute
    # percentages; rescale by the resting size actually in use. See the same
    # comment in ccpage.py's typeOf -- these two must stay identical.
    k = anchor_pct / sm["baseline"]
    sm_min, sm_max = sm["min"] * k, sm["max"] * k
    raw_size = _lerp(sm_min, sm_max, _clamp01(loudness))
    med_size = _lerp(sm_min, sm_max, median_loudness)
    emph_pct = toward_baseline(raw_size - med_size + anchor_pct, anchor_pct,
                               ex["size_response"], sm_min, sm_max)

    min_voiced = cfg["normalization"]["min_voiced_frac"]
    is_voiced = pitch_hz > 0 and voiced_frac >= min_voiced
    wm = mapping["pitch_to"]
    w_band = ex.get("anchor_wght") or [350, 700]
    w_anchor = _clamp(400 if median_pitch is None
                      else pitch_axis(wm, median_pitch, wm["domain_hz"]),
                      w_band[0], w_band[1])
    # Bound the RENDERED axis, not just the anchor -- see the matching comment
    # in ccpage.py's typeOf. These two must stay identical.
    w_range = ex.get("wght_range") or [wm["min"], wm["max"]]
    wght = round(_clamp(_clamp(
        toward_baseline(pitch_axis(wm, pitch_hz, wm["domain_hz"]), w_anchor,
                        ex["weight_response"], wm["min"], wm["max"])
        if is_voiced else w_anchor, wm["min"], wm["max"]),
        w_range[0], w_range[1]))

    wdth = 100
    if mapping.get("harmonics_to"):
        hm = mapping["harmonics_to"]
        h_band = ex.get("anchor_wdth") or [88, 112]
        h_anchor = _clamp(100 if median_pitch is None
                          else pitch_axis(hm, median_pitch, wm["domain_hz"]),
                          h_band[0], h_band[1])
        h_range = ex.get("wdth_range") or [hm["min"], hm["max"]]
        wdth = round(_clamp(_clamp(
            toward_baseline(pitch_axis(hm, pitch_hz, wm["domain_hz"]), h_anchor,
                            ex["width_response"], hm["min"], hm["max"])
            if is_voiced else h_anchor, hm["min"], hm["max"]),
            h_range[0], h_range[1]))

    emph_scale = emph_pct / max(1e-6, anchor_pct)
    if emph_scale < 1:
        emph_scale = 1 - (1 - emph_scale) * cc["quiet_deformation"]
    dev = abs(emph_scale - 1)
    band = cc["emphasis_deadband"]
    emph_scale = 1.0 if dev <= band else 1 + math.copysign(dev - band, emph_scale - 1)

    return {"restPct": anchor_pct, "emphScale": emph_scale,
            # ON THE /4 GRID, exactly as the page rounds it. The page quantizes
            # the ANIMATED weight to multiples of 4, so it puts the resting
            # weight on the same grid or the two spell one rest state two ways
            # and its style cache misses on every visibility change. Mirroring
            # that here is not cosmetic: this map gets INVERTED, so an unrounded
            # rest silently shifts every derived weight.
            "restWght": round(w_anchor / 4) * 4, "emphWght": wght,
            "wdth": wdth}


# ---------------------------------------------------------------------------
# Inversion
# ---------------------------------------------------------------------------

def invert_size(target, median_loudness, cfg, iters=60):
    """loudness that yields ``target`` emphScale. Monotone non-decreasing.

    The deadband makes the map exactly 1 over an interval; a target of 1 returns
    that interval's MIDPOINT, the canonically ordinary word.
    """
    def f(x):
        return forward(x, 150.0, median_loudness, 150.0, cfg)["emphScale"]

    if abs(target - 1.0) <= 1e-9:
        lo, hi = 0.0, 1.0
        # lower edge of the flat region
        a, b = 0.0, 1.0
        for _ in range(iters):
            m = (a + b) / 2
            if f(m) < 1.0:
                a = m
            else:
                b = m
        low_edge = b
        a, b = 0.0, 1.0
        for _ in range(iters):
            m = (a + b) / 2
            if f(m) <= 1.0:
                a = m
            else:
                b = m
        high_edge = a
        return _clamp01((low_edge + high_edge) / 2)

    lo, hi = 0.0, 1.0
    if target < f(lo):
        return lo
    if target > f(hi):
        return hi
    for _ in range(iters):
        m = (lo + hi) / 2
        if f(m) < target:
            lo = m
        else:
            hi = m
    return _clamp01((lo + hi) / 2)


def invert_weight(target, median_pitch, cfg, iters=60):
    """pitch_hz that yields ``target`` emphWght.

    ``pitch_to.invert`` is true, so weight DECREASES with rising Hz; bisect with
    the sense flipped. Inverts against the unrounded curve, then nudges if the
    rounded value misses.
    """
    wm = cfg["mapping"]["pitch_to"]
    lo, hi = float(wm["domain_hz"][0]), float(wm["domain_hz"][1])

    def f(hz):
        return forward(0.5, hz, 0.5, median_pitch, cfg)["emphWght"]

    if target >= f(lo):
        return lo
    if target <= f(hi):
        return hi
    for _ in range(iters):
        m = (lo + hi) / 2
        if f(m) > target:
            lo = m
        else:
            hi = m
    best = (lo + hi) / 2
    if f(best) != round(target):
        for cand in (lo, hi, best):
            if f(cand) == round(target):
                return cand
    return best


def reachable_emph(median_loudness, cfg):
    """The emphScale range the forward map can actually produce.

    Not everything is reachable. With the shipped constants the quiet side
    cannot leave the deadband at all: the scaled whisper floor gives a raw
    ratio of 0.833, ``quiet_deformation`` compresses that to a deviation of
    0.058, and ``emphasis_deadband`` is 0.10 — so no word, however quiet,
    animates. That matches the brief ("quiet words should produce little or
    almost no visible deformation") but it means a sub-1.0 target is
    unreachable and callers must be told rather than fed a silent miss.
    """
    lo = forward(0.0, 150.0, median_loudness, 150.0, cfg)["emphScale"]
    hi = forward(1.0, 150.0, median_loudness, 150.0, cfg)["emphScale"]
    return lo, hi


def invert_delta(target, cfg, iters=70):
    """The loudness OFFSET FROM THE MEDIAN that yields ``target`` emphScale.

    `emphScale` depends only on ``rawSize - medSize``, i.e. only on
    ``loudness - median_loudness`` — the map is translation-invariant and the
    absolute loudness level is a gauge freedom. Working in the offset makes the
    inversion exact and non-iterative at the spec level.
    """
    def f(d):
        return forward(_clamp01(0.5 + d), 150.0, 0.5, 150.0, cfg)["emphScale"]

    if abs(target - 1.0) <= 1e-9:
        return 0.0
    lo, hi = -0.5, 0.5
    if target <= f(lo):
        return lo
    if target >= f(hi):
        return hi
    for _ in range(iters):
        m = (lo + hi) / 2
        if f(m) < target:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def fit_spec_prosody(targets, cfg, iters=6, tol=1e-9, report=None):
    """Solve every word's prosody at once.

    Size: exact. Because the map depends only on the offset from the median,
    solve each word's offset, then re-centre so the MEDIAN offset is zero —
    which is forced, since by construction the median word wears emphScale 1.
    A measured target set whose median is not 1 simply means the recording's
    ordinary word is not our ordinary word; the re-centring absorbs that and
    the residual reports what could not be honoured.

    Weight: `emphWght` is not translation-invariant (it hangs off `anchor_wght`
    via the median pitch), so it takes a short damped iteration.

    ``targets`` is a list of ``{"emphScale": float, "emphWght": float|None}``.
    Returns a list of ``{"loudness", "pitch_hz"}``.
    """
    n = len(targets)
    if n == 0:
        return []

    def median(v):
        s = sorted(v)
        return s[len(s) // 2]

    lo_r, hi_r = reachable_emph(0.5, cfg)
    wanted = [_clamp(t["emphScale"], lo_r, hi_r) for t in targets]
    deltas = [invert_delta(w, cfg) for w in wanted]
    centre = median(deltas)
    loud = [_clamp01(0.5 + d - centre) for d in deltas]

    wm = cfg["mapping"]["pitch_to"]
    mid_hz = (wm["domain_hz"][0] + wm["domain_hz"][1]) / 2
    hz = [mid_hz] * n
    if any(t.get("emphWght") is not None for t in targets):
        med_p = mid_hz
        for _ in range(iters):
            new_h = [invert_weight(t["emphWght"], med_p, cfg)
                     if t.get("emphWght") is not None else mid_hz
                     for t in targets]
            hz = new_h
            nxt = median(hz)
            if abs(nxt - med_p) < 1e-6:
                break
            med_p = 0.5 * med_p + 0.5 * nxt

    if report is not None:
        ml, mp = median(loud), median(hz)
        for i, t in enumerate(targets):
            got = forward(loud[i], hz[i], ml, mp, cfg)["emphScale"]
            if abs(got - t["emphScale"]) > 1e-6:
                report.append(
                    f"word {i}: emphScale target {t['emphScale']:.3f} -> "
                    f"{got:.3f} (map spans {lo_r:.3f}..{hi_r:.3f})")
    return [{"loudness": l, "pitch_hz": h} for l, h in zip(loud, hz)]


def word_fields(loudness, pitch_hz):
    """The remaining schema-required fields, consistent with the above.

    ``loudness_db`` uses the same affine the built-in tuner line uses; it is
    schema-required but never read by the renderer.
    """
    return {
        "loudness": round(loudness, 6),
        "pitch": round(_clamp01((pitch_hz - 80.0) / 170.0), 6),
        "loudness_db": round(-34.0 + 22.0 * loudness, 3),
        "pitch_hz": round(pitch_hz, 3),
        "voiced_frac": 0.9,
        "conf": 0.95,
    }
