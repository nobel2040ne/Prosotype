/**
 * THE PRESENTATION PLAYHEAD — what makes CWI 2.2.1 possible in open captions.
 *
 * The design system is built on read-ahead: "Every line of dialogue should
 * first appear in white as a complete sentence... This allows the Deaf
 * community to read ahead at their own pace." Colour and the 2.2.3 pop then
 * sweep through text the viewer has already read. Every other feature hangs
 * off that ordering.
 *
 * A live recognizer cannot produce text before it is spoken, so for a long
 * time this project rendered each word at the moment it ARRIVED and had no
 * read-ahead at all. But arrival is not the only clock available. ASR delivers
 * a word roughly `L` seconds after it was spoken (~1.1 s for the 1120 ms
 * accurate stream). If the captions are presented from a playhead that runs
 * `D` seconds behind the true acoustic clock, then at any instant the browser
 * already holds every word up to `now - L` while it is only COLOURING up to
 * `now - D`. The difference `D - L` is genuine, non-fabricated read-ahead:
 * real recognized text, sitting on screen in white, ahead of the colour.
 *
 * At the shipped 2.5 s delay that is ~1.4 s of white lead — several words.
 *
 * Everything downstream becomes a pure function of the playhead:
 *   - a word is white before `start`, speaker-coloured after it (2.2.2)
 *   - its pop is scheduled at `start` (2.2.3)
 *   - it is frozen once the playhead passes it — the caption invariant stops
 *     being a set of guards and becomes a property of time itself
 *
 * This module is the clock only: recovering acoustic time from jittery SSE
 * arrivals. It holds no React state and touches no DOM.
 */

/** Acoustic seconds since capture start, as the server timestamps them. */
export interface ClockSample {
  /** `level.t` / `word.t`, in ms. */
  acousticMs: number;
  /** `performance.now()` when it was received. */
  monotonicMs: number;
}

export interface PlayheadClock {
  /**
   * `acousticMs - monotonicMs`. Adding it to `performance.now()` recovers the
   * current acoustic time between samples.
   */
  offsetMs: number;
  /** When `offsetMs` was last revised, for the drift decay. */
  updatedAtMs: number;
  /** False until the first sample; the caller must not present captions yet. */
  started: boolean;
  /**
   * Bumped whenever the clock resyncs onto a NEW capture timeline.
   *
   * Words scheduled against an older epoch describe a recording that no longer
   * exists. They were spoken, so they must settle -- re-deriving their turn
   * moment on the new timeline would place them in the future and revert them
   * to read-ahead, which is exactly what `--sample --loop` produced before this
   * existed: a full stage of already-spoken text turning white again.
   */
  epoch: number;
}

export const IDLE_CLOCK: Readonly<PlayheadClock> = Object.freeze({
  offsetMs: 0,
  updatedAtMs: 0,
  started: false,
  epoch: 0,
});

/**
 * How far the acoustic clock may jump back before it is treated as a new
 * capture rather than as jitter. `--sample --loop` restarts at t=0, and a
 * reconnect can replay an older position.
 */
export const RESYNC_TOLERANCE_MS = 1500;

/**
 * Drift bleed-off, in ms of offset per second of wall time.
 *
 * The filter below keeps the MAXIMUM observed offset, because transport jitter
 * can only ever make a sample look late (arrive at a larger `monotonicMs` for
 * the same `acousticMs`), never early. Left alone, a max filter would latch
 * onto one lucky early sample forever, so it relaxes slowly enough to be
 * invisible (5 ms/s is 1/200th of real time) but fast enough to track a device
 * clock that genuinely runs slow.
 */
export const DRIFT_DECAY_MS_PER_S = 5;

function finite(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/**
 * Fold one acoustic reading into the clock.
 *
 * Pure: returns a new clock, or the same object when nothing changed, so React
 * state updates can bail out cheaply.
 */
export function advanceClock(
  clock: PlayheadClock,
  acousticMs: number,
  monotonicMs: number,
  resyncToleranceMs = RESYNC_TOLERANCE_MS,
): PlayheadClock {
  const acoustic = finite(acousticMs);
  const monotonic = finite(monotonicMs);
  if (!Number.isFinite(acoustic) || !Number.isFinite(monotonic)) return clock;

  const sampleOffset = acoustic - monotonic;
  if (!clock.started) {
    return {
      offsetMs: sampleOffset,
      updatedAtMs: monotonic,
      started: true,
      epoch: clock.epoch,
    };
  }

  const elapsedS = Math.max(0, monotonic - clock.updatedAtMs) / 1000;
  const relaxed = clock.offsetMs - elapsedS * DRIFT_DECAY_MS_PER_S;

  // A large backwards step is a new capture (loop restart, restarted server),
  // not a late packet. Snap rather than holding a playhead that would sit in
  // the far future of the new timeline and colour every incoming word at once.
  if (sampleOffset < relaxed - Math.max(0, resyncToleranceMs)) {
    return {
      offsetMs: sampleOffset,
      updatedAtMs: monotonic,
      started: true,
      epoch: clock.epoch + 1,
    };
  }

  const offsetMs = Math.max(relaxed, sampleOffset);
  if (offsetMs === clock.offsetMs && monotonic === clock.updatedAtMs) {
    return clock;
  }
  return {
    offsetMs,
    updatedAtMs: monotonic,
    started: true,
    epoch: clock.epoch,
  };
}

/** Current acoustic time, interpolated between samples. */
export function acousticNowMs(
  clock: PlayheadClock,
  monotonicMs: number,
): number {
  if (!clock.started) return Number.NEGATIVE_INFINITY;
  return monotonicMs + clock.offsetMs;
}

/**
 * The caption playhead: acoustic time minus the read-ahead delay.
 *
 * Words at or before this are spoken; words after it are the white read-ahead.
 */
export function presentationNowMs(
  clock: PlayheadClock,
  monotonicMs: number,
  delayMs: number,
): number {
  if (!clock.started) return Number.NEGATIVE_INFINITY;
  return monotonicMs + clock.offsetMs - Math.max(0, delayMs);
}

/**
 * When, on `performance.now()`'s timeline, the playhead reaches `acousticMs`.
 *
 * This is the value that gets frozen per word and handed to CSS as an
 * `animation-delay`, so the browser — not a JavaScript timer — schedules the
 * colour turn and the pop. Freezing the ABSOLUTE moment rather than a relative
 * delay is what lets a word survive re-render and remount without its motion
 * restarting or jumping: the effect simply re-subtracts the current time.
 */
export function monotonicTimeForAcousticMs(
  clock: PlayheadClock,
  acousticMs: number,
  delayMs: number,
): number {
  return acousticMs - clock.offsetMs + Math.max(0, delayMs);
}

/**
 * Read-ahead actually available right now, in ms.
 *
 * `newestAcousticMs` is the newest word the browser holds. This is the
 * measurable version of "how far can the viewer read", and it is what a probe
 * should assert on: it should settle near `delay - recognizerLatency`, and a
 * value at or below zero means the caption is being coloured the instant it
 * arrives, i.e. there is no read-ahead at all.
 */
export function readAheadMs(
  clock: PlayheadClock,
  newestAcousticMs: number,
  monotonicMs: number,
  delayMs: number,
): number {
  const playhead = presentationNowMs(clock, monotonicMs, delayMs);
  if (!Number.isFinite(playhead) || !Number.isFinite(newestAcousticMs)) {
    return 0;
  }
  return Math.max(0, newestAcousticMs - playhead);
}
