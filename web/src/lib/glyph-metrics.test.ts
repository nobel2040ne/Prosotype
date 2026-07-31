import assert from "node:assert/strict";
import test from "node:test";
import {baselineOffsetEm, formatBaselineEm} from "./glyph-metrics.ts";

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
