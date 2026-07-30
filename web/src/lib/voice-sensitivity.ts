/**
 * Voice-shaped type axes: resolution near the speaker's centre, and continuous
 * amplitude with no trigger threshold.
 *
 * Two invariants, both load-bearing:
 *   - endpoints stay pinned, so the reachable extremes never grow (this is what
 *     stops ordinary speech rendering as fabricated whispers/shouts);
 *   - this is INTONATION (CWI 2.3.3-2.3.6) only. Never apply it to the constant
 *     synchronization cue (2.2.3), whose amplitude is identical for a shout and
 *     a whisper by design.
 *
 * CLAUDE.md carries the measurements and the calibration traps.
 */

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

/**
 * Steepen a normalized value's response near `center`, pinning both endpoints.
 *
 * @param value  measured value, expected within [minimum, maximum]
 * @param center the value that must map to itself (median / baseline)
 * @param gamma  < 1 expands small deviations; 1 is a no-op; > 1 compresses
 */
export function expandAroundCenter(
  value: number,
  center = 0.5,
  gamma = 1,
  minimum = 0,
  maximum = 1,
): number {
  if (!Number.isFinite(value)) return center;
  const bounded = clamp(value, minimum, maximum);
  if (!(gamma > 0) || gamma === 1) return bounded;

  // Each side is normalized by its OWN extent, so an off-centre baseline (a
  // high voice sitting near the top of the pitch range) still reaches its
  // endpoint instead of saturating early.
  const deviation = bounded - center;
  if (deviation === 0) return center;
  const extent = deviation > 0 ? maximum - center : center - minimum;
  if (extent <= 0) return center;

  const normalized = Math.abs(deviation) / extent;
  const expanded = Math.pow(normalized, gamma);
  return center + Math.sign(deviation) * expanded * extent;
}

export interface DeliveryReading {
  /** loudness/energy of the word, 0..1 */
  force: number;
  /** onset sharpness, 0..1 */
  attack: number;
  /** first-to-last F0 direction, -1..1 */
  contour: number;
  /** voiced continuity, 0..1 */
  flow: number;
  /** breathiness / spectral texture, 0..1 */
  texture: number;
}

/**
 * How much voice-shaped deviation a word earns — CONTINUOUS, no gate.
 *
 * Returns `floor..1`, with NO dead zone: an almost-neutral word returns a small
 * but non-zero value. `delivery_profile` still picks the motion family; it must
 * never again decide amplitude. The floor is only what a genuinely flat word
 * gets — nothing is snapped to it, so it is not a threshold.
 */
export function deliveryExpressiveness(
  reading: DeliveryReading,
  floor = 0.34,
  gamma = 0.62,
  forceNeutral = 0.30,
): number {
  const force = clamp(finite(reading.force, forceNeutral), 0, 1);
  const attack = clamp(finite(reading.attack), 0, 1);
  const contour = clamp(finite(reading.contour), -1, 1);

  // Only `contour` and `attack` have a DEFINITIONAL neutral (0 = level pitch,
  // 0 = soft onset), so only they can be read as a distance from neutral without
  // knowing the speaker. `force`, `flow` and `texture` do not: measured on the
  // bundled sample their medians are 0.283 / 0.478 / 0.582, and centring them at
  // 0.5 scored ordinary words as near-maximal deviation -- an unremarkable "You"
  // has flow 0.028 -- which inflated every word to ~0.79 against the old 0.30
  // and would have put the whole transcript in constant motion.
  //
  // `force` is therefore measured against a configured typical level, and `flow`
  // and `texture` are excluded from the magnitude entirely. They still drive
  // their own channels and the family choice; they just cannot fake emphasis.
  // A force of exactly zero means the estimator produced nothing for this word
  // (too short, or unvoiced), not that the speaker fell silent. Measured on the
  // sample, such words scored 0.618 -- MORE expressive than a word at typical
  // force -- so an absent measurement was reading as emphasis. Treat it as
  // neutral instead of maximally quiet.
  const forceMeasured = force > 1e-6;
  const deviations = [
    Math.abs(contour),
    attack,
    forceMeasured
      ? Math.abs(force - forceNeutral) / Math.max(forceNeutral, 1 - forceNeutral)
      : 0,
  ];

  // Euclidean magnitude rather than a max, so several mild cues combine into a
  // clearly expressive word instead of each being judged alone against a gate.
  const magnitude = Math.sqrt(
    deviations.reduce((total, value) => total + value * value, 0) /
      deviations.length,
  );
  // The same power curve used for the axes: steep near neutral, flat near the
  // extreme, so small differences separate and loud words do not all saturate.
  const shaped = Math.pow(clamp(magnitude, 0, 1), gamma);
  return clamp(floor + (1 - floor) * shaped, floor, 1);
}

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Expand a pitch reading around the speaker's own running baseline.
 *
 * Pitch is not normalized upstream, so the centre is the baseline in Hz rather
 * than 0.5. A speaker whose baseline is 110 Hz and one at 210 Hz both get their
 * own small inflections expanded, instead of the low voice spending its whole
 * range in the bottom third of a fixed 80-250 Hz map.
 */
export function expandPitch(
  pitchHz: number,
  baselineHz: number,
  gamma = 1,
  minimum = 80,
  maximum = 250,
): number {
  const baseline = clamp(
    Number.isFinite(baselineHz) ? baselineHz : 180,
    minimum,
    maximum,
  );
  return expandAroundCenter(pitchHz, baseline, gamma, minimum, maximum);
}
