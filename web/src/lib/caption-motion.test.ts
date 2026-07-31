import assert from "node:assert/strict";
import test from "node:test";

import {
  captionMotionFor,
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
