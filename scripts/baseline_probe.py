"""Does a swelling word stay on its baseline? Measured in pixels, every word.

CWI grows a word FROM its baseline and never moves it. Measured across the
reference's own baked curves, lift regresses on size at +0.043 and its biggest
word has a lift of exactly 0.000. Size does not raise a word; waiting does.

WHY IT IS A SEPARATE PROBE. The lift it catches is LAYOUT, not transform.
``studio_probe.py`` decides a word is moving from ``|matrix.f| > 0.5``, and a
word whose baseline rides up because its own line box grew keeps
``matrix.f == 0`` throughout — so that probe is structurally blind to it, and a
real 0.24em lift shipped undetected through three attempts to find it.

It segments with ``autocwi.refmeasure`` so both sides of any comparison run
identical segmentation, and because that module already thresholds each glyph
relative to ITS OWN peak luminance — a fixed threshold measures a yellow glyph
and a white one differently and fakes a size change exactly at the colour turn.

IT PINS THE CREST INSTEAD OF CHASING IT. Tracking a glyph across frames is the
textbook approach and does not work here: the stage re-flows whenever a word
arrives, so runs break constantly (a 314-frame capture yielded one swelling
glyph). Instead it holds the settled stage at one crest over CDP and compares
each word's ink bottom against its own at rest — same word, same pixels, so
glyph shape cancels.

**The MEDIAN is the verdict, not the max.** At a high crest adjacent rows
overlap, so a minority of words have no clean crop box and read the same in a
fixed build and a broken one. That is the harness. Korean is under-powered
here (n=5); its robust evidence is the DOM sweep instead.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autocwi.refmeasure import glyphs_array  # noqa: E402

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEBUG_PORT = 9224

# Hold EVERY THIRD word at one point on its crest. `--voice-phase` is a
# registered custom property driven by the `voice-phase` animation, and an
# author `!important` outranks an animation -- the same lever reduced motion
# uses.
#
# A SUBSET, NOT THE WHOLE STAGE. Pinning every word at 1.62x is not just
# unrealistic (peak simultaneous motions is ~5 of ~48), it makes the stage
# unmeasurable: at that crest adjacent rows overlap VERTICALLY, so any crop
# around one word also contains the ascenders of the row below and reads THEIR
# bottom as its own -- measured, a uniform -0.54em on every word, in the fixed
# build and the broken one alike. Leaving two words in three at rest keeps each
# subject surrounded by settled neighbours, which is also what a real crest
# looks like. (Layout is unaffected either way: word count, type size and every
# cell bottom are identical between passes -- checked.)
PIN = """
(() => {
  let style = document.getElementById('cwi-baseline-pin');
  if (!style) {
    style = document.createElement('style');
    style.id = 'cwi-baseline-pin';
    document.head.appendChild(style);
  }
  const words = [...document.querySelectorAll('.caption-feed .caption-word')];
  words.forEach((word, i) => {
    if (i %% 3 === 1) word.dataset.cwiPin = '1';
    else delete word.dataset.cwiPin;
  });
  style.textContent = '.caption-word[data-cwi-pin="1"] {' +
    '--voice-phase: 1 !important;' +
    '--voice-scale: %(crest)s !important;' +
    '--sync-pop: %(pop)s !important;' +
    '--hold-lift: 0em !important;' +
    '--char-wave: 0 !important;' + '}' + '%(broken)s';
  return true;
})()
"""

# SELF-TEST. Restores the pre-2026-08-03 anchoring -- box-bottom pin, resting
# pivot -- so the probe can be shown to FAIL on the defect it exists to catch.
# A green check that has never been seen to go red is not evidence.
BROKEN = (
    '.caption-word[data-cwi-pin="1"] .word-glyph {'
    "translate: none !important;"
    "transform-origin: 50% calc(100% - var(--glyph-baseline-em, .38em))"
    " !important;}"
)

# The DOM's account of where each word is. Used ONLY to crop; every measured
# number below comes from pixels.
LABELS = """
JSON.stringify({
  baselineEm: getComputedStyle(document.querySelector('.studio-shell'))
    .getPropertyValue('--glyph-baseline-em').trim(),
  words: [...document.querySelectorAll('.caption-feed .caption-word')]
    .map((word) => {
      const glyph = word.querySelector('.word-glyph');
      if (!glyph) return null;
      const cell = word.getBoundingClientRect();
      const box = glyph.getBoundingClientRect();
      return {
        pinned: word.dataset.cwiPin === '1',
        text: word.textContent,
        cellBottom: cell.bottom,
        x0: box.left, x1: box.right,
        restPx: parseFloat(getComputedStyle(word).fontSize),
      };
    }).filter(Boolean),
});
"""


def wait_for_debugger(port: int, timeout_s: float = 25.0) -> str:
    """Same handshake as ``studio_probe.py``: poll /json for the page target."""
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=2
            ) as response:
                targets = json.load(response)
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.3)
    raise SystemExit(f"Chrome debugger never ready on :{port} ({last})")


def pinned_passes(url, window, port, crests, pop, settle_s, keep,
                  broken=False):
    """One screenshot per crest, of a SETTLED stage that is no longer changing.

    Waiting for the sample to finish is what makes the passes comparable: the
    same words, in the same rows, differing only in the pinned crest.
    """
    profile = Path("/tmp") / f"cwi-baseline-probe-{port}"
    proc = subprocess.Popen([
        str(CHROME), "--headless=new", "--disable-gpu",
        f"--remote-debugging-port={port}", f"--window-size={window}",
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out: dict[float, tuple] = {}
    try:
        ws = wait_for_debugger(port)
        from websockets.sync.client import connect

        with connect(ws, max_size=64 * 1024 * 1024) as socket:
            state = {"id": 0}

            def call(method, params=None):
                state["id"] += 1
                mid = state["id"]
                socket.send(json.dumps(
                    {"id": mid, "method": method, "params": params or {}}))
                while True:
                    reply = json.loads(socket.recv())
                    if reply.get("id") == mid:
                        return reply.get("result", {})

            def evaluate(expr):
                return call("Runtime.evaluate", {
                    "expression": expr, "returnByValue": True,
                }).get("result", {}).get("value")

            print(f"  waiting {settle_s:.0f}s for the stage to fill and settle…")
            time.sleep(settle_s)
            for crest in crests:
                evaluate(PIN % {"crest": crest, "pop": pop,
                                "broken": BROKEN if broken else ""})
                time.sleep(0.4)          # one style + layout + paint
                labels = json.loads(evaluate(LABELS) or "null")
                data = call("Page.captureScreenshot", {"format": "png"}).get("data")
                if not data or not labels or not labels["words"]:
                    continue
                raw = base64.b64decode(data)
                if keep is not None:
                    (keep / f"crest{crest:.3f}.png").write_bytes(raw)
                out[crest] = (
                    np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"),
                               dtype=np.float32),
                    labels,
                )
    finally:
        proc.terminate()
    return out


def as_ink_on_black(patch: np.ndarray) -> np.ndarray:
    """Hand `refmeasure` the polarity it was written for.

    It segments the reference recordings, which are light ink on a black
    captions box (CWI 2.4.1), so `INK = 70` selects BRIGHT pixels. The studio's
    default stage is the light theme -- dark ink on #FAFAF8 -- where that picks
    out the BACKGROUND and returns nothing at all. Inverting keeps the
    segmentation byte-identical, which is the point of routing through that
    module rather than forking a second thresholder that would drift.
    """
    if float(np.median(patch.max(axis=2))) > 128.0:
        return 255.0 - patch
    return patch


# A word whose ink bottom is NOT its baseline cannot serve as its own guide at
# one size and something else at another -- but it can, because it is compared
# only with itself. Descenders are excluded anyway: they make the ink bottom a
# descender depth, which scales with the crest and would masquerade as a lift.
DESCENDERS = set("gjpqy(),;[]{}_")


def ink_bottom(frame: np.ndarray, word: dict, pad: float) -> float | None:
    """The lowest ink row of one word, in screen pixels."""
    rest = word["restPx"]
    x0 = max(0, int(word["x0"] - 3))
    x1 = min(frame.shape[1], int(word["x1"] + 3))
    y0 = max(0, int(word["cellBottom"] - pad * rest))
    # Only just below the cell bottom. A descenderless word's ink bottom is
    # its BASELINE, which sits `--glyph-baseline-em` ABOVE the cell bottom, so
    # nothing of this word lives down there -- but the next ROW does, and rows
    # are 1.38em apart. Reaching 1.0em below caught the row beneath and read
    # its ascenders as this word's ink bottom: measured, that produced
    # symmetric +/-45px readings on the Korean stage, where the rows are
    # closest. Extra ink ABOVE is harmless, because the bottom is a max.
    y1 = min(frame.shape[0], int(word["cellBottom"] + 0.20 * rest))
    if x1 - x0 < 4 or y1 - y0 < 6:
        return None
    found = glyphs_array(as_ink_on_black(frame[y0:y1, x0:x1]))
    if not found:
        return None
    return y0 + max(g["bot"] for g in found)


def measure(passes: dict, pad: float):
    """Per word: how far its ink bottom moved when the crest was applied."""
    if 1.0 not in passes:
        raise SystemExit("no rest pass (crest 1.0) — nothing to compare against")
    rest_frame, rest_labels = passes[1.0]
    rest_words = rest_labels["words"]
    rows = []
    for crest, (frame, labels) in sorted(passes.items()):
        if crest == 1.0:
            continue
        words = labels["words"]
        if len(words) != len(rest_words):
            print(f"  crest {crest}: stage changed ({len(words)} vs "
                  f"{len(rest_words)} words) — skipped")
            continue
        for rest_word, word in zip(rest_words, words):
            text = word["text"]
            if rest_word["text"] != text or DESCENDERS & set(text):
                continue
            if not word.get("pinned"):
                continue
            a = ink_bottom(rest_frame, rest_word, pad)
            b = ink_bottom(frame, word, pad)
            if a is None or b is None:
                continue
            # ROW-RELATIVE, NOT ABSOLUTE SCREEN Y. Differencing raw screen
            # positions between two passes assumes the word did not move, and
            # Korean breaks that immediately: pinned at 1.62x the words are
            # much wider, the rows re-wrap, and a word lands on a different
            # row -- measured, that produced symmetric +/-49px readings on
            # 야생동물들을 / 보기 that are a re-flow, not a lift.
            # `cellBottom` is the row's shared bottom edge, set by the hidden
            # resting `.word-sizer`, so it is invariant to the crest BY
            # CONSTRUCTION -- which is what makes it a legitimate datum rather
            # than a DOM number standing in for a pixel one. Every measured
            # quantity is still the ink bottom, read off the screen.
            depth_rest = a - rest_word["cellBottom"]
            depth_crest = b - word["cellBottom"]
            rise = depth_rest - depth_crest
            rows.append({
                "text": text[: len(text) // 3] or text,
                "crest": crest,
                # +ve = the swollen word sits ABOVE where it rests.
                "rise_px": rise,
                "rise_em": rise / word["restPx"],
                "rest_px": word["restPx"],
            })
    return rows, rest_labels.get("baselineEm", "?")


def reference_slope():
    """The same regression over the checked-in reference measurements."""
    root = Path(__file__).resolve().parent.parent / "assets" / "reference_specs"
    xs, ys = [], []
    for path in sorted(root.glob("*.json")):
        if path.stem == "demo":
            continue
        for word in json.loads(path.read_text())["words"]:
            motion = word.get("motion") or {}
            if not motion.get("lift") or not motion.get("scale"):
                continue
            xs.append(float(np.max(motion["scale"])))
            ys.append(float(np.max(motion["lift"])))
    if len(xs) < 3:
        return None
    slope, intercept = np.polyfit(xs, ys, 1)
    return slope, intercept, float(np.corrcoef(xs, ys)[0, 1]), len(xs)


def report(rows, baseline_em, limit_em) -> int:
    if len(rows) < 12:
        print(f"FAIL: only {len(rows)} word-measurements — nothing to conclude")
        return 1
    per_crest = min(sum(1 for r in rows if r["crest"] == c)
                    for c in {r["crest"] for r in rows})
    if per_crest < 8:
        print(f"NOTE: only {per_crest} words at the thinnest crest — the median "
              f"is noisy at that n. The Korean sample lands here; use the DOM "
              f"sweep for a robust answer.")
    crest = np.array([r["crest"] for r in rows])
    rise = np.array([r["rise_em"] for r in rows])
    print(f"\n--glyph-baseline-em = {baseline_em}")
    print(f"{len(rows)} word-measurements over "
          f"{len(set(crest))} pinned crests\n")
    print(f"  {'crest':>6} {'n':>4} {'median rise':>12} {'p95 |rise|':>11} {'max |rise|':>11}")
    for value in sorted(set(crest)):
        m = crest == value
        print(f"  {value:6.3f} {int(m.sum()):4d} {np.median(rise[m]):+11.4f}em "
              f"{np.percentile(np.abs(rise[m]), 95):10.4f}em "
              f"{np.abs(rise[m]).max():10.4f}em")

    # THE MEDIAN IS THE VERDICT; THE MAX IS DIAGNOSTIC ONLY.
    # A minority of crops still catch the ascenders of the row below -- at a
    # 1.62x crest adjacent rows overlap vertically, so for some words no crop
    # box separates them -- and those readings sit around 0.54em in the FIXED
    # build and the BROKEN one alike. That is this harness's limitation, not
    # the renderer's behaviour, and failing on it would be reporting on the
    # crop. The median is immune to it and separates decisively: measured on
    # English, +0.196em at crest 1.62 with the old anchoring against -0.025em
    # with the fix. Run with `--broken` and watch the median climb with the
    # crest; that is the check.
    verdict = []
    for value in sorted(set(crest)):
        if value <= 1.0:
            continue
        verdict.append(abs(float(np.median(rise[crest == value]))))
    worst_median = max(verdict) if verdict else 0.0
    grow = crest > 1.0
    slope = (float(np.polyfit(crest[grow], rise[grow], 1)[0])
             if grow.sum() > 2 else 0.0)
    ref = reference_slope()
    print(f"\n  worst median |rise| over the crests   {worst_median:.4f}em")
    print(f"  rise-vs-crest slope (all readings)    {slope:+.4f} em per 1.0x")
    if ref:
        print(f"  reference ({ref[3]} words) lift-vs-size slope {ref[0]:+.4f}")
    print(f"  max |rise| (crop-limited, diagnostic) {float(np.abs(rise).max()):.4f}em")

    ok = worst_median <= limit_em
    print(f"\n{'PASS' if ok else 'FAIL'}: a word must grow from its baseline. "
          f"worst median |rise| {worst_median:.4f}em (limit {limit_em}em; "
          f"the old anchoring gives 0.196em on English, 0.093em on Korean)")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--settle", type=float, default=76.0,
                    help="seconds to wait for the sample to finish")
    ap.add_argument("--port", type=int, default=DEBUG_PORT)
    ap.add_argument("--window", default="1440,900")
    ap.add_argument("--crests", default="1.0,0.78,1.15,1.30,1.62")
    ap.add_argument("--pop", default="1.15")
    ap.add_argument("--pad", type=float, default=2.4,
                    help="crop height above the cell bottom, in resting em")
    # One screen pixel is 0.0245em at the shipped 40.8px caption, so a
    # limit under ~0.05em is below what this measurement can resolve.
    # MEASURED noise floor with the fix in: every non-zero reading is
    # exactly +/-1px or +/-2px, and the MEDIAN is 0.0000em at every crest.
    # 1 screen px is 0.0245em at the shipped 40.8px caption, so anything under
    # ~0.05em is below what this can resolve. English measures 0.0245em with
    # the fix and 0.196em without it, so 0.06 sits between them with margin.
    ap.add_argument("--limit-em", type=float, default=0.075)
    ap.add_argument("--broken", action="store_true",
                    help="re-impose the old anchoring; the probe must FAIL")
    ap.add_argument("--keep", default="")
    args = ap.parse_args()

    keep = Path(args.keep) if args.keep else None
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    crests = [float(v) for v in args.crests.split(",")]
    passes = pinned_passes(args.url, args.window, args.port, crests,
                           args.pop, args.settle, keep, args.broken)
    print(f"captured {len(passes)} pinned passes from {args.url}")
    rows, baseline_em = measure(passes, args.pad)
    raise SystemExit(report(rows, baseline_em, args.limit_em))


if __name__ == "__main__":
    main()
