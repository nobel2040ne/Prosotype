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
  /**
   * Fraction of each side's range where the size does not move at all.
   *
   * Ordinary speech lives near the speaker's median; without this band every
   * unstressed word drifts smaller and the captions read as unstable.
   */
  scaleDeadband: number;
  /** Reachable `font-weight`. 400 is fixed at the 2.3.8 neutral band. */
  weight: readonly [number, number];
  /**
   * How much of the weight range an emphasised word takes, on top of 2.3.9.
   *
   * WITHOUT THIS THE WEIGHT CHANNEL ARGUES WITH THE VOLUME CHANNEL AND WINS.
   * 2.3.9 maps high pitch to LIGHT, and a shout raises F0 -- the PR film's
   * drill sergeant goes 140 Hz -> 278 Hz -- so the angriest voice in the film
   * rendered here at weight 200, the configured Light floor: the thinnest text
   * on the stage. The film does the opposite, unmistakably: crop its "louder"
   * at peak (t=16.7 s) beside the same word settled (t=18.0 s) and it is
   * Regular at rest and Black at 2.08x.
   *
   * The reconciliation is 2.3.7's own domain. "The frequency range of a
   * typical human voice falls between 80 and 250 Hz", and the pitch->weight
   * map describes a VOICE -- "lower voices ... are represented with a heavier
   * weight", a property of who is speaking. A 278 Hz shout is not an airy
   * voice, it is effort, and it leaves that domain entirely. So the Light half
   * is withdrawn in proportion to emphasis, and emphasis adds weight of its
   * own; ordinary speech, which is what 2.3.9 is about, is untouched.
   */
  weightEmphasis: number;
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

/**
 * Where the 2.3.5 baseline sits on the server's normalised 0..1 loudness.
 *
 * The server pivots each speaker's running median onto this point, so a word of
 * ordinary volume arrives here and renders at exactly 1.0.
 */
const LOUDNESS_PIVOT =
  (SIZE_BASELINE_PCT - SIZE_MIN_PCT) / (SIZE_MAX_PCT - SIZE_MIN_PCT);

/**
 * Volume -> type size, anchored on §2.3.5 and bounded by §2.3.6.
 *
 * THE DEADBAND IS WHAT MAKES THE QUIET HALF USABLE. Without one, every word
 * below the speaker's median shrinks a little: measured on the bundled clip,
 * 48% of ALL words rendered below normal, so ordinary unstressed speech was
 * drawn as if whispered. Weakening the response instead only made the whole
 * quiet channel invisible (a 10% floor that never reads on screen).
 *
 * A band around the median where the size does not move at all fixes both:
 * ordinary words sit at exactly 1.0, and everything outside the band gets the
 * FULL response, so a genuinely hushed word visibly shrinks. The band is a
 * fraction of each side's own range, because the pivot is not centred -- the
 * quiet half spans 0..0.22 and the loud half 0.22..1.
 */
export function voiceScale(
  loudness: number,
  ranges: VoiceTypeRanges,
): number {
  const level = clamp(Number.isFinite(loudness) ? loudness : 0.5, 0, 1);
  const deviation = level - LOUDNESS_PIVOT;
  const sideRange = deviation >= 0 ? 1 - LOUDNESS_PIVOT : LOUDNESS_PIVOT;
  const dead = clamp(ranges.scaleDeadband, 0, 0.95) * sideRange;
  const [minimum, maximum] = ranges.scale;
  if (Math.abs(deviation) <= dead) return 1;

  // Re-span what is left of the side so the mapping stays continuous at the
  // band edge and still reaches 2.3.6's limit at the extreme.
  const shaped = (Math.abs(deviation) - dead) / Math.max(1e-6, sideRange - dead);
  const limit = deviation >= 0
    ? SIZE_MAX_PCT / SIZE_BASELINE_PCT
    : SIZE_MIN_PCT / SIZE_BASELINE_PCT;
  const response = deviation >= 0
    ? ranges.scaleResponse
    : ranges.scaleResponseQuiet;
  return clamp(1 + response * shaped * (limit - 1), minimum, maximum);
}

