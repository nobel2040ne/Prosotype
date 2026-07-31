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
  wordMotionBacklogTargetMs: number;
  wordMotionRateHeadroom: number;
  wordMotionCatchupScale: number;
  maxActiveMotions: number;
  deliveryFlowDurationMs: number;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function acousticTimeMs(word: MotionTimingWord | undefined): number {
  if (!word) return Number.NaN;
  const seconds = finite(word.t, Number.NaN);
  if (Number.isFinite(seconds)) return seconds * 1000;
  const start = finite(word.start, Number.NaN);
  return Number.isFinite(start) ? start * 1000 : Number.NaN;
}

export function naturalMotionDurationMs(
  word: MotionTimingWord,
  settings: MotionDurationSettings,
): number {
  const spokenMs = Math.max(
    0,
    finite(word.end) - finite(word.start),
  ) * 1000;
  const flow = clamp(finite(word.delivery_flow), 0, 1);
  return clamp(
    settings.wordMotionBaseMs
      + spokenMs * settings.wordMotionSpanStretch
      + flow * settings.deliveryFlowDurationMs,
    settings.wordMotionBaseMs,
    settings.wordMotionMaxMs,
  );
}

/**
 * Estimate the actual spoken word cadence, not decoder arrival cadence.
 *
 * The window straddles the word being revealed so a batched recognizer can
 * immediately expose its source rate. Long pauses and invalid/reversed timing
 * are excluded because they do not limit sustained caption throughput.
 */
export function recentAcousticGapMs<T extends MotionTimingWord>(
  words: Record<string, T>,
  order: string[],
  aroundId: string,
): number | null {
  const around = Math.max(0, order.indexOf(aroundId));
  const ids = order.slice(
    Math.max(0, around - 8),
    Math.min(order.length, around + 13),
  );
  const gaps: number[] = [];
  for (let index = 1; index < ids.length; index += 1) {
    const previous = words[ids[index - 1]];
    const current = words[ids[index]];
    if (!previous || !current) continue;
    const gap = acousticTimeMs(current) - acousticTimeMs(previous);
    if (gap >= 50 && gap <= 800) gaps.push(gap);
  }
  if (!gaps.length) return null;
  gaps.sort((left, right) => left - right);
  const middle = Math.floor(gaps.length / 2);
  return gaps.length % 2
    ? gaps[middle]
    : (gaps[middle - 1] + gaps[middle]) / 2;
}

export function acousticBacklogMs<T extends MotionTimingWord>(
  words: Record<string, T>,
  currentId: string,
  newestId: string | undefined,
): number {
  const current = acousticTimeMs(words[currentId]);
  const newest = acousticTimeMs(newestId ? words[newestId] : undefined);
  return Number.isFinite(current) && Number.isFinite(newest)
    ? Math.max(0, newest - current)
    : 0;
}

export function isHistoricalInsertion(
  word: MotionTimingWord | undefined,
  presentedFrontierMs: number,
  toleranceMs = 40,
): boolean {
  const wordTime = acousticTimeMs(word);
  return (
    Number.isFinite(wordTime) &&
    Number.isFinite(presentedFrontierMs) &&
    wordTime + Math.max(0, toleranceMs) < presentedFrontierMs
  );
}

export function unpaintedReservationExpired(
  reservedAtMs: number | undefined,
  nowMs: number,
  timeoutMs: number,
): boolean {
  return (
    Number.isFinite(reservedAtMs) &&
    Number.isFinite(nowMs) &&
    nowMs - Number(reservedAtMs) >= Math.max(0, timeoutMs)
  );
}

/**
 * Fallback wake-up for logical cleanup when a browser drops `animationend`.
 *
 * Infinite expiries are unpainted reservations and have their own watchdog.
 * A null result means there is no painted motion to revisit.
 */
export function nextActiveMotionDelayMs(
  expiries: Iterable<number>,
  nowMs: number,
): number | null {
  let next = Number.POSITIVE_INFINITY;
  for (const expiry of expiries) {
    if (Number.isFinite(expiry)) next = Math.min(next, expiry);
  }
  return Number.isFinite(next) ? Math.max(0, next - nowMs) : null;
}

/**
 * Keep the two-word presentation lane sustainable at the measured speech rate.
 *
 * At ordinary cadence the authored 520–720 ms clock is untouched. Faster
 * speech receives only the duration reduction required for two slots to match
 * the acoustic word rate. If a decoder burst has already created lag, a
 * bounded extra reduction drains it instead of allowing minute-long growth.
 */
