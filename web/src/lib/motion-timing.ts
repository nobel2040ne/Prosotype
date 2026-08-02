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
  deliveryFlowDurationMs: number;
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
    Math.min(settings.wordMotionMinMs, settings.wordMotionBaseMs),
    settings.wordMotionMaxMs,
  );
}

/**
 * How long the CWI 2.3 voice crest takes, given how long the colour wipe
 * needs to cross the word.
 *
 * THE CREST MUST NOT LEAD THE WIPE. `@keyframes voice-phase` reaches full
 * phase at its literal 24% stop (a keyframe selector cannot take a `var()`,
 * so 0.24 here and the 24% there change TOGETHER). On the natural duration
 * that rise takes ~150-200 ms, while the per-character colour turn crosses a
 * long word in up to `wordMotionMaxMs` — so the word ballooned while most of
 * its letters were still uncoloured. The PR film never moves a word ahead of
 * its colour: in "weigh|ts" the size arrives WITH the sweep. Stretching the
 * crest window so phase 1 lands as the wipe completes reproduces that; for
 * the median word (sweep well under 28% of the natural window) this is a
 * no-op, so only the words that exhibited the defect change.
 */
export const VOICE_PHASE_RISE_FRACTION = 0.24;

export function crestDurationMs(sweepMs: number, naturalMs: number): number {
  const sweep = Math.max(0, finite(sweepMs));
  return Math.max(finite(naturalMs), sweep / VOICE_PHASE_RISE_FRACTION);
}
