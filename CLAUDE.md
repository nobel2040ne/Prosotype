# CLAUDE.md — working notes for Claude Code sessions

auto-CWI ("Prosotype"): a local, offline pipeline that automates the
**Caption with Intention** (CWI) design system for Deaf/HoH viewers.
**Primary mode = live captions** (mic → CWI-styled captions in the browser,
English or Korean, selected before capture). The offline video pipeline is kept as the source of the
**CaptionSpec contract** that a future haptic device module will consume. See
`ARCHITECTURE.md` and `docs/DESIGN.md`.

## Commands

```bash
.venv/bin/python -m pytest                       # offline tests, no downloads
npm --prefix web install                         # one-time Next.js dependencies
npm --prefix web run check                       # lint + TS reducer tests + static build
.venv/bin/python -m autocwi live                 # live captions from mic (opens browser)
.venv/bin/python -m autocwi live --lang ko       # bypass picker, Korean
.venv/bin/python -m autocwi live --lang en       # bypass picker, English
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --lang ko # Korean model + Korean sample
.venv/bin/python -m autocwi live --sample --lang en # English model + English sample
.venv/bin/python -m autocwi live --sample --loop # repeat the clip continuously
.venv/bin/python -m autocwi live --file x.wav    # stream a file as if live
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live --file x.wav --once  # headless test
.venv/bin/python -m autocwi run clip.mp4 --out out/ --stub   # offline pipeline, no models
.venv/bin/python -m autocwi run clip.mp4 --out out/ --speakers 2  # real (spec.json)
.venv/bin/python -m autocwi cc out/spec.json --media clip.mp4  # CWI closed captions
.venv/bin/python -m autocwi tune                 # live motion tuner, built-in line
.venv/bin/python -m autocwi tune out/spec.json   # ...against a real spec
.venv/bin/python -m autocwi cc out/spec.json --tune   # same, from the cc command
.venv/bin/python scripts/fetch_font.py           # one-time Roboto Flex + Noto Sans KR
.venv/bin/python scripts/fetch_streaming_model.py # one-time 3-stage live ASR download
.venv/bin/python scripts/fetch_streaming_model.py --korean-only # Korean streaming ASR
.venv/bin/python scripts/fetch_streaming_model.py --speaker-only # ONNX speaker + native Sortformer
.venv/bin/python scripts/fetch_streaming_model.py --sortformer-only # rebuild/prepare Core ML path
.venv/bin/python -m autocwi live --sample --diarizer embedding # fallback comparison
.venv/bin/python scripts/fetch_fleurs.py --lang ko --count 300  # one-time eval-set download
.venv/bin/python scripts/benchmark.py --lang ko    # THE benchmark: text + word timing
.venv/bin/python scripts/benchmark.py --lang ko --stress      # + noise/reverb/1.15x
.venv/bin/python scripts/benchmark.py --lang en --quiet-sweep # InputGain guard
.venv/bin/python scripts/benchmark.py --audio assets/sample.mp4 --lang en # score-free
.venv/bin/python scripts/benchmark.py --lang ko \
  --backends local,speechmatics,soniox   # provider A/B (UPLOADS audio; needs keys)
.venv/bin/python scripts/studio_probe.py --samples 60  # studio motion metrics (CDP)
.venv/bin/python -m autocwi live --list-devices   # pick a mic if the default is wrong
```

The venv is `.venv/` (Python 3.11). Always use `.venv/bin/python`, not system python.

## Hard rules

- **Local and offline by default; cloud is opt-in and must stay fallback-safe.**
  No telemetry. Permitted network: one-time model/font/eval-set downloads, plus
  `live.verifier_backend: openai` (default `local`). Any cloud lane may supply
  **text only** and must keep the local path as a mandatory fallback that runs
  first, so a dead uplink degrades instead of dropping an utterance.
  **The binding constraint is per-word `start`/`end`,** not locality: prosody,
  `delivery_cache`, the motion clock, reveal gaps, and Sortformer coverage all
  key off word spans. Never synthesize onsets from a transcript that lacks them
  — that fabricates what CWI §2.2.2 is most explicit about. OpenAI's streaming
  models return no word timestamps, which is why they sit at
  `EndpointVerifier` (audio in, bare text out) and nowhere else. **Unmeasured:**
  no A/B has shown that beats local Parakeet.
- **`web/` is the product frontend; Python remains the runtime.** Build it with
  `npm --prefix web run build`. `output: "export"` emits `web/out`, and
  `autocwi.live` serves it, `/runtime-config.json`, `/session`,
  `/session/language`, `/RobotoFlex.ttf`, `/NotoSansKR.ttf`, and `/events` from
  one origin. Do not
  add a required Node server, Next route
  handler, Server Action, cookie, rewrite, or other feature incompatible with
  static export. If the export is absent, live intentionally falls back to the
  generated diagnostics page; a built studio keeps it at `/legacy`.
- **The Next studio and legacy renderer consume the same SSE contract.**
  `web/src/lib/caption-store.ts` owns the product UI's pure revision reducer;
  `web/src/hooks/use-caption-stream.ts` owns EventSource/reveal scheduling.
  Keep their finality/source/revision rules and 140/80–260/60 ms queue
  policy pinned by TypeScript tests alongside `live_render_core.js`. React
  keys are semantic `word_id`s. Speaker repartitioning, text correction, and
  reconnect replay must not remount a word into a second motion.
  Freeze live/replay eligibility when an ID first enters the reveal queue, and
  freeze its acoustic word snapshot when the scheduler reserves a first-paint
  slot. Do not start the clock in that scheduler callback: `MotionWord` calls
  `confirmMotionPaint()` during its layout commit and anchors
  `performance.now()` immediately before the first browser paint. A later
  text/timing/speaker/replay revision must neither
  cancel nor reshape that first motion, and its negative CSS phase delay must
  resume the original clock after any render/remount. It may never start a
  second clock. Character keys are indices so respelling reuses existing
  spans; extra characters on an older revision stay normal, while the newest
  onset prefix may grow `H → He → Hel` inside the original clock.
  Maintain a monotonic acoustic discovery frontier. A newly discovered ID more
  than 40 ms behind it is verifier/onset backfill: reveal it settled and never
  reserve a motion slot for a word outside the current Stage window. Every
  pre-paint slot reservation also has a 250 ms watchdog. If its component
  cannot mount and confirm paint, atomically settle it and release the slot;
  `abortedUnpaintedMotions` diagnoses this fallback.
- **Stage is a stable caption stack, not a second live-text panel.**
  `selectStableCaptionStack()` flattens revisable speaker and utterance
  partitions into fixed-width rows of **as many words as the stage can carry**
  (`planStageLayout`, bounded by `display.studio_stack_words_min`…
  `studio_stack_words_per_block`) and retains **as many rows as the stage can
  actually hold** without
  hiding recognized provisional words. Transcript keeps complete turns and
  speaker/utterance partitions. The reveal scheduler may run at most
  `display.max_simultaneous_reveals` simultaneous word motions (`display.max_simultaneous_reveals`, THREE since
  2026-07-30 — it is a throughput ceiling, not a taste setting); never
  implement that concurrency cap by filtering words from Stage.
  Row keys derive from the first semantic word ID, so overflowing into a new
  row or
  correcting attribution/segmentation cannot remount the first eight words or
  replay their motion. `unknown`/`Attribution pending` must obey the same fixed
  row capacity and never create one-word rows. Only the first appearance of a
  genuinely new bottom row runs the Stage FLIP transition: retained rows
  glide upward for 540 ms, new rows enter for 620 ms from opacity 0,
  `translateY(0.58em)`, and `scale(.985)`, and reduced-motion mode bypasses
  both. The initial block gets the same entry; an initial replay containing
  multiple rows does not. Text/color/speaker updates with identical row IDs must return
  no stack motion; removal or reappearance of a seen row must also return none.
  **THE ROW WIDTH AND THE RETAINED ROW COUNT ARE BOTH MEASURED, NOT CONFIGURED
  (2026-07-30).** `useStageLayout` reads the feed's real width, gutters, height
  term and a rendered row's height, calls `planStageLayout`, and passes BOTH
  answers to `selectStableCaptionStack` (see the words-per-row entry below);
  `display.studio_stage_paragraph_history` is now only the pre-measurement
  fallback and the floor of the clamp. As a constant it was SIX, and measured at
  1440×900 six rows filled **52%** of the stage — so the seventh row evicted the
  first while half the surface sat empty and the stack visibly scrolled for no
  reason. The same window now holds **9 rows light / 8 dark** (dark adds .22em of
  row padding, which is a whole row over a full stack — so the THEME is a
  dependency of the hook; a ResizeObserver on the stage cannot see a theme swap).
  Measured fill is now 0.87 light / 0.895 dark. Read the row height off a
  rendered `.caption-paragraph`, not from a constant, and note that Chrome
  reports a percentage `max-height` as the literal string `"83%"` rather than
  resolving it — it has to be resolved against the stage box by hand.
  **The stack is TOP-ANCHORED (2026-07-30):** `.caption-feed` starts near the top
  of the stage and fills downward, so the newest caption sits at eye level rather
  than hugging the bottom edge. A new bottom row therefore displaces nothing
  until the capacity starts evicting from the top, and
  `planCaptionStackMotion` must return that lone `enter` — requiring an
  accompanying `shift` silently dropped the entry transition for every block
  before the cap was reached.
  **Anchoring is `top` + `max-height` + `justify-content: flex-end`, and all
  three are load-bearing.** `height: auto` lets the box hug its content and stay
  pinned at `top`, so a short stack sits high; once the content passes
  `max-height` the box stops growing and `flex-end` puts the negative free space
  at the TOP, so the OLDEST caption leaves the screen. A plain `top`/`bottom`
  box with `flex-start` clips the other end — measured, the newest caption
  vanished the moment the stage filled, which is the whole failure this
  arrangement exists to prevent. Verify by forcing `--caption-width-cap` far past
  its measured value (the Caption scale slider can no longer overflow the stage —
  see below) and confirming `OLDEST_clipped`, never the newest.
  Keep the selector tests whenever changing
  reducer order, finality, or paragraph identity.
