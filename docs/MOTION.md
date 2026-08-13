# The motion system

**This is the contract.** What a caption's motion is, what it must never do,
and the figures that make each rule checkable. Where anything else in the
repository disagrees with this file, this file is what ships.

Read it before changing anything a word does on screen. Most of the obvious
ideas have already been tried here, measured, and reverted, and the reasons are
recorded beside the rules they produced — often as a number that says how badly
the idea failed. [motion.html](motion.html) puts these channels — and the rest
of the project around them — on one page, with the motion running.

Two things to know before the rules:

- **The design system PDF specifies no motion timing at all.** The recordings
  in `reference/` are the only authority for the clock, and the After Effects
  template is the authority for what the motion *is*. Read the template before
  inferring anything from pixels — three separate attempts to recover the
  motion by measuring video produced confidently wrong numbers.
- **A person watching outranks a statistic.** More than one rule here was
  derived from a measurement, shipped, and then reversed because it read wrong
  on screen. Where this file records both, the human reading is the one in
  force and the measurement is kept to explain why it misled.

Last updated: 2026-08-13.

## Five channels

Each has one owner and one input. They do not share state, and three pairs are
explicitly independent.

| # | channel | where | driven by | rest | reachable |
|---|---|---|---|---|---|
| 1 | **colour turn** (2.2.2) | `word-color-turn` on `.caption-character` | the word's onset, wiped across its spoken span | read-ahead ink | speaker colour |
| 2 | **pop** (2.2.3) | `word-sync-pop` on `.word-glyph` | nothing — constant on every word | 1.00 | 1.15 |
| 3 | **crest / size** (2.3.5-6) | `--voice-phase` x `--voice-scale`, a FONT-SIZE on `.word-ink` | `loudness` | 1.00 | 0.72 .. 1.62 |
| 4 | **weight** (2.3.8-9) | `font-weight: calc(...)` | the SPEAKER's median F0, plus prominence | 400 | 340 .. 900 |
| 5 | **hold / lift** | `word-hold-spring` on `.word-ink` | silence around the word | 0 | 0 .. 0.525em |

There is no sixth channel. Width (2.3.10) rides the word's own pitch and has no
floor to fall into; the character wave is texture under channel 1, not a channel.

## The four rules that are not visible in the table

**1. Size and lift are independent, and mutually exclusive.**
A word that swells does not leave the line. A word that lifts shows no crest and
no weight. The reference is unambiguous: its "louder" more than doubles and
stays planted; its "is" floats at exactly its resting size and is never bolder
than its neighbours.

**Both gates are BINARY.** Every word carries the 2.2.3 pop, so a proportional
gate taxes a word for a cue it did not ask for — "is" renders 1.23x of which
1.15 *is* that pop, and a graded rule took 38% of its lift for what is
essentially resting size.

**2. The crest overshoots, settles, sustains, then releases.**
Not a hump, not a plateau. Measured off the film's "louder":

```
rest ──rise 0.25s──▶ PEAK 3.12  ──0.21s──▶ 2.52 ──hold 0.33s──▶ ──0.21s──▶ rest
```

The sustain is 0.70 of the peak. **A rise time and a fall time cannot express
this** — that is why fitting two endpoints kept failing.

**3. Weight is a property of the voice, not the word.**
2.3.9 draws high pitch light; a shout's F0 doubles; so taken per word the
mapping renders the angriest voice as the thinnest text. 2.3.7 resolves it — its
domain is "the frequency range of a typical human voice" and it says "lower
VOICES are represented with a heavier weight." That is about **who is speaking**.
Within one speaker, going high is *effort*. So the register term reads
`pitch_register_hz`, the speaker's running median.

**3b. What the lift actually detects is ISOLATION, not sustain.**
The intent is "the speaker held this word". The signal is
`min(gap_before, gap_after)` over **inter-onset** intervals, inside a band:
`hold_min_s` 0.78 (below it, ordinary speech) → `hold_full_s` 0.88 (full lift),
with `hold_max_s` 1.06 on the leading gap because a longer silence is a
sentence break, which the film does not lift. Emphatic words are gated out
entirely — a word that swells does not leave the line.

**It cannot tell a drawn-out word from a word followed by a pause.** The
recognizer's `end` runs to the next word's onset and attributes no silence to
anything, so the interval after a word is its own duration *plus* any trailing
silence, lumped. Both readings produce the same number. Measured, three words
lift: `is` 0.525em, `god` 0.525em, `spoken` 0.105em.

A true "sustain" signal would need the word's own **voiced** duration per
character, which the prosody lane already computes — `_prominence`'s
lengthening term, currently at `length_gain: 0.0`.

**4. Everything is frozen at first sight.**
Duration, axes, sweep, hold gap and turn moment are computed once per word and
must survive remounts. Recomputing any of them under a running animation is the
bug this project re-commits most: it has caused a shifted `animation-delay`, a
crest that un-gated mid-flight, and a hold that became a coin flip.

**4b. Frozen per word, but armed per CHARACTER.** The wipe crosses a word letter
by letter, so each `.caption-character` carries its own `--char-turn-delay`, and
a word GROWS after it is armed — the endpoint verifier appends punctuation, a
respelling lengthens it. Every span must be armed, including the ones that
arrive late; a span that never is stays in read-ahead ink for ten minutes, so
the word ends up half in the speaker's colour and half in the read-ahead grey
(measured: 23 of 137 words, fixed 2026-08-06). Arm each span exactly once —
never re-write one that is already running — and check it with
`scripts/caption_color_probe.py`.

## Timing — the playhead

Captions present from a clock running `display.read_ahead_delay_s` behind the
acoustic one, with a per-word floor beneath it. **This is what makes it a CWI
renderer:** 2.2.1 needs the line on screen before it is spoken, and a live
recognizer cannot produce text early — but ASR delivers a word ~0.6 s *after* it
was spoken, so colouring only up to `now - delay` leaves real, recognized,
still-uncoloured text ahead of the colour. **Nothing is predicted.**

* Captions present from a clock **1.75 s behind** the acoustic one. That delay
  is the lag, one for one.
* **Read-ahead is a per-WORD floor** (`min_read_ahead_ms`, 420 ms), not a time
  delay. The recogniser blocks ~1.3 s at each endpoint and then releases a
  batch, so a delay moves the mean lead and leaves the spread alone: at 1.75 s
  the median lead was healthy 700 ms while 42% of words still turned within
  100 ms of appearing. The floor takes that to 0%.
* The floor cannot invent words the recogniser has not sent. Frames with no
  read-ahead at all sit at ~12%; that is ASR latency, not scheduling.
* **Do not gate the turn on attribution.** A word's text arrives at a median
  0.62 s but durable speaker attribution at 4.48 s. The turn happens on time in
  whatever colour is known, or it does not happen on time at all.
* **Live motion is a function of the TIMELINE, not of arrival.** This used to
  read "live cannot move a word before ASR has created it", and first-paint
  activation, `dataset.moved`, reveal gaps and a concurrency cap all followed
  from it. The premise was true and the conclusion did not follow: live can move
  a word *later* than ASR creates it, and delaying the playhead means every word
  exists before its own turn arrives. So live behaves like `cc`. Only the
  Korean/legacy path in `livepage.py` still activates at first paint.

