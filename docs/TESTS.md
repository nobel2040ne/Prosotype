# Testing

Last updated: 2026-07-26

The normal pytest suite is **fully offline by design** — no model loads,
network, or video decoding. Audio is synthesised with known ground truth; the
reference recordings are represented by the CaptionSpecs already derived from
them. Keep it that way: a suite that needs 1.9 GB of weights or a 9 MB `.mov`
stops being run.

Generated pages retain structural source checks. The dependency-free renderer
reducer also runs under Node, and `scripts/live_render_probe.py` is the opt-in
real-DOM check for machines with the repository's existing Chrome installation.

## Running

```bash
python3.11 -m venv .venv                       # one time
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                     # the whole suite
.venv/bin/python -m pytest tests/test_speaker_attribution.py tests/test_schema.py -v
.venv/bin/python -m pytest tests/test_live.py tests/test_live_motion.py tests/test_live_render_core.py -v
node --test tests/cwi_motion_core.test.js tests/live_render_core.test.js
.venv/bin/python scripts/live_render_probe.py  # headless Chrome; no models/network
```

## Layout

```
tests/
├── fixtures/
│   └── forward_map_golden.json   441-point grid captured FROM the page's JS
├── test_schema.py      (8)  CaptionSpec validation, speaker fields, legacy specs
├── test_overlap.py     (5)  word -> speaker by max span overlap
├── test_fuse.py        (5)  per-speaker normalization, palette assignment
├── test_prosody.py     (3)  dB/F0 on synthetic tones with known answers
├── test_reference.py   (3)  the Python prosody mirror vs the golden grid
├── test_soundevents.py (14) local non-speech event state machine
├── test_live_motion.py (5)  live CWI transforms + first-display activation
├── cwi_motion_core.test.js  shared CWI envelope/rest invariants
├── live_render_core.test.js
│                      (25) revision/coalescing/mode/clock/motion reducer cases
├── test_live_render_core.py  runs the Node suite from the offline pytest suite
├── test_speaker_attribution.py
│                      (13) confidence lifecycle, revisions, SSE, haptics
└── test_live.py             live engine, both renderers, derived specs
```

`test_live.py` is most of the suite and covers four areas: the streaming
engine (batching, gain, endpoint verification, SSE replay), speaker tracking,
the live page, and the `cc` renderer plus the three derived reference specs.

`test_speaker_attribution.py` uses fixed synthetic unit embeddings and mock
timestamps only. It covers repeated enrollment, two separated voices, weak
short-turn continuity, unknown/ambiguous observations, switch hysteresis,
centroid update guards for short/overlap spans, provisional→stable revision,
provisional→corrected revision, same-`word_id` SSE reconstruction, provisional
haptic suppression, and repeated-run determinism. `test_schema.py` separately
pins status validation, probability clamping, and legacy CaptionSpec behavior.

`live_render_core.test.js` uses fixed word ids, timestamps, SSE ids, and
synthetic revisions. It covers one-node correction, stale speaker/text
protection, stable-state monotonicity, same-frame coalescing, separate-word
preservation, bounded queues, speaker-only and unchanged-verification updates,
replay/late/early clock decisions, curve continuity and return-to-rest,
`stable`/`fast`/`readahead` ownership, reduced motion, accurate-over-draft
authority, preservation of an independent newer text-revision counter,
first-display activation after an expired acoustic window, replay/reduced
suppression, Unicode-safe character-entry staggering, and repeated-run
determinism. It has no DOM or package dependency.

`scripts/live_render_probe.py` crosses the real generated-page boundary.
For all four display modes it injects the same burst (20 levels, three
hypotheses including an in-place text revision, cue, commit, verification,
correction, stale rollback) and records node creation/replacement, queue depth,
coalescing, stale rejection, geometry, recolour count, interpreting
state, motion starts/restarts, optional character-entry keyframes, and the
word's scheduled/actual/completed trace with its display/source trigger. This
is manual rather than pytest because Chrome is platform-specific.

The opt-in character slide is disabled by default; the production live path
should report `characterEntryStarts: 0`. A same-word text revision,
cue/commit colour change, verification, and speaker correction must leave the
motion-start counter unchanged. `sentence` intentionally keeps its whole-line
reveal and no per-word motion.

### Real `live --sample` acceptance run (2026-07-24)

This is deliberately a manual standard-sample check, not part of pytest:

```bash
.venv/bin/python -m autocwi live --sample
```

