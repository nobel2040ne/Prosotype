# Caption with Intention — Design System V1.0, extracted values

Source: [Design System PDF](https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf)
(V1.0 | 2025.1, 54 pp., captionwithintention.org, with the Chicago Hearing
Society). These are the exact values our implementation uses; section numbers
refer to the PDF. Also downloadable there: After Effects project, Roboto Flex TTF.

## 2.1 Attribution (speaker → color)

**Main characters (2.1.1)** — six colors, hex exact; assign in wheel order:

| # | Name | Hex |
|---|---|---|
| 01 | CI Main Yellow | `#E5E517` |
| 02 | CI Main Green | `#17E517` |
| 03 | CI Main Blue | `#17E5E5` |
| 04 | CI Main Pink | `#E517E5` |
| 05 | CI Main Red | `#E51717` |
| 06 | CI Main Orange | `#E58017` |

Guidance: 3 main characters → space colors far apart; hero and villain →
opposite colors.

**Supporting characters (2.1.2)** — 12 colors falling between the mains:
`#E85C2E #EBC247 #C2EB47 #82ED5E #47EB70 #5EEDC9 #47C2EB #5E82ED #8C6BED
#CC6BED #EB47C2 #ED5E82`. Keep supporting hues visually distant from main
hues in use (2.1.3).

**Minor characters (2.1.4)** — pastels from the wheel center: HSB S:30% B:90%
at listed hue angles (0°, 7°, 24°, 40°, 58°, 73°, 87°, 102°, 120°, 133°,
149°, 162°, 178°, 193°, 207°, 222°, 240°, 251°, 267°, 282°, 298°, 313°,
327°, 342°).

**Off-camera characters (2.1.5)** — same color rules, *italic* type.
(Not automatable from audio alone — not implemented.)

## 2.2 Synchronization

- **2.2.1 Read-ahead type**: every line first appears whole, in **white at
  90% opacity**, so viewers can read ahead at their own pace.
- **2.2.2 Color sync**: each word changes to the character color **as soon as
  its sound begins** (onset, not offset — "inexplicable" flips when "In" is
  spoken).
- **2.2.3 Motion** — the whole synchronization motion, stated outright:

  > To further ensure synchronization and guide the viewer's eye to the exact
  > part of the caption being spoken, Caption with Intention adds a motion
  > element to **each word as it changes color**. Each word should undergo a
  > **15% increase in type size before returning to its original size**,
  > creating a "pop" motion effect.

  The diagram on the same page labels the rise **25% elevation**.

  Three things follow, and all three were got wrong here before the PDF was
  read directly:
  1. The cue is **per WORD**, not per character (2.2.4 confirms: "In most
     cases, words will be spoken and animated **fully, one by one**" —
     syllable-at-a-time is the documented exception).
  2. Its amplitude is a **constant**. It is a synchronization cue whose job is
     to point the eye; it is not prosody. Per-word amplitude belongs to
     intonation (2.3.3–2.3.6), a different scope. Collapsing the two is what
     produced motion that was large on words the reference leaves still.
  3. Size **is** animated. The After Effects template contains no scale
     animator, and this project followed the template for several rounds — but
     the written design system is explicit, and it wins. `motion.elevation_em`
     and the template's position-only reading remain as the calm variant.
- **2.2.4 Syllable variation**: optionally animate syllable-by-syllable for
  drawn-out delivery ("un-be-lie-va-ble"). **Implemented** as a colour wipe
  across an already-visible word, gated to drawn-out words — see below.

## 2.3 Intonation (Roboto Flex)

- Typeface: **Roboto Flex** variable (2.3.1–2.3.2).
- **Volume → type size** (2.3.3): louder = larger.
- **Unit** (2.3.4): type size is a **percentage of screen height** — absolute
  across 1080p/4K/8K and all aspect ratios (1.85:1, 2.39:1, 16:9, IMAX shown
  in 2.3.5).
