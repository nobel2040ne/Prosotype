# CLAUDE.md — working notes for Claude Code sessions

auto-CWI ("Prosotype"): a local, offline pipeline that automates the
**Caption with Intention** (CWI) design system for Deaf/HoH viewers.
**Primary mode = live captions** (mic → CWI-styled captions in the browser,
English). The offline video pipeline is kept as the source of the
**CaptionSpec contract** that a future haptic device module will consume. See
`ARCHITECTURE.md` and `docs/cwi-design-system-notes.md`.

## Commands

```bash
.venv/bin/python -m pytest                       # 56 offline tests, no downloads
.venv/bin/python -m autocwi live                 # live captions from mic (opens browser)
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --loop # repeat the clip continuously
.venv/bin/python -m autocwi live --file x.wav    # stream a file as if live
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live --file x.wav --once  # headless test
.venv/bin/python -m autocwi run clip.mp4 --out out/ --stub   # offline pipeline, no models
.venv/bin/python -m autocwi run clip.mp4 --out out/ --speakers 2  # real (spec.json)
.venv/bin/python -m autocwi cc out/spec.json --media clip.mp4  # CWI closed captions
.venv/bin/python -m autocwi tune                 # live motion tuner, built-in line
.venv/bin/python -m autocwi tune out/spec.json   # ...against a real spec
.venv/bin/python -m autocwi cc out/spec.json --tune   # same, from the cc command
.venv/bin/python scripts/fetch_font.py           # one-time Roboto Flex download
.venv/bin/python scripts/fetch_streaming_model.py # one-time 3-stage live ASR download
.venv/bin/python scripts/benchmark_streaming.py --stress # WER + full-stack RTF matrix
.venv/bin/python scripts/benchmark_streaming.py --quiet-sweep  # recall vs input level
.venv/bin/python -m autocwi live --list-devices   # pick a mic if the default is wrong
```

The venv is `.venv/` (Python 3.11). Always use `.venv/bin/python`, not system python.

## Hard rules

- **Everything local and offline.** No cloud inference, no telemetry. Only
  permitted network: one-time model-weight/font downloads.
- **Pinned versions** in `requirements.txt`. Seed anything stochastic.
- **The CaptionSpec (`autocwi/schema.py`) is a versioned contract.** Renderers
  and the future haptic module consume ONLY `spec.json` / the SSE word events
  — never model objects. Extend the schema with optional fields; breaking
  changes require a version bump.
- **All mapping values live in `config.yaml`**, never hardcoded. They follow
  the official CWI Design System V1.0 — cite section numbers in comments
  (see `docs/cwi-design-system-notes.md` for the extracted values;
  `docs/research-notes.md` maps prior DHH-captioning research onto design
  decisions here).
- **In LIVE mode, size may be animated ONLY as a TRANSFORM on the active-word
  window, never as `font-size`, and it must return to rest.** (Updated
  2026-07-23: live now runs the full CWI 2.2.3 motion, ported from `cc` — the
  +15% pop, 25% elevation, an intonation swell scaled by loudness, and the
  analytic neighbour-push. See `motion.live_sync` in config.yaml and the motion
  loop in `livepage.py` — `registerMotion`/`resolveLine`/`motionTick`.) The old
  rule ("position + colour only, never size") is superseded, but its REASON is
  preserved by HOW the port is done, and that constraint still binds:
  * **Transform only.** The loop writes `transform` (scale = pop, translateY =
    elevation, translateX = neighbour shift) — never `font-size`. So `font-size`
    stays the frozen LOUDNESS channel (a shouted word stays large for life), the
    pop is a transient that returns to the word's frozen resting typography, and
    nothing touches the layout path (no reflow, no frozen-width dance cc needs
    because cc animates `font-variation-settings`; live does NOT animate weight).
  * **Active window only.** A per-frame `rAF` loop touches ONLY words within
    their ~0.3 s motion window (`dataset.moving="true"`), and writes each word to
    its resting transform exactly ONCE when the window passes — a settled word
    is never restyled (THE CAPTION INVARIANT holds; the churn instrument's
    "settled" now means turned AND `moving!=="true"`).
  * **Neighbours move in POSITION only, transiently.** The swelling word pushes
    row-mates aside via `transform` translate and they return; their size,
    weight, colour are never touched. This is the one relaxation the design
    asked for (`AskUserQuestion`, 2026-07-23: "full port + neighbour push").
  * Set `motion.live_sync.enabled: false` to fall back to the old calm lift.
  The AE template (`Academy_CI_Template.aep`) has zero scale animators — the
  stricter reading — but the WEBSITE reference animates the active word's size,
  and live now matches that within the transform-only/return-to-rest envelope.
  Because the whole `.cwi-line` is treated as ONE push row (live moves an
  overflowing word to a new line rather than wrapping), do not key live's push
  on `offsetTop` the way cc does: cc words all rest at the common baseline size
  so they share a top; live bakes loudness into resting SIZE, so they do not.
- **Input gain applies only to the recognizer's copy of the audio.**
  `AudioChunk.samples` must stay at the true captured level because prosody
  measures `loudness_db` from it; the gained copy is `asr_samples`. Gaining
  before that measurement would flatten whisper and shout to one size.
- Offline stages must stay independently runnable via their subcommands,
  reading/writing JSON intermediates in `--out`.

## Seeing the page (do this before judging visuals)

Headless Chrome can screenshot the live stage — never tune motion/typography
blind again:

```bash
.venv/bin/python -m autocwi live --sample --no-open &   # wait ~45s for replay
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --window-size=1440,900 --timeout=15000 \
  --screenshot=/tmp/cwi.png http://127.0.0.1:7337/
```

Use `--timeout`, NOT `--virtual-time-budget` (SSE never idles — it hangs).
`--dump-dom` exposes per-word classes/inline styles for debugging. Note rAF
does not run reliably in headless: time-based animations may appear frozen
mid-flight in screenshots (the 1.5 s self-heal sweep exists because a stalled
rAF chain froze syllable fills at --fill 0% = solid white words).

## Gotchas

- `HF_TOKEN` env var required for real diarization (pyannote weights are
  gated; user must also accept terms on `pyannote/speaker-diarization-3.1`
  and `pyannote/segmentation-3.0`). Without it, use `--stub`.
- Whisper models auto-download on first use (`small` ~460 MB, `base.en`
  ~145 MB). CTranslate2/faster-whisper runs CPU-only on Apple Silicon
  (int8); MPS is used by pyannote/torch only.
