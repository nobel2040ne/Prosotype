#!/usr/bin/env python3
"""What colour does a word paint FIRST, and is it the colour it keeps?

CWI 2.1 is the attribution pillar: a word is drawn in its speaker's colour.
Getting there eventually is not the same as getting there on time -- a word that
paints in the narrator's yellow and turns orange a second later has shown the
viewer the wrong speaker for a second, which is precisely the information the
pillar exists to carry.

THIS IS NOT SCORED FROM ``live_events.jsonl``. That file holds durable
``type: "word"`` records only, so every word in it already carries its settled
speaker and the churn measures 0%. The studio paints from ``hypothesis``,
``cue`` and ``commit`` too (see ``caption-store.ts``), so the only honest
measurement subscribes to the SSE stream and scores the FIRST speaker a
``word_id`` was ever published with.

    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    .venv/bin/python scripts/speaker_probe.py

Run it against a config with ``live.speaker_attribution.debug: true`` and it
additionally reports the native Sortformer slot each word was published under,
which is the only way to separate "the model never separated these speakers"
from "the model separated them and our mapping lost it". Those need opposite
fixes, and this project has already spent a round implementing the wrong one.
"""

from __future__ import annotations

import argparse
import collections
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

# Every SSE type the studio reducer turns into painted words. `verification`
# carries corrections, not first paints, but is included so a correction that
# arrives only at verification is still attributed to the right stage.
PAINTING_TYPES = {"hypothesis", "cue", "commit", "word", "verification"}


