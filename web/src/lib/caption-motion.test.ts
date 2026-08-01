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
  voiceWeight,
  voiceWidth,
  type VoiceTypeRanges,
} from "./caption-motion.ts";

const RANGES: VoiceTypeRanges = {
  scale: [0.90, 1.20],
  scaleResponse: 0.25,
  weight: [200, 760],
  width: [82, 124],
};

const LITERAL: VoiceTypeRanges = {
  scale: [0.6, 2.4],
  scaleResponse: 1,
  weight: [100, 1000],
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