- Live mode uses two local English Nemotron 0.6B profiles: 160 ms under
  `assets/streaming-nemotron-en-160ms/` for tentative drafts and 1120 ms under
  `assets/streaming-nemotron-en-1120ms/` for cues/commits, plus Parakeet Unified
  under `assets/parakeet-unified-en-offline/` for durable endpoint text. Use
  `--whisper MODEL` only for the legacy pause-segmented comparison path.
- Live server binds 127.0.0.1:7337 and falls back to :7338…:7346 if busy.
  A leftover `autocwi live` process is the usual cause — `pkill -f "autocwi live"`.
- macOS mic permission is granted per terminal app on first live run.
- When running the CLI in background with redirected output, set
  `PYTHONUNBUFFERED=1` or output is lost on kill.
- Tests are fully offline by design — keep them that way (synthetic audio,
  no model loads).

## State / open threads (2026-07)

- **THE DESIGN SYSTEM PDF IS IN THE REPO AND IT OUTRANKS EVERYTHING ELSE.**
  `docs/cwi-design-system-v1.0.pdf` (54 pp.). Read it with
  the Read tool's `pages` argument. Two rounds of work were spent inferring
  motion from the AE template and three screen recordings when the document
  states it outright. **Section 2.2.3, verbatim:**

  > Caption with Intention adds a motion element to **each word as it changes
  > color**. Each word should undergo a **15% increase in type size before
  > returning to its original size**, creating a "pop" motion effect.

  ...and its diagram labels the rise **25% elevation**. So:
  * The sync cue is **per WORD**, never per character. 2.2.4 is explicit:
    "In most cases, words will be spoken and animated **fully, one by one**" —
    syllable-at-a-time is the documented exception (`motion.syllable_fill`).
  * Its amplitude is a **CONSTANT**, identical for a shout and a whisper. Its
    job is to point the eye at the word being spoken. Per-word amplitude is
    INTONATION (2.3.3-2.3.6), a different scope. **Every wrong model shipped
    here came from collapsing those two** — the result is motion that is large
    on words the reference leaves still and absent on words it moves.
  * **Size IS animated.** The AE template has no scale animator and this
    project followed the template for several rounds; the written system wins.
  Implemented as `closed_caption.sync_pop: 0.15` / `sync_elevation_em: 0.25`
  in `syncAt()`, anchored on `w.start` (2.2.2: the word turns "as soon as the
  sound of the word begins to be pronounced, not after"). The recordings now
  supply only the cue's TIMING (rise 70-100 ms, peak +70-100 ms past the turn,
  fall 160-190 ms) and the per-word prosody.
- **Other numbers the PDF states outright**, all now in `config.yaml` with
  section numbers: baseline type size **5%** of screen height (2.3.5); range
  **3% whisper .. 12% shout** (2.3.6), so the reachable envelope is exactly
  0.6x..2.4x; **Regular 400 at 160-200 Hz** (2.3.8) over a **100..1000** axis
  spanning 80..250 Hz inverted (2.3.9); width 150..25 on harmonics; captions
  box 90% black (2.4.1); at most **two** lines per frame (2.4.2); work area =
  lower **20%** of the frame with 7.5% bottom margin (2.4.3).
- **`Word.motion` bakes each word's MEASURED curves into the spec**
  (`lift` in glyph heights, `scale`, `dwght`; uniform `t0`+`dt` grid so the
  sampler is an index plus one lerp). `closed_caption.motion_source: measured`
  replays them verbatim; **`spec` is the default and is what ships.** The
  curves exist to check the derivation against the recording, not to drive the
  render — the design system does that.
- **Flicker had six causes, all confirmed, none of them the motion model.**
  The two that dominated: (1) `speaking` required `t` to be INSIDE a word, so
  during every inter-word gap it went empty and `visible` fell back to
  `holding` in DOCUMENT order — the PREVIOUS line popped back on, 12 spurious
  flips in 30 s. A line is now "speaking" across its whole `[start, end]` and
  both fallback pools rank by recency. (2) `font-variation-settings` is
  animated per frame and is **on the layout path**: every weight step reflowed
  the flex row while `layout()` was separately pushing neighbours from resting
  widths — two competing horizontal displacements of the same word, every
  frame. `sizeAll()` now freezes each word's box at its measured resting width
  (`getBoundingClientRect().width`, fractional — `offsetWidth` rounds down and
  wrapped the last letter of every word) with `text-align:center` and
  `white-space:nowrap`. Also: `settle()` and `frame()` must emit BYTE-IDENTICAL
  rest strings (one `wordTransform`/`varSettings` helper, `restWght` rounded
  onto the same /4 grid) or the `setStyle` cache misses in both directions;
  no `"none"`-vs-transform branch (layer promotion thrash); `will-change` on
  `.cc-word`, never gated on `.on`. **Measure it, do not eyeball it:**
  `?churn=1` -> `window.__ccChurn.report()`. Target is flips == line count.
- **Deriving a spec: four bugs, all in glyph->word assignment.** (a) `align()`
  fed the DP observations in TIME order while the DP assumes reading order —
  several glyphs of a word turn on the same frame and their order is then
  arbitrary, which ran x backwards and handed "word" two of "is"'s characters,
  stretching it across a 1.4 s pause. Sort by x, map back. (b) Expected
  character x now comes from real ADVANCE widths (PIL + the bundled Roboto
  Flex), not from character index. (c) `word_boxes()` reads each word's x
  extent straight off the pixels — merge glyph runs at a space-sized gap, keep
  only frames that yield exactly as many runs as words — and the DP forbids
  any pairing outside them. Threshold and window must come from the RESTING
  boxes: derived from the frame's own median glyph height, a word swollen past
  2x raises the threshold and merges with its neighbour. (d) A word can never
  have MORE ink runs than characters (runs merge, never split), so a frame that
  gives it more has leaked a neighbour in — that alone is what stopped "louder"
  handing "or" a 1.85x envelope on a word that never moves.
- **Normalise each glyph by its OWN rest, then median — not the reverse.**
  Letters have different intrinsic ink heights and only some have descenders,
  so as glyphs enter and leave the co-present set the median steps to a
  different letter and the curve jumps: that artefact alone produced a 0.35x
  "size" excursion on `Caption` and +-0.16 of phantom lift on still words.
