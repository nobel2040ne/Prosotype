# Contributing

How to get running, the conventions, and the few rules that keep the captions
correct. If a term is unfamiliar, check the
[glossary](ARCHITECTURE.md#glossary).

## Setup

You need **Python 3.11 exactly**, Node.js (any recent LTS), and ffmpeg
(`brew install ffmpeg`). macOS on Apple Silicon additionally builds a small
Swift helper for native diarization; everywhere else falls back to a portable
backend and captions still run.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/fetch_font.py             # variable fonts, ~12 MB
.venv/bin/python scripts/fetch_streaming_model.py  # ASR + diarization, ~2.2 GB
npm --prefix web install
npm --prefix web run build
```

Always use `.venv/bin/python`, never the system Python. After the downloads the
app is fully offline. `fetch_streaming_model.py` takes `--korean-only`,
`--speaker-only`, `--sortformer-only` and `--onset-only` if you want the parts
separately.

The recorded-video pipeline needs two more, only if you run it: Whisper `small`
downloads on first `transcribe`, and pyannote diarization needs an `HF_TOKEN`
(accept the terms on `pyannote/speaker-diarization-3.1` and
`pyannote/segmentation-3.0`). Inference stays local — the token authorises the
download and nothing else. Without it, `--stub` gives a model-free run.

## See it run

```bash
.venv/bin/python -m autocwi live --sample              # bundled clip, no mic
.venv/bin/python -m autocwi live --sample --lang ko    # Korean clip + model
.venv/bin/python -m autocwi live                       # your microphone
.venv/bin/python -m autocwi live --list-devices        # if the wrong mic is picked
```

This opens `http://127.0.0.1:7337/`. Words appear before they are spoken, turn
to a speaker colour as they are said, and pop as they turn.

The first live run on macOS asks for microphone permission per terminal app. A
busy port is almost always a leftover process: `pkill -f "autocwi live"`.

For the *exact* reference motion — text known in advance, so nothing is
approximated — run the closed-caption renderer:

```bash
.venv/bin/python -m autocwi cc assets/reference_specs/demo.json
```

## Before you push

```bash
.venv/bin/python -m pytest        # offline, ~4 s
npm --prefix web run check        # lint + UI reducer tests + static build
```

Both must pass. The Python suite is **offline by design** — synthetic audio, no
model loads, no network — and `tests/` mirrors `autocwi/` module for module.
Never add a test that downloads a model or reaches the network.

## The ground rules

Breaking one of these usually makes the captions wrong in a way the tests do not
catch, so treat them as hard constraints.

**Stay local and offline.** No cloud inference, no telemetry. The only permitted
network access is the one-time model and font downloads, and the LAN link to the
hardware node.

**All tunable values live in `config.yaml`**, with a comment citing the CWI
section number. Never hardcode a mapping value in Python or JavaScript. A magic
number in code is a bug to report.

**The CaptionSpec is a versioned contract.** `autocwi/schema.py` defines
`spec.json` and the live SSE `word` events. Renderers and the haptic module
consume only this contract, never the internal model objects. Extend with
*optional* fields; a breaking change bumps the version.

**A settled caption never re-animates.** A word gets its motion once, at its own
moment on the acoustic timeline, and then settles. Later corrections — spelling,
timing, speaker, colour — may update it in place but must never restart its
motion. This is the single most important visual invariant; see
[docs/MOTION.md](docs/MOTION.md) and [web/README.md](web/README.md).

**The design system PDF outranks everything.**
`docs/reference/cwi-design-system-v1.0.pdf` is the source of truth for how captions look
and move. Read the relevant section before changing any typography or motion —
several rounds of past work were spent reverse-engineering values the PDF states
outright. [docs/RESEARCH.md — sources](docs/RESEARCH.md#sources) gives the order
of authority among the PDF, the recordings and the template.

**Language is chosen before capture** and locked for the session. Do not make
the selector cosmetic or hot-swap a recognizer mid-capture.

**Pin dependencies; seed randomness.** Versions are pinned in
`requirements.txt`.

## Code conventions

- **Match the surrounding code** — its naming, structure and comment density.
- **Offline stages stay independently runnable.** Each of `transcribe`,
  `diarize`, `prosody` and `fuse` reads and writes JSON in its `--out` directory
  and can run alone.
- **The frontend must stay statically exportable.** `web/` builds to a static
  export that Python serves; no required Node server, route handler, server
  action, cookie or rewrite. See [web/README.md](web/README.md).
- **Two renderers, one motion contract.** The studio and the legacy renderer
  consume the same SSE contract and must keep the same finality and revision
  behaviour.

## Making a change

Config is the best place to start, because every tunable lives in one file:
change a value in `config.yaml`, re-run `live --sample`, watch the result, then
run the tests.

For anything visual, **do not tune by eye**. `scripts/` holds a probe for each
question — clipping, colour, adjacent-row clearance, word overlap, whether a
settled word moved again — and every one takes `--broken` or an equivalent
negative control. **Run that first: a check that has never been seen to fail is
not evidence.**

## Commits & pull requests

- Work on a branch, not `main`.
- Keep commits focused; the message should say *why*.
- A pull request explains what changed, how you verified it (which probes, and
  for visual changes a screenshot), and which config values moved.

## Where to go next

- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit together and the data
  contract every component agrees on.
- [docs/MOTION.md](docs/MOTION.md) — the motion contract. Read it before
  changing anything a caption does.
- [docs/LIVE.md](docs/LIVE.md) — live mode in depth.
- [docs/RESEARCH.md — sources](docs/RESEARCH.md#sources) — the materials this
  implementation derives from.
