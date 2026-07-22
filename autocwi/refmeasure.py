"""Measuring caption motion from pixels — the reference recordings, and us.

Both sides of every comparison must run byte-identical segmentation, so this is
the single home for it: ``glyphs_array`` is the core, ``glyphs`` reads a file,
and the comparison harness feeds it slices of a screenshot sheet from memory.

The recordings in ``docs/`` are ~57 fps screen captures (frames/duration — NOT
the 120 fps the container claims). Two of the three scroll the caption line
horizontally, which breaks nearest-centre tracking: a line advancing ~4.5 px per
frame on average, lurching between words, fragmented one recording into 2249
tracks against 141 for the static one. ``scroll_offsets`` recovers the scroll as
a continuous sub-pixel curve so tracking can run in world coordinates — and that
same curve is the ground truth the renderer's own tracking mode is fitted to.
"""
from __future__ import annotations

import glob
import sys

import numpy as np
from PIL import Image

# Ink threshold, and the minimum blank columns that separate two glyph runs.
INK = 70
GAP = 2


def _derule(ink, frac=0.55):
    """Erase full-width and full-height rules before segmenting.

    The reference site draws thin layout guides across the caption band and a
    vertical playhead through it. A single full-width rule puts ink in EVERY
    column, so the column-gap segmentation below collapses the whole line into
    one run — measured, that took a 1029-frame recording from hundreds of
    glyphs to 14. Text never covers this much of a row or column, so the test
    is safe; it also removes the playhead, which must not be measured as a
    glyph.
    """
    h, w = ink.shape
    out = ink.copy()
    out[ink.sum(axis=1) > frac * w, :] = False
    out[:, ink.sum(axis=0) > frac * h] = False
    return out


def glyphs_array(rgb):
    """Segment one frame into glyph runs with position, size and saturation.

    ``rgb`` is a float array, H x W x 3. Saturation is what identifies the
    colour turn: unspoken text is white/grey and unsaturated, spoken text
    carries the speaker's colour.
    """
    lum = rgb.max(axis=2)
    ink = _derule(lum > INK)
    cols = ink.any(axis=0)
    runs, start, gap = [], None, 0
    for x in range(len(cols)):
        if cols[x]:
            if start is None:
                start = x
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= GAP:
                    runs.append((start, x - gap))
                    start = None
    if start is not None:
        runs.append((start, len(cols) - 1))

    out = []
    for x0, x1 in runs:
        if x1 - x0 < 3:
            continue
        # Threshold RELATIVE to this glyph's own peak luminance. A fixed
        # threshold measures a yellow glyph and a white glyph differently
        # (their anti-aliased edges sit at different absolute levels), which
        # shows up as a spurious size change exactly at the colour turn.
        band = lum[:, x0:x1 + 1]
        # ...and still masked by the de-ruled ink, or a guide line crossing the
        # glyph would be counted as part of it and inflate its height.
        sub = (band > 0.5 * band.max()) & ink[:, x0:x1 + 1]
        rows = np.nonzero(sub.any(axis=1))[0]
        if len(rows) < 4:
            continue
        px = rgb[:, x0:x1 + 1][sub]
        mx = px.max(axis=1); mn = px.min(axis=1)
        sat = float(np.mean((mx - mn) / np.maximum(mx, 1e-6)))
        out.append(dict(xc=(x0 + x1) / 2.0, x0=x0, x1=x1,
                        top=float(rows[0]), bot=float(rows[-1]),
                        h=float(rows[-1] - rows[0]), sat=sat,
                        ink=float(sub.sum()),
                        # Touching the crop boundary means the glyph is CLIPPED
                        # -- its height and ink are partial. A scrolling line
                        # clips its first and last words for many frames, and
                        # measuring "rest" from those made the final word of a
                        # line read as the most emphasised on screen.
                        edge=bool(x0 <= 2 or x1 >= lum.shape[1] - 3)))
    return out


def glyphs(path):
    """``glyphs_array`` for a frame on disk."""
    return glyphs_array(np.asarray(Image.open(path).convert("RGB")).astype(np.float32))


# ---------------------------------------------------------------------------
# Horizontal scroll recovery
# ---------------------------------------------------------------------------

