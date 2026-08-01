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
  type CSSProperties,
} from "react";
import {
  useCaptionStream,
  type LanguageSession,
  type LiveLanguageOption,
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
  characterVoiceTypes,
  type CaptionType,
  type VoiceTypeRanges,
} from "@/lib/caption-motion";
import {acousticTimeMs, naturalMotionDurationMs} from "@/lib/motion-timing";
import {baselineOffsetEm, formatBaselineEm} from "@/lib/glyph-metrics";
import {assignSpeakerColors} from "@/lib/speaker-colors";
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

/**
 * CWI 2.1, via `assignSpeakerColors` -- see that module for why this is wheel
 * geometry and not a lookup.
 *
 * This used to be `palette[hash(speakerId) % palette.length]`, which could hand
 * speakers 1 and 2 adjacent hues -- exactly the confusion 2.1.3 devotes a page
 * of do/don't wheels to preventing.
 *
 * Both fallbacks stay CSS variables rather than literals: they have to follow
 * the stage theme, and every consumer writes the result straight into a custom
 * property, so the indirection resolves for free.
 */
function speakerColor(
  speaker: string | null,
  status: string,
  colors: SpeakerColorMap,
): string {
  if (!speaker || status === "unknown") return "var(--caption-unknown)";
  return colors.get(speaker)?.color ?? "var(--accent)";
}

type SpeakerColorMap = ReturnType<typeof assignSpeakerColors>;

/**
 * Resolve the assignment once per roster, then swap in the themed palette by
 * INDEX so the light stage shows the same speaker in the same slot.
 */
