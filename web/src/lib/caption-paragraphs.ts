import type {CaptionWord} from "./caption-store.ts";

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
}

export function createStageMemory(): StageMemory {
  return {starts: new Set(), placed: new Set(), newestPlaced: Number.NEGATIVE_INFINITY};
}

export function selectStableCaptionStack(
  paragraphs: CaptionParagraph[],
  stackLimit = 6,
  wordsPerCaption = 8,
  memory: StageMemory = createStageMemory(),
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

  const rows: CaptionParagraph[] = [];
  for (const entry of placeable) {
    const utterance = Number(entry.word.utterance ?? 0);
    let row = rows.at(-1);
    const startsRow = memory.starts.has(entry.id);
    if (
      !row ||
      startsRow ||
      (wordsPerCaption > 0 && row.words.length >= wordsPerCaption)
    ) {
      row = {
        id: `stage:${entry.id}`,
        speaker: null,
        status: "unknown",
        utterance,
        words: [],
      };
      rows.push(row);
      memory.starts.add(entry.id);
    }
    row.words.push(entry);
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
    return [];
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
    if (deltaY >= 0.5) {
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
