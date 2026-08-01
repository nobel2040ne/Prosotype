import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCaptionParagraphs,
  planCaptionStackMotion,
  selectStableCaptionStack,
  createStageMemory,
} from "./caption-paragraphs.ts";
import type {CaptionWord} from "./caption-store.ts";

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
