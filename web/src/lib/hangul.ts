/** Script classification and Hangul syllable structure. */

/** Does this character occupy a full em — East Asian Wide or Fullwidth? */
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

/** Should this WORD render with the continuous wipe rather than per-glyph
   steps? */
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

/** A Hangul syllable's composition class, from the code point alone. */
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

/** Signed wave amplitudes for one syllable, so the stretch follows the
   block's own composition axis rather than a Latin shape. */
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