### One `animation-delay` drives the whole caption

`--turn-delay` is how long until the playhead reaches a word's onset; the 2.2.2
turn, the 2.2.3 pop and the 2.3 phase all take it, so the **browser** schedules
them. No JS timer, no per-frame work, and no reveal queue at all — no slots,
gaps, catch-up, backlog ceiling or watchdog. All of that existed to guess a
moment the recording already knows.

* The colour keyframe has **no `to`**: an omitted endpoint animates toward the
  element's own computed value, so one rule yields speaker hue, neutral, or a
  receded provisional mix, and a late correction lands as a direct write.
  `backwards` fill paints the read-ahead during the delay.
* `animation-fill-mode` stays `none`. A word delivered after its own onset gets
  a delay negative enough that the browser treats it as finished, so it paints
  settled. History needs no branch.
* **Write `--turn-delay` imperatively, never via the `style` prop** — React
  reapplies that prop every render, and rewriting `animation-delay` SHIFTS a
  running animation. `data-armed` separates a re-render (leave it alone) from a
  genuine remount (re-derive against the new origin). The turn moment is
  `onset - clockOffset + delay`, with no reference to "now", so a remount
  recomputes the same answer.
* The remount path returns the **stored** turn moment rather than recomputing
  it. The floor is relative to when a word was first delivered, so a recompute
  would move the turn.

### The clock

`web/src/lib/caption-clock.ts` is the clock, and is pure. It recovers acoustic
time from `level.t` (~64 ms cadence, the same timeline as `word.t`) with a
**max-filter plus 5 ms/s decay**: jitter can only make a sample look late, so
the truth is the maximum.

**Word events are NOT a clock source** — they are replayed to every new
connection, and an old timestamp reads as a restart. A backwards jump over 1.5 s
*is* a restart (`--sample --loop`): the clock snaps and bumps `epoch`, and
**words under an older epoch must settle, never be re-derived** — recomputing
puts them in the future, and a full stage of read captions turns white again.

**No catch-up slew.** The server blocks ~1.3 s at each endpoint, and the obvious
theory — source floods its queue, max-filter swallows it, playhead skips — was
implemented and measured: late words 13 with the cap and 13 without.
`newest - playhead` sits at a steady 1.22 s, goes negative during the stall,
returns to 1.22 s. The words stop; the clock does not.

## Acceptance figures

Measured with `scripts/word_motion.py` on the bundled film (`--sample`, which
*is* the PR film). Re-measure these, not a slope, after touching any channel.

| | |
|---|---|
| `"louder"` | **1.83x**, weight **~890**, lift **0** |
| `"softer"` | **0.82x**, lift **0** |
| held `"is"` | lift **0.525em**, size **1.15x**, weight **400** — the FIRST "is" ("as each word is spoken"); the second is not held, and comparing by word text reads the wrong one |
| lifting words | `is` 0.525, `god` 0.525, `spoken` 0.105 — and the held word is **intermittent**, measured wrong in ~1 run of 6 |
| whole film | median peak **1.15x** — the ordinary word carries the pop and nothing else |
| | **0** words lighter than Regular, **0** bold samples on any lifted word |
| adjacent-row ink gap | 9 px at rest, **1.0 px under motion — no headroom left** |

## Implementation rules — what a code change gets wrong

The contract above says what the motion *is*. This section is the part a code
change breaks. Each entry cost at least one round to find; the derivation is in
the project's decision log.

### Provenance — read these before inferring anything from pixels

**The motion was authored in After Effects, and the project is in git.**
`git cat-file blob 1518434:'AE PROJECT/AE PROJECT/Academy_CI_Template.aep'`. It
is RIFX; walk the chunks (`Utf8` holds the expressions) and the whole motion
system comes out as plain text. Three separate attempts to recover the motion by
measuring video each produced confidently wrong numbers. All four animators share
ONE range selector exactly **one word wide**, swept by
`ease(time, inTime, outTime, 0, textLenWords)` — so a word's motion lasts
`lineDuration / wordCount`.

**THERE ARE TWO ANTICIPATIONS IN THE TEMPLATE, NOT ONE (found 2026-08-11 by
re-reading the .aep after recovering the full official release).** This file
recorded only the 33 ms one. The template holds **8** distinct expressions, and
two of them shift time backwards:

```javascript
antecipation = framesToTime(1);   // 33 ms  -- the documented one, easeOut
antecipation = framesToTime(4);   // 133 ms -- NOT previously recorded
linear(time, inTime, outTime, -1, 0)
```

The 4-frame one is not a per-word range selector at all: it ramps a value
**-1 -> 0 across the whole marker span**, shifted 133 ms early. So the template
moves something a full four frames ahead of the line, on top of the one-frame
`Antecipate`.

That matters for a question this project is currently open on — MEASURED on the
PR film, the reference crest **peaks at the word's acoustic onset** (16.71 s
against a 16.67 s onset) having risen over the 0.21 s *before* it, while ours
starts at the onset and peaks 0.26 s (emphatic) or 0.52 s (ordinary) after. The
template having a 133 ms anticipation is evidence for that lead being deliberate
rather than an artefact of the website implementation. **Which property the
4-frame expression drives has not been identified** — the .aep names its groups
`Group 10`…`Group 25`, so the binding is not readable from the strings alone.

`Antecipate` is the same sweep shifted **33 ms**
earlier. There is no scale animator at all: 2.2.3's pop is the PDF's, and the PDF
wins on amplitude.

**The reference recordings are silent.** `ffprobe` returns only video for all
three `docs/reference/*.mov`, so `loudness`, `pitch_hz` and `voiced_frac` in
`assets/reference_specs/*.json` are solved *backwards* out of the measured
motion. **Never regress motion against them** — it returns circular nonsense
(peak size vs loudness −0.02, weight vs pitch −0.54). What they *can* answer is
what the motion DOES: `motion.scale/lift/dwght` are real pixel measurements. The
only source where motion and audio are both real is `docs/reference/pr-film.mp4`, which is
the PR film and is what `--sample` streams.

**The PDF specifies no motion timing at all** — no seconds, milliseconds, frames,
duration, speed or easing anywhere in it. 2.2.3 says only "a 15% increase in type
size before returning to its original size."

### Two motion clocks, and they must not be collapsed

`--motion-duration` (pop + wave) rides the **speech rate**, from the AE
template's one-word-wide selector. `--crest-duration` (`voice-phase`) rides
**emphasis**, which the template says nothing about and the recordings run far
longer. Driving both from the speech rate made the words that matter **4.7x too
fast**; driving both from the crest made ordinary words **4.8x too slow**.

* The crest window must be clamped to `word_motion_max_duration_s`.
  `crestDurationMs` divides the sweep by `VOICE_PHASE_RISE_FRACTION` — a 4.2x
  multiplier that overrode the configured ceiling outright until it was bounded.
* The crest ramp is **cubed, not linear**. The reference's bands are flat then
  steep: almost nothing until a word is genuinely emphatic, then it more than
  sextuples.
