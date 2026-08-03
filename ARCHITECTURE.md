# Architecture

Prosotype has three modes that share one analysis philosophy and one word-data
shape:

- **live** — captions from a microphone, in real time (the primary product);
- **offline** — a batch pipeline over recorded media that ends at `spec.json`;
- **`cc`** — the closed-caption renderer that plays a finished spec and is the
  motion reference the other two are measured against.

New to the terms here (ASR, diarization, prosody, CaptionSpec, SSE)? See the
[glossary](ARCHITECTURE.md#glossary).

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
                                                        ├─► per-character voice envelope
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
The full behavioral detail is in [docs/LIVE.md](docs/LIVE.md), and the frontend's
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

---

## Glossary

Plain-language definitions of the terms used throughout this project. If a term
in the code or docs is unclear, it should be here — if it isn't, please add it.

### Product & domain

**Prosotype** — the name of this project: an application that turns live speech
into expressive captions. "Prosody" (the melody and rhythm of speech) + "type"
(typography).

**Caption with Intention (CWI)** — the published design system we implement. It
specifies how captions should look and move so that Deaf and hard-of-hearing
viewers can follow *who* is speaking, *when* each word is spoken, and *how* it
is said. Authored by the Chicago Hearing Society. The V1.0 PDF is the single
source of truth for the visual design; see [docs/RESEARCH.md — sources](docs/RESEARCH.md#sources).

**Deaf / hard-of-hearing (Deaf/HoH, DHH)** — the primary audience. The whole
design exists to give this audience information that hearing viewers get for
free from the audio.

**Open captions** — captions burned into the view that everyone sees (as
opposed to *closed* captions the viewer can toggle). Our live mode renders open
captions in the browser.

#### The three CWI pillars

**Attribution** — *who is speaking.* Each speaker is assigned a distinct color
(yellow, green, blue, pink, red, orange, in that wheel order). A word is drawn
in its speaker's color.

**Synchronization** — *when a word is spoken.* As each word begins, it turns
from white to its speaker's color and does a brief "pop" (a small size increase
and lift, then a return to normal). This points the viewer's eye at the word
being said right now.

**Intonation** — *how a word is spoken.* The typography carries the voice:
louder speech is larger, and pitch changes the font weight and width. This uses
a *variable font* (see below).

### Speech processing

**Automatic speech recognition (ASR)** — turning audio into text. We run
recognizers locally (no cloud).

**Streaming / online ASR** — recognition that emits words continuously as you
speak, before the sentence is finished. Required for live captions. Contrasted
with offline recognition, which processes a whole recording at once.

**Diarization** — "who spoke when": splitting audio into speaker turns. It does
not identify names, only that speaker A differs from speaker B.

**Prosody** — the measurable qualities of *how* speech sounds: loudness, pitch,
and timing. Prosody drives the Intonation pillar.

**Endpoint** — the moment a phrase finishes (a pause). At an endpoint we run a
more accurate verification pass over the completed phrase.

**Onset** — the very beginning of a word or speech sound. The *onset sidecar* is
an optional component that guesses the first few letters of a word from its
opening sounds (e.g. `H → He → Hel`) so a drawn-out word can start appearing
before the recognizer commits to full spelling.

**Word error rate (WER)** — the standard accuracy metric for ASR: the fraction
of words inserted, deleted, or substituted compared to a reference transcript.

### Models & components

**Nemotron / Parakeet** — the English streaming recognizer (Nemotron) and its
endpoint verifier (Parakeet). Nemotron gives fast provisional text; Parakeet
re-checks each finished phrase.

**Zipformer** — the Korean streaming recognizer (a 174M-parameter causal
model).

**Sortformer** — the streaming diarization model (from NVIDIA) that tracks
speaker turns in real time on Apple Silicon.

**Speaker embedding** — a numeric "voiceprint" used to confirm a speaker's
identity at an endpoint. English uses a model called ERes2Net; Korean uses
CAM++.

**Variable font** — a font whose weight, width, and other axes can be set to any
value continuously, not just a few presets. We use Roboto Flex (English/Latin)
and Noto Sans KR (Korean). This is what lets typography track pitch smoothly.

### Data & runtime

**CaptionSpec (`spec.json`)** — the versioned data contract. It is the single,
stable description of a caption: the words, their timing, speaker, loudness,
pitch, and how to style them. **Every consumer (the renderer, a future haptic
device) reads only the CaptionSpec — never the internal model objects.** See
[../ARCHITECTURE.md](../ARCHITECTURE.md).

**Server-Sent Events (SSE)** — a one-way stream from the Python server to the
browser over plain HTTP. Live captions arrive as SSE `word` events. The browser
reconnects automatically and can replay missed events.

**Stage** — the main audience-facing caption surface in the studio UI: a stable
stack of the most recent caption rows.

**Transcript** — the secondary UI surface that keeps the complete history of
what was said, organized by speaker and utterance.

**Voice Compass** — the side-rail indicator that shows continuous voice
qualities (volume, pitch, brightness) as shapes, separate from the caption text.
It reserves a direction marker for future multi-microphone input. A second,
line-edge copy of the same channels (the "voice circle") sat beside the active
caption until 2026-08-04; the stage now carries captions only.

**Haptics** — physical/vibration feedback. Not built yet. A future haptic module
would subscribe to the same CaptionSpec / SSE contract and buzz on meaningful
events (speaker changes, emphasis) rather than every word.

### The three run modes

**Live** — the primary mode. Microphone → CWI-styled captions in the browser, in
real time.

**`cc` (closed-caption renderer)** — plays a finished `spec.json` with the text
known in advance. Because the future is known, it renders the *exact* reference
CWI motion. It is the visual benchmark the live mode is measured against.

**Offline** — a batch pipeline (`media → transcribe → diarize → prosody → fuse`)
that ends at `spec.json`. Kept as the reference generator for the CaptionSpec
contract.
