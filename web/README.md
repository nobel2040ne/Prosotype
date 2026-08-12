# Prosotype Studio

The product frontend for Prosotype. It is a Next.js App Router application,
statically exported into `web/out` and served by the existing Python live
process. Recognition, diarization, prosody, and event replay remain in Python;
the browser consumes their same-origin `/events` Server-Sent Event stream.
Before capture, the studio also owns the English/한국어 session choice; Python
does not load a recognizer until that choice reaches the local session API.

## Build

```bash
npm install
npm run check
```

`npm run check` runs ESLint, the TypeScript reducer tests, and the production
static export. `autocwi live` automatically selects `web/out/index.html` when
it exists. If it does not, the server falls back to the self-contained legacy
renderer.

The production routes are:

- `/` — Next.js studio;
- `/events` — replayable live SSE;
- `/session` — current startup/capture language state;
- `/session/language` — one-time language selection (`POST`);
- `/runtime-config.json` — safe presentation values derived from `config.yaml`;
- `/RobotoFlex.ttf` — local CWI variable font;
- `/NotoSansKR.ttf` — local Korean variable-weight caption font;
- `/legacy` — original diagnostic renderer.

## Development

Run the Python backend and Next development server separately:

```bash
.venv/bin/python -m autocwi live --sample --no-open
NEXT_PUBLIC_AUTOCWI_ORIGIN=http://127.0.0.1:7337 npm --prefix web run dev
```

Then open `http://localhost:3000`. The Python event and runtime endpoints allow
local cross-origin development; the exported production build uses the same
origin and needs no environment variable.

Open `/?demo=1` for a deterministic UI-only preview. It exercises two speakers,
all delivery-path families, the live waveform, and both voice indicators
without loading speech models.

## Structure

- `src/components/live-studio.tsx` — application shell, caption stage,
  transcript, signal rail, settings, and responsive presentation;
- `src/hooks/use-caption-stream.ts` — EventSource lifecycle, runtime config,
  pre-capture language session, real-time voice history, and reconnect
  diagnostics;
- `src/lib/caption-clock.ts` — the pure read-ahead playhead;
- `src/lib/caption-store.ts` — pure revision-aware event reducer and reveal
  deadline policy;
- `src/lib/caption-paragraphs.ts` — pure speaker/utterance paragraph
  partitioning plus the bounded, fixed-boundary audience stack;
- `src/app/globals.css` — visual system, responsive layouts, independent
  size/weight/width motion envelopes, and reduced-motion behavior.

