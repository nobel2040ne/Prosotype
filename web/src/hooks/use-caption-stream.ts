"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  initialCaptionModel,
  reduceCaptionEvent,
  wordKey,
  type CaptionEvent,
  type CaptionModel,
  type CaptionWord,
  type LevelEvent,
} from "@/lib/caption-store";
import {acousticTimeMs} from "@/lib/motion-timing";
import {
  advanceClock,
  IDLE_CLOCK,
  monotonicTimeForAcousticMs,
  presentationNowMs,
  readAheadMs,
  type PlayheadClock,
} from "@/lib/caption-clock";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "demo";

/**
 * Everything a word needs in order to animate itself, frozen at discovery.
 *
 * `turnAtMs` is the `performance.now()` moment the playhead reaches the word's
 * spoken onset; `durationMs` is its 2.2.3 window. Both are immutable for the
 * life of the word, so a verifier respelling, a speaker correction or a
 * reconnect replay can never restart, reshape or double-run its motion.
 */
export interface WordSchedule {
  turnAtMs: number;
  durationMs: number;
}
export type SessionState =
  | "checking"
  | "selecting"
  | "loading"
  | "listening"
  | "unavailable";

export interface LiveLanguageOption {
  id: "en" | "ko" | string;
  label: string;
  nativeLabel: string;
  description: string;
}

export interface LanguageSession {
  state: SessionState;
  language: string | null;
  languages: LiveLanguageOption[];
}

export interface RuntimeConfig {
  palette: string[];
  /** Speaker colors for the light stage: same hues, darkened to >=4.5:1. */
  paletteLight: string[];
  /** How many trailing entries of `palette` are CWI 2.1.2 supporting colours. */
  paletteSupportCount: number;
  displayMode: string;
  maxWords: number;
  paragraphWordLimit: number;
  stageParagraphHistory: number;
  stageWordsPerBlock: number;
  /** Floor on words per Stage row; below this a row stops reading as a phrase. */
  stageWordsMin: number;
  /** Rows the stack must fit before a shorter row (larger type) is preferred. */
  stageMinRows: number;
  /**
   * CWI 2.2.1. How far the caption playhead runs behind the acoustic clock.
   *
   * This is what buys the white read-ahead: the recognizer delivers a word
   * about 1.1 s after it is spoken, so a 2.5 s playhead leaves ~1.4 s of
   * recognized-but-not-yet-coloured text on screen at all times.
   */
  readAheadDelayMs: number;
  /** 2.2.1: "full white at 90% opacity" -- against 2.4.1's black box. */
  readAheadColor: string;
  /** The boxless light stage measures white at 1.05:1. See config.yaml. */
  readAheadColorLight: string;
  readAheadOpacity: number;
  /** Crossfade for the 2.2.2 turn. It eases with the lift, never a hard cut. */
  colorTurnMs: number;
  wordMotionBaseMs: number;
  wordMotionMaxMs: number;
  wordMotionSpanStretch: number;
  wordMotionMinMs: number;
  syncPop: number;
  deliveryMotionEnabled: boolean;
  /** A drawn-out word holds its 2.2.3 cue slightly longer. */
  deliveryFlowDurationMs: number;
  /** Settled wght band. CWI 2.3.9: low pitch heavy, high pitch light. */
  weightRange: [number, number];
  /** Settled wdth band. CWI 2.3.9/2.3.10: rich harmonics wider. */
  widthRange: [number, number];
  /** Transient voice-size band around the baseline. CWI 2.3.6. */
  voiceScaleRange: [number, number];
  /**
   * How much of CWI 2.3.6's size excursion is used at the motion crest, applied
   * about the 2.3.5 baseline so a normal speaking voice stays at exactly 1.
   * 1 is the design system's literal 3%..12%.
   */
  voiceScaleResponse: number;
  deliveryMinConfidence: number;
  languages: LiveLanguageOption[];
  selectedLanguage: string | null;
  languageSelectionRequired: boolean;
}

