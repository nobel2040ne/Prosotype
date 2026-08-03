import assert from "node:assert/strict";
import test from "node:test";
import {
  acousticTimeMs,
  crestDurationMs,
  crestWindowMs,
  naturalMotionDurationMs,
  VOICE_PHASE_RISE_FRACTION,
  type MotionDurationSettings,
} from "./motion-timing.ts";

// The shipped values, not a fixture of their own: this file used to pin
// 520/720 long after config.yaml had moved, which insulated the tests from
// every change they were supposed to catch.
const settings: MotionDurationSettings = {
  wordMotionBaseMs: 420,
  wordMotionMaxMs: 850,
  wordMotionSpanStretch: 0.42,
  wordMotionMinMs: 320,
  wordMotionPopMaxMs: 700,
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

test("a word moves for ONE WORD at the current speech rate", () => {
  // The AE template's range selector is exactly one word wide and sweeps the
  // line in `outTime - inTime`, so it sits on each word for
  // `lineDuration / wordCount`. Live, that is the interval to the next onset.
  const quick = naturalMotionDurationMs({start: 1, end: 1.2}, settings, 0.45);
  const slow = naturalMotionDurationMs({start: 1, end: 1.2}, settings, 0.90);
  assert.ok(slow > quick, `${quick} -> ${slow}`);
  assert.ok(Math.abs(quick - (450 + 200 * 0.42)) < 1e-6, `${quick}`);
  assert.ok(Math.abs(slow - settings.wordMotionPopMaxMs) < 1e-6, `${slow}`);

  // ...and NOT on how big the word gets. Two words at the same speech rate
  // move for the same time however loud either of them is; every earlier
  // version of this file assumed otherwise.
  // (a tolerance because `1.2 - 1` and `5.2 - 5` differ in the last bit)
  assert.ok(Math.abs(
    naturalMotionDurationMs({start: 1, end: 1.2}, settings, 0.45) -
    naturalMotionDurationMs({start: 5, end: 5.2}, settings, 0.45),
  ) < 1e-6);

  // No next word yet -- the last word of a capture -- falls back to the
  // authored base rather than collapsing to the floor.
  const orphan = naturalMotionDurationMs({start: 1, end: 1.2}, settings, 0);
  assert.ok(
    Math.abs(orphan - (settings.wordMotionBaseMs + 200 * 0.42)) < 1e-6,
    `${orphan}`,
  );
});

test("a drawn-out word runs longer, bounded by the maximum", () => {
  const drawn = naturalMotionDurationMs(
    {start: 1, end: 2.4, delivery_flow: 1},
    settings,
    2.0,
  );
  assert.equal(drawn, settings.wordMotionPopMaxMs);
  const short = naturalMotionDurationMs({start: 1, end: 1.1}, settings, 0.4);
  const long = naturalMotionDurationMs({start: 1, end: 1.6}, settings, 0.4);
  assert.ok(long > short, `${short} -> ${long}`);
});

test("flow lengthens the cue without exceeding the ceiling", () => {
  const steady = naturalMotionDurationMs({start: 0, end: 0.2}, settings, 0.4);
  const flowing = naturalMotionDurationMs(
    {start: 0, end: 0.2, delivery_flow: 1},
    settings,
    0.4,
  );
  assert.equal(flowing - steady, 90);
  assert.ok(flowing <= settings.wordMotionMaxMs);
});

test("the wipe stretch scales with the crest, or it becomes the floor", () => {
  // Applied flat, `sweep / 0.24` forces a 480ms window on a 160ms word (FWHM
  // 0.37s) against the reference's 0.16s -- so the anti-lead rule, not the
  // duration channel, would decide how fast an ordinary word moves. There is
  // nothing to lead when there is no crest.
  assert.equal(crestDurationMs(400, 300, 0), 300);
  assert.equal(crestDurationMs(400, 300, 1), 400 / VOICE_PHASE_RISE_FRACTION);
  assert.ok(crestDurationMs(400, 300, 0.5) < crestDurationMs(400, 300, 1));
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


test("the crest is the SLOW clock and the pop is the FAST one", () => {
  // The AE template animates position and colour only, so its speech-rate
  // selector governs the BOUNCE; the size crest is the PDF's and the
  // recordings run it far longer -- 1.560s for the words a viewer actually
  // sees, against 0.160s for the 37 of 43 that barely move. Driving both from
  // one clock is what made the motion read as either mush or a twitch.
  const quiet = crestWindowMs(0, settings);
  const loud = crestWindowMs(1, settings);
  assert.equal(quiet, settings.wordMotionMinMs);         // ~0.16s span
  assert.equal(loud, settings.wordMotionMaxMs);          // ~1.56s span
  // The RATIO is a config decision that has moved several times; pin that
  // the grading exists and is the right way round, not its magnitude.
  assert.ok(loud > quiet * 2, `${quiet} -> ${loud}`);

  // The pop never inherits that ceiling, however slowly the speaker talks.
  const pop = naturalMotionDurationMs({start: 0, end: 0.1}, settings, 5.0);
  assert.ok(pop <= settings.wordMotionPopMaxMs, `${pop}`);
  assert.ok(pop < loud, "the pop must stay crisp under a long crest");
  // The pop ceiling and the crest ceiling are independent knobs; the crest's
  // is re-derived from whichever envelope is in use, so pin only the ordering.
  assert.ok(settings.wordMotionPopMaxMs < settings.wordMotionMaxMs);
});
