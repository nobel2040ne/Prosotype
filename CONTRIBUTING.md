# Contributing

Welcome. This guide covers how to set up, the conventions we follow, and the few
non-negotiable rules that keep the captions correct. If you're brand new, do
[docs/ONBOARDING.md](docs/ONBOARDING.md) first.

## Setup

See [docs/ONBOARDING.md](docs/ONBOARDING.md) for the full install. In short:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py
.venv/bin/python scripts/fetch_streaming_model.py
npm --prefix web install
```

The virtual environment is `.venv/` (Python 3.11). Always use `.venv/bin/python`,
never the system Python.

## Before you push

Run both test suites locally:

```bash
.venv/bin/python -m pytest        # offline, ~4 s
npm --prefix web run check        # lint + UI reducer tests + static build
```

Both must pass. The Python suite is **offline by design** — synthetic audio, no
model loads, no network. Never add a test that downloads a model or hits the
network.

## The ground rules

These are the invariants the project is built on. Breaking one usually means the
captions look broken in a way tests don't always catch, so treat them as hard
constraints.

### Stay local and offline

No cloud inference, no telemetry. The only permitted network access is the
one-time model-weight and font downloads. Don't add a runtime that phones home.

### All tunable values live in `config.yaml`

Colors, size ranges, motion timing, thresholds — everything the design system
specifies goes in `config.yaml`, with a comment citing the CWI section number.
Never hardcode a mapping value in Python or JavaScript. If you see a magic number
in code, move it to config.

### The CaptionSpec is a versioned contract

`autocwi/schema.py` defines `CaptionSpec` (`spec.json`) and the live SSE `word`
events. Renderers and the future haptic module consume **only** this contract —
never the internal model objects. Extend the schema with *optional* fields only;
a breaking change requires a version bump.

### Captions must not "re-animate"

A word gets its motion **once**, at first paint, and then settles to normal
typography. After that, later corrections (spelling, timing, speaker, color) may
update the word in place but **must never restart its motion**. A settled word's
size, weight, and width return exactly to normal and stay there. This is the
single most important visual invariant — see
[docs/LIVE.md](docs/LIVE.md) and the frontend rules in
[web/README.md](web/README.md).

### The design system PDF outranks everything

`docs/cwi-design-system-v1.0.pdf` is the source of truth for how captions look
and move. Read the relevant section before changing any typography or motion —
several rounds of past work were spent reverse-engineering values that were
stated outright in the PDF. See [docs/SOURCES.md](docs/SOURCES.md)
for the order of authority among the PDF, recordings, and templates.

### Language is chosen before capture

English or Korean is selected before any recognizer loads, and locked for the
session. Don't make the selector cosmetic or hot-swap a recognizer mid-capture.

### Pin your dependencies; seed randomness

Versions are pinned in `requirements.txt`. Seed anything stochastic so runs are
reproducible.

## Code conventions

- **Match the surrounding code.** Follow the existing naming, structure, and
  comment density of the file you're editing.
- **Offline stages stay independently runnable.** Each offline pipeline stage
  (`transcribe`, `diarize`, `prosody`, `fuse`) reads and writes JSON in its
  `--out` directory and can run on its own.
- **The frontend must stay statically exportable.** `web/` builds to a static
  export that Python serves. Don't add a required Node server, route handler,
  server action, cookie, or rewrite. See [web/README.md](web/README.md).
- **Two renderers, one motion contract.** The Next.js studio and the legacy
  renderer consume the same SSE contract and must keep the same
  finality/revision behavior.

## Commits & pull requests

- Work on a branch, not `main`.
- Keep commits focused; write a clear message describing the *why*.
- A pull request should explain what changed, how you verified it (which tests,
  and — for visual changes — a screenshot or the render-diagnostics output), and
  which config values moved if any.
- For visual/motion changes, **don't tune by eye**. Use the motion tuner
  (`.venv/bin/python -m autocwi tune`), the render probe
  (`scripts/live_render_probe.py`), or a headless screenshot. See
  [docs/LIVE.md](docs/LIVE.md) for the measurement recipes.

## Getting help

- Terminology: [docs/GLOSSARY.md](docs/GLOSSARY.md)
- How the system fits together: [ARCHITECTURE.md](ARCHITECTURE.md)
- Design intent and exact values: [docs/SOURCES.md](docs/SOURCES.md)
  and [docs/DESIGN.md](docs/DESIGN.md)