- **Baseline size** (2.3.5): normal speaking volume = **5%** of screen height.
- **Size range** (2.3.6): whisper **3%** … shout **12%**. Scaling within the
  range may be judged by ear or derived from waveform analysis.
- **Pitch & harmonics** (2.3.7): lower voices → heavier + wider; higher
  voices → lighter + condensed.
- **Baseline weight** (2.3.8): typical voice ~80–250 Hz; **160–200 Hz →
  Roboto Flex Regular 400**.
- **Weight/width ranges** (2.3.9–2.3.10): pitch chart maps ~80 Hz → wght 1000
  down to ~250 Hz → wght 100 ("the higher the pitch, the lighter the font").
  Harmonics chart maps width ~150 → 25 ("the fewer the lower harmonics, the
  tighter the font"). We implement weight (domain 80–250 Hz → 1000–100,
  unvoiced → 400) and the 150→25 width axis. Live currently uses pitch as the
  local proxy for harmonic distribution; a dedicated spectral-harmonics
  feature would be a future refinement.

## 2.4 Elements rules

- **Captions Box (2.4.1)**: all captions sit in a box of **90% black**
  (60/70/80/100% shown rejected). Exception: very loud/sudden bursts may
  break out of the box. (Breakout not implemented.)
- **Box size (2.4.2)**: the box hugs and scales with the text; multiple
  caption lines → multiple boxes, **max two on screen**, with spacing.
- **Work area (2.4.3)**: captions occupy the **lower 20% of the frame** with
  proportional safety margins; figure shows (top→bottom) 5% / 2.5% / 5% /
  **7.5% bottom margin**, safe areas left/right.
- **Sound effects (2.4.4)**: white, in `[brackets]`, but still animated
  (size pop with the sound). (Not implemented.)
- **Music (2.4.5)**: ♫ symbols around a white descriptor; static, no color
  or animation. (Not implemented.)

## 3. Other considerations

- **Exceptions (3.1)**: e.g. black-and-white films may drop color attribution
  and keep only animation — editor's discretion.
- **Distribution (3.2)**: until players support it, distribute as burned-in
  open captions.
- **3.3–3.4**: CWI augments (not replaces) FCC-regulated closed captions;
  anything unaddressed defaults to classic CC rules.
- **Automation (3.5)**: the stated end-goal is an AI system automating CWI,
  open-source and free — i.e., exactly what this project prototypes.

## Motion, read from the AE template

Source: `AE PROJECT/AE PROJECT/Academy_CI_Template.aep` (the official template
shipped with the design system). Its expressions and property inventory are
recoverable with `strings`.

The complete inventory of animated text properties in that project is:

```
16  ADBE Text Position 3D
 8  ADBE Text Fill Color
12  range selectors (Index Start/End/Offset, Levels Max/Min Ease)
```

`ADBE Text Scale|Tracking|Size|Rotation|Blur|Opacity` appears **zero** times.
**CWI motion is vertical position plus the color turn. Nothing scales.**

This is not only a fidelity point. Type size *is* the loudness channel
(2.3.3–2.3.6). A per-word size pop would make every word transiently read as
louder than it was spoken, so the free channel — vertical position — carries
the "guide the eye" role instead. We removed our earlier 15% scale pop on this
evidence.

Per caption line the template has three animators:

1. `Words` — fill color.
2. `Up` — the lift: `y = -thisComp.layer("Control_Null").effect("amp")("Slider")`,
   with `effect("COLOR_01")("Color")` on the *same* animator, so color and
   motion are phase-locked to one selector.
3. `Antecipate` — the same sweep shifted 1–4 frames earlier
   (~33–133 ms at 30 fps) using `easeOut` instead of `ease`, so **motion
   reaches a word before its color does**.

The sweep walks a one-word-wide Range Selector along the line between the
`[START]` and `[END]` layer markers:

