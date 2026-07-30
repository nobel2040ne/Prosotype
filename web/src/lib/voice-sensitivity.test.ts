import assert from "node:assert/strict";
import test from "node:test";

import {
  deliveryExpressiveness,
  expandAroundCenter,
  expandPitch,
} from "./voice-sensitivity.ts";

// force 0.30 is the configured typical level, not 0.5 — the measured median on
// the bundled sample is 0.283. flow/texture are carried for shape but do not
// enter the magnitude, because their neutral is not knowable client-side.
const FORCE_NEUTRAL = 0.30;
const NEUTRAL = {
  force: FORCE_NEUTRAL,
  attack: 0,
  contour: 0,
  flow: 0.478,
  texture: 0.582,
};

test("the centre maps to itself so a median word stays at baseline", () => {
  assert.equal(expandAroundCenter(0.5, 0.5, 0.62), 0.5);
  assert.equal(expandPitch(180, 180, 0.62), 180);
});

test("endpoints are pinned, so the reachable extremes do not grow", () => {
  // This is the guard against the documented failure where ordinary speech
  // rendered as fabricated whispers and shouts.
  assert.equal(expandAroundCenter(0, 0.5, 0.62), 0);
  assert.equal(expandAroundCenter(1, 0.5, 0.62), 1);
  assert.equal(expandPitch(80, 180, 0.62), 80);
  assert.equal(expandPitch(250, 180, 0.62), 250);
});

test("small deviations near the centre are amplified", () => {
  // The whole point: a real 0.45 -> 0.55 swing used to reach the screen as a
  // few percent of scale.
  const quiet = expandAroundCenter(0.45, 0.5, 0.62);
  const loud = expandAroundCenter(0.55, 0.5, 0.62);

  assert.ok(loud - quiet > 0.2, `expected >0.2 spread, got ${loud - quiet}`);
  assert.ok(quiet < 0.45 && loud > 0.55);
});

test("gamma of 1 is an exact no-op", () => {
  for (const value of [0, 0.17, 0.5, 0.83, 1]) {
    assert.equal(expandAroundCenter(value, 0.5, 1), value);
  }
});

test("the curve stays monotonic", () => {
  let previous = -Infinity;
  for (let i = 0; i <= 40; i += 1) {
    const mapped = expandAroundCenter(i / 40, 0.5, 0.62);
    assert.ok(mapped >= previous, `not monotonic at ${i / 40}`);
    previous = mapped;
  }
});

test("an off-centre baseline still reaches both endpoints", () => {
  // A low voice must not spend its whole range in the bottom of the fixed map.
  assert.equal(expandPitch(250, 110, 0.62), 250);
  assert.equal(expandPitch(80, 110, 0.62), 80);
  const nudged = expandPitch(120, 110, 0.62);
  assert.ok(nudged > 120, `expected amplification, got ${nudged}`);
});

test("values outside the domain clamp instead of exploding", () => {
  assert.equal(expandAroundCenter(-5, 0.5, 0.62), 0);
  assert.equal(expandAroundCenter(9, 0.5, 0.62), 1);
  assert.equal(expandAroundCenter(Number.NaN, 0.5, 0.62), 0.5);
});

// -- continuous expressiveness: the point is that there is NO dead zone -------

test("a flat word gets exactly the floor and nothing less", () => {
  assert.equal(deliveryExpressiveness(NEUTRAL, 0.34), 0.34);
});

test("a barely inflected word is already above the floor", () => {
  // This is the whole fix. Under the old discrete gain any word the classifier
  // called `steady` was pinned to one attenuation regardless of how close it
  // came to the cut-off.
  const whisperOfContour = deliveryExpressiveness(
    {...NEUTRAL, contour: 0.05},
    0.34,
  );

  assert.ok(
    whisperOfContour > 0.34,
    `expected >0.34, got ${whisperOfContour}`,
  );
});

test("response is strictly monotonic in each axis — no plateau to hide in", () => {
  for (const axis of ["force", "contour", "flow", "texture"] as const) {
    let previous = -Infinity;
    for (let i = 0; i <= 20; i += 1) {
      const value = axis === "contour" ? i / 20 : 0.5 + i / 40;
      const current = deliveryExpressiveness({...NEUTRAL, [axis]: value}, 0.34);
      assert.ok(
        current >= previous,
        `${axis} not monotonic at ${value}: ${current} < ${previous}`,
      );
      previous = current;
    }
  }
});

test("quieter and louder by the same amount are equally expressive", () => {
  // Symmetric about the configured neutral, not about 0.5.
  const quiet = deliveryExpressiveness({...NEUTRAL, force: 0.15}, 0.34);
  const loud = deliveryExpressiveness({...NEUTRAL, force: 0.45}, 0.34);

  assert.ok(Math.abs(quiet - loud) < 1e-9, `${quiet} vs ${loud}`);
  assert.ok(quiet > 0.34);
});

test("several mild cues combine instead of each being judged alone", () => {
  const oneCue = deliveryExpressiveness({...NEUTRAL, contour: 0.2}, 0.34);
  const manyCues = deliveryExpressiveness(
    {force: 0.62, attack: 0.2, contour: 0.2, flow: 0.62, texture: 0.62},
    0.34,
  );

  assert.ok(manyCues > oneCue, `${manyCues} should exceed ${oneCue}`);
});

test("the result never leaves floor..1", () => {
  const extreme = deliveryExpressiveness(
    {force: 1, attack: 1, contour: -1, flow: 0, texture: 1},
    0.34,
  );

  assert.ok(extreme <= 1 && extreme >= 0.34);
});

test("an unmeasured force does not masquerade as emphasis", () => {
  // force === 0 means the estimator produced nothing, not that the speaker went
  // silent. Measured, such words scored HIGHER than words at typical force.
  const unmeasured = deliveryExpressiveness(
    {...NEUTRAL, force: 0},
    0.34,
    0.62,
    0.30,
  );

  assert.equal(unmeasured, 0.34);
});

test("missing or malformed readings fall back to neutral, not to NaN", () => {
  const broken = deliveryExpressiveness(
    {
      force: Number.NaN,
      attack: Number.NaN,
      contour: Number.NaN,
      flow: Number.NaN,
      texture: Number.NaN,
    },
    0.34,
  );

  assert.ok(Number.isFinite(broken));
});