def iter_events(url: str, idle_timeout_s: float, hard_timeout_s: float):
    """Yield decoded SSE payloads until the stream goes idle.

    A SOCKET TIMEOUT IS NOT THE END OF THE STREAM, and treating it as one makes
    this unusable: the server opens its HTTP port FIRST and warms the models on
    silence (~7.6 s cold), so a probe that attaches promptly -- which is the
    only way to catch the first words -- sees nothing at all for several
    seconds.

    BUT A TIMED-OUT `http.client` RESPONSE CANNOT BE RESUMED EITHER -- the next
    read raises `OSError: cannot read from timed out object`, so "short socket
    timeout, decide on the deadlines here" does not work. The reader therefore
    blocks with no timeout at all on a daemon thread, and the deadlines are
    enforced on the queue instead. A reader still blocked at exit costs nothing
    because the thread is a daemon.
    """

    payloads: queue.Queue = queue.Queue()

    def read() -> None:
        try:
            request = urllib.request.Request(
                url, headers={"Accept": "text/event-stream"}
            )
            with urllib.request.urlopen(request) as stream:
                for raw in stream:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        payloads.put(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:  # surfaced to the caller as a sentinel
            payloads.put({"type": "__error__", "message": str(exc)})
        payloads.put({"type": "__eof__"})

    threading.Thread(target=read, name="sse-reader", daemon=True).start()

    started = time.monotonic()
    last_payload = started
    while True:
        now = time.monotonic()
        if now - started > hard_timeout_s:
            return
        if now - last_payload > idle_timeout_s:
            # `level` keeps ticking after the audio source is exhausted, so
            # silence on every OTHER lane is what "finished" looks like.
            return
        try:
            payload = payloads.get(timeout=0.5)
        except queue.Empty:
            continue
        kind = payload.get("type")
        if kind == "__eof__":
            return
        if kind == "__error__":
            print(f"stream error: {payload['message']}", file=sys.stderr)
            return
        if kind != "level":
            last_payload = time.monotonic()
        yield payload


def words_in(payload: dict):
    """Every (word_id, record) this payload paints, whatever its shape."""

    kind = payload.get("type")
    if kind not in PAINTING_TYPES:
        return
    if isinstance(payload.get("words"), list):
        for word in payload["words"]:
            if isinstance(word, dict) and word.get("word_id"):
                yield str(word["word_id"]), word
        return
    if payload.get("word_id"):
        yield str(payload["word_id"]), payload


def native_slot(record: dict):
    """The Sortformer slot in the debug reason, when debug is enabled."""

    debug = record.get("speaker_debug")
    reason = (debug or {}).get("reason") if isinstance(debug, dict) else None
    if not reason or "native slot " not in reason:
        return None
    tail = reason.split("native slot ", 1)[1]
    digits = ""
    for character in tail:
        if character.isdigit():
            digits += character
        else:
            break
    return int(digits) if digits else None


def collect(url: str, idle_timeout_s: float, hard_timeout_s: float) -> dict:
    """Record every paint, with the wall clock and the acoustic clock beside it.

    THE WALL CLOCK IS NOT OPTIONAL, because the studio does not paint a word
    when it arrives -- it paints it when the PLAYHEAD reaches its onset, which
    is `display.read_ahead_delay_s` later. A correction that lands inside that
    window is never seen by anyone. Scoring arrival order alone answers a
    question about the event stream; scoring it against the playhead answers
    the question about the VIEWER, and those are different numbers.

    The acoustic clock is recovered from `level.t` exactly as
    `caption-clock.ts` does: a max filter, because transport jitter can only
    ever make a sample look late.
    """

    # Insertion-ordered: first key seen is the first word published.
    history: dict[str, list[dict]] = collections.OrderedDict()
    slots: dict[str, list[int]] = collections.defaultdict(list)
    clock_offset = None  # acoustic_s - monotonic_s

    for payload in iter_events(url, idle_timeout_s, hard_timeout_s):
        now = time.monotonic()
        if payload.get("type") == "level":
            acoustic = payload.get("t")
            if isinstance(acoustic, (int, float)):
                sample = float(acoustic) - now
                if clock_offset is None or sample > clock_offset:
                    clock_offset = sample
            continue
        for word_id, record in words_in(payload):
            history.setdefault(word_id, []).append({
                "type": payload.get("type"),
                "speaker": record.get("speaker"),
                "status": record.get("speaker_status"),
                "t": record.get("t"),
                "text": record.get("text"),
                "at": now,
                "clock_offset": clock_offset,
            })
            slot = native_slot(record)
            if slot is not None and record.get("speaker"):
                slots[record["speaker"]].append(slot)
    return {"history": history, "slots": slots}


def colour_at_turn(
    events: list[dict],
    read_ahead_s: float,
    min_read_ahead_s: float,
):
    """The speaker the viewer actually sees when this word turns colour.

    Two terms, both of which `scheduleWord` applies and both of which push the
    turn LATER -- i.e. both give a late correction more time to land before
    anyone sees the wrong colour:

    * the playhead runs `read_ahead_s` behind the acoustic clock, so the turn
      is at wall time `t - clock_offset + read_ahead_s`;
    * and a word may not turn until it has been on screen `min_read_ahead_s`,
      whenever it arrived, which is the per-WORD floor that exists because the
      recogniser delivers in bursts.

    Returns the last speaker published at or before that moment, or None when
    the word had no colour of its own yet.
    """

    onset = None
    offset = None
    for event in events:
        if event.get("t") is not None and event.get("clock_offset") is not None:
            onset = float(event["t"])
            offset = float(event["clock_offset"])
            break
    if onset is None or offset is None:
        return None, None
    turn_at = max(
        onset - offset + read_ahead_s,
        events[0]["at"] + min_read_ahead_s,
    )
    seen = None
    for event in events:
        if event["at"] > turn_at:
            break
        if event.get("speaker"):
            seen = event["speaker"]
    return seen, turn_at


def report(collected: dict, read_ahead_s: float, min_read_ahead_s: float) -> int:
    history = collected["history"]
    if not history:
        print("no words seen -- is the server running and streaming?")
        return 1

    first_paint_wrong = 0
    scored = 0
    never_attributed = 0
    flips = []
    final_order = []
    turn_wrong = 0
    turn_neutral = 0
    turn_scored = 0

    for word_id, events in history.items():
        attributed = [e for e in events if e.get("speaker")]
        if not attributed:
            never_attributed += 1
            continue
        first = attributed[0]
        last = attributed[-1]
        final_order.append((word_id, last["speaker"], last.get("text")))
        scored += 1
        if first["speaker"] != last["speaker"]:
            first_paint_wrong += 1
            flips.append((
                word_id,
                last.get("text") or "",
                first["speaker"],
                first.get("type"),
                last["speaker"],
                last.get("type"),
            ))
        # ...and what the VIEWER sees, which is the number that matters.
        seen, turn_at = colour_at_turn(events, read_ahead_s, min_read_ahead_s)
        if turn_at is None:
            continue
        turn_scored += 1
        if seen is None:
            turn_neutral += 1
        elif seen != last["speaker"]:
            turn_wrong += 1

    switches = sum(
        1 for a, b in zip(final_order, final_order[1:]) if a[1] != b[1]
    )
    speakers = collections.Counter(speaker for _, speaker, _ in final_order)

    print("=" * 62)
    print("FIRST PAINT vs SETTLED SPEAKER")
    print("=" * 62)
    print(f"  words published            {len(history)}")
    print(f"  ...ever attributed         {scored}")
    print(f"  ...never attributed        {never_attributed}")
    if scored:
        pct = 100.0 * first_paint_wrong / scored
        print(f"  FIRST PAINT WRONG          {first_paint_wrong}/{scored} = {pct:.1f}%")
    print()
    print("-" * 62)
    print(
        f"WHAT THE VIEWER SEES (playhead {read_ahead_s:.2f}s behind,"
        f" per-word floor {min_read_ahead_s * 1000:.0f}ms)"
    )
    print("-" * 62)
    if turn_scored:
        print(f"  words scored at their turn {turn_scored}")
        print(
            f"  WRONG COLOUR AT THE TURN   {turn_wrong}/{turn_scored}"
            f" = {100.0 * turn_wrong / turn_scored:.1f}%"
        )
        print(
            f"  neutral at the turn        {turn_neutral}/{turn_scored}"
            f" = {100.0 * turn_neutral / turn_scored:.1f}%"
        )
        right = turn_scored - turn_wrong - turn_neutral
        print(
            f"  correct at the turn        {right}/{turn_scored}"
            f" = {100.0 * right / turn_scored:.1f}%"
        )
    else:
        print("  (no clock samples -- cannot place the playhead)")
    print()
    print(f"  distinct settled speakers  {len(speakers)}")
    print(f"  speaker switches           {switches}")
    print(f"  words per speaker          {dict(speakers.most_common())}")

    if flips:
        print()
        print("-" * 62)
        print(f"WORDS THAT CHANGED COLOUR (first {min(25, len(flips))} of {len(flips)})")
        print("-" * 62)
        for word_id, text, first, first_type, last, last_type in flips[:25]:
            print(
                f"  {word_id:<12} {text[:22]:<24}"
                f" {first} ({first_type}) -> {last} ({last_type})"
            )

    if collected["slots"]:
        print()
        print("-" * 62)
        print("NATIVE SORTFORMER SLOT -> SPEAKERS PUBLISHED UNDER IT")
        print("-" * 62)
        by_slot: dict[int, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        for speaker, slot_list in collected["slots"].items():
            for slot in slot_list:
                by_slot[slot][speaker] += 1
        for slot in sorted(by_slot):
            listed = ", ".join(
                f"{speaker} x{count}"
                for speaker, count in by_slot[slot].most_common()
            )
            flag = "  <-- REUSED" if len(by_slot[slot]) > 1 else ""
            print(f"  slot {slot}: {listed}{flag}")
    else:
        print()
        print("(no native slot data -- run the server with a config whose")
        print(" live.speaker_attribution.debug is true to get it)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7337/events")
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=12.0,
        help="stop after this long with no word/cue/commit traffic",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=240.0,
        help="hard stop, so a --loop server cannot hang the probe",
    )
    parser.add_argument("--json", default=None, help="also write the raw history here")
    parser.add_argument(
        "--read-ahead-seconds",
        type=float,
        default=None,
        help="override display.read_ahead_delay_s (default: ask the server)",
    )
    args = parser.parse_args()

    read_ahead_s = args.read_ahead_seconds
    min_read_ahead_s = 0.42
    if read_ahead_s is None:
        # The server publishes the value the studio is actually using, so the
        # probe cannot drift from the running configuration.
        config_url = args.url.rsplit("/events", 1)[0] + "/runtime-config.json"
        try:
            with urllib.request.urlopen(config_url, timeout=5) as handle:
                runtime = json.load(handle)
            read_ahead_s = float(runtime.get("readAheadDelayMs", 1750)) / 1000.0
            min_read_ahead_s = float(runtime.get("minReadAheadMs", 420)) / 1000.0
        except Exception:
            read_ahead_s = 1.75
            min_read_ahead_s = 0.42

    try:
        collected = collect(args.url, args.idle_seconds, args.max_seconds)
    except urllib.error.URLError as exc:
        print(f"could not reach {args.url}: {exc}")
        return 1

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(
                {"history": collected["history"], "slots": collected["slots"]},
                handle,
                indent=1,
            )
    return report(collected, read_ahead_s, min_read_ahead_s)


if __name__ == "__main__":
    sys.exit(main())
