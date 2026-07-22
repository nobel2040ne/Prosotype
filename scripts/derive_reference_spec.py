"""Derive a CaptionSpec from a reference recording.

The transcript is given (the recordings loop, and they mix captions with title
cards, so auto-transcription would be guesswork); everything else -- per-word
timings, per-word emphasis and weight, and each word's own motion curves -- is
measured from the pixels.

    .venv/bin/python scripts/derive_reference_spec.py \\
        --frames "/tmp/sync/n_*.png" --fps 57.1256 --rotate 3 \\
        --transcript docs/reference/synchronization.txt \\
        --out assets/reference_specs/synchronization.json

See the README for each recording's true fps, crop and flags. The transcript is
one caption per line, ``SPEAKER<TAB>text``, in RECORDING order.

Method
------
Words first: each word's x extent is read straight off the pixels
(`word_boxes`), which constrains a DP that assigns tracked glyphs to character
indices. The renderer's law ``tTurn = start + ((c+0.5)/n)*(end-start)`` is
LINEAR in the unknowns, so per-word start/end come from one least-squares solve
over every confident character observation, with priors that keep one- and
two-letter words solvable.

Then emphasis, from TWO independent measurements, because each fails where the
other works. Per-glyph tracking is clean but breaks on a word that swells past
2x or shrinks to half -- its glyphs merge, or grow, and association fails --
which is precisely the set of words worth measuring. Per-frame segmentation
survives that but smears at word boundaries. The tracked curve is used by
default and the framed one where tracking produced nothing or under-read the
DEVIATION from rest; `Word.emphasis_source` records which won.

Prosody is inverted through ``autocwi.ccprosody`` so our renderer reproduces
the measured value, and each word's raw curves are baked into ``Word.motion``
so the derivation can be replayed and checked (`closed_caption.motion_source:
measured`). The design system's own model is what ships.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autocwi.ccprosody import (                              # noqa: E402
    fit_spec_prosody, merged_expression, word_fields,
)
from autocwi.config import load_config                       # noqa: E402
from autocwi.refmeasure import (                             # noqa: E402
    scroll_offsets, segment, track, turn_time,
)


def read_transcript(path):
    phrases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        speaker, text = line.split("\t", 1)
        speaker = speaker.strip()
        # A leading "-" consumes a caption instance without emitting it: the
        # recordings loop and interleave animated section headings with the
        # captions, and every on-screen caption has to be accounted for to keep
        # the ordered match aligned.
        emit = not speaker.startswith("-")
        phrases.append({"speaker": speaker.lstrip("-").strip() or "S1",
                        "text": text.strip(), "emit": emit})
    return phrases


def observations(frames, fps, scroll, cut=0.35):
    """Every glyph that confidently turned: (t_turn, world x, mean height).

    Returns ``(obs, segments, per_frame)``; ``segments`` is non-empty only when
    the line scrolls, and holds the frame ranges between which the caption is
    unchanged. ``per_frame`` is the one-and-only segmentation pass, kept so the
    track-free emphasis measure can reuse it instead of decoding every frame a
    second time.
    """
    offsets, segs = None, []
    if scroll:
        offsets, segs = scroll_offsets(frames, cut=cut)
    per_frame = segment(frames, offsets)
    obs = []
    for tr in track(frames, fps, offsets=offsets, per_frame=per_frame):
        if len(tr["pts"]) < 5:
            continue
        tt = turn_time(tr, fps)
        if tt is None:
            continue
        xs = [p["xw"] for p in tr["pts"]]
        obs.append({"t": tt, "x": float(np.median(xs)), "tr": tr,
                    "h": float(np.median([p["h"] for p in tr["pts"]]))})
    # Drop the dot of an "i", commas, apostrophes: they segment as their own
    # runs, so a phrase yields MORE observations than characters and the
    # alignment slips. Measured, "dynamic text animation" gave 25 runs for 20
    # characters and a 264 ms fit residual.
    if obs:
        full = float(np.median([o["h"] for o in obs]))
        obs = [o for o in obs if o["h"] > 0.45 * full]
    obs.sort(key=lambda o: o["t"])
    return obs, segs, per_frame


def split_by_segments(obs, segs, fps, min_s=0.30):
    """Split a SCROLLING recording's observations by scroll segment.

    Appearance-clustering cannot work here: a scrolling line's glyphs enter the
    crop progressively, so they do not appear together. But the caption change
    is exactly where the scroll correlation collapses, which
    ``scroll_offsets`` already reports as a segment break. Tiny segments are
    the blank frames at the change itself and are dropped.
    """
    keep = [(a, b) for a, b in segs if (b - a) / fps >= min_s]
    groups = [[] for _ in keep]
    for o in obs:
        # Bucket by the COLOUR TURN, not the track's first frame. A scrolling
        # caption's glyphs enter the crop progressively, so their tracks start
        # across several segments and bucketing on that scattered a third of
        # each caption into its neighbours.
        f = o["t"] * fps
        for i, (a, b) in enumerate(keep):
            if a <= f <= b:
                groups[i].append(o); break
    # A handful of runs is a stray, not a caption (a glyph clipped at the crop
    # edge during a handoff, say). Real captions here carry 20+ runs.
    groups = [g for g in groups if len(g) >= 4]
    for g in groups:
        g.sort(key=lambda o: o["t"])
    return groups


def split_phrases(obs, gap_s=0.30):
    """Group observations by which CAPTION they belong to.

    NOT by gaps between colour turns: measured on the sync recording, the pause
    between two phrases (0.67 s) is SHORTER than a pause inside one phrase
    ("precisely as each word is spoken." has a 1.2 s gap), so a turn-gap
    threshold both splits phrases and merges them. NOR by lifetime overlap:
    read-ahead puts the next line on screen before the previous one leaves, so
    overlap chains the whole clip into one group.

    What is reliably true is that a caption line is DRAWN ALL AT ONCE -- every
    glyph of one phrase appears within a frame or two of the others. So cluster
    on each track's first frame.
    """
    items = sorted(obs, key=lambda o: o["tr"]["t"][0])
    groups, cur = [], []
    for o in items:
        if cur and o["tr"]["t"][0] - cur[-1]["tr"]["t"][0] > gap_s:
            groups.append(cur); cur = []
        cur.append(o)
    if cur:
        groups.append(cur)
    for g in groups:
        g.sort(key=lambda o: o["t"])
    return groups


def group_tracks_horizontally(group, min_travel_px=24.0):
    """Whether this caption instance actually travels across the screen.

    ``--scroll`` means the RECORDING contains scrolling captions; its section
    title can still be static. Every tracked point already carries screen x
    and scroll-corrected world x, so ``xw - xc`` is the recovered line offset.
    Classify the instance from the robust span of that measured offset instead
    of tagging every line in the file and making a static title drift.
    """
    by_frame = {}
    for o in group:
        for p in o["tr"]["pts"]:
            by_frame.setdefault(p["fi"], []).append(p["xw"] - p["xc"])
    if len(by_frame) < 4:
        return False
    offsets = np.asarray([np.median(v) for _, v in sorted(by_frame.items())])
    return float(np.percentile(offsets, 95) - np.percentile(offsets, 5)) >= min_travel_px


def _merge(items, thr):
    """Merge (x0, x1[, h]) spans separated by less than ``thr``.

    ``thr`` may be a number or a callable ``(h_left, h_right) -> gap``. The
    callable form is what makes this work across a size range: a word rendered
    at half size also has half-size SPACES around it, so any absolute
    threshold that separates resting words merges shrunken ones. Measured,
    that is why "softer." at 0.50x was never split out from "or" and its whole
    shrink went unmeasured.
    """
    runs = []
    for it in items:
        a, b = it[0], it[1]
        h = it[2] if len(it) > 2 else 0.0
        if runs:
            gap = thr(runs[-1][2], h) if callable(thr) else thr
            if a - runs[-1][1] < gap:
                runs[-1][1] = max(runs[-1][1], b)
                runs[-1][2] = max(runs[-1][2], h)
                continue
        runs.append([a, b, h])
    return runs


def frame_words(gs, anchor, nwords, space_frac=0.40, block_frac=3.0,
                thr=None, window=None, lens=None):
    """One frame's glyphs -> one (x0, x1) run per WORD, or None.

    The caption is isolated from the site's own nav and headings first (they
    sit at x=139..715 beside a caption at x=1683), then split at the spaces.

    NO SINGLE SPLIT THRESHOLD WORKS. The line spans a 4x size range within one
    caption -- "louder" at 2.2x nearly touches its neighbour while "softer." at
    0.5x has half-size spaces around it -- so an absolute threshold merges the
    shrunken words and a size-relative one merges the swollen ones. Both were
    tried; each fixed one end and broke the other. Instead SEARCH a small
    ladder and accept only a split that yields exactly ``nwords`` runs AND
    passes a SCALE-INVARIANT consistency check: a run's width divided by its
    own glyph height is proportional to its CHARACTER COUNT, whatever size it
    is rendered at, so that ratio must correlate with the words' lengths.
    Checking run widths against the resting boxes instead does not work -- it
    assumes sizes have not changed, which is the very thing being measured,
    and it threw away every frame in which a word had swollen.

    That check is what catches an off-by-one: with "or softer." both at half
    size the ladder can merge "or"+"softer" while splitting the final ".",
    which still yields the right NUMBER of runs but shifts every word one
    place, and the shrink then lands on "or".
    """
    if len(gs) < 3:
        return None
    spans = sorted((g["x0"] + g["xw"] - g["xc"], g["x1"] + g["xw"] - g["xc"],
                    g["h"]) for g in gs)
    hh = float(np.median([g["h"] for g in gs]))
    if window is not None:
        block = window
    else:
        block = next((r for r in _merge(spans, block_frac * hh)
                      if r[0] - hh <= anchor <= r[1] + hh), None)
        if block is None:
            return None
    inside = [sp for sp in spans if block[0] <= sp[0] <= block[1]]
    if len(inside) < nwords:
        return None
    base = thr if thr else space_frac * hh
    for k in (1.0, 0.7, 0.5, 0.35, 1.4, 2.0):
        runs = _merge(inside, k * base)
        if len(runs) != nwords:
            continue
        if lens is not None and nwords > 2:
            est = np.array([(r[1] - r[0]) / max(6.0, r[2]) for r in runs])
            want = np.array(lens, float)
            if est.std() < 1e-6 or want.std() < 1e-6:
                continue
            if float(np.corrcoef(est, want)[0, 1]) < 0.75:
                continue
        return [(r[0], r[1]) for r in runs]
    return None


def box_split(boxes, pad_frac=0.6):
    """(threshold, window) for `frame_words`, from the resting word boxes."""
    if not boxes or len(boxes) < 2:
        return None, None
    gaps = [boxes[i + 1][0] - boxes[i][1] for i in range(len(boxes) - 1)]
    span = boxes[-1][1] - boxes[0][0]
    return (pad_frac * float(np.median(gaps)),
            (boxes[0][0] - 0.5 * span, boxes[-1][1] + 0.5 * span))


def word_boxes(per_frame, group, nwords, fps, space_frac=0.40,
               block_frac=3.0):
    """World-x extent of each WORD of one caption, read off the pixels.

    Which word a glyph belongs to is the foundation everything else rests on --
    a single glyph assigned to its neighbour drags that word's fitted timing
    across the whole phrase -- and until now it was inferred from character
    index (or advance width) alone, a proportional guess that drifts. But the
    boundary is directly visible: within a word, glyph runs are separated by a
    few pixels; between words, by a space. Merge runs across the small gaps and
    the surviving groups ARE the words.

    Only frames where the count comes out equal to the number of words are
    used, so a frame where two words have merged under a swell, or one is
    entering the crop, is simply skipped rather than corrupting the result.
    Returns ``[(x0, x1)]`` per word in world coordinates, or None.
    """
    # Only frames between this caption's first and last colour turn. A glyph's
    # TRACK spans read-ahead and hold, so it reaches into the neighbouring
    # caption -- and measuring boxes there returned the NEXT caption's words,
    # which then pushed "dynamic text animation" to a negative start time.
    t_lo = min(o["t"] for o in group)
    t_hi = max(o["t"] for o in group)
    fis = range(max(0, int(t_lo * fps)),
                min(len(per_frame), int(t_hi * fps) + 1))
    # The crop is the full frame width and carries the site's own nav and
    # headings -- at x=139..715 beside a caption at x=1683 -- so the caption
    # has to be isolated first. Do it with the SAME gap rule at a coarser
    # threshold: a caption's inter-word spaces are a fraction of a glyph
    # height, while the nearest unrelated block is many glyph heights away.
    # (Deriving the window from the observations instead fails on a caption
    # that was already coloured when the clip started -- the recording opens
    # mid-phrase on "dynamic text animation", whose first word never turns on
    # camera, and the window then began in the middle of it.)
    anchor = float(np.median([o["x"] for o in group]))
    per_word = [[] for _ in range(nwords)]
    hits = 0
    for fi in fis:
        gs = [g for g in per_frame[fi] if g["h"] > 4 and not g.get("edge")]
        runs = frame_words(gs, anchor, nwords, space_frac, block_frac)
        if runs is None:
            continue
        hits += 1
        for wi, (x0, x1) in enumerate(runs):
            per_word[wi].append((x0, x1))
    if hits < 5:
        return None
    return [(float(np.median([a for a, _ in w])),
             float(np.median([b for _, b in w]))) for w in per_word]


_ADVANCE_CACHE = {}


def _advance_positions(text, idx):
    """Normalised centre x of each character in ``idx``, by real advance width.

    Measured with PIL from the bundled Roboto Flex. The reference site is not
    necessarily set in Roboto Flex, but both are grotesque sans faces and only
    the RATIOS matter here (the result is normalised to 0..1), which is exactly
    what a uniform-index assumption gets wrong. Falls back to the index if the
    font cannot be loaded, so this stays an improvement and never a dependency.
    """
    key = ("pos", text)
    if key in _ADVANCE_CACHE:
        return _ADVANCE_CACHE[key]
    font = _ADVANCE_CACHE.get("font", ...)
    if font is ...:
        try:
            from PIL import ImageFont
            font = ImageFont.truetype(str(ROOT / "assets" / "RobotoFlex.ttf"), 64)
        except Exception:
            font = None
        _ADVANCE_CACHE["font"] = font
    if font is None:
        ci = np.array(idx, float)
        out = (ci - ci.min()) / max(1e-6, ci.max() - ci.min())
    else:
        # cumulative advance to the START of each character, then its centre
        edges = [font.getlength(text[:i]) for i in range(len(text) + 1)]
        mid = np.array([(edges[i] + edges[i + 1]) / 2 for i in idx], float)
        out = (mid - mid.min()) / max(1e-6, mid.max() - mid.min())
    _ADVANCE_CACHE[key] = out
    return out


def align(group, text, boxes=None):
    """Assign observations to character indices of ``text``.

    Both sequences are monotone in reading order, so a small DP over
    (observation, character) with normalised x as the cost recovers the
    assignment even when glyphs merge, punctuation splits off, or a character
    never turned confidently. Characters are indexed over the whole phrase
    INCLUDING spaces, so word boundaries stay addressable.

    With ``boxes`` from `word_boxes`, a pairing that would put an observation
    in a word whose measured box does not contain it is forbidden outright.
    That is the difference between a proportional guess and a measurement, and
    it is what stops one glyph of "is" being read as the last of "word".
    """
    chars = [(i, c) for i, c in enumerate(text) if not c.isspace()]
    n, m = len(group), len(chars)
    if n == 0 or m == 0:
        return []
    # The DP below only works if BOTH sequences are monotone in reading order,
    # and the group arrives in TIME order. Those usually agree -- but several
    # glyphs of one word turn on the same frame, and their order within that
    # frame is then arbitrary, which scrambles x. Measured on "precisely as
    # each word is spoken.": three characters shared t=4.995 and the resulting
    # alignment ran x backwards (2709 -> 2528 -> 2491), handing "word" two of
    # "is"'s characters and stretching it across the phrase's 1.4 s pause.
    # Sort by x here and map back afterwards.
    order = sorted(range(n), key=lambda i: group[i]["x"])
    ox = np.array([group[i]["x"] for i in order], float)
    ox = (ox - ox.min()) / max(1e-6, ox.max() - ox.min())
    # Expected normalised position of each non-space character -- from its real
    # ADVANCE, not its index. Character index is a bad proxy for x: "precisely
    # as each word is spoken." puts 'i' and 'l' next to 'w' and 'p', so a
    # uniform-width assumption drifts by more than a character across the
    # phrase and mis-assigned the first glyph of "is" to the last of "word",
    # which then stretched "word" across the phrase's 1.4 s pause.
    cx = _advance_positions(text, [i for i, _ in chars])

    # forbidden[i, j]: observation i cannot be character j (measured boxes)
    forbid = np.zeros((n, m), dtype=bool)
    if boxes:
        word_of = {}
        pos = 0
        for wi, w in enumerate(text.split(" ")):
            for k in range(len(w)):
                word_of[pos + k] = wi
            pos += len(w) + 1
        gx = np.array([group[i]["x"] for i in order], float)
        pad = 0.02 * (gx.max() - gx.min() + 1)
        for j, (cidx, _) in enumerate(chars):
            wi = word_of.get(cidx)
            if wi is None or wi >= len(boxes):
                continue
            a, b = boxes[wi]
            forbid[:, j] = (gx < a - pad) | (gx > b + pad)

    SKIP = 0.35
    D = np.full((n + 1, m + 1), 1e9)
    D[0, :] = np.arange(m + 1) * SKIP
    back = np.zeros((n + 1, m + 1), dtype=np.int8)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = (1e9 if forbid[i - 1, j - 1]
                     else D[i - 1, j - 1] + abs(ox[i - 1] - cx[j - 1]))
            skip_c = D[i, j - 1] + SKIP
            skip_o = D[i - 1, j] + SKIP
            best = min(match, skip_c, skip_o)
            D[i, j] = best
            back[i, j] = 0 if best == match else (1 if best == skip_c else 2)
    pairs, i, j = [], n, m
    while i > 0 and j > 0:
        if back[i, j] == 0:
            pairs.append((order[i - 1], chars[j - 1][0])); i -= 1; j -= 1
        elif back[i, j] == 1:
            j -= 1
        else:
            i -= 1
    pairs.reverse()
    return pairs


def fit_times(text, pairs, group, kappa, gap):
    """Least squares for every word's start/end in one phrase.

    ``tTurn = (1-a)*start + a*end`` with ``a = (c+0.5)/n`` is linear, so data
    rows go straight into one lstsq alongside the priors.
    """
    words, pos = [], 0
    for w in text.split(" "):
        words.append((pos, w))
        pos += len(w) + 1
    W = len(words)
    rows, rhs = [], []

    def row():
        return np.zeros(2 * W)

    for oi, ci in pairs:
        for wi, (start_idx, w) in enumerate(words):
            if start_idx <= ci < start_idx + len(w):
                c = ci - start_idx
                a = (c + 0.5) / len(w)
                r = row(); r[2 * wi] = 1 - a; r[2 * wi + 1] = a
                rows.append(r); rhs.append(group[oi]["t"])
                break

    if not rows:
        return None
    # Priors carry real weight here: adjacent letters merge into one ink run,
    # so a phrase yields roughly half as many observations as characters and
    # several words get one or none. Without strong priors those words float
    # free and the solve emits 20 ms words and overlapping neighbours.
    # The continuity prior must stay WEAK. It pulls inter-word gaps toward the
    # median gap, which actively flattens a real pause: the 1.47 s the speaker
    # leaves before "is" in "precisely as each word is spoken." came out as
    # 0.32 s, and with it the held anticipation that pause exists to show.
    # Measured gaps are data; only unobserved words should lean on the prior.
    SPAN, CONT = 1.0, 0.12
    for wi, (_, w) in enumerate(words):
        r = row(); r[2 * wi] = -SPAN; r[2 * wi + 1] = SPAN
        rows.append(r); rhs.append(SPAN * kappa * len(w))
    for wi in range(W - 1):
        r = row(); r[2 * wi + 1] = -CONT; r[2 * (wi + 1)] = CONT
        rows.append(r); rhs.append(CONT * gap)

    A = np.array(rows); b = np.array(rhs)
    ndata0 = len(pairs)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    # One robust pass. A single mis-assigned ink run -- a stray glyph from the
    # heading that follows, say -- drags the whole phrase: measured, one such
    # run took "precisely as each word is spoken." to a 247 ms residual while
    # its neighbours sat at 20-40 ms. Drop observations beyond 3 MAD and refit.
    r = np.abs(A[:ndata0] @ x - b[:ndata0])
    mad = float(np.median(r)) or 1e-6
    keep = r <= max(0.05, 3.0 * mad)
    if keep.sum() >= 3 and keep.sum() < ndata0:
        A = np.vstack([A[:ndata0][keep], A[ndata0:]])
        b = np.concatenate([b[:ndata0][keep], b[ndata0:]])
        ndata0 = int(keep.sum())
        x, *_ = np.linalg.lstsq(A, b, rcond=None)
    starts, ends = x[0::2].copy(), x[1::2].copy()
    # Forward sweep: every word gets at least a length-proportional duration,
    # and never starts before the previous one ends. A pairwise patch left
    # "synchronized" starting before "are" had finished.
    for i in range(W):
        floor = max(0.06, 0.45 * kappa * len(words[i][1]))
        if i > 0:
            starts[i] = max(starts[i], ends[i - 1] + 0.01)
        ends[i] = max(ends[i], starts[i] + floor)
    resid = float(np.sqrt(np.mean((A[:ndata0] @ x - b[:ndata0]) ** 2)))
    return [(float(s), float(e)) for s, e in zip(starts, ends)], resid


def _words_of(text):
    """[(char index the word starts at, word)], indices INCLUDING spaces."""
    words, pos = [], 0
    for w in text.split(" "):
        words.append((pos, w))
        pos += len(w) + 1
    return words


def _density(p):
    """Ink pixels per bounding-box pixel: the WEIGHT channel.

    A bolder glyph puts more ink inside the same box, so density separates
    "weights" (normal size, bold) from "sizes," (large, normal weight), which
    the height measure cannot tell apart. It is also invariant to the size
    envelope: a word that merely grows keeps its density.
    """
    return p["ink"] / max(1.0, (p["x1"] - p["x0"] + 1) * (p["h"] + 1))


def word_curves(text, pairs, group, nsamp=80):
    """Per-word CURVES for size, weight and lift, each normalised to its rest.

    This is the measurement the whole exercise turns on. ``emphasis`` and
    ``weight_ratio`` each used to build a co-present, clip-rejected,
    time-aligned matrix and then throw the curve away, keeping one scalar --
    and ``refmeasure.curves`` does the same across every glyph in a recording,
    medianing them into ONE average shape. A renderer handed only those scalars
    can never do anything but give every word the average word's motion, which
    is exactly why words that do not move in the reference were still lifting
    here. Keep the curve.

    NORMALISE EACH GLYPH BY ITS OWN REST, THEN MEDIAN -- not the other way
    round. Medianing raw pixel heights and baselines across a word's glyphs
    looks equivalent and is not: letters have different intrinsic ink heights
    ("o" against "l") and only some have descenders, so as glyphs enter and
    leave the co-present set the median steps to a different letter and the
    curve jumps. Measured, that composition artefact alone produced a 0.35x
    "size" excursion on `Caption` and +-0.16 of phantom lift on words that
    never moved. Per-track normalisation removes it: every track contributes
    1.0 at rest whatever letter it is.

    Medianing across the word's CO-PRESENT glyphs is still the trick that
    separates the two scopes: a per-character effect hits one letter at a time
    and barely moves the median, while a word-level envelope moves every letter
    together and moves it fully. Tracks must be compared AT THE SAME TIME --
    they start on different frames, so indexing two by array position compares
    different moments and reported the largest word on screen ("sizes,") as no
    emphasis at all.

    Rests differ per channel, on purpose:

    * height and density rest BEFORE that glyph's own colour turn. Read-ahead
      puts an unspoken word on screen at its resting size, while the TAIL is
      unusable on a scrolling line -- there it is the word leaving the frame,
      which made the last word of every line ("softer.") read as the most
      emphasised on screen.
    * baseline rests on the median over the glyph's WHOLE life. The lift is a
      transient excursion that settles back (CWI's letters all return to one
      baseline), so the median of a mostly-flat signal IS that baseline --
      whereas the pre-turn window is precisely where the anticipation crouch
      lives and would be absorbed into the reference, zeroing the very motion
      we are trying to copy.
    """
    obs_of = {}
    for oi, ci in pairs:
        obs_of.setdefault(ci, group[oi])
    out = []
    for start_idx, w in _words_of(text):
        mine = [obs_of[ci] for ci in range(start_idx, start_idx + len(w))
                if ci in obs_of]
        rec = {"word": w, "start_idx": start_idx, "n_tracks": len(mine),
               "ts": None, "h": None, "d": None, "lift": None,
               # When this word's first character turned colour. Recorded even
               # when no curve can be built from tracks alone, because it is
               # what `frame_word_curves` measures its rest against -- leaving
               # it None here silently denied every one- and two-letter word a
               # curve from EITHER measurement.
               "t_first": min((o["t"] for o in mine), default=None)}
        out.append(rec)
        if len(mine) < 2:
            continue
        t0 = min(o["tr"]["t"][0] for o in mine)
        t1 = max(o["tr"]["t"][-1] for o in mine)
        if t1 - t0 <= 0.15:
            continue
        ts = np.linspace(t0, t1, nsamp)
        rows_h, rows_d, rows_l = [], [], []
        for o in mine:
            tr, tt = o["tr"], np.asarray(o["tr"]["t"])
            hs = np.array([p["h"] for p in tr["pts"]], float)
            ds = np.array([_density(p) for p in tr["pts"]], float)
            bs = np.array([p["bot"] for p in tr["pts"]], float)
            ok = np.array([not p.get("edge") for p in tr["pts"]])
            pre = ok & (tt < o["t"]) & (tt <= tt[0] + REST_SPAN_S)
            if pre.sum() < 3:
                pre = ok & (tt < o["t"])
            if pre.sum() < 3 or not ok.any():
                continue
            rest_h = float(np.median(hs[pre]))
            rest_d = float(np.median(ds[pre]))
            rest_b = float(np.median(bs[ok]))
            if rest_h < 4 or rest_d < 1e-6:
                continue
            inside = (ts >= tt[0]) & (ts <= tt[-1])
            # a clipped sample has partial height and ink; interpolate the flag
            # so a sample adjacent to one is dropped too
            clip = np.interp(ts, tt, np.where(ok, 0.0, 1.0)) > 0.01
            keep = inside & ~clip

            def lay(vals, scale):
                row = np.full(nsamp, np.nan)
                row[keep] = np.interp(ts[keep], tt, vals) * scale
                return row

            rows_h.append(lay(hs, 1.0 / rest_h))
            rows_d.append(lay(ds, 1.0 / rest_d))
            # + = raised. Screen y grows downward, so a rising letter's bottom
            # row FALLS; and the rise is expressed in glyph heights, the unit
            # `refmeasure.curves` and the renderer both use.
            rows_l.append(lay(rest_b - bs, 1.0 / rest_h))
        if len(rows_h) < 2:
            continue
        H, D, L = np.array(rows_h), np.array(rows_d), np.array(rows_l)
        with np.errstate(all="ignore"):
            med_h = np.nanmedian(H, axis=0)
            med_d = np.nanmedian(D, axis=0)
            med_l = np.nanmedian(L, axis=0)
        alone = np.isfinite(H).sum(axis=0) < 2
        med_h[alone] = np.nan
        med_d[alone] = np.nan
        med_l[alone] = np.nan
        if np.isfinite(med_h).sum() < 4:
            continue
        rec.update(ts=ts, h=med_h, d=med_d, lift=med_l)
    return out


def emphasis(curves):
    """Per-word peak size, as a ratio to that word's own resting size.

    Sanity check on the output: the intonation recording must put "sizes," well
    clear of everything else, and the synchronization recording -- which
    demonstrates timing, not intonation -- must come out essentially uniform.
    A word that is BOLD rather than large ("weights") correctly shows no height
    change; that is what `weight_ratio` is for.
    """
    return _peak_of(curves, "h", SYNC_POP)


def weight_ratio(curves):
    """Per-word peak ink density, as a ratio to that word's own resting density.

    Weight is a different channel from size and needs a different measure: a
    bolder glyph puts more ink inside the same bounding box, and density is
    invariant to the size envelope, so it separates "weights" (normal size,
    bold) from "sizes," (large, normal weight).
    """
    return _peak_of(curves, "d")


# 2.2.3's synchronization pop is a CONSTANT +15% that every word gets at its
# colour turn. It is baked into any pixel measurement of the rendered result,
# so it has to come back out before the remainder can be read as intonation --
# otherwise every ordinary word reports a 1.15x "emphasis" it does not have.
SYNC_POP = 1.15


def _peak_of(curves, channel, pop=1.0):
    """Per-word emphasis: the LARGER deviation from rest, up or down.

    Taking `nanmax` alone silently discards the entire quiet half of the
    channel. A word that only ever shrinks still has a maximum -- its own
    resting moment, plus the sync pop -- so "softer." reported 1.19 (slightly
    LARGE) when the recording shrinks it to 0.50.
    """
    out, measured = [], []
    for rec in curves:
        arr = rec[channel]
        val, got = 1.0, False
        if arr is not None and np.isfinite(arr).any():
            v = arr[np.isfinite(arr)]
            # PERCENTILES, not the raw extremes. Glyph segmentation noise puts
            # a stray frame or two several percent off rest on every word, and
            # `nanmin` reads that as a shrink -- with the deviation rule below
            # that made every ordinary word report ~0.85 "quiet". A real
            # emphasis is HELD (the recording keeps "softer." at 0.50 for about
            # a second), so it survives trimming and noise does not.
            hi = float(np.percentile(v, 95)) / pop
            lo = float(np.percentile(v, 5))
            val = hi if (hi - 1.0) >= (1.0 - lo) else lo
            got = True
        out.append(val)
        measured.append(got)
    return out, measured


def frame_curves(per_frame, pairs, group, text, fps, boxes=None,
                 strict=True):
    """Per-word motion curves measured WITHOUT the word's own tracks surviving.

    Tracking breaks on exactly the words that matter. Association gates on
    ``abs(h - last_h) < 0.6*last_h`` and a 14 px step, and a word swelling past
    3x while its letters merge violates both -- so the most emphasised word in
    a recording yields the FEWEST tracks and reads as no emphasis at all
    ("louder" measured 1.085 against a true ~3.1). Short words fare no better:
    "as", "is" and "so" segment as a single merged run and drop out entirely.

    The earlier attempt attributed each frame's tallest glyph to whichever word
    the FITTED timings said was being spoken -- and the emphasis envelope LEADS
    the spoken onset, so a peak landed one word early ("or" was credited with
    "louder"'s swell), while widening the window let a word claim its
    neighbour's peak outright. Attribute in SPACE instead, two ways:

    * BY RANK, when the frame's ink splits into exactly as many runs as there
      are words (`frame_words`): the k-th run is then the k-th word, whatever
      size it has swollen to. This is the case that matters, because it is
      exactly the swelling word whose own tracks have died.
    * otherwise by interpolating the surviving tracks' x -> character-index map
      and reading a glyph's own x through it.

    Rank-matching is what stops the smear: interpolating across the hole left
    by "louder"'s dead tracks put its giant glyphs partly inside "or", which
    then measured 1.85x on a word that never moved.

    Returns one record per word with ``t``; ``h`` and ``d`` as ratios against
    the LINE's median glyph in that same frame (so a global size change or the
    scroll cancels); and ``hp`` and ``b``, the same word's median ink height
    and baseline in pixels, which is what the lift's unit needs. Rests are left
    to the caller.
    """
    words = _words_of(text)
    ci_word = {}
    for wi, (start_idx, w) in enumerate(words):
        for k in range(len(w)):
            ci_word[start_idx + k] = wi

    # anchors: frame index -> [(world x, character index)]
    anchors = {}
    for oi, ci in pairs:
        for p in group[oi]["tr"]["pts"]:
            anchors.setdefault(p["fi"], []).append((p["xw"], ci))

    anchor_x = float(np.median([o["x"] for o in group]))
    thr, window = box_split(boxes)
    lens = [len(w) for _, w in _words_of(text)]
    # Frames to look at. Anchors come from glyph TRACKS, and those die well
    # before the caption leaves -- on "so you can feel when my voice gets
    # louder or softer." they end at 7.48 s while "softer." is still shrinking
    # to half size at 8.5. So when the rank split succeeds, RANK is the
    # attribution and no anchor is needed; the window simply extends past the
    # last track and `frame_words` refuses any frame whose ink does not split
    # into exactly this caption's word count.
    fis = [p["fi"] for o in group for p in o["tr"]["pts"]]
    f_lo, f_hi = min(fis), min(len(per_frame) - 1,
                               max(fis) + int(round(EXTEND_S * fps)))
    acc = [{"t": [], "h": [], "d": [], "hp": [], "b": []} for _ in words]
    for fi in range(f_lo, f_hi + 1):
        gs = per_frame[fi]
        a = anchors.get(fi) or []
        ux = uc = None
        if len(a) >= 3:
            ax = np.array([x for x, _ in sorted(a)], float)
            ac = np.array([c for _, c in sorted(a)], float)
            ux, inv = np.unique(ax, return_inverse=True)
            if len(ux) < 3:
                ux = None
        if ux is not None:
            # two runs at the same world x are a merge: average their character
            # indices rather than dropping one
            uc = np.array([ac[inv == i].mean() for i in range(len(ux))])
            uc = np.maximum.accumulate(uc)      # reading order is monotone

        good = [g for g in gs if not g.get("edge") and g["h"] > 4]
        if len(good) < 5:
            continue
        runs = frame_words(good, anchor_x, len(words),
                           thr=thr, window=window, lens=lens)
        if runs is None and ux is None:
            continue
        h = np.array([g["h"] for g in good], float)
        d = np.array([_density(g) for g in good], float)
        # the line's own median glyph is the resting reference for this frame
        med_h, med_d = float(np.median(h)), float(np.median(d))
        if med_h < 4 or med_d < 1e-6:
            continue
        by_word = {}
        for g, gh, gd in zip(good, h, d):
            x = g["xw"]
            if runs is not None:
                wi = next((k for k, (x0, x1) in enumerate(runs)
                           if x0 - 1 <= x <= x1 + 1), None)
            elif strict or ux is None:
                continue
            else:
                if x < ux[0] or x > ux[-1]:
                    continue                   # outside the bracket: no anchor
                ci = int(round(float(np.interp(x, ux, uc))))
                wi = ci_word.get(ci)           # None = a space: ambiguous
            if wi is None:
                continue
            by_word.setdefault(wi, []).append(
                (gh / med_h, gd / med_d, gh, g["bot"]))
        for wi, vals in by_word.items():
            # One glyph is enough only for a word short enough to BE one run;
            # on a longer word a single glyph is the per-character bloom, which
            # is a different scope and must not be read as the word envelope.
            if len(vals) < 2 and len(words[wi][1]) > 3:
                continue
            # A word can never have MORE ink runs than it has characters: runs
            # merge, they never split (the dot of an "i" and stray punctuation
            # are already filtered upstream). More runs than characters means
            # the split leaked a neighbour's glyphs in -- which is exactly what
            # happens beside a word swollen past 2x, where "louder" ran into
            # "or" and handed it a 1.85x envelope on a word that never moved.
            if len(vals) > len(words[wi][1]):
                continue
            acc[wi]["t"].append(fi / fps)
            acc[wi]["h"].append(float(np.median([v[0] for v in vals])))
            acc[wi]["d"].append(float(np.median([v[1] for v in vals])))
            acc[wi]["hp"].append(float(np.median([v[2] for v in vals])))
            acc[wi]["b"].append(float(np.median([v[3] for v in vals])))
    return [{k: np.asarray(v, float) for k, v in rec.items()} for rec in acc]


def frame_word_curves(fcurves, curves, min_frames=12):
    """Normalise `frame_curves` per word, in the shape `word_curves` returns.

    Rest for size and density is measured before the word's own first colour
    turn, and the baseline's rest over the whole window -- identical rules to
    `word_curves`, so downstream the two are interchangeable and a word can
    take whichever measurement did not break on it.
    """
    out = []
    for rec, wc in zip(fcurves, curves):
        got = {"word": wc["word"], "start_idx": wc["start_idx"],
               "t_first": wc["t_first"], "n_tracks": 0,
               "ts": None, "h": None, "d": None, "lift": None}
        out.append(got)
        t, t_first = rec["t"], wc["t_first"]
        if len(t) < min_frames or t_first is None:
            continue
        rest_h = _rest_of(t, rec["h"], t_first)
        rest_d = _rest_of(t, rec["d"], t_first)
        rest_hp = _rest_of(t, rec["hp"], t_first)
        rest_b = _rest_of(t, rec["b"], None)
        if None in (rest_h, rest_d, rest_hp, rest_b):
            continue
        if rest_h < 1e-6 or rest_d < 1e-6 or rest_hp < 4:
            continue
        got.update(ts=t, n_tracks=len(t),
                   # Size is the word's OWN pixel height against its own rest.
                   # `rec["h"]` is divided by the line median and is useful for
                   # rejecting global changes, but normalising that ratio a
                   # second time overstates a swell whenever the other words'
                   # segmented median changes. The directly measured pixel
                   # height is the scale the renderer must replay.
                   h=rec["hp"] / rest_hp, d=rec["d"] / rest_d,
                   lift=(rest_b - rec["b"]) / rest_hp)
    return out


# How "rest" is found. The intonation envelope LEADS the spoken onset, so a
# window that merely ends at the word's colour turn is already inside the
# effect being measured: "softer." starts shrinking ~0.9 s before it turns, so
# a pre-turn rest was measured on the already-shrunk word and reported 0.92
# against a true 0.50. Read-ahead (2.2.1) guarantees the line is on screen
# whole, in white, at its resting size before anything is spoken -- so the
# FIRST moments of a word's support are the reliable rest.
REST_SPAN_S = 0.60
# How far past the last surviving glyph track to keep measuring.
EXTEND_S = 2.0


def _rest_of(t, vals, t_first):
    """Median of ``vals`` over the word's first `REST_SPAN_S`, before its turn."""
    ok = np.isfinite(vals)
    if t_first is not None:
        ok = ok & (t < t_first)
    early = ok & (t <= t[0] + REST_SPAN_S)
    use = early if early.sum() >= 3 else ok
    return float(np.median(vals[use])) if use.sum() >= 3 else None