Opening the page before playback and reading `window.__cwiRenderDiag.report()`
after the sequential queue drained produced 56 sequential reveals and 51
first-paint motion starts, with zero animation restarts. The difference is
expected: endpoint verification reused five visual slots whose semantic motion
had already been spent, and correctly did not create late motion for the
corrected spelling. The maximum simultaneous motion count was 2. The browser
received 28 hypothesis batches, 264 level updates, and 49 timed cues, confirming
that this was a fresh live attachment rather than SSE-history reconstruction.

The final DOM had no queued or moving words, no overlaps, no duplicate live
word IDs, and no residual transforms or font axes: every settled word was at
identity transform, weight 400, width 100. The motion registry and animation
frame loop both drained to zero. Speaker-attributed boxes contained no mixed
speaker runs or empty paragraphs, and the final frame had no active colour
sweep or piled-up glyphs. The formerly unknown “Look, just” resolved as stable
S1, and the energy-retimed final “Some without sugar” resolved as stable S2 in
its own paragraph. Natural sample variation exercised:

- duration: 520–720 ms;
- motion profiles: quiet, grounded, bright, strong, and neutral;
- peak scale: approximately 0.858–1.474;
- peak lift: approximately 0.056–0.280 em;
- peak weight: 288–496;
- peak width: 87–114;
- 48 ordinary colour sweeps and 14 syllable/phoneme sweeps.

After separating the live variable-font clocks, a visible Chrome run sampled
the actual inline transform and `font-variation-settings` every 24 ms. The
curves were demonstrably not phase-locked: on “Are,” weight was at 0.686 of
its excursion while size was at 0.414 and width at 0.331; later width remained
at 1.0 while weight had released to 0.637. “where” temporarily shrank to about
0.90 while thickening, whereas “Are” swelled above 1.46 while becoming lighter.
Fast-word weight/size/width attacks measured about 156/218/260 ms; drawn-word
attacks measured about 244/346/397 ms. At drain, moving words, active character
transforms, and non-normal variable-font axes were all zero, with no browser
exceptions or animation restarts.

The alphabet-level synchronization pass was rechecked against
`docs/reference/synchronization.mov` and `intonation.mov`. The live
character-local maximum is now 0.085 em / 1.030 with no pre-turn crouch.
Before painting, adjacent phase samples receive a 0.72 spatial blend. This
preserves a readable travelling boundary but removes the alternating
above/below-baseline zipper that made the alphabet look as if it were
ziggling. Fast words still use a 0.58 distance gain, easing to 1.0 for slower
delivery, without lengthening the reveal queue.

The fresh attachment retained zero restarts and at most two active words.
After the queue drained, character residuals, variable-axis residuals,
overlaps, the motion registry, and the animation-frame handle were all zero;
separate S1/S2 paragraphs remained.

These values are a timing-sensitive browser observation, not a deterministic
unit-test assertion. The acceptance criteria are the bounds/invariants: at
most two active words, no restarts or overlap, distinct speaker paragraphs, a
drained queue, and exact normal-font rest.

On 2026-07-24 the required visible command
`.venv/bin/python -m autocwi live --sample` opened the live page, loaded the
accurate/verifier/speaker/onset stack, processed the bundled clip to “audio
source finished,” and stopped cleanly. The focused automated checks additionally
pin three new contracts:

- a 180 Hz block is estimated within 4 Hz without a model dependency;
- the onset state advances `H → He → Hel` sequentially on one `uN:w0` identity
  and emits increasing `sustain_s`;
- rendered live HTML contains the pitch/texture voice-circle channels and the
  Chrome render probe completes with zero long tasks.

The final regression run passed all 113 Python tests and all 33 render-core
Node tests.

### Accumulating-delay and Voice Compass regression (2026-07-24)

The reveal scheduler now carries its original deadline forward. The pure-core
probe fixes the late case at 580 ms (the former `now + gap` calculation would
have produced 660 ms). That checkpoint originally settled a word after 200 ms
behind two motions; the 2026-07-25 lossless first-paint section below supersedes
that overload policy while retaining the non-compounding deadline.

The browser probe also confirms:

- a test word moves from Regular 400 to weight 520 during its active window;
- the small line-edge circle receives live scale, pitch, texture, and opacity;
- the large side-grid compass receives independent scale, pitch, core size,
  texture, and an explicit `unknown` direction state;
- the radar never fabricates an azimuth on the mono sample.

The visible `.venv/bin/python -m autocwi live --sample` run loaded the accurate
stream, endpoint verifier, speaker attribution, non-speech lane, and onset
hints, then reached `audio source finished` and stopped cleanly. No screen
capture or `--file` path was used. The full regression run passed all 113
Python tests and all 33 Node render-core tests.

### Next.js studio acceptance (2026-07-24)

