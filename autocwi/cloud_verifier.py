"""Opt-in cloud endpoint verifier (OpenAI `gpt-transcribe`).

The ONLY component that may send captured audio off the machine, and OFF by
default (`live.verifier_backend: local`).

It sits at `EndpointVerifier` because that is the one seam whose contract is
"audio in, bare text out" -- OpenAI's models return no word timing, and this
project keys every motion decision on word spans. Do not widen it. See CLAUDE.md
for the full rationale.

Uses `gpt-transcribe` (completed audio), not `gpt-live-transcribe`: an endpoint
buffer is already a complete utterance, so the streaming model would trade
quality for latency this seam does not need.
"""

from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass, field

import numpy as np

SR = 16_000


@dataclass
class CloudVerifierStats:
    """Counters for A/B comparison and for diagnosing a degraded booth link."""

    calls: int = 0
    cloud_used: int = 0
    fell_back: int = 0
    skipped_short: int = 0
    disagreements: int = 0
    total_latency_s: float = 0.0
    last_error: str = ""
    # Kept for offline inspection: (local_text, cloud_text) where they differed.
    samples: list[tuple[str, str]] = field(default_factory=list)

    def report(self) -> dict:
        mean_latency = (
            self.total_latency_s / self.cloud_used if self.cloud_used else 0.0
        )
        return {
            "calls": self.calls,
            "cloud_used": self.cloud_used,
            "fell_back": self.fell_back,
            "skipped_short": self.skipped_short,
            "disagreements": self.disagreements,
            "mean_cloud_latency_s": round(mean_latency, 3),
            "last_error": self.last_error,
            # The point of running the A/B is seeing WHAT the cloud changed, not
            # just how often. Without this the samples were collected and never
            # read.
            "disagreement_samples": self.samples[:10],
        }


def encode_wav(audio: np.ndarray, sample_rate: int = SR) -> bytes:
    """Encode float32 mono samples as an in-memory 16-bit WAV.

    Nothing touches disk: booth audio should not leave a copy behind just
    because the cloud lane is enabled.
    """

    import soundfile as sf

    audio = np.asarray(audio, dtype=np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    buffer.seek(0)
    return buffer.read()


class CloudEndpointVerifier:
    """Wrap a local `EndpointVerifier`, preferring a cloud transcript.

    The local verifier is ALWAYS run first and its result retained. The cloud
    call is then attempted under a hard timeout, and any failure -- no key, no
    network, a slow booth uplink, a malformed response -- silently returns the
    local text. `transcribe()` runs synchronously inside the capture path
    (`live.py:3206`), so an unbounded call would stall audio; a caption must
    never be lost because the uplink hiccuped.
    """

    def __init__(self, local, cfg: dict, client=None):
        self.local = local
        live_cfg = cfg.get("live", {}) or {}
        options = dict(live_cfg.get("openai_verifier", {}) or {})
        self.model = str(options.get("model", "gpt-transcribe"))
        self.timeout_s = float(options.get("timeout_s", 2.0))
        self.min_duration_s = float(options.get("min_duration_s", 0.4))
        self.language = options.get("language") or live_cfg.get("lang") or None
        self.prompt = str(options.get("prompt", "") or "")
        self.stats = CloudVerifierStats()
        self._keep_samples = bool(options.get("record_disagreements", True))

        # An injected client keeps the tests offline: they must never need the
        # openai package, a key, or a network.
        if client is not None:
            self.client = client
            return

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "live.verifier_backend is 'openai' but OPENAI_API_KEY is not "
                "set.\nExport the key, or set live.verifier_backend: local to "
                "stay fully offline."
            )

        # Imported lazily and only on this path: the offline default must never
        # require the dependency, and `import openai` must not happen at all
        # unless the operator explicitly enabled the cloud lane.
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SystemExit(
                "live.verifier_backend is 'openai' but the openai package is "
                "not installed.\n  .venv/bin/pip install openai"
            ) from exc

        self.client = OpenAI(api_key=api_key, timeout=self.timeout_s,
                             max_retries=0)

    # -- diagnostics --------------------------------------------------------

    def report(self) -> dict:
        return self.stats.report()

    # -- verification -------------------------------------------------------

    def transcribe(self, audio: np.ndarray) -> str:
        audio = np.asarray(audio, dtype=np.float32)
        local_text = self.local.transcribe(audio)
        self.stats.calls += 1

        # A very short buffer is usually a fragment or a false endpoint. It is
        # the least useful thing to spend a round trip and an API call on.
        if len(audio) < self.min_duration_s * SR:
            self.stats.skipped_short += 1
            return local_text

        started = time.perf_counter()
        try:
            cloud_text = self._request(audio)
        except Exception as exc:
            # Deliberately broad: a booth demo must degrade to the offline
            # path for ANY cloud failure rather than drop the utterance.
            self.stats.fell_back += 1
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            return local_text

        if not cloud_text:
            self.stats.fell_back += 1
            return local_text

        self.stats.cloud_used += 1
        self.stats.total_latency_s += time.perf_counter() - started
        if cloud_text.strip() != local_text.strip():
            self.stats.disagreements += 1
            if self._keep_samples and len(self.stats.samples) < 200:
                self.stats.samples.append((local_text, cloud_text))
        return cloud_text

    def _request(self, audio: np.ndarray) -> str:
        kwargs = {
            "model": self.model,
            "file": ("endpoint.wav", encode_wav(audio), "audio/wav"),
            "response_format": "text",
        }
        if self.language:
            kwargs["language"] = self.language
        if self.prompt:
            kwargs["prompt"] = self.prompt
        result = self.client.audio.transcriptions.create(**kwargs)
        # `response_format="text"` yields a bare string; the SDK may still hand
        # back an object with `.text` depending on version.
        text = result if isinstance(result, str) else getattr(result, "text", "")
        return str(text or "").strip()


def privacy_notice(model: str) -> str:
    """One-line, unmissable statement of what enabling this actually does."""

    return (
        "[live] CLOUD VERIFIER ACTIVE — endpoint audio is being uploaded to "
        f"OpenAI ({model}). This is not an offline session. Set "
        "live.verifier_backend: local to disable."
    )
