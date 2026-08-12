"""Closed-caption renderer: the full CWI motion system, text known in advance.

Live can only approximate CWI, because 2.2.1 read-ahead assumes the line exists
before it is spoken. This takes a finished CaptionSpec and plays it against a
clock, so read-ahead is real, the colour turn sweeps across a word over its own
spoken span, and the travelling wave is safe — a closed caption plays through
instead of accumulating under a reader.

The motion comes from ``Academy_CI_Template.aep``, not from the reference
recordings, which are a screen capture of the website and a different
implementation. The template's four animators touch only Position 3D and Fill
Color: no scale, tracking, size, rotation, skew or opacity animator exists in
the file. ``Yellow`` drives the lift and the fill from ONE range selector, so a
letter is at the top of its lift at the instant it turns. That is the bounce.

The recordings are matched as three composable systems on different scopes,
and they must not be collapsed into one generic text wave:

1. **Intonation**, on the WORD. One uniform envelope over every letter —
   amplitude is prosody. Size and weight are never sent letter by letter.
2. **Synchronization**, on each CHARACTER, around that letter's own turn.
3. **Speaker identity**, colour only — never a reason to swell or lift.

Both scales are transforms, never font-size, so an emphasised word cannot
reflow the line. Everything returns to one resting size, weight and baseline.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from string import Template

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _lines(words: list[dict], max_words: int, gap_s: float) -> list[list[dict]]:
    """Group words into caption lines on speaker change, pause, or length.

    ``max_words <= 0`` means never break on length, and a word carrying
    ``line_break: true`` always starts a new line. An authored spec — a
    reference derived from a recording, say — then keeps its own grouping
    instead of being regrouped by whatever ``display.max_words`` happens to be:
    the default 8 splits a 10-word sentence in half, and a 2 s gap threshold
    merges phrases that the recording shows as separate captions.
    """

    lines: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            previous = current[-1]
            word_status = word.get("speaker_status") or "stable"
            previous_status = previous.get("speaker_status") or "stable"
            stable_change = (
                word_status in {"stable", "corrected"}
                and previous_status in {"stable", "corrected"}
                and word["speaker"] != previous["speaker"]
            )
            if (word.get("line_break")
                    or stable_change
                    or (gap_s is not None and word["start"] - previous["end"] > gap_s)
                    or (max_words > 0 and len(current) >= max_words)):
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


def render_cc(config: dict, spec: dict, out_dir: str | Path,
              media: str | None = None, tune: bool = False) -> str:
    """Render the playback page. ``tune`` adds the live motion tuner.

    The tuner loops the clip and exposes every motion constant as a slider that
    takes effect on the next frame, so the feel can be judged in motion instead
    of from stills. It writes to a separate file so the normal page is never
    shipped carrying a control panel.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    font_path = Path(config["render"]["font_path"])
    if not font_path.is_absolute():
        font_path = _REPO_ROOT / font_path
    if not font_path.exists():
        raise SystemExit(
            f"variable font not found at {font_path} — run: python scripts/fetch_font.py"
        )
    font_b64 = base64.b64encode(font_path.read_bytes()).decode()

    palette = list(config["palette"]) + list(config.get("palette_support", []))
    box = config["caption_box"]
    motion = config.get("motion", {})
    display = config.get("display", {})
    cc = config.get("closed_caption", {})
    tracking = cc.get("tracking", {}) or {}
    speaker_attribution = config.get("live", {}).get("speaker_attribution", {}) or {}

    words = list(spec["words"])
    # `closed_caption` wins where it says anything: a spec derived from a
    # recording carries its own grouping and must not be re-cut by the live
    # transcript defaults.
    max_words = cc.get("max_words", display.get("max_words", 8))
    gap_s = cc.get("line_break_gap_s", display.get("line_break_gap_s", 2.0))
    lines = _lines(words, max_words, gap_s)
    # Colours come from the spec's own speaker table so an authored file keeps
    # its cast, falling back to palette order for anyone it does not name.
    speakers = {name: entry["color"]
                for name, entry in (spec.get("speakers") or {}).items()}
    for index, name in enumerate(dict.fromkeys(w["speaker"] for w in words)):
        speakers.setdefault(name, palette[index % len(palette)])

    # `cc` may push the expression axes harder than live mode. Live has to stay
    # calm because words accumulate and a settled word must not restyle; a
    # closed caption plays through and is gone, and the reference recordings
    # swell further than live's compression allows. Overrides live under
    # `closed_caption` and fall back to `expression`, so live is untouched.
    from .ccprosody import merged_expression
    expression = merged_expression(config)

    page_cfg = {
        "mapping": config["mapping"],
        "expression": expression,
        "min_voiced_frac": config["normalization"]["min_voiced_frac"],
        "speakers": speakers,
        "box_opacity": box["opacity"],
        "bottom_margin_pct": box["bottom_margin_pct"],
        "max_lines": cc.get("max_lines", box.get("max_lines", 2)),
        "size_pct": cc.get("size_pct"),
        "duration": spec.get("media", {}).get("duration", 0.0)
                    or (words[-1]["end"] + 2 if words else 0.0),
        # CWI 2.2.1: how long a line is legible in white before it is spoken.
        "read_ahead_s": cc.get("read_ahead_s", 2.0),
        "line_hold_s": cc.get("line_hold_s", 1.2),
        # word | character — how the colour turn crosses a word.
        "sync": cc.get("sync_granularity", "character"),
        "elevation_em": motion.get("elevation_em", 0.25),
        "anticipation_ms": motion.get("anticipation_ms", 33),
        "neighbor_bleed": cc.get("neighbor_bleed", 0.34),
        # Amplitude of the character wave, 0..1. 0 = the calm film setting
        # (colour sweep only, every letter on one baseline).
        "wave_reach": cc.get("wave_reach", 1.0),
        # Fitted to the three reference recordings (see config.yaml). All in
        # seconds / em, held in TIME so the ripple travels at one rate through
        # a two-letter word and a nine-letter one.
        "wave_crouch_em": cc.get("wave_crouch_em", 0.052),
        "wave_crouch_lead_s": cc.get("wave_crouch_lead_s", 0.22),
        "wave_release_s": cc.get("wave_release_s", 0.28),
        # How long the raised, still-white anticipation may hold.
        "wave_hold_max_s": cc.get("wave_hold_max_s", 0.90),
        "wave_hold_floor": cc.get("wave_hold_floor", 0.18),
        "wave_hold_full_s": cc.get("wave_hold_full_s", 0.70),
        "wave_peak_s": cc.get("wave_peak_s", 0.08),
        "pop_release_s": cc.get("pop_release_s", 0.29),
        "pop_peak_s": cc.get("pop_peak_s", 0.11),
        # "Antecipate": y = +2 against the lift's -(5 + amp), i.e. a small
        # DOWNWARD dip one frame ahead of the rise.
        "anticipation_dip_em": cc.get("anticipation_dip_em", 0.04),
        # 1. INTONATION, word level and UNIFORM across the word's letters.
        "emphasis_lead_s": cc.get("emphasis_lead_s", 0.18),
        # Quiet words barely deform; loud words swell freely.
        "quiet_deformation": cc.get("quiet_deformation", 0.35),
        # Only a genuine deviation animates; ordinary words sit still.
        "emphasis_deadband": cc.get("emphasis_deadband", 0.10),
        "emphasis_hold_s": cc.get("emphasis_hold_s", 0.08),
        "emphasis_tail_s": cc.get("emphasis_tail_s", 0.30),
        # 2. SYNCHRONIZATION, character level. Two asymmetric phases either
        # side of the letter's own colour turn.
        "wave_lift_em": cc.get("wave_lift_em", 0.10),
        "wave_dip": cc.get("wave_dip", 0.02),      # 0.98 approaching
        "wave_pop": cc.get("wave_pop", 0.06),      # 1.06 just after the turn
        "color_turn_ms": motion.get("color_turn_ms", 90),
        "rest_color": cc.get("rest_color", "rgba(255,255,255,.9)"),
        "lift_ms": round(motion.get("duration_s", 0.56) * 1000),
        "easing": motion.get("easing", "ease-in-out"),
        # The baked `lift` channel is in GLYPH HEIGHTS, the unit the recordings
        # are measured in; this converts it to em. Roboto Flex's cap height is
        # ~0.71 em and a mixed-case word's median ink height sits just under
        # it. Calibrate with scripts/compare_to_reference.py, never by eye.
        "glyph_height_em": cc.get("glyph_height_em", 0.70),
        # 2.2.3, stated outright in the design system: each word pops +15% in
        # type size and rises 25% as it changes colour, then returns. Same for
        # every word — it is a synchronization cue, not prosody.
        "sync_pop": cc.get("sync_pop", 0.15),
        "sync_elevation_em": cc.get("sync_elevation_em", 0.25),
        "sync_rise_s": cc.get("sync_rise_s", 0.09),
        "sync_peak_s": cc.get("sync_peak_s", 0.08),
        "sync_fall_s": cc.get("sync_fall_s", 0.18),
        "motion_source": cc.get("motion_source", "spec"),
        "debug_churn": bool(cc.get("debug_churn", False)),
        "provisional_color_strength": speaker_attribution.get(
            "provisional_color_strength", 0.55
        ),
        "tracking": {
            "enabled": bool(tracking.get("enabled", False)),
            "playhead_pct": tracking.get("playhead_pct", 50.0),
            "interp": tracking.get("interp", "monotone_cubic"),
            "coast_s": tracking.get("coast_s", 0.18),
            "handoff_s": tracking.get("handoff_s", 0.36),
            "catch_up_s": tracking.get("catch_up_s", 0.20),
            "enter_offset_pct": tracking.get("enter_offset_pct", 32.0),
            "exit_offset_pct": tracking.get("exit_offset_pct", -32.0),
        },
        "lines": [[{k: w[k] for k in
                    ("text", "start", "end", "speaker", "speaker_status",
                     "speaker_confidence", "speaker_change_probability",
                     "speaker_revision_id", "overlap", "loudness",
                     "pitch_hz", "voiced_frac", "motion", "tracking") if k in w}
                   for w in line]
                  for line in lines],
    }

    html = _TEMPLATE.safe_substitute(
        FONT_B64=font_b64,
        CFG_JSON=json.dumps(page_cfg),
        MEDIA=json.dumps(media or ""),
    )
    if tune:
        html = html.replace("</body>", _TUNER + "</body>")
    out = out_dir / ("tuner.html" if tune else "captions.html")
    out.write_text(html, encoding="utf-8")
    return str(out)


