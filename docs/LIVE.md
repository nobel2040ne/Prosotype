# Live captions in depth

Live mode is the primary product: a microphone streams into CWI-styled open
captions in the browser, in real time. This document explains how it behaves.
For the system diagram and data contract, see
[../ARCHITECTURE.md](../ARCHITECTURE.md); for terminology, see
[GLOSSARY.md](GLOSSARY.md).

## Running it

```bash
.venv/bin/python -m autocwi live                 # microphone; choose English/한국어 first
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --lang ko   # bundled Korean clip
.venv/bin/python -m autocwi live --file clip.wav # stream a file as if live
.venv/bin/python -m autocwi live --lang en|ko    # skip the picker
.venv/bin/python -m autocwi live --list-devices  # pick a microphone
```

It opens `http://127.0.0.1:7337/` — the statically exported **Prosotype Studio**
(Next.js). The Python process serves the UI, the fonts, the runtime
configuration, and the live event stream from one origin; Node is not needed
while captioning. The original diagnostic renderer stays available at `/legacy`
and is used automatically if the studio hasn't been built.

## Choosing a language

Language is a **pre-capture decision**. With no `--lang`, a full-screen startup
gate asks for English or 한국어 *before* any recognizer loads and before capture
starts. The choice is locked for the session, so the recognizer can never be
relabeled or swapped mid-capture. `--lang en|ko` skips the gate for scripted or
headless runs.

## Recognition

**English** runs an accuracy-first path. A streaming recognizer (Nemotron)
produces fast provisional text, and at each phrase end a verifier (Parakeet)
re-checks the completed phrase and owns the durable result. A lower-latency
160 ms draft model exists but is loaded only in the explicit `readahead` display
mode — running it hidden wasted CPU without improving the visible captions.
Endpoint corrections (insertions, deletions, replacements) are aligned back onto
the streaming word timeline rather than re-rendering the sentence.

**Korean** runs a single 174M causal Zipformer (320 ms chunks), trained on
~6,500 hours of Korean speech. It finalizes directly at each phrase end. Its
timed, leading-space tokens preserve Korean 어절 (word) boundaries. Korean does
not use the English-only verifier or onset sidecar.

Because Roboto Flex has no Hangul outlines, Korean captions render with the local
Noto Sans KR variable font so pitch can still drive a continuous weight change.

### The onset sidecar (English, optional)

A separate phoneme lane can build a conservative prefix at the start of a word,
revealing `H → He → Hel` while "Hello" is still being drawn out. The
authoritative recognizer then revises that same word in place to the full
spelling. Because sound-to-spelling is ambiguous, the hint is transient,
confidence-gated, and never written to the durable event log.

## Speaker attribution

Attribution (the CWI "who is speaking" pillar) runs live with four states:

| State | Meaning | Rendering |
|---|---|---|
| `unknown` | no defensible assignment | white |
| `provisional` | a revisable estimate | subdued color + dotted underline |
| `stable` | enrolled and confident | full speaker color; eligible for haptics |
| `corrected` | a stable assignment replacing an earlier one | recolored in place |

Only `stable` and `corrected` may signal a speaker change to downstream
consumers (`speaker_change: true`). Tuning lives under
`live.speaker_attribution` in `config.yaml`.

**How identity is decided.** On Apple Silicon the default backend runs NVIDIA
Streaming Sortformer continuously through a native Core ML helper for
low-latency, arrival-ordered speaker activity. At each phrase end, a segmentation
pass plus a full-turn voice embedding verifies the durable identity (English uses
ERes2Net; Korean uses the faster multilingual CAM++). The first two speakers
(S1/S2) stay immediate and provisional for responsiveness. A third-or-later
identity stays neutral until repeated clean observations confirm it, after which
earlier pending words are revised in place — this is evidence gating, **not a
two-speaker cap**.

If Sortformer misses quiet speech, sees more than four speakers, or isn't
available (non-Apple-Silicon platforms), the system falls back to the endpoint
segmentation/embedding tracker without dropping captions. Make the choice
explicit with `--diarizer sortformer|embedding|off`.

## Display modes

`display.mode` in `config.yaml` controls what reaches the Stage:

| Mode | Behavior |
|---|---|
| `fast` (default) | committed words plus the accurate stream's white tail (~35% less revision than the draft) |
| `stable` | committed words only |
| `sentence` | one finalized turn at a time |
| `readahead` | also loads the 160 ms draft — lowest latency, visibly revises |

In every mode, a word that has settled is protected from stale rollback.

## The Stage stack

Live captions use a stable, left-aligned stack that grows upward:

- Each row holds as many words as the stage can carry at a legible size (three
  to six, measured — a narrow window takes shorter rows and larger type rather
  than shrinking the captions to fit six across). Completed rows stay put while
  the active row grows; older rows move into the Transcript view rather than
  piling up on screen.
