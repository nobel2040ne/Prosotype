"""Read the Next studio's live motion metrics out of headless Chrome.

`live_render_probe.py` covers the LEGACY renderer via its `document.title` +
`--dump-dom` trick. That cannot work here: `--dump-dom` serializes at the load
event, before hydration and before any SSE word, returning essentially the raw
`web/out/index.html` shell. So this drives CDP and calls
`window.__cwiStudio.report()` on a real, connected page, sampling over time --
`activeMotions` is instantaneous, so only a running maximum can verify the cap.

Start a live server first, then:

    .venv/bin/python -m autocwi live --sample --lang en --loop --no-open &
    .venv/bin/python scripts/studio_probe.py --samples 40
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
DEBUG_PORT = 9223


def _configured_reveal_cap() -> int:
    """The concurrency cap from config.yaml, so the probe cannot drift from it."""
    try:
        import yaml
        root = Path(__file__).resolve().parent.parent
        cfg = yaml.safe_load((root / "config.yaml").read_text())
        return int(cfg["display"]["max_simultaneous_reveals"])
    except Exception:
        return 3


def wait_for_debugger(port: int, timeout_s: float = 25.0) -> str:
    """Return the page target's WebSocket URL once Chrome is listening."""

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
    raise SystemExit(f"Chrome debugger never became ready on :{port} ({last})")


def sample(url: str, samples: int, interval_s: float) -> list[dict]:
    from websockets.sync.client import connect

    collected: list[dict] = []
    with connect(url, max_size=8 * 1024 * 1024) as socket:
        message_id = 0
        for _ in range(samples):
            message_id += 1
            socket.send(json.dumps({
                "id": message_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression":
                        "JSON.stringify(window.__cwiStudio "
                        "? window.__cwiStudio.report() : null)",
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            }))
            # Skip unsolicited events until this request's reply arrives.
            while True:
                reply = json.loads(socket.recv())
                if reply.get("id") == message_id:
                    break
            payload = (
                reply.get("result", {}).get("result", {}).get("value")
            )
            if payload:
                try:
                    report = json.loads(payload)
                except (TypeError, ValueError):
                    report = None
                if report:
                    collected.append(report)
            time.sleep(interval_s)
    return collected


def summarize(reports: list[dict]) -> None:
    if not reports:
        raise SystemExit(
            "no reports captured -- is a live server running on the given URL?"
        )
    final = reports[-1]
    peaks = {
        "maxActiveMotions": max(r.get("maxActiveMotions", 0) for r in reports),
        "activeMotions (observed peak)": max(
            r.get("activeMotions", 0) for r in reports
        ),
        "pendingReveals (peak)": max(r.get("pendingReveals", 0) for r in reports),
        "maxPresentationBacklogMs": max(
            r.get("maxPresentationBacklogMs", 0) for r in reports
        ),
    }
    print(f"\nsamples: {len(reports)}   connection: {final.get('connection')}")
    print(f"words: {final.get('words')}   visible: {final.get('visible')}")
    print("\npeaks over the run")
    for name, value in peaks.items():
        print(f"  {name:<32} {value}")

    print("\nmotion integrity (all should be 0)")
    for name in ("motionsWithoutPaint", "abortedUnpaintedMotions",
                 "freshWordsWithoutMotion"):
        value = max(r.get(name, 0) for r in reports)
        flag = "" if value == 0 else "   <-- INVESTIGATE"
        print(f"  {name:<32} {value}{flag}")

    print("\nreveal / clock")
    for name in ("motionStarts", "motionPaintStarts", "adaptiveMotionStarts",
                 "minimumMotionDurationMs"):
        print(f"  {name:<32} {final.get(name)}")

    # The cap is config (display.max_simultaneous_reveals), not a constant --
    # it is the caption's throughput ceiling, so it moves when the lag does.
    limit = _configured_reveal_cap()
    cap = peaks["maxActiveMotions"]
    if cap > limit:
        print(f"\nFAIL: {cap} simultaneous motions — the cap is {limit}.")
    else:
        print(f"\nOK: peak simultaneous motions {cap} (cap {limit}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7337/")
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--port", type=int, default=DEBUG_PORT)
    parser.add_argument("--window", default="1440,900")
    args = parser.parse_args()

    if not CHROME.is_file():
        raise SystemExit(f"Chrome not found at {CHROME}")

    profile = Path(f"/tmp/cwi-studio-probe-{args.port}")
    chrome = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile}",
            f"--window-size={args.window}",
            "--no-first-run",
            "--no-default-browser-check",
            args.url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        socket_url = wait_for_debugger(args.port)
        print(f"attached to {args.url}; sampling {args.samples}x "
              f"every {args.interval}s")
        reports = sample(socket_url, args.samples, args.interval)
        summarize(reports)
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()


if __name__ == "__main__":
    sys.exit(main())
