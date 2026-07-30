# Testing

Last updated: 2026-07-30

The pytest suite is **fully offline by design** — no model loads, no network, no
video decoding. Audio is synthesised with known ground truth, and the reference
recordings are represented by the CaptionSpecs already derived from them. Keep it
that way: a suite that needs 1.9 GB of weights or a 9 MB `.mov` stops being run.

Anything that needs a model, a browser, or the FLEURS set is a **manual check**
below, not a test.

## Running

```bash
python3.11 -m venv .venv                       # one time
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m pytest                     # 151 tests, offline, ~seconds
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

### 3. Is the motion still lossless?

```bash
.venv/bin/python -m autocwi live --sample --lang en --no-open &
.venv/bin/python scripts/studio_probe.py --samples 70
```

Attach **before** the first word arrives. Acceptance is the invariants, not the
exact numbers:

| counter | required |
|---|---|
| `maxActiveMotions` | never above `display.max_simultaneous_reveals` |
| `motionStarts` vs `motionPaintStarts` | equal — every reserved slot painted |
| `motionsWithoutPaint` | 0 |
| `abortedUnpaintedMotions` | 0 — the 250 ms watchdog never fired |
| `freshWordsWithoutMotion` | 0 — no word appeared without its one motion |

**`presentationBacklogMs` must be read as a time series, not as a max.** It is
`newest - current` in acoustic time, so its peak just reports how deep the buffer
was when the browser attached — it read an identical 3211 ms across runs with
different settings, which is the tell. Sample it every ~0.5 s instead: it should
decay to 0 within a few seconds of attaching and then stay there. If it *stays*
high, that is real lag.

`staleSettledWords` counts words that arrived past
`display.word_motion_backlog_ceiling_s` and were revealed as history rather than
animated. Attaching mid-clip should produce a burst of these and then none;
attaching before the first word should produce zero.

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

Current: **12.54% CER** on 8 FLEURS ko_kr clips (44/351 chars). A meaningful
share is number formatting (`2011년` vs `이천십일년`), a convention rather than a
recognition error — normalize before comparing providers.

Superseded 2026-07-30: `benchmark_streaming.py` and `benchmark_asr.py` were
removed. The old "0 edits / 77 words" came from 3 clips of read narration that
ship inside the sherpa model directory — the vendor's own demo audio, which made
any A/B against that model circular. **Never quote that number.** Do not
reintroduce a second benchmark.
