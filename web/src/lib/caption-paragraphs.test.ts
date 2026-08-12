import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCaptionParagraphs,
  isWideChar,
  planCaptionStackMotion,
  selectStableCaptionStack,
  createStageMemory,
  wordWidthEm,
} from "./caption-paragraphs.ts";
import type {CaptionWord} from "./caption-store.ts";

/* `final: true`: these fixtures stand for text the viewer has already read,
   which is what the row-identity rules are about. */
function sentence(
  count: number,
  speaker = "S1",
): {
  words: Record<string, CaptionWord>;
  order: string[];
} {
  const words: Record<string, CaptionWord> = {};
  const order: string[] = [];
  for (let index = 0; index < count; index += 1) {
    const id = `u0:w${index}`;
    order.push(id);
    words[id] = {
      word_id: id,
      text: `word-${index}`,
      start: index * 0.2,
      end: index * 0.2 + 0.18,
      speaker,
      speaker_status: "stable",
      final: true,
    };
  }
  return {words, order};
}

test("a long speaker turn remains one wrapping paragraph", () => {
  const input = sentence(36);
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
    0,
  );
  assert.equal(paragraphs.length, 1);
  assert.equal(paragraphs[0].words.length, 36);
});

test("a real speaker change starts a new paragraph", () => {
  const input = sentence(18);
  for (let index = 11; index < 18; index += 1) {
    input.words[`u0:w${index}`].speaker = "S2";
  }
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
    0,
  );
  assert.deepEqual(
    paragraphs.map((paragraph) => [
      paragraph.speaker,
      paragraph.words.length,
    ]),
    [["S1", 11], ["S2", 7]],
  );
});

test("a new utterance starts a paragraph even for the same speaker", () => {
  const input = sentence(18);
  for (let index = 11; index < 18; index += 1) {
    input.words[`u0:w${index}`].utterance = 1;
  }
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
    0,
  );
  assert.deepEqual(
    paragraphs.map((paragraph) => [
      paragraph.utterance,
      paragraph.words.length,
    ]),
    [[0, 11], [1, 7]],
  );
});

test("a positive safety limit still splits exceptionally large turns", () => {
  const input = sentence(19);
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
    12,
  );
  assert.deepEqual(paragraphs.map((paragraph) => paragraph.words.length), [12, 7]);
});

test("the audience stack stays continuous while transcript turns remain intact", () => {
  const input = sentence(9);
  for (let index = 3; index < 6; index += 1) {
    input.words[`u0:w${index}`].utterance = 1;
  }
  for (let index = 6; index < 9; index += 1) {
    input.words[`u0:w${index}`].utterance = 2;
  }
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
  );
  const stack = selectStableCaptionStack(paragraphs, 2, 8);

  assert.deepEqual(paragraphs.map(({utterance}) => utterance), [0, 1, 2]);
  assert.deepEqual(stack.map(({words}) => words.length), [8, 1]);
  assert.deepEqual(
    stack.flatMap(({words}) => words.map(({id}) => id)),
    input.order,
  );
});

test("one long turn advances through six stable eight-word rows", () => {
  const input = sentence(48);
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
  );
  const stack = selectStableCaptionStack(paragraphs);

  assert.equal(paragraphs.length, 1);
  assert.equal(paragraphs[0].words.length, 48);
  assert.deepEqual(
    stack.map((paragraph) => paragraph.words.map(({id}) => id)),
    [
      [
        "u0:w0", "u0:w1", "u0:w2", "u0:w3",
        "u0:w4", "u0:w5", "u0:w6", "u0:w7",
      ],
      [
        "u0:w8", "u0:w9", "u0:w10", "u0:w11",
        "u0:w12", "u0:w13", "u0:w14", "u0:w15",
      ],
      [
        "u0:w16", "u0:w17", "u0:w18", "u0:w19",
        "u0:w20", "u0:w21", "u0:w22", "u0:w23",
      ],
      [
        "u0:w24", "u0:w25", "u0:w26", "u0:w27",
        "u0:w28", "u0:w29", "u0:w30", "u0:w31",
      ],
      [
        "u0:w32", "u0:w33", "u0:w34", "u0:w35",
        "u0:w36", "u0:w37", "u0:w38", "u0:w39",
      ],
      [
        "u0:w40", "u0:w41", "u0:w42", "u0:w43",
        "u0:w44", "u0:w45", "u0:w46", "u0:w47",
      ],
    ],
  );
});

