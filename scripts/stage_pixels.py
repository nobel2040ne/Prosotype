"""Measure OUR caption motion from pixels, to compare against the film's.

Every comparison before this measured the film from pixels and our render from
the DOM. Those are not the same quantity: the DOM reports the size a style
resolves to, pixels report the ink a viewer sees.

`motion_diff.py --film` cannot be pointed at our frames — it assumes ONE
caption band and detects cuts by inked-column change, and our stage is a
multi-row wall. Here each row is found and segmented on its own, which the
layout contract makes safe: rows never move once laid out.

    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    .venv/bin/python <scratch>/screencast.py --out /tmp/cast --seconds 18
    .venv/bin/python scripts/stage_pixels.py --frames /tmp/cast
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# The studio's chrome lives above and to the right of the stage; the caption
# block is the left column under the topbar. Cropping to it keeps the rail's
# meters and the topbar's pills out of the ink mask.
STAGE = (60, 470, 30, 940)   # top, bottom, left, right


def masks(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(is_ink, is_turned) for the caption stage of one frame.

    Same rules as the film side: ONE luminance threshold for both ink states, so
    read-ahead white is not eroded relative to coloured ink, and the turn is
    decided by CHROMA rather than by hue, so every speaker colour counts.
    """
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    a = a[STAGE[0]:STAGE[1], STAGE[2]:STAGE[3]]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    ink = lum > 140
    chroma = a.max(axis=2) - a.min(axis=2)
    return ink, ink & (chroma > 40)


def rows_of(ink: np.ndarray, gap: int = 4, floor: int = 6) -> list[tuple[int, int]]:
    """Caption rows: runs of inked scanlines separated by blank ones."""
    live = ink.sum(axis=1) > 0
    out, start, run = [], None, 0
    for y, v in enumerate(list(live) + [False]):
        if v:
            if start is None:
                start = y
            run = 0
        elif start is not None:
            run += 1
            if run > gap:
                if y - run - start >= floor:
                    out.append((start, y - run))
                start = None
    return out


def words_of(row: np.ndarray, gap: int = 5, floor: int = 4) -> list[tuple[int, int]]:
    profile = row.sum(axis=0)
    out, start, run = [], None, 0
    for x, v in enumerate(list(profile) + [0]):
        if v > 0:
            if start is None:
                start = x
            run = 0
        elif start is not None:
            run += 1
            if run > gap:
                if x - run - start >= floor:
                    out.append((start, x - run))
                start = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", required=True, type=Path)
    ap.add_argument("--settle", type=float, default=0.6,
                    help="ignore the first fraction of the capture, so rows are laid out")
    args = ap.parse_args()

    files = sorted(args.frames.glob("*.jpg")) or sorted(args.frames.glob("*.png"))
    if not files:
        raise SystemExit(f"no frames in {args.frames} -- INVALID, not empty")
    stamps = None
    index = args.frames / "index.json"
    if index.is_file():
        stamps = [row["t"] for row in json.loads(index.read_text())]
    if stamps is None or len(stamps) != len(files):
        stamps = [i / 24.0 for i in range(len(files))]

    start = int(len(files) * args.settle)
    data = [masks(f) for f in files[start:]]
    times = stamps[start:]
    # Segment on the LAST frame: every row is laid out and every word settled,
    # so no slot is measured from a frame with motion in it.
    ink_last, _ = data[-1]
    widths, peaks = [], []
    for top, bottom in rows_of(ink_last):
        band = ink_last[top:bottom]
        for a, b in words_of(band):
            rest = float((band[:, a:b + 1].sum(axis=1) >= 2).sum())
            if rest < 6:
                continue
            series = []
            for (ink_i, turned_i), t in zip(data, times):
                column = ink_i[top:bottom, a:b + 1]
                height = float((column.sum(axis=1) >= 2).sum())
                total = column.sum()
                frac = turned_i[top:bottom, a:b + 1].sum() / max(total, 1)
                series.append((t, height / rest, frac))
            values = np.array([v for _, v, _ in series])
            stamps_ = np.array([t for t, _, _ in series])
            # DROP THE APPEARANCE TRANSIENT. Our stage APPENDS words, so a slot
            # segmented on the last frame was empty earlier in the capture, and
            # empty-then-full measures as an enormous swell -- it put the p90
            # visible width at 2558ms, which is a word arriving, not moving.
            # Start each word at the first frame where it is substantially
            # inked, and require it to stay inked afterwards.
            present = np.where(values >= 0.6)[0]
            if len(present) < 6:
                continue
            first = present[0]
            values = values[first:]
            stamps_ = stamps_[first:]
            if (values < 0.4).any():
                continue      # it vanished again: a re-break, not motion
            peak = values.max()
            if not (1.05 < peak < 3.0):
                continue
            half = 1.0 + (peak - 1.0) / 2
            above = np.where(values >= half)[0]
            if len(above) < 2:
                continue
            widths.append(stamps_[above[-1]] - stamps_[above[0]])
            peaks.append(peak)
    if not widths:
        raise SystemExit("no words with a visible swell -- INVALID, not empty")
    w = np.array(widths)
    p = np.array(peaks)
    print(f"{len(w)} of our words measured FROM PIXELS\n")
    print(f"  visible width   p10 {np.percentile(w, 10) * 1000:5.0f}ms   "
          f"p50 {np.median(w) * 1000:5.0f}ms   p90 {np.percentile(w, 90) * 1000:5.0f}ms")
    print(f"  peak            p10 {np.percentile(p, 10):.3f}x   "
          f"p50 {np.median(p):.3f}x   p90 {np.percentile(p, 90):.3f}x")
    print("\n  FILM, same statistic, same code path:")
    print("  visible width   p10   210ms   p50   333ms")
    print(f"\n  under the film's p10: {(w < 0.210).mean() * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