# ---------------------------------------------------------------------------
# Live motion tuner (``--tune``). Appended to the page so the renderer itself
# stays free of it. Every control writes straight into CFG and the next frame
# picks it up; the few constants baked into each word's `_type` go through
# retype(). Deliberately no `$`, since the page is a string.Template.
# ---------------------------------------------------------------------------
_TUNER = r'''
<style>
  #tuner {
    position: fixed; top: 0; right: 0; width: 330px; height: 100vh; z-index: 20;
    background: #111116; border-left: 1px solid #2a2a33; overflow-y: auto;
    font: 12px/1.45 ui-sans-serif, system-ui, sans-serif; color: #d8d8e0;
    padding: 12px 14px 40px;
  }
  #tuner h2 { font-size: 12px; letter-spacing: .09em; text-transform: uppercase;
              color: #8a8a96; margin: 18px 0 8px; font-weight: 600; }
  #tuner h2:first-child { margin-top: 0; }
  #tuner .row { margin: 9px 0; }
  #tuner .lab { display: flex; justify-content: space-between; gap: 8px; }
  #tuner .lab b { font-weight: 500; color: #e8e8f0; }
  #tuner .lab span { font-variant-numeric: tabular-nums; color: #E5E517; }
  #tuner input[type=range] { width: 100%; accent-color: #E5E517; margin: 3px 0 0; }
  #tuner .note { color: #75757f; font-size: 11px; margin: 2px 0 0; }
  #tuner .bar { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
  #tuner button {
    font: inherit; background: #22222b; color: #e8e8f0; border: 1px solid #35353f;
    border-radius: 5px; padding: 5px 9px; cursor: pointer;
  }
  #tuner button:hover { background: #2c2c37; }
  #tuner textarea {
    width: 100%; height: 190px; margin-top: 8px; background: #0b0b0f;
    color: #cfcfd8; border: 1px solid #2a2a33; border-radius: 5px; padding: 8px;
    font: 11px/1.5 ui-monospace, monospace; resize: vertical;
  }
  #stage, footer { right: 330px; }
  #tuner .curve { width: 100%; height: 92px; background: #0b0b0f;
                  border: 1px solid #2a2a33; border-radius: 5px; display: block; }
</style>
<div id="tuner">
  <h2>Playback</h2>
  <div class="bar">
    <button id="tnPlay">Pause</button>
    <button id="tnSlow">0.5x</button>
    <button id="tnBack">Restart</button>
    <label style="display:flex;align-items:center;gap:5px">
      <input type="checkbox" id="tnLoop" checked> loop
    </label>
  </div>
  <p class="note" id="tnClock"></p>

  <h2>Character wave</h2>
  <canvas class="curve" id="tnCurve" width="300" height="92"></canvas>
  <p class="note">One letter's vertical motion, relative to its colour turn
    (dashed). Above the line = raised.</p>
  <div id="tnCharacter"></div>

  <h2>Word intonation</h2>
  <div id="tnWord"></div>

  <h2>Colour &amp; type</h2>
  <div id="tnColour"></div>

  <div class="bar">
    <button id="tnReset">Reset all</button>
    <button id="tnYaml">Show config.yaml</button>
  </div>
  <textarea id="tnOut" spellcheck="false" hidden></textarea>
</div>
<script>
"use strict";
(function () {
  // key, label, min, max, step, needsRetype, note
  const CHAR = [
    ["wave_reach",      "wave_reach",      0, 1,    0.01, 0, "master amount; 0 = calm, colour sweep only"],
    ["wave_crouch_em",     "wave_crouch_em",     0, 0.20, 0.002, 0, "how far BELOW the baseline before the turn"],
    ["wave_crouch_lead_s", "wave_crouch_lead_s", 0.04, 0.60, 0.01, 0, "when the crouch begins"],
    ["wave_lift_em",       "wave_lift_em",       0, 0.30, 0.002, 0, "how far ABOVE the baseline after it"],
    ["wave_peak_s",        "wave_peak_s",        0.02, 0.25, 0.005, 0, "when the rise peaks"],
    ["wave_release_s",     "wave_release_s",     0.06, 0.70, 0.01, 0, "rise + settle, all after the turn"],
    ["wave_pop",           "wave_pop",           0, 0.35, 0.005, 0, "size bloom after the turn"],
    ["pop_peak_s",         "pop_peak_s",         0.02, 0.30, 0.005, 0, "when the bloom peaks"],
    ["pop_release_s",      "pop_release_s",      0.06, 0.70, 0.01, 0, "how long the bloom lasts"],
    ["wave_dip",           "wave_dip",           0, 0.12, 0.005, 0, "optional squash during the crouch"],
  ];
  const WORD = [
    ["emphasis_lead_s",   "emphasis_lead_s",   0,    0.45, 0.01, 0, "swell starts before the spoken onset"],
    ["emphasis_hold_s",   "emphasis_hold_s",   0,    0.40, 0.01, 0, "hold past the word's end"],
    ["emphasis_tail_s",   "emphasis_tail_s",   0.05, 0.90, 0.01, 0, "decay back to rest"],
    ["emphasis_deadband", "emphasis_deadband", 0,    0.35, 0.01, 1, "ordinary words below this never animate"],
    ["quiet_deformation", "quiet_deformation", 0,    1,    0.01, 1, "how much a QUIET word shrinks"],
  ];
  const COLOUR = [
    ["color_turn_ms",   "color_turn_ms",   0, 320, 5,    0, "white to speaker colour crossfade"],
    ["anticipation_ms", "anticipation_ms", 0, 200, 1,    0, "motion leads the colour by this"],
    ["size_pct",        "size_pct",        1.2, 8, 0.05, 1, "resting size, % of frame height"],
  ];
  const ALL = CHAR.concat(WORD, COLOUR);
  const initial = {};
  ALL.forEach(s => { initial[s[0]] = CFG[s[0]]; });

  function build(host, spec) {
    spec.forEach(s => {
      const [key, label, min, max, step, retypes, note] = s;
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML =
        '<div class="lab"><b>' + label + '</b><span></span></div>' +
        '<input type="range">' +
        (note ? '<p class="note">' + note + '</p>' : "");
      const out = row.querySelector("span"), inp = row.querySelector("input");
      inp.min = min; inp.max = max; inp.step = step; inp.value = CFG[key];
      const show = () => { out.textContent = (+CFG[key]).toFixed(step < 0.01 ? 3 : (step < 1 ? 2 : 0)); };
      show();
      inp.addEventListener("input", () => {
        CFG[key] = parseFloat(inp.value);
        show();
        if (retypes) retype();
        drawCurve();
        render();
      });
      s.push(inp, show);
      host.appendChild(row);
    });
  }
  build(document.getElementById("tnCharacter"), CHAR);
  build(document.getElementById("tnWord"), WORD);
  build(document.getElementById("tnColour"), COLOUR);

  // --- the actual curve the current settings produce ----------------------
  const cv = document.getElementById("tnCurve"), cx = cv.getContext("2d");
  // Same model the renderer uses, normalised so the plot fills the box.
  function liftAt(d) {
    const em = CFG.wave_lift_em * pulse(d, CFG.wave_release_s, CFG.wave_peak_s)
             - CFG.wave_crouch_em * crouch(d, CFG.wave_crouch_lead_s);
    return em / Math.max(1e-6, CFG.wave_lift_em, CFG.wave_crouch_em);
  }
  function drawCurve() {
    const W = cv.width, H = cv.height, mid = H * 0.62;
    cx.clearRect(0, 0, W, H);
    cx.strokeStyle = "#2a2a33"; cx.beginPath();
    cx.moveTo(0, mid); cx.lineTo(W, mid); cx.stroke();
    const t0 = -0.30, t1 = 0.60;
    const xOf = tt => W * (tt - t0) / (t1 - t0);
    cx.strokeStyle = "#55555f"; cx.setLineDash([3, 3]); cx.beginPath();
    cx.moveTo(xOf(0), 0); cx.lineTo(xOf(0), H); cx.stroke(); cx.setLineDash([]);
    cx.strokeStyle = "#E5E517"; cx.lineWidth = 1.6; cx.beginPath();
    for (let i = 0; i <= W; i++) {
      const tt = t0 + (t1 - t0) * i / W;
      const y = mid - liftAt(tt) * CFG.wave_reach * (mid - 6);
      i ? cx.lineTo(i, y) : cx.moveTo(i, y);
    }
    cx.stroke();
  }
  drawCurve();

  // --- transport ----------------------------------------------------------
  const loopBox = document.getElementById("tnLoop");
  const clock = document.getElementById("tnClock");
  document.getElementById("tnPlay").onclick = e => {
    playBtn.click(); e.target.textContent = playing ? "Pause" : "Play";
  };
  document.getElementById("tnBack").onclick = () => { t = 0; render(); };
  document.getElementById("tnSlow").onclick = e => {
    const order = ["1", "0.5", "0.25"];
    const next = order[(order.indexOf(rate.value) + 1) % order.length];
    rate.value = next; rate.onchange && rate.onchange();
    e.target.textContent = next + "x";
  };
  // Loop by watching the clock: the page's own tick() stops at the end, and
  // re-entering through play() keeps the transport as the single owner of `t`.
  setInterval(() => {
    clock.textContent = t.toFixed(2) + " / " + CFG.duration.toFixed(2) + " s";
    if (loopBox.checked && !playing && t >= CFG.duration - 0.02) {
      t = 0; playBtn.click();
      document.getElementById("tnPlay").textContent = "Pause";
    }
  }, 120);
  if (!playing) { playBtn.click(); }

  // --- export / reset -----------------------------------------------------
  const out = document.getElementById("tnOut");
  document.getElementById("tnReset").onclick = () => {
    ALL.forEach(s => {
      CFG[s[0]] = initial[s[0]];
      s[7].value = initial[s[0]];
      s[8]();
    });
    retype(); drawCurve(); render();
  };
  document.getElementById("tnYaml").onclick = () => {
    const cc = ALL.filter(s => s[0] !== "color_turn_ms" && s[0] !== "anticipation_ms");
    const fmt = v => (Math.round(v * 1000) / 1000).toString();
    let text = "# closed_caption:\n";
    cc.forEach(s => { text += "  " + s[0] + ": " + fmt(CFG[s[0]]) + "\n"; });
    text += "\n# motion:\n";
    text += "  color_turn_ms: " + Math.round(CFG.color_turn_ms) + "\n";
    text += "  anticipation_ms: " + Math.round(CFG.anticipation_ms) + "\n";
    out.hidden = false; out.value = text; out.select();
  };
})();
</script>
'''


