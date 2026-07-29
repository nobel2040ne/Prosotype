"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("../autocwi/live_render_core.js");

function word(overrides) {
  return Object.assign({
    type: "hypothesis",
    _render_stage: "hypothesis",
    _sse_id: 1,
    word_id: "u0:w0",
    utterance: 0,
    text: "hello",
    t: 1,
    start: 1,
    end: 1.3,
    text_revision_id: 1,
    timing_revision_id: 1,
    speaker: "S1",
    speaker_status: "provisional",
    speaker_revision_id: 1,
    final: false,
    verified: false
  }, overrides || {});
}

test("multiple revisions retain one stable word identity", () => {
  const nodes = new Map();
  [word(), word({_sse_id: 2, text: "Hello", text_revision_id: 2})]
    .forEach(update => {
      const key = Core.wordKey(update);
      const current = nodes.get(key);
      nodes.set(key, Core.mergeWordUpdate(current, update).value);
    });
  assert.equal(nodes.size, 1);
  assert.equal(nodes.get("u0:w0").text, "Hello");
});

test("older speaker revision cannot overwrite stable state", () => {
  const stable = word({
    _sse_id: 8, speaker_status: "stable", speaker_revision_id: 4,
    final: true
  });
  const old = word({
    _sse_id: 3, speaker: "S2", speaker_status: "provisional",
    speaker_revision_id: 2
  });
  const merged = Core.mergeWordUpdate(stable, old);
  assert.equal(merged.value.speaker, "S1");
  assert.equal(merged.value.speaker_status, "stable");
  assert.equal(merged.stale, true);
});

test("late provisional state cannot visually downgrade stable state", () => {
  const stable = word({speaker_status: "stable", speaker_revision_id: 2});
  const provisional = word({
    _sse_id: 20, speaker_status: "provisional", speaker_revision_id: 9
  });
  assert.equal(
    Core.mergeWordUpdate(stable, provisional).value.speaker_status,
    "stable"
  );
});

test("newer stable correction updates identity in place", () => {
  const stable = word({
    speaker: "S1", speaker_status: "stable", speaker_revision_id: 2
  });
  const corrected = word({
    _sse_id: 5, speaker: "S2", speaker_status: "corrected",
    speaker_revision_id: 3, correction: true, final: true
  });
  const merged = Core.mergeWordUpdate(stable, corrected);
  assert.equal(Core.wordKey(merged.value), "u0:w0");
  assert.equal(merged.value.speaker, "S2");
  assert.equal(merged.value.speaker_status, "corrected");
  assert.equal(merged.changes.speaker, true);
});

test("one frame coalesces one word to its newest state", () => {
  const queue = Core.createFrameReducer(16);
  queue.enqueue(word({_sse_id: 1, text: "hel"}));
  queue.enqueue(word({_sse_id: 2, text: "hello", text_revision_id: 2}));
  queue.enqueue(word({
    _sse_id: 3, text: "Hello", text_revision_id: 3,
    type: "commit", _render_stage: "commit"
  }));
  const drained = queue.drain();
  assert.equal(drained.length, 1);
  assert.equal(drained[0].text, "Hello");
  assert.equal(queue.stats.coalesced, 2);
});

test("one frame preserves separate words in source order", () => {
  const queue = Core.createFrameReducer(16);
  queue.enqueue(word({word_id: "u0:w1", t: 2, text: "world"}));
  queue.enqueue(word({word_id: "u0:w0", t: 1, text: "hello"}));
  assert.deepEqual(queue.drain().map(item => item.word_id), ["u0:w0", "u0:w1"]);
});

test("bounded frame queue cannot grow without limit", () => {
  const queue = Core.createFrameReducer(3);
  for (let index = 0; index < 10; index += 1) {
    queue.enqueue(word({word_id: "u0:w" + index, t: index}));
  }
  assert.equal(queue.size, 3);
  assert.equal(queue.stats.evicted, 7);
});

