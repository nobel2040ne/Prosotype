/** Type size and words-per-row are ONE decision, so make it one calculation. */

/** Worst-case width of a row of `words` words, in em. NOT `words *
   perWordEm`. */
export function rowBudgetEm(
  words: number,
  linear: number,
  spread: number,
): number {
  return words * linear + spread * Math.sqrt(words);
}

export interface StageLayoutInput {
  /** Border-box width of `.caption-feed` -- the clip box, gutters included. */
  feedWidthPx: number;
  /** Border-box height of `.caption-stage`. */
  stageHeightPx: number;
  /** `(padding-left + padding-right) / font-size` on the feed. */
  gutterEm: number;
  /** `(padding-top + padding-bottom) / font-size` on the feed. */
  verticalGutterEm: number;
  /** Linear term of the row-width budget: see `rowBudgetEm`. */
  wordEmLinear: number;
  /** Spread term of the row-width budget: see `rowBudgetEm`. */
  wordEmSpread: number;
  /** A rendered row's height in em (the dark stage adds padding light does not). */
  rowHeightEm: number;
  /** The feed's `max-height`, as a fraction of the stage. */
  maxHeightFraction: number;
  /** The already-resolved height term of the font-size, in px. */
  heightCapPx: number;
  minWords: number;
  maxWords: number;
  /** Rows the stack must be able to show before a larger type is preferred. */
  minRows: number;
}

export interface StageLayout {
  wordsPerRow: number;
  /** What the CSS `min(height term, width cap)` will resolve to. */
  typePx: number;
  /** Rows that fit -- the stack retention limit. */
  rows: number;
}

const finite = (value: number, fallback: number) =>
  Number.isFinite(value) && value > 0 ? value : fallback;

function evaluate(
  wordsPerRow: number,
  input: StageLayoutInput,
): StageLayout {
  // This mirrors the CSS `min(<height term>, 93.6cqw / (rowBudget + gutter))` --
  // the component hands the budget to CSS as `--row-budget-em`, so there is one
  // number and the type size and the row width cannot disagree.
  const widthCapPx = input.feedWidthPx /
    (rowBudgetEm(wordsPerRow, input.wordEmLinear, input.wordEmSpread) +
      input.gutterEm);
  const typePx = Math.min(input.heightCapPx, widthCapPx);
  const available = input.stageHeightPx * input.maxHeightFraction -
    input.verticalGutterEm * typePx;
  const rows = Math.max(
    1,
    Math.floor(available / (input.rowHeightEm * typePx)),
  );
  return {wordsPerRow, typePx, rows};
}

export function planStageLayout(input: StageLayoutInput): StageLayout {
  const minWords = Math.max(1, Math.round(input.minWords));
  const maxWords = Math.max(minWords, Math.round(input.maxWords));
  const safe: StageLayoutInput = {
    ...input,
    minWords,
    maxWords,
    feedWidthPx: finite(input.feedWidthPx, 1),
    stageHeightPx: finite(input.stageHeightPx, 1),
    wordEmLinear: finite(input.wordEmLinear, 1.45),
    wordEmSpread: finite(input.wordEmSpread, 6.60),
    rowHeightEm: finite(input.rowHeightEm, 1.38),
    heightCapPx: finite(input.heightCapPx, 64),
    gutterEm: Number.isFinite(input.gutterEm) ? input.gutterEm : 0,
    verticalGutterEm: Number.isFinite(input.verticalGutterEm)
      ? input.verticalGutterEm
      : 0,
    maxHeightFraction: finite(input.maxHeightFraction, 0.92),
  };

  const candidates: StageLayout[] = [];
  for (let words = minWords; words <= maxWords; words += 1) {
    candidates.push(evaluate(words, safe));
  }

  const viable = candidates.filter(
    (candidate) => candidate.rows >= safe.minRows,
  );
  // A stage too short to show `minRows` at any row width is not a reason to blow
  // the type up -- pack the most words in, which is the most rows, and let the
  // stack be short.
  if (!viable.length) return candidates[candidates.length - 1];

  // Largest type wins; on a TIE the wider row wins, because when the HEIGHT term
  // is what bound the size, extra words per row cost nothing and use more of the
  // stage's width. `typePx` is non-increasing in `wordsPerRow` and the candidates
  // are in ascending order, so accepting anything within tolerance of the best
  // keeps the LAST tied entry, i.e. the widest row at the largest type.
  return viable.reduce((best, candidate) => (
    candidate.typePx >= best.typePx - 0.01 ? candidate : best
  ));
}
