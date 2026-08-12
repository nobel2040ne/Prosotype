/** WHICH LETTERS OF A WORD MOVE TOGETHER. */

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
  /* SILENT FINAL E. */
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

/** The group index of every character, 0-based and contiguous. */
export function syllableGroups(word: string, maxGroups = 4): number[] {
  const chars = [...word];
  const groups = new Array<number>(chars.length).fill(0);
  if (chars.length < 4) return groups;

  const cuts: number[] = [];
  const runs = nuclei(word);

  if (runs.length >= 2) {
    /* Between two nuclei the consonants decide the boundary: none -> at the
       next vowel ("say|ing"); one -> before it ("be|cause"); two or more ->
       inside the cluster, which closes the first syllable ("but|ton"). */
    for (let i = 0; i + 1 < runs.length; i += 1) {
      const clusterStart = runs[i][1];
      const clusterEnd = runs[i + 1][0];
      const span = clusterEnd - clusterStart;
      cuts.push(span >= 2 ? clusterStart + 1 : clusterStart);
    }
  } else if (runs.length === 1) {
    /* A MONOSYLLABLE STILL SPLITS -- at its nucleus. */
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

/** Does this word lift SYLLABLE BY SYLLABLE, rather than as one piece? */
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
