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
.venv/bin/python scripts/studio_probe.py --samples 40  # read-ahead + motion (CDP)
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
- **THE PLAYHEAD. READ THIS BEFORE TOUCHING LIVE MOTION.**
  Captions are presented from a clock running `display.read_ahead_delay_s`
  (**1.2 s**) BEHIND the acoustic clock. That is what makes this a CWI renderer:
  CWI 2.2.1 needs the line on screen before it is spoken, and a live recognizer
  cannot produce text early — but ASR delivers a word ~0.6 s AFTER it was
  spoken, so colouring only up to `now - 1.2 s` leaves real, recognized,
  still-uncoloured text ahead of the colour. Nothing is predicted.
  **THE DELAY IS THE LAG, ONE FOR ONE.** A word's turn and pop happen at
  `onset + delay`. Shipped at 2.5 s first; the user's verdict was "motion should
  be real-time... motion applies after the determination of speaker", and both
  halves were right — MEASURED, a word's TEXT arrives at a median 0.62 s but
  durable speaker attribution at 4.48 s, so at 2.5 s the word popped NEUTRAL and
  took its colour ~2 s later. 1.2 s clears the text latency and reads as
  synchronized. Read-ahead is thin there (median 0-1 words) and that is the
  trade. Do NOT gate the turn on attribution: it must happen on time in whatever
  colour is known.
  `web/src/lib/caption-clock.ts` is the clock, and is pure. It recovers acoustic
  time from `level.t` (~64 ms cadence, same timeline as `word.t`) with a
  **max-filter plus 5 ms/s decay**: jitter can only make a sample look late, so
  the truth is the maximum. Word events are NOT a clock source — they are
  replayed to every new connection and an old timestamp reads as a restart. A
  backwards jump over 1.5 s IS a restart (`--sample --loop`): the clock snaps
  and bumps `epoch`, and **words under an older epoch must settle, never be
  re-derived** — recomputing puts them in the future and a full stage of read
  captions turns white again.
  **ONE `animation-delay` DRIVES THE WHOLE CAPTION.** `--turn-delay` is how long
  until the playhead reaches a word's onset; the 2.2.2 turn, the 2.2.3 pop and
  the 2.3 phase all take it, so the BROWSER schedules them. No JS timer, no
  per-frame work, no reveal queue at all (no slots, gaps, catch-up, backlog
  ceiling or watchdog — all of it existed to guess a moment the recording knows).
  * The colour keyframe has **no `to`**: an omitted endpoint animates toward the
    element's own computed value, so one rule yields speaker hue, neutral, or
    the receded provisional mix, and a late correction lands as a direct write.
    `backwards` fill paints the read-ahead during the delay.
  * `animation-fill-mode` stays `none`. A word delivered after its own onset
    gets a delay negative enough that the browser treats it as finished, so it
    paints settled. History needs no branch.
  * **Write `--turn-delay` imperatively, never via the `style` prop** — React
    reapplies that prop every render and rewriting `animation-delay` SHIFTS a
    running animation. `data-armed` on the node separates a re-render (leave it
    alone) from a genuine remount (re-derive against the new origin). The turn
    moment is `onset - clockOffset + delay`, with no reference to "now", so a
    remount recomputes the same answer.
  **NO CATCH-UP SLEW.** The server blocks ~1.3 s at each endpoint, and the
  obvious theory — source floods its queue, max-filter swallows it, playhead
  skips — was implemented and measured: late words 13 with the cap and 13
  without. `newest - playhead` sits at a steady 1.22 s, goes negative during the
  stall, returns to 1.22 s. The words stop; the clock does not. Removed rather
  than shipped unmeasured.