The product frontend now builds from `web/` as a Next.js static export. Python
serves that export, runtime presentation config, Roboto Flex, and `/events`
from one origin while retaining the generated diagnostic renderer at
`/legacy`. Handler tests cover the root document, immutable Next assets,
runtime JSON, font response, and legacy route.

The TypeScript reducer has focused contracts for:

- final text never rolling back to a stale hypothesis;
- speaker correction changing attribution without altering text/timing;
- replacement of only the obsolete tentative tail;
- the same 580 ms non-compounding deadline as the legacy live renderer; fresh
  words wait hidden for a free motion slot instead of silently settling.

Desktop Chrome at 1440×900 was inspected against a completed real
`.venv/bin/python -m autocwi live --sample` stream. It retained separate S1/S2
paragraphs, normal-font settled words, an attached line orb, and the
direction-unknown compass without clipping. The deterministic `?demo=1`
preview verified active waveform/pitch/texture channels and two-speaker color.
A 390×844 responsive capture found and then fixed a no-wrap overflow: narrow
screens now wrap only at word boundaries, keep the orb on the active line,
hide the competing footer action, and preserve access to presentation
settings.

The frontend gate is `npm --prefix web run check`: ESLint, four TypeScript
reducer tests, TypeScript production compilation, and static export. The npm
audit reports zero known vulnerabilities; explicit overrides keep the
transitive PostCSS and Sharp versions above their current advisory ranges.
The final combined run passed 115 Python tests, 33 shared/legacy JavaScript
motion tests, and four Next studio reducer tests. A final visible
`.venv/bin/python -m autocwi live --sample` selected the Next studio, processed
the complete bundled source to `audio source finished`, and stopped cleanly.

### English/Korean startup acceptance (2026-07-24 baseline)

The local startup boundary now has unit coverage for all parts that must remain
deterministic and offline:

- runtime config advertises `en` and `ko`;
- `/session` starts in `selecting`;
- one valid `POST /session/language` advances it to `loading`;
- a different later language returns HTTP 409;
- the Korean config overlay selects the int8 Zipformer files and disables the
  English draft, verifier, and TIMIT prefix sidecar;
- Korean leading-space tokens reconstruct separate 어절 while retaining timed
  syllable pieces inside `척하려구`.

The model acceptance is intentionally separate from pytest because it loads
downloaded weights. sherpa-onnx 1.13.4 decoded the official Korean test wave
through the exact configured online recognizer, and the full headless live path
produced seven durable words:

```text
걔는 괜찮은 척하려구 애 쓰는 거 같았다
```

The real standard command `.venv/bin/python -m autocwi live --sample` was also
started without `--lang`: Python served the new full-screen picker and waited
without loading ASR or beginning source capture. Choosing English advanced the
session through `loading` to `listening`; the 34.5-second sample then reached
`audio source finished` in real time and stopped cleanly. Desktop Chrome at
1440×1000 was inspected at both the picker and live-stage states. The final
regression passed 118 Python tests, 33 shared/legacy JavaScript tests, and four
Next.js TypeScript reducer tests; the Next production export also compiled
successfully.

### Korean ASR and long-paragraph acceptance (2026-07-25)

The Korean recognizer was measured before changing the configured model. CER
is Unicode alphanumeric character edit distance with spacing and punctuation
removed; RTF includes local streaming decode but not real-time source pacing.

| recognizer | bundled KSS CER | RTF | mean source time to first text |
|---|---:|---:|---:|
| 2024 streaming Zipformer (old) | 11/76 = 14.47% | 0.068 | 0.848 s |
| 2026 174M chunk-16 (selected) | **0/76 = 0%** | 0.083 | 1.152 s |
| 2026 174M chunk-32 | **0/76 = 0%** | 0.053 | 1.472 s |
| 2024 offline endpoint candidate | 1/76 = 1.32% | 0.013 | endpoint only |

Chunk-16 won the product tradeoff: it matched chunk-32's local accuracy while
showing text roughly 320 ms sooner. The endpoint candidate was rejected because
its single edit changed text the 174M live recognizer had already gotten right.
The configured full-stack check was:

```bash
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live \
  --sample --lang ko --once --out /tmp/autocwi-ko-acceptance-20260725
```

It resolved the CC BY 4.0 FLEURS fixture `assets/sample-ko.wav` only after the
language was known, loaded `Korean Zipformer 174M · 320ms`, and emitted 14
durable words. The final standard-sample transcript is:

```text
널리 알려진 사파리라는 표현은 특히 사바나의 멋진 아프리카의 야생동물들을 보기 위한 육로 여행을 칭한다
```

