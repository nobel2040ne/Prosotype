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
  createStageMemory,
  type StageMemory,
  type CaptionStackPosition,
} from "@/lib/caption-paragraphs";
import type {CaptionWord, LevelEvent} from "@/lib/caption-store";
import {
  captionMotionFor,
  characterVoiceTypes,
  emphasisOf,
  voiceDeviationOf,
  type CaptionType,
  type VoiceTypeRanges,
} from "@/lib/caption-motion";
import {
  acousticTimeMs,
  charTurnDelayMs,
  crestDurationMs,
  crestWindowMs,
  HOLD_ENVELOPE_EMPHASIS,
  naturalMotionDurationMs,
} from "@/lib/motion-timing";
import {baselineOffsetEm, formatBaselineEm} from "@/lib/glyph-metrics";
import {
  assignSpeakerColors,
  speakerColor,
  speakerStatus,
  type SpeakerColorMap,
} from "@/lib/speaker-colors";
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
    scaleResponseQuiet: runtime.voiceScaleResponseQuiet,
    scaleDeadband: runtime.voiceScaleDeadband,
    weight: runtime.weightRange,
    weightEmphasis: runtime.weightEmphasis,
    width: runtime.widthRange,
  };
}

function speakerNumber(speaker: string | null): string {
  if (!speaker) return "—";
  const match = speaker.match(/\d+/);
  return String(match ? Number(match[0]) : 1).padStart(2, "0");
}

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

/* The character spans of a word that have never been given a turn moment.
   They are exactly the ones the stylesheet is still holding at its 600s
   default, i.e. painting in read-ahead ink; a span that already carries a
   delay is running and must not be touched. */
function unarmedCharacters(element: HTMLElement): HTMLElement[] {
  return Array.from(
    element.querySelectorAll<HTMLElement>(".caption-character, .character-sizer"),
  ).filter((span) => !span.style.getPropertyValue("--char-turn-delay"));
}

