#!/usr/bin/env python3
"""Is a caption row being CUT? Polled through live playback.

`.caption-words` is `nowrap`, so a row wider than its box is silently CLIPPED --
no error, no reflow, nothing on screen to say text went missing. This is the
check for that, and it has to run DURING playback: a settled stage can pass by
sampling a lucky instant.

    .venv/bin/python -m autocwi live --sample --lang ko --no-open &
    .venv/bin/python scripts/clip_probe.py --samples 60
    .venv/bin/python scripts/clip_probe.py --samples 60 --broken   # must FAIL

**MEASURE THE IN-FLOW SIZERS, NOT `scrollWidth`.** `.word-glyph` is
`position: absolute` and out of flow, so a swelling word inflates
`.caption-words`'s `scrollWidth` with no text lost -- that is the design, and a
probe on that basis reported 46-58px of "silent cutting" across ~500 of ~3300
row-samples that was a FALSE POSITIVE, chased through two attempted fixes. The
in-flow `.character-sizer` / `.word-sizer-crest` own the row's real width.

**MEASURE AGAINST THE STAGE, NOT THE FEED.** `.caption-feed`'s right padding is
the gutter that exists to absorb a row-final word's mid-pop overhang, so a row
spilling into it is the design working. `.caption-stage` carries
`overflow: hidden` and is where text actually disappears.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

# Per row: the rightmost edge any IN-FLOW sizer reaches, against the stage's
# own content box. Positive `over` means characters are past the clip edge.
PROBE = r"""
(() => {
  const stage = document.querySelector('.caption-stage');
  if (!stage) return {error: 'no stage'};
  const clip = stage.getBoundingClientRect();
  const rows = [...document.querySelectorAll('.caption-words')];
  const out = [];
  for (const row of rows) {
    const sizers = [...row.querySelectorAll('.character-sizer, .word-sizer-crest')];
    if (!sizers.length) continue;
    let right = -Infinity, left = Infinity;
    for (const s of sizers) {
      const r = s.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      right = Math.max(right, r.right);
      left = Math.min(left, r.left);
    }
    if (!Number.isFinite(right)) continue;
    out.push({
      over: right - clip.right,
      under: clip.left - left,
      width: right - left,
      words: row.querySelectorAll('.caption-word').length,
      text: (row.textContent || '').slice(0, 60),
    });
  }
  return {rows: out, stageWidth: clip.width};
})()
"""

# Re-imposes the bug: charge every character the LATIN width, which is what
# shipped before 2026-08-10 and is what clipped Korean.
BREAK = r"""
(() => {
  document.querySelectorAll('.caption-words').forEach((row) => {
    row.style.letterSpacing = '0.42em';
  });
  return true;
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
                targets = json.load(response)
            for target in targets:
                if (target.get("type") == "page"
                        and target.get("webSocketDebuggerUrl")):
                    return target["webSocketDebuggerUrl"]
        except Exception as exc:                              # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.3)
    raise SystemExit(f"Chrome debugger never became ready on :{port} ({last})")


def sample(url: str, samples: int, interval_s: float, broken: bool) -> list[dict]:
    from websockets.sync.client import connect

    collected: list[dict] = []
    with connect(url, max_size=8 * 1024 * 1024) as socket:
        state = {"id": 0}

        def evaluate(expression: str):
            state["id"] += 1
            message_id = state["id"]
            socket.send(json.dumps({
                "id": message_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            }))
            while True:
                reply = json.loads(socket.recv())
                if reply.get("id") == message_id:
                    result = reply.get("result", {}).get("result", {})
                    return result.get("value")

        for _ in range(samples):
            if broken:
                evaluate(BREAK)
            value = evaluate(PROBE)
            if isinstance(value, dict) and value.get("rows"):
                collected.append(value)
            time.sleep(interval_s)
    return collected


def summarize(samples: list[dict], broken: bool) -> int:
    rows = [row for s in samples for row in s["rows"]]
    if not rows:
        print("no row samples — the stage never filled. The run is INVALID, "
              "not a pass.")
        return 2

    clipped = [r for r in rows if r["over"] > 0.5]
    worst = max(rows, key=lambda r: r["over"])
    fills = [r["width"] / s["stageWidth"]
             for s in samples for r in s["rows"]]

    print(f"samples {len(samples)}   row-samples {len(rows)}")
    print(f"worst overflow      {worst['over']:+.1f}px")
    print(f"rows past the edge  {len(clipped)} of {len(rows)} "
          f"({100 * len(clipped) / len(rows):.1f}%)")
    print(f"median row fill     {sorted(fills)[len(fills) // 2]:.0%} of stage")
    if clipped:
        print("\nworst offender:")
        print(f"  +{worst['over']:.1f}px  {worst['words']} words  "
              f"{worst['text']!r}")

    ok = not clipped
    if broken:
        print("\n--broken: " + ("FAIL as expected — the check can go red"
                                if clipped else
                                "PASS, which means THIS CHECK IS WORTHLESS"))
        return 0 if clipped else 1
    print("\n" + ("PASS — nothing clipped" if ok else "FAIL — text is being cut"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--samples", type=int, default=60)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--port", type=int, default=9333)
    ap.add_argument("--window", default="1440,900")
    ap.add_argument("--broken", action="store_true",
                    help="widen every row; the check MUST go red")
    args = ap.parse_args()

    if not CHROME.exists():
        raise SystemExit(f"Chrome not found at {CHROME}")

    profile = Path(f"/tmp/cwi-clip-probe-{args.port}")
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
        print(f"attached to {args.url}; {args.samples} samples "
              f"every {args.interval}s\n")
        return summarize(
            sample(socket_url, args.samples, args.interval, args.broken),
            args.broken,
        )
    finally:
        chrome.terminate()


if __name__ == "__main__":
    sys.exit(main())
