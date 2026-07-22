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
core contract; motion follows the official AE template (position + colour
only — see `cwi-design-system-notes.md`).

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

**CuCap** (ASSETS '25,
[doi](https://dl.acm.org/doi/epdf/10.1145/3663547.3746400)) — expressive
caption preferences differ across culture/language (English findings don't
transfer 1:1 to Korean); emotion visualization is liked in both. **Noted as a
boundary**: this project is English-first by measurement (the multilingual
checkpoint scored worse), and CuCap is the evidence that a future Korean
version needs its own preference pass, not a translation of this one.

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
problem. **Deferred — hardware**, with a concrete path: their DSP works with
any 2+ mics (180°), so a cheap stereo USB mic plus a numpy cross-correlation
would let direction *replace* `SpeakerTracker` as the speaker signal at a
booth table. Two co-located speakers would still need the embeddings.

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

## Haptics (the planned hardware module)

**Haptic-Captioning** (CHI '23,
[doi](https://dlnext.acm.org/doi/fullHtml/10.1145/3544548.3581076)) — wrist
vibration alongside captions helps DHH viewers track speaker changes and
frees gaze. **Adopted at the contract level**: durable word events now carry
`speaker_change: true`, so the haptic module can pulse on turn-taking without
any analysis of its own.

**Tactile Emotions** (CHI '25,
[pdf](https://saadh.info/papers/pataca-chi-25/pataca-chi25.pdf)) — combined
visual+haptic beats visual-only for immersion, but continuous vibration is
distracting; actuate selectively, threshold it, let users tune intensity.
**Adopted at the contract level**: `emphasis: true` flags only words that
exceed the speaker's median loudness by `haptics.emphasis_db` (config-exposed
threshold, per-user tunable). The rule for the future module: **actuate on
flags, never on every word.**

**SoundHapticVR** (ASSETS '24) / **SoundWeaver** (CHI '25) — spatial haptic
mapping and salience-driven fusion of multiple audio-AI outputs. **Deferred**;
SoundWeaver's principle (choose what matters *now*, don't show everything) is
the same philosophy as our salience flags and stable display mode.

**Rich Captions** (ASSETS '24) — one caption file with extra attributes, many
renderings. **Already covered**: that is precisely the CaptionSpec/SSE
contract — attributes travel with words; renderers (visual page, future
haptics) choose their own mapping.

## What this list changed in the code

1. `speaker_change` / `emphasis` salience flags on durable word events, with
   `haptics.emphasis_db` in config (Haptic-Captioning, Tactile Emotions).
2. Confirmation that colour stays attribution-only (Caption Royale vs CWI).
3. Everything visual remains config-tunable as the customization mechanism
   (Caption Royale, CuCap).
4. Deferred items are recorded here so they are decisions, not omissions.
