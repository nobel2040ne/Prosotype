# CLAUDE.md — working notes for Claude Code sessions

auto-CWI ("Prosotype"): a local, offline pipeline that automates the
**Caption with Intention** (CWI) design system for Deaf/HoH viewers.
**Primary mode = live captions** (mic → CWI-styled captions in the browser,
English or Korean, selected before capture). The offline video pipeline is kept
as the source of the **CaptionSpec contract** the haptic device module
consumes.

**This file is the rules — the imperatives, and the numbers that make them
checkable.** The mechanism behind each one lives in the doc that owns its
subject, and the evidence behind all of them lives in `docs/DECISIONS.md`. Before
changing anything a rule here forbids, search that file: most of the obvious
ideas are in it with a measurement attached showing they did not work.

| Read this | For |
|---|---|
| `docs/MOTION.md` | **the motion contract** — five channels, acceptance figures, the playhead, and every implementation rule a code change gets wrong |
| `docs/LIVE.md` | live mode in depth — the Stage stack, speaker attribution, recognition, display modes |
| `web/README.md` | the studio frontend — non-negotiable caption behaviour, the chrome design system, the light stage |
| `docs/TESTS.md` | test layout and every measurement recipe, including how measurement has gone wrong |
| `docs/HARDWARE.md` | the ReSpeaker array + Pi + motor node: bring-up, wiring, booth runbook |
| `docs/KOREAN.md` | Korean expression: measured against English, and the material blocker |
| `docs/KOREAN-ASR.md` | Korean recognition: open-benchmark comparison, and the verifier recommendation |
| `config.yaml` | every tunable value, with its derivation in comments |
| `ARCHITECTURE.md` | module map, data contract, glossary |
| `docs/DECISIONS.md` | why each rule exists; what was tried, measured and reverted |
| `docs/reference/cwi-design-system-v1.0.pdf` | the design system itself, and the final word |

## Commands

```bash
.venv/bin/python -m pytest                       # offline tests, no downloads
npm --prefix web install                         # one-time Next.js dependencies
npm --prefix web run check                       # lint + TS reducer tests + static build
.venv/bin/python -m autocwi live                 # live captions from mic (opens browser)
.venv/bin/python -m autocwi live --lang ko       # bypass picker, Korean
.venv/bin/python -m autocwi live --lang multi    # bilingual, one model, auto-detect
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --lang ko # Korean model + Korean sample
.venv/bin/python -m autocwi live --sample --loop # repeat the clip continuously
.venv/bin/python -m autocwi live --file x.wav    # stream a file as if live
AUTOCWI_FAST=1 .venv/bin/python -m autocwi live --file x.wav --once  # headless test
.venv/bin/python -m autocwi live --list-devices  # pick a mic if the default is wrong

# hardware node (ReSpeaker array + Pi + motors) — see docs/HARDWARE.md
.venv/bin/python -m autocwi live --node --host 0.0.0.0   # capture from the node
python3 scripts/hw/probe_array.py                 # ON THE PI: devices + DoA command
python3 scripts/hw/probe_motor.py --wiring        # the driver circuit, touches nothing
python3 scripts/hw/prosotype_node.py --host MAC_IP --doa-cmd "..."  # ON THE PI
.venv/bin/python -m autocwi run clip.mp4 --out out/ --stub   # offline pipeline, no models
.venv/bin/python -m autocwi run clip.mp4 --out out/ --speakers 2  # real (spec.json)
.venv/bin/python -m autocwi cc out/spec.json --media clip.mp4  # CWI closed captions
.venv/bin/python -m autocwi tune                 # live motion tuner, built-in line
.venv/bin/python -m autocwi cc out/spec.json --tune   # same, from the cc command

# one-time downloads
.venv/bin/python scripts/fetch_font.py            # Roboto Flex + Noto Sans KR
.venv/bin/python scripts/fetch_streaming_model.py # 3-stage live ASR
.venv/bin/python scripts/fetch_streaming_model.py --korean-only
.venv/bin/python scripts/fetch_streaming_model.py --speaker-only   # ONNX speaker + Sortformer
.venv/bin/python scripts/fetch_streaming_model.py --sortformer-only # Core ML path
.venv/bin/python scripts/fetch_fleurs.py --lang ko --count 120     # eval set (use >=120)

# measurement — docs/TESTS.md says which probe answers which question
.venv/bin/python scripts/benchmark.py --lang ko              # THE benchmark: text + timing
.venv/bin/python scripts/benchmark.py --lang ko --stress     # + noise/reverb/1.15x
.venv/bin/python scripts/benchmark.py --lang en --quiet-sweep # InputGain guard
.venv/bin/python scripts/benchmark.py --audio docs/reference/pr-film.mp4 --lang en # score-free
.venv/bin/python scripts/benchmark.py --lang ko --backends local,speechmatics,soniox  # UPLOADS audio
.venv/bin/python scripts/korean_sweep.py          # KO chunk x decoding A/B
.venv/bin/python scripts/word_motion.py           # per-word motion fingerprint
.venv/bin/python scripts/motion_diff.py --film --out /tmp/film.json  # size envelope
.venv/bin/python scripts/motion_diff.py --compare /tmp/film.json /tmp/ours.json
.venv/bin/python scripts/word_by_word.py --rows /tmp/rows.json  # same word, same audio
.venv/bin/python scripts/weight_diff.py                         # does weight animate
.venv/bin/python scripts/studio_probe.py --samples 40  # read-ahead + motion (CDP)
.venv/bin/python scripts/speaker_probe.py         # CWI 2.1: is the FIRST colour right?
.venv/bin/python scripts/caption_color_probe.py   # ...and does the WHOLE word wear it?
.venv/bin/python scripts/baseline_probe.py        # does a swelling word stay on its line?
.venv/bin/python scripts/ink_collision.py         # adjacent-row clearance under motion
.venv/bin/python scripts/clip_probe.py            # is a caption row being CUT? (--broken)
.venv/bin/python -m autocwi live --sample --diarizer embedding  # Sortformer-off A/B
```