- **Two independent measurements, and each fails where the other works.**
  Per-glyph TRACKING is clean but breaks on a word that swells past 3x (its
  glyphs merge and grow, violating the association gates) or is short enough
  to segment as one run. Per-frame, spatially attributed measurement survives
  both but smears at word boundaries. Take the tracked curve by default, the
  framed one where tracking produced nothing or under-read by >15%.

- Live mode: triple-stage English ASR + speaker attribution. The
  160 ms white draft is merged under the 1120 ms accurate stream; accurate
  partials provide provisional motion cues/commits, while modified-beam
  Parakeet endpoint verification alone owns durable/haptic SSE words. The
  deterministic benchmark is 0/77 clean and 7/308 across the stress matrix.
- Offline renderer and burn-in were **removed** (live page is the renderer);
  offline pipeline ends at `spec.json`.
- Offline pyannote diarization never yet run (needs HF_TOKEN); live
  attribution uses the local titanet tracker instead.
- Syllable variation (CWI 2.2.4) is live: a colour wipe over already-visible
  text, gated by `motion.syllable_fill` to drawn-out words (~7% of words).
  Never make it a typewriter reveal — progressive appearance destroys the
  read-ahead in 2.2.1.
- Recognizer choice is measured, not assumed: the 2026-06-11 Nemotron 3.5 was
  A/B'd and scored 3.25% vs 2.27% matrix WER on English (worse), so English
  live stays on the 2026-04-25 English model. A/B with
  `benchmark_streaming.py --streaming-model` before swapping any checkpoint.
- **`autocwi cc` is the motion REFERENCE, live mode is the compromise.** With
  the text known in advance the full CWI system is exact: real read-ahead (a
  line legible in white before its first word), the colour turn sweeping
  through a word's letters over its spoken span, the `Antecipate` lead, and the
  travelling-wave neighbour bleed (safe here because a caption plays through
  instead of accumulating — which is why it stays off live). Playback is a pure
  function of `t`, so scrubbing back reproduces a frame exactly.
- **The unit of animation is the CHARACTER, not the word** (proven by the
  reference captures in `docs/`): the colour boundary lands mid-word
  ("Roya|le"), and a travelling wave lifts/scales individual letters
  ("a-ni-mati-o" at different heights). `cc` renders one span per character.
  Films use the calm version (one baseline, colour sweep only) — set
  `closed_caption.wave_reach: 0` for that.
- **A line being spoken outranks a line that has not started.** In `cc`,
  ranking visible lines by recency (`slice(-max_lines)`) let the NEXT line's
  read-ahead window — which opens `read_ahead_s` early — evict the caption
  mid-sentence. Priority is now: words on screen right now > lingering >
  read-ahead, with read-ahead only filling a free box.
- **Never gate the onset colour turn on speaker identity.** A `speaker_known`
  guard once blocked 48/48 cues and 39/46 commits, so words only coloured at
  the endpoint — seconds late, and it read as broken sync. Colour turns on
  time with the best-known speaker; `dataset.turned` then prevents any re-hue,
  which is what actually stops the flip.
- **Bound the RENDERED type axes** (`expression.wght_range`/`wdth_range`), not
  just the anchor: the response curve leaves values at the pitch-domain edge
  uncompressed, so a very high voice rendered hairline (wght 100) beside
  ordinary text. Resting size/weight follow the film stills (4.2% of frame
  height, normal weight), not the 5% cinematic baseline.
- **SUPERSEDED for amplitudes — see "THE DESIGN SYSTEM PDF" above.** The .aep
  remains the best source for the SHAPE of the motion and for what the calm
  film-still variant looks like, but 2.2.3 states the amplitudes outright and
  the template disagrees with it (the template has no scale animator at all).
  Where they conflict, the written design system wins.
  **READ THE .aep. It is the original source; the recordings are not.**
  `AE PROJECT/AE PROJECT/Academy_CI_Template.aep` is RIFX — walk it with a
  20-line chunk parser (`LIST`/`RIFX` are containers; `tdmn` = property match
  name, `tdsn` = stream name, `cdat` = static value, `Utf8` = expression) and
  the whole motion system falls out in plain text. Two rounds of tuning were
  spent inferring curves from `docs/*.mov` — a screen capture of the website,
  which is a *different implementation* — and both got it wrong. The template
  holds exactly four text animators:

  | animator | motion |
  |---|---|
  | `Words` | `fill = yellow` (the settled state) |
  | `Up` | `y = -5` |
  | `Yellow` | `y = -amp`, `fill = COLOR_01` |
  | `Antecipate` | `y = +2`, one frame earlier |

  Selector for all of them: Index units, **Based On = Words**, exactly one word
  wide (`Index End = start + 1`), **Ease High 50 / Ease Low 50**, swept by
  `ease(time, inTime, outTime, 0, textLenWords)` between the layer's
  `[START]`/`[END]` markers.
- **The template is position + colour only — but the WEBSITE is not, and the
  website is what is being matched.** `grep` the .aep: `ADBE Text Scale`,
  `Tracking`, `Size`, `Rotation`, `Skew`, `Opacity` all occur **zero** times;
  the four animators touch only `ADBE Text Position 3D` and
  `ADBE Text Fill Color`, and their expressions return `[x,y]`, so no Z either.
  That is the stricter, calmer reading of the system and is what
  `wave_reach: 0` gives. The recordings in `docs/` are the website — a
  different implementation — and it animates the active word's size and weight
  (see the bullet above). `cc` follows the recordings because they are the
  reference being matched; do not "fix" it back to the template without asking.
- **The lift is IN PHASE with the colour turn.** `Yellow` drives the `-amp`
  position AND the fill from ONE range selector, so a letter is at the top of
  its lift at the instant it turns and comes back down behind the boundary.
  **That is the bounce.** Making the lift merely LEAD the colour — landing at
  rest as the colour arrives — is smooth but dead, and that is exactly what got
  flagged as too slow. `Antecipate` (`y = +2`, i.e. DOWNWARD, one frame ahead)
  is a small dip before the rise, not a lead on the lift itself.
- **`anticipation_ms` is 33, not 110.** The template states it exactly:
  `antecipation = framesToTime(1)` — ONE frame at 30 fps. The old 110 ms came
  from the vaguer note "1..4 frames".
- **Do not measure motion by tracking a fixed screen COLUMN.** The line reflows
  horizontally as words differ in size, so a column does not follow one letter;
  and a column's top edge conflates lift with size, because a bigger letter
  also has a higher top edge. That is how a static loudness size-difference got
  misread as a transient "swell after the turn". Zoomed native-rate frame
  strips, then the .aep, settled it.
