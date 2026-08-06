# Testing

Last updated: 2026-08-04

The pytest suite is **fully offline by design** — no model loads, no network, no
video decoding. Audio is synthesised with known ground truth, and the reference
recordings are represented by the CaptionSpecs already derived from them. Keep it
that way: a suite that needs 1.9 GB of weights or a 9 MB `.mov` stops being run.

Anything that needs a model, a browser, or the FLEURS set is a **manual check**
below, not a test.

## Measuring the motion (manual, needs a browser)

None of this is a pytest test -- each needs a running `autocwi live` and headless
Chrome -- but each one is the ONLY trustworthy answer to its question, and every
one of them exists because an ad-hoc metric gave a confidently wrong answer.

| tool | answers | trap it replaces |
|---|---|---|
| `scripts/word_motion.py --trace rows.json` | one row per word: peak, floor, weight, motion width, lift | `max/min` over a word's samples cannot tell GROWTH from SHRINKAGE; font-size alone misses the 2.2.3 pop, which is a transform |
| `scripts/ink_collision.py` | do adjacent rows' INK touch | line-box arithmetic says rows overlap constantly and is useless; only pixels answer it |
| `scripts/baseline_probe.py` | does a swelling word stay on its line | `.word-ink`'s rect excludes the child transform; `.word-glyph`'s bottom is pinned by `bottom: 0`. Run `--broken` first -- a check never seen to fail is not evidence |
| `scripts/caption_color_probe.py` | does the WHOLE word end up in one colour | `studio_probe.py` reads a word's FIRST character, so a word whose last character never turned scores as fully coloured. That is exactly the defect it missed -- 23 of 137 words half in read-ahead grey. Also `--broken` |

**Screenshot before concluding anything about layout or typography.** Three
numeric probes reported "confounded but probably fine" on a glyph-anchoring
change that a single screenshot showed was catastrophically broken -- words
overlapping and clipped off the stage.

Two more traps, both of which cost a full round each:
* `scrollWidth` on `.caption-words` does NOT measure clipping. `.word-glyph` is
  out of flow, so a swelling word inflates it with no text lost. Compare the
  IN-FLOW sizers against their row instead.
* Keying a word by `(DOM index, text)` conflates repeats -- the stage scrolls,
  so one index holds different words over time, and "is" appears twice in the
  bundled film.

## Running

```bash
python3.11 -m venv .venv                       # one time
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m pytest                     # 161 tests, offline, ~seconds
npm --prefix web install                       # one time
npm --prefix web run check                     # lint + 49 TS tests + static build
```

`pytest` also runs the two Node suites (32 tests) through `test_node_suites.py`,
so the single command covers the shared motion engine and the live render
reducer. Run them directly while iterating:

```bash
node --test tests/cwi_motion_core.test.js tests/live_render_core.test.js
```

## Checking it by hand

The automated gates cannot see the screen. These are the commands to run when
you have changed motion, typography, layout, or the recognizer — each one says
what to look for.

### 1. Does it caption at all?

```bash
.venv/bin/python -m autocwi live --sample            # bundled clip, opens browser
.venv/bin/python -m autocwi live --sample --lang ko  # Korean clip + Korean model
.venv/bin/python -m autocwi live                     # your microphone
```

Expect: the page opens immediately with `boot` status, ~7.6 s of model loading,
then `listening`. Words appear in spoken order, each moving exactly once, and
settle to normal weight. The run ends at `audio source finished` and stops
cleanly. If the port is busy it steps to 7338…7346 — a leftover process is the
usual cause (`pkill -f "autocwi live"`).

### 2. Do the captions look right?

```bash
.venv/bin/python -m autocwi live --sample --no-open &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --window-size=1440,900 --timeout=15000 \
  --screenshot=/tmp/cwi.png http://127.0.0.1:7337/
```

Use `--timeout`, **not** `--virtual-time-budget` — SSE never idles, so the latter
hangs. Note this screenshots at the load event, which on an SSE page is *before
any word exists*; it proves the shell, not the captions. For a settled stack,
drive CDP and wait until `pendingReveals == 0 && activeMotions == 0` first.