The venv is `.venv/` (Python 3.11). Always use `.venv/bin/python`, not system
python. Every probe takes `--broken` or an equivalent negative control — **run it
first. A check that has never been seen to fail is not evidence.**

## Hard rules

### Locality and the data contract

- **Local and offline by default; cloud is opt-in and must stay fallback-safe.**
  No telemetry. Permitted network: one-time model/font/eval-set downloads,
  `live.verifier_backend: openai` (default `local`), and **the LAN link to the
  hardware node**. Any cloud lane may supply **text only** and must keep the
  local path as a mandatory fallback that runs first, so a dead uplink degrades
  instead of dropping an utterance.
- **The server binds `127.0.0.1` unless `--host` says otherwise, and that
  default does not move.** The hardware node needs a LAN address, so widening
  the bind is explicit, opt-in, and announced on stdout. It reaches nothing
  beyond the LAN — still no internet, still no telemetry.
- **The binding constraint is per-word `start`/`end`, not locality.** Prosody,
  `delivery_cache`, the motion clock, reveal gaps and Sortformer coverage all key
  off word spans. **Never synthesize onsets from a transcript that lacks them** —
  that fabricates what CWI §2.2.2 is most explicit about. OpenAI's streaming
  models return no word timestamps, which is why they sit at `EndpointVerifier`
  (audio in, bare text out) and nowhere else. No A/B has shown it beats local
  Parakeet.
- **The CaptionSpec (`autocwi/schema.py`) is a versioned contract.** Renderers and
  the future haptic module consume ONLY `spec.json` / the SSE word events — never
  model objects. Extend with optional fields; breaking changes bump the version.
- **Collapse word revisions by `word_id` when consuming SSE events.** A word is
  re-emitted under the same id when endpoint text or later speaker evidence
  revises it; counting every `type: "word"` event duplicates whole phrases. See
  `collapse_revisions()` in `scripts/asr_backends.py`.
- **Pinned versions** in `requirements.txt`. Seed anything stochastic. Offline
  stages stay independently runnable via their subcommands, reading/writing JSON
  intermediates in `--out`. **Tests are fully offline by design** — synthetic
  audio, no model loads, no network. Keep them that way.

### The frontend — see `web/README.md`

- **`web/` is the product frontend; Python remains the runtime.** `output:
  "export"` emits `web/out`, and `autocwi.live` serves it, `/runtime-config.json`,
  `/session`, `/session/language`, the two fonts and `/events` from one origin.
  **Do not add a required Node server, Next route handler, Server Action, cookie,
  rewrite, or anything else incompatible with static export.** If the export is
  absent, live falls back to the diagnostics page; a built studio keeps it at
  `/legacy`.
- **The stage carries captions and nothing else.** Do not re-add the nav rail,
  workspace header, transport bar, stage label, grid, corner brackets, or a card
  border around `.caption-stage` — the stage's border box *is* the workspace box,
  and the studio has one framing system, not two. **`.line-voice-orb` is gone; do
  not re-add it.**
- **Do not shrink `--caption-gutter-em`.** It is deliberately unreclaimed: it
  absorbs a row-final word's mid-pop overhang (measured up to .842em), and the
  last time it moved, words were silently clipped on ~15% of row-samples. Measure
  with `clip_probe.py` through live playback first.
- **Two design systems, and the boundary is literal: anything inside
  `.caption-word` is CWI, everything else is Apple.** Chrome follows the
  `apple-design-analysis` skill; captions follow CWI, which outranks it. Never let
  an Apple token reach `.caption-word`, and never let a CWI token style a button.