test("opening a second row does not change the first row identity", () => {
  const firstRowWords = sentence(8);
  const secondRowWords = sentence(9);
  const firstStack = selectStableCaptionStack(buildCaptionParagraphs(
    firstRowWords.words,
    firstRowWords.order,
  ));
  const secondStack = selectStableCaptionStack(buildCaptionParagraphs(
    secondRowWords.words,
    secondRowWords.order,
  ));

  assert.equal(firstStack[0].id, secondStack[0].id);
  assert.deepEqual(
    firstStack[0].words.map(({id}) => id),
    secondStack[0].words.map(({id}) => id),
  );
});

test("the audience stack does not hide recognized provisional words", () => {
  const input = sentence(7);
  for (let index = 3; index < 7; index += 1) {
    input.words[`u0:w${index}`].final = false;
  }
  const paragraphs = buildCaptionParagraphs(
    input.words,
    input.order,
  );
  const stack = selectStableCaptionStack(paragraphs, 2, 8);

  assert.deepEqual(
    stack[0].words.map(({id}) => id),
    input.order,
  );
  assert.equal(paragraphs[0].words.length, 7);
});

test("provisional accurate commits remain visible before endpoint verification", () => {
  const input = sentence(8);
  for (let index = 0; index < 8; index += 1) {
    const word = input.words[`u0:w${index}`];
    word.final = false;
    word.provisional = true;
    word.src = "accurate";
    word._render_stage = index < 5 ? "commit" : "hypothesis";
  }
  const stack = selectStableCaptionStack(buildCaptionParagraphs(
    input.words,
    input.order,
  ));

  assert.deepEqual(
    stack.flatMap(({words}) => words.map(({id}) => id)),
    input.order,
  );
  assert.deepEqual(stack.map(({words}) => words.length), [8]);
});

test("speaker churn cannot create one-word rows or remount the stack", () => {
  const alternating = sentence(16);
  for (let index = 0; index < 16; index += 1) {
    alternating.words[`u0:w${index}`].speaker = index % 2 ? "S2" : "S1";
  }
  const alternatingParagraphs = buildCaptionParagraphs(
    alternating.words,
    alternating.order,
  );
  const before = selectStableCaptionStack(alternatingParagraphs);

  const corrected = sentence(16, "S1");
  const correctedParagraphs = buildCaptionParagraphs(
    corrected.words,
    corrected.order,
  );
  const after = selectStableCaptionStack(correctedParagraphs);

  assert.equal(alternatingParagraphs.length, 16);
  assert.deepEqual(before.map(({words}) => words.length), [8, 8]);
  assert.deepEqual(before.map(({status}) => status), ["mixed", "mixed"]);
  assert.deepEqual(
    before.map(({id}) => id),
    after.map(({id}) => id),
  );
  assert.deepEqual(
    before.map((row) => row.words.map(({id}) => id)),
    after.map((row) => row.words.map(({id}) => id)),
  );
});

test("pending attribution and provisional utterances cannot break the stack", () => {
  const pending = sentence(16, "");
  for (let index = 0; index < 16; index += 1) {
    const word = pending.words[`u0:w${index}`];
    word.speaker = undefined;
    word.speaker_status = "unknown";
    word.utterance = index;
  }
  const before = selectStableCaptionStack(buildCaptionParagraphs(
    pending.words,
    pending.order,
  ));

  const attributed = sentence(16, "S1");
  const after = selectStableCaptionStack(buildCaptionParagraphs(
    attributed.words,
    attributed.order,
  ));

  assert.deepEqual(before.map(({words}) => words.length), [8, 8]);
  assert.deepEqual(before.map(({status}) => status), ["unknown", "unknown"]);
  assert.deepEqual(
    before.map(({id}) => id),
    after.map(({id}) => id),
  );
  assert.deepEqual(
    before.map((row) => row.words.map(({id}) => id)),
    after.map((row) => row.words.map(({id}) => id)),
  );
});

