# The motion system

Last updated: 2026-08-04. **This is the contract.** `DESIGN.md` is a changelog
of superseded interpretation; `../CLAUDE.md` holds the derivation and the record
of what was tried and reverted. If those disagree with this file, this file is
what ships.

## Five channels

Each has one owner and one input. They do not share state, and three pairs are
explicitly independent.

| # | channel | where | driven by | rest | reachable |
|---|---|---|---|---|---|
| 1 | **colour turn** (2.2.2) | `word-color-turn` on `.caption-character` | the word's onset, wiped across its spoken span | read-ahead ink | speaker colour |
| 2 | **pop** (2.2.3) | `word-sync-pop` on `.word-glyph` | nothing — constant on every word | 1.00 | 1.15 |
| 3 | **crest / size** (2.3.5-6) | `--voice-phase` x `--voice-scale`, a FONT-SIZE on `.word-ink` | `loudness` | 1.00 | 0.72 .. 1.62 |
| 4 | **weight** (2.3.8-9) | `font-weight: calc(...)` | the SPEAKER's median F0, plus prominence | 400 | 340 .. 900 |
| 5 | **hold / lift** | `word-hold-spring` on `.word-ink` | silence around the word | 0 | 0 .. 0.525em |

There is no sixth channel. Width (2.3.10) rides the word's own pitch and has no
floor to fall into; the character wave is texture under channel 1, not a channel.

## The four rules that are not visible in the table

**1. Size and lift are independent, and mutually exclusive.**
A word that swells does not leave the line. A word that lifts shows no crest and
no weight. The reference is unambiguous: its "louder" more than doubles and
stays planted; its "is" floats at exactly its resting size and is never bolder
than its neighbours.

**Both gates are BINARY.** Every word carries the 2.2.3 pop, so a proportional
gate taxes a word for a cue it did not ask for — "is" renders 1.23x of which
1.15 *is* that pop, and a graded rule took 38% of its lift for what is
essentially resting size.

**2. The crest overshoots, settles, sustains, then releases.**
Not a hump, not a plateau. Measured off the film's "louder":

```
rest ──rise 0.25s──▶ PEAK 3.12  ──0.21s──▶ 2.52 ──hold 0.33s──▶ ──0.21s──▶ rest
```

The sustain is 0.70 of the peak. **A rise time and a fall time cannot express
this** — that is why fitting two endpoints kept failing.

**3. Weight is a property of the voice, not the word.**
2.3.9 draws high pitch light; a shout's F0 doubles; so taken per word the
mapping renders the angriest voice as the thinnest text. 2.3.7 resolves it — its
domain is "the frequency range of a typical human voice" and it says "lower
VOICES are represented with a heavier weight." That is about **who is speaking**.
Within one speaker, going high is *effort*. So the register term reads
`pitch_register_hz`, the speaker's running median.

**3b. What the lift actually detects is ISOLATION, not sustain.**
The intent is "the speaker held this word". The signal is
`min(gap_before, gap_after)` over **inter-onset** intervals, inside a band:
`hold_min_s` 0.78 (below it, ordinary speech) → `hold_full_s` 0.88 (full lift),
with `hold_max_s` 1.06 on the leading gap because a longer silence is a
sentence break, which the film does not lift. Emphatic words are gated out
entirely — a word that swells does not leave the line.

**It cannot tell a drawn-out word from a word followed by a pause.** The
recognizer's `end` runs to the next word's onset and attributes no silence to
anything, so the interval after a word is its own duration *plus* any trailing
silence, lumped. Both readings produce the same number. Measured, three words
lift: `is` 0.525em, `god` 0.525em, `spoken` 0.105em.

A true "sustain" signal would need the word's own **voiced** duration per
character, which the prosody lane already computes — `_prominence`'s
lengthening term, currently at `length_gain: 0.0`.

**4. Everything is frozen at first sight.**
Duration, axes, sweep, hold gap and turn moment are computed once per word and
must survive remounts. Recomputing any of them under a running animation is the
bug this project re-commits most: it has caused a shifted `animation-delay`, a
crest that un-gated mid-flight, and a hold that became a coin flip.

## Timing

* Captions present from a clock **1.75 s behind** the acoustic one. That delay
  is the lag, one for one.
* **Read-ahead is a per-WORD floor** (`min_read_ahead_ms`, 420 ms), not a time
  delay. The recogniser blocks ~1.3 s at each endpoint and then releases a
  batch, so a delay moves the mean lead and leaves the spread alone: at 1.75 s
  the median lead was healthy 700 ms while 42% of words still turned within
  100 ms of appearing. The floor takes that to 0%.
* The floor cannot invent words the recogniser has not sent. Frames with no
  read-ahead at all sit at ~12%; that is ASR latency, not scheduling.

## Acceptance figures

Measured with `scripts/word_motion.py` on the bundled film (`--sample`, which
*is* the PR film). Re-measure these, not a slope, after touching any channel.

| | |
|---|---|
| `"louder"` | **1.83x**, weight **~890**, lift **0** |
| `"softer"` | **0.82x**, lift **0** |
| held `"is"` | lift **0.525em**, size **1.15x**, weight **400** — the FIRST "is" ("as each word is spoken"); the second is not held, and comparing by word text reads the wrong one |
| lifting words | `is` 0.525, `god` 0.525, `spoken` 0.105 — and the held word is **intermittent**, measured wrong in ~1 run of 6 |
| whole film | median peak **1.15x** — the ordinary word carries the pop and nothing else |
| | **0** words lighter than Regular, **0** bold samples on any lifted word |
| adjacent-row ink gap | 9 px at rest, **1.0 px under motion — no headroom left** |

## Before changing anything

1. **Screenshot it.** Three numeric probes called a glyph-anchoring change
   "probably fine"; one screenshot showed words overlapping and clipped off the
   stage. Layout and typography bugs are visual.
2. Use `scripts/word_motion.py`, not an ad-hoc aggregate. `max/min` over a
   word's samples cannot tell growth from shrinkage, and font-size alone misses
   the pop, which is a transform.
3. Re-run `scripts/ink_collision.py`. There is no clearance left; the next
   amplitude increase collides.
4. If a knob measures as a no-op, **say so and stop** — do not reach past it
   into shared structure. `voice_scale_range[0]` is inert because 2.3.6's
   3%/5% ratio is reached first; changing the mapping to make it bind also
   changed `reachableScaleRange`, which the hold and wave read, and broke the
   held word.
