# docs/ — the sources this implementation is derived from

Nothing here is generated. These are the primary materials, and the order below
is the order of authority: where two disagree, the one above wins.

## 1. The design system

**`cwi-design-system-v1.0.pdf`** — *Caption with Intention, Design System and
Caption Guidelines, V 1.0 (2025.1)*, 54 pp., by the Chicago Hearing Society.
Also at
<https://download.captionwithintention.org/Caption-With-Intention_Design-System_V1.0.pdf>.

**This is the authority.** It states the motion outright — §2.2.3 gives the
whole synchronization cue (+15% type size, 25% elevation, per word, at the
colour turn) and §2.3 gives every type value. Read it directly before
inferring anything from the recordings; several rounds of work here were spent
measuring video for numbers that were one page of this PDF away.

**`cwi-design-system-notes.md`** — the extracted values, section by section,
with what we implement, what we deviate from, and why. Read this to find a
number fast; read the PDF to settle an argument.

## 2. The reference recordings

`reference/` — three screen captures of the official site, each beside the
transcript read off its own frames:

| | recording | transcript |
|---|---|---|
| Character Identification | `character_identification.mov` | `character_identification.txt` |
| Synchronization | `synchronization.mov` | `synchronization.txt` |
| Intonation | `intonation.mov` | `intonation.txt` |

These are a *different implementation* of the design system — the website, not
the PDF and not the After Effects template — so they are evidence about
behaviour, never about intent. What they supply that the PDF cannot: the timing
of the motion, and which specific word in each sentence is actually loud, quiet
or bold. `scripts/derive_reference_spec.py` measures both out of the pixels
into `assets/reference_specs/`; the README has the commands and the per-file
fps, crop and flags.

The `.txt` files are `SPEAKER<TAB>text`, one caption per line, in **recording**
order, with `-` marking an instance to measure but not emit (a repeated section
heading, a loop repeat). They must list every caption instance the recording
shows, because groups are matched to them positionally.

## 3. Stills

`stills/` — frames kept for details that are easier to see than to describe:

- `site-volume-and-sync.png` — the volume waveform beside a caption mid-sweep,
  with the playhead and the colour boundary landing inside a word.
- `site-volume-and-pitch-axes.png` — the two intonation channels drawn as
  axes: low/high volume against type size, low/high pitch against weight.
- `film-pulp-fiction-royale.png` — "Roya|le with Cheese!": the mid-word colour
  boundary, cited throughout `CLAUDE.md` as proof the turn sweeps *through* a
  word rather than flipping it.
- `film-back-to-the-future-thank-you.png` — speaker colour plus a mid-word
  boundary on a short line.
- `film-toy-story-star-command.png` — emphasis on a single word ("read")
  inside an otherwise uniform line, which is the density the design aims for:
  occasional, not continuous.

The film stills are also where the **resting** type size was checked: they sit
nearer 4% of frame height than the 5% baseline of §2.3.5, because the box hugs
one short line.

## 4. Working notes

**`TESTS.md`** — what the suite covers, how to run it, and how to regenerate
the golden prosody grid when `mapping` or `expression` changes.

## 5. Research

**`research-notes.md`** — prior DHH-captioning research mapped onto the design
decisions here, and the grounding for the haptic salience flags (why a device
should actuate on speaker changes and emphasis rather than on every word).

---

Not in this folder, but part of the same set: the official After Effects
template in `AE PROJECT/`. It is the calm reading of the system — it contains
zero scale animators, so following it suppressed §2.2.3's size pop entirely.
Useful for the *shape* of the motion, superseded by the PDF for amplitudes.