A real-time looping `--sample --lang ko` server was opened in desktop Chrome at
1600×1000. The first inspection exposed that repeated same-speaker utterances
were being fused into one enormous paragraph. After the fix, each ASR utterance
was a separate stacked paragraph, its Korean words wrapped to the viewport,
older paragraphs clipped only at the top of the stage,
and the live orb remained inline after the final word. A synthetic 36-word
same-utterance regression proves that genuine long turns are not split at the
legacy eight-word line limit; speaker and utterance changes each have their own
partition tests.

That checkpoint passed 121 Python tests, 33 shared/legacy JavaScript motion tests,
and eight Next.js TypeScript tests; ESLint and the Next production export also
completed successfully.

### Stable stacked-caption acceptance (2026-07-25)

The real product was opened with both standard language-specific sample paths:

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open --port 8801
.venv/bin/python -m autocwi live --sample --lang ko --no-open --port 8802
```

A dedicated visible desktop Chrome window loaded both servers at 1440×900. The
English sample occupied `8 / 5` words and the Korean sample `8 / 6`. Both
English rows measured 55.8047 px high and remained one line. Korean's longer
first block wrapped cleanly to 93.6172 px while its second remained 55.8047 px;
the configured 9 px inter-row gap remained intact and no caption overlapped.
The live voice circle remained absolutely positioned beside the current row
and did not change row geometry. The complete semantic utterances remained
available to Transcript.

The browser selector is pinned by pure tests:

- one 48-word turn advances through six fixed eight-word rows;
- creating the second row leaves the first row's semantic word keys
  unchanged, so old motions cannot replay;
- alternating stable speaker assignments still produce eight-word rows and
  later correction to one speaker preserves every Stage row ID;
- sixteen pending-attribution words carrying sixteen provisional utterance IDs
  still produce `8 / 8` rows, and later stable attribution preserves both row
  IDs and membership;
- recognized provisional words remain visible while the reveal scheduler
  limits concurrent word motion to two;
- selecting the Stage stack does not mutate the full Transcript paragraphs.

The samples were instrumented at `Element.animate`. Creating row two moved the
retained row upward over 540 ms and settled the new row from
`translateY(0.32em)` over 460 ms. Each language produced only that one genuine
row transition for its 13/14 visible words. Pure planner tests confirm unchanged
row ID order—speaker, color, or text revision—returns no stack motion, and the
React path bypasses the animation under reduced motion.

The live Korean SSE trace also separated model behavior from layout behavior.
The recognizer revised only the current word slot—such as
`아` → `아프리카` → `아프리카의`—and occasionally a two-word tentative tail;
committed prefix words did not roll back. The UI keeps that accurate hypothesis
visible and bounds simultaneous reveal motion instead of discarding recognized
words.

The loaded caption used `Noto Sans KR Variable Local`; the separate motion
acceptance still proves an active Hangul word returns to weight 400 and
identity transform after its one-time cue.

All 14 Korean words remained `Attribution pending` and still formed `8 / 6`
rows with stable DOM row IDs. Instrumentation observed exactly one retained-row
shift plus one entry. This confirms pending speaker metadata does not gate row
insertion or the upward stack transition.

The English run is an equally required acceptance path. It exposed that
pre-verification `commit` records were being treated as disposable hypothesis
words: earlier words vanished, row IDs contracted, and the same row could enter
again. Accurate cue/commit/verification events now retain `src: accurate`; the
product reducer preserves provisional commits across later snapshots; and
Stage no longer uses the two-motion concurrency cap as a word-visibility
filter. With the eight-word capacity, the final visible bilingual trace
produced exactly one shift plus one entry in each language. English and Korean
both peaked at two simultaneous word motions. A persistent
seen-row guard suppressed removal/reappearance transitions, so English
verification and Korean pending attribution could update text/labels without
replaying stack motion.

That stack-fix checkpoint passed 121 Python tests, 33 shared/legacy JavaScript
motion tests, 19 Next.js TypeScript reducer/stack tests, ESLint, TypeScript
production compilation, and the Next static export.

## The golden grid

`autocwi/ccprosody.py` re-implements the renderer's own `typeOf()` so the
derivation can **invert** it. Two implementations of one map drift, and drift
is silent here — the spec still validates and the page still renders while
every derived word is wrong.

So the map is pinned to a grid captured from the JavaScript itself. After
touching `mapping`, `expression`, `closed_caption`'s axis keys, or `typeOf`:

```bash
.venv/bin/python scripts/dump_forward_map.py   # needs Chrome; never run by pytest
```

`test_reference.py` asserts Python reproduces every point *and* that the config
stored beside the grid still matches `config.yaml`, so a stale fixture fails
with "re-run dump_forward_map.py" instead of quietly passing. It earned this on
its first run: it caught `restWght` being rounded to a multiple of 4 in the
page but not in Python.

## Conventions

- Assertions carry the *reason* in a comment. Most of this suite exists because
  something specific broke; a bare `assert x == 3` invites the next person to
  update the number instead of the code.
- Pin behaviour, not implementation strings, wherever there is a choice — but
  when the only handle is generated JS, assert the source string and say why.
- Values the design system states are asserted **against the PDF's section
  number** (`sync_pop == 0.15`, 2.2.3), not against whatever the code happens
  to do.
- No mocks or fakes; the boundaries that need crossing are crossed with small
  real inputs (synthetic numpy audio, a three-word spec).

## Benchmarks

Not part of the suite — they load models and take minutes.

```bash
.venv/bin/python scripts/benchmark_streaming.py            # WER + RTF
.venv/bin/python scripts/benchmark_streaming.py --stress   # 4-condition matrix
.venv/bin/python scripts/benchmark_streaming.py --quiet-sweep
```

Current: 0 edits / 77 words clean; 7 edits / 308 words across the stress
matrix (2.27%). Re-run before swapping any checkpoint — the recognizer choice
here is measured, not assumed.

### Streaming diarization acceptance (2026-07-25)

The model-backed acceptance uses the product command, not a synthetic waveform:

```bash
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live \
  --sample --lang en --diarizer sortformer --once \
  --out /tmp/autocwi-sortformer-en
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live \
  --sample --lang ko --diarizer sortformer --once \
  --out /tmp/autocwi-sortformer-ko
