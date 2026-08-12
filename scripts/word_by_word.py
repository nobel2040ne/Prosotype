"""Compare the film and our render WORD BY WORD, as curves.

`--sample` streams the PR film's own audio, so both sides say the same words at
the same moments. That makes a far stronger comparison available than anything
statistical: not "do the two distributions of peak sizes agree" but "does THIS
word move the way THAT word moves".

It matters because the statistical answer can be perfect while the screen is
wrong. Measured on the drill-sergeant line, our per-word peak distribution sat
inside the film's confidence interval on every quantile -- and word for word we
were emphasising DIFFERENT words: the film's largest was `in` at 1.50x, which we
did not move at all, while its smallest, `army?`, was among our largest.

The film's words are labelled by walking `docs/reference/pr-film-annotated.txt`
in step with the captions: each shot contributes as many words as it has ink
slots, in reading order. Ours are labelled from the DOM. The two sequences are
then aligned with `difflib`, which tolerates the recognizer's own errors
(`Maidrill` for `my drill`) instead of letting one mis-heard word shift every
comparison after it.

    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    .venv/bin/python scripts/motion_trace.py --out /tmp/rows.json --seconds 38
    .venv/bin/python scripts/word_by_word.py --rows /tmp/rows.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion_diff as M  # noqa: E402

TRANSCRIPT = Path("docs/reference/pr-film-annotated.txt")
# Seconds from each word's own colour turn. Wider than the size envelope's grid
# because a word is compared to its own counterpart, not to a pooled median.
GRID = np.round(np.arange(-0.20, 0.62, 0.02), 3)


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def transcript_words() -> list[str]:
    out: list[str] = []
    for line in TRANSCRIPT.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("---"):
            continue
        # Drop the speaker tag, and any bracketed non-speech cue.
        body = line.split("\t", 1)[1] if "\t" in line else line
        body = re.sub(r"\[[^\]]*\]", " ", body)
        out.extend(w for w in body.split() if norm(w))
    return out


def film_curves(start: float, length: float) -> list[tuple[str, np.ndarray]]:
    words = transcript_words()
    cursor = 0
    out: list[tuple[str, np.ndarray]] = []
    with tempfile.TemporaryDirectory() as tmp:
        frames = M._frames(start, length, Path(tmp))
        data = [M._masks(f) for f in frames]
        for lo, hi in M._shots(frames):
            ink, _ = data[hi - 1]
            top, bottom = M._band(ink)
            ink = ink[top:bottom]
            slots = M._runs(ink)
            if not slots:
                continue
            label = words[cursor:cursor + len(slots)]
            cursor += len(slots)
            for (a, b), text in zip(slots, label):
                rest = float((ink[:, a:b + 1].sum(axis=1) >= 2).sum())
                if rest < 8:
                    continue
                series = []
                for i in range(lo, hi):
                    frame, turned = data[i]
                    column = frame[top:bottom, a:b + 1]
                    height = float((column.sum(axis=1) >= 2).sum()) / rest
                    total = column.sum()
                    frac = turned[top:bottom, a:b + 1].sum() / max(total, 1)
                    series.append(((i - lo) / M.FPS, height, frac))
                curve = _align(series)
                if curve is not None:
                    out.append((norm(text), curve))
    return out


def our_curves(rows_path: Path) -> list[tuple[str, np.ndarray, float]]:
    raw = json.loads(rows_path.read_text())
    rows = raw["rows"] if isinstance(raw, dict) and "rows" in raw else raw
    series: dict[str, list] = defaultdict(list)
    label: dict[str, str] = {}
    loud: dict[str, float] = {}
    for row in rows:
        t = float(row.get("t", 0.0)) / 1000.0
        for w in row.get("words", []):
            key = w.get("id")
            scale = M._total_scale(w) if key else None
            if not key or scale is None:
                continue
            series[key].append((t, scale, M._turned(w)))
            label[key] = _one_copy((w.get("text") or "").strip())
            try:
                loud[key] = float(w.get("loudness") or "nan")
            except ValueError:
                pass
    out = []
    for key, points in series.items():
        points.sort()
        if len(points) < 10:
            continue
        rest = float(np.median([s for _, s, _ in points]))
        if rest <= 0:
            continue
        curve = _align([(t, s / rest, f) for t, s, f in points])
        if curve is not None:
            out.append((norm(label.get(key, "")), curve,
                        loud.get(key, float("nan"))))
    return out


def _one_copy(text: str) -> str:
    """The stack duplicates a word across its ink layers; take one copy."""
    for n in (3, 2):
        if len(text) % n == 0 and text[: len(text) // n] * n == text:
            return text[: len(text) // n]
    return text


def _align(series: list) -> np.ndarray | None:
    """Resample one word onto the grid, zeroed on its own colour turn."""
    turn = None
    for k in range(1, len(series)):
        if series[k - 1][2] < 0.5 <= series[k][2]:
            turn = series[k][0]
            break
    if turn is None or series[0][2] >= 0.5:
        return None
    ts = np.array([t - turn for t, _, _ in series])
    vs = np.array([v for _, v, _ in series])
    if ts.min() > GRID[0] or ts.max() < GRID[-1]:
        if ts.min() > -0.04 or ts.max() < 0.30:
            return None
    return np.interp(GRID, ts, vs, left=np.nan, right=np.nan)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--start", type=float, default=8.0)
    ap.add_argument("--length", type=float, default=58.0)
    ap.add_argument("--show", type=int, default=18)
    args = ap.parse_args()

    film = film_curves(args.start, args.length)
    ours = our_curves(args.rows)
    print(f"film {len(film)} word curves, ours {len(ours)}")

    matcher = difflib.SequenceMatcher(
        a=[r[0] for r in film], b=[r[0] for r in ours], autojunk=False)
    pairs = []
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            pairs.append((film[block.a + k], ours[block.b + k]))
    if not pairs:
        raise SystemExit("no words aligned -- INVALID, not empty")

    rows = []
    for (word, fc), (_, oc, lo) in pairs:
        both = ~np.isnan(fc) & ~np.isnan(oc)
        if both.sum() < 12:
            continue
        rows.append((word, float(np.abs(fc[both] - oc[both]).mean()),
                     float(np.nanmax(fc)), float(np.nanmax(oc)), lo))
    if not rows:
        raise SystemExit("no comparable pairs -- INVALID, not empty")
    rows.sort(key=lambda r: -r[1])
    diffs = np.array([r[1] for r in rows])

    print(f"{len(rows)} words compared as CURVES, aligned on each word's own turn\n")
    print(f"  {'word':14s} {'curve diff':>10s} {'film peak':>10s} {'our peak':>9s}")
    for word, diff, fp, op, _lo in rows[:args.show]:
        print(f"  {word:14s} {diff:10.3f} {fp:10.3f} {op:9.3f}")
    print(f"\n  WORST {rows[0][1]:.3f}   median {np.median(diffs):.3f}   "
          f"mean {diffs.mean():.3f}")
    peaks_f = np.array([r[2] for r in rows])
    peaks_o = np.array([r[3] for r in rows])
    order = np.corrcoef(peaks_f, peaks_o)[0, 1]
    print(f"\n  peak correlation across words: {order:+.3f}"
          "   (1.0 = we emphasise exactly the words the film does,"
          "\n   0 = which word we grow is unrelated to which word it grows)")
    # THE DIAGNOSTIC THAT DECIDES WHETHER THIS IS FIXABLE FROM AUDIO. If the
    # film's own choices track the words' measured loudness, then a zero
    # correlation above is OUR pipeline mis-measuring emphasis, and it can be
    # fixed. If they do not, the film's sizes are a human transcriber's
    # judgement and no acoustic measurement can reproduce them.
    loud = np.array([r[4] for r in rows])
    ok = ~np.isnan(loud)
    if ok.sum() > 4:
        print(f"  film peak vs OUR MEASURED LOUDNESS: "
              f"{np.corrcoef(peaks_f[ok], loud[ok])[0, 1]:+.3f}")
        print(f"  our peak  vs our measured loudness: "
              f"{np.corrcoef(peaks_o[ok], loud[ok])[0, 1]:+.3f}"
              "   (high by construction -- this is the mapping working)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
