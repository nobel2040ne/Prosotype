"use client";

import {
  AudioWaveform,
  Captions,
  Check,
  ChevronRight,
  CircleGauge,
  Eye,
  Globe2,
  Mic2,
  Navigation,
  PanelRightClose,
  PanelRightOpen,
  SlidersHorizontal,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type AnimationEvent,
  type CSSProperties,
} from "react";
import {
  useCaptionStream,
  type LanguageSession,
  type LiveLanguageOption,
  type MotionSnapshot,
  type RevealState,
  type RuntimeConfig,
} from "@/hooks/use-caption-stream";
import {
  buildCaptionParagraphs,
  planCaptionStackMotion,
  selectStableCaptionStack,
  type CaptionParagraph,
  type CaptionStackPosition,
} from "@/lib/caption-paragraphs";
import type {CaptionWord, LevelEvent} from "@/lib/caption-store";
import {
  captionMotionFor,
  type VoiceTypeRanges,
} from "@/lib/caption-motion";
import {naturalMotionDurationMs} from "@/lib/motion-timing";
import {planStageLayout, rowBudgetEm} from "@/lib/stage-layout";

type CSSVars = CSSProperties & Record<`--${string}`, string | number>;
type ViewMode = "stage" | "transcript";
interface SettingsState {
  captionScale: number;
  motionIntensity: number;
  reducedMotion: boolean;
  highContrast: boolean;
  lightStage: boolean;
}

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const STACK_SHIFT_DURATION_MS = 540;
const STACK_ENTER_DURATION_MS = 620;
const STACK_EASING = "cubic-bezier(.18,.72,.22,1)";

const number = (value: unknown, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

/** The CWI 2.3 crest bounds, as the runtime config declares them. */
function voiceRanges(runtime: RuntimeConfig): VoiceTypeRanges {
  return {
    scale: runtime.voiceScaleRange,
    scaleResponse: runtime.voiceScaleResponse,
    weight: runtime.weightRange,
    width: runtime.widthRange,
  };
}

function speakerStatus(word: CaptionWord): string {
  if (word.speaker_status) return word.speaker_status;
  return word.speaker ? "stable" : "unknown";
}

function speakerNumber(speaker: string | null): string {
  if (!speaker) return "—";
  const match = speaker.match(/\d+/);
  return String(match ? Number(match[0]) : 1).padStart(2, "0");
}

// Both fallbacks are CSS variables rather than literals: they have to follow the
// stage theme, and every consumer of the returned string writes it straight into
// a custom property, so the indirection resolves for free.
function speakerColor(
  speaker: string | null,
  status: string,
  palette: string[],
): string {
  if (!speaker || status === "unknown") return "var(--caption-unknown)";
  let hash = 0;
  for (const char of speaker) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length] ?? "var(--accent)";
}