```

The native palettized Sortformer processed 34.5 s English in 4.01 s (8.6×
real time) and 13.3 s Korean in 1.50 s (8.9×) on the target Apple Silicon
machine. English endpoint output contained only S1/S2 and retained the expected
alternating dialogue turns; the transient raw third slot on the quiet
“Uh, yeah” was merged back to S1 by endpoint identity. Korean emitted all 14
recognized words live, then re-emitted those same IDs as stable S1 at endpoint.

A standard paced `live --sample --lang en --no-open` run was also opened in
headless Chrome against the real Next.js page. `window.__cwiStudio.report()`
reported 63 visible reducer entries, zero active/pending motions after EOF, and
the Transcript rendered distinct Speaker 01/Speaker 02 paragraphs. The extra
entries are the existing speculative onset/read-ahead records rather than
additional durable words; `live_events.jsonl` contained 59 unique English word
records. This browser check crosses the file source, both model layers, SSE,
revision reducer, and actual product DOM.

The equivalent paced Korean product run reported exactly 14 visible words,
zero active/pending motions after EOF, two stable eight-word/six-word Stage
rows owned by Speaker 01, and one complete stable Speaker 01 paragraph in
Transcript. Thus both language-specific sample paths crossed the real browser;
Korean was not inferred from the English acceptance.

The offline unit suite separately pins:

- activity-weighted selection when a longer but faint overlapping track exists;
- provisional Sortformer assignment followed by endpoint identity correction
  and slot reuse;
- Korean/no-text-verifier endpoints still calling speaker `label_words` and
  revising the same IDs to stable attribution;
- deep language-overlay merging so Korean changes the embedding and thresholds
  without losing shared Sortformer/segmentation settings.

Final repository gates after the delivery upgrade: 127 Python tests, 33
shared/legacy JavaScript motion tests, 19 Next.js TypeScript tests, ESLint,
TypeScript production compilation, the Next static export, and the Swift
release build.

### Expressive delivery acceptance (2026-07-25)

The delivery layer was accepted through the paced product path, with Chrome
attached while each standard sample played:

```bash
.venv/bin/python -m autocwi live \
  --sample --lang en --no-open --port 8811 \
  --out /tmp/autocwi-delivery-en-paced-20260725
.venv/bin/python -m autocwi live \
  --sample --lang ko --no-open --port 8812 \
  --out /tmp/autocwi-delivery-ko-paced-20260725