def _profile(rgb):
    """Column ink profile. The MASK, not luminance: the colour turn changes
    luminance a lot and the ink mask almost not at all, so correlating masks
    tracks position without being dragged around by the colour."""
    return (rgb.max(axis=2) > INK).sum(axis=0).astype(np.float64)


def _lag(a, b, max_lag):
    """Sub-pixel lag of ``a`` against ``b`` by normalised cross-correlation.

    Returns ``(lag, peak)``; ``peak`` is the correlation at the best lag, which
    the caller uses to reject blocks where text is entering the crop and to
    detect the speaker change (where the two profiles share nothing).
    """
    a = a - a.mean(); b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0, 0.0
    a, b = a / na, b / nb
    lags = np.arange(-max_lag, max_lag + 1)
    scores = np.empty(len(lags))
    for i, L in enumerate(lags):
        if L < 0:
            scores[i] = float(np.dot(a[-L:], b[:len(b) + L]))
        elif L > 0:
            scores[i] = float(np.dot(a[:len(a) - L], b[L:]))
        else:
            scores[i] = float(np.dot(a, b))
    k = int(np.argmax(scores))
    peak = float(scores[k])
    # parabolic refinement through the peak and its neighbours
    if 0 < k < len(scores) - 1:
        y0, y1, y2 = scores[k - 1], scores[k], scores[k + 1]
        denom = y0 - 2 * y1 + y2
        sub = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
    else:
        sub = 0.0
    return float(lags[k] + np.clip(sub, -1, 1)), peak


def scroll_offsets(frames, max_lag=60, blocks=4, reject=0.5, cut=0.35,
                   refine=2):
    """Recover each frame's horizontal scroll offset, in pixels.

    Returns ``(s, segments)``: ``s[f]`` is the offset of frame ``f`` in a shared
    world coordinate (add it to a glyph's ``xc``), and ``segments`` is a list of
    ``(first, last)`` frame indices between which ``s`` is continuous. A
    segment break is a speaker change — the profiles share nothing, correlation
    collapses, and integrating across it would be meaningless.

    A swelling word locally STRETCHES the line, so no single rigid lag fits the
    whole band. Correlating four horizontal blocks independently and taking the
    median makes the estimate robust to that; blocks whose peak correlation is
    below ``reject`` (text entering at an edge) are dropped.
    """
    profs = [_profile(np.asarray(Image.open(f).convert("RGB")).astype(np.float32))
             if isinstance(f, str) else _profile(f) for f in frames]
    n = len(profs)
    if n == 0:
        return np.zeros(0), []

    deltas = np.zeros(n)
    peaks = np.ones(n)
    width = len(profs[0])
    edges = np.linspace(0, width, blocks + 1).astype(int)
    for f in range(1, n):
        lags, ps = [], []
        for b in range(blocks):
            lo, hi = edges[b], edges[b + 1]
            L, p = _lag(profs[f][lo:hi], profs[f - 1][lo:hi], max_lag)
            if p >= reject:
                lags.append(L); ps.append(p)
        if lags:
            deltas[f] = float(np.median(lags))
            peaks[f] = float(np.max(ps))
        else:
            # nothing correlated anywhere: whole-band fallback, and let the
            # low peak mark it as a possible cut
            deltas[f], peaks[f] = _lag(profs[f], profs[f - 1], max_lag)

    segments, start = [], 0
    for f in range(1, n):
        if peaks[f] < cut:
            segments.append((start, f - 1))
            start = f
    segments.append((start, n - 1))

    s = np.zeros(n)
    for a, b in segments:
        for f in range(a + 1, b + 1):
            s[f] = s[f - 1] + deltas[f]

    # Re-anchor against an accumulated world profile. Integrating a thousand
    # deltas accumulates drift; correlating every frame against a common
    # template instead makes each offset absolute.
    for _ in range(refine):
        for a, b in segments:
            span = b - a + 1
            if span < 3:
                continue
            off = s[a:b + 1]
            pad = int(np.ceil(max(0.0, float(np.max(off) - np.min(off))))) + 2
            world = np.zeros(width + 2 * pad)
            base = off.min()
            for f in range(a, b + 1):
                k = int(round(s[f] - base))
                world[pad - k:pad - k + width] += profs[f]
            for f in range(a, b + 1):
                L, p = _lag(profs[f], world[pad:pad + width], max_lag + pad)
                if p >= reject:
                    s[f] = base + L
    return s, segments