# Baked-curve sampling. dt is the source frame interval (~57 fps) rounded up;
# the curves are medians of interpolated tracks and carry nothing faster.
BAKE_DT = 0.02
BAKE_LEAD_S = 0.60      # minimum lead, when the previous word ran right up
BAKE_MAX_LEAD_S = 2.00  # ...and the most anticipation any word gets
BAKE_TAIL_S = 0.90      # the envelope decays after the word is spoken
BAKE_EDGE_S = 0.12      # keep clear of the caption being drawn / torn down


def bake_motion(rec, start, end, prev_end, t_shift, dwght_of):
    """One word's measured curves -> a `Motion` dict on a uniform grid.

    ``start``/``end`` are on the RECORDING's clock, like ``rec["ts"]``;
    ``t_shift`` is added once at the end to move the result onto the spec's.
    ``dwght_of`` turns an instantaneous density ratio into a wght-axis offset.

    The window is trimmed to the word's own span plus the lead and tail the
    envelope actually occupies. A glyph's track covers the whole caption's time
    on screen, so baking that raw would store several seconds of flat curve per
    word -- and the renderer's defaults outside the window are exactly rest, so
    nothing is lost by cutting it.

    The LEAD runs back to the previous word's end, not a fixed offset, because
    the anticipation is as long as the pause before the word. In "precisely as
    each word is spoken." the recording lifts "is" as soon as "word" finishes
    and HOLDS it raised, white, for 1.2 s before it turns yellow and drops --
    which a fixed 0.6 s lead cut off entirely, turning the single most visible
    gesture in that caption into a brief blip.
    """
    if rec["ts"] is None:
        return None
    ts = rec["ts"]
    lead = BAKE_LEAD_S if prev_end is None else max(
        BAKE_LEAD_S, min(BAKE_MAX_LEAD_S, start - prev_end))
    # The measured support's own edges are where glyphs enter and leave the
    # crop, and where the next caption is drawn over this one; both read as a
    # step change in every channel. Stay clear of them.
    lo = max(ts[0] + BAKE_EDGE_S, start - lead)
    hi = min(ts[-1] - BAKE_EDGE_S, end + BAKE_TAIL_S)
    if hi - lo < 4 * BAKE_DT:
        return None
    grid = np.arange(lo, hi + BAKE_DT * 0.5, BAKE_DT)

    def chan(arr, transform):
        """Resample one normalised channel onto the grid.

        Gaps where fewer than two glyphs were co-present are NaN; interpolating
        ACROSS them (rather than dropping the word) is right, because the
        neighbours either side are the same continuous motion seen through a
        different subset of letters. Outside the measured support the channel
        holds its rest value, which is what the renderer would use anyway.
        """
        ok = np.isfinite(arr)
        if ok.sum() < 4:
            return None
        return transform(np.interp(grid, ts[ok], arr[ok]))

    scale = chan(rec["h"], lambda v: v)
    lift = chan(rec["lift"], lambda v: v)
    dwght = chan(rec["d"], dwght_of)
    if scale is None or lift is None:
        return None
    if dwght is None:
        dwght = np.zeros(len(grid))
    # Rest exactly at the ends. The window is cut at a lead/tail rather than
    # where the motion happens to be zero, so without this a word can be handed
    # a step at t0 -- and a word that steps on appearing is precisely the
    # flicker this whole change exists to remove. Ramp over the first and last
    # 80 ms rather than detrending the whole curve, which would tilt a held
    # anticipation back down to nothing.
    edge = max(2, int(round(0.08 / BAKE_DT)))
    for ch, rest in ((lift, 0.0), (scale, 1.0), (dwght, 0.0)):
        ch[:edge] = rest + (ch[:edge] - rest) * np.linspace(0, 1, edge)
        ch[-edge:] = rest + (ch[-edge:] - rest) * np.linspace(1, 0, edge)
    return {"t0": round(float(grid[0] + t_shift), 3),
            "dt": BAKE_DT,
            "lift": [round(float(v), 4) for v in lift],
            "scale": [round(float(v), 4) for v in scale],
            "dwght": [round(float(v), 1) for v in dwght]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scroll", action="store_true")
    ap.add_argument("--no-emphasis", dest="emphasis", action="store_false",
                    help="emit neutral prosody instead of deriving per-word "
                         "emphasis from the video")
    ap.add_argument("--config", default=None)
    ap.add_argument("--gap", type=float, default=0.30)
    ap.add_argument("--rotate", type=int, default=0,
                    help="rotate the EMITTED phrase order by N. The transcript "
                         "must stay in RECORDING order for the 1:1 match, but "
                         "the recordings loop and start mid-cycle, so the "
                         "site's own order is a rotation of it.")
    ap.add_argument("--cut", type=float, default=0.35,
                    help="scroll-correlation level below which a caption change "
                         "is declared. Raise it for a WIDE crop: more content "
                         "keeps the correlation high across a change, so 0.35 "
                         "merges captions that 0.55 separates.")
    ap.add_argument("--list-groups", metavar="PNG", default=None,
                    help="write a contact sheet of one frame per caption "
                         "instance and exit -- READ THE TRANSCRIPT OFF THIS "
                         "rather than guessing it; the recordings loop and "
                         "interleave animated headings with the captions")
    args = ap.parse_args()

    cfg = load_config(args.config)
    cc_cfg = cfg.get("closed_caption", {})
    frames = sorted(glob.glob(args.frames))
    if not frames:
        raise SystemExit("no frames matched " + args.frames)
    phrases = read_transcript(args.transcript)

    obs, segs, per_frame = observations(frames, args.fps, args.scroll,
                                        cut=args.cut)
    groups = (split_by_segments(obs, segs, args.fps) if args.scroll
              else split_phrases(obs, args.gap))
    print(f"{len(frames)} frames, {len(obs)} confident turns, "
          f"{len(groups)} caption instances, {len(phrases)} transcript lines")

    if args.list_groups:
        from PIL import Image
        ims = []
        for gi, g in enumerate(groups):
            tmid = (g[0]["t"] + g[-1]["t"]) / 2
            k = min(len(frames) - 1, int(round(tmid * args.fps)))
            ims.append(Image.open(frames[k]).convert("RGB"))
            xs = [o["x"] for o in g]
            print(f"  group {gi}: {len(g):3d} runs  t {g[0]['t']:.2f}..{g[-1]['t']:.2f}s"
                  f"  x {min(xs):.0f}..{max(xs):.0f}  (frame {k})")
        w, h = ims[0].size
        sheet = Image.new("RGB", (w, (h + 8) * len(ims)))
        for i, im in enumerate(ims):
            sheet.paste(im, (0, i * (h + 8)))
        sheet.save(args.list_groups)
        print(f"wrote {args.list_groups} -- one frame per instance, in order")
        return

    # STRICT 1:1 IN TIME ORDER. Matching by run count is hopeless -- every
    # group here has 10-15 runs while the phrases want 20-28 characters,
    # because adjacent letters merge into single ink runs. The transcript
    # therefore lists every caption the recording shows, in the order it shows
    # them (headings and loop repeats included, prefixed "-" to measure but not
    # emit), and groups map to it positionally.
    if len(groups) != len(phrases):
        print(f"  !! {len(groups)} caption instances on screen but "
              f"{len(phrases)} transcript lines -- they must correspond 1:1.")
        for gi, g in enumerate(groups):
            xs = [o["x"] for o in g]
            print(f"     group {gi}: {len(g):3d} runs  t {g[0]['t']:.2f}..{g[-1]['t']:.2f}s"
                  f"  x {min(xs):.0f}..{max(xs):.0f}")
        raise SystemExit(1)
    chosen = list(groups)
    for ph, g in zip(phrases, chosen):
        mark = "" if ph["emit"] else "  (measured, not emitted)"
        print(f"  {ph['text'][:44]:46s} {len(g):3d} runs"
              f"  t {g[0]['t']:.2f}..{g[-1]['t']:.2f}s{mark}")

    kappa_all, gaps = [], []
    for ph, g in zip(phrases, chosen):
        if g and len(g) > 1:
            span = g[-1]["t"] - g[0]["t"]
            kappa_all.append(span / max(1, len([c for c in ph["text"] if not c.isspace()])))
    kappa = float(np.median(kappa_all)) if kappa_all else 0.05
    gap = 0.02

    order = list(range(len(phrases)))
    if args.rotate:
        keep = [i for i in order if phrases[i]["emit"]]
        r = args.rotate % max(1, len(keep))
        rotated = keep[r:] + keep[:r]
        order = []
        seen = set(keep)
        for i in range(len(phrases)):
            if i in seen:
                order.append(rotated.pop(0))
            else:
                order.append(i)

    words_out, t0, emitted = [], 0.0, 0
    for pi in order:
        ph, g = phrases[pi], chosen[pi]
        if not g or not ph["emit"]:
            continue
        nwords = len(ph["text"].split(" "))
        tracks_horizontally = bool(args.scroll and group_tracks_horizontally(g))
        boxes = word_boxes(per_frame, g, nwords, args.fps)
        pairs = align(g, ph["text"], boxes)
        fitted = fit_times(ph["text"], pairs, g, kappa, gap)
        if fitted is None:
            continue
        times, resid = fitted
        # Anchor on the phrase's own earliest START, not its first colour turn:
        # a word begins before its first character turns, so anchoring on the
        # turn pushes the opening word to a negative time (schema requires >= 0).
        base = min(st for st, _ in times)
        print(f"  phrase {pi}: {len(pairs)} aligned, residual {resid*1000:.0f} ms"
              + ("   <-- HIGH" if resid > 0.025 else ""))
        curves = None
        if args.emphasis:
            # TWO independent measurements of the same motion, and each fails
            # where the other works. Per-glyph tracking is clean but breaks on
            # a word that swells past 3x or is short enough to segment as one
            # merged run; the per-frame, spatially-attributed measure survives
            # both but is noisier and smears at word boundaries. Take the
            # tracked curve by default and the frame curve where tracking
            # produced nothing, or decisively under-read the swell.
            tracked = word_curves(ph["text"], pairs, g)
            framed = frame_word_curves(
                frame_curves(per_frame, pairs, g, ph["text"], args.fps,
                             boxes),
                tracked)
            t_emph, _ = emphasis(tracked)
            f_emph, f_meas = emphasis(framed)
            curves, sources, took = [], [], []
            for wi in range(nwords):
                tr, fr = tracked[wi], framed[wi]
                if tr["ts"] is None:
                    chosen_curve = fr
                    source = "frames"
                else:
                    # A strongly swelling word loses its individual glyph
                    # tracks exactly around the peak. Use the frame curve for
                    # SIZE only (including its surviving timing/support), and
                    # keep lift and density from their independent tracks.
                    # Replacing the whole record would let the noisier frame
                    # baseline invent vertical or weight motion.
                    chosen_curve = dict(tr)
                    source = "track"
                    # Compare DEVIATIONS from rest, not raw values. `>` can
                    # never be satisfied by a word that SHRINKS, so requiring
                    # f_emph > 1.15*t_emph (and t_emph > 1) made the frame
                    # measurement unreachable for the entire quiet half of the
                    # channel -- "softer." shrinks to 0.50 in the recording and
                    # was stuck reporting the 0.91 its broken tracks gave.
                    # Tracking is least reliable exactly here: a word shrinking
                    # to half loses its tracks, and the replacements measure
                    # their own "rest" on the already-small glyph.
                    if (fr["ts"] is not None
                            and abs(f_emph[wi] - 1.0)
                            > 1.15 * abs(t_emph[wi] - 1.0)):
                        fts = np.asarray(fr["ts"], float)
                        chosen_curve["ts"] = fts
                        chosen_curve["h"] = np.asarray(fr["h"], float)
                        for channel, rest in (("d", 1.0), ("lift", 0.0)):
                            arr = np.asarray(tr[channel], float)
                            ok = np.isfinite(arr)
                            if ok.sum() >= 2:
                                chosen_curve[channel] = np.interp(
                                    fts, np.asarray(tr["ts"])[ok], arr[ok],
                                    left=rest, right=rest)
                            else:
                                chosen_curve[channel] = np.full(len(fts), rest)
                        source = "frames"
                        took.append(f"{ph['text'].split(' ')[wi]} "
                                    f"{t_emph[wi]:.2f}->{f_emph[wi]:.2f}")
                curves.append(chosen_curve)
                sources.append(source)
            emph, measured = emphasis(curves)
            dens, dmeas = weight_ratio(curves)
            print(f"    size measurable for {sum(measured)}/{len(emph)}, "
                  f"weight for {sum(dmeas)}/{len(dens)} words")
            print("    " + "  ".join(
                f"{w}:{e:.2f}{'F' if sources[i] == 'frames' else ''}"
                for i, (w, e) in enumerate(zip(ph["text"].split(" "), emph))))
            if took:
                print("    frame-measured: " + ", ".join(took))
        else:
            emph, measured = [1.0] * nwords, [False] * nwords
            dens, dmeas = [1.0] * nwords, [False] * nwords
            sources = [None] * nwords
        # emphasis is relative to the MEDIAN word, as the renderer defines it
        med = float(np.median(emph)) if emph else 1.0
        # Density -> a weight target. Both are relative to the median word, as
        # the renderer defines emphasis, and the observed density spread is
        # mapped onto the weight span the renderer can actually reach.
        dmed = float(np.median(dens)) if dens else 1.0
        _ex = merged_expression(cfg)
        anchor = _ex.get("anchor_wght", [340, 430])[1]
        wlo, whi = _ex.get("wght_range", [280, 500])
        # Density -> a weight target, with a DEADBAND and a FIXED full-scale.
        # Normalising by the phrase's own maximum deviation was the bug behind
        # bold landing on the wrong words: in a phrase where nothing is
        # emphasised, the largest noise deviation gets stretched to full bold.
        # Measured, real emphasis is unmistakable and noise is not --
        # "weights" +0.53 and "louder" +0.19 against +-0.09 for everything
        # else -- so an absolute threshold separates them cleanly and keeps
        # magnitudes comparable between phrases.
        dead = cc_cfg.get("weight_deadband", 0.12)
        full = cc_cfg.get("weight_full_dev", 0.55)
        targets = []
        for e, d in zip(emph, dens):
            dev = d / dmed - 1.0
            if abs(dev) <= dead:
                wt = None
            else:
                frac = min(1.0, (abs(dev) - dead) / max(1e-6, full - dead))
                frac = frac if dev > 0 else -frac
                wt = anchor + frac * ((whi - anchor) if frac > 0
                                      else (anchor - wlo))
            targets.append({"emphScale": e / med, "emphWght": wt})
        report = []
        prosody = fit_spec_prosody(targets, cfg, report=report)
        for r in report[:3]:
            print("    !", r)

        # The same deadband/full-scale rule the scalar targets use, applied to
        # the INSTANTANEOUS density. The deviation is measured against the
        # word's OWN rest (the curve is already normalised to it), not against
        # the phrase median: dividing by `dmed` a second time put every word
        # at a non-zero weight offset while it was resting, which is a
        # permanent restyle rather than a motion.
        def dwght_of(ratio):
            dev = np.asarray(ratio) - 1.0
            frac = np.clip((np.abs(dev) - dead) / max(1e-6, full - dead), 0, 1)
            frac = np.where(dev > 0, frac, -frac)
            return frac * np.where(frac > 0, whi - anchor, anchor - wlo)

        baked = 0
        for wi, (word, (s, e)) in enumerate(zip(ph["text"].split(" "), times)):
            entry = {"text": word,
                     "start": round(max(0.0, s - base + t0), 3),
                     "end": round(e - base + t0, 3),
                     "speaker": ph["speaker"]}
            entry.update(word_fields(prosody[wi]["loudness"], prosody[wi]["pitch_hz"]))
            entry["emphasis_measured"] = bool(measured[wi])
            if sources[wi]:
                entry["emphasis_source"] = sources[wi]
            entry["tracking"] = tracks_horizontally
            if curves is not None and curves[wi]["ts"] is not None:
                entry["emphasis_source"] = sources[wi]
            if wi == 0 and emitted > 0:
                entry["line_break"] = True
            if curves is not None:
                # `- base + t0` is exactly the shift applied to start/end above,
                # so the baked clock and the word's clock stay one clock.
                m = bake_motion(curves[wi], s, e,
                                times[wi - 1][1] if wi else None,
                                t0 - base, dwght_of)
                if m is not None:
                    entry["motion"] = m
                    baked += 1
            words_out.append(entry)
        if curves is not None:
            print(f"    baked motion for {baked}/{nwords} words")
        emitted += 1
        t0 = words_out[-1]["end"] + 0.9

    speakers = {}
    palette = list(cfg["palette"])
    for i, name in enumerate(dict.fromkeys(w["speaker"] for w in words_out)):
        speakers[name] = {"color": palette[i % len(palette)]}
    spec = {
        "version": "1.0",
        "media": {"path": Path(args.transcript).stem, "fps": 30.0,
                  "duration": round(words_out[-1]["end"] + 1.5, 3)},
        "speakers": speakers,
        "words": words_out,
        "mapping": cfg["mapping"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(f"wrote {out}: {len(words_out)} words, "
          f"{spec['media']['duration']}s")


if __name__ == "__main__":
    main()
