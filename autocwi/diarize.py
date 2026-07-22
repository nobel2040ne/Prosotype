"""Speaker diarization via pyannote-audio (local inference; gated model weights
require a Hugging Face token in HF_TOKEN)."""

from __future__ import annotations

import os
from pathlib import Path

from .schema import DiarSegment

_TOKEN_HELP = """\
HF_TOKEN is not set. pyannote's pretrained diarization weights are gated:

  1. Create a (free) token at https://huggingface.co/settings/tokens
  2. Accept the conditions of BOTH gated repos:
       https://huggingface.co/pyannote/speaker-diarization-3.1
       https://huggingface.co/pyannote/segmentation-3.0
  3. export HF_TOKEN=hf_...

Inference itself runs fully locally; the token is only used to download weights once.
(Or run with --stub to use placeholder diarization.)"""


def diarize(
    audio_path: str | Path,
    num_speakers: int | None = None,
    device: str = "cpu",
    model: str = "pyannote/speaker-diarization-3.1",
) -> list[DiarSegment]:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit(_TOKEN_HELP)

    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(model, use_auth_token=token)
    if device in ("cuda", "mps"):
        pipeline.to(torch.device(device))

    annotation = pipeline(str(audio_path), num_speakers=num_speakers)

    # Relabel SPEAKER_00-style names to S1, S2, ... by order of first appearance.
    relabel: dict[str, str] = {}
    segments: list[DiarSegment] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        if speaker not in relabel:
            relabel[speaker] = f"S{len(relabel) + 1}"
        segments.append(
            DiarSegment(speaker=relabel[speaker],
                        start=round(turn.start, 3), end=round(turn.end, 3))
        )
    print(f"[diarize] {len(relabel)} speakers, {len(segments)} turns")
    return segments
