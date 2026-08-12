"""Does the PR film animate WEIGHT? Measured in the same units our DOM reports.

The size envelope was matched to the film and the live stage still looked wrong,
because a per-word size envelope normalises away everything else. Watching
`autocwi live --sample`, our words BOLD UP: measured off the DOM, weight swings a
median of 155 within one word's life and up to 497 (Regular 400 -> nearly 900).
The film's After Effects template has no weight animator at all -- only
`ADBE Text Fill Color` and `ADBE Text Position 3D` -- so if the film really holds
weight constant, that swing is a whole channel we animate and the reference does
not, and no amount of size fitting will make the two look alike.

Reading it off the film needs care. Ink AREA is biased: a swollen word overflows
its fixed slot and the overflow is not counted, which made an earlier area-based
test report 0.72 (apparently LIGHTER) purely from clipping. STROKE THICKNESS does
not have that problem -- it is measured inside the glyph, and dividing by the
glyph's own height makes it scale-invariant, so pure growth leaves it flat.

To compare against our DOM numbers the film's stroke ratio is converted BACK into
a weight, by rendering the project's own Roboto Flex at known weights and
measuring the same ratio.

    .venv/bin/python scripts/weight_diff.py
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion_diff as M  # noqa: E402

FONT = Path("assets/RobotoFlex.ttf")
SAMPLE = "Handgloves"


def stroke_ratio(mask: np.ndarray) -> float | None:
    """Median horizontal ink run length, over the ink's vertical extent.

    Run length inside a glyph IS its stroke thickness. Taking the median over
    every row rejects the serif-free ends and the odd joined pair; dividing by
    the height is what makes a word that merely grew read as unchanged.
    """
    rows = np.where(mask.sum(axis=1) >= 2)[0]
    if len(rows) < 6:
        return None
    height = float(rows[-1] - rows[0] + 1)
    runs: list[int] = []
    for y in rows:
        line = mask[y]
        run = 0
        for value in line:
            if value:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        if run:
            runs.append(run)
    if len(runs) < 8:
        return None
    return float(np.median(runs)) / height


def calibrate() -> list[tuple[int, float]]:
    """Stroke ratio of the project's own face at known weights."""
    from PIL import Image, ImageDraw, ImageFont

    out = []
    probe = ImageFont.truetype(str(FONT), 160)
    axes = probe.get_variation_axes()
    # ROBOTO FLEX HAS 13 AXES and `set_variation_by_axes` wants every one of
    # them, in order. Passing three silently left the default instance, so every
    # weight rendered identically and the calibration was a flat line -- which
    # then "proved" the film's weight never moves, from no data at all.
    weight_index = next(i for i, a in enumerate(axes)
                        if a["name"].decode().lower() == "weight")
    defaults = [a["default"] for a in axes]
    for weight in range(300, 1000, 50):
        font = ImageFont.truetype(str(FONT), 160)
        values = list(defaults)
        values[weight_index] = weight
        font.set_variation_by_axes(values)
        image = Image.new("L", (1600, 320), 0)
        ImageDraw.Draw(image).text((20, 40), SAMPLE, font=font, fill=255)
        ratio = stroke_ratio(np.asarray(image) > 128)
        if ratio:
            out.append((weight, ratio))
    return out


def to_weight(ratio: float, table: list[tuple[int, float]]) -> float:
    xs = np.array([r for _, r in table])
    ys = np.array([w for w, _ in table])
    order = np.argsort(xs)
    return float(np.interp(ratio, xs[order], ys[order]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=float, default=8.0)
    ap.add_argument("--length", type=float, default=58.0)
    args = ap.parse_args()

    table = calibrate()
    if len(table) < 4:
        raise SystemExit("could not calibrate the face -- INVALID, not empty")
    print("Roboto Flex calibration (weight -> stroke/height):")
    print("  " + "  ".join(f"{w}:{r:.3f}" for w, r in table))

    with tempfile.TemporaryDirectory() as tmp:
        frames = M._frames(args.start, args.length, Path(tmp))
        data = [M._masks(f) for f in frames]
        swings, rests, peaks, raw = [], [], [], []
        for lo, hi in M._shots(frames):
            ink, _ = data[hi - 1]
            top, bottom = M._band(ink)
            ink = ink[top:bottom]
            for a, b in M._runs(ink):
                rest_h = float((ink[:, a:b + 1].sum(axis=1) >= 2).sum())
                if rest_h < 10:
                    continue
                series = []
                for i in range(lo, hi):
                    frame, _ = data[i]
                    column = frame[top:bottom, a:b + 1]
                    height = float((column.sum(axis=1) >= 2).sum())
                    ratio = stroke_ratio(column)
                    if ratio:
                        series.append((height / rest_h, ratio))
                if len(series) < 8:
                    continue
                grown = max(series, key=lambda s: s[0])
                if grown[0] < 1.05:
                    continue
                settled = float(np.median([r for h, r in series if h < 1.02]
                                          or [grown[1]]))
                rests.append(to_weight(settled, table))
                peaks.append(to_weight(grown[1], table))
                swings.append(peaks[-1] - rests[-1])
                raw.append(grown[1] / settled if settled else 1.0)

    if not swings:
        raise SystemExit("no film words measured -- INVALID, not empty")
    s = np.array(swings)
    print(f"\n{len(s)} film words that visibly grow.")
    print("WEIGHT swing from the word's own rest to its peak, in font units:")
    for q in (10, 25, 50, 75, 90):
        print(f"  p{q:<3d} {np.percentile(s, q):+7.1f}")
    r = np.array(raw)
    print("\nRAW stroke-thickness ratio, peak / rest "
          "(1.00 = pure growth, no added weight):")
    for q in (25, 50, 75):
        print(f"  p{q:<3d} {np.percentile(r, q):.3f}")
    print(f"\n  film rest weight   median {np.median(rests):.0f}")
    print(f"  film peak weight   median {np.median(peaks):.0f}")
    print("\nOURS, read off the DOM over the same sample:"
          "\n  swing p50 +155.5   p90 +430.4   max +497.2   (400 -> 897)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