Check both 1440×900 and a narrow 390×844: mobile wraps at word boundaries, and
desktop paragraphs must wrap too. `/?demo=1` is a deterministic two-speaker
preview that needs no audio. `/legacy` is the original frame-level renderer.

Two things to look at specifically, because the automated gates cannot:

* **Fill the stage and keep going.** `--sample --loop` is the quick way. Older
  rows must leave off the TOP while the newest stays pinned at the bottom edge.
  If the newest is what disappears, `.caption-feed` has lost one of `top` /
  `max-height` / `justify-content: flex-end`. To force it, set
  `--caption-scale` past the slider's 1.35 from the console.
* **A corrected word must land in place.** Watch a row while endpoint
  verification respells it: the row must not flip between one and two visual
  lines. That flip moves every row below it, and it is why words-per-row and
  caption type size have to be chosen together.
* **The light stage has no captions box.** Type sits directly on `--stage-bg`,
  and speaker identity is carried by colour alone. Toggling `Light stage` off
  must bring back the CWI 2.4.1 black box *and* the exact CI palette — if the
  colours stay muted, the toggle changed the CSS but not the React state.

### 3. Is the read-ahead real, and is the motion lossless?

```bash
.venv/bin/python -m autocwi live --sample --lang en --loop --no-open &
.venv/bin/python scripts/studio_probe.py --samples 40
```

The studio presents captions from a playhead running
`display.read_ahead_delay_s` behind the acoustic clock, which is what puts
recognized-but-uncoloured text on screen (CWI 2.2.1). Acceptance is the
invariants, not the exact numbers:

| counter | required |
|---|---|
| `readAheadMs` | well above 0 — at 0 the page is colouring text the instant it arrives, so 2.2.1 is not being delivered at all |
| `words` vs `visible` | equal — read-ahead words are the white ones; nothing is withheld |
| `domUnarmed` | 0 — an unscheduled word would stay read-ahead forever |
| DOM white words vs `aheadWords` | agree within ~2; a gap means the page is not showing what the schedule believes |
| `lateWords` | a burst on attach, then flat. Steadily climbing means the delay is shorter than the recognizer's delivery latency |

### Does every character of a word wear the speaker's colour?

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open &
.venv/bin/python scripts/caption_color_probe.py            # must PASS
.venv/bin/python scripts/caption_color_probe.py --broken   # must FAIL
```

CWI 2.1 makes colour THE speaker signal, so a word drawn in two colours makes
two claims about who spoke it. The turn is a WIPE, so mid-word boundaries are
correct *while the boundary is crossing* — the verdict is the LAST sample, when
nothing can still be moving, plus how many consecutive samples any one word
stayed mixed (1 is a wipe; more is a word that stopped mid-turn).

It caught a word growing after it was armed: `--char-turn-delay` is written per
character, and characters appended by the endpoint verifier
(`animation` → `animation,`) never got one, so they held the stylesheet's
600000ms default and stayed in read-ahead ink. **23 of 137 settled words**, each
for the remaining 28–63 s of the capture. `--broken` strips each word's last
delay to reproduce it.

### Does a swelling word stay on its baseline?

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open &
.venv/bin/python scripts/baseline_probe.py            # must PASS
.venv/bin/python scripts/baseline_probe.py --broken   # must FAIL
```

CWI grows a word FROM its baseline and never moves it, and the design system's
own measurements are per word: across the 48 words with baked curves in
`assets/reference_specs/*.json`, peak lift regressed on peak size has a slope of
**+0.043**, and its single biggest word — "louder" at 2.21x — has a lift of
**exactly 0.000**. A held word at 1.32x has the largest lift in the whole
reference. Size does not raise a word; waiting does.

| metric | required |
|---|---|
| worst median \|rise\| over the pinned crests | ≤ 0.06em. The old anchoring gives **0.196em** on English, 0.093em on Korean |
| `--broken` | must FAIL. A check never seen to go red is not evidence |
| `--glyph-baseline-em` | 0.3617em English, **0.2598em** Korean. If the two faces report the SAME number the probe is measuring the wrong element — that has happened twice |
| max \|rise\| | diagnostic only. At a 1.62x crest adjacent rows overlap vertically and a minority of crops catch the row below, in the fixed build and the broken one alike |