_TEMPLATE = Template(r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Caption with Intention — closed captions</title>
<style>
  @font-face {
    font-family: "Roboto Flex VF";
    src: url(data:font/ttf;base64,$FONT_B64) format("truetype-variations");
    font-weight: 100 1000; font-stretch: 25% 151%;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #08080a; color: #f4f2ea; }
  body { font-family: "Roboto Flex VF", sans-serif; overflow: hidden; }
  .shell { height: 100vh; position: relative; }
  #stage {
    position: absolute; inset: 0; overflow: hidden; background: #000;
    display: flex; flex-direction: column; justify-content: flex-end;
    align-items: center;
  }
  #video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
  #rack {
    width: 100%; display: flex; flex-direction: column; align-items: center;
    position: relative; z-index: 2;
  }
  /* The film reference: a tight black box hugging one centred line, sitting in
     the lower work area (2.4.3). Not a transcript — one line at a time. */
  .cc-line {
    display: flex; align-items: baseline; flex-wrap: wrap; max-width: 86%;
    padding: .06em .30em; margin-top: .1em; background: rgba(0,0,0,.9);
    display: none;
  }
  /* Hidden lines must leave the FLOW, not just fade: at opacity 0 they still
     occupied height and pushed the visible line up out of the work area. */
  .cc-line.on { display: flex; }
  /* Hidden lines have no box, so measuring a word's resting width while its
     line is display:none returns 0. Forced on only for the measuring pass in
     sizeAll(), never during playback. */
  .cc-line.measuring { display: flex; }
  /* The word wrapper carries the INTONATION envelope: one uniform scale and
     weight for the whole word. Scaling by transform (not font-size) keeps it
     off the layout path, so an emphasised word cannot reflow the line, wrap
     it, or shift it vertically. */
  .cc-word {
    line-height: 1.06; display: inline-block; margin-right: .27em;
    /* Centred inside a box frozen at its resting width (see sizeAll), and
       NEVER allowed to break: the frozen width is a rounded measurement, so
       without this the last letter of every word wrapped to a second line. */
    text-align: center; white-space: nowrap;
    color: rgba(255,255,255,.9);
    transform-origin: 50% 100%;
    font-optical-sizing: none; font-synthesis: none;
    text-rendering: geometricPrecision; font-variant-ligatures: none;
  }
  /* One span per CHARACTER. The reference recordings show the colour boundary
     AND the lift landing between letters inside a single word ("a-ni-mati-o"
     at different heights), so the letter is the unit of animation, not the
     word. Spans are inline-block so each can carry its own transform. */
  .cc-ch {
    display: inline-block; white-space: pre;
    transform-origin: 50% 100%;
    backface-visibility: hidden;
  }
  /* Promote the WORD, not each of its letters, and never gated on `.on`:
     toggling will-change with visibility created and destroyed a compositor
     layer per letter on every change, which is a layer storm rather than an
     optimisation. The word is the unit that moves. */
  .cc-word { will-change: transform; }
  /* Tracking is opt-in. In that mode lines leave normal flow and cross the
     clipped rack on one unwrapped row; ordinary CaptionSpecs retain the
     centred flex layout byte-for-byte. */
  html.tracking #rack {
    position: absolute; inset: 0; overflow: hidden; display: block;
  }
  html.tracking .cc-line {
    position: absolute; left: 0; bottom: 0; max-width: none;
    flex-wrap: nowrap; white-space: nowrap; margin: 0;
  }
  footer {
    position: absolute; left: 0; right: 0; bottom: 0; z-index: 5;
    display: flex; align-items: center; gap: 14px; padding: 10px 20px;
    background: linear-gradient(transparent, rgba(0,0,0,.85));
    opacity: 0; transition: opacity .25s ease;
  }
  .shell:hover footer, footer:focus-within { opacity: 1; }
  button {
    font: inherit; background: #1b1b21; color: #f4f2ea; border: 1px solid #333;
    border-radius: 4px; padding: 7px 14px; cursor: pointer;
  }
  button:hover { background: #26262e; }
  #scrub { flex: 1; accent-color: #e5e517; }
  .readout { font-variant-numeric: tabular-nums; color: #9a9aa2; font-size: 12px; min-width: 96px; }
  label { color: #9a9aa2; font-size: 11px; display: flex; align-items: center; gap: 6px; }
  @media (prefers-reduced-motion: reduce) {
    *, *:before, *:after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
  }
</style>
</head>
<body>
<div class="shell">
  <div id="stage"><video id="video" playsinline></video><div id="rack"></div></div>
  <footer>
    <button id="play">Play</button>
    <input id="scrub" type="range" min="0" step="0.01" value="0">
    <span class="readout" id="clock">0.00 / 0.00</span>
    <label>speed
      <select id="rate">
        <option value="0.25">0.25x</option><option value="0.5">0.5x</option>
        <option value="1" selected>1x</option>
      </select>
    </label>
    <label><input type="checkbox" id="sync" checked> character sweep</label>
    <label><input type="checkbox" id="wave" checked> wave</label>
  </footer>
</div>

<script id="cfg" type="application/json">$CFG_JSON</script>
<script>
"use strict";
const CFG = JSON.parse(document.getElementById("cfg").textContent);
const MEDIA = $MEDIA;
const M = CFG.mapping, EX = CFG.expression;
const stage = document.getElementById("stage");
const rack = document.getElementById("rack");
const video = document.getElementById("video");
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const charSweep = document.getElementById("sync");
const waveOn = document.getElementById("wave");
charSweep.checked = CFG.sync === "character";
document.documentElement.classList.toggle("tracking", !!CFG.tracking.enabled);

function lerp(a, b, f) { return a + (b - a) * f; }
function clamp01(f) { return Math.min(1, Math.max(0, f)); }
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
const colorFor = s => CFG.speakers[s] || "#E5E517";
// Smoothstep: zero slope at BOTH ends. Every envelope below is shaped through
// it, because a ramp that starts or stops with a non-zero derivative shows up
// as a visible kick at the moment motion begins or ends.
function ease(f) { f = clamp01(f); return f * f * (3 - 2 * f); }
// A single-humped pulse fitted to the reference recordings: leaves 0 with a
// positive slope, peaks at `peak` seconds, and is back to 0 at `dur`.
// sin(pi x)*e^(-kx), with k solved so the maximum lands where it was measured.
function pulse(d, dur, peak) {
  if (d <= 0 || d >= dur) return 0;
  const xp = clamp(peak / dur, 0.02, 0.48);
  const k = Math.PI / Math.tan(Math.PI * xp);
  const norm = Math.sin(Math.PI * xp) * Math.exp(-k * xp);
  return Math.sin(Math.PI * (d / dur)) * Math.exp(-k * (d / dur)) / norm;
}
// The crouch a letter holds while it is still unspoken: down, then back to the
// baseline exactly as it turns.
function crouch(d, lead) {
  if (d >= 0 || d <= -lead) return 0;
  // A plateau, not a hump: measured, the letter drops over ~60 ms, HOLDS down
  // for ~120 ms, then releases into the turn over ~40 ms.
  const u = -d / lead;
  return ease((1 - u) / 0.32) * ease(u / 0.22);
}

// --- colour interpolation -------------------------------------------------
// The turn used to be a boolean per letter, so a character jumped white ->
// full speaker colour in one frame. `motion.color_turn_ms` was already in the
// config ("color eases with the lift, never a hard cut") and simply unused.
function parseColor(c) {
  c = c.trim();
  if (c[0] === "#") {
    const h = c.length === 4
      ? c[1] + c[1] + c[2] + c[2] + c[3] + c[3] : c.slice(1);
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16),
            parseInt(h.slice(4, 6), 16), 1];
  }
  const n = c.replace(/^rgba?\(|\)$/g, "").split(",").map(parseFloat);
  return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1];
}
const REST_RGBA = parseColor(CFG.rest_color);
const _mixCache = new Map();
function mixColor(speaker, f) {
  // Quantized to 32 steps: the eye cannot resolve finer, and it keeps the
  // written string stable across frames so most writes become no-ops.
  const q = Math.round(clamp01(f) * 32);
  const key = speaker + "|" + q;
  let hit = _mixCache.get(key);
  if (hit) return hit;
  const to = parseColor(colorFor(speaker)), g = q / 32;
  hit = "rgba(" + Math.round(lerp(REST_RGBA[0], to[0], g)) + ","
                + Math.round(lerp(REST_RGBA[1], to[1], g)) + ","
                + Math.round(lerp(REST_RGBA[2], to[2], g)) + ","
                + lerp(REST_RGBA[3], to[3], g).toFixed(3) + ")";
  _mixCache.set(key, hit);
  return hit;
}
function speakerStatus(w) { return w.speaker_status || "stable"; }
function wordColor(w, f) {
  const status = speakerStatus(w);
  const strength = status === "unknown" ? 0 :
    (status === "provisional" ? CFG.provisional_color_strength : 1);
  return mixColor(w.speaker, f * strength);
}

