"""THE benchmark. One script, one standard eval set: FLEURS.

There is deliberately only one -- do not add a second. FLEURS (Conneau et al.,
102 languages, CC BY 4.0) is the standard multilingual ASR set, so a score here
is comparable to the literature. Fetch it once with `scripts/fetch_fleurs.py`.

    .venv/bin/python scripts/fetch_fleurs.py --lang ko
    .venv/bin/python scripts/benchmark.py --lang ko
    .venv/bin/python scripts/benchmark.py --lang ko --stress
    .venv/bin/python scripts/benchmark.py --lang en --quiet-sweep   # InputGain guard
    .venv/bin/python scripts/benchmark.py --audio assets/sample.mp4 --lang en

Scoring is text AND word timing: every expressive path here keys off per-word
`start`/`end`, so a backend with better words and worse spans is a downgrade.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import conditions as condition_sets  # noqa: E402
from asr_backends import BACKENDS, TimedWord, Transcript  # noqa: E402

from autocwi.config import load_config  # noqa: E402
from autocwi.scoring import edit_distance, has_digits, scored_units  # noqa: E402

SR = 16_000
DEFAULT_SET = "assets/eval-fleurs-{lang}"


def onset_gaps(words: list[TimedWord]) -> list[float]:
    """Spacing between consecutive word onsets.

    This is what `motion-timing.ts` measures -- median ACOUSTIC onset spacing,
    not decoder arrival spacing -- so a backend whose spans are compressed or
    quantized shows up here even when its text is perfect.
    """

    ordered = sorted(words, key=lambda word: word.start)
    return [
        later.start - earlier.start
        for earlier, later in zip(ordered, ordered[1:])
        if later.start >= earlier.start
    ]


def align_words(left: list[TimedWord], right: list[TimedWord]
                ) -> list[tuple[TimedWord, TimedWord]]:
    """Pair words two backends agree on, by Levenshtein backtrace.

    Only exact text matches pair up: a substitution has no shared onset to
    compare.
    """

    left_keys = [word.text.casefold() for word in left]
    right_keys = [word.text.casefold() for word in right]
    rows, columns = len(left), len(right)
    table = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows + 1):
        table[i][0] = i
    for j in range(columns + 1):
        table[0][j] = j
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            cost = 0 if left_keys[i - 1] == right_keys[j - 1] else 1
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1,
                              table[i - 1][j - 1] + cost)

    pairs = []
    i, j = rows, columns
    while i > 0 and j > 0:
        if (left_keys[i - 1] == right_keys[j - 1]
                and table[i][j] == table[i - 1][j - 1]):
            pairs.append((left[i - 1], right[j - 1]))
            i, j = i - 1, j - 1
        elif table[i][j] == table[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif table[i][j] == table[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def describe(values: list[float]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    median = statistics.median(ordered) * 1000
    low = ordered[int(0.1 * (len(ordered) - 1))] * 1000
    high = ordered[int(0.9 * (len(ordered) - 1))] * 1000
    return f"median {median:.0f}ms (p10 {low:.0f} / p90 {high:.0f})"


def load_eval_set(args) -> tuple[dict[str, str], dict[str, Path], bool]:
    """Return (references, paths, scoring)."""

    if args.audio:
        references, paths = {}, {}
        for raw in args.audio:
            path = Path(raw)
            if not path.is_absolute():
                path = ROOT / path
            if not path.is_file():
                raise SystemExit(f"no such audio file: {path}")
            references[path.name] = ""
            paths[path.name] = path
        return references, paths, False

    refs = Path(args.refs or DEFAULT_SET.format(lang=args.lang))
    if not refs.is_absolute():
        refs = ROOT / refs
    transcript = refs / "test_wavs" / "trans.txt"
    if not transcript.is_file():
        raise SystemExit(
            f"no FLEURS eval set at {transcript}\n"
            "  fetch it once: .venv/bin/python scripts/fetch_fleurs.py "
            f"--lang {args.lang}"
        )
    references, paths = {}, {}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        if " " not in line:
            continue
        name, text = line.split(" ", 1)
        references[name] = text
        paths[name] = refs / "test_wavs" / name
    return references, paths, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=["en", "ko"], default="en")
    parser.add_argument("--refs", default=None, metavar="DIR",
                        help=f"eval set (default {DEFAULT_SET})")
    parser.add_argument("--audio", metavar="FILE", nargs="+",
                        help="score-free mode: compare backends on bare audio "
                             "with no reference transcript (e.g. "
                             "assets/sample.mp4, which has none)")
    parser.add_argument("--backends", default="local",
                        help="comma-separated: " + ",".join(BACKENDS) +
                             ". Cloud arms UPLOAD AUDIO and need API keys.")
    parser.add_argument("--stress", action="store_true",
                        help="also room-noise, quiet-device and 1.15x speech")
    parser.add_argument("--quiet-sweep", action="store_true",
                        help="attenuate in 10 dB steps; the InputGain guard")
    parser.add_argument("--no-gain", action="store_true",
                        help="disable adaptive input gain (pre-fix behaviour)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    references, clip_paths, scoring = load_eval_set(args)
    if args.limit:
        references = dict(list(references.items())[:args.limit])
        clip_paths = {name: clip_paths[name] for name in references}

    cfg = load_config()
    if args.no_gain:
        cfg = {**cfg, "live": {**cfg["live"],
                               "input_gain": {**cfg["live"]["input_gain"],
                                              "enabled": False}}}

    names = [name.strip() for name in args.backends.split(",") if name.strip()]
    unknown = [name for name in names if name not in BACKENDS]
    if unknown:
        raise SystemExit(f"unknown backend(s): {unknown}. Known: {list(BACKENDS)}")
    if any(name != "local" for name in names):
        print("[!] A cloud backend is selected. Audio WILL be uploaded to a "
              "third party. This run is not offline.\n")

    backends = {}
    for name in names:
        print(f"loading {name}…")
        cls = BACKENDS[name]
        backends[name] = (cls(cfg, language=args.lang) if name == "local"
                          else cls(language=args.lang))

    active = condition_sets.build(stress=args.stress, quiet_sweep=args.quiet_sweep)
    unit_name = "CER" if args.lang == "ko" else "WER"
    grand = {name: {"edits": 0, "units": 0} for name in names}

    for condition_index, (condition, transform) in enumerate(active):
        print(f"\n{'=' * 72}\n[{condition}]")
        results: dict[str, dict[str, Transcript]] = {name: {} for name in names}
        totals = {name: {"edits": 0, "units": 0, "audio": 0.0, "wall": 0.0}
                  for name in names}

        for clip_index, (clip, reference) in enumerate(references.items()):
            audio, _ = librosa.load(clip_paths[clip], sr=SR, mono=True)
            rng = np.random.default_rng(42 + condition_index * 100 + clip_index)
            audio = transform(audio.astype(np.float32), rng)
            duration = len(audio) / SR
            for name, backend in backends.items():
                transcript = backend.transcribe(audio, SR)
                results[name][clip] = transcript
                if transcript.error:
                    print(f"  {clip} {name}: ERROR {transcript.error}")
                    continue
                totals[name]["audio"] += duration
                totals[name]["wall"] += transcript.elapsed_s
                if scoring:
                    reference_units = scored_units(reference, args.lang)
                    hypothesis_units = scored_units(transcript.text, args.lang)
                    edits = edit_distance(reference_units, hypothesis_units)
                    totals[name]["edits"] += edits
                    totals[name]["units"] += len(reference_units)
                    grand[name]["edits"] += edits
                    grand[name]["units"] += len(reference_units)

        header = (f"{'backend':<14}{unit_name:>8}{'edits':>11}{'RTF':>8}"
                  f"{'onset gaps':>31}" if scoring else
                  f"{'backend':<14}{'words':>8}{'RTF':>10}{'onset gaps':>38}")
        print(header)
        print("-" * 72)
        for name in names:
            total = totals[name]
            gaps = [gap for clip in results[name].values()
                    for gap in onset_gaps(clip.words)]
            words = sum(len(clip.words) for clip in results[name].values())
            rtf = total["wall"] / max(total["audio"], 1e-6)
            if not scoring:
                print(f"{name:<14}{words:>8}{rtf:>10.3f}{describe(gaps):>38}")
            elif total["units"]:
                rate = 100 * total["edits"] / total["units"]
                print(f"{name:<14}{rate:7.2f}%{total['edits']:>8}/"
                      f"{total['units']:<4}{rtf:>7.3f}  {describe(gaps):>29}")
            else:
                print(f"{name:<14}{'no output':>8}")

        if len(names) > 1:
            print("\n  pairwise word-onset agreement (matched words):")
            for i, left in enumerate(names):
                for right in names[i + 1:]:
                    deltas = []
                    for clip in references:
                        a, b = results[left].get(clip), results[right].get(clip)
                        if not a or not b or a.error or b.error:
                            continue
                        deltas.extend(abs(x.start - y.start)
                                      for x, y in align_words(a.words, b.words))
                    print(f"    {left} vs {right}: {describe(deltas)} "
                          f"over {len(deltas)} words")

    if not scoring:
        print(f"\n{len(references)} clip(s), NO reference transcript -- nothing "
              "here is an accuracy figure.\n  Cross-backend disagreement flags "
              "likely errors and timing is comparable, but which\n  backend is "
              "RIGHT is undetermined. Never derive a reference from a model's "
              "own output.")
        return

    if len(active) > 1:
        print(f"\n{'=' * 72}\nMATRIX TOTAL")
        for name in names:
            if grand[name]["units"]:
                rate = 100 * grand[name]["edits"] / grand[name]["units"]
                print(f"  {name:<14}{rate:7.2f}% "
                      f"({grand[name]['edits']}/{grand[name]['units']})")

    units = max((grand[name]["units"] for name in names), default=0)
    per_condition = units // max(len(active), 1)
    print(f"\nFLEURS {args.lang}: {len(references)} clips, {per_condition} "
          f"scored units per condition.")
    if per_condition < 1000:
        print(f"  WARNING: small -- one edit moves the rate "
              f"{100 / max(per_condition, 1):.2f} points. Fetch more with "
              f"scripts/fetch_fleurs.py --count 300")
    if any(has_digits(text) for text in references.values()):
        print("  NOTE: references contain digits. Number formatting (2011년 vs "
              "이천십일년) is\n  counted as error and will favour whichever "
              "backend matches FLEURS' style.\n  Normalize before comparing "
              "providers.")
    print("  FLEURS is READ speech -- no spontaneous turn-taking, no room "
          "noise. It is the\n  comparable academic standard, not a booth "
          "simulation.")
    print("  Timing columns are DISTRIBUTIONS and pairwise agreement; FLEURS "
          "carries no\n  word alignment, so they are not accuracy.")


if __name__ == "__main__":
    main()