- **The selector pass is held in SECONDS (`wave_window_s`), not as a fraction
  of the word.** As a fraction it lasted `0.5 x span`, so the wave sped up and
  slowed down with every word — a two-letter word rippled in 70 ms and a
  nine-letter one in 290 ms.
- **The colour turn is a crossfade over `motion.color_turn_ms`.** The config
  always said "color eases with the lift, never a hard cut", but the renderer
  compared `sweep >= at` and flipped each letter to full colour in one frame.
  Blend white -> speaker colour instead (quantized to 32 steps so the written
  string is stable across frames).
- **Every envelope must leave and return to rest with zero slope.** `sin(pi x)`
  has a non-zero derivative at its ends, so motion started and stopped with a
  visible kick; `sin^2` and smoothstep (`ease()`) do not.
- **`frame(t)` animates only the VISIBLE lines**, and `setStyle` skips writing
  an unchanged value (font-variation-settings recalcs force the whole line to
  re-lay-out). It used to restyle every character in the file every frame, so
  cost grew with transcript length, not with what is on screen: measured on a
  1360-word spec, 5.47 ms -> 0.215 ms per frame. `will-change` likewise belongs
  on `.cc-line.on .cc-ch` only — on every span it is a compositor layer per
  letter of the whole transcript.
- **THREE SEPARATE, COMPOSABLE SYSTEMS — do not collapse them into one generic
  text wave.** (The framing is right and still holds; system 2's numbers below
  are the FITTED ones and are superseded by 2.2.3's stated 15% pop / 25%
  elevation. Kept because the fitted timings are still what `sync_rise_s` /
  `sync_peak_s` / `sync_fall_s` use.) Each is on a different scope, and every wrong model shipped here
  came from merging two of them:
    1. **Intonation** — the WORD wrapper. Uniform scale/weight envelope across
       all its letters: swells from `emphasis_lead_s` before the SPOKEN ONSET
       (may still be white), peaks near the stressed portion, holds while the
       word is spoken, decays over `emphasis_tail_s` to the common resting
       typography. Amplitude is prosody. **Never send size/weight through a
       word letter by letter** — only the sync wave travels.
    2. **Synchronization** — each CHARACTER span, **purely vertical**, and ONE
       bump **CENTRED ON THE LETTER'S OWN COLOUR TURN**. The .aep drives the
       lift and the fill from a SINGLE range selector: they are the same event,
       so the letter is at the top of its rise exactly as it turns (less the
       template's one-frame `anticipation_ms` lead). An approach-only bump —
       peaking before the turn and reaching zero AT it — leaves the letter
       perfectly still at the instant it changes colour, and the motion reads
       as **disconnected from the speech**. `wave_dip`/`wave_pop` (the scale
       bounce) exist but default to **0**: a lift AND a dip AND a pop is three
       oscillations per letter at ~15 letters/sec, which is what reads as the
       letters *vibrating*. Size belongs to the word envelope, and the AE
       template's only per-character property is `Position 3D` too.
       **FITTED to all three recordings in `docs/`** (`scratchpad/fit.py`
       method: track individual glyphs frame to frame, find each one's colour
       turn from its saturation, align that glyph's trajectory on its OWN turn,
       average). Consistent across all three:

       | | measured |
       |---|---|
       | crouch before the turn | -9.9% of glyph height, from -220 ms |
       | crosses baseline | at the colour turn |
       | peak above | +9.9% at +80 ms |
       | settled | +240 ms, **no undershoot** |
       | size | flat until the turn, 1.13 at +110 ms, rest by +280 ms |
       | colour crossfade | 52 ms (10-90%) |

       So the shape is a CROUCH then a rise THROUGH the turn — which is the
       .aep's two position animators seen from the other end: `Antecipate`
       (`y = +2`, DOWNWARD, ahead) handing off to `Up`/`Yellow` (`y = -5`).
       10% of glyph height = 0.052 em (lowercase ink height is 0.529 em).
       Our curve reproduces it to a mean error of 0.80 pct-points on lift and
       0.004 on size — under the measurement's own ~2% quantization floor.
       Do NOT apply `anticipation_ms` on top: the fit is relative to the turn,
       so the lead is already in its shape, and adding it ran the letter 35 ms
       early. The crouch is a PLATEAU (down ~60 ms, hold ~120 ms, release
       ~40 ms), not a sine hump.
    3. **Speaker identity** — colour only. Never a reason to swell or lift.
  They compose: `word scale x char scale + char lift`. Wrong models tried and
  rejected: prosody baked in permanently; no size motion at all (the .aep has
  no scale animator, but the website does — and without it the motion is dead);
  a single transient swell at the turn; and the emphasis attack sweeping letter
  by letter (that is system 2's job, not system 1's).
- **A swelling word PUSHES its neighbours aside** — words to its left slide
  left, words to its right slide right, and the row stays centred. Static
  margin cannot do this and two attempts at it failed: the growth is symmetric
  about the word's own centre, so the row must be resolved as a whole.
  `layout()` does it analytically each frame from resting widths measured once:
  `shift_i = SUM(dW_j, j<i) + dW_i/2 - SUM(all dW)/2`, where `dW = W(S-1)`.
  Rows are keyed on resting `offsetTop` so a wrapped line resolves each row
  independently. Pure arithmetic on stored measurements — never touches the
  layout path (0.21 ms/frame on 1360 words).
- **Measuring resting widths requires the lines to be LAID OUT.** `.cc-line` is
  `display:none` until it is on screen, and a hidden element reports
  `offsetWidth` 0 — so every width was 0, every shift resolved to 0, and the
  overlap fix silently did nothing (twice, in two different forms). `sizeAll()`
  adds `.measuring` to force `display:flex` for the measuring pass only. Also
  re-measure on `document.fonts.ready`: the font is embedded but still loads
  async, so the first pass can land on the fallback face.
- Verify overlap by measuring the real rendered gap between adjacent words
  (`getBoundingClientRect`) across the whole timeline — the worst gap must stay
  positive. Eyeballing a screenshot missed it.
- **Tune the motion in the tuner, not by round-tripping screenshots.**
  `python -m autocwi tune` loops a built-in line (long word for the character
  sweep, two-letter words to check the ripple's rate, one loud and one quiet
  word to bracket the envelope, two speakers) with every motion constant on a
  slider, plus a live plot of the curve the current settings produce. Writes
  `out/tuner.html`, never `captions.html`. "Show config.yaml" prints the values
  to keep. Constants baked into a word's `_type` (`size_pct`,
  `emphasis_deadband`, `quiet_deformation`) need `retype()` — without it the
  slider moves and nothing on screen changes.
