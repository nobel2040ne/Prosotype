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
  /** How much of the 2.3.6 excursion is used above the 2.3.5 baseline. */
  scaleResponse: number;
  /**
   * ...and below it. Deliberately smaller.
   *
   * The two directions are not symmetric in what they cost. Growing a word
   * makes it easier to read and reads as emphasis; SHRINKING it makes it
   * harder to read, and the speaker's own loudness percentiles put a great
   * many ordinary words below the median. Measured on the bundled clip with a
   * symmetric response, 48% of all words rendered smaller than normal, down to
   * 0.75x -- ordinary unstressed speech drawn as if it were whispered, which
   * reads as instability rather than as intonation.
   */
  scaleResponseQuiet: number;
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
  const response = literal >= 1
    ? ranges.scaleResponse
    : ranges.scaleResponseQuiet;
  return clamp(1 + response * (literal - 1), minimum, maximum);
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
/**
 * The word's own intonation contour, sampled evenly across its spoken span.
 *
 * `loudness` is already on the 2.3.5-pivoted 0..1 scale (the server normalises
 * it through the same function as the word-level value), `pitch` is Hz, and
 * `texture` is 0..1 brightness, matching what `voiceWidth` already consumes.
 */
export interface VoiceEnvelope {
  loudness: readonly number[];
  pitch: readonly number[];
  texture: readonly number[];
}

/** Linear interpolation of a sampled contour at a 0..1 position. */
export function sampleContour(
  values: readonly number[],
  position: number,
): number {
  if (!values.length) return Number.NaN;
  if (values.length === 1) return values[0];
  const at = clamp(position, 0, 1) * (values.length - 1);
  const low = Math.floor(at);
  const high = Math.min(values.length - 1, low + 1);
  return values[low] + (values[high] - values[low]) * (at - low);
}

/**
 * CWI 2.3 IS PER CHARACTER. One `CaptionType` for each letter of the word.
 *
 * The design system's illustrations are the argument: p.34 sets "Put that
 * coffee dOWn!" beneath its own waveform with the `O` and `W` huge and the `d`
 * and `n!` small; p.38 varies weight across "neeee**eeeed**" under a pitch
 * curve; p.40 ramps one sentence from black to hairline. A single value per
 * word cannot express any of that, and collapsing to one is what made the
 * captions read as flat.
 *
 * Each character is placed at the centre of its share of the span and reads the
 * contour there. This is deliberately uniform rather than advance-weighted: the
 * recognizer gives no per-character alignment, so anything finer would be
 * invented rather than measured. Without an envelope every character falls back
 * to the word-level voice, which is exactly the previous behaviour.
 */
export function characterVoiceTypes(
  characterCount: number,
  envelope: VoiceEnvelope | null | undefined,
  wordVoice: {loudness: number; pitchHz: number; texture: number},
  ranges: VoiceTypeRanges,
  expression = 1,
): CaptionType[] {
  const count = Math.max(0, Math.floor(characterCount));
  const amount = clamp(Number.isFinite(expression) ? expression : 1, 0, 1);
  const types: CaptionType[] = [];
  for (let index = 0; index < count; index += 1) {
    const position = count === 1 ? 0.5 : (index + 0.5) / count;
    const loudness = envelope?.loudness?.length
      ? sampleContour(envelope.loudness, position)
      : wordVoice.loudness;
    const pitchHz = envelope?.pitch?.length
      ? sampleContour(envelope.pitch, position)
      : wordVoice.pitchHz;
    const texture = envelope?.texture?.length
      ? sampleContour(envelope.texture, position)
      : wordVoice.texture;
    const target = voiceTypeFor({loudness, pitchHz, texture}, ranges);
    types.push({
      scale: 1 + (target.scale - 1) * amount,
      weight: Math.round(400 + (target.weight - 400) * amount),
      width: Math.round(100 + (target.width - 100) * amount),
    });
  }
  return types;
}

/** The widest any character of this word gets, for the layout reservation. */
export function peakCharacterScale(types: readonly CaptionType[]): number {
  return types.reduce((peak, type) => Math.max(peak, type.scale), 1);
}

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
