# Prosotype

A local, fully offline pipeline that turns a short video/audio clip into an
**expressive caption track** for Deaf and hard-of-hearing viewers, automating
the "Caption with Intention" design system:

The renderer follows the official **CWI Design System V1.0**
([PDF](https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf)):

- **Attribution** — each speaker gets a CI Main color (yellow, green, blue,
  pink, red, orange in wheel order; CI Supporting colors for speakers 7+)
- **Synchronization** — each line appears whole as white *read-ahead type*
  (90% opacity); every word flips to its speaker color at its exact spoken
  onset, with the documented 15% size pop and 25% elevation
- **Intonation** — Roboto Flex encodes prosody: loudness → type size
  (3–12% of frame height, baseline 5%), pitch → weight and width over an
  absolute Hz scale (lower voices heavier/wider, higher voices lighter/narrower)
- Captions overlay the video inside a 90%-opacity black **Captions Box**
  in the lower work area of the frame

All analysis runs on your machine (CPU, or CUDA/Apple-MPS when available).
No cloud inference, no telemetry. The only network access is one-time
downloads of model weights and the font.

## Architecture

```
live:     microphone ──► streaming ASR + prosody ──► SSE revisions/words ──► live.html
                                                               │
offline:  media ──► transcribe ──► diarize ──► prosody ──► fuse
                   words.json   segments.json prosody.json  spec.json
                                                               │
                                                               └──► (future haptic module)
```

`out/spec.json` (**CaptionSpec**, versioned, validated by `autocwi/schema.py`)
is the stable contract between analysis and every output. The renderer reads
*only* this file; a future haptic device module will read `words[].loudness`,
`words[].pitch` and timing from the same file without touching the models.
Loudness/pitch are normalized **within each speaker** (5th–95th percentile of
that speaker's own range); raw dB/Hz values are kept alongside for debugging
and future tuning.

## Setup

```bash
brew install ffmpeg                      # if not present
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py   # one-time Roboto Flex download
.venv/bin/python scripts/fetch_streaming_model.py  # local live-ASR model
```

### Hugging Face token (diarization only)

pyannote's pretrained weights are gated. One-time setup:

1. Create a free token: https://huggingface.co/settings/tokens
2. Accept the conditions of **both** repos:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. `export HF_TOKEN=hf_...`

Inference is local; the token only authorizes the one-time weight download.

### First-run downloads (then fully offline)

| What | Size | When |
|---|---|---|
| Roboto Flex `.ttf` | ~2 MB | `scripts/fetch_font.py` |
| Production live ASR: Nemotron 160 + 1120 ms and Parakeet Unified verifier, int8 | ~1.9 GB | `scripts/fetch_streaming_model.py` |
| Speaker embedding (titanet-small) for live attribution | ~38 MB | `scripts/fetch_streaming_model.py` |
| Whisper `small` (CTranslate2) | ~460 MB | first `transcribe` |
| pyannote diarization 3.1 | ~30 MB | first `diarize` (needs `HF_TOKEN`) |

## Live captions (primary mode)

```bash
.venv/bin/python -m autocwi live                 # microphone, English
.venv/bin/python -m autocwi live --sample        # stream the bundled clip, no mic
.venv/bin/python -m autocwi live --sample --loop # repeat it continuously
.venv/bin/python -m autocwi live --file clip.wav # demo: stream a file as if live
.venv/bin/python -m autocwi live --list-devices  # pick a mic if the default is wrong
```

Opens `http://127.0.0.1:7337/` — a CWI caption stage with live **Attribution,
Synchronization, Intonation**, and **Input** views. Three local stages
cooperate: the 160 ms Nemotron supplies immediate revisable draft words; the
accuracy-first 1120 ms Nemotron supplies stable committed words; and a
modified-beam Parakeet Unified pass verifies each completed phrase. Only that
verified phrase writes durable `word` events. Endpoint insertions, deletions,
and replacements are aligned back onto the streaming word clock. Locked words
retain token timestamps and are sized by loudness, weighted by pitch, and
expanded or condensed on Roboto Flex's width axis. **Speakers are attributed
live** (CWI 2.1): voice embeddings are segmented at change points and clustered
online, so each discovered voice takes the next palette colour; commits carry a
provisional label and the endpoint pass corrects it in place.

**Display mode** (`display.mode` in `config.yaml`) governs what reaches the
stage. Default **`fast`** shows settled committed words plus the accurate
stream's own not-yet-committed tail as white read-ahead (~1.2 s behind the
voice, rarely revising) — so a lone word appears promptly in white and turns
colour when locked. `stable` shows committed words only; `sentence` shows one
finalized turn at a time; `readahead` adds the 160 ms draft layer at the cost
of visible revision. Captions are left-aligned and accumulate transcript-style —
lines stay until the stage is full, then the oldest are pushed off the top
(`display.retention`). Each line ends with an **intention circle** that pulses
with the live voice level on the active line and freezes as a record of
delivery on finished lines (`display.intent_circle`).