function useSpeakerColors(
  paragraphs: CaptionParagraph[],
  runtime: RuntimeConfig,
  lightStage: boolean,
): SpeakerColorMap {
  return useMemo(() => {
    // Order of FIRST APPEARANCE, which is what config.yaml has always claimed.
    const order: string[] = [];
    const seen = new Set<string>();
    for (const paragraph of paragraphs) {
      for (const {word} of paragraph.words) {
        const speaker = word.speaker;
        if (!speaker || seen.has(speaker)) continue;
        seen.add(speaker);
        order.push(speaker);
      }
    }
    const mains = runtime.palette.length - runtime.paletteSupportCount;
    const assigned = assignSpeakerColors(order, {
      main: runtime.palette.slice(0, mains),
      support: runtime.palette.slice(mains),
    });
    if (!lightStage || !runtime.paletteLight.length) return assigned;
    const themed: SpeakerColorMap = new Map();
    for (const [speaker, entry] of assigned) {
      themed.set(speaker, {
        ...entry,
        color: entry.index >= 0
          ? runtime.paletteLight[entry.index] ?? entry.color
          : entry.color,
      });
    }
    return themed;
  }, [paragraphs, runtime, lightStage]);
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
  color,
  intensity,
  runtime,
  clockEpoch,
  scheduleWord,
}: {
  id: string;
  word: CaptionWord;
  color: string;
  intensity: number;
  runtime: RuntimeConfig;
  clockEpoch: number | null;
  scheduleWord: (
    id: string,
    word: CaptionWord,
    durationMs: number,
  ) => {turnAtMs: number; epoch: number} | null;
}) {
  const wordRef = useRef<HTMLSpanElement>(null);
  const armedRef = useRef<{turnAtMs: number; epoch: number} | null>(null);
  const motionWord = word;
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
  );

  /*
   * CWI 2.3 IS PER CHARACTER (PDF p.34 / p.38 / p.40), so the word is split and
   * each letter reads the word's own intonation contour at its own position.
   * `Array.from` rather than `split("")`: a Hangul syllable block or any
   * astral-plane character must stay one unit, and Korean is a shipped language.
   */
  const characters = Array.from(word.text);
  const characterTypes: CaptionType[] = characterVoiceTypes(
    characters.length,
    motionWord.env_loudness && motionWord.env_pitch && motionWord.env_texture
      ? {
          loudness: motionWord.env_loudness,
          pitch: motionWord.env_pitch,
          texture: motionWord.env_texture,
        }
      : null,
    {loudness, pitchHz: pitch, texture},
    voiceRanges(runtime),
    intensity,
  );

  // One span per character, keyed by INDEX so a verifier respelling reuses the
  // existing spans instead of remounting the word and restarting its motion.
  const renderCharacters = (crest: boolean) =>
    characters.map((character, index) => (
      <span
        className={crest ? "character-sizer" : "caption-character"}
        key={index}
        style={{
          "--char-scale": (characterTypes[index]?.scale ?? 1).toFixed(3),
          "--char-weight": String(characterTypes[index]?.weight ?? 400),
          "--char-width": `${characterTypes[index]?.width ?? 100}%`,
        } as CSSVars}
      >
        {character === " " ? "\u00a0" : character}
      </span>
    ));

  /* Frozen at mount: a verifier respelling can revise `end`, and a caption
     already in flight must not have its clock reshaped underneath it. */
  const [duration] = useState(
    () => naturalMotionDurationMs(motionWord, runtime),
  );
  const style: CSSVars = {
    "--speaker-color": color,
    // 2.2.3 is constant; the Expression control changes §2.3, not this cue.
    "--sync-pop": motion.sync.scale.toFixed(3),
    "--motion-duration": `${duration.toFixed(0)}ms`,
  };
  const status = speakerStatus(word);

  /*
   * ARM THE WORD ONCE, THEN LEAVE IT ALONE.
   *
   * `--turn-delay` is the `animation-delay` for all three caption animations:
   * the 2.2.2 colour turn, the 2.2.3 pop and the 2.3 voice crest. Writing it
   * imperatively -- never through the `style` prop -- is deliberate: React
   * reapplies that prop on every render, and rewriting `animation-delay`
   * shifts a running animation, so a verifier respelling would visibly yank a
   * word that was already mid-pop.
   *
   * `data-armed` lives on the DOM node rather than in a ref, so the two cases
   * that must behave differently actually do:
   *   - a re-render (new text, new colour, new speaker) finds the flag set and
   *     touches nothing, so the motion continues undisturbed;
   *   - a genuine remount arrives with a fresh node and no flag, re-derives the
   *     delay against the new animation origin, and resumes at the same wall
   *     moment rather than replaying from the start.
   *
   * The turn moment itself is frozen in `armedRef` on first arm. Because it is
   * computed as `onset - clockOffset + delay` -- with no reference to "now" --
   * even a remount that has to recompute it lands on the same answer.
   *
   * Until this runs, the stylesheet's own large positive default holds the word
   * in read-ahead type. Because this is a LAYOUT effect in the same commit that
   * first paints the word, a word can never flash coloured on arrival.
   */
  useLayoutEffect(() => {
    const element = wordRef.current;
    if (!element) return;
    if (armedRef.current === null) {
      // No acoustic clock yet. `clockEpoch` brings us back when there is one.
      const armed = scheduleWord(id, word, duration);
      if (armed === null) return;
      armedRef.current = armed;
    }
    /*
     * A capture restart (a looping sample, a restarted server) invalidates the
     * timeline this word was placed on. It was spoken -- on the previous pass
     * -- so it settles. Re-deriving its onset against the new clock would put
     * it in the FUTURE and turn a whole stage of already-read captions back to
     * read-ahead white, which is what `--sample --loop` used to do.
     */
    if (clockEpoch !== null && armedRef.current.epoch !== clockEpoch) {
      element.dataset.armed = "stale";
      element.style.setProperty("--turn-delay", "-600000ms");
      return;
    }
    if (element.dataset.armed === "true") return;
    element.dataset.armed = "true";
    element.style.setProperty(
      "--turn-delay",
      `${Math.round(armedRef.current.turnAtMs - performance.now())}ms`,
    );
  }, [clockEpoch, duration, id, scheduleWord, word]);

  return (
    <span
      className="caption-word"
      data-status={status}
      data-final={word.final ? "true" : "false"}
      data-sustain={word.sustain_active ? "true" : "false"}
      data-delivery={deliveryProfile}
      // CWI 2.1.5: an off-camera voice keeps its speaker colour and is set in
      // italic. Live capture has no camera and never sets this; it is here so
      // the SSE contract can carry the distinction rather than inventing it.
      data-off-camera={word.off_camera ? "true" : "false"}
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
        {renderCharacters(true)}
      </span>
      <span className="word-glyph" aria-label={word.text}>
        <span className="word-ink" aria-hidden="true">
          {renderCharacters(false)}
        </span>
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
  speakerColors,
  level,
  intensity,
  runtime,
  clockEpoch,
  scheduleWord,
  playheadMs,
  transcript,
  reducedMotion,
}: {
  paragraphs: CaptionParagraph[];
  speakerColors: SpeakerColorMap;
  level: LevelEvent;
  intensity: number;
  runtime: RuntimeConfig;
  clockEpoch: number | null;
  scheduleWord: (
    id: string,
    word: CaptionWord,
    durationMs: number,
  ) => {turnAtMs: number; epoch: number} | null;
  playheadMs: number;
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

  /*
   * WHERE SPEECH ACTUALLY IS, which is no longer the bottom of the stack.
   *
   * With read-ahead the last row holds words nobody has said yet, so pinning
   * the voice orb to it would park the live instrument next to white text. The
   * orb belongs on the row the playhead is inside. This changes only when the
   * playhead crosses a row boundary, so the coarse playhead tick is plenty --
   * and because the words themselves take no playhead prop, their memoisation
   * is untouched by it.
   */
  const spokenRow = Math.max(
    0,
    paragraphs.findLastIndex((paragraph) => paragraph.words.some(
      ({word}) => acousticTimeMs(word) <= playheadMs,
    )),
  );

  // The feed container is rendered even while empty: it is the element the stage
  // measures to decide how many rows fit (`useStackCapacity`), and that answer is
  // needed BEFORE the first word arrives. The empty state is a sibling.
  return (
    <div className={transcript ? "transcript-feed" : "caption-feed"}>
      {paragraphs.map((paragraph, paragraphIndex) => {
        const color = speakerColor(paragraph.speaker, paragraph.status, speakerColors);
        const isLatest = paragraphIndex === spokenRow;
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
                {paragraph.words.map(({id, word}) => (
                  <MotionWord
                    id={id}
                    word={word}
                    clockEpoch={clockEpoch}
                    scheduleWord={scheduleWord}
                    color={speakerColor(
                      word.speaker ?? null,
                      speakerStatus(word),
                      speakerColors,
                    )}
                    intensity={intensity}
                    runtime={runtime}
                    key={id}
                  />
                ))}
                {paragraphIndex === spokenRow && !transcript && (
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
/**
 * Find the baseline inside a caption word's box, so the cue can grow FROM it.
 *
 * CWI never moves a word's baseline (see `glyph-metrics.ts` for the evidence in
 * `docs/reference/`), but `transform-origin: 50% 100%` is the bottom of the line
 * box, a descender plus half-leading below the baseline. Scaling about that
 * point lifts the word — further the louder it is, because the scale carries the
 * voice — which is the hop the design system does not have.
 *
 * Measured rather than tabulated because the offset depends on the face's own
 * ascent/descent AND on the line-height: Roboto Flex and Noto Sans KR give
 * different answers, and a hardcoded number would silently be wrong for Korean.
 *
 * Cheap: one probe, once per face. The caption font is locked before the first
 * word arrives, so there is nothing to keep re-measuring.
 */
function useGlyphBaseline(language: string | null): string | null {
  const [offset, setOffset] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      // The probe has to carry the REAL caption typography, so it borrows the
      // live class names rather than restating font-family/line-height here.
      const host = document.createElement("div");
      host.className = "caption-feed";
      host.setAttribute("aria-hidden", "true");
      host.style.cssText =
        "position:absolute;left:-9999px;top:0;visibility:hidden;" +
        "contain:strict;width:400px;height:200px;";
      // `.caption-words` is not optional scaffolding: it carries the caption
      // line-height, and the baseline's distance from the box bottom is
      // half-leading PLUS descent. Measuring without it returned an identical
      // 0.2500em for Roboto Flex and Noto Sans KR -- the giveaway that the
      // probe was reading `line-height: normal` rather than the real 1.38, and
      // leaving the pivot ~0.1em below the true baseline.
      const row = document.createElement("div");
      row.className = "caption-words";
      const word = document.createElement("span");
      word.className = "caption-word";
      const glyph = document.createElement("span");
      glyph.className = "word-glyph";
      // `position:absolute` on the real glyph would detach it from this probe's
      // flow; static keeps the same line box, which is what carries the metric.
      glyph.style.position = "static";
      glyph.textContent = "Hxg";
      // A zero-width inline-block sits with its bottom margin edge ON the
      // baseline. It is the only way to reach the baseline from JavaScript.
      const strut = document.createElement("i");
      strut.style.cssText = "display:inline-block;width:0;height:0;";
      glyph.appendChild(strut);
      word.appendChild(glyph);
      row.appendChild(word);
      host.appendChild(row);
      // MOUNT IT INSIDE THE SHELL. `--font-caption` is switched by
      // `.studio-shell[data-language="ko"]`, so a probe parented to
      // `document.body` silently measures Roboto Flex even in a Korean
      // session -- which is exactly how this returned an identical number for
      // both faces twice before.
      const shell = document.querySelector(".studio-shell") ?? document.body;
      shell.appendChild(host);
      const fontSize = parseFloat(getComputedStyle(glyph).fontSize);
      const measured = baselineOffsetEm(
        glyph.getBoundingClientRect(),
        strut.getBoundingClientRect(),
        fontSize,
      );
      host.remove();
      if (measured === null) return;
      const next = formatBaselineEm(measured);
      setOffset((current) => (current === next ? current : next));
    };
    // The caption faces are local @font-face downloads. Measuring before they
    // load returns the fallback face's metrics, which is a different number.
    document.fonts.ready.then(measure).catch(measure);
    return () => {
      cancelled = true;
    };
  }, [language]);
  return offset;
}

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
    rowBudgetEm: rowBudgetEm(runtime.stageWordsPerBlock, 1.45, 6.60),
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
        parseFloat(styles.getPropertyValue("--word-em-linear")) || 1.45,
        parseFloat(styles.getPropertyValue("--word-em-spread")) || 6.60,
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
    scheduleWord,
    clockEpoch,
    playheadMs,
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
      runtime.paragraphWordLimit,
    ),
    [model.words, model.order, runtime.paragraphWordLimit],
  );
  const glyphBaselineEm = useGlyphBaseline(session.language);
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
  // CWI 2.1 assignment (wheel geometry, first-appearance order). The CI palette
  // is built for the black captions box and measures as low as 1.19:1 on the
  // light stage, so the light theme substitutes `palette_light` by INDEX --
  // same hues, darkened to >=4.5:1, same speaker in the same slot. Both arrive
  // from config.yaml via /runtime-config.json; neither is hardcoded here.
  const speakerColors = useSpeakerColors(
    paragraphs,
    runtime,
    settings.lightStage,
  );
  const fallbackColor = (settings.lightStage && runtime.paletteLight.length
    ? runtime.paletteLight
    : runtime.palette)[0];
  const activeColor = currentParagraph
    ? speakerColor(currentParagraph.speaker, currentParagraph.status, speakerColors)
    : fallbackColor;
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
    // CWI 2.2.1: read-ahead is full white at 90% opacity -- which the PDF
    // specifies against 2.4.1's 90%-black box. The light stage has no box, and
    // white measures 1.05:1 on it, so it takes the same-semantic legible value
    // the way palette_light does. Both arrive from config.yaml.
    "--read-ahead-color": settings.lightStage
      ? runtime.readAheadColorLight
      : runtime.readAheadColor,
    "--read-ahead-opacity": runtime.readAheadOpacity,
    "--color-turn-ms": `${runtime.colorTurnMs}ms`,
    // CWI grows a word from its BASELINE and never moves it. This is where that
    // baseline actually is inside the glyph's line box, measured off the live
    // caption face; the CSS fallback covers the frame before it resolves.
    ...(glyphBaselineEm ? {"--glyph-baseline-em": glyphBaselineEm} : {}),
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
            /* CWI 2.4.4 and 2.4.5. A sound effect is white, inside brackets,
               and otherwise obeys the caption system: its type grows and pops
               with the loudness of the sound it describes. Music is the
               documented exception -- it is wrapped in the ♫ symbol on either
               side and, per 2.4.5, "they don't need to be animated and don't
               change color", so its scale is pinned at 1. */
            <div
              className="sound-caption"
              data-category={model.sound.category ?? "environmental"}
              style={{
                "--sound-level": clamp(
                  (number(level.rms_db, -72) + 52) / 34,
                  0,
                  1,
                ).toFixed(3),
              } as CSSVars}
            >
              {model.sound.category === "music" ? "♫ " : null}
              [{model.sound.label ?? model.sound.category ?? "sound"}]
              {model.sound.category === "music" ? " ♫" : null}
            </div>
          )}
          <CaptionFeed
            paragraphs={stageParagraphs}
            speakerColors={speakerColors}
            level={level}
            intensity={settings.motionIntensity}
            runtime={runtime}
            clockEpoch={clockEpoch}
            scheduleWord={scheduleWord}
            playheadMs={playheadMs}
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
              const color = speakerColor(speaker, status, speakerColors);
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
