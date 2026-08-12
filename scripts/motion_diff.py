"""Measure the PR film's per-word motion envelope, and ours, and difference them.

THIS IS THE COMPARISON THE MOTION WORK KEPT LACKING. Four separate attempts to
match `docs/reference/pr-film.mp4` failed the same way: the film was
measured in isolation, a number was fitted, and whether the result actually
matched was left to judgement. Every one of those judgements was wrong. This
measures BOTH sides into the same shape and prints the gap.

The shape is a per-word size envelope, normalised and turn-aligned:

    for each word:  scale(t) = ink_height(t) / ink_height_at_rest
                    t        = seconds from that word's own colour turn

Normalising by the word's own rest is what makes the two comparable at all --
the film's captions are ~40px on a 720p frame and ours are ~16px in a paragraph,
so absolute pixels compare nothing. Aligning on each word's own turn is what
makes the curves stackable across words spoken at different times.

    # the film, straight from the mp4
    .venv/bin/python scripts/motion_diff.py --film --out /tmp/film.json

    # ours, from a motion_trace capture of a running studio
    .venv/bin/python -m autocwi live --sample --lang en --loop --no-open &
    .venv/bin/python scripts/motion_trace.py --out /tmp/rows.json --seconds 40
    .venv/bin/python scripts/motion_diff.py --ours /tmp/rows.json --out /tmp/ours.json

    .venv/bin/python scripts/motion_diff.py --compare /tmp/film.json /tmp/ours.json

WHY THE TWO SIDES ARE MEASURED DIFFERENTLY, and why that is not a cheat: the
film exists only as pixels, so its envelope is segmented off the frames; ours
exists as a DOM, where the same quantity is readable exactly and at 33Hz instead
of 24. Both produce "size relative to this word's own rest, against time from
this word's own turn". Measuring ours through screenshots as well would add
sampling error to the side we can measure exactly.

TRAPS ALREADY PAID FOR, do not re-introduce:
  * A word swollen past ~2x merges with its neighbour under column-gap
    segmentation, so word slots MUST come from a settled frame, never from a
    frame with motion in it.
  * Letters have different ink heights and only some have descenders, so a word
    must be normalised by ITS OWN rest -- never by the line's median, which
    steps to a different letter as words enter and leave and invents excursions
    that are not there.
  * The film cuts between captions. A shot boundary inside a tracked window
    hands one slot two different words; shots are detected and cut.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

FILM = Path("docs/reference/pr-film.mp4")
FPS = 24.0
# The caption band. The film is 1280x720 and the caption sits low; cropping to
# the band keeps the video's own bright pixels out of the ink mask.
# The caption does NOT sit at a fixed height. The Gump section captions low over
# video; the intonation demo captions mid-frame on black. A hardcoded band threw
# away every section but one and left the reference resting on 8 word curves.
BAND = None
# The envelope grid, in seconds from the word's own turn. It starts BEFORE the
# turn because whether the swell leads or follows is exactly what was got wrong.
GRID = np.round(np.arange(-0.30, 0.66, 0.02), 3)


def frames_from_dir(directory: Path) -> tuple[list[Path], float]:
    """Use an already-captured frame directory instead of the film.

    This is what makes a PIXEL-LEVEL comparison possible at all: our render is
    captured by `screencast.py` as real frames, so the film's own segmentation
    and tracking can be run over it unchanged. Measuring one side from pixels
    and the other from the DOM compares two different quantities, however
    carefully each is done.
    """
    files = sorted(p for p in directory.glob("*.jpg")) or \
        sorted(p for p in directory.glob("*.png"))
    if not files:
        raise SystemExit(f"no frames in {directory} -- INVALID, not empty")
    index = directory / "index.json"
    fps = FPS
    if index.is_file():
        stamps = [row["t"] for row in json.loads(index.read_text())]
        if len(stamps) > 2 and stamps[-1] > stamps[0]:
            fps = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    return files, fps


def _frames(start: float, length: float, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start}", "-i", str(FILM),
         "-t", f"{length}", "-vf", f"fps={FPS:g}", str(out / "%04d.png"), "-y"],
        check=True,
    )
    return sorted(out.glob("*.png"))


def _derule(ink: np.ndarray, frac: float = 0.55) -> np.ndarray:
    """Erase the layout guide rules.

    The film draws thin full-width/full-height rules through the caption area.
    ONE full-width rule puts ink in every column, so column-gap segmentation
    collapses a whole line into a single run -- the trap `refmeasure._derule`
    exists for, where a 1029-frame recording yielded 14 glyphs instead of
    hundreds. Text never covers >55% of a row or column; a rule always does.
    """
    out = ink.copy()
    rows = out.mean(axis=1) > frac
    cols = out.mean(axis=0) > frac
    out[rows, :] = False
    out[:, cols] = False
    return out


def _band(ink: np.ndarray, pad: int = 6) -> tuple[int, int]:
    """The caption's own rows, WITH ROOM FOR THE SWELL.

    THE PAD IS NOT COSMETIC. A 6px pad clips any word that grows much past its
    neighbours, and the film's do: measured with no clipping at all, one caption
    ranges 1.03x .. 2.86x, with "louder" at 2.86x. Through a 6px band the whole
    film's p90 came back as 1.394x -- every large word truncated at the band
    edge, the distribution compressed, and a crest ceiling then fitted to it.
    The band is expanded to twice its own height so a 3x word still fits.
    """
    rows = ink.sum(axis=1)
    live = rows > max(8, rows.max() * 0.06)
    best = (0, 0, 0)
    start = None
    for y, v in enumerate(list(live) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            weight = rows[start:y].sum()
            if weight > best[0]:
                best = (weight, start, y)
            start = None
    _, lo, hi = best
    room = max(pad, int((hi - lo) * 1.0))
    return max(0, lo - room), min(ink.shape[0], hi + room)


def _masks(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (is_ink, is_turned) for the caption band of one frame.

    ONE threshold decides ink for both states, and that is not a detail. Testing
    read-ahead white with `r,g,b > 170` while testing turned colour with a hue
    rule is a STRICTER test for white: antialiased glyph edges drop out of the
    white mask and survive the coloured one, so an untouched word measures a
    couple of pixels shorter. On a 22px cap that is ~9%, and it read as the film
    rendering its read-ahead words at 0.91x -- a motion channel that does not
    exist, invented entirely by the measurement.
    """
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # 190 IS VALIDATED, not chosen. On the drill-sergeant line -- seven words,
    # segmented by eye -- this is the threshold whose column-gap segmentation
    # returns exactly seven slots; 150 and 170 split letters into fragments and
    # measure the fragments as words. The turn->peak offset is +0.08..+0.12s at
    # EVERY threshold, so that finding does not depend on this choice.
    ink = _derule(lum > 190)
    # SATURATION, not hue. Matching green-and-yellow only was a hue rule for the
    # two speakers of the drill-sergeant line, and CWI assigns a whole palette:
    # every word in any other speaker's colour was classified as never turning,
    # which silently discarded 50 of 136 word slots -- a third of the reference.
    # Read-ahead ink is white and settled ink is a saturated hue whatever the
    # speaker, so the distinction is chroma.
    chroma = a.max(axis=2) - a.min(axis=2)
    turned = ink & (chroma > 40)
    return ink, turned


