import type {CaptionWord} from "./caption-store.ts";
// One classifier, in `hangul.ts` beside the syllable structure that needs
// it. Re-exported so existing importers of this module keep working.
import {isWideChar} from "./hangul.ts";

export {isWideChar};

export interface CaptionParagraph {
  id: string;
  speaker: string | null;
  status: string;
  utterance: number;
  words: Array<{
    id: string;
    word: CaptionWord;
  }>;
}

export interface CaptionStackPosition {
  id: string;
  top: number;
}

export interface CaptionStackMotion {
  id: string;
  kind: "enter" | "shift";
  deltaY: number;
}

function speakerStatus(word: CaptionWord): string {
  if (word.speaker_status) return word.speaker_status;
  return word.speaker ? "stable" : "unknown";
}

/**
 * Build semantic speaker turns, not layout-sized lines.
 *
 * A zero word limit is intentional: wrapping belongs to CSS and therefore
 * follows the actual viewport. A positive limit remains available as a safety
 * valve, but is not the studio default.
 *
 * EVERY recognized word is included, including words the playhead has not
 * reached yet. That is the point: CWI 2.2.1 wants the line on screen in white
 * BEFORE it is spoken, so withholding a word until its moment -- which the old
 * reveal state did -- is precisely what made read-ahead impossible. Words
 * ahead of the playhead are rendered as read-ahead type, not hidden.
 */
export function buildCaptionParagraphs(
  words: Record<string, CaptionWord>,
  order: string[],
  wordLimit = 0,
): CaptionParagraph[] {
  const paragraphs: CaptionParagraph[] = [];
  for (const id of order) {
    const word = words[id];
    if (!word) continue;

    const status = speakerStatus(word);
    const speaker = status === "unknown" ? null : (word.speaker ?? null);
    const utterance = Number(word.utterance ?? 0);
    const current = paragraphs.at(-1);
    const limitReached = wordLimit > 0 && (
      current?.words.length ?? 0
    ) >= wordLimit;
    if (
      !current ||
      current.speaker !== speaker ||
      current.utterance !== utterance ||
      limitReached
    ) {
      paragraphs.push({
        id: `${id}:u${utterance}:${speaker ?? "unknown"}`,
        speaker,
        status,
        utterance,
        words: [],
      });
    }
    paragraphs.at(-1)?.words.push({id, word});
  }
  return paragraphs;
}

/**
 * Keep the audience surface as a bounded caption stack.
 *
 * The transcript retains every paragraph. Stage keeps only the most recent
 * fixed-boundary blocks, but it never hides recognized words inside those
 * blocks. Filtering provisional words here made English captions disappear
 * until endpoint verification.
 */
/**
 * What the stage remembers between renders so laid-out rows cannot move.
 *
 * The caller owns this and passes the same object back in.
 */
export interface StageMemory {
  /** Words that start a row. Once set, a word keeps starting its row. */
  starts: Set<string>;
  /** Every word the stage has already placed. */
  placed: Set<string>;
  /** Acoustic time of the furthest word placed so far, in seconds. */
  newestPlaced: number;
  /**
   * Which row (by its anchor's word id) each placed word belongs to.
   *
   * MEMBERSHIP IS DECIDED ONCE, AND THAT IS WHAT MAKES A WIDTH BUDGET SAFE.
   * Anchored row STARTS already stop an edit from re-chunking the rows below
   * one. They do not stop a break from moving INSIDE a row, because the break
   * test is re-evaluated on every render: with a word COUNT that is harmless
   * (respelling does not change the count), but a WIDTH grows whenever a word
   * is respelled, so the row would overrun, open a new anchor mid-row, and push
   * its tail down -- re-keying every row below and remounting the words in
   * them. Deciding membership at first placement removes the re-evaluation
   * entirely: a lengthened word makes its own row wider, never shorter.
   *
   * RE-BREAKING WHILE A WORD IS STILL A HYPOTHESIS WAS BUILT, MEASURED AND
   * REVERTED (2026-08-06). The argument for it is good: a word placed as a stub
   * grows into its settled spelling, so a row that fit when frozen can overrun
   * later -- measured on `--sample`, one row per capture, worst 6.33em past the
   * line -- and a word that is not `final` is still read-ahead text nobody has
   * read, so the ahead-of-the-playhead invariant permits revising it. Gated on
   * `final`, splitting only ever moved the TAIL into a new row, so the row the
   * viewer was reading kept its id and its first word. Clipping went to ZERO.
   * It still cost the motion: the moved words remount, and the held word's
   * `holdAmount` lives in child state, so a remount re-runs the race CLAUDE.md
   * records as not fully closed. MEASURED over six runs, the film's one held
   * word ("is" in "as each word is spoken") came out right 3 times and wrong 3
   * -- 0.000em and 0.105em against its 0.525em -- where the same build without
   * re-breaking was right 3 of 3. A 50% flake on an acceptance number is worse
   * than a rare clipped row, so the reserve carries the growth instead.
   * Retrying this means first lifting the hold state out of `MotionWord` so a
   * remount cannot lose it -- which is motion work, not layout work.
   */
  rowOf: Map<string, string>;
}