// ---------------------------------------------------------------------------
// Typography — same CWI mapping as live mode, but resolved ONCE for the whole
// file up front. An authored caption has no reason to discover its own
// dynamics as it goes, so there is no smoothing state and no drift.
// ---------------------------------------------------------------------------
function pitchAxis(m, hz) {
  const d = m.domain_hz || M.pitch_to.domain_hz;
  let f = clamp01((hz - d[0]) / (d[1] - d[0]));
  if (m.invert) f = 1 - f;
  return lerp(m.min, m.max, f);
}
function towardBaseline(value, baseline, response, min, max) {
  const extent = value >= baseline ? max - baseline : baseline - min;
  if (!(extent > 0)) return baseline;
  const d = clamp((value - baseline) / extent, -1, 1);
  return baseline + Math.sign(d) * Math.pow(Math.abs(d), 1 / response) * extent;
}
const allWords = CFG.lines.flat();
const voiced = allWords.filter(w => w.pitch_hz > 0 && w.voiced_frac >= CFG.min_voiced_frac);
const medianPitch = voiced.length
  ? voiced.map(w => w.pitch_hz).sort((a, b) => a - b)[voiced.length >> 1] : null;

// Type is STATIC per word. The .aep contains exactly four text animators
// ("Words", "Up", "Yellow", "Antecipate") and between them they touch only
// `ADBE Text Position 3D` and `ADBE Text Fill Color` — there is no
// `ADBE Text Scale`, `ADBE Text Tracking`, `ADBE Text Size`, rotation, skew
// or opacity animator anywhere in the file. Size is therefore not a motion
// channel at all: it is the LOUDNESS channel (CWI 2.3.3-2.3.6), set once per
// word and never animated. Weight is pitch, likewise static.
//
// ...that is the AE TEMPLATE. The reference recordings in docs/ are the
// website, a different implementation, and it plainly does animate size and
// weight: "sizes," is large only while it is the active word and returns to
// normal as "weights" takes over. This renderer follows the recordings,
// because they are what the design is being matched against; the template's
// position-and-colour-only rule is the stricter, calmer reading of the same
// system and is what `wave_reach: 0` gives.
const medianLoudness = (() => {
  const v = allWords.map(w => clamp01(w.loudness)).sort((a, b) => a - b);
  return v.length ? v[v.length >> 1] : 0.5;
})();
function typeOf(w) {
  const sm = M.loudness_to;
  // Pivot the scale on the MEDIAN word so ordinary speech lands on the CWI
  // baseline (2.3.5) instead of mid-range, then compress deviations by
  // `size_response` so normal delivery does not read as whisper/shout.
  const anchorPct = CFG.size_pct || sm.baseline;
  // CWI's size anchors are RATIOS around its baseline (2.3.5: whisper 3% /
  // normal 5% / shout 12%), written here as absolute percentages. They only
  // mean that when the resting size IS the baseline, so rescale the range by
  // whatever resting size is in use. Without this, a `size_pct` below
  // `loudness_to.min` puts the baseline outside the range, `towardBaseline`
  // takes its `extent <= 0` guard for every quiet word, and the whole quiet
  // half of the loudness channel silently renders as no deviation at all.
  const k = anchorPct / sm.baseline;
  const smMin = sm.min * k, smMax = sm.max * k;
  const rawSize = lerp(smMin, smMax, clamp01(w.loudness));
  const medSize = lerp(smMin, smMax, medianLoudness);
  const emphPct = towardBaseline(rawSize - medSize + anchorPct, anchorPct,
                                 EX.size_response, smMin, smMax);
  const isVoiced = w.pitch_hz > 0 && w.voiced_frac >= CFG.min_voiced_frac;
  const wm = M.pitch_to;
  const wBand = EX.anchor_wght || [350, 700];
  const wAnchor = clamp(medianPitch === null ? 400 : pitchAxis(wm, medianPitch),
                        wBand[0], wBand[1]);
  // Bound the RENDERED axis, not just the anchor. The response curve leaves
  // values at the pitch-domain edge uncompressed, so an 80 Hz voice resolves to
  // wght 1000 and a 250 Hz one to 100 -- ultra-black and hairline beside
  // ordinary text. Live mode has always clamped to `expression.wght_range`;
  // `cc` did not, which is the same bug this file's own notes describe.
  const wRange = EX.wght_range || [wm.min, wm.max];
  const wght = Math.round(clamp(clamp(isVoiced
    ? towardBaseline(pitchAxis(wm, w.pitch_hz), wAnchor, EX.weight_response, wm.min, wm.max)
    : wAnchor, wm.min, wm.max), wRange[0], wRange[1]));
  let wdth = 100;
  if (M.harmonics_to) {
    const hm = M.harmonics_to;
    const hBand = EX.anchor_wdth || [88, 112];
    const hAnchor = clamp(medianPitch === null ? 100 : pitchAxis(hm, medianPitch),
                          hBand[0], hBand[1]);
    const hRange = EX.wdth_range || [hm.min, hm.max];
    wdth = Math.round(clamp(clamp(isVoiced
      ? towardBaseline(pitchAxis(hm, w.pitch_hz), hAnchor, EX.width_response, hm.min, hm.max)
      : hAnchor, hm.min, hm.max), hRange[0], hRange[1]));
  }
  // EVERY word rests at the same size and weight. Prosody is only the SIZE OF
  // THE ENVELOPE a word swells through while it is spoken — `emphScale` is a
  // ratio against the common resting size, so a median word is ~1.0 (almost no
  // deformation), a loud word clearly larger, a quiet one slightly smaller.
  // Nothing is baked in: after the envelope decays a word is identical to its
  // neighbours.
  let emphScale = emphPct / Math.max(1e-6, anchorPct);
  // The envelope is an EMPHASIS: a loud word swells freely, but a quiet one
  // should barely deform rather than visibly shrink — an unemphatic word is
  // not an event. The below-baseline side is therefore compressed on its own.
  if (emphScale < 1) emphScale = 1 - (1 - emphScale) * CFG.quiet_deformation;
  // DEADBAND. CWI reads as uniform type with only OCCASIONAL emphasis; giving
  // every word its own envelope means something is always moving, which is
  // what reads as noise. Ordinary delivery is pinned to exactly 1 (no envelope
  // at all, no writes) and only a genuine deviation animates. Subtracted
  // rather than thresholded, so a word just past the gate starts from zero
  // instead of jumping to full amplitude.
  const dev = Math.abs(emphScale - 1);
  emphScale = dev <= CFG.emphasis_deadband ? 1
    : 1 + Math.sign(emphScale - 1) * (dev - CFG.emphasis_deadband);
  return {restPct: anchorPct, emphScale: emphScale,
          // ON THE SAME /4 GRID the animated weight is quantized to. As a raw
          // float this produced '"wght" 347.6234...' from build/retype/settle
          // against '"wght" 348' from frame(), so the _vf cache could never
          // match across a settle boundary and every resume forced a
          // font-variation-settings write -- which relays out the whole line.
          restWght: Math.round(wAnchor / 4) * 4, emphWght: wght, wdth: wdth};
}