export function adaptiveMotionDurationMs(
  naturalDurationMs: number,
  acousticGapMs: number | null,
  backlogMs: number,
  queuedWordCount: number,
  settings: MotionDurationSettings,
): number {
  const natural = clamp(
    naturalDurationMs,
    settings.wordMotionMinMs,
    settings.wordMotionMaxMs,
  );
  const activeSlots = Math.max(1, settings.maxActiveMotions);
  const sustainableBudget = acousticGapMs !== null && acousticGapMs > 0
    ? acousticGapMs
      * activeSlots
      * clamp(settings.wordMotionRateHeadroom, 0.5, 1)
    : natural;
  const target = Math.max(1, settings.wordMotionBacklogTargetMs);
  const pressure = clamp(
    (Math.max(0, backlogMs) - target * 0.5) / (target * 1.5),
    0,
    1,
  );
  const catchupScale = 1 - pressure * (
    1 - clamp(settings.wordMotionCatchupScale, 0.5, 1)
  );
  const batchDrainBudget = backlogMs > target
    ? target * activeSlots / Math.max(1, queuedWordCount)
    : natural;
  return clamp(
    Math.min(
      natural,
      sustainableBudget * catchupScale,
      batchDrainBudget,
    ),
    settings.wordMotionMinMs,
    natural,
  );
}

export interface CharacterWaveTiming {
  /** Delay between one letter's bump and the next. */
  stepMs: number;
  /** How long ONE letter's bump lasts -- not the whole word's clock. */
  bumpMs: number;
}

/**
 * Time the alphabet-level hand-off so it actually TRAVELS across the word.
 *
 * A wave exists only if the letters of one word are at DIFFERENT phases at the
 * same instant. Two things have to be true for that, and the previous model had
 * neither:
 *
 *   1. The step was `min(18ms, duration * 0.42 / (n - 1))`, and that 18ms cap
 *      fired for every word up to 13 characters -- i.e. essentially always. A
 *      seven-letter word spread its letters over 108ms.
 *   2. Every letter animated for the WHOLE word clock (520-720ms). Offsetting a
 *      520ms bump by 18ms leaves the letters ~97% in phase, so even a large
 *      amplitude reads as one synchronous word-level pulse.
 *
 * Measured on the running studio, the result was a median phase spread across a
 * word of **0.017em** -- 0.8px at 47px type. The alphabet motion was present in
 * the DOM and invisible on screen.
 *
 * So both come from one constraint instead: `overlap` letters should be in
 * flight at once, and the hand-off must finish exactly when the word's own clock
 * does (a character animation outliving the wrapper would be cut off mid-air
 * when `.is-settled` lands). With `bump = overlap * step` and
 * `(n - 1) * step + bump = duration`, that is `step = duration / (n - 1 + overlap)`.
 *
 * At overlap 3 a 520ms word gives 87ms steps on a four-letter word and 46ms on a
 * nine-letter one -- inside the 53-110ms letter-to-letter spacing measured on the
 * reference recording -- and a long word compresses gracefully instead of losing
 * the hand-off entirely.
 */
export function characterWaveTiming(
  durationMs: number,
  characterCount: number,
  overlap: number,
): CharacterWaveTiming {
  const duration = Math.max(0, durationMs);
  const letters = Math.max(1, Math.floor(characterCount));
  if (letters <= 1) return {stepMs: 0, bumpMs: duration};
  const inFlight = clamp(finite(overlap, 3), 1, letters);
  const stepMs = duration / (letters - 1 + inFlight);
  return {stepMs, bumpMs: stepMs * inFlight};
}

/**
 * Is this word so far behind the newest one that it is history, not speech?
 *
 * The adaptive clock can shorten a motion, but it cannot make one free, so a
 * deep queue still has to play every word through the concurrency slots. That
 * is fine for a decoder burst and wrong for a cold start: model loading takes
 * seconds while the source keeps running, so the first browser to attach can
 * inherit a backlog of tens of words spanning MEASURED 12.7 s of clip time.
 * Animating those is the late-motion defect in slow motion -- the caption
 * races, arrives seconds after the sound, and reads as choppy.
 *
 * A word this far behind the acoustic frontier already missed its moment. It
 * still appears, in order, as readable text; it just does not pretend to be
 * live. Live words -- inside the ceiling -- animate exactly as before.
 */
export function exceedsMotionBacklogCeiling(
  backlogMs: number,
  ceilingMs: number,
): boolean {
  if (!Number.isFinite(backlogMs) || !Number.isFinite(ceilingMs)) return false;
  if (ceilingMs <= 0) return false;
  return backlogMs > ceilingMs;
}
