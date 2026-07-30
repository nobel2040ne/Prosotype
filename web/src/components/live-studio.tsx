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
  characterMotionStepMs,
  naturalMotionDurationMs,
} from "@/lib/motion-timing";
import {planStageLayout, rowBudgetEm} from "@/lib/stage-layout";
import {
  deliveryExpressiveness,
  expandAroundCenter,
  expandPitch,
} from "@/lib/voice-sensitivity";

type CSSVars = CSSProperties & Record<`--${string}`, string | number>;
type ViewMode = "stage" | "transcript";
type MotionFamily =
  | "steady"
  | "rising"
  | "falling"
  | "sustained"
  | "forceful"
  | "gentle"
  | "textured";

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

const MOTION_FAMILY_GAINS: Record<
  MotionFamily,
  {scale: number; lift: number; weight: number; width: number}
> = {
  steady: {scale: 1, lift: 1, weight: 1, width: 1},
  rising: {scale: 1.12, lift: 1.16, weight: 1.04, width: 1.08},
  falling: {scale: 1.12, lift: 1.16, weight: 1.04, width: 1.08},
  sustained: {scale: 1.07, lift: 1.10, weight: 1.08, width: 1.12},
  forceful: {scale: 1.20, lift: 1.24, weight: 1.18, width: 1.16},
  gentle: {scale: 1, lift: 1, weight: 0.64, width: 0.72},
  textured: {scale: 1.08, lift: 1.05, weight: 0.86, width: 1.24},
};