**This is a separate probe because `studio_probe.py` cannot see it.** That one
decides a word is moving from `|matrix.f| > 0.5` on `.word-glyph`, and this lift
is LAYOUT — `matrix.f` stays 0 the whole time, so a real 0.24em lift shipped
undetected. Korean is under-powered here (n=5); for a robust Korean answer take
the DOM route instead, over a `--loop` capture: crest-vs-rise correlation must
sit near 0 (measured **+0.002**, slope **+0.02 px per 1.0x**).

**Measured 2026-08-01** on the bundled clip: read-ahead 2.43 s median against a
2.5 s delay (English) and 1.47 s (Korean); 0 invisible words; 0 unarmed; peak
simultaneous motions 4–6.

**The time window is not the word count.** `readAheadMs` measures the far edge
of the window, and `fast` mode holds a word back until the following one is
stable, so the last part of that window is often one lone hypothesis word.
Words actually past the playhead, measured across delays: 1 median / 6 max at
2.5 s, 2/8 at 4.0 s, 6/16 at 5.5 s. Raise `read_ahead_delay_s` for a fuller
white line where lag is cheap.

There is no concurrency cap and no presentation backlog any more. Both belonged
to the playhead schedule, which the playhead replaced — a word animates at its
recorded onset or, if it arrived after that moment, not at all.

The legacy renderer has its own probe:

```bash
.venv/bin/python scripts/live_render_probe.py   # headless Chrome, no models
```

It injects one burst across all four display modes and reports node
creation/replacement, queue depth, stale rejection, motion starts/restarts, and
each word's scheduled/actual/completed trace. The production path must report
`characterEntryStarts: 0`; a text revision, cue/commit, verification, or speaker
correction must leave the motion-start counter unchanged.

### 4. Tuning the feel

```bash
.venv/bin/python -m autocwi tune                # built-in line, every knob a slider
.venv/bin/python -m autocwi tune out/spec.json  # ...against a real spec
```

Tune here rather than round-tripping screenshots. The built-in line has a long
word for the character sweep, two-letter words to check the ripple rate, and one
loud plus one quiet word to bracket the envelope. "Show config.yaml" prints the
values to keep. Writes `out/tuner.html`, never `captions.html`.

### 5. Recognizer quality

```bash
.venv/bin/python scripts/fetch_fleurs.py --lang ko --count 300  # one time
.venv/bin/python scripts/benchmark.py --lang ko                 # text + timing
.venv/bin/python scripts/benchmark.py --lang ko --stress        # + noise/reverb
.venv/bin/python scripts/benchmark.py --lang en --quiet-sweep   # InputGain guard
```

## Layout

```
tests/
├── fixtures/forward_map_golden.json  441-point grid captured FROM the page's JS
├── test_live.py              (67) live engine, both renderers, derived specs
├── test_speaker_attribution.py (20) confidence lifecycle, revisions, SSE, haptics
├── test_asr_backends.py      (14) backend adapters, revision collapsing
├── test_soundevents.py       (14) local non-speech event state machine
├── test_schema.py             (8) CaptionSpec validation, speaker fields
├── test_cloud_verifier.py     (7) opt-in cloud lane and its local fallback
├── test_overlap.py            (5) word -> speaker by max span overlap
├── test_fuse.py               (5) per-speaker normalization, palette assignment
├── test_prosody.py            (3) dB/F0 on synthetic tones with known answers
├── test_reference.py          (3) the Python prosody mirror vs the golden grid
├── test_live_motion.py        (3) live CWI transforms + first-display activation
├── test_node_suites.py        (2) runs both Node suites from pytest
├── cwi_motion_core.test.js    (6) shared CWI envelope/rest invariants
└── live_render_core.test.js  (26) revision/coalescing/mode/clock/motion reducer

web/src/lib/*.test.ts         (49) caption store, paragraphs/stack selector,
                                   motion timing, voice sensitivity
```

