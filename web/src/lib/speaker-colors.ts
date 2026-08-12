/** CWI 2.1: which colour each speaker gets, and why. The design system treats
   this as GEOMETRY on the colour wheel, not as a list to walk. */

/** Hue in degrees, or null for a colour we cannot parse (never chosen by distance). */
export function hueOf(color: string): number | null {
  const hex = color.trim().replace(/^#/, "");
  const full = hex.length === 3
    ? hex.split("").map((c) => c + c).join("")
    : hex;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  const r = parseInt(full.slice(0, 2), 16) / 255;
  const g = parseInt(full.slice(2, 4), 16) / 255;
  const b = parseInt(full.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const span = max - min;
  if (span === 0) return null;              // greys have no hue to space out
  let hue: number;
  if (max === r) hue = ((g - b) / span) % 6;
  else if (max === g) hue = (b - r) / span + 2;
  else hue = (r - g) / span + 4;
  hue *= 60;
  return hue < 0 ? hue + 360 : hue;
}

/** Shortest distance between two hues, in degrees (0..180). */
export function hueDistance(left: number, right: number): number {
  const delta = Math.abs(left - right) % 360;
  return delta > 180 ? 360 - delta : delta;
}

/** CWI 2.1.4: minor characters are pastels from the centre of the wheel. */
export function pastelForHue(hue: number): string {
  // HSB(h, 30%, 90%) -> RGB, exactly the values on the 2.1.4 page.
  const s = 0.3;
  const v = 0.9;
  const c = v * s;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = v - c;
  const sector = Math.floor(((hue % 360) + 360) % 360 / 60);
  const [r, g, b] = [
    [c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x],
  ][sector];
  const channel = (value: number) =>
    Math.round((value + m) * 255).toString(16).padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

export interface SpeakerPalettes {
  /** CWI 2.1.1 main-character colours, in wheel order. */
  main: readonly string[];
  /** CWI 2.1.2 supporting colours. */
  support: readonly string[];
}

/** Assign colours to speakers in the order they first spoke. */
export function assignSpeakerColors(
  speakers: readonly string[],
  palettes: SpeakerPalettes,
): Map<string, {color: string; index: number}> {
  const assigned = new Map<string, {color: string; index: number}>();
  const takenHues: number[] = [];
  const used = new Set<number>();

  const pool = [...palettes.main, ...palettes.support];
  const hues = pool.map(hueOf);

  for (const speaker of speakers) {
    if (assigned.has(speaker)) continue;

    // Prefer the main palette until it is exhausted (2.1.1 before 2.1.2).
    const limit = used.size < palettes.main.length ? palettes.main.length : pool.length;

    let bestIndex = -1;
    let bestDistance = -1;
    for (let index = 0; index < limit; index += 1) {
      if (used.has(index)) continue;
      const hue = hues[index];
      // The first speaker, or an unparseable swatch: take it in wheel order.
      const distance = hue === null || !takenHues.length
        ? Number.POSITIVE_INFINITY
        : Math.min(...takenHues.map((taken) => hueDistance(hue, taken)));
      if (distance > bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
      if (!Number.isFinite(distance)) break;   // nothing can beat the first pick
    }

    if (bestIndex >= 0) {
      used.add(bestIndex);
      const hue = hues[bestIndex];
      if (hue !== null) takenHues.push(hue);
      assigned.set(speaker, {color: pool[bestIndex], index: bestIndex});
      continue;
    }

    // 2.1.4: past both palettes, generate a pastel at the emptiest hue rather
    // than repeating a colour that is already carrying an identity.
    let bestHue = 0;
    let widest = -1;
    for (let hue = 0; hue < 360; hue += 5) {
      const distance = takenHues.length
        ? Math.min(...takenHues.map((taken) => hueDistance(hue, taken)))
        : 180;
      if (distance > widest) {
        widest = distance;
        bestHue = hue;
      }
    }
    takenHues.push(bestHue);
    assigned.set(speaker, {color: pastelForHue(bestHue), index: -1});
  }

  return assigned;
}

/** The themed assignment map the studio passes around. */
export type SpeakerColorMap = Map<string, {color: string; index: number}>;

/** DISPLAY status, not tracker status. */
export function speakerStatus(
  word: {speaker?: string | null; speaker_status?: string | null},
): string {
  const reported = word.speaker_status
    ?? (word.speaker ? "stable" : "unknown");
  if (reported === "unknown" && word.speaker) return "provisional";
  return reported;
}

/** CWI 2.1, via `assignSpeakerColors` — see the module comment for why the
   assignment is wheel geometry and not a lookup. */
export function speakerColor(
  speaker: string | null | undefined,
  colors: SpeakerColorMap,
): string {
  if (!speaker) return "var(--caption-unknown)";
  return colors.get(speaker)?.color ?? "var(--accent)";
}