**Input level** is normalized before recognition: an adaptive gain lifts quiet
speech toward the recognizer's training level (a streaming transducer emits
nothing well below it) while the *true* captured dBFS still drives type size,
so a whisper stays small. The header **Input** meter shows live dBFS, noise
floor, and applied gain — a too-quiet or wrong mic is visible without speaking
a word. Tune or pin it with `live.input_gain` in config, `--gain DB`, or
`--no-gain`; pick a device with `--device`.

On the three model-bundled reference clips, the checked-in benchmark reports
0 edits over 77 reference words (0.00% normalized WER) and an end-to-end RTF
around 0.40 on the target M1. `--stress` adds deterministic 14 dB-SNR room
echo/noise, a quiet-device floor, and 1.15× speech: 7 edits over 308 words
(2.27% matrix WER). Most repeated stress edits are the orthographic convention
`for ever` versus `forever`; one fast-speech proper-name error remains. These
are narrow regression and synthetic-stress results, not a population-wide
accuracy claim.

Live input is wall-clock paced and lossless. Microphone blocks that arrive
while recognition is busy are drained and decoded together; file playback
runs without sleeps until it catches the media clock. Normal backlog never
throws speech away. The two decoders run concurrently across CPU cores and the
microphone requests PortAudio's low-latency path. A resync is reserved for a
real capture-device gap.

Durable words also carry research-grounded haptic salience flags
(`speaker_change`, `emphasis` — threshold `haptics.emphasis_db`), so a future
haptic module actuates selectively instead of buzzing every word (see
`docs/research-notes.md`).

Six SSE shapes are sent at `/events`: revisable `hypothesis` snapshots,
provisional `cue` timing, stable-stream `commit` words, endpoint
`verification` batches, CaptionSpec-shaped `word, final: true` events for
durable consumers, and continuous `level` events (dBFS / floor / gain) for the
input meter. Only durable `word`/`commit`/`verification` events are logged;
`level` and `hypothesis` are display-only. Every event has an SSE id. The
server keeps bounded durable history, disconnects a stalled tab instead of
leaking memory, and replays from
`Last-Event-ID` on reconnect. Only verifier-owned final words are logged to
`out/live_events.jsonl`, so a future haptic module never reacts to text that
may be corrected. The bundled streaming models are English.
The old pause-segmented path remains available for comparison with
`--whisper small`.

macOS note: the first mic run asks for microphone permission for your
terminal app.

## Offline pipeline usage

The offline pipeline (kept as the source of the `spec.json` haptics contract)
analyzes a media file into a validated `spec.json`:

```bash
# full pipeline: media -> spec.json
.venv/bin/python -m autocwi run clip.mp4 --out out/ --speakers 2

# stages individually (each reads/writes JSON in --out, so you can inspect/swap)
.venv/bin/python -m autocwi transcribe clip.mp4 --out out/
.venv/bin/python -m autocwi diarize    clip.mp4 --out out/ --speakers 2
.venv/bin/python -m autocwi prosody    clip.mp4 --out out/
.venv/bin/python -m autocwi fuse       clip.mp4 --out out/

# no models at all (deterministic placeholders; good for testing the contract)
.venv/bin/python -m autocwi run clip.mp4 --out out/ --stub
```

Flags: `--whisper base|small|medium` (default `small`), `--speakers N` fixes
the speaker count.

All mapping choices live in `config.yaml` — palette, size range, weight range,
`invert` for the pitch→weight polarity, normalization percentiles.

## Samples

