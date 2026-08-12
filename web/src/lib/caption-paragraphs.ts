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

/** Build semantic speaker turns, not layout-sized lines. */
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

/** Keep the audience surface as a bounded caption stack. The transcript
   retains every paragraph. */
/** What the stage remembers between renders so laid-out rows cannot move. */
export interface StageMemory {
  /** Words that start a row. Once set, a word keeps starting its row. */
  starts: Set<string>;
  /** Every word the stage has already placed. */
  placed: Set<string>;
  /** Acoustic time of the furthest word placed so far, in seconds. */
  newestPlaced: number;
  /** Which row (by its anchor's word id) each placed word belongs to.
     MEMBERSHIP IS DECIDED ONCE, AND THAT IS WHAT MAKES A WIDTH BUDGET SAFE. */
  rowOf: Map<string, string>;
}

/** How wide a row may get, for a chunker that has no DOM. */
export interface StageWidthBudget {
  /** Usable row width in em -- `planStageLayout`'s `rowBudgetEm`. */
  rowEm: number;
  /** Per-character width for NARROW scripts. Fitted on Latin; see above. */
  charEm: number;
  wordEm: number;
  /** Fraction of `rowEm` a row may fill, absorbing the fit's residual. */
  fill: number;
  /** Per-character width for East Asian WIDE scripts, measured off the live
     face. */
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

/** Estimated settled footprint of one word, in em, gap included. */
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

  /* Stage geometry deliberately ignores both speaker and utterance
     partitions. */
  /* ROW STARTS ARE ANCHORED TO WORD IDS, NOT TO POSITION. */
  /* A LATE WORD MAY ONLY APPEND, NEVER INSERT. */
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

  /* A ROW BREAKS WHEN IT IS FULL, NOT WHEN IT HAS COUNTED TO N. */
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
         `starts` ratchet is ignored. */
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

/** Plan row-level FLIP motion only when stack membership/order changes. */
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
    /* SAME PARAGRAPHS, DIFFERENT PLACES. */
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
    /* EITHER DIRECTION. */
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