```js
ret = ease(time, inTime, durMarkers + inTime, 0, textLenWords);
```

Because the selector has Ease High/Low set, neighbouring words are *partially*
displaced as it passes — the line reads as one travelling wave, not a row of
isolated twitches.

Live-mode adaptation: we keep the color turn exactly on the spoken onset
(2.2.2 is explicit about onset).

**The neighbour bleed is off by default (`motion.neighbor_bleed: 0`).** The
template animates a finished line that the viewer watches play through, so a
wave passing along it disturbs nothing. Live, words accumulate and stay on
screen: displacing a settled word moves text somebody is still reading, which
is the opposite of what read-ahead exists for. Only the word being spoken
moves, and each word moves exactly once — `dataset.moved` guards re-entry, and
an endpoint verification re-states the phrase without replaying any motion.
Raise `neighbor_bleed` above 0 to restore the template's travelling wave.

## Closed captions vs live — what each can actually do

`autocwi cc spec.json` renders a finished CaptionSpec against a clock. Because
the text exists before it is spoken, it is the **faithful** CWI implementation
and the reference the live renderer is measured against:

| behaviour | `cc` (authored) | `live` (ASR) |
|---|---|---|
| read-ahead (2.2.1) | real — line legible in white first | impossible; ASR has no future |
| colour turn (2.2.2) | sweeps through the word's letters over its span | flip at commit |
| anticipation lead | exact (template's 1-4 frames) | approximated by lifting the next word |
| travelling wave | on — a caption plays through | off — would displace settled transcript |
| determinism | pure function of `t`; scrub back = same frame | monotonic, best-effort |

### Read off the reference captures (docs/*.mov, docs/*.png)

The user's captures of the official site settle three things the PDF notes and
the free AE template could not:

1. **The colour boundary lands INSIDE a word.** "Roya|le with Cheese!" — orange
   through `Roya`, white from `le`. Character-level, not word-level.
2. **There is a travelling wave at CHARACTER level.** In the intonation demo a
   single word renders with its letters at different heights and sizes —
   `a`(base) `ni`(raised, larger) `mati`(lowered, smaller) — and the diagram
   frame shows `con`+`sec`+`tet`+`ur` stepping up around the playhead. The
   letter, not the word, is the unit of animation.
3. **Films use the calm version.** The three film stills (Royale / Thank you /
   Star Command) show every character on ONE baseline with only the colour
   sweep. The wave appears in the *intonation demonstration*, not in shipped
   captions — so it is a capability to expose, not a default to force.

4. **Size and weight are TRANSIENT, not baked.** Consecutive frames show
   "types **sizes**, weights…" then "types sizes, **weights**…" — with `sizes`
   back to normal. Emphasis travels with the spoken boundary and settles
   behind it, which is exactly why every film still looks uniformly sized.
   So prosody sets how far a letter *excursions* as the wave crosses it, not
   where it rests. Everything rests at the CWI baseline.

5. **Two motions, two scopes.** Frame-by-frame at 120 fps: `sizes` is
   uniformly large across *all* its letters and holds for several frames,
   while `weights` visibly **bolds before it turns yellow**. So size/weight is
   a slow per-WORD envelope that leads the colour turn (the template's
   `Antecipate`), and only the vertical lift travels letter to letter
   ("a-ni-mati-o"). Modelling emphasis as a per-character ripple was wrong.

Implemented in `autocwi/ccpage.py` as one span per character:
`closed_caption.wave_reach` (how far either side of the boundary the ripple
extends, as a fraction of the word) and `wave_scale` (peak letter scale, CWI
2.2.3's 15%). Setting `wave_reach: 0` gives the film-still behaviour.

Film-still layout also differs from our live stage: centred, ONE line, a tight
box hugging the text, and type noticeably smaller than ours. Our live stage is
left-aligned and accumulates by explicit user preference — a deliberate
divergence, recorded here so it is not mistaken for a bug.

**On "alphabet-level" motion:** the AE template drives a *word*-index Range
Selector (`textLenWords`; the animator is literally named `Words`) — but with
Ease High/Low set, so the hand-off between consecutive words is smoothed
*across characters*. Word-level timing produces character-level appearance.
`closed_caption.sync_granularity: character|word` exposes both readings.

## Syllable variation (2.2.4) — what the timing actually supports

**It is a colour wipe, never a typewriter reveal.** The word is already fully
visible in white; only the boundary between spoken colour and unspoken white
moves through it. Revealing characters progressively would destroy the 2.2.1
read-ahead, which is the property that lets a Deaf viewer read at their own
pace rather than the speaker's. That would be a regression dressed as a
feature.

The transducer quantizes timestamps to its encoder frame (80 ms), and short
words emit every sub-word piece on a single frame:

```
' y' 2.24   'e' 2.24   'llow' 2.24        <- "yellow": no internal timing at all
' s' 4.56   'qu' 4.56  'al' 4.64  'id' 4.72  <- "squalid": 3 distinct onsets
```

So genuine per-syllable timing exists only for drawn-out words — exactly the
case 2.2.4 is written for. `HypothesisWord.pieces` keeps the sub-word tokens,
`syllables()` merges those sharing a frame, and `_syllable_stops()` gates on
`motion.syllable_fill` in `config.yaml` and emits
`{"t": fraction of span, "c": fraction of characters}` stops. On the bundled
test audio this fires for about 7% of words (`nightfall`, `dishonoured`,
`mortals`, `finally`), which matches "optionally, for drawn-out delivery".

Verified endpoint words carry no pieces (they are re-timed from scratch), so
they fall back to the plain whole-word turn.

## Recognizer choice

Measured on the stress matrix, July 2026, with `--streaming-model`:

| model | matrix WER |
|---|---|
| `nemotron-speech-streaming-en-0.6b` (2026-04-25) | **2.27%** (7/308) |
| `nemotron-3.5-asr-streaming-0.6b` (2026-06-11) | 3.25% (10/308) |

The newer 3.5 checkpoint is *multilingual* (40 locales) and loses on English
across every stressed condition, so English live mode stays on the 2026-04-25
English model. Re-run this A/B with `--streaming-model` before adopting any new
checkpoint.

## Read-ahead does not survive contact with live ASR

CWI 2.2.1 has the line appear whole, in white, *before* it is spoken. That works
because a film caption is authored in advance: it never revises, and that
stability is exactly what lets a viewer read ahead at their own pace.

Live ASR has no such line. It guesses and corrects. Rendering those guesses as
read-ahead measured, on one 48-word utterance:

| stage churn | readahead | stable |
|---|---|---|
| word deletions | 96 | **0** |
| in-place rewrites | 23 | **0** |

Text that will not hold still is not read-ahead — it is the opposite, because
the reader cannot get ahead of it. `display.mode: stable` therefore renders only
words the accurate stream has committed: they appear in spoken order, one at a
time, and never change. The cost is latency, ~1.1 s behind the voice instead of
~0.2 s. `display.mode: readahead` restores the speculative layer.

The speculative hypothesis still drives the sidebar timeline and status line in
stable mode, so what the recognizer is working on stays visible without
rewriting the captions.

### Three display modes

`display.mode` in config.yaml:

- **`sentence`** — turn-taking. Nothing shows until an utterance is
  finalized; then it is split into sentences and each is revealed as a whole
  settled line, no per-word motion. This is what "sentence by sentence" needs,
  with one wrinkle: the streaming words are lowercase and unpunctuated, so the
  sentence *boundaries* come from the verifier's punctuated text, not the
  streaming stream. The endpoint verifier is coarse (it waits for a real pause),
  so a fast passage can finalize as one long utterance; splitting on `.?!`
  recovers the individual sentences from it. Reducing `endpoint_silence_s` to
  segment acoustically instead was rejected — 0.6 s gave 8 turns but WER rose
  2.27%→8.77%.
- **`fast`** (the shipped default) — stable's settled words plus the ACCURATE stream's own
  tail as white read-ahead. Measured ~35% less revision than draft read-ahead,
  and its revisions are mostly a trailing word completing its spelling. This
  is also how a lone word becomes visible without waiting for the endpoint:
  the trailing word is deliberately never committed early (measured: an early
  release saves no time and commits truncations), it shows white instead.
- **`stable`** — committed words one at a time, ~1.1 s behind, never revised.
- **`readahead`** — also shows the 160 ms draft; lowest latency, visible churn.

## Expression response — why the raw mapping looked wrong

CWI's anchors are absolute: 3% whisper / 5% normal / 12% shout, wght 1000 at
80 Hz down to 100 at 250 Hz. Those describe *deliberate* dynamics — a whisper,
a shout, one character against another.

Applied raw to per-word acoustics of a single speaker they mistake the natural
amplitude envelope of connected speech for intent. Measured on one calm
sentence of the bundled test audio:

| on one calm sentence (18 words) | before | after |
|---|---|---|
| type size | 3.0%–9.7% (**3.2x**) | holds 4–6.5%, centred on 5% |
| size changes | every word (17/17) | 4/17 |
| weight | 400–977 (spread 577) | constant |

Unstressed function words ("would", "and", "the") were rendering at 3% — the
whisper size — and "early"/"yellow" near shout size, in a sentence read at one
steady volume. Unvoiced words snapped from wght 958 to 400 and back mid-line.

`expression` in `config.yaml` controls three stages, all of which turned out to
be necessary:

1. **Response curve.** How much of each deviation from the speaker's own
   running baseline survives. This is a power curve, not a linear scale:
   scaling deviation linearly also shrinks the extremes, so a genuine whisper
   could never reach 3% however quietly it was spoken. `response: 1.0` is the
   literal CWI mapping.
2. **Running median** over `smoothing_words`. A median, not an average — an
   average let one emphatic word drag the value up and decay slowly, so a
   single loud word resized the following half-dozen. A median ignores an
   isolated outlier outright and still follows sustained change.
3. **Discrete levels with hysteresis.** The value is held on a step until it
   passes the boundary with the *adjacent* level by `hysteresis` of the gap.
   Levels move one at a time. Measuring against the nearest level instead lets
   large jumps skip levels; measuring against a distant one makes the last step
   unreachable.

Unvoiced words hold the speaker's baseline rather than snapping to Regular 400,
because for a deep voice already near wght 950 a drop to 400 reads as a
different speaker, not a quieter word.

Verified behaviour (levels per word, `size_steps` = 3/4/5/6.5/9/12):

```
steady normal        5 5 5 5 5 5 5 5 5 5          0 changes
single loud word     5 5 5 5 5 5 5 5              0 changes
emphasis every 3rd   5 5 5 5 5 5 5 5 5 5          0 changes
sustained shout      5 5 5 5 6.5 9 12 12 12 12    3 changes
sustained whisper    5 5 5 5 4 3 3 3 3 3          2 changes
```

Noise produces no change at all; real dynamics still reach the ends of the
scale.

## Implementation status here

Implemented: main+supporting palettes, streaming-hypothesis read-ahead,
accurate-profile provisional color cues, stable final words, baseline-anchored
vertical lift with the template's anticipation and neighbour bleed, eased color
turn, syllable variation for drawn-out words, synchronization timeline,
%-of-height sizing (3/5/12), absolute-Hz weight + width mapping, live intonation meters, 90% captions
box, bottom margin, and max-two-boxes (live page).
Not implemented: minor-character pastels, off-camera italics, dedicated
harmonic-spectrum analysis, box breakout, sound-effect/music captions.