```

This deliberately omitted `AUTOCWI_FAST`: it exercised real file pacing, live
ASR arrival, SSE, the word queue, CSS motion, and final rest rather than replaying
an already-complete event file.

English wrote 59 unique delivery-bearing word IDs. After the conservative
threshold pass its natural dialogue produced `steady` (46), `gentle` (7),
`falling` (3), and `rising` (3): only 22.0% received an expressive profile,
down from 86.4% under the sparse two-frame contour rule. Korean wrote 14 unique
IDs with `steady` (10), `falling` (3), and `rising` (1): 28.6% expressive,
down from 92.9%. Repeated hypothesis/commit/verification records changed zero
delivery signatures in both event logs.

The durable contour path now uses Praat at 10 ms instead of the immediate
64 ms orb estimator. It requires at least five voiced frames and 30% voiced
coverage, removes values outside 1.6× of the word median, maps seven semitones
to full scale, and requires `abs(contour) >= 0.45`. A quiet source alone cannot
select `gentle`; low force/attack must also carry at least 0.60 texture.

After the queues drained, Chrome reported:

| sample | reducer words | visible | active | pending | residual settled effects |
|---|---:|---:|---:|---:|---:|
| English | 63 | 63 | 0 | 0 | 0 |
| Korean | 14 | 14 | 0 | 0 | 0 |

“Residual” checks every settled `.word-glyph`/`.word-ink` for a non-identity
transform, non-400 weight, or non-100% width. The line orb and Voice Compass
continued to expose the current `delivery_profile` while correctly leaving mono
direction unknown.

The rebuilt frontend's maximum observed word clock was exactly 720 ms in both
samples. Flow can hold more of that window but cannot extend it, so expression
does not reintroduce cumulative caption delay.

A direct real-browser path probe then injected one current word per expressive
family. Computed animation names were separately
`word-delivery-rising`, `word-delivery-falling`,
`word-delivery-sustained`, `word-delivery-forceful`, and
`word-delivery-gentle`; `textured` used the base geometry path with a 0.275
resonance value. This guards the original failure where every label selected the
same physical motion.

The smoothing regression trace sampled all seven families frame by frame in
the real product DOM. Every path now begins near the baseline rather than
teleporting to its crest: worst first-frame translation was 0.441 px, worst
first-frame scale offset 2.5%, and minimum first opacity 0.66. The largest
observed vertical step was 0.256 px/frame and scale step 0.0127/frame. All
seven subsequently reported identity transform, weight 400, width 100%, and
resonance opacity 0. Ordinary `steady` words use only 30% of the expressive
axis excursion.

The targeted automated gates add synthetic rising/falling chirps, rejection of
shallow or under-evidenced contours, JSON-safe continuous delivery events,
first-slot signature freezing across respelling, runtime-config/deadband
plumbing, Next reducer tests, and a production build.

### Reference-scale live-motion correction (2026-07-25)

The earlier smoothing pass accidentally applied the delivery-profile gain to
both intonation and the synchronization lift, leaving correct motions too small
to perceive. The Next renderer now composes two independent layers:

- a constant live CWI cue of at least 10% scale and 0.20 em rise;
- thresholded voice-shaped scale, lift, weight, width, path, and resonance.

The same real paced English and Korean sample commands above were reopened in
the rebuilt Next.js product. At EOF, English reported 63/63 reducer/visible
words and Korean 14/14; both had zero active motions, zero pending reveals, and
zero settled residual transform/weight/width effects. The active style targets
observed in the real sample DOM were:

| sample | active scale range | active lift range | max word clock |
|---|---:|---:|---:|
| English | 1.100–1.257 | 0.201–0.250 em | 720 ms |
| Korean | 1.100–1.163 | 0.200–0.229 em | 720 ms |

A frame-by-frame Chrome probe of a current rising word measured 1.159 peak
scale, 4.712 px vertical travel, and a 0.482 px maximum vertical step. The first
sampled frame remained near the baseline (0.307 px translation), and the
completed word returned to
`transform: none`, weight 400, and width 100%. This restores perceptible
reference-scale motion without restoring the zipper effect or delaying the
caption queue.

### Lossless first-paint motion and family variety (2026-07-25)

The intermittent omission was the explicit overload policy: after 200 ms behind
two occupied slots, a fresh word was painted directly at rest. Both product and
legacy schedulers now retain that word hidden until a slot opens. The original
acoustic deadline and 60 ms catch-up floor remain, so waiting does not restart
a full inter-word delay. A word is never visible before this motion begins and
therefore cannot acquire a late pop.

For an exact first-paint audit, Chrome connected before sample capture and a
mutation probe keyed every node by immutable `data-word-id`. English observed
60 semantic first paints: 60 active, zero initially settled, and zero that
never became active. Korean observed 14/14, while
`window.__cwiStudio.report()` independently returned `motionStarts: 14` and
`freshWordsWithoutMotion: 0`. Korean's busiest sampled frame had exactly two
physically running word animations. Both samples drained to zero pending/active
motions and zero residual transform, weight, or width.

The conservative semantic profile threshold remains unchanged. A separate
presentation-only family selector routes trustworthy continuous acoustic
dimensions into distinct timing without claiming an emotion. The paced English
sample exercised all seven families:

| family | unique first paints |
|---|---:|
| steady | 31 |
| gentle | 7 |
| textured | 6 |
| falling | 6 |
| rising | 5 |
| sustained | 3 |
| forceful | 2 |

Korean exercised steady (6), falling (5), rising (1), gentle (1), and sustained
(1). Each family now owns a distinct glyph animation and a distinct
weight/width intonation animation. A direct Chrome probe measured family peaks
from 1.100 to 1.286 scale, 5.74–6.53 px travel for the ordinary/expressive
paths, and forceful weight up to 680. The repaired quiet/gentle edge case now
reaches the full 1.100 synchronization scale and 5.79 px travel instead of
looking motionless; its upward-only character ribbon travels 2.18 px and then
all channels return to `none` / 400 / 100%.

Final gates for this correction: 127 Python tests, 32 shared/legacy JavaScript
motion tests, 19 Next.js TypeScript tests, ESLint, the production static export,
and the four-mode headless-Chrome legacy render probe.

### No eligible first-paint motion is lost (2026-07-26)

Two paths produced occasional motionless pops. First, animation eligibility
was read again from the latest word record when a hidden queue slot opened; a
reconnect/verification update could therefore turn an unseen live word into
settled replay. Second, immediately settling an active historical correction
could cancel its legitimate first clock before the visible peak.

The queue now stores immutable first-seen intent, while activation stores a
frozen acoustic `MotionSnapshot`; the layout commit records its real
first-paint start time. Revisions use a negative CSS phase delay to continue
that same clock. They cannot change its
family/scale/weight/width/duration and cannot start another clock. Index-stable
character nodes prevent respelling from restarting hand-off; extra characters
on an older corrected word receive no independent animation.

A clean Chrome probe corrected `Hi → Historical` after a newer word arrived
and changed its delivery from forceful to gentle. The word remained active,
advanced from its existing phase, and retained its original 720 ms forceful
envelope and 1.380 scale. Its eight appended historical characters had zero
independent animations. It then completed at normal weight 400 with no running
animation. In a separate overload probe, an unseen third word waited behind
two active slots, received `_replay: true` verification while queued, and still
first-painted active with 19 running descendant animations.

Model loading may also delay the browser bundle until startup events have been
retained. The broadcaster now marks history sent to the first audience
connection as `_first_presentation: true`; only that unseen opening backlog
keeps motion eligibility. A later EventSource reconnect/page refresh receives
ordinary settled replay.

Chrome then audited both bundled commands:

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open --port 8877
.venv/bin/python -m autocwi live --sample --lang ko --no-open --port 8878
```

