import assert from "node:assert/strict";
import test from "node:test";
import {
  assignSpeakerColors,
  hueDistance,
  hueOf,
  pastelForHue,
} from "./speaker-colors.ts";

// The CI main palette (config.yaml `palette`), in the wheel order 2.1.1 shows.
const MAIN = [
  "#E5E517", // yellow
  "#17E517", // green
  "#17E5E5", // blue
  "#E517E5", // pink
  "#E51717", // red
  "#E58017", // orange
];
const SUPPORT = ["#E85C2E", "#EBC247", "#C2EB47", "#5EEDC9"];

test("hue is read off the swatch, and greys have none", () => {
  assert.equal(Math.round(hueOf("#E51717") ?? -1), 0);     // red
  assert.equal(Math.round(hueOf("#17E517") ?? -1), 120);   // green
  assert.equal(Math.round(hueOf("#17E5E5") ?? -1), 180);   // blue
  assert.equal(hueOf("#808080"), null);
  assert.equal(hueOf("not a colour"), null);
});

test("hue distance wraps around the wheel", () => {
  assert.equal(hueDistance(10, 350), 20);
  assert.equal(hueDistance(0, 180), 180);
  assert.equal(hueDistance(90, 90), 0);
});

test("2.1.1: three speakers are spaced as far apart as possible", () => {
  const assigned = assignSpeakerColors(["S1", "S2", "S3"], {
    main: MAIN,
    support: SUPPORT,
  });
  const hues = ["S1", "S2", "S3"].map(
    (id) => hueOf(assigned.get(id)!.color)!,
  );
  // Every pair must be far apart -- the failure this replaces handed out
  // adjacent hues, which 2.1.3 calls out as visually blending.
  for (let i = 0; i < hues.length; i += 1) {
    for (let j = i + 1; j < hues.length; j += 1) {
      assert.ok(
        hueDistance(hues[i], hues[j]) >= 110,
        `speakers ${i + 1}/${j + 1} only ${hueDistance(hues[i], hues[j])}deg apart`,
      );
    }
  }
});

test("2.1.1: the second speaker takes the farthest hue the palette offers", () => {
  const assigned = assignSpeakerColors(["A", "B"], {main: MAIN, support: SUPPORT});
  const first = hueOf(assigned.get("A")!.color)!;
  const chosen = hueDistance(first, hueOf(assigned.get("B")!.color)!);
  // Assert OPTIMALITY, not a fixed angle: the CI mains sit at 0/31/60/120/180/
  // 300 degrees, so nothing is truly opposite yellow and a hardcoded threshold
  // would only encode this palette. What must hold is that no unused main hue
  // is farther away than the one taken.
  const best = Math.max(
    ...MAIN.map((color) => hueDistance(first, hueOf(color)!)),
  );
  assert.equal(chosen, best);
  assert.ok(chosen >= 90, `hero/villain only ${chosen}deg apart`);
});

test("no colour is reused while any remain", () => {
  const ids = Array.from({length: MAIN.length + SUPPORT.length}, (_, i) => `S${i}`);
  const assigned = assignSpeakerColors(ids, {main: MAIN, support: SUPPORT});
  const colors = ids.map((id) => assigned.get(id)!.color);
  assert.equal(new Set(colors).size, colors.length);
});

test("main characters are exhausted before supporting ones (2.1.1 then 2.1.2)", () => {
  const ids = MAIN.map((_, i) => `S${i}`);
  const assigned = assignSpeakerColors(ids, {main: MAIN, support: SUPPORT});
  for (const id of ids) {
    assert.ok(assigned.get(id)!.index < MAIN.length, `${id} skipped to support`);
  }
});

test("2.1.4: past both palettes, speakers get centre-of-wheel pastels", () => {
  const ids = Array.from({length: MAIN.length + SUPPORT.length + 2}, (_, i) => `S${i}`);
  const assigned = assignSpeakerColors(ids, {main: MAIN, support: SUPPORT});
  const extra = assigned.get(`S${ids.length - 1}`)!;
  assert.equal(extra.index, -1, "should be generated, not from a palette");
  // HSB(h, 30%, 90%): pale, and never fully saturated.
  assert.match(extra.color, /^#[0-9a-f]{6}$/);
  const hex = extra.color.slice(1);
  const channels = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  assert.equal(Math.max(...channels), 230, "brightness 90%");
  assert.equal(Math.min(...channels), 161, "saturation 30%");
});

test("assignment is stable as later speakers appear", () => {
  const two = assignSpeakerColors(["S1", "S2"], {main: MAIN, support: SUPPORT});
  const four = assignSpeakerColors(["S1", "S2", "S3", "S4"], {
    main: MAIN,
    support: SUPPORT,
  });
  // A speaker's identity colour must not change because someone else spoke.
  assert.equal(two.get("S1")!.color, four.get("S1")!.color);
  assert.equal(two.get("S2")!.color, four.get("S2")!.color);
});

test("a pastel is a real colour at every hue", () => {
  for (let hue = 0; hue < 360; hue += 37) {
    assert.match(pastelForHue(hue), /^#[0-9a-f]{6}$/);
  }
});