export const DEFAULT_RUNTIME_CONFIG: RuntimeConfig = {
  palette: ["#e6ff2e", "#56e39f", "#55d7ff", "#c387ff", "#ff667d", "#ffb84d"],
  paletteLight: ["#6d7816", "#31805a", "#307b91", "#895fb4", "#bd4c5d", "#936a2c"],
  paletteSupportCount: 0,
  displayMode: "fast",
  maxWords: 8,
  paragraphWordLimit: 0,
  stageParagraphHistory: 6,
  stageWordsPerBlock: 6,
  stageWordsMin: 3,
  stageMinRows: 10,
  readAheadDelayMs: 2500,
  readAheadColor: "#ffffff",
  readAheadColorLight: "#6e6e73",
  readAheadOpacity: 0.9,
  colorTurnMs: 90,
  wordMotionBaseMs: 520,
  wordMotionMaxMs: 720,
  wordMotionSpanStretch: 0.42,
  wordMotionMinMs: 320,
  syncPop: 0.15,
  deliveryMotionEnabled: true,
  deliveryFlowDurationMs: 90,
  weightRange: [200, 760],
  widthRange: [82, 124],
  voiceScaleRange: [0.90, 1.20],
  voiceScaleResponse: 0.25,
  deliveryMinConfidence: 0.38,
  languages: [
    {
      id: "en",
      label: "English",
      nativeLabel: "English",
      description: "English streaming recognition",
    },
    {
      id: "ko",
      label: "Korean",
      nativeLabel: "한국어",
      description: "한국어 실시간 음성 인식",
    },
  ],
  selectedLanguage: null,
  languageSelectionRequired: true,
};

const EMPTY_LEVEL: LevelEvent = {
  type: "level",
  rms_db: -72,
  floor_db: -72,
  gain_db: 0,
  status: "idle",
  speech: false,
  pitch_hz: 0,
  pitch_confidence: 0,
  spectral_centroid_hz: 0,
};

/**
 * How often the playhead is published to React.
 *
 * Nothing about a word's own motion depends on this: colour and pop are CSS
 * animations the browser schedules from a frozen `animation-delay`. The tick
 * exists only for things that track WHERE speech currently is — the trailing
 * voice orb's row, and the diagnostics probe — so it is deliberately coarse.
 */
const PLAYHEAD_TICK_MS = 66;

interface StreamOptions {
  reducedMotion: boolean;
}

/**
 * The newest word the browser currently HOLDS -- the far edge of the
 * read-ahead.
 *
 * It has to be read off the live model rather than accumulated as a
 * high-water mark. The reducer deletes non-final hypothesis words routinely,
 * so a running maximum keeps counting text that is no longer on screen and
 * reports read-ahead the viewer cannot actually read. Measured, that
 * overstated it by roughly 1.5 s. `order` is time-sorted, so this is the last
 * entry.
 */
function newestAcousticMs(model: CaptionModel): number {
  const newest = model.order.at(-1);
  return newest ? acousticTimeMs(model.words[newest]) : Number.NaN;
}

