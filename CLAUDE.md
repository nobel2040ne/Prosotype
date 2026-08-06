# CLAUDE.md — working notes for Claude Code sessions

auto-CWI ("Prosotype"): a local, offline pipeline that automates the
**Caption with Intention** (CWI) design system for Deaf/HoH viewers.
**Primary mode = live captions** (mic → CWI-styled captions in the browser,
English or Korean, selected before capture). The offline video pipeline is kept as the source of the
**CaptionSpec contract** that a future haptic device module will consume. See
`ARCHITECTURE.md`, and `docs/MOTION.md` for the motion contract.

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
.venv/bin/python scripts/fetch_fleurs.py --lang ko --count 120  # one-time eval-set download
.venv/bin/python scripts/benchmark.py --lang ko    # THE benchmark: text + word timing
.venv/bin/python scripts/korean_sweep.py           # KO chunk x decoding A/B (accuracy vs read-ahead)
.venv/bin/python scripts/fetch_streaming_model.py --korean-sweep # its chunk-16/64 exports
.venv/bin/python scripts/benchmark.py --lang ko --stress      # + noise/reverb/1.15x
.venv/bin/python scripts/benchmark.py --lang en --quiet-sweep # InputGain guard
.venv/bin/python scripts/benchmark.py --audio assets/sample.mp4 --lang en # score-free
.venv/bin/python scripts/benchmark.py --lang ko \
  --backends local,speechmatics,soniox   # provider A/B (UPLOADS audio; needs keys)
