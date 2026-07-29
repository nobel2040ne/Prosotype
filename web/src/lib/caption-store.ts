export type SpeakerStatus =
  | "unknown"
  | "provisional"
  | "stable"
  | "corrected";

export type RenderStage =
  | "hypothesis"
  | "cue"
  | "commit"
  | "word"
  | "verification";

export interface CaptionWord {
  type?: string;
  word_id?: string;
  text: string;
  t?: number;
  start: number;
  end: number;
  utterance?: number;
  speaker?: string | null;
  speaker_status?: SpeakerStatus;
  speaker_confidence?: number;
  speaker_revision_id?: number;
  text_revision_id?: number;
  timing_revision_id?: number;
  loudness?: number;
  loudness_db?: number;
  pitch?: number;
  pitch_hz?: number;
  voiced_frac?: number;
  spectral_centroid_hz?: number;
  pitch_confidence?: number;
  delivery_force?: number;
  delivery_attack?: number;
  delivery_contour?: number;
  delivery_contour_confidence?: number;
  delivery_flow?: number;
  delivery_texture?: number;
  delivery_confidence?: number;
  delivery_profile?: string;
  conf?: number;
  final?: boolean;
  verified?: boolean;
  provisional?: boolean;
  correction?: boolean;
  src?: string;
  sustain_active?: boolean;
  sustain_s?: number;
  _render_stage?: RenderStage;
  _sse_id?: number;
  _replay?: boolean;
}

export interface LevelEvent {
  type: "level";
  t?: number;
  rms_db: number;
  floor_db?: number;
  gain_db?: number;
  status?: "idle" | "good" | "too-quiet" | "clipping" | string;
  speech?: boolean;
  pitch_hz?: number;
  pitch_confidence?: number;
  spectral_centroid_hz?: number;
  direction_deg?: number;
  azimuth_deg?: number;
  delivery_force?: number;
  delivery_attack?: number;
  delivery_contour?: number;
  delivery_flow?: number;
  delivery_texture?: number;
  delivery_confidence?: number;
  delivery_profile?: string;
}

export interface SoundEvent {
  type: "sound";
  label?: string;
  category?: string;
  state?: "start" | "end";
  t?: number;
}

export interface CaptionEvent {
  type: string;
  words?: CaptionWord[];
  stage?: string;
  utterance?: number;
  resync?: boolean;
  [key: string]: unknown;
}

export interface CaptionModel {
  words: Record<string, CaptionWord>;
  order: string[];
  bootStage: string;
  sound: SoundEvent | null;
}

export const initialCaptionModel: CaptionModel = {
  words: {},
  order: [],
  bootStage: "connecting",
  sound: null,
};

const STAGE_RANK: Record<string, number> = {
  hypothesis: 0,
  cue: 1,
  commit: 2,
  word: 3,
  verification: 4,
};

const SPEAKER_RANK: Record<SpeakerStatus, number> = {
  unknown: 0,
  provisional: 1,
  stable: 2,
  corrected: 3,
};

export function wordKey(word: CaptionWord): string {
  if (word.word_id) return String(word.word_id);
  return [
    "u",
    Number(word.utterance ?? 0),
    Math.round(Number(word.start ?? word.t ?? 0) * 50),
  ].join(":");
}

export type RevealIntent = "animate" | "settle";

/**
 * Motion eligibility belongs to first discovery, not to a later word update.
 *
 * An unseen live word keeps its entrance through verification or an
 * EventSource reconnect while it is queued. A word first reconstructed from
 * history remains settled even if a later live record clears `_replay`.
 */
export function revealIntentForFirstSeen(
  word: CaptionWord,
  reducedMotion: boolean,
): RevealIntent {
  return word._replay || reducedMotion ? "settle" : "animate";
}

export function pendingRevealCanAnimate(
  intent: RevealIntent,
  reducedMotion: boolean,
  motionAlreadyStarted: boolean,
): boolean {
  return (
    intent === "animate" &&
    !reducedMotion &&
    !motionAlreadyStarted
  );
}