- **THE STAGE IS THE ONLY THING IN THE WORKSPACE (2026-07-30, at the user's
  request).** Removed: the nav rail (a "Live" button for the view you are already
  in, a `/legacy` link, and a "Setup" button duplicating the topbar's settings
  icon — 72px of stage width); the workspace header (`CAPTURE 01 › FAST`, a title
  repeating the Stage tab, and word/speaker/signal counts the rail already
  reports); the transport bar (three static `Local processing / No cloud / Stream
  active` badges — its one live reading, input dBFS, is a topbar chip now); the
  `AUDIENCE VIEW / VOICE-SHAPED MOTION` stage label, the stage grid and the four
  corner brackets (the light stage already hid the last two); the rail's fourth
  "system" section (a hardcoded string, the settings slider's own value, and the
  compass readout again); and the compass's `Hardware: Mono input`, which said
  what `Direction: Awaiting array` says one line above it. Measured at 1440×900
  the stage went 974×596 → **1072×729** and the caption type 37.4 → **47.1px**.
- **TWO DESIGN SYSTEMS, AND THE BOUNDARY IS THE WORD.** (2026-07-30.) The
  studio CHROME follows the Apple design analysis skill; the CAPTIONS follow
  CWI, which outranks it. The dividing line is literal: anything inside
  `.caption-word` is CWI, everything else is Apple.
  * **Apple, for chrome:** one accent and one only — Action Blue `#0066cc` on
    light, Sky Link Blue `#2997ff` on dark (Action Blue measures **2.68:1** on a
    dark tile, which is why the analysis reserves a separate on-dark accent).
    Ink `#1d1d1f` on parchment `#f5f5f7` / canvas `#ffffff`; the near-black tile
    ladder `#272729`/`#2a2a2c`/`#252527` on black. Radius only on the
    0/5/8/11/18/pill scale (`--r-*`), and **`--r-md` (11px) has no caller on
    purpose** — the analysis calls it the rare Pearl Button step, so dense rail
    cards are `--r-sm` and large surfaces are `--r-lg`; five `--r-md` callers was
    the "mixed radii grammar" the Don'ts name. Weight ladder 300/400/600/700 —
    **500 is deliberately absent**, so no 560/590/650/680. No shadows on chrome
    and no decorative gradients: surface-colour alternation is the divider. A
    shadow on chrome is allowed only where it is a DATA channel (the voice orb /
    compass halo carries periodicity); `.voice-compass` also had a hardcoded
    `inset 0 0 34px rgba(0,0,0,.38)` that was pure decoration and, being black,
    smudged the dial on the light stage instead of inverting with `--tint`.
    Focus ring `#0071e3`; `button:active { transform: scale(.95) }` once,
    globally, and it is the system's ONLY transform micro-interaction — no hover
    lift, no sliding arrow. Default and active states only: the analysis
    documents no hover, so the studio has none.
    **Tracking is subtle.** The ramp's entire negative range is
    `-.12px .. -.374px` (≈ -.005em .. -.011em), so `-.035em` on a 21px title and
    `-.03em` on a 28px label were 3× tighter than anything in it and read as
    cramped. Prefer the literal px ramp values over hand-rolled em.
  * **CWI, for captions:** Roboto Flex / Noto Sans KR with live variable axes,
    the CI speaker palette (or `palette_light`), and the §2.2.3 motion cue.
    Never let an Apple token reach `.caption-word`, and never let a CWI token
    style a button. Apple's "UI recedes so the product can speak" is why the
    captions carry no box, no frame, and no per-block label — here the captions
    ARE the product. The language gate's `English`/`한국어` is a BUTTON LABEL, not
    a caption sample: it sat on `--font-caption` (Roboto Flex) while the Korean
    option was separately overridden to a system Hangul stack, so the two options
    did not even match each other. Both are `--font-ui` now.
  * The analysis's 17px body is a marketing-page pace and does not transplant
    onto a dense studio rail. What did transplant is its FLOOR: every label
    below the 10px micro-legal rung was lifted onto 10/12/14, which is most of
    what made the UI more readable.
- **The light stage is a toggle-gated, MEASURED deviation from the PDF.**
  (Added 2026-07-30 from a reference the user supplied.) `Settings → Light stage`
  defaults ON and writes `data-theme` onto `document.documentElement`; every
  studio surface is a token, and `--tint` inverts all 14 hairline/inset/grid
  tints at once. **It has NO captions box at all** — `--caption-box` and
  `--caption-box-shadow` are `transparent`/`none`, type sits directly on
  `--stage-bg`, and the per-block speaker label is hidden on Stage, so what
  carries the caption is typography. It therefore contradicts **§2.4.1**
  (captions box black at 90%) outright, and consequently **§2.1.1/§2.1.2**,
  because the CI palette is built for that black
  box: measured against the light stage `#FAFAF8`, CI Yellow is
  **1.19:1**, Green **1.52:1**, Blue **1.39:1** — invisible, not merely weak.
  Speaker identity is then carried by COLOUR alone, which is what §2.1
  specifies anyway; the rail's Active speakers panel still names them, and
  Transcript keeps the per-paragraph label and timestamp.
  `--stage-bg` is the surface `palette_light` is measured against — change one
  and re-derive the other.
  `palette_light`/`palette_support_light` in `config.yaml` keep each CI HUE and
  darken only its VALUE to ≥4.5:1; CI Red `#E51717` already passed and is
  unchanged. Do not hardcode either palette in CSS or TSX — both arrive through
  `/runtime-config.json`, and `speakerColor()` returns `var(--caption-unknown)` /
  `var(--accent)` rather than literals so the fallbacks follow the theme too.
  Turning the toggle off must restore the exact CI values and the black box.
  `autocwi cc` and the legacy diagnostics page are NOT themed: `cc` is the
  design-system reference renderer and §2.4.1 applies to it literally.
- **Language is a pre-capture model decision.** With no `--lang`, the Next
  studio POSTs exactly one `en`/`ko` choice before Python loads ASR or iterates
  the mic/file source. `LiveLanguageSession` then locks it for the capture.
  `--lang en|ko` is the deterministic/headless bypass. Never make the selector
  cosmetic or hot-swap a recognizer under retained decoder/audio state.
- **Keep live diarization hybrid and language-complete.** On Apple Silicon,
  `live.diarization.backend: auto` prefers the native Streaming Sortformer v2.1
  helper, while endpoint segmentation/embeddings verify durable identity and
  recover quiet speech or >4-speaker sessions. English uses ERes2Net; Korean
  uses multilingual CAM++ and must receive the same endpoint speaker pass even
  though its weaker text verifier is disabled. Never replace final identity
  with an unverified transient Sortformer slot. Keep S1/S2 immediate, but do
  not expose an unmapped native slot above that frontier. A third-or-later
  embedding profile needs repeated clean endpoint observations before its
  `S3…S6` label becomes public; confirmation revises earlier neutral words.
  This is not a two-speaker hard cap. Never make
  `Attribution pending` gate the Stage stack. `--diarizer embedding` is the
  deterministic A/B and unsupported-platform fallback.
- **Pinned versions** in `requirements.txt`. Seed anything stochastic.
- **The CaptionSpec (`autocwi/schema.py`) is a versioned contract.** Renderers
  and the future haptic module consume ONLY `spec.json` / the SSE word events
  — never model objects. Extend the schema with optional fields; breaking
  changes require a version bump.