- **The light stage is a toggle-gated, measured deviation from §2.4.1 and
  defaults OFF.** Do not hardcode either palette — both arrive through
  `/runtime-config.json`. Turning it off must restore the exact CI values and the
  black box. **A theme swap is a row-composition change** (dark adds .22em of row
  padding, ~one row over a full stack), so re-run the six-capture motion check
  after any theme default change. `autocwi cc` is never themed.

### Motion — see `docs/MOTION.md` first

`docs/MOTION.md` is the contract: the five channels, the four rules that are not
visible in its table, the playhead, the acceptance figures, and every
implementation rule a code change gets wrong. **Read it before touching motion.**
What must be true regardless of which file you are in:

- **All mapping values live in `config.yaml`**, never hardcoded, and cite PDF
  section numbers in comments. **Do not restate a tunable in prose** — that is how
  this file drifted from the config on four separate numbers.
- **Read the numbers out of `docs/reference/cwi-design-system-v1.0.pdf` itself, not out of
  `docs/DESIGN.md`** (the user's instruction: "it is wrong"). DESIGN.md mixes the
  PDF's stated values with derivations fitted to `docs/reference/*.mov`, and where
  they disagree the fitted material has been wrong every time — those recordings
  are the project's *website*, not the spec.
- **The PDF specifies no motion timing at all.** The recordings are the sole
  authority for the clock; the AE template (`git cat-file blob 1518434:'AE
  PROJECT/AE PROJECT/Academy_CI_Template.aep'`) is the authority for what the
  motion *is*. **Read the template before inferring anything from pixels** — three
  attempts to recover the motion by measuring video produced confidently wrong
  numbers.
- **The reference recordings are silent, so their audio columns are back-fitted.
  Never regress motion against them.** The only source where motion and audio are
  both real is `docs/reference/pr-film.mp4` — the PR film, which is what `--sample` streams.
- **THERE ARE TWO MOTION SYSTEMS, AND LEGACY IS THE ONE THAT SHIPS.**
  `Settings → Enhanced motion` defaults **OFF**. Enhanced is fitted to the PR
  film — word-unit colour turn, no push, film-paced envelope — and every one of
  its statistics sits inside the film's own confidence interval, but watched
  beside the film it still read wrong and legacy read closer. **A person
  watching outranks the fit.** Legacy is also the clock every acceptance figure
  here was measured on, and is bit-identical to what it always was.
- **A WORD'S MOTION IS COLOUR AND SIZE. Weight and width do not animate** —
  they are properties of the word, applied whole for its whole life. The AE
  template carries no weight or width animator, and measured, the film's weight
  swing from a word's rest to its peak is a median of −40 against ours ramping
  +155. Enhanced-only so far; legacy still ramps.
- **WHICH WORD THE FILM ENLARGES IS NOT IN THE AUDIO, so no rule reproduces it.**
  Word for word on the same audio our emphasis correlates **−0.018** with the
  film's, and the film's own sizes correlate **−0.277** with its own soundtrack:
  they are a transcriber's judgement. Shape, timing and amplitude match; *which
  word* cannot. **Do not fit per-word sizes to the clip.**
- **THE HAND READING OF THE FILM OUTRANKS EVERY ENVELOPE MEASUREMENT.**
  `docs/reference/pr-film-annotated.txt` is annotated word by word from 28 s
  on, and where it disagrees with a statistic the annotation wins: at ~17 px
  type a 15% pop is under 3 px, i.e. beneath the envelope's own floor, and two
  rules here were wrong for exactly that reason. **Every word pops**, upward
  from the baseline, with a small lift on all of them; **weight is the channel
  the film withholds**, per line rather than per word. See `docs/MOTION.md`
  § "THE FILM, READ BACK BY HAND".
- **THE LIFT IS THE DEFAULT TREATMENT AND THE POP IS THE EXCEPTION** — decided
  at the array, against a real talker, and the film's own annotation agrees on
  a count (~30 lifts to ~8 pops). An unemphasised word **lifts and does not
  grow**; pop, crest and weight are the emphasised word's. Do not re-gate the
  lift, and do not restore a universal pop: reading the film says every word
  pops and it does, but forty at 2.5 words/s is noise where four in a held shot
  is emphasis. `word_lift_em_enhanced`; it shipped at .045em, which is under a
  pixel and was reported as the lift being ignored.
  **It was set to 0 once, on a misread, and put back the same day.** The report
  was about the crest demo on the reference PAGE, whose line box grew with the
  type; the stage cannot do that, because the crest lives on an absolute
  overlay above a hidden resting sizer. **A report about `docs/` is not a
  report about the stage** — check which one is being watched.
- **LETTERS LIFT IN SYLLABLES, and the colour still travels per letter.**
  `se|en`, `Gu|mp`, `but|ton`, `be|cause`, `say|ing`, `res|cue!` — those six are
  the film's own, and they are the tests in `web/src/lib/syllables.ts`. A fixed
  pair gets the first two right and `button` wrong. `--char-wave-delay` (the
  group's clock) and `--char-turn-delay` (the letter's) are separate and must
  stay separate.
  **THE TIMING SPLITS AT 4 LETTERS, THE LIFT AT 6** (`liftsInGroups`). The film
  staggers `se|en` at four but only raises the halves independently from six
  up, which is where all four of its split-lift words sit. Below the threshold
  a word still lifts — as one piece, on `--word-lift-em`. `--group-lift-em`
  rides on top of legacy's -.05em stretch, which alone is ~1px and is why a
  split word looked unsplit.
- **MEASURING MOTION AGAINST THE FILM:** `scripts/motion_diff.py` (size
  envelope), `scripts/word_by_word.py` (same word, same audio, as curves),
  `scripts/weight_diff.py` (does weight animate). Four rules learned the hard
  way — **a probe must read every layer**, because `character-wave` lives on
  `.caption-character` and reading only `.word-ink`/`.word-glyph` reported a
  stationary word while its glyphs travelled (`charMotion` in
  `scripts/motion_trace.py` is the fix); **watch `live --sample` before
  believing any of their numbers**, because
  a per-word envelope normalises away type size, density and rhythm; **put BOTH
  motion systems beside the reference**, because a day was lost fitting one arm
  of a two-arm choice; and **never capture with `--loop`**, because a restart
  settles words without motion and measures as a flat envelope.
- **Everything is frozen at first sight.** Duration, axes, sweep, hold gap and
  turn moment are computed once per word and must survive remounts. Recomputing
  any of them under a running animation is the bug this project re-commits most.
  **The AXES live in `WordMemo.voice`** and were the one item not implementing
  this: weight reads the speaker's RUNNING median F0, so every settled word was
  re-derived as the speaker kept talking, which flipped `--voice-envelope` and
  visibly re-ran the motion. `scripts/word_remotion.py` is the check — a
  pre-turn remount is NOT a re-motion, so it filters on a negative
  `--turn-delay`.
- **Two motion clocks, never collapsed.** `--motion-duration` (pop + wave) rides
  the speech rate; `--crest-duration` rides emphasis. Collapsing them made the
  words that matter 4.7x too fast in one direction and ordinary words 4.8x too
  slow in the other.
- **The word grows from its baseline. It does not move.** No `translateY`, no
  box-bottom pivot. Wrong four times.
- **The colour turn is a wipe across the word's characters**, and every span must
  be armed — including ones appended later, or they sit in read-ahead ink for ten
  minutes. **`voice-phase` stays on `.caption-word`**; moving it down kills every
  voice channel while the page still looks alive.
- **Size and lift are independent and mutually exclusive, and both gates are
  binary.** A word that swells does not leave the line; a word that lifts shows no
  crest and no weight.
- **Weight is a property of the VOICE, not the word** — the register term reads
  the speaker's running median F0, or a shout renders as the thinnest text in the
  film.
- **There is no clearance left: 9 px at rest, 1.0 px under motion.** Re-run
  `scripts/ink_collision.py` after any change to `voice_scale_range`, wave
  amplitude, `hold_lift_em` or `character_wave_falloff`.
- **A LATER SPEAKER CORRECTION EASES; THE TURN ITSELF DOES NOT.**
  `word-color-turn` carries no `forwards` fill, so after it runs the character
  paints from its base `color` — and the endpoint pass can revise
  `--speaker-color` seconds later, which snapped on already-read text. A
  `transition: color` on `.caption-character` covers exactly that and cannot
  touch the turn, because a running or filling animation owns the property
  outright. **Do not give `word-color-turn` a `forwards` fill** — that would
  hand `color` to the animation permanently and the transition would never
  fire.
- **Reduced motion keeps the colour turn** and drops only the geometry. Pin
  `--voice-phase: 0 !important` rather than cancelling the word's animation,
  which also carries the turn.
- **Never make the syllable fill a typewriter reveal** — progressive appearance
  destroys the read-ahead in 2.2.1.

### The playhead and the caption invariant

- **Captions present from a clock behind the acoustic one, with a per-WORD floor
  beneath it.** The delay is the lag, one for one; the floor is what actually
  delivers read-ahead, because the recognizer releases words in bursts and a time
  delay moves the mean lead without touching its spread. **Nothing is predicted.**
- **Do not gate the colour turn on speaker attribution.** Text arrives at a median
  0.62 s, durable attribution at 4.48 s. The turn happens on time in whatever
  colour is known.
- **Live motion is a function of the timeline, not of arrival.** Live behaves like
  `cc`; only the Korean/legacy path in `livepage.py` still activates at first
  paint. **Never restart the pop** for text, speaker, timing, commit or
  verification revisions.
- **Word events are not a clock source** — they are replayed to every connection,
  and an old timestamp reads as a restart. Words under an older `epoch` must
  settle, never be re-derived.
- **THE CAPTION INVARIANT IS STRUCTURAL.** A word's colour turn is a fixed moment
  on the acoustic timeline, so **text may be revised only while the word is still
  ahead of the playhead; behind it is frozen history.** Enforced by
  `settledTextRef`, not merely documented. Corrections never change a word's
  duration or axes.
- **Write `--turn-delay` imperatively, never via the `style` prop** — React
  reapplies that prop every render, and rewriting `animation-delay` shifts a
  running animation.

### The Stage stack — see `docs/LIVE.md`

- **Rows never move once laid out.** Row starts are anchored to word ids, and **a
  late word may only append, never insert.** Measured: already-read words changing
  row 7 → 3 → **0**.
- **`WordMemo` and row re-breaking ship together.** Do not re-enable one without
  the other — a word that changes row is unmounted and rebuilt, and what it
  forgets (`duration`, `holdAmount`) is the bug.
- **The stage rows never feed the motion clock.** `CaptionFeed` takes
  `timingWords` — the whole ordered recording — because deriving pace and hold
  gaps from the retained rows made layout an input to the clock.
- **Row width is per CHARACTER, not per language.** `charEm` is a LATIN fit;
  East Asian wide scripts take `wideCharEm`, measured off the live face by
  `useWideCharEm`. Charging Hangul the Latin width packed ~2x too many Korean
  words into a row and `nowrap` cut the rest silently, with no error and nothing
  on screen to show for it. **Latin widths must stay bit-identical** — a moved
  English break remounts words and puts the motion acceptance figures at risk;
  there is a test on exactly that. Check with `scripts/clip_probe.py --broken`.
- **Row width and retained row count are both measured, not configured.**
  `display.studio_stage_paragraph_history` is only the pre-measurement fallback.
- **Top-anchoring needs `top` + `max-height` + `justify-content: flex-end`, and
  all three are load-bearing** — get it wrong and the NEWEST caption is what
  vanishes. Verify by forcing `--caption-width-cap` past its measured value and
  confirming `OLDEST_clipped`.
- **There is no concurrency cap** (`max_simultaneous_reveals` is dead). Overlapping
  pops during fast speech are the design system working.
- **Never let `Attribution pending` gate the Stage stack**, and never let
  diarization or utterance segmentation decide row geometry.
- **Keep the selector tests** whenever changing reducer order, finality or
  paragraph identity.

### Speaker attribution (CWI 2.1) — see `docs/LIVE.md`

- **An undecided word publishes `speaker: null`.** `self.speaker` survives only
  where it is a fact. Defaulting to S1 measured 17 right out of 43 — the
  narrator's base rate, i.e. zero information and 26 words painted wrong. **A
  wrong colour is a false claim about who spoke, which is the one thing 2.1 exists
  to prevent; neutral is the design system's own `unknown` state.**
- **Grey is reserved for `speaker == null`.** A speaker-carrying word whose tracker
  status is unknown displays as `provisional`, or words that turned while
  attribution was pending stay grey forever. Do not resurrect the provisional
  colour-mix washes — the wipe animates toward the computed colour, and a washed
  one mutes the turn itself. Do not change `caption-paragraphs.ts`'s speaker
  null-ing either: it feeds row identity.
- **This is not a two-speaker cap.** `max_speakers` is 12. A third-or-later profile
  needs repeated clean endpoint observations **or** one long turn — gated on the
  longest single observation, never on summed durations.
- **Never replace final identity with an unverified transient Sortformer slot**,
  and never expose an unmapped native slot above the S1/S2 frontier.
- **Keep live diarization hybrid and language-complete.** Korean must receive the
  same endpoint speaker pass as English even though its text verifier is disabled.
  A failed native startup must degrade to the ONNX embedding path **without
  aborting captions**.
- **Direction is EVIDENCE in attribution, not only a stopgap (2026-08-12).**
  `SpeakerBearingMap.match()` names the speaker whose own learned bearing band
  explains a word's azimuth — a real voice-identified speaker, where
  `DirectionSpeakerMap`'s geometric slots can only say "the 2nd distinct
  direction". It fills an undecided word and may **contest** a voice decision
  below `direction_override_below`, never a `final` one, always leaving the
  word `provisional` so the endpoint pass corrects it. A bearing matching
  nobody stays unmatched — that is evidence of a NEW speaker, not of the
  nearest old one. **UNMEASURED against two real simultaneous talkers.**
- **THE CIRCULARITY GUARD IS LOAD-BEARING.** `_record_speaker_bearing` refuses
  to record a bearing under any `direction*` reason, so the bearing map is
  built from voice evidence alone and can never confirm its own guess. Relax it
  and the lane becomes a feedback loop that looks like a confident answer.
  There is a test on all three direction reasons.
- **The read-ahead lane asks Sortformer and must not `_record`** — a read-ahead
  guess must not masquerade as the durable answer an endpoint is about to correct.
- **Colour stability is a separate question from colour correctness**, and needs
  its own measurement: a 45.9% → 29.2% correctness win left the flicker untouched.
- **The four-slot ceiling is structural and the preset A/B is settled** — every
  Sortformer variant lands at 49.7–50.9% correct, and fp16 is a no-op at 2.5x the
  size. Do not re-litigate without a new measurement.
- **Agreement is not accuracy.** Always score identity *structure* (speakers and
  switches per utterance) beside it — that is what caught mid-utterance
  verification silently merging every speaker into one.

### Audio, language, and the voice instrument — see `docs/LIVE.md`

- **Input gain applies only to the recognizer's copy of the audio.**
  `AudioChunk.samples` must stay at the true captured level because prosody
  measures `loudness_db` from it; the gained copy is `asr_samples`. Gaining before
  that measurement would flatten whisper and shout to one size.
- **There are THREE capture profiles, and `multi` is an ADDITION.** `en` and
  `ko` keep their own models untouched (2.27% WER / 10.54% CER); `multi` is
  Nemotron 3.5 ASR 0.6B, 40 locales in one model, for sessions where both
  languages are spoken including inside one sentence. **Do not make `multi` the
  only model** — it A/B'd worse on English here (3.25% vs 2.27%), so replacing
  the English path with it trades a 43% relative English regression for the
  Korean win.
  **Its language is a PER-STREAM option, not a recognizer argument.** The
  multilingual encoder takes a 6th input (`prompt_index`), exposed as
  `stream.set_option("language", "auto")`, so `_new_stream` applies it at every
  stream creation **including the reset after each endpoint** — a stream opened
  without it silently decodes under the model's default.
  **It needs sherpa-onnx from master** (PR #3671, merged but unreleased);
  `requirements.txt` says so and pinning back to 1.13.4 disables only this
  profile. See `docs/KOREAN-ASR.md`.
- **Language is a pre-capture model decision.** Never make the selector cosmetic
  or hot-swap a recognizer under retained decoder/audio state. **A language flag
  alone does not switch languages** — `_configure_live_language()` is what swaps
  `streaming_model_dir` and disables the English sidecars; setting `live.lang`
  alone transcribed Korean at 100% CER.
- **Korean caption motion requires the local variable font.** Roboto Flex has no
  Hangul outlines; a static system fallback is degradation for a missing download,
  not the intended rendering.
- **The per-CHARACTER channel is script-sensitive, and Korean gets a continuous
  wipe.** A Hangul block is 0.91em against Latin's 0.43em, so a per-glyph step
  moved the colour boundary 2.1x further and 46% of Korean words had <=2 steps —
  a switch, not a sweep, in the channel that carries ordinary words. Wide script
  now sweeps a clipped overlay instead. **Both ink layers carry the same
  character spans** so they stretch together; `background-clip: text` cannot do
  this. `--wipe` rests at 100% with a `from`-only keyframe, exactly like
  `word-color-turn`. `Settings → Hangul-shaped motion` (default OFF) additionally
  orients the wave along each syllable's own composition axis.
  **`wordIsWide` must never return true for an all-Latin word** — that is what
  keeps English on its existing path, and there is a test on it.
- **Korean word-level motion is NOT broken — measured, it matches English**
  (median peak 1.14x vs 1.16x, 29% vs 29% of words above 1.20x, max weight 893 vs
  858, and it lifts). **The gap is the MATERIAL:** `sample-ko.wav` is 13.3 s of
  neutral read FLEURS narration at -53 dBFS, so the words that grow are arbitrary
  content nouns nobody emphasised. **Do not re-fit any prosody constant for Korean
  against it** — record Korean audio with intentional prosody first. See
  `docs/KOREAN.md`.
- **`font-stretch` is inert in Korean** — `NotoSansKR.ttf` has only a `wght` axis,
  so §2.3.10 is silently dropped. It is also nearly inert in English (99.3% of
  word-samples render at exactly 100%), so this is worth knowing and not worth
  fixing; no Korean variable font has a width axis anyway.
- **Keep the voice instrument outside the glyphs.** Completed captions must never
  shake because a later audio block arrived. `delivery_profile` is a descriptive
  acoustic readout. **Do not infer or label emotion.**
- **Never fabricate direction in the DATA — the dial may still draw one.**
  With a mic array attached, `direction_deg` reaches the level event and
  durable words; with a local mic, no array, or a reading older than the TTL,
  **the field stays absent**, because `autocwi/haptics.py` drives motors from
  it and a defaulted bearing would point the ring at nobody. That half does not
  move. **The DISPLAY falls back to front/0°** (2026-08-13, at the user's
  direction) rather than going inert, and carries `data-measured="false"` so
  the needle and rim hold back until a reading is real.
- **Haptics actuate on flags, never on every word, and never on raw direction.**
  `speaker_change`/`emphasis` gate every cue; direction rides on the WORD.
  Driving motors from the DoA stream is the continuous vibration *Tactile
  Emotions* (CHI '25) measured as distracting, and it is the one thing this
  module exists not to do. **One motor cannot encode direction** — a
  single-motor build pulses the whole ring and claims nothing about where.
- **The hardware node analyses nothing.** The Pi Zero 2 W cannot host the
  recognizers (512 MB against 600 MB-per-model weights), so it captures and
  actuates while the Mac decides — which also keeps the salience decision beside
  the speaker tracker. See `docs/HARDWARE.md`.
- **Speech emotion/intention is research-only.** Before adding a model, benchmark
  Korean macro F1 on KEMDy20 + booth audio, local RTF, and its license. Freeze a
  smoothed estimate only onto future/unseen words — **never use an utterance-end
  result to animate or reweight historical words.**
- **The onset sidecar is OFF** (`live.onset_prefix.enabled: false`). It fired at
  the start of every sentence and was ~40% of all visible churn. **Do not confuse
  it with CWI 2.2.1 read-ahead**, which is the design system's uncoloured preview
  of the line.
- **Live capture is lossless.** Keep deadline-based file pacing and drain queued
  microphone blocks into catch-up batches; normal backlog skipping caused missed
  words.
- **Endpoint verification reconciles per word** — matches corrected in place,
  deletions dropped, insertions added at their spoken position. **Never tear an
  utterance down and re-render it**; a structural mismatch fires on almost every
  utterance, and a block rebuild makes each sentence flash at every pause.
- **Do not reduce `live.endpoint_silence_s`** for finer sentences (WER 2.27% →
  8.77% at 0.6 s), and **do not release the held-back trailing word early** —
  measured, it saves nothing and commits truncated spellings.
- **Haptics: subscribe only to final `type: "word"` events**, and actuate on the
  `speaker_change`/`emphasis` salience flags, never every word.
  `autocwi/haptics.py` owns the salience -> actuation mapping and the bearing ->
  motor mapping; `scripts/hw/` is the Pi node and its probes.

## Measuring

**Screenshot before judging visuals.** Three numeric probes called a
glyph-anchoring change "probably fine"; one screenshot showed words overlapping
and clipped off the stage. Typography and layout bugs are visual.

**Use `scripts/word_motion.py`, not an ad-hoc aggregate** — and key it by
`word_id`, since it keys by `(index, text)` and a layout change moves every index.
Anything touching the chunker must be fingerprinted with it before and after.
Four ad-hoc metrics gave confidently wrong answers in one session before it
existed.

`docs/TESTS.md` has the rest: which probe answers which question, the headless
Chrome recipe (`--timeout`, never `--virtual-time-budget` — SSE never idles), how
to measure the film as a continuous curve, and the full catalogue of ways this
measurement has produced a confident wrong answer. Read it before writing a new
probe; most of them have already been written once and been wrong.

## Gotchas

- `HF_TOKEN` required for real diarization (pyannote weights are gated; also
  accept terms on `pyannote/speaker-diarization-3.1` and
  `pyannote/segmentation-3.0`). Without it, use `--stub`.
- Whisper models auto-download on first use. CTranslate2/faster-whisper runs
  CPU-only on Apple Silicon (int8); MPS is used by pyannote/torch only.
  `--whisper MODEL` is the legacy pause-segmented comparison path.
- Live `fast` mode uses the local 1120 ms English Nemotron 0.6B profile plus
  Parakeet Unified for durable endpoint text. The 160 ms profile loads only under
  `display.mode: readahead` — running it behind fast mode while hiding its output
  caused avoidable decoder backlog.
- Korean uses `assets/streaming-zipformer-ko-174m/`, the **chunk-32** int8 causal
  export. `verifier_enabled`, `draft_enabled` and the English TIMIT `onset_prefix`
  are false in the `ko` overlay. Do not pass Korean through English sidecars or
  overwrite it with the weaker 2024 Korean endpoint model. **The lever is latency,
  not weights:** chunk-64 wins on text and is disqualified on time (a word lands
  at p90 1552 ms, leaving 198 ms before the turn — under `min_read_ahead_ms`, so
  2.2.1 read-ahead would be gone). `modified_beam_search` is worse here despite
  the model card's table. **Measure FIRST PAINT, not the durable word** — scoring
  only `type: "word"` events puts the lag a whole endpoint late and would have
  disqualified every arm including the shipped one.
- Apple-Silicon live diarization uses `native/sortformer/.build/release/
  autocwi-sortformer` plus `assets/sortformer-coreml/`. FluidAudio is pinned to
  0.15.5. Score Sortformer overlap by activity, not duration.
- Live server binds 127.0.0.1:7337, falling back to :7338…:7346. A leftover
  process is the usual cause — `pkill -f "autocwi live"`. macOS mic permission is
  per terminal app on first live run. When running the CLI in background with
  redirected output, set `PYTHONUNBUFFERED=1` or output is lost on kill.
- A studio stuck on "Preparing language setup" with a healthy backend is a torn
  `web/out` (index.html referencing 404 chunk hashes) — rebuild, and **do not
  build while a live server is serving that directory.**
- Cold start is ~7.6 s of model loading (GIL-bound; parallelizing barely helps).
  The server/page open FIRST with `boot` status events; "listening" appears only
  when capture is real.
- **Never edit a `@keyframes` stop with a first-occurrence string replace.**
  `globals.css` has several animations sharing the same percentages; a replace
  intended for `word-hold-spring` landed in `voice-phase`, flattening the pulse and
  leaving the spring's stops out of order. The build stays green and the page
  still looks animated. After any keyframe edit, print every animation's stop list
  and assert it is sorted.
- `scripts/baseline_probe.py --settle` defaults to **76.0** (the sample length) on
  purpose. A small value cuts the probe off before the stage fills and it reports
  "only N word-measurements — nothing to conclude". **That means the run is
  INVALID**, not that the check passed.
- **The reference-replay regression test already exists** —
  `test_derived_reference_specs_replay_the_recordings` in `tests/test_live.py`,
  NOT `test_reference.py`. Do not add a second one.
- **Reference-spec derivation and the .aep provenance live in a skill:**
  `.claude/skills/derive-reference-spec/SKILL.md`. Invoke it before touching that
  pipeline; do not re-derive from scratch.

## State / open threads

- **THERE IS EXACTLY ONE BENCHMARK: `scripts/benchmark.py` on FLEURS.** Do not add
  a second. `--stress`/`--quiet-sweep` are *conditions on that set*, not separate
  benchmarks. **Never quote `0/77 clean`** — it came from the vendor's own demo
  clips and is circular. Recognizer choice is measured, not assumed: Nemotron 3.5
  A/B'd worse on English (3.25% vs 2.27%), so English stays on the 2026-04-25
  model. Re-run that A/B before swapping any checkpoint.
- **The benchmark scores timing as well as text** — a backend with better words
  and worse spans is a downgrade here.
- **Korean is 10.54% CER normalized / 13.23% raw** on 120 FLEURS ko clips. Do not
  quote 5.19%, and do not fetch fewer than ~120 clips. Full numbers, the stress
  matrix and its two caveats are in `docs/TESTS.md`.
- **`assets/sample-ko.wav` is row 16 of that eval set** — the Korean demo clip is
  *not* held out, so a good result on it is not independent evidence.
- **`docs/reference/pr-film.mp4` has no reference transcript**, so it cannot be scored —
  only compared across backends. Do not derive a reference from a model's own
  output. It IS the PR film. Note the film does caption the Gump clip (t=28–36 s)
  despite its transcript saying "[No on screen captions]", and the first "GUMP!"
  is never recognized at all — **check recognition before blaming motion.**

Open, not started:

- **Offline pyannote diarization has never been run** (needs `HF_TOKEN`), and
  should move to `speaker-diarization-community-1` after isolating the pyannote
  4.x dependency.
- **The haptic module ships but has never run against real motors.** The
  mapping and the wire protocol are tested offline; Phase 0 of
  `docs/HARDWARE.md` (does the array report DoA, does a motor turn) needs the
  hardware and has not been done. **The Pi itself is now provisioned and
  reachable over SSH** — see `docs/HARDWARE.md` § Reaching the Pi, which also
  says why `requirements.txt` must not be installed on it.
- **The Korean endpoint verifier is off, and the best candidate to turn it on
  with is Qwen3-ASR-0.6B** (Apache-2.0, 0.9B, best open Korean CER on
  OpenKoASR, MLX build for Apple Silicon). It cannot replace the STREAMING
  model — its streaming mode returns no timestamps, the same disqualifier
  OpenAI's streaming models carry — but as a text-only endpoint verifier it fits
  the existing English architecture exactly, and a full-utterance pass is the
  specific fix for Korean's largest error category, the first word of an
  utterance. Desk research only; see `docs/KOREAN-ASR.md`. It is off today
  because a 2024 offline model once changed a correctly-recognized phrase — a judgement made on four bundled
  utterances, now re-testable against 120 scored clips. It adds a revision lane.
- **A quiet Korean talker is a genuine booth risk.** At matched ~14–15 dB SNR,
  absolute level alone costs 3.3x accuracy, and gain reaches the recognizer
  without restoring it — so `input_gain`'s target/headroom deserves a pass against
  the Korean model specifically.
- **The residual first-paint colour error needs a better provisional pass**, not a
  better Sortformer preset: a wider context, or running the endpoint embedding at
  segmentation boundaries inside one turn.