function demoEvents(): Array<{delay: number; event: CaptionEvent}> {
  const base = {
    utterance: 0,
    loudness: 0.58,
    loudness_db: -27,
    pitch_hz: 172,
    voiced_frac: 0.91,
    delivery_force: 0.58,
    delivery_attack: 0.36,
    delivery_contour: 0,
    delivery_flow: 0.64,
    delivery_texture: 0.25,
    delivery_confidence: 0.88,
    delivery_profile: "steady",
    conf: 0.94,
    final: true,
    speaker: "S1",
    speaker_status: "stable" as const,
    speaker_confidence: 0.92,
  };
  const phrases = [
    ["The", 0.00, 0.22, 0.42, 188],
    ["voice", 0.23, 0.60, 0.72, 154],
    ["isn't", 0.62, 0.91, 0.48, 176],
    ["just", 0.94, 1.18, 0.62, 168],
    ["heard.", 1.20, 1.66, 0.82, 148],
  ] as const;
  const second = [
    ["Now", 1.95, 2.20, 0.54, 224],
    ["you", 2.22, 2.43, 0.46, 236],
    ["can", 2.45, 2.68, 0.58, 228],
    ["see", 2.70, 3.08, 0.74, 244],
    ["it.", 3.10, 3.42, 0.50, 218],
  ] as const;
  const events: Array<{delay: number; event: CaptionEvent}> = [
    {delay: 0, event: {type: "boot", stage: "listening"}},
  ];
  [...phrases, ...second].forEach((item, index) => {
    const [text, start, end, loudness, pitch] = item;
    const secondSpeaker = index >= phrases.length;
    events.push({
      delay: 180 + index * 155,
      event: {
        ...base,
        type: "word",
        word_id: `u0:w${index}`,
        text,
        t: start,
        start,
        end,
        loudness,
        pitch_hz: pitch,
        delivery_force: loudness,
        delivery_attack: index % 4 === 0 ? 0.82 : 0.28,
        delivery_contour: [-0.58, 0.04, 0.62, -0.08, -0.42][index % 5],
        delivery_flow: index % 3 === 1 ? 0.86 : 0.52,
        delivery_texture: index % 4 === 2 ? 0.71 : 0.24,
        delivery_profile: [
          "falling", "sustained", "rising", "steady", "forceful",
        ][index % 5],
        speaker: secondSpeaker ? "S2" : "S1",
        speaker_status: "stable",
        speaker_revision_id: 1,
        text_revision_id: 1,
        timing_revision_id: 1,
      },
    });
  });
  return events;
}

