# Onboarding — your first day

This guide takes you from a fresh clone to running captions and making a first
change. If a term is unfamiliar, check the [glossary](GLOSSARY.md).

## 1. Prerequisites

- **macOS** on Apple Silicon (recommended) or **Linux**. Apple Silicon unlocks
  the native diarization helper; everything still works without it.
- **Python 3.11** (exactly — the virtual environment expects it).
- **Node.js** (any recent LTS) for building the browser UI.
- **ffmpeg** for audio handling: `brew install ffmpeg` on macOS.

## 2. Install

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Always use `.venv/bin/python`, never the system `python`.

Then download the one-time assets (models and fonts). After this, the app is
fully offline:

```bash
.venv/bin/python scripts/fetch_font.py               # variable fonts
.venv/bin/python scripts/fetch_streaming_model.py    # live ASR + diarization
npm --prefix web install                             # UI dependencies
npm --prefix web run build                           # build the browser UI
```

### What gets downloaded

| Asset | Size | Notes |
|---|---|---|
| Roboto Flex + Noto Sans KR fonts | ~12 MB | English and Korean variable fonts |
| English live ASR (Nemotron + Parakeet, int8) | ~1.9 GB | streaming + endpoint verifier |
| Korean live ASR (174M Zipformer, int8) | ~152 MB | fetch alone with `--korean-only` |
| Speaker models (ERes2Net, CAM++) | ~50 MB | fetch alone with `--speaker-only` |
| Native diarizer (Core ML, Apple Silicon) | ~106 MB | fetch alone with `--sortformer-only` |
| Phoneme onset sidecar | ~378 MB | fetch alone with `--onset-only` |

On Apple Silicon the setup script also builds a small Swift helper for native
diarization. On other platforms it skips the helper and uses the portable
embedding backend instead — captions still run.

### Offline pipeline extras (optional)

Only needed if you run the recorded-video pipeline:

- Whisper `small` (~460 MB) downloads on first `transcribe`.
- pyannote diarization (~30 MB) downloads on first `diarize` and needs a
  Hugging Face token. Create one at
  <https://huggingface.co/settings/tokens>, accept the terms on
  `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0`, then
  `export HF_TOKEN=hf_...`. Inference stays local; the token only authorizes the
  one-time download. Without it, use `--stub` for a model-free deterministic run.

## 3. See it run

Start with the bundled sample so you don't need a microphone:

```bash
.venv/bin/python -m autocwi live --sample
```

This opens `http://127.0.0.1:7337/` and streams a short English clip through the
full pipeline. You should see words appear in sequence, turn to a speaker color
as they're "spoken," and briefly pop.

Try the variations:

```bash
.venv/bin/python -m autocwi live --sample --lang ko   # Korean sample + Korean model
.venv/bin/python -m autocwi live --sample --loop      # repeat continuously
.venv/bin/python -m autocwi live                       # your real microphone
.venv/bin/python -m autocwi live --list-devices        # if the wrong mic is picked
```

> **First live run on macOS** grants microphone permission per terminal app. If
> a port is busy (usually a leftover process), run `pkill -f "autocwi live"`.

For the *exact* reference motion (text known in advance), run the closed-caption
renderer:

```bash
.venv/bin/python -m autocwi cc assets/reference_specs/demo.json
```

## 4. Run the tests

```bash
.venv/bin/python -m pytest        # ~4 s, fully offline, no model loads
npm --prefix web run check        # lint + UI reducer tests + static build
```

The Python suite is **offline by design**: synthetic audio, no model downloads,
no video decoding. Keep it that way. See [TESTS.md](TESTS.md) for the layout.

## 5. Make your first change

A good first task is a config tweak, because all tunable values live in one
place:

1. Open `config.yaml`. Every mapping value (colors, size ranges, motion timing)
   lives here, with comments citing the CWI design-system section.
2. Change a value — for example a color or a motion duration.
3. Re-run `.venv/bin/python -m autocwi live --sample` and watch the result.
4. Run `.venv/bin/python -m pytest` to confirm nothing broke.

Nothing about the mapping is hardcoded in Python — if you find a magic number in
code, that's a bug to report.

## 6. Where to go next

- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — how the pieces fit together and
  the data contract every component agrees on.
- **[LIVE.md](LIVE.md)** — the live mode in depth.
- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — conventions and the ground rules
  to follow before opening a pull request.
- **[SOURCES.md](SOURCES.md)** — the design system PDF and
  reference recordings this implementation is derived from. Read the PDF before
  changing any motion or typography.