`test_live.py` is most of the suite: the streaming engine (batching, gain,
endpoint verification, SSE replay), speaker tracking, both renderers, and the
derived reference specs.

`test_speaker_attribution.py` uses fixed synthetic unit embeddings and mock
timestamps only — repeated enrollment, two separated voices, weak short-turn
continuity, ambiguous observations, switch hysteresis, centroid update guards,
provisional→stable→corrected revision, same-`word_id` SSE reconstruction,
provisional haptic suppression, and repeated-run determinism.

## The golden grid

`autocwi/ccprosody.py` re-implements the renderer's own `typeOf()` so the
derivation can **invert** it. Two implementations of one map drift, and drift is
silent here — the spec still validates and the page still renders while every
derived word is wrong.

So the map is pinned to a grid captured from the JavaScript itself. After
touching `mapping`, `expression`, `closed_caption`'s axis keys, or `typeOf`:

```bash
.venv/bin/python scripts/dump_forward_map.py   # needs Chrome; never run by pytest
```

`test_reference.py` asserts Python reproduces every point *and* that the config
stored beside the grid still matches `config.yaml`, so a stale fixture fails with
"re-run dump_forward_map.py" instead of quietly passing. It earned this on its
first run: it caught `restWght` being rounded to a multiple of 4 in the page but
not in Python.

## Observed ranges

Measured on the bundled samples with a real browser attached. These are what
"normal" looks like — a change that moves them by a lot needs an explanation, but
they are timing-sensitive observations, not assertions.

**These figures measured the LEGACY renderer and are kept only as its record.**
The product studio's are below, from `scripts/word_motion.py` on the bundled
film (which is the PR film, not the old booth clip):

| channel | studio, English `sample.mp4` |
|---|---|
| motion window | 520–1050 ms (crest), speech-rate for pop and wave |
| peak size, ordinary word | **1.15** — the 2.2.3 pop and nothing else |
| peak size, `"louder"` | **1.83** |
| floor, `"softer"` | **0.82** |
| weight | 400 resting, **~890** on the film's emphatic words, none below 400 |
| lift | 0 for ordinary speech; **0.525 em** on a held word, which shows no crest and no weight |
| adjacent-row ink gap | 9 px at rest, **1.0 px under motion** — no headroom left |

Legacy renderer, for reference only:

| channel | English `sample.mp4` | Korean `sample-ko.wav` |
|---|---|---|
| word motion clock | 320–720 ms | 320–720 ms |
| active scale | 1.100–1.257 | 1.100–1.163 |
| active lift | 0.201–0.250 em | 0.200–0.229 em |
| active weight | 288–496 (forceful to 680) | returns to 400 |
| active width | 87–114 | 100 at rest |
| durable words | 59 unique (63 reducer entries) | 14 |
| speakers | S1/S2 | S1 only |

Delivery families on English: steady 31, gentle 7, textured 6, falling 6,
rising 5, sustained 3, forceful 2 — about 22% expressive. Korean: steady 6,
falling 5, rising 1, gentle 1, sustained 1.

The variable-font clocks are deliberately **not** phase-locked. On one sampled
word, weight was at 0.686 of its excursion while size was at 0.414 and width at
0.331. Fast words attack weight/size/width at about 156/218/260 ms; drawn words
at about 244/346/397 ms. Character turns stay roughly 53–110 ms apart.

Whatever the values, after the queue drains every settled `.word-glyph` /
`.word-ink` must be at identity transform, weight 400, width 100%.

## Conventions

- Assertions carry the *reason* in a comment. Most of this suite exists because
  something specific broke; a bare `assert x == 3` invites the next person to
  update the number instead of the code.
- Pin behaviour, not implementation strings. `assert "someFunction(" in page`
  passes when the behaviour breaks and breaks on a harmless rename — it guards a
  string, not a contract. Roughly 60 of these were removed on 2026-07-30; what
  they nominally covered lives in the Node suites and the Chrome probes, which
  build state, dispatch events, and assert computed output.