test("speaker-only revision leaves text and timing untouched", () => {
  const prior = word({speaker_status: "stable", speaker_revision_id: 2});
  const next = word({
    _sse_id: 2, speaker_status: "corrected", speaker_revision_id: 3
  });
  const merged = Core.mergeWordUpdate(prior, next);
  assert.deepEqual(merged.changes, {
    text: false, timing: false, speaker: true, final: false
  });
});

test("verification with unchanged text has no text revision", () => {
  const committed = word({
    type: "commit", _render_stage: "commit", _sse_id: 4
  });
  const verified = word({
    type: "word", _render_stage: "verification", _sse_id: 5,
    final: true, verified: true
  });
  const merged = Core.mergeWordUpdate(committed, verified);
  assert.equal(merged.changes.text, false);
  assert.equal(merged.value.verified, true);
});

test("later event stage cannot lower an independent text revision counter", () => {
  const revised = word({
    src: "accurate", text: "Hello", text_revision_id: 4, _sse_id: 8
  });
  const cue = word({
    type: "cue", _render_stage: "cue", text: "hello",
    text_revision_id: 3, _sse_id: 9
  });
  const commit = word({
    type: "commit", _render_stage: "commit", text: "hello",
    text_revision_id: 3, _sse_id: 10
  });
  const afterCue = Core.mergeWordUpdate(revised, cue).value;
  const afterCommit = Core.mergeWordUpdate(afterCue, commit).value;
  assert.equal(afterCue.text_revision_id, 4);
  assert.equal(afterCommit.text_revision_id, 4);
  assert.equal(afterCommit.text, "Hello");
});

test("reconnect replay settles without replaying completed motion", () => {
  const clock = Core.createMediaClock();
  clock.observe(10, 10000);
  const plan = Core.planMotion(
    word({t: 9}), clock, 10000,
    {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18},
    {replay: true}
  );
  assert.equal(plan.state, "settled");
});

test("late event settles directly after the motion window", () => {
  const clock = Core.createMediaClock();
  clock.observe(2, 2000);
  const plan = Core.planMotion(
    word({t: 1}), clock, 2000,
    {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18}
  );
  assert.equal(plan.state, "settled");
});

test("early event schedules against the media clock", () => {
  const clock = Core.createMediaClock();
  clock.observe(1, 1000);
  const plan = Core.planMotion(
    word({t: 1.25}), clock, 1000,
    {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18}
  );
  assert.equal(plan.state, "scheduled");
  assert.equal(plan.onsetPerformance, 1250);
});

test("slightly late event seeks into the current curve", () => {
  const clock = Core.createMediaClock();
  clock.observe(1.05, 1050);
  const plan = Core.planMotion(
    word({t: 1}), clock, 1050,
    {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18}
  );
  assert.equal(plan.state, "active");
  assert.ok(plan.elapsed > 0.049 && plan.elapsed < 0.051);
});

test("synchronization curve attacks and returns continuously to rest", () => {
  const timing = {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18};
  const samples = [0, 0.03, 0.06, 0.09, 0.13, 0.17, 0.23, 0.3, 0.35]
    .map(time => Core.syncEnvelope(time, timing));
  assert.equal(samples[0], 0);
  assert.equal(samples[3], 1);
  assert.equal(samples[4], 1);
  assert.equal(samples.at(-1), 0);
  assert.ok(samples.every(value => value >= 0 && value <= 1));
  assert.ok(Math.abs(Core.syncEnvelope(0.09 - 1e-7, timing) -
                     Core.syncEnvelope(0.09 + 1e-7, timing)) < 1e-5);
});

test("late reveal deadline catches up instead of compounding a full gap", () => {
  assert.equal(Core.nextRevealDeadline(220, 520, 140, 60), 580);
  assert.equal(Core.nextRevealDeadline(0, 1000, 140, 60), 1140);
});

test("stable mode never exposes a tentative tail", () => {
  assert.deepEqual(Core.reduceTentativeTail([word()], "stable", new Set(), 8), []);
});