def _runs(mask: np.ndarray, gap: int = 9, floor: int = 5) -> list[tuple[int, int]]:
    """Column-gap segmentation into word slots."""
    profile = mask.sum(axis=0)
    out: list[tuple[int, int]] = []
    start = None
    run = 0
    for x, v in enumerate(profile):
        if v > 0:
            if start is None:
                start = x
            run = 0
        elif start is not None:
            run += 1
            if run > gap:
                out.append((start, x - run))
                start = None
    if start is not None:
        out.append((start, len(profile) - 1))
    return [(a, b) for a, b in out if b - a >= floor]


def _shots(frames: list[Path]) -> list[tuple[int, int]]:
    """Split the frame list where the CAPTION changes.

    Correlating column profiles was tried first and is wrong: a word popping
    changes its own columns enough to drop the correlation below any useful
    threshold, so a caption got cut mid-life -- 37 shots with a median length of
    one second, and 101 of 153 word slots then had no colour turn inside their
    own shot because the turn fell in a neighbouring fragment. Only 28 curves
    survived, from a film with roughly 150 words.

    Overlap of the inked COLUMN SET is the right signal. A swelling word keeps
    almost all of its columns and adds a few; a new caption replaces them.
    """
    supports = []
    for f in frames:
        ink, _ = _masks(f)
        top, bottom = _band(ink)
        supports.append(ink[top:bottom].sum(axis=0) > 0)
    cuts = [0]
    for i in range(1, len(supports)):
        p, q = supports[i - 1], supports[i]
        if p.sum() < 20 or q.sum() < 20:
            continue
        union = (p | q).sum()
        overlap = (p & q).sum() / union if union else 1.0
        if overlap < 0.55:
            cuts.append(i)
    cuts.append(len(frames))
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= 12]


