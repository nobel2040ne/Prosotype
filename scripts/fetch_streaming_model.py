"""One-time setup for production local English and Korean live recognition.

Downloads NVIDIA's int8 English Nemotron 0.6B exports: 160 ms for immediate
draft words and 1120 ms for the accuracy-first stream, plus the int8 Parakeet
Unified endpoint verifier that owns durable text, plus a Zipformer AudioSet
audio-tagging model that detects non-speech / paralinguistic sounds (laughter,
applause, music, environmental) for the non-speech caption lane, plus the
optional first-phone CTC sidecar used to reveal a speculative initial grapheme
before the word recognizer fires. It also downloads the int8 174M Korean
streaming Zipformer used by the startup language picker, English ERes2Net and
multilingual CAM++ identity encoders, and—on Apple Silicon—a pinned native
Core ML Streaming Sortformer helper/model. Inference is fully local afterwards.
"""

import tarfile
import urllib.request
import argparse
import platform
from pathlib import Path
import shutil
import subprocess

CORE_MODELS = (
    ("sherpa-onnx-nemotron-speech-streaming-en-0.6b-160ms-int8-2026-04-25",
     "streaming-nemotron-en-160ms"),
    ("sherpa-onnx-nemotron-speech-streaming-en-0.6b-1120ms-int8-2026-04-25",
     "streaming-nemotron-en-1120ms"),
)

KOREAN_MODEL_ID = "kangkyu/icefall-asr-ko-streaming-zipformer-174m"
KOREAN_MODEL_DIR = "streaming-zipformer-ko-174m"
KOREAN_MODEL_FILES = (
    "tokens.txt",
    "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
)

OFFLINE_VERIFIERS = (
    ("sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming",
     "parakeet-unified-en-offline"),
)

# Non-speech sound tagging (AudioSet 527-class). Zipformer, not CED: this
# sherpa-onnx build's AudioTaggingModelConfig exposes only the `zipformer`
# field. Different release TAG than the ASR models (`audio-tagging-models`);
# the archive layout (tarball -> onnx + class_labels_indices.csv) is the same.
AUDIO_TAGGING = (
    ("sherpa-onnx-zipformer-audio-tagging-2024-04-09", "audio-tagging-en"),
)

# English 3D-Speaker ERes2Net plus learned pyannote speaker segmentation.
# Both are local ONNX models. Segmentation provides turn/overlap evidence;
# ERes2Net provides stable identity across those turns.
SPEAKER_MODELS = (
    (
        "speaker-recongition-models",
        "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx",
        "speaker-embedding-en/"
        "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx",
    ),
    (
        "speaker-recongition-models",
        "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
        "speaker-embedding-multilingual/"
        "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    ),
)

SPEAKER_SEGMENTATION = (
    ("sherpa-onnx-pyannote-segmentation-3-0", "speaker-segmentation-en"),
)

ONSET_MODEL_ID = (
    "bihungba1101/wav2vec2-base-timit-phoneme-demo-google-colab"
)
ONSET_MODEL_FILES = (
    "added_tokens.json",
    "config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
)


def fetch_speaker_models(assets: Path) -> None:
    for tag, name, rel_dest in SPEAKER_MODELS:
        dest = assets / rel_dest
        if dest.exists():
            print(f"already present: {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = (f"https://github.com/k2-fsa/sherpa-onnx/releases/download/"
               f"{tag}/{name}")
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"wrote {dest}")