/**
 * How wide a row may get, for a chunker that has no DOM.
 *
 * MEASURED on the bundled film through the live studio: `width_em =
 * 0.4343 * chars + 0.4289`, the intercept covering side bearings and the .30em
 * inter-word margin. Residuals run +1.21/-0.97em about a median of +0.005em,
 * which is why `fill` leaves slack rather than aiming at 1.0 --
 * `.caption-words` is `nowrap`, so an over-long row is CUT, silently.
 *
 * FIT IT ON A SETTLED STAGE, NOT ON A MINIMUM OVER LIVE SAMPLES. `.caption-word`
 * is an inline-grid whose cell is `max(normal, crest)`, so a word sampled
 * mid-crest reads wide, and the first fit here defended against that by taking
 * each word's NARROWEST observed width. A minimum over noisy samples is a
 * biased-LOW estimator: measured, it under-read by a mean of +0.062em per word,
 * which is +0.74em on a 12-word row -- a systematic overrun that grows with
 * exactly the short-word rows the width budget packs hardest. A replayed
 * capture settles every word behind the playhead, so the whole stage can be
 * read at rest at once with no minimum-taking at all.
 */
export interface StageWidthBudget {
  /** Usable row width in em -- `planStageLayout`'s `rowBudgetEm`. */
  rowEm: number;
  /** Per-character width for NARROW scripts. Fitted on Latin; see above. */
  charEm: number;
  wordEm: number;
  /** Fraction of `rowEm` a row may fill, absorbing the fit's residual. */
  fill: number;
  /**
   * Per-character width for East Asian WIDE scripts, measured off the live
   * face. Omit to fall back to `charEm`, which is the pre-2026-08-10 behaviour.
   *
   * WHY THIS EXISTS. `charEm` was fitted on the English PR film and then
   * applied to every script, so a Hangul syllable was budgeted at 0.4343em
   * against a real advance of **0.9200em** -- uniform, min = max, because
   * Hangul is a fixed-width script. The chunker therefore packed about twice
   * as many Korean words into a row as fit, and `.caption-words` is `nowrap`,
   * so the overrun was CUT with no error and no visual warning.
   *
   * The code still carried the fossil of the version that got this right:
   * `--per-word-em` was referenced in three comments, one of them naming
   * `[data-language="ko"]`, and defined nowhere. The 2026-08-06 width-budget
   * rewrite replaced a per-language budget with one English constant.
   *
   * MEASURE IT, DO NOT TABULATE IT. The font's own `hmtx` cannot supply this:
   * frequency-weighted over the PR film transcript Latin advances read
   * 0.4934em against the shipped 0.4343em, a 0.88 ratio absorbed by the
   * slope/intercept fit and the live variable-font axes, and there is no
   * reason that ratio transfers to a different face. `useGlyphBaseline` hit
   * exactly this and its lesson is recorded -- a hardcoded number is silently
   * wrong for Korean, and two probes agreeing across two faces is the bug
   * signal, not a confirmation.
   */
  wideCharEm?: number;
}

