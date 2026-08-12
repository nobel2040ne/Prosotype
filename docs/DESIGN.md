# Caption with Intention — Design System V1.0, extracted values

> **READ THE PDF, NOT THIS FILE, FOR ANY NUMBER YOU ARE ABOUT TO IMPLEMENT.**
> `cwi-design-system-v1.0.pdf` is the source of truth. This file mixes the
> PDF's stated values with interpretations fitted to `reference/*.mov`, and
> where the two disagree the fitted material has been wrong every time — the
> recordings are the project's *website*, not the spec. Treat it as a
> changelog of superseded interpretation. `../CLAUDE.md` holds the current
> contract.

Source: [Design System PDF](https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf)
(V1.0 | 2025.1, 54 pp., captionwithintention.org, with the Chicago Hearing
Society). Section numbers refer to the PDF. These were the values the
implementation used WHEN EACH SECTION WAS WRITTEN, which is not the same as
what it uses now — see the warning above, and CLAUDE.md for the live contract. Also downloadable there: After Effects project, Roboto Flex TTF.

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
  1. The cue is **triggered per WORD** (2.2.4: words are normally animated
     fully, one by one), but the website recording eases that word event
     through its character spans. In other words, event ownership is
     word-level while the visible synchronization hand-off can be
     alphabet-level. This does not make the caption a typewriter reveal:
     every letter is already present.
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
That describes the downloadable template's calmer implementation, not the
whole design-system contract. The PDF is authoritative and §2.2.3 explicitly
requires the 15% temporary pop as well as the diagram's 25% elevation. Live and
`cc` therefore implement both as a transient transform that returns to rest.
In live, a separate overlaid glyph carries the §2.3 size/weight/width excursion
during that same one-shot window; normal type owns layout and every axis returns
to 5% / Regular 400 / width 100. Voice never changes synchronization amplitude.

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

Live-mode adaptation: authored CWI can place read-ahead type before speech,
but an open-caption word cannot exist until ASR supplies it. `stable`, `fast`,
and `readahead` therefore treat the node's first paint as its visual activation.
The base §2.2.3 cue is then shaped by the word's measured delivery: loudness
sets the temporary size excursion, pitch sets temporary weight, and the
available spectral proxy sets temporary width. These axes do **not** share one
temporal envelope: pitch/weight has the earliest attack and release,
loudness/size breathes through the middle, and resonance/width arrives later.
All three use smoothstep at both ends. A separate character-local curve follows
the website recording, but adjacent samples are blended into a continuous
upward ribbon before paint. Each already-visible letter lifts/pops gently near
its own turn and settles before the wave reaches the end of the word. There is
no below-baseline anticipation: the earlier crouch made alternating letters
look like a zipper rather than one travelling boundary. The ranges are
deliberately compressed for a stacked transcript. Every wrapper and character
returns to the same normal-font rest (`scale(1)`, no character transform,
weight 400, width 100).

The [Quickstart Guide](Caption%20with%20Intention%20%E2%80%93%20Quickstart%20Guide.pdf)
confirms that animation timing belongs to the `[START]`/`[END]` markers rather
than to the layer's `IN`/`OUT` lifetime. Live preserves that separation:
first-paint geometry has one monotonic 520–720 ms clock, while the later
speaker-colour decision owns only the white→speaker-colour sweep. Verification
can revise text or attribution during that clock without restarting or
settling it early; after the clock finishes, no later event can move the word.
Replayed history never moves. The live cue is the design system's own
15% scale / 0.25 em elevation, and the voice shapes the transient crest (2.3);
the alphabet hand-off adds at most 0.085 em lift and 3% local pop, with zero
pre-turn crouch. A `0.72` neighbour blend turns the sampled character phases
into one smooth ribbon. Its separate virtual clock spaces character turns by
0.18 s (capped at 2.20 s) before mapping them into the same bounded 520–720 ms
display window. The word wrapper keeps its own compact clock, so spelling
length cannot compress its attack.

Fast live speech is handled without delaying text. Acoustic word span maps the
complete motion continuously from 520 to 720 ms, while
`fast_speech_motion_gain` eases its travel from 0.58 to 1.0. Slow delivery also
delays the independent axis peaks by up to 6% of that longer window; this makes
a sustained word develop more languidly instead of replaying one generic curve.
Reveal/onset scheduling stays unchanged. In the standard sample this produces
roughly 53–110 ms between character turns. The measured fast-word
weight/size/width attacks are about 156/218/260 ms, compared with
244/346/397 ms for a drawn word. Bounded loudness and pitch response still
makes quiet, grounded, bright, strong, and neutral deliveries perceptibly
different. These are diagnostic descriptions of continuous motion, not canned
effects.