// ---------------------------------------------------------------------------
// Build every line once. Nothing is created or destroyed during playback —
// only --fill and transform change, which is why this can never churn.
// ---------------------------------------------------------------------------
const built = CFG.lines.map(words => {
  const div = document.createElement("div");
  div.className = "cc-line";
  div.style.background = "rgba(0,0,0," + CFG.box_opacity + ")";
  const nodes = words.map(w => {
    const el = document.createElement("span");
    el.className = "cc-word";
    el.dataset.speakerStatus = speakerStatus(w);
    el.classList.add("speaker-" + speakerStatus(w));
    el.setAttribute("aria-label", w.text + " · speaker attribution " +
                    speakerStatus(w));
    const chars = Array.from(w.text).map(c => {
      const span = document.createElement("span");
      span.className = "cc-ch";
      span.textContent = c;
      el.appendChild(span);
      return span;
    });
    const t = typeOf(w);
    el._type = t;
    el._vf = '"opsz" 14, "wght" ' + t.restWght + ', "wdth" ' + t.wdth;
    el.style.fontVariationSettings = el._vf;
    el.title = w.text + "  " + w.start.toFixed(2) + "-" + w.end.toFixed(2) + "s";
    div.appendChild(el);
    return {el: el, chars: chars, w: w};
  });
  rack.appendChild(div);
  const explicitTracking = words.some(w => w.tracking !== undefined);
  return {div: div, nodes: nodes, words: words,
          start: words[0].start, end: words[words.length - 1].end,
          // Derived specs mark every word explicitly, so a static title can
          // coexist with scrolling sentences. Synthetic/tuner specs have no
          // marker and follow the master switch.
          trackingRequested: explicitTracking
            ? words.some(w => w.tracking === true) : true};
});

function trackingOn(line) {
  return !!CFG.tracking.enabled && line.trackingRequested;
}
function turnAt(node, c) {
  const span = Math.max(1e-3, node.w.end - node.w.start);
  return charSweep.checked
    ? node.w.start + (c + 0.5) / node.chars.length * span
    : node.w.start;
}

// Each word records when its PREDECESSOR's last character turned, so the
// anticipation can run from there rather than from a fixed offset. Recomputed
// by retype() so the tuner can move the timings underneath it.
function linkTurns() {
  built.forEach(line => {
    let prev;
    line.nodes.forEach(n => {
      n.prevTurn = prev;
      const w = n.w, m = n.chars.length;
      const span = Math.max(1e-3, w.end - w.start);
      prev = w.start + ((m - 1) + 0.5) / m * span;
    });
  });
}

// Fritsch-Carlson slopes for a monotone cubic. Character centres increase in
// reading order and their turn times increase in speech order, so this gives a
// C1 playhead path that cannot briefly run backwards between samples.
function monotoneSlopes(a) {
  const n = a.length, d = [], m = new Array(n).fill(0);
  if (n < 2) return m;
  for (let i = 0; i < n - 1; i++)
    d.push((a[i + 1].x - a[i].x) / Math.max(1e-6, a[i + 1].t - a[i].t));
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++)
    m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(d[i]) < 1e-9) { m[i] = 0; m[i + 1] = 0; continue; }
    const aa = m[i] / d[i], bb = m[i + 1] / d[i];
    const q = aa * aa + bb * bb;
    if (q > 9) {
      const tau = 3 / Math.sqrt(q);
      m[i] = tau * aa * d[i]; m[i + 1] = tau * bb * d[i];
    }
  }
  return m;
}
function offsetInside(el, ancestor) {
  let x = 0, p = el;
  while (p && p !== ancestor) { x += p.offsetLeft; p = p.offsetParent; }
  return x;
}
function buildTracking(line) {
  if (!line.trackingRequested) { line.track = null; return; }
  const anchors = [];
  line.nodes.forEach((node, wi) => {
    const wordLeft = offsetInside(node.el, line.div);
    node.wordCentre = wordLeft + node.restW / 2;
    node.chars.forEach((ch, ci) => {
      const x = offsetInside(ch, line.div) + ch.offsetWidth / 2;
      anchors.push({t: turnAt(node, ci), x: x, node: node,
                    dx: x - node.wordCentre, wi: wi});
    });
  });
  anchors.sort((a, b) => a.t - b.t || a.x - b.x);
  const slopes = monotoneSlopes(anchors);
  anchors.forEach((a, i) => { a.slope = slopes[i]; });
  line.track = anchors;
  line.restLineW = Math.max(1, line.div.scrollWidth);
}

