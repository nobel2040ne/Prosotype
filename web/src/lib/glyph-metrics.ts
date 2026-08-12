/** Where a caption word's BASELINE sits inside its own box. CWI grows a word
   from its baseline and never moves it. */

/** Distance from an element's box bottom up to its text baseline, in em. */
export function baselineOffsetEm(
  box: DOMRect,
  strut: DOMRect,
  fontSizePx: number,
): number | null {
  if (!Number.isFinite(fontSizePx) || fontSizePx <= 0) return null;
  if (!Number.isFinite(box.bottom) || !Number.isFinite(strut.bottom)) {
    return null;
  }
  const offset = (box.bottom - strut.bottom) / fontSizePx;
  // A sane line box puts the baseline inside itself. Anything outside that is a
  // measurement taken before layout settled, and the fallback is safer.
  if (!Number.isFinite(offset) || offset < 0 || offset > 1) return null;
  return offset;
}

/** Round to a stable string so re-measuring cannot churn the CSS variable. */
export function formatBaselineEm(offsetEm: number): string {
  return `${offsetEm.toFixed(4)}em`;
}

/**
 * ...AND THE PIVOT ALONE IS NOT ENOUGH, WHICH TOOK A FOURTH ATTEMPT TO SEE.
 *
 * The 2.3 crest is carried as a FONT-SIZE on `.word-ink`, so it is the one
 * voice channel that changes a BOX and not just its paint. `.word-glyph` is
 * `position: absolute; bottom: 0` with an auto height, so its height IS its
 * line box — and `.word-ink` is a baseline-aligned inline-block whose depth
 * below the baseline is `baselineEm * crestScale`, against the strut's fixed
 * `baselineEm`. The line box takes the max of the two INDEPENDENTLY above and
 * below the baseline, so with the box BOTTOM pinned the word's baseline rides
 * up by `baselineEm * (crestScale - 1)` while every neighbour's stays put.
 *
 * Measured before the correction, guide taken per frame from a settled
 * neighbour in the same row: the rise correlated **0.867** with
 * `0.3799 * (crest - 1) * restingFontPx`, "louder" sat **+0.201em** off the
 * line and the largest words **+0.236em**. The design system's own numbers say
 * it must be zero — regressing peak lift on peak size across the 48 words in
 * `assets/reference_specs/*.json` gives a slope of **+0.043**, and its single
 * biggest word, "louder" at 2.21x, has a lift of exactly **0.000**.
 *
 * Note the geometry HINGES at `crestScale = 1` rather than passing smoothly
 * through it: below 1 the strut is the deeper half and nothing moves at all.
 * That is why "softer" — which SHRINKS — measured clean and masked this for so
 * long, and it is what the two `max()` clamps in the stylesheet encode.
 *
 * This module is the MODEL. `globals.css` is the implementation, and only the
 * pixel probe (`scripts/baseline_probe.py`) proves the two agree.
 */
export interface CrestGeometry {
  /** `--glyph-baseline-em`: box bottom -> baseline, in the element's own em. */
  baselineEm: number;
  /** `.caption-words`' unitless `line-height`. */
  lineHeightEm: number;
  /** `--crest-scale`: `.word-ink`'s font-size multiplier. */
  crestScale: number;
  /** `word-sync-pop`'s instantaneous `scale()` on `.word-glyph`. */
  popScale: number;
}

/** The two declarations the stylesheet writes on `.word-glyph`. */
export interface GlyphPlacement {
  /** `transform-origin`'s y, as a distance ABOVE the box bottom, in em. */
  originAboveBottomEm: number;
  /** The `translate` property's y, positive = DOWN, in em. */
  translateDownEm: number;
}

/** Where the ink's baseline sits above `.word-glyph`'s box bottom, in em. */
export function inkBaselineAboveBottomEm(geometry: CrestGeometry): number {
  return geometry.baselineEm * Math.max(1, geometry.crestScale);
}

/** `.word-glyph`'s line-box height, in caption em. */
export function glyphBoxHeightEm(geometry: CrestGeometry): number {
  const above = geometry.lineHeightEm - geometry.baselineEm;
  return (
    Math.max(above, above * geometry.crestScale) +
    inkBaselineAboveBottomEm(geometry)
  );
}

/** What the stylesheet declares so a word grows FROM the row's baseline. */
export function crestGlyphPlacement(geometry: CrestGeometry): GlyphPlacement {
  return {
    originAboveBottomEm: inkBaselineAboveBottomEm(geometry),
    translateDownEm: geometry.baselineEm * Math.max(0, geometry.crestScale - 1),
  };
}

/** What shipped before the correction: an unscaled pivot and no shift. */
export function uncorrectedGlyphPlacement(
  geometry: CrestGeometry,
): GlyphPlacement {
  return {originAboveBottomEm: geometry.baselineEm, translateDownEm: 0};
}

/** How far the word's baseline sits ABOVE a settled neighbour's, in em.
   Positive = risen off the line, which CWI does not have. */
export function baselineRiseEm(
  geometry: CrestGeometry,
  placement: GlyphPlacement,
): number {
  const baseline = inkBaselineAboveBottomEm(geometry);
  // `transform`'s scale is about the origin; the `translate` PROPERTY composes
  // outside it, in the parent's frame, so the pop never multiplies it.
  const scaled =
    placement.originAboveBottomEm +
    geometry.popScale * (baseline - placement.originAboveBottomEm);
  return scaled - placement.translateDownEm - geometry.baselineEm;
}
