"""A/B the Korean recognizer's export chunk and decoding method.

`kangkyu/icefall-asr-ko-streaming-zipformer-174m` ships chunk-16, chunk-32 and
chunk-64 ONNX exports of the SAME weights, and the model card's own numbers are
all `modified_beam_search`. The shipped config picked chunk-16 + greedy, so two
accuracy levers were never measured here. This runs the grid on FLEURS ko.

    .venv/bin/python scripts/korean_sweep.py
    .venv/bin/python scripts/korean_sweep.py --limit 24 --chunks 16,32
    .venv/bin/python scripts/korean_sweep.py --condition quiet-device

Needs the other two exports, which the default fetch does not pull:

    .venv/bin/python scripts/fetch_streaming_model.py --korean-sweep

It scores accuracy AND delivery, because a longer chunk buys CER with latency
and CWI 2.2.1 read-ahead is spent out of the same budget:

  CER       normalized (see autocwi/scoring.canonical_korean)
  paint     word onset -> the block after which the FIRST event carrying that
            word had been emitted (cue/commit/word), which is what decides
            whether it can be on screen before the playhead reaches it.
            Scoring only durable `word` events puts this a whole endpoint late
            and disqualifies every arm including the shipped one.
  durable   the same, for `type: "word"` alone
  onset gap spacing between consecutive word onsets -- `motion-timing.ts`
            reads the median of exactly this, so a chunk that quantizes spans
            coarsely shows up here even at identical text

`--condition` reuses scripts/conditions.py with benchmark.py's exact seeding,
so a robustness check here is the same degraded audio `--stress` reports on. A
chunk that wins on clean read speech and collapses under noise is not a win.
"""

from __future__ import annotations

import argparse
import copy
import statistics
import sys
import time
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import conditions as condition_sets  # noqa: E402
from asr_backends import collapse_revisions  # noqa: E402

from autocwi.config import load_config  # noqa: E402
from autocwi.scoring import edit_distance, scored_units  # noqa: E402

SR = 16_000
EVAL = ROOT / "assets/eval-fleurs-ko"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))]


def configure(cfg: dict, chunk: int, decoding: str) -> dict:
    """Point the Korean overlay at one chunk export and decoding method."""

    cfg = copy.deepcopy(cfg)
    korean = cfg["live"]["languages"]["ko"]
    korean["streaming_files"] = {
        "tokens": "tokens.txt",
        "encoder": f"encoder-epoch-99-avg-1-chunk-{chunk}-left-128.int8.onnx",
        "decoder": f"decoder-epoch-99-avg-1-chunk-{chunk}-left-128.int8.onnx",
        "joiner": f"joiner-epoch-99-avg-1-chunk-{chunk}-left-128.int8.onnx",
    }
    korean["decoding_method"] = decoding
    return cfg


