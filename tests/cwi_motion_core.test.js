"use strict";

// Pins the SHARED CWI motion engine (cwi_motion_core.js) that live and cc both
// drive. These assert the design-system shapes (§2.2 synchronization, §2.3
// intonation) so the math cannot silently drift — the failure mode that made
// live diverge from cc for so long.

const test = require("node:test");
const assert = require("node:assert/strict");
const Motion = require("../autocwi/cwi_motion_core.js");

function ctx(overrides) {
  return Object.assign({
    cfg: {
      sync_pop: 0.15, sync_elevation_em: 0.25,
      sync_rise_s: 0.09, sync_peak_s: 0.08, sync_fall_s: 0.18,
      color_turn_ms: 90,
      emphasis_lead_s: 0.18, emphasis_hold_s: 0.08, emphasis_tail_s: 0.30,
      quiet_deformation: 1.0, emphasis_deadband: 0.05, size_pct: 5.0,
      min_voiced_frac: 0.2, provisional_color_strength: 0.55,
      glyph_height_em: 0.70, motion_source: "spec",
      rest_color: "rgba(255,255,255,.9)",
      char_sync_reach: 1, char_sync_lift_em: 0.12, char_sync_pop: 0.07,
      char_sync_crouch_em: 0.025, char_sync_lead_s: 0.14,
      char_sync_peak_s: 0.10, char_sync_fall_s: 0.26,
      speakers: {S1: "#E5E517", S2: "#17E517"}
    },
    mapping: {
      loudness_to: {min: 3, max: 12, baseline: 5},
      pitch_to: {min: 100, max: 1000, domain_hz: [80, 250], invert: true}
    },
    expression: {
      size_response: 1.0, weight_response: 1.0, width_response: 1.0,
      wght_range: [100, 1000], anchor_wght: [380, 420]
    },
    medianLoudness: 0.5, medianPitch: 180,
    charSweep: true, waveOn: true, reduced: false
  }, overrides);
}

function word(o) {
  return Object.assign({
    text: "hello", start: 1.0, end: 1.5, speaker: "S1",
    speaker_status: "stable", loudness: 0.5, pitch_hz: 180, voiced_frac: 0.9
  }, o);
}
function nodeFor(w) {
  const M = Motion.create(ctx());
  return {el: {_type: M.typeOf(w)}, w: w, chars: Array.from(w.text)};
}

test("typeOf: every word rests at the common baseline (nothing baked in)", () => {
  const M = Motion.create(ctx());
  const median = M.typeOf(word({loudness: 0.5}));
  const loud = M.typeOf(word({loudness: 0.98}));
  const quiet = M.typeOf(word({loudness: 0.02}));
  // Rest size/weight are identical for all three — prosody is only the envelope.
  assert.equal(median.restPct, loud.restPct);
  assert.equal(median.restPct, quiet.restPct);
  assert.equal(median.restWght, loud.restWght);
  // A median word barely deforms (inside the deadband); loud swells, quiet shrinks.
  assert.ok(Math.abs(median.emphScale - 1) < 1e-9, "median ~ 1");
  assert.ok(loud.emphScale > 1.3, "loud swells: " + loud.emphScale);
  assert.ok(quiet.emphScale < 0.95, "quiet shrinks: " + quiet.emphScale);
});

test("syncAt: peaks just AFTER the turn, zero far from it", () => {
  const M = Motion.create(ctx());
  assert.equal(M.syncAt(0, 1), 0);                 // long before
  assert.equal(M.syncAt(5, 1), 0);                 // long after
  const peak = M.syncAt(1 + 0.08, 1);              // at tTurn + sync_peak_s
  assert.ok(peak > 0.99, "peak ~1 just past the turn: " + peak);
});

test("scaleOf/liftOf: transient — swell at the turn, exactly 1 / 0 at rest", () => {
  const M = Motion.create(ctx());
  const node = nodeFor(word({loudness: 0.98}));
  const atPeak = M.scaleOf(node.w.start + 0.08, node);
  const atRest = M.scaleOf(node.w.end + 5, node);
  assert.ok(atPeak > 1.3, "loud word swells while spoken: " + atPeak);
  assert.ok(Math.abs(atRest - 1) < 1e-6, "returns to baseline: " + atRest);
  assert.ok(M.liftOf(node.w.start + 0.08, node) > 0, "lifts at the turn");
  assert.ok(Math.abs(M.liftOf(node.w.end + 5, node)) < 1e-9, "no lift at rest");
});

test("charColorAt: per-character sweep — white before, full colour after", () => {
  const M = Motion.create(ctx());
  const node = nodeFor(word({text: "hello", start: 1.0, end: 1.5}));
  const white = M.charColorAt(node, 4, 1.0);       // last letter, at word onset
  const full = M.charColorAt(node, 0, 3.0);        // first letter, well after
  assert.ok(/255, ?255/.test(white), "unspoken letter is white: " + white);
  assert.ok(/229, ?229, ?23/.test(full), "spoken letter is speaker colour: " + full);
  // The turn spreads across the span: an earlier letter turns before a later one.
  assert.ok(M.turnAt(node, 0) < M.turnAt(node, 4), "sweep advances through the word");
});

test("character synchronization travels alphabetically and returns to exact rest", () => {
  const M = Motion.create(ctx());
  const node = nodeFor(word({text: "hello", start: 1.0, end: 1.5}));
  const firstPeak = M.turnAt(node, 0) + 0.10;
  assert.ok(M.charLiftOf(firstPeak, node, 0) > 0.11,
            "first letter rises at its own turn");
  assert.ok(M.charScaleOf(firstPeak, node, 0) > 1.06,
            "first letter pops at its own turn");
  assert.equal(M.charLiftOf(firstPeak, node, 4), 0,
               "last letter has not started when the first peaks");
  assert.equal(M.charScaleOf(firstPeak, node, 4), 1);
  assert.equal(M.charTransform(0, 1), "none",
               "settled character has no residual effect");
  assert.equal(M.charLiftOf(5, node, 0), 0);
  assert.equal(M.charScaleOf(5, node, 0), 1);
});

test("resolveNeighborPush: a swelling word shifts neighbours, row stays centred", () => {
  const M = Motion.create(ctx());
  const w0 = nodeFor(word({loudness: 0.5}));
  const big = nodeFor(word({loudness: 0.98}));
  const w2 = nodeFor(word({loudness: 0.5}));
  [w0, big, w2].forEach(n => { n.restW = 100; n.restRow = 0; });
  // Freeze the middle word mid-swell; neighbours at rest.
  const getScale = (t, n) => n === big ? 1.5 : 1.0;
  M.resolveNeighborPush([w0, big, w2], 0, getScale);
  assert.ok(w0.shift < 0, "left neighbour slides left: " + w0.shift);
  assert.ok(w2.shift > 0, "right neighbour slides right: " + w2.shift);
  assert.ok(Math.abs(big.shift) < 1e-9, "the swelling word stays centred");
  assert.ok(Math.abs(w0.shift + w2.shift) < 1e-9, "row stays balanced");
});