The English run recorded 60 words, 60 active first paints, 60 physically
animated IDs, zero initially settled words, and
`freshWordsWithoutMotion: 0`. It exercised all seven presentation families.
Korean recorded 14/14 active first paints, 14/14 physically animated IDs, zero
initially settled words, and `freshWordsWithoutMotion: 0`.

Final gates: 128 Python tests, 32 shared/legacy JavaScript tests, 22 Next.js
TypeScript behavior tests, ESLint, TypeScript compilation, the Next.js
production static build, and the four-mode generated-page Chrome probe.

### Paint-anchored motion under fast speech (2026-07-26)

A rapid recognizer burst exposed that the scheduler's `performance.now()` was
not necessarily the word's first visible time. When React was busy, the
negative phase delay correctly preserved absolute time but could make a newly
painted word enter after its attack or peak. The scheduler now reserves a
motion slot with no running expiry; `MotionWord` confirms its layout commit
immediately before paint, which starts both the CSS phase and slot lifetime.
The diagnostic report distinguishes `motionStarts` from
`motionPaintStarts` and reports `motionsWithoutPaint`.

A real Stage probe injected 24 final words in one synchronous batch with
acoustic timestamps only 35 ms apart. Chrome sampled every animation frame:
24/24 first appeared active, 24/24 had physically running descendant
animations, `motionStarts - motionPaintStarts` was zero, the maximum first
phase age was 0.6 ms, and the busiest frame contained exactly two active
words. The queue drained without a timeout or motionless fallback.

