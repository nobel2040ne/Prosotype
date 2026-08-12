"use client";

import {
  AudioWaveform,
  AlignEndHorizontal,
  Captions,
  Check,
  ChevronRight,
  CircleGauge,
  Eye,
  Globe2,
  Mic2,
  Minus,
  PanelRightClose,
  PanelRightOpen,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Type,
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
  FILM_WORD_TURN_MS,
  HOLD_ENVELOPE_EMPHASIS,
  naturalMotionDurationMs,
} from "@/lib/motion-timing";
import {baselineOffsetEm, formatBaselineEm} from "@/lib/glyph-metrics";
import {waveGrain, wordIsWide} from "@/lib/hangul";
import {FILM_PEAK_FRACTION, fallDurationMs} from "@/lib/motion-timing";
import {groupLeads, liftsInGroups, syllableGroups} from "@/lib/syllables";

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
  hangulWave: boolean;
  enhancedMotion: boolean;
  rollingCaptions: boolean;
  captionRules: boolean;
}

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const STACK_SHIFT_DURATION_MS = 540;
const STACK_ENTER_DURATION_MS = 620;
const STACK_EASING = "cubic-bezier(.18,.72,.22,1)";
/* HOW LONG THE BOX TAKES TO OPEN over a newly appended word. It is a CLIP, so
   while it runs the word is hidden -- a progressive appearance, which is what
   2.2.1's read-ahead cannot afford much of. Against the 1.75s read-ahead lead
   this spends 9% of the word's own preview, which is the trade taken
   knowingly. Do not lengthen it; if the growth ever needs to read as slower,
   soften the easing instead. */
const ROW_GROW_DURATION_MS = 160;
/* How far past its turn a word may still animate. Beyond this it settles --
   see the arming effect. Roughly four frames: long enough to absorb render
   jitter, far short of the ~1s a stretched tail now runs for. */
const SETTLE_GRACE_MS = 70;