* **The 2.2.3 pop belongs on the CREST clock.** Splitting it onto the
  speech-rate clock decoupled two SIZE channels that must compound — the pop
  finished long before the crest peaked and the visible peak fell to ~1.3x where
  the film reaches ~2.0x. Only the character wave rides the speech rate.
* **Do not judge this by the median over all words.** 37 of 43 reference words
  barely move, so the median is dominated by motions nobody notices. Score the
  bands separately and weight the top one — that is what a viewer sees.

### The word grows from its baseline. It does not move.

Wrong four times. No `translateY`, and no box-bottom pivot: `transform-origin` is
`50% calc(100% - var(--glyph-baseline-em))`, measured off the live face by
`useGlyphBaseline` (.3799em Roboto Flex, .2598em Noto Sans KR). **It cannot be a
constant** — two bad probes both returned an IDENTICAL number for the two fonts,
and that equality is the bug signal.

**The pivot is not enough: the anchor has to move too.** The crest is a
FONT-SIZE, so it changes a BOX and not just its paint. `.word-glyph` is
`position: absolute; bottom: 0` with auto height, so the ink's depth below the
baseline grows with the crest while the strut's does not, and the word floats up
by `--glyph-baseline-em x (crest - 1)`. Measured before the fix: correlation
**0.867**, the largest words **+0.236em**, where the reference's own baked curves
regress lift on size at +0.043 and put its biggest word at exactly 0.000.

Fixed by a pair on `.word-glyph`: a `translate` pushing the box down by that
amount, and a `transform-origin` tracking the CURRENT baseline via
`max(1, crest)`. **Both are STATIC properties** — `word-sync-pop` has
`fill-mode: none` and a shorter duration than `--crest-duration`, so a correction
placed in its keyframes switches off mid-crest. Both clamp at 1, because below it
the strut is the deeper half and nothing moves (which is why "softer" measured
clean and hid this for so long). Measured after: slope **14.91 → 0.23 px per
1.0x**, correlation **0.908 → 0.028**.

**Measuring this defeated three attempts.** `.word-ink`'s rect does not contain
the pop (a transform on a CHILD); `.word-glyph`'s rect bottom is pinned by
`bottom: 0` and cannot move by construction; `studio_probe.py` keys on
`|matrix.f| > 0.5` and this lift is LAYOUT, so `matrix.f` stays 0 throughout.
`scripts/baseline_probe.py` is the check — run `--broken` first.

### The colour turn is a wipe across the word, not a switch on it

The PR film puts the colour boundary INSIDE a word constantly, in ordinary
captions: "I like i|t", "dynamic te|xt", "weigh|ts" — and in that last one the
size and weight sweep in *with* the colour, "weigh" already big and bold while
"ts" is still small and grey. 2.2.4 calls per-syllable animation the exception;
the film makes it the rule.

So `word-color-turn` lives on `.caption-character`, each letter on its own
`--char-turn-delay`, spread across the word's spoken span (72%, capped at
`wordMotionMaxMs`), written imperatively for the same reason the word's is.

**The word is armed once, but so is each SPAN.** The arming effect used to return
early on `data-armed`, i.e. for the whole WORD — so a character appended after
the first arm (endpoint punctuation, `animation` → `animation,`; a lengthening
respelling) never got a delay, kept the stylesheet's 600000ms default, and sat in
`word-color-turn`'s `backwards` fill — **read-ahead ink** — for ten minutes.
Measured: **23 of 137 settled words ended the capture two-coloured**, each mixed
for the remaining 28–63 s. That is a false claim about who spoke, which is the
one thing 2.1 exists to prevent.

A span that already carries a delay is now left strictly alone (rewriting it
would shift a running wipe); only new spans are written, against the same frozen
absolute moment. `perWord` freezes at the ARM for the same reason — appending to
the denominator would hand a late character an EARLIER delay and the boundary
would travel backwards. After: two-coloured words **23 → 0**.

**`studio_probe.py` cannot see this** — it asks whether a word's FIRST character
is still read-ahead ink, and here the first character turned and the last never
did. `scripts/caption_color_probe.py --broken` is the check.

### Only the colour moves down to the characters

**`voice-phase` stays on `.caption-word`.** An edit moved the phase down with the
colour and every voice channel died at once while the page still LOOKED alive:
the phase's consumers — the crest calc on `.word-ink`, the push reservation on
`.word-sizer-crest` — are ANCESTORS of the characters, and an animated custom
property never propagates upward. Measured: font-weight pinned at exactly 400 for
all 100 words across 525 samples, no crest, no push — reported as "there is just
flowing motion", because the wipe, the pop and the wave all still ran.

**The crest must not lead the wipe.** On the natural window the phase rises in
~150–200 ms while the wipe crosses a long word in up to 720 ms, so words
ballooned while still mostly uncoloured; the film never moves a word ahead of its
colour. `--crest-duration = max(natural, sweep/0.28)` stretches only the crest —
**0.28 is bound to the literal 28% stop in `@keyframes voice-phase` and they
change together.** `sweepMs` and `crestMs` freeze at mount beside the duration so
the arm effect and the animation agree on one number.

**One phase per word drives every character.** `@property --voice-phase` is
animated once on `.caption-word`; each character computes
`calc(1em * (1 + phase * (charScale - 1)))`. Per-character animations do NOT
work: `animation-delay` counts from when the animation was applied, and live words
GROW as a hypothesis extends, so a span appended later ran behind its neighbours —
measured, half a Korean word sat at rest while the other half was at its crest.
`.character-sizer` applies the same interpolation times the pop, so it tracks the
visible curve at EVERY phase, not just the peak.

### Two scopes, and they own different channels

This took the longest to see, because the PDF states neither scope.

**2.3 intonation is per WORD, uniform.** In `intonation.mov` f395 every glyph of
"louder" is the same size and the same weight. Driving size/weight/width per
character off the intra-word envelope is what made this read as "very
character-level".

**The per-character channel is a travelling STRETCH**, and it is what makes the
reference feel chewy: as the colour passes through a word the letters stretch —
hard up and down, only a little in width — scatter off the line and close back
up. Shipped as a TRANSFORM on `.caption-character` (±13% scaleY, ∓2.2% scaleX,
staggered by `--char-turn-delay`), so it cannot disturb layout and needs no
reservation. Amplitudes were halved on 2026-08-01: at the old size the wave
COMPETED with the colour turn instead of supporting it. The rebound is gentler
than the rise — an overshoot as large as the rise reads as a wobble.

**The two trade off, and this is the rule that ties them together.** A word
carried by VOLUME moves as a WORD and its letters stay together; a word at
ordinary volume has little word-level motion and the wave carries it. So
`--char-wave` = (this letter's departure from its own WORD's size) x
(1 − wordVolumeDeviation x `character_wave_falloff`), floored at
`character_wave_floor`. Both are now set so suppression is **total** at both
extremes — "louder" and "softer" measure scaleY excursion exactly 0.0000, against
ordinary words at 0.055–0.169. It also fixed a headroom problem as a side effect:
the loudest words no longer stack a big wave on top of a big swell.

