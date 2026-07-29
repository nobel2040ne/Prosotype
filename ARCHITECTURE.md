# Architecture

Prosotype has three modes that share one analysis philosophy and one word-data
shape:

- **live** — captions from a microphone, in real time (the primary product);
- **offline** — a batch pipeline over recorded media that ends at `spec.json`;
- **`cc`** — the closed-caption renderer that plays a finished spec and is the
  motion reference the other two are measured against.

New to the terms here (ASR, diarization, prosody, CaptionSpec, SSE)? See the
[glossary](docs/GLOSSARY.md).

## Contents

- [System diagram](#system-diagram)
- [Module map](#module-map)
- [The data contract](#the-data-contract)
- [How live rendering works](#how-live-rendering-works)
- [Speaker attribution](#speaker-attribution)
- [Design decisions & rationale](#design-decisions--rationale)
- [Extension points](#extension-points)

## System diagram

```
live: startup UI ─► lock en/ko ─► load matching local recognizer ─► begin capture

      mic/file ─► lossless batcher ─► input gain ─┬─► EN 1120ms ─► read-ahead/commit ─┐
      (recognizer copy only; prosody reads raw)   ├─► 160ms draft (readahead only) ──┤
                                                  ├─► Parakeet verifier ─► final ────┤
                                                  └─► KO 174M/320ms ─► final ────────┤
                                                                                     ├─► CaptionSpec/SSE
      audio ─► native Streaming Sortformer ─► provisional turn slots ────────────────┤
            └─► endpoint segmentation + identity embedding ─► stable/corrected ──────┘        │
                                      unknown | provisional | stable | corrected             ├─► Next.js studio
                                                                                             │   (static export)
                                                                                             ├─► legacy live.html
                                                                                             └─► durable haptics

browser: SSE ─► revision reducer ─► per-word reveal queue ─► stable word identity
                                                        ├─► six-row audience stack
                                                        ├─► acoustic sequential reveal
                                                        ├─► one first-paint voice envelope
                                                        └─► complete Transcript history
         level ─► separate meter frame (never caption layout)

offline:  media ─► transcribe ─► diarize ─► prosody ─► fuse ─► spec.json
          (audio) (asr)         (diarize)  (prosody)  (fuse)      │
                 words.json  segments.json prosody.json           ├─► future haptic module
                                                                  └─► cc ─► captions.html

reference:  docs/reference/*.mov ─► derive_reference_spec ─► assets/reference_specs/*.json
            (+ transcript)          (measures the pixels)      └─► build_demo ─► demo.json
```

## Module map

### Live engine

| Module | Responsibility |
|---|---|
| `autocwi/live.py` | The live engine and startup controller. Locks the English/Korean choice before capture, loads the matching recognizer, batches the mic/file source losslessly, applies adaptive input gain (recognizer copy only), runs recognition and hybrid diarization, and serves the replayable HTTP + SSE endpoints. |
| `autocwi/sortformer.py` | Thread-safe bridge to the native Core ML diarizer. Keeps its timeline off the ASR thread and projects speaker spans onto words. |
| `native/sortformer/` | Swift 6 helper (pinned to FluidAudio 0.15.5) that runs NVIDIA Streaming Sortformer v2.1 in Core ML on Apple Silicon and emits finalized/tentative speaker timelines. |

### Frontend

| Module | Responsibility |
|---|---|
| `web/` | Next.js App Router studio. Builds to a static export that Python serves at `/`. Provides the pre-capture language gate, the Stage/Transcript views, presentation settings, speaker cards, and the voice indicators — with no Node runtime. |
| `web/src/lib/caption-store.ts` | Pure event reducer: stable word identity, independent revision channels, source/finality authority, and the reveal deadline policy. |
| `web/src/lib/caption-paragraphs.ts` | Pure layout partitioner: Transcript keeps complete paragraphs; Stage flattens them into stable eight-word rows and keeps the newest six. |
| `web/src/hooks/use-caption-stream.ts` | Client boundary for the language session, the event stream, the reveal scheduler, reconnect state, and the `?demo=1` preview. |
| `autocwi/livepage.py` | Generates the legacy `live.html` renderer (kept as a fallback and diagnostic tool). |
| `autocwi/live_render_core.js` | Dependency-free ordering/reduction core shared by the legacy page and its Node tests. |

### Reference renderer (`cc`)

| Module | Responsibility |
|---|---|
| `autocwi/ccpage.py` | Generates `captions.html` (and `tuner.html` with `--tune`). Because the text is known in advance, read-ahead, the color sweep through a word, and per-word motion are all exact. Playback is a pure function of time, so scrubbing reproduces a frame exactly. |
| `autocwi/ccprosody.py` | Python mirror of the page's typography map, plus its inversion (measured emphasis → the loudness/pitch that reproduce it). Pinned to the JavaScript by a golden grid so the two can't drift. |
| `autocwi/refmeasure.py` | Shared pixel-measurement code: glyph segmentation, color-turn timing, scroll recovery. One implementation so the recording and our own render are measured identically. |

### Offline pipeline

| Module | Responsibility |
|---|---|
| `autocwi/asr.py` | Offline ASR (faster-whisper): word timestamps + confidence. |
| `autocwi/diarize.py` | pyannote diarization (gated weights → `HF_TOKEN`); relabels speakers to S1, S2… by first appearance. |
| `autocwi/prosody.py` | Per-word loudness (RMS dB) and pitch (median F0 + voiced fraction), restricted to ASR word spans. |
| `autocwi/fuse.py` | Assigns words to speakers, normalizes loudness/pitch per speaker, assigns the palette, and emits a validated CaptionSpec. |
| `autocwi/schema.py` | The CaptionSpec models (Pydantic v2) plus JSON I/O. **The versioned contract.** |
| `autocwi/audio.py` | ffmpeg/ffprobe helpers: probe duration/fps, extract 16 kHz mono wav. |
| `autocwi/stubs.py` | Deterministic placeholder stages (`--stub`) so the pipeline runs with zero models. |
| `autocwi/device.py` | Compute-device selection (cuda → mps → cpu) and seeding. |
| `autocwi/cli.py` | Subcommands: `live`, `run`, `cc`, `tune`, `transcribe`, `diarize`, `prosody`, `fuse`. |

### Reference derivation

| Module | Responsibility |
|---|---|
| `scripts/derive_reference_spec.py` | Turns a recording + transcript into a validated CaptionSpec by measuring the pixels. |
| `scripts/build_demo.py` | Concatenates the three derived specs onto one timeline (`demo.json`). |
| `scripts/live_render_probe.py` | Injects a deterministic event burst into the pages in headless Chrome and reports DOM, queue, and motion metrics. |

## The data contract

**`CaptionSpec` (`spec.json`)** is the stable, versioned (currently `"1.0"`)
boundary between analysis and any consumer. Renderers and the future haptic
module read only this — never the internal model objects.

Key semantics:

- `words[].loudness` / `pitch` — normalized **within each speaker** (5th–95th
  percentile of that speaker's own values), so the mapping reflects each voice's
  own range. Raw `loudness_db` / `pitch_hz` are kept alongside.
- `words[].voiced_frac` — used to neutralize pitch styling on unvoiced words.
- Optional speaker-lifecycle fields: `speaker_status`
  (`unknown | provisional | stable | corrected`), `speaker_confidence`,
  `speaker_change_probability`, `speaker_revision_id`, and `overlap`. A legacy
  word with none of these is treated as a stable assignment to its existing
  `speaker`.
- `mapping` — how consumers should style: `loudness_to {axis, min, max, unit}`
  and `pitch_to {axis, min, max, invert, domain_hz}`. When `domain_hz` is set,
  the consumer maps **raw Hz** over that domain (CWI's absolute pitch
  convention).

Example additive word fields:

```json
{
  "speaker": "S1",
  "speaker_status": "provisional",
  "speaker_confidence": 0.72,
  "speaker_change_probability": 0.81,
  "speaker_revision_id": 4,
  "overlap": false
}
```

Every new field here is optional, so no version bump was needed and `1.0` files
still validate. Absence means "legacy stable", **not** `unknown`.

**Live events** (SSE `/events`, logged to `out/live_events.jsonl`) use the same
word shape plus `type: "word"`, `final: true`, `utterance`, a stable `word_id`,
revision counters, and `t` (absolute stream onset). Display clients also receive
`type: "hypothesis"`, `"cue"`, `"commit"`, and `"verification"` events during the
speech lifecycle; only `type: "word"` events are durable. Reconnect replays from
`Last-Event-ID` without replaying motion.

The renderer compares text, timing, speaker, finality, source authority, and SSE
id rather than trusting arrival order, so a delayed provisional event cannot
downgrade a settled word.

## How live rendering works

The browser reduces the event stream into stable, per-word DOM nodes and gives
each word its motion exactly once, at first paint. The pipeline:

```text
SSE event
  → merge by word_id, coalesce a burst into one animation frame
  → update text / attribution / finality only if changed
  → queue unseen words in acoustic order (at most two active)
  → reserve a slot + freeze the word's acoustic snapshot
  → the word's layout commit confirms first paint and starts the clock
  → one phase-locked size/lift/weight/width motion, then a return to normal
  → an independent color sweep; later revisions reuse the same node
```

The load-bearing invariant: **a word animates once and then settles.** Later
corrections (spelling, timing, speaker, color) update it in place but never
restart its motion, and a settled word's typography returns exactly to normal.
The full behavioral detail — reveal scheduling, the throughput-aware duration,
the Stage stack, delivery dynamics — is in
[docs/LIVE.md](docs/LIVE.md), and the frontend's
non-negotiables are listed in [web/README.md](web/README.md).

## Speaker attribution

Attribution runs live with four states — `unknown`, `provisional`, `stable`,
`corrected` — and only `stable`/`corrected` may signal a speaker change. Timing
and identity are separate evidence: Streaming Sortformer supplies continuous
provisional turn slots, and at each endpoint a segmentation pass plus a full-turn
voice embedding verifies the durable identity (ERes2Net for English, CAM++ for
Korean). See [docs/LIVE.md](docs/LIVE.md#speaker-attribution)
for the full behavior.

A haptic module plugs in by consuming either the SSE `word` events or `spec.json`
— it must never import analysis code.

## Design decisions & rationale

- **Per-speaker loudness, absolute pitch.** Loudness expressiveness is relative
  to a voice's own range, but CWI's pitch→weight scale is explicitly absolute
  (80 Hz heavy ↔ 250 Hz thin), which also makes male/female contrast visible —
  so the renderer uses raw Hz for pitch.
- **Accuracy-first live path.** The streaming model gives fast provisional text;
  the endpoint verifier owns the durable result. Corrections are aligned back
  onto the streaming timeline rather than re-rendering the sentence.
- **Draft inference is demand-driven.** The low-latency 160 ms model loads only
  in `readahead` mode. Running it hidden wasted CPU the accurate path needed.
- **Verified text is durable; attribution is revisable.** The verifier owns text,
  but a word's speaker may still firm up later under the same `word_id`.
- **Backlog is lossless.** Capture blocks carry their source-clock position and
  are drained into catch-up batches after a stall, so no audio is skipped.
- **Two-layer level handling.** Adaptive gain drives only the recognizer's copy
  toward its training level; raw captured loudness still feeds prosody, so size
  reflects true loudness.
- **SSE over stdlib `http.server`, not websockets.** One-way stream, automatic
  browser reconnect, zero extra dependencies, replay from `Last-Event-ID`.
- **Frame-coalesced in-place rendering.** Stable `word_id` nodes survive text,
  verification, and attribution revisions; ordinary updates never replace the
  stage, line, or word node.
- **Self-contained HTML** (fonts as data URIs, config embedded): pages survive
  being moved, with no CDN or CSP concerns.
- **Stubs as first-class** (`--stub`): the contract and pipeline are testable
  with no model downloads. The offline tests rely on this.

## Extension points

1. **Haptics** — consume final `type: "word"` events from `/events`, or read
   `spec.json`; map loudness/pitch + timing to actuators. Ignore revisable
   hypotheses/cues/commits and provisional speaker changes, and apply
   same-`word_id` revisions to state without re-actuating.
2. **Offline video renderer** — removed; if revived, it should consume only
   CaptionSpec (the previous implementation followed CWI §2.2/§2.4: white
   read-ahead, onset color flip, the captions box).
