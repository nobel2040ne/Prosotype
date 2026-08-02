# Design sources

Everything the implementation is derived from lives here. Nothing in this list is
generated — these are the primary materials. **The order below is the order of
authority: where two sources disagree, the one higher up wins.**

Read the design system PDF *before* inferring anything from the recordings or
templates. Past work repeatedly measured video for values that were stated
outright in the PDF.

## 1. The design system (the authority)

**`cwi-design-system-v1.0.pdf`** — *Caption with Intention, Design System and
Caption Guidelines, V1.0 (2025.1)*, 54 pages, by the Chicago Hearing Society.
Also at
<https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf>.

This is the single source of truth. It states the motion outright: §2.2.3 gives
the full synchronization cue (+15% type size, 25% elevation, per word, at the
color turn), and §2.3 gives every type value. Read it directly to settle any
question about intent.

**`DESIGN.md`** — the values extracted from the PDF, section by
section, with what we implement, where we deviate, and why. Use this to find a
number fast; use the PDF to settle an argument.

**`Caption with Intention – Quickstart Guide.pdf`** — the two-page After Effects
template workflow. Its key architectural rule: the `[START]`/`[END]` markers own
the animation window independently of the layer's lifetime. The live renderer
follows the same separation, with a one-time first-paint motion clock and an
independent speaker-color clock.

## 2. The reference recordings

`reference/` — three screen captures of the official CWI website, each paired
with the transcript read off its own frames:

| Section | Recording | Transcript |
|---|---|---|
| Character Identification | `character_identification.mov` | `character_identification.txt` |
| Synchronization | `synchronization.mov` | `synchronization.txt` |
| Intonation | `intonation.mov` | `intonation.txt` |

These are a *different implementation* of the design system — the website, not
the PDF and not the After Effects template — so they are evidence about
**behavior**, never about intent. What they supply that the PDF cannot: the
timing of the motion, and which specific word in each sentence is actually loud,
quiet, or bold. `scripts/derive_reference_spec.py` measures both out of the
pixels into `assets/reference_specs/`.

The `.txt` files are `SPEAKER<TAB>text`, one caption per line, in **recording
order**, with a leading `-` marking an instance to measure but not emit (a
repeated heading or loop repeat). Every caption instance the recording shows must
be listed, because groups are matched to the transcript positionally.

## 3. Stills

`stills/` — frames kept for details easier to see than to describe:

- `site-volume-and-sync.png` — the volume waveform beside a caption mid-sweep,
  with the playhead and the color boundary landing inside a word.
- `site-volume-and-pitch-axes.png` — the two intonation channels drawn as axes:
  volume against type size, pitch against weight.
- `film-pulp-fiction-royale.png` — "Roya|le with Cheese!": the mid-word color
  boundary, proof that the turn sweeps *through* a word rather than flipping it.
- `film-back-to-the-future-thank-you.png` — speaker color plus a mid-word
  boundary on a short line.
- `film-toy-story-star-command.png` — emphasis on a single word inside an
  otherwise uniform line: the density the design aims for (occasional, not
  continuous).

The film stills are also where the **resting** type size was checked — nearer 4%
of frame height than the 5% baseline of §2.3.5, because the box hugs one short
line.

## 4. The After Effects template

Not in this folder, but part of the same set: the official template in
`AE PROJECT/`. It is the *calm* reading of the system — it contains zero scale
animators, so following it literally would suppress §2.2.3's size pop. Useful for
the **shape** of the motion, but superseded by the PDF for amplitudes.

## Related working notes

- **[TESTS.md](TESTS.md)** — what the test suite covers and how to regenerate the
  golden prosody grid.
- **[RESEARCH.md](RESEARCH.md)** — prior DHH-captioning research
  mapped onto the design decisions here, plus the grounding for the haptic
  salience flags and the diarization and delivery-dynamics decisions.
- **[../web/README.md](../web/README.md)** — the frontend boundary and UI
  invariants.
- The bundled acceptance fixtures: `../assets/sample.mp4` (English) and
  `../assets/sample-ko.wav` (Korean). Caption changes should be tested against
  both — a single-language run is not sufficient acceptance.

## `Caption With Intention PR FILM.mp4` (113 s, with audio)

CWI applied to real footage (Forrest Gump, Toy Story) plus documentary
interviews, and a demo section (0:40–1:04) covering the same sentences as the
three `.mov` screen recordings. **The most authoritative reference for how the
system is actually used**, and the only one with usable audio.

Authoritative for: the colour turn as a per-character WIPE, transient swells
that sustain then return to normal, read-ahead in white at normal size,
off-camera italic, bracketed sound effects, and the line re-flowing around a
swelling word.

**NOT a calibration target for the loudness mapping.** Measured on its own
audio, the word "louder" in the intonation demo is **−23.5 dB — quieter than
the phrase before it**. Its huge caption is authored from meaning, not derived
from the waveform. Fitting our dB→size mapping to this film would be fitting to
an editor's judgement.