/**
 * Pitch -> type weight, with §2.3.8's complete neutral band held at 400.
 *
 * `prominence` is how loud this word is for its speaker, 0..1, BEFORE the size
 * deadband. At 0 this is exactly the PDF's mapping.
 *
 * THE TWO HALVES USED TO BE SCALED AGAINST DIFFERENT WIDTHS, AND THAT ALONE
 * MADE SHOUTS THIN. The pitch term was scaled by the LIGHT half
 * (`400 - floor`) while the emphasis bonus was scaled by the BOLD half
 * (`ceiling - 400`). At the shipped [200, 760] those are 200 and 360, so for
 * any voice at or above 250 Hz -- where `voiceTone` saturates at -1 -- the
 * whole function collapsed to `200 + 398p`, crossing Regular only at p = 0.50.
 * `weightEmphasis` had to exceed `(400-floor)/(ceiling-400)` = 0.556 for a
 * fully-emphasised shout merely to RETURN to Regular, and the shipped value
 * was 0.55 -- under the threshold by 0.006. MEASURED consequence: 72 of the
 * film's 165 words (44%) rendered lighter than Regular, the drill sergeant
 * among them, where the reference lightens 5 of 48 and never past -53.
 * Both terms now scale against the same half, so `weightEmphasis` means what
 * its name says and no arithmetic accident can put an emphasised word below
 * Regular.
 *
 * IT ALSO TAKES PROMINENCE, NOT THE POST-DEADBAND SIZE. It used to read
 * `emphasisOf(voiceScale(loudness))`, and `voice_scale_deadband` pins that at
 * exactly 0 up to normalised loudness ~0.485 -- so every word inside the band,
 * which is most of them, got pure 2.3.9 and went to the floor if high-pitched.
 * The deadband exists so an ordinary word does not RESIZE; it was never meant
 * to silence the weight channel too.
 */
export function voiceWeight(
  tone: number,
  ranges: VoiceTypeRanges,
  prominence = 0,
): number {
  const [floor, ceiling] = ranges.weight;
  const pushed = clamp(Number.isFinite(prominence) ? prominence : 0, 0, 1);
  const bold = ceiling - 400;
  const light = 400 - floor;
  // The register half, withdrawn as the voice is pushed: a pressed voice is
  // not an airy one, whatever its pitch.
  const register = tone < 0 ? tone * (1 - pushed) : tone;
  const shaped = register > 0 ? register * bold : register * light;
  // ...and the prominence half. The light half is now shallow enough
  // (`weight_range`'s floor is set from the reference's own worst lightening,
  // -53 from Regular) that this can never be out-run by it.
  const pressed = pushed * clamp(ranges.weightEmphasis ?? 0, 0, 1) * bold;
  return Math.round(clamp(400 + shaped + pressed, floor, ceiling));
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

/**
 * The size band `voiceScale` can ACTUALLY produce, which is not `ranges.scale`.
 *
 * `scale` is a clamp; the response is what the mapping really reaches, and on
 * the quiet side the two differ a lot -- configured 0.72, reachable 0.78,
 * because `scaleResponseQuiet` is 0.55. Anything that asks "how far from
 * normal is this word, as a fraction of the possible" has to divide by the
 * REACHABLE extreme or it can never reach 1: measured, the most hushed word in
 * the film scored 0.786, so a wave suppression keyed on the configured range
 * left 21% of the wave running on "softer." -- a word the reference sets as
 * six glyphs held together, with no scatter at all.
 */
export function reachableScaleRange(
  ranges: VoiceTypeRanges,
): [number, number] {
  const loud = Math.min(
    ranges.scale[1],
    1 + ranges.scaleResponse * (SIZE_MAX_PCT / SIZE_BASELINE_PCT - 1),
  );
  const quiet = Math.max(
    ranges.scale[0],
    1 - ranges.scaleResponseQuiet * (1 - SIZE_MIN_PCT / SIZE_BASELINE_PCT),
  );
  return [quiet, loud];
}

/**
 * How loud this word is for its speaker, 0..1, BEFORE the size deadband.
 *
 * `emphasisOf` reads the size the word ended up at, so it inherits
 * `voice_scale_deadband` and is exactly 0 for every word inside the band --
 * which is most of them. That is right for anything asking "how much did this
 * word GROW", and wrong for anything asking "how prominent is this word",
 * because the band exists only to stop ordinary words resizing.
 */
export function prominenceOf(loudness: number): number {
  const level = clamp(Number.isFinite(loudness) ? loudness : LOUDNESS_PIVOT, 0, 1);
  return clamp((level - LOUDNESS_PIVOT) / (1 - LOUDNESS_PIVOT), 0, 1);
}

/** How far up the reachable §2.3.6 range this word's size sits, 0..1. */
export function emphasisOf(scale: number, ranges: VoiceTypeRanges): number {
  const top = Math.max(reachableScaleRange(ranges)[1], 1 + 1e-6);
  return clamp((scale - 1) / (top - 1), 0, 1);
}

/**
 * How far this word's size departs from normal, 0..1, on whichever side it is.
 *
 * A whisper and a shout both read as 1, so the character wave can trade off
 * against the word-level swell symmetrically.
 */
export function voiceDeviationOf(
  scale: number,
  ranges: VoiceTypeRanges,
): number {
  const [quiet, loud] = reachableScaleRange(ranges);
  const span = scale >= 1
    ? Math.max(1e-6, loud - 1)
    : Math.max(1e-6, 1 - quiet);
  return clamp(Math.abs(scale - 1) / span, 0, 1);
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
  const scale = voiceScale(loudness, ranges);
  return {
    scale,
    weight: voiceWeight(tone, ranges, prominenceOf(loudness)),
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
