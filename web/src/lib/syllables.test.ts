import assert from "node:assert/strict";
import test from "node:test";

import {groupLeads, liftsInGroups, syllableGroups} from "./syllables.ts";

/** "but|ton" from the group indices, so a failure names the split. */
function split(word: string): string {
  const groups = syllableGroups(word);
  const parts: string[] = [];
  [...word].forEach((c, i) => {
    if (groups[i] !== groups[i - 1] && i > 0) parts.push("|");
    parts.push(c);
  });
  return parts.join("");
}

// THE FILM'S OWN SPLITS, read off frame by frame and recorded in
// `docs/reference/pr-film-annotated.txt`. These are the acceptance cases:
// the pairing rule this replaced got the first two right and "button" wrong.
test("the character groups are the film's syllables", () => {
  assert.equal(split("seen"), "se|en");
  assert.equal(split("Gump"), "Gu|mp");
  assert.equal(split("button"), "but|ton");
  assert.equal(split("because"), "be|cause");
  assert.equal(split("saying"), "say|ing");
  assert.equal(split("rescue!"), "res|cue!");
});

test("short words move as one piece", () => {
  for (const word of ["I", "so", "oh", "my", "God", "can", "wow"]) {
    assert.deepEqual(
      new Set(syllableGroups(word)),
      new Set([0]),
      `${word} should not split`,
    );
  }
});

// "many, times, but, now, I'm, like: all both lift" -- two halves, both
// leaving the line, which is the whole point of splitting a monosyllable.
test("four-letter words still split in two", () => {
  for (const word of ["many", "times", "I've", "like", "much", "more"]) {
    assert.equal(
      Math.max(...syllableGroups(word)) + 1,
      2,
      `${word} should be two groups, got ${split(word)}`,
    );
  }
});

test("groups are contiguous and start at zero", () => {
  for (const word of ["understand", "Sergeant", "whatever", "purpose", "a"]) {
    const groups = syllableGroups(word);
    assert.equal(groups.length, [...word].length);
    assert.equal(groups[0], 0);
    for (let i = 1; i < groups.length; i += 1) {
      const step = groups[i] - groups[i - 1];
      assert.ok(step === 0 || step === 1, `${word} jumps at ${i}`);
    }
  }
});

test("a long word is capped, not fragmented", () => {
  for (const word of ["understanding", "unbelievable", "communication"]) {
    assert.ok(
      Math.max(...syllableGroups(word)) + 1 <= 4,
      `${word} split into ${split(word)}`,
    );
  }
});

test("groupLeads is the first index of each group", () => {
  assert.deepEqual(groupLeads(syllableGroups("button")), [0, 3]);
  assert.deepEqual(groupLeads(syllableGroups("seen")), [0, 2]);
  assert.deepEqual(groupLeads([0, 0, 0]), [0]);
});

// THE LIFT SPLITS LATER THAN THE TIMING DOES. The film staggers `se|en` at
// four letters but raises the halves independently only from six up -- which
// is where every one of its own split-lift words sits.
test("only words of six letters or more lift in parts", () => {
  for (const word of ["button", "saying", "because", "rescue!", "Sergeant"]) {
    assert.ok(liftsInGroups(word), `${word} should lift in parts`);
  }
  for (const word of ["seen", "Gump", "many", "times", "I've", "so", "wow"]) {
    assert.ok(!liftsInGroups(word), `${word} should lift as one word`);
  }
});

test("the timing split is unchanged by the lift threshold", () => {
  // `seen` still staggers -- it just does not raise its halves separately.
  assert.equal(Math.max(...syllableGroups("seen")) + 1, 2);
  assert.ok(!liftsInGroups("seen"));
});