.venv/bin/python scripts/studio_probe.py --samples 40  # read-ahead + motion (CDP)
.venv/bin/python scripts/speaker_probe.py         # CWI 2.1: is the FIRST colour right?
.venv/bin/python scripts/caption_color_probe.py   # ...and does the WHOLE word wear it?
.venv/bin/python scripts/caption_color_probe.py --broken  # prove that check can fail
.venv/bin/python scripts/baseline_probe.py            # does a swelling word stay on its line?
.venv/bin/python scripts/baseline_probe.py --broken   # ...and prove that check can fail
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
  (**1.75 s**) BEHIND the acoustic clock, with a per-WORD floor beneath it
  (`display.min_read_ahead_ms`, **420 ms**) — see the entry after this one,
  because the delay alone does not deliver read-ahead. That is what makes this a CWI renderer:
  CWI 2.2.1 needs the line on screen before it is spoken, and a live recognizer
  cannot produce text early — but ASR delivers a word ~0.6 s AFTER it was
  spoken, so colouring only up to `now - 1.75 s` leaves real, recognized,
  still-uncoloured text ahead of the colour. Nothing is predicted.
  **THE DELAY IS THE LAG, ONE FOR ONE.** A word's turn and pop happen at
  `onset + delay`. Shipped at 2.5 s first; the user's verdict was "motion should
  be real-time... motion applies after the determination of speaker", and both
  halves were right — MEASURED, a word's TEXT arrives at a median 0.62 s but
  durable speaker attribution at 4.48 s, so at 2.5 s the word popped NEUTRAL and
  took its colour ~2 s later. Do NOT gate the turn on attribution: it must
  happen on time in whatever colour is known.
  **THE DELAY SETS THE MEAN LEAD AND NOTHING ABOUT ITS SPREAD, WHICH IS WHY
  1.2 s DELIVERED ALMOST NO READ-AHEAD (2026-08-03, user: "the feeling of
  awful comes from the timing").** Every per-word curve measured correct
  against the film — rise, overshoot, sustain, release — and the studio still
  read as wrong. MEASURED at 1.2 s: a word was on screen a median of **170 ms**
  before its own motion began, p25 **0 ms**, and **42% of words turned within
  100 ms of appearing**. They materialised already moving, so there was never
  a moment to read the line early, which is the whole of 2.2.1 absent nearly
  half the time.
  Raising the delay is not sufficient and 1.2 -> 1.75 s proves it: the median
  lead went 170 -> 700 ms while the stage still showed ZERO words ahead of the
  playhead in 11% of frames and one in another 18%, against 28 at p75. The
  recognizer blocks ~1.3 s at each endpoint and then releases a BATCH, so
  read-ahead arrives in bursts and a time delay moves the mean of that
  distribution without touching its variance.
  **The floor is therefore per WORD** (the user's suggestion: "intentionally
  adding a delay of about one or two words"). A word may not turn until it has
  been on screen `min_read_ahead_ms`, whenever it arrived — 420 ms is ~1.6
  words at the measured 262 ms speech rate. AFTER: words turning with under
  100 ms of lead **42% -> 0%**, p10 lead **478 ms**, motion-onset interval
  unchanged at 233 ms, and every per-word crest/weight/lift identical.
  **It lives in `scheduleWord` and the remount path had to change with it.**
  That path used to RECOMPUTE `turnAtMs`, which was safe only because the old
  value was a pure function of the recording; the floor is relative to when a
  word was first delivered, so a recompute would move the turn. It now returns
  the STORED moment, which keeps the invariant intact — frozen at first sight
  exactly like the duration and the axes.
  **What the floor cannot do is invent words the recognizer has not sent.**
  Frames showing zero words ahead stayed 11% -> 12%: between endpoint flushes
  there is genuinely no text to read into. That is ASR latency, not
  presentation, and no scheduling change reaches it.
  Now that the floor does the work, `read_ahead_delay_s` is likely reducible
  back toward 1.2 s — the two are partly redundant, and the delay is the lag
  one for one. Unmeasured.
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
  (a measured em budget since 2026-08-06 — see the width-budget entry below;
  `planStageLayout`'s `display.studio_stack_words_min`…
  `studio_stack_words_per_block` is now only the ceiling) and retains **as many
  rows as the stage can actually hold** without
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
  **AND THE STAGE'S BORDER BOX IS NOW THE WORKSPACE BOX (2026-08-06, also at
  the user's request).** `.caption-stage` was a rounded card inset 14px/16px
  inside `.workspace`, so the studio carried TWO framing systems: a full-bleed
  hairline grid (the topbar's bottom rule, the rail's left rule, the window
  edges) and a floating panel repeating that same boundary 16px inside it.
  Flush, the stage's edges ARE those rules, so the frame is drawn once — which
  is why the border and the `--r-lg` radius went with the padding rather than
  surviving it. Measured at 1440×900 the stage went 1072×729 → **1104×757** and
  the caption type 28.3 → **29.2px**; `--caption-width-cap` follows the
  container in `cqw`, so it tracks automatically.
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
    shadow on chrome is allowed only where it is a DATA channel (the compass
    halo carries periodicity); `.voice-compass` also had a hardcoded
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
  embedding profile needs repeated clean endpoint observations **OR one turn of
  at least `stable_after_duration_s`** before its `S3…S12` label becomes
  public; confirmation revises earlier neutral words.
  This is not a two-speaker hard cap. Never make
  `Attribution pending` gate the Stage stack. `--diarizer embedding` is the
  deterministic A/B and unsupported-platform fallback.
  **A CHARACTER WHO SPEAKS ONCE IS STILL A CHARACTER (fixed 2026-08-02).** On
  the PR film — eleven speakers, most with a single line — the tracker produced
  **one speaker switch in 68 seconds** and put the drill sergeant in the
  narrator's colour, which is the whole of CWI 2.1 failing. Turn
  `speaker_attribution.debug: true` on and read the `@observation:` lines; the
  two causes were both in the guards, not the embeddings:
  * **The margin guard blocked ENROLLMENT.** `min_confidence_margin` exists so
    a word is not handed to the wrong ENROLLED speaker when two profiles score
    alike. It is meaningless when nobody is a plausible match — four new voices
    arrived at best/second of 0.016/0.000, 0.084/0.065, 0.120/0.048 and
    0.167/0.161, which is the strongest possible evidence for someone NEW, and
    every one was called ambiguous, which cleared `can_update` and refused to
    enroll them. It now applies only above `provisional_threshold`.
  * **Stability required a REPEAT that a one-line character never gets.**
    `_profile_is_stable` demanded two distinct endpoint groups for index ≥
    `immediate_speaker_limit`, and `_public_attribution` renders an unstable
    higher profile as neutral — so everyone after the second speaker was
    permanently grey. It now also accepts one long turn. Gate that on the
    LONGEST SINGLE observation, never on `enrolled_durations`: two clean
    fragments of one endpoint sum to the same number as one real turn and are
    not independent evidence (there is a test pinning exactly that).
  * `max_speakers` was **6**, the CI MAIN palette — but 2.1.2 defines twelve
    supporting colours and `assignSpeakerColors` already allocates them by hue
    separation and generates 2.1.4 pastels beyond. It is 12 now.
  MEASURED on `--sample`: profiles 5 → **11**, speaker switches 1 → **10**,
  words rendered with no speaker 19 → **5**, and the drill sergeant (S6) and
  Gump (S7) are separate colours, which is what the film draws.
  **THE LIVE PATH CANNOT COLOUR A SPEAKER CHANGE ON TIME ON THIS MATERIAL, AND
  THE REASON IS THE NATIVE MODEL, NOT THE MAPPING (measured 2026-08-02).** Put
  the native slot in the Sortformer decision's `reason` and read it back: the
  model has FOUR slots and reuses them across eleven speakers — slot 1
  published S1, S2, S7, S8 and S10 at different moments, slot 0 published S1
  for 54 observations, and **the entire drill-sergeant exchange came back as
  slot 0/2, i.e. the narrator**. It does not separate them inside its 1.04 s
  context, so there is no live signal to act on. Consequently **47% of words
  first paint in one speaker's colour and finish in another** — the endpoint
  is doing all the work. Collapsing only `type: "word"` events hides this
  completely (it reports 0%): the studio paints from `cue`/`commit` too, so
  score the FIRST speaker a `word_id` was ever published with.
  Two fixes for it were implemented and MEASURED AS NO-OPS, then reverted
  rather than shipped: refusing to let an unverified slot borrow a name
  another slot already holds (never fired — the slot legitimately held S1),
  and distrusting a slot after an endpoint disagreed with it (0 change, because
  `classify_span` then falls through to the embedding tracker, which returns
  the same wrong speaker by continuity). What DID ship is the plain bug: the
  slot→speaker mapping used `setdefault`, so a reused slot kept its first
  occupant's identity for the whole session. Its measured effect on this clip
  is within run-to-run noise (50% → 47%); it is correct regardless.
  Fixing the first paint needs a better provisional pass — a wider Sortformer
  context, or running the endpoint embedding at segmentation boundaries
  instead of only at ASR endpoints, since one ASR utterance here contains four
  speakers.
- **THE 47% WAS NOT ALL THE MODEL. HALF OF IT WAS A HARDCODED "S1" (fixed
  2026-08-04).** Measure it with `scripts/speaker_probe.py`, which is new and
  is the only honest way to see this: `live_events.jsonl` holds durable words
  only, so every word in it already carries its settled speaker and the churn
  scores 0%. The probe subscribes to SSE, scores the FIRST speaker a `word_id`
  was ever published with, and — this is the part that matters — scores it
  **against the playhead**, because a correction landing inside the 1.75 s
  delay is never seen. It does not: 45.9% of words were still the wrong colour
  at their own colour turn.
  Every word reaches the stage as a `hypothesis` first, and that call site
  passed **no speaker at all**, so `_attribution` returned unknown and the
  publication line defaulted it to `self.speaker` = "S1". MEASURED: 160 of 172
  words first painted as S1/unknown. Two individually-correct changes composed
  into a false claim — the server defaulted to S1 because "unknown assignments
  are rendered neutral, `speaker_status` is authoritative", which stopped being
  true on 2026-08-02 when `speakerStatus` began promoting a speaker-carrying
  unknown to `provisional` (itself right, for durable words stuck grey
  forever). After that, `speakerColor("S1")` is narrator yellow.
  Two fixes, both measured:
  * **The read-ahead lane asks Sortformer** (`provisional_span`). Free
    timeline lookup, no embedding fallback (~66 ms, would run several times per
    word before commit) and **no `_record`** — a read-ahead guess must not
    masquerade as the durable answer an endpoint is about to correct. Answers
    117 of 172 words at **62%** correct.
  * **An undecided word publishes `speaker: null`.** `self.speaker` survives
    only where it is a fact — no tracker at all. The old default measured 17
    right out of 43, which is just the narrator's base rate (79/172): zero
    information, 26 words painted wrong. Both renderers already draw null
    neutrally (`speakerColor(null)`, and legacy keys on `speaker_known`).
  MEASURED, wrong-at-turn **45.9% → 40.1% → 29.2%**; deterministic across runs
  on `--sample`. The cost is deliberate: 9.6 points moved from "accidentally
  correct" to neutral. A wrong colour is a false claim about who spoke, which
  is the one thing 2.1 exists to prevent; neutral is the design system's own
  `unknown` state and is already the read-ahead ink.
- **MID-UTTERANCE VERIFICATION: BUILT, MEASURED, REVERTED (2026-08-04).** The
  entry above says the next step is verifying at segmentation boundaries rather
  than ASR endpoints. It was implemented both ways and neither shipped. The
  residual error is entirely in multi-speaker utterances — per utterance,
  first-paint wrong ran **9%** on the single-speaker monologue against
  **49–64%** on the ones carrying three to five speakers.
  * **Without enrollment (`learn=False`): a no-op**, 29.2% → 28.7%. It
    withdraws a wrong guess (S1 → neutral) but cannot NAME a voice appearing
    for the first time — and a first appearance inside a long utterance is
    exactly the failing case.
  * **With enrollment: it MERGES SPEAKERS.** Spans are cut at COMMIT
    boundaries, not turn boundaries, so a 1.6 s span straddles a real turn, the
    mixed embedding enrolls a broad centroid, and that centroid swallows
    everyone: utterance 3 went from three speakers to **one**, and a single id
    took 74 words across three utterances. That is the "one speaker switch in
    68 seconds" failure fixed on 2026-08-02, reintroduced.
  **AND IT LOOKED LIKE A WIN — THIS IS THE TRAP TO REMEMBER.** First-paint-vs-
  final agreement rose 50.3% → **62.2%**, because first paint and the final
  answer now agreed on the same WRONG identity. Agreement is not accuracy.
  Always score identity STRUCTURE beside it — speakers and switches per
  utterance — which is why `speaker_probe.py` prints both.
  If retried: find turn boundaries FIRST and verify only spans lying inside one
  turn. Note also that sharing one `observation_group` per utterance is
  mandatory for any repeated pass, because `_profile_is_stable` counts DISTINCT
  groups and `label_words` allocates one per call.
- **THE STAGE ROWS NO LONGER FEED THE MOTION CLOCK (fixed 2026-08-06).** Rows
  used to fill a median of **65%** of the line because they break on a WORD
  COUNT while a row's width is set by its CHARACTERS, and the type size comes
  from the worst case that count can produce. Chunking on WIDTH fixes that, and
  the first attempt was reverted on 2026-08-05 because the user reported "the
  motion has changed" and they were right. Three causes were recorded; the
  first was the real one and it is now repaired:
  * **`paceGaps` and `holdGaps` read the WORD LIST, not the rows.**
    `CaptionFeed` used to derive both by flattening its `paragraphs` prop —
    which on Stage is the RETAINED ROWS — so a word at the edge of the retained
    window had no neighbour to measure against, and which words sat at those
    edges was a function of how the chunker had packed the rows. `paceGapS`
    sets `--motion-duration` and the hold gate is `min(gap_before, gap_after)`,
    so LAYOUT WAS AN INPUT TO THE MOTION CLOCK. It now takes a separate
    `timingWords` prop: the whole ordered recording, independent of what the
    stage is showing. The rows still decide what is DRAWN.
    MEASURED, this is a repair and not just a decoupling — the build's own
    run-to-run noise floor fell below pristine HEAD's on every channel:
    weight-peak max |d| **434 -> 47**, peak-size max **0.797 -> 0.053**, and
    words whose hold lift differed between two runs **1 -> 0**. Those outliers
    were the flake, and they were layout reaching the clock.
  * Row ids are `stage:${firstWordId}`, so re-chunking re-keys rows, remounts
    them and re-arms every word inside. Still true — which is why row
    membership is frozen (below), not why width chunking was unsafe.
  * Bigger rows also change how often the Stage FLIP runs — a new row appears
    less often but carries more text. Accepted.
  **Anything that touches the chunker must still be fingerprinted with
  `scripts/word_motion.py` before and after**, not just measured for fill, and
  the fingerprint must be keyed by `word_id` — `word_motion.py` keys by
  `(index, text)` and a layout change moves every index.
- **THE WIDTH BUDGET, AS SHIPPED (2026-08-06).** `selectStableCaptionStack`
  takes a `StageWidthBudget` and breaks a row when it is FULL in em rather than
  when it has counted to N; `wordsPerCaption` survives as a ceiling. MEASURED
  at 1440x900 on `--sample`, row fill **64% -> 78% median** (p90 81%, max 85%),
  rows carrying 3–13 words, and the motion is inside the noise floor with every
  acceptance number intact (`louder` 1.80x/884, `softer` 0.82, held `is`
  0.525em at 1.15x/400).
  Three things decide it and each was measured, not chosen:
  * **`width_em = 0.4343 * chars + 0.4289`, fitted on a SETTLED stage.**
    `.caption-word` is an inline-grid whose cell is `max(normal, crest)`, so a
    word sampled mid-crest reads wide, and the first fit defended against that
    by taking each word's NARROWEST observed width during playback. A minimum
    over noisy samples is a biased-LOW estimator: measured, it under-read by
    **+0.062em per word**, i.e. **+0.74em on a 12-word row**, which is a
    systematic overrun concentrated in exactly the short-word rows the budget
    packs hardest. A replayed capture settles every word behind the playhead,
    so read the whole stage at rest at once and take no minimum at all.
  * **`fill` is a RESERVE, and what it covers is the CREST.** Measured per
    capture: fit residual ~1em on a 12-word row, and crest **median +1.19em,
    max +4.92em** — which does not scale with word count (4.92em on an 11-word
    row, 0.14em on a 15-word one; it is ONE loud word, so `spread*sqrt(n)` is
    not the model). Post-formation GROWTH used to be the dominant term and is
    now re-broken for instead (below). At 0.92 the reserve was 2.63em and a row
    was cut past the stage edge on roughly one capture in three; at **0.82**
    nothing is clipped and 0 rows even reach the feed's content box.
    **0.82 IS A MOTION NUMBER, NOT A LAYOUT ONE.** 0.87 clips nothing either
    and fills more (median 83% vs 78%) — but a fuller row sits closer to its
    break, so more words re-break and more words are rebuilt, and the held "is"
    measured **4 of 6 runs right at 0.87 against 6 of 6 at 0.82**. `WordMemo`
    makes a rebuild value-identical; it does not make one free. Raising this
    means re-running the six-capture check, not arguing about fill.
  * **Measure clipping against the STAGE, not the feed.** `.caption-stage`
    carries `overflow: hidden`; `.caption-feed`'s right padding is the gutter
    that exists to absorb a row-final word's mid-pop overhang, so a row
    spilling into it is the design working. Scoring against the feed's content
    box reports rows "overflowing" that lose no text.
  **A ROW RE-BREAKS WHILE ITS WORDS ARE STILL HYPOTHESES, AND THAT IS ONLY SAFE
  BECAUSE OF `WordMemo` — THE TWO SHIP TOGETHER (2026-08-06).** A word that is
  not `final` is read-ahead text nobody has read, so the ahead-of-the-playhead
  invariant permits re-breaking it; gated on `final`, the split only ever moves
  the TAIL down, so the row being read keeps its id and its first word. It also
  retires a STALE break: while a word is unsettled the `starts` ratchet is
  ignored and capacity alone decides, which is what removes the sliver rows.
  Built without `WordMemo` first, it measured the held "is" right **3 of 6**
  against 3 of 3 without re-breaking, and was reverted for a day. With
  `WordMemo` it is **6 of 6**. Do not re-enable one without the other.
- **A WORD THAT CHANGES ROW IS REBUILT, AND WHAT IT FORGETS IS THE BUG
  (2026-08-06).** A row is a DOM element and a word is its CHILD, so React
  reconciles words within one row only: `key={id}` preserves identity among
  siblings and does nothing across parents. Moving a word to another row
  therefore UNMOUNTS it and constructs a new one — new DOM node, and every
  `useState`/`useRef` inside `MotionWord` re-derived from scratch. That is why
  every attempt to re-flow rows here has changed the motion, and it is an
  artifact of the tree shape, not a law:
  * The rebuild ITSELF is invisible. A word only changes row while it is still
    ahead of the playhead, so nothing has begun animating; `--turn-delay` is
    re-derived against the same frozen absolute moment and the word paints the
    same. The forgotten values were the entire casualty.
  * Two were still child-local and both were live hazards. `duration` is
    derived from `paceGapS`, which is **0 until the NEXT word arrives**, so a
    word rebuilt after its neighbour landed re-derived a DIFFERENT motion
    duration than the one it was already wearing. `holdAmount` re-ran the
    settle race that `holdSettled` exists to win.
  * `WordMemo` holds both in `CaptionFeed`, keyed by word id — the same pattern
    `holdMemoRef` already used for the hold GAP, for exactly this reason. Held
    in lazily-initialised STATE, not a ref, because the children read it during
    render, which `react-hooks/refs` forbids for a ref (the same rule
    `StageMemory` hit).
  MEASURED: the held "is" 6 of 6 runs correct, and the build's own run-to-run
  noise floor now beats PRISTINE HEAD's on every channel — peak-size max |d|
  **0.797 → 0.128**, weight-peak max **434 → 80.5**, words differing in hold
  lift **1 → 0**. So this also closed part of "a second source of
  nondeterminism remains and has not been found": it was the rebuild.
  Still do not claim the held word is deterministic — 6 runs is 6 runs.
  **THE 2–3 WORD SLIVER ROWS ARE THE ANCHOR RATCHET, AND EVERY BREAK THAT MADE
  THEM WAS CORRECT (measured 2026-08-06).** The user asked why a row carries
  fewer than two words. Instrumenting the chunker's real decisions on
  `--sample`: **17 anchors born, 17 of them on a genuinely full row, 0 on a row
  that was not full** — and **3700 of 16145 row-opening decisions are RATCHET
  RE-FIRES**, a word re-opening its row when that row is no longer full. The
  arithmetic is not wrong; the rows go short AFTER the fact. Four candidates
  were tested and three eliminated by measurement:
  * NOT eviction — `rows.slice(-stackLimit)` chunks the whole history every
    render, so a top row is never a fragment;
  * NOT deletion — **0 of 19 rows ever lost a word** across a full capture;
  * NOT the width test — reconstructed at the split, `'colors will distinguish'`
    (10.41em) + `'characters'` (4.77em) = 15.18em against a 26.94em ceiling,
    i.e. it SHOULD have fit; likewise `'in this army'` + `'to'` at 6.93em and
    `'my godan'` + `'feel'` at 6.06em;
  * NOT the budget drifting — `--row-budget-em` measured constant at 32.850 and
    `--stack-words` at 9 across all 472 samples.
  What is left is the interaction of two individually-correct rules: a break is
  made when the row is full, and `memory.starts` is a RATCHET so a word that has
  started a row keeps starting it, which is what stops already-read text from
  re-flowing. When the recognizer later INSERTS words ahead of an existing
  anchor (an endpoint respelling that adds text where the hypothesis had none),
  those words land between two anchors that were each born correctly against
  different text, and the leftover between them is a sliver no rule may merge
  away. Note this also means the anchors are NOT born in word order.
  It is a property of the anchoring rule (2026-08-05), not of the width budget
  — but the budget makes it more visible, because a WORD COUNT break sits at the
  same index however the text is respelled while a WIDTH break moves.
  **FIXED the same day, once `WordMemo` made a rebuild safe:** while a word is
  unsettled the `starts` ratchet is ignored and capacity alone decides, so a
  break made against text that no longer exists is retired. MEASURED over a
  full capture, permanent slivers **3–4 rows seen 200–380 samples each → one
  2-word row seen 14 samples** while it was still filling, which is just the
  newest row being partial. Two rows shed a tail word, which is the re-break
  working.
- **"is" OCCURS TWICE IN THE FILM AND ONLY THE FIRST IS HELD (2026-08-05).**
  "as each word **is** spoken" is the held one; "This **is** what it looks
  like" is not. A `word_motion.py` comparison keyed by word TEXT silently reads
  whichever occurrence comes last, and that produced a confident, wrong
  diagnosis that the held word had regressed, a wrong attribution to
  `read_ahead_delay_s`, and a re-calibration of `hold_min_s`/`hold_full_s` that
  actually broke it. **Compare by OCCURRENCE (position), never by text.**
  Measured correctly, three words lift and the set is identical on pristine
  HEAD and on the current build: **`is` 0.525em, `god` 0.525em, `spoken`
  0.105em** (the config's claim of "exactly one word" is stale).
- **THE HOLD GATE FREEZES AT THE TURN, NOT AT THE MOUNT (2026-08-05).**
  The gap is `min(before, after)` and `after` needs the NEXT word, which has
  usually not arrived when a word first renders — so the parent commits nothing
  yet, and a child that froze on its first render captured a pre-neighbourhood
  value. Whether it won that race depended on render cadence, so any unrelated
  change that altered how often the tree re-renders flipped it: MEASURED, the
  held word came out 0.525em on one run and 0.000 on the next of the SAME
  build. The user reported it as "'is' is so important so it should not
  change".
  `holdSettled` now tells the child when the parent's answer is final, and the
  child stops accepting revisions once the playhead passes the word — the same
  ahead-of-the-playhead invariant everything else here follows.
  **IT IMPROVES THE ODDS, IT DOES NOT CLOSE THEM.** Measured: without the fix
  1 of 2 runs wrong; with it **1 of 6**. A second source of nondeterminism
  remains and has not been found. Do not claim this word is deterministic.
- **"HARD TO FOLLOW" WAS TWO THINGS, AND NEITHER WAS THE ONE I WAS OPTIMISING
  (2026-08-04).** The user reported the captions as hard to follow and, asked to
  narrow it, named the colours jumping around and the motion/pace — not the
  wording. Both were measured on the RENDER, not the event stream.
  * **Colour flicker.** The speaker colour changed every **8.6 words** (median
    run 7, **25% of runs ≤3 words**), inside sentences spoken by one person:
    "Why"(green) "don't they"(purple) "answer they answer? Shift"(green). CWI
    2.1 makes colour THE speaker signal, so each change asserts a turn that did
    not happen. **This is not the same question as "is the colour right"** — the
    45.9% → 29.2% correctness win earlier the same day left the flicker
    untouched, because nothing measured stability. `scripts/speaker_probe.py`
    now reports run lengths, words-per-colour-change and % runs ≤3.
    **THE FIX IS AN INTERACTION AND NEITHER HALF WORKS ALONE — MEASURED.**
    `speaker_min_run_words` 2 → 3 alone: no change (19 changes, 8.6 w/c). Re-
    smoothing the hybrid's output alone: no change. **Both: 17 changes, 9.5
    w/c, 22% short runs**, speakers unchanged at 8. The reason is that
    `SortformerHybridSpeakerTracker.label_words` overrode the smoothed fallback
    per word and returned unsmoothed, so the rule could never reach the output
    however it was tuned; and at `run = 2` it could only ever rescue a run of
    EXACTLY ONE, while four of the five short runs were 2–3 words flanked by
    the same speaker ("or softer." as S4 between S1 and S1).
    **RAISING IT IS SAFE AND THE EDGE GUARDS ARE WHY.** The rule skips the
    first and last word of an utterance and fires only when both sides agree,
    so `["S1","S1","S2","S2"]` — the genuine two-word turn
    `test_speaker_tracker_votes_per_word_across_a_turn_change` pins — is
    unchanged at 2, 3 and 4. **5 is too far**: settled speakers drop 8 → 7.
    4 measured identical to 3.
    The smoother also never `_record`ed, so `revision_history` kept the
    pre-smoothing id and `drain_revisions` could un-smooth a fixed word; it now
    overwrites that entry, and prints under `debug: true` (it was previously
    the one decision in the system that left no trace).
  * **Pace: there was essentially no read-ahead.** See the
    `read_ahead_delay_s` entry in config.yaml. MEASURED at the shipped 1.75 s:
    **121 ms delivered, a median of ONE unread word on screen.** 2.2.1 asks for
    a whole line in white to read into. Restored to 2.5 s → **1146 ms, 4
    words**. `min_read_ahead_ms` does NOT substitute: it keeps a word on screen
    420 ms before it turns, which is not a QUEUE of unread words.
    **AND `studio_probe.py` WAS LYING ABOUT IT.** It counted read-ahead words
    by reading `getComputedStyle(word).color` on `.caption-word` — but the
    colour turn moved down to `.caption-character` on 2026-08-01, so the parent
    never carries the animated ink and the counter read **0 in every sample of
    every run**, which looks exactly like "2.2.1 is not implemented". Fixed to
    read the character. A counter that has never been seen to move is not
    evidence.
    The cost is honest and is the documented one-for-one: 0.75 s more lag, and
    wrong-colour-at-turn rises 28.1% → 33.9% while neutral falls 20.5% → 11.1%
    (more words get a Sortformer answer in time, and that lane is 62% right).
- **SORTFORMER IS DOING ALL OF THE ON-TIME ATTRIBUTION, AND SWAPPING WEIGHTS
  INSIDE IT CHANGES NOTHING (measured 2026-08-04).** `preset` and `fp16` are
  now config (`live.diarization.sortformer`) so this is a one-line A/B; every
  option below runs at the SAME 1.04 s latency. Measured on `--sample`, all
  with the shipped read-ahead attribution:
  | config | wrong at turn | neutral | **correct at turn** | speakers | switches |
  |---|---|---|---|---|---|
  | `fastV2_1` palettized (shipped) | 30.4% | 19.3% | **50.3%** | 8 | 19 |
  | `fastV2_1` **fp16** | 29.2% | 21.1% | **49.7%** | 8 | 19 |
  | `balancedV2_1` (fifo 188 vs 40) | 31.0% | 18.1% | **50.9%** | 8 | 18 |
  | `balancedV2` (v2 weights) | 26.6% | 23.7% | **49.7%** | 8 | 23 |
  | **Sortformer OFF** (`--diarizer embedding`) | 3.3% | **88.7%** | **7.9%** | 8 | 19 |
  Every Sortformer variant lands at 49.7–50.9% correct — inside the ~2-word
  run-to-run noise (the shipped config itself measured 29.2% and 30.4% on two
  runs). **fp16 is a no-op**: identical first-paint, identical speakers and
  switches, identical slot reuse, at 2.5x the model size (235 MB vs 93 MB). Its
  96.4% -> 100% NeMo argmax parity is real and lands somewhere other than our
  errors. `balancedV2`'s lower wrong-at-turn is bought entirely with neutrals,
  not with correct answers. Do not re-litigate these without a new measurement.
  **The last row is the finding.** With Sortformer off, 88.7% of words are
  neutral at their turn and only 7.9% are correct — the endpoint lane cannot
  inform the playhead AT ALL, and its final answers are unchanged (8 speakers,
  19 switches), i.e. it is right but late. Sortformer alone takes correct-at-turn
  7.9% -> 50.3%. So it is not underperforming; it is doing everything, and the
  ceiling is structural: **four native slots cannot represent eleven speakers.**
  Read the slot histogram in `speaker_probe.py` — one slot published S1 x76,
  S8 x56, S10 x40 in a single pass.
  Precision and context are therefore the wrong knobs. The levers that remain
  are MORE SLOTS (`mago-ai/ultra_diar_streaming_sortformer_8spk_v1`, Apache-2.0,
  fine-tuned from our exact `4spk-v2.1` base — but unbenchmarked, NeMo-only, and
  FluidAudio hardcodes four slots, so it needs a Core ML conversion AND a fork),
  or an on-time identity signal that is not Sortformer at all.
- **Pinned versions** in `requirements.txt`. Seed anything stochastic.
- **The CaptionSpec (`autocwi/schema.py`) is a versioned contract.** Renderers
  and the future haptic module consume ONLY `spec.json` / the SSE word events
  — never model objects. Extend the schema with optional fields; breaking
  changes require a version bump.
- **THERE ARE TWO MOTION CLOCKS AND THEY MUST NOT BE COLLAPSED (2026-08-03).**
  The AE template animates POSITION and COLOUR only — no scale animator at all
  — so its one-word-wide selector, and the speech-rate window that falls out of
  it, govern the BOUNCE. The SIZE crest is the PDF's (2.2.3's +15%, 2.3.6's
  range); the template says nothing about how long it takes, and the recordings
  run it far longer. MEASURED, span above half-peak:
  | word's peak | reference | one clock, speech rate | one clock, crest | TWO CLOCKS |
  |---|---|---|---|---|
  | 1.05–1.20 (37 of 43 words) | 0.160s | 0.259s | 0.244s | **0.110s** |
  | 1.20–1.45 | 0.240s | 0.332s | 0.756s | **0.334s** |
  | 1.45+ (the ones you SEE) | 1.560s | 0.354s | 0.704s | **1.068s** |
  Driving both from the speech rate made the words that matter **4.7x too
  fast** (reported as "too fast at a glance"); driving both from the crest made
  ordinary words **4.8x too slow**. `--motion-duration` (pop + wave) rides the
  speech rate; `--crest-duration` (`voice-phase`) rides emphasis. The two CSS
  variables were always there for this.
  **AND THE CREST WINDOW MUST BE CLAMPED TO `wordMotionMaxMs` (2026-08-03).**
  `crestDurationMs` stretches the window so the crest cannot lead the colour
  wipe, by dividing the sweep by `VOICE_PHASE_RISE_FRACTION` (0.24) — a 4.2x
  multiplier that OVERRODE the configured ceiling outright, because nothing
  bounded it. MEASURED on screen, the film's "louder" ran **2.9 s with a
  1.56 s return where the film takes 0.25 s**, and that is what reads as the
  motion refusing to let go. `word_motion_max_duration_s` is **1.05** (the
  film's whole motion) and the stretch may not exceed it.
  **The crest ramp is CUBED, not linear.** The reference's bands are flat then
  steep — almost nothing until a word is genuinely emphatic, then it more than
  sextuples. Linear put the middle band at 0.712s against 0.240s.
  **Do not judge this by the median over all words.** 37 of 43 reference words
  barely move, so the median is dominated by motions nobody notices; score the
  bands separately, and weight the top one, because that is what a viewer sees.
- **THE MOTION WAS AUTHORED IN AFTER EFFECTS, AND THE PROJECT IS IN GIT.**
  `AE PROJECT/AE PROJECT/Academy_CI_Template.aep` was deleted in `73798fd` but
  is intact in the first commit — `git cat-file blob 1518434:'AE PROJECT/AE
  PROJECT/Academy_CI_Template.aep'`. It is RIFX; walk the chunks (`LIST`/`RIFX`
  are containers, `Utf8` holds the expressions) and the whole motion system
  comes out as plain text. **Read it before inferring anything from pixels.**
  Three separate attempts here tried to recover the motion by measuring video
  and each produced confidently wrong numbers.
  What it says: all four animators (`Words`, `Up`, `Yellow`, `Antecipate`)
  share ONE range selector, exactly **one word wide** (`Index End = start + 1`),
  whose start is swept by `ease(time, inTime, outTime, 0, textLenWords)`
  between the layer's `[START]`/`[END]` markers. So a word's motion lasts
  `lineDuration / wordCount` — **one word at the current speech rate, and
  nothing to do with how big the word gets.** `Antecipate` is the same sweep
  shifted `framesToTime(1)` = **33 ms** earlier with `easeOut`. The lift
  amplitude is a `Control_Null` "amp" slider. There is no scale animator at all
  (`ADBE Text Scale`, `Tracking`, `Size`, `Rotation`, `Skew`, `Opacity` occur
  zero times) — 2.2.3's +15% pop is the PDF's, and the PDF wins on amplitude.
  **The `.mov` recordings are the WEBSITE, a different implementation.** Fitting
  the clock to them is what produced the duration-vs-size ramp (their peak size
  and motion FWHM correlate at +0.69); the template has no such relationship.
- **THE REFERENCE RECORDINGS ARE SILENT — THEIR AUDIO COLUMNS ARE BACK-FITTED
  (2026-08-03).** `ffprobe` returns only `0,h264,video` for all three
  `docs/reference/*.mov`. So `loudness`, `loudness_db`, `pitch_hz` and
  `voiced_frac` in `assets/reference_specs/*.json` are not measurements of
  anything — they are solved BACKWARDS out of the measured motion by
  `ccprosody.fit_spec_prosody`. `character_identification.json` gives it away:
  `pitch_hz` is **165 for all 14 words**, which is exactly the "silently
  CONSTANT prosody column" failure this file already warns about.
  **Never regress motion against them.** Doing so returns confident nonsense —
  measured: peak size vs loudness −0.02, weight vs pitch −0.54, duration vs
  loudness −0.58, all circular. What those specs CAN answer is what the motion
  DOES: `motion.scale/lift/dwght` are real pixel measurements, and the word
  timings are read off the frames. The only source where motion AND audio are
  both real is `assets/sample.mp4` (h264 **plus aac**), which is the PR film
  and is what `--sample` streams.
- **THE PDF SPECIFIES NO MOTION TIMING AT ALL.** Searched: no seconds,
  milliseconds, frames, duration, speed or easing anywhere in it. 2.2.3 says
  only "a 15% increase in type size before returning to its original size".
  The recordings are therefore the sole authority for the clock — and there,
  unlike their audio, the motion columns are trustworthy.
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
- **THE MOTION SPEC AS SHIPPED — READ THIS FIRST (2026-08-04).**
  Standalone copy for non-agent readers: `docs/MOTION.md`. Change both together. Everything
  after this entry is the derivation and the record of what was tried; this is
  the current answer. Five channels, each with one owner and one input.

  | channel | CSS | driven by | resting | reachable |
  |---|---|---|---|---|
  | 2.2.2 colour turn | `word-color-turn` per `.caption-character` | word onset, wiped across the spoken span | read-ahead ink | speaker colour |
  | 2.2.3 pop | `word-sync-pop` on `.word-glyph` | constant, every word | 1.00 | 1.15 |
  | 2.3.5/6 crest (SIZE) | `--voice-phase` x `--voice-scale` as a FONT-SIZE on `.word-ink` | `loudness` (p90 of the word's 30 ms frames) | 1.00 | 0.72 .. 1.62 |
  | 2.3.8/9 weight | `font-weight: calc(...)` | pitch vs the SPEAKER's median F0, plus prominence | 400 | 340 .. 900 |
  | hold / lift | `word-hold-spring` on `.word-ink` | silence around the word, `min(gap_before, gap_after)` | 0 | 0 .. 0.525em |

  Measured on the bundled film, and these are the acceptance numbers:
  `"louder"` **1.83x / weight ~890**, `"softer"` **0.82x**, held `"is"`
  **lift 0.525em at 1.15x / weight 400**, whole-film **median peak 1.15x**
  (i.e. the ordinary word carries the pop and nothing else), **0 words lighter
  than Regular**, and **0 bold samples on any lifted word**.

  Rules that are not obvious from the table:
  * **Size and lift are INDEPENDENT and mutually exclusive.** A word that
    swells does not leave the line; a word that lifts shows no crest and no
    weight. Both gates are BINARY, because every word carries the 2.2.3 pop and
    a proportional gate taxes a word for that alone. The reference's "louder"
    doubles and never leaves the baseline; its "is" floats at resting size.
  * **The crest envelope OVERSHOOTS, settles, sustains, then releases** —
    peak, back to 0.70 of it, hold, go. Two endpoints cannot express it.
  * **Weight is a property of the VOICE, not the word.** The register term
    reads the speaker's running median F0 (`pitch_register_hz`); a word's own
    excursion above its speaker is effort, not a lighter voice.
  * **Every word is readable before it moves** — a per-WORD floor
    (`min_read_ahead_ms`), not a time delay, because the recogniser delivers in
    bursts.
  * **All of it is frozen at first sight.** Duration, axes, sweep, hold gap and
    turn moment are computed once and survive remounts. Recomputing any of them
    under a running animation is the bug this project keeps re-committing.

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
  * **THE WORD GROWS FROM ITS BASELINE. IT DOES NOT MOVE.** Wrong FOUR times —
    the fourth is below, and it shipped for months behind a correct-looking
    fix for the third.
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
    **AND THE PIVOT IS NOT ENOUGH: THE ANCHOR HAS TO MOVE TOO (2026-08-03).**
    The crest is a FONT-SIZE on `.word-ink`, so it is the one voice channel
    that changes a BOX and not just its paint. `.word-glyph` is
    `position: absolute; bottom: 0` with an auto height, so its height IS its
    line box — and the ink's depth below the baseline grows with the crest
    while the strut's does not. With the box BOTTOM pinned, the word's baseline
    rides up by `--glyph-baseline-em × (crest − 1)`, and the louder the word
    the higher it floats. MEASURED before the fix, guide taken per frame from a
    settled neighbour in the same row: correlation **0.867**, "louder" at
    **+0.201em**, the largest words **+0.236em**. The reference's own baked
    curves regress lift on size at **+0.043** and put its biggest word,
    "louder" at 2.21x, at a lift of **exactly 0.000**.
    Fixed by a pair on `.word-glyph`: a `translate` that pushes the box down by
    `--glyph-baseline-em × max(0, crest − 1)`, and a `transform-origin` that
    tracks the CURRENT baseline via `max(1, crest)` instead of the resting one
    (the pop's 1.15 about the old pivot added ~0.035em more). Both are STATIC
    properties, because `word-sync-pop` has `fill-mode: none` and a shorter
    duration than `--crest-duration` — a correction in its keyframes switches
    off mid-crest. Both clamp at 1, because below it the STRUT is the deeper
    half and nothing moves; that is why "softer" measured clean and hid this.
    `--crest-scale` on `.caption-word` is the single definition all four
    consumers read.
    MEASURED after — DOM sweep, all words: slope **14.91 → 0.23 px per 1.0x**,
    correlation **0.908 → 0.028**; Korean **+0.002 / +0.02 px**. Pixel probe,
    median rise at crest 1.62: **+0.196em → −0.025em**.
    **THE MEASUREMENT IS THE HARD PART, AND IT DEFEATED THREE ATTEMPTS.**
    `.word-ink`'s rect does not contain the pop (a transform on a CHILD).
    `.word-glyph`'s rect BOTTOM is pinned by `bottom: 0` and cannot move by
    construction — measuring it returns a constant +2.22px of descender space
    and looks like proof of no lift. `scripts/studio_probe.py` keys on
    `|matrix.f| > 0.5` and the lift is LAYOUT, so `matrix.f` stays 0 throughout.
    What works is `scripts/baseline_probe.py`: pin `--voice-phase`/
    `--voice-scale` over CDP on a SETTLED stage and compare each word's ink
    bottom with its own at rest. Run it with `--broken` first — it re-imposes
    the old anchoring, and a check that has never been seen to go red is not
    evidence.
  * **THE COLOUR TURN IS A WIPE ACROSS THE WORD, NOT A SWITCH ON IT
    (2026-08-01, from the PR film).** `docs/Caption With Intention PR FILM.mp4`
    puts the colour boundary INSIDE a word constantly, in ordinary captions:
    "I like i|t" (88.15s), "dynamic te|xt" (42.0s), "brings in|" (49.3s),
    "weigh|ts" (51.35s), "character|s," (60.4s), "instantly kn|ow" (62.1s). In
    "weigh|ts" the SIZE AND WEIGHT sweep in with the colour — "weigh" already
    big and bold while "ts" is still small and grey. 2.2.4 calls per-syllable
    animation the exception; the film makes it the rule.
    So `word-color-turn` lives on `.caption-character`, each letter on its own
    `--char-turn-delay`, spread across the word's spoken span (72%, capped at
    `wordMotionMaxMs`). The delays are written IMPERATIVELY per character for
    the same reason the word's is: live words grow as a hypothesis extends, and
    a span appended later would otherwise turn late. Verified: 39 sampled
    frames showed a mid-word boundary (`SOMething → SOMEThing → SOMETHIng`).
    **AND THE WORD IS ARMED ONCE, BUT SO IS EACH SPAN — THE SENTENCE ABOVE WAS
    THE INTENT AND THE CODE DID NOT DO IT (fixed 2026-08-06).** The arming
    effect returned early on `data-armed`, i.e. for the whole WORD, so a
    character appended after the first arm — endpoint punctuation
    (`animation` → `animation,`), a respelling that lengthens — never got a
    `--char-turn-delay`, kept the stylesheet's 600000ms default, and sat in
    `word-color-turn`'s `backwards` fill (READ-AHEAD INK) for ten minutes.
    MEASURED on `--sample`: **23 of 137 settled words ended the capture two-
    coloured**, each mixed for the remaining 28–63 s, the stray colour
    `#6e6e73` = `read_ahead.color_light`. The user reported it as "some words
    contain the speaker's color and black color", and it is a false claim about
    who spoke, which is the one thing 2.1 exists to prevent. Now a span that
    already carries a delay is left strictly alone (rewriting it would shift a
    running wipe) and only new spans are written, against the same frozen
    absolute moment. AFTER: settled two-coloured words **23 → 0**, and every
    mixed word is mixed in exactly ONE 1 s sample, which is the wipe crossing
    it. `perWord` freezes at the ARM for the same reason: appending to the
    denominator would hand a late character an EARLIER delay than one already
    running and the boundary would travel backwards.
    **`studio_probe.py` CANNOT SEE THIS** — it asks whether a word's FIRST
    character is still read-ahead ink, and here the first character turned and
    the last never did. `scripts/caption_color_probe.py` is the check (with
    `--broken`, which strips each word's last delay and must go red).
    **ONLY THE COLOUR MOVES DOWN TO THE CHARACTERS. `voice-phase` STAYS ON
    `.caption-word` (2026-08-02).** An edit moved the phase down with the
    colour, and every voice channel died at once while the page still LOOKED
    alive: the phase's consumers — the crest calc on `.word-ink`, the push
    reservation on `.word-sizer-crest` — are ANCESTORS of the characters, and
    an animated custom property never propagates upward. MEASURED on the PR
    film via CDP: font-weight pinned at exactly 400 for all 100 words across
    525 samples, no crest, no push — user-reported as "there is just flowing
    motion", because the wipe, the 1.15 pop and the wave all still ran. The
    film's "weigh" turning big+bold while "ts" is small stays the accepted
    compromise: size/weight rise word-uniform under the travelling colour.
    **THE CREST MUST NOT LEAD THE WIPE (2026-08-02).** On the natural window
    the phase's rise takes ~150-200 ms while the wipe crosses a long word in
    up to 720 ms, so words BALLOONED while mostly uncoloured — the film never
    moves a word ahead of its colour. `--crest-duration` =
    `crestDurationMs(sweepMs, naturalMs)` = max(natural, sweep/0.28) stretches
    only the crest (pop and wave keep `--motion-duration`); 0.28 is bound to
    the literal 28% stop in `@keyframes voice-phase` and they change together.
    `sweepMs` and `crestMs` freeze at mount beside the duration so the arm
    effect and the animation agree on one number. MEASURED after:
    crest-before-colour violations 918-sample probe, 0.
    **I first concluded the film had NO per-character motion.** That came from
    looking only at the Forrest Gump clip, where the captions are simple. The
    demo section has it throughout. Do not generalise from one excerpt — watch
    the whole thing after 0:40.
  * **(WRONG — CORRECTED 2026-08-03) "THE FILM'S INTONATION CANNOT BE
    REPRODUCED FROM ITS OWN AUDIO."** This entry claimed the narrator never
    said "louder" louder, that its size is authored from MEANING, and that any
    acoustic loudness→size mapping renders the line flat "correctly". All of
    it was an artefact of ONE statistic: it scored each word by the RMS or
    MEDIAN over the word's whole span. A span contains the word's stops, its
    unvoiced consonants and the gaps between phones, and those are near-silent
    however the speaker is talking — so averaging over them buries exactly the
    difference being looked for.
    Score each word on its LOUD frames instead (p90 of 30 ms frames,
    `_span_db`) and the same audio says the opposite:
    | | whole-span median (old) | p90 of frames (`_span_db`) |
    |---|---|---|
    | "my voice gets" | −22.3 | −18.1 |
    | **"louder"** | −23.5 (looks QUIETER) | **−11.4** |
    | "softer" | −28.5 | **−23.6** |
    **12.2 dB between "louder" and "softer", in the right direction, from
    plain level and nothing else.** End to end the pipeline now emits
    "louder" loudness **0.963** and "softer" **0.000** against a 0.211 median,
    and on screen "louder" grows to 1.62x while "softer" SHRINKS to 0.79x —
    which is what the film draws.
    The cost of the error was large: `_prominence`'s spectral tilt, F0
    excursion and lengthening terms were all built to recover a signal that
    was never missing. `length_gain` is **0.0** now (see below).
    This is the same correction `_vocal_effort` had already made for tilt
    ("the loudest half of the 30 ms frames measures the tilt where the voice
    actually is") — level needed it for identical reasons and did not get it.
    **The lesson generalises: when a channel looks dead, check the STATISTIC
    before concluding the signal is absent.**
    **THE "GUMP!" COUNTER-EXAMPLE WAS WRONG — DELETED 2026-08-02.** This entry
    used to claim "emphasis does fire when the audio really is loud (GUMP!
    −13.3 dB against −22.4 dB calm narration)". That compared a PEAK against a
    MEAN and manufactured a 9 dB difference that does not exist. Measured
    consistently, the drill-sergeant section is **1.6 dB QUIETER** than the
    narration (mean RMS −20.6 vs −19.0; p90 short-frame −16.6 vs −15.8), and
    the loudest second in the whole film is not GUMP! at all but t=57–58 s.
    Nothing in this film is acoustically loud, shouting included, so no
    level→size mapping can enlarge any of it.
    **WORSE, ALL THREE CWI CHANNELS AGREE TO RENDER A SHOUT AS WEAK.** The
    shout is not louder, but its F0 doubles (narration 140 Hz → 278 Hz) and its
    spectrum tilts up 6.3 dB — textbook vocal effort. 2.3.9 maps high pitch to
    LIGHT and 2.3.10's diagonal ties light to CONDENSED, so MEASURED on screen
    the drill-sergeant words render down to **weight 200, the configured Light
    floor**, where the narration bottoms out at 363. The angriest voice in the
    film is drawn as the thinnest, narrowest text in it.
    **FIXED 2026-08-02 by `expression.studio.weight_emphasis`, and the FILM is
    the argument.** Crop its "louder" at peak (t=16.7 s) beside the same word
    settled (t=18.0 s): Regular at rest, **Black** at 2.08x. The design
    system's own renderer puts weight WITH size on an emphasised word, not
    against it. 2.3.7 is what reconciles that with 2.3.9 — its stated domain is
    "the frequency range of a typical human voice ... between 80 and 250 Hz"
    and it describes a VOICE ("lower voices are represented with a heavier
    weight"), i.e. who is speaking. A 278 Hz shout is vocal effort and has left
    that domain entirely. So emphasis withdraws the Light half in proportion
    and adds weight of its own; at emphasis 0 — ordinary speech, which is all
    2.3.9 is about — the mapping is bit-for-bit the PDF's.
    Width was NOT changed with it: the film's peak "louder" measures slightly
    condensed rather than wide, which contradicts 2.3.10's diagonal, but that
    measurement is confounded (ink-to-ink across separated letters at peak
    versus one merged cluster at rest) and an unmeasured change is worse than
    none.
    **THE REGISTER HALF IS PER SPEAKER, NOT PER WORD (2026-08-03).** This is
    the real resolution of 2.3.9 against the shout, and it replaces leaning on
    `weight_emphasis` to claw the Light half back. 2.3.9 draws high pitch
    LIGHT; a shout's F0 doubles (140 Hz narration -> 278 Hz here); so taken
    PER WORD the mapping renders the angriest voice in the film as its
    thinnest text. MEASURED with `scripts/word_motion.py`, **20 words rendered
    lighter than Regular, including "damn" from "Goddamnit"** — which the film
    sets Black. 2.3.7's own wording is the fix: its domain is "the frequency
    range of a typical human voice" and it says "lower VOICES are represented
    with a heavier weight". That is a statement about WHO IS SPEAKING. Within
    one speaker, going high is EFFORT, not register.
    So `live.py` publishes `pitch_register_hz` — the speaker's running median
    F0, already computed for `_prominence`'s baseline — and `voiceTypeFor`
    takes the register term from THAT. A word's own excursion above its
    speaker can no longer drive it toward Light. Pitch still separates
    speakers, which is all 2.3.9 is really about. Width keeps the WORD's own
    pitch: 2.3.10's diagonal is about the utterance and has no floor to fall
    into. Falls back to the word's pitch before a register is known.
    MEASURED after: words lighter than Regular **20 -> 0**; "louder" weight
    **893** and "Goddamnit" 807 where the film sets both Black; whole-film
    median peak stays 1.15x, i.e. the ordinary word still just pops.
    **THE BOLD CEILING WAS UNREACHABLE BY CONSTRUCTION UNTIL 2026-08-03.**
    A fully-prominent word renders `400 + emphasis x (ceiling - 400)`, so with
    `weight_range` [340, **760**] and `weight_emphasis` 0.55 the most emphatic
    word possible was 400 + 198 = ~598 and the 760 ceiling could never be
    approached. MEASURED with `scripts/word_motion.py`, "louder" rendered 579
    and the whole drill-sergeant line peaked at 592 — SemiBold, where the film
    sets its stressed words BLACK. Now [340, **900**] at **0.92**: 0.92 x 500
    = 460, so a fully emphasised word lands ~860. AFTER: "louder" **823**,
    "Sergeant." 714, "your" 694, "whatever" 656. The ordinary and quiet halves
    are untouched, because both terms are gated on prominence.
    Note `whats`/`this` still render Light (340/355) on that line and that is
    2.3.9 WORKING: they are the unstressed words of "What's your SOLE purpose
    in this army?", and the film does not emphasise them either.
    MEASURED after: no word that grows past 1.35x renders near the Light floor
    any more (the drill sergeant's line runs 231–539 where it ran 200), and the
    floor is now reached only by words peaking at 1.15x — i.e. unemphasised
    high-pitched speech, which is exactly what 2.3.9 is about. Eight
    moderately-emphasised words still sit slightly under Regular (315–379);
    that is the blend working, not a bug.
    Also note the first "GUMP!" (t≈28–30 s) is **never recognized at all** —
    no word event, so nothing to animate. Check recognition before blaming
    motion.
  * **VOCAL EFFORT IS THE FOURTH INPUT, AND IT IS WHY A SHOUT READS AS A SHOUT
    (added 2026-08-02 at the user's request).** 2.3.5 asks for VOLUME; `db`
    measures LEVEL; on mastered, AGC'd or auto-levelled audio those are
    different quantities and the film proves it. `live.vocal_effort` adds a
    one-sided lift to normalised loudness from the spectral tilt of each
    word's strongest frames (`_vocal_effort`). It does NOT touch
    `loudness_db`, which still reports what the microphone heard and is what
    haptics threshold on. MEASURED end to end on `--sample`: narration lift
    **0% of words** (bit-identical), drill sergeant **67%**, rendered peak size
    on the shout **1.333 -> 1.861** while narration stays 1.150.
    Four things this cost, all of them non-obvious:
    - **Energy-weight the tilt.** Over a whole span it measures PHONEMES — a
      word's fricatives carry huge HF energy, its silences none — giving a
      21 dB per-word spread and a useless ranking. The loudest half of the
      30 ms frames measures the tilt where the voice actually is.
    - **Smooth it causally, and NOT off `effort_history`.** That deque holds
      FINAL words only, and a word's lift is frozen while its own utterance is
      still open — so during the shout the newest finals are still the calm
      narration before it, the mean is dragged back to baseline, and the lift
      computes to exactly 0.0 for every shouted word and is then CACHED.
      `effort_recent` is keyed by time slot (re-emissions overwrite, the
      `db_bootstrap` trick). The BASELINE deliberately stays on settled
      history: a shout is measured against the calm speech around it.
    - **Apply the lift AFTER the frozen restore.** `prosody_cache` is written
      on the first CALL for a slot — when the word is still at the edge of the
      audio buffer and effort cannot be measured — and it is also inherited
      from a NEIGHBOURING slot by the retiming lookup. A lift applied before
      that restore is silently discarded; measured 0.000 across the whole
      shout, twice, before the order was fixed. The lift has its own per-slot
      freeze so "a shown word stops changing" still holds.
    - **It needs a deadband** for the same reason `voice_scale_deadband` does:
      without one, 34% of ordinary narration words lifted and sibilant-heavy
      ones ("synchronized", "so") gained +0.30 — spelling driving type size.
    - **Clip the effort `level` at 1, like `_normalize_db` does.** Unclipped, a
      word far above the speaker's p95 computed a level of 2 or 3, and the
      lift slammed `loudness` into its own ceiling: measured, 10% of the film's
      words pinned at the crest clamp and 19.4% rendered above 1.50x against
      the film's 2.8%. With the clip the largest possible lift is a config
      decision (`gain` × 0.514) rather than an artefact of the window.
    Also worth knowing before a demo: the film is broadcast-mastered, so its
    span is compressed — measured over the DURABLE WORDS the pipeline actually
    normalises against, p10–p95 = **10.6 dB**. That sits under
    `live.db_min_span` (18), which widens the window to 18 dB and so divides
    every loud-side deviation by ~1.77x. **That is not a bug and lowering it
    measured WORSE** — see the `db_min_span` entry below and in config.yaml.
  * **EFFORT ALONE STILL COULD NOT SEE "louder", AND THAT WAS THE USER'S FIRST
    EXAMPLE (2026-08-02).** The complaint was "the motion doesn't catch the
    loud sound and strong voice such as 'louder'", and MEASURED on screen it
    was exact: **75% of all words rendered at a voice scale of exactly 1.000**,
    "louder" among them, so their only motion was the constant 1.15 pop. Two
    independent causes, both now fixed, and neither is where you would look:
    - **The channel was OFF for the entire demo section.** `effort_history`
      takes FINAL words only and the film opens with ONE 24 s utterance, so the
      lift's own `len(effort_history) >= 6` gate was false for every word the
      film itself captions. `effort_bootstrap` is the same cold-start fix
      `db_bootstrap` already carried, slot-keyed so re-emissions overwrite.
      The first positive lift in the old build was at **t = 32.8 s**.
    - **`smoothing_words` deleted it even so.** Sustained shouting is a
      speaking STYLE and a causal mean reads it far better than any single word
      (AUC 0.801 → 0.905). ONE stressed word is an EVENT, and that mean is
      exactly what erases it: "louder"'s own tilt is **+1.64 dB against a
      −9.51 dB median**, the strongest word in its neighbourhood, but the six
      words before it are calm narration (−7.5, −13.6, −20.8, −14.7, −18.5), so
      the mean lands at −12.2 and the lift computes to **0.000 at every setting
      of everything else**. `emphasis_blend` is how much of a word's own tilt
      survives the mean.
    **THE SYMMETRIC-CONTRAST REWRITE THIS WAS MEANT TO BE REPLACED BY IS CLOSED
    UNBUILT (2026-08-04).** The plan was to spend the one-word lookahead
    measuring emphasis against a SYMMETRIC neighbourhood, retiring
    `emphasis_blend` -- a patch that exists only because there was no future.
    It is not needed. The reason a causal mean erased "louder" was never the
    window's asymmetry; it was that the LEVEL signal feeding it was destroyed
    upstream by a whole-span average. `_span_db` now scores each word on its
    loud frames and separates "louder" from "softer" by 12.2 dB on plain level,
    so the tilt/pitch/lengthening composite does far less work than when it was
    written (`length_gain` is already 0). Rebuilding the window symmetric would
    re-tune a term whose job has largely gone away, and cost one word of latency
    on every prosody decision. Revisit only if a measurement shows the composite
    still deciding something the level channel gets wrong.
    `_prominence` therefore scores `blend·own + (1−blend)·mean`, plus two more
    correlates that survive mastering exactly as tilt does and were already
    measured here: **F0 excursion** above the speaker's running median, and
    **lengthening**. Both are dB ratios, so they add to the tilt directly.
    Lengthening is per CHARACTER — raw word duration mostly measures syllable
    count, and "identification." would then outrank every shout in the film.
    Measured over the film (blend / pitch gain / length gain):
    | blend | "louder" | shout lifted | narration | AUC |
    |---|---|---|---|---|
    | 0.00 | 0.000 | 42% | 2% | 0.925 |
    | 0.40 | 0.149 | 63% | 5% | 0.936 |
    | 0.60 | 0.246 | 63% | 5% | 0.936 |
    | 1.00 | 0.396 | 58% | 5% | 0.906 |
    Pitch is what buys back the separation the blend costs (0.882 → 0.958 at
    blend 0). Shipped at blend 0.75 / pitch 1.0, and **`length_gain` 0.0 since
    2026-08-03**: lengthening was a proxy for the level signal `_span_db` now
    supplies directly, and as a live term it did active harm — the two words
    the film draws SMALL, "or softer", are both drawn out, so it enlarged
    precisely what should shrink.
    `gain`, `vocal_effort.deadband` and `voice_scale_response` were then chosen
    together from an EXACT sweep, not from more captures: one run with
    `vocal_effort.enabled: false` gives every word's pre-lift loudness and one
    at a known gain/deadband inverts to its prominence excess, after which every
    other setting is arithmetic on 165 numbers. Do it that way — each live
    capture is ~90 s and the knobs interact.
    **SCORE BOTH OF THE USER'S EXAMPLES, NOT JUST THE FIRST.** Tuned on
    "louder" and the overall tail alone, the sweep picked a setting that
    rendered the entire "Goddamnit Gump!" line at a flat 1.150 — the other half
    of the same complaint. Adding a shout-line term to the score is what chose
    gain 1.6 over 1.3.
    **AND THE DEADBAND MUST RE-SPAN, NOT SUBTRACT (2026-08-02).** `lift = gain *
    ((level - pivot) - dead)` makes the band steal from the TOP: widening it to
    keep ordinary words still also caps the loudest word, so the drill
    sergeant's line could not be strengthened without the narration following
    it up. That is the same trap `voice_scale_response_quiet` fell into —
    "weakening the response made the whole channel disappear instead of
    stopping ordinary words from moving" — and `voiceScale` already re-spans
    for exactly this reason. After the re-span, `gain` 1.6 → 0.55 buys a
    STRONGER shout at a smaller overall tail.
    MEASURED ON SCREEN (CDP, per-word peak against its OWN rest, the only ratio
    that is not mostly glyph shape):
    | | before | after | film |
    |---|---|---|---|
    | "louder" | **1.150** | **1.798** (weight 590) | ~2.08, Black |
    | "my drill" / "God" / "damn" | 1.15 | **1.822 / 1.539 / 1.375** | ~2.0 / — / — |
    | words >1.16x | 10.9% | 32.1% | 19.3% |
    | words >1.30x | 7.3% | 27.5% | 7.3% |
    | words >1.50x | 4.8% | 16.0% | 2.8% |
    | median | 1.149 | 1.150 | — |
    The film's own >1.30/>1.50 shares are biased LOW — its tracker breaks a
    track exactly when a word swells and re-flows the line — so treat 7.3/2.8
    as a floor, not a target. We are well above it, and that is the deliberate
    cost of the user asking twice for the shout to read.
    **THE FILM DOES CAPTION THE GUMP CLIP — GO AND LOOK AT IT.** The transcript
    file says "[No on screen captions]" for that section and it is WRONG: at
    t=28–36 s the film sets "GUMP!", "What's your sole purpose in this army?"
    (green), "To do whatever you tell me, Drill Sergeant." (orange) and
    "Goddamnit Gump!" (green) in the 2.4.1 black box, with the stressed word of
    each line at roughly 2x and Black — "sole" (t=30.45), "in" (t=31.0), "you"
    (t=33.0), "Sergeant." (t=34.0), "Goddamnit" (t=35.15). It is the best
    reference in the film for what a shout should look like, and it is also
    where its two speaker colours are unmistakable.
    Note the film's choices there are AUTHORED, not acoustic: "sole" is
    emphasised because of what the line means. Ours renders it at the bare pop
    and that is the honest answer from the audio.
  * **TWO SCOPES, AND THEY OWN DIFFERENT CHANNELS.** This is the thing that
    took the longest to see, because the PDF states neither scope.
    **2.3 intonation is per WORD, uniform.** In `intonation.mov` f395 every
    glyph of "louder" is the same size and the same weight; f470, every glyph of
    "or softer." is uniformly small. Driving size/weight/width per character off
    the intra-word envelope is what made ours read as "very character-level".
    **The per-character channel is a travelling STRETCH**, and it is what makes
    the reference feel chewy: as the colour passes through a word the letters
    stretch — hard UP AND DOWN, only a little in width — scatter off the line
    and close back up (`animation,` f194-216, `spo|ken` f282). It happens on
    every motion, not only long words.
    Shipped as a TRANSFORM on `.caption-character`: ±13% scaleY, ∓2.2% scaleX,
    a small translateY, staggered by `--char-turn-delay` so it travels.
    (`--wave-step` and `--motion-intensity` were written per word and read
    by NOTHING -- deleted 2026-08-04. `--wave-span` is real and stays.)
    **THE TWO SCOPES TRADE OFF, AND THIS IS THE RULE THAT TIES THEM TOGETHER.**
    A word carried by VOLUME — loud or hushed — moves as a WORD and its letters
    stay together; a word at ordinary volume has little word-level motion and
    the character wave is what carries it. The reference is explicit: "louder"
    (f395) is six glyphs at one size with no scatter at all, while "animation,"
    (f194-216) is ordinary volume and scatters hard.
    So `--char-wave` = (this letter's departure from its own WORD's size) x
    (1 − wordVolumeDeviation x `character_wave_falloff`), floored at
    `character_wave_floor`. MEASURED on injected words:
    SHOUTING 66.2px swell / +5% wave, ordinary 53.5px / **+13%**, whispered
    40.9px / +7% — the wave peaks at ordinary volume and is suppressed at BOTH
    extremes.
    It also fixed the headroom problem as a side effect: the loudest words no
    longer stack a big wave on top of a big swell, and ink clearance went
    **3.0px back to 10.5px**.
    **THE SUPPRESSION IS NOW TOTAL, AND MEASURED AGAINST THE REACHABLE RANGE
    (2026-08-02, user: "'louder' and 'softer' -> no lifting effects").** Two
    separate reasons those words still moved vertically. First, `falloff` 0.78
    with a 0.18 floor left 22% of the wave on "louder" — and the 2.2.3 pop
    carries no `translateY` at all (MEASURED: 0.000px across 1995 swelling
    samples), so this wave was the ONLY vertical motion on them, and the
    reference has none. Both are gone: `character_wave_falloff` 1.0,
    `character_wave_floor` 0.0.
    Second, the deviation was divided by `voice_scale_range`, which is a CLAMP
    and not what the mapping reaches — `voice_scale_response_quiet` stops the
    shrink at **0.78** against a configured 0.72, so the most hushed word in
    the film scored 0.786 and kept a fifth of its wave even at floor 0.
    `reachableScaleRange()` is the fix, and anything else asking "how far from
    normal is this word, as a fraction of the possible" must use it too
    (`emphasisOf` does).
    MEASURED after, as the real scaleY excursion rather than a count of
    transforms — an identity matrix is not `none`, so counting says nothing:
    **"louder" 0.0000, "softer" 0.0000**, ordinary words unchanged at
    0.055–0.169 (median 0.110).
    **AND THE BASELINE ITSELF IS CLEAN — MEASURE IT ON `.word-glyph`, NOT ON
    `.word-ink`.** The crest is a font-size on `.word-ink` but the 2.2.3 pop is
    a transform on `.word-glyph`, and a parent's `getBoundingClientRect` does
    not grow with a child's transform — so measuring `.word-ink` cannot see a
    word leaving the line AT ALL, which is how an earlier "0.00px drift" result
    was worthless. Take the guide from a STATIC NEIGHBOUR in the same row, per
    frame, exactly as the film measurement does: the row's own box moves while
    a word swells, so an absolute reading shows every word drifting.
    Done properly: every swelling word's glyph box bottom sits **+2.22px**
    lower during its motion, identically at every scale and every phase. It is
    not a lift — it is the descender space below the baseline growing with the
    pop, which is what scaling about the baseline is supposed to do. A real
    pivot error would scale with the swell, so a word at 1.56x would drift 4x
    further than one at 1.15x. It does not.
    **AMPLITUDES HALVED 2026-08-01** (user: "the motion waves seem a bit too
    distracted"). Was ±26%/∓4.5% with a .10em rise, measuring +29% vertical on
    screen; now +11%. At the old size every letter of every word was visibly
    moving and the wave COMPETED with the colour turn instead of supporting it
    — 2.2.3's cue is what should point the eye and the wave is texture under
    it. The rebound is gentler still (∓3.2% vs ∓8%): an overshoot as large as
    the rise is what makes a wave read as a wobble.
    A transform cannot disturb layout, so the row's width stays owned by the
    word-level sizer and the wave needs no reservation — which also means it
    cannot desynchronise from the footprint the way per-character `font-size`
    did.
    **The envelope is still used**, just for amplitude rather than type.
  * **THE QUIET HALF NEEDS A DEADBAND, NOT A WEAKER RESPONSE.** Two failures,
    in order, and the second was mine:
    1. Symmetric 0.62 response: **48% of ALL words rendered below normal, down
       to 0.75x**. Ordinary unstressed speech was drawn as if whispered, because
       the speaker's own loudness percentiles put a great many words below the
       median. It read as instability, not intonation.
    2. Weakening the quiet response to 0.26 "fixed" that to 31% and a 0.90x
       floor — and the user's LIVE test then showed no quiet motion at all,
       correctly: a 10% floor with ordinary quiet words at 3-5% is invisible.
       Weakening the response made the whole channel disappear instead of
       stopping ordinary words from moving.
    The right lever is `voice_scale_deadband` (**0.34** of each side's range):
    a band around the median where size does not move AT ALL, with the full
    response outside it. Ordinary words then sit at exactly 1.0 and only
    genuinely loud or hushed ones move — which is what "occasional emphasis"
    means. `voice_scale_response_quiet` is back to **0.55**.
    **`voice_scale_response_quiet` 0.55 -> 0.92 ON 2026-08-03** (user:
    "'softer' is just normal, it should be small as reference"). It was the
    last channel still at its original timid setting after the loud half went
    to 1.0, and a 12% shrink beside a word that GROWS 83% reads as no motion
    at all. The deadband still decides WHICH words move, so this deepens the
    genuinely hushed ones without adding to the count: MEASURED, "softer"
    floor **0.88 -> 0.83**, words that shrink 11 -> 14, median floor 0.88 ->
    0.83, and ink clearance did not move (a shrinking word retreats FROM its
    neighbours).
    MEASURED after: median exactly **1.000**, **22%** of words move (was 48%),
    floor **0.780** — a visible 22% shrink where it was an invisible 10%.
    Fewer words move, and the ones that do read.
    The pivot is not centred (quiet half spans 0..0.22 of normalised loudness,
    loud half 0.22..1), so the band is a FRACTION of each side, not an absolute.
    Tests pin the band, the visible floor, monotonicity and continuity at the
    band edge — a discontinuity there would render two near-identical words at
    obviously different sizes.
    **`live.db_min_span` LOOKS LIKE THE CULPRIT AND IS NOT — LOWERING IT WAS
    TRIED AND MEASURED WORSE (2026-08-02).** It widens a narrow-range speaker's
    percentiles, which shrinks every normalised deviation, and the deadband
    above is a fraction of each side's FULL range, so the two compound. On the
    PR film that argument is fully loaded: durable-word p10–p95 is 10.6 dB, the
    18 dB floor binds, and the loud side gets divided by ~1.77x. One
    on-screen statistic seems to confirm it — **the largest word in ANY frame
    is 1.15x at p90**, i.e. usually the biggest thing happening is the bare
    2.2.3 pop. But that statistic is a LAYOUT artifact: the stage carries ~42
    words and the film's line carries 7, so our large moments are diluted ~6x
    per frame even when the words themselves are identical.
    Score the WORDS, not the frames. Per-word peak rendered size:
    | | film | 18.0 | 14.0 | 12.0 |
    |---|---|---|---|---|
    | p90 | 1.220 | **1.236** | 1.409 | 1.475 |
    | p95 | 1.340 | **1.361** | 1.623 | 1.733 |
    | >1.30x | 7.3% | **7.9%** | 12.4% | 15.3% |
    | >1.50x | 2.8% | **2.4%** | 7.4% | 9.7% |
    18.0 already tracks the reference; 12.0 renders 3.5x too many very large
    words. Our one real shortfall at 18 is the >1.15x share (11.1% vs 19.3%)
    and the maximum (1.542 vs 1.857) — and `db_min_span` is the wrong knob for
    it, because lowering it scales ALL deviations and blows the top out long
    before it fills the middle.
    **The measurement that first argued for lowering it was contaminated**, and
    that is the durable lesson: index-matched cluster tracking on the film
    breaks whenever a swelling word re-flows the line, and the resulting
    one-frame "peaks" (7.78x!) inflated the film's tail enough to make a 3.5x
    overshoot look like a match. Validate tracks before trusting an aggregate.
    **THE FIRST UTTERANCE CALIBRATES FROM CUES, AND UNMEASURED IS NEUTRAL
    (2026-08-02).** `db_history` appends FINAL words only, and a long first
    utterance finalizes all at once at its endpoint — the PR film's 24 s
    opening monologue left ~60 words normalising against the static
    `db_range` fallback, saturated at loudness ≈ 1.0, EVERY word at the crest
    clamp. `db_bootstrap` (slot-keyed so hypothesis re-emissions overwrite,
    never double-count) now feeds the same percentile+`db_min_span` maths from
    non-final emissions until six finals exist; below six bootstrap entries
    `_normalize_db` returns the PIVOT — an unmeasured channel renders at the
    2.3.5 baseline, the same reasoning that renders an unattributed word
    neutral, never the raw config-range guess. MEASURED on the film: u0
    durable loudness median 0.218 (pivot 0.222), zero words ≥ 0.98; on
    screen 32% of words move (median excursion exactly 1.000) and the largest
    crest is 1.34 on genuinely stressed words, where before the fix the whole
    demo section sat pinned at 1.62.
  * **A HELD WORD CROUCHES, SPRINGS, FLOATS, AND LANDS AS IT TURNS.**
    Re-measured 2026-08-02 off the PR FILM — a cleaner and larger recording
    than `synchronization.mov`, which is where the old 0.382em came from. Same
    word, "is" in "precisely as each word is spoken.", tracked at 24 fps
    against the static yellow "word" beside it (`scratchpad/is_track2.py`;
    font-size ~49.5px, reference ink height 37px):
    | t (s) | what | size | lift |
    |---|---|---|---|
    | 6.45–6.62 | at rest on the line | 1.000 | 0 |
    | 6.66–6.78 | **CROUCH** | **0.714** | **−0.14em** (below the line) |
    | 6.83–6.91 | launch, overshooting | **1.314** | rising |
    | 6.95–7.03 | apex | 1.286 | 0.40em |
    | 7.03–7.70 | floats; size decays to 1.0 | 1.0 | creeps to **0.525em** |
    | 7.75–8.04 | lands, eased out, ~290 ms | 1.0 | → 0 |
    So there are two corrections, and the user asked for both ("more higher,
    and have more stretched ... more like spring"): the lift is **0.525em**,
    not 0.382, and there is an **anticipation crouch** — the word ducks BELOW
    the baseline and squashes before it goes up. The crouch is what makes it
    read as a spring rather than a lift.
    **EXACTLY ONE WORD IN THE FILM'S FIRST 18 s LEAVES THE LINE, AND THE RULE
    THAT PICKS IT IS NOT A PAUSE THRESHOLD (2026-08-03, at the user's
    instruction: "Only the 'is' lifts").** Measured with the tracking-free
    method below — per frame, every caption cluster's ink BOTTOM against the
    median bottom of that same frame — only "is" rises, 0.84 em from 6.88 s to
    7.83 s. Nothing else moves at all. Three separate things were wrong:
    * **`onset - previousEnd` IS 0.00 s FOR EVERY WORD.** The recognizer's
      `end` runs to the next word's onset and attributes no silence to
      anything, so the subtraction is structurally always zero and the hold
      had NEVER fired on a real pause — including the 0.96 s before "is".
      Use inter-onset intervals.
    * **A FLOOR CANNOT SEPARATE THEM, BECAUSE THE WRONG WORDS HAVE THE LONGER
      PAUSES.** `Caption`, `Intonation.`, `weights,`, `Now,` and `So` follow
      gaps of **1.10 s+** and stay on the line; "is" follows 0.96 s. Long
      silence is a sentence break, medium silence is a rhetorical hold, so the
      lift lives in a BAND (`hold_max_s`). Utterance metadata cannot do this
      job either — the film opens with ONE 24 s utterance, so those words are
      all inside it with no boundary to test.
    * **A HELD WORD IS ISOLATED ON BOTH SIDES, AND THAT IS WHAT THE ONE-WORD
      LOOKAHEAD BUYS.** A leading gap alone still admits `the` and `and`. "is"
      has 0.96 s before AND 0.80 s after; the function words sharing its
      leading gap are followed immediately by more speech. Score
      `min(before, after)` — it needs the NEXT onset, which is exactly the one
      word of delay this project agreed to spend. On that statistic "is"
      scores 0.92, "spoken." 0.82 and "or" 0.72, so `hold_min_s` 0.86 /
      `hold_full_s` 0.92 gives the film's word a full lift and the other two
      none. MEASURED: lifting words 36 → 10 → 4 → **1**.
    **AND THE EXCLUSION RUNS BOTH WAYS: A LIFTED WORD IS AT REST IN SIZE AND
    WEIGHT (2026-08-03, user: "'is''s lift motion don't have a size and weight
    effect").** Stepping the film's "is", once the launch overshoot decays the
    word floats at EXACTLY its resting size for 0.67 s and is never bolder than
    its neighbours — the whole of its motion IS the lift and the spring.
    MEASURED here before the fix, "is" rendered peak **1.41x at weight 838**,
    carrying all three channels at once. Size and weight are now withdrawn in
    proportion to `holdAmount`, so a partially-held word degrades smoothly.
    AFTER: "is" peak **1.15** (the bare 2.2.3 pop and nothing else) at weight
    **400..400**, lift 0.525em, with "louder" 1.82x/892 untouched.
    **SIZE AND LIFT ARE INDEPENDENT CHANNELS, AND THE GATE IS BINARY.** The
    film's "louder" more than doubles and never leaves the baseline; "is" is at
    its RESTING size the whole time it floats. Letting a loud word do both
    measured `corr(peak size, lift)` **+0.337** with "louder" lifting a full
    0.525 em, against the reference's +0.043 and its biggest word at exactly
    0.000. So a swelling word does not lift — but **do not make that
    proportional**: every word carries the constant 2.2.3 pop, so "is" renders
    1.23x of which 1.15 IS that cue, and a graded rule taxed 38% of its lift
    for what is essentially resting size. One threshold
    (`HOLD_ENVELOPE_EMPHASIS`), and score only the LOUD side — `emphasisOf`
    measures deviation in EITHER direction and "is" sits slightly BELOW the
    median (loudness 0.183 vs 0.211), so a two-sided score penalised it for
    being quiet. After: "is" full 0.525 em, "louder" 0.000.
    Wait-dependent, not universal — "or softer." follows immediately in
    `intonation.mov` and never leaves the line — so the whole choreography
    ramps from `hold_min_s` to `hold_full_s`, and
    `--hold-spring` gates the squash/stretch on that same amount so an ordinary
    word runs `word-hold-spring` as a flat identity.
    **THE WHOLE THING IS ANCHORED ON THE TURN, NOT ON ARRIVAL.** One animation
    of `--hold-pre` + `--hold-land`, delayed by `--turn-delay` MINUS the
    pre-roll, with **`backwards` fill** painting the resting 0% keyframe for
    however long the read-ahead lasts. A word delivered later than its own
    pre-roll gets a negative delay and joins the spring part-way through — the
    same mechanism every other caption animation here uses for late arrivals.
    **The scale needs `transform-origin` on the baseline**, for exactly the
    reason `.word-glyph` does: the box bottom is a descender plus half-leading
    below the line, so scaling about it lifts the word in proportion to the
    stretch. It is safe to express in `.word-ink`'s own `em` because
    `--voice-phase` is still 0 for the whole spring — the crest is what changes
    that font-size, and it starts at the turn.
    **THE PRE-ROLL IS BOUNDED BY HOW LONG A WORD ACTUALLY EXISTS, NOT BY THE
    FILM.** The film crouches ~1.05 s ahead of the turn. MEASURED by CDP on the
    sample, the gap between a word entering the DOM and its colour turn is a
    median of **0.30 s** (p75 0.49, p90 0.67): the playhead runs 1.2 s behind
    the acoustic clock, but ASR delivers a word a median 0.62 s after it was
    spoken and the endpoint holds the newest word back. Shipped at 1050 ms
    first and it was invisible — ZERO held words had the lead, one joined
    during the float and the rest joined during the LANDING, so the crouch and
    the launch never ran. `hold_pre_ms` is **420** so a typical word joins at
    the LAUNCH, entering stretched and rising, instead of already on its way
    down. Verified: a word with the lead shows the whole shape (crouch to
    scaleY 0.814 at +0.106em BELOW the line → overshoot scaleY 1.229 →
    −0.518em aloft → landing over ~220 ms).
    The gap is computed in the component, and note `t` is on the STREAM
    timeline while `start`/`end` are utterance-relative — a word's end on the
    stream clock is `t + (end - start)`.
  * **THE HOLD SCALES WITH EMPHASIS — TWO ENVELOPES, NOT ONE SHAPE
    (2026-08-03, after stepping the film frame by frame).** I corrected this
    twice in one day and both corrections were half right. The aggregate shape
    statistic (time-above-90% / time-above-50%) is **0.40** across the 43
    reference words and a raised cosine is 0.41 — but that median is carried by
    the **37 of 43 words that barely move**. Step the film's "louder" at 8 fps
    across 1.8 s and it rises over ~2 frames, sits at FULL size for ~6, and
    falls over ~2: a hold of ~0.75 s inside a ~1.25 s motion, share ~0.6. Both
    are true; the shape is a function of emphasis.
    So there are two keyframe sets. `voice-phase` is the pulse (raised cosine);
    `--voice-envelope` picks between them at `HOLD_ENVELOPE_EMPHASIS`, because
    a keyframe's stops cannot take a `var()` but `animation-name` can.
    **AND THE EMPHATIC ONE OVERSHOOTS, SETTLES, SUSTAINS, THEN RELEASES
    (2026-08-03).** It used to rise to full and hold there, which is wrong: the
    word goes PAST where it ends up and then holds LOWER. Off the continuous
    curve, "louder":
    | t | ratio | |
    |---|---|---|
    | 16.46 | 1.15 | at rest |
    | 16.71 | **3.12** | PEAK, reached in 0.25 s |
    | 16.92 | 2.52 | settled back over 0.21 s |
    | 17.25 | 2.52 | sustained flat 0.33 s |
    | 17.46 | 1.15 | released over 0.21 s |
    The sustain is `(2.52-1.15)/(3.12-1.15)` = **0.70 of the peak**, and the
    four legs are 25% / 21% / 33% / 21% of a 1.0 s window — which is why the
    ceiling is 1.05 s. Verified on screen, phase traced
    `0.36 0.74 0.92 0.94 0.83 0.76 0.70 0.70 0.70 0.70 0.70 0.70 0.55 0.35 0.10`.
    **THE RELEASE IS SHORTER THAN THE FILM'S, DELIBERATELY (2026-08-03, user:
    "bolded thing's turning into normal font's returning speed is too slow").**
    Weight is where a slow release shows: 900 -> 400 is a far larger
    perceptual step than 1.8x -> 1.0x, and both ride this one phase.
    LENGTHENING THE SUSTAIN INSTEAD WAS TRIED AND MEASURED WORSE — running the
    hold to 85% and falling over the last 15% took time-above-half-peak from
    0.68 s to **0.74 s**, because the word simply stayed up longer before
    letting go. The sustain still ends at 79% where the film's does; what
    changed is the SHAPE of the fall, which sheds two thirds of the phase in
    its first 5% and is home by 89% (~105 ms) rather than easing to 100%.
    AFTER: "louder" 0.74 -> **0.65 s**, "Sergeant." 0.75 -> 0.66 s, with rise,
    overshoot and hold untouched.
    **A rise time and a fall time cannot express this** — that is the whole
    reason "start and end points" kept failing to reproduce the reference.
    **The envelope decides how much of the window sits above half-peak**, so
    `word_motion_*_duration_s` must be RE-DERIVED whenever the keyframes
    change: the pulse spends 0.50 of its window there, the hold 0.78. Those
    numbers have moved the config three times (210/2050 → 320/3120 → 320/1300
    → 320/1050).
    **And the 2.2.3 pop belongs on the CREST clock.** Splitting the pop onto
    the speech-rate clock decoupled two SIZE channels that must compound: the
    pop finished long before the crest peaked and the visible peak fell to
    ~1.3x where the film reaches ~2.0x. Only the character wave rides the
    speech rate.
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
    returning. `voice_scale_range` [0.72, 1.62] at response **1.0** — the PDF's
    own response, with the range as the only narrowing — so with the 1.15 pop
    the largest crest is 1.86x. It was [0.90, 1.20] — a 1.33x span against
    2.3.6's specified 4x — and that crush is what read as "no feeling".
    **The response went 0.62 → 1.0 on 2026-08-02, and it was the right lever
    only AFTER `_prominence` existed.** It cannot move a word inside
    `voice_scale_deadband`, so it grows the emphatic tail without adding to the
    count of words that move at all — which is useless while the wrong words
    are the ones above the band, and exactly right once they are not.
  * **LEADING: 1.38, and the arithmetic that said otherwise was wrong.**
    `lineHeight >= capHeight * maxScale + descent` predicted 1.56, cost 4px of
    type, and bought ONE pixel: forcing the true 1.863x crest measured a 10.5px
    gap at 1.38 vs 11.5px at 1.58. Line-box geometry cannot answer this — a
    scaled box overlaps its neighbour long before any letter does, and that
    overlap grows WITH the leading. `scratchpad/ink_collision.py` reads pixels
    and is the real test; the box check in `overflow.py` is informational.
    **Headroom at the forced worst case is 10.5px.** It fell to 5.0px when the
    character wave landed and to 3.0px when the held lift did — then returned to
    10.5px once the wave/word trade-off went in, because a loud word no longer
    stacks a full wave on top of a full swell. Re-run `ink_collision.py` after
    any change to `voice_scale_range`, the wave amplitude, `hold_lift_em` or
    `character_wave_falloff` — this is the first constraint that will break.
    **IT IS `scripts/ink_collision.py` NOW, NOT A SCRATCHPAD FILE, AND THE
    CONSTRAINT HAS DEGRADED (2026-08-03).** Re-run after the weight ceiling
    went to 900, `hold_lift_em` to 0.525, the landing spring, and the row
    density: minimum gap **8px -> 1.0px**, median **36px -> 11px**, pairs under
    4px **0 -> 1**. Rows are not touching, but there is essentially no margin
    left. The minimum is 1.0px at 15, 16 AND 18 rows, so it is NOT set by row
    density or type size -- it is motion amplitude. `hold_lift_em` 0.525 alone
    is ~13px of upward travel at 24.8px type, straight at the row above.
    **AND IT IS THE CREST, NOT THE LIFT — BOTH WERE TESTED.** Setting
    `hold_lift_em: 0.0` left the minimum at 1.0px with 3 pairs under 4px, so
    the held word is not what closes the gap; do not shrink it to buy
    clearance. Freezing EVERY voice channel instead (`--voice-phase: 0`,
    `--hold-lift: 0`, `--char-wave: 0`, `transform: none`) and re-measuring the
    settled stage gives **9.0px minimum, 11px median** — so the layout hands
    each row 9px at rest and MOTION EATS 8px OF IT. That is the 1.83x crest on
    weight-892 ink, which is the reference behaviour and not something to tune
    away casually.
    Note the resting MEDIAN is 11px where this file once recorded 36px: that
    is the row density (more rows in the same stage), and it is the term to
    move if clearance is ever needed. The 1.0px floor itself is unchanged at
    15, 16 and 18 rows.
    (Superseded note follows.)
    **It is a scratchpad tool and it does not survive the session**, so it gets
    rewritten each time; the method is the durable part: screenshot the stage
    densely (0.45 s is enough), band the ink by row, and take the minimum gap
    between adjacent bands. Re-measured 2026-08-02 after `voice_scale_response`
    0.62 → 1.0 and `hold_lift_em` 0.382 → 0.525: **min 8px over 150 row pairs,
    median 36px, zero frames under 4px.** The ceiling did not move (the
    response was already clamped by `voice_scale_range`), but the held lift and
    the landing DO now overlap the crest — a word lands over 290 ms after its
    turn while the crest peaks 146–322 ms after it — so this had to be checked
    rather than argued.
  * **Duration** is all that survives of the old scheduler:
    `naturalMotionDurationMs` — **950 ms** base, stretched by the spoken span
    and delivery flow, capped at **1150 ms**. Freeze it per word at mount.
    **RE-FITTED 2026-08-02 to the film, and the RETURN is what it buys.**
    Tracking the PR film's "louder" at 24 fps (`scratchpad/louder_curve.py`;
    16.43 begins, 16.68 peak, holds to 17.23, normal by 17.48) gives rise
    **0.25 s**, hold **0.55 s**, return **0.25 s** — ~1.05 s in all, against a
    720 ms ceiling here. The user asked to "increase the motion time of
    'motion -> normal'".
    **THE STOPS ARE FRACTIONS, SO THE WINDOW IS THE ONLY LEVER ON THE RETURN.**
    Re-fitting `@keyframes voice-phase` 28%/62% -> 24%/76% to the film's
    proportions on its own SHORTENED the return, 274 ms -> 184 ms, because
    24% of a short word's window is less than the old 38% was. Both had to
    move. MEASURED on screen after: rise 0.19 / hold 0.59 / return **0.20**
    (sampling at 30 ms loses ~1 frame at each edge, so ~0.22/0.59/0.23), total
    0.93 s. Peak simultaneous motions 5, median 1 — the longer window costs
    concurrency and that is the trade.
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
- **The voice instrument is continuous audio state, not another caption effect
  — AND IT NO LONGER TOUCHES THE STAGE (2026-08-04).**
  `_realtime_voice_features()` estimates F0, autocorrelation periodicity, and
  spectral centroid from each true ~64 ms capture block. `level_event()` sends
  those with RMS. The side-grid `.voice-compass` maps radius=volume, bead
  height=F0, oval width=brightness, opacity/halo=periodicity, and reserves
  direction for `direction_deg`/`azimuth_deg`. Rolling delivery
  force/attack/contour/flow/texture shape its inner resonance;
  `delivery_profile` is a descriptive acoustic readout, not an emotion
  classifier.
  **`.line-voice-orb` IS GONE — DO NOT RE-ADD IT.** The Next studio used to
  render a second copy of the same channels as a `.82em` sphere just past the
  right edge of whichever row the playhead was inside. Removed at the user's
  request ("let's remove the sphere next to the captions"). It was the one live
  instrument INSIDE the caption surface, and the stage is captions and nothing
  else — the same reasoning that removed the nav rail, the workspace header and
  the transport bar on 2026-07-30. No channel was lost: the compass carries all
  of them, at a size where they can actually be read. Verified on `--sample`,
  two captures: zero `.line-voice-orb` in the DOM or the built export, compass
  live, caption rows unchanged.
  It was out of flow (`position: absolute`), so removing it changed NO row
  geometry — but `.caption-feed`'s right padding was sized to clear it and is
  **deliberately unreclaimed**. Shrinking `--caption-gutter-em` (2.50 = .60 left
  + 1.90 right) is real caption width, but that gutter also absorbs a row-final
  word's mid-pop overhang, measured up to .842em, and the last time this number
  moved it was because words were being CLIPPED silently on ~15% of
  row-samples. Measure with `clip_probe.py` through live playback before
  touching it.
  Current mono input must say `awaiting array`; never fabricate direction. The
  compass carries **no `front` label** (removed 2026-07-30): with direction
  reserved there is no bearing to orient, so the word was labelling an axis the
  instrument does not yet report. The rail's `DIRECTION / Awaiting array` readout
  is what states that.
  The legacy diagnostics page (`livepage.py`) still has its own
  `.intent-circle`; it was left alone as a diagnostic, not a product surface.
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

**MEASURE THE FILM AS A CONTINUOUS CURVE. DO NOT TRACK CLUSTERS (2026-08-03).**
Per-glyph/per-cluster tracking on the film has now failed FOUR times, always
the same way: a swelling word re-flows the line, so the track breaks at exactly
the moment worth measuring. The fourth attempt failed its own validation —
"louder", visibly ~2x and holding, came back as **1.05x** in 6- and 7-frame
fragments, because tracking begins after the word has already grown and "rest"
then equals "peak". Numbers from a tracker that has not been shown to reproduce
a word you can see with your own eyes are worthless.
What works needs no frame-to-frame correspondence at all: **per frame, the ink
height of the TALLEST caption cluster over the MEDIAN cluster's**. Only one
word is emphasised at a time, so that ratio IS the current word's swell,
sampled every frame. It validates on both words that can be checked by eye
("louder" and "sizes,"). The same trick answers the lift question with ink
BOTTOMS instead of heights — each cluster's bottom against the median bottom of
its own frame. Guides are stripped BY HUE (cyan rules, yellow playhead), never
by density.
**USE `scripts/word_motion.py`, NOT AN AD-HOC AGGREGATE.** It reports ONE ROW
PER WORD -- peak and floor against that word's OWN modal rest, weight peak and
floor with a flag when a word renders lighter than Regular, half-excursion
width and window measured INSIDE the motion, character count, and hold lift.
It excludes words that were only ever sampled settled instead of counting them
as 1.00x. Validated against the three words whose behaviour can be checked by
eye: "louder" peak 1.62 / lift 0.000, "softer" floor 0.79 and flagged Light,
"is" lift 0.525. Four ad-hoc metrics gave confidently wrong answers in one
session before it existed; the two below are why.
**`scrollWidth` ON `.caption-words` DOES NOT MEASURE CLIPPING (2026-08-03).**
`.word-glyph` is `position: absolute` and out of flow, so a swelling word's
overhang inflates `scrollWidth` without any text being lost -- that is the
design (the visible glyph moves nothing; the in-flow `.character-sizer` owns
the width). A probe on that basis reported 46-58px of "silent cutting" across
~500 of ~3300 row-samples and it was a FALSE POSITIVE, chased through two
attempted fixes: `--word-em-linear` 1.45 -> 1.72 (measured 47px vs 46px, and
structurally incapable of helping -- that budget DERIVES the type size, so
inflating it shrinks the type by the same proportion and overflow in `em` is
invariant) and a per-row CHARACTER budget in the chunker (no change, and it
broke 8 selector tests). Both reverted.
To ask whether text is actually cut, compare the IN-FLOW sizers
(`.character-sizer`, `.word-sizer-crest`) against their row's client box.
MEASURED that way, worst excursion is **0.0px** -- nothing is clipped.
**AND `max/min` OVER A WORD'S SAMPLES CANNOT TELL GROWTH FROM SHRINKAGE.** This
cost a whole round: "softer" was reported as rendering 1.27x and chased as a
bug, when 1.27 was `rest / crest` — the word was correctly SHRINKING to 0.79x,
which is what the film draws. Always divide a word's peak by ITS OWN RESTING
size (the modal font-size across its samples), and report the floor separately
from the peak.

**COMPARING OUR MOTION TO THE FILM: MEASURE EACH WORD AGAINST ITSELF.**
(2026-08-02.) `--sample` IS the PR film, so the two can be scored on one
statistic — but only one. Two ways to get a confidently wrong answer, both hit
here first:
* **Never compare one word's ink height to another's.** "types" runs
  ascender-to-descender, "sizes," is x-height plus a comma; the ratio between
  them is mostly glyph shape. Worse, the studio side is naturally measured off
  ELEMENT boxes, which are glyph-INdependent — so the two sides are not
  measuring the same quantity, and the film looks wildly more dynamic than it
  is. Track each word across frames and divide its peak by its OWN resting
  height. **Equal cluster COUNT does not make the i-th cluster the same word**
  — a swelling word re-flows the line, two neighbours whose gap closes merge
  while something else splits, the count survives and the identities do not.
  That produced one-frame "peaks" of 7.78x and inflated the film's measured
  tail enough to justify a config change that was really a 3.5x overshoot.
  Require every cluster to stay near its own previous x-centre, width and
  height, and break the track when it does not.
* **Strip the film's authoring guides by HUE, not by density.** The cyan rules
  and the yellow playhead are not captions. Removing "rows/columns that are
  mostly lit" also punches gaps through the caption, and banding on those gaps
  TRUNCATES every tall word at the band edge — which made t=12.0, where
  "sizes," is visibly ~1.9x its neighbours, measure as uniform 1.0. Validate
  any change to that code against t=12.0 before trusting an aggregate.
On the studio side read `font-size × the .word-glyph transform`: the 2.2.3 pop
is a transform on a CHILD of `.word-ink`, so `.word-ink`'s own
`getBoundingClientRect()` does not contain it.

Use `--timeout`, NOT `--virtual-time-budget` (SSE never idles — it hangs).
A studio stuck on "Preparing language setup" with a healthy backend is a torn
`web/out` (index.html referencing 404 chunk hashes) — `npm --prefix web run
build`, and do not build while a live server is serving that directory.
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
  Zipformer int8 export (KsponSpeech + AIHub, ~6,500 h). Its leading-space
  tokens preserve 어절 boundaries and timed
  pieces. `verifier_enabled`, `draft_enabled`, and the English TIMIT
  `onset_prefix` are false in the `ko` overlay.
  Do not pass Korean through English sidecars or overwrite it with the weaker
  2024 Korean endpoint model. Korean typography is
  `assets/NotoSansKR.ttf`, not the previous static system-font stack.
  **IT IS THE chunk-32 EXPORT SINCE 2026-08-05, AND THE LEVER IS LATENCY, NOT
  WEIGHTS.** The repo ships chunk-16/32/64 exports of the SAME checkpoint and
  the decoding method is free, so `scripts/korean_sweep.py` runs that 6-cell
  grid on 120 FLEURS ko clips. Two results, both against expectation:
  * **chunk-64 wins on text and is disqualified on time.** 10.07% vs chunk-16's
    10.80% normalized CER — but a word first reaches the screen at p90
    **1552 ms**, and against `display.read_ahead_delay_s` 1.75 that leaves
    **198 ms** before the playhead turns its colour, under
    `min_read_ahead_ms` (420). CWI 2.2.1 read-ahead would simply be gone.
    chunk-32 keeps **758 ms**, still 1.8x the floor.
  * **`modified_beam_search` is WORSE here, though the model card's whole table
    uses it.** +0.77 points at chunk-16, +0.43 at chunk-32; it only helps at
    chunk-64. Greedy stays. Decoding is deterministic, so these are exact
    numbers, not samples — but re-run the sweep rather than re-arguing them.
  Shipped chunk-32: CER **10.80% -> 10.54%**, RTF **0.078 -> 0.055**, onset-gap
  distribution unchanged (median 560 ms, p10 320 / p90 920), which is the check
  that matters — a backend with better words and worse spans is a downgrade.
  **MEASURE FIRST PAINT, NOT THE DURABLE WORD.** Scoring only `type: "word"`
  events puts the lag a whole endpoint late (1152 ms vs 552 ms at chunk-16) and
  would have disqualified every arm including the shipped one. The studio
  colours from `cue`/`commit` too, so the read-ahead budget is the FIRST event
  carrying a `word_id` and text.
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
- **Never edit a `@keyframes` stop with a first-occurrence string replace.**
  `globals.css` has several animations sharing the same percentages, and a
  replace of `"\n  30% {"` intended for `word-hold-spring` landed in
  `voice-phase` instead — flattening the raised-cosine pulse AND leaving the
  spring's stops out of order. The build stays green and the page still looks
  animated. After any keyframe edit, print every animation's stop list and
  assert it is sorted; the `baseline_probe.py` FAIL that caught this reported
  a rise of exactly `hold_lift_em`, which looked like a physics bug and was a
  text-editing bug.
- `scripts/baseline_probe.py --settle` defaults to **76.0** (the sample
  length) on purpose. Passing a small value cuts the probe off before the
  stage fills, and it then reports "only N word-measurements — nothing to
  conclude". That message means the run is INVALID, not that the check passed
  or failed — do not quote a PASS from a short-settle run.
- Tests are fully offline by design — keep them that way (synthetic audio,
  no model loads).

## State / open threads (2026-07)

- Live mode: pre-capture English/Korean selection + confidence-aware speaker
  attribution. English uses its three-stage ASR path; Korean uses the
  authoritative 174M chunk-32 online Zipformer and finalizes directly at its
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
- **THE NORMALIZER EXISTS NOW, AND THE 8-CLIP SLICE WAS LYING TWICE OVER
  (2026-08-05).** The old entry here read "Korean is ~12.5% CER, 44/351 chars
  on 8 FLEURS ko_kr clips, much of it number formatting — write a shared text
  normalizer before comparing providers". Both halves are now measured, and
  each moved the number in the OPPOSITE direction:
  * `autocwi.scoring.canonical_korean` reads digits out (`2011년` ->
    `이천십일년`, via Sino-Korean `sino_korean()`) and drops unspoken
    punctuation, on reference AND hypothesis alike, so it can only remove a
    formatting difference and never invent agreement about a phoneme. Tests
    pin both directions. `scored_units(..., normalize=False)` keeps the raw
    column so older records stay comparable, and `benchmark.py` prints both.
  * **The 8 clips were unrepresentative — 120 is the eval set now.** On those
    8, normalization took CER 12.54% -> **5.19%** (26 of 44 edits sat within
    six characters of a digit, 59%). On 120 clips it is 13.23% -> **10.54%**:
    the slice was number-heavy AND easy. Do not quote 5.19%, and do not fetch
    fewer than ~120 clips — at 351 units one edit moved the rate 0.28 points.
  So the honest Korean number is **10.54% CER normalized / 13.23% raw**, not
  ~12.5% and certainly not ~0%.
  **What is left is NOT number formatting.** The largest remaining category is
  the FIRST word of a clip: measured on the 8-clip slice, 5 of 8 had an error
  in their opening word (`다리 밑`, `염`, `합금은` dropped outright). It is the
  model, not the pipeline — MEASURED, padding 1.5 s of leading silence and
  disabling `InputGain` both changed nothing, separately and together. The
  clips needing it have 1.0–1.3 s of leading silence already.
  The obvious next lever is the Korean endpoint verifier, which is off because
  a 2024 offline model "changed one phrase this stream had already recognized
  correctly" — a judgement made on four bundled utterances and now re-testable
  against 120 scored clips. Not attempted here: it adds a revision lane.
- **THE KOREAN STRESS MATRIX HAD NEVER BEEN RUN, AND ONE OF ITS CONDITIONS WAS
  MEASURING THE WRONG THING (2026-08-05).** First Korean `--stress` numbers:
  clean **10.54%**, `room-noise-14db` **15.94%**, `quiet-device` **52.08%**,
  `fast-1.15x` **50.06%**. Two of those need reading carefully.
  * **`quiet-device` was ~0 dB SNR, not a quiet device.** It attenuated speech
    22 dB over a **-52 dBFS** floor; MEASURED, FLEURS ko speech frames sit at
    a p90 of -28..-31 dBFS, so they land at -50..-53 — at or BELOW the noise,
    an effective SNR of **-1.4 to +1.8 dB**. No gain recovers that, because
    gain lifts the noise equally: instrumented, `InputGain` correctly reached
    **25.8 dB** and the score was still 73.65%. `conditions.py`'s own
    `attenuated()` docstring names this exact trap and guards against it with a
    -78 dBFS floor; `quiet_noise` simply had not been checked. The floor is
    **-68 dBFS** now (measured 14.8 dB SNR), which is the level test the name
    claims, and the score moved 73.65% -> **52.08%**.
    **Re-measure English `--stress` — that total moves too.**
    **THE REMAINDER IS A REAL LEVEL PROBLEM, AND THE MATCHED-SNR COMPARISON IS
    WHAT PROVES IT.** `room-noise` and the fixed `quiet-device` now sit at the
    SAME ~14-15 dB SNR, and score **15.94% vs 52.08%** — 3.3x worse from
    absolute level alone (-50..-53 dBFS speech). Gain reaches the recognizer
    without restoring accuracy, so a quiet Korean talker is a genuine booth
    risk and `input_gain`'s target/headroom deserve a pass against the Korean
    model specifically.
  * **`fast-1.15x` at 50% is real, and partly an artifact of the transform.**
    Not a scoring effect: on 0002 the output collapses from 39 characters to
    18, and 0007 comes back as unrelated words. But `time_stretch` is a phase
    vocoder, so the condition conflates tempo with phase smearing, and real
    fast speech carries no such artifact. Treat it as a red flag to re-test
    with genuinely fast recordings, not as a measured fast-talker number.
  **chunk-32 beat chunk-16 under EVERY condition**, which is why the export
  change is safe and not a clean-speech overfit: clean 10.80 -> 10.54,
  quiet-device 75.17 -> 73.65, fast-1.15x 53.62 -> 50.06.
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
  **The studio's version of the same bug (fixed 2026-08-02):** `speakerColor`
  returned grey whenever `speaker_status` was `"unknown"`, and many durable
  records legitimately end with `speaker: S1, speaker_status: "unknown"` — so
  words that turned while attribution was pending stayed grey FOREVER ("you",
  "gets", "they"). `speakerStatus`/`speakerColor` live in
  `web/src/lib/speaker-colors.ts` now: grey is reserved for `speaker == null`,
  and a speaker-carrying word whose tracker status is unknown displays as
  `provisional`. The provisional colour-mix washes are also gone from
  `globals.css` — the `word-color-turn` keyframe has no `to`, so the wipe
  animates toward the COMPUTED colour and a washed computed colour was muting
  the turn itself; "revisable" is signalled by the read-ahead paint before the
  turn and the dark stage's dotted rule after it. Do not resurrect either in
  `caption-paragraphs.ts` — its speaker null-ing feeds row identity, and
  changing it remounts rows. MEASURED: grey-after-turn words 0 across a full
  film pass.
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
  the active caption. **The stage carries captions and nothing else** — the
  line-edge voice circle that used to ride the active row was removed
  2026-08-04. The Voice Compass in the side grid is now the only live voice
  instrument: volume changes its outer radius, F0 moves the bead vertically,
  periodicity/brightness shape its restrained inner texture, and it
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