- **Stage is a stable caption stack, not a second live-text panel.**
  `selectStableCaptionStack()` flattens revisable speaker and utterance
  partitions into fixed-width rows of **as many words as the stage can carry**
  (`planStageLayout`, bounded by `display.studio_stack_words_min`…
  `studio_stack_words_per_block`) and retains **as many rows as the stage can
  actually hold** without
  hiding recognized provisional words — including the read-ahead words the
  playhead has not reached, which are exactly what the viewer is meant to read
  early. Transcript keeps complete turns and speaker/utterance partitions.
  **There is no concurrency cap any more** (`max_simultaneous_reveals` is dead):
  each word pops at its own recorded onset, so overlapping pops during fast
  speech are the design system working, not a scheduling failure. Measured on
  the bundled English sample, peak simultaneous motions is **4**.
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
  **ROWS NEVER MOVE ONCE LAID OUT.** Rows were chunked by INDEX, so row
  membership was a function of how many words preceded a word — the verifier
  deleting or inserting ONE word anywhere earlier shifted everything after it
  and re-flowed the stack, rearranging text the viewer had already read. (It is
  also why `rearmedWords` measured 53 of 64.) Two parts, both needed:
  * **Row starts are anchored to word ids** (`StageMemory.starts`): once a word
    starts a row it keeps starting that row, so an earlier edit cannot pull
    words across a boundary. A row that would overrun capacity opens a new
    anchor there — capacity still wins, because `--row-budget-em` is sized for
    `wordsPerRow` and `nowrap` CLIPS an over-long row. A one-word row is the
    acceptable cost.
  * **A late word may only APPEND, never insert.** Anchors alone still let an
    insertion lengthen its row and push the tail out: measured live, the
    verifier turned "Something without" into "Give me something without" and
    `[it, Look, just, Something, without]` became
    `[it, Look, just, Give, Something] + [without …]`. A word the stage has
    never placed, whose onset falls behind the furthest word it HAS placed, is
    not shown — it stays in the model and in Transcript. Appends are untouched,
    so a word arriving late after the endpoint stall still appears.
  MEASURED: already-read words changing row 7 -> 3 (anchors) -> **0** (append
  rule). Hold the memory in lazily-initialised STATE, not a ref: the chunker
  reads it during render, which `react-hooks/refs` forbids for a ref.
  Guards that refused deletions/insertions in the REDUCER were tried first and
  measured 7 vs 7 — no effect, because settled words are already `final`, which
  that branch never deletes. Reverted rather than shipped unmeasured.
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
- **THE MOTION SYSTEM, IN FULL.** The PDF describes exactly three things and
  the studio implements exactly those. `docs/cwi-design-system-v1.0.pdf`
  pp.26-41 — and READ THE PICTURES, not only the prose: they are what settled
  most of the arguments below.
  1. **2.2.2 colour turn** — the word takes its speaker colour at its spoken
     onset ("when 'In' is spoken, not when 'ble' is").
  2. **2.2.3 motion** — "a **15% increase in type size** before returning to its
     original size". Constant on every word; a shout and a whisper get the same
     cue. Amplitude is INTONATION, a different scope — collapsing the two is
     what produced every wrong model here.
  3. **2.3 intonation** — volume -> SIZE (2.3.5/2.3.6: 5% baseline, 3%..12%),
     pitch -> WEIGHT (2.3.8: 160-200 Hz is Regular 400, a BAND not a pivot;
     2.3.9: 80 Hz heavy, 250 Hz light), harmonics -> WIDTH (2.3.10's diagonal:
     heavy goes with wide, light with condensed).
  * **THE WORD GROWS FROM ITS BASELINE. IT DOES NOT MOVE.** Wrong three times.
    Method that works: crop a popping word WITH a static neighbour and draw the
    baseline guide from that neighbour **per frame** — the reference re-fits its
    line while a word swells, so one guide from the first frame drifts and
    manufactures a rise. Done properly, `intonation.mov` shows "louder" at ~4x
    its neighbours with its ink bottom exactly on the shared baseline.
    So: no `translateY`, AND no box-bottom pivot. `transform-origin` is
    `50% calc(100% - var(--glyph-baseline-em))`, measured off the live face by
    `useGlyphBaseline` (**.3799em Roboto Flex, .2598em Noto Sans KR**). It
    cannot be a constant: two bad probes both returned an IDENTICAL number for
    the two fonts, and that equality is the bug signal. One omitted the
    `.caption-words` wrapper (so it read `line-height: normal`), the other
    parented to `document.body` (so it never inherited the Korean face).
    The diagram's "25% elevation" is just where the TOP ends up.
  * **2.3 IS PER CHARACTER.** p.34 sets "Put that coffee **dOWn!**" under its
    own waveform; p.38 varies weight across "neeee**eeeed**"; p.40 ramps one
    sentence black -> hairline. One value per word cannot express any of it, and
    `_prosody()` was computing the contour and discarding it with `np.median`.
    `_intonation_envelope()` keeps 8 readings across the word's own audio
    (`display.intonation_envelope_samples`), loudness through the SAME 2.3.5
    pivot as the word-level value. `characterVoiceTypes()` samples it per
    character and reuses the existing anchor functions unchanged.
    Split with `Array.from`, never `split("")` — Hangul syllable blocks.
    The slot cache fallback must match on SPAN as well as proximity: a slot is
    50 ms, and a 0.02 s "You" inherited the envelope of the 0.72 s "know".
  * **ONE PHASE PER WORD DRIVES EVERY CHARACTER.** `@property --voice-phase` is
    animated once on `.caption-word`; each character computes
    `calc(1em * (1 + phase * (charScale - 1)))`. Per-character animations do NOT
    work: `animation-delay` counts from when the animation was applied, and live
    words GROW as a hypothesis extends, so a span appended later ran behind its
    neighbours — measured, half a Korean word sat at rest while the other half
    was at its crest and the reservation under-read by 23px.
    `.character-sizer` applies the same interpolation times the 2.2.3 pop, so it
    tracks the visible curve at EVERY phase, not just the peak. Glyph-past-cell
    0.0px both languages (was +18px en / +23px ko).
  * **THE PUSH IS THE MOTION.** The reference's dominant motion is what a word
    does to its NEIGHBOURS — `intonation.mov` frames 352->396, the line re-flows
    around "louder". Look at the neighbours, not the word. The visible glyph is
    out of flow and moves nothing, so the push comes from the in-flow
    `.character-sizer`: the grid track is max(normal, crest), and growing the
    crest grows the cell, which flex turns into a shove. Identical at phase 0,
    so a settled row is exactly as wide as its words.
    `motion.live_sync.neighbor_push` stays false — that flag is the LEGACY
    renderer's.
  * **RETURN-TO-NORMAL.** Every word begins and ends at 5% / Regular 400 /
    width 100. The PDF's static pages show voice type persisting; the recordings
    show it returning (`intonation.mov` frames 440-540) and the user chose
    returning. `voice_scale_range` [0.72, 1.62] at response 0.62; with the 1.15
    pop the largest crest is 1.86x. It was [0.90, 1.20] — a 1.33x span against
    2.3.6's specified 4x — and that crush is what read as "no feeling".
  * **LEADING: 1.38, and the arithmetic that said otherwise was wrong.**
    `lineHeight >= capHeight * maxScale + descent` predicted 1.56, cost 4px of
    type, and bought ONE pixel: forcing the true 1.863x crest measured a 10.5px
    gap at 1.38 vs 11.5px at 1.58. Line-box geometry cannot answer this — a
    scaled box overlaps its neighbour long before any letter does, and that
    overlap grows WITH the leading. `scratchpad/ink_collision.py` reads pixels
    and is the real test; the box check in `overflow.py` is informational.
  * **Duration** is all that survives of the old scheduler:
    `naturalMotionDurationMs` — 520 ms base, stretched by the spoken span and
    delivery flow, capped at 720 ms. Freeze it per word at mount.
  * **`cc` is the authored reference** and may drive the axes harder via
    `closed_caption` overrides (merge with `ccprosody.merged_expression()`;
    reading `cfg["expression"]` directly silently gets live's values). Its
    per-character wave, neighbour bleed and `Antecipate` lead are safe there
    because a caption plays through instead of accumulating.
  * **Reduced motion keeps the colour turn** and drops only the geometry:
    read-ahead and the onset turn involve no movement and are how a viewer knows
    which word is being spoken. Pin `--voice-phase: 0 !important` rather than
    cancelling the word's animation, which also carries the turn.

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
- **THE ONSET SIDECAR IS OFF (`live.onset_prefix.enabled: false`).** It made a
  speculative letter appear before the recognizer had a word (`H` -> `He` ->
  `Hel`) and reset after silence, so it fired at the START OF EVERY SENTENCE —
  reported as a hitch there. MEASURED: 39 text changes with it on, 14 from a
  1-2 letter stub, versus 23 and 0 with it off — ~40% of all visible churn.
  It is NOT the ~1.3 s sentence stall (1261 ms on, 1315 ms off).
  **Do not confuse it with CWI 2.2.1 read-ahead** — unrelated, and the confusion
  cost a round trip. Read-ahead is the design system's uncoloured preview of the
  line; this was a speculative first phoneme. Korean always had it off.
  If re-enabled: it owns a provisional prefix, not durable spelling; extensions
  need repeated compatible observations; no onset event enters
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
- **`autocwi cc` is the motion REFERENCE; live is no longer far behind
  (updated 2026-08-01).** With
  the text known in advance the full CWI system is exact: real read-ahead (a
  line legible in white before its first word), the colour turn sweeping
  through a word's letters over its spoken span, the `Antecipate` lead, and the
  travelling-wave neighbour bleed (safe here because a caption plays through
  instead of accumulating — which is why it stays off live). Playback is a pure
  function of `t`, so scrubbing back reproduces a frame exactly.
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
- **A JS syntax error takes the whole page down silently.** Twice a bad edit
  left an unbalanced brace and the only symptom was a probe reporting
  "built is not defined". Check first with an `onerror` handler injected before
  the cfg script — it reports the message and line directly.
- **A silently CONSTANT prosody column looks exactly like an unimplemented
  effect.** Twice the derived specs carried one loudness value (0.5) or one
  pitch (165 Hz) for every word, so the size and weight envelopes could not
  fire and the renderer appeared not to implement them. `test_derived_reference
  _specs_replay_the_recordings` now asserts >= 3 distinct values in each
  column. When a channel looks dead, check the DATA before the renderer.
- **THE CAPTION INVARIANT IS STRUCTURAL.** A word's colour turn is a fixed
  moment on the acoustic timeline, so text may be revised only while the word is
  still AHEAD of the playhead; behind it is frozen history. Enforced, not merely
  documented: `settledTextRef` records what a word wore when the playhead
  reached it and later revisions to it are dropped (spelling only — colour,
  finality and timing still update, because a late attribution correction is a
  direct colour write). Two traps, both hit: the single-word event path
  (`cue`/`commit`/`word` carry `text` at the top level) needs the same filter,
  and recording must happen ON THE PLAYHEAD TICK, because the reducer deletes a
  non-final word and re-adds it with the verifier's spelling. Measured on
  screen: coloured-caption rewrites 14 -> 0.
  Corrections never change a word's duration or axes: both frozen at mount.
  Replay needs no special case — replayed words land behind the playhead and
  settle. A capture restart is the one explicit case (see `epoch`).
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
  boundaries cannot create one-word rows. Rebuilding the words is now survivable
  rather than fatal — a remounted word re-derives the same absolute turn moment
  and resumes — but it still costs a re-arm per word, so avoid it.
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
  **LIVE MOTION BELONGED TO FIRST PAINT — NOT ANY MORE (2026-08-01).**
  This paragraph used to say "live cannot move a word before ASR has created
  it", and everything else followed from that premise: motion started at a
  word's earliest DOM appearance, `dataset.moved` made it once-only, batches
  were revealed in timestamp order through a 140 ms base gap and a concurrency
  cap, and a word waited hidden for a free slot. The premise was true and the
  conclusion did not follow. Live cannot move a word before ASR creates it, but
  it can move a word LATER than that — and delaying the playhead 2.5 s behind
  the acoustic clock means every word is created before its own turn arrives.
  So live now behaves like `cc`: motion is a function of the timeline, not of
  arrival. See the playhead entry at the top of this file. What survives is the
  Korean/legacy path in `livepage.py`, which still uses first-paint activation.
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
