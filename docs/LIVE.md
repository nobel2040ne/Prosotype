# Live captions in depth

Live mode is the primary product: a microphone streams into CWI-styled open
captions in the browser, in real time. This document explains how it behaves.
For the system diagram and data contract, see
[../ARCHITECTURE.md](../ARCHITECTURE.md); for terminology, see
[ARCHITECTURE.md — glossary](../ARCHITECTURE.md#glossary).

## Running it

```bash
.venv/bin/python -m autocwi live                 # microphone; choose English/한국어 first
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --lang ko   # bundled Korean clip
.venv/bin/python -m autocwi live --file clip.wav # stream a file as if live
.venv/bin/python -m autocwi live --lang en|ko|multi  # skip the picker
.venv/bin/python -m autocwi live --list-devices  # pick a microphone
```

It opens `http://127.0.0.1:7337/` — the statically exported **Prosotype Studio**
(Next.js). The Python process serves the UI, the fonts, the runtime
configuration, and the live event stream from one origin; Node is not needed
while captioning. The original diagnostic renderer stays available at `/legacy`
and is used automatically if the studio hasn't been built.

## Choosing a language

Language is a **pre-capture decision**. With no `--lang`, a full-screen startup
gate offers **English / 한국어 / Bilingual** *before* any recognizer loads and
before capture starts. The choice is locked for the session, so the recognizer
can never be relabeled or swapped mid-capture. `--lang en|ko|multi` skips the
gate for scripted or headless runs. The gate builds its buttons straight from
`live.languages`, so a profile added there appears with no UI change.

### Bilingual (`multi`)

One model for both languages, for a session where either may be spoken —
including **inside one sentence** (`디자인 system이`), which neither
single-language model can do. It runs
`nvidia/nemotron-3.5-asr-streaming-0.6b`: 40 language-locales in 600M
parameters, cache-aware streaming at the same 1120 ms chunk the English path
uses. Measured end to end on the bundled clips with no language hint — Korean 13
words, English 161, RTF 0.060/0.061 against the Korean Zipformer's 0.055.

**It is an addition, not a replacement.** English and Korean keep their own
models and their own numbers (2.27% WER / 10.54% CER). Nemotron 3.5 A/B'd *worse*
on English here — 3.25% against 2.27% — so making it the only recognizer would
trade a 43% relative English regression for the Korean gain. A test pins that the
single-language profiles carry no `streaming_language`.

**The language is a per-STREAM option.** The multilingual encoder takes a 6th
input (`prompt_index`), which sherpa-onnx exposes as
`stream.set_option("language", "auto")` — *not* as a recognizer argument. So
`_new_stream` applies it at every stream creation, **including the reset after
each endpoint**; a stream opened without it silently decodes under the model's
default. `auto` is the model's own language ID, which NVIDIA measures at 7.30%
Korean CER against 7.12% with the language named.

**Two things that would have broken it quietly.** sherpa's CJK formatter strips
spaces from the formatted `text`, which would collapse a whole Korean caption
into one word and destroy every per-word timing, motion and row break — the
tokens carry the boundaries as standalone `' '` tokens, and `hypothesis_words`
already handles that case. And the caption face must cover both scripts:
`[data-language="multi"]` lists Roboto Flex *first* so Latin keeps the variable
axes CWI drives, with Noto Sans KR behind it for Hangul, because font fallback
is per glyph.

It needs sherpa-onnx built from master (PR #3671, merged but unreleased); see
[KOREAN-ASR.md](KOREAN-ASR.md).

## Recognition

**English** runs an accuracy-first path. A streaming recognizer (Nemotron)
produces fast provisional text, and at each phrase end a verifier (Parakeet)
re-checks the completed phrase and owns the durable result. A lower-latency
160 ms draft model exists but is loaded only in the explicit `readahead` display
mode — running it hidden wasted CPU without improving the visible captions.
Endpoint corrections (insertions, deletions, replacements) are aligned back onto
the streaming word timeline rather than re-rendering the sentence.

**Korean** runs a single 174M causal Zipformer (640 ms chunks), trained on
~6,500 hours of Korean speech. It finalizes directly at each phrase end. Its
timed, leading-space tokens preserve Korean 어절 (word) boundaries. Korean does
not use the English-only verifier or onset sidecar.

Because Roboto Flex has no Hangul outlines, Korean captions render with the local
Noto Sans KR variable font so pitch can still drive a continuous weight change.

### The onset sidecar (English, optional)

**This ships OFF** (`live.onset_prefix.enabled: false`), and Korean never had it.
A separate phoneme lane can build a conservative prefix at the start of a word,
revealing `H → He → Hel` while "Hello" is still being drawn out. The
authoritative recognizer then revises that same word in place to the full
spelling. Because sound-to-spelling is ambiguous, the hint is transient,
confidence-gated, and never written to the durable event log.

It was disabled because it reset after silence and therefore fired at the start
of **every sentence**, where it read as a hitch. Measured: 39 text changes with
it on, 14 of them from a 1–2 letter stub, against 23 and 0 with it off — roughly
40% of all visible churn. It is *not* the ~1.3 s sentence stall (1261 ms on,
1315 ms off). **Do not confuse it with CWI 2.2.1 read-ahead**, which is the
design system's uncoloured preview of the line; that confusion has cost a round
trip before. If it is ever re-enabled it owns a provisional prefix, not durable
spelling: extensions need repeated compatible observations, no onset event may
enter `live_events.jsonl`, and no prefix revision may replay motion.

## Speaker attribution

Attribution (the CWI "who is speaking" pillar) runs live with four states:

| State | Meaning | Rendering |
|---|---|---|
| `unknown` | no defensible assignment — the event carries **no speaker** | neutral |
| `provisional` | a revisable estimate | subdued color + dotted underline |
| `stable` | enrolled and confident | full speaker color; eligible for haptics |
| `corrected` | a stable assignment replacing an earlier one | recolored in place |

Only `stable` and `corrected` may signal a speaker change to downstream
consumers (`speaker_change: true`). Tuning lives under
`live.speaker_attribution` in `config.yaml`.

**An undecided word carries no speaker at all.** It used to carry the fallback
id `S1`, on the basis that the renderer drew unknowns neutrally anyway; once
that stopped being true, every unattributed word was being painted in the
narrator's colour — measured, 46% of words were the wrong colour when the
playhead reached them. A word is now drawn neutral until its speaker has
actually been measured. Read-ahead words are attributed from the continuous
Sortformer timeline where it has an answer, which is most but not all of them.
Measure it with `scripts/speaker_probe.py`.

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

**A character who speaks once is still a character.** On the PR film — eleven
speakers, most with a single line — the tracker once produced *one* speaker
switch in 68 seconds and put the drill sergeant in the narrator's colour, which
is the whole of CWI 2.1 failing. Both causes were in the guards, not the
embeddings:

- **The margin guard blocked enrollment.** `min_confidence_margin` exists so a
  word is not handed to the wrong *enrolled* speaker when two profiles score
  alike. It is meaningless when nobody is a plausible match — four new voices
  arrived at best/second scores that were the strongest possible evidence for
  someone NEW, and every one was called ambiguous. It applies only above
  `provisional_threshold` now.
- **Stability required a repeat a one-line character never gets.**
  `_profile_is_stable` demanded two distinct endpoint groups, so everyone after
  the second speaker was permanently grey. It now also accepts one long turn —
  gated on the **longest single observation**, never on `enrolled_durations`,
  because two clean fragments of one endpoint sum to the same number and are not
  independent evidence (a test pins exactly that).

Measured: profiles 5 → **11**, speaker switches 1 → **10**, words with no
speaker 19 → 5. `max_speakers` is **12**, not 6: 2.1.2 defines twelve supporting
colours and `assignSpeakerColors` generates 2.1.4 pastels beyond.

**Colour stability is a separate question from colour correctness**, and it needs
its own measurement — a 45.9% → 29.2% correctness win left the flicker completely
untouched. The colour was changing every 8.6 words *inside sentences spoken by one
person*, and each change asserts a turn that did not happen. The fix is an
interaction and neither half works alone: `speaker_min_run_words` 3 **and**
re-smoothing the hybrid's output. `label_words` used to override the smoothed
fallback per word and return unsmoothed, so the rule could never reach the output
however it was tuned. Raising the run length is safe because the rule skips the
first and last word of an utterance and fires only when both sides agree, leaving
a genuine two-word turn unchanged — but 5 is too far (settled speakers drop
8 → 7). The smoother must also `_record`, or `drain_revisions` can un-smooth a
word it just fixed.

### The structural ceiling: four slots cannot represent eleven speakers

Sortformer is doing **all** of the on-time attribution — with it off, 88.7% of
words are neutral at their turn and only 7.9% are correct, while the final answers
are unchanged. It takes correct-at-turn **7.9% → 50.3%**. So it is not
underperforming; the limit is that it has four slots and reuses them across
eleven speakers (one slot published S1 ×76, S8 ×56 and S10 ×40 in a single pass),
which is why ~47% of words first paint in one speaker's colour and finish in
another.

**Precision and context are therefore the wrong knobs, and this is settled.**
Every preset — `fastV2_1` palettized, `fastV2_1` fp16, `balancedV2_1`,
`balancedV2` — lands at 49.7–50.9% correct, inside run-to-run noise, at the same
1.04 s latency. **fp16 is a no-op** at 2.5× the model size. Do not re-litigate
without a new measurement. The
levers that remain are more slots (`ultra_diar_streaming_sortformer_8spk_v1` —
Apache-2.0 and fine-tuned from our exact base, but unbenchmarked, NeMo-only, and
FluidAudio hardcodes four slots) or an on-time signal that is not Sortformer.

**Mid-utterance verification was built both ways and neither shipped.** Without
enrollment it is a no-op; with enrollment it *merges speakers*, because spans cut
at commit boundaries straddle real turns and the mixed embedding enrolls a
centroid that swallows everyone — one utterance went from three speakers to one.
**And it looked like a win:** first-paint-vs-final agreement rose 50.3% → 62.2%,
because both now agreed on the same *wrong* identity. **Agreement is not
accuracy — always score identity structure beside it**, which is why
`speaker_probe.py` prints speakers and switches per utterance too. If retried:
find turn boundaries first, verify only spans lying inside one turn, and share one
`observation_group` per utterance.

**Measure this with `scripts/speaker_probe.py`, not `live_events.jsonl`.** That
file holds durable words only, so every word already carries its settled speaker
and the churn scores 0%. The probe subscribes to SSE, scores the first speaker a
`word_id` was ever published with, and scores it **against the playhead** —
a correction landing inside the read-ahead delay is never seen by anyone.

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

Live captions use a stable, left-aligned stack that fills **downward from the top
of the stage**, so the newest caption sits at eye level rather than hugging the
bottom edge.

- Each row holds **as many words as the stage can carry** — a measured em budget,
  not a word count, so rows run 3–13 words depending on how long they are.
  `display.studio_stack_words_per_block` is only the ceiling. A narrow window
  takes shorter rows and larger type rather than shrinking the captions to fit.
- The stack keeps **as many rows as the stage can actually hold** — measured in
  the browser from the stage's own height and a real row's height, so the
  captions fill the surface instead of scrolling while it is half empty
  (measured at 1440×900: nine rows on the light stage, eight on the dark one,
  which puts extra padding on every row). Every currently recognized word stays
  visible in that stack, including the read-ahead words the playhead has not
  reached — those are exactly what the viewer is meant to read early.
- Row identity comes from the first word's stable ID, so adding a word or
  correcting a speaker **cannot remount earlier words or replay their motion**.
- Neither provisional utterance segmentation nor diarization controls row
  geometry — both remain semantic boundaries in the Transcript only. This
  prevents pending attribution from creating one-word rows.
- When a new bottom row appears, retained rows glide upward (540 ms) and the new
  row eases in (620 ms). This entry animation is keyed only to a genuinely new
  bottom row — text, color, speaker, removal, and reappearance updates cannot
  replay it. Reduced-motion mode skips it. Because the stack is top-anchored, a
  new row displaces nothing until capacity starts evicting, so that lone `enter`
  must still animate; requiring an accompanying `shift` silently dropped the
  entry transition for every block before the cap was reached.

The **Transcript** view keeps the complete history, split into paragraphs by
speaker and utterance.

### Rows never move once laid out

Rows used to be chunked by INDEX, so row membership was a function of how many
words preceded a word — the verifier deleting or inserting ONE word anywhere
earlier re-flowed the stack and rearranged text the viewer had already read. Two
rules fix it, and both are needed:

- **Row starts are anchored to word ids** (`StageMemory.starts`): once a word
  starts a row it keeps starting that row, so an earlier edit cannot pull words
  across a boundary. A row that would overrun capacity opens a new anchor there —
  capacity still wins, because `nowrap` CLIPS an over-long row.
- **A late word may only APPEND, never insert.** Anchors alone still let an
  insertion lengthen its row and push the tail out: measured live, the verifier
  turned "Something without" into "Give me something without" and pushed a word
  off the row. A word the stage has never placed, whose onset falls behind the
  furthest word it HAS placed, is not shown — it stays in the model and in
  Transcript. Appends are untouched, so a word arriving late after the endpoint
  stall still appears.

Measured: already-read words changing row **7 → 3** (anchors) **→ 0** (append
rule). Guards that refused deletions and insertions in the *reducer* were tried
first and measured 7 vs 7 — no effect, because settled words are already `final`,
which that branch never deletes.

While a word is still unsettled the `starts` ratchet is ignored and capacity alone
decides, which retires a break made against text that no longer exists. That is
safe only because a word that is not `final` is read-ahead text nobody has read.
It is what removes the permanent 2–3 word sliver rows (measured: 3–4 rows seen
200–380 samples each → one 2-word row seen 14 samples while it was still filling).

**Hold `StageMemory` in lazily-initialised state, not a ref** — the chunker reads
it during render, which `react-hooks/refs` forbids for a ref.

### A word that changes row is rebuilt

A row is a DOM element and a word is its child, so React reconciles words within
one row only: `key={id}` preserves identity among siblings and does nothing
across parents. Moving a word to another row therefore unmounts it and constructs
a new one, and every `useState`/`useRef` inside `MotionWord` re-derives from
scratch. This is an artifact of the tree shape, not a law — and it is why every
earlier attempt to re-flow rows changed the motion.

The rebuild itself is invisible (a word only changes row while it is still ahead
of the playhead, so nothing has begun animating). **The forgotten values were the
entire casualty**, and two were live hazards: `duration` derives from `paceGapS`,
which is 0 until the NEXT word arrives, so a word rebuilt after its neighbour
landed re-derived a *different* motion duration than the one it was wearing; and
`holdAmount` re-ran the settle race that `holdSettled` exists to win.

`WordMemo` holds both in `CaptionFeed`, keyed by word id — also in
lazily-initialised state, because the children read it during render.
**`WordMemo` and row re-breaking ship together; do not re-enable one without the
other** (measured: held "is" correct 3 of 6 runs without it, 6 of 6 with).

### The stage rows never feed the motion clock

`CaptionFeed` takes a separate `timingWords` prop — the whole ordered recording,
independent of what the stage is showing. `paceGaps` and `holdGaps` used to be
derived by flattening the `paragraphs` prop, which on Stage is the RETAINED ROWS,
so a word at the edge of the retained window had no neighbour to measure against
and **layout was an input to the motion clock**. Measured, decoupling it dropped
the build's own run-to-run noise floor below pristine HEAD's on every channel
(weight-peak max |d| 434 → 47, peak-size max 0.797 → 0.053). The rows still decide
what is DRAWN.

### The width budget

`selectStableCaptionStack` takes a `StageWidthBudget` and breaks a row when it is
full in em. Three things decide it, each measured rather than chosen:

- **`width_em = 0.4343 * chars + 0.4289`, fitted on a SETTLED stage.**
  `.caption-word` is an inline-grid whose cell is `max(normal, crest)`, so a word
  sampled mid-crest reads wide. Taking each word's *narrowest* observed width to
  defend against that is a biased-low estimator — measured, it under-read by
  0.062em per word, i.e. 0.74em on a 12-word row, concentrated in exactly the
  short-word rows the budget packs hardest. Read a replayed capture at rest and
  take no minimum at all.
- **`fill` 0.82 is a RESERVE, and what it covers is the CREST** (median +1.19em,
  max +4.92em — it does not scale with word count, so `spread*sqrt(n)` is not the
  model). **0.82 is a motion number, not a layout one:** 0.87 clips nothing either
  and fills more (median 83% vs 78%), but a fuller row sits closer to its break,
  so more words re-break and are rebuilt, and the held "is" measured 4 of 6 runs
  right at 0.87 against 6 of 6 at 0.82. Raising it means re-running the
  six-capture motion check, not arguing about fill.
- **Measure clipping against the STAGE, not the feed.** `.caption-stage` carries
  `overflow: hidden`; `.caption-feed`'s right padding is the gutter that absorbs a
  row-final word's mid-pop overhang, so a row spilling into it is the design
  working. Scoring against the feed's content box reports rows "overflowing" that
  lose no text. `scripts/clip_probe.py` is the check, polled through live
  playback — a settled stage can pass by sampling a lucky instant. Run
  `--broken` first.

### Row width is per CHARACTER, not per language (2026-08-10)

`charEm` was fitted on the English PR film and then charged to every script. A
Hangul syllable is **0.9078em** on the live face — uniform, because Hangul is
fixed-width — against the 0.4343em it was billed, so Korean rows carried roughly
**twice the words that fit** and `nowrap` cut the rest with no error and nothing
on screen to show for it. Measured after the fix: **0 of 308 row-samples clipped**,
rows breaking at 6–9 Korean words, fill median 65% / max 76% against the 82%
ceiling.

Three things decide the shape of this fix:

- **Per character, not per language.** The code still carried the fossil of a
  `--per-word-em` that switched on `[data-language="ko"]` and was lost in the
  2026-08-06 rewrite. A language switch cannot price `2011년`, where the digits
  are narrow and the syllable is not — and FLEURS Korean is full of exactly that.
  `isWideChar` classifies by Unicode East Asian Wide/Fullwidth range.
- **Latin arithmetic is bit-identical, and there is a test on it.** A word that
  changes row is unmounted and rebuilt, and every motion acceptance figure is
  measured on the English film — so if Latin widths do not move by one bit, no
  English break decision moves and English motion cannot. `wordWidthEm` counts
  wide and narrow characters and multiplies once; accumulating per character
  would break that, because float addition is not associative.
- **Measured off the live face, not tabulated.** The font's own `hmtx` does not
  answer it: frequency-weighted over the PR film transcript Latin reads 0.4934em
  by `hmtx` against the shipped 0.4343em, and that 0.88 ratio does **not**
  transfer — Hangul measured 0.9078 live against 0.9200 by `hmtx`. `useWideCharEm`
  probes once per face, mounted inside `.studio-shell` so it sees the Korean
  font stack, exactly as `useGlyphBaseline` must.

**Korean now UNDER-fills, and that is a separate open issue.** *(Corrected
2026-08-11: the cause is NOT English-fitted coefficients — `[data-language="ko"]`
carries its own measured `--word-em-linear: 2.20` / `--word-em-spread: 4.35`. The
budget was already script-aware; what makes Korean rows stop short is word
GRANULARITY, since a Korean 어절 is 3–5em against an English word's ~2.3em and a
row cannot hold a partial word.)* `planStageLayout` sizes the type from
`--word-em-linear`/`--word-em-spread`,
so a Korean row reaches ~29em of a 38.6em budget and the captions occupy about
55% of the stage width. Nothing is clipped; the stage is simply not full. Fixing
it means a script-aware type size, which changes Korean row composition (never
English) — it has not been done.

Measured at 1440×900: row fill **64% → 78% median**, rows carrying 3–13 words,
motion inside the noise floor with every acceptance figure intact.

### Anchoring

`top` + `max-height` + `justify-content: flex-end`, and all three are
load-bearing. `height: auto` lets the box hug its content and stay pinned at
`top`, so a short stack sits high; once the content passes `max-height` the box
stops growing and `flex-end` puts the negative free space at the TOP, so the
OLDEST caption leaves the screen. A plain `top`/`bottom` box with `flex-start`
clips the other end — measured, the NEWEST caption vanished the moment the stage
filled, which is the whole failure this arrangement exists to prevent.

## Voice indicators

The **Voice Compass** in the side grid shows continuous voice qualities
*without* touching the caption glyphs (so completed captions never shake when a
later audio block arrives). Its radius follows true captured volume, its bead
height follows pitch, and its inner texture follows periodicity and brightness.
It reserves an angular marker for a future multi-microphone direction estimate;
mono input explicitly displays `awaiting array` rather than inventing an angle.

A second, smaller copy of the same channels — a voice circle that sat just after
the active caption — was removed on 2026-08-04. The stage carries captions and
nothing else; no channel was lost, and the compass renders them at a size where
they can actually be read.

### The stage stops snapping (2026-08-13)

Two layout transitions, both reported as the captions appearing "딱딱 끊겨서".

**A paragraph that GROWS now glides.** `planCaptionStackMotion` returned no
motion whenever the paragraph id list was unchanged — but a paragraph grows as
words are appended to it, and in the rolling layout that pushes everything
above it with no membership change at all to notice. It also tested
`deltaY >= 0.5`, i.e. upward only, while the rolling layout is bottom-anchored
and moves rows the other way. Both fixed; measured, single-frame paragraph
moves over 12px went from routine to **1** across a 22s capture, median 0.6px.

**The caption box opens sideways over a newly appended word.** It is a
`clip-path`, not a width animation, and the first attempt was the latter:
`transition: width` on a content-sized box is silently inert, because the
SPECIFIED value stays `auto` and never becomes a transition endpoint —
`interpolate-size: allow-keywords` does not rescue it, since it makes `auto`
interpolable but supplies no second endpoint. Measured with that CSS in place,
the box still snapped 23 times by up to 255px. Animating the used width from JS
would work and would relayout the row every frame, which is row breaking and
the motion clock put at risk for a cosmetic effect. The clip touches no layout.

`ROW_GROW_DURATION_MS` is 160ms and should not grow: while the clip opens it
hides the word that caused it, which is a progressive appearance, and 2.2.1's
read-ahead is what progressive appearance destroys. At 160ms against the 1.75s
lead it costs 9% of that word's preview.

A row that is brand new is left alone — it has no width to grow from, and
that case is already the stack's ENTER transition.

### The ring marks are ARCS, and the width is the uncertainty (2026-08-12)

A speaker's standing position was a 6px dot in their caption colour. Two things
were wrong with it: at rail size the dot is hard to see, and it claimed a
precision the measurement does not have — a speaker seen once from one angle
and one seen thirty times from the same angle got identical marks.

Each speaker now owns an ARC of the ring in their colour, spanning two circular
standard deviations of their own observed bearings. `SpeakerBearingMap.marks`
publishes that as `spread`: it was already computing the concentration to
decide whether to show a mark at all, and throwing it away. A settled talker
reads as a tight band, an unsettled one as a wide smear.

Floored at 8 deg (below that an arc is a dot again) and capped at 150 deg (past
that it stops meaning a direction; genuinely scattered speakers are already
dropped by `MIN_CONCENTRATION`). The older `speaker_slots_deg` lane carries no
dispersion, so its marks take a mid width rather than pretending to be precise.

The live dot still wears the ACTIVE speaker's colour and sits at the current
bearing — so when the talker is settled, the dot sits inside their own band.

**A speaker never leaves the ring once placed.** `MIN_CONCENTRATION` used to
drop anyone whose bearings scattered, which is why marks vanished mid-session.
The mean still comes from the recent window — a stale average is not published
as a position — but the speaker is re-emitted at the last place they were
actually seen, flagged `stale`, and drawn dimmed and de-glowed. From the
viewer's side "this speaker left" and "this speaker's bearings went noisy for a
moment" are indistinguishable, and a mark that disappears reads as the compass
forgetting people.

The flip side holds and is tested: a speaker who was **never** concentrated
enough to locate is not invented. Absent stays absent, which is the same rule
direction itself follows.

## Live motion

Motion is a **one-time interpretation of the voice**, not a permanent font
style. Each word's motion is scheduled by the playhead — at its own recorded
onset — so the browser runs it from a single `animation-delay`. The full contract
is [MOTION.md](MOTION.md); the key rules here:

- Words animate at their spoken onset, concurrently if speech is fast. There is
  **no concurrency cap** and no reveal queue: overlapping pops during quick
  speech are the design system working, not a scheduling failure. Measured peak
  simultaneous motions on the bundled film is 4.
- Every word starts and ends at normal 5% / Regular 400 / width 100 typography.
  During its one motion window, volume shapes size and pitch shapes weight
  **per word, uniformly** (§2.3, PDF pp.34/38/40) — the whole word swells
  together, exactly as the reference draws it. The per-character channel is a
  separate travelling *stretch* under the colour wipe, and the two trade off: a
  word carried by volume moves as a word and its letters stay together. Those
  values are transient and cannot restyle a completed word.
- **Every word receives the same synchronization cue as it turns colour**: a
  15% increase in type size, then back (§2.2.3). This cue is independent of the
  voice-shaped axes and of the Expression control.
- Normal type is an invisible layout sizer and the moving glyph is overlaid.
  Therefore motion cannot reflow a row, needs no browser width measurement, and
  drops back to normal even if logical animation cleanup is delayed.
- The schedule is anchored to acoustic timing; a slow frame doesn't restart
  anything, because there is no JS timer to restart — the browser owns every
  moment through one `animation-delay`.
- Speaker color has a **separate clock** (a white→color sweep), so a late speaker
  decision can recolor a settled word but can never make it move again.
- Corrections — spelling, timing, attribution, replay — reuse the same word node
  and never restart its motion.

**Live motion is a function of the timeline, not of arrival.** This used to read
"a microphone can't know future words, so live motion always begins at a word's
first real appearance", and it was named as the main way live differed from `cc`.
The premise was true and the conclusion did not follow: live cannot move a word
*before* ASR creates it, but it can move one *later*, and running the playhead
behind the acoustic clock means every word exists before its own turn arrives. So
live behaves like `cc`. Only the Korean/legacy path in `livepage.py` still
activates at first paint.

### The caption invariant

A word's colour turn is a fixed moment on the acoustic timeline, so **text may be
revised only while the word is still ahead of the playhead; behind it is frozen
history.** This is enforced, not merely documented: `settledTextRef` records what
a word wore when the playhead reached it, and later revisions to it are dropped —
spelling only, because colour, finality and timing still update (a late
attribution correction is a direct colour write).

Two traps, both hit: the single-word event path (`cue`/`commit`/`word` carry
`text` at the top level) needs the same filter, and recording must happen **on
the playhead tick**, because the reducer deletes a non-final word and re-adds it
with the verifier's spelling. Measured: coloured-caption rewrites 14 → 0.
Corrections never change a word's duration or axes — both are frozen at mount.
Replay needs no special case, since replayed words land behind the playhead and
settle; a capture restart is the one explicit case (see `epoch` in
[MOTION.md](MOTION.md)).

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

Every probe named above takes `--broken` or an equivalent negative control.
Run that first: a check that has never been seen to fail is not evidence.
