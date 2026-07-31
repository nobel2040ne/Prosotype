"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  initialCaptionModel,
  nextRevealDeadline,
  pendingRevealCanAnimate,
  reduceCaptionEvent,
  revealIntentForFirstSeen,
  type CaptionEvent,
  type CaptionModel,
  type CaptionWord,
  type LevelEvent,
  type RevealIntent,
} from "@/lib/caption-store";
import {
  acousticTimeMs,
  acousticBacklogMs,
  adaptiveMotionDurationMs,
  exceedsMotionBacklogCeiling,
  isHistoricalInsertion,
  naturalMotionDurationMs,
  nextActiveMotionDelayMs,
  recentAcousticGapMs,
  unpaintedReservationExpired,
} from "@/lib/motion-timing";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "demo";
export type RevealState = "hidden" | "active" | "settled";
export interface MotionSnapshot {
  word: CaptionWord;
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
  displayMode: string;
  maxWords: number;
  paragraphWordLimit: number;
  stageParagraphHistory: number;
  stageWordsPerBlock: number;
  /** Floor on words per Stage row; below this a row stops reading as a phrase. */
  stageWordsMin: number;
  /** Rows the stack must fit before a shorter row (larger type) is preferred. */
  stageMinRows: number;
  revealGapMs: number;
  revealGapMinMs: number;
  revealGapMaxMs: number;
  revealTimingStrength: number;
  catchupGapMs: number;
  maxActiveMotions: number;
  wordMotionBaseMs: number;
  wordMotionMaxMs: number;
  wordMotionSpanStretch: number;
  wordMotionMinMs: number;
  wordMotionBacklogTargetMs: number;
  /** Above this acoustic backlog a word settles instead of animating. */
  motionBacklogCeilingMs: number;
  wordMotionRateHeadroom: number;
  wordMotionCatchupScale: number;
  syncPop: number;
  syncElevationEm: number;
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
  displayMode: "fast",
  maxWords: 8,
  paragraphWordLimit: 0,
  stageParagraphHistory: 6,
  stageWordsPerBlock: 6,
  stageWordsMin: 3,
  stageMinRows: 10,
  revealGapMs: 140,
  revealGapMinMs: 80,
  revealGapMaxMs: 260,
  revealTimingStrength: 0.75,
  catchupGapMs: 60,
  maxActiveMotions: 3,
  wordMotionBaseMs: 520,
  wordMotionMaxMs: 720,
  wordMotionSpanStretch: 0.42,
  wordMotionMinMs: 320,
  wordMotionBacklogTargetMs: 600,
  motionBacklogCeilingMs: 1200,
  wordMotionRateHeadroom: 0.90,
  wordMotionCatchupScale: 0.82,
  syncPop: 0.15,
  syncElevationEm: 0.25,
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

const UNPAINTED_RESERVATION_TIMEOUT_MS = 250;

interface PendingReveal {
  id: string;
  intent: RevealIntent;
}

interface StreamOptions {
  reducedMotion: boolean;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
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
  const [reveal, setReveal] = useState<Record<string, RevealState>>({});
  const [motionSnapshots, setMotionSnapshots] =
    useState<Record<string, MotionSnapshot>>({});
  const [startedAt] = useState(() => Date.now());
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  const modelRef = useRef(model);
  const revealRef = useRef(reveal);
  const levelRef = useRef(level);
  const pendingRef = useRef<PendingReveal[]>([]);
  const knownRef = useRef(new Set<string>());
  const activeRef = useRef(new Map<string, number>());
  const motionStartedRef = useRef(new Set<string>());
  const motionPaintStartedRef = useRef(new Map<string, number>());
  const unpaintedReservationsRef = useRef(new Map<string, number>());
  const abortedUnpaintedRef = useRef(new Set<string>());
  const motionEligibleRef = useRef(new Set<string>());
  const discoveryFrontierTimeRef = useRef(Number.NEGATIVE_INFINITY);
  const maxPresentationBacklogRef = useRef(0);
  const adaptiveMotionStartsRef = useRef(0);
  // Peak simultaneous motions. `activeMotions` is instantaneous, so a headless
  // sample almost never lands on the peak; the concurrency cap can only be
  // verified against a running maximum.
  const maxActiveMotionsRef = useRef(0);
  const staleSettledRef = useRef(0);
  const minimumMotionDurationRef = useRef(Number.POSITIVE_INFINITY);
  const deadlineRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pumpRef = useRef<() => void>(() => undefined);
  const eventIdRef = useRef(0);