**Anything asking "how far from normal is this word, as a fraction of the
possible" must divide by `reachableScaleRange()`**, not by the configured clamp.
`voice_scale_response_quiet` stops the shrink before `voice_scale_range[0]`, so
the most hushed word in the film scored 0.786 against a configured 0.72 and kept
a fifth of its wave even at floor 0. `emphasisOf` uses it too.

### The push is the motion

The reference's dominant motion is what a word does to its NEIGHBOURS —
`intonation.mov` frames 352→396, the line re-flows around "louder". **Look at the
neighbours, not the word.** The visible glyph is out of flow and moves nothing;
the push comes from the in-flow `.character-sizer`, whose grid track is
`max(normal, crest)`, and growing the crest grows the cell, which flex turns into
a shove. Identical at phase 0, so a settled row is exactly as wide as its words.
`motion.live_sync.neighbor_push` stays false — that flag is the LEGACY renderer's.

### Loudness → size

**Return to normal.** Every word begins and ends at 5% / Regular 400 / width 100.
The PDF's static pages show voice type persisting; the recordings show it
returning, and the user chose returning.

**The quiet half needs a DEADBAND, not a weaker response.** Two failures, in
order: a symmetric response drew **48% of ALL words below normal**, down to
0.75x, so ordinary unstressed speech was drawn as if whispered and read as
instability; weakening the quiet response then "fixed" that to 31% and made the
whole channel invisible instead. `voice_scale_deadband` is a band around the
median where size does not move AT ALL, with the full response outside it — and
it is a **fraction of each side**, not an absolute, because the pivot is not
centred. Measured after: median exactly 1.000, 22% of words move, floor 0.780.
Tests pin the band, the visible floor, monotonicity, and **continuity at the band
edge** — a discontinuity there renders two near-identical words at obviously
different sizes.

**Vocal effort is the fourth input.** 2.3.5 asks for VOLUME; `db` measures LEVEL;
on mastered, AGC'd or auto-levelled audio those are different quantities, and the
film proves it. `live.vocal_effort` adds a one-sided lift from the spectral tilt
of each word's strongest frames, and does NOT touch `loudness_db`, which still
reports what the microphone heard and is what haptics threshold on. Four
non-obvious costs, all of them measured:

* **Energy-weight the tilt.** Over a whole span it measures PHONEMES — a word's
  fricatives carry huge HF energy, its silences none — giving a 21 dB per-word
  spread and a useless ranking.
* **Smooth it causally, and NOT off `effort_history`.** That deque holds FINAL
  words only, so during a shout the newest finals are still the calm narration
  before it, the mean is dragged back to baseline, and the lift computes to
  exactly 0.0 for every shouted word and is then CACHED. `effort_recent` is keyed
  by time slot. The BASELINE deliberately stays on settled history: a shout is
  measured against the calm speech around it.
* **Apply the lift AFTER the frozen restore.** `prosody_cache` is written on the
  first CALL for a slot, when the word is still at the edge of the audio buffer
  and effort cannot be measured, and it is also inherited from a neighbouring
  slot by the retiming lookup. A lift applied before that restore is silently
  discarded — measured 0.000 across a whole shout, twice, before the order was
  fixed.
* **It needs a deadband, and the level must clip at 1.** Without the deadband,
  34% of ordinary narration lifted and sibilant-heavy words gained +0.30 —
  spelling driving type size. Unclipped, a word far above the speaker's p95
  computed a level of 2 or 3 and slammed `loudness` into its own ceiling.

**`db_min_span` looks like the culprit for a flat channel and is not.** Lowering
it was tried and measured WORSE: it scales ALL deviations, so it blows the top
out long before it fills the middle. Score the WORDS, not the frames — at 18.0
the per-word peak distribution tracks the film (p90 1.236 vs 1.220, >1.30x 7.9%
vs 7.3%); at 12.0 it renders 3.5x too many very large words. The measurement that
first argued for lowering it was contaminated by index-matched cluster tracking.

**The first utterance calibrates from cues, and unmeasured is neutral.**
`db_history` appends FINAL words only, and a long first utterance finalizes all
at once at its endpoint — the film's 24 s opening left ~60 words normalising
against the static fallback, saturated at the crest clamp. `db_bootstrap`
(slot-keyed, so hypothesis re-emissions overwrite rather than double-count) feeds
the same percentile maths from non-final emissions; below six entries
`_normalize_db` returns the PIVOT. **An unmeasured channel renders at the 2.3.5
baseline** — the same reasoning that renders an unattributed word neutral, never
a raw config-range guess.

### The hold

**The gate freezes at the TURN, not at the mount.** The gap is
`min(before, after)`, and `after` needs the NEXT word, which has usually not
arrived when a word first renders — so a child that froze on its first render
captured a pre-neighbourhood value, and whether it won that race depended on
render cadence. Any unrelated change to how often the tree re-renders flipped it:
measured, the held word came out 0.525em on one run and 0.000 on the next of the
SAME build. `holdSettled` now tells the child when the parent's answer is final,
and the child stops accepting revisions once the playhead passes the word.
**It improves the odds; it does not close them** — 1 of 6 runs still wrong. A
second source of nondeterminism has not been found. Do not claim this word is
deterministic.

**The whole choreography is anchored on the turn, not on arrival.** One animation
of `--hold-pre` + `--hold-land`, delayed by `--turn-delay` *minus* the pre-roll,
with `backwards` fill painting the resting 0% keyframe for however long the
read-ahead lasts. A word delivered later than its own pre-roll gets a negative
delay and joins the spring part-way through. The scale needs `transform-origin`
on the baseline, for the same reason `.word-glyph` does; it is safe to express in
`.word-ink`'s own `em` because `--voice-phase` is still 0 for the whole spring.

**The pre-roll is bounded by how long a word actually exists, not by the film.**
The film crouches ~1.05 s ahead of the turn; measured here, a word is on screen a
median **0.30 s** before its turn (p75 0.49, p90 0.67). Shipped at 1050 ms first
and it was invisible — zero held words had the lead, one joined during the float
and the rest during the LANDING, so the crouch and the launch never ran. Note `t`
is on the STREAM timeline while `start`/`end` are utterance-relative.

**The hold scales with emphasis — two envelopes, not one shape.** The aggregate
shape statistic is 0.40 across the 43 reference words and a raised cosine is
0.41, but that median is carried by the 37 words that barely move; the film's
"louder" holds at full size for ~6 of ~10 frames. `--voice-envelope` picks
between them at `HOLD_ENVELOPE_EMPHASIS`, because a keyframe's stops cannot take
a `var()` but `animation-name` can. **A rise time and a fall time cannot express
the emphatic one** — that is why fitting two endpoints kept failing.

The release is deliberately **shorter than the film's**: weight is where a slow
release shows, since 900 → 400 is a far larger perceptual step than 1.8x → 1.0x
and both ride this one phase. Lengthening the sustain instead was tried and
measured WORSE (time-above-half-peak 0.68 s → 0.74 s — the word simply stayed up
longer). **`word_motion_*_duration_s` must be RE-DERIVED whenever the keyframes
change**: the envelope decides how much of the window sits above half-peak (pulse
0.50, hold 0.78), and those numbers have moved the config three times.

