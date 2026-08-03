import assert from "node:assert/strict";
import test from "node:test";
import {
  baselineOffsetEm,
  baselineRiseEm,
  crestGlyphPlacement,
  formatBaselineEm,
  glyphBoxHeightEm,
  uncorrectedGlyphPlacement,
  type CrestGeometry,
} from "./glyph-metrics.ts";

const rect = (bottom: number): DOMRect => ({bottom} as DOMRect);

test("the offset is the gap from the box bottom up to the baseline", () => {
  // A 40px line box whose baseline sits 14px above its bottom edge.
  assert.equal(baselineOffsetEm(rect(200), rect(186), 40), 0.35);
});

test("a baseline on the box bottom means no correction is needed", () => {
  assert.equal(baselineOffsetEm(rect(200), rect(200), 40), 0);
});

test("unlaid-out or nonsensical geometry returns null, not a wrong origin", () => {
  // Never measured: font-size 0 (display:none, detached probe).
  assert.equal(baselineOffsetEm(rect(200), rect(186), 0), null);
  // Baseline below the box bottom, or further above it than the box is tall:
  // both mean layout had not settled, and the caller's fallback is safer than
  // an origin that would put the pivot outside the glyph.
  assert.equal(baselineOffsetEm(rect(200), rect(214), 40), null);
  assert.equal(baselineOffsetEm(rect(200), rect(140), 40), null);
  assert.equal(baselineOffsetEm(rect(Number.NaN), rect(186), 40), null);
});

test("the published value is stable so re-measuring cannot churn CSS", () => {
  assert.equal(formatBaselineEm(0.3512345), "0.3512em");
  assert.equal(formatBaselineEm(0.35123449), formatBaselineEm(0.3512344));
});

const EN = 0.3799;   // Roboto Flex, measured by useGlyphBaseline
const KO = 0.2598;   // Noto Sans KR, measured
const geometry = (over: Partial<CrestGeometry> = {}): CrestGeometry => ({
  baselineEm: EN, lineHeightEm: 1.38, crestScale: 1, popScale: 1, ...over,
});
const CRESTS = [0.72, 0.78, 0.9, 1, 1.15, 1.3, 1.62];

test("a corrected word keeps its baseline on the row at every crest and pop", () => {
  for (const baselineEm of [EN, KO]) {
    for (const crestScale of CRESTS) {
      for (const popScale of [1, 1.15]) {
        const g = geometry({baselineEm, crestScale, popScale});
        const rise = baselineRiseEm(g, crestGlyphPlacement(g));
        assert.ok(
          Math.abs(rise) < 1e-12,
          `${baselineEm} x ${crestScale} x ${popScale} rose ${rise}`,
        );
      }
    }
  }
});

test("the uncorrected placement reproduces the rise measured on screen", () => {
  // "louder" ran at a 1.620x crest and measured +0.201em; the largest words
  // +0.236em. The model must land there, or it is describing something else.
  const loud = geometry({crestScale: 1.62});
  assert.ok(
    Math.abs(baselineRiseEm(loud, uncorrectedGlyphPlacement(loud)) - 0.2355) < 1e-3,
  );
  // ...and a word that SHRINKS does not move, which is why "softer" measured
  // clean and hid this for three attempts.
  const soft = geometry({crestScale: 0.78});
  assert.equal(baselineRiseEm(soft, uncorrectedGlyphPlacement(soft)), 0);
});

test("the rise hinges at 1, it is not a line through it", () => {
  for (const crestScale of CRESTS) {
    const g = geometry({crestScale});
    const rise = baselineRiseEm(g, uncorrectedGlyphPlacement(g));
    if (crestScale <= 1) {
      assert.equal(rise, 0, `${crestScale} should not move`);
    } else {
      // The shape the r=0.867 fit confirmed: slope is exactly `baselineEm`.
      assert.ok(Math.abs(rise / (crestScale - 1) - EN) < 1e-12);
    }
  }
});

test("the pop's drifting pivot is the second, smaller half of the defect", () => {
  const g = geometry({crestScale: 1.62, popScale: 1.15});
  const flat = geometry({crestScale: 1.62, popScale: 1});
  const extra =
    baselineRiseEm(g, uncorrectedGlyphPlacement(g)) -
    baselineRiseEm(flat, uncorrectedGlyphPlacement(flat));
  assert.ok(Math.abs(extra - 0.0353) < 1e-3, `${extra}`);
});

test("dropping either clamp breaks a word that shrinks", () => {
  // The un-clamped form, i.e. what you get by writing (S - 1) and S directly.
  const g = geometry({crestScale: 0.78});
  const unclamped = {
    originAboveBottomEm: g.baselineEm * g.crestScale,
    translateDownEm: g.baselineEm * (g.crestScale - 1),
  };
  const rise = baselineRiseEm(g, unclamped);
  assert.ok(rise > 0.08, `a quiet word would be shoved UP by ${rise}em`);
});

test("a settled word's geometry is untouched by the correction", () => {
  // Most words never crest. The fix has to be a no-op for them.
  assert.deepEqual(crestGlyphPlacement(geometry()), {
    originAboveBottomEm: EN,
    translateDownEm: 0,
  });
  assert.deepEqual(crestGlyphPlacement(geometry()), uncorrectedGlyphPlacement(geometry()));
});

test("the glyph box never shrinks the row, and only grows past the crest", () => {
  for (const baselineEm of [EN, KO]) {
    for (const crestScale of CRESTS) {
      const height = glyphBoxHeightEm(geometry({baselineEm, crestScale}));
      const expected = crestScale <= 1 ? 1.38 : 1.38 * crestScale;
      assert.ok(Math.abs(height - expected) < 1e-12, `${crestScale}: ${height}`);
    }
  }
});

test("Korean gets a proportionally smaller correction and still lands", () => {
  // Two bad probes have returned an IDENTICAL number for the two faces, and
  // that equality is the bug signal. Pin that they differ AND both land.
  const ko = geometry({baselineEm: KO, crestScale: 1.62});
  const en = geometry({baselineEm: EN, crestScale: 1.62});
  const koRise = baselineRiseEm(ko, uncorrectedGlyphPlacement(ko));
  const enRise = baselineRiseEm(en, uncorrectedGlyphPlacement(en));
  assert.ok(koRise < enRise, `${koRise} should be under ${enRise}`);
  assert.ok(Math.abs(koRise - 0.1611) < 1e-3, `${koRise}`);
  assert.ok(Math.abs(baselineRiseEm(ko, crestGlyphPlacement(ko))) < 1e-12);
});

test("the drop the bottom clip gutter has to cover", () => {
  // The glyph box now hangs this far below the row. `.caption-feed`'s bottom
  // padding is what has to cover it.
  assert.ok(
    Math.abs(crestGlyphPlacement(geometry({crestScale: 1.62})).translateDownEm
      - 0.2355) < 1e-3,
  );
  assert.equal(crestGlyphPlacement(geometry({crestScale: 0.78})).translateDownEm, 0);
});
