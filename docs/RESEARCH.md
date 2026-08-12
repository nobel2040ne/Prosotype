# Related work → what this project does about it

Each entry: the finding that matters, then its status here — **adopted**,
**already covered**, or **deferred** with a reason. This is the design
rationale for reviewers; section numbers in code comments refer to the CWI
design system, entries here to the works below.

## Presentation of prosody and emotion

**Caption with Intention** (FCB Chicago / Chicago Hearing Society,
[captionwithintention.org](https://www.captionwithintention.org/)) — the
design system this project automates: speaker→colour attribution, per-word
onset synchronization, prosody→typography intonation. **Adopted** as the
core contract. The PDF is authoritative: §2.2.3 supplies one constant 15%
pop plus 25% elevation per word, while §§2.3.3–2.3.10 separately map prosody
to size/weight/width. The official AE template and reference recordings show
that those expressive axes travel with the spoken boundary and return to normal;
the template's position-only implementation does not override the PDF. The live
open-caption adaptation uses first paint as activation because the word is not
available earlier. It compresses the authored amplitude for an accumulated
stacked transcript, shapes the one-time excursion from measured voice features,
and gives size, weight, and width independent smooth temporal envelopes instead
of reducing all voice features to one canned pulse. Acoustic word span controls
the bounded live clock and continuously delays the curve development for
drawn-out delivery. Every axis always returns to normal-font rest. The optional
character slide is off.
Attribution colour has a separate clock: it may sweep during motion or update
later, but it is never a second motion trigger.

**Visible Nuances** (CHI '23,
[doi](https://dl.acm.org/doi/full/10.1145/3544548.3581130)) — automatic
paralinguistic analysis feeding expressive captions is viable and valued by
DHH viewers. **Already covered** in approach: our prosody chain
(RMS/F0/voiced-fraction → size/weight/width) is exactly this pipeline, run
live.

**Visualization of Speech Prosody and Emotion in Captions** (CHI '23,
[doi](https://dl.acm.org/doi/10.1145/3544548.3581511)) — flat auto-captions
strip affect and make sentences ambiguous; prosody-only, emotion-only, and
combined models each help. **Partially covered**: we render prosody, not
inferred emotion. Emotion classification is **deferred** — it needs another
model and, per Caption Royale below, its visual channel collides with CWI's.

**Caption Royale** (CHI '24,
[doi](https://dl.acm.org/doi/fullHtml/10.1145/3613904.3642258)) — valence
reads well through colour; arousal is hard to convey with size/weight alone;
preferences vary strongly per user, so customization is essential.
**Adopted where compatible**: (1) everything visual is a `config.yaml` knob —
that is our customization story; (2) we do NOT add emotion-colour, because
colour is already CWI's *attribution* channel and overloading it would break
speaker identification, the one thing DHH viewers rank hardest in live
multi-speaker settings (see Haptic-Captioning). Arousal difficulty supports
keeping our size channel for loudness only.

**WaveFont** ([Mada Innovation](https://nafath.mada.org.qa/nafath-article/wavefont-visualization-of-information-and-emotions-from-voice-in-captions/))
maps voice stress and duration into typographic weight/width and describes
longer/slower speech with wider forms. **Adopted in channel choice, not literal
styling**: live already maps measured voice to size/weight/width during the
one-shot motion. A continuing but unknown phone prefix uses a separate
paint-on duration trail, so the text does not repeatedly stretch or shake.

**Visualizing speech styles in captions** (IJHCS 2025,
[article](https://www.sciencedirect.com/science/article/abs/pii/S1071581924001691))
compares punctuation, paint-on, colour, and boldness for extension, emphasis,
and pauses. **Adopted conservatively**: extension is a bounded paint-on trail;
colour remains reserved for speaker attribution; settled type returns to
normal. Together with Caption Royale's readability/minimal-distraction
findings, this rules out jagged baselines, flicker, and automatic
emotion-labelled effects. Continuous frequency/texture belongs in the
side-rail Voice Compass instead of the caption letters.

**CuCap** (ASSETS '25,
[doi](https://dl.acm.org/doi/epdf/10.1145/3663547.3746400)) — expressive
caption preferences differ across culture/language (English findings don't
transfer 1:1 to Korean); emotion visualization is liked in both. **Noted as a
boundary**: this project is English-first by measurement (the multilingual
checkpoint scored worse), and CuCap is the evidence that a future Korean
version needs its own preference pass, not a translation of this one.

**MEASURED 2026-08-10** after a report that Korean captions do not feel
expressive: the motion system renders Korean equivalently to English on every
channel (median peak 1.14x vs 1.16x, 29% vs 29% of words above 1.20x, max weight
893 vs 858, three lifting words). The gap is the MATERIAL -- `sample-ko.wav` is
13.3 s of neutral read FLEURS narration, so the mapping fires on incidental
syllable energy rather than on emphasis anyone performed. CuCap's own finding
lands the same way: emotion visualization was universally favoured, and it was
*prosody* preference that diverged. See [KOREAN.md](KOREAN.md).

**WaveFont** (Cyberworlds '20) and **Visualizing Speech Styles in Captions**
(IJHCS '24) — voice-driven type and automatic elongation/emphasis/pause
visualization. **Already covered**: variable-font prosody mapping; syllable
colour-wipe for drawn-out delivery (2.2.4); emphasis exists acoustically in
our `haptics.emphasis_db` flag. A visual pause marker is **deferred** (the
line-break gap already encodes long pauses spatially).

**Google Expressive Captions** (Android, 2024) — on-device expressive
captions using discrete text transforms (all-caps loudness, stretched
spelling, vocal-burst tags). **Rejected as technique, validating as
direction**: destructive text transforms fight readability and the verifier's
authoritative text; our continuous typography carries the same signal without
rewriting words. Vocal bursts/environmental sounds (also SoundWatch's domain)
are **deferred** — a sound-event classifier is a separate model class.

## Speaker identity and direction

**Speech Compass** (Google DeepMind,
[github](https://github.com/google-deepmind/speech-compass)) — directional
captions from a 4-mic phone case. Verified from the repo: there is **no
custom speech model at all** — ASR is the phone's stock Android recognizer;
the direction comes from classical **GCC-PHAT** cross-correlation plus kernel
density estimation on an STM32 microcontroller, and words are coloured by
**azimuth**, not voice identity. That is why its diarization looks flawless:
geometry is nearly error-free when speakers are spatially separated, where
our single-mic embedding clustering must solve the harder who-sounds-like-whom
problem. **Visualization adopted; localization deferred — hardware.** The live
page now includes a radar/minimap-style Voice Compass beside the caption stage,
mirroring volume, pitch, periodicity, and brightness, with an angular channel
ready for `direction_deg`/`azimuth_deg`. It deliberately displays
`awaiting array` on mono. Their DSP works with
any 2+ mics (180°), so a cheap stereo USB mic plus a numpy cross-correlation
could supply `direction_estimate` to `SpeakerTracker` at a booth table. The
manager exposes that input with `direction_prior_weight: 0.05`, but treats it
only as a weak prior alongside voice evidence. The current mono capture path
does not invent an angle. Two co-located speakers would still need embeddings,
and direction alone would not solve identity.

**Mixed Reality Speaker Identification** (VRST '19) and **HMD Sound
Awareness** (CHI '15) — fast-switching multi-speaker settings defeat plain
captions; peripheral directional indicators beat central overlays.
**Partially adopted**: speaker colour + per-line attribution is our
equivalent within a flat screen; the intention circle sits at the line edge
(peripheral, not overlaying text). Directional arrows are deferred with
Speech Compass.

**See-Through Captions** (ASSETS '21) — captions on transparent displays so
lipreading/gesture stays visible. **Out of scope** (display hardware), but it
motivates our overflow retention: readers glance away and back, so lines must
persist longer than speech.

## Model decisions, in one line each

Three model choices were made by benchmark rather than by reputation. The
comparisons, the numbers and the rejected candidates are in the decision log;
what they settled:

- **Live diarization is hybrid.** Streaming Sortformer where it is available,
  an ONNX speaker-embedding path everywhere else, and a failed native startup
  degrades to the embedding lane without aborting captions.
- **Korean streaming stays on the local Zipformer.** 10.54% CER normalised on
  120 FLEURS clips. The lever is latency, not weights: a larger chunk wins on
  text and is disqualified on time, because it leaves less than the read-ahead
  floor before the colour turn.
- **Speech emotion/intention is research-only.** Before adding a model,
  benchmark Korean macro F1 on KEMDy20 plus booth audio, local RTF, and its
  licence. Freeze a smoothed estimate onto future words only — never use an
  utterance-end result to reweight words already on screen.

See [KOREAN-ASR.md](KOREAN-ASR.md) for the Korean recognition comparison in
full, since that one is still an open recommendation rather than a closed
decision.

## Haptics (the planned hardware module)

**Haptic-Captioning** (CHI '23,
[doi](https://dlnext.acm.org/doi/fullHtml/10.1145/3544548.3581076)) — wrist
vibration alongside captions helps DHH viewers track speaker changes and
frees gaze. **Adopted at the contract level**: durable word events now carry
`speaker_change: true`, so the haptic module can pulse on turn-taking without
any analysis of its own. The confidence lifecycle gates that flag:
`unknown` and `provisional` attribution cannot actuate it; only
`stable`/`corrected` attribution can. A later historical speaker revision
updates durable state without replaying a delayed pulse.

**Tactile Emotions** (CHI '25,
[pdf](https://saadh.info/papers/pataca-chi-25/pataca-chi25.pdf)) — combined
visual+haptic beats visual-only for immersion, but continuous vibration is
distracting; actuate selectively, threshold it, let users tune intensity.
**Adopted at the contract level**: `emphasis: true` flags only words that
exceed the speaker's median loudness by `haptics.emphasis_db` (config-exposed
threshold, per-user tunable). The rule for the future module: **actuate on
flags, never on every word.**

**SoundHapticVR** (ASSETS '24) / **SoundWeaver** (CHI '25) — spatial haptic
mapping and salience-driven fusion of multiple audio-AI outputs. **Adopted
2026-08-10, in a salience-gated form** (was *Deferred* — real hardware reversed
it: a ReSpeaker XVF3800 mic array supplies direction of arrival, and a ring of
coin motors on a Pi Zero 2 W can express it).

The gating is the whole design, and it is what reconciles spatial mapping with
*Tactile Emotions* above. Driving motors from raw DoA is continuous vibration —
precisely what that paper measured as distracting. So **direction rides on a
word, not on the audio**: a durable word carries `direction_deg` (the bearing
measured over its span) alongside its existing salience flags, and the motors
fire only on `speaker_change`/`emphasis`. What the wearer feels is *"someone
new, and they are over there"* — one event, with a direction — rather than an
ambient field. SoundWeaver's principle (choose what matters *now*, don't show
everything) is unchanged and is exactly why the flags gate the cue.

Two consequences recorded in code rather than left to the caller:
`bearing_weights` cross-fades between the two nearest motors so four read as a
continuous direction; and **one motor cannot encode direction at all**, so a
single-motor build pulses the whole ring and claims nothing about where. See
[HARDWARE.md](HARDWARE.md).

**Rich Captions** (ASSETS '24) — one caption file with extra attributes, many
renderings. **Already covered**: that is precisely the CaptionSpec/SSE
contract — attributes travel with words; renderers (visual page, future
haptics) choose their own mapping.

## What this list changed in the code

1. `speaker_change` / `emphasis` salience flags on durable word events, with
   `haptics.emphasis_db` in config and stable-attribution gating
   (Haptic-Captioning, Tactile Emotions).
2. Confirmation that colour stays attribution-only (Caption Royale vs CWI).
3. Speaker uncertainty gets neutral/tentative/full visual states and a
   non-colour marker instead of a forced palette assignment.
4. Everything visual remains config-tunable as the customization mechanism
   (Caption Royale, CuCap).
5. Direction has a clean weak-prior hook. It stayed inactive until a real mic
   array existed; with the XVF3800 attached it populates `direction_deg` on the
   level event and on durable words, and it is still **omitted, never
   defaulted**, when nothing is measuring a bearing.
6. Spatial haptics: a motor ring addressed by that bearing, gated on the
   salience flags rather than driven continuously (SoundHapticVR, SoundWeaver,
   reconciled with Tactile Emotions).
7. Deferred items are recorded here so they are decisions, not omissions.

---

## Sources

Everything the implementation is derived from lives here. Nothing in this list is
generated — these are the primary materials. **The order below is the order of
authority: where two sources disagree, the one higher up wins.**

Read the design system PDF *before* inferring anything from the recordings or
templates. Past work repeatedly measured video for values that were stated
outright in the PDF.

### 1. The design system (the authority)

**`reference/cwi-design-system-v1.0.pdf`** — *Caption with Intention, Design System and
Caption Guidelines, V1.0 (2025.1)*, 54 pages, by the Chicago Hearing Society.
Also at
<https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf>.

This is the single source of truth. It states the motion outright: §2.2.3 gives
the full synchronization cue (+15% type size, 25% elevation, per word, at the
color turn), and §2.3 gives every type value. Read it directly to settle any
question about intent.

**`docs/MOTION.md`** — the motion values in force, section by
section, with what we implement, where we deviate, and why. Use this to find a
number fast; use the PDF to settle an argument.

**`reference/cwi-quickstart-guide.pdf`** — the two-page After Effects
template workflow. Its key architectural rule: the `[START]`/`[END]` markers own
the animation window independently of the layer's lifetime. The live renderer
follows the same separation, with a one-time first-paint motion clock and an
independent speaker-color clock.

### 2. The reference recordings

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

### 3. Stills

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

### 4. The After Effects template

Not in this folder, but part of the same set: the official template in
`AE PROJECT/`. It is the *calm* reading of the system — it contains zero scale
animators, so following it literally would suppress §2.2.3's size pop. Useful for
the **shape** of the motion, but superseded by the PDF for amplitudes.

### Related working notes

- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — what the test suite covers and how to regenerate the
  golden prosody grid.
- **[RESEARCH.md](RESEARCH.md)** — prior DHH-captioning research
  mapped onto the design decisions here, plus the grounding for the haptic
  salience flags and the diarization and delivery-dynamics decisions.
- **[../web/README.md](../web/README.md)** — the frontend boundary and UI
  invariants.
- The bundled acceptance fixtures: `../docs/reference/pr-film.mp4` (English) and
  `../assets/sample-ko.wav` (Korean). Caption changes should be tested against
  both — a single-language run is not sufficient acceptance.

### `docs/reference/pr-film.mp4` (113 s, with audio)

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
