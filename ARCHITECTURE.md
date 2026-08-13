# Architecture

Prosotype has three modes that share one analysis philosophy and one word-data
shape:

- **live** — captions from a microphone, in real time (the primary product);
- **offline** — a batch pipeline over recorded media that ends at `spec.json`;
- **`cc`** — the closed-caption renderer that plays a finished spec and is the
  motion reference the other two are measured against.

New to the terms? The [glossary](#glossary) is at the foot.

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
                                                        ├─► per-character voice envelope
                                                        └─► complete Transcript history
         level ─► separate meter frame (never caption layout)

offline:  media ─► transcribe ─► diarize ─► prosody ─► fuse ─► spec.json
          (audio) (asr)         (diarize)  (prosody)  (fuse)      │
                 words.json  segments.json prosody.json           ├─► future haptic module
                                                                  └─► cc ─► captions.html

reference:  screen recordings ─► derive_reference_spec ─► assets/reference_specs/*.json
            (+ transcript)       (measures the pixels)     └─► build_demo ─► demo.json
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

The browser reduces the event stream into stable, per-word DOM nodes and
presents them from a **playhead** that runs `display.read_ahead_delay_s` behind
the acoustic clock. Because ASR delivers a word after it was spoken, that delay
is what lets a word be on screen *before* its own colour turn — CWI 2.2.1's
read-ahead, without predicting anything. The pipeline:

```text
SSE event
  → merge by word_id (revisions collapse onto the same node)
  → recover acoustic time from `level.t`; the playhead trails it by the delay
  → freeze each word's turn moment: onset − clockOffset + delay
  → hand that to CSS as one `--turn-delay`
  → the browser schedules the 2.2.2 colour turn, the 2.2.3 pop and the
    2.3 per-character voice phase off it — no JS timer, no queue
```

There is no reveal scheduler: slots, gaps, catch-up and backlog ceilings all
existed to guess, from arrival order, a moment the recording already knows.

The load-bearing invariant: **text may be revised only ahead of the playhead.**
Once the colour turn passes a word it is frozen — spelling included — so
corrections land in the read-ahead zone where they are invisible. A settled
word's typography returns exactly to normal.
The frontend's non-negotiables are listed in
[web/README.md](web/README.md), and
[the project page](https://nobel2040ne.github.io/Prosotype/) shows the playhead running.

## Speaker attribution

Attribution runs live with four states — `unknown`, `provisional`, `stable`,
`corrected` — and only `stable`/`corrected` may signal a speaker change. Timing
and identity are separate evidence: Streaming Sortformer supplies continuous
provisional turn slots, and at each endpoint a segmentation pass plus a full-turn
voice embedding verifies the durable identity (ERes2Net for English, CAM++ for
Korean). [the project page](https://nobel2040ne.github.io/Prosotype/) shows the
four states and what each one may claim.

A haptic module plugs in by consuming either the SSE `word` events or `spec.json`
— it must never import analysis code.

## Design decisions & rationale

- **Per-speaker loudness, absolute pitch.** Loudness is relative to a voice's
  own range; CWI's pitch→weight scale is explicitly absolute (80 Hz heavy ↔
  250 Hz thin), which also makes voice-to-voice contrast visible.
- **Accuracy-first live path.** The streaming model gives fast provisional text;
  the endpoint verifier owns the durable result, aligned back onto the streaming
  timeline rather than re-rendering the sentence.
- **Verified text is durable; attribution is revisable** under the same
  `word_id`.
- **Backlog is lossless.** Capture blocks carry their source-clock position and
  drain into catch-up batches, so no audio is skipped.
- **Two-layer level handling.** Adaptive gain drives only the recognizer's copy;
  raw captured loudness still feeds prosody, so size reflects true loudness.
- **SSE over stdlib `http.server`.** One-way, automatic reconnect, no extra
  dependencies, replay from `Last-Event-ID`.
- **Stable `word_id` nodes** survive every revision; an update never replaces the
  stage, the line, or the word.
- **Stubs are first-class** (`--stub`): the contract is testable with no models.

## Extension points

**Haptics** — consume final `type: "word"` events, or read `spec.json`. Ignore
hypotheses, cues, commits and provisional speaker changes; apply same-`word_id`
revisions without re-actuating.

---

## Glossary

**Prosotype** — this project. "Prosody" (the melody of speech) + "type".

**Caption with Intention (CWI)** — the design system implemented here, from the
Chicago Hearing Society. Its three pillars:

| Pillar | Question | How |
|---|---|---|
| **Attribution** | who is speaking | one colour per speaker, in wheel order |
| **Synchronization** | when a word is spoken | it turns to that colour and pops as it is said |
| **Intonation** | how it was said | a variable font: louder is larger, pitch moves weight and width |

**Open captions** — burned into the view, not toggleable. Live mode renders
these.

### Speech processing

| Term | Meaning |
|---|---|
| **ASR** | automatic speech recognition; runs locally here |
| **Streaming ASR** | emits words as you speak, before the sentence ends — required for live |
| **Diarization** | who spoke when. It separates speakers; it does not name them |
| **Prosody** | the measurable qualities of *how* speech sounds: loudness, pitch, timing |
| **Endpoint** | the moment a phrase finishes. A more accurate pass runs there |
| **Onset** | the beginning of a word — the moment its colour turn is scheduled for |
| **WER / CER** | word / character error rate, the standard accuracy metrics |

### Models

| Name | Role |
|---|---|
| **Nemotron** | the English streaming recognizer |
| **Parakeet** | its endpoint verifier — owns the durable text |
| **Zipformer** | the Korean streaming recognizer (174M, causal) |
| **Sortformer** | streaming diarization, in Core ML on Apple Silicon |
| **ERes2Net / CAM++** | voice embeddings that confirm identity at an endpoint (EN / KO) |
| **Roboto Flex / Noto Sans KR** | the variable fonts; their axes are what carry intonation |

### Data & runtime

**CaptionSpec (`spec.json`)** — the versioned contract: words, timing, speaker,
loudness, pitch, and how to style them. **Every consumer reads only this**,
never the internal model objects. Defined in `autocwi/schema.py`.

**SSE** — a one-way stream from Python to the browser over plain HTTP. Live
captions arrive as `word` events; the browser reconnects and replays by itself.

**Stage** — the audience-facing caption surface. **Transcript** — the complete
history, by speaker and utterance. **Voice Compass** — the rail dial: volume,
pitch, texture, and where each speaker is.

**Haptics** — a motor ring that pulses on speaker changes and emphasis, never on
every word. It consumes the same contract and imports no analysis code.

### The three run modes

**live** — microphone to captions, in real time. The product.
**`cc`** — plays a finished `spec.json` with the text known in advance, so it
renders the exact reference motion. The benchmark, not the product.
**offline** — a batch pipeline ending at `spec.json`, kept as the contract's
reference generator.
