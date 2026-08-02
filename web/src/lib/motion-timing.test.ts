import assert from "node:assert/strict";
import test from "node:test";
import {
  acousticTimeMs,
  crestDurationMs,
  naturalMotionDurationMs,
  VOICE_PHASE_RISE_FRACTION,
  type MotionDurationSettings,
} from "./motion-timing.ts";

const settings: MotionDurationSettings = {
  wordMotionBaseMs: 520,
  wordMotionMaxMs: 720,
  wordMotionSpanStretch: 0.42,
  wordMotionMinMs: 320,
  deliveryFlowDurationMs: 90,
};

test("acoustic time prefers the global stream timeline", () => {
  // `t` is stream_base + start, the same timeline `level.t` reports, so it is
  // directly comparable with the playhead. `start` alone is utterance-relative.
  assert.equal(acousticTimeMs({t: 41.5, start: 1.5}), 41_500);
  assert.equal(acousticTimeMs({start: 1.5}), 1_500);
  assert.ok(Number.isNaN(acousticTimeMs(undefined)));
  assert.ok(Number.isNaN(acousticTimeMs({})));
});

test("an ordinary word keeps the authored 520 ms clock", () => {
  assert.equal(
    naturalMotionDurationMs({start: 1, end: 1.2}, settings),
    520 + 200 * 0.42,
  );
});

test("a drawn-out word runs longer, bounded by the maximum", () => {
  const drawn = naturalMotionDurationMs(
    {start: 1, end: 2.4, delivery_flow: 1},
    settings,
  );
  assert.equal(drawn, 720);
  assert.ok(drawn > naturalMotionDurationMs({start: 1, end: 1.1}, settings));
});

test("flow lengthens the cue without exceeding the ceiling", () => {
  const steady = naturalMotionDurationMs({start: 0, end: 0.2}, settings);
  const flowing = naturalMotionDurationMs(
    {start: 0, end: 0.2, delivery_flow: 1},
    settings,
  );
  assert.equal(flowing - steady, 90);
  assert.ok(flowing <= settings.wordMotionMaxMs);
});

test("the crest never leads the wipe, and short words are untouched", () => {
  // Sweep comfortably inside the rise fraction of the natural window: no-op.
  assert.equal(crestDurationMs(120, 520), 520);
  assert.equal(crestDurationMs(0, 520), 520);
  // A long wipe stretches the window so phase 1 lands as the wipe completes.
  assert.equal(crestDurationMs(400, 520), 400 / VOICE_PHASE_RISE_FRACTION);
  // Bounded by the wipe cap: sweep is already clamped to wordMotionMaxMs.
  assert.equal(
    crestDurationMs(settings.wordMotionMaxMs, 720),
    settings.wordMotionMaxMs / VOICE_PHASE_RISE_FRACTION,
  );
  // Monotone in the sweep.
  let previous = 0;
  for (let sweep = 0; sweep <= 720; sweep += 60) {
    const duration = crestDurationMs(sweep, 520);
    assert.ok(duration >= previous);
    previous = duration;
  }
});
