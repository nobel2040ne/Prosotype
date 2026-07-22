"""ffmpeg/ffprobe helpers: media probing and 16 kHz mono wav extraction."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SAMPLE_RATE = 16_000


class FfmpegNotFound(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise FfmpegNotFound(
            f"{cmd[0]} not found — install ffmpeg (e.g. `brew install ffmpeg`)"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{cmd[0]} failed:\n{e.stderr}") from e


def probe(path: str | Path) -> dict:
    """Return {"duration": float seconds, "fps": float | None}."""
    out = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]).stdout
    info = json.loads(out)
    duration = float(info["format"]["duration"])
    fps = None
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            num, _, den = stream.get("avg_frame_rate", "0/1").partition("/")
            if num and den and int(den) != 0 and int(num) != 0:
                fps = int(num) / int(den)
            break
    return {"duration": duration, "fps": fps}


def extract_wav(path: str | Path, out_dir: str | Path) -> Path:
    """Extract mono 16 kHz wav next to the other stage outputs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / "audio.wav"
    _run([
        "ffmpeg", "-y", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le", str(wav),
    ])
    return wav
