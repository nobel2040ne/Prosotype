#!/usr/bin/env python3
"""Does every character of a settled word carry ONE colour?

CWI 2.1 makes colour the speaker signal, so a word drawn in two colours makes
two claims about who spoke it. The 2.2.2 turn is a WIPE, so a word is
legitimately two-coloured while the boundary is crossing it -- for `sweepMs`
(bounded by `word_motion_max_duration_s`, 1.05 s) and no longer. A word still
two-coloured seconds after its turn is a defect.

WHY THIS EXISTS. `studio_probe.py` counts read-ahead words by asking whether a
word's FIRST character is still in read-ahead ink; it cannot see a word whose
first character turned and whose last one never did. That is exactly the shape
of the defect it missed: `--char-turn-delay` is written imperatively once per
word, and characters appended after that -- endpoint punctuation
("animation" -> "animation,"), a respelling that lengthens -- kept the
stylesheet's 600000ms default and sat in `word-color-turn`'s `backwards` fill,
i.e. read-ahead ink, for ten minutes. MEASURED on `--sample` before the fix:
23 of 137 settled words, each mixed for the remaining 28-63 s of the capture.
Reported by the user as "some words contain the speaker's color and black
color" -- `#6e6e73` is `read_ahead.color_light`.

THE VERDICT IS THE LAST SAMPLE, NOT THE WORST ONE. Mid-wipe words are the
design working; the question is whether they RESOLVE. So this scores the final
sample (long after the sample clip ends, nothing can still be moving) and also
reports how many consecutive samples any one word stayed mixed -- 1 is a wipe,
more is a word that stopped mid-turn.

Usage:
    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    scripts/caption_color_probe.py
    scripts/caption_color_probe.py --broken   # ...and prove it can go red
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import time
import urllib.request

# Its OWN port. `studio_probe.py` holds 9223 and `baseline_probe.py` 9224, and
# a leftover browser on a shared port is attached to SILENTLY: the second run
# reads a closed page, sees an empty stage, and reports "the capture never
# filled it" -- which looks like a live-server problem and is not one.
DEBUG_PORT = 9225

# Per sample: every word on the Stage, and the set of colours its characters
# are actually painted in. `.character-sizer` is the hidden in-flow copy that
# owns the row's width and carries no ink, so only `.caption-character` counts.
DOM = r"""
(() => {
  const stage = document.querySelector('.caption-stage:not(.is-transcript)')
    || document;
  const rows = Array.from(stage.querySelectorAll('.caption-word')).map((word) => {
    /* WIDE SCRIPT TAKES A DIFFERENT PATH, AND SO MUST THIS CHECK.
       A Hangul word does not turn per glyph -- its base ink layer stays
       read-ahead white for life and a clipped overlay in the speaker colour is
       swept across it, because a per-glyph step moves the boundary 0.91em in
       Hangul against 0.43em in Latin and 46% of Korean words have <=2 steps.
       So reading `.caption-character` colours here would see white AND the
       speaker colour on every wide word and call all of them two-coloured --
       measured, it reported 135 false positives the first time it ran against
       the new path.
       The defect this probe exists for is a character left in read-ahead ink
       forever. On the wide path its exact analogue is a SETTLED word whose
       wipe never reached 100%, so that is what gets scored: `colors` carries
       the overlay's colour alone, and `wipe` carries the coverage. */
    const turned = word.querySelector('.word-ink-turned');
    const wide = word.getAttribute('data-script') === 'wide';
    const chars = Array.from(
      wide && turned
        ? turned.querySelectorAll('.caption-character')
        : word.querySelectorAll('.caption-character'));
    const colors = chars.map((c) => getComputedStyle(c).color);
    const wipe = turned
      ? parseFloat(getComputedStyle(turned).getPropertyValue('--wipe')) : null;
    return {
      wide,
      wipe: Number.isFinite(wipe) ? wipe : null,
      id: word.getAttribute('data-word-id') || '',
      text: (word.querySelector('.word-glyph') || {getAttribute: () => ''})
        .getAttribute('aria-label') || '',
      status: word.getAttribute('data-status') || '',
      armed: word.dataset.armed || '',
      chars: chars.length,
      colors: Array.from(new Set(colors)),
      // A span the arming effect never reached. It is the mechanism behind
      // every mixed word measured so far, so report it beside the symptom.
      unarmed: Array.from(word.querySelectorAll('.caption-character')).filter(
        (c) => !c.style.getPropertyValue('--char-turn-delay')).length,
    };
  });
  return JSON.stringify({rows});
})()
"""

# Re-impose the defect: strip the inline delay from each word's LAST character,
# which is precisely what an append used to leave behind. The check must go red.
BREAK = r"""
(() => {
  let broke = 0;
  for (const word of document.querySelectorAll('.caption-word')) {
    // Wide script: freeze the sweep part-way, which is the analogue of a
    // character that never got its delay -- part of the word never turns.
    const turned = word.querySelector('.word-ink-turned');
    if (turned) {
      turned.style.setProperty('--wipe', '55%');
      turned.style.animation = 'none';
      broke += 1;
      continue;
    }
    const chars = word.querySelectorAll('.caption-character');
    if (chars.length < 2) continue;
    const last = chars[chars.length - 1];
    if (!last.style.getPropertyValue('--char-turn-delay')) continue;
    last.style.removeProperty('--char-turn-delay');
    broke += 1;
  }
  return String(broke);
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
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target["webSocketDebuggerUrl"]
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.3)
    raise SystemExit(f"Chrome debugger never became ready on :{port} ({last})")


def capture(url: str, window: str, port: int, settle_s: float,
            interval_s: float, broken: bool) -> list[dict]:
    chrome = subprocess.Popen([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--headless=new", "--disable-gpu", f"--window-size={window}",
        f"--remote-debugging-port={port}",
        "--user-data-dir=/tmp/cwi-caption-color-probe", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        from websockets.sync.client import connect

        samples: list[dict] = []
        with connect(wait_for_debugger(port), max_size=32 * 1024 * 1024) as socket:
            state = {"id": 0}

            def evaluate(expression: str):
                state["id"] += 1
                message_id = state["id"]
                socket.send(json.dumps({
                    "id": message_id,
                    "method": "Runtime.evaluate",
                    "params": {"expression": expression,
                               "returnByValue": True, "awaitPromise": False},
                }))
                while True:
                    reply = json.loads(socket.recv())
                    if reply.get("id") == message_id:
                        return (reply.get("result", {})
                                .get("result", {}).get("value"))

            # Never trust the attach: a browser on this port that is showing
            # something else is the failure mode above, and it is silent.
            here = evaluate("location.href") or ""
            if not str(here).startswith(url.rstrip("/")):
                raise SystemExit(
                    f"attached to a browser showing {here!r}, not {url} -- a "
                    f"leftover Chrome is holding :{port}. Kill it and re-run."
                )

            deadline = time.time() + settle_s
            while time.time() < deadline:
                if broken:
                    evaluate(BREAK)
                payload = evaluate(DOM)
                if payload:
                    samples.append(json.loads(payload))
                time.sleep(interval_s)
        return samples
    finally:
        chrome.terminate()


def report(samples: list[dict], interval_s: float, lingering_n: int) -> int:
    if not samples:
        raise SystemExit("no samples -- is a live server running on that URL?")

    # THE VERDICT SAMPLE IS THE LAST FULL ONE, NOT THE LAST ONE. A page whose
    # SSE stream reconnects after the clip has finished gets the words back but
    # no `level` event, so `clockStarted` stays false and the stage renders
    # EMPTY -- measured, `__cwiStudio.report()` said words 170 / visible 170
    # with zero `.caption-word` in the DOM. Reading that as the verdict reports
    # "the capture never filled the stage" on a perfectly good run.
    full = [s["rows"] for s in samples if len(s["rows"]) >= 8]
    if not full:
        raise SystemExit(
            "the stage never carried 8 words in any sample -- nothing to "
            "conclude. Attach while the capture is running (start the probe "
            "within a few seconds of the server) and give --settle the clip "
            "length."
        )
    final = full[-1]

    # Consecutive samples a word spent two-coloured. ONE is the wipe crossing
    # it, which is the design; the sweep is bounded by
    # `word_motion_max_duration_s` (1.05 s), so anything past a couple of
    # samples is a word that stopped mid-turn.
    def unfinished(row: dict) -> bool:
        """Is this word showing more than one colour, on either path?

        Narrow: its characters are painted in more than one colour.
        Wide: the base layer is read-ahead by design and the OVERLAY carries
        the speaker colour, so the equivalent question is whether the sweep has
        finished covering the word. `--wipe` under 100% means part of it is
        still read-ahead ink -- mid-sweep for a moment, stuck if it persists.
        """
        if row.get("wide"):
            wipe = row.get("wipe")
            if wipe is None:
                return False
            # MATCH THE NARROW SEMANTICS EXACTLY. There, a word every one of
            # whose characters is still read-ahead ink counts as ONE colour and
            # is not a defect -- that is just a word the playhead has not
            # reached, which CWI 2.2.1 requires to exist. The wide analogue is
            # `--wipe: 0%`. Only a PARTIAL sweep is two-coloured.
            return 0.5 < wipe < 99.5
        return len(row["colors"]) > 1

    run = collections.Counter()
    longest = collections.Counter()
    for snap in samples:
        seen = set()
        for row in snap["rows"]:
            if unfinished(row):
                seen.add(row["id"])
                run[row["id"]] += 1
                longest[row["id"]] = max(longest[row["id"]], run[row["id"]])
        for word_id in list(run):
            if word_id not in seen:
                run[word_id] = 0

    # A SINGLE MID-SWEEP SAMPLE IS NOT EVIDENCE ON THE WIDE PATH. The narrow
    # turn is `--color-turn-ms` (90 ms), so sampling one in progress at a 1 s
    # interval is rare and a mixed verdict sample really does mean stopped. The
    # wide sweep deliberately spans the word's whole spoken span (up to
    # `word_motion_max_duration_s`, 1.05 s), so catching one in progress is
    # ordinary -- measured, one word per run. For wide words the real defect is
    # therefore PERSISTENCE, which `stuck` already measures; scoring them here
    # too would fail a healthy capture on timing alone.
    mixed = [r for r in final if not r.get("wide") and unfinished(r)]
    unarmed = [r for r in final if r["unarmed"] > 0]
    stuck = sorted(n for n in longest.values() if n >= lingering_n)

    print(f"\nsamples {len(samples)} at {interval_s:.2f}s   "
          f"{len(full)} with a full stage   verdict sample {len(final)} words")
    print(f"  words ever seen mid-wipe          {len(longest)}")
    print(f"  ...mixed for >= {lingering_n} samples in a row  {len(stuck)}"
          f"   longest {max(longest.values()) if longest else 0}")
    print(f"  SETTLED words with >1 colour      {len(mixed)}")
    print(f"  words with an unarmed character   {len(unarmed)}")
    for row in (mixed or unarmed)[:12]:
        wipe = f" wipe={row['wipe']:.0f}%" if row.get("wipe") is not None else ""
        print(f"    {row['text']!r:>22} chars={row['chars']}{wipe} "
              f"unarmed={row['unarmed']} status={row['status']} "
              f"armed={row['armed']} {row['colors']}")

    ok = not mixed and not unarmed and not stuck
    print(f"\n{'PASS' if ok else 'FAIL'}: every settled word carries one colour. "
          f"{len(mixed)} two-coloured at rest, {len(unarmed)} carrying an "
          f"unarmed character, {len(stuck)} stuck mid-wipe (before the "
          f"2026-08-06 fix: 23, 23 and 23 of 137).")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7337/")
    ap.add_argument("--port", type=int, default=DEBUG_PORT)
    ap.add_argument("--window", default="1440,900")
    # Long enough for the bundled sample to finish AND to leave the last word
    # well behind the playhead; a short run measures words still mid-wipe.
    ap.add_argument("--settle", type=float, default=80.0)
    ap.add_argument("--interval", type=float, default=1.0)
    # A wipe crosses a word in at most `word_motion_max_duration_s` (1.05 s),
    # so at the default 1 s interval two consecutive mixed samples is already
    # generous and three cannot be a wipe.
    ap.add_argument("--lingering-samples", type=int, default=3)
    ap.add_argument("--broken", action="store_true",
                    help="strip each word's last delay; the probe must FAIL")
    args = ap.parse_args()

    samples = capture(args.url, args.window, args.port, args.settle,
                      args.interval, args.broken)
    raise SystemExit(report(samples, args.interval, args.lingering_samples))


if __name__ == "__main__":
    main()
