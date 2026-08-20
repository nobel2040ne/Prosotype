import assert from "node:assert/strict";
import test from "node:test";

import {
  captionMotionFor,
  characterVoiceTypes,
  peakCharacterScale,
  sampleContour,
  NORMAL_CAPTION_TYPE,
  voiceScale,
  voiceTone,
  voiceTypeFor,
  voiceDeviationOf,
  reachableScaleRange,
  voiceWeight,
  voiceWidth,
  type VoiceTypeRanges,
} from "./caption-motion.ts";

const RANGES: VoiceTypeRanges = {
  scale: [0.90, 1.20],
  scaleResponse: 0.25,
  scaleResponseQuiet: 0.25,
  scaleDeadband: 0,
  weight: [200, 760],
  weightEmphasis: 0.55,
  width: [82, 124],
};

const LITERAL: VoiceTypeRanges = {
  scale: [0.6, 2.4],
  scaleResponse: 1,
  scaleResponseQuiet: 1,
  scaleDeadband: 0,
  weight: [100, 1000],
  weightEmphasis: 0.55,
  width: [25, 150],
};

test("every motion is normal before and after its transient", () => {
  for (const voice of [
    {loudness: 0, pitchHz: 80, texture: 0},
    {loudness: 0.5, pitchHz: 180, texture: 0.5},
    {loudness: 1, pitchHz: 250, texture: 1},
  ]) {
    const plan = captionMotionFor(voice, RANGES, 1, 0.15);
    assert.deepEqual(plan.rest, NORMAL_CAPTION_TYPE);
  }
});

test("2.2.3 is a constant 15% growth on every voice", () => {
  const quiet = captionMotionFor(
    {loudness: 0, pitchHz: 250, texture: 1},
    RANGES,
    1,
    0.15,
  );
  const loud = captionMotionFor(
    {loudness: 1, pitchHz: 80, texture: 0},
    RANGES,
    0,
    0.15,
  );
  assert.deepEqual(quiet.sync, {scale: 1.15});
  assert.deepEqual(loud.sync, quiet.sync);
});

test("the enhanced pop is proportional to emphasis, and never zero", () => {
  // THE BAND THE REFERENCE LIVES IN IS UNREACHABLE WITH A FLAT STEP.
  // Measured across assets/reference_specs, 90% of words move and 60% land
  // between 1.02x and 1.15x. A constant pop can only ever produce two values,
  // so no gate threshold reproduces that -- which is why moving the gate
  // traded forty identical big pops for 79% of words not moving at all.
  const FLOOR = 0.5;
  const quiet = captionMotionFor(
    {loudness: 0, pitchHz: 250, texture: 1}, RANGES, 1, 0.15, FLOOR,
  );
  const loud = captionMotionFor(
    {loudness: 1, pitchHz: 80, texture: 0}, RANGES, 1, 0.15, FLOOR,
  );

  // An unemphasised word still moves -- the film's own rule is "every word
  // pops", and what it varies is by how much.
  assert.ok(quiet.sync.scale > 1,
    `an unemphasised word must still pop, got ${quiet.sync.scale}`);
  // ...but by strictly less than an emphatic one.
  assert.ok(loud.sync.scale > quiet.sync.scale,
    `emphasis must buy a bigger pop: ${loud.sync.scale} vs ${quiet.sync.scale}`);
  // The floor is exactly that: the quiet word takes FLOOR of the full pop.
  assert.ok(Math.abs(quiet.sync.scale - (1 + 0.15 * FLOOR)) < 1e-9);
  // And the ceiling is unchanged, so the loudest word renders as it always did.
  assert.ok(loud.sync.scale <= 1 + 0.15 + 1e-9);

  // Omitting the floor must keep LEGACY bit-identical: a flat step.
  const legacyQuiet = captionMotionFor(
    {loudness: 0, pitchHz: 250, texture: 1}, RANGES, 1, 0.15,
  );
  const legacyLoud = captionMotionFor(
    {loudness: 1, pitchHz: 80, texture: 0}, RANGES, 1, 0.15,
  );
  assert.deepEqual(legacyQuiet.sync, {scale: 1.15});
  assert.deepEqual(legacyLoud.sync, legacyQuiet.sync);
});

