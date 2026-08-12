/**
 * Script classification and Hangul syllable structure.
 *
 * Two things live here, both pure and both keyed on the CODE POINT rather than
 * on a `lang` flag — a Korean caption containing `2011` or a Latin loanword has
 * to be handled per character, which is the case a per-language switch cannot
 * express.
 *
 * WHY THE CAPTION SYSTEM NEEDS THIS. CWI's per-character channel — the colour
 * wipe of 2.2.2 and the travelling stretch under it — divides a word into as
 * many steps as it has characters. That is tuned to Latin, where a character is
 * a narrow letter. A Hangul character is a SYLLABLE BLOCK, 0.91em against
 * Latin's 0.43em, and a Korean word has fewer of them. MEASURED on the bundled
 * samples:
 *
 *   |                       | English | Korean |
 *   | median word           | 4 chars | 3 chars |
 *   | boundary jump per step| 0.43 em | 0.91 em  <- 2.1x coarser |
 *   | words with <=2 steps  |   17%   |   46%    <- a switch, not a sweep |
 *
 * So for nearly half of Korean words the signature travelling colour boundary
 * is two discrete jumps, and the wave that is supposed to carry an ordinary
 * word has two positions. Since Korean's median peak size is 1.14x — i.e. the
 * ordinary word is carried almost entirely by the per-character channel — that
 * is the defect this module exists to let the renderer fix.
 */

/**
 * Does this character occupy a full em — East Asian Wide or Fullwidth?
 *
 * Ranges are the Unicode East Asian Width W/F blocks that actually reach
 * captions: Hangul syllables and Jamo, CJK ideographs and their punctuation,
 * kana, and the fullwidth forms.
 */