- **The reference recordings carry LAYOUT GUIDE RULES, and they destroy glyph
  segmentation.** The site draws thin full-width rules across the caption band
  and a vertical playhead through it. One full-width rule puts ink in EVERY
  column, so column-gap segmentation collapses the whole line into a single
  run: measured, a 1029-frame recording yielded **14** glyphs instead of
  hundreds, and the "fit" from it was meaningless. `refmeasure._derule` erases
  any row/column covering >55% of the band before segmenting (text never does);
  it also removes the playhead, which must never be measured as a glyph.
- **Crop the caption band by COLOUR, not by ink.** The sync recording's band
  starts at x=139 — that is the page's left navigation menu, not the caption.
  The caption is the only text carrying a speaker colour, so find the band by
  matching the CWI palette (`R,G high & B low` for yellow, `G high & R,B low`
  for green) below the browser chrome. Crops in use:
  sync `1620:210:1390:1075`, intonation `2300:200:1000:1680`,
  speaker-id `2380:190:890:1265`.
- **Scroll recovery is what makes the two scrolling recordings measurable.**
  With `_derule` + `scroll_offsets` the usable glyph curves went 4 -> **59**
  (intonation) and 37 -> **130** (speaker-id). Nearest-centre tracking alone
  cannot follow a line moving ~4.5 px/frame.
- **`size_pct` below `mapping.loudness_to.min` silently kills the quiet half of
  the loudness channel.** `towardBaseline` computes `extent = baseline - min`
  for values under the baseline; if the resting size is below `min` that is
  negative, the `extent <= 0` guard fires, and EVERY quiet word returns exactly
  the baseline. Lowering `size_pct` to 2.8 (below `min: 3`) did this. Fixed by
  rescaling the range by `size_pct / baseline` in BOTH `typeOf` (JS) and
  `ccprosody.forward` (Python): CWI's anchors are ratios around its baseline
  and only read as absolute percentages when the resting size IS that baseline.
- **THE QUIET SIDE NOW WORKS — and three separate bugs were hiding it.**
  Measured, "softer." shrinks to **0.50x** the line's median glyph height, and
  the pipeline reported 0.92 (i.e. nothing). (a) `emphasis()` took `nanmax`
  only, so a word that merely shrinks reports its own resting moment plus the
  sync pop; it now takes the larger DEVIATION from rest, with 2.2.3's constant
  +15% divided out of the upward side, using p5/p95 rather than raw extremes
  so segmentation noise is not read as a shrink. (b) "Rest" was measured
  before the word's colour TURN — but the intonation envelope leads the onset,
  and "softer." starts shrinking ~0.9 s before it turns, so rest was measured
  on the already-shrunk word. Rest now comes from the first `REST_SPAN_S` of
  the word's support, which read-ahead (2.2.1) guarantees is resting. (c) The
  tracked-vs-framed choice compared RAW VALUES (`f_emph > 1.15 * t_emph` and
  `t_emph > 1.001`), which no shrink can ever satisfy — it compares deviations
  now. Tracking is least reliable exactly here: a word shrinking to half loses
  its tracks and the replacements measure their rest on the small glyph.
  `Word.emphasis_source` records which measurement won, per word.
- **No single word-split threshold works across one caption.** The line spans
  a 4x size range: "louder" at 2.2x nearly touches its neighbour, "softer." at
  0.5x has half-size spaces. An absolute threshold merges the shrunken words;
  a size-relative one merges the swollen ones. Both were tried and each broke
  the other end. `frame_words` searches a small threshold ladder and accepts
  only a split that yields exactly the right run count AND passes a
  SCALE-INVARIANT check: a run's width over its own glyph height is
  proportional to its CHARACTER COUNT at any size, so that must correlate with
  the words' lengths. Checking run widths against the RESTING boxes instead
  fails by assuming sizes have not changed, which is the thing being measured.
  The check earns its keep on an off-by-one: with "or softer." both at half
  size the ladder can merge "or"+"softer" while splitting the final ".", which
  still gives the right NUMBER of runs but shifts every word one place.
- **Frame attribution must outlive the glyph tracks.** Anchors come from
  tracks, and those die well before the caption leaves — on the "louder"
  phrase they end at 7.48 s while "softer." is still at half size at 8.5. When
  the rank split succeeds, RANK is the attribution and no anchor is needed;
  the window extends `EXTEND_S` past the last track and `frame_words` refuses
  any frame that does not split into this caption's word count.
