/**
 * WHICH LETTERS OF A WORD MOVE TOGETHER.
 *
 * The film does not lift a word's glyphs one at a time, and it does not lift
 * them as one block either: it lifts them in SYLLABLES. Read back frame by
 * frame from 28s on (`docs/reference/pr-film-annotated.txt`, annotated):
 *
 *     seen     ->  se | en
 *     Gump     ->  Gu | mp
 *     button   ->  but | ton
 *     because  ->  be | cause
 *     saying   ->  say | ing
 *     rescue!  ->  res | cue!
 *
 * and of the short words -- "I've", "many", "times", "but", "now", "I'm",
 * "like" -- the note is "all both lift", i.e. two halves, both leaving the
 * line. So even a monosyllable splits, at its nucleus.
 *
 * A fixed pair (`floor(index / 2)`) gets "se|en" and "Gu|mp" right and
 * "button" wrong (bu|tt|on), which is why this exists instead. Every split
 * above comes out of the rules below unchanged.
 *
 * This is TEXT structure, not audio: it is the same for a word however it was
 * spoken, so it is frozen with the word and cannot be re-derived under a
 * running animation.
 */

const VOWELS = new Set(["a", "e", "i", "o", "u"]);

/** `y` is a vowel except word-initially ("yes" vs "say", "many"). */
function isVowel(word: string, index: number): boolean {
  const c = word[index]?.toLowerCase() ?? "";
  if (VOWELS.has(c)) return true;
  return c === "y" && index > 0;
}

/** Maximal runs of vowels, as [start, endExclusive]. */
function nuclei(word: string): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  let start: number | null = null;
  for (let i = 0; i <= word.length; i += 1) {
    if (i < word.length && isVowel(word, i)) {
      if (start === null) start = i;
    } else if (start !== null) {
      out.push([start, i]);
      start = null;
    }
  }
  /* SILENT FINAL E. "times" and "because" both end on an `e` that carries no
     syllable, and counting it produces "tim|es" and "be|caus|e" -- neither of
     which the film shows. Dropped when it is a lone `e` with an earlier
     nucleus and NOTHING but a plural `s` after it.
     The tail test is this narrow on purpose: allowing any consonant after it
     also swallowed the real nucleus in "whatever" (-> "wha|tever"), because
     `e`-consonant-end looks identical from here whether the `e` is silent or
     not. Erring toward keeping it costs a boundary; erring the other way
     costs a whole group on every longer word. */
  if (out.length > 1) {
    const [s, e] = out[out.length - 1];
    const tail = word.slice(e);
    if (e - s === 1 && word[s]?.toLowerCase() === "e"
        && /^[^a-z]*s?[^a-z]*$/i.test(tail)) {
      out.pop();
    }
  }
  return out;
}

/**
 * The group index of every character, 0-based and contiguous.
 *
 * `maxGroups` caps how finely a long word divides -- watched, the film never
 * shows more than three or four moving parts in one word.
 */
export function syllableGroups(word: string, maxGroups = 4): number[] {
  const chars = [...word];
  const groups = new Array<number>(chars.length).fill(0);
  if (chars.length < 4) return groups;

  const cuts: number[] = [];
  const runs = nuclei(word);

  if (runs.length >= 2) {
    /* BETWEEN TWO NUCLEI, the consonants decide where the boundary falls:
       none -> at the next vowel ("say|ing"); one -> before it, leaving the
       first syllable open ("be|cause"); two or more -> inside the cluster,
       which is what closes the first syllable ("but|ton", "res|cue!"). */
    for (let i = 0; i + 1 < runs.length; i += 1) {
      const clusterStart = runs[i][1];
      const clusterEnd = runs[i + 1][0];
      const span = clusterEnd - clusterStart;
      cuts.push(span >= 2 ? clusterStart + 1 : clusterStart);
    }
  } else if (runs.length === 1) {
    /* A MONOSYLLABLE STILL SPLITS -- at its nucleus. A long nucleus divides
       inside itself ("se|en"); a short one hands the coda to the second group
       ("Gu|mp"). */
    const [s, e] = runs[0];
    cuts.push(e - s >= 2 ? s + Math.ceil((e - s) / 2) : e);
  }

  let boundaries = cuts.filter((c) => c > 0 && c < chars.length);
  boundaries = [...new Set(boundaries)].sort((a, b) => a - b);
  // Keep the outermost splits: a cap that dropped the tail would leave a long
  // word's last syllables fused to a group that already moved.
  while (boundaries.length > maxGroups - 1) {
    boundaries.splice(Math.floor(boundaries.length / 2), 1);
  }

  let group = 0;
  for (let i = 0; i < chars.length; i += 1) {
    if (boundaries.includes(i)) group += 1;
    groups[i] = group;
  }
  return groups;
}

/**
 * Does this word lift SYLLABLE BY SYLLABLE, rather than as one piece?
 *
 * The grouping above is finer than this on purpose: it is the wave's CLOCK,
 * and the film staggers `se|en` and `Gu|mp` at four letters. What it does not
 * do at four letters is visibly raise the halves independently -- those read
 * as one word leaving the line. From six letters up it does, which is where
 * `but|ton`, `say|ing`, `be|cause` and `res|cue!` all sit.
 *
 * So the timing splits early and the LIFT splits late, and this is the second
 * question. A word under the threshold still lifts -- as a whole word, on
 * `--word-lift-em`.
 */
export function liftsInGroups(word: string, minChars = 6): boolean {
  const chars = [...word];
  if (chars.length < minChars) return false;
  return Math.max(...syllableGroups(word)) > 0;
}

/** The first character index of each group, for reading a group's own clock. */
export function groupLeads(groups: number[]): number[] {
  const leads: number[] = [];
  groups.forEach((g, i) => {
    if (leads[g] === undefined) leads[g] = i;
  });
  return leads;
}
