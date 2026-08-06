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
}

export interface MotionDurationSettings {
  wordMotionBaseMs: number;
  wordMotionMaxMs: number;
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
): number {
  const push = clamp(Number.isFinite(emphasis) ? emphasis : 0, 0, 1);
  const floor = Math.min(settings.wordMotionMinMs, settings.wordMotionMaxMs);
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