const MotionWord = memo(function MotionWord({
  id,
  word,
  color,
  intensity,
  runtime,
  holdGapS,
  holdSettled,
  paceGapS,
  clockEpoch,
  scheduleWord,
}: {
  id: string;
  word: CaptionWord;
  color: string;
  intensity: number;
  runtime: RuntimeConfig;
  /** Silence before this word, in seconds -- how long it had to wait. */
  holdGapS: number;
  /* Whether `holdGapS` is FINAL -- the parent has seen this word's next
     neighbour. Until then the gap is half a neighbourhood and must not be
     frozen; see the hold block below. */
  holdSettled: boolean;
  /** Onset-to-onset interval to the NEXT word: one word at this speech rate. */
  paceGapS: number;
  clockEpoch: number | null;
  scheduleWord: (
    id: string,
    word: CaptionWord,
    durationMs: number,
  ) => {turnAtMs: number; epoch: number} | null;
}) {
  const wordRef = useRef<HTMLSpanElement>(null);
  const armedRef = useRef<{turnAtMs: number; epoch: number} | null>(null);
  // How many letters the colour wipe was laid out across when this word armed.
  const charSpanRef = useRef<number | null>(null);
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
  /* The SPEAKER's running median F0. 2.3.7's weight ladder describes a voice,
     so the register half reads this and a word's own excursion above it is
     treated as effort rather than as a lighter voice. */
  const register = number(motionWord.pitch_register_hz, 0);
  const motion = captionMotionFor(
    {loudness, pitchHz: pitch, texture, registerHz: register},
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
  /*
   * The envelope no longer sets each character's TYPE -- 2.3 is per word (see
   * below). It sets how hard each character STRETCHES, so the wave still rides
   * the audio the way the reference's does.
   */
  /*
   * How far this WORD's volume departs from normal, 0..1 -- normalised against
   * whichever side of `voice_scale_range` it is on, so a whisper and a shout
   * both read as 1.
   */
  /*
   * Measured against the REACHABLE size band, not the configured clamp. The
   * quiet side never reaches `voice_scale_range[0]` -- `scaleResponseQuiet`
   * caps it at 0.78 against a configured 0.72 -- so dividing by the clamp put
   * the most hushed word in the film at 0.786 instead of 1, and left a fifth
   * of the wave running on "softer.". See `reachableScaleRange`.
   */
  const voiceDeviation = voiceDeviationOf(
    motion.voice.scale,
    voiceRanges(runtime),
  );
  const waveSuppression = Math.max(
    runtime.characterWaveFloor,
    1 - voiceDeviation * runtime.characterWaveFalloff,
  );

  const characterTypes: CaptionType[] = characterVoiceTypes(
    characters.length,
    motionWord.env_loudness && motionWord.env_pitch && motionWord.env_texture
      ? {
          loudness: motionWord.env_loudness,
          pitch: motionWord.env_pitch,
          texture: motionWord.env_texture,
        }
      : null,
    {loudness, pitchHz: pitch, texture, registerHz: register},
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
        data-char-index={index}
        style={crest ? {"--char-index": index} as CSSVars : {
          // Where this letter sits in the wave, and how hard it stretches.
          "--char-index": index,
          /*
           * THE TWO SCOPES TRADE OFF. Amplitude is this letter's departure
           * from its own WORD's size -- so the wave describes variation
           * INSIDE the word -- scaled down by how far the whole word's volume
           * has departed from normal. A loud or hushed word therefore moves as
           * a word with its letters held together ("louder" is six glyphs at
           * one size), while an ordinary-volume word lets the wave carry it
           * ("animation," scatters hard).
           */
          "--char-wave": (waveSuppression * clamp(
            0.85 + ((characterTypes[index]?.scale ?? 1) - motion.voice.scale) * 1.6,
            0.45,
            1.30,
          )).toFixed(3),
        } as CSSVars}
      >
        {character === " " ? "\u00a0" : character}
      </span>
    ));

  /* Frozen at mount: a verifier respelling can revise `end`, and a caption
     already in flight must not have its clock reshaped underneath it. The
     wipe's sweep and the crest window freeze on the same terms — the arm
     effect and the crest animation must agree on ONE number, and a running
     crest must not be re-timed by a retiming revision. As state, the style
     prop rewrites them with identical strings on every render, so no running
     animation is ever reshaped. */
  /* How much of the hold choreography this word earns, 0..1: the gap of
     silence in front of it, ramped between `holdMinS` and `holdFullS`. Drives
     both the lift and the spring's amplitude, so a word nobody waited for runs
     the animation as a flat identity. */
  /* AND A WORD THAT SWELLS DOES NOT LIFT. THE TWO CHANNELS ARE INDEPENDENT.
     This is the reference's own rule, visible in one shot: the film's
     "louder" more than doubles in size and never leaves the baseline, while
     "is" -- the single word it does lift in the first 18s -- is at its
     RESTING size the whole time it is aloft (measured frame by frame: it
     overshoots to 1.31 on the launch, then decays to exactly 1.0 and floats
     there for 0.67s). Size answers "how was this said"; the lift answers "how
     long was it held". Letting a loud word do both coupled them -- measured,
     corr(peak size, lift) was +0.337 with "louder" lifting a full 0.525em --
     and the reference regresses that at +0.043 with its largest word at
     exactly 0.000.
     THE GATE IS BINARY, NOT PROPORTIONAL. A graded withdrawal taxes a word
     for the 2.2.3 pop every word carries: "is" renders 1.23x, of which 1.15
     is that constant cue, so its real crest is 1.07 -- and a proportional
     rule still took 38% of its lift for what is essentially resting size.
     The reference makes one distinction, not a spectrum: a word that is
     genuinely swelling does not leave the line, and everything else may. */
  /* ONE-SIDED: only SWELLING withdraws the lift, not shrinking. `emphasisOf`
     scores distance from normal in EITHER direction, which is right for the
     motion window but wrong here -- a hushed word is not competing with the
     lift for the viewer's attention, it is the opposite. Measured, "is" comes
     in at loudness 0.183 against a 0.211 median, i.e. very slightly QUIET, and
     the two-sided score taxed its lift to 62% of full. The film holds "is" at
     its resting size for the whole float; what it never does is lift a word
     that has grown. */
  const holdEmphasis = motion.voice.scale > 1
    ? emphasisOf(motion.voice.scale, voiceRanges(runtime))
    : 0;
  /* FROZEN AT MOUNT, like the duration and the axes -- and for a sharper
     reason than either. `holdGapS` is recomputed from the whole word list on
     every render, so a later insertion or deletion could move it AFTER the
     word had already been drawn lifted. `--hold-spring` gates the crest and
     the weight (see globals.css), so the instant it dropped to 0 mid-motion a
     held word un-gated and snapped to its full crest: MEASURED, "is" floated
     at weight 400 / 28.3px for 0.42s and then, on landing, jumped to weight
     837 and 39.8px in a single step -- reported as "when it lands, it gets
     black". Recomputing a gate under a running animation is the same class of
     bug as rewriting `animation-delay` under one. */
  /* ...AND THE FREEZE IS AT THE TURN, NOT AT THE MOUNT (2026-08-05).
     Freezing is right -- see above. Freezing on the child's FIRST RENDER was
     not: the gap is `min(before, after)` and `after` needs the NEXT word,
     which has usually not arrived by then, so the parent commits nothing yet
     and a child that freezes immediately captures a pre-neighbourhood value.
     Whether it wins that race depends on render cadence, so any unrelated
     change that alters how often the tree re-renders flips it. MEASURED, the
     film's held word came out 0.525em on one run and 0.000 on the next of the
     SAME build, and the user reported exactly that: "'is' is so important so
     it should not change."
     The rule is the project's own invariant -- revise only while the word is
     still AHEAD of the playhead. So take the parent's answer until the gap is
     settled, and stop at the turn regardless. The neighbourhood settles ~0.3 s
     after a word arrives and the turn is `read_ahead_delay_s` later, so the
     real answer always lands first, with nothing animating.
     MEASURED after: 0.525em on every run, which is `docs/MOTION.md`'s figure. */
  const holdTarget = clamp(
    (holdGapS - runtime.holdMinS) /
      Math.max(1e-6, runtime.holdFullS - runtime.holdMinS),
    0,
    1,
  ) * (holdEmphasis >= HOLD_ENVELOPE_EMPHASIS ? 0 : 1);
  const [holdAmount, setHoldAmount] = useState(holdTarget);
  const holdFrozen = useRef(false);
  useEffect(() => {
    if (holdFrozen.current) return;
    const armed = armedRef.current;
    if (armed && performance.now() >= armed.turnAtMs) {
      holdFrozen.current = true;   // the playhead has passed: history
      return;
    }
    if (!holdSettled) return;
    holdFrozen.current = true;
    setHoldAmount((current) => (current === holdTarget ? current : holdTarget));
  }, [holdSettled, holdTarget]);
  const holdEnvelope = holdEmphasis >= HOLD_ENVELOPE_EMPHASIS;
  const [{duration, sweepMs, crestMs}] = useState(() => {
    /* ONE WORD AT THE CURRENT SPEECH RATE -- the AE template's one-word-wide
       range selector, and nothing about this word's own size. Frozen here with
       everything else, so a verifier respelling can never re-time a running
       crest. `emphasisOf` still feeds the WIPE guard below, which is about how
       far the colour has to travel, not about how long the swell lasts. */
    const push = emphasisOf(motion.voice.scale, voiceRanges(runtime));
    const naturalMs = naturalMotionDurationMs(motionWord, runtime, paceGapS);
    const spokenMs = Math.max(0, number(word.end) - number(word.start)) * 1000;
    // Finish the wipe before the word is done being said, and never let a
    // very long word crawl: the sweep is speech-paced, not decorative.
    const sweep = clamp(spokenMs * 0.72, 0, runtime.wordMotionMaxMs);
    return {
      duration: naturalMs,
      sweepMs: sweep,
      // The crest is the SLOW clock -- emphasis, not speech rate.
      crestMs: crestDurationMs(
        sweep, crestWindowMs(push, runtime), push, runtime.wordMotionMaxMs,
      ),
    };
  });
  const style: CSSVars = {
    "--speaker-color": color,
    // 2.2.3 is constant; the Expression control changes §2.3, not this cue.
    "--sync-pop": motion.sync.scale.toFixed(3),
    "--motion-duration": `${duration.toFixed(0)}ms`,
    // The 2.3 crest takes its own window so its rise tracks the colour wipe
    // instead of leading it (`crestDurationMs`); the pop and wave keep the
    // natural window.
    "--crest-duration": `${crestMs.toFixed(0)}ms`,
    /* Ordinary words pulse; emphatic ones rise, HOLD and fall. The film's
       "louder" sits at full size for ~0.75s of a ~1.25s motion (share ~0.6)
       while the corpus median is 0.40 -- the median is carried by the 37 of 43
       words that barely move, and reading it as one universal shape is what
       flattened the emphatic words. A keyframe's stops cannot take a `var()`,
       but `animation-name` can. */
    "--voice-envelope": holdEnvelope ? "voice-phase-hold" : "voice-phase",
    // CWI 2.3 is a WORD-level property: in intonation.mov every glyph of
    // "louder" is the same size and weight, and every glyph of "softer" is
    // uniformly small. Only the wave below is per character.
    /* A LIFTED WORD IS AT REST. THE EXCLUSION RUNS BOTH WAYS.
       `holdAmount` already refuses to lift a word that SWELLS; this is the
       other direction, and the reference is explicit about it. Stepping the
       film's "is" frame by frame, once the launch overshoot decays the word
       floats at EXACTLY its resting size for 0.67s, and it is never bolder
       than its neighbours — the whole of its motion is the lift and the
       spring. MEASURED here before this, "is" rendered peak 1.41x at weight
       838, so a held word was carrying all three channels at once and read as
       doing too much. Size and weight are withdrawn in proportion to the lift,
       so a partially-held word degrades smoothly rather than switching. */
    "--voice-scale": (1 + (motion.voice.scale - 1) * (1 - holdAmount))
      .toFixed(3),
    "--voice-weight": String(
      Math.round(400 + (motion.voice.weight - 400) * (1 - holdAmount)),
    ),
    "--voice-width": `${motion.voice.width}%`,
    // The wave hands off letter to letter across ~55% of the window, so it
    // travels visibly instead of pulsing the word as one block.
    "--wave-span": `${(duration * 0.72).toFixed(0)}ms`,
    /* A word that waited crouches, springs, floats and lands as it turns.
       Zero for ordinary speech, so nothing moves unless the speaker actually
       held -- and `--hold-spring` gates the squash/stretch on the same wait,
       so the keyframes collapse to an identity for every ordinary word. */
    "--hold-lift": `${(holdAmount * runtime.holdLiftEm).toFixed(3)}em`,
    "--hold-spring": holdAmount.toFixed(3),
    /* BINARY, unlike `--hold-spring`. The spring's amplitude ramps with the
       wait, but the CREST does not get to half-fire: a word that holds at all
       shows no size and no weight, exactly as the reference's "is" floats at
       its resting size throughout. Gating the crest proportionally meant a
       partially-held word ("spoken." at gap 0.82 against a 0.78..0.88 band)
       came out part-bold while aloft -- MEASURED, 11-16 lifted samples bold
       per run. */
    "--hold-gate": holdAmount > 0 ? "1" : "0",
    "--hold-pre": `${runtime.holdPreMs}ms`,
    "--hold-hold": `${runtime.holdHoldMs}ms`,
    "--hold-land": `${runtime.holdLandMs}ms`,
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
      // The crest window is the word's longest-running animation, so it is
      // what `activeMotions` should count.
      const armed = scheduleWord(id, word, Math.max(duration, crestMs));
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
      // A character appended AFTER the restart settles with the word it belongs
      // to. Without this it keeps the stylesheet's 600s default and paints in
      // read-ahead ink beside its own already-coloured word -- see the loop
      // below, which is where that defect actually lived.
      for (const span of unarmedCharacters(element)) {
        span.style.setProperty("--char-turn-delay", "-600000ms");
      }
      return;
    }
    const rearming = element.dataset.armed !== "true";
    element.dataset.armed = "true";
    const turnDelay = armedRef.current.turnAtMs - performance.now();
    // The word's own delay is written ONCE: rewriting `animation-delay` shifts
    // a running animation, which is the hazard `data-armed` exists to prevent.
    if (rearming) {
      element.style.setProperty("--turn-delay", `${Math.round(turnDelay)}ms`);
      // The wipe is laid out across the letters the word had WHEN IT WAS ARMED,
      // and that denominator is then frozen with the sweep. See the loop below.
      charSpanRef.current = Math.max(1, characters.length);
    }
    const perWord = charSpanRef.current ?? Math.max(1, characters.length);

    /*
     * THE COLOUR TURN IS A WIPE THROUGH THE WORD, NOT A SWITCH.
     *
     * `Caption With Intention PR FILM.mp4` shows the boundary INSIDE a word
     * over and over -- "dynamic te|xt" (42.0s), "brings in|" (49.3s),
     * "weigh|ts" (51.35s), "character|s," (60.4s), "instantly kn|ow" (62.1s) --
     * and in "weigh|ts" the SIZE AND WEIGHT sweep in with it: "weigh" is
     * already big and bold while "ts" is still small and grey. So a word does
     * not flip; a boundary crosses it at speech rate. (2.2.4 calls this the
     * exception; in the film it is the norm.)
     *
     * Each character therefore gets its own delay, spread across the word's own
     * spoken span. Written IMPERATIVELY, per character, for the same reason the
     * word's delay is: `animation-delay` counts from when the animation was
     * applied to that element, and live words GROW as a hypothesis extends, so
     * a span appended later would otherwise turn late. Re-deriving each span's
     * delay against the frozen absolute moment keeps the sweep correct through
     * appends and remounts alike.
     *
     * AND THE ARMED WORD MUST STILL ADOPT NEW CHARACTERS (fixed 2026-08-06).
     * The comment above was the intent; the code did not do it. `data-armed`
     * returned early for the WHOLE word, so a span appended after the first arm
     * -- endpoint punctuation ("animation" -> "animation,"), a respelling that
     * lengthens ("godan", "rescue") -- kept the stylesheet's `600000ms` default
     * and sat in the `backwards` fill, i.e. READ-AHEAD INK, for ten minutes.
     * MEASURED on `--sample`: 23 of 137 settled words ended the capture two-
     * coloured, every one of them with an unwritten span, the stray colour
     * `#6e6e73` (`read_ahead.color_light`) against the speaker's hue. Reported
     * as "some words contain the speaker's color and black color", and it is a
     * false claim about who spoke -- the one thing CWI 2.1 exists to prevent.
     * So the word is armed once and each SPAN is armed once: a span that
     * already carries a delay is left strictly alone (rewriting it would shift
     * a running wipe), and only the new ones are written. `turnDelay` is
     * recomputed here against the same frozen absolute moment, which is correct
     * for a span whose animation origin is this commit -- the same reasoning
     * the remount path uses.
     */
    // `perWord` is FROZEN AT THE ARM, not read from the current length:
    // appending to the denominator moves every existing letter's position in
    // the wipe, so a word that grew would hand a late character an EARLIER
    // delay than one already running ("Some" -> "Something": char 3 at .75
    // sweep, new char 4 at .44) and the boundary would visibly travel
    // backwards. Past the frozen length the wipe is over, so the tail turns
    // with its last letter. `sweepMs` freezes at mount alongside the crest
    // window, so the rise and the wipe are computed from the same number.
    for (const span of unarmedCharacters(element)) {
      const index = Number(span.dataset.charIndex ?? 0);
      span.style.setProperty(
        "--char-turn-delay",
        `${charTurnDelayMs(turnDelay, index, perWord, sweepMs)}ms`,
      );
    }
    // `duration` is deliberately absent: like `crestMs` and `sweepMs` it is
    // frozen at mount, and re-running this effect would rewrite
    // `animation-delay` on a RUNNING animation, which shifts it -- the exact
    // hazard `data-armed` exists to prevent.
    // `characters.length` IS load-bearing: it is what brings the effect back
    // when a word grows, and every new span is armed on that pass.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clockEpoch, crestMs, id, scheduleWord, sweepMs, word, characters.length]);

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

/*
 * THE SIDE-GRID INSTRUMENT, AND NOW THE ONLY ONE.
 *
 * There used to be a second, smaller rendering of exactly these channels --
 * `.line-voice-orb`, a sphere parked just past the right edge of whichever row
 * the playhead was inside. Removed 2026-08-04 at the user's request. It was the
 * one live instrument that sat INSIDE the caption surface, and the stage is
 * meant to hold captions and nothing else (the same reasoning that took out the
 * nav rail, the workspace header and the transport bar on 2026-07-30). The
 * compass carries every channel it carried -- volume, F0, brightness,
 * periodicity, the delivery terms -- at a size where they can actually be read.
 */
function VoiceCompass({
  level,
  color,
}: {
  level: LevelEvent;
  color: string;
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
    "--orb-scale": (0.84 + volume * 0.29).toFixed(3),
    "--orb-halo": `${(volume * periodicity * 38).toFixed(1)}px`,
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
  /** Hold gap per word id, frozen at first sight; survives child remounts. */
  const holdMemoRef = useRef(new Map<string, number>());
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
   * With read-ahead the last row holds words nobody has said yet, so marking it
   * as current would point `data-current` at white text. The row the playhead is
   * inside is the one being spoken. This changes only when the playhead crosses
   * a row boundary, so the coarse playhead tick is plenty -- and because the
   * words themselves take no playhead prop, their memoisation is untouched by
   * it.
   */
  /*
   * How long the speaker paused before each word. `t` is on the stream
   * timeline while `start`/`end` are utterance-relative, so the word's end on
   * the stream clock is `t + (end - start)`.
   */
  /* KEYED BY WORD ID AND PERSISTED, BECAUSE A REMOUNT MUST NOT RE-DERIVE IT.
     The gap is computed from the whole word list, so it moves as words arrive
     -- and `--hold-spring` gates the crest and the weight (globals.css), so
     the instant it changed under a word already drawn lifted, that word
     un-gated and snapped to its full crest. Freezing it in the child's
     `useState` was not enough: MEASURED, "is" held translateY -14.9px at
     weight 400 for 0.38s, then at 5.68s its `--hold-lift` went 0.525em ->
     0.000em in one frame -- a REMOUNT, which re-runs the initialiser against
     the newer gap -- and from 6.11s the weight climbed 403 -> 554. Reported as
     "when 'is' is landing, it gets bold".
     This ref lives in the parent, so it outlives any child remount, exactly
     like `scheduledRef` does for the turn moment. First answer wins. */
  const holdGaps = new Map<string, number>();
  /* Ids whose hold gap is final. The child freezes on this rather than on its
     own first render; the two are not the same moment, and the difference is a
     whole held word. */
  const holdSettledIds = new Set<string>();
  /*
   * ...AND HOW LONG THE MOTION LASTS, WHICH IS ONE WORD AT THE CURRENT SPEECH
   * RATE. Straight out of the After Effects template this system was authored
   * in (`AE PROJECT/Academy_CI_Template.aep`, recoverable from the first
   * commit): every animator is driven by ONE range selector, exactly one word
   * wide (`Index End = start + 1`), whose start sweeps
   *   ease(time, inTime, outTime, 0, textLenWords)
   * across the LINE. A one-word-wide window crossing `textLenWords` words in
   * `outTime - inTime` therefore sits on each word for
   * `lineDuration / wordCount` -- the local speech rate, and nothing else.
   * It does NOT depend on the word's size, its loudness, or its own spoken
   * length, which is what every previous attempt here assumed.
   * Live, the interval to the NEXT word's onset is that same quantity, and it
   * is exactly what the one-word lookahead buys.
   */
  const paceGaps = new Map<string, number>();
  {
    let previousOnset: number | null = null;
    let previousUtterance: number | null = null;
    const flat = paragraphs.flatMap((paragraph) => paragraph.words);
    for (let index = 0; index < flat.length; index += 1) {
      const {id, word} = flat[index];
      /* A SENTENCE BREAK IS NOT A HELD WORD. Measured on the film's first 18s
         -- per frame, every caption cluster's ink bottom against the median of
         its own frame -- EXACTLY ONE word leaves the line: "is" in "precisely
         as each word is spoken", up 0.84em from 6.88s to 7.83s. Nothing else
         lifts at all. But the pause before "is" (0.96s) is not distinctive on
         its own: `Caption`, `Intonation.` and `The` all follow gaps of 0.90s+
         in the same stretch. What separates them is that those are the FIRST
         word of an utterance -- the ordinary silence between sentences --
         while "is" is a rhetorical hold in the MIDDLE of a phrase. The film
         lifts the second kind and not the first. */
      const utterance = number(word.utterance, Number.NaN);
      const startsUtterance = Number.isFinite(utterance) &&
        previousUtterance !== null && utterance !== previousUtterance;
      if (Number.isFinite(utterance)) previousUtterance = utterance;
      const onset = number(word.t ?? word.start, Number.NaN);
      /* ONSET TO ONSET, NOT END TO ONSET. The recognizer's `end` runs to the
         next word's onset -- it attributes no silence to anything -- so
         `onset - previousEnd` is **0.00s for every word in the capture**,
         measured, and the hold could never fire on a real pause. "is" in
         "precisely as each word is spoken" follows a 0.96s gap and scored
         zero. The inter-onset interval is the honest signal: ordinary speech
         runs ~0.08-0.32s here and a pause stands well clear of it. */
      /* ...AND A LONGER PAUSE IS A SENTENCE BREAK, WHICH DOES NOT LIFT.
         Utterance metadata cannot make this distinction here: the film opens
         with ONE 24s utterance, so `Intonation.`, `The` and `weights,` sit
         INSIDE it and no boundary exists to test. The gaps do separate them,
         just not with a floor -- measured, those words follow gaps of 1.10s+
         while "is", the one word the film actually lifts, follows 0.96s. The
         long gaps are sentence breaks and the medium one is a rhetorical
         hold, so the lift lives in a BAND. */
      const next = flat[index + 1];
      const nextOnset = next
        ? number(next.word.t ?? next.word.start, Number.NaN)
        : Number.NaN;
      /* SILENCE ON BOTH SIDES, AND THIS IS WHAT THE ONE-WORD LOOKAHEAD BUYS.
         A gap BEFORE alone cannot pick "is" out: `the` and `and` follow
         pauses in the same band and the film leaves both on the line. What is
         distinctive about a held word is that it stands ALONE -- the speaker
         stopped, said it, and stopped again. Measured: "is" has 0.96s before
         it and 0.80s after; the function words that shared its leading gap are
         followed immediately by more speech. Scoring the SMALLER of the two
         gaps is the whole rule, and it needs the next word's onset, which is
         exactly the one word of delay this project agreed to spend. */
      if (previousOnset !== null && Number.isFinite(onset) && !startsUtterance) {
        const before = Math.max(0, onset - previousOnset);
        const after = Number.isFinite(nextOnset)
          ? Math.max(0, nextOnset - onset)
          : before;
        const gap = Math.min(before, after);
        /* ...BUT ONLY ONCE BOTH NEIGHBOURS EXIST. The gap is
           `min(before, after)`, and `after` needs the NEXT word -- which has
           usually not arrived on the render where this word first appears. A
           memo written then freezes a value computed from half a
           neighbourhood, and MEASURED it froze "is" at a full 0.525em lift on
           one run and at 0.000 on the next: the hold became a coin flip. Wait
           for the real neighbourhood, then freeze; until it exists, compute
           live and commit nothing. */
        const remembered = holdMemoRef.current.get(id);
        const settledGap = before <= runtime.holdMaxS ? gap : 0;
        if (remembered !== undefined) {
          holdGaps.set(id, remembered);
          holdSettledIds.add(id);
        } else {
          if (Number.isFinite(nextOnset)) {
            holdMemoRef.current.set(id, settledGap);
            holdSettledIds.add(id);
          }
          if (settledGap > 0) holdGaps.set(id, settledGap);
        }
      }
      if (Number.isFinite(onset) && Number.isFinite(nextOnset)) {
        paceGaps.set(id, Math.max(0, nextOnset - onset));
      }
      if (Number.isFinite(onset)) previousOnset = onset;
    }
  }

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
        const color = speakerColor(paragraph.speaker, speakerColors);
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
                    holdGapS={holdGaps.get(id) ?? 0}
                    holdSettled={holdSettledIds.has(id)}
                    paceGapS={paceGaps.get(id) ?? 0}
                    clockEpoch={clockEpoch}
                    scheduleWord={scheduleWord}
                    color={speakerColor(word.speaker, speakerColors)}
                    intensity={intensity}
                    runtime={runtime}
                    key={id}
                  />
                ))}
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
  // Which words start a row. Persisted so a later edit to earlier text cannot
  // re-chunk rows the viewer has already read -- see selectStableCaptionStack.
  // Held as lazily-initialised state rather than a ref: the object identity is
  // stable for the life of the component, and reading it during render is what
  // the chunker needs, which a ref is not allowed to provide.
  const [stageMemory] = useState<StageMemory>(createStageMemory);
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
      stageMemory,
    )
    : paragraphs;
  /* CWI 2.4.4/2.4.5: sound labels yield to speech. The PR film shows
     "[Toy music]"/"[Beep]" only while no one is speaking, never beside an
     active dialogue caption. Speech is active while the playhead sits inside
     the DISPLAYED timeline's speech — up to the newest word's end plus a
     short linger — which also covers read-ahead: white upcoming words push
     the edge past the playhead. Old retained rows cannot suppress (their
     ends are far behind), and `level.speech` would be wrong here: it lives
     on the acoustic clock, `read_ahead_delay_s` AHEAD of what the viewer
     sees. */
  const speechEndMs = useMemo(() => {
    let newest = Number.NEGATIVE_INFINITY;
    for (const paragraph of stageParagraphs) {
      for (const {word} of paragraph.words) {
        const onset = acousticTimeMs(word);
        if (!Number.isFinite(onset)) continue;
        const end = onset
          + Math.max(0, number(word.end) - number(word.start)) * 1000;
        if (end > newest) newest = end;
      }
    }
    return newest;
  }, [stageParagraphs]);
  const speechActive = playheadMs <= speechEndMs + runtime.soundLingerMs;
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
    ? speakerColor(currentParagraph.speaker, speakerColors)
    : fallbackColor;
  const direction = number(level.direction_deg ?? level.azimuth_deg, Number.NaN);
  const directionKnown = Number.isFinite(direction);
  const inputGood = level.status === "good";
  const studioStyle: CSSVars = {
    "--caption-scale": settings.captionScale,
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
              data-suppressed={speechActive ? "true" : "false"}
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
            <VoiceCompass level={level} color={activeColor} />
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
              const color = speakerColor(speaker, speakerColors);
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
