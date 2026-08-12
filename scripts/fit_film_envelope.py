"""Emit the enhanced motion envelope straight from the film's measured curve.

Hand-fitting a raised cosine to the film got the peak amplitude, peak time and
half-width to within one grid step, and then stalled: the parametric shape has
two knobs (window length, peak fraction) and they trade against each other --
shortening the window moves the peak earlier AND narrows the curve, when the
film wanted earlier AND wider. There is no reason to keep guessing a shape when
the shape has been measured.

This reads `motion_diff.py --film` output and writes:

  * `@keyframes voice-phase-film` / `word-sync-pop-film` -- the film's own
    normalised envelope, resampled onto 0..100% of its own duration
  * the `word_motion_enhanced_ms` and `crest_lag_ms` that place it against the
    word's colour turn

    .venv/bin/python scripts/motion_diff.py --film --out /tmp/film.json
    .venv/bin/python scripts/fit_film_envelope.py /tmp/film.json --write

THE STOPS MUST STAY SORTED. `globals.css` has several animations sharing these
percentages and a first-occurrence replace once landed in the wrong one, leaving
a keyframe list out of order while the page still looked animated.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

CSS = Path("web/src/app/globals.css")
CONFIG = Path("config.yaml")
# Where the envelope is considered to start and end, as a fraction of its peak.
# Not zero: the measured tails are noise around rest, and chasing them would set
# the window from the noise floor rather than from the motion.
FOOT = 0.06


def fit(film: dict) -> dict:
    grid = np.array(film["grid"], float)
    med = np.array([np.nan if v is None else v for v in film["median"]], float)
    ok = ~np.isnan(med)
    grid, med = grid[ok], med[ok]
    # Light smoothing: the reference is a median over a few dozen word curves
    # sampled at 24fps, so single-point wobble is sampling noise, not shape.
    kernel = np.array([0.25, 0.5, 0.25])
    smooth = np.convolve(med, kernel, mode="same")
    smooth[0], smooth[-1] = med[0], med[-1]

    rest = float(np.median(smooth[grid < -0.15])) if (grid < -0.15).any() else 1.0
    peak_i = int(np.argmax(smooth))
    amplitude = float(smooth[peak_i] - rest)
    if amplitude <= 0:
        raise SystemExit("the film curve has no excursion -- INVALID")
    phase = np.clip((smooth - rest) / amplitude, 0.0, 1.0)

    foot = FOOT
    lo = peak_i
    while lo > 0 and phase[lo - 1] > foot:
        lo -= 1
    hi = peak_i
    while hi < len(phase) - 1 and phase[hi + 1] > foot:
        hi += 1
    start, end = float(grid[lo]), float(grid[hi])
    window = end - start
    if window <= 0:
        raise SystemExit("degenerate envelope window -- INVALID")

    stops = np.arange(0, 101, 5)
    sampled = np.interp(start + stops / 100.0 * window, grid, phase)
    sampled[0] = 0.0
    sampled[-1] = 0.0
    return {
        "window_ms": int(round(window * 1000)),
        "lag_ms": int(round(start * 1000)),
        "peak_amplitude": round(amplitude, 4),
        "stops": [(int(p), round(float(v), 3)) for p, v in zip(stops, sampled)],
    }


def render(fitted: dict) -> str:
    inner = "\n".join(
        f"  {p}% {{ --voice-phase: {v:.3f}; }}"
        for p, v in fitted["stops"] if 0 < p < 100)
    pop = "\n".join(
        f"""  {p}% {{
    transform: translate3d(-50%, 0, 0) scale(calc(1 + (var(--sync-pop) - 1) * {v:.3f}));
  }}""" for p, v in fitted["stops"] if 0 < p < 100)
    return f"""
/* THE FILM'S OWN ENVELOPE, resampled from `scripts/motion_diff.py --film` by
   `scripts/fit_film_envelope.py`. Do not hand-edit: re-run the fit.
   Enhanced only -- legacy's `voice-phase` and `word-sync-pop` are untouched.
   Window {fitted['window_ms']}ms, starting {fitted['lag_ms']}ms from the turn. */
@keyframes voice-phase-film {{
  0%, 100% {{ --voice-phase: 0; }}
{inner}
}}

@keyframes word-sync-pop-film {{
  0%, 100% {{
    transform: translate3d(-50%, 0, 0) scale(1);
  }}
{pop}
}}
"""


def write(fitted: dict) -> None:
    css = CSS.read_text()
    for name in ("voice-phase-film", "word-sync-pop-film"):
        i = css.find(f"@keyframes {name} {{")
        if i < 0:
            continue
        depth, j = 1, css.index("{", i) + 1
        while depth and j < len(css):
            depth += (css[j] == "{") - (css[j] == "}")
            j += 1
        head = css.rfind("/*", 0, i)
        start = head if head >= 0 and "@keyframes" not in css[head:i] else i
        css = css[:start] + css[j:]
    CSS.write_text(css.rstrip() + "\n" + render(fitted))

    cfg = CONFIG.read_text()
    cfg = re.sub(r"^(      word_motion_enhanced_ms: ).*$",
                 rf"\g<1>{fitted['window_ms']}", cfg, count=1, flags=re.M)
    cfg = re.sub(r"^(      crest_lag_ms: ).*$",
                 rf"\g<1>{fitted['lag_ms']}", cfg, count=1, flags=re.M)
    CONFIG.write_text(cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("film", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    fitted = fit(json.loads(args.film.read_text()))
    print(f"window {fitted['window_ms']}ms   start {fitted['lag_ms']}ms from turn"
          f"   amplitude {fitted['peak_amplitude']}")
    print("  " + "  ".join(f"{p}%:{v:.2f}" for p, v in fitted["stops"]))
    if args.write:
        write(fitted)
        print("  -> globals.css + config.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