- **(Superseded, kept for the reasoning.) The quiet side once could not leave
  the deadband.** Scaled
  whisper floor -> emphScale 0.833, `quiet_deformation: 0.35` compresses that
  to a deviation of 0.058, and `emphasis_deadband: 0.10` swallows it. So no
  word, however quiet, animates — consistent with the brief ("quiet words
  should produce little or almost no visible deformation"), but it means
  `quiet_deformation` is a no-op at these settings. Lower the deadband below
  0.058 if quiet words should visibly shrink.
- **`emphScale` depends only on `loudness - median_loudness`.** The map is
  translation-invariant, so the absolute loudness level is a gauge freedom and
  there is no fixed point unless the MEDIAN word's target is exactly 1.0 —
  which is the correct semantics, since emphasis is relative to the median
  word. `ccprosody.fit_spec_prosody` therefore solves each word's offset and
  re-centres, exactly and without iterating; an earlier iterate-the-median
  version oscillated forever.
- **Deriving a reference spec: READ the transcript off the frames, never guess
  it.** `scripts/derive_reference_spec.py --list-groups sheet.png` renders one
  frame per caption instance. Guessing cost two rounds: the sync recording also
  animates its "Synchronization" HEADING and carries a line I had missed
  ("Caption with Intention uses"), and the intonation recording has a
  decorative marker row as a fourth instance. The transcript lists EVERY
  instance in time order, `-` prefixing ones to measure but not emit (headings,
  loop repeats), and groups map to it 1:1 positionally -- matching by run count
  is hopeless because merged letters give ~13 runs for 28 characters.
- **Splitting captions needs a different signal per recording.** Turn-gap
  splitting fails outright: the pause BETWEEN two phrases (0.67 s) is shorter
  than one INSIDE "precisely as each word is spoken." (1.2 s). Lifetime overlap
  fails because read-ahead puts the next line up before the previous leaves.
  Static recordings: cluster on when each caption is DRAWN (a line appears all
  at once). Scrolling recordings: that fails too (glyphs enter the crop
  progressively), so use the `scroll_offsets` SEGMENTS -- the caption change is
  exactly where the scroll correlation collapses.
- **The per-word timing fit needs strong priors and one robust pass.** Merged
  runs mean roughly half as many observations as characters, so several words
  get one or none; weak priors emitted 20 ms words and overlapping neighbours.
  Span + continuity priors at weight 1.0/0.8, a forward sweep for ordering and
  minimum duration, and a 3-MAD outlier refit took residuals from 264 ms to
  21-36 ms (sync) -- one stray run had been dragging a whole phrase to 247 ms.
- **Per-word EMPHASIS is the MEDIAN ink height across a word's co-present
  glyphs.** The median is the whole trick, and three earlier attempts failed:
    * MAX height reads the ONE letter currently blooming as emphasis -- it put
      "voice" and "feel" at the ceiling and lost "louder";
    * WIDTH between glyphs cancels the bloom correctly (each glyph scales about
      its own centre) but is contaminated by scroll-recovery error, and still
      put "dynamic" and "uses" at the ceiling on the static recording;
    * comparing two tracks by ARRAY INDEX compares different moments, because
      tracks start on different frames.
  The per-character bloom hits one letter at a time (~1.13 for ~0.29 s), so it
  barely moves the median; the intonation envelope lifts every letter together,
  so it moves the median fully. Height is also immune to scroll error. Use ALL
  co-present glyphs, not first-and-last: on a scrolling line the first letter
  leaves the crop before the last enters.
  **Sanity check the output, always:** intonation must put "sizes," well clear
  of everything else, and synchronization -- which demonstrates timing, not
  intonation -- must come out essentially uniform. A word that is BOLD rather
  than large ("weights") correctly shows no height change; weight would need an
  ink-density measure, which does not exist yet.
- **`cc` may drive the axes harder than live, via `closed_caption` overrides.**
  `size_response`, `weight_response`, `width_response`, `wght_range`,
  `wdth_range` fall back to `expression` unless `closed_caption` names them.
  Live must stay compressed (words accumulate; a settled word must not
  restyle); `cc` plays through and is gone, and the reference genuinely swells
  further than live's compression allows. Measured, "sizes," reaches 1.43x its
  own resting height and "weights" 1.49x in ink density; live's
  `size_response: 0.42` caps the reachable swell at exactly 1.43 (so the
  measured value CLAMPED, and the effect read as too weak) and
  `wght_range: [280,500]` leaves +70 units above the anchor, which is
  invisible. `cc` uses 0.60 and [250,700]. **Merge via
  `ccprosody.merged_expression()` — three call sites need it, and a caller that
  reads `cfg["expression"]` directly silently gets live's values.**
- **Measure "rest" from the SETTLED TAIL, not the whole window.** An emphasised
  word is enlarged for much of its own window, so a full-window median absorbs
  the swell into the baseline and under-reports the ratio — "sizes," measured
  1.355 that way against a true 1.433.
- **The reference recordings are `docs/reference/character_identification.mov` (character id), `synchronization.mov`
  (synchronization), `intonation.mov` (intonation)** — trimmed to one cycle each, which
  removed the loop repeats that used to force `-` skip lines, and captured the
  two section titles the untrimmed captures had missed. True fps is
  frames/duration: **57.27 / 57.13 / 57.36** (NOT the container's 120). Crops,
  full width so a scrolling line is tracked before it exits::

  character_identification.mov  crop=3456:200:0:1270      --scroll --cut 0.75 --rotate 2
           synchronization.mov  crop=3456:210:0:1075                          --rotate 3
                intonation.mov  crop=3456:200:0:1680      --scroll --cut 0.55 --rotate 3

  `--rotate` exists because the transcript must stay in RECORDING order for the
  1:1 group match, but the recordings start mid-cycle, so the site's own order
  is a rotation of it.
- **THE PEAK LANDS AFTER THE TURN, AND THE RISE SPANS THE GAP.** Aggregated
  over all three trimmed recordings the lift peaks at **+70..100 ms** past the
  colour turn and the rise takes **70..100 ms** — longer than fast speech's
  ~60 ms gap, so the rise cannot be bounded by the gap. Model: the rise runs
  from the previous character's turn to `tTurn + wave_peak_s`, then releases
  over `wave_release_s` (measured fall 160-190 ms). With a long gap the same
  ramp simply stretches, which is why "is" is already near its peak and
  descending by the time it turns — one model, both cases. Verified at both
  ends: fast speech 17.6% at +80 ms (measured ~16% at +70..100 ms), held "is"
  77.5% (measured 77%).
- **THE ANTICIPATION LIFT IS A WORD-LEVEL MOTION, NOT PER-CHARACTER.** The
  word moves as one rigid unit. Measured on "is" in "precisely as each word is
  spoken.", both glyphs dip, rise, hold and land in LOCKSTEP: -21/-26%, then
  59/78%, peaking 77/102%, back to 1.5/4%. The i/s difference is only the
  normaliser — "i" has a taller ink box because of its dot, so an identical
  PIXEL lift reads as a smaller percentage of it.
  Driving it per character was wrong twice over: a word's first letter got the
  long INTER-word gap while every other letter got a tiny intra-word one, so
  each word led with a lifted first letter (a visible stutter on every word),
  and a word held through a pause raised only its first glyph. `wordLift()`
  now runs on the word wrapper and characters carry no vertical offset at all.
- **Deriving WEIGHT: use an ABSOLUTE density deadband, never the phrase's own
  maximum.** Normalising each phrase by its largest deviation stretches the
  biggest NOISE deviation to full bold whenever nothing in that phrase is
  actually emphasised — which is why bold kept landing on the wrong words.
  Measured, real emphasis is unmistakable: "weights" +0.53 and "louder" +0.19
  in ink density against +-0.09 for everything else. `weight_deadband: 0.12`
  and `weight_full_dev: 0.55` separate them and keep magnitudes comparable
  across phrases.
- **A JS syntax error takes the whole page down silently.** Twice a bad edit
  left an unbalanced brace and the only symptom was a probe reporting
  "built is not defined". Check first with an `onerror` handler injected before
  the cfg script — it reports the message and line directly.
- **A WORD HOLDS RAISED UNTIL IT IS SPOKEN.** The anticipation window is the
  WAIT — from the previous character's colour turn to this one's — never a
  fixed duration, and the rise GROWS with it. Measured on "precisely as each
  word |is| spoken.": the speaker pauses **1.47 s** before "is", and through it
  "is" dips to -21% of its glyph height, rises, and then **sits raised and
  white at 39->77% for ~0.75 s**, turning colour only at the end and landing
  ~0.24 s after. Ordinary fast speech (wait ~60 ms) reaches only ~14%.
  One fixed window with one amplitude cannot do both: it leaves a held word at
  rest through the pause (which is what read as "is should hold for a time")
  and makes fast speech leap. Knobs: `wave_hold_max_s`, `wave_hold_floor`,
  `wave_hold_full_s`; `linkTurns()` gives each word its predecessor's last turn.
- **The continuity prior in the timing fit must stay WEAK (0.12, not 0.8).** It
  pulls inter-word gaps toward the median gap, which actively flattens a real
  pause: the measured 1.47 s before "is" came out as 0.32 s, taking the held
  anticipation with it. Measured gaps are DATA; only unobserved words should
  lean on the prior. Weakening it also improved every residual (12-77 ms ->
  12-32 ms).
- **GROUND TRUTH for the intonation recording, measured frame by frame:**
  "louder" reaches **3.14x the line's median glyph height** and **2.2x its ink
  density** — it is enormous and heavily bold, far beyond anything measured so
  far. Method that sees it: per frame take the line's median glyph height as the
  resting reference and its tallest non-clipped glyph as the emphasis
  (`frame_emphasis`). **Per-glyph TRACKING cannot see it**: a word that swells
  to 3x and thickens has its glyphs merge and grow fast enough that association
  breaks, so the single most emphasised word in the recording produces the
  fewest usable tracks and measures as ~1.09.
  `frame_emphasis` is written and correct on magnitude but its word
  ATTRIBUTION is off by roughly one word — it credited "or" with the swell
  belonging to "louder", both with a +0.25 s slop window and with exact spans.
  **That is the next thing to fix**; until then the per-track measure is wired
  in, because it attributes to the right word even though it under-reads.
- **The config now has room for the real range** (it did not before): `cc`
  overrides `size_response: 1.0` (uncompressed), `quiet_deformation: 1.0` and
  `emphasis_deadband: 0.05`, reachable emphScale **0.88..2.20** (2.83 at a low
  median) and emphWght **200..900**. Before this the ceiling was 1.43 and the
  quiet side was entirely inside the deadband, so "louder" clamped and
  "softer." could not shrink at all however quiet it measured.
- **SIZE and WEIGHT are two channels and need two measures.** Size = median ink
  HEIGHT across the word's glyphs; weight = median ink DENSITY
  (ink pixels / bbox area), which is invariant to the size envelope — a word
  that merely grows keeps its density, one that thickens raises it. That is the
  only thing that separates "sizes," (large, normal weight) from "weights"
  (normal size, bold); height alone reports "weights" as no emphasis at all,
  which is *correct for height* and useless as a weight signal.
- **`cc` never clamped the RENDERED type axes.** `expression.wght_range` /
  `wdth_range` were applied in `livepage.py` and **zero** times in `ccpage.py`,
  so the uncompressed response curve resolved an 80 Hz voice to wght 1000 and a
  250 Hz one to 100 — ultra-black and hairline beside ordinary text. This file
  already documented the fix for live; `cc` had never received it. Now clamped
  in both `typeOf` (JS) and `ccprosody.forward` (Python), reachable span
  280..500 instead of 100..1000.
- **A silently CONSTANT prosody column looks exactly like an unimplemented
  effect.** Twice the derived specs carried one loudness value (0.5) or one
  pitch (165 Hz) for every word, so the size and weight envelopes could not
  fire and the renderer appeared not to implement them. `test_derived_reference
  _specs_replay_the_recordings` now asserts >= 3 distinct values in each
  column. When a channel looks dead, check the DATA before the renderer.
- **Two ways to measure per-letter lift, and they do NOT agree.** From the DOM
  (`getBoundingClientRect().bottom` over every char, one headless launch) the
  answer is exact: every character box is the same height, and the lift is a
  pure translate, so the spread of box bottoms equals the ink spread among
  non-descenders. It returns exactly `wave_lift_em / 0.529` at peak. The PIXEL
  method (segment glyphs by column gaps) inflates the tail badly — 38%/50% for
  a configured 17% — because merged runs and crop-edge glyphs land in the
  upper percentiles. Use the DOM for "what is the renderer actually doing",
  and the pixel method ONLY for comparing against the original recording,
  where it is all that is available — the same artifacts inflate both sides,
  so it stays apples-to-apples. Never mix a DOM number with a pixel number.
- **Measure per-letter motion against the original, don't judge it by eye.**
  Segment a frame into glyphs by column gaps, take each glyph's bottom edge,
  and report the spread across a row as a % of glyph height (drop descenders
  with a threshold PROPORTIONAL to glyph height — a fixed one leaves them in at
  small sizes and doubles the number). Like-for-like over the same span of a
  line, the original is **median 19.6%** and `cc` (calibrated,
  `wave_lift_em: 0.10`) is **20.8%** — equal to within the metric's own
  resolution, since one pixel at our glyph size is 4.2%. Calibrate on the
  MEDIAN only: p90/max are dominated by segmentation artifacts (they read
  38%/50% for a configured, DOM-verified 18.9%), so chasing them tunes noise.
  Two traps: measure the SAME extent in both (a narrow crop of one word only
  has motion while the boundary is inside it, so it scores far lower than a
  whole line), and match resolution.
- **What reads as "noisy" is COUNT, not amplitude.** The fix was to make fewer
  things move, not to move them less:
    * `emphasis_deadband` pins ordinary words to exactly 1.0 so they never
      animate at all — 1 word in 17 (6%) on the reference line, which is the
      "only occasional emphasis" the film stills show. An envelope on every
      word means something is always moving.
    * `wave_window_s` 0.16 (not the brief's 0.20-0.22): at conversational pace
      the wider window held ~6 letters in motion at once.
  Instrument it rather than eyeballing — count characters whose transform has
  a non-zero lift or a scale != 1. Now max 5, mean 2.8. **Careful:** the browser
  normalises `translate3d(0,0,0)` to `translate3d(0px, 0px, 0px)`, so a string
  compare against the written value counts every settled character as moving
  (it reported 70).
- `transform-origin: 50% 100%` on both scopes, so letters grow from the
  baseline rather than floating from their centre.
- **Word-level timing, character-level appearance.** The AE template drives a
  WORD-index range selector (`textLenWords`, animator literally named "Words")
  but with Ease High/Low set, which smooths the hand-off across characters. So
  "alphabet-level motion" and "word-level sync" are the same thing seen from
  two ends; `closed_caption.sync_granularity` switches between them.
- **THE CAPTION INVARIANT: a word that has been shown must stop changing —
  once its MOTION WINDOW passes.** (Refined 2026-07-23 for `motion.live_sync`.)
  A word turns its speaker colour, then animates through a ~0.3 s transient (the
  2.2.3 pop/elevation/swell) and comes to rest; from that point its size,
  weight, colour and RESTING position are frozen for life. What the transient is
  allowed to touch is bounded: `transform` only (so `font-size`/weight are never
  re-resolved), on the word itself and — POSITION only — on its row-mates, and
  every transform returns to rest and is written exactly once when the window
  ends. Verification may add/remove words and (under `display.stability:
  corrections`) respell one; it may never restyle one. Enforced by: server
  freezes `loudness`/prosody per time SLOT in `prosody_cache` (key
  `("§slot", utterance, round(start*20))` — text-keyed missed exactly when the
  verifier respelled); page's `typeCache` is first-write-wins and geometry is
  frozen on the node as `el._type`; the motion loop marks `dataset.moving` for
  the window and writes rest once at its end; tentative words and the sidebar
  `project()` instead of `fold()` so they never vote in the running median.
  Verify with slot determinism (server) and `window.__cwiChurn.report()` (page,
  `display.debug_churn: true`) — whose "settled" now means turned AND
  `dataset.moving !== "true"`, so bounded transform writes during the window are
  expected and a settled word must still show ~0 mutations.
- **Typography bugs are visual — screenshot before theorising.** Four real
  ones were invisible to metrics and only found by looking (see the recipe
  above): (a) live loudness used a `median - 5 dB` floor while real speech
  spreads ~26 dB below its median, clipping 35% of words to 3% whisper size;
  (b) a plain lo..hi window then put the MEDIAN word at mid-scale (6.5%), so
  ordinary speech read as shouted — the scale is now pivoted on the median so
  it lands on CWI's 5% baseline; (c) caption boxes did not wrap, and since
  verification ENLARGES words after placement, text ran off the stage — boxes
  now `flex-wrap`; (d) syllable fills froze at `--fill 0%` (solid white words)
  when the rAF chain stalled, so a 1.5 s sweep finalizes them.
- Type axes are anchored to the speaker's running baseline via `expression`
  in config.yaml. Mapping CWI's absolute anchors straight onto per-word
  acoustics made ordinary speech render as fabricated whispers/shouts (size
  swung 3.2x, weight 577). Do not raise `*_response` to 1.0 without re-checking
  that.
- A word animates exactly once, when spoken. Words already on screen are
  settled and must never move: `neighbor_bleed` is 0, `dataset.moved` guards
  re-entry, and endpoint verification re-colours without replaying motion.
- `display.mode` has four settings (config.yaml). Default **`fast`**: settled
  committed words PLUS the accurate stream's own tail as white read-ahead
  (~1.2 s behind the voice; ~35% less revision than the draft — the lone-word
  and follow-a-video mode). `stable`: committed words only, never revised.
  `sentence`: turn-taking, split at the verifier's punctuation. `readahead`:
  adds the 160 ms draft — lowest latency, visible rewriting. Do NOT reduce
  `live.endpoint_silence_s` for finer sentences (WER 2.27%→8.77% at 0.6 s),
  and do NOT release the held-back trailing word early: measured, it saves
  nothing (fires with the endpoint) and commits truncated spellings — a lone
  word reaches the screen through fast mode's white tail instead.
- Presentation (user preference, deviates from CWI 2.4): captions left-aligned,
  `display.retention: overflow` keeps lines until the stage is full and pushes
  the oldest off the top, and `display.intent_circle` closes each line with a
  circle — pulsing with the live level events on the active line (true dBFS,
  not the gained copy), frozen on finished lines.
- Endpoint verification reconciles PER WORD: matches corrected in place,
  deletions dropped, insertions (usually the one endpoint-held word) added at
  their spoken position via the normal word path. Never tear an utterance down
  and re-render it — the newest word is held back from committing until the
  endpoint, so a structural mismatch fires on almost every utterance, and a
  block rebuild makes each sentence flash discretely at every pause (a full
  `rack.replaceChildren()` even wiped the transcript).
- Live speaker attribution (CWI 2.1) runs by default: titanet-small
  embeddings (one-time ~38 MB fetch), segment-then-cluster in
  `SpeakerTracker`. Commits get a provisional classify-only label; the
  endpoint pass segments at change points, clusters whole segments, merges
  converged identities (aliases keep on-screen numbering stable). On the film
  sample it finds the major turns but still conflates the two voices in fast
  overlapping runs — close-mic'd speech separates far better (0.5 vs 0.2
  cosine on clean spans). Tune under `live.diarization`.
- Haptic hardware module: not started; it should subscribe only to final
  `type: "word"` events at `/events` (live) or read `spec.json` (offline).
  Durable words carry optional `speaker_change`/`emphasis` salience flags
  (threshold `haptics.emphasis_db`) — actuate on those, never every word
  (see docs/research-notes.md for the grounding).
- Cold start is ~7.6 s of model loading (GIL-bound, parallelizing barely
  helps). The server/page open FIRST with `boot` status events, models warm
  up on silence, and "listening" appears only when capture is real — words
  spoken before that are not being heard.
- Live capture is lossless. Keep deadline-based file pacing and drain all
  queued microphone blocks into catch-up batches; do not reintroduce normal
  backlog skipping, which caused missed words.
- Quiet speech used to produce nothing: there was no gain anywhere, and the
  transducer stops emitting tokens well below its training level. Fixed by
  `InputGain` (adaptive, holds through silence, acquisition ramp for the first
  utterance). `--quiet-sweep` measures it: at -40 dB the WER was 12.99%
  without gain and 3.90% with it. The browser now shows a continuous input
  meter, so a dead or too-quiet mic is visible without speaking a word.
