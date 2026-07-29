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
  pre-capture language session, real-time voice history, bounded reveal
  scheduler, and reconnect diagnostics;
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

- A semantic word gets motion once, at first visible paint.
- A late speaker/color decision cannot replay geometry.
- At most two words physically animate; a fresh third word waits hidden for a
  slot and then first appears with its cue. No current word silently skips
  motion, and no already-visible word pops late.
- A word box is frozen at normal-font width while its inner glyph animates.
- Size, weight, width, and character synchronization use separate temporal
  envelopes and return exactly to normal.
- Frozen force/attack/contour/flow/texture select different rising, falling,
  sustained, forceful, gentle, or textured glyph paths and independent
  weight/width clocks. Presentation family selection does not lower or replace
  the conservative semantic delivery-profile thresholds.
- `steady` words retain only 30% of the additional voice-shaped gain; every
  active word still gets the full 10% / 0.20 em synchronization cue. Expressive
  paths start near the baseline with zero-slope easing; no profile may appear
  already displaced on its first frame.
- The delivery signature for a visible word cannot change on a later
  transcription, timing, colour, or speaker revision.
- Speaker corrections repartition paragraphs by stable word identity.
- Transcript keeps complete speaker/utterance paragraphs.
- Stage uses stable eight-word row boundaries, retains four rows, and never
  exposes more than two mutable hypothesis words.
- Diarization never partitions Stage geometry; speaker updates may recolor or
  relabel words without changing row keys.
- Crossing a row boundary must preserve semantic word keys and cannot replay
  a completed word's motion.
- Mono input never fabricates a compass direction.
- Language is selected before capture and cannot change under an active decoder.
- Korean captions use the local Noto Sans KR variable-weight face; Roboto Flex
  remains the English CWI variable font. Both fall back to system fonts only
  when their one-time download is missing.
