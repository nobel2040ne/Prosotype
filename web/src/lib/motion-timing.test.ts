import assert from "node:assert/strict";
import test from "node:test";
import {
  acousticBacklogMs,
  adaptiveMotionDurationMs,
  characterMotionStepMs,
  isHistoricalInsertion,
  naturalMotionDurationMs,
  recentAcousticGapMs,
  unpaintedReservationExpired,
  type MotionDurationSettings,
} from "./motion-timing.ts";

const settings: MotionDurationSettings = {
  wordMotionBaseMs: 520,
  wordMotionMaxMs: 720,
  wordMotionSpanStretch: 0.42,
  wordMotionMinMs: 320,
  wordMotionBacklogTargetMs: 600,
  wordMotionRateHeadroom: 0.90,
  wordMotionCatchupScale: 0.82,
  maxActiveMotions: 2,
  deliveryFlowDurationMs: 90,
};

test("ordinary speech retains the authored motion duration", () => {
  const natural = naturalMotionDurationMs({
    start: 0,
    end: 0.2,
    delivery_flow: 0,
  }, settings);
  assert.equal(natural, 604);
  assert.equal(
    adaptiveMotionDurationMs(natural, 400, 0, 1, settings),
    natural,
  );
});

test("fast speech receives a sustainable two-slot duration", () => {
  assert.equal(
    adaptiveMotionDurationMs(650, 200, 0, 1, settings),
    360,
  );
});

test("an existing acoustic backlog gets bounded catch-up headroom", () => {
  assert.equal(
    adaptiveMotionDurationMs(650, 250, 1_500, 2, settings),
    369,
  );
});

test("extreme speed never collapses below the smooth-motion floor", () => {
  assert.equal(
    adaptiveMotionDurationMs(650, 50, 5_000, 1, settings),
    320,
  );
});

test("a sparse decoder batch drains even when word cadence is slow", () => {
  assert.equal(
    adaptiveMotionDurationMs(720, null, 8_400, 14, settings),
    320,
  );
});

test("source timing estimates cadence and backlog across a decoder batch", () => {
  const words = Object.fromEntries(Array.from({length: 12}, (_, index) => [
    `w${index}`,
    {
      start: index * 0.2,
      end: index * 0.2 + 0.16,
      utterance: 0,
    },
  ]));
  const order = Object.keys(words);
  assert.equal(recentAcousticGapMs(words, order, "w4"), 200);
  assert.equal(acousticBacklogMs(words, "w4", "w11"), 1_400);
});

test("a shortened word clock still reaches every character hand-off", () => {
  const step = characterMotionStepMs(320, 20);
  assert.ok(step < 8);
  assert.ok(step * 19 <= 320 * 0.42);
  assert.equal(characterMotionStepMs(720, 5), 18);
});

test("a word inserted behind the presented frontier cannot move late", () => {
  assert.equal(
    isHistoricalInsertion({start: 4}, 5_000),
    true,
  );
  assert.equal(
    isHistoricalInsertion({start: 4.98}, 5_000),
    false,
  );
});

test("an unpainted reservation has a bounded deadlock watchdog", () => {
  assert.equal(unpaintedReservationExpired(1_000, 1_249, 250), false);
  assert.equal(unpaintedReservationExpired(1_000, 1_250, 250), true);
  assert.equal(unpaintedReservationExpired(undefined, 2_000, 250), false);
});