def fetch_sortformer(root: Path, assets: Path) -> None:
    """Build and prepare the native Apple-Silicon streaming diarizer."""

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        print(
            "Sortformer Core ML setup skipped: it requires Apple Silicon; "
            "the ONNX embedding diarizer remains available"
        )
        return
    swift = shutil.which("swift")
    if swift is None:
        print(
            "Sortformer Core ML setup skipped: Swift is not installed; "
            "the ONNX embedding diarizer remains available"
        )
        return
    package = root / "native" / "sortformer"
    print("building native Streaming Sortformer helper ...")
    subprocess.run(
        [
            swift,
            "build",
            "--package-path",
            str(package),
            "-c",
            "release",
            "--product",
            "autocwi-sortformer",
        ],
        check=True,
    )
    executable = (
        package / ".build" / "release" / "autocwi-sortformer"
    )
    cache = assets / "sortformer-coreml"
    print("downloading/preparing palettized Sortformer v2.1 Core ML model ...")
    subprocess.run(
        [
            str(executable),
            "--prepare",
            "--cache",
            str(cache),
        ],
        check=True,
    )
    print(f"wrote {cache}")


def fetch_tarball_models(assets: Path, models, release_tag: str) -> None:
    for name, dest_name in models:
        dest = assets / dest_name
        if dest.exists() and any(dest.glob("*.onnx")):
            print(f"already present: {dest}")
            continue
        tmp = assets / f"{name}.tar.bz2"
        if tmp.exists():
            print(f"using existing archive: {tmp}")
        else:
            url = (f"https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                   f"{release_tag}/{name}.tar.bz2")
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, tmp)
        print("extracting ...")
        with tarfile.open(tmp, "r:bz2") as tf:
            tf.extractall(assets, filter="data")
        (assets / name).rename(dest)
        tmp.unlink()
        print(f"wrote {dest}")


def fetch_onset_model(assets: Path) -> None:
    dest = assets / "phoneme-onset-en"
    if all((dest / name).is_file() for name in ONSET_MODEL_FILES):
        print(f"already present: {dest}")
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "onset-prefix download needs transformers/huggingface-hub; run "
            ".venv/bin/pip install -r requirements.txt"
        ) from exc
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading {ONSET_MODEL_ID} ...")
    snapshot_download(
        repo_id=ONSET_MODEL_ID,
        local_dir=dest,
        allow_patterns=list(ONSET_MODEL_FILES),
    )
    print(f"wrote {dest}")


def fetch_korean_model(assets: Path) -> None:
    dest = assets / KOREAN_MODEL_DIR
    if all((dest / name).is_file() for name in KOREAN_MODEL_FILES):
        print(f"already present: {dest}")
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "Korean model download needs huggingface-hub; run "
            ".venv/bin/pip install -r requirements.txt"
        ) from exc
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading {KOREAN_MODEL_ID} ...")
    snapshot_download(
        repo_id=KOREAN_MODEL_ID,
        local_dir=dest,
        allow_patterns=list(KOREAN_MODEL_FILES),
    )
    print(f"wrote {dest}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--speaker-only",
        action="store_true",
        help="download only live speaker models (including Sortformer on Mac)",
    )
    parser.add_argument(
        "--sortformer-only",
        action="store_true",
        help="build/download only the Apple-Silicon Streaming Sortformer",
    )
    parser.add_argument(
        "--onset-only",
        action="store_true",
        help="download only the first-phone onset model",
    )
    parser.add_argument(
        "--korean-only",
        action="store_true",
        help="download only the Korean streaming recognizer",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    if args.sortformer_only:
        fetch_sortformer(root, assets)
        return
    if args.onset_only:
        fetch_onset_model(assets)
        return
    if args.korean_only:
        fetch_korean_model(assets)
        return
    fetch_speaker_models(assets)
    fetch_tarball_models(
        assets,
        SPEAKER_SEGMENTATION,
        "speaker-segmentation-models",
    )
    if args.speaker_only:
        fetch_sortformer(root, assets)
        return
    fetch_tarball_models(
        assets,
        CORE_MODELS + OFFLINE_VERIFIERS,
        "asr-models",
    )
    fetch_sortformer(root, assets)
    fetch_korean_model(assets)
    fetch_tarball_models(assets, AUDIO_TAGGING, "audio-tagging-models")
    fetch_onset_model(assets)


if __name__ == "__main__":
    main()