function numeric(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function stageRank(word: CaptionWord): number {
  return STAGE_RANK[word._render_stage ?? word.type ?? "hypothesis"] ?? 0;
}

function speakerStatus(word: CaptionWord): SpeakerStatus {
  if (word.speaker_status) return word.speaker_status;
  return word.speaker ? "stable" : "unknown";
}

function sourceRank(word: CaptionWord): number {
  if (word.verified || word._render_stage === "verification") return 3;
  if (word.src === "accurate") return 2;
  if (word.src === "draft") return 0;
  return 1;
}

function newestRevision(
  incoming: CaptionWord,
  current: CaptionWord,
  field: "text_revision_id" | "timing_revision_id" | "speaker_revision_id",
): boolean {
  const left = numeric(incoming[field], stageRank(incoming));
  const right = numeric(current[field], stageRank(current));
  if (sourceRank(incoming) !== sourceRank(current) && field !== "speaker_revision_id") {
    return sourceRank(incoming) > sourceRank(current);
  }
  return left > right || (
    left === right &&
    numeric(incoming._sse_id) >= numeric(current._sse_id)
  );
}

export function mergeCaptionWord(
  current: CaptionWord | undefined,
  incoming: CaptionWord,
): CaptionWord {
  if (!current) return {...incoming};

  const merged = {...current};
  const incomingFinal = Boolean(incoming.final || incoming.verified);
  const currentFinal = Boolean(current.final || current.verified);

  if ((!currentFinal || incomingFinal) &&
      newestRevision(incoming, current, "text_revision_id")) {
    merged.text = incoming.text;
  }

  if ((!currentFinal || incomingFinal) &&
      newestRevision(incoming, current, "timing_revision_id")) {
    merged.t = incoming.t;
    merged.start = incoming.start;
    merged.end = incoming.end;
    merged.utterance = incoming.utterance;
  }

  const incomingSpeakerStatus = speakerStatus(incoming);
  const currentSpeakerStatus = speakerStatus(current);
  if (
    SPEAKER_RANK[incomingSpeakerStatus] > SPEAKER_RANK[currentSpeakerStatus] ||
    (
      SPEAKER_RANK[incomingSpeakerStatus] === SPEAKER_RANK[currentSpeakerStatus] &&
      newestRevision(incoming, current, "speaker_revision_id")
    )
  ) {
    merged.speaker = incoming.speaker;
    merged.speaker_status = incomingSpeakerStatus;
    merged.speaker_confidence = incoming.speaker_confidence;
    merged.speaker_revision_id = incoming.speaker_revision_id;
  }

  if (
    sourceRank(incoming) > sourceRank(current) ||
    (
      sourceRank(incoming) === sourceRank(current) &&
      numeric(incoming._sse_id) >= numeric(current._sse_id)
    )
  ) {
    Object.assign(merged, incoming, {
      text: merged.text,
      start: merged.start,
      end: merged.end,
      t: merged.t,
      speaker: merged.speaker,
      speaker_status: merged.speaker_status,
      speaker_confidence: merged.speaker_confidence,
      speaker_revision_id: merged.speaker_revision_id,
    });
  }

  merged.final = currentFinal || incomingFinal;
  merged.verified = Boolean(current.verified || incoming.verified);
  merged.provisional = merged.verified
    ? false
    : Boolean(current.provisional || incoming.provisional);
  merged._sse_id = Math.max(
    numeric(current._sse_id),
    numeric(incoming._sse_id),
  );
  if (merged.verified) merged._render_stage = "verification";
  else if (merged.final) merged._render_stage = "word";
  return merged;
}

function sortOrder(words: Record<string, CaptionWord>): string[] {
  return Object.keys(words).sort((left, right) => {
    const a = words[left];
    const b = words[right];
    return (
      numeric(a.t, numeric(a.start)) - numeric(b.t, numeric(b.start)) ||
      numeric(a.utterance) - numeric(b.utterance) ||
      left.localeCompare(right)
    );
  });
}

function eventWords(event: CaptionEvent, sseId: number): CaptionWord[] {
  const stage = event.type as RenderStage;
  const replay = Boolean(event._replay) &&
    !Boolean(event._first_presentation);
  if (Array.isArray(event.words)) {
    return event.words.map((word) => ({
      ...word,
      _render_stage: stage,
      _sse_id: sseId,
      _replay: replay,
    }));
  }
  if (["cue", "commit", "word"].includes(event.type) && event.text) {
    return [{
      ...(event as unknown as CaptionWord),
      _render_stage: stage,
      _sse_id: sseId,
      _replay: replay,
    }];
  }
  return [];
}

export function reduceCaptionEvent(
  state: CaptionModel,
  event: CaptionEvent,
  sseId = 0,
): CaptionModel {
  if (event.type === "boot") {
    return {...state, bootStage: String(event.stage ?? "starting")};
  }
  if (event.type === "sound") {
    const sound = event as unknown as SoundEvent;
    return {...state, sound: sound.state === "end" ? null : sound};
  }

  const updates = eventWords(event, sseId);
  if (!updates.length) return state;
  const words = {...state.words};

  if (event.type === "hypothesis") {
    const incomingIds = new Set(updates.map(wordKey));
    const utterances = new Set(updates.map((word) => numeric(word.utterance)));
    const sources = new Set(updates.map((word) => word.src ?? "accurate"));
    for (const [key, word] of Object.entries(words)) {
      if (
        !word.final &&
        stageRank(word) < STAGE_RANK.commit &&
        utterances.has(numeric(word.utterance)) &&
        sources.has(word.src ?? "accurate") &&
        !incomingIds.has(key)
      ) {
        delete words[key];
      }
    }
  }

  for (const update of updates) {
    const key = wordKey(update);
    words[key] = mergeCaptionWord(words[key], update);
  }

  const boundedOrder = sortOrder(words).slice(-180);
  const boundedWords = Object.fromEntries(
    boundedOrder.map((key) => [key, words[key]]),
  );
  return {
    ...state,
    words: boundedWords,
    order: boundedOrder,
  };
}

export function nextRevealDeadline(
  currentDeadline: number,
  now: number,
  gap: number,
  catchupGap: number,
): number {
  const base = currentDeadline > 0 ? currentDeadline : now;
  return Math.max(base + Math.max(0, gap), now + Math.max(0, catchupGap));
}