export function createStageMemory(): StageMemory {
  return {
    starts: new Set(),
    placed: new Set(),
    newestPlaced: Number.NEGATIVE_INFINITY,
    rowOf: new Map(),
  };
}

/**
 * Estimated settled footprint of one word, in em, gap included.
 *
 * `Array.from` rather than `split("")`: a Hangul syllable block or any
 * astral-plane character must stay ONE unit, which is also what makes the
 * per-character width meaningful.
 *
 * MOTION-NEUTRALITY IS A PROPERTY OF THIS FUNCTION, and there is a test on it.
 * With no wide characters present the arithmetic is `n * charEm + wordEm`,
 * bit-identical to the pre-2026-08-10 version whether or not `wideCharEm` is
 * supplied. That matters because a word that changes row is unmounted and
 * REBUILT, and row-break frequency is what flipped the held "is" between 4 of 6
 * and 6 of 6 runs at fill 0.87 against 0.82 -- while every motion acceptance
 * figure is measured on the ENGLISH film. Identical Latin widths mean identical
 * break decisions, so English motion cannot move.
 */
export function wordWidthEm(text: string, budget: StageWidthBudget): number {
  let narrow = 0;
  let wide = 0;
  for (const character of Array.from(text ?? "")) {
    if (isWideChar(character.codePointAt(0) ?? 0)) wide += 1;
    else narrow += 1;
  }
  // COUNT, THEN MULTIPLY -- do not accumulate per character. Float addition is
  // not associative, so summing `charEm` n times can differ in the last bits
  // from `n * charEm`, and that alone would be enough to move an English row
  // break. With no wide characters this reduces to `narrow * charEm + 0 +
  // wordEm`; adding an exact 0 is exact, so the result is the same float the
  // single-constant version returned.
  const wideEm = budget.wideCharEm ?? budget.charEm;
  return narrow * budget.charEm + wide * wideEm + budget.wordEm;
}

