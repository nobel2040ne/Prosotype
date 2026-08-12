/** How LONG a word's CWI 2.2.3 cue runs. WHEN it runs belongs to the playhead
   (`caption-clock.ts`), and the browser schedules it. */

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
  /** When true the motion lasts as long as the word was actually SPOKEN. */
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

/** THERE ARE TWO CLOCKS, AND COLLAPSING THEM INTO ONE IS WHY THIS KEPT
   MISSING. */
/** Emphasis at which a word stops pulsing and starts HOLDING its peak. */
export const HOLD_ENVELOPE_EMPHASIS = 0.5;

export function crestWindowMs(
  emphasis: number,
  settings: MotionDurationSettings,
  spokenMs?: number,
): number {
  const push = clamp(Number.isFinite(emphasis) ? emphasis : 0, 0, 1);
  /* THE FLOOR IS THE WORD'S OWN SPEECH, not a constant, when the clock
     follows the speaker. */
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

/** HOW LONG A WORD MOVES: ONE WORD, AT THE CURRENT SPEECH RATE. */
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

/** A word's position on the shared acoustic timeline, in ms. */
export function acousticTimeMs(word: MotionTimingWord | undefined): number {
  if (!word) return Number.NaN;
  const seconds = finite(word.t, Number.NaN);
  if (Number.isFinite(seconds)) return seconds * 1000;
  const start = finite(word.start, Number.NaN);
  return Number.isFinite(start) ? start * 1000 : Number.NaN;
}

/** The one-shot window, stretched a little by the word's own spoken span. */
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
       point of a synchronised caption and is not what the other branch does. */
    const voiced = clamp(finite(word.voiced_frac, 1), 0, 1);
    const spoken = spokenMs * (voiced > 0 ? voiced : 1);
    /* SCALED, because the visible part of an envelope is about half its
       length. */
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

/** How long the CWI 2.3 voice crest takes, given how long the colour wipe
   needs to cross the word. */
// The EARLIER of the two envelopes' peaks (`voice-phase-hold` reaches full
// phase at 24%; the pulse at 50%), so the guard below holds under either.
export const VOICE_PHASE_RISE_FRACTION = 0.24;

/** Where the FILM envelope peaks, as a fraction of its own window. */
export const FILM_PEAK_FRACTION = 0.357;

/** How long a word's return should last so its motion reaches the next word. */
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

/** The two parts of that tail: the film's own return, then a long low drift. */
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

/** WHEN A SINGLE LETTER TURNS, relative to the moment the playhead reaches
   its word. */
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

/* THE PR FILM'S OWN CLOCK, measured off `docs/reference/pr-film.mp4` rather
   than fitted. */
export const FILM_WORD_TURN_MS = 80;
