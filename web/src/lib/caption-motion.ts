/**
 * The one-shot caption motion described by CWI 2.2.3 and 2.3.
 *
 * The live adaptation has an explicit lifecycle:
 *
 *   normal type -> voice-shaped crest + synchronization pop -> normal type
 *
 * Normal type owns layout. The voice-shaped type is painted on an overlaid
 * glyph during the motion window, so changing size, weight, or width cannot
 * reflow the caption row and no DOM measurement is required.
 *
 * WHEN it runs is not decided here, and is no longer decided by a scheduler at
 * all. Because the playhead (`caption-clock.ts`) presents captions behind the
 * acoustic clock, every word's colour turn has a known future moment, which is
 * handed to the browser as one `animation-delay`. The reveal queue, its
 * concurrency slots, its catch-up policy and its unpainted-reservation
 * watchdog were all machinery for guessing that moment from arrival order;
 * none of it survives.
 */

export interface VoiceTypeRanges {
  /** Reachable multiples of the 2.3.5 baseline. The PDF's span is 0.6..2.4. */
  scale: readonly [number, number];
  /** How much of the 2.3.6 excursion is used by the live presentation. */
  scaleResponse: number;
  /** Reachable `font-weight`. 400 is fixed at the 2.3.8 neutral band. */
  weight: readonly [number, number];
  /** Reachable `font-stretch` %. 100 is the neutral width. */
  width: readonly [number, number];
}

export interface CaptionType {
  scale: number;
  weight: number;
  width: number;
}

export interface CaptionMotionPlan {
  /** The exact type before and after motion. */
  rest: CaptionType;
  /** CWI 2.3 type at the expressive crest of the motion. */
  voice: CaptionType;
  /**
   * CWI 2.2.3's eye-guiding cue: ONE growth, anchored at the baseline.
   *
   * There is no elevation term. The diagram's "25% elevation" is what
   * scaling about the glyph box's bottom does to the TOP of the word; as a
   * separate translation it made the word hop instead of grow. See the
   * `word-sync-pop` keyframe.
   */
  sync: {
    scale: number;
  };
}

export const NORMAL_CAPTION_TYPE: Readonly<CaptionType> = Object.freeze({
  scale: 1,
  weight: 400,
  width: 100,
});

/** CWI 2.3.6: smallest 3%, largest 12%; 2.3.5: normal baseline 5%. */
const SIZE_MIN_PCT = 3;
const SIZE_MAX_PCT = 12;
const SIZE_BASELINE_PCT = 5;

/** CWI 2.3.8/2.3.9 pitch anchors. */
const PITCH_NEUTRAL_LOW_HZ = 160;
const PITCH_NEUTRAL_HIGH_HZ = 200;
const PITCH_FLOOR_HZ = 80;
const PITCH_CEILING_HZ = 250;

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));

/**
 * Low/rich (+1) through neutral (0) to high/thin (-1).
 *
 * The complete 160–200 Hz range is neutral. A missing/unvoiced 0 Hz reading is
 * also neutral rather than being treated as an impossibly low voice.
 */
export function voiceTone(pitchHz: number): number {
  if (!Number.isFinite(pitchHz) || pitchHz <= 0) return 0;
  if (pitchHz < PITCH_NEUTRAL_LOW_HZ) {
    return (PITCH_NEUTRAL_LOW_HZ - Math.max(pitchHz, PITCH_FLOOR_HZ)) /
      (PITCH_NEUTRAL_LOW_HZ - PITCH_FLOOR_HZ);
  }
  if (pitchHz <= PITCH_NEUTRAL_HIGH_HZ) return 0;
  return -(Math.min(pitchHz, PITCH_CEILING_HZ) - PITCH_NEUTRAL_HIGH_HZ) /
    (PITCH_CEILING_HZ - PITCH_NEUTRAL_HIGH_HZ);
}

/** Volume -> type size, anchored on §2.3.5 and bounded by §2.3.6. */
export function voiceScale(
  loudness: number,
  ranges: VoiceTypeRanges,
): number {
  const level = clamp(Number.isFinite(loudness) ? loudness : 0.5, 0, 1);
  const pct = SIZE_MIN_PCT + level * (SIZE_MAX_PCT - SIZE_MIN_PCT);
  const literal = pct / SIZE_BASELINE_PCT;
  const [minimum, maximum] = ranges.scale;
  return clamp(1 + ranges.scaleResponse * (literal - 1), minimum, maximum);
}

/** Pitch -> type weight, with §2.3.8's complete neutral band held at 400. */
export function voiceWeight(tone: number, ranges: VoiceTypeRanges): number {
  const [floor, ceiling] = ranges.weight;
  const shaped = tone > 0 ? tone * (ceiling - 400) : tone * (400 - floor);
  return Math.round(clamp(400 + shaped, floor, ceiling));
}

/**
 * Harmonics -> width, constrained to §2.3.10's heavy+wide / light+condensed
 * diagonal. The available texture estimate refines pitch but cannot contradict
 * it.
 */
export function voiceWidth(
  tone: number,
  texture: number,
  ranges: VoiceTypeRanges,
): number {
  const harmonics = Number.isFinite(texture)
    ? clamp((0.5 - texture) * 2, -1, 1)
    : 0;
  let blended = clamp(tone * 0.7 + harmonics * 0.3, -1, 1);
  if (tone > 0) blended = Math.max(blended, 0);
  if (tone < 0) blended = Math.min(blended, 0);
  const [floor, ceiling] = ranges.width;
  const shaped = blended > 0
    ? blended * (ceiling - 100)
    : blended * (100 - floor);
  return Math.round(clamp(100 + shaped, floor, ceiling));
}

export function voiceTypeFor(
  {loudness, pitchHz, texture}: {
    loudness: number;
    pitchHz: number;
    texture: number;
  },
  ranges: VoiceTypeRanges,
): CaptionType {
  const tone = voiceTone(pitchHz);
  return {
    scale: voiceScale(loudness, ranges),
    weight: voiceWeight(tone, ranges),
    width: voiceWidth(tone, texture, ranges),
  };
}

/**
 * Build the whole motion without inspecting rendered geometry.
 *
 * Expression only interpolates the §2.3 voice target. The §2.2.3 cue remains
 * the same 15% / 25% on every word, as required by the PDF.
 */
export function captionMotionFor(
  voice: {loudness: number; pitchHz: number; texture: number},
  ranges: VoiceTypeRanges,
  expression: number,
  syncPop: number,
): CaptionMotionPlan {
  const target = voiceTypeFor(voice, ranges);
  const amount = clamp(Number.isFinite(expression) ? expression : 1, 0, 1);
  return {
    rest: {...NORMAL_CAPTION_TYPE},
    voice: {
      scale: 1 + (target.scale - 1) * amount,
      weight: Math.round(400 + (target.weight - 400) * amount),
      width: Math.round(100 + (target.width - 100) * amount),
    },
    sync: {
      scale: 1 + Math.max(0, syncPop),
    },
  };
}