function motionFamilyForDelivery({
  profile,
  enabled,
  contour,
  flow,
  force,
  attack,
  texture,
}: {
  profile: string;
  enabled: boolean;
  contour: number;
  flow: number;
  force: number;
  attack: number;
  texture: number;
}): MotionFamily {
  const named = profile as MotionFamily;
  if (
    named !== "steady" &&
    Object.hasOwn(MOTION_FAMILY_GAINS, named)
  ) return named;
  if (!enabled) return "steady";

  // The semantic delivery profile deliberately has a high evidence threshold.
  // Motion variety is a separate, lower-stakes presentation decision: a
  // trustworthy continuous acoustic dimension may choose a timing family
  // without relabelling the word as an emotion or strong delivery category.
  if (Math.abs(contour) >= 0.26) return contour > 0 ? "rising" : "falling";
  if (flow >= 0.76) return "sustained";
  if (force >= 0.38 && attack >= 0.55) return "forceful";
  if (texture >= 0.70) return "textured";
  if (force <= 0.16 && attack <= 0.24 && texture >= 0.42) return "gentle";
  return "steady";
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
  isFrontier,
  state,
  color,
  pitchBaseline,
  intensity,
  runtime,
  onMotionPaint,
  onMotionComplete,
}: {
  id: string;
  word: CaptionWord;
  motionSnapshot: MotionSnapshot | undefined;
  isFrontier: boolean;
  state: RevealState;
  color: string;
  pitchBaseline: number;
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
  const force = deliveryEnabled
    ? clamp(number(motionWord.delivery_force, loudness), 0, 1)
    : loudness;
  const attack = deliveryEnabled
    ? clamp(number(motionWord.delivery_attack), 0, 1)
    : 0;
  const contour = deliveryEnabled
    ? clamp(number(motionWord.delivery_contour), -1, 1)
    : 0;
  const flow = deliveryEnabled
    ? clamp(number(motionWord.delivery_flow), 0, 1)
    : 0;
  const texture = deliveryEnabled
    ? clamp(number(motionWord.delivery_texture), 0, 1)
    : 0;
  const deliveryProfile = deliveryEnabled
    ? String(motionWord.delivery_profile ?? "steady")
    : "steady";
  // NO GATE in the amplitude path. This used to be a lookup on the discrete
  // `delivery_profile`, where `steady` -- 78% of words, measured -- kept only
  // 30% of its excursion, so a word just under the classifier's cut-off was
  // attenuated exactly as hard as a flat one. The magnitude is now continuous in
  // the measured acoustics, so a small change in the voice produces a small but
  // real change on screen instead of nothing. `delivery_profile` still selects
  // the motion family below; it no longer decides how much voice gets through.
  const profileGain = deliveryExpressiveness(
    {force, attack, contour, flow, texture},
    runtime.deliveryExpressivenessFloor,
    runtime.voiceSensitivityGamma,
  );
  const motionFamily = motionFamilyForDelivery({
    profile: deliveryProfile,
    enabled: deliveryEnabled,
    contour,
    flow,
    force,
    attack,
    texture,
  });
  const familyGain = MOTION_FAMILY_GAINS[motionFamily];
  const expressiveIntensity = intensity * profileGain;
  const axisIntensity = intensity * Math.max(
    profileGain,
    deliveryEnabled ? runtime.deliveryAxisGainFloor : 0.30,
  );
  const rawPitch = number(motionWord.pitch_hz, pitchBaseline) || pitchBaseline;
  // Expand each axis around the speaker's own centre before mapping it. Real
  // speech occupies a narrow band around the median, and a linear map spent
  // almost none of the visual range on it -- small voice changes were measured
  // and then discarded in presentation. Endpoints stay pinned, so the reachable
  // extremes are unchanged and this cannot fabricate whispers or shouts.
  const gamma = runtime.voiceSensitivityGamma;
  const pitch = expandPitch(rawPitch, pitchBaseline, gamma);
  // SCALE expands only ABOVE the median. Scale may never fall below the constant
  // 10% sync pop, so `max(sync, …)` already flattens sub-median words; expanding
  // downward as well pushed MORE of them onto that same floor and removed the
  // gradient that exists today (measured 2.26% -> 0.02% between loudness 0.30
  // and 0.45). Above the median there is real headroom, and the spread over a
  // 0.45->0.55 swing goes from 3.19% to 7.65%.
  const scaleLoudness = loudness > 0.5
    ? expandAroundCenter(loudness, 0.5, gamma)
    : loudness;
  // LIFT has headroom in BOTH directions and is therefore the only channel that
  // can express "quieter than the median" at all. It gets the full symmetric
  // expansion, which is what makes a small drop in the voice visible (measured
  // 0.9 -> 16.4 milli-em between loudness 0.30 and 0.45).
  const liftLoudness = expandAroundCenter(loudness, 0.5, gamma);
  // CWI 2.3.9: weight is inverted pitch over an 80..250 Hz domain. The RENDERED
  // band is config (`live_sync.weight_range`), because the old hardcoded 180..700
  // was the main reason the weight channel barely showed: measured, it produced a
  // median deviation of only 102 units from Regular 400, and 400->500 on Roboto
  // Flex is Regular->Medium. The word still lands on exactly 400 at rest.
  const [weightFloor, weightCeiling] = runtime.weightRange;
  const activeWeight = clamp(
    weightFloor +
      ((250 - clamp(pitch, 80, 250)) / 170) * (weightCeiling - weightFloor),
    weightFloor,
    weightCeiling,
  );
  const activeWidth = clamp(
    88 + ((190 - clamp(pitch, 80, 250)) / 110) * 18,
    85,
    115,
  );
  const rawScale = clamp(0.78 + scaleLoudness * 0.58, 0.82, 1.34);
  // Synchronization is the always-legible CWI timing cue. The delivery
  // profile gain affects only the voice-shaped deviation, not this base cue.
  const intonationScale = 1 + (rawScale - 1) * axisIntensity;
  const synchronizationScale = 1 + runtime.syncPop * intensity;
  const baseActiveScale = clamp(
    Math.max(
      synchronizationScale,
      intonationScale * synchronizationScale,
    ),
    0.82,
    1.36,
  );
  const activeScale = clamp(
    1 + (baseActiveScale - 1) * familyGain.scale,
    synchronizationScale,
    1.38,
  );
  // Deviation magnitude from the symmetric channel, so a word BELOW the median
  // lifts differently from one above it rather than both collapsing to the pop.
  const liftIntonation = 1
    + (clamp(0.78 + liftLoudness * 0.58, 0.82, 1.34) - 1) * axisIntensity;
  const activeLift = Math.max(
    runtime.syncElevationEm * intensity,
    (
      runtime.syncElevationEm
        + Math.abs(liftIntonation - 1)
          * runtime.deliveryIntonationLiftGain
          * familyGain.lift
    ) * intensity,
  );
  const duration = motionSnapshot?.durationMs ??
    naturalMotionDurationMs(motionWord, runtime);
  const characters = Array.from(String(word.text ?? ""));
  const characterStep = characterMotionStepMs(duration, characters.length);
  const forceLift = force * runtime.deliveryForceLiftEm * expressiveIntensity;
  const contourLift = contour * runtime.deliveryContourLiftEm * expressiveIntensity;
  const flowHold = flow * runtime.deliveryFlowHoldEm * expressiveIntensity;
  const releaseLift = clamp(
    activeLift * 0.52 + forceLift + contourLift + flowHold,
    0,
    activeLift + runtime.deliveryContourLiftEm + runtime.deliveryFlowHoldEm,
  );
  const style: CSSVars = {
    "--speaker-color": color,
    // `weightGain` lifts the weight channel ALONE. It multiplies only the
    // deviation from 400, so a word with no measured pitch deviation still
    // renders Regular and the rest still land back on exactly 400 -- this
    // changes how far the transient travels, not where it ends.
    "--active-weight": String(Math.round(clamp(
      400 + (activeWeight - 400) *
        axisIntensity * familyGain.weight * runtime.weightGain,
      weightFloor,
      weightCeiling,
    ))),
    "--active-width": `${
      Math.round(clamp(
        100 + (activeWidth - 100) * axisIntensity * familyGain.width,
        85,
        115,
      ))
    }%`,
    "--active-scale": activeScale.toFixed(3),
    "--active-lift": `${activeLift.toFixed(3)}em`,
    "--delivery-start-drop": `${
      (attack * runtime.deliveryAttackDropEm * expressiveIntensity).toFixed(3)
    }em`,
    "--delivery-release-lift": `${releaseLift.toFixed(3)}em`,
    "--delivery-hold-scale": (
      1 + (activeScale - 1) * (0.28 + flow * 0.48)
    ).toFixed(3),
    "--delivery-glow": `${
      (texture * runtime.deliveryTextureGlowPx * expressiveIntensity).toFixed(1)
    }px`,
    "--delivery-resonance-opacity": (
      texture * (0.14 + force * 0.30) * expressiveIntensity
    ).toFixed(3),
    "--character-lift": `${
      (runtime.characterWaveLiftEm * intensity).toFixed(3)
    }em`,
    "--character-scale": (
      1 + runtime.characterWavePop * intensity
    ).toFixed(3),
    "--motion-duration": `${duration.toFixed(0)}ms`,
    "--motion-phase-delay": "0ms",
    "--character-step": `${characterStep.toFixed(2)}ms`,
  };
  const status = speakerStatus(word);
  const initialCharacterCount = Array.from(
    String(motionWord.text ?? ""),
  ).length;

  useLayoutEffect(() => {
    const element = wordRef.current;
    if (!element) return;
    element.style.width = "";
    // Freeze the box at its resting layout width so the inner glyph's weight and
    // width axes cannot reflow the row. offsetWidth/getBoundingClientRect on the
    // WRAPPER report layout width, which a descendant's transform never touches.
    //
    // FREEZE IT IN em, NOT px. The stage font-size is
    // `clamp(20px, 4.6vh, 50px) * --caption-scale`, so a pixel box goes stale the
    // moment the window is resized or the Caption scale slider moves: the glyphs
    // re-render at the new size while the box keeps the old one. Measured at
    // scale 1.8, every word spilled its box (15px on "a", 43px on "tab") and the
    // words overlapped each other. Glyph advances are linear in font-size and the
    // word inherits the feed's size at 1em, so an em width tracks them exactly
    // and never needs re-measuring. (A change of FACE -- not size -- would still
    // need one, but the caption font is locked before the first word arrives.)
    const fontSize = parseFloat(getComputedStyle(element).fontSize) || 1;
    // Fractional, then a hair of slack: offsetWidth rounds down, which clipped
    // the last letter of every word the last time this was measured in integers.
    const restingWidth = element.getBoundingClientRect().width;
    element.style.width = `${(restingWidth / fontSize + 0.01).toFixed(4)}em`;
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
      data-motion={motionFamily}
      data-word-id={id}
      style={style}
      ref={wordRef}
      title={`${deliveryProfile} delivery · ${Math.round(pitch)} Hz · ${
        number(word.loudness_db, -72).toFixed(1)
      } dB`}
    >
      <span
        className="word-glyph"
        aria-label={word.text}
        onAnimationEnd={handleAnimationEnd}
      >
        <span className="word-ink">
          {characters.map((char, index) => (
            <span
              className="caption-character"
              aria-hidden="true"
              data-revision-added={
                state === "active" &&
                !isFrontier &&
                index >= initialCharacterCount
                  ? "true"
                  : "false"
              }
              key={index}
              style={{"--char-index": index} as CSSVars}
            >
              {char}
            </span>
          ))}
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
  palette,
  level,
  pitchBaseline,
  intensity,
  runtime,
  motionSnapshots,
  frontierId,
  confirmMotionPaint,
  completeMotion,
  transcript,
  reducedMotion,
}: {
  paragraphs: CaptionParagraph[];
  palette: string[];
  level: LevelEvent;
  pitchBaseline: number;
  intensity: number;
  runtime: RuntimeConfig;
  motionSnapshots: Record<string, MotionSnapshot>;
  frontierId: string | null;
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
                    isFrontier={id === frontierId}
                    state={reveal}
                    color={speakerColor(
                      word.speaker ?? null,
                      speakerStatus(word),
                      palette,
                    )}
                    pitchBaseline={pitchBaseline}
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
          max="1.35"
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
    pitchBaseline,
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
            pitchBaseline={pitchBaseline}
            intensity={settings.motionIntensity}
            runtime={runtime}
            motionSnapshots={motionSnapshots}
            frontierId={model.order.at(-1) ?? null}
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
