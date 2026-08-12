# Korean expression: what is measured, and what is missing

Measured 2026-08-10, after a report that Korean captions do not convey emotion
the way English does.

**Two findings, and the first round only got half of it.**

1. Every **word-level** channel — size, weight, lift — behaves the same in Korean
   as in English. The words Korean picks out are arbitrary because the sample is
   neutral read narration: **that half is the material, not the renderer.**
2. The **per-character** channel is a different story, and the first round missed
   it by measuring only word-level statistics. It was 2.1x coarser in Korean, in
   the channel that carries ordinary words. **That half was a real defect and is
   now fixed** — see "What was fixed" below.

Three hypotheses were tested in round one and **all three were wrong**; they are
kept here so they are not re-proposed.

## The measurement

`scripts/motion_trace.py` (new — the producer `word_motion.py` documents had
never been in the repo) captured both languages through the same instrument at
30 ms, then `scripts/word_motion.py` scored them. `--sample --loop`, 45 s each,
1440×900.

| | **Korean** | **English** |
|---|---|---|
| words observed in motion | 45 | 127 |
| median peak size | **1.14x** | **1.16x** |
| p90 peak size | **1.80x** | **1.81x** |
| max peak size | **1.81x** | **1.84x** |
| % words above 1.20x | **29%** | **29%** |
| % words above 1.50x | 16% | 22% |
| min floor (shrink) | 0.81x | 0.82x |
| weight at rest | **400** | **400** |
| max weight peak | **893** | 858 |
| words that lift | **3** | 0 \* |
| max lift | **0.525em** | — \* |
| median motion width | 0.22s | 0.21s |

\* The English capture is a 45 s window of a 68.6 s loop, so it did not
necessarily contain the film's held `"is"` (t≈6.9 s), and `"is"` occurs twice
with only the first held. Read as a limitation of the capture window, **not** as
English having lost its lifts.

Korean reaches the same crest, the same weight, the same motion width, and the
same proportion of emphasized words. It also lifts, which is the channel most
likely to have silently died.

## What was tried and did not explain it

Three plausible explanations were tested and none survived: that the Korean
clock was wrong, that the wide-script wipe was dropping motion, and that a
prosody constant needed refitting for Korean. The measurements are in the
decision log. What they left is the section below — the material, not the code.

## What is actually wrong

**The motion fires correctly on material where loudness variation is incidental
rather than communicative.**

Which words each language renders above 1.4x:

- **Korean:** `육로` 1.81x, `사바나의` 1.81x, `사파리라는` 1.45x — and *only* those
  three, at the same values on every loop.
- **English:** `instantly` 1.84x, `they` 1.83x, `caption` 1.82x, `character`,
  `know`, `varying`, `word`, `dynamic`, **`louder`**, `captions`, `brings`,
  `uses` …

`사파리라는` means "called safari". `육로` means "land route". These are ordinary
content nouns in a neutral encyclopedia sentence and **nobody said them with
emphasis** — they are simply the syllables that happened to carry more energy.
The mapping is deterministic and repeatable (the same three words hit the same
1.81x every loop), so it is tracking something real in the audio. It is just not
tracking anything a listener would call emphasis.

English's list contains `louder`, which an actor deliberately says louder. That
is the difference, and it is in the recording, not the renderer.

### The material

| | `sample.mp4` (English) | `sample-ko.wav` (Korean) |
|---|---|---|
| length | 68.6 s | **13.3 s** |
| content | performed film, actor demonstrating loud/soft, shouted exchange | **read FLEURS narration**, encyclopedic text |
| speakers | 11 | 1 |
| level span p10–p95 | 20.1 dB | 22.7 dB |
| F0 span p10–p90 | 247 Hz | **74 Hz** |
| median level | −24.1 dBFS | **−53.6 dBFS** |
| held out from eval? | n/a | **no — it is FLEURS ko row 16** |

The Korean clip is 30 dB quieter, one sixth the length, monotone by
construction, and part of the set the recognizer is scored on.

**So the blocker is Korean reference material, and no amount of tuning
substitutes for it.** Every English constant in `config.yaml` was swept against
audio with intentional prosody. Re-fitting them against neutral narration would
produce numbers that look tuned and mean nothing — the failure this project
records as *"an unmeasured change is worse than none."*

## What to record next

Roughly 60–90 s of Korean, matching what the English film supplies: an ordinary
line, one deliberately louder word, one hushed word, a shouted line, a held word
with silence either side, and two speakers. That is enough to (a) see whether the
mapping reads Korean emphasis correctly and (b) give the demo something to show.
It also removes the held-out problem.

Only after that: per-language expression overrides. `config.yaml`'s `ko` overlay
currently carries **only ASR settings** — every prosody constant is global.

## References

Found for this question; the first is the direct one and was already cited in
[RESEARCH.md](RESEARCH.md).

- **CuCap** (ASSETS '25) — 49 DHH participants, 28 North American and 21 South
  Korean, customizing which speech features their captions display. **Emotion
  visualization was universally favoured; *prosody* preferences diverged by
  culture and language.** Precisely this problem's shape: the intent transfers,
  the prosody→type mapping does not. RESEARCH.md already concluded a Korean
  version "needs its own preference pass, not a translation of this one."
  <https://dl.acm.org/doi/10.1145/3663547.3746400>
- **Interpretive Caption** (ASSETS '25) — real-time vocal emotion cues for DHH.
  <https://dl.acm.org/doi/pdf/10.1145/3663547.3759697>
- **OnomaCap** (CHI '25) — non-speech sound captions through onomatopoeia, from a
  sound-to-onomatopoeia dataset **transcribed by Korean listeners** and
  deliberately differentiated ("eu hak ha ha" for a boisterous laugh, "he he" for
  a soft one) rather than one generic word per sound. Korean 의성어/의태어 is a
  native expressive resource with no English equivalent, and this project already
  has a non-speech sound lane (`autocwi/soundevents.py`) emitting English
  category labels. <https://dl.acm.org/doi/full/10.1145/3706598.3713911>
- **Design of Kinetic Typography Interaction based on the Structural
  Characteristics of Hangul** (Int. J. Contents, 2016) — Hangul syllables are
  **가로모임 / 세로모임 / 섞임모임** (horizontal-, vertical-, mixed-gather) by
  consonant–vowel composition, and that structure is what its motion system keys
  on. The Hangul-native typographic axis Latin has no equivalent of — the
  candidate to look at *if* a Korean-specific channel is ever wanted.
  <https://koreascience.or.kr/article/JAKO201629149528406.page>
- **Using kinetic typography to convey emotion in text-based interpersonal
  communication** (DIS '06) — the foundational kinetic-typography-for-emotion
  result. <https://dl.acm.org/doi/10.1145/1142405.1142414>

## One English observation, deliberately not acted on

The same capture shows **48 of 127 English words dipping to weight ~351** during
their motion window — all unstressed function words (`the`, `so`, `as`, `each`,
`is`), floor clustered tightly at 351–352, never below 350.

`docs/MOTION.md`'s acceptance table says **0 words lighter than Regular**, while
The §2.3.9 reading in force says light unstressed words are *"2.3.9 working"*
and quotes `whats`/`this` at 340/355. **The two disagree**, and this measurement
is a transient dip inside the motion window rather than a resting weight
(`weight_rest` is 400 for all of them), which may be a third thing again.

Not investigated and not changed: English motion was reported as fine, and
resolving this needs a decision about which of the two documents is right.