  useEffect(() => {
    modelRef.current = model;
  }, [model]);
  useEffect(() => {
    revealRef.current = reveal;
  }, [reveal]);
  useEffect(() => {
    levelRef.current = level;
  }, [level]);

  const backendOrigin =
    process.env.NEXT_PUBLIC_AUTOCWI_ORIGIN?.replace(/\/$/, "") ?? "";

  const dispatch = useCallback((event: CaptionEvent, eventId?: number) => {
    const id = eventId ?? ++eventIdRef.current;
    setLastEventAt(Date.now());
    if (event.type === "level") {
      const incoming = event as unknown as LevelEvent;
      setLevel(incoming);
      setWaveform((values) => [...values.slice(-31), Number(incoming.rms_db)]);
      return;
    }
    setModel((current) => reduceCaptionEvent(current, event, id));
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
      const levelTimer = setInterval(() => {
        const phase = performance.now() / 420;
        dispatch({
          type: "level",
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

  const schedulePump = useCallback((delay = 0) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(
      () => pumpRef.current(),
      Math.max(0, delay),
    );
  }, []);

  const pump = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    const now = performance.now();
    const expiredIds: string[] = [];
    for (const [id, expiry] of activeRef.current) {
      if (!modelRef.current.words[id]) {
        activeRef.current.delete(id);
        unpaintedReservationsRef.current.delete(id);
      } else if (
        expiry === Number.POSITIVE_INFINITY &&
        unpaintedReservationExpired(
          unpaintedReservationsRef.current.get(id),
          now,
          UNPAINTED_RESERVATION_TIMEOUT_MS,
        )
      ) {
        activeRef.current.delete(id);
        unpaintedReservationsRef.current.delete(id);
        abortedUnpaintedRef.current.add(id);
        motionEligibleRef.current.delete(id);
        expiredIds.push(id);
      } else if (now >= expiry) {
        activeRef.current.delete(id);
        expiredIds.push(id);
      }
    }
    if (expiredIds.length) {
      setReveal((current) => {
        const next = {...current};
        for (const id of expiredIds) {
          if (next[id] === "active") next[id] = "settled";
        }
        return next;
      });
    }
    while (
      pendingRef.current.length &&
      !modelRef.current.words[pendingRef.current[0].id]
    ) {
      const dropped = pendingRef.current.shift();
      if (dropped && revealRef.current[dropped.id] === "hidden") {
        knownRef.current.delete(dropped.id);
        motionEligibleRef.current.delete(dropped.id);
      }
    }
    if (!pendingRef.current.length) {
      deadlineRef.current = 0;
      const cleanupDelay = nextActiveMotionDelayMs(
        activeRef.current.values(),
        now,
      );
      if (cleanupDelay !== null) schedulePump(cleanupDelay);
      return;
    }
    if (now < deadlineRef.current) {
      schedulePump(deadlineRef.current - now);
      return;
    }

    const pending = pendingRef.current[0];
    const activeCount = activeRef.current.size;
    if (activeCount >= runtime.maxActiveMotions) {
      schedulePump(16);
      return;
    }

    pendingRef.current.shift();
    const word = modelRef.current.words[pending.id];
    if (!word) {
      schedulePump(0);
      return;
    }
    // Measured BEFORE the animate decision: a word far enough behind the
    // acoustic frontier is history, and history settles rather than racing
    // through the motion queue long after it was spoken.
    const backlogMs = acousticBacklogMs(
      modelRef.current.words,
      pending.id,
      modelRef.current.order.at(-1),
    );
    const isStale = exceedsMotionBacklogCeiling(
      backlogMs,
      runtime.motionBacklogCeilingMs,
    );
    const animate = !isStale && pendingRevealCanAnimate(
      pending.intent,
      reducedMotion,
      motionStartedRef.current.has(pending.id),
    );
    const nextState: RevealState = animate ? "active" : "settled";
    if (animate) {
      const acousticGapMs = recentAcousticGapMs(
        modelRef.current.words,
        modelRef.current.order,
        pending.id,
      );
      const naturalDurationMs = naturalMotionDurationMs(word, runtime);
      const durationMs = adaptiveMotionDurationMs(
        naturalDurationMs,
        acousticGapMs,
        backlogMs,
        pendingRef.current.length + 1,
        runtime,
      );
      maxPresentationBacklogRef.current = Math.max(
        maxPresentationBacklogRef.current,
        backlogMs,
      );
      minimumMotionDurationRef.current = Math.min(
        minimumMotionDurationRef.current,
        durationMs,
      );
      if (durationMs < naturalDurationMs - 0.5) {
        adaptiveMotionStartsRef.current += 1;
      }
      motionStartedRef.current.add(pending.id);
      setMotionSnapshots((current) => (
        current[pending.id]
          ? current
          : {
              ...current,
              [pending.id]: {
                word: {...word},
                durationMs,
              },
            }
      ));
      // Reserve the concurrency slot immediately, but do not start its clock
      // until the word's layout effect confirms the first real browser paint.
      activeRef.current.set(pending.id, Number.POSITIVE_INFINITY);
      maxActiveMotionsRef.current = Math.max(
        maxActiveMotionsRef.current,
        activeRef.current.size,
      );
      unpaintedReservationsRef.current.set(pending.id, performance.now());
      schedulePump(UNPAINTED_RESERVATION_TIMEOUT_MS);
    } else {
      if (isStale) staleSettledRef.current += 1;
      motionEligibleRef.current.delete(pending.id);
    }
    setReveal((current) => ({...current, [pending.id]: nextState}));

    const nextPending = pendingRef.current[0];
    if (!nextPending) {
      deadlineRef.current = 0;
      return;
    }
    const nextWord = modelRef.current.words[nextPending.id];
    const from = Number(word.t ?? word.start);
    const to = Number(nextWord?.t ?? nextWord?.start);
    const acoustic = Number.isFinite(from) && Number.isFinite(to) && to > from
      ? clamp((to - from) * 1000, runtime.revealGapMinMs, runtime.revealGapMaxMs)
      : runtime.revealGapMs;
    const gap = isStale
      ? 0
      : runtime.revealGapMs +
        (acoustic - runtime.revealGapMs) * runtime.revealTimingStrength;
    deadlineRef.current = nextRevealDeadline(
      deadlineRef.current || now,
      performance.now(),
      gap,
      runtime.catchupGapMs,
    );
    schedulePump(deadlineRef.current - performance.now());
  }, [reducedMotion, runtime, schedulePump]);

  useEffect(() => {
    pumpRef.current = pump;
  }, [pump]);

  useEffect(() => {
    const currentIds = new Set(model.order);
    const revealUpdates: Record<string, RevealState> = {};
    pendingRef.current = pendingRef.current.filter(({id}) => currentIds.has(id));
    for (const id of model.order) {
      const word = model.words[id];
      const wordTime = acousticTimeMs(word);
      if (knownRef.current.has(id)) {
        if (Number.isFinite(wordTime)) {
          discoveryFrontierTimeRef.current = Math.max(
            discoveryFrontierTimeRef.current,
            wordTime,
          );
        }
        continue;
      }
      knownRef.current.add(id);
      const discoveredBehindFrontier = isHistoricalInsertion(
        word,
        discoveryFrontierTimeRef.current,
      );
      const intent = word && !discoveredBehindFrontier
        ? revealIntentForFirstSeen(word, reducedMotion)
        : "settle";
      if (Number.isFinite(wordTime)) {
        discoveryFrontierTimeRef.current = Math.max(
          discoveryFrontierTimeRef.current,
          wordTime,
        );
      }
      if (intent === "settle") {
        revealUpdates[id] = "settled";
      } else {
        revealUpdates[id] = "hidden";
        motionEligibleRef.current.add(id);
        pendingRef.current.push({id, intent});
      }
    }
    for (const id of knownRef.current) {
      if (!currentIds.has(id) && revealRef.current[id] === "hidden") {
        knownRef.current.delete(id);
        motionEligibleRef.current.delete(id);
      }
    }
    const revealTimer = Object.keys(revealUpdates).length
      ? setTimeout(() => {
          setReveal((current) => ({...current, ...revealUpdates}));
        }, 0)
      : null;
    schedulePump(0);
    return () => {
      if (revealTimer) clearTimeout(revealTimer);
    };
  }, [model.order, model.words, reducedMotion, schedulePump]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const confirmMotionPaint = useCallback((id: string, durationMs: number) => {
    const existing = motionPaintStartedRef.current.get(id);
    if (existing !== undefined) return existing;
    const startedAt = performance.now();
    motionPaintStartedRef.current.set(id, startedAt);
    unpaintedReservationsRef.current.delete(id);
    if (activeRef.current.has(id)) {
      activeRef.current.set(id, startedAt + Math.max(0, durationMs));
    }
    schedulePump(0);
    return startedAt;
  }, [schedulePump]);

  const completeMotion = useCallback((id: string) => {
    activeRef.current.delete(id);
    unpaintedReservationsRef.current.delete(id);
    setReveal((current) => (
      current[id] === "settled"
        ? current
        : {...current, [id]: "settled"}
    ));
    schedulePump(0);
  }, [schedulePump]);

  useEffect(() => {
    window.__cwiStudio = {
      dispatch,
      report: () => ({
        connection,
        words: modelRef.current.order.length,
        visible: modelRef.current.order
          .filter((id) => revealRef.current[id] !== "hidden").length,
        activeMotions: activeRef.current.size,
        maxActiveMotions: maxActiveMotionsRef.current,
        staleSettledWords: staleSettledRef.current,
        pendingReveals: pendingRef.current.length,
        motionStarts: motionStartedRef.current.size,
        motionPaintStarts: motionPaintStartedRef.current.size,
        motionsWithoutPaint: [...motionStartedRef.current].filter(
          (id) => (
            !motionPaintStartedRef.current.has(id) &&
            !abortedUnpaintedRef.current.has(id)
          ),
        ).length,
        abortedUnpaintedMotions: abortedUnpaintedRef.current.size,
        presentationBacklogMs: pendingRef.current.length
          ? acousticBacklogMs(
              modelRef.current.words,
              pendingRef.current[0].id,
              modelRef.current.order.at(-1),
            )
          : 0,
        maxPresentationBacklogMs: maxPresentationBacklogRef.current,
        adaptiveMotionStarts: adaptiveMotionStartsRef.current,
        minimumMotionDurationMs: Number.isFinite(
          minimumMotionDurationRef.current,
        )
          ? minimumMotionDurationRef.current
          : 0,
        motionEligibleWords: motionEligibleRef.current.size,
        freshWordsWithoutMotion: modelRef.current.order.filter((id) => {
          return (
            !reducedMotion &&
            motionEligibleRef.current.has(id) &&
            revealRef.current[id] === "settled" &&
            !motionStartedRef.current.has(id)
          );
        }).length,
        directionKnown: Number.isFinite(
          Number(levelRef.current.direction_deg ??
            levelRef.current.azimuth_deg),
        ),
      }),
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
    reveal,
    motionSnapshots,
    confirmMotionPaint,
    completeMotion,
    startedAt,
    lastEventAt,
    dispatch,
  };
}
