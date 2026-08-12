"""Concatenate the derived reference specs into one united demo.

    .venv/bin/python scripts/build_demo.py

Reads ``assets/reference_specs/{character_identification,synchronization,
intonation}.json`` -- each already DERIVED from its recording, so nothing here
is hand-authored -- and writes ``assets/reference_specs/demo.json``: every
caption from all three recordings, in the order the site presents them, on one
timeline.

Section order follows the site: Character Identification, then
Synchronization, then Intonation. Each source spec keeps its own word timings
and its own measured prosody; only the time origin is shifted, and each
section's first word carries `line_break` so the sections cannot merge.

Speakers are renamed per source (`CI_S1`, `SY_S1`, ...) so two sections cannot
collide on one name, and each keeps the palette colour its own recording used.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autocwi.config import load_config          # noqa: E402
from autocwi.schema import CaptionSpec, load_model, save_model  # noqa: E402

# (file stem, short speaker prefix) in the order the site presents them
SECTIONS = [
    ("character_identification", "CI"),
    ("synchronization", "SY"),
    ("intonation", "IN"),
]
SECTION_GAP_S = 1.6


def main() -> None:
    cfg = load_config()
    specs_dir = ROOT / "assets" / "reference_specs"

    words: list[dict] = []
    speakers: dict[str, dict] = {}
    cursor = 0.0
    for stem, prefix in SECTIONS:
        path = specs_dir / f"{stem}.json"
        if not path.exists():
            print(f"  skipping {stem}: not derived yet")
            continue
        spec = load_model(CaptionSpec, path).model_dump(exclude_none=True)
        base = min(w["start"] for w in spec["words"])
        shift = cursor - base
        for i, w in enumerate(spec["words"]):
            w = dict(w)
            w["speaker"] = f"{prefix}_{w['speaker']}"
            w["start"] = round(w["start"] + shift, 3)
            w["end"] = round(w["end"] + shift, 3)
            # Motion is on the same absolute clock as start/end.
            if w.get("motion"):
                w["motion"] = dict(w["motion"])
                w["motion"]["t0"] = round(w["motion"]["t0"] + shift, 3)
            if i == 0:
                w["line_break"] = True
            words.append(w)
        for name, entry in spec["speakers"].items():
            speakers[f"{prefix}_{name}"] = entry
        span = max(w["end"] for w in spec["words"]) - base
        print(f"  {stem:26s} {len(spec['words']):3d} words, {span:5.2f}s "
              f"-> starts at {cursor:5.2f}s")
        cursor += span + SECTION_GAP_S

    if not words:
        raise SystemExit("no derived specs found; run derive_reference_spec.py first")

    demo = {
        "version": "1.0",
        "media": {"path": "reference demo", "fps": 30.0,
                  "duration": round(words[-1]["end"] + 1.5, 3)},
        "speakers": speakers,
        "words": words,
        "mapping": cfg["mapping"],
    }
    out = specs_dir / "demo.json"
    # Validate before writing: a demo that fails the contract is worse than none
    save_model(CaptionSpec.model_validate(demo), out)
    lines = sum(1 for w in words if w.get("line_break")) or 1
    print(f"\nwrote {out}")
    print(f"  {len(words)} words, {lines} caption lines, "
          f"{len(speakers)} speakers, {demo['media']['duration']}s")


if __name__ == "__main__":
    main()