// One resting size for every word. The intonation envelope is a transform on
// top of it, never a change to the measured font size.
function sizeAll() {
  const h = stage.clientHeight;
  built.forEach(line => line.nodes.forEach(n => {
    n.el.style.fontSize = (n.el._type.restPct / 100 * h).toFixed(1) + "px";
  }));
  // Measure each word's RESTING width and which visual row it sits on. A
  // swelling word pushes its neighbours aside (see `layout()`), and the push
  // is computed from these — reserving static margin instead just padded the
  // line out and still overlapped, because the growth is symmetric about the
  // word's own centre. offsetWidth/offsetTop are layout values, unaffected by
  // any transform, so this stays correct however the words are animating.
  // Every line must be laid out to be measurable: a display:none line reports
  // offsetWidth 0 for all of its words, which silently disables the push
  // entirely (every shift resolves to 0 and words grow over each other).
  built.forEach(line => line.div.classList.add("measuring"));
  built.forEach(line => line.nodes.forEach(n => { n.el.style.width = ""; }));
  built.forEach(line => line.nodes.forEach(n => {
    // getBoundingClientRect is FRACTIONAL; offsetWidth rounds, and a width
    // rounded down by half a pixel is narrower than the text it has to hold.
    n.restW = n.el.getBoundingClientRect().width;
    n.restRow = n.el.offsetTop;
  }));
  // ...then FREEZE the box at its resting width. `font-variation-settings` is
  // animated per frame and is ON THE LAYOUT PATH: every weight step changes
  // the word's advance and reflows the flex row, while layout() is separately
  // pushing neighbours using these resting widths. Two competing horizontal
  // displacements of the same word, every frame -- the sideways jitter. With
  // the box fixed the content overflows it symmetrically (text-align:center,
  // transform-origin 50% 100%) and layout()'s analytic shift is the only
  // horizontal motion, which is what the design comment above already claimed.
  built.forEach(line => line.nodes.forEach(n => {
    n.el.style.width = n.restW.toFixed(2) + "px";
  }));
  built.forEach(buildTracking);
  built.forEach(line => {
    line.restLineW = Math.max(1, line.div.scrollWidth);
    if (CFG.tracking.enabled)
      line.div.style.bottom = (CFG.bottom_margin_pct / 100 * h) + "px";
  });
  built.forEach(line => line.div.classList.remove("measuring"));
  rack.style.paddingBottom = CFG.tracking.enabled ? "0px"
    : (CFG.bottom_margin_pct / 100 * h) + "px";
}
// Some constants (size_pct, the deadband, quiet_deformation, the response
// curves) are resolved ONCE into each word's `_type`. Re-resolve them so the
// tuner can change those live too, not just the per-frame ones.
function retype() {
  built.forEach(line => line.nodes.forEach(n => {
    n.el._type = typeOf(n.w);
    const t = n.el._type;
    n.el._vf = '"opsz" 14, "wght" ' + t.restWght + ', "wdth" ' + t.wdth;
    n.el.style.fontVariationSettings = n.el._vf;
    n.el.style.marginLeft = "";
    n.el.style.marginRight = "";
  }));
  linkTurns();
  sizeAll();
}
linkTurns();
sizeAll();
addEventListener("resize", sizeAll);
// The variable font is embedded but still loads asynchronously, so the first
// measuring pass can land on the fallback face and record the wrong resting
// widths. Re-measure (and re-render) once the real face is in.
if (document.fonts && document.fonts.ready) {
  // Re-measure only; do NOT render out of band. An extra render outside the
  // rAF chain lands a frame at a stale `t` and, together with every restW
  // changing at once, shows as a single visible jump mid-playback.
  document.fonts.ready.then(() => { sizeAll(); if (!playing) render(); });
}

// ---------------------------------------------------------------------------
// The clock. Everything below is a pure function of `t` — scrubbing backwards
// produces exactly the same frame as playing forwards to that point.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// MEASURED MOTION. When a word carries `motion`, its lift, scale and weight
// were measured from a reference recording frame by frame and are replayed
// here verbatim; the parametric envelopes below are not evaluated for it.
//
// This is the difference between copying the reference and approximating it.
// The envelopes are one shape fitted to the MEDIAN of every glyph curve in a
// recording, so by construction they hand a word that does not move the same
// motion as one that does — which is exactly why words were lifting where the
// reference leaves them still. They remain the fallback for live and synthetic
// specs, where there is nothing to measure.
//
// Uniform grid, so this is an index and one lerp — no scan over keyframes.
// Outside the baked window every channel holds its rest value, which is what
// the renderer would use anyway.
function sampleMotion(m, ch, t, rest) {
  const a = m[ch], n = a.length;
  const f = (t - m.t0) / m.dt;
  if (!n || f < 0 || f > n - 1) return rest;
  if (f === 0) return a[0];
  if (f === n - 1) return a[n - 1];
  const i = f | 0;
  return a[i] + (a[i + 1] - a[i]) * (f - i);
}

// Emphasis envelope for one word: rises BEFORE the word is spoken (the
// template's "Antecipate" lead), peaks as it is spoken, and decays after —
// spanning roughly the word's own duration rather than a narrow ripple.
// 1. INTONATION. A word-level envelope: it begins to swell and thicken BEFORE
// the word is spoken (while the word may still be white), peaks around the
// stressed portion, holds briefly, then decays back to the common resting
// typography. Uniform across the word's letters — size and weight are never
// sent through a word letter by letter; only the synchronization wave below
// travels.
function intonationAt(t, w) {
  const span = Math.max(1e-3, w.end - w.start);
  const peak = w.start + 0.3 * span;           // near the stressed portion
  const tail = Math.max(1e-3, CFG.emphasis_tail_s);
  // The rise BEGINS `emphasis_lead_s` before the SPOKEN ONSET (not before the
  // peak) and arrives at full emphasis on the stressed portion — that is what
  // "begins expanding shortly before it is spoken" means, and anchoring the
  // lead to the peak instead left the word still at rest at its own onset.
  const from = w.start - Math.max(1e-3, CFG.emphasis_lead_s);
  if (t < peak) return ease((t - from) / Math.max(1e-3, peak - from));
  // Hold while the word is still being spoken, then decay. A long word stays
  // emphasised across its own span ("sizes," holds large for all of it);
  // decaying from the peak alone let a word shrink mid-utterance.
  const held = Math.max(peak + CFG.emphasis_hold_s, w.end);
  if (t <= held) return 1;
  return 1 - ease((t - held) / tail);
}
// 2. ANTICIPATION. The whole word dips, rises, HOLDS RAISED WHILE IT WAITS,
// and lands. Driven by the gap before the word's own first colour turn, so a
// word spoken straight after its neighbour barely moves while one held through
// a pause rises far and waits there.
//
// Measured on all three recordings: the rise peaks `wave_peak_s` AFTER the
// turn and takes 70..100 ms -- longer than fast speech's ~60 ms gap, so the
// ramp is not bounded by the gap; with a long gap the same ramp simply
// stretches, which is why "is" is already near its peak and descending by the
// time it turns. Fast speech reaches ~16% of glyph height, a held word 77%.
function wordLift(t, node) {
  const w = node.w;
  const m = node.chars.length;
  const span = Math.max(1e-3, w.end - w.start);
  // the word's own first colour turn, and when the previous word finished
  const tTurn = charSweep.checked ? w.start + 0.5 / m * span : w.start;
  const tPrev = node.prevTurn !== undefined
    ? node.prevTurn : tTurn - CFG.wave_crouch_lead_s;
  const wait = Math.min(CFG.wave_hold_max_s, Math.max(0.04, tTurn - tPrev));
  const amp = CFG.wave_lift_em *
              (CFG.wave_hold_floor + (1 - CFG.wave_hold_floor) *
               Math.min(1, wait / CFG.wave_hold_full_s));
  const dp = t - (tTurn + CFG.wave_peak_s);
  const rise = Math.max(0.04, (tTurn + CFG.wave_peak_s) - tPrev);
  if (dp < 0 && dp > -rise) {
    const u = clamp01(1 + dp / rise);
    const dip = crouch(-(1 - u) * rise, Math.max(1e-3, rise * 0.30));
    return amp * ease(u) - CFG.wave_crouch_em * dip;
  }
  if (dp >= 0 && dp < CFG.wave_release_s) {
    return amp * (1 - ease(dp / CFG.wave_release_s));
  }
  return 0;
}

// The three channels the renderer actually writes. Each takes the MEASURED
// curve when the word has one and falls back to the parametric envelope when
// it does not — the single place that choice is made, so `layout()` and the
// write path can never disagree about how large a word is.
// 2.2.3, THE SYNCHRONIZATION CUE. One envelope, identical for every word,
// centred on the moment that word changes colour: it rises, peaks just past
// the turn, and returns to rest. The design system fixes the amplitudes
// (+15% type size, 25% elevation); the recordings only supply the timing of
// the same event (rise 70-100 ms, peak +70-100 ms past the turn, fall
// 160-190 ms). Zero slope at both ends, or the motion starts and stops with a
// visible kick.
function syncAt(t, tTurn) {
  const d = t - (tTurn + CFG.sync_peak_s);
  if (d < 0) {
    const rise = Math.max(1e-3, CFG.sync_rise_s + CFG.sync_peak_s);
    return d <= -rise ? 0 : ease(1 + d / rise);
  }
  const fall = Math.max(1e-3, CFG.sync_fall_s);
  return d >= fall ? 0 : 1 - ease(d / fall);
}
// 2.2.2: "Each word should change color as soon as the sound of the word
// begins to be pronounced, not after." So the cue is anchored on the word's
// spoken onset, not on the middle of its colour sweep.
function turnOf(node) { return node.w.start; }
const REPLAY = CFG.motion_source === "measured";

