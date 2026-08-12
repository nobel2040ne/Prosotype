/**
 * How LONG a word's CWI 2.2.3 cue runs. WHEN it runs belongs to the playhead
 * (`caption-clock.ts`), and the browser schedules it.
 *
 * Everything else this module used to hold existed to make an arrival-ordered
 * reveal queue survive: median acoustic gap estimation, backlog measurement, a
 * staleness ceiling, an adaptive clock that shortened motions under pressure,
 * and a watchdog for concurrency slots that never painted. A presented word is
 * now placed by its own recorded onset, so there is no queue to keep fed, no
 * backlog to drain and no slot to reclaim. Deleted 2026-08-01.
 */

export interface MotionTimingWord {
  start?: number;
  end?: number;
  t?: number;
  utterance?: number;
  delivery_flow?: number;
  /** Fraction of the word's span that is actually voiced. See below. */
  voiced_frac?: number;
}

export interface MotionDurationSettings {
  /**
   * When true the motion lasts as long as the word was actually SPOKEN.
   *
   * `word.end` runs to the NEXT word's onset -- the recognizer attributes no
   * silence to anything -- so the span is an inter-onset interval, not speech.
   * Multiplying by `voiced_frac` recovers the real thing, and the two agree:
   * measured against an energy-gated voiced span computed straight off the
   * film's audio, `span x voiced_frac` correlates +0.765, medians 0.170s and
   * 0.200s.
   *
   * The gap this closes is large. Our `--motion-duration` ran a median 580ms
   * against 170ms of actual speech -- 3.4x too long -- so a word was still
   * animating two words after it stopped being said.
   */
  wordMotionFollowsSpeech: boolean;
  /** Animation length per second of speech. See `word_motion_speech_scale`. */
  wordMotionSpeechScale: number;
  wordMotionBaseMs: number;
  wordMotionMaxMs: number;
  /** Floor for the speech-following clock. */
  wordMotionSpeechFloorMs: number;
  wordMotionSpanStretch: number;
  wordMotionMinMs: number;
  /** Ceiling for the 2.2.3 pop, which must stay crisp however slow the talk. */
  wordMotionPopMaxMs: number;
  deliveryFlowDurationMs: number;
}

/**
 * THERE ARE TWO CLOCKS, AND COLLAPSING THEM INTO ONE IS WHY THIS KEPT MISSING.
 *
 * The After Effects template animates POSITION and COLOUR only -- it has no
 * scale animator at all -- so its one-word-wide selector, and the speech-rate
 * window that falls out of it, govern the BOUNCE. The SIZE crest is the PDF's
 * (2.2.3's +15% pop, 2.3.6's range), the template has nothing to say about how
 * long it takes, and the recordings show it running far longer:
 *
 *   peak 1.05-1.20 (37 of 43 words, barely move)   span above half  0.160s
 *   peak 1.20-1.45 (noticeable)                                     0.240s
 *   peak 1.45-3.00 (the ones a viewer actually sees)                1.560s
 *
 * Driving both from the speech rate made the words that matter ~4.7x too fast
 * ("too fast at a glance"); driving both from the crest made ordinary words
 * ~4.8x too slow. So the pop rides the speech rate and the crest rides the
 * emphasis, which is what the two CSS variables were always for.
 *
 * `FWHM ~= 0.76 x window` for this envelope, so 0.16s wants ~210ms and 1.56s
 * wants ~2050ms -- `wordMotionMinMs` and `wordMotionMaxMs`.
 */
/**
 * Emphasis at which a word stops pulsing and starts HOLDING its peak.
 *
 * Exported so the stylesheet's envelope choice and the window below cannot
 * drift apart: a word given the hold envelope must also be given enough window
 * to hold in, or it reads as a pulse with a longer tail.
 */
export const HOLD_ENVELOPE_EMPHASIS = 0.5;

