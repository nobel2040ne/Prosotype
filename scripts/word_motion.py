#!/usr/bin/env python3
"""Per-word motion measurement for the live stage. ONE WORD PER ROW, no slopes.

WHY THIS EXISTS. Four different ad-hoc metrics gave confidently wrong answers
in a single session, and each one cost a round of chasing a bug that was not
there:

  * ``max/min`` over a word's samples CANNOT TELL GROWTH FROM SHRINKAGE.
    "softer" was reported as rendering 1.27x and chased as a defect; 1.27 was
    ``rest / crest`` and the word was correctly shrinking to 0.79x, which is
    what the film draws. Peak and floor are separate quantities and are
    reported separately here, both against the word's OWN rest.
  * "bold for X% of its life" divides by the wrong denominator. A word sits
    settled on the stage for many seconds after a ~1 s motion, so 7% of a 15 s
    life IS about a second -- the statistic says nothing about the motion. All
    durations here are measured INSIDE the motion window.
  * A whole-span average buries the thing being looked for (see ``_span_db``
    in ``autocwi/live.py``: span-median dB made "louder" look quieter than its
    neighbours and produced a wrong project-wide conclusion).
  * A word sampled only while settled is NOT a word that did not move -- it is
    a word that was not observed moving. Those are counted and excluded, never
    silently averaged in as 1.00x.

DEFINITIONS, all per word and all against that word's own resting value:

  rest    the MODAL sample value. A word is settled for most of its life, so
          the mode is its rest -- robust to the motion and to outliers in a
          way the mean and the min are not.
  window  the contiguous run of samples around the extreme in which the value
          differs from rest by more than ``--tol``. Everything temporal is
          measured in here.
  peak    max/rest inside the window (>= 1.0). growth.
  floor   min/rest inside the window (<= 1.0). shrink.
  above   seconds at or past half of the peak EXCURSION, i.e. the width of the
          motion, comparable with the film's own half-peak spans.

Usage:
    scripts/word_motion.py --trace rows.json            # table, every word
    scripts/word_motion.py --trace rows.json --words louder,softer,is
    scripts/word_motion.py --trace rows.json --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict


def _num(value, fallback=float("nan")) -> float:
    try:
        return float(str(value).rstrip("px").strip())
    except (TypeError, ValueError):
        return fallback


def _scale(transform: str) -> float:
    """The uniform scale in a CSS matrix, 1.0 if absent.

    THE 2.2.3 POP IS A TRANSFORM ON `.word-glyph`, NOT A FONT-SIZE. Reading
    font-size alone sees only the 2.3 crest, so every word whose prominence is
    zero looks like it never moved -- 21 of 31 words on the drill-sergeant line
    were reported as "only sampled settled" for exactly this reason, when they
    were popping the whole time. Effective type size is
    `font-size x glyph scale`, which is what CLAUDE.md's comparison recipe
    already specifies.
    """
    if not transform or transform == "none":
        return 1.0
    nums = re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", transform)
    if len(nums) < 4:
        return 1.0
    a, d = float(nums[0]), float(nums[3])
    return (abs(a) + abs(d)) / 2 or 1.0


def _base_text(raw: str) -> str:
    """The stage repeats a word's text once per sizer, so 'is' arrives as
    'isisis'. Recover the unit rather than trusting the whole string."""
    flat = re.sub(r"\W", "", raw or "").lower()
    if not flat:
        return ""
    for parts in (3, 2):
        if len(flat) % parts == 0:
            unit = len(flat) // parts
            if flat == flat[:unit] * parts:
                return flat[:unit]
    return flat


@dataclass
class WordMotion:
    text: str
    chars: int
    n_samples: int
    observed_moving: bool
    rest_px: float
    peak: float            # max / rest, >= 1
    floor: float           # min / rest, <= 1
    above_half_s: float    # width of the motion at half its excursion
    window_s: float
    weight_rest: float
    weight_peak: float
    weight_floor: float
    lift_em: float


def _mode(values: list[float], quantum: float) -> float:
    """Modal value, bucketed -- floats never repeat exactly."""
    if not values:
        return float("nan")
    counts = Counter(round(v / quantum) for v in values)
    best = max(counts.items(), key=lambda kv: (kv[1], -abs(kv[0])))
    return best[0] * quantum


def _window(values: list[float], rest: float, tol: float) -> tuple[int, int]:
    """Contiguous run around the largest excursion where value != rest."""
    if not values:
        return 0, 0
    dev = [abs(v - rest) for v in values]
    peak = max(range(len(values)), key=lambda i: dev[i])
    if dev[peak] <= tol:
        return peak, peak + 1
    lo = peak
    while lo > 0 and dev[lo - 1] > tol:
        lo -= 1
    hi = peak
    while hi + 1 < len(values) and dev[hi + 1] > tol:
        hi += 1
    return lo, hi + 1


def measure(samples: list[dict], text: str, tol_px: float) -> WordMotion:
    times = [s["t"] for s in samples]
    sizes = [s["size"] for s in samples]
    weights = [s["weight"] for s in samples]

    rest = _mode(sizes, 0.25)
    lo, hi = _window(sizes, rest, tol_px)
    win_t, win_v = times[lo:hi], sizes[lo:hi]
    moving = (hi - lo) > 1

    peak = max(win_v) / rest if moving and rest else 1.0
    floor = min(win_v) / rest if moving and rest else 1.0

    # Half of the EXCURSION, on whichever side actually moved -- a shrinking
    # word's half-peak is below rest, not above it.
    above = 0.0
    if moving:
        grow, shrink = max(win_v) - rest, rest - min(win_v)
        if grow >= shrink:
            mark = rest + grow / 2
            hit = [t for t, v in zip(win_t, win_v) if v >= mark]
        else:
            mark = rest - shrink / 2
            hit = [t for t, v in zip(win_t, win_v) if v <= mark]
        if len(hit) > 1:
            above = hit[-1] - hit[0]

    w_rest = _mode(weights, 5.0)
    w_win = weights[lo:hi] if moving else weights
    return WordMotion(
        text=text,
        chars=len(text),
        n_samples=len(samples),
        observed_moving=moving,
        rest_px=round(rest, 2),
        peak=round(peak, 3),
        floor=round(floor, 3),
        above_half_s=round(above, 3),
        window_s=round(win_t[-1] - win_t[0], 3) if len(win_t) > 1 else 0.0,
        weight_rest=round(w_rest, 0),
        weight_peak=round(max(w_win), 0),
        weight_floor=round(min(w_win), 0),
        lift_em=round(max(s["lift"] for s in samples), 3),
    )


def load(path: str) -> dict[tuple[int, str], list[dict]]:
    rows = json.load(open(path))
    t0 = rows[0]["t"]
    seq: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in rows:
        t = (row["t"] - t0) / 1000.0
        for index, word in enumerate(row.get("words", [])):
            text = _base_text(word.get("text", ""))
            if not text:
                continue
            lift = word.get("holdLift") or "0em"
            seq[(index, text)].append({
                "t": t,
                "size": _num(word.get("fontSize"), 0.0)
                        * _scale(word.get("transform", "")),
                "weight": _num(word.get("weight"), 400.0),
                "lift": _num(str(lift).replace("em", ""), 0.0),
            })
    return seq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="rows.json from motion_trace")
    ap.add_argument("--words", default="", help="comma-separated filter")
    ap.add_argument("--min-samples", type=int, default=8)
    ap.add_argument("--tol-px", type=float, default=0.4)
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    wanted = {w.strip().lower() for w in args.words.split(",") if w.strip()}
    seq = load(args.trace)

    measured, unobserved = [], []
    for (_, text), samples in seq.items():
        if len(samples) < args.min_samples:
            continue
        if wanted and text not in wanted:
            continue
        m = measure(samples, text, args.tol_px)
        (measured if m.observed_moving else unobserved).append(m)

    if not measured:
        print("no word was observed in motion — nothing to conclude")
        return 1

    print(f"{len(measured)} words observed IN MOTION; "
          f"{len(unobserved)} only ever sampled settled (excluded, not counted as 1.00x)")
    print()
    print(f"{'word':<16}{'ch':>3}{'peak':>7}{'floor':>7}{'wght':>6}"
          f"{'w.lo':>6}{'half':>7}{'win':>7}{'lift':>7}")
    for m in sorted(measured, key=lambda m: -m.peak):
        light = "*" if m.weight_floor < 395 else " "
        print(f"{m.text:<16}{m.chars:>3}{m.peak:>7.2f}{m.floor:>7.2f}"
              f"{m.weight_peak:>6.0f}{m.weight_floor:>6.0f}{light}"
              f"{m.above_half_s:>6.2f}{m.window_s:>7.2f}{m.lift_em:>7.3f}")

    grew = [m for m in measured if m.peak > 1.02]
    shrank = [m for m in measured if m.floor < 0.98]
    light = [m for m in measured if m.weight_floor < 395]
    print()
    print(f"  grew  {len(grew):>3}   median peak  "
          f"{statistics.median([m.peak for m in grew]) if grew else float('nan'):.2f}")
    print(f"  shrank{len(shrank):>3}   median floor "
          f"{statistics.median([m.floor for m in shrank]) if shrank else float('nan'):.2f}")
    print(f"  rendered LIGHTER than Regular: {len(light)}  "
          f"{sorted(m.text for m in light)[:8]}")
    print(f"  lifted {len([m for m in measured if m.lift_em > 0.02])}")

    if args.csv:
        with open(args.csv, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(measured[0])))
            writer.writeheader()
            for m in measured:
                writer.writerow(asdict(m))
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