const number = (value: unknown, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

/**
 * How much of a word's span was actually voiced, 1 when unknown.
 *
 * The recognizer's `end` runs to the NEXT word's onset and attributes no
 * silence to anything, so `end - start` is an inter-onset interval. Multiplying
 * by this recovers the duration the speaker was actually speaking -- validated
 * against an energy-gated voiced span measured straight off the film's audio,
 * correlation +0.765.
 */
function voicedFraction(word: {voiced_frac?: number | null}): number {
  const value = Number(word?.voiced_frac);
  return Number.isFinite(value) && value > 0 ? Math.min(1, value) : 1;
}

/** The CWI 2.3 crest bounds, as the runtime config declares them. */
function voiceRanges(runtime: RuntimeConfig, enhanced = false): VoiceTypeRanges {
  return {
    scale: runtime.voiceScaleRange,
    scaleResponse: enhanced
      ? runtime.voiceScaleResponseEnhanced
      : runtime.voiceScaleResponse,
    scaleResponseQuiet: runtime.voiceScaleResponseQuiet,
    scaleDeadband: enhanced
      ? runtime.voiceScaleDeadbandEnhanced
      : runtime.voiceScaleDeadband,
    ...(enhanced ? {scalePivot: runtime.voiceScalePivotEnhanced,
                    scaleCurve: runtime.voiceScaleCurveEnhanced,
                    scalePoints: runtime.voiceScalePointsEnhanced} : {}),
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

/**
 * Per-word values that must survive a word being rebuilt in another row.
 *
 * Held by `CaptionFeed` in lazily-initialised STATE, not a ref: the children
 * read it while rendering, which `react-hooks/refs` forbids for a ref.
 */
interface WordMemo {
  /** The motion clock: frozen the first time the word was ever drawn. */
  clock: Map<string, {duration: number; sweepMs: number; crestMs: number}>;
  /** The resolved hold, once the gate has closed on it. */
  hold: Map<string, number>;
  /* THE 2.3 VOICE AXES, frozen at first sight like the clock beside them.
     "Everything is frozen at first sight -- duration, AXES, sweep, hold gap and
     turn moment" is the standing rule and the axes were the one item not
     actually implementing it.
     What moved them was the SPEAKER'S RUNNING REGISTER. Weight is a property of
     the voice, so it reads the speaker's median F0, and that median keeps
     updating as the speaker talks -- which silently re-derived the size and
     weight of words that had finished animating minutes earlier. MEASURED with
     the re-motion detector: "like" settled at scale 1.000 / weight 400 and was
     recomputed 7.3s later to 1.460 / 860, which also flipped `--voice-envelope`
     from `voice-phase-film` to `voice-phase-hold` -- an animation-NAME change,
     so the whole word visibly re-ran its motion.
     Reported as "the previous words motions again sometimes". */
  voice: Map<string, ReturnType<typeof captionMotionFor>>;
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
  memo,
  hangulWave,
  enhancedMotion,
}: {
  id: string;
  word: CaptionWord;
  color: string;
  intensity: number;
  runtime: RuntimeConfig;
  /** Settings toggle: give wide-script characters their own Hangul grain. */
  hangulWave: boolean;
  /** Settings toggle: anticipate the crest and sweep the whole spoken word. */
  enhancedMotion: boolean;
  /*
   * WHAT THIS WORD FROZE AT FIRST SIGHT, KEPT OUTSIDE THE WORD (2026-08-06).
   * A row is a DOM element and a word is its CHILD, so React reconciles words
   * within one row only: a word that moves to another row is UNMOUNTED and
   * rebuilt, and everything held in its own state is thrown away and re-derived.
   * That is not a hypothetical -- `duration` is derived from `paceGapS`, which
   * is 0 until the NEXT word arrives, so a word rebuilt after its neighbour
   * landed re-derived a different motion duration than the one it was drawn
   * with, and `holdAmount` re-ran the settle race the hold gate exists to win.
   * A word only ever changes row while it is still AHEAD of the playhead, so
   * the rebuild itself is invisible -- nothing has begun animating. The frozen
   * values were the whole casualty, so they live in the parent, keyed by word
   * id, exactly as the hold GAP already did.
   */
  memo: WordMemo;
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
  /* FROZEN AT FIRST SIGHT -- see `WordMemo.voice`. Recomputing this under a
     settled word is what made already-read captions animate again, because the
     speaker's running register keeps moving after the word is history.
     Written during render, exactly as `memo.clock` is, and for the same reason:
     the value has to exist before the first paint that uses it, or the word
     turns wearing one size and settles wearing another. */
  const motion = (() => {
    const remembered = memo.voice.get(id);
    if (remembered) return remembered;
    const fresh = captionMotionFor(
      {loudness, pitchHz: pitch, texture, registerHz: register},
      voiceRanges(runtime, enhancedMotion),
      intensity,
      /* 2.2.3's amplitude is per CLOCK: the PDF's verbatim 15% on legacy, and
         on enhanced the ~55% the PR film actually renders. Measured per word
         off the film -- see `live_sync.studio.sync_pop_enhanced`. */
      enhancedMotion ? runtime.syncPopEnhanced : runtime.syncPop,
    );
    memo.voice.set(id, fresh);
    return fresh;
  })();

  /*
   * CWI 2.3 IS PER CHARACTER (PDF p.34 / p.38 / p.40), so the word is split and
   * each letter reads the word's own intonation contour at its own position.
   * `Array.from` rather than `split("")`: a Hangul syllable block or any
   * astral-plane character must stay one unit, and Korean is a shipped language.
   */
  const characters = Array.from(word.text);
  /* Which colour-turn path this word takes. Frozen per word by its text, and
     `wordIsWide` is written so an all-Latin word can never come back true --
     that is what keeps English on its existing per-glyph path, byte for byte. */
  const isWide = wordIsWide(word.text);
  /* WHICH LETTERS LEAVE THE LINE TOGETHER. The film lifts a word's glyphs in
     syllables -- "but|ton", "se|en", "res|cue!" -- so each character carries
     the index of the group's FIRST letter, and the wave reads its clock from
     there. A Hangul block is already a syllable, so wide script is one group
     per character and its existing per-glyph timing is untouched.
     Derived from the text alone, so it is stable across every revision that
     does not respell the word, and a respelling remounts anyway. */
  /* Only a word of six letters or more raises its syllables independently --
     see `liftsInGroups`. Wide script is excluded: a Hangul block is already a
     syllable and its own wave shape carries the motion. */
  /* .085em -> .155em (2026-08-13): measured, the widest a word's letters came
     apart was 1.85px and the user still could not see the split. Bounded by
     `scripts/ink_collision.py`, which has 16px of clearance and 0 close pairs
     at this value. */
  const groupLift = !isWide && liftsInGroups(word.text) ? ".155em" : "0em";
  const waveLead = isWide
    ? characters.map((_, i) => i)
    : (() => {
        const groups = syllableGroups(word.text);
        const leads = groupLeads(groups);
        return characters.map((_, i) => leads[groups[i] ?? 0] ?? i);
      })();
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
          /* EACH LETTER TILTS SLIGHTLY DIFFERENTLY, and letters move in
             SYLLABLES. Watched on the film: "seen" lifts as "se" + "en",
             "Gump" as "Gu" + "mp", "button" as "but" + "ton", and inside a
             lifting group the glyphs sit at slightly different angles -- it is
             a hand-set look, not a rigid block. `Math.sin` on the index gives a
             deterministic, non-repeating spread (a modulo would visibly cycle
             every few letters); the GROUP carries the lift and the tilt varies
             within it. Frozen with the word: derived from `index` alone, so a
             remount cannot re-roll it. */
          "--char-tilt": `${(Math.sin(index * 2.399) * 1.35).toFixed(2)}deg`,
          /* HOW FAR THIS LETTER'S SYLLABLE LEAVES THE LINE. Zero unless the
             word is long enough to lift in parts, so a short word still moves
             as one piece on `--word-lift-em` and only a `but|ton` raises its
             halves separately. Bounded by `scripts/ink_collision.py`: this
             travels toward the row above, on top of the word-level lift. */
          "--group-lift-em": groupLift,
          "--char-group": waveLead[index] ?? index,
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
          /* Hangul-structural grain, wide script + toggle only. Absent
             otherwise, and `character-wave` then reads its own literals, so
             the Latin keyframe is byte-for-byte what it was. */
          ...(hangulWave && isWide ? (() => {
            const {ay, ax} = waveGrain(character.codePointAt(0) ?? 0);
            return {"--wave-ay": ay.toFixed(4), "--wave-ax": ax.toFixed(4)};
          })() : {}),
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
  /* ...AND ONCE IT IS FROZEN IT IS REMEMBERED OUTSIDE THIS COMPONENT, so a
     word rebuilt in another row resumes the answer it was drawn with instead
     of re-running the race above. See `memo`. */
  const [holdAmount, setHoldAmount] = useState(
    () => memo.hold.get(id) ?? holdTarget,
  );
  const holdFrozen = useRef(memo.hold.has(id));
  useEffect(() => {
    if (holdFrozen.current) return;
    const armed = armedRef.current;
    if (armed && performance.now() >= armed.turnAtMs) {
      // The playhead has passed: history. Keep what it actually wore.
      holdFrozen.current = true;
      memo.hold.set(id, holdAmount);
      return;
    }
    if (!holdSettled) return;
    holdFrozen.current = true;
    memo.hold.set(id, holdTarget);
    setHoldAmount((current) => (current === holdTarget ? current : holdTarget));
  }, [holdSettled, holdTarget, holdAmount, id, memo]);
  const holdEnvelope = holdEmphasis >= HOLD_ENVELOPE_EMPHASIS;
  /* HOW LONG THIS WORD TAKES TO COME BACK DOWN -- long enough to reach the
     next word's turn, so the stage is never still while somebody is talking.
     WAIT FOR THE NEIGHBOURHOOD, THEN FREEZE, exactly as the hold gap does.
     `paceGapS` is 0 until the NEXT word has arrived, and freezing at first
     sight would therefore capture 0 for almost every word and do nothing at
     all. The wait is safe: a word is first drawn when it arrives and does not
     turn until `read_ahead_delay_s` (1.75s) later, while its neighbour lands
     at a median 0.62s -- so this settles well before the animation starts and
     never re-times a running one.
     Frozen in a ref rather than in `memo.clock`, because the clock is the
     thing that must freeze at FIRST sight and this is the thing that must
     not. */
  const fallRef = useRef<number | null>(null);
  /* ...AND IT STOPS ACCEPTING ONE ONCE THE WORD HAS TURNED. The neighbour
     usually lands long before the turn, but the LAST word of an utterance can
     wait seconds for the next one -- and taking its gap then would change
     `--fall-ms` under an animation that is already running, which restarts it.
     Reported as "두번 motion이 실행되는 단어들이 있음". Behind the playhead a
     word is frozen history; this is that rule applied to the tail. */
  const turnedRef = useRef(false);
  if (fallRef.current === null && paceGapS > 0 && !turnedRef.current) {
    fallRef.current = paceGapS;
  }

  const [{duration, sweepMs, crestMs}] = useState(() => {
    /* FROZEN THE FIRST TIME THIS WORD WAS EVER DRAWN, not the first time this
       COMPONENT was, which are different moments once a word can change row.
       `duration` reads `paceGapS`, and that is 0 until the NEXT word arrives --
       so a word rebuilt in a new row after its neighbour landed would re-derive
       a different motion duration than the one it is already wearing. */
    const remembered = memo.clock.get(id);
    if (remembered) return remembered;
    /* ONE WORD AT THE CURRENT SPEECH RATE -- the AE template's one-word-wide
       range selector, and nothing about this word's own size. Frozen here with
       everything else, so a verifier respelling can never re-time a running
       crest. `emphasisOf` still feeds the WIPE guard below, which is about how
       far the colour has to travel, not about how long the swell lasts. */
    const push = emphasisOf(motion.voice.scale, voiceRanges(runtime));
    const naturalMs = naturalMotionDurationMs(motionWord, runtime, paceGapS);
    const spokenMs = Math.max(0, number(word.end) - number(word.start)) * 1000;
    /* LEGACY finishes the wipe before the word is done being said (0.72), a
       boundary travelling across the characters -- which is what
       `synchronization.mov` shows and what CWI 2.2.2 describes.

       THE PR FILM DOES NOT DO THAT. Its AE range selector is expressed in WORD
       units (`ret = ease(time, inTime, ..., 0, textLenWords)`, template
       expressions 2 and 7), so a whole word changes colour at once. Checked
       against the frames at 24fps rather than trusting the template: tracking
       each word's green fraction through its own turn, `sole`, `in` and `this`
       each spend exactly ONE frame between <15% and >85% turned. There is no
       gradual boundary to find.

       So enhanced turns the word as a unit. It matters beyond fidelity: with a
       wipe running the length of the spoken word, the word is still mostly
       white at the moment it punches, which is visibly wrong beside the film.
       A short non-zero sweep keeps the turn from being a hard cut and keeps
       every per-character span armed. */
    /* LEGACY finishes the wipe before the word is done being said (0.72), a
       boundary travelling across the characters, which is CWI 2.2.2 and what
       `synchronization.mov` shows. A fixed per-character step was measured off
       the film (42 ms, one frame) and TRIED HERE; it is recorded in
       docs/MOTION.md and was reverted at the user's direction. */
    const sweep = enhancedMotion
      ? FILM_WORD_TURN_MS
      : clamp(spokenMs * 0.72, 0, runtime.wordMotionMaxMs);
    /* HOW LONG THE SIZE CHANGE LASTS -- and the legacy answer is far too long.
       Legacy stretches the crest by `sweep / VOICE_PHASE_RISE_FRACTION` so the
       swell cannot lead the wipe, dragging an ordinary word's size change out
       toward a second. The film's words rise and fall in about a QUARTER
       SECOND, every one of them, so enhanced runs the size channel on a fixed
       film-paced window and lets only a genuinely emphatic word (`push`) run
       longer. Ours previously overlapped three pops inside one 0.25s sample
       because the window outlasted the gap between words; the film shows one
       word punching at a time. */
    /* AND THE BIGGER THE SWELL, THE LONGER THE WINDOW. The paragraph above
       says "lets only a genuinely emphatic word run longer" and the code did
       not do it -- every enhanced word ran the same 424ms whatever size it
       reached, so the size channel's peak VELOCITY rose with its amplitude and
       the words that grow most snapped. Reported as "some pop motions are too
       fast -> looks aggressive", and it is the largest ones that were.
       `push` is already this word's emphasis, 0..1, and already frozen here.
       Ordinary words are untouched (push = 0 inside the deadband); the ceiling
       is the crest's own `wordMotionMaxMs`, the same one legacy tops out at. */
    const crest = enhancedMotion
      ? Math.min(
          runtime.wordMotionMaxMs,
          runtime.wordMotionEnhancedMs + push * runtime.wordMotionEnhancedEmphasisMs,
        )
      : crestDurationMs(
          sweep,
          // The word's REAL speech: `end` runs to the next onset, so the raw
          // span is an inter-onset interval and `voiced_frac` is what makes it
          // speech. This anchors the crest's floor to the speaker.
          crestWindowMs(push, runtime, spokenMs * voicedFraction(word)),
          push, runtime.wordMotionMaxMs,
        );
    const clock = {
      duration: naturalMs,
      sweepMs: sweep,
      // The crest is the SLOW clock -- emphasis, not speech rate.
      crestMs: crest,
    };
    memo.clock.set(id, clock);
    return clock;
  });
  /* A word with no emphasis holds Regular -- see `--voice-weight` below.
     `voice.scale` is the 2.3 size, which sits at exactly 1 for anything inside
     the deadband, so it is the emphasis signal already. THIS GATES WEIGHT
     ONLY. It used to gate the pop too, and that was wrong: see `--sync-pop`. */
  const quietWord = enhancedMotion && motion.voice.scale <= 1.005;
  const style: CSSVars = {
    "--speaker-color": color,
    /* The word's normalised loudness, published so `scripts/motion_diff.py` can
       read the distribution the size mapping is fed. Fitting that mapping to
       the film needs the INPUT distribution, not just the output: a single
       power curve cannot match the film's p50 and p75 at once because the two
       distributions differ in shape, and diagnosing that from voice-scale alone
       is impossible -- every word below the pivot clamps to 1 and the inverse
       is ambiguous exactly where the disagreement is. Display-only. */
    "--voice-loudness": loudness.toFixed(4),
    /* The size cue trails the turn on the enhanced clock and starts with it on
       legacy, where `calc(X + 0ms)` is X and the delay arithmetic is untouched. */
    "--crest-lag": `${enhancedMotion ? runtime.crestLagMs : 0}ms`,
    /* NOT EVERY WORD POPS -- and this has now been decided from the stage
       twice, against the film both times, so it is settled here rather than
       re-derived. Reading the film word by word says every word pops, and it
       does; watching a real talker through the array at real speech rate, the
       user's verdict both times was "so many words pop" and the stage read as
       hard to follow. The difference is context, not fidelity: the film gives a
       line four words and a held shot, this stage carries forty at 2.5 words/s,
       and forty simultaneous pops is noise where four is emphasis.
       So an unemphasised word keeps the colour turn, the character wave and the
       small lift, and does NOT pop. Legacy is untouched and still pops
       everything. */
    "--sync-pop": (quietWord ? 1 : motion.sync.scale).toFixed(3),
    /* ...AND WHAT AN UNEMPHASISED WORD DOES INSTEAD IS LIFT. Every word gets
       it, popped or not -- the film's own reading opens "lifting -> maybe all
       has". Ungated on purpose: this is the channel that keeps a quiet word
       alive now that it does not grow, so gating it too would put the stage
       back to nothing moving. */
    "--word-lift-em": `${runtime.wordLiftEmEnhanced}em`,
    "--motion-duration": `${duration.toFixed(0)}ms`,
    // The 2.3 crest takes its own window so its rise tracks the colour wipe
    // instead of leading it (`crestDurationMs`); the pop and wave keep the
    // natural window.
    "--crest-duration": `${crestMs.toFixed(0)}ms`,
    /* The wide-script wipe sweeps across the word over exactly this window, so
       the continuous boundary reaches a given point at the same moment the
       per-glyph steps used to. Frozen at mount with `duration`/`crestMs`. */
    "--sweep-duration": `${sweepMs.toFixed(0)}ms`,
    // Anticipation. 0ms on legacy -> `calc(turn-delay - 0ms)` is turn-delay.
    /* Ordinary words pulse; emphatic ones rise, HOLD and fall. The film's
       "louder" sits at full size for ~0.75s of a ~1.25s motion (share ~0.6)
       while the corpus median is 0.40 -- the median is carried by the 37 of 43
       words that barely move, and reading it as one universal shape is what
       flattened the emphatic words. A keyframe's stops cannot take a `var()`,
       but `animation-name` can. */
    /* The film's envelope peaks at 58% of its excursion, not half way, so the
       rise is long and the fall short. A held word keeps its own envelope on
       both clocks -- the lift is a separate cue and was never fitted here. */
    "--voice-envelope": holdEnvelope
      ? "voice-phase-hold"
      : (enhancedMotion ? "voice-phase-film" : "voice-phase"),
    /* The two halves of the split envelope. Only read when `data-tail` is
       `extended`; harmless otherwise. */
    "--rise-ms": `${(crestMs * FILM_PEAK_FRACTION).toFixed(0)}ms`,
    "--fall-ms": `${fallDurationMs(crestMs, fallRef.current ?? 0).toFixed(0)}ms`,
    "--sync-envelope": enhancedMotion ? "word-sync-pop-film" : "word-sync-pop",
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
    /* AN UNEMPHASISED WORD HOLDS REGULAR. This is the one channel the film
       withholds: read back line by line, the shouted lines are bold on every
       word and the spoken ones are not bold at all, while both pop. The weight
       rides the same phase as the pop, so leaving it live gave every word a
       weight swing and made the whole stage read as bold. */
    "--voice-weight": String(
      quietWord
        ? 400
        : Math.round(400 + (motion.voice.weight - 400) * (1 - holdAmount)),
    ),
    "--voice-width": `${motion.voice.width}%`,
    /* HOW LONG ONE GLYPH STAYS ELEVATED. Measured off the film at 3x upscale
       (at 720p glyphs touch and segment as 2-3 character blobs, which is what
       makes the grouping look authored): across 57 glyphs each stays up for 4
       frames = 167 ms, while adjacent glyphs step 1 frame = 42 ms apart. Four
       are elevated at once, and THAT overlap is the "characters grouped in
       2-3 moving together" -- they step one at a time and each outlasts its
       neighbour's start.
       This used to be `duration * 0.72`, which at our step gave ~7 glyphs up
       at once: too many and each too long, so the word smeared instead of a
       group travelling across it. */
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
        span.style.setProperty("--char-wave-delay", "-600000ms");
      }
      return;
    }
    const rearming = element.dataset.armed !== "true";
    element.dataset.armed = "true";
    const turnDelay = armedRef.current.turnAtMs - performance.now();
    // Past its turn this word is history: nothing about its motion may change
    // again. See `turnedRef` above.
    if (turnDelay <= 0) turnedRef.current = true;
    // The word's own delay is written ONCE: rewriting `animation-delay` shifts
    // a running animation, which is the hazard `data-armed` exists to prevent.
    if (rearming) {
      /* A WORD WHOSE TURN HAS PASSED SETTLES. IT DOES NOT PLAY THE REMAINDER.
         "Live motion is a function of the timeline, not of arrival" -- so a
         word armed after its own turn moment is history and must paint its end
         state, not resume mid-curve. A negative delay does resume mid-curve,
         and that is what fired an OLD word's motion right after a NEW one:
         measured on the sample, 27 words were armed 200-640ms past their turn
         and adjacent pairs were firing right-to-left.
         THE TAIL IS WHY THIS SURFACED NOW. The window in which a negative
         delay still lands inside the animation was rise+fall = 424ms and is
         now up to 1051ms, so a remount from a row re-break replays far more
         often than it used to.
         The grace is small: a word can arm a few frames after its turn purely
         from render timing, and cutting those would make ordinary words
         silently static. Past it, settle. */
      const settled = turnDelay < -SETTLE_GRACE_MS;
      element.style.setProperty(
        "--turn-delay",
        settled ? "-600000ms" : `${Math.round(turnDelay)}ms`,
      );
      // The wipe is laid out across the letters the word had WHEN IT WAS ARMED,
      // and that denominator is then frozen with the sweep. See the loop below.
      charSpanRef.current = Math.max(1, characters.length);
    }
    const perWord = charSpanRef.current ?? Math.max(1, characters.length);

    /*
     * THE COLOUR TURN IS A WIPE THROUGH THE WORD, NOT A SWITCH.
     *
     * `docs/reference/pr-film.mp4` shows the boundary INSIDE a word
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
    // THE COLOUR TRAVELS PER LETTER; THE LIFT TRAVELS PER SYLLABLE. Watched on
    // the film, "seen" lifts as `se` + `en`, "button" as `but` + `ton` -- the
    // letters of a syllable leave the line together -- while the colour
    // boundary still crosses one letter at a time. So the wave gets its own
    // delay, read from the group's FIRST letter (`waveLead`), and every letter
    // of that group shares it. Frozen on the same terms as the turn delay, and
    // written in the same pass, so `unarmedCharacters` (which tests only
    // `--char-turn-delay`) can keep testing one property.
    for (const span of unarmedCharacters(element)) {
      const index = Number(span.dataset.charIndex ?? 0);
      span.style.setProperty(
        "--char-turn-delay",
        `${charTurnDelayMs(turnDelay, index, perWord, sweepMs)}ms`,
      );
      span.style.setProperty(
        "--char-wave-delay",
        `${charTurnDelayMs(turnDelay, waveLead[index] ?? index, perWord, sweepMs)}ms`,
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
      /* THE SPLIT IS UNCONDITIONAL ON THE ENHANCED CLOCK, and that is the
         point: this used to also require a known next onset, so a word whose
         neighbour arrived late flipped from `natural` to `extended` AFTER it
         had turned -- an animation-NAME change, which restarts the animation
         and runs the whole motion a second time.
         A word with no neighbour yet simply gets the natural fall duration, so
         the split renders exactly what the single animation did. Legacy and
         the hold envelope keep their own unsplit shapes. */
      data-tail={
        enhancedMotion && !holdEnvelope ? "extended" : "natural"
      }
      data-status={status}
      data-final={word.final ? "true" : "false"}
      data-sustain={word.sustain_active ? "true" : "false"}
      data-delivery={deliveryProfile}
      // CWI 2.1.5: an off-camera voice keeps its speaker colour and is set in
      // italic. Live capture has no camera and never sets this; it is here so
      // the SSE contract can carry the distinction rather than inventing it.
      data-off-camera={word.off_camera ? "true" : "false"}
      /* Wide scripts take the CONTINUOUS wipe: a Hangul block is 0.91em against
         Latin's 0.43em, so a per-glyph step moves the colour boundary 2.1x
         further, and 46% of Korean words have <=2 steps -- a switch, not a
         sweep. Decided per WORD from the code points, never from the session
         language, so a Korean caption carrying `2011` still behaves. */
      data-script={isWide ? "wide" : "narrow"}
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
        {/* THE CONTINUOUS WIPE, wide script only. A second ink layer in the
            speaker colour, revealed by an animated clip. It carries the SAME
            character spans as the base, so both layers stretch identically and
            stay registered while the wave runs -- precisely what a
            `background-clip: text` gradient could NOT do, because the gradient
            lives in the ancestor's coordinate space while the wave is a
            transform on the descendants. Checked on a spike before building.
            The speaker colour is inherited from `.caption-word`, so a late
            attribution correction rewrites `--speaker-color` and recolours this
            layer directly -- the same property the `to`-less colour keyframe
            gives the narrow path. */}
        {isWide ? (
          <span className="word-ink word-ink-turned" aria-hidden="true">
            {renderCharacters(false)}
          </span>
        ) : null}
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
  speakerColors,
  sound,
}: {
  level: LevelEvent;
  color: string;
  speakerColors?: SpeakerColorMap;
  sound?: {label?: string; category?: string} | null;
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
  /* THE DIAL FALLS BACK TO 0°; THE EVENT DOES NOT (2026-08-13, at the user's
     direction, and knowingly against this project's own standing rule).
     "Never fabricate direction -- omit it. Do not default it to 0, which is
     front and would be a claim about the room that nothing measured." The rule
     still holds where it can do harm: `direction_deg` stays ABSENT from the
     level and word events, so `autocwi/haptics.py` never drives a motor at a
     bearing nobody observed and nothing downstream can mistake this for data.
     What changes is only what the dial DRAWS with nothing to draw: it points
     front and reads 0° instead of going inert. `data-measured` keeps the
     distinction on the element, so the display can still tell the truth about
     itself. */
  const directionMeasured = Number.isFinite(direction);
  const directionKnown = true;
  const style: CSSVars = {
    "--orb-color": color,
    /* THE PULSE HAS A RANGE WORTH SEEING. 0.84..1.13 was a 29% span that read
       as the dial twitching rather than breathing -- reported as moving "너무
       찔금씩". 0.78..1.22 is nearly half again, which is a level meter you can
       read from across a booth. It is bounded by the rail, not by taste: the
       dial's own width is a clamp, so the top of this range has to fit inside
       the section's padding at the widest rail. */
    "--orb-scale": (0.78 + volume * 0.46).toFixed(3),
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
    "--direction-angle": `${directionMeasured ? ((direction % 360) + 360) % 360 : 0}deg`,
  };
  // Standing speaker positions, the SpeechCompass minimap idea: the live dot
  // is where sound is arriving NOW, these are where each speaker sits. Colours
  // are the caption colours, so the ring answers "who is where" with the same
  // vocabulary the text uses. Absent until the array has placed somebody.
  //
  // `speaker_bearings` NAMES its speaker and is preferred wherever it arrives:
  // the older `speaker_slots_deg` colours by array INDEX, which is the order
  // bearings were first seen and not the order speakers were identified, so
  // its marks can wear another speaker's colour. It also only ever grew while
  // attribution was undecided -- measured live, one mark for two speakers
  // across a 37 deg sweep -- which is why the ring never remembered anybody.
  const marksRaw = level.speaker_bearings;
  const marks = Array.isArray(marksRaw) ? marksRaw : [];
  const slotsRaw = level.speaker_slots_deg;
  const slots = marks.length
    ? marks.map((mark) => number(mark.deg, 0))
    : Array.isArray(slotsRaw) ? slotsRaw : [];
  const slotSpeaker = (index: number): string =>
    marks.length ? String(marks[index]?.speaker ?? "") : `S${index + 1}`;

  const label = `${profile} delivery, ${number(level.rms_db, -72).toFixed(1)} dB, ${
    number(level.pitch_hz) > 0 ? `${Math.round(number(level.pitch_hz))} Hz` : "unvoiced"
  }${directionMeasured
    ? `, ${Math.round(direction)} degrees`
    : ", direction not measured"}`;

  return (
    <div
      className="voice-compass"
      data-direction={directionKnown ? "known" : "unknown"}
      data-measured={directionMeasured ? "true" : "false"}
      data-delivery={profile}
      role="img"
      aria-label={`Voice compass: ${label}`}
      style={style}
    >
      {/* THE DIAL SHOWS WHERE PEOPLE ARE, AND NOTHING ELSE (2026-08-13).
          Two concentric radar rings and a full crosshair were drawing a radar
          set: none of it was data, and at 152px they were the busiest thing in
          a rail that had just been emptied for this dial's benefit. What a
          bearing needs is a frame of reference, which is four ticks -- front,
          both sides, behind -- and `.compass-front` marks which one is the
          front of the case, the one thing a viewer has to know to read any of
          the others. */}
      {/* A DIAL WITHOUT A SCALE CANNOT BE READ. Four ticks stripped the radar
          decoration and took the legibility with it -- on a bare circle there
          is nothing to place 231 degrees AGAINST. Twelve, every 30 degrees,
          with the four cardinals long: that is a scale, and a scale is
          information rather than ornament.
          The FRONT tick stays the brightest, because which way the case points
          is what every other bearing is relative to -- and is the one value
          this project has not measured against the real case. */}
      {Array.from({length: 12}, (_, i) => i * 30).map((deg) => (
        <span
          key={`tick-${deg}`}
          className="compass-tick"
          data-cardinal={deg % 90 === 0 ? "true" : "false"}
          data-front={deg === 0 ? "true" : "false"}
          style={{"--tick-angle": `${deg}deg`} as CSSVars}
        />
      ))}
      {slots.map((bearing, index) => {
        const angle = ((Number(bearing) % 360) + 360) % 360;
        /* AN ARC, NOT A DOT, AND ITS WIDTH IS THE UNCERTAINTY. A 6px mark is
           hard to see at rail size and it claims a precision the measurement
           does not have: a speaker seen once from one angle and one seen
           thirty times from the same angle got identical marks. The arc spans
           two circular standard deviations of that speaker's own bearings, so
           a settled talker reads as a tight band and an unsettled one as a
           wide smear -- which is the honest picture and also the one that
           reads peripherally.
           FLOORED AND CAPPED. Below ~8deg an arc is a dot again; past ~150deg
           it wraps far enough to stop meaning a direction, and the tracker has
           already dropped anything genuinely scattered (`MIN_CONCENTRATION`).
           `spread` is absent on the older `speaker_slots_deg` lane, which
           carries no dispersion at all -- those fall back to a mid width
           rather than pretending to be precise. */
        const spread = marks.length ? number(marks[index]?.spread, 26) : 26;
        const span = clamp(spread * 2, 8, 150);
        /* A SPEAKER NEVER LEAVES THE RING once they have been placed, so some
           marks are the last place somebody was seen rather than where they
           are now. Drawn dimmer and hollow: still there, no longer a claim
           about the present. Dropping them instead was read as the compass
           forgetting people, and "this speaker left" is indistinguishable from
           "their bearings went noisy" from the viewer's side. */
        const stale = Boolean(marks.length && marks[index]?.stale);
        return (
          <span
            key={`slot-${index}`}
            className="compass-slot"
            data-stale={stale ? "true" : "false"}
            style={{
              "--slot-angle": `${angle.toFixed(1)}deg`,
              "--slot-span": `${span.toFixed(1)}deg`,
              "--slot-color": speakerColors
                ? speakerColor(slotSpeaker(index), speakerColors)
                : "var(--accent)",
            } as CSSVars}
          />
        );
      })}
      {/* THE NEEDLE. A 9px dot on the rim asked the viewer to find it and then
          work out which way it lay; a line from the centre states the bearing
          the way a compass has always stated it. The dot stays at its tip --
          it is what carries the ACTIVE speaker's colour. */}
      {/* WHAT IS HAPPENING IN THE ROOM, IN THE MIDDLE OF THE INSTRUMENT THAT
          DESCRIBES THE ROOM (2026-08-13, at the user's request). A non-speech
          sound is not a word -- it has no speaker, no colour and no place in a
          line of text -- but it IS an event around the listener, which is
          exactly what this dial is for.
          The stage keeps its own `[Toy music]` caption: CWI 2.4.4 requires the
          bracketed white label and this does not replace it. This is the same
          fact placed where the room is drawn. */}
      {sound?.label || sound?.category ? (
        <span className="compass-sound" data-category={sound.category ?? "environmental"}>
          <i>[{sound.label ?? sound.category}]</i>
        </span>
      ) : null}
      <span className="compass-direction"><b /><i /></span>
      {/* `.compass-texture` and `.compass-pitch` are gone with them. Both were
          voice channels -- brightness and F0 -- and both are on screen already
          as the caption's own texture and weight under CWI 2.3. The dial was
          restating the captions inside a diagram about space. */}
    </div>
  );
}

function CaptionFeed({
  paragraphs,
  timingWords,
  speakerColors,
  intensity,
  runtime,
  clockEpoch,
  scheduleWord,
  playheadMs,
  transcript,
  reducedMotion,
  hangulWave,
  enhancedMotion,
}: {
  paragraphs: CaptionParagraph[];
  /*
   * THE MOTION CLOCK READS THE WORD LIST, NOT THE ROWS (2026-08-06).
   * `holdGaps` and `paceGaps` both need a word's NEIGHBOURS -- the hold gate is
   * `min(gap_before, gap_after)` and the pace is the interval to the next
   * onset. Taking them from `paragraphs` meant taking them from the RETAINED
   * STAGE ROWS, so a word at the edge of the retained window had no neighbour
   * to measure against, and which words sat at those edges was a function of
   * how the chunker had packed the rows. Layout was therefore an input to the
   * motion clock: MEASURED, moving the row break from a word count to a width
   * budget took the held "is" from 1-in-6 runs wrong to 2-in-3, because the
   * word's neighbourhood became available on a different render.
   * This is the ordered word list the recording defines, independent of what
   * the stage is currently showing, which is what both quantities were always
   * about. The rows still decide what is DRAWN; they no longer decide timing.
   */
  timingWords: CaptionParagraph["words"];
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
  /** Settings toggle, threaded to `MotionWord`. Wide script only. */
  hangulWave: boolean;
  /** Settings toggle, threaded to `MotionWord`. */
  enhancedMotion: boolean;
}) {
  /** Hold gap per word id, frozen at first sight; survives child remounts. */
  const holdMemoRef = useRef(new Map<string, number>());
  /* Everything else a word freezes at first sight, for the same reason -- see
     `WordMemo`. State, not a ref: `MotionWord` reads it while rendering. */
  const [wordMemo] = useState<WordMemo>(() => ({
    clock: new Map(),
    hold: new Map(),
    voice: new Map(),
  }));
  const rowNodes = useRef(new Map<string, HTMLElement>());
  const previousPositions = useRef<CaptionStackPosition[]>([]);
  const stackInitialized = useRef(false);
  const stackAnimations = useRef(new Map<string, Animation>());
  const seenRows = useRef(new Set<string>());
  /* Each caption row's last measured width, keyed by its position in the feed.
     INDEX IS A LEGITIMATE KEY HERE and nowhere else: the layout contract is
     that rows never move once laid out and a late word may only append, so a
     row's index is stable for as long as it is on screen. */
  const rowWidths = useRef<number[]>([]);
  const rowGrowAnimations = useRef(new Map<number, Animation>());

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

  /* THE BOX OPENS SIDEWAYS OVER A NEWLY APPENDED WORD.

     A clip, not a width animation: `.caption-words` is sized by its content,
     so there is no transitionable width, and animating the used width would
     relayout the row every frame -- which is row breaking and the motion clock
     put at risk for a cosmetic effect. `clip-path` touches no layout at all.

     Measured in the same pass as the stack shift, and deliberately AFTER it in
     source order so both read the same post-layout geometry. */
  useLayoutEffect(() => {
    if (transcript || reducedMotion) {
      for (const animation of rowGrowAnimations.current.values()) {
        animation.cancel();
      }
      rowGrowAnimations.current.clear();
      rowWidths.current = [];
      return;
    }
    // Rows in paragraph order, from the nodes the stack effect already
    // tracks -- no second ref, and the order is the stack's own.
    const rows = paragraphs.flatMap((paragraph) => {
      const node = rowNodes.current.get(paragraph.id);
      return node
        ? Array.from(node.querySelectorAll<HTMLElement>(".caption-words"))
        : [];
    });
    const widths = rows.map((row) => row.getBoundingClientRect().width);
    const previous = rowWidths.current;
    rowWidths.current = widths;
    // The first pass has nothing to compare against, and a row that appears
    // with the paragraph it belongs to is the stack's ENTER transition --
    // opening it sideways as well would double the effect.
    if (previous.length === 0) return;
    rows.forEach((row, index) => {
      const before = previous[index];
      const after = widths[index];
      if (before === undefined || after - before < 1) return;
      rowGrowAnimations.current.get(index)?.cancel();
      const animation = row.animate(
        [
          {clipPath: `inset(0 ${(after - before).toFixed(1)}px 0 0)`},
          {clipPath: "inset(0 0 0 0)"},
        ],
        {duration: ROW_GROW_DURATION_MS, easing: "cubic-bezier(.22,.61,.36,1)"},
      );
      rowGrowAnimations.current.set(index, animation);
      animation.addEventListener("finish", () => {
        if (rowGrowAnimations.current.get(index) === animation) {
          rowGrowAnimations.current.delete(index);
        }
      }, {once: true});
    });
  }, [paragraphs, reducedMotion, transcript]);

  useEffect(() => () => {
    for (const animation of rowGrowAnimations.current.values()) {
      animation.cancel();
    }
    rowGrowAnimations.current.clear();
  }, []);

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
    const flat = timingWords;
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
                    hangulWave={hangulWave}
                    enhancedMotion={enhancedMotion}
                    id={id}
                    word={word}
                    holdGapS={holdGaps.get(id) ?? 0}
                    holdSettled={holdSettledIds.has(id)}
                    paceGapS={paceGaps.get(id) ?? 0}
                    clockEpoch={clockEpoch}
                    scheduleWord={scheduleWord}
                    memo={wordMemo}
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
 * `--word-em-linear`/`--word-em-spread` row budget, and a rendered row's true
 * height, which
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

/**
 * How wide one WIDE-script character is, in em, on the live caption face.
 *
 * The row chunker budgets `chars * charEm + wordEm`, and `charEm` was fitted on
 * the English PR film and then applied to every script. A Hangul syllable's real
 * advance is 0.9200em -- uniform, min = max, because Hangul is fixed-width --
 * against the 0.4343em it was charged, so the chunker packed about twice as many
 * Korean words into a row as fit. `.caption-words` is `nowrap`, so the overrun
 * was CUT, silently.
 *
 * MEASURED, NOT TABULATED, for the same reason `useGlyphBaseline` is. The font's
 * own `hmtx` does not answer it: frequency-weighted over the PR film transcript,
 * Latin advances read 0.4934em against the shipped 0.4343em -- a 0.88 ratio
 * absorbed by the chunker's slope/intercept fit and by the live variable-font
 * axes -- and there is no reason that ratio transfers to a different face.
 * Returning a hardcoded number here would be a guess wearing a measurement's
 * clothes, and this project has shipped that mistake before.
 *
 * Cheap, and once per face: the caption font is locked before the first word.
 */
function useWideCharEm(language: string | null): number | null {
  const [em, setEm] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    const measure = () => {
      if (cancelled) return;
      const host = document.createElement("div");
      host.className = "caption-feed";
      host.setAttribute("aria-hidden", "true");
      // No `contain:strict` and no fixed width: this probe MEASURES width, so
      // it must be free to be as wide as the text makes it.
      host.style.cssText =
        "position:absolute;left:-9999px;top:0;visibility:hidden;" +
        "width:max-content;white-space:nowrap;";
      const row = document.createElement("div");
      row.className = "caption-words";
      const word = document.createElement("span");
      word.className = "caption-word";
      // A spread of real syllables rather than one repeated block, so a face
      // with per-glyph variation cannot be read off an unlucky sample. Hangul
      // measures uniform, which is itself worth confirming at runtime.
      const sample = "가나다라마바사아자차카타파하각힣";
      word.textContent = sample;
      row.appendChild(word);
      host.appendChild(row);
      // MOUNT IT INSIDE THE SHELL -- `--font-caption` is switched by
      // `.studio-shell[data-language="ko"]`, so a probe parented to
      // `document.body` measures Roboto Flex even in a Korean session. That is
      // the exact mistake `useGlyphBaseline` made twice.
      const shell = document.querySelector(".studio-shell") ?? document.body;
      shell.appendChild(host);
      const fontSize = parseFloat(getComputedStyle(word).fontSize);
      const width = word.getBoundingClientRect().width;
      host.remove();
      const count = Array.from(sample).length;
      if (!Number.isFinite(fontSize) || fontSize <= 0 || width <= 0) return;
      const measured = width / fontSize / count;
      // Sanity band. A wide character cannot be narrower than a Latin one, and
      // cannot exceed one em by much. Outside this the probe measured the wrong
      // face or the fallback, and a wrong number here CLIPS captions -- so
      // report nothing and let the chunker fall back to `charEm`, which is
      // today's behaviour rather than a new failure.
      if (measured < 0.5 || measured > 1.4) return;
      setEm((current) => (
        current !== null && Math.abs(current - measured) < 1e-4
          ? current
          : measured
      ));
    };
    document.fonts.ready.then(measure).catch(measure);
    return () => {
      cancelled = true;
    };
  }, [language]);
  return em;
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
          {/* The eyebrow was the only blue thing on the screen, and blue is
              the interactive signal -- on a page whose entire content is three
              buttons, colouring the one non-interactive line was backwards. */}
          <span className="eyebrow">
            <Globe2 size={13} aria-hidden="true" />
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
                {/* ONE SHAPE FOR ALL THREE. They had three different internal
                    layouts -- EN put the code inline with the name, KO added a
                    latin gloss beside it, MULTI stacked the code on its own
                    line and slipped "Bilingual" between name and description --
                    so the eye had to re-learn the row each time. Every option
                    is now code, name, gloss, description, in that order, and a
                    gloss that would repeat the name is simply absent. */}
                <span className="language-code">{language.id.toUpperCase()}</span>
                <span className="language-name">
                  <strong lang={language.id}>{language.nativeLabel}</strong>
                  {language.nativeLabel !== language.label && (
                    <small>{language.label}</small>
                  )}
                </span>
                <span className="language-description">{language.description}</span>
                <ChevronRight size={17} aria-hidden="true" />
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

      <button
        className="toggle-row"
        aria-pressed={settings.hangulWave}
        onClick={() => setSettings({
          ...settings,
          hangulWave: !settings.hangulWave,
        })}
      >
        <span><Type size={15} /> Hangul-shaped motion</span>
        <i data-on={settings.hangulWave ? "true" : "false"} />
      </button>

      <button
        className="toggle-row"
        aria-pressed={settings.rollingCaptions}
        onClick={() => setSettings({
          ...settings,
          rollingCaptions: !settings.rollingCaptions,
        })}
      >
        <span><AlignEndHorizontal size={15} /> Rolling captions</span>
        <i data-on={settings.rollingCaptions ? "true" : "false"} />
      </button>

      <button
        className="toggle-row"
        aria-pressed={settings.captionRules}
        onClick={() => setSettings({
          ...settings,
          captionRules: !settings.captionRules,
        })}
      >
        <span><Minus size={15} /> Caption rules, not a box</span>
        <i data-on={settings.captionRules ? "true" : "false"} />
      </button>

      <button
        className="toggle-row"
        aria-pressed={settings.enhancedMotion}
        onClick={() => setSettings({
          ...settings,
          enhancedMotion: !settings.enhancedMotion,
        })}
      >
        <span><Sparkles size={15} /> Enhanced motion</span>
        <i data-on={settings.enhancedMotion ? "true" : "false"} />
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
    /* OFF BY DEFAULT SINCE 2026-08-07, ON THE MEASUREMENT (user: "just dark
       mode"). The light stage has no captions box, so `palette_light` darkens
       every CI hue until it just clears 4.5:1 on white -- and the result is
       that they ALL land there. Measured mid-playback on `--sample`, every
       speaker colour rendered between 4.81:1 and 4.86:1: the hues differ but
       their VALUES do not, so at a glance the stage is one wall of mid-grey and
       a speaker change does not announce itself. On 2.4.1's black box the same
       palette runs 4.47:1 to 15.55:1 (yellow 4.81 -> 15.55, cyan 4.82 -> 13.38,
       green 4.86 -> 12.26) and the turns are unmistakable, which is the whole
       job of CWI 2.1. The toggle keeps the light stage one click away. */
    lightStage: false,
    /* Hangul-structural character motion. The Latin wave is Y-dominant --
       `scale(1 - .022w, 1 + .13w)`, a narrow mark stretching upward -- and a
       Hangul block is a square assembly whose grain depends on where its vowel
       sits. With this on, a horizontal-gather block (가) breathes along its
       width and a vertical-gather one (고) upward, per the design factor in
       *Kinetic Typography from the Structural Characteristics of Hangul*.
       DEFAULT ON since 2026-08-11, at the user's request after seeing it.
       It remains a JUDGEMENT, not a measurement -- no probe can tell you a
       stretch axis feels native -- so the toggle stays, and turning it off
       restores the Latin wave exactly. It affects wide script only; English
       never reaches this branch. */
    hangulWave: true,
    /* THE ENHANCED MOTION SYSTEM (2026-08-11). The legacy clock is intact and
       one click away; this is the corrected one, and both corrections are
       measurements against the reference rather than taste:
         - the crest is ANTICIPATED so it peaks ON the word's onset. The film
           peaks +0.04s from the acoustic onset having risen 0.21s before it;
           ours rose a median 0.161s AFTER the turn, i.e. ~0.12s late on every
           word.
         - the colour wipe spans the WHOLE spoken word instead of 72% of it,
           so the boundary lands as the word ends. Measured on the film's
           "To do whatever you tell me, Drill Sergeant" line, its turns track
           the spoken onsets at a mean offset of +0.02s.
       DEFAULT ON (2026-08-12), and this is the second time the default has
       moved -- read both halves before moving it again.

       It went OFF because the user watched `--sample` beside the film and
       judged legacy closer. That was correct for what was on screen: the
       sample played from 0 s, which is the film's TITLES DEMO on black, and
       the demo half uses a per-character wave -- which is what legacy does.

       Measured since, the film uses TWO treatments split at 28 s. After 28 s,
       CWI applied to real footage: 63% of words turn colour in a single frame,
       word top-edges travel 2.6% of a glyph height, weight swings a median of
       -40, and no word scatters its characters at all. Colour and size, both
       per WORD. That is the enhanced clock exactly, and it is the half that
       matches this product -- captions over live speech, not a titles demo.
       `--sample` now starts at 28 s for the same reason.

       Legacy remains one click away and is bit-identical to what it always
       was; it is the right choice for the 0-28 s treatment. */
    enhancedMotion: true,
    /* ROLLING CAPTIONS: newest at the bottom, history rising above it and
       receding as it goes. DEFAULT ON (2026-08-12, at the user's direction).
       Presentation only: it changes where a caption SITS, never how a word
       moves, so no motion figure in docs/MOTION.md depends on it -- and the
       top-anchored stack is one click away in Settings, unchanged.
       The layout contract is unaffected either way: rows still never move once
       laid out and a late word may still only append. What flips is which end
       of the stage is the live one, so the top-anchoring invariant
       (`top` + `max-height` + `justify-content`) is mirrored rather than
       dropped -- see `[data-layout="rolling"]` in globals.css. */
    rollingCaptions: true,
    /* THE CAPTION PLATE, AS TWO RULES INSTEAD OF A FILLED BOX. A deviation
       from CWI 2.4.1, which specifies a 90%-black captions box -- so it is a
       toggle, exactly like the light stage, and `autocwi cc` (which renders
       over real footage, where the plate is what carries legibility) never
       sees it. On this stage the surface behind the captions is already a
       controlled dark field, so the box is drawing a lozenge rather than
       buying contrast. Default ON at the user's request; one click restores
       the compliant box. */
    captionRules: true,
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
  /* The ordered word list the motion clock measures neighbours against -- see
     `CaptionFeed`'s `timingWords`. It is the whole recording, not the retained
     stage window, so no layout decision can reach the hold gate or the pace. */
  const timingWords = useMemo(
    () => paragraphs.flatMap((paragraph) => paragraph.words),
    [paragraphs],
  );
  const glyphBaselineEm = useGlyphBaseline(session.language);
  const wideCharEm = useWideCharEm(session.language);
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
      /* The count is now a CEILING, not the break rule -- the em budget below
         decides. `planStageLayout` sizes the type for the worst case
         `wordsPerRow` words can produce, so a row of short words has room for
         more of them; without raising this, the count would still close every
         row first and the budget could never fill one. Doubling it bounds a
         pathological row (all one-letter words) without binding in practice. */
      stageLayout.wordsPerRow * 2,
      stageMemory,
      {
        rowEm: stageLayout.rowBudgetEm,
        // Measured through the live studio; see `StageWidthBudget`.
        charEm: 0.4343,
        wordEm: 0.4289,
        /* WHAT `fill` HAS TO COVER, MEASURED (2026-08-06), because a row that
           overruns is CLIPPED and not wrapped. Three terms, and only the first
           is the fit:
             - fit residual, now UNBIASED (median +0.005em/word) but spread
               -0.43..+0.44em per word, so ~1em over a 12-word row;
             - the CREST: a word swelling to 1.83x widens its own in-flow cell,
               measured median +1.19em and max +4.92em per row. It does not
               scale with the word count (4.92em on an 11-word row, 0.14em on a
               15-word one) -- it is one loud word -- so a flat reserve is the
               honest model and `spread * sqrt(n)` is not;
             - growth after the row was formed, which the row now RE-BREAKS for
               while its words are still hypotheses, so the reserve no longer
               has to carry it. It only carries growth after a word goes
               `final`, which is rare.
           At 0.92 the reserve was 2.63em against a measured worst case near
           10em, and a row was cut past the stage edge on roughly one capture in
           three. It is 0.82 rather than a tighter number for a MOTION reason,
           not a layout one: 0.87 also clipped nothing (median fill 83% vs 78%),
           but a fuller row sits closer to its break, so more words re-break,
           so more words are rebuilt -- and the held "is" measured 4 of 6 runs
           right at 0.87 against 6 of 6 at 0.82. `WordMemo` makes a rebuild
           value-identical; it does not make one free. */
        fill: 0.82,
        /* Per-character width for East Asian WIDE scripts, measured off the
           live face (`useWideCharEm`). `charEm` above is a LATIN fit and was
           being charged for Hangul too, at 0.4343em against a real 0.9200em --
           so Korean rows carried about twice the words that fit and `nowrap`
           cut the rest with no error and nothing on screen to show for it.
           Undefined until the probe resolves, and `wordWidthEm` then falls back
           to `charEm`, which is the pre-fix behaviour rather than a new one.
           Latin text costs the identical float either way -- there is a test on
           exactly that, because a moved English break would remount words and
           put the motion acceptance figures at risk. */
        ...(wideCharEm !== null ? {wideCharEm} : {}),
      },
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
  // The bearing is read inside `VoiceCompass` now -- the parent no longer
  // renders a number for it, so it no longer needs to know one.
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
      data-hangul-wave={settings.hangulWave ? "true" : "false"}
      data-motion={settings.enhancedMotion ? "enhanced" : "legacy"}
      data-layout={settings.rollingCaptions ? "rolling" : "stack"}
      data-plate={settings.captionRules ? "rules" : "box"}
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
          {/* THE BRACKETED LABEL LIVES IN THE COMPASS NOW (2026-08-13, at the
              user's direction: "[GASP] 이런게 캡션에서 잘 반영이 안되서 그냥
              콤퍼스에서 처리하는게 좋겠다").
              It sat at the foot of the stage as a second, differently-shaped
              caption -- no speaker, no colour, no motion, and outside the row
              stack that every other caption belongs to. A non-speech sound is
              an event in the ROOM rather than a word in the line, and the dial
              is the instrument that draws the room.
              THIS IS A DEVIATION FROM CWI 2.4.4, which puts sound effects in
              white brackets among the captions. It is a placement change, not
              a removal: the same label, the same brackets, the same white, the
              same vibration -- moved to where it is legible. `autocwi cc`,
              which renders to the design system's own layout, is untouched. */}
          <CaptionFeed
            paragraphs={stageParagraphs}
            timingWords={timingWords}
            speakerColors={speakerColors}
            intensity={settings.motionIntensity}
            runtime={runtime}
            clockEpoch={clockEpoch}
            scheduleWord={scheduleWord}
            playheadMs={playheadMs}
            transcript={view === "transcript"}
            reducedMotion={settings.reducedMotion}
            hangulWave={settings.hangulWave}
            enhancedMotion={settings.enhancedMotion}
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
        <section className="rail-section compass-section">
          {/* The arrow glyph went with the heading: an icon alone in an
              otherwise empty row is decoration, and the dial already draws a
              bearing. */}
          <header className="rail-heading">
            <h2>Voice compass</h2>
          </header>
          <div className="compass-layout">
            <VoiceCompass level={level} color={activeColor}
                          speakerColors={speakerColors}
                          sound={speechActive ? null : model.sound} />
            {/* THE DIAL IS THE WHOLE READOUT NOW (2026-08-13).
                It has lost, in order: `Direction` (a label on a number that
                already ended in a degree sign), `Voice profile` (the voice
                described in prose the captions carry -- delivery is weight and
                size under CWI 2.3), and finally the number itself. `231°` sat
                beside a dial that was already pointing at it, and with no
                array it read `0°`, which is a bearing nobody measured.
                Twelve ticks put the needle inside 30° at a glance, which is
                the resolution "who is where" actually needs. */}
          </div>
        </section>

        {/* THE LEVEL SITS BELOW THE COMPASS (2026-08-13, at the user's
            direction). In the rolling layout the rail is bottom-aligned and
            the reader's eye is at the bottom of the stage, so the section
            nearest them should be the one they least need to look at -- "is
            the mic working" is a glance, "who is where" is the thing being
            read. */}
        <section className="rail-section signal-section">
          <header className="rail-heading">
            <h2>Voice activity</h2>
          </header>
          <SignalWaveform values={waveform} />
          {/* THE TWO Hz READINGS ARE GONE (2026-08-13). "215 Hz pitch" and
              "2641 Hz color" are engineering telemetry: a viewer cannot act on
              either, and both channels are ALREADY on screen in the form that
              matters -- pitch is the caption's weight and colour-brightness is
              its texture, per CWI 2.3. The rail was restating the captions in
              numbers. Level stays because it is the one reading that says
              whether the mic is working at all. */}
          {/* ONE LINE, NOT TWO CORNERS. The status word sat top-right and the
              level sat bottom-left, and they are the same fact at two
              resolutions: `IDLE` is the summary, `-17.6 dBFS` is the number
              behind it. Read together they answer "is the microphone working"
              once instead of twice. */}
          <div className="level-line" data-good={inputGood ? "true" : "false"}>
            <strong>{level.status ?? "idle"}</strong>
            <span>{number(level.rms_db, -72).toFixed(1)} dBFS</span>
          </div>
        </section>

        {/* ACTIVE SPEAKERS IS GONE (2026-08-13, at the user's direction).
            Every speaker it listed is already on screen wearing their colour,
            in the captions and on the compass ring -- CWI 2.1 makes colour THE
            speaker signal, so a legend restating it is redundant by the design
            system's own logic. What the section added on top was
            `provisional · 95% confidence`, which is the system talking about
            its own certainty: operator information, and it belongs with the
            operator.
            The `speakers` memo went with it. It fed nothing else --
            `useSpeakerColors` reads `paragraphs` directly, which is what the
            captions and the compass ring have always been coloured from. */}
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