The 2026-07-24 browser sample check captured the distinction directly from
painted styles. On “Are,” weight had reached 69% while size was at 41% and
width at 33%; later, width remained at 100% while weight had released to 64%.
Across the captured phrase, temporary size targets ranged from 0.78× to 1.34×
and weight excursions ranged from 56 units lighter to 79 units heavier. The
completed page reported zero animation restarts, zero moving words, zero active
character transforms, and zero non-normal variable-font axes.

Words reveal sequentially using their acoustic onset gaps, with at most two
active together. Before the spelling is known, the phone sidecar may advance
one confidence-gated prefix on the same first-word node (`H → He → Hel`) and
send duration-only updates while the current sound is held. The letters
themselves remain stable; a short paint-on trail after the last known letter
represents continuing duration. Once the authoritative spelling is known, a
drawn-out word keeps that full spelling visible and advances colour through
measured syllable/phoneme stops. This is the closest honest live equivalent of
§2.2.1/2.2.4 when future text is unavailable.
The sweep interpolates the colour of each existing character span; applying
`background-clip:text` to a parent containing those spans is unsafe in Chromium
and can visually stack all glyphs at one origin.

The PDF does not prescribe attack/hold/release durations or easing;
`motion.live_sync.rise_s`, `peak_s`, and `fall_s` are tunable implementation
defaults.

The legacy Web Animations neighbour lift and analytic neighbour push are both
off in stacked live mode (`motion.neighbor_bleed: 0`,
`motion.live_sync.neighbor_push: false`). Only the active word and its own
character spans move. Each word's activation still runs once —
`dataset.moved` guards re-entry, and endpoint or speaker verification never
restarts motion.

## Closed captions vs live — what each can actually do

`autocwi cc spec.json` renders a finished CaptionSpec against a clock. Because
the text exists before it is spoken, it is the **faithful** CWI implementation
and the reference the live renderer is measured against:

| behaviour | `cc` (authored) | `live` (ASR) |
|---|---|---|
| read-ahead (2.2.1) | real — line legible in white first | impossible; ASR has no future |
| colour turn (2.2.2) | sweeps through the word's letters over its span | onset-aligned when the cue arrives in time; late events settle |
| alphabet synchronization | character lift/pop around each known turn | same curve rebased onto the one-time first-paint clock |
| timing clock | exact media clock | source-to-browser clock map; early schedule / late seek |
| neighbour displacement | authored line | analytic transform-only push when `neighbor_push` is enabled |
| determinism | pure function of `t`; scrub back = same frame | monotonic revision order; deterministic reducer |

### Read off the reference captures (docs/*.mov, docs/*.png)

> **THOSE RECORDINGS HAVE NO AUDIO STREAM.** `ffprobe` returns only
> `0,h264,video` for all three. Anything here keyed to loudness, pitch or
> voicing is therefore NOT a measurement — it was solved backwards out of the
> measured motion by `ccprosody.fit_spec_prosody`, and regressing motion
> against it returns confident nonsense (peak size vs loudness −0.02, weight vs
> pitch −0.54: all circular). What these captures CAN answer is what the motion
> DOES — `motion.scale/lift/dwght` are real pixel measurements and the word
> timings are read off the frames. The only source where motion AND audio are
> both real is `docs/reference/pr-film.mp4`, which is the PR film and what `--sample`
> streams.

The user's captures of the official site settle three things the PDF notes and
the free AE template could not:

1. **The colour boundary lands INSIDE a word.** "Roya|le with Cheese!" — orange
   through `Roya`, white from `le`. Character-level, not word-level.
2. **There is a travelling wave at CHARACTER level.** In the synchronization demo a
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
extends), `wave_lift_em`, and `wave_pop` (peak local character scale). The
wrapper's separate `sync_pop` retains CWI 2.2.3's 15% word cue. Setting
`wave_reach: 0` gives the film-still behaviour.

The authored film stills use one tight centred line. The live product is a
stacked adaptation: left-aligned, text-hugging boxes grow upward so recent
speech remains readable in context, and the oldest box leaves when the stage
fills. Each attributed speaker gets a separate paragraph. A late stable
attribution partitions the already-rendered nodes without replaying motion;
adjacent fragments attributed to the same speaker merge again when they fit.
Unknown speech stays neutral. `display.retention: linger` retains the bounded
two-box alternative.

**On "alphabet-level" motion:** the AE template drives a *word*-index Range
Selector (`textLenWords`; the animator is literally named `Words`) — but with
Ease High/Low set, so the website-style hand-off is visibly resolved across
character spans. Word-level ownership and character-level appearance are
composable, not contradictory. `closed_caption.sync_granularity:
character|word` exposes both readings; live always uses character appearance
inside the active word.

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

