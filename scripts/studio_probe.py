"""Read the Next studio's live motion metrics out of headless Chrome.

`live_render_probe.py` covers the LEGACY renderer via its `document.title` +
`--dump-dom` trick. That cannot work here: `--dump-dom` serializes at the load
event, before hydration and before any SSE word, returning essentially the raw
`web/out/index.html` shell. So this drives CDP and calls
`window.__cwiStudio.report()` on a real, connected page, sampling over time.

THE HEADLINE NUMBER IS `readAheadMs`. CWI 2.2.1 wants the line legible in white
before it is spoken, and the studio delivers that by running its playhead
behind the acoustic clock. Read-ahead should settle near
`read_ahead_delay_s - recognizer latency`. A value at or near zero means
captions are being coloured the instant they arrive -- the page may look fine
and still not be implementing the design system.

It also reads the DOM directly, because "how many words are currently white"
is the thing a viewer actually sees and no counter can stand in for it.

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


def _configured_read_ahead_ms() -> float:
    """The delay from config.yaml, so the probe cannot drift from it."""
    try:
        import yaml
        root = Path(__file__).resolve().parent.parent
        cfg = yaml.safe_load((root / "config.yaml").read_text())
        return float(cfg["display"]["read_ahead_delay_s"]) * 1000
    except Exception:
        return 2500.0


# Counting white words is a DOM question, not a counter question: read-ahead is
# defined by what the viewer can see, and the colour is produced by a CSS
# animation the JavaScript never observes.
DOM_PHASES = r"""
(() => {
  const words = [...document.querySelectorAll('.caption-word')];
  let readAhead = 0, moving = 0;
  const shell = document.querySelector('.studio-shell');
  const ink = shell
    ? getComputedStyle(shell).getPropertyValue('--read-ahead-color').trim()
    : '#FFFFFF';
  const probe = document.createElement('span');
  probe.style.color = ink;
  document.body.appendChild(probe);
  const target = getComputedStyle(probe).color;
  probe.remove();
  for (const word of words) {
    /* READ THE CHARACTER, NOT THE WORD. The 2.2.2 colour turn moved down to
       `.caption-character` on 2026-08-01 (the wipe crosses a word letter by
       letter), so `.caption-word` no longer carries the animated colour at
       all -- it reports whatever it inherits. Measuring the parent made this
       counter read 0 read-ahead words in every sample of every run, which
       looks exactly like "CWI 2.2.1 is not being delivered" and is instead
       the probe looking at the wrong element. */
    const glyphInk = word.querySelector('.caption-character')
      || word.querySelector('.word-ink');
    if (glyphInk && getComputedStyle(glyphInk).color === target) readAhead += 1;
    const glyph = word.querySelector('.word-glyph');
    if (!glyph) continue;
    const transform = getComputedStyle(glyph).transform;
    if (transform === 'none') continue;
    const matrix = new DOMMatrixReadOnly(transform);
    if (Math.abs(matrix.a - 1) > 0.002 || Math.abs(matrix.f) > 0.5) moving += 1;
  }
  return JSON.stringify({
    domWords: words.length,
    domReadAhead: readAhead,
    domMoving: moving,
    domUnarmed: words.filter((w) => !w.dataset.armed).length,
  });
})()
"""


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
            # Skip unsolicited events until this request's reply arrives.
            while True:
                reply = json.loads(socket.recv())
                if reply.get("id") == message_id:
                    return reply.get("result", {}).get("result", {}).get("value")

        for _ in range(samples):
            payload = evaluate(
                "JSON.stringify(window.__cwiStudio "
                "? window.__cwiStudio.report() : null)"
            )
            if payload:
                try:
                    report = json.loads(payload)
                except (TypeError, ValueError):
                    report = None
                if report:
                    dom = evaluate(DOM_PHASES)
                    if dom:
                        try:
                            report.update(json.loads(dom))
                        except (TypeError, ValueError):
                            pass
                    collected.append(report)
            time.sleep(interval_s)
    return collected


def summarize(reports: list[dict]) -> None:
    if not reports:
        raise SystemExit(
            "no reports captured -- is a live server running on the given URL?"
        )
    started = [r for r in reports if r.get("clockStarted")]
    if not started:
        raise SystemExit(
            "the acoustic clock never started: no `level` event carrying `t` "
            "reached the page, so nothing can be presented."
        )
    final = started[-1]

    print(f"\nsamples: {len(reports)} ({len(started)} with a running clock)"
          f"   connection: {final.get('connection')}")
    print(f"words: {final.get('words')}   visible: {final.get('visible')}"
          f"   scheduled: {final.get('scheduledWords')}")

    # Drop the attach transient: a browser joining a running capture inherits
    # history, and its first samples describe the backlog, not the steady state.
    steady = started[len(started) // 3:] or started
    read_ahead = sorted(r.get("readAheadMs", 0) for r in steady)
    median = read_ahead[len(read_ahead) // 2]
    configured = _configured_read_ahead_ms()

    print("\nread-ahead (CWI 2.2.1) -- recognized text ahead of the colour")
    print(f"  configured delay              {configured:.0f} ms")
    print(f"  delivered read-ahead, median  {median:.0f} ms")
    print(f"  delivered read-ahead, min     {min(read_ahead):.0f} ms")
    white = sorted(r.get("domReadAhead", 0) for r in steady)
    ahead = sorted(r.get("aheadWords", 0) for r in steady)
    print(f"  white words in the DOM, median {white[len(white) // 2]}"
          f"   max {max(white)}")
    print(f"  words past the playhead, median {ahead[len(ahead) // 2]}"
          f"   max {max(ahead)}")
    # The two must agree: a word scheduled in the future is exactly a word the
    # colour turn has not reached, and CSS paints those from the read-ahead
    # keyframe. A gap means the DOM is not showing what the schedule believes.
    gap = max(abs(r.get("domReadAhead", 0) - r.get("aheadWords", 0))
              for r in steady)
    print(f"  worst disagreement            {gap}"
          f"{'' if gap <= 2 else '   <-- INVESTIGATE'}")

    print("\nintegrity (all should be 0)")
    checks = {
        # Every recognized word is on screen -- read-ahead words are the white
        # ones. Nothing is withheld, so these must agree.
        "words not visible": final.get("words", 0) - final.get("visible", 0),
        # A word painted without a schedule would sit in read-ahead forever.
        "unarmed words in DOM": max(
            r.get("domUnarmed", 0) for r in started
        ),
    }
    for name, value in checks.items():
        flag = "" if value == 0 else "   <-- INVESTIGATE"
        print(f"  {name:<30} {value}{flag}")

    print("\nmotion")
    print(f"  peak simultaneous motions     "
          f"{max(r.get('domMoving', 0) for r in started)}")
    print(f"  re-armed (remounted) words    {final.get('rearmedWords')}")
    print(f"  capture restarts (epoch)      {final.get('clockEpoch')}")

    # Words delivered after their own onset had already passed. A cold start or
    # a late-attaching browser produces a burst of these legitimately; a figure
    # that keeps climbing during steady speech means the delay is too short.
    late_growth = final.get("lateWords", 0) - steady[0].get("lateWords", 0)
    print(f"  late words (total / steady)   "
          f"{final.get('lateWords')} / {late_growth}")

    if median < 200:
        print(f"\nFAIL: only {median:.0f} ms of read-ahead. CWI 2.2.1 is not "
              f"being delivered -- raise display.read_ahead_delay_s above the "
              f"recognizer's own latency.")
    else:
        print(f"\nOK: {median:.0f} ms of read-ahead against a "
              f"{configured:.0f} ms delay.")


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