test("fast mode exposes accurate tail but not draft churn", () => {
  const words = [
    word({word_id: "u0:w0", src: "draft"}),
    word({word_id: "u0:w1", src: "accurate", t: 1.2})
  ];
  assert.deepEqual(
    Core.reduceTentativeTail(words, "fast", new Set(), 8)
      .map(item => item.src),
    ["accurate"]
  );
});

test("readahead gives an overlapping slot to the accurate stream", () => {
  const words = [
    word({word_id: "u0:w0", src: "draft", t: 1.05, text: "helo"}),
    word({word_id: "u0:w0", src: "accurate", t: 1.0, text: "hello"})
  ];
  const tail = Core.reduceTentativeTail(words, "readahead", new Set(), 8);
  assert.equal(tail.length, 1);
  assert.equal(tail[0].src, "accurate");
});

test("accurate source supersedes an independently newer draft counter", () => {
  const draft = word({
    src: "draft", text: "helo", text_revision_id: 8, _sse_id: 20
  });
  const accurate = word({
    src: "accurate", text: "hello", text_revision_id: 1, _sse_id: 21
  });
  const merged = Core.mergeWordUpdate(draft, accurate);
  assert.equal(merged.value.text, "hello");
  assert.equal(merged.value.src, "accurate");
});

test("settled word ownership removes it from readahead", () => {
  const item = word({src: "accurate"});
  const tail = Core.reduceTentativeTail(
    [item], "readahead", new Set([Core.wordKey(item)]), 8
  );
  assert.deepEqual(tail, []);
});

test("reduced motion disables pop and elevation scheduling", () => {
  const clock = Core.createMediaClock();
  clock.observe(1, 1000);
  assert.equal(
    Core.planMotion(
      word({t: 1.1}), clock, 1000,
      {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18},
      {reducedMotion: true}
    ).state,
    "reduced"
  );
});

test("a newly displayed word gets the CWI cue even after source onset expired", () => {
  const clock = Core.createMediaClock();
  clock.observe(10, 1000);
  const plan = Core.planMotion(
    word({t: 1}), clock, 2000,
    {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18},
    {displayOnCreate: true}
  );
  assert.equal(plan.state, "active");
  assert.equal(plan.trigger, "display");
  assert.equal(plan.onsetPerformance, 2000);
  assert.equal(plan.elapsed, 0);
});

test("display activation is suppressed for replay and reduced motion", () => {
  const clock = Core.createMediaClock();
  clock.observe(1, 1000);
  const timing = {rise_s: 0.09, peak_s: 0.08, fall_s: 0.18};
  const replay = Core.planMotion(
    word({t: 1}), clock, 1000, timing,
    {displayOnCreate: true, replay: true}
  );
  assert.equal(replay.state, "settled");
  assert.equal(replay.trigger, "replay");
  const reduced = Core.planMotion(
    word({t: 1}), clock, 1000, timing,
    {displayOnCreate: true, reducedMotion: true}
  );
  assert.equal(reduced.state, "reduced");
  assert.equal(reduced.trigger, "reduced");
});

test("character entry delays progress in reading order by Unicode character", () => {
  assert.deepEqual(
    Core.characterEntryDelays("A🙂B", 0.02),
    [0, 0.02, 0.04]
  );
  assert.deepEqual(Core.characterEntryDelays("word", 0), [0, 0, 0, 0]);
});

test("reduction and scheduling are deterministic across runs", () => {
  function run() {
    const queue = Core.createFrameReducer(8);
    [
      word({_sse_id: 1, text: "h"}),
      word({_sse_id: 2, text: "he", text_revision_id: 2}),
      word({_sse_id: 3, text: "hello", text_revision_id: 3})
    ].forEach(item => queue.enqueue(item));
    return JSON.stringify({words: queue.drain(), stats: queue.stats});
  }
  assert.equal(run(), run());
});