export function useCaptionStream({reducedMotion}: StreamOptions) {
  const [model, setModel] = useState<CaptionModel>(initialCaptionModel);
  const [level, setLevel] = useState<LevelEvent>(EMPTY_LEVEL);
  const [waveform, setWaveform] = useState<number[]>(() => Array(32).fill(-72));
  const [connection, setConnection] =
    useState<ConnectionState>("connecting");
  const [runtime, setRuntime] =
    useState<RuntimeConfig>(DEFAULT_RUNTIME_CONFIG);
  const [session, setSession] = useState<LanguageSession>({
    state: "checking",
    language: null,
    languages: DEFAULT_RUNTIME_CONFIG.languages,
  });
  const [languageError, setLanguageError] = useState<string | null>(null);
  const [playheadMs, setPlayheadMs] = useState(Number.NEGATIVE_INFINITY);
  const [clockEpoch, setClockEpoch] = useState<number | null>(null);
  const [startedAt] = useState(() => Date.now());
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  const modelRef = useRef(model);
  const levelRef = useRef(level);
  const scheduledRef = useRef(new Map<string, WordSchedule>());
  // The clock lives in a ref, not in state: it is revised ~15 times a second by
  // level events and must not re-render the studio on every one of them. The
  // coarse playhead tick below is what React actually sees.
  const clockRef = useRef<PlayheadClock>(IDLE_CLOCK);
  const runtimeRef = useRef(runtime);
  const lateWordsRef = useRef(0);
  const frozenTextRef = useRef(0);
  // id -> the text the word was WEARING when the playhead reached it.
  const settledTextRef = useRef(new Map<string, string>());
  const rearmedWordsRef = useRef(0);
  const minReadAheadRef = useRef(Number.POSITIVE_INFINITY);
  const eventIdRef = useRef(0);

  useEffect(() => {
    modelRef.current = model;
  }, [model]);
  useEffect(() => {
    levelRef.current = level;
  }, [level]);
  useEffect(() => {
    runtimeRef.current = runtime;
  }, [runtime]);

  const backendOrigin =
    process.env.NEXT_PUBLIC_AUTOCWI_ORIGIN?.replace(/\/$/, "") ?? "";

  const dispatch = useCallback((event: CaptionEvent, eventId?: number) => {
    const id = eventId ?? ++eventIdRef.current;
    setLastEventAt(Date.now());
    if (event.type === "level") {
      const incoming = event as unknown as LevelEvent;
      // THE CLOCK SOURCE. `level.t` is the capture position in seconds on the
      // same timeline as `word.t` (`stream_base + word.start`), and it arrives
      // every ~64 ms whether or not anyone is speaking, which is exactly what a
      // playhead needs. Word events are NOT used here: they are retained and
      // replayed to each new audience connection, so an old timestamp would
      // look like a capture restart and yank the playhead backwards.
      const seconds = Number(incoming.t);
      if (Number.isFinite(seconds)) {
        clockRef.current = advanceClock(
          clockRef.current,
          seconds * 1000,
          performance.now(),
        );
      }
      setLevel(incoming);
      setWaveform((values) => [...values.slice(-31), Number(incoming.rms_db)]);
      return;
    }
    /*
     * THE CAPTION INVARIANT, ENFORCED RATHER THAN MERELY DOCUMENTED.
     *
     * "Text may be revised only AHEAD of the playhead; once the colour turn
     * passes a word it is frozen." That was true of hypothesis churn, which
     * happens in the white zone, but NOT of endpoint verification, which
     * arrives seconds later and rewrote words the viewer had already read.
     * Measured on the bundled clip: 44 text changes over 74 words, 38 of them
     * landing more than the read-ahead delay after the word's own onset --
     * "sixteen" became "1640" 4.5 s after it was spoken, in place, on screen.
     *
     * A word whose turn has passed therefore keeps the text it was drawn with.
     * Only the spelling is frozen: speaker colour, finality and timing still
     * update, because a late attribution correction is a direct colour write
     * and that is exactly what the design system asks for.
     *
     * The verifier is not being ignored -- it simply loses the race for words
     * the viewer has already read. Raising `display.read_ahead_delay_s` widens
     * the window in which it can still win.
     */
    const freezeText = <T extends {text?: string}>(word: T): T => {
      const key = wordKey(word as unknown as CaptionWord);
      // Recorded when the playhead passed the word -- NOT read from the live
      // model here. The reducer routinely deletes a non-final word and re-adds
      // it a moment later with the verifier's spelling, and comparing against
      // the model alone let exactly that path through: at the instant of
      // re-insertion there was nothing to compare to. Measured, 14 coloured
      // captions still rewrote themselves ("tab" -> "tab.", "right" ->
      // "Right,") until this was remembered independently.
      const settled = settledTextRef.current.get(key);
      if (settled === undefined || settled === word.text) return word;
      frozenTextRef.current += 1;
      return {...word, text: settled};
    };
    if (Array.isArray(event.words)) {
      event = {...event, words: event.words.map(freezeText)};
    } else if (typeof event.text === "string") {
      // `cue`/`commit`/`word` may carry a single word at the top level rather
      // than in a `words` array. Missing this path let endpoint punctuation
      // ("it" -> "it,", "okay" -> "okay?") still rewrite coloured captions.
      event = freezeText(event as CaptionEvent & {text: string});
    }
    setModel((current) => reduceCaptionEvent(
      current, event, id, new Set<string>(),
    ));
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${backendOrigin}/runtime-config.json`)
      .then((response) => response.ok ? response.json() : null)
      .then((value: Partial<RuntimeConfig> | null) => {
        if (!cancelled && value) {
          setRuntime({...DEFAULT_RUNTIME_CONFIG, ...value});
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [backendOrigin]);

  useEffect(() => {
    let cancelled = false;
    const isDemo = new URLSearchParams(window.location.search).has("demo");
    if (isDemo) {
      const timer = setTimeout(() => setSession({
          state: "listening",
          language: "en",
          languages: DEFAULT_RUNTIME_CONFIG.languages,
        }), 0);
      return () => clearTimeout(timer);
    }
    fetch(`${backendOrigin}/session`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Session service is unavailable.");
        return response.json() as Promise<LanguageSession>;
      })
      .then((value) => {
        if (!cancelled) setSession(value);
      })
      .catch(() => {
        if (!cancelled) {
          setSession((current) => ({...current, state: "unavailable"}));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [backendOrigin]);

  const selectLanguage = useCallback(async (language: string) => {
    setLanguageError(null);
    try {
      const response = await fetch(`${backendOrigin}/session/language`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({language}),
      });
      const value = await response.json() as LanguageSession & {error?: string};
      if (!response.ok) {
        throw new Error(value.error ?? "Could not select that language.");
      }
      setSession(value);
    } catch (error) {
      setLanguageError(
        error instanceof Error ? error.message : "Could not select that language.",
      );
    }
  }, [backendOrigin]);

  useEffect(() => {
    const isDemo = new URLSearchParams(window.location.search).has("demo");
    if (isDemo) {
      const connectionTimer = setTimeout(() => setConnection("demo"), 0);
      const timers: Array<ReturnType<typeof setTimeout>> = [];
      const demoStartedAt = performance.now();
      const levelTimer = setInterval(() => {
        const phase = performance.now() / 420;
        dispatch({
          type: "level",
          // The demo needs a real acoustic clock too, or the playhead never
          // starts and every word stays white. Its words span t=0..3.4 s, so a
          // wall clock from mount plays the read-ahead exactly as live does:
          // the whole block appears white first, then colours word by word.
          t: (performance.now() - demoStartedAt) / 1000,
          rms_db: -32 + Math.sin(phase) * 9,
          floor_db: -61,
          gain_db: 0,
          status: "good",
          speech: true,
          pitch_hz: 196 + Math.sin(phase * 0.72) * 44,
          pitch_confidence: 0.82,
          spectral_centroid_hz: 1900 + Math.cos(phase * 0.44) * 760,
          delivery_force: 0.52 + Math.sin(phase) * 0.24,
          delivery_attack: Math.max(0, Math.sin(phase * 1.8)) * 0.7,
          delivery_contour: Math.sin(phase * 0.72) * 0.72,
          delivery_flow: 0.68 + Math.cos(phase * 0.33) * 0.19,
          delivery_texture: 0.32 + Math.sin(phase * 0.44) * 0.18,
          delivery_confidence: 0.88,
          delivery_profile: Math.sin(phase * 0.72) > 0.25
            ? "rising"
            : Math.sin(phase * 0.72) < -0.25
              ? "falling"
              : "sustained",
        });
      }, 64);
      for (const item of demoEvents()) {
        timers.push(setTimeout(() => dispatch(item.event), item.delay));
      }
      return () => {
        clearTimeout(connectionTimer);
        clearInterval(levelTimer);
        timers.forEach(clearTimeout);
      };
    }

    const source = new EventSource(`${backendOrigin}/events`);
    source.onopen = () => setConnection("live");
    source.onerror = () => setConnection("reconnecting");
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as CaptionEvent;
        if (event.type === "boot") {
          setSession((current) => ({
            ...current,
            state: event.stage === "listening" ? "listening" : "loading",
            language: String(event.language ?? current.language ?? "") || null,
          }));
        }
        dispatch(event, Number(message.lastEventId || 0));
      } catch {
        // A malformed diagnostic event must not tear down a live session.
      }
    };
    return () => source.close();
  }, [backendOrigin, dispatch]);

  /*
   * SCHEDULING, IN FULL.
   *
   * A word is placed on the playhead once, by the word itself, in its own
   * layout effect (see `MotionWord`). There is no queue, no concurrency cap,
   * no reveal gap, no catch-up policy and no backlog ceiling, because none of
   * those questions exist any more: a word's colour turn happens when the
   * playhead reaches its recorded onset, and the browser owns that schedule as
   * a single `animation-delay`.
   *
   * The old scheduler had to answer "when should this word appear?" from
   * arrival order alone, which is why it grew slots, deadlines, an adaptive
   * clock, a staleness ceiling and a watchdog for reservations that never
   * painted. The playhead answers it from the recording itself.
   *
   * This callback is stable for the life of the hook, so passing it to every
   * word costs no re-renders, and it is called from a layout effect in the
   * SAME commit that first paints the word -- which is what makes the frozen
   * turn moment exact rather than one frame late.
   */
  const scheduleWord = useCallback((
    id: string,
    word: CaptionWord,
    durationMs: number,
  ): {turnAtMs: number; epoch: number} | null => {
    const clock = clockRef.current;
    const acousticMs = acousticTimeMs(word);
    // Before the first level event there is no acoustic clock and therefore no
    // honest moment to turn this word. Returning null leaves it in read-ahead
    // type; it is scheduled as soon as the clock starts.
    if (!clock.started || !Number.isFinite(acousticMs)) return null;
    const turnAtMs = monotonicTimeForAcousticMs(
      clock,
      acousticMs,
      runtimeRef.current.readAheadDelayMs,
    );
    const previous = scheduledRef.current.get(id);
    scheduledRef.current.set(id, {turnAtMs, durationMs});
    if (previous) {
      // The word was already scheduled, so this is a remount asking for its
      // delay again. That is a supported path -- the turn moment is derived
      // from the recording and the clock, never from "now", so the word
      // resumes at the same wall moment against its new animation origin --
      // but it is worth counting, because a large figure means the stack is
      // churning React keys and paying for it.
      rearmedWordsRef.current += 1;
      return {turnAtMs, epoch: clock.epoch};
    }
    /*
     * A word delivered after its own onset had already passed needs no special
     * case: the negative delay puts both CSS animations past their end, so it
     * paints settled and coloured, which is exactly right for history. Count
     * it once per word, though -- a steadily rising figure is the signal that
     * the read-ahead delay is shorter than the recognizer's real latency, i.e.
     * that no read-ahead is being delivered at all.
     */
    if (turnAtMs < performance.now()) lateWordsRef.current += 1;
    return {turnAtMs, epoch: clock.epoch};
  }, []);

  /*
   * Publish the playhead coarsely.
   *
   * No word's motion depends on this -- CSS runs those. It exists so the
   * trailing voice orb can sit on the row speech has actually reached, and so
   * the probe can report the read-ahead it is really delivering.
   */
  useEffect(() => {
    let frame = 0;
    let last = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const now = performance.now();
      if (now - last < PLAYHEAD_TICK_MS) return;
      last = now;
      const clock = clockRef.current;
      if (!clock.started) return;
      // Publishing the epoch is what starts words scheduling, and what tells
      // words from a previous capture to settle. Both are rare transitions, so
      // this bails out on the common path.
      setClockEpoch((current) => (
        current === clock.epoch ? current : clock.epoch
      ));
      const playhead = presentationNowMs(
        clock,
        now,
        runtimeRef.current.readAheadDelayMs,
      );
      // A word's text is fixed the moment the playhead reaches it. Doing this
      // on the tick rather than on the next revision means a word that is
      // deleted and re-added still comes back wearing what the viewer read.
      for (const [id, schedule] of scheduledRef.current) {
        if (now < schedule.turnAtMs) continue;
        if (settledTextRef.current.has(id)) continue;
        const word = modelRef.current.words[id];
        if (word?.text !== undefined) {
          settledTextRef.current.set(id, word.text);
        }
      }

      const newest = newestAcousticMs(modelRef.current);
      if (Number.isFinite(newest) && scheduledRef.current.size > 0) {
        minReadAheadRef.current = Math.min(
          minReadAheadRef.current,
          readAheadMs(
            clock,
            newest,
            now,
            runtimeRef.current.readAheadDelayMs,
          ),
        );
      }
      setPlayheadMs(playhead);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    window.__cwiStudio = {
      dispatch,
      report: () => {
        const now = performance.now();
        const clock = clockRef.current;
        const delayMs = runtimeRef.current.readAheadDelayMs;
        const playhead = presentationNowMs(clock, now, delayMs);
        const live = new Set(modelRef.current.order);
        for (const id of scheduledRef.current.keys()) {
          if (!live.has(id)) scheduledRef.current.delete(id);
        }
        const scheduled = [...scheduledRef.current.values()];
        return {
          connection,
          words: modelRef.current.order.length,
          // Every recognized word is on screen now: read-ahead words are the
          // white ones. Nothing is withheld, so this must equal `words`.
          visible: modelRef.current.order.filter(
            (id) => Boolean(modelRef.current.words[id]),
          ).length,
          clockStarted: clock.started,
          readAheadDelayMs: delayMs,
          /*
           * THE NUMBER THAT MATTERS. Recognized text sitting on screen ahead of
           * the colour, in ms. It should settle near
           * `readAheadDelayMs - recognizerLatency` (~1.4 s at the shipped 2.5 s
           * against the 1120 ms accurate stream). Zero means the caption is
           * being coloured the instant it arrives -- i.e. CWI 2.2.1 is not
           * actually being delivered, whatever the page looks like.
           */
          readAheadMs: readAheadMs(
            clock,
            newestAcousticMs(modelRef.current),
            now,
            delayMs,
          ),
          minReadAheadMs: Number.isFinite(minReadAheadRef.current)
            ? minReadAheadRef.current
            : 0,
          aheadWords: scheduled.filter((item) => item.turnAtMs > now).length,
          activeMotions: scheduled.filter(
            (item) => item.turnAtMs <= now &&
              now - item.turnAtMs < item.durationMs,
          ).length,
          scheduledWords: scheduled.length,
          /*
           * Words that arrived after their own onset had already passed and so
           * could never animate. A steadily rising count means the read-ahead
           * delay is shorter than the recognizer's real latency.
           */
          lateWords: lateWordsRef.current,
          // Revisions REJECTED because the playhead had already passed the
          // word. A healthy figure; zero would mean the invariant is unused.
          frozenTextRevisions: frozenTextRef.current,
          rearmedWords: rearmedWordsRef.current,
          playheadMs: Number.isFinite(playhead) ? playhead : null,
          newestAcousticMs: Number.isFinite(newestAcousticMs(
            modelRef.current,
          ))
            ? newestAcousticMs(modelRef.current)
            : null,
          clockEpoch: clock.epoch,
          reducedMotion,
          directionKnown: Number.isFinite(
            Number(levelRef.current.direction_deg ??
              levelRef.current.azimuth_deg),
          ),
        };
      },
    };
    return () => {
      delete window.__cwiStudio;
    };
  }, [connection, dispatch, reducedMotion]);

  // `?probe=1` publishes report() into document.title so headless Chrome can
  // read it with --dump-dom, matching how `scripts/live_render_probe.py` reads
  // the legacy renderer. Without this the studio's metrics are only reachable
  // from a devtools console, so motion could not be verified numerically --
  // --dump-dom alone returns the pre-hydration static shell.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (new URLSearchParams(window.location.search).get("probe") !== "1") return;
    const publish = () => {
      const report = window.__cwiStudio?.report();
      if (report) document.title = `CWI_STUDIO_PROBE ${JSON.stringify(report)}`;
    };
    publish();
    const timer = window.setInterval(publish, 250);
    return () => window.clearInterval(timer);
  }, []);

  return {
    model,
    level,
    waveform,
    connection,
    runtime,
    session,
    languageError,
    selectLanguage,
    scheduleWord,
    clockEpoch,
    playheadMs,
    startedAt,
    lastEventAt,
    dispatch,
  };
}
