# Contributing

## Setup

Python 3.11 exactly, Node.js, and ffmpeg (`brew install ffmpeg`).

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py             # fonts, ~12 MB
.venv/bin/python scripts/fetch_streaming_model.py  # models, ~2.2 GB
npm --prefix web install && npm --prefix web run build
```

Always `.venv/bin/python`, never the system Python. After the downloads the app
is fully offline. `fetch_streaming_model.py` takes `--korean-only`,
`--speaker-only`, `--sortformer-only` and `--onset-only`.

The recorded-video pipeline additionally wants Whisper (downloads on first
`transcribe`) and an `HF_TOKEN` for pyannote diarization — inference still runs
locally, the token only authorises the download. `--stub` runs it model-free.

## See it run

```bash
.venv/bin/python -m autocwi live --sample          # bundled clip, no mic
.venv/bin/python -m autocwi live                   # your microphone
.venv/bin/python -m autocwi live --list-devices    # if the wrong mic is picked
```

Words appear before they are spoken, turn to a speaker colour as they are said,
and pop as they turn. macOS asks for microphone permission per terminal app on
the first run; a busy port is a leftover process (`pkill -f "autocwi live"`).

## Before you push

```bash
npm --prefix web run check        # lint + reducer tests + static build
```

The Python suite and the measurement probes are development tooling and are not
distributed with the project. If you have them, run `pytest` too — it is offline
by design and must stay that way.

## The ground rules

Breaking one of these makes the captions wrong in a way the tests do not catch.

- **Local and offline.** No cloud inference, no telemetry. Permitted network:
  the one-time downloads and the LAN link to the hardware node.
- **Every tunable lives in `config.yaml`**, with a comment citing its CWI
  section. A magic number in code is a bug to report.
- **The CaptionSpec is a versioned contract** (`autocwi/schema.py`). Consumers
  read only it. Extend with optional fields; a breaking change bumps the version.
- **A settled caption never re-animates.** A word gets its motion once, at its
  own moment on the acoustic timeline. Corrections update it in place and must
  never restart it. This is the load-bearing visual invariant.
- **The design system outranks everything** — read the relevant section of
  [captionwithintention.org](https://captionwithintention.org) before changing
  any typography or motion.
- **Language is chosen before capture** and locked for the session.
- **The frontend stays statically exportable**: no required Node server, route
  handler, server action, cookie or rewrite.

## Making a change

Start in `config.yaml`: change a value, re-run `live --sample`, watch it.

For anything visual, **do not tune by eye**. There is a probe for each question
— clipping, colour, row clearance, word overlap, whether a settled word moved
again — and each takes `--broken` or an equivalent negative control. **Run that
first: a check that has never been seen to fail is not evidence.**

Work on a branch. A pull request says what changed, how it was verified (which
probes, and a screenshot for anything visual), and which config values moved.

## Next

[ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces fit together ·
[the project page](https://nobel2040ne.github.io/Prosotype/) for what a caption does, and why.