For live captions, `--sample` streams the bundled reference clip
(`assets/sample.mp4`) with no microphone needed.

## Seeing the CWI motion

Three things to run, in increasing fidelity.

### 1. The motion tuner

```bash
.venv/bin/python -m autocwi tune
```

Loops a built-in line with every motion constant on a slider, plus a live plot
of the curve the current settings produce (one word's vertical motion against
time, with its colour turn marked). `sync_pop` and `sync_elevation_em` are the
two the design system fixes (2.2.3); the `sync_*_s` sliders shape the same cue
in time. **Show config.yaml** prints your values back in a form you can paste
into `config.yaml`. Writes `out/tuner.html`, never `out/captions.html`.

The built-in line deliberately stresses everything at once: a long word for the
character sweep, two-letter words to check the ripple's rate against, one loud
word (`louder`) and one quiet one, a run of ordinary words the deadband should
hold still, and a speaker change.

### 2. The reference sentences, replayed

`assets/reference_specs/` holds CaptionSpecs **derived from the recordings in
`docs/reference/`** — the real sentences, with per-word timings and per-word
emphasis measured from the pixels rather than invented.

**The united demo** plays all three sections back to back, in the order the
site presents them:

```bash
.venv/bin/python -m autocwi cc assets/reference_specs/demo.json
```

```
Character Identification                                       (yellow)
Now, colors will distinguish characters,                       (yellow)
so Deaf people instantly know who's speaking.                  (green)
Synchronization
Caption with Intention uses
dynamic text animation
so captions are synchronized
precisely as each word is spoken.
Intonation
This system brings in varying
types sizes, weights and animation,
so you can feel when my voice gets louder or softer.
```

Twelve caption lines: each section title is itself a caption the site
animates, so it is derived and played like any other.

`demo.json` is built by `scripts/build_demo.py`, which concatenates the three
derived specs onto one timeline — nothing in it is hand-authored. Rebuild it
after re-deriving any section. The individual sections still run on their own:

```bash
.venv/bin/python -m autocwi cc assets/reference_specs/synchronization.json
.venv/bin/python -m autocwi cc assets/reference_specs/intonation.json
.venv/bin/python -m autocwi cc assets/reference_specs/character_identification.json
```

What to watch in each:

- **`intonation`** — the two prosody channels, and that they are separate:
  `sizes,` swells **large** (normal weight) while `weights` goes **bold**
  (normal size), each as it is spoken, both returning to rest afterwards.
- **`character_identification`** — the speaker change: the line turns yellow
  for the first speaker, green for the second.
- **`synchronization`** — deliberately uniform in size (it demonstrates timing,
  not intonation), so it is the one to watch for the colour boundary landing
  mid-word.

`cc` drives the type axes harder than live mode via `closed_caption`
overrides (`size_response`, `wght_range`, …), because live has to stay
compressed — words accumulate there and a settled word must never restyle —
while a closed caption plays through and is gone.

### 2b. Where the motion comes from

