---
name: derive-reference-spec
description: Use when re-deriving a CWI reference spec from the recordings in docs/reference/*.mov (scripts/derive_reference_spec.py), measuring per-glyph or per-word motion off video frames, or checking where a motion amplitude originally came from — including the After Effects template (AE PROJECT/Academy_CI_Template.aep). Carries the crop values, fps, segmentation traps, and the fitted measurements.
---

# Deriving a CWI reference spec

Extracted from CLAUDE.md so it loads on demand. Every entry below is a
hard-won measurement or a trap that cost real time — read the relevant one
before touching `scripts/derive_reference_spec.py` or the `refmeasure` path.

## The derivation pipeline

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
- **THE DERIVATION IS REPRODUCIBLE — verified 2026-07-30.** Re-deriving
  `synchronization` reproduced the committed
  `assets/reference_specs/synchronization.json` exactly: same 18 words, identical
  text, **0.0 ms** start/end delta, 0.0000 loudness delta, 10 distinct loudness
  values both. Only `pitch_hz` moved, by ≤0.58 Hz, from passing fps 57.126
  instead of 57.13. The committed fixtures are current and the pipeline is
  deterministic, so a future mismatch means a real change, not noise. The
  incantation (473 frames, 8.28 s):
  `ffmpeg -i docs/reference/synchronization.mov -vf "crop=3456:210:0:1075"
  -vsync 0 /tmp/sync/n_%04d.png`, then `derive_reference_spec.py --frames
  "/tmp/sync/n_*.png" --fps 57.126 --transcript
  docs/reference/synchronization.txt --rotate 3`. Residuals were 6–29 ms and the
  documented sanity check holds: synchronization demonstrates TIMING, so its
  emphasis is essentially uniform (0.94–1.06) apart from the animated
  `Synchronization` heading at 1.18 and the held `is` at 0.87.
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
- **Deriving WEIGHT: use an ABSOLUTE density deadband, never the phrase's own
  maximum.** Normalising each phrase by its largest deviation stretches the
  biggest NOISE deviation to full bold whenever nothing in that phrase is
  actually emphasised — which is why bold kept landing on the wrong words.
  Measured, real emphasis is unmistakable: "weights" +0.53 and "louder" +0.19
  in ink density against +-0.09 for everything else. `weight_deadband: 0.12`
  and `weight_full_dev: 0.55` separate them and keep magnitudes comparable
  across phrases.
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
- **SIZE and WEIGHT are two channels and need two measures.** Size = median ink
  HEIGHT across the word's glyphs; weight = median ink DENSITY
  (ink pixels / bbox area), which is invariant to the size envelope — a word
  that merely grows keeps its density, one that thickens raises it. That is the
  only thing that separates "sizes," (large, normal weight) from "weights"
  (normal size, bold); height alone reports "weights" as no emphasis at all,
  which is *correct for height* and useless as a weight signal.
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

## Provenance: the After Effects template

The `.aep` is the original source for the SHAPE of the motion. Where it and the
design system PDF disagree on AMPLITUDE, the PDF wins — see the PDF entry in
CLAUDE.md.

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
- **The template is position + colour only — but PDF §2.2.3 is authoritative.**
  `grep` the .aep: `ADBE Text Scale`,
  `Tracking`, `Size`, `Rotation`, `Skew`, `Opacity` all occur **zero** times;
  the four animators touch only `ADBE Text Position 3D` and
  `ADBE Text Fill Color`, and their expressions return `[x,y]`, so no Z either.
  That is the stricter, calmer reading of the system and is what
  `wave_reach: 0` gives. The recordings in `docs/` are the website — a
  different implementation — and it animates the active word's size and weight
  (see the bullet above). Both live and `cc` retain the PDF's required,
  constant +15% pop; do not "fix" them back to the template's omission.
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