def segment(frames, offsets=None):
    """Segment every frame ONCE, in world coordinates.

    Segmentation is the expensive half of every measurement here (a PIL decode
    and a column sweep per frame), and three separate passes used to redo it:
    tracking, per-word curves, and the per-frame emphasis measure. Returns a
    list of per-frame glyph lists, each glyph carrying ``xw``; pass it to
    ``track`` so the whole pipeline decodes each frame at most once.
    """
    out = []
    for fi, path in enumerate(frames):
        gs = glyphs(path) if isinstance(path, str) else glyphs_array(path)
        shift = 0.0 if offsets is None else float(offsets[fi])
        for g in gs:
            g["xw"] = g["xc"] + shift
        out.append(gs)
    return out


def track(frames, fps, offsets=None, per_frame=None):
    """Follow glyphs across frames by nearest centre; return per-glyph tracks.

    With ``offsets`` (from ``scroll_offsets``) association happens in WORLD
    coordinates, so a scrolling line does not fragment into thousands of
    one-frame tracks. ``per_frame`` reuses a previous ``segment`` pass; every
    track point also carries ``fi``, the frame it was seen on, so a caller can
    line tracks up with the per-frame glyph lists without re-deriving it from
    the timestamp.
    """
    if per_frame is None:
        per_frame = segment(frames, offsets)
    tracks, live = [], []
    for fi, gs in enumerate(per_frame):
        for g in gs:
            g["fi"] = fi
        used = set()
        for tr in live:
            last = tr["pts"][-1]
            best, bd = None, 1e9
            for j, g in enumerate(gs):
                if j in used:
                    continue
                d = abs(g["xw"] - last["xw"])
                # letters move only a little between frames, and never
                # vertically far enough to be confused with another row
                if d < bd and d < 14 and abs(g["h"] - last["h"]) < 0.6 * last["h"]:
                    best, bd = j, d
            if best is None:
                tr["dead"] = True
            else:
                used.add(best)
                tr["pts"].append(gs[best]); tr["t"].append(fi / fps)
        live = [t for t in live if not t.get("dead")]
        for j, g in enumerate(gs):
            if j not in used:
                tr = dict(pts=[g], t=[fi / fps], dead=False)
                tracks.append(tr); live.append(tr)
    return tracks


def turn_time(tr, fps):
    """Sub-frame time at which this glyph's colour turned, or ``None``."""
    sat = np.array([p["sat"] for p in tr["pts"]])
    t = np.array(tr["t"])
    lo, hi = np.percentile(sat, 5), np.percentile(sat, 95)
    if hi - lo < 0.20:                          # never actually turned
        return None
    mid = (lo + hi) / 2
    idx = np.nonzero(sat >= mid)[0]
    if not len(idx) or idx[0] == 0:
        return None
    k = idx[0]
    f = (mid - sat[k - 1]) / max(1e-6, sat[k] - sat[k - 1])
    return float(t[k - 1] + f * (t[k] - t[k - 1]))


def curves(tracks, fps, min_len=14):
    """Per-glyph baseline and height, aligned on that glyph's own colour turn."""
    lifts, sizes, turns = [], [], []
    for tr in tracks:
        if len(tr["pts"]) < min_len:
            continue
        sat = np.array([p["sat"] for p in tr["pts"]])
        bot = np.array([p["bot"] for p in tr["pts"]])
        hgt = np.array([p["h"] for p in tr["pts"]])
        t = np.array(tr["t"])
        t_turn = turn_time(tr, fps)
        if t_turn is None:
            continue
        lo, hi = np.percentile(sat, 5), np.percentile(sat, 95)
        k = int(np.nonzero(sat >= (lo + hi) / 2)[0][0])
        rest = np.median(bot[max(0, k - 2):][-8:]) if len(bot) - k >= 8 else np.median(bot[-6:])
        restH = np.median(hgt[-6:])
        if restH < 4:
            continue
        lifts.append((t - t_turn, (rest - bot) / restH))     # +ve = raised
        sizes.append((t - t_turn, hgt / restH))
        # colour crossfade width: 10%->90% of the saturation swing
        s10, s90 = lo + 0.1 * (hi - lo), lo + 0.9 * (hi - lo)
        a = np.nonzero(sat >= s10)[0]; b = np.nonzero(sat >= s90)[0]
        if len(a) and len(b) and b[0] >= a[0]:
            turns.append((b[0] - a[0]) / fps)
    return lifts, sizes, turns


