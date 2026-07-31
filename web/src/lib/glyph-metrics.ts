/**
 * Where a caption word's BASELINE sits inside its own box.
 *
 * CWI grows a word from its baseline and never moves it. Verified by looking at
 * all three recordings in `docs/reference/` with a baseline guide taken, per
 * frame, from a static neighbouring word: in `intonation.mov` the word "louder"
 * reaches roughly FOUR times the size of the text beside it and its ink bottom
 * stays exactly on the shared baseline; `character_identification.mov` shows
 * read-ahead and spoken words at visibly different sizes all sitting on one
 * line. Zero vertical displacement, at any size.
 *
 * CSS cannot express that directly. `transform-origin: 50% 100%` is the bottom
 * of the LINE BOX, which sits a descender plus half-leading BELOW the baseline,
 * so scaling about it lifts the baseline by `(scale - 1) * thatOffset` -- and
 * because the scale carries the voice, louder words lift further. That is the
 * word-level lift the design system does not have.
 *
 * There is no baseline keyword for `transform-origin`, and the offset depends on
 * the font's own ascent/descent and on the line-height, so it has to be read
 * from the rendered font. It is measured ONCE per caption face (the face is
 * locked before the first word arrives) and published as a CSS variable.
 *
 * This is a deterministic geometry read, not a fitted constant: the same face at
 * the same line-height always returns the same number, and Roboto Flex and Noto
 * Sans KR legitimately return different ones.
 */

/**
 * Distance from an element's box bottom up to its text baseline, in em.
 *
 * A zero-width `inline-block` participating in a line of text has its bottom
 * margin edge ON that line's baseline, which is what makes the baseline
 * reachable from JavaScript at all.
 *
 * Returns null when the element has not been laid out (zero font-size, detached
 * from the document, display:none), so callers can keep their fallback rather
 * than baking in a wrong origin.
 */
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