export function selectStableCaptionStack(
  paragraphs: CaptionParagraph[],
  stackLimit = 6,
  wordsPerCaption = 8,
  memory: StageMemory = createStageMemory(),
  // Omitted -> pure word-count chunking, exactly as before. Only the studio,
  // which knows the measured row width, opts into the width budget.
  budget: StageWidthBudget | null = null,
): CaptionParagraph[] {
  const stageWords = paragraphs.flatMap((paragraph) => paragraph.words);

  /*
   * Stage geometry deliberately ignores both speaker and utterance
   * partitions. Those are annotation/segmentation channels and can remain
   * pending or be revised after words are already visible. Letting either
   * channel create a row produced one-word stacks and remounted captions.
   *
   * Only immutable word order and the fixed row capacity define the audience
   * stack. The transcript still preserves semantic speaker/utterance
   * paragraphs.
   */
  /*
   * ROW STARTS ARE ANCHORED TO WORD IDS, NOT TO POSITION.
   *
   * Chunking purely by index made row membership a function of how many words
   * precede a word -- so the verifier deleting or inserting ONE word anywhere
   * earlier shifted every later word and re-flowed the whole stack. The user
   * reported exactly that: "the old sentences adjusting causes discrete word
   * location changes -> disturbs the readability." It is also why `rearmedWords`
   * measured 53 of 64: re-chunking re-keys every row after the change.
   *
   * Once a word has started a row it keeps starting that row. An earlier
   * deletion now just makes its own row shorter, and an insertion lengthens
   * only the row it lands in -- neither can pull words across a boundary that
   * the viewer has already read. A row that overruns capacity opens a NEW
   * anchor at that point, so the correction stays local to that row instead of
   * cascading down the stack.
   */
  /*
   * A LATE WORD MAY ONLY APPEND, NEVER INSERT.
   *
   * Anchored row starts stop an edit from re-chunking the rows BELOW it, but a
   * word inserted into a row still lengthens that row and pushes its own tail
   * out. Measured live, the verifier corrected "Something without" to "Give me
   * something without" and the row went
   *   [it, Look, just, Something, without]
   *   [it, Look, just, Give, Something] + [without ...]
   * -- text the viewer had already read, rearranged.
   *
   * So a word the stage has never placed, whose onset falls behind the furthest
   * word it HAS placed, is not shown. It stays in the model and in Transcript;
   * it simply does not get to reopen a line that has been read. Appends are
   * untouched, so a word arriving late after the endpoint stall still appears.
   */
  const placeable = stageWords.filter((entry) => {
    if (memory.placed.has(entry.id)) return true;
    const onset = Number(entry.word.t ?? entry.word.start);
    if (Number.isFinite(onset) && onset < memory.newestPlaced - 1e-6) {
      return false;
    }
    return true;
  });
  for (const entry of placeable) {
    memory.placed.add(entry.id);
    const onset = Number(entry.word.t ?? entry.word.start);
    if (Number.isFinite(onset)) {
      memory.newestPlaced = Math.max(memory.newestPlaced, onset);
    }
  }

  /*
   * A ROW BREAKS WHEN IT IS FULL, NOT WHEN IT HAS COUNTED TO N.
   *
   * Rows used to close at `wordsPerCaption` words, but a row's width is set by
   * its CHARACTERS -- so `planStageLayout` had to size the type for the WORST
   * case that count can produce, and an ordinary row of short words stopped
   * well short of the right edge. MEASURED at 1440x900, rows filled a median of
   * 64% of the line (p10 34%), with 7 of 20 under 60%: every full row carried
   * nine words and every empty one had closed for some other reason.
   *
   * With a budget, `wordsPerCaption` becomes a CEILING and the em budget --
   * the same number the type was already sized against -- decides the break.
   * The type size, `planStageLayout` and the rows-per-stage answer are all
   * untouched; only composition changes.
   *
   * Membership is frozen at first placement (`memory.rowOf`), so this cannot
   * re-flow text the viewer has read -- see that field's own note, including
   * why re-breaking a row while its words are still hypotheses was measured
   * and rejected.
   */
  const rows: CaptionParagraph[] = [];
  let rowEm = 0;
  const ceiling = budget ? budget.rowEm * budget.fill : 0;
  for (const entry of placeable) {
    const utterance = Number(entry.word.utterance ?? 0);
    let row = rows.at(-1);
    const anchor = memory.rowOf.get(entry.id);
    const cost = budget ? wordWidthEm(entry.word.text ?? "", budget) : 0;
    // A word whose spelling can still change can still be re-broken; a settled
    // one keeps the row it was read in.
    const settled = entry.word.final === true;
    let opens: boolean;
    if (!row) {
      opens = true;
    } else if (anchor !== undefined && settled) {
      // Settled: it starts a row only if it is that row's anchor.
      opens = anchor === entry.id;
    } else {
      /* While the spelling can still change, CAPACITY ALONE decides and the
         `starts` ratchet is ignored. Holding a word to a break made earlier is
         what leaves 2-word sliver rows: every break is correct when made, but
         the recognizer then inserts words ahead of an existing anchor, and the
         leftover between two anchors born against different text can never be
         merged away. Re-testing an unread word retires the stale one. */
      opens = (settled && memory.starts.has(entry.id)) ||
        (wordsPerCaption > 0 && row.words.length >= wordsPerCaption) ||
        (budget !== null && row.words.length > 0 && rowEm + cost > ceiling);
    }
    // `|| !row` is redundant at runtime (`opens` is already true when there is
    // no row) and load-bearing for the compiler: it is what narrows `row` to
    // defined after this block.
    if (opens || !row) {
      row = {
        id: `stage:${entry.id}`,
        speaker: null,
        status: "unknown",
        utterance,
        words: [],
      };
      rows.push(row);
      rowEm = 0;
      memory.starts.add(entry.id);
    }
    row.words.push(entry);
    rowEm += cost;
    memory.rowOf.set(entry.id, row.words[0].id);
  }

  for (const row of rows) {
    const attributed = row.words
      .map(({word}) => ({
        speaker: word.speaker ?? null,
        status: speakerStatus(word),
      }))
      .filter(({speaker, status}) => speaker && status !== "unknown");
    const speakers = new Set(attributed.map(({speaker}) => speaker));
    if (speakers.size === 1) {
      row.speaker = attributed[0].speaker;
      row.status = attributed.some(({status}) => status === "corrected")
        ? "corrected"
        : attributed.some(({status}) => status === "stable")
          ? "stable"
          : "provisional";
    } else if (speakers.size > 1) {
      row.status = "mixed";
    }
  }

  return stackLimit > 0 ? rows.slice(-stackLimit) : rows;
}

