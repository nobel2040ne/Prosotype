# Prosotype

Prosotype turns live speech into **expressive captions** for Deaf and
hard-of-hearing viewers. It automates the official
[Caption with Intention](https://captionwithintention.org) (CWI) design system:
captions that show *who* is speaking (color), *when* each word is spoken
(motion), and *how* it is said (typography that tracks loudness and pitch).

The **primary mode is live captions** — a microphone streams into CWI-styled
open captions in the browser, in English or Korean. A batch pipeline for
recorded video is kept as the reference generator for the caption data contract.

Everything runs **locally and offline**. No cloud inference, no telemetry. The
only network access is one-time downloads of model weights and fonts.

> New here? Start with **[CONTRIBUTING.md — first day](CONTRIBUTING.md#your-first-day)** for a
> step-by-step first run, and **[ARCHITECTURE.md — glossary](ARCHITECTURE.md#glossary)** for the
> terminology.

## What it does

The renderer follows the **CWI Design System V1.0**
([PDF](docs/cwi-design-system-v1.0.pdf)) across its three pillars:

- **Attribution** — each speaker gets a distinct color (yellow, green, blue,
  pink, red, orange, in wheel order).
- **Synchronization** — a word turns to its speaker's color at the moment it is
  spoken, with a brief size "pop" and lift that returns to normal.
- **Intonation** — a variable font carries the voice: louder speech is larger,
  pitch changes weight and width.

Captions sit in a dark box in the lower area of the frame, as the design system
specifies.

## Quick start

Requires **Python 3.11**, **Node.js**, and **ffmpeg** on macOS (Apple Silicon
recommended) or Linux.

```bash
brew install ffmpeg                                  # if not already installed
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py               # one-time: English + Korean fonts
.venv/bin/python scripts/fetch_streaming_model.py    # one-time: live ASR + diarization models
npm --prefix web install                             # one-time: studio dependencies
npm --prefix web run build                           # build the browser UI
```

Then run the bundled demo — no microphone needed:

```bash
.venv/bin/python -m autocwi live --sample            # opens http://127.0.0.1:7337/
```

Full setup notes (download sizes, offline extras, gated model tokens) are in
**[CONTRIBUTING.md — first day](CONTRIBUTING.md#your-first-day)**.

## Common commands

```bash
# Live captions (primary mode)
.venv/bin/python -m autocwi live                     # microphone; pick English/한국어 first
.venv/bin/python -m autocwi live --lang ko           # skip the picker, use Korean
.venv/bin/python -m autocwi live --sample            # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --list-devices      # choose a microphone

# Reference renderer (exact CWI motion from a finished spec)
.venv/bin/python -m autocwi cc assets/reference_specs/demo.json
.venv/bin/python -m autocwi tune                     # motion tuner with live sliders

# Offline pipeline (generates spec.json)
.venv/bin/python -m autocwi run clip.mp4 --out out/ --speakers 2

# Tests
.venv/bin/python -m pytest                           # fast, offline, no model loads
npm --prefix web run check                           # lint + UI reducer tests + build
```

## Project map

```
autocwi/          Python runtime: live engine, offline pipeline, renderers, schema
  live.py           live capture → recognition → SSE server (primary mode)
  cli.py            subcommands: live, run, cc, tune, transcribe, diarize, prosody, fuse
  schema.py         the CaptionSpec data contract (versioned)
  ccpage.py         cc reference renderer
  sortformer.py     bridge to the native diarization helper
web/              Next.js studio (the browser UI); static-exported and served by Python
native/           Swift helper for native diarization on Apple Silicon
scripts/          one-time model/font downloads, benchmarks, spec derivation
assets/           fonts, bundled audio samples, reference specs
config.yaml       ALL tunable mapping values (never hardcoded in code)
docs/             design system, architecture, onboarding, glossary, research
tests/            offline test suite (synthetic audio, no model loads)
```

A fuller breakdown of every module is in
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Documentation

| Document | What's in it |
|---|---|
| [CONTRIBUTING.md — first day](CONTRIBUTING.md#your-first-day) | Day-one setup and first run |
| [ARCHITECTURE.md — glossary](ARCHITECTURE.md#glossary) | Definitions of every domain term |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, modules, and the data contract |
| [docs/LIVE.md](docs/LIVE.md) | How live mode works in depth |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, conventions, ground rules, PR flow |
| [docs/TESTS.md](docs/TESTS.md) | Test layout and how to run/regenerate them |
| [docs/RESEARCH.md — sources](docs/RESEARCH.md#sources) | The primary source materials |
| [docs/MOTION.md](docs/MOTION.md) | **The motion contract** — five channels, the rules, the acceptance figures |
| [docs/DESIGN.md](docs/DESIGN.md) | PDF values by section, plus superseded interpretation (read MOTION.md first) |
| [docs/RESEARCH.md](docs/RESEARCH.md) | Research grounding for design decisions |
| [web/README.md](web/README.md) | The studio frontend |

## Scope & limitations

Prosotype is a research/demonstration project, not a finished product. Known
limits:

- **Live captions are an approximation.** A microphone can't know future words,
  so motion follows acoustic evidence as it arrives. The `cc` renderer shows the
  exact reference motion because it knows the text in advance.
- **English and Korean only.** No automatic language detection; the language is
  chosen before capture and locked for the session.
- **Speaker attribution is uncertain at the edges.** Very short turns, rapid
  back-and-forth, and similar voices can stay ambiguous. The UI shows that
  uncertainty rather than guessing.
- **CPU-bound latency.** Recognition runs on CPU (Apple Silicon or x86); on
  slower hardware latency grows, though no audio is dropped.
- **Not yet implemented from the spec:** off-camera italics, sound-effect and
  music captions, and the haptic device module.

See [docs/LIVE.md](docs/LIVE.md) for the full detail behind
each of these.

## License & attribution

The Caption with Intention design system is authored by the Chicago Hearing
Society. Bundled audio samples carry their own licenses (see the
`assets/*.LICENSE.md` files). Model weights and fonts are downloaded from their
respective sources under their own licenses.
