import assert from "node:assert/strict";
import test from "node:test";
import {
  mergeCaptionWord,
  reduceCaptionEvent,
  initialCaptionModel,
  type CaptionWord,
} from "./caption-store.ts";

const word = (patch: Partial<CaptionWord> = {}): CaptionWord => ({
  word_id: "u0:w0",
  text: "Hello",
  start: 0,
  end: 0.4,
  utterance: 0,
  text_revision_id: 1,
  timing_revision_id: 1,
  speaker_revision_id: 1,
  speaker: "S1",
  speaker_status: "stable",
  ...patch,
});

test("a final word cannot roll back to an older hypothesis", () => {
  const stable = word({
    text: "Hello",
    final: true,
    verified: true,
    text_revision_id: 3,
    _render_stage: "verification",
    _sse_id: 8,
  });
  const stale = word({
    text: "Hullo",
    text_revision_id: 2,
    _render_stage: "hypothesis",
    _sse_id: 9,
  });
  const merged = mergeCaptionWord(stable, stale);
  assert.equal(merged.text, "Hello");
  assert.equal(merged.verified, true);
});

test("speaker correction repartitions without changing text or timing", () => {
  const current = word({final: true, speaker: "S1", speaker_revision_id: 1});
  const corrected = word({
    text: "wrong",
    start: 9,
    end: 10,
    speaker: "S2",
    speaker_status: "corrected",
    speaker_revision_id: 2,
    text_revision_id: 0,
    timing_revision_id: 0,
  });
  const merged = mergeCaptionWord(current, corrected);
  assert.equal(merged.text, "Hello");
  assert.equal(merged.start, 0);
  assert.equal(merged.speaker, "S2");
});

test("hypothesis replacement removes only its obsolete tentative tail", () => {
  let state = reduceCaptionEvent(initialCaptionModel, {
    type: "hypothesis",
    words: [
      word({word_id: "u0:w0", text: "Hello", src: "accurate"}),
      word({word_id: "u0:w1", text: "there", start: 0.5, src: "accurate"}),
    ],
  }, 1);
  state = reduceCaptionEvent(state, {
    type: "hypothesis",
    words: [word({word_id: "u0:w0", text: "Hi", text_revision_id: 2, src: "accurate"})],
  }, 2);
  assert.deepEqual(state.order, ["u0:w0"]);
  assert.equal(state.words["u0:w0"].text, "Hi");
});

test("a provisional accurate commit survives later hypothesis snapshots", () => {
  let state = reduceCaptionEvent(initialCaptionModel, {
    type: "hypothesis",
    words: [
      word({word_id: "u0:w0", text: "The", final: false, src: "accurate"}),
      word({
        word_id: "u0:w1",
        text: "voice",
        start: 0.5,
        final: false,
        src: "accurate",
      }),
    ],
  }, 1);
  state = reduceCaptionEvent(state, {
    ...word({
      word_id: "u0:w0",
      text: "The",
      final: false,
      provisional: true,
      src: "accurate",
    }),
    type: "commit",
  }, 2);
  state = reduceCaptionEvent(state, {
    type: "hypothesis",
    words: [
      word({
        word_id: "u0:w1",
        text: "voice",
        start: 0.5,
        final: false,
        src: "accurate",
      }),
      word({
        word_id: "u0:w2",
        text: "stays",
        start: 0.9,
        final: false,
        src: "accurate",
      }),
    ],
  }, 3);

  assert.deepEqual(state.order, ["u0:w0", "u0:w1", "u0:w2"]);
  assert.equal(state.words["u0:w0"]._render_stage, "commit");
  assert.equal(state.words["u0:w0"].provisional, true);
});

test("the first audience presentation is not treated as reconnect history", () => {
  const opening = reduceCaptionEvent(initialCaptionModel, {
    type: "commit",
    _replay: true,
    _first_presentation: true,
    words: [word()],
  }, 4);
  const reconnect = reduceCaptionEvent(initialCaptionModel, {
    type: "commit",
    _replay: true,
    _first_presentation: false,
    words: [word()],
  }, 4);

  assert.equal(opening.words["u0:w0"]._replay, false);
  assert.equal(reconnect.words["u0:w0"]._replay, true);
});