function scaleOf(t, node) {
  const m = node.w.motion;
  if (REPLAY && m) return sampleMotion(m, "scale", t, 1);
  // Two scopes, composed — never collapsed. INTONATION (2.3.3-2.3.6) is the
  // word's own amplitude, from its measured loudness, and is what makes
  // "louder" enormous and "softer." small. SYNCHRONIZATION (2.2.3) is the
  // fixed +15% pop every word gets at its turn.
  const env = 1 + (node.el._type.emphScale - 1) * intonationAt(t, node.w);
  return env * (1 + CFG.sync_pop * syncAt(t, turnOf(node)));
}
function liftOf(t, node) {
  const m = node.w.motion;
  // The baked channel is in GLYPH HEIGHTS; the renderer works in em.
  if (REPLAY && m) return CFG.glyph_height_em * sampleMotion(m, "lift", t, 0);
  return CFG.sync_elevation_em * syncAt(t, turnOf(node));
}
function wghtOf(t, node, env) {
  const ty = node.el._type, m = node.w.motion;
  // Quantized to a multiple of 4 on BOTH paths, and restWght is already on
  // that grid (see typeOf), so the resting string is byte-identical wherever
  // it is produced and the setStyle cache actually holds.
  const w = (REPLAY && m) ? ty.restWght + sampleMotion(m, "dwght", t, 0)
                          : lerp(ty.restWght, ty.emphWght, env);
  return Math.round(clamp(w, EX.wght_range ? EX.wght_range[0] : 100,
                          EX.wght_range ? EX.wght_range[1] : 1000) / 4) * 4;
}

// Per-character values are written as strings; writing the same string back
// still costs a style recalc, and font-variation-settings recalcs force the
// whole line to re-lay-out. Cache and skip.
function setStyle(el, prop, key, value) {
  if (el[key] === value) return;
  el[key] = value;
  el.style[prop] = value;
  if (CHURN) CHURN.writes++;
}
// Flicker is a COUNT, not a feeling: how many style writes a frame really
// makes, and how often the set of visible lines changes. Both were being
// judged by eye, which is how twelve spurious visible-set flips over a 30 s
// demo went unnoticed through three rounds of "the flickering isn't solved".
const CHURN = CFG.debug_churn || location.search.indexOf("churn=1") >= 0
  ? {writes: 0, frames: 0, flips: 0, last: "", peak: 0} : null;
if (CHURN) {
  window.__ccChurn = {
    report() {
      return {frames: CHURN.frames,
              writesPerFrame: +(CHURN.writes / Math.max(1, CHURN.frames)).toFixed(2),
              peakWritesInAFrame: CHURN.peak,
              visibleSetFlips: CHURN.flips};
    },
    reset() { CHURN.writes = CHURN.frames = CHURN.flips = CHURN.peak = 0; },
  };
}
// Rest state for a line that is off screen (or for the calm setting). Applied
// once on the way out instead of every frame.
// Every rest string is produced HERE and nowhere else. settle() and frame()
// used to spell the same rest state two different ways -- char transform
// "translate3d(0,0,0)" against "none", and an unrounded restWght against one
// quantized to a multiple of 4 -- so the setStyle cache missed in BOTH
// directions on every visibility change, forcing a real write (and a
// compositor layer create/destroy) per letter.
function restTransform(node) { return wordTransform(0, 0, 1); }
function wordTransform(shift, lift, scale) {
  return "translate3d(" + shift.toFixed(2) + "px," + (-lift).toFixed(4)
       + "em,0) scale(" + scale.toFixed(4) + ")";
}
function varSettings(ty, wght) {
  return '"opsz" 14, "wght" ' + wght + ', "wdth" ' + ty.wdth;
}
function charColorAt(node, c, t) {
  return wordColor(node.w, ease((t - turnAt(node, c))
                   / Math.max(1e-3, CFG.color_turn_ms / 1000)));
}
function settle(line, t) {
  for (const node of line.nodes) {
    const ty = node.el._type;
    node.shift = 0;
    setStyle(node.el, "transform", "_tf", restTransform(node));
    setStyle(node.el, "fontVariationSettings", "_vf",
             varSettings(ty, ty.restWght));
    for (let ci = 0; ci < node.chars.length; ci++) {
      const c = node.chars[ci];
      // In tracking mode an outgoing line remains visible after its final
      // word; preserve whatever each character had reached at this time
      // instead of washing the whole line back to white during the handoff.
      setStyle(c, "color", "_c", charColorAt(node, ci, t));
      setStyle(c, "transform", "_tf", "none");
    }
  }
}
// A swelling word must PUSH its neighbours aside, not grow over them. Resolve
// the whole row analytically each frame and hand every word a `shift`.
//
// A word scales about its own centre, so at scale S it widens by dW = W(S-1),
// spilling dW/2 past each of its resting edges. For the row to stay tight,
// word i's rendered left edge must sit at its resting left plus everything
// that grew before it, so:
//
//     shift_i = SUM(dW_j for j < i) + dW_i/2 - SUM(all dW)/2
//
// The final term re-centres the row, so it expands symmetrically about the
// middle rather than pushing everything to the right — which is what the
// reference does as a word swells. Rows are keyed on the resting offsetTop so
// a wrapped line resolves each of its rows independently. This is pure
// arithmetic on measurements taken once, so it never touches the layout path.
function layout(t, line) {
  const rows = new Map();
  for (const node of line.nodes) {
    const s = scaleOf(t, node);
    node._dW = node.restW * (s - 1);
    if (!rows.has(node.restRow)) rows.set(node.restRow, 0);
    rows.set(node.restRow, rows.get(node.restRow) + node._dW);
  }
  const acc = new Map();
  for (const node of line.nodes) {
    const before = acc.get(node.restRow) || 0;
    node.shift = before + node._dW / 2 - rows.get(node.restRow) / 2;
    acc.set(node.restRow, before + node._dW);
  }
}
function liveAnchor(a, t) {
  return a.node.wordCentre + a.node.shift + a.dx * scaleOf(t, a.node);
}
function trackingPosition(line, t) {
  const a = line.track;
  if (!a || !a.length) return line.restLineW / 2;
  const coast = Math.max(0, CFG.tracking.coast_s)
              + Math.max(0, CFG.tracking.catch_up_s);
  if (t <= a[0].t) {
    const dt = Math.max(-coast, t - a[0].t);
    return liveAnchor(a[0], t) + a[0].slope * dt;
  }
  const z = a.length - 1;
  if (t >= a[z].t) {
    const dt = Math.min(coast, t - a[z].t);
    return liveAnchor(a[z], t) + a[z].slope * dt;
  }
  let lo = 0, hi = z;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (a[mid].t <= t) lo = mid; else hi = mid;
  }
  const p = a[lo], q = a[hi], h = Math.max(1e-6, q.t - p.t);
  const u = clamp01((t - p.t) / h);
  const y0 = liveAnchor(p, t), y1 = liveAnchor(q, t);
  if (CFG.tracking.interp !== "monotone_cubic") return lerp(y0, y1, u);
  const u2 = u * u, u3 = u2 * u;
  let y = (2*u3 - 3*u2 + 1) * y0 + (u3 - 2*u2 + u) * h * p.slope
        + (-2*u3 + 3*u2) * y1 + (u3 - u2) * h * q.slope;
  // Dynamic word scaling perturbs the precomputed resting slopes. Clamp the
  // evaluated point to its live endpoints so even a 2x swell cannot make the
  // line reverse for one frame.
  y = clamp(y, Math.min(y0, y1), Math.max(y0, y1));
  return y;
}
function handoffOffset(line, t) {
  const h = Math.max(1e-3, CFG.tracking.handoff_s);
  const width = stage.clientWidth;
  if (t < line.start)
    return CFG.tracking.enter_offset_pct / 100 * width
         * (1 - ease((t - (line.start - h)) / h));
  if (t > line.end)
    return CFG.tracking.exit_offset_pct / 100 * width
         * ease((t - line.end) / h);
  return 0;
}
function positionLine(t, line) {
  let x;
  if (trackingOn(line)) {
    x = CFG.tracking.playhead_pct / 100 * stage.clientWidth
      - trackingPosition(line, t) + handoffOffset(line, t);
  } else {
    x = (stage.clientWidth - line.restLineW) / 2;
  }
  setStyle(line.div, "transform", "_tf",
           "translate3d(" + x.toFixed(2) + "px,0,0)");
}
function frame(t) {
  const before = CHURN ? CHURN.writes : 0;
  const lead = CFG.read_ahead_s, hold = CFG.line_hold_s;
  // A line being spoken NEVER yields to one that has not started. Ranking all
  // candidates by time and keeping the last N let the next line's read-ahead
  // window (which opens `lead` seconds early) evict the line currently being
  // spoken — the caption vanished mid-sentence.
  // Strict priority: a line with a word ON SCREEN RIGHT NOW outranks one that
  // is merely lingering, which outranks one not yet spoken. Ranking purely by
  // recency let a trailing hold — or a read-ahead window — push out the line
  // actually being spoken.
  // A line is speaking across its WHOLE span, gaps between its words
  // included. Requiring `t` to fall inside a word made `speaking` empty during
  // every inter-word pause, and `visible` then fell back to `holding` — which
  // is in DOCUMENT order, so the PREVIOUS line popped back on. Measured over
  // demo.json at 60 fps: 12 spurious flips in 30 s, one lasting 17 ms, four
  // inside 550 ms. Each is a display:none <-> flex on the whole caption box.
  // That is the blink.
  const speaking = built.filter(l => t >= l.start && t <= l.end);
  const holding = built.filter(l => !speaking.includes(l) &&
    t >= l.start && t <= l.end + hold);
  const ahead = built.filter(l => t >= l.start - lead && t < l.start);
  let visible = speaking.slice(-CFG.max_lines);     // CWI 2.4.2: max boxes
  // ...and both fallback pools rank by RECENCY, for the same reason.
  for (const pool of [holding, ahead]) {
    if (visible.length >= CFG.max_lines) break;
    visible = visible.concat(pool.slice(-(CFG.max_lines - visible.length)));
  }
  if (CHURN) {
    const key = visible.map(l => built.indexOf(l)).join(",");
    if (key !== CHURN.last) { CHURN.flips++; CHURN.last = key; }
  }
  built.forEach(l => {
    const on = visible.includes(l);
    l.div.classList.toggle("on", on);
    // A line that just left the screen is settled ONCE. Previously every
    // character of every line in the file was restyled on every frame, so the
    // frame cost grew with the length of the transcript rather than with what
    // is actually on screen — the transcript-length stutter.
    if (!on && l._on) settle(l);
    l._on = on;
  });

  for (const line of visible) {
    layout(t, line);
    for (const node of line.nodes) {
      const w = node.w, chars = node.chars, n = chars.length;
      const ty = node.el._type;
      const span = Math.max(1e-3, w.end - w.start);
      const turnS = Math.max(1e-3, CFG.color_turn_ms / 1000);
      const antic = CFG.anticipation_ms / 1000;                 // Antecipate
      // Pre-turn influence window and post-turn settle. Held in TIME, so the
      // ripple travels at one rate through a two-letter word and a nine-letter
      // one; as a fraction of the word it sped up and slowed with every word.
      const live = !reduced.matches && waveOn.checked && CFG.wave_reach > 0;

      // --- 1. INTONATION: word level, uniform over every letter -------------
      const env = intonationAt(t, w);
      const wordScale = scaleOf(t, node);

      // --- 2. BASE SYNCHRONIZATION LIFT: WORD level --------------------------
      // The design-system +25% cue moves the wrapper. The website recording
      // adds a character-local hand-off below; keeping the two scopes separate
      // is what lets a word rise coherently while its alphabet still reads as
      // synchronized with the sound.
      const lift = live ? liftOf(t, node) : 0;
      // ONE format, always written. Branching to "none" below a threshold
      // promoted and demoted a compositor layer at frame rate for any word
      // hovering near it; the setStyle cache already makes an unchanged frame
      // free, so the branch bought nothing and cost repaint flashes.
      setStyle(node.el, "transform", "_tf",
               wordTransform(node.shift, lift, wordScale));
      setStyle(node.el, "fontVariationSettings", "_vf",
               varSettings(ty, wghtOf(t, node, env)));

      // --- 2/3. SYNCHRONIZATION + COLOUR: character level -------------------
      for (let c = 0; c < n; c++) {
        // The moment THIS letter turns. Character sweep spreads the turns
        // across the word's own span — the mid-word colour split visible in
        // "Roya|le with Cheese!"; word sync turns them together.
        const at = (c + 0.5) / n;
        const tTurn = charSweep.checked ? w.start + at * span : w.start;
        // When the PREVIOUS character turned. The anticipation runs from there
        // to this letter's own turn, however long that is (see below).
        const tPrev = c > 0
          ? (charSweep.checked ? w.start + ((c - 1) + 0.5) / n * span : w.start)
          : (node.prevTurn !== undefined ? node.prevTurn
                                         : w.start - CFG.wave_crouch_lead_s);
        // Soft turn: the letter crossfades over `color_turn_ms` instead of
        // flipping in a single frame.
        setStyle(chars[c], "color", "_c",
                 wordColor(w, ease((t - tTurn) / turnS)));
        // WEBSITE SYNCHRONIZATION: unlike the word-wide intonation envelope,
        // the baseline/pop hand-off visibly lands between letters in
        // synchronization.mov. The first letter may have waited through an
        // inter-word pause; later letters inherit their local turn spacing.
        // This preserves the large split visible on a held two-letter word
        // without forcing that amplitude onto every fast character.
        const wait = Math.min(
          CFG.wave_hold_max_s,
          Math.max(0.04, tTurn - tPrev)
        );
        const waitGain = CFG.wave_hold_floor +
          (1 - CFG.wave_hold_floor) *
          Math.min(1, wait / Math.max(1e-3, CFG.wave_hold_full_s));
        const d = t - tTurn;
        let chLift = 0, chScale = 1;
        if (live) {
          chLift = CFG.wave_reach * (
            CFG.wave_lift_em * waitGain *
              pulse(d, CFG.wave_release_s, CFG.wave_peak_s) -
            CFG.wave_crouch_em *
              crouch(d, CFG.wave_crouch_lead_s)
          );
          chScale = 1 + CFG.wave_reach * (
            CFG.wave_pop * pulse(d, CFG.pop_release_s, CFG.pop_peak_s) -
            CFG.wave_dip * crouch(d, CFG.wave_crouch_lead_s)
          );
        }
        setStyle(chars[c], "transform", "_tf",
                 Math.abs(chLift) > 0.00005 ||
                 Math.abs(chScale - 1) > 0.00005
                   ? "translate3d(0," + (-chLift).toFixed(4) +
                     "em,0) scale(" + chScale.toFixed(4) + ")"
                   : "none");                       // matches settle()
      }
    }
  }
  if (CHURN) {
    CHURN.frames++;
    CHURN.peak = Math.max(CHURN.peak, CHURN.writes - before);
  }
}
// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------
const playBtn = document.getElementById("play");
const scrub = document.getElementById("scrub");
const clock = document.getElementById("clock");
const rate = document.getElementById("rate");
let t = 0, playing = false, last = 0;
scrub.max = CFG.duration;