## (SUPERSEDED 2026-08-04) Read-ahead does not survive contact with live ASR

> **This section's conclusion is wrong and the studio now does the opposite.**
> It argued that live ASR cannot give CWI 2.2.1's read-ahead because it guesses
> and corrects. The missing piece was that read-ahead is not a property of the
> TEXT but of the PLAYHEAD: presenting from a clock that trails the acoustic
> one puts every word on screen before its own turn arrives, and a per-WORD
> floor (`min_read_ahead_ms`) guarantees it even when the recogniser delivers
> in bursts. MEASURED: words turning with under 100 ms of lead went **42% ->
> 0%**, median lead 170 ms -> ~700 ms. Kept for the measurement below, which is
> still a fair account of what raw hypothesis text does if you render it
> directly.

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

### Four display modes

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
- **`stable`** — committed words one at a time and the least revisable view.
- **`readahead`** — also loads and shows the 160 ms draft; lowest latency,
  visible churn. The draft is not loaded by the normal fast path because hidden
  draft inference delayed the more accurate words it was supposed to support.

All revisable modes now share one ordering/reduction path: text, timing,
speaker, source authority, finality, and SSE id are compared before a DOM
change. Updates coalesce once per word per animation frame, settled words never
roll back to provisional, and tentative-tail reconciliation moves or edits
stable nodes instead of rebuilding earlier lines.

## Continuous voice circle (live-only extension)

> **SUPERSEDED 2026-08-04: there is no line-edge circle any more.** It was
> removed at the user's request; the stage carries captions and nothing else.
> Everything below still describes the **Voice Compass**, which kept every
> channel — read "the indicator" as the compass alone.

The design-system type axes remain the semantic caption channels. Live also
has measurements before any word exists, so a small indicator immediately
after the active speaker line exposes them without guessing text or emotion.
A larger radar/minimap-style Voice Compass in the side grid mirrors the same
signals:

- outer radius = true captured RMS volume (`-60…-15 dBFS`);
- bead height = block-level autocorrelation F0 (`80…250 Hz`);
- inner oval width = spectral centroid (brightness);
- inner opacity/halo = periodicity (tonal/voiced strength).

The analyzer runs on each ~64 ms input block, and the browser smooths the
indicators separately from caption motion. They are never embedded in a glyph,
never change line geometry, and never revise a settled word. Unvoiced audio
centres/fades the bead instead of inventing a pitch. The large compass accepts
future `direction_deg`/`azimuth_deg` events, but reports `awaiting array` on the
current mono path. This is a live-only accessibility cue, not a claim that the
CWI V1.0 PDF specifies either circle.

The 2026-07-25 delivery extension adds only observable acoustic dimensions:
force, attack, F0 contour, voiced flow, and texture. The line orb gently tilts
with contour, stretches with flow/force, and changes its inner resonance with
texture; the large compass mirrors those channels without fabricating a mono
direction. The labels (`rising`, `falling`, `sustained`, `forceful`, `gentle`,
`textured`, `steady`) describe delivery, not emotion.

For caption words, the same values choose distinct *temporary paths*: a rising
word reaches its crest late, a falling word crests early and resolves, a
sustained word holds, forceful and gentle words use different travel/attack,
and texture appears as a non-jittering halo. This is a live adaptation, not a
new CWI V1.0 semantic channel. Speaker colour remains identity-only,
loudness→scale and pitch→weight stay interpretable, and every path finishes at
the exact common rest state. The backend freezes the dimensions before first
paint; a later colour, spelling, or attribution update cannot select a new
path.

These paths are deliberately sparse. Durable contour uses a 10 ms Praat track,
not the noisier two-frame orb estimate, and needs five voiced frames, 30%
coverage, octave filtering, and a ±0.45 deadband. This reduced expressive
profiles from 86–93% of ordinary standard-sample words to 22–29%. `steady`
words keep only 30% of the additional voice-shaped deviation, but still receive
the whole live synchronization cue: 15% scale and 0.25 em elevation. A
quiet-word intonation value cannot cancel that floor. All CSS paths begin near
the baseline and use a zero-slope curve; falling/forceful do not teleport into
their crest on the first frame.

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

## Implementation status

**Moved.** This section listed a reveal queue with "at most two active", a 25%
elevation and a 0.085 em character ribbon — all removed. The queue in
particular no longer exists at all: words are placed by their recorded onset,
not by arrival, so there are no slots, gaps or concurrency caps to describe.

The current, measured contract is the five-channel table at the top of
`../CLAUDE.md`'s motion section, and the acceptance figures are in
`TESTS.md`. Do not maintain a third copy here.