- Values the design system states are asserted **against the PDF's section
  number** (`sync_pop == 0.15`, 2.2.3), not against whatever the code happens to
  do. This is the one place a literal constant belongs in a test.
- No mocks or fakes; boundaries are crossed with small real inputs (synthetic
  numpy audio, a three-word spec).

## Benchmark

**One benchmark, one standard set.** Not part of the suite — it loads models and
takes minutes. Commands are in "Recognizer quality" above.

FLEURS (Conneau et al., CC BY 4.0) is the academic standard for multilingual ASR,
so scores are comparable to published numbers. `--stress` and `--quiet-sweep` are
conditions applied to that set, not separate benchmarks.

Current Korean: **10.54% CER normalized / 13.23% raw** on 120 FLEURS ko_kr clips
(575/5453 chars), chunk-32 greedy.

The benchmark prints both columns. The headline is normalized: digits are read
out (`2011년` → `이천십일년`) and unspoken punctuation dropped, on reference and
hypothesis alike, so a writing convention cannot decide a backend A/B. `raw` is
the pre-2026-08-05 scoring, kept so older records stay comparable.

Two superseded numbers, both from an 8-clip slice that was too small to trust —
at 351 units one edit moved the rate 0.28 points:

- "12.54% CER, 44/351" was the raw score on those 8 clips. On 120 clips the raw
  score is 13.23%.
- Normalizing those same 8 clips gives **5.19%**, which looks like a huge win and
  is an artefact: that slice was unusually number-heavy. Do not quote it.

`scripts/korean_sweep.py` is the export/decoding A/B behind the shipped chunk-32
config; it scores read-ahead alongside CER, because an export that recognizes
better but paints later can still break CWI 2.2.1.

**`assets/sample-ko.wav` is `0016.wav` of this eval set** (verified by hash) —
the bundled Korean demo clip is FLEURS ko_kr row 16 and is *not* held out. A
good result on the demo clip is therefore not independent evidence about the
recognizer, and anything tuned against this set is circular with respect to the
demo. Record separate booth audio and pass it with `--refs` before treating a
demo run as validation.

### Korean stress matrix (first run, 2026-08-05)

| condition | CER | note |
|---|---|---|
| clean | 10.54% | |
| room-noise-14db | 15.94% | 14 dB SNR plus small-room echoes |
| quiet-device | 52.08% | 14.8 dB SNR but 22 dB down; was 73.65% pre-fix |
| fast-1.15x | 50.06% | see caveat below |

`quiet-device`'s floor was **−52 dBFS until 2026-08-05**, which put attenuated
speech at or below the noise (effective SNR **−1.4 to +1.8 dB**) and made the
condition impossible rather than quiet. `InputGain` was verified working
throughout — it reached 25.8 dB — and could not help, because gain lifts noise
equally. The floor is **−68 dBFS** now (14.8 dB SNR) and the score moved
73.65% → **52.08%**.

**What is left is a real level problem, and the comparison that shows it is
`room-noise` vs `quiet-device` at matched SNR.** Both now sit at ~14–15 dB SNR;
room-noise scores 15.94% and quiet-device 52.08% — **3.3× worse from absolute
level alone**, since quiet-device speech sits at −50..−53 dBFS. Gain reaches
the recognizer but does not restore accuracy, so a quiet Korean talker is a
genuine risk at the booth. This is the strongest argument for checking
`InputGain`'s target/headroom against the Korean model specifically.

`fast-1.15x` is a genuine collapse, not a scoring artifact — output drops from
39 characters to 18 on one clip and returns unrelated words on another — but
`librosa.effects.time_stretch` is a phase vocoder, so the condition mixes tempo
with phase smearing that real fast speech does not have. Re-test with real
fast recordings before quoting it as a fast-talker figure.

Superseded 2026-07-30: `benchmark_streaming.py` and `benchmark_asr.py` were
removed. The old "0 edits / 77 words" came from 3 clips of read narration that
ship inside the sherpa model directory — the vendor's own demo audio, which made
any A/B against that model circular. **Never quote that number.** Do not
reintroduce a second benchmark.