- The stack keeps **as many rows as the stage can actually hold** — measured in
  the browser from the stage's own height and a real row's height, so the
  captions fill the surface instead of scrolling while it is half empty
  (measured at 1440×900: nine rows on the light stage, eight on the dark one,
  which puts extra padding on every row). Every currently recognized word stays
  visible in that stack.
- Row identity comes from the first word's stable ID, so adding a ninth word or
  correcting a speaker **cannot remount earlier words or replay their motion**.
- Neither provisional utterance segmentation nor diarization controls row
  geometry — both remain semantic boundaries in the Transcript only. This
  prevents pending attribution from creating one-word rows.
- When a new bottom row appears, retained rows glide upward (540 ms) and the new
  row eases in (620 ms). This entry animation is keyed only to a genuinely new
  bottom row — text, color, speaker, removal, and reappearance updates cannot
  replay it. Reduced-motion mode skips it.

The **Transcript** view keeps the complete history, split into paragraphs by
speaker and utterance.

## Voice indicators

Two indicators show continuous voice qualities *without* touching the caption
glyphs (so completed captions never shake when a later audio block arrives):

- The **voice circle** sits just after the active caption. Its radius follows
  true captured volume, its bead height follows pitch, and its inner texture
  follows periodicity and brightness.
- The larger **Voice Compass** in the side grid mirrors those channels and
  reserves an angular marker for a future multi-microphone direction estimate.
  Mono input explicitly displays `awaiting array` rather than inventing an
  angle.

## Live motion

Motion is a **one-time interpretation of the voice**, not a permanent font
style. Each word's motion is scheduled by the playhead — at its own recorded
onset — so the browser runs it from a single `animation-delay`. The key rules:

- Words animate at their spoken onset, concurrently if speech is fast. There is
  no concurrency cap: overlapping pops during quick speech are the design system
  working, not a scheduling failure.
- Every word starts and ends at normal 5% / Regular 400 / width 100 typography.
  During its one motion window, volume shapes size, pitch shapes weight, and the
  harmonics proxy shapes width — **per character**, sampled from the word's own
  intonation contour (§2.3, PDF pp.34/38/40). Those values are transient and
  cannot restyle a completed word.
- **Every word receives the same synchronization cue as it turns colour**: a
  15% increase in type size with a 25% rise, then back (§2.2.3). This cue is
  independent of the voice-shaped axes and of the Expression control.
- Normal type is an invisible layout sizer and the moving glyph is overlaid.
  Therefore motion cannot reflow a row, needs no browser width measurement, and
  drops back to normal even if logical animation cleanup is delayed.
- The reveal schedule is anchored to acoustic timing; a slow frame doesn't
  restart the gap. During fast speech the motion duration shortens (down to a
  320 ms floor) so the three-slot pipeline never accumulates a growing backlog;
  ordinary speech keeps the full duration.
- Speaker color has a **separate clock** (a white→color sweep), so a late speaker
  decision can recolor a settled word but can never make it move again.
- Corrections — spelling, timing, attribution, replay — reuse the same word node
  and never restart its motion.

Because a microphone can't know future words, live motion always begins at a
word's first real appearance. This is the main way live differs from the `cc`
reference renderer, which knows the text in advance and can lead the motion.

### Delivery dynamics

Beyond loudness and pitch, live mode measures the *delivery* of each word —
force, attack, pitch contour, voiced flow, and texture — and selects a distinct
one-time motion path (rising, falling, sustained, forceful, gentle, textured).
All paths return to identity. **These are descriptions of the sound, not
emotion claims** — the system never labels a speaker as angry, happy, or sad.
Categorical speech-emotion classification is deliberately *not* in the motion
loop; see [RESEARCH.md](RESEARCH.md).

## Input level

Quiet speech is a real problem: recognizers stop emitting below their training
level. An adaptive gain lifts the *recognizer's copy* of the audio toward that
level, while the **true** captured loudness still drives the size motion (so a
whisper and a shout don't look identical). The header **Input** meter shows live
level, noise floor, and gain, so a dead or too-quiet mic is visible without
speaking. Tune with `live.input_gain`, `--gain DB`, or `--no-gain`.

## Haptics (future)

Durable `word` events carry salience flags (`speaker_change`, `emphasis`, using
the `haptics.emphasis_db` threshold) so a future haptic device can buzz
selectively — on speaker changes and emphasis, not every word. Nothing consumes
these yet.

## Diagnostics

- `display.debug_render` and `?renderdiag=1` expose per-word render diagnostics.
- `window.__cwiStudio.report()` (studio) summarizes the read-ahead playhead and
  motion state; `window.__cwiRenderDiag.report()` (legacy) summarizes the older
  renderer's playhead schedule.
- `scripts/live_render_probe.py` injects a deterministic event burst into a
  headless browser and reports DOM, queue, and motion metrics.

See [TESTS.md](TESTS.md) for the measurement recipes and observed ranges.