- **All mapping values live in `config.yaml`**, never hardcoded. They follow
  the official CWI Design System V1.0 — cite section numbers in comments.
  **READ THE NUMBERS OUT OF `docs/cwi-design-system-v1.0.pdf` ITSELF, NOT OUT OF
  `docs/DESIGN.md` (the user's instruction, 2026-07-31: "it is wrong").** That
  file mixes the PDF's stated values with derivations fitted to
  `docs/reference/*.mov`, and where the two disagree the fitted material has
  been wrong every time — the recordings are the project's *website*, not the
  spec. Treat `docs/DESIGN.md` as a changelog of superseded interpretation.
  `docs/RESEARCH.md` maps prior DHH-captioning research onto design decisions
  here and is unaffected.
- **ALL PRESENTATIONS SHARE THE CWI MOTION SEMANTICS.** (Current live contract
  updated 2026-07-24.) The legacy live diagnostics consume
  `autocwi/cwi_motion_core.js`; the Next product UI expresses the same
  first-paint/rest/reveal invariants with typed event state and independent CSS
  envelopes. The shared JavaScript module holds `typeOf`,
  `intonationAt`, `scaleOf`/`liftOf`/`wghtOf`, `charColorAt`,
  `charLiftOf`/`charScaleOf`, and optional `resolveNeighborPush`. The
  presentations intentionally do not share tuning:
  authored `cc` can use the full reference wave against known text, while a
  stacked live transcript uses calmer `motion.live_sync` amplitudes and never
  moves settled neighbors.
  * **`cc`** drives the same curve family off the global media clock `t` (pure
    function of `t`; read-ahead is real). *(NOTE: `livepage.py` consumes the
    module; `ccpage.py` still has an inline authored-clock implementation. Its
    character amplitude is additionally wait-aware through
    `wave_hold_floor`/`wave_hold_full_s`, so the two are contract-equivalent,
    not byte-identical. Migrating those authored-clock inputs into
    `cwi_motion_core.js` is a future structural cleanup, not a visual change.)*
  * **legacy live** runs the shared synchronization/character primitives plus its
    independent variable-font envelopes on a PER-WORD first-paint clock.
    `virtualT()` maps the full synchronization rise/peak/return onto 520–720 ms
    according to the acoustic word span (680 ms for a first-phone onset hint).
    Raw decoder spans are not played directly; doing so compressed long-word
    attacks into a few frames. A separate `displayCharacterMotionWord()` gives
    internal character turns 0.18 s of virtual spacing (capped at 2.20 s)
    before mapping the curve into that window. `smoothCharacterChannel()` then
    blends neighbouring samples by 0.72, so long spelling never compresses the
    wrapper and the alphabet hand-off reads as one ribbon. The independent
    cue/commit clock owns colour and never starts or restarts geometry.
    See `resolveCCLine`/`motionTick`/`settleWord`/`playWordMotion` in
    `livepage.py`. Verify with `scratchpad`-style sweep probes and
    `scripts/live_render_probe.py`.
  * **MEASURED 2026-07-30 via `scripts/studio_probe.py` (sample.mp4, 60
    samples).** Peak simultaneous motions **2** (the cap was 2 then; it is 3 now);
    `motionsWithoutPaint` / `abortedUnpaintedMotions` /
    `freshWordsWithoutMotion` all **0**; `motionStarts == motionPaintStarts`
    (58), so every reserved slot painted. But **presentation backlog peaked at
    3.4 s single-pass and 7.6 s looped, against a 600 ms target**, with
    `minimumMotionDurationMs` bottomed out at the 320 ms floor — the adaptive
    clock ran out of room and still could not keep up. Conversational English on
    this clip has ~160 ms median onset spacing (vs 520 ms for FLEURS Korean),
    i.e. ~6.2 words/s, which is exactly the two-slot queue's ceiling at the
    320 ms floor. **Do not lower the 320 ms floor to fix this** — below it the
    motion stops reading as motion.
  * **RESOLVED 2026-07-30, and the max was the wrong statistic.**
    `presentationBacklogMs` is `newest − current` in ACOUSTIC time, so its
    peak is dominated by whatever was buffered when the browser attached. It
    read an identical 3211 ms across runs with different settings, which is the
    tell. Sampled as a SERIES it decays to 0 by ~7 s and stays there — there
    was never steady-state lag. Two real causes, two fixes:
    1. `max_simultaneous_reveals` **2 → 3**. N slots at the 320 ms floor cap
       throughput at N/0.32 words/s, so two slots (6.25 w/s) sat exactly on
       conversational English's 6.2 w/s. Three gives 9.4 w/s of headroom.
    2. `display.word_motion_backlog_ceiling_s` (**1.20**) — the actual fix.
       Cold start takes ~7.6 s while the source keeps running, so the first
       browser to attach inherited a measured 12.7–18.2 s / 28–53-word queue
       and spent ~7 s animating words that were spoken seconds ago. The
       adaptive clock cannot help: it shortens a motion, it cannot make one
       free. A word past the ceiling is HISTORY — it reveals settled and
       un-paced (`gap: 0`), exactly like every other historical insertion.
       Measured on an 18.2 s backlog: 57 words settled, catch-up finished in
       **4.1 s**, the 3 words inside the ceiling animated normally, and every
       integrity counter stayed 0. `staleSettledWords` in
       `window.__cwiStudio.report()` makes the path observable.
    **Sample the backlog as a time series, never as a max.** The max answers
    "how deep was the buffer at attach", which is not the question.
  * **`--dump-dom` cannot read the studio.** It serializes at the load event,
    before hydration and before any SSE word, returning essentially the raw
    `web/out/index.html` shell. `live_render_probe.py`'s document.title trick
    works only for the legacy non-React page. Use `scripts/studio_probe.py`,
    which drives CDP over a websocket and calls `window.__cwiStudio.report()` on
    a live page. Screenshots still work (they wait for paint) but give pixels,
    not metrics.
  * **THE SETTLED-TYPE ANCHORS ARE ABSOLUTE. NEVER RE-CENTRE THEM ON THE
    SPEAKER (2026-07-31).** `web/src/lib/settled-type.ts` is now the single
    source of CWI 2.3, and it is deliberately gamma-free. **SUPERSEDES** the two
    entries that used to sit here — "there is no trigger threshold on amplitude"
    (`deliveryExpressiveness`) and "axis response is expanded around the
    speaker's own centre" (`expandAroundCenter`/`expandPitch`). Both belonged to
    the era when voice was an ANIMATION amplitude; once voice became the resting
    type, the same expansion destroyed the two anchors the PDF is most explicit
    about. `web/src/lib/voice-sensitivity.ts` is deleted — nothing imported it.
    The three defects, all measured on the bundled English sample
    (233 SSE words / 111 rendered), all invisible to the integrity counters:
    1. **2.3.5's baseline was off by 20%.** The server already normalizes
       `loudness` onto the design system's own size axis — 0 is 3% of screen
       height, 1 is 12%, and it pivots the speaker's running median onto the 5%
       baseline at **0.2222** (`_word_event` in `live.py`). The client centred
       that on **0.5**, as if it were a plain normalized level, so the MEDIAN
       word rendered at **0.793×** the baseline: measured median 0.224 → 0.79.
       Ordinary speech was captioned as permanently quiet, and the stage type
       had been shrunk on top of that to clear a ceiling only shouts reached
       (median word **28.0px**). The literal map is just `(3 + 9L) / 5`.
    2. **2.3.8's neutral band did not exist.** "All captions within this vocal
       range maintain this type-weight as a default" describes a **BAND**
       (160–200 Hz → Regular 400), not a pivot. The client had a single pivot at
       180 Hz *and* re-centred pitch on the speaker's running baseline with
       gamma 0.62, so a word 10 Hz off that median was thrown across the whole
       axis: **67 distinct weights spanning 100–876** on ordinary conversation,
       with only **19%** of words on Regular. Use RAW Hz against the PDF's
       absolute 80/160/200/250 anchors.
    3. **2.3.10's diagonal was broken.** Width summed two always-positive terms,
       so measured `font-stretch` **never once fell below 100%** — the condensed
       half, i.e. the entire "thinner or sharper" reading, was unreachable — while
       weight ran to 876. Loud/high words therefore rendered big + hairline +
       normal-width, exactly the mismatch p.41 rules out. Width is now centred on
       100% and driven by the same signed tone as weight (0.7 pitch / 0.3
       texture), with the harmonics proxy allowed to pull TOWARD neutral but
       never past it — a plain 0.7/0.3 blend does not hold the diagonal at mild
       tones, and a 130 Hz word with a thin proxy still resolved heavy+condensed.
    **Measured after** (`scratchpad/motionprobe.py`, CDP, 500 frames):
    median settled scale **1.00** at **31.8px**, 65 distinct scales; median
    weight exactly **400** with **32%** on Regular, 30 distinct weights,
    200–726; **44%** of words condensed, 21 distinct widths; **0** off-diagonal
    pairs. Pop still exactly 1.150 / 0.250em on every word, `motionStarts ==
    motionPaintStarts`, every integrity counter 0, peak concurrency 3.
    Config: `settled_scale_response` (0.60) is the live narrowing lever and it
    compresses ABOUT the baseline, so 2.3.5 is exact at any value — the clamp
    alone cannot do that, it flattens the top of the distribution into one
    indistinguishable size. `settled_scale_range` [0.72, 1.55],
    `weight_range` [200, 760], `width_range` [82, 124]; 400 and 100% must stay
    strictly INSIDE the last two or the neutral band cannot be expressed.
  * **`settledScaleAllowance`'s coefficient tracks the DISTRIBUTION, not the
    range (2026-07-31).** It was 0.60, fitted while the median word rendered at
    0.79× the baseline. Correcting that anchor moved the measured requirement to
    **1.467** at a 1.55 ceiling, which 0.60 under-budgets by 13% — rows would
    have overflowed the stage. Re-fitted across scale responses 0.45–1.0 the
    requirement is `1 + (max−1)*0.85` to within 1.5%; shipped **0.88**.
    Measure it by sliding a window over the recognizer's REAL word order with
    each word at the settled size/weight/width its own voice earns and its
    advance measured in the real caption face (`scratchpad/measure_widths.py`),
    never by IID-sampling widths. Widening `width_range` from [88,115] to
    [82,124] cost 0.004 of budget, because the widest row and the loudest run
    are never the same row. Base type 35.45 → 32.73px, median word 28.0 →
    31.8px — the corrected anchor buys size back despite the larger allowance.
    Acceptance after any change here is `scratchpad/overflow.py`: sweep
    theme × 1440×900 / 390×844, driving the theme through the REAL settings
    toggle, and assert 0 wrapped rows, 0 orb overlap and no glyph past the clip
    box while motions are active. Detect a wrapped row by vertical OVERLAP of
    its words, NOT by equal box tops — words rest at different sizes on a shared
    baseline, so equal tops flags every row. The one legitimate overflow is the
    TOP edge on row 0: `justify-content: flex-end` clips the OLDEST row by
    design (measured 5.95px at 390×844 light, 13 rows).
  * **THE DESIGN SYSTEM PDF DESCRIBES EXACTLY THREE THINGS. BUILD THOSE.**
    (2026-07-31, after the user cut short several rounds of inferring motion
    from `docs/reference/*.mov` — that is the project's *website*, not the
    spec.) `docs/cwi-design-system-v1.0.pdf` pp.26–41:
    1. **2.2.2 colour sync** — the word turns the speaker colour at its spoken
       onset ("when 'In' is spoken, not when 'ble' is spoken").
    2. **2.2.3 motion** — "Each word should undergo a **15% increase in type
       size** before returning to its original size, creating a 'pop' motion
       effect", and the diagram labels the rise **25% elevation**. Its inset
       ("we need to talk") shows the popped word both LARGER and RAISED off its
       neighbours' baseline. One transient, per word, once. **Its amplitude is a
       CONSTANT** — verify `popScale` p50 == max == 1.15 and `liftEm`
       p50 == max == 0.25em.
    3. **2.3 intonation** — volume → type SIZE (2.3.3/2.3.6: 3%…12% of screen
       height, 5% baseline), pitch → type WEIGHT (2.3.8: 160–200 Hz is Regular
       400; 2.3.9: 80 Hz heavy, 250 Hz light), harmonics → type WIDTH
       (2.3.9/2.3.10). **THIS IS THE RESTING TYPE, NOT AN ANIMATION.** The pages
       show whole STATIC sentences with a different size and weight on every
       word — p.34 "Put that coffee **dOWn!** Coffee's for closers only!",
       p.40 "The higher the pitch, the lighter the font becomes."
    **We had it inverted, and that was the whole problem.** Every word settled
    to IDENTICAL typography and all the voice was crammed into transients: a
    word-wide size swell with six delivery variants, a word-wide weight+width
    swell with six more, and a travelling character bulge — nine animations in
    flight on up to three words where the PDF has one. That is what read as
    "messy and promiscuous", and because every channel returned to the same rest
    state the voice never actually showed, which is what "the font size effect
    and word level lifting doesn't happen" meant.
    Now: `settledTypeFor()` writes `--settled-scale` / `--settled-weight` /
    `--settled-width` once per word from the frozen prosody, NEVER animated (the
    caption invariant is satisfied by construction — there is nothing to re-run),
    and `@keyframes word-sync-pop` is the only caption animation in the
    stylesheet. **The MAPPINGS shipped with this round were wrong and were
    corrected 2026-07-31 — see the settled-type-anchors entry above for the three
    defects and the current measurements.** Getting the animation count right did
    not make the axes right: a channel can be present, continuous and still
    anchored 20% off its stated baseline.
    Consequences, all load-bearing:
    * **`transform`, not `font-size`, for the cue.** It is transient and must
      never reflow the row. `transform-origin: 50% 100%` so it grows from the
      baseline, as the diagram shows.
    * **One leading for every row, as a LENGTH** on `.caption-words`:
      `1.12em * --settled-max + --sync-elevation-em`. Sized per-row from that
      row's own biggest word instead, row heights varied, `useStageLayout`'s
      capacity estimate (available height ÷ a *sampled* row's height) was wrong
      for every other row, and the stack overran the top of the stage by a
      measured **308px**. A NUMBER line-height fails differently: it is
      re-multiplied by each word's own font-size, so the biggest word drives the
      row height again.
    * **The row budget carries the settled spread**, via
      `settledScaleAllowance()`. MEASURED, not guessed: the widest row at settled
      sizes is 15.42 / 18.37 / 21.16 / 24.44 em at N=3…6 against unscaled budgets
      of 11.65 / 14.20 / 16.61 / 18.93 — a ratio of ~1.30, flat in N. Two traps:
      the settled scales centre on **1.0 at the median loudness**, not on the
      midpoint of the range (measured mean 1.024 against a [0.7,1.6] midpoint of
      1.15, so the midpoint over-budgets by 12%); and multiplying a worst-case
      WIDTH by a worst-case SCALE double-counts, because the widest row and the
      loudest run are not the same row. Re-measure with
      `scratchpad/scaleallow.js` if `settled_scale_range` changes.
    * **Cost of the wide range:** the base type drops (47 → 35.5px at 1440×987)
      because rows are ~30% wider. Typical words render near the base, loud words
      at 1.6×. Narrowing `settled_scale_range` is the lever if that is too small.
    * **No shadow anywhere inside `.caption-word`**, and no per-word delivery
      motion families — the PDF has neither. Delivery survives as a readout and
      through the settled weight/width axes.
    **SUPERSEDED by this entry** (kept only so the reasoning is not re-derived):
    the travelling character bulge, "the baseline is flat / nothing lifts", the
    reflowing line, and "25% elevation is 25% of glyph height". All four came
    from the recordings. The PDF's own diagram raises the word, and 2.2.4 says
    words animate "fully, one by one" — syllable-at-a-time is the documented
    *exception*, gated by `motion.syllable_fill`.

  * **RETURN-TO-NORMAL IS STRUCTURAL (2026-07-31, USER CORRECTION).**
    **SUPERSEDES** the "settled-type anchors" and "resting type" implementation
    entries immediately above. The §2.3 anchors remain absolute, but in the live
    studio they define the voice-shaped CREST of a word's one motion window, not
    permanent caption typography. Every word begins and ends at normal 5% /
    Regular 400 / width 100.
    `web/src/lib/caption-motion.ts` builds the pure plan:
    normal → §2.3 voice crest composed with §2.2.3's constant 1.15 / 0.25em cue
    → normal. CSS implements it with an invisible `.word-sizer` that owns layout
    and an absolutely overlaid `.word-glyph`; no width measurement or frozen
    inline size exists. Both keyframes have explicit normal endpoints and use
    the default `animation-fill-mode: none`, so pixels return to normal even if
    an `animationend` callback is delayed. The callback only clears logical
    state/concurrency. Config keys are `voice_scale_range` ([0.90, 1.20]) and
    `voice_scale_response` (0.25); composed with the fixed 1.15 cue, the largest
    live crest is 1.38x. There is no `settledScaleAllowance`.

  * **Speech rate must not reduce caption throughput.** A fixed 520–720 ms
    duration gives the two-slot Next reveal queue a hard ceiling of roughly
    3.8 words/s and creates an ever-growing presentation buffer above it.
    `motion-timing.ts` measures median acoustic onset spacing—not decoder
    arrival spacing—and selects only the shorter clock needed to sustain that
    rate. Ordinary speech retains 520–720 ms. Faster speech and decoder-batch
    debt can reduce toward a 320 ms smoothness floor; the backlog target is
    600 ms, rate headroom is 0.90, and catch-up scale is 0.82. Pending count
    also supplies a batch-drain budget, so sparse Korean endpoint batches catch
    up even when their individual acoustic gaps are slow. Freeze that selected
    duration in `MotionSnapshot`; a later revision may not change it.
    In the legacy renderer, acoustic span continuously maps the complete
    motion to 520–720 ms; `_motionPaceGain` also eases from
    0.58 on a minimum-duration word to 1.0 on a slow/drawn-out word. A
    `slow_delivery_curve_delay` of 0.06 shifts the independent axis peaks later
    inside a slow word's already-longer clock, so it feels languid rather than
    like the fast shape played at a lower frame rate. Caption reveal/onset
    spacing is unchanged. In the bundled browser sample, fast words attacked
    weight/size/width at about 156/218/260 ms; drawn words at about
    244/346/397 ms. Character turns remained roughly 53–110 ms apart.
  * **Weight and width animate per frame.** The word box is frozen at its
    resting width (`el.style.width`, measured once in `resolveCCLine`; CSS
    `text-align:center; white-space:nowrap`), so the variable axes cannot reflow
    or overlap the row. `live_sync.neighbor_push` is false: no earlier caption
    moves because a new word is active.
  * **Colour has a separate clock.** An ordinary moving word receives a
    150–280 ms white→speaker-colour sweep; a drawn-out word uses measured
    syllable/phoneme stops over 180–900 ms. Colour may begin while geometry is
    active. A late colour decision on a settled word is a direct colour write,
    never a delayed motion trigger. Paint `.cwi-ch` spans individually; do not
    restore `background-clip:text` on their parent. Chromium can collapse the
    inline children onto one origin while compositing that effect, producing
    the piled-up glyph corruption seen in the 2026-07-24 sample.
  * **The caption invariant is visual-first-paint, once only.** Decoder batches
    reveal in acoustic order (140 ms base blended with 80–260 ms measured
    onset gaps), bounded by the configured concurrency. Deadlines stay anchored to the
    planned sequence; never replace them with `performance.now() + gap`, which
    compounds latency after every late frame. Keep the 60 ms catch-up floor.
    If both motion slots are occupied, a fresh word stays hidden until a slot
    opens; never paint it motionless and never pop an already-visible word.
    `_type` is first-write-wins per
    acoustic slot and `dataset.moved` plus the semantic motion-history set guard
    re-entry. Verification preserves an unseen node's queue eligibility and an
    active node's clock; an already visible correction never replays motion.
    Replay/reduced-motion/historical correction records settle directly.
    This includes a newly inserted word whose acoustic start is behind the
    monotonic discovery frontier. It may update readable history but must not
    animate late or reserve one of the two Stage slots.
    Never settle an active first-paint clock merely because its word was
    corrected: that truncated a few words before their visible peak. The Next
    studio renders motion from the frozen `MotionSnapshot`, phase-locks CSS
    with `--motion-phase-delay`, and lets the selected 320–720 ms clock finish.
    Its concurrency slot is reserved before React renders, but the clock and
    expiry begin only when `confirmMotionPaint()` runs in the word's layout
    effect. A busy render therefore cannot consume the attack off-screen.
    Slot timeout and settled state are committed together so a fast burst
    cannot expose a third active word for one frame.
    Corrections do not change its family/axes/duration. Once settled, all later
    same-ID revisions remain Regular 400/100% with `animation-name: none`.
    The broadcaster marks retained records on the first audience connection
    `_first_presentation`; those unseen startup words remain motion-eligible.
    Actual reconnect/page-refresh history stays `_replay` and settles directly.
  * **Next studio motion is independently phased, never one canned keyframe.**
    `.word-glyph` owns size/lift, `.word-ink` owns separate weight and width
    envelopes, and `.caption-character` owns the local
    hand-off. The conservative semantic `delivery_profile` remains diagnostic;
    a separate `data-motion` family lets trustworthy continuous contour, flow,
    force/attack, or texture choose rising, falling, sustained, forceful,
    gentle, or textured timing without making an emotion claim. Each family
    owns both a glyph path and its own weight/width intonation clock. Every CSS
    family starts near the baseline
    (`opacity >= .66`, scale >= .975), uses the zero-slope
    `cubic-bezier(.42,0,.22,1)`, and rises to its own early/middle/late crest;
    falling/forceful must never start already at peak displacement. Character
    handoff uses a still-subordinate 0.085 em / 3% ribbon;
    keep its upward-only, zero-slope path so it cannot become a second ziggle.
    **The word wrapper freezes its resting layout width before paint, IN em —
    never in px.** (Fixed 2026-07-30.) The freeze exists so the animating
    weight/width axes cannot reflow the row, but the stage font-size is
    `min(clamp(20px, 16cqh, 64px) * --caption-scale, --caption-width-cap)`, so a
    pixel box goes stale the
    instant the window is resized or the Caption scale slider moves: the glyphs
    re-render at the new size against the old box. Measured at scale 1.8, every
    word spilled its own box — 15px on "a", 43px on "tab" — and the words
    overlapped each other. Glyph advances are linear in font-size and the word
    inherits the feed's size at 1em, so an em width tracks them exactly and never
    needs re-measuring; max spill after the fix is 0.9px (sub-pixel slack). A
    change of FACE, not size, would still need a re-measure, but the caption font
    is locked before the first word arrives. Measure with
    `getBoundingClientRect().width`, not `offsetWidth`, which rounds down and
    clipped the last letter of every word the previous time this was done in
    integers. A descendant's transform never affects the wrapper's own border box,
    so reading it mid-motion is safe.
    All four channels return to identity/Regular 400/100% width, and only the
    wrapper animation calls `completeMotion()` to release the reveal queue.
    The stage resting size is `min(clamp(20px, 16cqh, 64px) * scale,
    --caption-width-cap)` — measured **47.1px** at 1440×900 — with **1.38**
    line-height and `-.012em` tracking (raised 2026-07-30 from
    `clamp(18px, 2.65vh, 34px)`/1.14 when the light stage dropped the captions
    box, the frame, and the per-block speaker label). Leading is not decoration
    here: a word's transient lift reaches 0.25 em, so tight leading puts a
    moving word into the line above it. **Type size and
    `display.studio_stack_words_per_block` are one decision.** At this size
    eight words sat exactly on the wrap boundary, so a verifier respelling that
    changed a word's width flipped a row between one and two visual lines and
    the whole stack below it jumped; six words leave ~25% slack and a
    correction lands in place. Re-check a full six-row stack at 1440×900 and
    390×844, with a long-word utterance, before changing either.
    **STAGE ROWS DO NOT WRAP (2026-07-30, at the user's request).** A Stage block
    is already a fixed-width row of six words, so a second visual line inside one
    block was a wrap accident that moved every row beneath it whenever a verifier
    respelling changed a word's width. `.caption-feed .caption-words` is
    `nowrap` + `max-width: none`; Transcript still wraps, because there viewport
    width legitimately chooses the visual lines.
    Two consequences, both load-bearing:
    1. **WORDS-PER-ROW AND TYPE SIZE ARE ONE CALCULATION (2026-07-30, second
       pass).** `min(clamp(20px, 16cqh, 64px) * scale, var(--caption-width-cap))`
       where `--caption-width-cap` is
       `93.6cqw / (--row-budget-em + --caption-gutter-em)`, with `.caption-stage`
       as a **`size`** container so both `cqw` and `cqh` track it. Without the cap
       `nowrap` does not wrap an oversized row, it CLIPS it.
       Holding words-per-row at SIX hands the caption size to the window's aspect
       ratio, and that was the whole bug. Measured: 1440×900 → 47px type, 86% of
       the stage filled; **862×998 → 23.6px type, 40% of the stage EMPTY**, because
       six words still had to cross a 538px stage. `planStageLayout`
       (`web/src/lib/stage-layout.ts`) now picks BOTH: the largest type whose stack
       still shows `display.studio_stack_min_rows` (10) rows, over
       `studio_stack_words_min`(3)…`studio_stack_words_per_block`(6). The narrow
       window gets **3 words at 35.8px and 91% fill**; 1440 keeps 6 at 47px. Both
       terms are load-bearing: maximise type alone and a wide stage collapses to
       three-word rows at the height ceiling using 65% of its width; require rows
       alone and you are back at 23.6px.
       **`rowBudgetEm` is `N*linear + spread*√N`, NOT `N * perWord`.** The per-word
       cost RISES as rows shorten — a short row cannot average a long word away.
       Measured by sliding a window over the recognizer's real word order: English
       worst-case rows are 10.82 / 12.92 / 15.26 / 17.60 em at N = 3…6, i.e.
       **3.61em per word at three but 2.93em at six**, so a constant fitted to
       six-word rows under-budgets a three-word row by 19% — which is exactly how
       the first attempt shipped rows that overflowed. Fitting N=3 and N=6 gives
       linear 1.31 / spread 3.98 and predicts the unfitted N=4/N=5 rows to within
       2%. Shipped +8%: **en 1.40/4.30, ko 2.20/4.35** (ko measured 12.73/16.50/
       18.50/21.53 em, +10% because that sample is only 65 어절). Do NOT budget by
       IID-sampling the word-width distribution: real text does not put three long
       words together at random, and sampling predicted 15.5em for a three-word row
       against a measured 10.8em.
       **Declare `--caption-width-cap` on `.studio-shell`, never on `:root`.** A
       custom property resolves its own `var()`s at computed-value time ON THE
       ELEMENT THAT DECLARES IT; only relative UNITS (`cqw`) stay unresolved until
       use. On `:root` it baked in `:root`'s `--stack-words: 6`, so React's
       per-stage override changed the row width and left the type at the six-word
       value — measured, three-word rows still rendered at 24.2px.
       Because the cap binds at 100%, **the Caption scale slider only reduces**
       (0.6–1.0): 100% is the largest type that still fits a full row.
    2. **THREE OF `.caption-feed`'s FOUR PADDINGS ARE CLIP GUTTERS, NOT SPACING.**
       `overflow` clips at the PADDING box, so a padding strip is room *inside* the
       clip that layout does not consume — the only way to keep a transform from
       being cut off without moving where the words sit. Current value
       `.40em 1.50em .66em .60em`:
       * **right** — clears the trailing orb, whose `right: -1.66em` positions its
         RIGHT edge, so that number is (clearance + the orb's own .82em width).
         Clearance is MEASURED: the last word's ink reaches −0.005em past the row
         edge at rest (p99) but **0.842em** while its scale channel is mid-motion,
         because scale grows the ink by (scale−1)/2 of the word's own width. At
         −.78em the orb's LEFT edge sat .04em INSIDE the row and the moving word
         ran straight over it.
       * **`.caption-feed .caption-words` must also be `flex: 0 0 auto`.** It is a
         flex ITEM of `.caption-surface`, so it inherited `flex-shrink: 1` and got
         squeezed to the surface width whenever the row was wider, while its own
         children (`flex: 0 0 auto`) refused to shrink and simply overflowed it.
         The orb then attached to the SHRUNKEN right edge — measured 84px on top of
         the last word — and every probe that measured this box under-reported the
         true row width, so an over-wide row read as fitting. Same failure as the
         earlier `max-width: none` fix (measured −19px overlap at 390px), arriving
         by a second route: the box has to hug its content for the orb to trail it.
       * **left** — a first-paint motion scales a word to 1.38 about
         `transform-origin: 50% 100%`, so the FIRST word of every row grows
         LEFTWARD past the row origin and Chrome clipped it mid-motion. This was
         the reported "when the word gets large it overflows on the left side";
         `padding-left` was 0.
       * **bottom** — the box hugs its content, so the newest row's bottom edge IS
         the content edge, and the Stage FLIP entry starts that row at
         `translateY(0.58em)`. Measured, the entering row and its orb were cut off
         for the whole 620 ms entry. Safe to spend: `flex-end` sends eviction
         overflow to the TOP, so the bottom strip is never used by it.
       * **top** — the same scale grows upward, plus up to .25em of transient lift,
         which exceeds the 1.38 line box's leading.
    Verify all of this with the CDP probe, not by eye: sweep theme × 1440×900 /
    390×844 × scale, and assert wrapped rows 0, no glyph past ANY edge of the clip
    box while motions are active, and the orb neither clipped nor overlapping the
    last word. Drive the theme through the real settings toggle, not by stamping
    `data-theme` on the DOM — the latter bypasses `useStackCapacity`.
  * **Diarization must consume speech, not synthetic verifier slots.** A
    verifier-confirmed post-punctuation suffix whose claimed slots are quiet
    while stronger speech follows is moved onto the first substantial activity
    cluster by `repair_verified_tail_timing`; later sound-effect islands are
    excluded. Short turns below the normal ERes2Net cosine threshold may match
    only an already-stable profile and only above
    `short_stable_min_margin`. Do not “fix” this by lowering enrollment
    thresholds globally.
  * `motion.live_sync.enabled: false` still settles words directly. Do not feed
    the full authored `closed_caption` response into live: accumulated live
    words require the compressed range documented in `config.yaml`.
- **Input gain applies only to the recognizer's copy of the audio.**
  `AudioChunk.samples` must stay at the true captured level because prosody
  measures `loudness_db` from it; the gained copy is `asr_samples`. Gaining
  before that measurement would flatten whisper and shout to one size.
- **The voice circle is continuous audio state, not another caption effect.**
  `_realtime_voice_features()` estimates F0, autocorrelation periodicity, and
  spectral centroid from each true ~64 ms capture block. `level_event()` sends
  those with RMS. The line-edge `.intent-circle` (legacy) /
  `.line-voice-orb` (Next) sits immediately after the active caption and maps
  radius=volume, bead height=F0, oval width=brightness,
  opacity/halo=periodicity. **It has to be big enough to READ those three
  channels (2026-07-30).** At `.52em` it measured 20.9px across on a 37px
  caption, which put the F0 bead under 4px and the periodicity ring under 1px —
  the instrument was present and unresolvable, which is what "the small sphere
  isn't readable" meant. It is `.82em` now (~28–42px, bead 22%), and its resting
  opacity went .34 → .52 because a .34 circle on the light stage reads as a
  smudge rather than a readout. Rolling delivery force/attack/contour/flow/texture
  also tilt/stretch the line orb and shape the compass's inner resonance;
  `delivery_profile` is a descriptive acoustic readout, not an emotion
  classifier. The side-grid `.voice-compass` mirrors them at a
  larger scale and reserves direction for `direction_deg`/`azimuth_deg`.
  Current mono input must say `awaiting array`; never fabricate direction. The
  compass carries **no `front` label** (removed 2026-07-30): with direction
  reserved there is no bearing to orient, so the word was labelling an axis the
  instrument does not yet report. The rail's `DIRECTION / Awaiting array` readout
  is what states that.
  Keep these signals outside glyphs; completed captions must never shake
  because a later audio block arrived. Do not infer or label emotion.
- **Korean caption motion requires the local variable font.** Roboto Flex has
  no Hangul outlines. `scripts/fetch_font.py` downloads the OFL
  `assets/NotoSansKR.ttf`; Python serves it at `/NotoSansKR.ttf`, and
  `[data-language="ko"]` uses its real `wght` 100–900 axis. A static system
  fallback is only degradation for a missing download, not the intended Korean
  rendering. Pitch-driven weight must still return to 400 after the one motion.
- **Speech emotion/intention is research-only.** SenseVoiceSmall is the first
  Korean-capable rolling-window candidate and emotion2vec+ base is its
  benchmark challenger; neither is installed or loaded now. Before adding one,
  benchmark Korean macro F1/confusion on KEMDy20 + booth audio, local RTF, and
  its model license. Freeze a smoothed estimate only onto future/unseen words.
  Never use an utterance-end result to animate or reweight historical words;
  that recreates the late-motion defect. See `docs/RESEARCH.md`.
- **The onset sidecar owns a provisional prefix, not durable spelling.**
  `PhonemeOnsetDetector` advances one confidence-gated phone at a time on the
  authoritative first slot (`H → He → Hel`, always `uN:w0`). Extensions require
  repeated compatible observations. Timing keepalives set `sustain_active` and
  grow only the bounded paint-on trail after the final known character.
  Nemotron/Parakeet replace that same node; no onset event enters
  `live_events.jsonl`, and no prefix revision may replay motion.
- Offline stages must stay independently runnable via their subcommands,
  reading/writing JSON intermediates in `--out`.

## Seeing the page (do this before judging visuals)

Headless Chrome can screenshot the live stage — never tune motion/typography
blind again:

```bash
.venv/bin/python -m autocwi live --sample --no-open &
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --window-size=1440,900 --timeout=15000 \
  --screenshot=/tmp/cwi.png http://127.0.0.1:7337/
```

For motion acceptance, attach the browser immediately—before sample words
arrive—then wait for `audio source finished` and for the sequential queue to
drain. Inspect `window.__cwiRenderDiag.report()` plus computed DOM styles; a
single screenshot taken afterward proves resting layout, not the animation.
The 2026-07-24 standard-sample run recorded 51 first-paint motions, 56
sequential reveals, maximum 2 simultaneous motions, zero restarts/overlaps,
and no queued, moving, or non-normal-font words at the end. See
`docs/TESTS.md` for the observed expressive ranges.

Use `--timeout`, NOT `--virtual-time-budget` (SSE never idles — it hangs).
`--dump-dom` exposes per-word classes/inline styles for debugging. Note rAF
does not run reliably in headless: time-based animations may appear frozen
mid-flight in screenshots (the 1.5 s self-heal sweep exists because a stalled
rAF chain froze syllable fills at --fill 0% = solid white words).

The default root is the Next studio when `web/out` exists. Use `/?demo=1` for
a deterministic UI-only two-speaker/voice-signal preview and
`window.__cwiStudio.report()` for its queue summary. Use `/legacy` plus
`window.__cwiRenderDiag.report()` when diagnosing the original frame-level
motion engine. Review both 1440×900 and a narrow 390×844 viewport; mobile may
wrap at word boundaries, and desktop paragraphs must wrap too. One ASR
utterance/speaker turn is one semantic paragraph; viewport width—not an
words-per-row constant—chooses its visual lines.

## Gotchas

- `HF_TOKEN` env var required for real diarization (pyannote weights are
  gated; user must also accept terms on `pyannote/speaker-diarization-3.1`
  and `pyannote/segmentation-3.0`). Without it, use `--stub`.
- Whisper models auto-download on first use (`small` ~460 MB, `base.en`
  ~145 MB). CTranslate2/faster-whisper runs CPU-only on Apple Silicon
  (int8); MPS is used by pyannote/torch only.
- Live `fast` mode uses the local 1120 ms English Nemotron 0.6B profile under
  `assets/streaming-nemotron-en-1120ms/` for accurate read-ahead/cues/commits,
  plus Parakeet Unified for durable endpoint text. The 160 ms profile is loaded
  only by explicit `display.mode: readahead`; running it behind fast mode while
  hiding all its output caused avoidable decoder backlog. Use `--whisper MODEL`
  only for the legacy pause-segmented comparison path.
- Korean uses `assets/streaming-zipformer-ko-174m/`, the 2026 174M causal
  Zipformer chunk-16 int8 export (320 ms model chunk; KsponSpeech + AIHub,
  ~6,500 h). Its leading-space tokens preserve 어절 boundaries and timed
  pieces. `verifier_enabled`, `draft_enabled`, and the English TIMIT
  `onset_prefix` are false in the `ko` overlay. The older online model measured
  11/76 character errors on the bundled Korean set; this model measured 0/76.
  Do not pass Korean through English sidecars or overwrite it with the weaker
  2024 Korean endpoint model. Korean typography is
  `assets/NotoSansKR.ttf`, not the previous static system-font stack.
- Apple-Silicon live diarization uses
  `native/sortformer/.build/release/autocwi-sortformer` plus
  `assets/sortformer-coreml/`. The Swift package is pinned to FluidAudio
  0.15.5; `scripts/fetch_streaming_model.py --sortformer-only` builds it and
  precompiles/downloads the palettized model. Intel macOS, Linux, a missing
  helper, or a failed native startup must degrade to the ONNX embedding path
  without aborting captions. Sortformer owns provisional timing, not durable
  identity. Its direct cache has four slots; the fallback is configured for six.
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
- **Two independent measurements, and each fails where the other works.**
  Per-glyph TRACKING is clean but breaks on a word that swells past 3x (its
  glyphs merge and grow, violating the association gates) or is short enough
  to segment as one run. Per-frame, spatially attributed measurement survives
  both but smears at word boundaries. Take the tracked curve by default, the
  framed one where tracking produced nothing or under-read by >15%.

- Live mode: pre-capture English/Korean selection + confidence-aware speaker
  attribution. English uses its three-stage ASR path; Korean uses the
  authoritative 174M chunk-16 online Zipformer and finalizes directly at its
  endpoint.
  Speaker observations now move through unknown/provisional/stable/corrected;
  gated enrollment, EMA centroids, ambiguity checks and switch hysteresis keep
  short/noisy turns from forcing IDs. Stable `word_id`/revision metadata lets
  endpoint or later profile evidence recolor an existing word in place, and
  only stable/corrected attribution may raise speaker-change haptics. The
  1120 ms accurate stream provides provisional read-ahead/cues/commits, while
  modified-beam Parakeet endpoint verification alone owns durable/haptic SSE
  words. Explicit readahead mode additionally merges the 160 ms white draft.
  The
  deterministic benchmark is 0/77 clean and 7/308 across the stress matrix.
- Offline renderer and burn-in were **removed** (live page is the renderer);
  offline pipeline ends at `spec.json`.
- Offline pyannote diarization never yet run (needs HF_TOKEN). Live attribution
  now uses native Streaming Sortformer v2.1 for provisional timing plus local
  int8 pyannote segmentation and language-specific 3D-Speaker identity
  embeddings at endpoints: ERes2Net for English, multilingual CAM++ for Korean.
  On the target Apple Silicon machine the cached native model processed the
  34.5 s English sample in 4.01 s (8.6× real time) and the 13.3 s Korean sample
  in 1.50 s (8.9×). The browser acceptance retained only S1/S2 for the English
  dialogue; all 14 Korean sample word IDs settled to stable S1 at endpoint.
- Syllable variation (CWI 2.2.4) is live: a colour wipe over already-visible
  text, gated by `motion.syllable_fill` to drawn-out words (~7% of words).
  Never make it a typewriter reveal — progressive appearance destroys the
  read-ahead in 2.2.1.
- **THERE IS EXACTLY ONE BENCHMARK: `scripts/benchmark.py` on FLEURS.** Do not
  add a second. FLEURS (Conneau et al., 102 languages, CC BY 4.0) is the
  standard multilingual ASR set and the one published Korean/English numbers are
  measured against, so a score is comparable to the literature. Fetch it once
  with `scripts/fetch_fleurs.py`; `--stress`/`--quiet-sweep` are *conditions on
  that set*, not separate benchmarks. Removed 2026-07-30: `benchmark_streaming.py`
  and `benchmark_asr.py`, which overlapped and scored the sherpa model's own
  3-clip demo audio (circular; one edit moved it 1.30 points).
  **Never quote `0/77 clean` — that number came from the vendor's demo clips.**
  Recognizer choice is still measured, not assumed: the 2026-06-11 Nemotron 3.5
  A/B'd worse on English (3.25% vs 2.27%), so English stays on the 2026-04-25
  model. Re-run that A/B on FLEURS before swapping any checkpoint.
- **MEASURED 2026-07-30: Korean is ~12.5% CER, not ~0%.** 44/351 chars on 8
  FLEURS ko_kr clips; the ~0% came from one easy bundled clip. Much of it is
  **number formatting** (it writes `2011년` as `이천십일년`) — a convention, not an
  error, which will rig a provider A/B toward whichever backend matches FLEURS'
  style. **Write a shared text normalizer before comparing providers.**
- The benchmark scores **timing as well as text** — a backend with better words
  and worse spans is a downgrade here. It reports onset-gap distributions
  (FLEURS ko: median 520 ms, p10 320 / p90 920; conversational English
  sample.mp4: median 160 ms) and pairwise onset agreement. FLEURS carries no
  word alignment, so these are distributions, not accuracy.
- **A language flag alone does not switch languages.** Setting `live.lang`
  loaded the ENGLISH models and transcribed Korean as "Terrika" at 100% CER.
  `_configure_live_language()` is what swaps `streaming_model_dir` and disables
  the `draft`/`verifier` English sidecars.
- **`assets/sample.mp4` has NO reference transcript**, so it cannot be scored —
  only compared across backends (`benchmark.py --audio`). Do not derive a
  reference from a model's own output; that is the circularity the bundled sets
  already suffered from. It is still the most booth-like audio in the repo
  (34.5 s, conversational, two speakers, 59 durable words, S1/S2).
- **Collapse word revisions by `word_id` when consuming SSE events.** A word is
  re-emitted under the same id when endpoint text or later speaker evidence
  revises it. Counting every `type: "word"` event duplicated whole phrases on
  sample.mp4 the moment diarization was enabled (59 → 64 words, "You know where
  1640 River?" twice). See `collapse_revisions()` in `scripts/asr_backends.py`.
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
- **`size_pct` below `mapping.loudness_to.min` silently kills the quiet half of
  the loudness channel.** `towardBaseline` computes `extent = baseline - min`
  for values under the baseline; if the resting size is below `min` that is
  negative, the `extent <= 0` guard fires, and EVERY quiet word returns exactly
  the baseline. Lowering `size_pct` to 2.8 (below `min: 3`) did this. Fixed by
  rescaling the range by `size_pct / baseline` in BOTH `typeOf` (JS) and
  `ccprosody.forward` (Python): CWI's anchors are ratios around its baseline
  and only read as absolute percentages when the resting size IS that baseline.
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
- **The reference-replay regression test already exists** —
  `test_derived_reference_specs_replay_the_recordings` in `tests/test_live.py`,
  NOT `test_reference.py` (which only covers Python↔JS forward-map parity). It
  loads the four checked-in specs and never decodes a video. Do not add a second
  one; it already asserts caption-line reconstruction, monotone non-degenerate
  timings, ≥3 distinct loudness values, and ≥70% of words carrying equal-length
  measured motion arrays.
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
- **SYNCHRONIZATION COMPOSES WORD AND CHARACTER GEOMETRY.** The PDF's base
  elevation/pop belongs to the word event and remains on the wrapper. But the
  website recording is unambiguous at frame level: the `i/s` split and the
  moving letter inside “spoken” occupy different baselines inside one word.
  The renderer therefore adds a wait-aware character crouch/lift/pop around
  each letter's own colour-turn time. A held first letter may rise farther;
  fast intra-word turns use `wave_hold_floor`, preventing the full held-pause
  amplitude from becoming a stutter on every character. Intonation size and
  weight remain uniform across the word. Every character transform is
  explicitly reset to `none` at rest.
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
- **The config now has room for the real range** (it did not before): `cc`
  overrides `size_response: 1.0` (uncompressed), `quiet_deformation: 1.0` and
  `emphasis_deadband: 0.05`, reachable emphScale **0.88..2.20** (2.83 at a low
  median) and emphWght **200..900**. Before this the ceiling was 1.43 and the
  quiet side was entirely inside the deadband, so "louder" clamped and
  "softer." could not shrink at all however quiet it measured.
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
  but with Ease High/Low set, while the website resolves the hand-off on
  character spans. So "alphabet-level motion" and "word-level sync" are
  composable scopes, not competing interpretations;
  `closed_caption.sync_granularity` switches the turn timing and live uses the
  alphabet appearance within its active word.
- **THE CAPTION INVARIANT: a word that has been shown must stop changing once
  its MOTION WINDOW passes.** (Refined 2026-07-24 for expressive live motion.)
  A word animates through one 520–720 ms first-paint transient and returns to
  **its own settled typography**. During that window only its own `transform`
  may change; `font-size`, the variable-font axes, line geometry, and earlier
  words stay fixed. Speaker colour has an independent clock and may sweep during
  motion or write directly afterward.
  **REST IS NOT UNIFORM (2026-07-31).** A word rests at the size/weight/width its
  own voice earned (CWI 2.3 — see the PDF entry above); "returns to rest" means
  `transform: none`, not Regular 400 at width 100. Resetting every word to
  identical typography is exactly what erased the voice. The settled values are
  computed once from the frozen prosody, so they cannot change afterwards and the
  invariant holds by construction.
  Verification may add/remove/respell words and recolour them, but
  it may never start a second motion. Enforced by: server
  freezes `loudness`/prosody per time SLOT in `prosody_cache` (key
  `("§slot", utterance, round(start*20))` — text-keyed missed exactly when the
  verifier respelled), and freezes force/attack/contour/flow/texture separately
  in `delivery_cache` on the first event even during cold-start calibration;
  page's `typeCache` is first-write-wins and geometry is
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
  it lands on CWI's 5% baseline; (c) wrapped flex boxes created multi-row
  captions and verification overlaps, so each box is now `nowrap` and measured
  overflow moves an unseen word to a new box; (d) syllable fills froze at
  `--fill 0%` (solid white words) when the rAF chain stalled, so a 1.5 s sweep
  finalizes them.
- Type axes are anchored to the speaker's running baseline via `expression`
  in config.yaml. Mapping CWI's absolute anchors straight onto per-word
  acoustics made ordinary speech render as fabricated whispers/shouts (size
  swung 3.2x, weight 577). Do not raise `*_response` to 1.0 without re-checking
  that.
- A word's synchronization activation runs exactly once. `dataset.moved`
  guards re-entry, and endpoint/speaker verification never restarts it.
  `neighbor_bleed` is 0 and `live_sync.neighbor_push` is false; stacked live
  must not shift row-mates while somebody may still be reading them.
- `display.mode` has four settings (config.yaml). Default **`fast`** adds the
  accurate stream's own white tail (~35% less revision than the draft) to
  committed words. `stable` hides the tail and shows committed words only.
  `sentence`: turn-taking, split at the verifier's punctuation. `readahead`:
  adds the 160 ms draft — lowest latency, visible rewriting. Do NOT reduce
  `live.endpoint_silence_s` for finer sentences (WER 2.27%→8.77% at 0.6 s),
  and do NOT release the held-back trailing word early: measured, it saves
  nothing (fires with the endpoint) and commits truncated spellings — a lone
  word reaches the screen through fast mode's white tail instead.
- Live presentation is intentionally stacked: left-aligned text-hugging boxes
  fill downward from the top of the stage, and product Stage is always bounded
  to fixed-width
  rows. Older rows remain in Transcript; do not let them accumulate behind
  the active caption. The line-edge voice circle is on: volume changes its outer radius,
  F0 moves the bead vertically, and periodicity/brightness shape its restrained
  inner texture. It follows the active speaker line without entering the
  glyphs. A larger Voice Compass mirrors those channels in the side grid and
  reserves its direction marker for future 2+ microphone
  `direction_deg`/`azimuth_deg`; mono must display `awaiting array`. A
  provisional/stable/corrected speaker change or a new ASR utterance starts a
  separate semantic paragraph in Transcript. Stage row geometry ignores
  diarization and utterance segmentation and follows immutable semantic word
  order, so pending attribution, late speaker churn, or provisional utterance
  boundaries cannot create one-word rows. Never rebuild the words:
  their first-paint motion clock must survive the partition.
- Endpoint verification reconciles PER WORD: matches corrected in place,
  deletions dropped, insertions (usually the one endpoint-held word) added at
  their spoken position via the normal word path. Never tear an utterance down
  and re-render it — the newest word is held back from committing until the
  endpoint, so a structural mismatch fires on almost every utterance, and a
  block rebuild makes each sentence flash discretely at every pause (a full
  `rack.replaceChildren()` even wiped the transcript).
- Live paint is also PER WORD and PER FRAME. `text_revision_id`,
  `timing_revision_id`, `speaker_revision_id`, source authority, finality, and
  SSE id feed `live_render_core.js`; a bounded map coalesces bursts before one
  `requestAnimationFrame` flush. `level` owns a separate meter/voice-circle
  frame.
  Ordinary updates never replace a word/line/stage, and replay payloads
  reconstruct state without replaying motion. Inspect locally with
  `display.debug_render`, `window.__cwiRenderDiag.report()`, or
  `scripts/live_render_probe.py`.
  **LIVE MOTION BELONGS TO FIRST PAINT (updated 2026-07-24).** Unlike `cc`,
  live cannot move a word before ASR has created it. `renderReadAhead` therefore
  starts each word's one §2.2.3 pop at its earliest real DOM appearance.
  `dataset.moved` makes that activation once-only. The later onset cue, commit,
  verification, and speaker correction are colour/text-only and can never
  start or restart geometry. A decoder batch is revealed in timestamp order,
  using a 140 ms base gap blended with bounded 80–260 ms acoustic onset gaps,
  bounded by the configured concurrency. Preserve the planned reveal deadline and its
  60 ms catch-up floor; using `now + gap` at each start accumulates latency.
  A current word waits hidden for a free slot instead of skipping its motion.
  Each motion lasts 520–720 ms and returns
  naturally rather than being snapped so a third word can start. Colour
  received while queued is held until first paint; colour received while moving
  begins its sweep immediately without changing geometry. Verification keeps
  unseen replacements queued and preserves an in-flight clock. Endpoint words
  that have never been visible still receive first-paint motion; only historical
  replay/correction insertions settle without it.
  * **The per-character slide-in entry is OFF by default** (`character_entry_
    enabled: false`) — cc has no such effect; it was a live-only addition and is
    the other thing that read as extra motion. Set true to re-enable.
  Never restart the pop for text, speaker, timing, commit, or verification
  revisions; replay and reduced-motion records settle directly.
- Live speaker attribution (CWI 2.1) is hybrid. On Apple Silicon the native
  FluidAudio/Core ML conversion of NVIDIA
  `diar_streaming_sortformer_4spk-v2.1` supplies continuous provisional timing
  with the official 1.04 s context. The 1.5 MB int8 pyannote segmentation model
  plus a full-turn 3D-Speaker embedding verifies endpoint identity, recovers
  quiet speech, and supports the configured six identities beyond Sortformer's
  four direct slots. English uses the 25 MB ERes2Net model (~66 ms measured);
  Korean uses the 27 MB multilingual CAM++ model (~32 ms vs ~90 ms ERes2Net on
  held-out Korean spans). Score Sortformer overlap by activity, not duration.
  S1/S2 may remain arrival-ordered and provisional for latency. Never expose
  unmapped higher native slots directly; S3…S6 embedding identities require
  repeated clean endpoint observations, after which prior neutral words are
  revised in place. Attach only endpoint-verified additional slots to the
  durable S1… namespace; a short
  phantom native slot must merge back to the embedding identity rather than
  creating a one-word speaker paragraph. On unsupported platforms, native
  startup/model failure must fall back to embeddings without aborting capture.
  Offline pyannote 3.1 should separately move to
  `speaker-diarization-community-1` after isolating the pyannote 4.x dependency
  and gated model download. Details and primary links are in
  `docs/RESEARCH.md`.
- Haptic hardware module: not started; it should subscribe only to final
  `type: "word"` events at `/events` (live) or read `spec.json` (offline).
  Durable words carry optional `speaker_change`/`emphasis` salience flags
  (threshold `haptics.emphasis_db`) — actuate on those, never every word
  (see docs/RESEARCH.md for the grounding).
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
- **Reference-spec derivation and the .aep provenance live in a skill now.**
  Everything about re-deriving `assets/reference_specs/*.json` from
  `docs/reference/*.mov` — the crop-by-colour method, the guide-rule/playhead
  erasure, scroll recovery, glyph->word assignment, the ink-density weight
  measure, the reproducibility run — plus the After Effects template analysis is
  in `.claude/skills/derive-reference-spec/SKILL.md`. It is ~18k characters of
  method that only matters when you are actually re-deriving or re-litigating
  where a motion number came from, so it loads on demand instead of every
  session. Invoke it before touching that pipeline; do not re-derive from
  scratch.