/**
 * Plan row-level FLIP motion only when stack membership/order changes.
 *
 * Text, color, and speaker revisions leave the same row IDs in the same order
 * and therefore return no motion. This keeps late attribution from moving
 * captions while letting a newly created row enter, and letting the rows it
 * displaces glide once the history cap starts evicting from the top.
 */
export function planCaptionStackMotion(
  previous: CaptionStackPosition[],
  current: CaptionStackPosition[],
  seen: ReadonlySet<string> = new Set(),
): CaptionStackMotion[] {
  if (current.length === 0) return [];
  if (previous.length === 0) {
    const first = current.length === 1 ? current[0] : null;
    return first && !seen.has(first.id)
      ? [{id: first.id, kind: "enter", deltaY: 0}]
      : [];
  }
  if (
    previous.length === current.length &&
    previous.every(({id}, index) => id === current[index]?.id)
  ) {
    /* SAME PARAGRAPHS, DIFFERENT PLACES. This used to return nothing, and it
       is why the stack jumped: a paragraph GROWS as words are appended to it,
       and in the rolling layout that pushes every paragraph above it upward
       with no membership change at all to notice. The id list is identical, so
       every guard below passes it over.
       A pure shift is safe to plan here -- nothing entered, nothing left, so
       there is no entry transition to confuse it with, and a row whose top did
       not actually move produces no motion. */
    return current.flatMap(({id, top}) => {
      const previousTop = previous.find((row) => row.id === id)?.top;
      if (previousTop === undefined) return [];
      const deltaY = previousTop - top;
      return Math.abs(deltaY) >= 0.5
        ? [{id, kind: "shift" as const, deltaY}]
        : [];
    });
  }

  const previousIds = new Set(previous.map(({id}) => id));
  const currentIds = new Set(current.map(({id}) => id));
  const entering = current.filter(({id}) => !previousIds.has(id));
  if (
    entering.length !== 1 ||
    entering[0].id !== current.at(-1)?.id ||
    seen.has(entering[0].id) ||
    current.length < previous.length
  ) {
    return [];
  }
  const retainedBefore = previous
    .filter(({id}) => currentIds.has(id))
    .map(({id}) => id);
  const retainedAfter = current
    .filter(({id}) => previousIds.has(id))
    .map(({id}) => id);
  if (
    retainedBefore.length !== retainedAfter.length ||
    retainedBefore.some((id, index) => id !== retainedAfter[index])
  ) {
    return [];
  }

  const previousTops = new Map(previous.map(({id, top}) => [id, top]));
  const motions: CaptionStackMotion[] = [];
  for (const {id, top} of current) {
    const previousTop = previousTops.get(id);
    if (previousTop === undefined) {
      motions.push({id, kind: "enter", deltaY: 0});
      continue;
    }
    const deltaY = previousTop - top;
    /* EITHER DIRECTION. The stack only ever glided upward, so this took
       `deltaY >= 0.5`; the rolling layout is bottom-anchored and a growing
       paragraph pushes its neighbours the other way. A one-sided test left
       exactly those moves un-animated, which is the jump this fixes. */
    if (Math.abs(deltaY) >= 0.5) {
      motions.push({id, kind: "shift", deltaY});
    }
  }
  // A new bottom row may legitimately move nothing: the stack is top-anchored,
  // so retained rows only glide once the history cap starts evicting from the
  // top. Requiring an accompanying shift here silently dropped the entry
  // transition for every block before that cap was reached. Replay, removal,
  // and same-membership revisions are already rejected by the guards above.
  return motions;
}
