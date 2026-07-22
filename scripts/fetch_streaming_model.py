"""One-time setup for production local English live recognition.

Downloads NVIDIA's int8 English Nemotron 0.6B exports: 160 ms for immediate
draft words and 1120 ms for the accuracy-first stream, plus the int8 Parakeet
Unified endpoint verifier that owns durable text. The active stack is about
1.9 GB; inference is fully local afterwards.
"""

import tarfile
import urllib.request
import argparse
from pathlib import Path

CORE_MODELS = (
    ("sherpa-onnx-nemotron-speech-streaming-en-0.6b-160ms-int8-2026-04-25",
     "streaming-nemotron-en-160ms"),
    ("sherpa-onnx-nemotron-speech-streaming-en-0.6b-1120ms-int8-2026-04-25",
     "streaming-nemotron-en-1120ms"),
)

OFFLINE_VERIFIERS = (
    ("sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming",
     "parakeet-unified-en-offline"),
)

# Single-file speaker-embedding model for live diarization (speaker -> color).
SPEAKER_MODELS = (
    ("speaker-recongition-models", "nemo_en_titanet_small.onnx",
     "speaker-embedding-en/nemo_en_titanet_small.onnx"),
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


def main() -> None:
    argparse.ArgumentParser().parse_args()
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    fetch_speaker_models(assets)
    models = CORE_MODELS + OFFLINE_VERIFIERS
    for name, dest_name in models:
        dest = assets / dest_name
        if dest.exists() and any(dest.glob("*.onnx")):
            print(f"already present: {dest}")
            continue
        tmp = assets / f"{name}.tar.bz2"
        if tmp.exists():
            print(f"using existing archive: {tmp}")
        else:
            url = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{name}.tar.bz2"
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, tmp)
        print("extracting ...")
        with tarfile.open(tmp, "r:bz2") as tf:
            tf.extractall(assets, filter="data")
        (assets / name).rename(dest)
        tmp.unlink()
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