export function crestWindowMs(
  emphasis: number,
  settings: MotionDurationSettings,
  spokenMs?: number,
): number {
  const push = clamp(Number.isFinite(emphasis) ? emphasis : 0, 0, 1);
  /* THE FLOOR IS THE WORD'S OWN SPEECH, not a constant, when the clock follows
     the speaker. It used to be a flat `wordMotionMinMs` (520ms), so every word
     -- however briefly said -- held its size for at least half a second, and
     the crest ran a median 3.1x the 170ms actually spoken.

     This is NOT the collapse this file warns about. Collapsing meant driving
     the crest off the SPEECH RATE and losing emphasis, which made emphatic
     words 4.7x too fast. Here the emphasis term is untouched -- still cubed,
     still reaching `wordMotionMaxMs` -- and only its BASE moves from a constant
     to the word's own duration, so an ordinary word tracks the speaker and an
     emphatic one still stretches far past it. */
  const floor = settings.wordMotionFollowsSpeech && spokenMs
    ? clamp(spokenMs * Math.max(0.1, finite(settings.wordMotionSpeechScale, 1)),
            settings.wordMotionSpeechFloorMs, settings.wordMotionMaxMs)
    : Math.min(settings.wordMotionMinMs, settings.wordMotionMaxMs);
  // CUBED, because the reference's curve is flat and then steep, not linear.
  // Its three bands are 0.160s / 0.240s / 1.560s: almost nothing happens until
  // a word is genuinely emphatic, and then it more than sextuples. A linear
  // ramp put the middle band at 0.712s against the reference's 0.240s --
  // measured -- because emphasis 0.5 is only halfway up the range but nowhere
  // near halfway up the reference's duration.
  // SQUARED WAS TRIED AND MEASURED WORSE on both bands that moved: the middle
  // went 0.266s -> 0.439s against a 0.240s reference, and the top 1.097s ->
  // 0.915s against 1.560s. Note the two runs disagree by more than that, since
  // the recognizer puts different words in each band each time -- so anything
  // finer than this is fitting noise, not the reference.
  // FLOORING THIS FOR THE HOLD BAND WAS TRIED AND MEASURED AS A NO-OP: the
  // band moved 0.694s -> 0.692s against a ~1.0s target, so it was reverted
  // rather than shipped. The remaining shortfall is in how emphasis maps to
  // this window, not in the window's floor.
  return floor + push ** 3 * Math.max(0, settings.wordMotionMaxMs - floor);
}

/**
 * HOW LONG A WORD MOVES: ONE WORD, AT THE CURRENT SPEECH RATE.
 *
 * Straight out of the After Effects template the design system was authored in
 * (`AE PROJECT/Academy_CI_Template.aep` -- not in the tree, recoverable from
 * the first commit; RIFX, walk it with a chunk parser and the expressions come
 * out as plain text). All four animators share ONE range selector, exactly one
 * word wide (`Index End = start + 1`), whose start is swept by
 *
 *     ease(time, inTime, outTime, 0, textLenWords)
 *
 * between the layer's [START]/[END] markers. A one-word-wide window crossing
 * `textLenWords` words in `outTime - inTime` sits on each word for
 * `lineDuration / wordCount` -- the local speech rate.
 *
 * SO THE DURATION DOES NOT DEPEND ON THE WORD'S SIZE. Every previous attempt
 * here assumed it did, in one direction or another: a near-constant clock
 * first, then a ramp keyed on the crest. The ramp was fitted to the .mov
 * recordings, where peak size and motion FWHM correlate at +0.69 -- but those
 * recordings are the design system's WEBSITE, a different implementation, and
 * the skill that documented the template says so outright: "READ THE .aep. It
 * is the original source; the recordings are not."
 *
 * The interval to the next word's onset is that same quantity measured live,
 * and it is exactly what one word of lookahead buys.
 */
