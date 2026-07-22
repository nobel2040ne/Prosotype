# Architecture

auto-CWI has two modes sharing one analysis philosophy and one word-data shape.

```
live: mic/file ─► lossless batcher ─► input gain ─┬─► 160ms draft ─► hypothesis ─┐
      (recogniser copy only; prosody reads raw)   ├─► 1120ms ─► cue/commit ───────┼─► live.html
                                                  └─► Parakeet verifier ─► final ─┘  (display.mode:
                                                                                  │   sentence|stable|
offline:  media ─► transcribe ─► diarize ─► prosody ─► fuse ─► spec.json          │   readahead)
          (audio) (asr)         (diarize)  (prosody)  (fuse)      │
                 words.json  segments.json prosody.json           └─► future haptic module
```

## Modules

| Module | Responsibility |
|---|---|
| `autocwi/live.py` | Live engine: lossless mic/file source-clock batcher → adaptive `InputGain` (recognizer copy only) → dual sherpa-onnx Nemotron 0.6B (160 ms draft + 1120 ms accuracy-first stream) → Parakeet Unified modified-beam endpoint verification and timing alignment; emits a continuous `level` event; `SpeakerTracker` live diarization (titanet-small embeddings, segment-then-cluster with centroid merging); bounded/replayable stdlib HTTP + SSE server. `--sample`/`--loop` stream the bundled clip. The old adaptive-segmented Whisper path is an explicit fallback. |
| `autocwi/livepage.py` | Generates `live.html`: CWI caption stage (three `display.mode`s: sentence/stable/readahead) plus Attribution, Synchronization, Intonation, and Input views; embeds Roboto Flex; per-word motion is a baseline-anchored vertical lift (position + colour only, matching the AE template — no scale) isolated from line layout; syllable colour-wipe for drawn-out words (2.2.4); type axes smoothed to the speaker's running baseline (`expression`) |
| `autocwi/asr.py` | Offline ASR (faster-whisper), word timestamps + confidence |
| `autocwi/diarize.py` | pyannote diarization (gated weights → `HF_TOKEN`); relabels to S1, S2… by first appearance |
| `autocwi/prosody.py` | Per-word RMS dB (librosa) + median F0/voiced fraction (parselmouth cc, 75–500 Hz), restricted to ASR word spans |
| `autocwi/fuse.py` | Word↔speaker by max span overlap (gap words snap to nearest segment); per-speaker 5–95-percentile loudness/pitch normalization; deterministic palette assignment; emits validated CaptionSpec |
| `autocwi/schema.py` | Pydantic v2 models: CaptionSpec + per-stage intermediates + JSON I/O helpers |
| `autocwi/audio.py` | ffmpeg/ffprobe: probe duration/fps, extract 16 kHz mono wav |
| `autocwi/stubs.py` | Deterministic placeholder stages (`--stub`) — pipeline runs with zero models |
| `autocwi/device.py` | cuda → mps → cpu selection (printed at startup), seeding |
| `autocwi/cli.py` | Subcommands: `live`, `run`, `transcribe`, `diarize`, `prosody`, `fuse` |

## The contract

**`CaptionSpec` (`spec.json`)** is the stable, versioned (currently `"1.0"`)
boundary between analysis and any consumer. Key semantics:

- `words[].loudness` / `pitch` — normalized **within each speaker**
  (5th–95th percentile of that speaker's own values) so mappings reflect each
  voice's own dynamic range. Raw `loudness_db` / `pitch_hz` kept alongside.
- `words[].voiced_frac` — used to neutralize pitch styling on unvoiced words
  (< 0.2 → pitch 0.5 / weight 400).
- `mapping` — how consumers should style: `loudness_to {axis, min, max, unit}`,
  `pitch_to {axis, min, max, invert, domain_hz}`. When `domain_hz` is set the
  consumer maps **raw Hz** over that domain (CWI's absolute pitch convention)
  instead of the normalized value. `unit: pct_video_height` means sizes are %
  of frame height.

**Live final-word events** (SSE `/events`, logged to `out/live_events.jsonl`)
use the same word shape plus `type: "word"`, `final: true`, `utterance`, and
`t` (absolute stream onset). Live `loudness` is normalized against a running
median and `pitch` is fixed 0.5 because rendering uses raw `pitch_hz`.
Display clients additionally receive `type: "hypothesis"` snapshots and
`type: "cue"`, `type: "commit"`, and `type: "verification"` events. White
hypothesis words are tentative and replace the prior snapshot. A cue
colors/pops an accurate-profile partial once, a commit is stable-stream text,
and verification atomically locks the phrase. Only the verifier-owned final
`word` events are written to the durable log or intended for haptic actuation.

A haptic module plugs in by consuming either source; it must never import
analysis code.

## Design decisions & rationale

- **Per-speaker loudness but absolute pitch.** Loudness expressiveness is
  relative to a voice's own range; CWI's pitch→weight scale is explicitly
  absolute (80 Hz heavy ↔ 250 Hz thin, 400 at 160–200 Hz), which also makes
  male/female voice contrast visible — so the renderer uses raw Hz.
- **Three recognition stages.** The 160 ms stream fills the
  unseen white tail immediately. The 1120 ms stream takes precedence wherever
  their timestamps overlap and emits provisional visual cues/commits. Parakeet
  Unified verifies a longer phrase at the endpoint; equal corrections preserve
  streaming timestamps, while insertions/deletions are monotonically aligned
  over the disputed span. This spends memory/CPU to avoid forcing one model to
  choose between latency and accuracy.
- **The two profiles decode concurrently.** Separate ONNX sessions run in a
  two-worker pool and the first completed update is published immediately.
  Four intra-model threads is the measured optimum on the target M1; combined
  RTF remains below one even on the included 2×-speed stress clip.
- **Only verified events are durable.** White hypotheses and colored commits
  may revise, but a final/haptic event is emitted once from the endpoint
  verifier and is never retracted. This is why the UI and long-lived event log
  consume distinct SSE message types.
- **Backlog is lossless.** Capture blocks carry their source-clock position and
  are drained into one inference batch after transient stalls. File pacing is
  deadline-based, so it runs flat-out rather than sleeping while behind. Only
  a real capture-device discontinuity resets the streams.
- **Two-layer level handling**: an adaptive `InputGain` drives only the
  recognizer's copy toward its training level (quiet speech otherwise decodes to
  nothing); the *raw* captured dBFS still feeds prosody, so type size reflects
  true loudness. On top of that the size mapping is anchored to the speaker's
  running-median baseline (`expression`) and stepped with hysteresis so ordinary
  speech does not modulate word to word.
- **SSE over stdlib http.server**, not websockets: one-way stream, browser
  `EventSource` auto-reconnects, zero extra dependencies. Events carry ids;
  committed/verified history is bounded and replayed from `Last-Event-ID`. A
  stalled tab is disconnected and resumes from history instead of accumulating
  an unbounded in-memory queue.
- **Self-contained HTML** (font as data URI, spec/config embedded): pages
  survive being moved, no CDN/CSP concerns, honest offline story.
- **Stubs as first-class** (`--stub`): contract and pipeline are testable
  with no model downloads; tests rely on this.

## Extension points

1. **Haptics** — consume final `type: "word"` messages from `/events` or read
   `spec.json`; map `loudness`/`pitch_hz` + timing to actuators. Ignore
   revisable `type: "hypothesis"` snapshots and provisional `type: "cue"`
   events.
2. **Offline video renderer** — was removed; if revived, consume only
   CaptionSpec (previous implementation followed CWI 2.2/2.4: read-ahead
   white 90%, onset color flip, captions box).