`docs/cwi-design-system-v1.0.pdf` is the source of truth.
Section **2.2.3** states the whole synchronization motion: each word pops
**+15% in type size** and rises **25%** as it changes colour, then returns.
That cue is per WORD (2.2.4: "words will be spoken and animated fully, one by
one") and its amplitude is a CONSTANT — per-word amplitude is intonation
(2.3.3-2.3.6), which is a different channel and comes from the measured
prosody. `closed_caption.sync_pop` / `sync_elevation_em` hold those numbers.

The three recordings in `docs/reference/` supply what the PDF cannot: timing,
and which word in each sentence is actually loud, quiet or bold. Each derived
word also carries its own measured curves (`Word.motion`); set
`closed_caption.motion_source: measured` to replay them verbatim instead of
the design system's model, which is useful for checking the derivation.

### 3. Re-deriving a spec from a recording

Each recording sits beside the transcript read off it, in `docs/reference/`.

| stem | true fps | crop | flags |
|---|---|---|---|
| `character_identification` | 57.2735 | `3456:200:0:1270` | `--rotate 2` |
| `synchronization` | 57.1256 | `3456:210:0:1075` | `--rotate 3` |
| `intonation` | 57.3638 | `3456:200:0:1680` | `--scroll --cut 0.55 --rotate 3` |

True fps is **frames / duration**, not the 120 the container claims. The crop
is full width so a scrolling line is still tracked as it leaves the frame.

```bash
S=/tmp/sync && mkdir -p $S
ffmpeg -i docs/reference/synchronization.mov \
    -vf "crop=3456:210:0:1075" -vsync 0 $S/n_%04d.png

# READ the transcript off the frames -- never guess it. The recordings loop and
# interleave animated section headings with the captions, so every instance has
# to be accounted for or the 1:1 match slips.
.venv/bin/python scripts/derive_reference_spec.py \
    --frames "$S/n_*.png" --fps 57.1256 \
    --transcript docs/reference/synchronization.txt \
    --out /tmp/spec.json --list-groups /tmp/groups.png

.venv/bin/python scripts/derive_reference_spec.py \
    --frames "$S/n_*.png" --fps 57.1256 --rotate 3 \
    --transcript docs/reference/synchronization.txt \
    --out assets/reference_specs/synchronization.json
.venv/bin/python scripts/build_demo.py        # re-stitch the united demo
```

`--rotate` exists because the transcript must stay in **recording** order for
the 1:1 group match, while the recordings start mid-cycle — the site's own
order is a rotation of it. `--scroll` recovers the horizontal scroll before
tracking; only `intonation` needs it, because its line moves far enough that
nearest-centre tracking fragments without it.

Two things to read in the output:

- a per-phrase **fit residual** — under ~35 ms is one to two frames at the
  recording's rate;
- a per-word **emphasis** line, with `F` marking words whose size came from the
  frame measurement rather than from glyph tracks (recorded as
  `Word.emphasis_source`). Tracking breaks on exactly the words that matter —
  one swelling past 2x or shrinking to half loses its glyph tracks — so `F` on
  `louder`, `sizes,` and `softer.` is expected and correct.

`docs/reference/*.txt` are the transcripts: one caption per line as
`SPEAKER<TAB>text`, with `-` marking instances to measure but not emit
(section headings that repeat, loop repeats).

## Tests

```bash
.venv/bin/python -m pytest                                  # 73, ~3 s, offline
.venv/bin/python scripts/benchmark_streaming.py [--stress]  # loads models
```

The suite is fully offline by design — synthetic audio, no model loads, no
video decoding. See **[docs/TESTS.md](docs/TESTS.md)** for the layout, the
conventions, and how to regenerate the golden prosody grid that pins
`autocwi/ccprosody.py` to the page's own JavaScript.

## Honest limitations

- **Live CWI is necessarily an approximation**: the official system is
  manually authored, so its complete white line exists before dialogue and
  every animation can be placed at the known word onset. A microphone system
  cannot know future words. This implementation matches the public 90%-white,
  speaker-color, 15% pop plus 25% elevation, sizing, weight/width, box, and
  work-area rules; the accurate provisional cue still arrives after acoustic
  evidence. The official downloadable example is authored video, not an
  embeddable live recognizer or motion runtime.
- **Streaming accuracy tradeoff**: the immediate 160 ms draft is less accurate
  by design and can visibly revise. The 1120 ms profile owns cues/commits and
  Parakeet owns final text; names, heavy accents, crosstalk, and noisy program
  audio can still need correction. White words are tentative, colored words
  are stable-stream output, and “verified locally” is the durable phrase lock.
- **CPU requirement**: live mode runs two 0.6B int8 recognizers. The target M1
  runs the pair faster than real time in the included benchmark. On slower
  hardware, audio remains lossless but latency can grow; no implementation can
  preserve every word and real-time delivery if inference stays below 1×.
- **Diarization**: acoustically language-agnostic, but rapid turn-taking,
  short backchannels and overlapped speech produce boundary errors.
  Fixing `--speakers N` helps.
- **Judgment calls, not ground truth**: the 5–95 percentile loudness
  normalization and the neutral weight (400) for unvoiced words are our
  choices; the size range (3–12% of frame height), pitch→weight Hz anchors,
  palette, and box opacity follow the CWI design system and are all exposed
  in `config.yaml`.
- **Not yet implemented from the CWI spec**: box-breakout for very loud
  bursts, italics for off-camera voices (needs video analysis, not audio),
  and sound-effect/music captions.