The same probe then opened both standard product paths:

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open --port 8891
.venv/bin/python -m autocwi live --sample --lang ko --no-open --port 8892
```

English produced 61/61 active and physically animated first paints, with all
seven motion families, zero `motionsWithoutPaint`, zero
`freshWordsWithoutMotion`, and at most two active words. Korean produced 14/14
with the same zero-loss and two-word-concurrency result. Both real SSE queues
drained to zero. Their maximum first-frame phase ages were 0.1 ms and 0.0 ms,
respectively.

Final gates: 128 Python tests, 32 shared/legacy JavaScript tests, 22 Next.js
TypeScript behavior tests, ESLint, TypeScript compilation, the production
Next.js build, and all four generated-page Chrome render modes.

### No accumulating one-minute presentation buffer (2026-07-26)

The fixed motion duration imposed a throughput ceiling: two 520–720 ms slots
can display at most roughly 2.8–3.8 words/s. Faster speech therefore accumulated
hidden, motion-eligible words even though recognition itself remained current.
The Stage scheduler now derives a sustainable duration from median acoustic
word spacing. It does not react to decoder arrival bursts. Existing acoustic
backlog and pending count add a bounded batch-drain budget, with a 600 ms
target and 320 ms smooth-motion floor. Every selected duration is frozen in
the word's first-paint `MotionSnapshot`. Character-step timing also scales so
the final character begins no later than 42% of the selected clock.

A full real-Chrome Stage run delivered 300 words at five words/s for exactly
60 seconds. Frame sampling observed 300/300 active first paints and 300/300
physical motions, with a maximum of two active words. At the 10, 20, 30, 40,
50, and 60 second checkpoints, both `pendingReveals` and
`presentationBacklogMs` were zero. All 300 scheduled starts were confirmed by
300 browser paints, and the final queue drained to zero.

The latest standard product samples were also opened from their real model and
SSE paths. English produced 63/63 active, physically animated words and Korean
14/14, with zero `motionsWithoutPaint`, zero `freshWordsWithoutMotion`, and no
more than two active words. Korean's sparse 14-word decoder batch previously
used fourteen 720 ms clocks; the batch-debt policy now used 320 ms for eleven,
400 ms for one, and retained 720 ms for the final two after the debt cleared.
Both language queues returned to zero.

Final gates: 128 Python tests, 32 shared/legacy JavaScript tests, 29 Next.js
TypeScript behavior/timing tests, ESLint, TypeScript compilation, the
production Next.js build, and four generated-page Chrome modes with zero
animation restarts or long tasks.

### Stage cannot stall on historical insertion (2026-07-26)

An early-attached English `--sample` run reproduced a complete presentation
stop. At 10 seconds the model had 48 words, but only 43 were visible. By
11 seconds, two later-arriving words with older acoustic timestamps had
reserved both motion slots while falling outside the then-four-row Stage
window. They never mounted, so `motionStarts` stayed at 44,
`motionPaintStarts` at 42, and 19 later words remained pending through the end
of the clip.

The reveal scheduler now maintains a monotonic acoustic discovery frontier.
A newly discovered ID more than 40 ms behind it is verifier/onset backfill and
settles without reserving motion. This implements the existing rule that an
older modification may update text but must not move. Every pre-paint
reservation also has a 250 ms watchdog; a component that still cannot mount is
settled and its slot released. `abortedUnpaintedMotions` makes that emergency
path observable.

The repaired early-attached English sample reached 63/63 visible words, zero
pending and active slots, 52/52 scheduled/painted motions, zero unpainted
motions, and zero watchdog aborts. Eleven historical insertions settled
directly. Korean reached 14/14 visible and 14/14 scheduled/painted, again with
zero pending slots, unpainted motions, or watchdog aborts.

Final gates: 128 Python tests, 32 shared/legacy JavaScript tests, 31 Next.js
TypeScript behavior/timing tests, ESLint, TypeScript compilation, the
production Next.js build, and all four generated-page Chrome modes.

### Speaker-count gate and six-row Stage entry (2026-07-26)

Two independent false-count paths now have regressions. A mock native speaker
slot 4 cannot become visible `S5` before endpoint identity verification. The
embedding fallback may internally retain a candidate S3, but its first clean
endpoint is public `unknown`; a second clean endpoint confirms S3 and queues an
in-place revision for the earlier pending word. S1/S2 remain immediate, and
the configured six-person capacity remains available rather than being
hard-capped to two.

The standard paced English command was opened in the actual Next.js Stage:

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open --port 8912
```

A pre-navigation `Element.animate` trace recorded seven newly created caption
blocks. Every block—including the first—received exactly one 620 ms entry from
opacity 0, `translateY(0.58em)`, and `scale(.985)` to rest. Retained rows used
the separate 540 ms upward FLIP. The Stage stayed capped at six eight-word
rows, ended at 63/63 visible reducer words with no pending/active/unpainted
motion, and its 59 unique durable words contained only S1/S2.

Final gates: 130 Python tests, 32 shared/legacy JavaScript tests, 32 Next.js
TypeScript behavior/timing tests, ESLint, TypeScript compilation, the
production Next.js build, and all four generated-page Chrome modes.