test("expression changes voice shape without weakening the synchronization cue", () => {
  const voice = {loudness: 1, pitchHz: 80, texture: 0};
  const off = captionMotionFor(voice, RANGES, 0, 0.15);
  const on = captionMotionFor(voice, RANGES, 1, 0.15);
  assert.deepEqual(off.voice, NORMAL_CAPTION_TYPE);
  assert.notDeepEqual(on.voice, NORMAL_CAPTION_TYPE);
  assert.deepEqual(off.sync, on.sync);
});

test("2.3.5: normal speaking volume maps to the baseline size", () => {
  const normal = (5 - 3) / (12 - 3);
  assert.equal(voiceScale(normal, LITERAL), 1);
  for (const scaleResponse of [1, 0.6, 0.25, 0]) {
    assert.equal(voiceScale(normal, {...RANGES, scaleResponse}), 1);
  }
});

test("2.3.6: the literal voice-size range is 3%..12% of screen height", () => {
  assert.equal(voiceScale(0, LITERAL), 3 / 5);
  assert.equal(voiceScale(1, LITERAL), 12 / 5);
});

test("2.3.8: the whole 160-200 Hz band is Regular 400", () => {
  for (const hz of [160, 168, 180, 191, 200]) {
    assert.equal(voiceTone(hz), 0);
    assert.equal(voiceWeight(voiceTone(hz), RANGES), 400);
    assert.equal(voiceWidth(voiceTone(hz), 0.5, RANGES), 100);
  }
});

test("2.3.9: low voices get heavier and high voices lighter", () => {
  assert.equal(voiceWeight(voiceTone(80), LITERAL), 1000);
  assert.equal(voiceWeight(voiceTone(250), LITERAL), 100);
  assert.equal(voiceWeight(voiceTone(40), RANGES), RANGES.weight[1]);
  assert.equal(voiceWeight(voiceTone(480), RANGES), RANGES.weight[0]);
});

test("an unvoiced word is neutral, not maximally deep", () => {
  assert.equal(voiceTone(0), 0);
  assert.equal(voiceTone(Number.NaN), 0);
  assert.equal(voiceWeight(voiceTone(0), RANGES), 400);
});

test("2.3.10: weight and width stay on the same diagonal", () => {
  for (let hz = 80; hz <= 250; hz += 10) {
    for (const texture of [0, 0.25, 0.5, 0.75, 1]) {
      const tone = voiceTone(hz);
      const weight = voiceWeight(tone, RANGES);
      const width = voiceWidth(tone, texture, RANGES);
      if (weight > 400) assert.ok(width >= 100, `heavy+condensed at ${hz} Hz`);
      if (weight < 400) assert.ok(width <= 100, `light+expanded at ${hz} Hz`);
    }
  }
});

test("every voice target stays inside its configured band", () => {
  for (const loudness of [-1, 0, 0.5, 1, 4, Number.NaN]) {
    for (const pitchHz of [-20, 0, 90, 180, 300, Number.NaN]) {
      for (const texture of [0, 0.5, 1, Number.NaN]) {
        const type = voiceTypeFor({loudness, pitchHz, texture}, RANGES);
        assert.ok(type.scale >= RANGES.scale[0] && type.scale <= RANGES.scale[1]);
        assert.ok(type.weight >= RANGES.weight[0] && type.weight <= RANGES.weight[1]);
        assert.ok(type.width >= RANGES.width[0] && type.width <= RANGES.width[1]);
      }
    }
  }
});