function useElapsed(startedAt: number): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const MotionWord = memo(function MotionWord({
  id,
  word,
  motionSnapshot,
  state,
  color,
  intensity,
  runtime,
  onMotionPaint,
  onMotionComplete,
}: {
  id: string;
  word: CaptionWord;
  motionSnapshot: MotionSnapshot | undefined;
  state: RevealState;
  color: string;
  intensity: number;
  runtime: RuntimeConfig;
  onMotionPaint: (id: string, durationMs: number) => number;
  onMotionComplete: (id: string) => void;
}) {
  const wordRef = useRef<HTMLSpanElement>(null);
  const motionWord = motionSnapshot?.word ?? word;
  const loudness = clamp(number(motionWord.loudness, 0.5), 0, 1);
  const deliveryConfidence = clamp(
    number(motionWord.delivery_confidence),
    0,
    1,
  );
  const deliveryEnabled = runtime.deliveryMotionEnabled &&
    deliveryConfidence >= runtime.deliveryMinConfidence;
  // 0.5 is the neutral of the breathiness proxy, so an unavailable reading
  // leaves the width axis on the pitch term alone rather than pushing it wide.
  const texture = deliveryEnabled
    ? clamp(number(motionWord.delivery_texture, 0.5), 0, 1)
    : 0.5;
  // Retained as a readout only. CWI has no delivery-specific motion families:
  // every word receives the same 2.2.3 cue while the continuous 2.3 axes shape
  // the glyph inside that one motion window.
  const deliveryProfile = deliveryEnabled
    ? String(motionWord.delivery_profile ?? "steady")
    : "steady";
  const pitch = number(motionWord.pitch_hz, 0);
  const motion = captionMotionFor(
    {loudness, pitchHz: pitch, texture},
    voiceRanges(runtime),
    intensity,
    runtime.syncPop,
    runtime.syncElevationEm,
  );

  const duration = motionSnapshot?.durationMs ??
    naturalMotionDurationMs(motionWord, runtime);
  const style: CSSVars = {
    "--speaker-color": color,
    "--voice-scale": motion.voice.scale.toFixed(3),
    "--motion-footprint-scale": (
      motion.voice.scale * motion.sync.scale
    ).toFixed(3),
    "--voice-weight": String(motion.voice.weight),
    "--voice-width": `${motion.voice.width}%`,
    // 2.2.3 is constant; the Expression control changes §2.3, not this cue.
    "--sync-pop": motion.sync.scale.toFixed(3),
    "--sync-elevation": `${motion.sync.elevationEm.toFixed(3)}em`,
    "--motion-duration": `${duration.toFixed(0)}ms`,
    "--motion-phase-delay": "0ms",
  };
  const status = speakerStatus(word);

  useLayoutEffect(() => {
    const element = wordRef.current;
    if (!element) return;
    // The hidden normal-type sizer owns layout; the animated glyph is overlaid.
    // No width read/freeze is necessary, even while weight and width change.
    const phaseStartedAt = state === "active" && motionSnapshot
      ? onMotionPaint(id, duration)
      : performance.now();
    const phaseElapsed = state === "active"
      ? clamp(performance.now() - phaseStartedAt, 0, duration)
      : 0;
    element.style.setProperty(
      "--motion-phase-delay",
      `${(-phaseElapsed).toFixed(1)}ms`,
    );
  }, [
    duration,
    id,
    motionSnapshot,
    onMotionPaint,
    state,
    word.text,
  ]);

  const handleAnimationEnd = (event: AnimationEvent<HTMLSpanElement>) => {
    if (event.target === event.currentTarget) onMotionComplete(id);
  };

  return (
    <span
      className={`caption-word ${state === "active" ? "is-active" : "is-settled"}`}
      data-status={status}
      data-final={word.final ? "true" : "false"}
      data-sustain={word.sustain_active ? "true" : "false"}
      data-delivery={deliveryProfile}
      data-word-id={id}
      style={style}
      ref={wordRef}
      title={`${deliveryProfile} delivery · ${
        pitch > 0 ? `${Math.round(pitch)} Hz` : "unvoiced"
      } · ${number(word.loudness_db, -72).toFixed(1)} dB · ${
        motion.voice.weight
      }/${motion.voice.width}%`}
    >
      <span className="word-sizer word-sizer-normal" aria-hidden="true">
        {word.text}
      </span>
      <span className="word-sizer word-sizer-crest" aria-hidden="true">
        {word.text}
      </span>
      <span
        className="word-glyph"
        aria-label={word.text}
        onAnimationEnd={handleAnimationEnd}
      >
        <span className="word-ink" aria-hidden="true">{word.text}</span>
      </span>
    </span>
  );
});