function render() {
  frame(t);
  scrub.value = t;
  clock.textContent = t.toFixed(2) + " / " + CFG.duration.toFixed(2);
}
function tick(now) {
  if (!playing) return;
  // When media is attached the video's own clock is the authority — a
  // separately accumulated clock drifts away from the audio over a few minutes
  // and the captions stop landing on the words.
  if (video.src && !video.paused) {
    t = Math.min(CFG.duration, video.currentTime);
    last = now;
  } else {
    // Capped: after a stall (tab hidden, GC pause) an uncapped delta jumps the
    // clock by the whole gap, skipping every word in between in one frame.
    const dt = Math.min(0.1, (now - last) / 1000) * parseFloat(rate.value);
    last = now;
    t = Math.min(CFG.duration, t + dt);
  }
  render();
  if (t >= CFG.duration) { playing = false; playBtn.textContent = "Play"; return; }
  requestAnimationFrame(tick);
}
playBtn.onclick = () => {
  playing = !playing;
  playBtn.textContent = playing ? "Pause" : "Play";
  if (video.src) { playing ? video.play() : video.pause(); }
  if (playing) { last = performance.now(); requestAnimationFrame(tick); }
};
scrub.oninput = () => { t = parseFloat(scrub.value); if (video.src) video.currentTime = t; render(); };
rate.onchange = () => { if (video.src) video.playbackRate = parseFloat(rate.value); };
charSweep.onchange = waveOn.onchange = render;
addEventListener("keydown", e => {
  if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
  if (e.code === "ArrowRight") { t = Math.min(CFG.duration, t + 0.1); render(); }
  if (e.code === "ArrowLeft") { t = Math.max(0, t - 0.1); render(); }
});
if (MEDIA) { video.src = MEDIA; } else { video.style.display = "none"; }
render();

// `#t=12.34` seeks and renders SYNCHRONOUSLY, then flags the page ready. This
// is how the comparison harness captures a frame: headless Chrome fires
// --screenshot once per launch and does not run rAF reliably, so playback
// cannot be used. `data-ready` goes up only after the embedded font has
// actually loaded, because a shot taken on the fallback face measures the
// wrong glyph widths.
function seekHash() {
  const m = /(?:^|[#&])t=(-?[\d.]+)/.exec(location.hash);
  if (!m) return;
  t = Math.max(0, Math.min(CFG.duration, parseFloat(m[1])));
  playing = false;
  render();
}
addEventListener("hashchange", seekHash);
seekHash();
const ready = () => {
  sizeAll(); seekHash(); render();
  document.documentElement.setAttribute("data-ready", "1");
};
if (document.fonts && document.fonts.ready) document.fonts.ready.then(ready);
else ready();
</script>
</body>
</html>
''')
