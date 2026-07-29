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
line-edge voice circle and the larger Voice Compass instead of the caption
letters.

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

## Live diarization model decision (updated 2026-07-25)

The live default is now a **hybrid**, not one model pretending to solve two
different problems:

1. [`nvidia/diar_streaming_sortformer_4spk-v2.1`](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1)
   supplies continuous, arrival-ordered speaker activity with the official
   1.04 s low-latency context and four native slots.
2. Endpoint pyannote segmentation plus a full-turn speaker embedding verifies
   the durable S1/S2 identity, recovers quiet speech that Sortformer omitted,
   and continues beyond four total identities.

Installing NeMo directly was rejected for this application environment: the
current official stack targets Python 3.12/PyTorch 2.7, while Prosotype is pinned
to Python 3.11/PyTorch 2.5 and uses local CPU/Core ML inference. Instead, a
small Swift helper pinned to
[FluidAudio](https://github.com/FluidInference/FluidAudio) 0.15.5 owns the
palettized Core ML model and streams timeline snapshots to Python. This keeps
the ASR process free of NeMo's dependency/runtime cost.

Measured on the target Apple Silicon machine after model preparation:

- the 34.5 s English dialogue processed in 4.01 s (8.6× real time);
- the 13.3 s Korean sample processed in 1.50 s (8.9× real time);
- cached model load was 0.14 s (the one-time download/Core ML preparation is
  performed by the setup script).

The first integration pass exposed an important distinction between raw DER and
caption behavior. Sortformer's English timeline found the main two actors, but
also emitted a short third slot for a quiet “Uh, yeah” and a faint overlapping
track inside one turn. Projecting by overlap duration alone created visible
speaker flicker. The shipped projection therefore weights overlap by model
activity, uses endpoint embeddings as the identity verifier, maps reliable
Sortformer slots into the durable S1… namespace, and lets a weak embedding merge
a transient extra slot back to an existing speaker. The real English
`live --sample --lang en` acceptance then produced only S1/S2 and the expected
alternating dialogue turns.

Live microphone testing later exposed the remaining count failure: an
unverified Sortformer slot was allowed to become S3/S4 immediately, while a
single noisy endpoint span could enroll S3…S6 by duration alone. The deployed
policy now keeps only S1/S2 immediate. Higher native slots fall back to
non-learning identity classification, and a third-or-later embedding identity
must recur in a second clean endpoint observation before becoming public.
Pending words are then revised to the confirmed identity. This preserves
multi-person support while preventing one-off tracks from presenting two
people as five.

Identity encoder choice is language-specific and measured:

- **English:** 3D-Speaker ERes2Net remains best on the bundled film. Meaningful
  same-speaker turn pairs measured approximately 0.30–0.57, cross-speaker pairs
  0.04–0.25, with a 0.046 worst-case clean margin and about 66 ms mean
  inference. TitaNet Small/Large and multilingual CAM++ separated this sample
  less reliably.
- **Korean:** multilingual 3D-Speaker CAM++ is the fallback. On two held-out
  FLEURS Korean voices it preserved essentially the same clean same-vs-cross
  margin as ERes2Net (about 0.418) while running about 32 ms instead of 90 ms
  for the measured spans, approximately 2.8× faster. The real single-speaker
  Korean sample kept all 14 word IDs on S1 and now finalizes them at the ASR
  endpoint even though Korean intentionally has no weaker offline text
  verifier.

This is not evidence that Sortformer is language-neutral. NVIDIA notes that the
checkpoint was trained primarily on English, and it directly supports only four
speaker slots. Korean therefore retains CAM++ endpoint verification, and every
unsupported platform or failed native startup automatically uses the ONNX
embedding path. `--diarizer embedding` is the controlled A/B, not a dead legacy
branch.

For offline media, `pyannote/speaker-diarization-community-1` is the clear
upgrade from the configured 3.1 pipeline: its model card reports improved
speaker assignment/counting, exclusive diarization for ASR alignment, and
lower DER on most listed benchmarks. It is tied to the pyannote 4.x model
collection and gated weights, while this environment remains pinned to
pyannote.audio 3.3.2, so that upgrade should be isolated from the latency-critical
live environment rather than silently changing its dependencies.

## Korean streaming ASR decision (updated 2026-07-25)

The first backend was the official 2024
[sherpa-onnx Korean streaming Zipformer](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html#sherpa-onnx-streaming-zipformer-korean-2024-06-16-korean).
It established the correct architecture—a true online transducer with timed
leading-space pieces—but its recognition was not good enough. On the four
bundled KSS utterances it produced 11 character edits out of 76 (14.47% CER)
at 0.068 RTF.

The replacement is the 2026
[174M Korean causal Zipformer](https://huggingface.co/kangkyu/icefall-asr-ko-streaming-zipformer-174m),
trained on roughly 6,500 hours of KsponSpeech + AIHub. Its model card reports
8.255% CER / 0.073 RTF for chunk-16 and 7.815% / 0.054 for chunk-32 on the same
6,000-cut KsponSpeech evaluation. Local A/B found both chunks perfect on the
bundled set; chunk-16 was selected because its first visible hypothesis arrived
at 1.152 s of source audio versus 1.472 s for chunk-32. The configured chunk-16
path measured 0/76 character edits and 0.083 RTF on this M1.

A live event trace on 2026-07-25 measured partial stability as well as final
CER. The 174M decoder revised one current word slot at a time
(`아` → `아프리카` → `아프리카의`,
`야생` → `야생동물` → `야생동물들을`) and only once exposed two tentative
words at the tail. Earlier words were already durable commits. This is useful
progressive Hangul, not historical-caption churn; the presentation layer now
keeps the current accurate hypothesis visible while bounding simultaneous
first-paint motions—not visible words—to two.

The current model remains the best local streaming choice found:

- its official card reports 8.255% streaming CER at 320 ms for chunk-16;
- its 72M sibling is less accurate in the card's direct evaluation;
- SenseVoiceSmall supports Korean, but sherpa-onnx lists the released Korean
  checkpoint under non-streaming ASR, while FunASR's named streaming Paraformer
  checkpoint covers Chinese/English;
- Qwen3-ASR and Whisper are larger offline challengers, and the 174M card's
  same-set comparison reports lower Korean CER than both.

Do not swap models from a final-transcript demo. A challenger must beat the
174M path on first-word source latency, maximum mutable-tail length, committed
prefix rollback count, Korean CER, and CPU RTF on the same recordings.

An official 2024 offline Korean Zipformer was also tested as an endpoint
corrector. It reduced the old stream to 1/76 edits at only 0.013 RTF, and
exposed a sherpa formatting bug: `result.text` removed all Korean spaces even
though `result.tokens` retained exact leading-space boundaries. The generic
verifier now reconstructs those boundaries and normalization is Unicode-aware.
It is not enabled for Korean, because it changed one phrase that the stronger
174M live stream had already recognized correctly.

The language boundary remains strict: selection is locked before model load;
English Parakeet and TIMIT sidecars are disabled; `--sample` is resolved only
after selection so `--sample --lang ko` uses `assets/sample-ko.wav` rather than
silently feeding the English CWI video to a Korean recognizer.

## Speech emotion / intention sidecar decision (2026-07-25)

“Intention” needs two separate meanings here. Acoustic affect—angry, sad,
happy, fearful, surprised—is audible and can shape future caption motion.
Semantic intent—question, request, warning, sarcasm—depends on recognized text
and conversation context. A single late utterance label must not be allowed to
rewrite either one onto words the viewer has already read.

The first local prototype candidate is
[SenseVoiceSmall](https://github.com/QwenAudio/SenseVoice). Its released
checkpoint accepts Korean as well as Mandarin, Cantonese, English, and
Japanese, and emits seven emotion tags together with ASR/audio-event output.
Its non-autoregressive architecture and current CPU/edge runtimes make it the
most practical sidecar to measure in this application. It is not yet a product
dependency: the official speech-emotion comparison is reported on Chinese and
English test sets, not Korean, and its checkpoint uses the separate
[FunASR model license](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE).
Korean recognition support is not evidence of Korean emotion accuracy.
The official
[sherpa-onnx SenseVoice recipe](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)
is attractive because this repository already ships that runtime: its int8
model is 228 MB and exposes an `emotion` result. It is still utterance-level,
non-streaming inference simulated behind VAD, so it cannot truthfully drive the
beginning of the word that supplied its own label.

The benchmark challenger is
[emotion2vec+ base](https://huggingface.co/emotion2vec/emotion2vec_plus_base).
It is approximately 90M parameters and exposes nine categories, including
angry and neutral. The underlying
[ACL 2024 emotion2vec paper](https://aclanthology.org/2024.findings-acl.931/)
reports gains across ten speech-emotion languages, and the model can emit
frame-level features at 50 Hz. However, the published checkpoint card does not
show a Korean confusion matrix or true streaming latency, and its weight
license is also a model-specific agreement. It is a useful A/B model, not a
reason to replace the current acoustic motion rules.

The dimensional
[audEERING wav2vec2 emotion model](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim)
is attractive because arousal/dominance/valence map more naturally to
continuous typography than a hard “angry” label. It is rejected for shipping:
it was fine-tuned on English MSP-Podcast, is roughly 200M parameters, and is
CC BY-NC-SA research-only. It remains a useful offline comparison.

[EmoBox](https://arxiv.org/abs/2406.07162) reinforces the evaluation warning:
its unified benchmark spans 32 datasets and 14 languages precisely because
cross-corpus speech-emotion results do not transfer cleanly. A model may not be
called “Korean-capable” here merely because Korean ASR tokens are supported.

[Voice Activity Projection](https://arxiv.org/abs/2205.09812) and its
[real-time](https://arxiv.org/abs/2401.04868) and
[multilingual](https://arxiv.org/abs/2403.06487) variants are candidates for a
different intention channel: floor holding, turn completion, and likely
backchannels. They predict conversational timing, not emotion, so they should
eventually guide the compass/turn boundary rather than emotion-label a word.

Korean evaluation should use ETRI's
[KEMDy20](https://epretx.etri.re.kr/dataFileList?id=318&lang=ko) dyadic
conversation corpus, subject to its data agreement, plus a small booth-domain
set recorded with the actual microphone. Report macro F1/confusion—especially
angry versus neutral/happy—not just overall accuracy, because the class
distribution is imbalanced.

The only acceptable live integration is:

1. Run a sidecar on a rolling 1.5–2.5 s raw-audio window with a 320–500 ms hop.
2. Smooth probabilities with hysteresis; an isolated frame cannot flip intent.
3. Freeze the estimate onto a word only before that word's first visible paint.
4. Let arousal alter the *distance/hold* of a future word's existing CWI
   envelope. Do not shake letters or shorten the calm 520–720 ms motion into
   an “angry” twitch. Keep pitch→weight and loudness→size interpretable.
5. Never retroactively animate, resize, or reweight a visible word. A late
   estimate may update a diagnostic panel, not historical caption geometry.

### Applied now: delivery dynamics, not emotion claims

No speech-emotion model is loaded by the runtime today. Instead, the live path
measures language-independent, directly observable delivery dimensions:

- `delivery_force`: captured level relative to the live acoustic range;
- `delivery_attack`: early word energy relative to its preceding context;
- `delivery_contour`: first-to-last voiced F0 change, in bounded semitones;
- `delivery_flow`: voiced continuity/periodicity;
- `delivery_texture`: a restrained aperiodicity/brightness mixture;
- `delivery_confidence`: whether the word span contains enough evidence.

Those continuous values choose a primary diagnostic profile—`rising`,
`falling`, `sustained`, `forceful`, `gentle`, `textured`, or `steady`—but the UI
never presents that profile as the speaker's inner emotion. Each expressive
profile owns a different zero-to-rest path: rising develops its crest late,
falling crests early and resolves downward, sustained holds, forceful travels
farther from a measured attack, gentle eases through a smaller arc, and
textured adds a soft resonance halo without shaking letters.

The first implementation reused the 64 ms real-time orb pitch samples for word
contour and accepted only two voiced samples with a ±0.25 threshold. Octave
jumps saturated ordinary words and marked 86.4% of English / 92.9% of Korean
sample words expressive. Durable contour now uses a Praat 10 ms track with at
least five voiced frames, 30% coverage, a 1.6× median octave filter, seven
semitones to full scale, and a ±0.45 profile deadband. `steady` words retain
only 30% of the additional expressive presentation gain. The fixed live
synchronization cue is separate: every active word still receives at least a
10% scale pop and 0.20 em rise. A separate presentation-only family selector
uses trustworthy sub-threshold continuous dimensions to vary timing without
changing that conservative diagnostic label.

The per-word result is written to `delivery_cache` on the first event for its
time slot and is never remeasured for verification. The ~64 ms `level` lane
separately sends rolling force/attack/contour/flow/texture to the line orb and
Voice Compass, so the voice has an immediate visual presence before ASR emits a
word. All word paths end at identity transform, weight 400, width 100, and zero
halo.

Paced 2026-07-25 product acceptance used both standard samples in real Chrome.
English produced 59 unique styled words with 22.0% expressive; Korean produced
14 with 28.6% expressive. Repeated SSE records changed zero frozen delivery
signatures in either language. At EOF both browsers reported zero active or
pending motions and zero settled words with residual geometry/font effects.
A direct browser path probe exercised all six expressive families plus the
steady fallback and observed distinct glyph plus weight/width curves. After
restoring reference-scale
travel, a representative rising word reached 15.9% scale and 4.712 px lift;
the largest vertical frame step stayed at 0.482 px and the word returned to
identity/400/100%. Across paced product samples, English targets ranged
10–25.7% scale and 0.201–0.250 em lift; Korean ranged 10–16.3% and
0.200–0.229 em.

SenseVoiceSmall remains the first categorical sidecar challenger, not a motion
dependency. It may be added only as an opt-in diagnostic after Korean
macro-F1/confusion, local RTF, license, and rolling-window stability are
measured. A late categorical result may never animate historical words.

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
mapping and salience-driven fusion of multiple audio-AI outputs. **Deferred**;
SoundWeaver's principle (choose what matters *now*, don't show everything) is
the same philosophy as our salience flags and stable display mode.

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
5. Direction has a clean weak-prior hook but stays inactive without actual
   multi-microphone input.
6. Deferred items are recorded here so they are decisions, not omissions.
