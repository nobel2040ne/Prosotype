import type {CaptionWord} from "./caption-store.ts";

export type CaptionRevealState = "hidden" | "active" | "settled";

export interface CaptionParagraph {
  id: string;
  speaker: string | null;
  status: string;
  utterance: number;
  words: Array<{
    id: string;
    word: CaptionWord;
    reveal: CaptionRevealState;
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
 */
export function buildCaptionParagraphs(
  words: Record<string, CaptionWord>,
  order: string[],
  reveal: Record<string, CaptionRevealState>,
  wordLimit = 0,
): CaptionParagraph[] {
  const paragraphs: CaptionParagraph[] = [];
  for (const id of order) {
    const state = reveal[id] ?? "hidden";
    const word = words[id];
    if (state === "hidden" || !word) continue;

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
    paragraphs.at(-1)?.words.push({id, word, reveal: state});
  }
  return paragraphs;
}

/**
 * Keep the audience surface as a bounded caption stack.
 *
 * The transcript retains every paragraph. Stage keeps only the most recent
 * fixed-boundary blocks, but it never hides recognized words inside those
 * blocks. Concurrency belongs to the reveal scheduler; filtering provisional
 * words here made English captions disappear until endpoint verification.
 */
export function selectStableCaptionStack(
  paragraphs: CaptionParagraph[],
  stackLimit = 6,
  wordsPerCaption = 8,
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
  const rows: CaptionParagraph[] = [];
  for (const entry of stageWords) {
    const utterance = Number(entry.word.utterance ?? 0);
    let row = rows.at(-1);
    if (
      !row ||
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
