"""Reproducible local WER/throughput check for the configured live pipeline."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import librosa
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autocwi.config import load_config
from autocwi.live import (
    BLOCK,
    AudioChunk,
    DualStreamingCaptioner,
    InputGain,
    load_endpoint_verifier,
    load_streaming_recognizer,
)

def normalized_words(text: str) -> list[str]:
    return re.findall(r"[A-Z0-9']+", text.upper())


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def add_noise(audio: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    signal_rms = max(float(np.sqrt(np.mean(audio**2))), 1e-6)
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    noise *= signal_rms / (10 ** (snr_db / 20)) / max(
        float(np.sqrt(np.mean(noise**2))), 1e-6
    )
    return np.clip(audio + noise, -1.0, 1.0).astype(np.float32)


def room_noise(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Deterministic small-room echoes plus 14 dB SNR background noise."""

    impulse = np.zeros(int(0.22 * 16_000), dtype=np.float32)
    impulse[[0, int(.055 * 16_000), int(.12 * 16_000), int(.20 * 16_000)]] = [
        1.0, 0.34, 0.18, 0.08,
    ]
    reverberant = np.convolve(audio, impulse, mode="full")[:len(audio)]
    peak = max(float(np.max(np.abs(reverberant))), 1e-6)
    reverberant = reverberant * min(1.0, 0.92 / peak)
    return add_noise(reverberant.astype(np.float32), 14.0, rng)


def quiet_noise(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Speech attenuated 22 dB over an absolute -52 dBFS device floor."""

    quiet = audio * (10 ** (-22 / 20))
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    noise *= 10 ** (-52 / 20) / max(float(np.sqrt(np.mean(noise**2))), 1e-6)
    return np.clip(quiet + noise, -1.0, 1.0).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stress", action="store_true",
        help="also test deterministic room/noise, quiet-device, and 1.15x speech",
    )
    parser.add_argument(
        "--quiet-sweep", action="store_true",
        help="attenuate each clip in 10 dB steps and report recall per level; "
             "measures quiet-speech handling without needing a quiet talker",
    )
    parser.add_argument(
        "--no-gain", action="store_true",
        help="disable the adaptive input gain (shows the pre-fix behaviour)",
    )
    parser.add_argument("--streaming-model", default=None, metavar="DIR",
                        help="override live.streaming_model_dir (A/B a candidate)")
    parser.add_argument("--draft-model", default=None, metavar="DIR",
                        help="override live.draft_model_dir")
    parser.add_argument("--refs", default=None, metavar="DIR",
                        help="model dir supplying test_wavs/trans.txt (default: "
                             "the model under test)")
    parser.add_argument("--endpoint-silence", type=float)
    parser.add_argument("--endpoint-max", type=float)
    args = parser.parse_args()
    cfg = load_config()
    if args.streaming_model or args.draft_model:
        cfg = {**cfg, "live": {**cfg["live"]}}
        if args.streaming_model:
            cfg["live"]["streaming_model_dir"] = args.streaming_model
        if args.draft_model:
            cfg["live"]["draft_model_dir"] = args.draft_model
    if args.no_gain:
        cfg = {**cfg, "live": {**cfg["live"],
                               "input_gain": {**cfg["live"]["input_gain"],
                                              "enabled": False}}}
    live_cfg = cfg["live"]
    if args.endpoint_silence is not None:
        live_cfg["endpoint_silence_s"] = args.endpoint_silence
    if args.endpoint_max is not None:
        live_cfg["endpoint_max_s"] = args.endpoint_max
    accurate_dir = Path(live_cfg["streaming_model_dir"])
    if not accurate_dir.is_absolute():
        accurate_dir = ROOT / accurate_dir
    # The evaluation set is fixed independently of the model under test, so an
    # A/B between checkpoints compares recognizers rather than test material.
    refs_dir = Path(args.refs) if args.refs else accurate_dir
    if not refs_dir.is_absolute():
        refs_dir = ROOT / refs_dir
    references = {}
    for line in (refs_dir / "test_wavs" / "trans.txt").read_text().splitlines():
        name, text = line.split(" ", 1)
        references[name] = text

    draft = load_streaming_recognizer(cfg, live_cfg["draft_model_dir"])
    accurate = load_streaming_recognizer(cfg, accurate_dir)
    verifier = load_endpoint_verifier(cfg)
    conditions = [("clean", lambda audio, rng: audio)]
    if args.quiet_sweep:
        # A fixed -78 dBFS device floor under progressively quieter speech.
        # The floor has to stay well below the quietest condition or the sweep
        # stops measuring level handling and turns into an SNR test: at -40 dB
        # over a -60 dBFS floor the speech and the noise are the same size, and
        # no amount of gain can recover that.
        def attenuated(db):
            def transform(audio, rng):
                quiet = audio * (10 ** (db / 20))
                noise = rng.standard_normal(len(audio)).astype(np.float32)
                noise *= 10 ** (-78 / 20) / max(
                    float(np.sqrt(np.mean(noise**2))), 1e-6
                )
                return np.clip(quiet + noise, -1.0, 1.0).astype(np.float32)
            return transform

        conditions = [(f"attenuated-{db}db", attenuated(db))
                      for db in (0, -10, -20, -30, -40)]
    if args.stress:
        conditions.extend([
            ("room-noise-14db", room_noise),
            ("quiet-device", quiet_noise),
            ("fast-1.15x", lambda audio, rng: librosa.effects.time_stretch(
                y=audio, rate=1.15
            ).astype(np.float32)),
        ])

    grand_edits = grand_words = 0
    for condition_index, (condition, transform) in enumerate(conditions):
        total_edits = total_words = 0
        total_audio = total_wall = 0.0
        print(f"\n[{condition}]")
        for clip_index, (name, reference) in enumerate(references.items()):
            audio, _ = librosa.load(refs_dir / "test_wavs" / name,
                                    sr=16_000, mono=True)
            rng = np.random.default_rng(42 + condition_index * 100 + clip_index)
            audio = transform(audio.astype(np.float32), rng)
            captioner = DualStreamingCaptioner(
                draft, accurate, cfg, verifier=verifier
            )
            started = time.perf_counter()
            events = []
            gain = InputGain(cfg)
            try:
                for offset in range(0, len(audio), BLOCK):
                    chunk = gain.process(AudioChunk(
                        audio[offset:offset + BLOCK], offset / 16_000
                    ))
                    events.extend(captioner.accept(chunk))
                events.extend(captioner.finish())
            finally:
                captioner.close()
            elapsed = time.perf_counter() - started
            hypothesis = " ".join(
                event["text"] for event in events if event["type"] == "word"
            )
            ref_words = normalized_words(reference)
            hyp_words = normalized_words(hypothesis)
            edits = edit_distance(ref_words, hyp_words)
            duration = len(audio) / 16_000
            total_edits += edits
            total_words += len(ref_words)
            total_audio += duration
            total_wall += elapsed
            print(f"{name}: {edits}/{len(ref_words)} edits, RTF {elapsed / duration:.3f}"
                  f", gain {gain.gain_db:+.1f} dB")
            print(f"  {hypothesis}")

        grand_edits += total_edits
        grand_words += total_words
        print(f"{condition} TOTAL: {total_edits}/{total_words} edits, "
              f"WER {100 * total_edits / total_words:.2f}%, "
              f"RTF {total_wall / total_audio:.3f}")
    if len(conditions) > 1:
        print(f"\nMATRIX TOTAL: {grand_edits}/{grand_words} edits, "
              f"WER {100 * grand_edits / grand_words:.2f}%")


if __name__ == "__main__":
    main()