function VoiceOrb({
  level,
  color,
  large = false,
}: {
  level: LevelEvent;
  color: string;
  large?: boolean;
}) {
  const volume = clamp((number(level.rms_db, -72) + 60) / 45, 0, 1);
  const pitch = clamp((number(level.pitch_hz, 165) - 80) / 170, 0, 1);
  const brightness = clamp(
    (number(level.spectral_centroid_hz, 1600) - 500) / 3000,
    0,
    1,
  );
  const periodicity = clamp(number(level.pitch_confidence, 0), 0, 1);
  const force = clamp(number(level.delivery_force, volume), 0, 1);
  const attack = clamp(number(level.delivery_attack), 0, 1);
  const contour = clamp(number(level.delivery_contour), -1, 1);
  const flow = clamp(number(level.delivery_flow, periodicity), 0, 1);
  const texture = clamp(number(level.delivery_texture, 1 - periodicity), 0, 1);
  const profile = String(level.delivery_profile ?? "steady");
  const direction = number(
    level.direction_deg ?? level.azimuth_deg,
    Number.NaN,
  );
  const directionKnown = Number.isFinite(direction);
  const style: CSSVars = {
    "--orb-color": color,
    "--orb-scale": large
      ? (0.84 + volume * 0.29).toFixed(3)
      : (0.72 + volume * 0.62).toFixed(3),
    "--orb-halo": `${(volume * periodicity * (large ? 38 : 14)).toFixed(1)}px`,
    "--pitch-y": `${(78 - pitch * 56).toFixed(1)}%`,
    "--texture-x": (0.68 + brightness * 0.78).toFixed(3),
    "--texture-size": (0.74 + volume * 0.48).toFixed(3),
    "--texture-opacity": (0.10 + periodicity * 0.48).toFixed(3),
    "--texture-angle": `${(-14 + brightness * 28 + contour * 18).toFixed(1)}deg`,
    "--delivery-tilt": `${(contour * 8).toFixed(1)}deg`,
    "--delivery-stretch-x": (0.96 + flow * 0.12).toFixed(3),
    "--delivery-stretch-y": (0.94 + force * 0.15).toFixed(3),
    "--delivery-energy": (0.18 + force * 0.62 + attack * 0.20).toFixed(3),
    "--delivery-texture": texture.toFixed(3),
    "--direction-angle": `${directionKnown ? ((direction % 360) + 360) % 360 : 0}deg`,
  };
  const label = `${profile} delivery, ${number(level.rms_db, -72).toFixed(1)} dB, ${
    number(level.pitch_hz) > 0 ? `${Math.round(number(level.pitch_hz))} Hz` : "unvoiced"
  }${directionKnown ? `, ${Math.round(direction)} degrees` : ""}`;

  if (!large) {
    return (
      <span
        className="line-voice-orb"
        data-speech={level.speech ? "true" : "false"}
        data-delivery={profile}
        role="img"
        aria-label={`Live voice: ${label}`}
        style={style}
      >
        <i />
      </span>
    );
  }

  return (
    <div
      className="voice-compass"
      data-direction={directionKnown ? "known" : "unknown"}
      data-delivery={profile}
      role="img"
      aria-label={`Voice compass: ${label}`}
      style={style}
    >
      <span className="compass-radar-ring ring-one" />
      <span className="compass-radar-ring ring-two" />
      <span className="compass-crosshair horizontal" />
      <span className="compass-crosshair vertical" />
      <span className="compass-direction"><i /></span>
      <span className="compass-texture" />
      <span className="compass-pitch" />
    </div>
  );
}