test("stack motion occurs for a new row and the rows it pushes upward", () => {
  const motion = planCaptionStackMotion(
    [
      {id: "row-0", top: 500},
      {id: "row-1", top: 560},
    ],
    [
      {id: "row-0", top: 440},
      {id: "row-1", top: 500},
      {id: "row-2", top: 560},
    ],
  );

  assert.deepEqual(motion, [
    {id: "row-0", kind: "shift", deltaY: 60},
    {id: "row-1", kind: "shift", deltaY: 60},
    {id: "row-2", kind: "enter", deltaY: 0},
  ]);
});

test("a new bottom row enters even when it displaces nothing", () => {
  // Top-anchored stack below the history cap: the retained rows keep their
  // positions and only the new row moves.
  assert.deepEqual(
    planCaptionStackMotion(
      [
        {id: "row-0", top: 200},
        {id: "row-1", top: 260},
      ],
      [
        {id: "row-0", top: 200},
        {id: "row-1", top: 260},
        {id: "row-2", top: 320},
      ],
    ),
    [{id: "row-2", kind: "enter", deltaY: 0}],
  );
});

test("the first caption block receives one calm entry motion", () => {
  assert.deepEqual(
    planCaptionStackMotion([], [{id: "row-0", top: 560}]),
    [{id: "row-0", kind: "enter", deltaY: 0}],
  );
  assert.deepEqual(
    planCaptionStackMotion(
      [],
      [{id: "row-0", top: 560}],
      new Set(["row-0"]),
    ),
    [],
  );
  assert.deepEqual(
    planCaptionStackMotion(
      [],
      [
        {id: "row-0", top: 500},
        {id: "row-1", top: 560},
      ],
    ),
    [],
  );
});

test("speaker or text updates cannot replay stack motion", () => {
  const positions = [
    {id: "row-0", top: 440},
    {id: "row-1", top: 500},
  ];
  assert.deepEqual(planCaptionStackMotion(positions, positions), []);
});

test("row removal or reappearance cannot replay stack motion", () => {
  const full = [
    {id: "row-0", top: 440},
    {id: "row-1", top: 500},
  ];
  const contracted = [{id: "row-0", top: 500}];

  assert.deepEqual(planCaptionStackMotion(full, contracted), []);
  assert.deepEqual(
    planCaptionStackMotion(
      contracted,
      full,
      new Set(["row-0", "row-1"]),
    ),
    [],
  );
});

test("an earlier deletion cannot re-chunk the rows below it", () => {
  // Six words, three per row: [w0 w1 w2] [w3 w4 w5].
  const input = sentence(6);
  const memory = createStageMemory();
  const before = selectStableCaptionStack(
    buildCaptionParagraphs(input.words, input.order, 0), 0, 3, memory,
  );
  assert.deepEqual(before.map((r) => r.words.length), [3, 3]);
  const secondRow = before[1].words.map(({id}) => id);

  // The verifier drops one word from the FIRST row.
  const trimmed = {
    words: {...input.words},
    order: input.order.filter((id) => id !== "u0:w1"),
  };
  delete trimmed.words["u0:w1"];
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(trimmed.words, trimmed.order, 0), 0, 3, memory,
  );

  // Chunking by index would pull w3 up into row 0 and shift everything the
  // viewer had already read. Anchored rows keep the boundary where it was.
  assert.deepEqual(after.map((r) => r.words.length), [2, 3]);
  assert.deepEqual(after[1].words.map(({id}) => id), secondRow);
  assert.equal(after[1].id, before[1].id, "row identity must survive");
});

