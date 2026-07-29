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

export function characterMotionStepMs(
  durationMs: number,
  characterCount: number,
): number {
  if (characterCount <= 1) return 0;
  return Math.min(
    18,
    Math.max(0, durationMs) * 0.42 / (characterCount - 1),
  );
}
