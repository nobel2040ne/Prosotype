import assert from "node:assert/strict";
import test from "node:test";
import {isWideChar, syllable, waveGrain, wordIsWide} from "./hangul.ts";

const cp = (ch: string) => ch.codePointAt(0)!;

// --- script classification ----------------------------------------------

test("wide characters cover the scripts captions actually use", () => {
  for (const ch of ["가", "힣", "ㄱ", "漢", "字", "あ", "ア", "，", "！"]) {
    assert.ok(isWideChar(cp(ch)), `${ch} is wide`);
  }
  for (const ch of ["a", "Z", "0", "-", ".", " ", "'", "é"]) {
    assert.ok(!isWideChar(cp(ch)), `${ch} is narrow`);
  }
});

test("an all-Latin word is NEVER wide", () => {
  /*
   * THE MOTION GATE. A word classified wide takes the continuous-wipe path;
   * an English word must never reach it, or English motion moves — and every
   * motion acceptance figure is measured on the English film.
   */
  for (const text of [
    "louder", "softer", "is", "synchronized", "precisely", "animation,",
    "Goddamnit", "a", "don't", "1640", "S1:", "", "...", "café",
  ]) {
    assert.equal(wordIsWide(text), false, `"${text}" must stay narrow`);
  }
});

test("an all-Hangul word is wide", () => {
  for (const text of ["육로", "사바나의", "야생동물들을", "가"]) {
    assert.ok(wordIsWide(text), `"${text}" must be wide`);
  }
});

test("a mixed word follows its majority script, ignoring punctuation", () => {
  // `2011년` is mostly digits, so it stays on the per-glyph path; `한국2` is
  // mostly Hangul. Punctuation is script-neutral and must not tip either.
  assert.equal(wordIsWide("2011년"), false);
  assert.ok(wordIsWide("한국2"));
  assert.ok(wordIsWide("사파리."));
  assert.equal(wordIsWide("safari."), false);
});

// --- syllable structure (Phase 2 input) ----------------------------------

test("the composition axis follows where the vowel sits", () => {
  // 가 = ㄱ+ㅏ, vowel to the RIGHT -> horizontal gather (가로모임)
  assert.equal(syllable(cp("가")).axis, "horizontal");
  // 고 = ㄱ+ㅗ, vowel BELOW -> vertical gather (세로모임)
  assert.equal(syllable(cp("고")).axis, "vertical");
  // 의 = ㅇ+ㅢ, a compound vowel -> mixed (섞임모임)
  assert.equal(syllable(cp("의")).axis, "mixed");
});

test("batchim is detected independently of the axis", () => {
  assert.equal(syllable(cp("가")).batchim, false);
  assert.equal(syllable(cp("각")).batchim, true);   // horizontal + closing ㄱ
  assert.equal(syllable(cp("곡")).batchim, true);   // vertical + closing ㄱ
  assert.equal(syllable(cp("고")).batchim, false);
});

test("a non-Hangul character has no axis", () => {
  for (const ch of ["a", "1", "漢", "ㄱ"]) {
    assert.equal(syllable(cp(ch)).axis, "none");
    assert.equal(syllable(cp(ch)).batchim, false);
  }
});

test("every Hangul syllable classifies, and all three axes occur", () => {
  // The block is 11,172 syllables; none may fall through to "none", or a
  // real caption would silently lose its per-character treatment.
  const seen = new Set<string>();
  for (let i = 0; i < 11172; i += 1) {
    const s = syllable(0xac00 + i);
    assert.notEqual(s.axis, "none");
    seen.add(s.axis);
  }
  assert.deepEqual([...seen].sort(), ["horizontal", "mixed", "vertical"]);
});

test("the axis mix of real Korean caption text is not degenerate", () => {
  // If one class dominated completely there would be nothing for an
  // axis-aware wave to express. Measured on the bundled sample's vocabulary:
  // roughly 64% horizontal, 29% vertical, 7% mixed.
  const text = "널리알려진사파리라는표현은특히사바나의멋진아프리카의야생동물들을보기위한육로여행을칭한다";
  const counts: Record<string, number> = {};
  for (const ch of text) {
    const {axis} = syllable(cp(ch));
    counts[axis] = (counts[axis] ?? 0) + 1;
  }
  assert.ok(counts.horizontal > 0 && counts.vertical > 0 && counts.mixed > 0);
  // No single class may swallow the text.
  for (const n of Object.values(counts)) {
    assert.ok(n / text.length < 0.9);
  }
});

// --- Hangul-structural wave grain ---------------------------------------

test("the wave breathes along the block's own grain", () => {
  // 가 is horizontal-gather: the vowel sits to the RIGHT, so the block reads
  // wide and stretches along its width.
  const horizontal = waveGrain(cp("가"));
  assert.ok(horizontal.ax > 0, "horizontal-gather stretches wider");
  assert.ok(horizontal.ay < 0, "...and not taller");

  // 고 is vertical-gather: vowel BELOW, so it stretches upward like Latin.
  const vertical = waveGrain(cp("고"));
  assert.ok(vertical.ay > 0, "vertical-gather stretches taller");
  assert.ok(vertical.ax < 0);
});

test("a batchim damps the vertical stretch and leaves the horizontal alone", () => {
  // 각 = 가 + closing ㄱ. The consonant fills the lower half, so there is less
  // vertical slack; the width is unaffected.
  const open = waveGrain(cp("고"));
  const closed = waveGrain(cp("곡"));
  assert.ok(Math.abs(closed.ay) < Math.abs(open.ay), "less vertical excursion");
  assert.equal(closed.ax, open.ax, "width term untouched");
});

test("a non-Hangul character inside a wide word keeps the Latin shape", () => {
  // A digit or loanword letter IS a Latin letterform; giving it a Hangul grain
  // would be applying the wrong model to the right glyph.
  assert.deepEqual(waveGrain(cp("2")), {ay: 0.13, ax: -0.022});
  assert.deepEqual(waveGrain(cp("a")), {ay: 0.13, ax: -0.022});
});

test("no grain exceeds the amplitude the Latin wave already uses", () => {
  // The wave was deliberately halved once because it competed with the 2.2.3
  // cue. Redistributing it across axes must not smuggle that back.
  for (let i = 0; i < 11172; i += 7) {
    const {ay, ax} = waveGrain(0xac00 + i);
    assert.ok(Math.abs(ay) <= 0.13 + 1e-9);
    assert.ok(Math.abs(ax) <= 0.13 + 1e-9);
  }
});