test("a word inserted behind what is already placed is not shown", () => {
  const input = sentence(6);
  const memory = createStageMemory();
  selectStableCaptionStack(
    buildCaptionParagraphs(input.words, input.order, 0), 0, 3, memory,
  );

  // The verifier finds a word it missed, in the middle of read text.
  const grown = {words: {...input.words}, order: [...input.order]};
  grown.words["u0:w1b"] = {...input.words["u0:w1"], word_id: "u0:w1b",
    text: "inserted", start: 0.25, end: 0.3, t: 0.25};
  grown.order.splice(2, 0, "u0:w1b");
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(grown.words, grown.order, 0), 0, 3, memory,
  );

  // Showing it would lengthen a read row and push its tail onto the next line.
  const shown = after.flatMap((row) => row.words.map(({id}) => id));
  assert.ok(!shown.includes("u0:w1b"), "late insertion must not reopen a row");
  assert.deepEqual(after.map((r) => r.words.length), [3, 3]);
  assert.deepEqual(after.at(-1)!.words.map(({id}) => id),
                   ["u0:w3", "u0:w4", "u0:w5"]);
});

test("a word arriving late at the END still appends", () => {
  const input = sentence(3);
  const memory = createStageMemory();
  selectStableCaptionStack(
    buildCaptionParagraphs(input.words, input.order, 0), 0, 3, memory,
  );
  const grown = {words: {...input.words}, order: [...input.order]};
  grown.words["u0:w3"] = {...input.words["u0:w2"], word_id: "u0:w3",
    text: "later", start: 9, end: 9.2, t: 9};
  grown.order.push("u0:w3");
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(grown.words, grown.order, 0), 0, 3, memory,
  );
  const shown = after.flatMap((row) => row.words.map(({id}) => id));
  assert.ok(shown.includes("u0:w3"), "an append must still reach the screen");
});

test("a fresh stack still chunks by capacity", () => {
  const input = sentence(7);
  const rows = selectStableCaptionStack(
    buildCaptionParagraphs(input.words, input.order, 0), 0, 3, createStageMemory(),
  );
  assert.deepEqual(rows.map((r) => r.words.length), [3, 3, 1]);
});

/** Words with controlled TEXT, so the width budget can be exercised directly. */
function texts(list: string[], {speaker = "S1", final = true} = {}) {
  const words: Record<string, CaptionWord> = {};
  const order: string[] = [];
  list.forEach((text, index) => {
    const id = `u0:w${index}`;
    order.push(id);
    words[id] = {
      word_id: id,
      text,
      start: index * 0.2,
      end: index * 0.2 + 0.18,
      speaker,
      speaker_status: "stable",
      final,
    };
  });
  return {words, order};
}

const BUDGET = {rowEm: 20, charEm: 0.432, wordEm: 0.378, fill: 1};

test("a row breaks when it is FULL, not when it has counted to N", () => {
  // Rows used to close at `wordsPerCaption` however wide the words were, so
  // the type had to be sized for the worst case that count could produce and
  // an ordinary row stopped well short of the edge (measured: median 64% full).
  const tiny = texts(Array(40).fill("a"));
  const wide = texts(Array(40).fill("consideration"));
  const short = selectStableCaptionStack(
    buildCaptionParagraphs(tiny.words, tiny.order),
    99, 50, createStageMemory(), BUDGET,
  );
  const long = selectStableCaptionStack(
    buildCaptionParagraphs(wide.words, wide.order),
    99, 50, createStageMemory(), BUDGET,
  );
  // 1-char words cost .81em, 13-char words 6.0em, against a 20em row.
  assert.equal(short[0].words.length, 24, "short words fill the line");
  assert.equal(long[0].words.length, 3, "long ones cannot");
  // ...and neither is the word ceiling, which is what used to decide both.
  assert.ok(short[0].words.length < 50 && long[0].words.length < 50);
});

const WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"];

test("a SETTLED row's membership is frozen, so a respelling cannot re-flow it", () => {
  // THIS IS WHAT MAKES A WIDTH BUDGET SAFE. Anchored row starts already stop an
  // edit re-chunking the rows BELOW one; without frozen membership the break
  // inside a row still moves when the verifier lengthens a word, which re-keys
  // every row after it and remounts their words -- the motion change that sank
  // the previous attempt at this.
  const memory = createStageMemory();
  const first = texts(WORDS);
  const before = selectStableCaptionStack(
    buildCaptionParagraphs(first.words, first.order),
    99, 50, memory, BUDGET,
  );
  const shape = before.map(({words}) => words.map(({id}) => id));

  // A word already on screen is respelled longer, after it went final.
  const second = texts(WORDS);
  second.words["u0:w1"].text = "beta-considerably-longer-now";
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(second.words, second.order),
    99, 50, memory, BUDGET,
  );

  assert.deepEqual(after.map(({words}) => words.map(({id}) => id)), shape);
  assert.deepEqual(after.map(({id}) => id), before.map(({id}) => id));
});

test("a row re-breaks while its words are still hypotheses", () => {
  // A live word is placed while it is still a stub and grows into its settled
  // spelling, so a row that fit when it was formed can overrun later -- and
  // freezing membership at first PLACEMENT freezes it against widths that are
  // not real yet. Measured on `--sample`, a row that fit at 28.5em settled at
  // 37.5em on a 32.8em line and was silently cut. Unsettled words are
  // read-ahead text nobody has read, so the stage may still re-break them.
  const memory = createStageMemory();
  const stubs = texts(["alpha", "beta", "gam", "del"], {final: false});
  const before = selectStableCaptionStack(
    buildCaptionParagraphs(stubs.words, stubs.order),
    99, 50, memory, BUDGET,
  );
  assert.equal(before.length, 1, "the stubs fit on one row");

  const grown = texts(["alpha", "beta", "gamma-much-longer", "delta-much-longer"],
    {final: false});
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(grown.words, grown.order),
    99, 50, memory, BUDGET,
  );
  assert.ok(after.length > 1, "and are re-broken once they no longer do");
  // The row already on screen keeps its identity and its first word: only the
  // tail moves down, so nothing the viewer has read is re-keyed.
  assert.equal(after[0].id, before[0].id);
  assert.equal(after[0].words[0].id, before[0].words[0].id);
});

test("a stale break is retired once the text that caused it changes", () => {
  // THIS IS WHAT REMOVES THE 2-WORD SLIVER ROWS. Every break is correct when
  // it is made, but the recognizer then rewrites the text around it, and a
  // permanent `starts` ratchet pins a boundary to text that no longer exists.
  // Measured on `--sample`: 17 anchors born, all 17 on a genuinely full row,
  // yet 3700 of 16145 row-opening decisions were the ratchet re-firing on a row
  // that was no longer full -- which is where 'my godan' and 'in this army'
  // came from. An unsettled word is re-tested on capacity alone.
  const memory = createStageMemory();
  const long = texts(["alpha", "beta", "gamma-much-longer", "delta-much-longer"],
    {final: false});
  const split = selectStableCaptionStack(
    buildCaptionParagraphs(long.words, long.order),
    99, 50, memory, BUDGET,
  );
  assert.ok(split.length > 1, "the long spellings break the row");

  const short = texts(["alpha", "beta", "gam", "del"], {final: false});
  const healed = selectStableCaptionStack(
    buildCaptionParagraphs(short.words, short.order),
    99, 50, memory, BUDGET,
  );
  assert.equal(healed.length, 1, "and the break goes when they shorten again");
});

/* SCRIPT-AWARE ROW WIDTH. */

const KO_BUDGET = {...BUDGET, wideCharEm: 0.92};