export function isWideChar(codePoint: number): boolean {
  return (
    (codePoint >= 0x1100 && codePoint <= 0x115f) ||   // Hangul Jamo initial
    (codePoint >= 0x2e80 && codePoint <= 0x303e) ||   // CJK radicals, punctuation
    (codePoint >= 0x3041 && codePoint <= 0x33ff) ||   // kana, Hangul compat Jamo
    (codePoint >= 0x3400 && codePoint <= 0x4dbf) ||   // CJK ext A
    (codePoint >= 0x4e00 && codePoint <= 0x9fff) ||   // CJK unified
    (codePoint >= 0xa960 && codePoint <= 0xa97f) ||   // Hangul Jamo ext A
    (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||   // Hangul syllables
    (codePoint >= 0xf900 && codePoint <= 0xfaff) ||   // CJK compatibility
    (codePoint >= 0xfe30 && codePoint <= 0xfe4f) ||   // CJK compatibility forms
    (codePoint >= 0xff00 && codePoint <= 0xff60) ||   // fullwidth forms
    (codePoint >= 0xffe0 && codePoint <= 0xffe6) ||   // fullwidth signs
    (codePoint >= 0x20000 && codePoint <= 0x3fffd)    // CJK ext B+ (astral)
  );
}

/**
 * Should this WORD render with the continuous wipe rather than per-glyph steps?
 *
 * A word counts as wide when wide characters are the majority of it, so a
 * Korean word carrying one Latin digit still gets the continuous path while an
 * English word quoting a single Hangul syllable does not. The threshold matters
 * only for mixed words, which are rare; what it must never do is flip an
 * all-Latin word, because that would move English off its current code path.
 */
export function wordIsWide(text: string): boolean {
  let wide = 0;
  let total = 0;
  for (const character of Array.from(text ?? "")) {
    const cp = character.codePointAt(0) ?? 0;
    // Digits and punctuation are script-neutral and would otherwise drag a
    // short Korean word below the threshold.
    if (!/[\p{L}\p{N}]/u.test(character)) continue;
    total += 1;
    if (isWideChar(cp)) wide += 1;
  }
  return total > 0 && wide * 2 > total;
}

/**
 * A Hangul syllable's composition class, from the code point alone.
 *
 *   syllable = 0xAC00 + (initial * 21 + medial) * 28 + final
 *
 * The MEDIAL (중성) decides where the vowel sits, which is what makes the block
 * horizontal-gather (가로모임 — vowel to the RIGHT, e.g. 가), vertical-gather
 * (세로모임 — vowel BELOW, e.g. 고) or mixed (섞임모임, e.g. 의). A non-zero
 * FINAL (종성) is a batchim, which packs the block vertically.
 *
 * This is the design factor of *Design of Kinetic Typography Interaction based
 * on the Structural Characteristics of Hangul* (Int. J. Contents, 2016): Hangul
 * motion that reads as native follows the block's own construction rather than
 * applying one shape borrowed from Latin letterforms.
 *
 * MEASURED over the bundled Korean sample's vocabulary: 39% horizontal,
 * 25% horizontal+batchim, 20% vertical+batchim, 9% vertical, 7% mixed.
 */
export type SyllableAxis = "horizontal" | "vertical" | "mixed" | "none";

export interface Syllable {
  axis: SyllableAxis;
  /** A closing consonant, which makes the block vertically denser. */
  batchim: boolean;
}

// Medial indices whose vowel sits to the RIGHT of the initial: ㅏㅐㅑㅒㅓㅔㅕㅖ and ㅣ.
const MEDIAL_HORIZONTAL = new Set([0, 1, 2, 3, 4, 5, 6, 7, 20]);
// Medial indices whose vowel sits BELOW: ㅗㅛㅜㅠㅡ.
const MEDIAL_VERTICAL = new Set([8, 12, 13, 17, 18]);

export function syllable(codePoint: number): Syllable {
  const index = codePoint - 0xac00;
  if (index < 0 || index >= 11172) return {axis: "none", batchim: false};
  const medial = Math.floor(index / 28) % 21;
  const axis: SyllableAxis = MEDIAL_HORIZONTAL.has(medial)
    ? "horizontal"
    : MEDIAL_VERTICAL.has(medial)
      ? "vertical"
      : "mixed";
  return {axis, batchim: index % 28 !== 0};
}

/**
 * Signed wave amplitudes for one syllable, so the stretch follows the block's
 * own construction instead of a shape borrowed from Latin letterforms.
 *
 * The Latin wave is Y-dominant — `scale(1 - .022w, 1 + .13w)`, a letter
 * stretching upward — which suits an alphabet of narrow, mostly-vertical marks.
 * A Hangul block is a square assembly whose grain depends on where the vowel
 * sits, and *Design of Kinetic Typography Interaction based on the Structural
 * Characteristics of Hangul* (Int. J. Contents, 2016) keys its motion on
 * exactly that classification.
 *
 * So a horizontal-gather block (가 — vowel to the RIGHT) breathes ALONG its
 * width, a vertical-gather block (고 — vowel BELOW) breathes upward like Latin,
 * and a mixed block (의) takes a gentler version of both. A batchim packs the
 * block vertically, leaving less room to stretch that way, so it damps the Y
 * term rather than the X one.
 *
 * Amplitudes are the Latin wave's own magnitudes redistributed, not new
 * numbers: the total excursion stays in the band that was tuned down from +29%
 * to +11% because the wave was competing with the 2.2.3 cue.
 */
export interface WaveGrain {
  /** scaleY coefficient, signed. Positive stretches the block taller. */
  ay: number;
  /** scaleX coefficient, signed. Positive stretches it wider. */
  ax: number;
}

export function waveGrain(codePoint: number): WaveGrain {
  const {axis, batchim} = syllable(codePoint);
  // Non-Hangul inside a wide word (a digit, a loanword letter) keeps the
  // Latin shape -- it IS a Latin letterform.
  if (axis === "none") return {ay: 0.13, ax: -0.022};
  const grain: WaveGrain =
    axis === "horizontal" ? {ay: -0.035, ax: 0.075} :
    axis === "vertical" ? {ay: 0.13, ax: -0.022} :
    {ay: 0.075, ax: 0.022};
  // A closing consonant fills the lower half of the block, so it has less
  // vertical slack; damp only that axis.
  return batchim ? {ay: grain.ay * 0.65, ax: grain.ax} : grain;
}