def resample(curves_, grid):
    out = []
    for x, y in curves_:
        if x[0] > grid[0] or x[-1] < grid[-1]:
            continue
        out.append(np.interp(grid, x, y))
    return np.array(out)


GRID = np.arange(-0.30, 0.62, 0.01)


def summarize(grid, m, ms=None, turns=None):
    """The fitted numbers, as a dict — shared by the fit script and the
    comparison harness so both report the same quantities the same way."""
    peak_i = int(np.argmax(m))
    after = m[peak_i:]
    under_i = peak_i + int(np.argmin(after))
    out = {
        "lift_peak": float(m[peak_i]),
        "lift_peak_s": float(grid[peak_i]),
        "undershoot": float(m[under_i]),
        "undershoot_s": float(grid[under_i]),
    }
    pre = np.nonzero(m[:peak_i] <= 0.1 * m[peak_i])[0]
    out["rise_s"] = float(grid[peak_i] - grid[pre[-1]]) if len(pre) else None
    zero = np.nonzero(after <= 0)[0]
    out["fall_s"] = float(grid[peak_i + zero[0]] - grid[peak_i]) if len(zero) else None
    if ms is not None and len(ms):
        out["size_peak"] = float(ms.max())
        out["size_peak_s"] = float(grid[int(np.argmax(ms))])
    if turns:
        out["colour_s"] = float(np.median(turns))
    return out


def measure(frames, fps, scroll=False):
    """frames -> (grid, median lift, median size, summary). The whole pipeline."""
    offsets = None
    if scroll:
        offsets, _ = scroll_offsets(frames)
    tr = track(frames, fps, offsets=offsets)
    lifts, sizes, turns = curves(tr, fps)
    L = resample(lifts, GRID)
    S = resample(sizes, GRID)
    if not len(L):
        return None
    m = np.median(L, axis=0)
    ms = np.median(S, axis=0) if len(S) else None
    return GRID, m, ms, summarize(GRID, m, ms, turns), len(tr), len(L)


def main(pattern, fps, label, scroll=False):
    frames = sorted(glob.glob(pattern)) if isinstance(pattern, str) else pattern
    if not frames:
        print(f"{label}: no frames"); return None
    got = measure(frames, fps, scroll=scroll)
    print(f"\n=== {label} ===")
    if got is None:
        print("no usable glyph curves"); return None
    grid, m, ms, s, ntracks, ncurves = got
    print(f"{len(frames)} frames @ {fps:.1f} fps, {ntracks} tracks, "
          f"{ncurves} usable glyph curves")
    print(f"lift peak      {s['lift_peak']*100:5.1f}% of glyph height at "
          f"{s['lift_peak_s']*1000:+.0f} ms from the colour turn")
    print(f"undershoot     {s['undershoot']*100:5.1f}% at {s['undershoot_s']*1000:+.0f} ms")
    if s["rise_s"] is not None:
        print(f"rise 10%->peak {s['rise_s']*1000:5.0f} ms")
    if s["fall_s"] is not None:
        print(f"peak->baseline {s['fall_s']*1000:5.0f} ms")
    if "size_peak" in s:
        print(f"glyph size     rest 1.000, peak {s['size_peak']:.3f} at "
              f"{s['size_peak_s']*1000:+.0f} ms")
    if "colour_s" in s:
        print(f"colour 10-90%  {s['colour_s']*1000:5.0f} ms")
    return grid, m, ms


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), sys.argv[3],
         scroll="--scroll" in sys.argv)