test("a contour is read by linear interpolation, endpoints included", () => {
  const values = [0, 1, 0];
  assert.equal(sampleContour(values, 0), 0);
  assert.equal(sampleContour(values, 0.5), 1);
  assert.equal(sampleContour(values, 1), 0);
  assert.equal(sampleContour(values, 0.25), 0.5);
  // Degenerate contours must not produce NaN styling.
  assert.equal(sampleContour([0.4], 0.9), 0.4);
  assert.ok(Number.isNaN(sampleContour([], 0.5)));
});

test("2.3 varies WITHIN a word, following its own contour", () => {
  // p.34's "dOWn!": quiet at the edges, shouted in the middle. The letters
  // must not all come out the same size -- that collapse is the defect.
  const envelope = {
    loudness: [0.1, 0.9, 0.9, 0.1],
    pitch: [200, 90, 90, 200],
    texture: [0.8, 0.1, 0.1, 0.8],
  };
  const types = characterVoiceTypes(
    4,
    envelope,
    {loudness: 0.5, pitchHz: 180, texture: 0.5},
    RANGES,
  );
  assert.equal(types.length, 4);
  assert.ok(types[1].scale > types[0].scale, "loud middle is larger");
  assert.ok(types[1].weight > types[0].weight, "low middle is heavier");
  // 2.3.10's diagonal has to hold per character too: heavy goes with wide.
  for (const type of types) {
    if (type.weight > 400) assert.ok(type.width >= 100, "heavy is not condensed");
    if (type.weight < 400) assert.ok(type.width <= 100, "light is not expanded");
  }
});

test("without an envelope every character keeps the word-level voice", () => {
  const word = {loudness: 0.8, pitchHz: 120, texture: 0.2};
  const types = characterVoiceTypes(3, null, word, RANGES);
  const single = voiceTypeFor(word, RANGES);
  assert.equal(types.length, 3);
  for (const type of types) assert.deepEqual(type, single);
});

test("expression scales the per-character shape toward normal", () => {
  const envelope = {
    loudness: [0.1, 0.9],
    pitch: [220, 90],
    texture: [0.9, 0.1],
  };
  const word = {loudness: 0.5, pitchHz: 180, texture: 0.5};
  const off = characterVoiceTypes(4, envelope, word, RANGES, 0);
  for (const type of off) assert.deepEqual(type, NORMAL_CAPTION_TYPE);
  const on = characterVoiceTypes(4, envelope, word, RANGES, 1);
  assert.ok(on.some((type) => type.scale !== 1 || type.weight !== 400));
});

test("the layout reservation follows the widest character, never below 1", () => {
  assert.equal(peakCharacterScale([]), 1);
  assert.equal(
    peakCharacterScale([
      {scale: 0.8, weight: 400, width: 100},
      {scale: 1.4, weight: 400, width: 100},
    ]),
    1.4,
  );
  // An all-quiet word still reserves its normal footprint.
  assert.equal(
    peakCharacterScale([{scale: 0.7, weight: 400, width: 100}]),
    1,
  );
});

test("ordinary speech does not move at all (2.3.5 deadband)", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 0.62, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  // The server pivots each speaker's MEDIAN onto 0.2222, so that is "ordinary".
  assert.equal(voiceScale(0.2222, ranges), 1);
  // ...and so is everything inside the band, on both sides.
  assert.equal(voiceScale(0.18, ranges), 1);
  assert.equal(voiceScale(0.42, ranges), 1);
});

test("a genuinely hushed word shrinks VISIBLY, not by 3%", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 0.62, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  const hushed = voiceScale(0, ranges);
  assert.ok(hushed < 0.85, `whisper only reached ${hushed.toFixed(3)}`);
  // Weakening the response instead of using a deadband produced a 0.90 floor
  // that the user could not see in a live test. Guard against regressing to it.
  assert.ok(hushed >= 0.72, "must stay inside the configured band");
});

