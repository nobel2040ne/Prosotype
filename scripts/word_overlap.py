#!/usr/bin/env python3
"""Does a swelling word grow INTO the word beside it? Polled through playback.

The two existing geometry probes do not see this. `ink_collision.py` measures
the clearance between adjacent ROWS, and `clip_probe.py` measures a row running
off the stage. A word overlapping its neighbour is neither: the row's width is
correct, the stage is not exceeded, and the text is destroyed anyway.

It happens because `.word-glyph` is `position: absolute` -- out of flow, so it
does not reserve its grown width -- and grows about its own centre, while the
design system's own rule is that a swelling word does not PUSH its neighbours.
Both halves are deliberate. What bounds them is the crest amplitude, and this
is the check on it.

    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    .venv/bin/python scripts/word_overlap.py
    .venv/bin/python scripts/word_overlap.py --broken   # must FAIL

MEASURED 2026-08-12, which is what sized `voice_scale_points_enhanced`: at a
1.56x ceiling this reported 189 overlapping pair-samples, worst -23.8px
("whatever|you", "do|whatever", "the|rescue"); at 1.46x it reports none.

Sample fast. The crest's whole window is 424-1050ms and the overlap exists only
near its peak, so a slow poll misses it and reports a clean stage.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from motion_trace import CHROME, wait_for_debugger  # noqa: E402

# Adjacent glyph boxes within one row. Sorted by `left` rather than by DOM
# order: the overlaid glyph is centred on its sizer, so a large word's box can
# start left of the box before it, and comparing in DOM order would then
# measure the wrong pair.
PROBE = r"""
(() => {
  const out = [];
  for (const row of document.querySelectorAll('.caption-words')) {
    const glyphs = [...row.querySelectorAll('.word-glyph')]
      .map((g) => ({r: g.getBoundingClientRect(), t: (g.textContent || '').trim()}))
      .filter((g) => g.r.width > 0)
      .sort((a, b) => a.r.left - b.r.left);
    for (let i = 1; i < glyphs.length; i += 1) {
      const gap = glyphs[i].r.left - glyphs[i - 1].r.right;
      if (gap < 0) {
        out.push({gap: Math.round(gap * 10) / 10,
                  pair: glyphs[i - 1].t + '|' + glyphs[i].t});
      }
    }
  }
  return out;
})()
"""

# The negative control. `--voice-scale` is NOT the lever here: the crest clamps
# it at the stage ceiling, so forcing it larger changes almost nothing and the
# control passed while proving nothing. Scale the glyph directly instead, which
# is downstream of every clamp.
BREAK = r"""
(() => {
  const s = document.createElement('style');
  s.textContent = '.word-glyph { transform: translate3d(-50%,0,0) scale(1.6) !important; }';
  document.head.appendChild(s);
  return true;
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--seconds", type=float, default=22.0)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--port", type=int, default=9226)
    ap.add_argument("--broken", action="store_true",
                    help="force oversized words; the probe MUST report overlap")
    args = ap.parse_args()

    proc = subprocess.Popen(
        [str(CHROME), "--headless=new", f"--remote-debugging-port={args.port}",
         "--window-size=1280,720", "--no-first-run", "--disable-gpu",
         f"--user-data-dir=/tmp/word-overlap-{args.port}", args.url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    hits: list[dict] = []
    worst, samples = 0.0, 0
    try:
        url = wait_for_debugger(args.port)
        from websockets.sync.client import connect
        with connect(url, max_size=None) as ws:
            counter = 0

            def evaluate(expression: str):
                nonlocal counter
                counter += 1
                ws.send(json.dumps({
                    "id": counter, "method": "Runtime.evaluate",
                    "params": {"expression": expression, "returnByValue": True}}))
                while True:
                    message = json.loads(ws.recv())
                    if message.get("id") == counter:
                        return message["result"]["result"].get("value")

            if args.broken:
                evaluate(BREAK)
            end = time.time() + args.seconds
            while time.time() < end:
                found = evaluate(PROBE)
                if found is not None:
                    samples += 1
                    for hit in found:
                        hits.append(hit)
                        worst = min(worst, hit["gap"])
                if args.broken and samples > 6:
                    evaluate(BREAK)   # re-apply after a re-render
                time.sleep(args.interval)
    finally:
        proc.terminate()

    if samples < 10:
        print(f"only {samples} samples — the stage never rendered. INVALID, "
              "not a pass.")
        return 2
    print(f"\nsamples {samples}   word-pairs overlapping {len(hits)}")
    print(f"worst overlap  {worst:.1f}px")
    for hit in sorted(hits, key=lambda h: h["gap"])[:6]:
        print(f"  {hit['gap']:7.1f}px  {hit['pair']}")
    if hits:
        if args.broken:
            print("\n--broken: FAIL as expected — the check can go red")
            return 0
        print("\nFAIL — a word grew into its neighbour")
        return 1
    if args.broken:
        print("\n--broken: THE CONTROL DID NOT FAIL — the probe proves nothing")
        return 1
    print("\nPASS — no word grew into its neighbour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