**Every envelope must leave and return to rest with zero slope.** `sin(pi x)` has
a non-zero derivative at its ends, so motion started and stopped with a visible
kick; `sin^2` and smoothstep do not.

### Leading and clearance

**Leading is 1.38, and the arithmetic that said otherwise was wrong.**
`lineHeight >= capHeight * maxScale + descent` predicted 1.56, cost 4px of type
and bought ONE pixel. Line-box geometry cannot answer this — a scaled box
overlaps its neighbour long before any letter does, and that overlap grows WITH
the leading. `scripts/ink_collision.py` reads pixels and is the real test.

**There is no headroom left: 9 px at rest, 1.0 px under motion.** It is the
CREST, not the lift (`hold_lift_em: 0.0` left the minimum at 1.0 px with 3 pairs
under 4 px), and it is not row density (identical at 15, 16 and 18 rows). Motion
eats 8 of the 9 px the layout hands each row, and that is reference behaviour,
not something to tune away casually. **Re-run `ink_collision.py` after any change
to `voice_scale_range`, wave amplitude, `hold_lift_em` or
`character_wave_falloff` — this is the first constraint that will break.**

### The renderers

**`cc` is the authored reference** and may drive the axes harder via
`closed_caption` overrides — merge with `ccprosody.merged_expression()`, since
reading `cfg["expression"]` directly silently gets live's values. Its
per-character wave, neighbour bleed and `Antecipate` lead are safe there because a
caption plays through instead of accumulating, which is why they stay off live.

**A line being spoken outranks a line that has not started.** In `cc`, ranking
visible lines by recency let the NEXT line's read-ahead window — which opens
`read_ahead_s` early — evict the caption mid-sentence. Priority: words on screen
now > lingering > read-ahead, with read-ahead only filling a free box.

**Reduced motion keeps the colour turn** and drops only the geometry: read-ahead
and the onset turn involve no movement and are how a viewer knows which word is
being spoken. Pin `--voice-phase: 0 !important` rather than cancelling the word's
animation, which also carries the turn.

**The per-character slide-in entry is OFF** (`character_entry_enabled: false`).
`cc` has no such effect; it was a live-only addition and read as extra motion.

**Syllable variation (2.2.4) is a colour wipe over already-visible text**, gated
by `motion.syllable_fill` to drawn-out words (~7%). **Never make it a typewriter
reveal** — progressive appearance destroys the read-ahead in 2.2.1.

**The colour turn is a crossfade over `motion.color_turn_ms`** — blend white →
speaker colour, quantized to 32 steps so the written string is stable across
frames. Never a hard cut, however much `sweep >= at` looks right.

### The forward map

**Bound the RENDERED type axes** (`expression.wght_range`/`wdth_range`), not just
the anchor: the response curve leaves values at the pitch-domain edge
uncompressed, so a very high voice rendered hairline beside ordinary text.

**`size_pct` below `mapping.loudness_to.min` silently kills the quiet half of the
loudness channel.** `towardBaseline` computes `extent = baseline - min`; if the
resting size is below `min` that is negative, the `extent <= 0` guard fires, and
EVERY quiet word returns exactly the baseline. Fixed by rescaling the range by
`size_pct / baseline` in BOTH `typeOf` (JS) and `ccprosody.forward` (Python) —
CWI's anchors are ratios around its baseline and read as absolute percentages only
when the resting size IS that baseline.

**`emphScale` depends only on `loudness - median_loudness`.** The map is
translation-invariant, so the absolute level is a gauge freedom and there is no
fixed point unless the MEDIAN word's target is exactly 1.0 — which is the correct
semantics, since emphasis is relative to the median word. `fit_spec_prosody`
solves each word's offset and re-centres, exactly and without iterating; an
earlier iterate-the-median version oscillated forever.

## Legacy is the default (2026-08-12)

`Settings → Enhanced motion` defaults **OFF**. The user watched
`autocwi live --sample` beside the PR film and judged legacy the closer of the
two. **That judgement is the deciding evidence and it outranks every number
below** — the enhanced clock had been tuned until every statistic sat inside the
film's own 95% interval, and the stage still read wrong.

Why the numbers could not catch it, and the process failure behind it, are in
*Measuring motion against the film*. Both are worth reading before trusting any
motion metric.

What enhanced measured is real and is kept behind the toggle: the no-push
reservation, the film-fitted envelope, and above all rule 4 — weight and width do
not animate. Those findings survive their default being off.

**`scripts/ink_collision.py` PASSES on legacy** (adjacent rows never come within
4 px). It warns under enhanced, whose larger pops deliberately overlap, and that
is correct for that path.

## Two systems: legacy and enhanced

Everything above this section describes **legacy**, which is what ships and what
every acceptance figure in this file was measured on. Enhanced is one toggle
away and is **bit-identical to legacy when off** — its delay arithmetic is
untouched and there are tests on it.

Enhanced is fitted to `docs/reference/pr-film.mp4`. Each change
below is a measurement, not a preference, and several replace an earlier reading
of the same thing that was wrong — where that happened the correction is stated,
because the wrong version is the one a future session will otherwise re-derive.

**1. The crest FOLLOWS the turn — it does not anticipate it.** Tracked per word,
the film turns a word's colour first and peaks its size ~0.1 s later
(`sole` +0.08 s, `purpose` +0.08 s, `in` +0.12 s). Legacy sits at +0.161 s, i.e.
very nearly right. An earlier version of this file had it backwards and started
the crest early, which put the peak at −0.26 s and made words swell while still
in read-ahead white. `--crest-pre` and `crestPreRollMs()` are deleted. This does
not contradict the `"louder"` figure of +0.04 s from the ACOUSTIC onset: the film
turns a word ON its onset, so both say the crest follows.

**2. There is no push.** The film's line extent is constant while an interior
word swells — measured, 350→931 px unchanged — and only a word at the very edge
bulges the edge outward ~20 px. Its swollen words visibly overlap their
neighbours instead of shoving them along the line. So the enhanced reservation
is frozen at the word's resting width and the crest overflows into the gap.
Reserving the *peak* was tried and makes every slot ~1.9× the resting width,
which re-composes the rows and leaves the line gappy at rest.

**3. The word turns as a UNIT.** The template's range selector is expressed in
word units (`ease(time, inTime, ..., 0, textLenWords)`), and the frames agree: at
24 fps a word spends exactly ONE frame between <15% and >85% turned. This is a
real divergence between the two CWI artifacts — `synchronization.mov`, the design
system's own site, shows a per-character wipe and CWI 2.2.2 describes one. Legacy
keeps the wipe; enhanced turns the word as a unit.

