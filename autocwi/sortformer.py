"""Native Streaming Sortformer bridge for Apple Silicon.

The model runs in a tiny Swift helper so the Python 3.11 live process does not
inherit NeMo's Python/PyTorch dependency stack.  Audio and timeline snapshots
travel over newline-delimited JSON; float32 blocks are base64 encoded and never
leave the machine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

import numpy as np


@dataclass(frozen=True)
class SortformerDecision:
    speaker_index: int
    coverage: float
    activity: float
    finalized: bool
    processed_through: float


def select_sortformer_decision(
    segments: list[dict],
    start_s: float,
    end_s: float,
    processed_through: float,
) -> SortformerDecision | None:
    """Select the speaker with the strongest activity-weighted word overlap.

    Sortformer can retain two speaker tracks across a real overlap or a soft
    hand-off. Comparing duration alone lets a faint secondary track steal the
    word even when the primary track is much more active.
    """

    start = float(start_s)
    end = max(start, float(end_s))
    duration = max(1e-6, end - start)
    by_speaker: dict[int, dict[str, float | bool]] = {}
    for segment in segments:
        left = max(start, float(segment.get("start", 0.0)))
        right = min(end, float(segment.get("end", 0.0)))
        overlap = max(0.0, right - left)
        if overlap <= 0:
            continue
        speaker = int(segment.get("speaker", 0))
        current = by_speaker.setdefault(
            speaker,
            {"overlap": 0.0, "activity_sum": 0.0, "finalized": True},
        )
        current["overlap"] = float(current["overlap"]) + overlap
        current["activity_sum"] = (
            float(current["activity_sum"])
            + overlap * float(segment.get("activity", 0.0))
        )
        current["finalized"] = bool(
            current["finalized"] and segment.get("finalized", False)
        )
    if not by_speaker:
        return None
    speaker, chosen = max(
        by_speaker.items(),
        key=lambda item: (
            float(item[1]["activity_sum"]),
            float(item[1]["overlap"]),
            -item[0],
        ),
    )
    overlap = float(chosen["overlap"])
    return SortformerDecision(
        speaker_index=speaker,
        coverage=float(np.clip(overlap / duration, 0.0, 1.0)),
        activity=(
            float(chosen["activity_sum"]) / overlap if overlap > 0 else 0.0
        ),
        finalized=bool(chosen["finalized"]),
        processed_through=float(processed_through),
    )


class SortformerBridge:
    """Persistent local subprocess owning Core ML model state."""

    def __init__(
        self,
        executable: str | Path,
        cache_dir: str | Path,
        *,
        startup_timeout_s: float = 120.0,
        debug: bool = False,
    ):
        self.executable = Path(executable)
        self.cache_dir = Path(cache_dir)
        self.debug = bool(debug)
        self._condition = threading.Condition()
        self._segments: list[dict] = []
        self._processed_through = 0.0
        self._finished = False
        self._closed = False
        self._ready: queue.Queue[dict] = queue.Queue(maxsize=1)
        self._stderr_lines: queue.Queue[str] = queue.Queue(maxsize=64)
        self.process = subprocess.Popen(
            [
                str(self.executable),
                "--cache",
                str(self.cache_dir),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="sortformer-timeline",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            name="sortformer-log",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()
        try:
            event = self._ready.get(timeout=max(0.1, startup_timeout_s))
        except queue.Empty as exc:
            self.close()
            raise TimeoutError("Sortformer helper did not become ready") from exc
        if event.get("type") != "ready":
            self.close()
            raise RuntimeError(
                event.get("message") or "Sortformer helper failed to start"
            )
        self.latency_s = float(event.get("latencySeconds") or 1.04)

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type in {"ready", "error"} and self._ready.empty():
                self._ready.put_nowait(event)
            if event_type in {"timeline", "reset"}:
                with self._condition:
                    self._segments = list(event.get("segments") or [])
                    self._processed_through = float(
                        event.get("processedThrough")
                        or self._processed_through
                    )
                    self._condition.notify_all()
            elif event_type == "finished":
                with self._condition:
                    self._processed_through = max(
                        self._processed_through,
                        float(
                            event.get("processedThrough")
                            or self._processed_through
                        ),
                    )
                    self._finished = True
                    self._condition.notify_all()

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for raw in self.process.stderr:
            line = raw.rstrip()
            if self.debug and line:
                print(f"[sortformer] {line}")
            try:
                self._stderr_lines.put_nowait(line)
            except queue.Full:
                try:
                    self._stderr_lines.get_nowait()
                except queue.Empty:
                    pass

    def _send(self, payload: dict) -> None:
        if self._closed or self.process.poll() is not None:
            raise RuntimeError("Sortformer helper is not running")
        assert self.process.stdin is not None
        line = json.dumps(payload, separators=(",", ":"))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def feed(
        self,
        samples: np.ndarray,
        *,
        source_start: float,
        discontinuity: bool = False,
    ) -> None:
        if discontinuity:
            self._send({"type": "reset", "offset": float(source_start)})
        audio = np.ascontiguousarray(samples, dtype="<f4")
        self._send({
            "type": "audio",
            "audio": base64.b64encode(audio.tobytes()).decode("ascii"),
        })

    def decision(
        self,
        start_s: float,
        end_s: float,
        *,
        wait_ms: float = 0.0,
    ) -> SortformerDecision | None:
        deadline = time.monotonic() + max(0.0, float(wait_ms)) / 1000.0
        with self._condition:
            while self._processed_through + 1e-6 < end_s:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            return select_sortformer_decision(
                self._segments,
                start_s,
                end_s,
                self._processed_through,
            )

    def finish(self, *, timeout_s: float = 3.0) -> None:
        if self._closed or self.process.poll() is not None:
            return
        with self._condition:
            self._finished = False
        self._send({"type": "finish"})
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while not self._finished and time.monotonic() < deadline:
                self._condition.wait(
                    timeout=max(0.0, deadline - time.monotonic())
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write('{"type":"close"}\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        for stream in (
            self.process.stdin,
            self.process.stdout,
            self.process.stderr,
        ):
            if stream is not None:
                stream.close()