test("size is monotone in loudness and continuous at the band edge", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 0.62, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  let previous = -Infinity;
  let biggestStep = 0;
  for (let level = 0; level <= 1.0001; level += 0.01) {
    const value = voiceScale(level, ranges);
    assert.ok(value >= previous - 1e-9, `not monotone at ${level.toFixed(2)}`);
    if (previous > -Infinity) biggestStep = Math.max(biggestStep, value - previous);
    previous = value;
  }
  // No jump at the edge of the deadband -- a discontinuity there would make
  // two words of near-identical volume render at obviously different sizes.
  assert.ok(biggestStep < 0.03, `discontinuity of ${biggestStep.toFixed(3)}`);
});

test("a shout is not drawn as the thinnest text on the stage", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 0.62, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  // The PR film's drill sergeant: 278 Hz against ~140 Hz of calm narration,
  // and loud. 2.3.9 alone sends that to the Light floor, so the angriest voice
  // in the film rendered as its thinnest type while the film draws it Black.
  const shout = voiceTypeFor({loudness: 0.95, pitchHz: 278, texture: 0.6}, ranges);
  assert.ok(shout.scale > 1.4, `shout only reached ${shout.scale.toFixed(3)}`);
  assert.ok(
    shout.weight > 400,
    `a loud 278 Hz word rendered at weight ${shout.weight}`,
  );

  // ORDINARY SPEECH IS UNTOUCHED: 2.3.9 is a statement about a VOICE, and at
  // ordinary volume it still owns the weight axis outright.
  const airy = voiceTypeFor({loudness: 0.22, pitchHz: 278, texture: 0.6}, ranges);
  assert.equal(airy.scale, 1);
  assert.equal(airy.weight, voiceWeight(voiceTone(278), ranges));
  assert.ok(airy.weight < 400, `quiet high voice rendered at ${airy.weight}`);
});

test("emphasis adds weight without breaking the 2.3.8 neutral band", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 0.62, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  // 160-200 Hz is the PDF's neutral BAND, and an unemphasised word in it must
  // still be exactly Regular.
  for (const hz of [160, 180, 200]) {
    assert.equal(voiceWeight(voiceTone(hz), ranges, 0), 400);
  }
  // Weight rises monotonically with emphasis and never leaves the range.
  let previous = -Infinity;
  for (let e = 0; e <= 1.0001; e += 0.05) {
    const weight = voiceWeight(voiceTone(320), ranges, e);
    assert.ok(weight >= previous, `not monotone in emphasis at ${e.toFixed(2)}`);
    assert.ok(weight >= 200 && weight <= 760, `out of range: ${weight}`);
    previous = weight;
  }
  // A LOW voice keeps its 2.3.9 weight and gains on top of it, rather than
  // being re-derived from emphasis alone.
  assert.ok(
    voiceWeight(voiceTone(90), ranges, 0.8) >
      voiceWeight(voiceTone(90), ranges, 0),
  );
});

test("the wave measures against the REACHABLE size band, not the clamp", () => {
  const ranges: VoiceTypeRanges = {
    scale: [0.72, 1.62], scaleResponse: 1.0, scaleResponseQuiet: 0.55,
    scaleDeadband: 0.34, weight: [200, 760], weightEmphasis: 0.55,
    width: [82, 124],
  };
  const [quiet, loud] = reachableScaleRange(ranges);
  // The quiet response caps the shrink well inside the configured clamp, so a
  // deviation keyed on the clamp can never reach 1 -- which left a fifth of the
  // character wave running on the most hushed word in the film.
  assert.ok(quiet > ranges.scale[0], `${quiet} should not reach the clamp`);
  assert.equal(loud, ranges.scale[1]);

  const hushed = voiceScale(0, ranges);
  assert.equal(voiceDeviationOf(hushed, ranges), 1);
  assert.equal(voiceDeviationOf(voiceScale(1, ranges), ranges), 1);
  // ...and an ordinary word inside the deadband deviates not at all, so it
  // keeps the whole wave.
  assert.equal(voiceDeviationOf(voiceScale(0.2222, ranges), ranges), 0);
});
