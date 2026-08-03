#!/usr/bin/env python3
"""Do adjacent caption ROWS ever touch? Measured in PIXELS, not line boxes.

THIS IS THE FIRST CONSTRAINT THAT BREAKS. A word can swell to ~1.86x (the 2.3
crest times the 2.2.3 pop) and the leading is 1.38, so line-box arithmetic says
rows should overlap constantly -- and they do overlap, as BOXES, long before
any ink does. Box geometry cannot answer this question; only ink can.
`autocwi/overflow.py`'s box check is informational for exactly this reason.

Method, and the method is the durable part:
  * screenshot the live stage densely (0.45 s apart is enough to catch crests),
  * threshold the ink and project it onto the y axis,
  * split into BANDS of lit rows -- one band per caption row,
  * report the minimum vertical gap between adjacent bands over the whole run.

Re-run after ANY change to `voice_scale_range`, the character-wave amplitude,
`hold_lift_em`, `character_wave_falloff`, `weight_range` (bolder ink is taller
as well as wider) or the row density.
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

import numpy as np
from PIL import Image
from websockets.sync.client import connect


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--port", type=int, default=9226)
    ap.add_argument("--window", default="1440,900")
    ap.add_argument("--shots", type=int, default=60)
    ap.add_argument("--interval", type=float, default=0.45)
    ap.add_argument("--warmup", type=float, default=10.0)
    ap.add_argument("--min-gap-px", type=float, default=4.0)
    args = ap.parse_args()

    chrome = subprocess.Popen([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--headless=new", "--disable-gpu", f"--remote-debugging-port={args.port}",
        f"--window-size={args.window}", args.url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    time.sleep(args.warmup)
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{args.port}/json"))
    ws = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")

    counter = [0]

    def cmd(sock, method, **params):
        counter[0] += 1
        sock.send(json.dumps({"id": counter[0], "method": method, "params": params}))
        while True:
            msg = json.loads(sock.recv())
            if msg.get("id") == counter[0]:
                return msg.get("result", {})

    BOX = """(()=>{const s=document.querySelector('.caption-stage')
      ||document.querySelector('.caption-feed'); if(!s) return null;
      const b=s.getBoundingClientRect();
      const bg=getComputedStyle(document.documentElement)
        .getPropertyValue('--stage-bg')||'';
      return {x:b.x,y:b.y,w:b.width,h:b.height,bg:bg.trim()};})()"""

    gaps: list[tuple[float, int, int]] = []
    rows_seen: list[int] = []
    with connect(ws, max_size=None) as sock:
        cmd(sock, "Runtime.enable")
        box = cmd(sock, "Runtime.evaluate", expression=BOX,
                  returnByValue=True).get("result", {}).get("value")
        if not box:
            print("no caption stage on the page — is the sample running?")
            chrome.kill()
            return 1
        for _ in range(args.shots):
            shot = cmd(sock, "Page.captureScreenshot", format="png")
            if not shot.get("data"):
                time.sleep(args.interval)
                continue
            im = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
            scale = im.width / float(args.window.split(",")[0])
            crop = im.crop((
                int(box["x"] * scale), int(box["y"] * scale),
                int((box["x"] + box["w"]) * scale),
                int((box["y"] + box["h"]) * scale)))
            a = np.asarray(crop).astype(np.int16)
            # The stage is themed; take ink as whatever differs from the modal
            # background colour, so this works on the light stage and the dark.
            flat = a.reshape(-1, 3)
            bg = np.median(flat, axis=0)
            ink = (np.abs(a - bg).sum(axis=2) > 90)
            lit = ink.sum(axis=1)
            # A row of text lights many columns; antialiasing lights a few.
            on = lit > max(2, int(0.004 * ink.shape[1]))
            bands, start = [], None
            for y, v in enumerate(on):
                if v and start is None:
                    start = y
                elif not v and start is not None:
                    if y - start >= 3:
                        bands.append((start, y))
                    start = None
            if start is not None and len(on) - start >= 3:
                bands.append((start, len(on)))
            rows_seen.append(len(bands))
            for i in range(1, len(bands)):
                gap = (bands[i][0] - bands[i - 1][1]) / scale
                gaps.append((gap, bands[i - 1][1], bands[i][0]))
            time.sleep(args.interval)
    chrome.kill()

    if not gaps:
        print("no adjacent row pairs were captured — nothing to conclude")
        return 1
    values = sorted(g for g, _, _ in gaps)
    worst = values[0]
    median = values[len(values) // 2]
    under = [g for g in values if g < args.min_gap_px]
    print(f"{len(gaps)} adjacent row-pairs over {len(rows_seen)} frames "
          f"({min(rows_seen)}–{max(rows_seen)} rows per frame)")
    print(f"  minimum gap between adjacent rows : {worst:.1f}px")
    print(f"  median gap                        : {median:.1f}px")
    print(f"  pairs under {args.min_gap_px:.0f}px                  : {len(under)}")
    if worst <= 0:
        print("\nFAIL: adjacent rows' ink is touching.")
        return 1
    if under:
        print(f"\nWARN: {len(under)} pairs closer than {args.min_gap_px:.0f}px.")
        return 0
    print("\nPASS: adjacent rows never come within "
          f"{args.min_gap_px:.0f}px of each other.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