test("Latin widths are BIT-IDENTICAL with and without a wide-char width", () => {
  /* THE MOTION GATE. A moved English break remounts words and puts the
     motion acceptance figures at risk, which is why the wide-script fix is
     script-aware rather than a re-measurement of every width. */
  for (const text of [
    "louder", "softer", "is", "synchronized", "precisely", "animation,",
    "Goddamnit", "a", "", "don't", "1640", "S1:",
  ]) {
    assert.equal(
      wordWidthEm(text, KO_BUDGET),
      wordWidthEm(text, BUDGET),
      `"${text}" must cost the same with and without wideCharEm`,
    );
  }
});

test("a Hangul syllable costs the wide width, not the Latin one", () => {
  // 3 syllables: 3*0.92 + 0.378 against the old 3*0.432 + 0.378.
  assert.equal(wordWidthEm("안녕히", KO_BUDGET), 3 * 0.92 + 0.378);
  // 3.138em against 1.674em: the old estimate is 1.87x low. Not the full 2.12x
  // the per-character ratio implies, because the `wordEm` intercept is charged
  // once either way and dilutes it -- which is exactly why this has to be
  // asserted on the real numbers rather than reasoned from 0.92/0.4343.
  assert.ok(
    wordWidthEm("안녕히", KO_BUDGET) > wordWidthEm("안녕히", BUDGET) * 1.8,
    "the old estimate was far under",
  );
});

test("a mixed Korean and Latin word charges each character its own width", () => {
  // `2011년` is exactly the case a per-LANGUAGE budget could not express, and
  // FLEURS Korean is full of it.
  assert.equal(wordWidthEm("2011년", KO_BUDGET), 4 * 0.432 + 0.92 + 0.378);
});

test("without a wide width, Korean falls back to the old behaviour", () => {
  // The chunker is a pure function used by callers that have not measured a
  // face; it must not start throwing or returning NaN for them.
  assert.equal(wordWidthEm("안녕히", BUDGET), 3 * 0.432 + 0.378);
});

test("Korean rows break about twice as early as they used to", () => {
  // The bug, end to end: same words, same 20em row, correct widths.
  const ko = texts(Array(40).fill("안녕히"));
  const before = selectStableCaptionStack(
    buildCaptionParagraphs(ko.words, ko.order), 99, 50, createStageMemory(),
    BUDGET,
  );
  const after = selectStableCaptionStack(
    buildCaptionParagraphs(ko.words, ko.order), 99, 50, createStageMemory(),
    KO_BUDGET,
  );
  assert.equal(before[0].words.length, 11, "the under-estimate packed 11");
  assert.equal(after[0].words.length, 6, "the real width fits 6");
  // 11 words at a TRUE 3.138em each is 34.5em in a 20em row: 73% past the edge,
  // cut with no error and nothing on screen to show for it.
});

test("English row composition is unchanged by the wide-char width", () => {
  // The same assertion as the bit-identical test, but at the level that
  // actually matters: identical rows means identical row ids, so no word is
  // remounted and no motion is re-armed.
  const en = texts([
    "as", "each", "word", "is", "spoken", "precisely", "synchronized",
    "with", "the", "audio", "so", "that", "everyone", "can", "follow",
  ]);
  const rows = (budget: typeof BUDGET) => selectStableCaptionStack(
    buildCaptionParagraphs(en.words, en.order), 99, 50, createStageMemory(),
    budget,
  ).map((row) => [row.id, row.words.map((w) => w.word.text).join(" ")]);

  assert.deepEqual(rows(KO_BUDGET), rows(BUDGET));
});

test("wide-character classification covers the scripts captions actually use", () => {
  for (const ch of ["가", "힣", "ㄱ", "漢", "字", "あ", "ア", "，", "！"]) {
    assert.ok(isWideChar(ch.codePointAt(0)!), `${ch} is wide`);
  }
  for (const ch of ["a", "Z", "0", "-", ".", " ", "'", "é"]) {
    assert.ok(!isWideChar(ch.codePointAt(0)!), `${ch} is narrow`);
  }
});
