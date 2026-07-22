"""ASR with word-level timestamps via faster-whisper (CTranslate2, local)."""

from __future__ import annotations

from pathlib import Path

from .schema import WordTiming

MIN_WORD_DUR = 0.02  # guard against zero/negative-length whisper word spans


def transcribe(
    audio_path: str | Path,
    model_size: str = "small",
    lang: str | None = None,
    beam_size: int = 5,
    temperature: float = 0.0,
    device: str = "cpu",
) -> list[WordTiming]:
    from faster_whisper import WhisperModel

    # CTranslate2 supports cpu/cuda only; MPS falls back to CPU int8.
    ct2_device = "cuda" if device == "cuda" else "cpu"
    compute = "float16" if ct2_device == "cuda" else "int8"
    model = WhisperModel(model_size, device=ct2_device, compute_type=compute)

    segments, info = model.transcribe(
        str(audio_path),
        language=lang,
        word_timestamps=True,
        beam_size=beam_size,
        temperature=temperature,
        vad_filter=True,
    )
    print(f"[asr] whisper-{model_size} lang={info.language} (p={info.language_probability:.2f})")

    words: list[WordTiming] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            end = w.end if w.end - w.start >= MIN_WORD_DUR else w.start + MIN_WORD_DUR
            words.append(
                WordTiming(text=text, start=round(w.start, 3), end=round(end, 3),
                           conf=round(min(max(w.probability, 0.0), 1.0), 3))
            )
    return words