def run_arm(cfg: dict, clips: dict[str, Path], references: dict[str, str],
            chunk: int, decoding: str, transform=None,
            condition_index: int = 0) -> dict:
    """Transcribe every clip once, block by block, timing each delivery."""

    from autocwi.live import (
        BLOCK,
        AudioChunk,
        DualStreamingCaptioner,
        InputGain,
        _configure_live_language,
        load_streaming_recognizer,
    )

    arm_cfg = _configure_live_language(configure(cfg, chunk, decoding), "ko")
    recognizer = load_streaming_recognizer(arm_cfg)

    edits = units = 0
    raw_edits = raw_units = 0
    lags: list[float] = []
    durable_lags: list[float] = []
    gaps: list[float] = []
    audio_s = wall_s = 0.0

    for index, (clip, reference) in enumerate(references.items()):
        audio, _ = librosa.load(clips[clip], sr=SR, mono=True)
        audio = audio.astype(np.float32)
        if transform is not None:
            # benchmark.py's exact seed, INCLUDING its condition offset -- with
            # `42 + index` alone the noise realization differs and the absolute
            # numbers here stop matching the ones `--stress` prints. (The A/B
            # would still be valid, since both arms see the same audio; the
            # cross-tool comparison is what breaks.)
            audio = transform(
                audio, np.random.default_rng(42 + condition_index * 100 + index)
            )
        # No verifier/draft/diarizer: this A/B is about the streaming stage, and
        # the Korean overlay disables both sidecars anyway. Excluding the
        # speaker tracker keeps the lag column free of its ~30 ms per endpoint.
        captioner = DualStreamingCaptioner(None, recognizer, arm_cfg,
                                           verifier=None, speaker_tracker=None)
        gain = InputGain(arm_cfg)
        # word_id -> (stream-clock onset, first painted, durable)
        painted: dict[str, tuple[float, float]] = {}
        durable: dict[str, tuple[float, float]] = {}
        events = []
        started = time.perf_counter()
        try:
            for offset in range(0, len(audio), BLOCK):
                block_end = min(offset + BLOCK, len(audio)) / SR
                # Materialize: `accept` yields, so consuming it twice would
                # leave the second pass empty -- which reads as "no words were
                # delivered mid-stream" rather than as a bug.
                produced = list(captioner.accept(
                    gain.process(AudioChunk(audio[offset:offset + BLOCK],
                                            offset / SR))
                ))
                events.extend(produced)
                for event in produced:
                    key = event.get("word_id")
                    if not key or not event.get("text"):
                        continue
                    # `t` is the STREAM clock; `start`/`end` are relative to
                    # their utterance, so subtracting `start` here would mix
                    # two timelines and understate the lag.
                    stamp = (float(event.get("t", 0.0)), block_end)
                    # FIRST PAINT is the read-ahead budget: the studio colours
                    # from `cue`/`commit` as well as `word`, so scoring only
                    # durable events overstates the lag by a whole endpoint.
                    painted.setdefault(key, stamp)
                    if event.get("type") == "word":
                        durable.setdefault(key, stamp)
            events.extend(captioner.finish())
        finally:
            captioner.close()
        wall_s += time.perf_counter() - started
        audio_s += len(audio) / SR

        words = collapse_revisions(events)
        hypothesis = " ".join(word.text for word in words).strip()
        reference_units = scored_units(reference, "ko")
        edits += edit_distance(reference_units, scored_units(hypothesis, "ko"))
        units += len(reference_units)
        raw_reference = scored_units(reference, "ko", normalize=False)
        raw_edits += edit_distance(
            raw_reference, scored_units(hypothesis, "ko", normalize=False))
        raw_units += len(raw_reference)

        lags.extend(max(0.0, delivered - onset)
                    for onset, delivered in painted.values())
        durable_lags.extend(max(0.0, delivered - onset)
                            for onset, delivered in durable.values())
        ordered = sorted(word.start for word in words)
        gaps.extend(later - earlier
                    for earlier, later in zip(ordered, ordered[1:])
                    if later >= earlier)

    return {
        "cer": 100 * edits / max(units, 1),
        "raw_cer": 100 * raw_edits / max(raw_units, 1),
        "edits": edits,
        "units": units,
        "rtf": wall_s / max(audio_s, 1e-6),
        "lag_median": statistics.median(lags) if lags else float("nan"),
        "lag_p90": percentile(lags, 0.90),
        "durable_median": (statistics.median(durable_lags)
                           if durable_lags else float("nan")),
        "durable_p90": percentile(durable_lags, 0.90),
        "gap_median": statistics.median(gaps) if gaps else float("nan"),
        "words": len(lags),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", default="16,32,64")
    parser.add_argument("--decoding", default="greedy_search,modified_beam_search")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refs", default=None)
    parser.add_argument("--condition", default="clean",
                        choices=["clean", "room-noise-14db", "quiet-device",
                                 "fast-1.15x"],
                        help="degrade the audio exactly as benchmark --stress "
                             "does, to check a chunk choice is not robust only "
                             "on clean read speech")
    args = parser.parse_args()

    refs = Path(args.refs) if args.refs else EVAL
    if not refs.is_absolute():
        refs = ROOT / refs
    transcript = refs / "test_wavs" / "trans.txt"
    if not transcript.is_file():
        raise SystemExit(
            f"no FLEURS eval set at {transcript}\n"
            "  fetch it once: .venv/bin/python scripts/fetch_fleurs.py --lang ko"
        )
    references, clips = {}, {}
    for line in transcript.read_text(encoding="utf-8").splitlines():
        if " " not in line:
            continue
        name, text = line.split(" ", 1)
        references[name] = text
        clips[name] = refs / "test_wavs" / name
    if args.limit:
        references = dict(list(references.items())[:args.limit])
        clips = {name: clips[name] for name in references}

    cfg = load_config()
    chunks = [int(value) for value in args.chunks.split(",") if value.strip()]
    methods = [value.strip() for value in args.decoding.split(",") if value.strip()]

    missing = [
        chunk for chunk in chunks
        if not (ROOT / "assets/streaming-zipformer-ko-174m"
                / f"encoder-epoch-99-avg-1-chunk-{chunk}-left-128.int8.onnx"
                ).is_file()
    ]
    if missing:
        raise SystemExit(
            f"missing chunk export(s) {missing}. Fetch them once:\n"
            "  .venv/bin/python scripts/fetch_streaming_model.py --korean-only"
        )

    delay_s = float(cfg["display"]["read_ahead_delay_s"])
    floor_ms = float(cfg["display"]["min_read_ahead_ms"])

    built = condition_sets.build(stress=True)
    condition_index = next(index for index, (label, _) in enumerate(built)
                           if label == args.condition)
    transform = built[condition_index][1] if condition_index else None

    print(f"FLEURS ko: {len(references)} clips, condition [{args.condition}]")
    print(f"read_ahead_delay_s {delay_s:.2f}s, min_read_ahead_ms "
          f"{floor_ms:.0f} -- a word must be painted before the playhead "
          f"reaches it.\n")
    print(f"{'chunk':>6}  {'decoding':<21}{'CER':>8}{'raw':>8}{'edits':>11}"
          f"{'RTF':>7}{'paint med/p90':>16}{'durable':>10}{'lead p90':>10}")
    print("-" * 100)
    rows = []
    for chunk in chunks:
        for method in methods:
            result = run_arm(cfg, clips, references, chunk, method, transform,
                             condition_index)
            rows.append((chunk, method, result))
            # What the viewer gets: how long a word is legible before its own
            # colour turn, in the WORST decile. Negative means the playhead
            # arrives first and CWI 2.2.1 read-ahead is simply absent.
            lead = (delay_s - result["lag_p90"]) * 1000
            result["lead_p90_ms"] = lead
            print(f"{chunk:>6}  {method:<21}{result['cer']:7.2f}%"
                  f"{result['raw_cer']:7.2f}%"
                  f"{result['edits']:>7}/{result['units']:<4}"
                  f"{result['rtf']:>6.3f}"
                  f"{result['lag_median'] * 1000:>8.0f}/"
                  f"{result['lag_p90'] * 1000:<7.0f}"
                  f"{result['durable_median'] * 1000:>9.0f}"
                  f"{lead:>9.0f}{'!' if lead < floor_ms else ' '}")

    viable = [row for row in rows if row[2]["lead_p90_ms"] >= floor_ms]
    best = min(rows, key=lambda row: row[2]["cer"])
    print(f"\nlowest CER overall: chunk-{best[0]} {best[1]} at "
          f"{best[2]['cer']:.2f}% (p90 lead {best[2]['lead_p90_ms']:.0f} ms)")
    if viable:
        pick = min(viable, key=lambda row: row[2]["cer"])
        print(f"lowest CER that still leaves read-ahead: chunk-{pick[0]} "
              f"{pick[1]} at {pick[2]['cer']:.2f}%")
        shipped = next((row for row in rows
                        if row[0] == 16 and row[1] == "greedy_search"), None)
        if shipped and shipped is not pick:
            delta = shipped[2]["cer"] - pick[2]["cer"]
            lag = (pick[2]["lag_median"] - shipped[2]["lag_median"]) * 1000
            print(f"  vs shipped chunk-16 greedy_search: {delta:+.2f} points "
                  f"({100 * delta / max(shipped[2]['cer'], 1e-9):.0f}% "
                  f"relative), median paint lag {lag:+.0f} ms")
    else:
        print("NO arm leaves the per-word read-ahead floor -- keep the "
              "shipped config.")
    print("\n`paint` is the FIRST event carrying the word (cue/commit/word), "
          "which is what the\nstudio colours from; `durable` is the endpoint "
          "`word` event alone. Scoring only\ndurable events overstates the lag "
          "by a whole endpoint. A `!` marks an arm whose\nworst-decile word "
          "reaches the screen too late to be read before it turns.")


if __name__ == "__main__":
    main()
