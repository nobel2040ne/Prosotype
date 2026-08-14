# Weave

Live speech into **expressive captions** for Deaf and hard-of-hearing viewers.
It automates [Caption with Intention](https://captionwithintention.org): colour
for *who* is speaking, motion for *when* each word is spoken, a variable font
for *how* it is said.

English or Korean, from a microphone, **entirely offline**. No cloud inference,
no telemetry — the only network access is a one-time model and font download.

**[See how it works →](https://nobel2040ne.github.io/Weave/)** — the whole
project on one page, with the motion running.

## Quick start

Python 3.11, Node.js and ffmpeg, on macOS (Apple Silicon) or Linux.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py             # fonts, ~12 MB
.venv/bin/python scripts/fetch_streaming_model.py  # models, ~2.2 GB
npm --prefix web install && npm --prefix web run build
```

Then, no microphone needed:

```bash
.venv/bin/python -m autocwi live --sample          # opens 127.0.0.1:7337
```

## Commands

```bash
.venv/bin/python -m autocwi live                   # microphone; pick a language first
.venv/bin/python -m autocwi live --lang ko         # skip the picker
.venv/bin/python -m autocwi live --list-devices    # choose a microphone
.venv/bin/python -m autocwi cc assets/reference_specs/demo.json   # exact reference motion
```

## Map

```
autocwi/     the runtime: live engine, offline pipeline, renderers, schema
web/         the studio UI; static-exported and served by Python
native/      Swift helper for diarization on Apple Silicon
scripts/     one-time downloads; the Raspberry Pi node
assets/      fonts, sample audio, reference specs
config.yaml  every tunable value — never hardcoded in code
```

Tests and measurement probes are development tooling and are not distributed.

## Documentation

| | |
|---|---|
| **[nobel2040ne.github.io/Weave](https://nobel2040ne.github.io/Weave/)** | the project, on one page |
| [ARCHITECTURE.md](ARCHITECTURE.md) | modules, data contract, glossary |
| [CONTRIBUTING.md](CONTRIBUTING.md) | setup and the ground rules |
| [web/README.md](web/README.md) | the studio frontend |
| [captionwithintention.org](https://captionwithintention.org) | the design system — the final word |

## Limits

A research demonstration, not a product.

- **Live motion follows evidence, not foresight.** The playhead buys back CWI's
  read-ahead, and pays 1.75 s of latency for it. `cc` shows the exact reference
  motion because it knows the text in advance.
- **English and Korean**, chosen before capture and locked for the session.
- **Attribution is uncertain at the edges** — short turns and similar voices can
  stay ambiguous. The UI shows that rather than guessing.
- **Not implemented from the spec:** off-camera italics, the sound-effect and
  music caption rules, and the haptic device.

## License

The code is MIT — see [LICENSE](LICENSE).

The Caption with Intention design system is authored by the Chicago Hearing
Society. This is an independent implementation, not affiliated with or endorsed
by them. Bundled samples, model weights and fonts carry their own licenses.