**4. A word's motion is COLOUR and SIZE. Weight and width do not animate.** This
is the rule that mattered most and it is the one no size fitting substituted for.
The template drives exactly `ADBE Text Fill Color` and `ADBE Text Position 3D` —
no weight animator, no width animator. Measured off the film by stroke thickness
over glyph height (scale-invariant, so pure growth reads flat, calibrated against
this project's own Roboto Flex), the weight swing from a word's rest to its peak
is a **median of −40 with a p75 of 0**. Ours ramped a **median of +155 and up to
+497**. On the enhanced clock `--voice-weight` and `--voice-width` are applied
whole instead of ramped: 2.3.8–2.3.10 still compute exactly what they computed,
a shouted word is still heavier — for its whole life, as the film's louder words
are authored larger rather than growing into it. `scripts/weight_diff.py`.

**5. The pop is EMPHASIS-SCALED, and its floor is the PDF's 15%.** Per section,
calm narration peaks at 1.09× and the shouted drill-sergeant line at 1.28×.
**An earlier version of this file claimed a uniform ~55% on every word. That was
wrong** — it came from measuring only the shouted line with a biased metric. The
film's floor is ~1.09×, essentially 2.2.3's stated 15%, so the design system and
the reference agree after all.

## WHICH WORD the film enlarges is not in the audio

`--sample` streams the film's own audio, so both sides say the same words at the
same moments and can be compared word for word rather than statistically.
`scripts/word_by_word.py` does that. **The correlation between which words we
enlarge and which words the film enlarges is −0.018.** Not weak — absent. Our
per-word peak distribution sits inside the film's confidence interval on every
quantile while the assignment is unrelated: on the drill-sergeant line the film's
largest word is `in` (1.50×), which we do not move at all, and its smallest,
`army?`, is among our largest.

Three checks, because a null result is the easiest thing to get wrong:

* **Our mapping works** — loudness → `--voice-scale` correlates **+0.977**.
* **The film-side measurement is reliable** — every film word measured twice,
  from its full ink slot and from its central 60%, agrees at **+0.997**.
* **The film's sizes do not track the film's own audio** — **−0.277** across the
  41 words that visibly grow, and its bigger half measures **1.0 dB quieter**
  than its smaller half.

So the film's per-word sizes are a transcriber's judgement, which is what CWI's
workflow describes. **No acoustic rule can reproduce them.** Shape, timing,
amplitude distribution and the weight rule all match; *which word* cannot. Do not
fit per-word sizes to the clip — it would overfit one film, and the product is
live captioning with no transcriber in the loop.

## The motion is locked to the speaker (2026-08-12)

**The target is the SPEAKER, not the film.** Real speech duration is
**`(end - start) x voiced_frac`**, and the second factor is the whole point: the
recognizer's `end` runs to the NEXT word's onset and attributes no silence to
anything, so the raw span is an inter-onset interval, not speech. Validated
against an energy-gated voiced span computed straight off the audio —
correlation **+0.765**, medians 0.170 s and 0.200 s. `voiced_frac` was already on
every word event and simply unused by the clock.

**MEASURE THE VISIBLE WIDTH, NOT THE TOTAL DURATION.** Equating the total
animation to the spoken duration was the first attempt and it measured — and
looked — **too fast**. An envelope only spends about half its length above
half-height, so the part a viewer actually sees came out at **0.49x** the word's
speech against the film's **1.18x**. What reads as synchronised is the rise and
the peak, not the long shallow tail. `word_motion_speech_scale` exists for
exactly this, and it is fitted against `motion_diff`'s `width_s`.

| | before | after |
|---|---|---|
| `--motion-duration` | 580 ms — 3.4x the real speech | tracks the word |
| visible width (`width_s`) vs real speech | — | **1.03x** (film 1.18x) |
| motion clock's correlation with speech | +0.728 (against the raw span) | **+0.688** (against real speech) |

**This is not the clock collapse this file warns against.** That meant driving
the crest off the speech RATE and losing emphasis, which made emphatic words
4.7x too fast. Here the emphasis term is untouched — still cubed, still reaching
`word_motion_max_duration_s` — and only its BASE moved from a flat 520 ms to the
word's own duration. An ordinary word tracks the speaker; an emphatic one still
stretches well past it, which is why the crest correlates only +0.273 with
speech where the motion clock correlates +0.688.

`word_motion_follows_speech`, `word_motion_speech_scale` and
`word_motion_speech_floor_s` in `config.yaml`. The floor exists because a 60 ms
animation is a flicker rather than a cue.

**THREE THINGS ARE UNRESOLVED. Do not treat this as settled.**

* **The scale knob saturates.** Raising `word_motion_speech_scale` from 2.4 to
  2.85 moved the visible width only 0.168 s -> 0.174 s, +3% for +19% of input.
  Something else binds the SIZE envelope — most likely `crestDurationMs`'s
  `sweep / VOICE_PHASE_RISE_FRACTION` term, which is unaffected by this clock.
  Find it before turning the knob again; it is currently doing almost nothing.
* **The peak lands late.** Ours peaks at +0.131 s against the film's +0.091 s.
  Legacy's `voice-phase` peaks at 50% of its window, so a longer window pushes
  the peak later — width and peak position are coupled and cannot both be fitted
  from duration alone.
* **Clearance now warns intermittently** — 43 and 27 pairs under 4 px on
  consecutive runs, where legacy passed outright before this change. It varies
  with which words are emphatic, so it is not a clean regression, but clearance
  has no headroom (9 px at rest, 1.0 px under motion). `motion_diff` also
  reports the per-word peak p90 rising 1.37x -> 1.81x; that may be a TRUER
  measurement rather than a bigger motion, since a word in motion far less of
  the time has a much cleaner resting baseline. Neither is verified.

## THE FILM, READ BACK BY HAND (2026-08-12) — this section outranks the three below

The user annotated `docs/reference/pr-film-annotated.txt` word by word from
28 s on. That reading is the authority for everything in this file that was
derived from a size envelope, because the envelope is blind to most of it: at
the film's ~17 px type a 15% pop is under 3 px, which is inside the envelope's
own detection floor. **A person watching outranks the fit** — the project rule,
applied here.

What the annotation says, and what implements it:

| the film | here |
|---|---|
| **every word pops** — every line, every word | `--sync-pop` is ungated (`live-studio.tsx`) |
| the pop goes **up, not centred** | `.word-glyph` `transform-origin` is the baseline |
| **all words carry a small lift** ("maybe all has little bit -y moved") | `--word-lift-em`, .045em, on `word-sync-pop-lift` |
| **bold is per line, not per word** — S3 shouting is bold on every word, S4 and S5 are not bold at all | `quietWord` gates weight only |
| letters lift **in syllables**: `se\|en`, `Gu\|mp`, `but\|ton`, `be\|cause`, `say\|ing`, `res\|cue!` | `web/src/lib/syllables.ts` → `--char-wave-delay` |
| inside a group each letter sits at a **slightly different angle** | `--char-tilt`, frozen from the character index |
| a word either **pops** or **lifts**, not both | the binary hold/crest gate, already the rule |
| sound labels (`[Toy music]`, `[Beep]`) **vibrate** | `sound-vibrate`, on `.sound-caption-shake` |

### THE LIFT IS THE DEFAULT, THE POP IS THE EXCEPTION (2026-08-12, from the array)

Decided watching a real talker through the ReSpeaker, which is the first time
this stage has been judged at booth conditions rather than against the film.
The verdict was that too many words popped and the stage was hard to follow.

**Count the annotation and it agrees.** Across the lines read back word by word
from 28 s on there are roughly **thirty lifts against eight pops** — "Buzz Light
year to the rescue!", "I like it because I can track,", "what the actor is
saying in real time.", "I'll show you." are *lift on every word*, and the pops
are the handful the speaker leans on. The reading opens with the rule outright:
*"lifting ->> maybe all has (little bit -y moved -> up lifting)"*.

So the treatments swapped rank:

| | before | now |
|---|---|---|
| unemphasised word | pops 8.6%, lifts .045em (**under 1px — invisible**) | **lifts 0.16em (~3.5px)**, does not grow |
| emphasised word | pops + crest + bold | unchanged |
| every word | colour turn, character wave | unchanged |

`word_lift_em_enhanced` is the tunable. Measured after: 22-25% of words pop
where 100% did, and the lift travels 4.1px where it travelled 1.0px.
`ink_collision` is unchanged by it — 1.0px minimum and 11 close pairs at
**both** 0.045em and 0.16em, i.e. the pre-existing under-motion figure, not a
cost of this.

**This is the second time the pop gate has been decided from the stage and the
first time it was decided the same way twice.** Reading the film says every word
pops, and it does; forty of them at 2.5 words/s is noise where four in a held
shot is emphasis. The film's own rule is not wrong — the density is different.

**The character wave is legacy's shape again.** It was briefly a pure lift plus
a per-letter angle; watched on the array, legacy's elastic stretch read better,
so the stops are legacy's byte for byte with the tilt riding on top. What the
syllable work left behind is the CLOCK — `--char-wave-delay` groups the letters
so a syllable stretches together — which is the half the film shows.

### THE WORD LIFT WAS TURNED OFF FOR ONE ROUND, AND PUT BACK (2026-08-13)

`word_lift_em_enhanced` went to 0 on a misread: the report was about
`motion.html`'s **crest demo**, whose own line box grew with the type and took
the baseline with it, not about the stage. The stage never had that defect —
`.word-glyph` is an absolute overlay over a hidden resting sizer, so the crest
cannot move a row (measured: row tops and cell bottoms identical at rest and at
a pinned 1.62x crest, 0.00px on all 108 words).

Worth keeping from the round, because it is the only measurement of what the
lift actually costs: traced over the film, the lift is **4.10px of vertical
travel on 59 of 106 words**, and removing it left the size cue untouched
(glyph scale p90 1.076 either way). The per-letter wave is a separate 0.57px
median, 4.46px max.

**The lesson is the scope, not the number.** A report about the reference page
is not a report about the stage; check which one is being watched before
changing a tunable that only the stage reads.

### A word past its turn SETTLES; it does not resume (2026-08-13)

Reported as motion running in reverse, and clarified as: a newly appeared
word's motion runs, and then an OLDER word's runs after it.

The mechanism is a remount. A row re-break rebuilds a word, and the arming
effect re-derives `--turn-delay` against the frozen absolute turn moment -- so
a word remounted after its turn gets a NEGATIVE delay, and a negative delay
inside the animation's span resumes it mid-curve. The old word replays its
tail, right after the new word that caused the re-break played its rise.

**THE TAIL EXTENSION IS WHY THIS SURFACED.** That span was rise+fall = 424ms
and is now up to 1051ms, so the window in which a remount replays instead of
landing already-finished is more than twice as wide.

Fixed by `SETTLE_GRACE_MS`: past its turn by more than ~70ms a word writes
`-600000ms` and paints its end state. This is the standing rule applied where
it was not -- "live motion is a function of the timeline, not of arrival", and
"words under an older epoch must settle, never be re-derived". The grace is
there because a word can arm a few frames late purely from render timing, and
settling those would make ordinary words silently static.

**HONEST STATUS OF THE MEASUREMENT: it did not hold up.** The count of words
"armed mid-motion" read 27 before the fix, 1 after -- and then 0 both with the
fix and with it disabled on later runs. A within-row ordering probe
(`order2.py`) reported 0 out-of-order pairs in both states, so it proves
nothing either; the words involved are in EARLIER ROWS, which that probe never
looks at. The fix is kept because the mechanism is real and the rule already
required it, not because a measurement confirmed it. **Anyone re-opening this
needs a probe that watches across rows and survives run-to-run variance.**

### The join at the peak, and what the residual actually is (2026-08-13)

Splitting the envelope put two animations end to end at the word's own maximum,
and the first cut of it CORNERED there: the rise arrived at full speed and the
fall left at a different one, so the velocity stepped in a single frame. Value
continuity was never the issue -- both sides are exactly 1.0 at the boundary.

Fixed by making BOTH sides approach the peak with near-zero slope, which is
what a smooth maximum has. Doing it on both sides rather than matching the two
slopes to each other is deliberate: the durations are never equal, since the
fall stretches to reach the next word while the rise is fixed, so a matched
pair would hold for one ratio only.

**Measured: a 76% -> 62% step in the speed either side of the peak**, as a
fraction of the word's own fastest moment.

**THE RESIDUAL IS THE FILM'S OWN ASYMMETRY, NOT A DEFECT.** Its envelope rises
over 35.7% and falls over 64.3% -- a 1.8x speed ratio, which is exactly a
45-55% step by this measure. Two further attempts confirmed it: flattening the
peak harder moved nothing (53% -> 55%), and running the film's return at the
film's speed with a separate low drift behind it also moved nothing (54%) while
making the stage deader, 16% -> 27% of samples with nothing moving, because a
drift below 0.12 amplitude is invisible. That second attempt is reverted;
`tailSegmentsMs` is kept with the reasoning, since it is sound and only the
premise was wrong.

**Do not re-fit this against a 30ms probe.** At that rate a 151ms rise gets
five samples, and "the fastest of the three before the peak" is the rise's
midpoint rather than its approach -- which is why the metric bottoms out at the
envelope's own asymmetry and cannot see past it.

### THE RISE IS FIXED, THE FALL REACHES THE NEXT WORD (2026-08-13)

A word popped, stopped dead, and the next one started from nothing, so the
stage read as switching on and off rather than as one continuous motion.
**Measured before changing anything: 42% of all samples had NOTHING moving**,
in 22 dead gaps with a median of 0.21s and a longest of 2.31s.

The envelope is now SPLIT at its own peak (35.7% for the crest, 42% for the
lift) into two animations that run back to back. **The rise keeps its absolute
duration** -- the moment a word starts growing is the moment it is spoken, and
that is what CWI 2.2.2 is about, so stretching it would decouple the cue from
the audio. Only the return is stretched, out to the next word's turn.

`fallDurationMs` in `motion-timing.ts`; capped at 4s, because a word still
easing four seconds later reads as a stuck animation rather than as continuity.

**Result: 42% -> 24% dead**, with gaps longer than 0.3s going 9 -> 2 and the
longest 2.31s -> 1.80s. Words carry tails up to 1.29s where the neighbour is
known.

**THE NEIGHBOUR ARRIVES TOO LATE TO USE, and that is why the default tail is
long.** The obvious design -- wait for the next word, then set the fall to
reach it -- cannot work: a word turns 1.75s after arriving, and the word after
a two-second pause lands about half a second AFTER that. So the gap that most
needs filling is precisely the one that is not known in time, and revising the
duration then restarts the animation, which is a word visibly running its
motion twice. `unknownMs` (900ms) is therefore generous and never revised; an
early neighbour just starts its own motion over this one's tail, which is
allowed -- there is no concurrency cap.

The residual 24% is 22 gaps under 0.3s plus two ~1.8s silences the film itself
contains. Most of the short ones are the last, sub-pixel part of a fall
measuring as "still"; raising `unknownMs` closes the long two at the cost of
every word easing for longer.

Three things this got wrong first, all of them worth knowing:

- **Extending the CREST does nothing for most words.** ~75% of words do not
  pop, so their size amplitude is exactly zero and a longer decay of zero is
  still zero. The channel every word carries is the LIFT, and that is what had
  to be split. The first attempt moved the dead time by 0%.
- **Specificity ate the animation name.** `.studio-shell[data-motion="enhanced"]
  .word-glyph` sets `animation-name`, and a less specific rule setting the
  `animation` shorthand did not win it back -- the element ended up with ONE
  animation name and TWO durations, so the pop ran at the rise's 151ms instead
  of 424ms. Read it out of the DOM; it is invisible in the source.
- **An animation-NAME change restarts the motion, so the tail mode must not
  flip.** `data-tail` was conditional on the next onset being known, so a word
  whose neighbour arrived late flipped from `natural` to `extended` AFTER it
  had turned and ran its whole motion a second time. Reported by the user
  before any probe caught it: `word_remotion.py` needed `REST_RUN` dropped from
  8 to 3 samples to see it, because the word re-fired while still inside its
  own return and was never still long enough to count.
- **Do not run another CDP probe against the server before tracing.** Doing so
  pushed the trace past the end of the sample and it measured a settled stage:
  78% dead and an 11.82s "gap" that was the clip having finished. Restart the
  server and keep the timing identical to the baseline run.

### The window has to scale with the swell (2026-08-12)

The enhanced size cue ran a **fixed 424 ms for every word**, whatever size that
word reached. An ordinary word travels the 8.6% pop in that window; a shouted
one travels the pop *plus* the whole 2.3 crest, up to 1.56x. Same window, ~7x
the distance — so the size channel's peak velocity climbed with its amplitude
and the biggest words snapped. Reported as *"some pop motions are too fast ->
looks aggressive"*, and it was the large ones.

The window now runs `word_motion_enhanced_ms + push x
word_motion_enhanced_emphasis_ms`, i.e. 424 ms at rest and 1050 ms at full
emphasis — the same ceiling the legacy crest already tops out at.
`push` is `emphasisOf`, zero inside the 2.3 deadband, so **the median word is
bit-identical**. Measured over the sample: ordinary words 424 ms (65 of 106),
mid 541 ms, large 746 ms with a maximum of 989 ms. Amplitude-per-window on the
largest words is roughly halved.

**The cost, stated:** a 989 ms window outlasts the gap between words, so two
emphatic words can now be at size together. That is what the fixed window was
originally chosen to prevent. It is accepted here — there is no concurrency cap
by design, and overlapping pops during fast speech are the design system
working — but if the stage ever reads as crowded, this is the trade to revisit
first, not the amplitude.

**Observed and NOT implemented:** `WHOOOOOA!!` gets a "rainbow slow pop". It is
one caption, on a `--` (speakerless) line, and no non-arbitrary trigger for it
exists in what we measure — implementing it would mean matching a literal
string. Recorded here rather than fitted.

The syllable splitter is worth reading before changing: a fixed pair
(`floor(index / 2)`) gets `se|en` and `Gu|mp` right and `but|ton` wrong, which
is why `syllables.ts` exists. Its tests are the film's own six splits.

## Measuring motion against the film

`scripts/motion_diff.py` (per-word size envelope, turn-aligned and normalised),
`scripts/word_by_word.py` (the same word on the same audio, as curves),
`scripts/weight_diff.py` (does weight animate).

**Watch `live --sample` before believing any number they produce.** A per-word
envelope is normalised by each word's own rest and aligned on its own turn, so it
divides out type size, density, how many words move at once and the rhythm of the
line. Every enhanced statistic sat inside the film's confidence interval while
the stage still read wrong, and that is how the wrong default shipped for a day.

**Put BOTH motion systems beside the reference.** Legacy was never once compared
to the film; every measurement was enhanced-versus-film. That is the process
failure behind all of the above.

**Never capture with `--loop`** — a restart changes the epoch, so words repaint
in read-ahead ink and settle without motion, which measures as a flat envelope.

### Nine ways this measurement lied before it worked

Each produced a confident wrong number first.

* **Asymmetric ink thresholds** — testing read-ahead white with `r,g,b > 170`
  while testing turned ink by hue is stricter for white, so untouched words
  measured ~9% shorter. It read as the film rendering read-ahead at 0.91×, a
  channel that does not exist.
* **Max-column height** — keys on one antialiased stroke; swept across
  thresholds it reported 1.05×, 2.00×, 1.14× and 1.40× for the same film.
* **Ink area** — stable but biased low, because a swollen word overflows its
  fixed slot. Vertical extent with a 2px-per-row floor has neither problem.
* **A hardcoded caption band** — the Gump section captions low over video, the
  demo mid-frame on black. A fixed band discarded every section but one.
* **The layout guide rules** — one full-width rule puts ink in every column and
  collapses a line into a single run. `_derule` erases any row or column covered
  >55%.
* **Cut detection by profile correlation** — a popping word decorrelates its own
  caption, so captions were cut mid-life and 101 of 153 slots had no turn inside
  their own shot. Overlap of the inked COLUMN SET is stable under a pop.
* **Turn detection by hue** — matching green and yellow only discarded every word
  in another speaker's colour, a third of the reference. Use chroma.
* **Grid-quantised summary metrics** — read off the 0.02 s grid, peak time and
  width quantise, so whichever was made exact threw the other a full step out
  forever. Both are sub-grid now (parabolic vertex, interpolated half-maximum).
* **A unit error and a contaminated population** — `motion_trace` records
  milliseconds, and read as seconds it produced a perfectly flat envelope that
  looked like a result; and a word spoken before the capture starts changes
  colour when attribution resolves, which a naive detector calls a turn.

One more, in `weight_diff.py`: **Roboto Flex has thirteen variation axes**, so a
`set_variation_by_axes` call passing three silently renders the default instance
and calibrates a flat line — which then "proves" the film's weight never moves,
from no data at all.

## Before changing anything

1. **Screenshot it.** Three numeric probes called a glyph-anchoring change
   "probably fine"; one screenshot showed words overlapping and clipped off the
   stage. Layout and typography bugs are visual.
2. Use `scripts/word_motion.py`, not an ad-hoc aggregate. `max/min` over a
   word's samples cannot tell growth from shrinkage, and font-size alone misses
   the pop, which is a transform.
3. Re-run `scripts/ink_collision.py`. There is no clearance left; the next
   amplitude increase collides.
4. If a knob measures as a no-op, **say so and stop** — do not reach past it
   into shared structure. `voice_scale_range[0]` is inert because 2.3.6's
   3%/5% ratio is reached first; changing the mapping to make it bind also
   changed `reachableScaleRange`, which the hold and wave read, and broke the
   held word.
