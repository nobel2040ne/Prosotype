"""Fetch a FLEURS evaluation slice (one-time download).

FLEURS is CC BY 4.0, covers 102 languages, and is what published Korean WER/CER
numbers are measured against, so a score on it is externally comparable rather
than self-referential. `assets/sample-ko.wav` is already FLEURS ko_kr row 16.

This is a ONE-TIME download in the same category as the model-weight and font
fetches, not runtime inference. Nothing here runs during capture.

    .venv/bin/python scripts/fetch_fleurs.py --lang ko --count 120
    .venv/bin/python scripts/fetch_fleurs.py --lang en --count 120
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASET = "google/fleurs"
CONFIGS = {"ko": "ko_kr", "en": "en_us"}
# The rows endpoint caps a single request at 100.
PAGE = 100

ATTRIBUTION = """\
# Evaluation set: FLEURS

Source: Google FLEURS (`google/fleurs`), split `test`, config `{config}`.
Licence: CC BY 4.0 -- https://creativecommons.org/licenses/by/4.0/
Downloaded: {when}
Rows: {count}

FLEURS is read speech. It is a real, externally comparable benchmark and it
fixes the "no Korean eval set at all" problem, but it is NOT booth audio: it has
no spontaneous speech, no two-speaker turn-taking, and no room noise. Treat a
score here as a floor, not as evidence the system works at the fair. Record real
booth audio and pass it with `--refs` before trusting any A/B for the demo.
"""


def fetch_json(url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.load(response)
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retrying after {type(exc).__name__}: {exc}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_rows(config: str, count: int) -> list[dict]:
    rows: list[dict] = []
    while len(rows) < count:
        query = urllib.parse.urlencode({
            "dataset": DATASET,
            "config": config,
            "split": "test",
            "offset": len(rows),
            "length": min(PAGE, count - len(rows)),
        })
        payload = fetch_json(f"{ROWS_API}?{query}")
        page = payload.get("rows", [])
        if not page:
            break
        rows.extend(page)
        print(f"  {len(rows)}/{count} rows")
    return rows[:count]


def audio_url(row: dict) -> str | None:
    audio = row.get("audio")
    if isinstance(audio, list) and audio:
        return audio[0].get("src")
    if isinstance(audio, dict):
        return audio.get("src")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--count", type=int, default=120,
                        help="rows to fetch (default 120; ~1500+ words, enough "
                             "that one edit no longer moves the score a point)")
    parser.add_argument("--out", default=None, metavar="DIR")
    args = parser.parse_args()

    config = CONFIGS[args.lang]
    out = Path(args.out) if args.out else ROOT / "assets" / f"eval-fleurs-{args.lang}"
    wavs = out / "test_wavs"
    wavs.mkdir(parents=True, exist_ok=True)

    print(f"fetching {args.count} FLEURS rows ({config})")
    rows = fetch_rows(config, args.count)
    if not rows:
        raise SystemExit("no rows returned -- is the datasets-server reachable?")

    lines: list[str] = []
    skipped = 0
    for index, entry in enumerate(rows):
        row = entry.get("row", {})
        # `transcription` is the normalized form; `raw_transcription` keeps
        # punctuation. Score against the normalized one -- punctuation is a
        # formatting choice each recognizer makes differently and would show up
        # as fake errors.
        text = str(row.get("transcription") or "").strip()
        source = audio_url(row)
        if not text or not source:
            skipped += 1
            continue
        name = f"{index:04d}.wav"
        target = wavs / name
        if not target.is_file():
            try:
                with urllib.request.urlopen(source, timeout=60) as response:
                    target.write_bytes(response.read())
            except Exception as exc:
                print(f"  skip {name}: {type(exc).__name__}: {exc}")
                skipped += 1
                continue
        lines.append(f"{name} {text}")
        if (index + 1) % 25 == 0:
            print(f"  downloaded {len(lines)} clips")

    if not lines:
        raise SystemExit("every row failed to download")

    (wavs / "trans.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "SOURCE.md").write_text(
        ATTRIBUTION.format(config=config, count=len(lines),
                           when=time.strftime("%Y-%m-%d")),
        encoding="utf-8",
    )

    units = sum(
        len([c for c in text.split(" ", 1)[1] if not c.isspace()])
        if args.lang == "ko" else len(text.split()) - 1
        for text in lines
    )
    print(f"\nwrote {len(lines)} clips to {out} ({skipped} skipped)")
    print(f"~{units} scored units "
          f"({'characters' if args.lang == 'ko' else 'words'})")
    print(f"\nUse it:\n  .venv/bin/python scripts/benchmark.py --lang {args.lang}")


if __name__ == "__main__":
    sys.exit(main())
