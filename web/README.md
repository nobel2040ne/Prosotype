# Weave Studio

The product frontend: a Next.js App Router app, statically exported to `web/out` and served by the Python live process. Recognition, diarization, prosody and replay stay in Python; the browser consumes the same-origin `/events` SSE stream. The studio also owns the pre-capture language choice — Python loads no recognizer until that reaches `/session/language`.

## Build

```bash
npm install && npm run check     # lint + reducer tests + static export
```

`autocwi live` picks up `web/out/index.html` when it exists and falls back to the legacy renderer when it does not.

Routes: `/` studio · `/events` replayable SSE · `/session` + `/session/language` language state · `/runtime-config.json` presentation values from `config.yaml` · `/RobotoFlex.ttf` + `/NotoSansKR.ttf` · `/legacy` diagnostics.

## Development

```bash
.venv/bin/python -m autocwi live --sample --no-open
NEXT_PUBLIC_AUTOCWI_ORIGIN=http://127.0.0.1:7337 npm --prefix web run dev
```

`/?demo=1` is a deterministic UI-only preview — two speakers, every delivery path, both voice indicators, no models.

**The app must stay statically exportable.** No required Node server, route handler, server action, cookie or rewrite.

## Structure

| | |
|---|---|
| `components/live-studio.tsx` | shell, stage, transcript, rail, settings |
| `hooks/use-caption-stream.ts` | EventSource lifecycle, runtime config, language session |
| `lib/caption-clock.ts` | the pure read-ahead playhead |
| `lib/caption-store.ts` | pure revision-aware event reducer |
| `lib/caption-paragraphs.ts` | paragraph partitioning + the bounded stage stack |
| `app/globals.css` | the visual system and the motion envelopes |

## Caption invariants

[the project page](https://nobel2040ne.github.io/Weave/) shows these running.

- **A word animates at its recorded onset**, scheduled by the playhead through one `animation-delay` — not at first paint. No reveal queue, no slot, no concurrency cap: fast speech overlaps, and that is the design system working.
- **Everything is frozen at first sight** — duration, axes, sweep, hold gap, turn moment — and must survive a remount. `WordMemo` carries them across a row change, which unmounts the word.
- **Corrections reuse the word node.** Spelling, timing, attribution and replay may update a word but never replay its geometry.
- **Text may be revised only while a word is ahead of the playhead.** Behind it is frozen history; `settledTextRef` enforces it.
- A word box is frozen at normal-font width while its glyph animates, so motion cannot reflow a row.
- Size, weight, width and the 2.2.3 cue have separate envelopes and return exactly to normal. Every active word gets the full 15% cue; 2.3's size and weight apply per word, uniformly. Only the character wave is per character.
- **Rows never move once laid out.** Rows break on a measured em budget (3–13 words), keep as many as the stage measures it can hold, and are anchored by word id — a late word may only append, never insert.
- Diarization never partitions stage geometry. Speaker updates recolour without changing row keys.
- **An endpoint is one commit, not one per word.** The server publishes an endpoint word by word — 74 SSE messages inside 100 ms — and each commit forces a synchronous layout, so `useCaptionStream` queues caption events and applies them in one reducer pass per animation frame. Word turns are unaffected: they sit on the acoustic clock, not on arrival.
- **Grey is reserved for `speaker == null`.** A speaker-carrying word whose tracker status is unknown renders `provisional`, or words that turned while attribution was pending stay grey forever.
- Mono input never fabricates a compass direction.
- Language is selected before capture and cannot change under a live decoder.
- Korean uses the local Noto Sans KR variable face; Roboto Flex stays the English CWI font.

## The stage

The workspace holds captions and nothing else — no nav rail, header, transport bar, stage label, grid or corner brackets, and no card border around `.caption-stage`. The studio has **one** framing system, the full-bleed hairline grid, and the stage's border box *is* the workspace box. At 1440×900 that gives the stage **1104×757** and caption type at **29.2 px**.

`.caption-feed`'s right padding is deliberately unreclaimed: `--caption-gutter-em` absorbs a row-final word's mid-pop overhang, measured up to .842em. Shrink it and words clip silently — measured on ~15% of row-samples.

## Two design systems

The chrome follows the Apple design analysis; the captions follow CWI, which outranks it. **Anything inside `.caption-word` is CWI, everything else is Apple.** Never let an Apple token reach a caption, or a CWI token style a button.

- One accent: Action Blue `#0066cc` on light, Sky Link Blue `#2997ff` on dark (Action Blue measures 2.68:1 on a dark tile).
- Radius on the 0/5/8/11/18/pill scale; `--r-md` has no caller on purpose.
- Weight ladder 300/400/600/700 — **500 is deliberately absent**.
- No shadows and no decorative gradients on chrome; surface alternation is the divider. A shadow is allowed only where it is a data channel.
- Default and active states only — the analysis documents no hover.
- Nothing below the 10px micro-legal rung.

## Light stage

`Settings → Light stage` defaults **off**; the compliant dark stage ships. It has no captions box at all, so it contradicts §2.4.1 and consequently §2.1 — the CI palette is built for that black box. Against `#FAFAF8`, CI Yellow measures **1.19:1**.

`palette_light` darkens each hue to ≥4.5:1, which works and is also the defect: measured mid-playback every speaker colour lands between **4.81:1 and 4.86:1** — one wall of mid-grey where a speaker change does not announce itself. On the black box the same palette spans 4.47:1 to 15.55:1.

Both palettes arrive through `/runtime-config.json`; **do not hardcode either**. The theme also changes layout — dark adds .22em of row padding, about one row over a full stack — so it is a dependency of the layout hook, and a `ResizeObserver` cannot see it. `autocwi cc` is never themed.
