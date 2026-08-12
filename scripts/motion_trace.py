#!/usr/bin/env python3
"""Capture the stage's per-word motion into `rows.json` for `word_motion.py`.

`word_motion.py` documents its input as "rows.json from motion_trace" and the
producer has never been in the repo -- it was rewritten as a scratchpad tool
each session, which is why the acceptance figures are expensive to re-check.
This is that producer, kept.

    .venv/bin/python -m autocwi live --sample --lang ko --loop --no-open &
    .venv/bin/python scripts/motion_trace.py --out /tmp/ko-rows.json --seconds 40
    .venv/bin/python scripts/word_motion.py --trace /tmp/ko-rows.json

WHAT IT READS, and why each one:

  fontSize   on `.word-ink` -- the 2.3 crest, which IS a font-size.
  transform  on `.word-glyph` -- the 2.2.3 pop is a TRANSFORM ON A CHILD, so
             `.word-ink`'s own rect does not contain it and font-size alone
             misses it entirely. `word_motion.py` multiplies the two.
  weight     the resolved `font-weight`, the 2.3.8/9 channel.
  holdLift   `--hold-lift`, the held word's rise.
  stretch    `font-stretch`, the 2.3.10 width channel. Recorded so a face with
             no `wdth` axis shows up as a channel that never moves rather than
             as an absence nobody measured -- Noto Sans KR has ONLY `wght`, so
             `font-stretch` on Korean captions is silently inert.

Sample fast: the motion window is ~1 s and the crest's rise is ~0.2 s, so a
slow poll aliases the peak away and every word reads as settled.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

PROBE = r"""
(() => {
  const words = [...document.querySelectorAll('.caption-word')].map((w) => {
    const ink = w.querySelector('.word-ink') || w;
    const glyph = w.querySelector('.word-glyph') || w;
    const gi = getComputedStyle(ink);
    const gg = getComputedStyle(glyph);
    /* `id` and `color` are what let `motion_diff.py` build a turn-aligned
       envelope: a word must be followed across samples, and its own colour
       turn is the only landmark the film also carries. Keying by index would
       break the moment a row re-breaks -- the trap `word_motion.py` documents. */
    /* The FIRST character. Indexing to the "middle" to match the film's
       half-the-ink landmark was tried and measured WORSE (peak 0.08s vs 0.10s
       against the film's 0.14s): `.caption-character` spans more than one ink
       layer, so the midpoint of the node list is not the midpoint of the word. */
    const chars = w.querySelectorAll('.caption-character');
    const lit = chars.length ? chars[0] : ink;
    return {
      text: w.textContent || '',
      id: w.dataset.wordId || w.getAttribute('data-word-id') || '',
      color: getComputedStyle(lit).color,
      loudness: getComputedStyle(w).getPropertyValue('--voice-loudness').trim(),
      motionDur: getComputedStyle(w).getPropertyValue('--motion-duration').trim(),
      crestDur: getComputedStyle(w).getPropertyValue('--crest-duration').trim(),
      sweepDur: getComputedStyle(w).getPropertyValue('--sweep-duration').trim(),
      /* THE CHARACTER LAYER, without which this probe measures only part of
         the motion. `character-wave` is a transform on `.caption-character` --
         a different element from `.word-ink` and `.word-glyph` -- so it changed
         the ink a viewer sees while being invisible here. Measured from pixels
         the visible motion was ~4x what this probe reported, and that gap was
         entirely this. Report the largest and smallest vertical scale across
         the word's glyphs, which is what the wave actually varies.

         AND READ THE LIFT AND THE ANGLE, not just the scale. The wave is now
         a LIFT plus a small per-letter ROTATION -- the film lifts letters in
         pairs ("se"+"en", "Gu"+"mp") at slightly different angles -- and a
         probe reading only `scaleY` reports a stationary word while its
         glyphs travel. Same trap as the one above, one layer down.
         `charY` is the per-letter translateY in px, min and max across the
         word; `charRot` is the rotation in degrees, likewise. */
      charScale: (() => {
        const cs = w.querySelectorAll('.caption-character');
        if (!cs.length) return '';
        let lo = Infinity, hi = -Infinity;
        for (const c of cs) {
          const m = getComputedStyle(c).transform;
          let sy = 1;
          if (m && m.startsWith('matrix(')) {
            const p = m.slice(7, -1).split(',').map(Number);
            if (p.length >= 4) sy = Math.abs(p[3]);
          }
          if (sy < lo) lo = sy;
          if (sy > hi) hi = sy;
        }
        return `${lo.toFixed(4)},${hi.toFixed(4)}`;
      })(),
      charMotion: (() => {
        const cs = w.querySelectorAll('.caption-character');
        if (!cs.length) return '';
        const ys = [], rots = [];
        for (const c of cs) {
          const m = getComputedStyle(c).transform;
          if (!m || !m.startsWith('matrix(')) { ys.push(0); rots.push(0); continue; }
          const p = m.slice(7, -1).split(',').map(Number);
          ys.push(p[5] || 0);
          /* atan2(b, a) recovers the rotation from the 2x2 block. The wave's
             scale is Y-only, so it does not contaminate this angle. */
          rots.push(Math.atan2(p[1], p[0]) * 180 / Math.PI);
        }
        return ys.map((y) => y.toFixed(2)).join(' ') + '|'
             + rots.map((r) => r.toFixed(2)).join(' ');
      })(),
      voiceScale: getComputedStyle(w).getPropertyValue('--voice-scale').trim(),
      fontSize: gi.fontSize,
      transform: gg.transform,
      weight: gi.fontWeight,
      stretch: gi.fontStretch,
      holdLift: getComputedStyle(w).getPropertyValue('--hold-lift').trim(),
      phase: getComputedStyle(w).getPropertyValue('--voice-phase').trim(),
    };
  });
  return {t: performance.now(), words};
})()
"""


def wait_for_debugger(port: int, timeout_s: float = 25.0) -> str:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json", timeout=2
            ) as response:
                for target in json.load(response):
                    if (target.get("type") == "page"
                            and target.get("webSocketDebuggerUrl")):
                        return target["webSocketDebuggerUrl"]
        except Exception as exc:                              # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.3)
    raise SystemExit(f"Chrome debugger never became ready on :{port} ({last})")


def capture(url: str, seconds: float, interval_s: float) -> list[dict]:
    from websockets.sync.client import connect

    rows: list[dict] = []
    with connect(url, max_size=32 * 1024 * 1024) as socket:
        state = {"id": 0}

        def evaluate(expression: str):
            state["id"] += 1
            message_id = state["id"]
            socket.send(json.dumps({
                "id": message_id,
                "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True},
            }))
            while True:
                reply = json.loads(socket.recv())
                if reply.get("id") == message_id:
                    return reply.get("result", {}).get("result", {}).get("value")

        deadline = time.time() + seconds
        while time.time() < deadline:
            row = evaluate(PROBE)
            if isinstance(row, dict) and row.get("words"):
                rows.append(row)
            time.sleep(interval_s)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--interval", type=float, default=0.03,
                    help="poll period; the crest rises in ~0.2s (default 0.03)")
    ap.add_argument("--settle", type=float, default=12.0,
                    help="wait before capturing, for models to load and words "
                         "to reach the stage (default 12)")
    ap.add_argument("--port", type=int, default=9399)
    ap.add_argument("--window", default="1440,900")
    args = ap.parse_args()

    if not CHROME.exists():
        raise SystemExit(f"Chrome not found at {CHROME}")

    profile = Path(f"/tmp/cwi-motion-trace-{args.port}")
    chrome = subprocess.Popen(
        [
            str(CHROME), "--headless=new", "--disable-gpu",
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile}",
            f"--window-size={args.window}",
            "--no-first-run", "--no-default-browser-check",
            args.url,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        socket_url = wait_for_debugger(args.port)
        print(f"attached to {args.url}; settling {args.settle}s")
        time.sleep(args.settle)
        print(f"capturing {args.seconds}s every {args.interval}s")
        rows = capture(socket_url, args.seconds, args.interval)
    finally:
        chrome.terminate()

    if not rows:
        print("no samples — the stage never showed a word. The run is INVALID, "
              "not an empty result.")
        return 2
    Path(args.out).write_text(json.dumps(rows))
    words = max(len(r["words"]) for r in rows)
    print(f"{len(rows)} rows, up to {words} words on stage -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