def film_envelope(start: float, length: float,
                  directory: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        global FPS
        if directory is not None:
            frames, fps = frames_from_dir(directory)
            FPS = fps
        else:
            frames = _frames(start, length, Path(tmp))
        if not frames:
            raise SystemExit("no frames")
        data = [_masks(f) for f in frames]
        curves: list[list[tuple[float, float]]] = []
        for lo, hi in _shots(frames):
            # Slots come from the LAST frame of the shot: every word has turned
            # and every word is back at rest, so nothing is mid-swell.
            settled_ink, _settled_turned = data[hi - 1]
            # The band is found ONCE per shot, from its settled frame, and then
            # applied to every frame of that shot -- so a word swelling out of
            # the band cannot move the band under its own measurement.
            top, bottom = _band(settled_ink)
            settled_ink = settled_ink[top:bottom]
            slots = _runs(settled_ink)
            for a, b in slots:
                rest = float((settled_ink[:, a:b + 1].sum(axis=1) >= 2).sum())
                if rest < 8:
                    continue
                series = []
                for i in range(lo, hi):
                    ink_i, turned_i = data[i]
                    ink_i = ink_i[top:bottom]
                    turned_i = turned_i[top:bottom]
                    column = ink_i[:, a:b + 1]
                    # VERTICAL EXTENT, and both alternatives were tried first.
                    # Max-column height keys on one antialiased stroke: swept
                    # across ink thresholds it returned 1.05x, 2.00x, 1.14x and
                    # 1.40x for the same film, i.e. it measured the threshold.
                    # Ink AREA is stable but biased low -- a popped word
                    # overflows its slot, and the slot is fixed at the word's
                    # settled extent, so the overflow is simply not counted.
                    # Vertical extent has neither problem: overflow is
                    # horizontal, and requiring 2px per row rejects stray edge
                    # pixels without keying on any single one.
                    rows = (column.sum(axis=1) >= 2)
                    height = float(rows.sum())
                    total = column.sum()
                    frac = turned_i[:, a:b + 1].sum() / max(total, 1)
                    series.append(((i - lo) / FPS, height / rest, frac))
                turn = None
                for k in range(1, len(series)):
                    if series[k - 1][2] < 0.5 <= series[k][2]:
                        turn = series[k][0]
                        break
                if turn is None:
                    continue
                curves.append([(t - turn, s) for t, s, _ in series])
    label = (f"pixels {directory.name}" if directory is not None
             else f"PR film {start:g}-{start + length:g}s")
    return _stack(curves, label)


def _stack(curves: list[list[tuple[float, float]]], label: str) -> dict:
    """Resample every word onto the shared grid and take the median."""
    rows = []
    for c in curves:
        ts = np.array([t for t, _ in c])
        vs = np.array([v for _, v in c])
        if ts.min() > GRID[0] or ts.max() < GRID[-1]:
            # Only keep words whose own window covers the grid, so the median is
            # not a different population at each end.
            if ts.min() > -0.06 or ts.max() < 0.30:
                continue
        rows.append(np.interp(GRID, ts, vs, left=np.nan, right=np.nan))
    if not rows:
        raise SystemExit(f"{label}: no usable word curves -- INVALID, not empty")
    stack = np.vstack(rows)
    median = np.nanmedian(stack, axis=0)
    # PER-WORD PEAKS, not just the median curve. The film's pop is emphasis
    # scaled -- calm narration peaks ~1.09x and the shouted drill-sergeant line
    # ~1.28x -- so a matching median can still hide a system that pops every
    # word by the same amount. The spread is what tests that.
    peaks = np.nanmax(stack, axis=1)
    # WHERE each word peaks, not just how high. If a pointwise median sits far
    # below the median per-word peak, the words are not peaking together -- and
    # whether that is true is a fact about the reference, not an inference.
    offsets = []
    for row in stack:
        if np.all(np.isnan(row)):
            continue
        offsets.append(float(GRID[int(np.nanargmax(row))]))
    peaks = peaks[~np.isnan(peaks)]
    # Keep the raw per-word peaks so `--compare` can bootstrap a confidence
    # interval. The film yields few word curves, so a percentile difference is
    # only meaningful once it is bigger than the reference's own sampling error;
    # without this the tool invites tuning against noise, which is the failure
    # mode this whole comparison exists to end.
    return {
        "label": label,
        "words": int(stack.shape[0]),
        "grid": [float(x) for x in GRID],
        "median": [None if np.isnan(v) else round(float(v), 4) for v in median],
        "peak_p25": round(float(np.percentile(peaks, 25)), 4),
        "peak_p50": round(float(np.percentile(peaks, 50)), 4),
        "peak_p75": round(float(np.percentile(peaks, 75)), 4),
        "peak_p90": round(float(np.percentile(peaks, 90)), 4),
        "peaks": [round(float(v), 4) for v in peaks],
        "offsets": [round(v, 4) for v in offsets],
        # Every word curve, so `--compare` can bootstrap the median CURVE
        # too. Its peak, peak time and width are statistics of a few dozen
        # words like any other, and treating them as exact invites tuning
        # against the reference's own sampling noise.
        "curves": [[None if np.isnan(v) else round(float(v), 4) for v in row]
                   for row in stack],
    }


def ours_envelope(rows_path: Path) -> dict:
    """Build the same envelope from a `motion_trace.py` capture."""
    raw = json.loads(rows_path.read_text())
    rows = raw["rows"] if isinstance(raw, dict) and "rows" in raw else raw
    by_word: dict[str, list[tuple[float, float, float]]] = {}
    for row in rows:
        # `motion_trace` records `performance.now()`, which is MILLISECONDS.
        # Reading it as seconds put every curve outside the grid and produced a
        # perfectly flat envelope -- a wrong answer that looked like a result.
        t = float(row.get("t", 0.0)) / 1000.0
        for w in row.get("words", []):
            key = str(w.get("id") or w.get("word_id") or "")
            if not key:
                continue
            scale = _total_scale(w)
            if scale is None:
                continue
            by_word.setdefault(key, []).append((t, scale, _turned(w)))
    curves = []
    for series in by_word.values():
        series.sort()
        if len(series) < 8:
            continue
        rest = float(np.median([s for _, s, _ in series]))
        if rest <= 0:
            continue
        # THE TURN MUST BE THE WORD'S OWN, and this filter is why the numbers
        # were wrong without it. A word spoken before the capture starts sits on
        # the stage as settled history; when speaker attribution finally
        # resolves, its colour changes -- and a naive white->coloured detector
        # calls that a turn. Those words then contribute a perfectly FLAT curve
        # (measured: 1.000x across 1415 samples), which dragged our peak p25 to
        # 1.000 where the film's is 1.107. The film has no attribution lane and
        # so no such population. Require the word to be in read-ahead ink when
        # first seen, and to turn soon after.
        if series[0][2] >= 0.5:
            continue
        turn = None
        for k in range(1, len(series)):
            if series[k - 1][2] < 0.5 <= series[k][2]:
                turn = series[k][0]
                break
        if turn is None or turn - series[0][0] > 3.0:
            continue
        # NOT jittered. Injecting the film's +-1 frame landmark error into our
        # turn was tried, on the theory that its pointwise median is smeared by
        # measurement: it moved our curve peak only 1.138 -> 1.131 against the
        # film's 1.092, so that is NOT what the gap is. See the note in
        # docs/MOTION.md -- the film's per-word timing genuinely varies, because
        # its AE selector sweeps an EASED ramp across the whole caption rather
        # than starting each word at its own spoken onset.
        # QUANTISE OUR TURN TO THE FILM'S FRAME RATE. The film is 24fps, so its
        # turn landmark carries up to +-1 frame of error, and that error smears
        # the pointwise median: its median CURVE peaks at 1.0916x while its
        # median PER-WORD peak is 1.156x. Our turn is read from the DOM at 33Hz
        # and is effectively exact, so our two statistics agree with each other
        # and cannot both match the film's. Comparing a sub-frame measurement
        # against a frame-quantised one is comparing different resolutions --
        # the fix is to measure ours the way the film can be measured, not to
        # add jitter to the renderer, which would be fabricating motion.
        turn = round(turn * FPS) / FPS
        curves.append([(t - turn, s / rest) for t, s, _ in series])
    return _stack(curves, f"ours ({rows_path.name})")


def _total_scale(w: dict) -> float | None:
    """Font size times any transform scale -- the visible size, not one layer."""
    size = w.get("fontSize")
    if size is None:
        return None
    try:
        value = float(str(size).replace("px", ""))
    except ValueError:
        return None
    matrix = str(w.get("transform") or "")
    if matrix.startswith("matrix("):
        try:
            parts = [float(x) for x in matrix[7:-1].split(",")]
            value *= abs(parts[0])
        except (ValueError, IndexError):
            pass
    return value


def _turned(w: dict) -> float:
    """1 once the word carries its speaker colour, 0 while in read-ahead ink."""
    colour = str(w.get("color") or w.get("inkColor") or "")
    if not colour:
        return float(w.get("turned", 0.0) or 0.0)
    nums = [int(n) for n in _digits(colour)][:3]
    if len(nums) < 3:
        return 0.0
    r, g, b = nums
    return 0.0 if (r > 170 and g > 170 and b > 170) else 1.0


def _digits(text: str) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if ch.isdigit():
            cur += ch
        elif cur:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def summarise(env: dict) -> dict:
    """Peak height, peak time and half-width -- all SUB-GRID.

    Reading these straight off the grid quantises them to the 0.02s step, which
    is not a property of the motion but of the sampling: a genuine 0.005s
    difference reports as either 0.000 or 0.020 depending on which side of a
    grid point it lands. That made the last two figures un-closeable -- fitting
    the width exact threw the peak time one step out and vice versa, forever.
    The peak is interpolated parabolically through its three highest points and
    the half-maximum crossings linearly, so both are continuous and a fit can
    actually converge.
    """
    grid = np.array(env["grid"])
    med = np.array([np.nan if v is None else v for v in env["median"]], float)
    ok = ~np.isnan(med)
    if not ok.any():
        return {}
    g, m = grid[ok], med[ok]
    i = int(np.argmax(m))
    base = float(np.nanmedian(m[g < -0.15])) if (g < -0.15).any() else 1.0

    # Parabolic vertex through (i-1, i, i+1): sub-sample peak time and height.
    if 0 < i < len(m) - 1:
        y0, y1, y2 = m[i - 1], m[i], m[i + 1]
        denom = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denom if denom else 0.0
        shift = float(np.clip(shift, -1.0, 1.0))
        step = float(g[i + 1] - g[i])
        peak_at = float(g[i]) + shift * step
        peak = float(y1 - 0.25 * (y0 - y2) * shift)
    else:
        peak_at, peak = float(g[i]), float(m[i])

    half = base + (peak - base) / 2
    def cross(lo: int, hi: int) -> float | None:
        """Where the curve passes `half` between two samples, interpolated."""
        a, b = m[lo], m[hi]
        if (a - half) * (b - half) > 0 or a == b:
            return None
        return float(g[lo] + (half - a) / (b - a) * (g[hi] - g[lo]))
    left = right = None
    for k in range(i, 0, -1):
        left = cross(k - 1, k)
        if left is not None:
            break
    for k in range(i, len(m) - 1):
        right = cross(k, k + 1)
        if right is not None:
            break
    width = (right - left) if (left is not None and right is not None) else 0.0
    return {
        "peak": round(peak, 4),
        "peak_at_s": round(peak_at, 4),
        "width_s": round(width, 4),
        "rest": round(base, 4),
    }


def compare(a: dict, b: dict) -> int:
    sa, sb = summarise(a), summarise(b)
    ga = np.array(a["grid"])
    ma = np.array([np.nan if v is None else v for v in a["median"]], float)
    mb = np.array([np.nan if v is None else v for v in b["median"]], float)
    both = ~np.isnan(ma) & ~np.isnan(mb)
    diff = np.abs(ma[both] - mb[both])
    print(f"\n  {'':14s} {a['label'][:26]:>26s}  {b['label'][:26]:>26s}   diff")
    print(f"  {'words':14s} {a['words']:26d}  {b['words']:26d}")
    for key, unit in (("peak", "x"), ("peak_at_s", "s"), ("width_s", "s")):
        va, vb = sa.get(key), sb.get(key)
        if va is None or vb is None:
            continue
        print(f"  {key:14s} {va:25.4f}{unit}  {vb:25.4f}{unit}   {abs(va - vb):+.4f}")
    fa = np.array(a.get("peaks") or [])
    rng = np.random.default_rng(20260812)   # seeded: this must be reproducible
    for key, q in (("peak_p25", 25), ("peak_p50", 50),
                   ("peak_p75", 75), ("peak_p90", 90)):
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            continue
        note = ""
        if len(fa) > 4:
            draws = rng.choice(fa, size=(2000, len(fa)), replace=True)
            lo, hi = np.percentile(np.percentile(draws, q, axis=1), [2.5, 97.5])
            inside = lo <= vb <= hi
            note = f"  film 95% CI {lo:.3f}-{hi:.3f}  {'WITHIN' if inside else 'OUTSIDE'}"
        print(f"  {key:14s} {va:25.3f}x  {vb:25.3f}x   {abs(va - vb):+.3f}{note}")
    # Bootstrap the film's median CURVE, then ask whether our three envelope
    # statistics fall inside it. This is the difference between "ours is 0.037
    # from the film's number" and "ours is outside what the film's own sample
    # can pin down" -- only the second is a real disagreement.
    rows = a.get("curves")
    if rows:
        arr = np.array([[np.nan if v is None else v for v in r] for r in rows], float)
        rng = np.random.default_rng(20260812)
        stats = {"peak": [], "peak_at_s": [], "width_s": []}
        for _ in range(400):
            pick = rng.integers(0, arr.shape[0], arr.shape[0])
            boot = {"grid": a["grid"],
                    "median": [None if np.isnan(v) else float(v)
                               for v in np.nanmedian(arr[pick], axis=0)]}
            got = summarise(boot)
            for k in stats:
                if k in got:
                    stats[k].append(got[k])
        print()
        for key, unit in (("peak", "x"), ("peak_at_s", "s"), ("width_s", "s")):
            vals = np.array(stats[key])
            if not len(vals) or sb.get(key) is None:
                continue
            lo, hi = np.percentile(vals, [2.5, 97.5])
            inside = lo <= sb[key] <= hi
            print(f"  {key:14s} film 95% CI {lo:.4f}-{hi:.4f}{unit}   ours "
                  f"{sb[key]:.4f}{unit}   {'WITHIN' if inside else 'OUTSIDE'}")
    print(f"\n  envelope difference   max {diff.max():.3f}   mean {diff.mean():.3f}"
          f"   ({both.sum()} grid points compared)")
    print("\n  curve, size relative to the word's own rest:")
    print(f"  {'t from turn':>12} {'film':>8} {'ours':>8} {'diff':>8}")
    for i, t in enumerate(ga):
        if not both[i] or round(float(t), 2) % 0.06 > 0.021:
            continue
        print(f"  {t:12.2f} {ma[i]:8.3f} {mb[i]:8.3f} {ma[i] - mb[i]:+8.3f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--film", action="store_true")
    ap.add_argument("--frames", type=Path,
                    help="measure a captured frame directory with the SAME "
                         "pipeline the film gets")
    ap.add_argument("--start", type=float, default=28.0)
    ap.add_argument("--length", type=float, default=17.0)
    ap.add_argument("--ours", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--compare", nargs=2, type=Path)
    args = ap.parse_args()

    if args.compare:
        a = json.loads(args.compare[0].read_text())
        b = json.loads(args.compare[1].read_text())
        return compare(a, b)
    if args.frames:
        env = film_envelope(args.start, args.length, directory=args.frames)
    elif args.film:
        env = film_envelope(args.start, args.length)
    elif args.ours:
        env = ours_envelope(args.ours)
    else:
        ap.error("one of --film, --ours or --compare")
    print(f"{env['label']}: {env['words']} word curves")
    s = summarise(env)
    print(f"  peak {s.get('peak')}x at {s.get('peak_at_s')}s from turn, "
          f"half-width {s.get('width_s')}s")
    if args.out:
        args.out.write_text(json.dumps(env, indent=1))
        print(f"  -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
