import assert from "node:assert/strict";
import test from "node:test";
import {
  planStageLayout,
  rowBudgetEm,
  type StageLayoutInput,
} from "./stage-layout.ts";

/**
 * Every default here is MEASURED off the running studio, not chosen:
 * `.caption-feed` spans 93.6% of the stage's padding box, its horizontal clip
 * gutters total 3.50em and its vertical ones 1.06em, `max-height` is 92%, and a
 * light-stage row is 1.38em tall. The budget coefficients are fitted to the
 * measured worst-case rows. See `scratchpad` probes in CLAUDE.md.
 */
const base: StageLayoutInput = {
  feedWidthPx: 1001,
  stageHeightPx: 816,
  gutterEm: 3.50,
  verticalGutterEm: 1.06,
  wordEmLinear: 1.40,
  wordEmSpread: 4.30,
  rowHeightEm: 1.38,
  maxHeightFraction: 0.92,
  heightCapPx: 64,
  minWords: 3,
  maxWords: 6,
  minRows: 10,
};

// The two real viewports this was built from: a 1440x900 desktop, and the
// 862x998 window where six-words-per-row produced 23.6px captions on a stage
// that was 40% empty.
const desktop: StageLayoutInput = {...base};
const narrow: StageLayoutInput = {
  ...base,
  feedWidthPx: 502,
  stageHeightPx: 914,
};

test("a wide stage spends its width on words, not on shrinking the type", () => {
  const layout = planStageLayout(desktop);
  // Not a hardcoded six. The exact choice moves with the clip gutters, and those
  // now carry the motion's transient too -- the bulge is a real type-size change,
  // so a row is at its widest MID-MOTION. What must hold is that a wide stage
  // takes both a long row and a large type.
  assert.ok(layout.wordsPerRow >= 5, `${layout.wordsPerRow}`);
  assert.ok(
    layout.typePx > 43 && layout.typePx <= desktop.heightCapPx,
    `${layout.typePx}`,
  );
  assert.ok(layout.rows >= desktop.minRows, `${layout.rows}`);
});

test("a narrow stage buys type size back by shortening the row", () => {
  const layout = planStageLayout(narrow);
  assert.ok(layout.wordsPerRow < 6, `${layout.wordsPerRow}`);
  // The measured failure was 23.6px on this exact stage. Half again as large is
  // the point of the whole exercise; anything near 23.6 is the bug returning.
  assert.ok(layout.typePx > 31, `${layout.typePx}`);
  assert.ok(layout.rows >= narrow.minRows, `${layout.rows}`);
});

test("the chosen row always fits the width it was chosen for", () => {
  for (const input of [desktop, narrow]) {
    const layout = planStageLayout(input);
    const rowPx = rowBudgetEm(
      layout.wordsPerRow, input.wordEmLinear, input.wordEmSpread,
    ) * layout.typePx;
    const contentPx = input.feedWidthPx - input.gutterEm * layout.typePx;
    assert.ok(
      rowPx <= contentPx + 0.5,
      `row ${rowPx.toFixed(1)}px over content ${contentPx.toFixed(1)}px`,
    );
  }
});

test("row count never exceeds the available height", () => {
  for (const input of [desktop, narrow]) {
    const layout = planStageLayout(input);
    const available = input.stageHeightPx * input.maxHeightFraction -
      input.verticalGutterEm * layout.typePx;
    assert.ok(
      layout.rows * input.rowHeightEm * layout.typePx <= available + 0.5,
      `${layout.rows} rows overflow`,
    );
  }
});

test("a stage too short for minRows packs words instead of enlarging type", () => {
  const short = planStageLayout({...desktop, stageHeightPx: 420});
  assert.equal(short.wordsPerRow, desktop.maxWords);
});

test("Korean's wider syllable blocks shorten the row before the type shrinks", () => {
  const koreanInput = {...desktop, wordEmLinear: 1.86, wordEmSpread: 4.68};
  const korean = planStageLayout(koreanInput);
  const english = planStageLayout(desktop);
  assert.ok(
    korean.wordsPerRow <= english.wordsPerRow,
    `ko ${korean.wordsPerRow} vs en ${english.wordsPerRow}`,
  );
  const rowPx = rowBudgetEm(korean.wordsPerRow, 1.86, 4.68) * korean.typePx;
  assert.ok(rowPx <= desktop.feedWidthPx - desktop.gutterEm * korean.typePx + 0.5);
});

test("a short row costs MORE per word than a long one", () => {
  // The whole reason `rowBudgetEm` is not `N * constant`: measured, the worst
  // English row costs 2.93em/word at six words and 3.61em at three.
  const perWord = (n: number) => rowBudgetEm(n, 1.40, 4.30) / n;
  assert.ok(perWord(3) > perWord(6), `${perWord(3)} vs ${perWord(6)}`);
  assert.ok(perWord(3) > 3.4 && perWord(3) < 4.0, `${perWord(3)}`);
  assert.ok(perWord(6) > 2.9 && perWord(6) < 3.3, `${perWord(6)}`);
});

test("the budget covers the measured worst-case rows with slack", () => {
  // Sliding-window worst cases over the recognizer's real word order.
  for (const [words, measured] of [[3, 10.82], [4, 12.92], [5, 15.26], [6, 17.60]]) {
    const budget = rowBudgetEm(words, 1.40, 4.30);
    assert.ok(budget >= measured, `${words}: ${budget} < ${measured}`);
    assert.ok(budget <= measured * 1.15, `${words}: ${budget} wastes width`);
  }
});

test("when the height term binds, the widest row wins the tie", () => {
  // A very wide, short stage: every candidate is capped at the same type size,
  // so nothing is paid for using more of the width.
  const layout = planStageLayout({
    ...desktop,
    feedWidthPx: 4000,
    stageHeightPx: 1400,
    minRows: 6,
  });
  assert.equal(layout.typePx, desktop.heightCapPx);
  assert.equal(layout.wordsPerRow, desktop.maxWords);
});

test("degenerate input cannot produce a zero or negative layout", () => {
  const layout = planStageLayout({
    ...desktop,
    feedWidthPx: 0,
    stageHeightPx: Number.NaN,
    wordEmLinear: 0,
    wordEmSpread: Number.NaN,
    rowHeightEm: Number.NaN,
  });
  assert.ok(Number.isFinite(layout.typePx) && layout.typePx > 0);
  assert.ok(layout.rows >= 1);
  assert.ok(layout.wordsPerRow >= desktop.minWords);
});

test("words per row stays inside the configured bounds", () => {
  for (let width = 200; width <= 2600; width += 37) {
    const layout = planStageLayout({...base, feedWidthPx: width});
    assert.ok(
      layout.wordsPerRow >= base.minWords &&
      layout.wordsPerRow <= base.maxWords,
      `${width}px -> ${layout.wordsPerRow}`,
    );
  }
});