export function motionSpreadMs(
  paceGapS: number,
  settings: MotionDurationSettings,
): number {
  const pace = Number.isFinite(paceGapS) ? paceGapS * 1000 : 0;
  // No next word yet (the last word of a capture): fall back to the authored
  // base rather than collapsing to the floor.
  const window = pace > 1 ? pace : settings.wordMotionBaseMs;
  return clamp(
    window,
    Math.min(settings.wordMotionMinMs, settings.wordMotionBaseMs),
    settings.wordMotionPopMaxMs,
  );
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * A word's position on the shared acoustic timeline, in ms.
 *
 * `t` is `stream_base + word.start` — seconds since capture began, the same
 * timeline `level.t` reports — so it is directly comparable with the playhead.
 */
export function acousticTimeMs(word: MotionTimingWord | undefined): number {
  if (!word) return Number.NaN;
  const seconds = finite(word.t, Number.NaN);
  if (Number.isFinite(seconds)) return seconds * 1000;
  const start = finite(word.start, Number.NaN);
  return Number.isFinite(start) ? start * 1000 : Number.NaN;
}

/**
 * The one-shot window, stretched a little by the word's own spoken span so a
 * drawn-out word reads as languid rather than as the fast shape slowed down.
 */
export function naturalMotionDurationMs(
  word: MotionTimingWord,
  settings: MotionDurationSettings,
  paceGapS = 0,
): number {
  const spokenMs = Math.max(
    0,
    finite(word.end) - finite(word.start),
  ) * 1000;
  const flow = clamp(finite(word.delivery_flow), 0, 1);
  if (settings.wordMotionFollowsSpeech) {
    /* THE MOTION LASTS AS LONG AS THE WORD WAS SPOKEN, which is the whole
       point of a synchronised caption and is not what the other branch does.
       `voiced_frac` is what turns the recognizer's inter-onset span into real
       speech; without it a word followed by a pause reads as a long word.
       Still floored, because a 60ms animation is a flicker rather than a cue,
       and still capped by the pop ceiling. */
    const voiced = clamp(finite(word.voiced_frac, 1), 0, 1);
    const spoken = spokenMs * (voiced > 0 ? voiced : 1);
    /* SCALED, because the visible part of an envelope is about half its length.
       Equating the TOTAL to the spoken duration put our half-width at 0.49x the
       word's speech against the film's 1.18x, i.e. visibly too fast. */
    const scale = Math.max(0.1, finite(settings.wordMotionSpeechScale, 1));
    return clamp(spoken * scale, settings.wordMotionSpeechFloorMs,
                 settings.wordMotionPopMaxMs);
  }
  // `motionSpreadMs` is the channel; the span and flow terms stay as the
  // second-order shaping they always were.
  return clamp(
    motionSpreadMs(paceGapS, settings)
      + spokenMs * settings.wordMotionSpanStretch
      + flow * settings.deliveryFlowDurationMs,
    Math.min(settings.wordMotionMinMs, settings.wordMotionBaseMs),
    settings.wordMotionPopMaxMs,
  );
}

/**
 * How long the CWI 2.3 voice crest takes, given how long the colour wipe
 * needs to cross the word.
 *
 * THE CREST MUST NOT LEAD THE WIPE. `@keyframes voice-phase` reaches full
 * phase at its literal 50% stop -- the peak of the raised-cosine hump (a
 * keyframe selector cannot take a `var()`, so 0.50 here and that stop change
 * TOGETHER). On the natural duration
 * that rise takes ~150-200 ms, while the per-character colour turn crosses a
 * long word in up to `wordMotionMaxMs` — so the word ballooned while most of
 * its letters were still uncoloured. The PR film never moves a word ahead of
 * its colour: in "weigh|ts" the size arrives WITH the sweep. Stretching the
 * crest window so phase 1 lands as the wipe completes reproduces that; for
 * the median word (sweep well under 28% of the natural window) this is a
 * no-op, so only the words that exhibited the defect change.
 */
// The EARLIER of the two envelopes' peaks (`voice-phase-hold` reaches full
// phase at 24%; the pulse at 50%), so the guard below holds under either.
export const VOICE_PHASE_RISE_FRACTION = 0.24;

/**
 * Where the FILM envelope peaks, as a fraction of its own window.
 *
 * `voice-phase-film`'s stops put the peak at 35.7%, and the split envelopes
 * (`voice-phase-film-rise` / `-fall`) are that same curve cut at exactly this
 * point. It is here rather than inline because the CSS and the durations
 * computed for it have to agree: if they drift, the rise animation ends
 * somewhere other than the peak and the word visibly steps.
 */
export const FILM_PEAK_FRACTION = 0.357;

/**
 * How long a word's return should last so its motion reaches the next word.
 *
 * MEASURED before this existed: 42% of samples had nothing moving on the
 * stage, in 22 dead gaps with a median of 0.21s and a longest of 2.31s. A word
 * popped, stopped dead, and the next started from nothing.
 *
 * The RISE is never stretched -- the moment a word starts growing is the
 * moment it is spoken, which is what CWI 2.2.2 is about -- so all of the
 * filling happens here, in the return.
 *
 * `gapS` is the interval to the NEXT word's onset, and is 0 until that word
 * has arrived.
 *
 * WITH NO NEIGHBOUR YET, THE TAIL IS LONG BY DEFAULT -- `unknownMs` -- and this
 * is the whole trick. The obvious way round is to wait for the neighbour and
 * use the real gap, and it cannot work: a word turns 1.75s after it arrives,
 * while the word after a two-second pause lands about half a second AFTER
 * that, so the gap that most needs filling is the one that arrives too late to
 * use. Changing the duration then would restart a running animation, which is
 * a word visibly running its motion twice.
 * So the default is generous and is never revised. A neighbour that turns up
 * early simply starts its own motion over this one's tail -- overlapping
 * motion is the design system working, and there is no concurrency cap.
 *
 * Capped: a word still easing four seconds later reads as a stuck animation
 * rather than as continuity.
 */
export function fallDurationMs(
  crestMs: number,
  gapS: number,
  maxMs = 4000,
  unknownMs = 900,
): number {
  const naturalFall = crestMs * (1 - FILM_PEAK_FRACTION);
  const riseMs = crestMs * FILM_PEAK_FRACTION;
  const gap = finite(gapS);
  const toNextTurn = gap > 0
    ? Math.max(0, gap * 1000 - riseMs)
    : unknownMs;
  return Math.min(maxMs, Math.max(naturalFall, toNextTurn));
}

/**
 * The two parts of that tail: the film's own return, then a long low drift.
 *
 * STRETCHING THE WHOLE RETURN IS WHAT MADE THE JOIN LOOK BROKEN. A word rose
 * in 151ms and came down over 900ms, which is a 6:1 asymmetry the film never
 * has -- its own is 151:273 -- so the curve visibly cornered at the peak even
 * after both sides were flattened into it. Measured, flattening further did
 * nothing (53% -> 55%, noise): the peak SHAPE was not the problem, the peak
 * SPEED RATIO was.
 *
 * So the film's return runs at the film's speed, all the way down to a low
 * residual, and only what is left over is stretched. The shape a viewer reads
 * as "the word coming down" is then exactly the reference's, and the filling
 * happens where the amplitude is too small to have a shape at all.
 *
 * TRIED AND REVERTED (2026-08-13), and kept here because the reasoning is
 * sound and the measurement is the useful part. It did NOT improve the join
 * (54% against 55% -- noise) and it made the stage deader, 16% -> 27% of
 * samples with nothing moving, because a drift from 0.12 to 0 is below the
 * amplitude anything can see.
 *
 * WHAT THE MEASUREMENT ACTUALLY SAYS: the residual ~54% "step" at the join is
 * not a defect, it is the FILM'S OWN ASYMMETRY. Its envelope rises over 35.7%
 * and falls over 64.3%, a 1.8x speed ratio, which is exactly a 45-55% step by
 * this measure. Rounding both sides into the peak took it from 76% to 53% --
 * that was the real corner -- and everything after that was chasing noise.
 * Do not re-fit this without a probe that samples faster than 30ms.
 */
export function tailSegmentsMs(
  crestMs: number,
  totalFallMs: number,
): {fallMs: number; driftMs: number} {
  const naturalFall = crestMs * (1 - FILM_PEAK_FRACTION);
  const fallMs = Math.min(naturalFall, totalFallMs);
  return {fallMs, driftMs: Math.max(0, totalFallMs - fallMs)};
}

export function crestDurationMs(
  sweepMs: number,
  naturalMs: number,
  emphasis = 1,
  maxMs = Number.POSITIVE_INFINITY,
): number {
  const sweep = Math.max(0, finite(sweepMs));
  // ...AND THE STRETCH SCALES WITH THE CREST, or it becomes the floor.
  // This rule exists because a word BALLOONED while most of its letters were
  // still uncoloured -- a problem only when there IS a crest to lead. Applied
  // flat it forces a 480 ms window on a 160 ms word (FWHM 0.37 s) against the
  // reference's 0.16 s, so it, not the duration channel, would decide how fast
  // an ordinary word moves.
  const push = clamp(Number.isFinite(emphasis) ? emphasis : 1, 0, 1);
  // ...AND IT MAY NEVER EXCEED THE CONFIGURED CEILING. This stretch used to
  // override `wordMotionMaxMs` outright, and on the film's "louder" it ran the
  // crest for 2.9s against the reference's ~1.05s -- MEASURED on screen, the
  // return from peak to normal took **1.56s where the film takes 0.25s**, and
  // that is what reads as the motion refusing to let go. Dividing a sweep of
  // up to `wordMotionMaxMs` by 0.24 is a 4.2x multiplier; nothing bounded it.
  const ceiling = Number.isFinite(maxMs) ? maxMs : Number.POSITIVE_INFINITY;
  return Math.min(
    Math.max(finite(naturalMs), push * sweep / VOICE_PHASE_RISE_FRACTION),
    Math.max(finite(naturalMs), ceiling),
  );
}

/**
 * WHEN A SINGLE LETTER TURNS, relative to the moment the playhead reaches its
 * word. The 2.2.2 turn is a WIPE, not a switch -- the PR film puts the colour
 * boundary inside a word constantly ("weigh|ts", "instantly kn|ow") -- so each
 * character is offset across the word's spoken sweep.
 *
 * `perWord` is the letter count the wipe was LAID OUT ACROSS, frozen when the
 * word armed, and it is deliberately not the current length. Live words grow
 * after they are armed: the endpoint verifier appends punctuation, a respelling
 * lengthens the word. Dividing by the CURRENT length would move every existing
 * letter's place in the wipe, so a character arriving late could be handed an
 * earlier moment than one already running and the boundary would travel
 * backwards through text the viewer is reading. Past the frozen count the wipe
 * is over, so a late letter turns with the last one.
 */
export function charTurnDelayMs(
  turnDelayMs: number,
  index: number,
  perWord: number,
  sweepMs: number,
): number {
  const span = Math.max(1, finite(perWord));
  const at = Math.min(1, Math.max(0, finite(index)) / span);
  return Math.round(finite(turnDelayMs) + at * Math.max(0, finite(sweepMs)));
}

/*
 * THE PR FILM'S OWN CLOCK, measured off `docs/reference/pr-film.mp4`
 * rather than fitted. Both are ENHANCED-only; legacy keeps its own timings and
 * every acceptance figure measured on them.
 *
 * `FILM_WORD_TURN_MS` -- how long a word takes to change colour. The film's AE
 * template drives its range selector in WORD units, and the frames agree: at
 * 24fps a word spends exactly ONE frame between <15% and >85% turned, i.e. it
 * turns as a unit. That is 42ms; 80ms is a deliberate softening so the turn is
 * not a hard cut at display refresh, and so every per-character span still gets
 * armed rather than being skipped as a zero-length animation.
 *
 * (The size cue's WINDOW is `live_sync.studio.word_motion_enhanced_ms` in
 * config.yaml, fitted with `scripts/motion_diff.py`, not a constant here.)
 */
export const FILM_WORD_TURN_MS = 80;