The app follows Next.js static-export constraints so Python remains the only
runtime server. See the official
[Next.js static export guide](https://nextjs.org/docs/app/guides/static-exports).

## Non-negotiable caption behavior

Motion rules are the summary; [../docs/MOTION.md](../docs/MOTION.md) is the
contract and [../docs/LIVE.md](../docs/LIVE.md) covers the stack in depth.

- A word animates at its **recorded onset**, scheduled by the playhead through a
  single `animation-delay` — not at first paint. There is no reveal queue, no
  slot, and **no concurrency cap**: words animate concurrently when speech is
  fast (measured peak 4). No current word silently skips motion, and no
  already-visible word pops late.
- A late speaker/colour decision cannot replay geometry. Corrections — spelling,
  timing, attribution, replay — reuse the same word node.
- **Everything is frozen at first sight**: duration, axes, sweep, hold gap and
  turn moment are computed once and must survive a remount. `WordMemo` carries
  `duration` and `holdAmount` across a row change, which unmounts the word.
- A word box is frozen at normal-font width while its inner glyph animates, so
  motion cannot reflow a row.
- Size, weight, width, and the synchronization cue use separate temporal
  envelopes and return exactly to normal. Every active word gets the full
  **15%** (§2.2.3) cue; §2.3's voice-shaped size and weight apply **per word,
  uniformly**, and only the character wave is per character.
- Expressive paths start near the baseline with zero-slope easing; no profile may
  appear already displaced on its first frame. The delivery signature for a
  visible word cannot change on a later transcription, timing, colour, or speaker
  revision.
- **Text may be revised only while a word is still ahead of the playhead.**
  Behind it is frozen history — `settledTextRef` enforces it.
- Stage rows are broken on a **measured em budget** (3–13 words), retain **as
  many rows as the stage measures it can hold** (9 light / 8 dark at 1440×900),
  and are anchored by word id so a row start never moves. A late word may only
  append, never insert.
- Diarization never partitions Stage geometry; speaker updates may recolor or
  relabel words without changing row keys. Speaker corrections repartition
  Transcript paragraphs by stable word identity, and Transcript keeps complete
  speaker/utterance paragraphs.
- Crossing a row boundary must preserve semantic word keys and cannot replay a
  completed word's motion.
- Grey is reserved for `speaker == null`. A speaker-carrying word whose tracker
  status is unknown displays as `provisional` — never grey, or words that turned
  while attribution was pending stay grey forever.
- Mono input never fabricates a compass direction.
- Language is selected before capture and cannot change under an active decoder.
- Korean captions use the local Noto Sans KR variable-weight face; Roboto Flex
  remains the English CWI variable font. Both fall back to system fonts only
  when their one-time download is missing.

## The stage is the only thing in the workspace

Removed at the user's request (2026-07-30, 2026-08-06) and **not to be re-added**:
the nav rail, the workspace header, the transport bar, the `AUDIENCE VIEW` stage
label, the stage grid and its four corner brackets, the rail's "system" section,
the compass's `Hardware: Mono input` line and `front` label, and `.caption-stage`'s
card inset, border and radius. Measured at 1440×900, the stage went 974×596 →
**1104×757** and the caption type 37.4 → **29.2px**.

The studio has **one** framing system — the full-bleed hairline grid (the topbar's
bottom rule, the rail's left rule, the window edges). The stage's border box *is*
the workspace box; a floating panel repeating that boundary 16px inside it drew
the frame twice.

**`.line-voice-orb` is gone — do not re-add it.** It was a second copy of the
compass's channels rendered just past the active row, and it was the one live
instrument inside the caption surface. No channel was lost. It was out of flow, so
removing it changed no row geometry — but `.caption-feed`'s right padding is
**deliberately unreclaimed**: `--caption-gutter-em` (2.50 = .60 left + 1.90 right)
absorbs a row-final word's mid-pop overhang, measured up to .842em, and the last
time that number moved, words were silently clipped on ~15% of row-samples.
Measure with `clip_probe.py` through live playback before touching it.

## The 2026-08-13 design pass, in rules

The reasoning, the measurements and the two things that were measured wrong are
in the decision log. What the pass settled:

- **The chrome recedes.** A reading is not a control: `-22.4 dBFS`, `LIVE`,
  `00:01` and the status word are things the studio tells you, so none of them
  wears a button's border, fill or pill. Rail sections divide by whitespace.
- **One accent, and it belongs to the captions.** Speaker colour is CWI 2.1 and
  the only colour on screen that means anything. Chrome colour is reserved for
  a state needing attention; the healthy state is quiet.
- **The rail says two things: is the mic working, and who is where.** The
  speaker roster went — every speaker it listed is already on screen wearing
  their colour. The `Hz pitch` / `Hz colour` readings went — both are on screen
  already as the caption's weight and texture under CWI 2.3.
- **The dial is the whole readout.** No `Direction` label, no `Voice profile`
  prose, no numeric bearing. Twelve ticks put the needle inside 30° at a
  glance, which is the resolution "who is where" needs. Its size is a clamp,
  not a fixed value, and the ticks are full-size rotating layers so the scale
  follows the diameter.
- **The bracketed sound label lives in the dial**, not at the foot of the
  stage. A non-speech sound is an event in the room, and the dial draws the
  room. A **placement** deviation from CWI 2.4.4, not a removal; `autocwi cc`
  is untouched.
- **The stage is the darkest surface.** With §2.4.1's plate replaced by rules,
  the stage is the caption's ground and carries the contrast the box did.
- **`Settings → Caption rules, not a box`** replaces the plate with a hairline
  above and below the live line. A toggle-gated deviation from §2.4.1, gated
  exactly like the light stage, and `autocwi cc` never sees it — that renderer
  draws over real footage, where the filled plate is what carries legibility.
- **The rail yields before the captions do.** `--rail-width` is a clamp because
  `--caption-width-cap` derives from the workspace's container width; a fixed
  rail meant every pixel a narrower window cost came out of the stage.
- **Korean shares the motion system.** The render branches on script in exactly
  five places, all forced by what a Hangul syllable is: the wide-script colour
  turn (a block is 0.91em against Latin's 0.43em, so a per-glyph step is a
  switch rather than a sweep), `waveLead`, `groupLift`, the Hangul wave toggle,
  and `wideCharEm`. Everything else is one code path.

## Two design systems, and the boundary is the word

The chrome follows the Apple design analysis; the captions follow CWI, which
outranks it. The line is literal: **anything inside `.caption-word` is CWI,
everything else is Apple.** Never let an Apple token reach `.caption-word`, and
never let a CWI token style a button. Apple's "UI recedes so the product can
speak" is why the captions carry no box, no frame and no per-block label — here
the captions *are* the product.

Project-specific deviations and traps:

- One accent only — Action Blue `#0066cc` on light, Sky Link Blue `#2997ff` on
  dark (Action Blue measures **2.68:1** on a dark tile, which is why the analysis
  reserves a separate on-dark accent).
- Radius on the 0/5/8/11/18/pill scale, and **`--r-md` (11px) has no caller on
  purpose** — the analysis calls it the rare Pearl Button step, so dense rail
  cards are `--r-sm` and large surfaces `--r-lg`. Five `--r-md` callers was the
  "mixed radii grammar" the Don'ts name.
- Weight ladder 300/400/600/700 — **500 is deliberately absent**, so no
  560/590/650/680.
- **No shadows and no decorative gradients on chrome**; surface-colour
  alternation is the divider. A shadow is allowed only where it is a DATA channel
  (the compass halo carries periodicity).
- **Default and active states only.** The analysis documents no hover, so the
  studio has none. `button:active { transform: scale(.95) }` once, globally, is
  the system's only transform micro-interaction.
- **Tracking is subtle.** The ramp's entire negative range is `-.12px .. -.374px`
  (≈ -.005em .. -.011em); `-.035em` on a 21px title reads as cramped. Prefer the
  literal px ramp over hand-rolled em.
- The analysis's 17px body is a marketing-page pace and does not transplant onto
  a dense studio rail. What does transplant is its FLOOR: nothing below the 10px
  micro-legal rung.
- The language gate's `English`/`한국어` is a **button label, not a caption
  sample** — both are `--font-ui`.

## The light stage

`Settings → Light stage` **defaults OFF since 2026-08-07**; the compliant dark
stage is what ships. It writes `data-theme` onto `document.documentElement`, and
`--tint` inverts all 14 hairline/inset/grid tints at once.

It has **no captions box at all** — `--caption-box` is `transparent`, type sits
directly on `--stage-bg`, and the per-block speaker label is hidden on Stage — so
it contradicts CWI **§2.4.1** outright, and consequently §2.1.1/§2.1.2, because
the CI palette is built for that black box. Measured against `#FAFAF8`, CI Yellow
is **1.19:1**, Green 1.52:1, Blue 1.39:1.

`palette_light`/`palette_support_light` keep each CI hue and darken only its value
to ≥4.5:1. Both arrive through `/runtime-config.json` — **do not hardcode either
palette in CSS or TSX**, and `speakerColor()` returns `var(--caption-unknown)` /
`var(--accent)` rather than literals so the fallbacks follow the theme too.
Turning the toggle off must restore the exact CI values and the black box.
`--stage-bg` is the surface `palette_light` is measured against: change one and
re-derive the other.

**Why it no longer defaults on.** Measured mid-playback — not on a finished stage,
which replays every word settled and neutral — every speaker colour on the light
stage renders between **4.81:1 and 4.86:1**. That is `palette_light` working
exactly as designed, and it is also the defect: each hue is darkened until it just
clears 4.5:1, so they all arrive at the same *value*, and a page of captions is
one wall of mid-grey in which a speaker change does not announce itself. On the
black box the same palette spans **4.47:1 to 15.55:1** and the turns are
unmistakable. The deviation did not merely trade §2.4.1 away — it flattened
§2.1's signal.

**CI Red is the one colour that got worse: 4.84:1 → 4.47:1**, i.e. just under AA,
and it is the one hue `palette_light` left unchanged because it already passed on
white. Flagged, not fixed. Do not "fix" it by lightening toward the CI spec
without re-measuring both stages.

The theme also changes **layout** — dark adds .22em of row padding, about one
whole row over a full stack — so a theme swap is a row-composition change, the
theme is a dependency of `useStageLayout`, and a `ResizeObserver` on the stage
cannot see it. Caption type goes 29.2 → **25.6px** with 59 → 70 characters per
line. Re-run the six-capture motion check after any theme default change.

`autocwi cc` and the legacy diagnostics page are **not** themed: `cc` is the
design system's reference renderer, and §2.4.1 applies to it literally.