function CaptionFeed({
  paragraphs,
  palette,
  level,
  intensity,
  runtime,
  motionSnapshots,
  confirmMotionPaint,
  completeMotion,
  transcript,
  reducedMotion,
}: {
  paragraphs: CaptionParagraph[];
  palette: string[];
  level: LevelEvent;
  intensity: number;
  runtime: RuntimeConfig;
  motionSnapshots: Record<string, MotionSnapshot>;
  confirmMotionPaint: (id: string, durationMs: number) => number;
  completeMotion: (id: string) => void;
  transcript: boolean;
  reducedMotion: boolean;
}) {
  const rowNodes = useRef(new Map<string, HTMLElement>());
  const previousPositions = useRef<CaptionStackPosition[]>([]);
  const stackInitialized = useRef(false);
  const stackAnimations = useRef(new Map<string, Animation>());
  const seenRows = useRef(new Set<string>());

  useLayoutEffect(() => {
    if (transcript || reducedMotion || paragraphs.length === 0) {
      for (const animation of stackAnimations.current.values()) {
        animation.cancel();
      }
      stackAnimations.current.clear();
      previousPositions.current = [];
      stackInitialized.current = false;
      return;
    }

    const currentPositions = paragraphs.flatMap((paragraph) => {
      const node = rowNodes.current.get(paragraph.id);
      if (!node) return [];
      const transform = getComputedStyle(node).transform;
      const animatedY = transform === "none"
        ? 0
        : new DOMMatrixReadOnly(transform).m42;
      return [{
        id: paragraph.id,
        top: node.getBoundingClientRect().top - animatedY,
      }];
    });
    if (!stackInitialized.current) {
      const motions = planCaptionStackMotion(
        [],
        currentPositions,
        seenRows.current,
      );
      previousPositions.current = currentPositions;
      for (const {id} of currentPositions) seenRows.current.add(id);
      stackInitialized.current = true;
      for (const motion of motions) {
        const node = rowNodes.current.get(motion.id);
        if (!node) continue;
        const targetOpacity = getComputedStyle(node).opacity;
        const animation = node.animate(
          [
            {opacity: 0, transform: "translateY(0.58em) scale(.985)"},
            {opacity: targetOpacity, transform: "translateY(0) scale(1)"},
          ],
          {
            duration: STACK_ENTER_DURATION_MS,
            easing: STACK_EASING,
          },
        );
        stackAnimations.current.set(motion.id, animation);
        animation.addEventListener("finish", () => {
          if (stackAnimations.current.get(motion.id) === animation) {
            stackAnimations.current.delete(motion.id);
          }
        }, {once: true});
      }
      return;
    }

    const motions = planCaptionStackMotion(
      previousPositions.current,
      currentPositions,
      seenRows.current,
    );
    for (const motion of motions) {
      const node = rowNodes.current.get(motion.id);
      if (!node) continue;
      stackAnimations.current.get(motion.id)?.cancel();
      const targetOpacity = getComputedStyle(node).opacity;
      const animation = node.animate(
        motion.kind === "shift"
          ? [
            {transform: `translateY(${motion.deltaY}px)`},
            {transform: "translateY(0)"},
          ]
          : [
            {opacity: 0, transform: "translateY(0.58em) scale(.985)"},
            {opacity: targetOpacity, transform: "translateY(0) scale(1)"},
          ],
        {
          duration: motion.kind === "shift"
            ? STACK_SHIFT_DURATION_MS
            : STACK_ENTER_DURATION_MS,
          easing: STACK_EASING,
        },
      );
      stackAnimations.current.set(motion.id, animation);
      animation.addEventListener("finish", () => {
        if (stackAnimations.current.get(motion.id) === animation) {
          stackAnimations.current.delete(motion.id);
        }
      }, {once: true});
    }
    for (const {id} of currentPositions) seenRows.current.add(id);
    previousPositions.current = currentPositions;
  }, [paragraphs, reducedMotion, transcript]);

  useEffect(() => () => {
    for (const animation of stackAnimations.current.values()) {
      animation.cancel();
    }
    stackAnimations.current.clear();
  }, []);

  // The feed container is rendered even while empty: it is the element the stage
  // measures to decide how many rows fit (`useStackCapacity`), and that answer is
  // needed BEFORE the first word arrives. The empty state is a sibling.
  return (
    <div className={transcript ? "transcript-feed" : "caption-feed"}>
      {paragraphs.map((paragraph, paragraphIndex) => {
        const color = speakerColor(paragraph.speaker, paragraph.status, palette);
        const isLatest = paragraphIndex === paragraphs.length - 1;
        const firstWord = paragraph.words[0]?.word;
        return (
          <section
            className="caption-paragraph"
            data-current={isLatest ? "true" : "false"}
            data-row-id={paragraph.id}
            data-status={paragraph.status}
            key={paragraph.id}
            ref={(node) => {
              if (node) rowNodes.current.set(paragraph.id, node);
              else rowNodes.current.delete(paragraph.id);
            }}
            style={{"--speaker-color": color} as CSSVars}
          >
            <header>
              <span className="speaker-index">
                {paragraph.status === "mixed" ? "↔" : speakerNumber(paragraph.speaker)}
              </span>
              <span>{
                paragraph.status === "mixed"
                  ? "Speaker transition"
                  : paragraph.speaker
                    ? `Speaker ${speakerNumber(paragraph.speaker)}`
                    : "Attribution pending"
              }</span>
              {transcript && (
                <time>{number(firstWord?.start).toFixed(1)}s</time>
              )}
            </header>
            <div className="caption-surface">
              <div className="caption-words">
                {paragraph.words.map(({id, word, reveal}) => (
                  <MotionWord
                    id={id}
                    word={word}
                    motionSnapshot={motionSnapshots[id]}
                    state={reveal}
                    color={speakerColor(
                      word.speaker ?? null,
                      speakerStatus(word),
                      palette,
                    )}
                    intensity={intensity}
                    runtime={runtime}
                    onMotionPaint={confirmMotionPaint}
                    onMotionComplete={completeMotion}
                    key={id}
                  />
                ))}
                {isLatest && !transcript && (
                  <VoiceOrb level={level} color={color} />
                )}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}

/**
 * Resolve the stage's two coupled unknowns: words per row, and rows retained.
 *
 * Neither can be a constant. `studio_stack_words_per_block` was six and
 * `studio_stage_paragraph_history` was six, and between them they handed the
 * caption size to the window's aspect ratio. Measured at 1440x900 that gave
 * 47px type and an 86%-full stage; measured at 862x998 -- the same studio in a
 * narrower window -- the identical settings gave **23.6px** type on a stage that
 * was **40% empty**, because six words still had to fit across a 538px stage.
 *
 * Everything the planner needs is read off the live DOM rather than restated
 * here: the feed's real width and clip gutters, the height term
 * (`--caption-height-cap`, registered with `@property` so it computes to px), the
 * per-language `--per-word-em` budget, and a rendered row's true height, which
 * the dark stage inflates with .22em of padding the light stage does not have.
 */
function useStageLayout(
  stage: React.RefObject<HTMLDivElement | null>,
  runtime: RuntimeConfig,
  hasRows: boolean,
  captionScale: number,
  view: ViewMode,
  // A ResizeObserver on the stage cannot see a theme swap, and the theme changes
  // a row's height, so it has to be an explicit dependency.
  theme: string,
): {wordsPerRow: number; rows: number; rowBudgetEm: number} {
  const [layout, setLayout] = useState(() => ({
    wordsPerRow: runtime.stageWordsPerBlock,
    rows: runtime.stageParagraphHistory,
    rowBudgetEm: rowBudgetEm(runtime.stageWordsPerBlock, 1.40, 4.30),
  }));
  useEffect(() => {
    const node = stage.current;
    if (!node || view !== "stage") return;
    const measure = () => {
      const feed = node.querySelector<HTMLElement>(".caption-feed");
      if (!feed) return;
      const styles = getComputedStyle(feed);
      const fontSize = parseFloat(styles.fontSize);
      const stageHeight = node.clientHeight;
      if (!fontSize || !stageHeight) return;
      // Chrome reports a percentage `max-height` as the literal "92%" instead of
      // resolving it, so recover the fraction rather than parsing a px value.
      const maxHeightFraction = styles.maxHeight.endsWith("%")
        ? parseFloat(styles.maxHeight) / 100
        : (parseFloat(styles.maxHeight) || stageHeight) / stageHeight;
      // A rendered row is exact; before the first word its line box is the only
      // estimate there is.
      const row = feed.querySelector<HTMLElement>(".caption-paragraph");
      const rowHeightEm = row
        ? row.getBoundingClientRect().height / fontSize
        : 1.38;
      const next = planStageLayout({
        feedWidthPx: feed.getBoundingClientRect().width,
        stageHeightPx: stageHeight,
        gutterEm: (parseFloat(styles.paddingLeft) +
          parseFloat(styles.paddingRight)) / fontSize,
        verticalGutterEm: (parseFloat(styles.paddingTop) +
          parseFloat(styles.paddingBottom)) / fontSize,
        wordEmLinear: parseFloat(styles.getPropertyValue("--word-em-linear")),
        wordEmSpread: parseFloat(styles.getPropertyValue("--word-em-spread")),
        rowHeightEm,
        maxHeightFraction,
        heightCapPx:
          parseFloat(styles.getPropertyValue("--caption-height-cap")) *
          captionScale,
        minWords: runtime.stageWordsMin,
        maxWords: runtime.stageWordsPerBlock,
        minRows: runtime.stageMinRows,
      });
      const budget = rowBudgetEm(
        next.wordsPerRow,
        parseFloat(styles.getPropertyValue("--word-em-linear")) || 1.40,
        parseFloat(styles.getPropertyValue("--word-em-spread")) || 4.30,
      );
      setLayout((current) => (
        current.wordsPerRow === next.wordsPerRow &&
        current.rows === next.rows &&
        current.rowBudgetEm === budget
          ? current
          : {wordsPerRow: next.wordsPerRow, rows: next.rows, rowBudgetEm: budget}
      ));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [stage, runtime, hasRows, captionScale, view, theme]);
  return layout;
}

function SignalWaveform({values}: {values: number[]}) {
  return (
    <div className="signal-waveform" aria-label="Recent input level">
      {values.map((db, index) => {
        const height = clamp((db + 72) / 57, 0.08, 1);
        return (
          <i
            key={index}
            style={{"--bar-height": height.toFixed(3)} as CSSVars}
          />
        );
      })}
    </div>
  );
}

function LanguageGate({
  session,
  error,
  onSelect,
}: {
  session: LanguageSession;
  error: string | null;
  onSelect: (language: string) => void;
}) {
  const selected = session.languages.find(
    (language) => language.id === session.language,
  );
  const selecting = session.state === "selecting";
  const unavailable = session.state === "unavailable";

  return (
    <section
      className="language-gate"
      role="dialog"
      aria-modal="true"
      aria-labelledby="language-gate-title"
    >
      <div className="language-gate-glow" aria-hidden="true" />
      <div className="language-gate-card">
        <header className="language-gate-brand">
          <div>
            <strong>AutoCWI</strong>
            <span>Live caption setup</span>
          </div>
        </header>

        <div className="language-gate-copy">
          <span className="eyebrow">
            <Globe2 size={14} />
            Session language
          </span>
          <h1 id="language-gate-title">
            {selecting
              ? "What language will be spoken?"
              : unavailable
                ? "The local caption engine is unavailable"
                : selected
                  ? `Preparing ${selected.nativeLabel}`
                  : "Preparing language setup"}
          </h1>
          <p>
            {selecting
              ? "Choose before capture begins. AutoCWI will load the matching local speech model and lock it for this session."
              : unavailable
                ? "Open this studio through “python -m autocwi live” so it can reach the local session controller."
                : "Loading the matching recognizer before microphone capture starts. No audio has been captured yet."}
          </p>
        </div>

        {selecting ? (
          <div className="language-options" role="list" aria-label="Caption language">
            {session.languages.map((language: LiveLanguageOption) => (
              <button
                className="language-option"
                key={language.id}
                lang={language.id}
                onClick={() => onSelect(language.id)}
                type="button"
              >
                <span className="language-name">
                  <span className="language-code">{language.id.toUpperCase()}</span>
                  <strong>{language.nativeLabel}</strong>
                  {language.nativeLabel !== language.label && (
                    <small>{language.label}</small>
                  )}
                </span>
                <span className="language-description">{language.description}</span>
                <ChevronRight size={18} />
              </button>
            ))}
          </div>
        ) : !unavailable ? (
          <div className="language-loading" aria-live="polite">
            <span className="language-loader" aria-hidden="true" />
            <div>
              <strong>Loading locally</strong>
              <span>{selected?.description ?? "Connecting to the caption engine"}</span>
            </div>
          </div>
        ) : null}

        {error && <p className="language-error" role="alert">{error}</p>}
        <footer className="language-gate-footer">
          <span><i /> On-device processing</span>
          <span>Language cannot change during capture</span>
        </footer>
      </div>
    </section>
  );
}

function SettingsPanel({
  settings,
  setSettings,
  close,
}: {
  settings: SettingsState;
  setSettings: (settings: SettingsState) => void;
  close: () => void;
}) {
  return (
    <aside className="settings-panel" aria-label="Presentation settings">
      <header>
        <h2>Presentation</h2>
        <button className="icon-button" onClick={close} aria-label="Close settings">
          <X size={17} />
        </button>
      </header>

      <label className="range-control">
        <span><Captions size={15} /> Caption scale</span>
        <output>{Math.round(settings.captionScale * 100)}%</output>
        {/* 100% is now the LARGEST size that still fits a full row across the
            stage, not an arbitrary middle. The width cap is a hard bound -- rows
            do not wrap, so anything above it is clipped, not wrapped -- which is
            why the slider only reduces. */}
        <input
          type="range"
          min="0.6"
          max="1"
          step="0.05"
          value={settings.captionScale}
          onChange={(event) => setSettings({
            ...settings,
            captionScale: Number(event.target.value),
          })}
        />
      </label>

      <label className="range-control">
        <span><Sparkles size={15} /> Expression</span>
        <output>{Math.round(settings.motionIntensity * 100)}%</output>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={settings.motionIntensity}
          onChange={(event) => setSettings({
            ...settings,
            motionIntensity: Number(event.target.value),
          })}
        />
      </label>

      <button
        className="toggle-row"
        aria-pressed={settings.reducedMotion}
        onClick={() => setSettings({
          ...settings,
          reducedMotion: !settings.reducedMotion,
        })}
      >
        <span><Eye size={15} /> Reduce motion</span>
        <i data-on={settings.reducedMotion ? "true" : "false"} />
      </button>

      <button
        className="toggle-row"
        aria-pressed={settings.highContrast}
        onClick={() => setSettings({
          ...settings,
          highContrast: !settings.highContrast,
        })}
      >
        <span><CircleGauge size={15} /> High contrast</span>
        <i data-on={settings.highContrast ? "true" : "false"} />
      </button>

      <button
        className="toggle-row"
        aria-pressed={settings.lightStage}
        onClick={() => setSettings({
          ...settings,
          lightStage: !settings.lightStage,
        })}
      >
        <span><Sun size={15} /> Light stage</span>
        <i data-on={settings.lightStage ? "true" : "false"} />
      </button>

      <div className="settings-note">
        <Check size={15} />
        <p>These controls affect presentation only. Recognition and speaker evidence stay untouched.</p>
      </div>
    </aside>
  );
}

export function LiveStudio() {
  const [settings, setSettings] = useState<SettingsState>({
    captionScale: 1,
    motionIntensity: 1,
    reducedMotion: false,
    highContrast: false,
    lightStage: true,
  });
  const [view, setView] = useState<ViewMode>("stage");
  const [railOpen, setRailOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const {
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
  } = useCaptionStream({reducedMotion: settings.reducedMotion});
  const elapsed = useElapsed(startedAt);
  const activeLanguage = session.languages.find(
    (language) => language.id === session.language,
  );

  const stageRef = useRef<HTMLDivElement>(null);
  const paragraphs = useMemo(
    () => buildCaptionParagraphs(
      model.words,
      model.order,
      reveal,
      runtime.paragraphWordLimit,
    ),
    [model.words, model.order, reveal, runtime.paragraphWordLimit],
  );
  const stageLayout = useStageLayout(
    stageRef,
    runtime,
    paragraphs.length > 0,
    settings.captionScale,
    view,
    settings.lightStage ? "light" : "dark",
  );
  const stageParagraphs = view === "stage"
    ? selectStableCaptionStack(
      paragraphs,
      stageLayout.rows,
      stageLayout.wordsPerRow,
    )
    : paragraphs;
  const speakers = useMemo(() => {
    const bySpeaker = new Map<string, CaptionWord>();
    for (const paragraph of paragraphs) {
      if (!paragraph.speaker) continue;
      const latest = paragraph.words.at(-1)?.word;
      if (latest) bySpeaker.set(paragraph.speaker, latest);
    }
    return [...bySpeaker.entries()].sort(([left], [right]) =>
      left.localeCompare(right, undefined, {numeric: true})
    );
  }, [paragraphs]);
  const currentParagraph = paragraphs.at(-1);
  // The CI palette (CWI 2.1.1) is built for the black captions box and measures
  // as low as 1.19:1 on the light stage, so the light theme draws speakers from
  // `palette_light` -- same hues, darkened to >=4.5:1. Both arrive from
  // config.yaml via /runtime-config.json; neither is hardcoded here.
  const palette = settings.lightStage && runtime.paletteLight.length
    ? runtime.paletteLight
    : runtime.palette;
  const activeColor = currentParagraph
    ? speakerColor(currentParagraph.speaker, currentParagraph.status, palette)
    : palette[0];
  const direction = number(level.direction_deg ?? level.azimuth_deg, Number.NaN);
  const directionKnown = Number.isFinite(direction);
  const inputGood = level.status === "good";
  const studioStyle: CSSVars = {
    "--caption-scale": settings.captionScale,
    "--motion-intensity": settings.motionIntensity,
    "--active-color": activeColor,
    // The CSS width cap is derived from this, so the type size and the row width
    // can never disagree about how many words a row holds.
    "--stack-words": stageLayout.wordsPerRow,
    "--row-budget-em": stageLayout.rowBudgetEm.toFixed(3),
  };

  // The theme lives on the document element, not on the shell: `html`/`body`
  // carry `background: var(--bg)`, so anything the shell does not cover --
  // fullscreen backdrop, overscroll edge -- has to see it too.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = settings.lightStage ? "light" : "dark";
    root.style.colorScheme = settings.lightStage ? "light" : "dark";
  }, [settings.lightStage]);

  return (
    <main
      className="studio-shell"
      data-rail={railOpen ? "open" : "closed"}
      data-contrast={settings.highContrast ? "high" : "normal"}
      data-theme={settings.lightStage ? "light" : "dark"}
      data-reduced-motion={settings.reducedMotion ? "true" : "false"}
      data-language={session.language ?? "pending"}
      lang={session.language === "ko" ? "ko" : "en"}
      style={studioStyle}
    >
      <header className="topbar">
        <div className="brand">
          <div>
            <strong>AutoCWI</strong>
            <span>Expressive caption studio</span>
          </div>
        </div>

        <nav className="view-switcher" aria-label="Studio view">
          <button
            data-active={view === "stage"}
            onClick={() => setView("stage")}
          >
            Stage
          </button>
          <button
            data-active={view === "transcript"}
            onClick={() => setView("transcript")}
          >
            Transcript
          </button>
        </nav>

        <div className="topbar-actions">
          {/* The transport bar under the stage carried this, plus three static
              "Local processing / No cloud / Stream active" badges. The badges said
              nothing that changes; the input level does, so it moves up here and
              the stage gets the 61px back. */}
          <span className="mic-state" data-good={inputGood ? "true" : "false"}>
            <Mic2 size={14} />
            {number(level.rms_db, -72).toFixed(1)} dBFS
          </span>
          {activeLanguage && (
            <span className="language-pill">
              <Globe2 size={13} />
              {activeLanguage.nativeLabel}
            </span>
          )}
          <span className="session-clock">{elapsed}</span>
          <span className="connection-pill" data-state={connection}>
            <i />
            {connection === "demo" ? "Preview" : connection}
          </span>
          <button
            className="icon-button settings-button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Presentation settings"
          >
            <SlidersHorizontal size={17} />
          </button>
          <button
            className="icon-button rail-toggle"
            onClick={() => setRailOpen((value) => !value)}
            aria-label={railOpen ? "Close signal rail" : "Open signal rail"}
          >
            {railOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </button>
        </div>
      </header>

      <section className="workspace">
        <div
          className={`caption-stage ${view === "transcript" ? "is-transcript" : ""}`}
          ref={stageRef}
        >
          {model.sound && (
            <div className="sound-chip">
              <AudioWaveform size={13} />
              [{model.sound.label ?? model.sound.category ?? "sound"}]
            </div>
          )}
          <CaptionFeed
            paragraphs={stageParagraphs}
            palette={palette}
            level={level}
            intensity={settings.motionIntensity}
            runtime={runtime}
            motionSnapshots={motionSnapshots}
            confirmMotionPaint={confirmMotionPaint}
            completeMotion={completeMotion}
            transcript={view === "transcript"}
            reducedMotion={settings.reducedMotion}
          />
          {!stageParagraphs.length && (
            <div className="empty-stage">
              <div className="empty-mark">
                <AudioWaveform size={26} strokeWidth={1.5} />
              </div>
              <p>Ready for a voice</p>
              <span>
                {lastEventAt ? "Speech will appear here as it is understood." : model.bootStage}
              </span>
            </div>
          )}
        </div>
      </section>

      <aside className="signal-rail" aria-label="Live signal intelligence">
        <section className="rail-section signal-section">
          <header className="rail-heading">
            <h2>Voice activity</h2>
            <span className="health-badge" data-good={inputGood ? "true" : "false"}>
              {level.status ?? "idle"}
            </span>
          </header>
          <SignalWaveform values={waveform} />
          <div className="metric-row three">
            <div><strong>{number(level.rms_db, -72).toFixed(1)}</strong><span>dBFS</span></div>
            <div><strong>{Math.round(number(level.pitch_hz)) || "—"}</strong><span>Hz pitch</span></div>
            <div><strong>{Math.round(number(level.spectral_centroid_hz)) || "—"}</strong><span>Hz color</span></div>
          </div>
        </section>

        <section className="rail-section compass-section">
          <header className="rail-heading">
            <h2>Voice compass</h2>
            <Navigation size={16} />
          </header>
          <div className="compass-layout">
            <VoiceOrb level={level} color={activeColor} large />
            <div className="compass-readout">
              <div>
                <span>Direction</span>
                <strong>{directionKnown ? `${Math.round(direction)}°` : "Awaiting array"}</strong>
              </div>
              <div>
                <span>Voice profile</span>
                <strong>{
                  number(level.pitch_hz) <= 0
                    ? "Awaiting voice"
                    : `${String(level.delivery_profile ?? "steady")} · ${
                      number(level.delivery_contour) > 0.2
                        ? "rising"
                        : number(level.delivery_contour) < -0.2
                          ? "falling"
                          : number(level.delivery_flow) > 0.68
                            ? "flowing"
                            : "level"
                    }`
                }</strong>
              </div>
              {/* "Hardware: Mono input" said the same thing as "Direction:
                  Awaiting array" one line above it. */}
            </div>
          </div>
        </section>

        <section className="rail-section speakers-section">
          <header className="rail-heading">
            <h2>Active speakers</h2>
            <span className="section-count">{speakers.length}</span>
          </header>
          <div className="speaker-list">
            {speakers.length ? speakers.map(([speaker, word]) => {
              const status = speakerStatus(word);
              const color = speakerColor(speaker, status, palette);
              return (
                <div className="speaker-card" key={speaker}>
                  <span className="speaker-avatar" style={{"--speaker-color": color} as CSSVars}>
                    {speakerNumber(speaker)}
                  </span>
                  <div>
                    <strong>Speaker {speakerNumber(speaker)}</strong>
                    <span>{status} · {Math.round(number(word.speaker_confidence, 0) * 100)}% confidence</span>
                  </div>
                  <i style={{"--speaker-color": color} as CSSVars} />
                </div>
              );
            }) : (
              <div className="speaker-empty">
                <span>—</span>
                <p>Speaker profiles appear after the first attributed turn.</p>
              </div>
            )}
          </div>
        </section>

        {/* A fourth "system" section listed Recognition (a hardcoded string),
            Expression (the settings slider's own value) and Direction (the
            compass readout, again). None of it was a signal. */}
      </aside>

      {settingsOpen && (
        <>
          <button
            className="settings-scrim"
            aria-label="Close settings"
            onClick={() => setSettingsOpen(false)}
          />
          <SettingsPanel
            settings={settings}
            setSettings={setSettings}
            close={() => setSettingsOpen(false)}
          />
        </>
      )}
      {session.state !== "listening" && (
        <LanguageGate
          session={session}
          error={languageError}
          onSelect={selectLanguage}
        />
      )}
    </main>
  );
}
