"""Generate the self-contained live CWI caption studio.

The primary stage is backed by SSE at ``/events``. Streaming hypotheses are
white CWI read-ahead words and can revise in place; stable word events flip to
the speaker color and drive the Attribution, Synchronization, and Intonation
visualizations beside the stage. Roboto Flex is embedded, so the page stays
fully local and makes no browser network requests beyond its own SSE stream.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from string import Template

_REPO_ROOT = Path(__file__).resolve().parent.parent


def render_live(config: dict, out_dir: str | Path) -> str:
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
    page_cfg = {
        "mapping": config["mapping"],
        "palette": palette,
        "box_opacity": box["opacity"],
        "bottom_margin_pct": box["bottom_margin_pct"],
        "motion_elevation_em": motion.get("elevation_em", 0.25),
        "motion_anticipation_ms": motion.get("anticipation_ms", 33),
        "motion_neighbor_bleed": motion.get("neighbor_bleed", 0.34),
        "motion_color_turn_ms": motion.get("color_turn_ms", 90),
        "motion_duration_ms": round(motion.get("duration_s", 0.56) * 1000),
        "motion_min_duration_ms": round(motion.get("min_duration_s", 0.42) * 1000),
        "motion_max_duration_ms": round(motion.get("max_duration_s", 0.90) * 1000),
        "motion_easing": motion.get("easing", "ease-in-out"),
        "expression": config["expression"],
        "min_voiced_frac": config["normalization"]["min_voiced_frac"],
        "display_mode": display.get("mode", "stable"),
        "display_align": display.get("align", "left"),
        "display_retention": display.get("retention", "overflow"),
        "intent_circle": display.get("intent_circle", True),
        "line_break_gap_s": display.get("line_break_gap_s", 2.0),
        "max_words": display.get("max_words", 8),
        "max_lines": box.get("max_lines", 2),
        "line_linger_s": display.get("line_linger_s", 9.0),
        "sentence_stagger_ms": round(display.get("sentence_stagger_s", 0.7) * 1000),
        "debug_churn": display.get("debug_churn", False),
    }

    html = _TEMPLATE.safe_substitute(
        FONT_B64=font_b64,
        CFG_JSON=json.dumps(page_cfg),
    )
    out = out_dir / "live.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


_TEMPLATE = Template(r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Captioned with intent — local live captions</title>
<style>
  @font-face {
    font-family: "Roboto Flex VF";
    src: url(data:font/ttf;base64,$FONT_B64) format("truetype-variations");
    font-weight: 100 1000;
    font-stretch: 25% 151%;
  }
  :root {
    color-scheme: dark;
    --ink: #f4f2ea;
    --muted: #85858d;
    --panel: #121216;
    --line: rgba(255,255,255,.12);
    --yellow: #e5e517;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; background: #08080a; color: var(--ink); }
  body {
    font-family: "Roboto Flex VF", "Apple SD Gothic Neo", sans-serif;
    overflow: hidden;
  }
  button { font: inherit; }
  .skip {
    position: fixed; left: 16px; top: -60px; z-index: 10; padding: 10px 14px;
    background: var(--ink); color: #08080a; text-decoration: none;
  }
  .skip:focus { top: 12px; }
  .shell { height: 100vh; min-height: 620px; display: grid; grid-template-rows: 76px 1fr 42px; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 26px; border-bottom: 1px solid var(--line); background: #0a0a0c;
  }
  .brand { display: flex; align-items: center; gap: 13px; }
  .mark {
    width: 34px; aspect-ratio: 1; border: 1px solid #66666c; border-radius: 50%;
    display: grid; place-items: center; font-size: 10px; letter-spacing: -.04em;
  }
  .brand-copy strong { display: block; font-size: 15px; font-weight: 570; letter-spacing: -.02em; }
  .brand-copy span { color: var(--muted); font-size: 10px; letter-spacing: .16em; text-transform: uppercase; }
  .header-meta { display: flex; gap: 10px; align-items: center; }
  .pill {
    border: 1px solid var(--line); border-radius: 999px; padding: 7px 11px;
    font-size: 10px; letter-spacing: .11em; text-transform: uppercase; color: #aaaab1;
  }
  #status { display: flex; align-items: center; gap: 7px; }
  #status .dot { width: 7px; height: 7px; border-radius: 50%; background: #6a6a70; }
  #status.on .dot { background: #4de071; box-shadow: 0 0 12px rgba(77,224,113,.55); }

  main { min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 340px; }
  .stage-wrap { position: relative; min-width: 0; padding: 18px; }
  #stage {
    position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden;
    display: flex; flex-direction: column; justify-content: flex-end; align-items: center;
    /* The captions box is 90% black (2.4.1). On a PURE black stage the boxes
       disappear entirely (verified by screenshot) — a barely-lighter flat
       tone stands in for dim video so the boxes read as boxes again. */
    background: #101014;
    border: 1px solid var(--line); border-radius: 3px;
  }
  #stage:before {
    content: ""; position: absolute; inset: 5% 4% 7.5%; pointer-events: none;
    border: 1px solid rgba(255,255,255,.055);
  }
  .stage-label {
    position: absolute; left: 18px; top: 15px; display: flex; align-items: center; gap: 8px;
    color: #777780; font-size: 9px; letter-spacing: .14em; text-transform: uppercase;
  }
  .stage-label:before { content: ""; width: 18px; border-top: 1px solid #5d5d65; }
  #hint {
    position: absolute; inset: 0; display: grid; place-content: center; text-align: center;
    color: #55555e; transition: opacity .5s ease; pointer-events: none;
  }
  #hint strong { color: #777780; font-size: clamp(18px, 2vw, 30px); font-weight: 420; }
  #hint span { margin-top: 8px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; }
  #captionRack {
    width: 100%; display: flex; flex-direction: column; align-items: center;
    position: relative; z-index: 2; padding-inline: 2%;
  }
  .cwi-line {
    /* Wrapping is the structural guarantee against horizontal overflow.
       Verification can ENLARGE a word after it was placed (settle() re-applies
       typography), so no insertion-time width check can be sufficient — words
       ran off the stage mid-word until the box was allowed to wrap. */
    display: flex; align-items: baseline; flex-wrap: wrap; white-space: normal;
    max-width: 96%;
    min-height: 1.3em; padding: .18em .52em; margin-top: .15em;
    background: rgba(0,0,0,.9); transition: opacity .35s ease;
  }
  .cwi-line.gone { opacity: 0; }
  .cwi-word {
    line-height: 1.05; display: inline-block;
    font-optical-sizing: none; font-synthesis: none; text-rendering: geometricPrecision;
    font-kerning: normal; font-variant-ligatures: none;
    /* The AE template eases fill color through the same range selector that
       drives the lift, so the read-ahead turn is a fast blend, not a hard cut.
       Size and the variable-font axes ease for the same reason: nothing in CWI
       cuts, and a revision that resizes a word must not snap the line. */
    transition:
      color var(--turn, 90ms) linear,
      font-size var(--type-ms, 190ms) cubic-bezier(.4, 0, .2, 1),
      font-variation-settings var(--type-ms, 190ms) cubic-bezier(.4, 0, .2, 1);
  }
  .cwi-word.partial { color: rgba(255,255,255,.9); }
  .cwi-glyph {
    display: inline-block; color: inherit; transform: translate3d(0,0,0);
    transform-origin: 50% 100%; will-change: transform; backface-visibility: hidden;
  }
  /* Real-time intention indicator: one circle closes each caption line. On the
     active line it pulses with the live voice level (driven by `level` SSE
     events, so it moves before words land); on finished lines it freezes as a
     record of how that line was delivered. */
  .intent-circle {
    display: inline-block; flex: 0 0 auto; border-radius: 50%;
    margin-left: .23em; align-self: center;
    background: var(--c, #e5e517); opacity: .3;
    transform: scale(.7); transform-origin: 50% 50%;
    transition: transform 100ms linear, opacity .25s ease;
  }
  /* CWI 2.2.4 syllable variation: the colour turn advances through a drawn-out
     word rather than flipping it at once. The glyph is already fully visible in
     white — only the fill moves, so read-ahead (2.2.1) is untouched. --fill is
     driven from JS, so no @property registration is needed. */
  .cwi-glyph.syllabic {
    --fill: 0%;
    background-image: linear-gradient(90deg,
      var(--spoken) 0 var(--fill), var(--unspoken) var(--fill) 100%);
    -webkit-background-clip: text; background-clip: text;
    color: transparent; -webkit-text-fill-color: transparent;
  }

  aside {
    min-height: 0; border-left: 1px solid var(--line); background: #0b0b0e;
    padding: 18px; overflow: auto;
  }
  .eyebrow { color: #6f6f77; font-size: 9px; letter-spacing: .17em; text-transform: uppercase; }
  aside h1 { margin: 9px 0 4px; max-width: 280px; font-size: 27px; line-height: .96; font-weight: 490; letter-spacing: -.045em; }
  .dek { margin: 10px 0 18px; color: #8f8f96; font-size: 11px; line-height: 1.45; }
  .system-card { border-top: 1px solid var(--line); padding: 15px 0 17px; }
  .card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .card-head h2 { margin: 0; font-size: 10px; letter-spacing: .14em; font-weight: 560; }
  .card-head span { color: #6f6f76; font-size: 9px; text-align: right; }

  .voice { display: grid; grid-template-columns: 46px 1fr; align-items: center; gap: 12px; margin-top: 13px; }
  #voiceSwatch {
    width: 46px; aspect-ratio: 1; border-radius: 50%; background: var(--yellow);
    box-shadow: 0 0 26px rgba(229,229,23,.13); position: relative;
  }
  #voiceSwatch:after { content: "01"; color: #080808; position: absolute; inset: 0; display: grid; place-items: center; font-size: 10px; }
  .voice strong { font-size: 13px; font-weight: 520; }
  .voice p { margin: 3px 0 0; color: #777780; font-size: 10px; }
  .palette { display: flex; gap: 4px; margin-top: 12px; }
  .palette i { height: 4px; flex: 1; background: var(--c); opacity: .28; transition: opacity .2s, transform .2s; }
  .palette i.active { opacity: 1; transform: scaleY(1.8); }

  .sync-stage { margin-top: 13px; position: relative; padding: 14px 0 10px; }
  .sync-stage:before { content: ""; position: absolute; left: 72%; top: 5px; bottom: 3px; border-left: 1px solid var(--yellow); z-index: 2; }
  .sync-stage:after { content: "now"; position: absolute; left: calc(72% - 9px); top: -7px; color: var(--yellow); font-size: 7px; text-transform: uppercase; }
  #syncTokens { height: 42px; display: flex; gap: 3px; align-items: end; overflow: hidden; }
  .sync-token {
    min-width: 16px; flex: var(--duration) 0 0; max-width: 72px; height: 20px;
    border-top: 2px solid var(--color); background: color-mix(in srgb, var(--color) 15%, transparent);
    color: #8e8e95; font-size: 7px; overflow: hidden; padding: 4px 3px 0; text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sync-token.partial { --color: rgba(255,255,255,.72) !important; border-top-style: dashed; }
  .sync-token.cued { border-top-style: solid; color: #d5d5da; }
  .sync-legend { display: flex; gap: 13px; color: #6f6f76; font-size: 8px; }
  .sync-legend i { display: inline-block; width: 13px; border-top: 2px solid; margin-right: 5px; vertical-align: 2px; }
  .sync-legend .read i { border-top-style: dashed; color: rgba(255,255,255,.72); }
  .sync-legend .spoken i { color: var(--yellow); }

  .intonation { display: grid; grid-template-columns: 75px 1fr; gap: 14px; align-items: center; margin-top: 13px; }
  #typeSample {
    height: 75px; display: grid; place-items: center; border: 1px solid var(--line);
    font-size: 35px; line-height: 1; color: var(--yellow); font-variation-settings: "opsz" 14, "wght" 400;
    transition: font-size .2s ease, font-variation-settings .2s ease;
  }
  .level-bar {
    position: relative; height: 6px; background: #27272d; overflow: hidden; margin-top: 12px;
  }
  .level-bar i { display: block; width: 0; height: 100%; background: #4de071; transition: width .1s linear; }
  .level-bar u {
    position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(255,255,255,.45);
    transition: left .4s ease;
  }
  .level-meta { display: flex; justify-content: space-between; margin-top: 7px; color: #777780; font-size: 9px; }
  #inputCard[data-status="too-quiet"] .level-bar i { background: #e5a017; }
  #inputCard[data-status="clipping"] .level-bar i { background: #e51717; }
  #inputCard[data-status="no-signal"] .level-bar i,
  #inputCard[data-status="idle"] .level-bar i { background: #4a4a52; }
  #inputCard[data-status="too-quiet"] #inputStatus { color: #e5a017; }
  #inputCard[data-status="clipping"] #inputStatus { color: #e51717; }
  #inputCard[data-status="good"] #inputStatus { color: #4de071; }
  .level-scale { display: flex; justify-content: space-between; margin-top: 4px; color: #55555e; font-size: 7px; }

  .meters { display: grid; gap: 10px; }
  .meter-row label { display: flex; justify-content: space-between; color: #777780; font-size: 8px; margin-bottom: 5px; text-transform: uppercase; letter-spacing: .09em; }
  .meter { height: 3px; background: #27272d; overflow: hidden; }
  .meter i { display: block; width: 0; height: 100%; background: var(--yellow); transition: width .2s ease; }
  .confidence { margin-top: 12px; display: flex; justify-content: space-between; color: #686870; font-size: 9px; }
  #revisionState { color: #b1b1b6; }
  #revisionState.live { color: #fff; }

  footer {
    display: flex; align-items: center; justify-content: space-between; padding: 0 26px;
    border-top: 1px solid var(--line); color: #66666e; font-size: 9px;
    letter-spacing: .08em; text-transform: uppercase;
  }
  .privacy { color: #929299; }

  @media (max-width: 900px) {
    .shell { min-height: 680px; grid-template-rows: 64px 1fr 34px; }
    main { grid-template-columns: 1fr; grid-template-rows: minmax(340px, 58vh) 1fr; overflow: auto; }
    body { overflow: auto; }
    .stage-wrap { padding: 10px; }
    aside { border-left: 0; border-top: 1px solid var(--line); overflow: visible; display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
    aside > .eyebrow, aside > h1, aside > .dek { grid-column: 1 / -1; }
    .system-card { min-width: 0; }
  }
  @media (max-width: 640px) {
    .header-meta .pill:first-child { display: none; }
    header, footer { padding-inline: 14px; }
    aside { display: block; }
    aside h1 { font-size: 24px; }
    .cwi-line { max-width: 98%; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *:before, *:after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
  }
</style>
</head>
<body>
<a class="skip" href="#captionRack">Skip to live captions</a>
<div class="shell">
  <header>
    <div class="brand">
      <div class="mark" aria-hidden="true">CWI</div>
      <div class="brand-copy"><strong>Captioned with intent</strong><span>Local expressive speech</span></div>
    </div>
    <div class="header-meta">
      <span class="pill">100% offline</span>
      <span class="pill" id="status"><i class="dot"></i><span id="statusText">connecting</span></span>
    </div>
  </header>

  <main>
    <section class="stage-wrap" aria-label="Live caption stage">
      <div id="stage">
        <div class="stage-label">Live frame · lower work area</div>
        <div id="hint"><strong>Speak naturally.</strong><span>Words will appear while you talk</span></div>
        <div id="captionRack" aria-live="polite" aria-atomic="false"></div>
      </div>
    </section>

    <aside aria-label="Caption design system visualizations">
      <div class="eyebrow">Live design system</div>
      <h1>See how speech becomes intent.</h1>
      <p class="dek">Each locked word updates the three visual signals used by the caption stage.</p>

      <section class="system-card" id="inputCard" data-status="no-signal">
        <div class="card-head"><h2>INPUT</h2><span id="inputStatus">no signal</span></div>
        <div class="level-bar"><i id="levelFill"></i><u id="levelFloor" title="noise floor"></u></div>
        <div class="level-scale"><span>-72</span><span>-48</span><span>-24</span><span>0 dBFS</span></div>
        <div class="level-meta"><span id="levelDb">— dBFS</span><span id="levelGain">+0.0 dB to ASR</span></div>
      </section>

      <section class="system-card" id="attributionCard">
        <div class="card-head"><h2>ATTRIBUTION</h2><span>Who is speaking</span></div>
        <div class="voice"><div id="voiceSwatch"></div><div><strong id="speakerName">Speaker 01</strong><p>Persistent character color</p></div></div>
        <div class="palette" id="palette" aria-label="CWI character palette"></div>
      </section>

      <section class="system-card" id="synchronizationCard">
        <div class="card-head"><h2>SYNCHRONIZATION</h2><span>When each word begins</span></div>
        <div class="sync-stage"><div id="syncTokens"></div></div>
        <div class="sync-legend"><span class="read"><i></i>read-ahead</span><span class="spoken"><i></i>spoken</span></div>
      </section>

      <section class="system-card" id="intonationCard">
        <div class="card-head"><h2>INTONATION</h2><span>How it is delivered</span></div>
        <div class="intonation">
          <div id="typeSample">Aa</div>
          <div class="meters">
            <div class="meter-row"><label><span>Volume / size</span><b id="dbValue">— dB</b></label><div class="meter"><i id="volumeMeter"></i></div></div>
            <div class="meter-row"><label><span>Pitch / weight</span><b id="hzValue">— Hz</b></label><div class="meter"><i id="pitchMeter"></i></div></div>
          </div>
        </div>
        <div class="confidence"><span id="confidenceValue">Waiting for speech</span><span id="revisionState">revisable words in white</span></div>
      </section>
    </aside>
  </main>

  <footer><span class="privacy">No cloud · no telemetry · audio stays here</span><span>Roboto Flex · CWI v1.0</span></footer>
</div>

<script id="cfg" type="application/json">$CFG_JSON</script>
<script>
"use strict";
const CFG = JSON.parse(document.getElementById("cfg").textContent);
const M = CFG.mapping;
const stage = document.getElementById("stage");
const rack = document.getElementById("captionRack");
const hint = document.getElementById("hint");
const paletteEl = document.getElementById("palette");
const syncTokens = document.getElementById("syncTokens");
const revisionState = document.getElementById("revisionState");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const cuedSlots = new Set();

document.documentElement.style.setProperty("--turn", CFG.motion_color_turn_ms + "ms");
document.documentElement.style.setProperty("--type-ms", CFG.expression.transition_ms + "ms");
// Lines accumulate and are pushed off the top when they no longer fit,
// terminal-style, instead of fading on a timer.
const OVERFLOW_RETAIN = CFG.display_retention === "overflow";
const INTENT_CIRCLE = CFG.intent_circle !== false;
if (CFG.display_align === "left") {
  rack.style.alignItems = "flex-start";
  rack.style.paddingInline = "4%";
}

function lerp(a, b, f) { return a + (b - a) * f; }
function clamp01(f) { return Math.min(1, Math.max(0, f)); }
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

// Input level is reported continuously and independently of recognition, so a
// microphone that is too quiet to produce any words is still visible as one.
const INPUT_LABEL = {
  "no-signal": "no signal",
  "idle": "room tone",
  "good": "good",
  "too-quiet": "too quiet",
  "clipping": "clipping"
};
const inputCard = document.getElementById("inputCard");
function updateInputLevel(ev) {
  const pct = db => (clamp01((db + 72) / 72) * 100).toFixed(1) + "%";
  document.getElementById("levelFill").style.width = pct(ev.rms_db);
  document.getElementById("levelFloor").style.left = pct(ev.floor_db);
  document.getElementById("levelDb").textContent = ev.rms_db.toFixed(1) + " dBFS";
  document.getElementById("levelGain").textContent =
    (ev.gain_db > 0 ? "+" : "") + ev.gain_db.toFixed(1) + " dB to ASR";
  inputCard.dataset.status = ev.status;
  document.getElementById("inputStatus").textContent =
    INPUT_LABEL[ev.status] || ev.status;
}
function escTitle(ev) { return ev.loudness_db + " dB · " + ev.pitch_hz + " Hz · " + Math.round(ev.conf * 100) + "%"; }

// The active line's circle pulses with the live voice: `level` events arrive
// several times a second regardless of recognition, so the intention shows
// before its words do. It reads the TRUE captured level (rms_db), not the
// gained recognizer copy, for the same honesty reason type size does.
function updateIntentCircle(ev) {
  if (!current || !current.circle) return;
  const f = clamp01((ev.rms_db + 60) / 45);   // -60 dBFS silence .. -15 shout
  current.circle.style.transform = "scale(" + (0.6 + f * 1.6).toFixed(2) + ")";
  current.circle.style.opacity = ev.speech ? "1" : ".3";
}

const speakerColor = {};
function colorFor(spk) {
  if (!(spk in speakerColor)) speakerColor[spk] = CFG.palette[Object.keys(speakerColor).length % CFG.palette.length];
  return speakerColor[spk];
}
CFG.palette.slice(0, 6).forEach((color, i) => {
  const bar = document.createElement("i");
  bar.style.setProperty("--c", color);
  if (i === 0) bar.className = "active";
  paletteEl.appendChild(bar);
});

// CWI's absolute anchors describe deliberate dynamics. Per-word acoustics of a
// single speaker deviate far more than the speaker's intent does, so each axis
// is pulled back toward that speaker's own running baseline. See `expression`
// in config.yaml for the measurements this exists to fix.
const EX = CFG.expression;
const pitchHistory = [];
function notePitch(ev) {
  if (!(ev.pitch_hz > 0) || ev.voiced_frac < CFG.min_voiced_frac) return;
  pitchHistory.push(ev.pitch_hz);
  if (pitchHistory.length > EX.baseline_words) pitchHistory.shift();
}
function baselinePitch() {
  if (!pitchHistory.length) return null;
  const sorted = pitchHistory.slice().sort((a, b) => a - b);
  return sorted[sorted.length >> 1];
}
// Compress deviation near the baseline but keep the ends of the scale
// reachable. Scaling deviation linearly by `response` also shrinks the
// extremes, so a genuine whisper could never reach 3% however quietly it was
// spoken. A power curve flattens ordinary variation and still maps a true
// extreme onto a true extreme. response 1.0 is the literal CWI mapping.
function towardBaseline(value, baseline, response, min, max) {
  const extent = value >= baseline ? max - baseline : baseline - min;
  if (!(extent > 0)) return baseline;
  const d = clamp((value - baseline) / extent, -1, 1);
  const gamma = response > 0 ? 1 / response : 1;
  return baseline + Math.sign(d) * Math.pow(Math.abs(d), gamma) * extent;
}
function pitchAxis(m, hz) {
  const domain = m.domain_hz || (M.pitch_to && M.pitch_to.domain_hz);
  let f = clamp01((hz - domain[0]) / (domain[1] - domain[0]));
  if (m.invert) f = 1 - f;
  return lerp(m.min, m.max, f);
}
// Each word used to be resolved from its own measurement alone, so the type
// re-decided on every word and never settled. The axes now carry state: a new
// measurement moves the running value part-way (EMA), and the result is held on
// a discrete step until it crosses a boundary by more than `hysteresis`. Type
// therefore holds steady through a passage and changes only when delivery
// actually shifts — which is also how hand-authored CWI reads.
function slotKey(ev) {
  return ev.speaker + "|" + Math.round(ev.t * 20);
}
// A running median, not a moving average. An average lets one emphatic word
// drag the running value up and then decay slowly, so a single loud word
// resized the following half-dozen. A median ignores an isolated outlier
// completely while still following a sustained change in delivery.
function runningMedian(buffer, value, window) {
  buffer.push(value);
  if (buffer.length > window) buffer.shift();
  const sorted = buffer.slice().sort((a, b) => a - b);
  return sorted[sorted.length >> 1];
}
function stepsFor(min, max, step) {
  if (!(step > 0)) return null;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  if (!out.length || out[0] > min) out.unshift(min);
  if (out[out.length - 1] < max) out.push(max);
  return out;
}
// Move at most one level per word, and only once the value has passed the
// boundary with the ADJACENT level by `hysteresis` of the gap. Measuring
// against the nearest level instead would let a large jump skip levels, and
// measuring against a distant level makes the last step unreachable; the
// margin is what stops a value resting on a boundary from oscillating.
function snapIndex(steps, value, previousIndex, hysteresis) {
  if (previousIndex === undefined) {
    let index = 0, best = Infinity;
    steps.forEach((s, i) => {
      const d = Math.abs(s - value);
      if (d < best) { best = d; index = i; }
    });
    return index;
  }
  const up = previousIndex + 1, down = previousIndex - 1;
  if (up < steps.length) {
    const gap = steps[up] - steps[previousIndex];
    if (value >= (steps[previousIndex] + steps[up]) / 2 + gap * hysteresis) return up;
  }
  if (down >= 0) {
    const gap = steps[previousIndex] - steps[down];
    if (value <= (steps[previousIndex] + steps[down]) / 2 - gap * hysteresis) return down;
  }
  return previousIndex;
}
const SIZE_STEPS = EX.size_steps && EX.size_steps.length ? EX.size_steps : null;
const WGHT_STEPS = stepsFor(M.pitch_to.min, M.pitch_to.max, EX.weight_step);
const WDTH_STEPS = M.harmonics_to
  ? stepsFor(M.harmonics_to.min, M.harmonics_to.max, EX.width_step) : null;

// Resolve a value against the current smoothing state without advancing it.
// Tentative read-ahead words (many of which are deleted moments later) and the
// sidebar readout must not get a vote in the running median.
function project(state, key, target, min, max, steps, initial) {
  const buffer = (state[key + "Buf"] || []).slice();
  const smoothed = runningMedian(buffer, clamp(target, min, max),
                                 EX.smoothing_words);
  if (!steps) return smoothed;
  let index = state[key + "Step"];
  if (index === undefined) {
    index = snapIndex(steps, initial === undefined ? smoothed : initial,
                      undefined, EX.hysteresis);
  }
  return steps[index];
}
function fold(state, key, target, min, max, steps, initial) {
  const buffer = state[key + "Buf"] || (state[key + "Buf"] = []);
  const smoothed = runningMedian(buffer, clamp(target, min, max),
                                 EX.smoothing_words);
  state[key] = smoothed;
  if (!steps) return smoothed;
  let index = state[key + "Step"];
  if (index === undefined) {
    // Open at the neutral level rather than wherever the first word happened
    // to land, or every utterance starts on an arbitrary size and then settles.
    index = snapIndex(steps, initial === undefined ? smoothed : initial,
                      undefined, EX.hysteresis);
  } else if (buffer.length >= EX.smoothing_words) {
    // A partly-filled window biases the median, so judging a change before
    // there is a full window to judge it by makes the opening words oscillate.
    index = snapIndex(steps, smoothed, index, EX.hysteresis);
  }
  state[key + "Step"] = index;
  return steps[index];
}
const expressionState = {};
const typeCache = new Map();
// Resolved once per word slot. Hypothesis revisions re-render the same word
// repeatedly; without this the state would advance several times per word and
// the smoothing would be meaningless.
function expressionFor(ev, advance) {
  // One audio stream, one typography state. Keying state by speaker made
  // adjacent words compute from different smoothing states once diarization
  // relabels landed — the within-line size ping-pong. Cache by time slot so
  // a speaker relabel cannot re-derive different geometry for the same word.
  // A slot resolves exactly once and then stays fixed forever.
  // FIRST WRITE WINS. The old graded cache re-resolved a word at verification,
  // which both resized it on screen AND pushed the same word into the running
  // median a second time — corrupting the size of every word after it.
  const key = Math.round(ev.t * 20);
  const cached = typeCache.get(key);
  if (cached) return cached;
  const state = expressionState.global || (expressionState.global = {});
  const sizeMap = M.loudness_to;
  const f = sizeMap.invert ? 1 - ev.loudness : ev.loudness;
  const rawSize = lerp(sizeMap.min, sizeMap.max, clamp01(f));
  const step = advance === false ? project : fold;
  const pct = step(state, "size",
                   towardBaseline(rawSize, sizeMap.baseline, EX.size_response,
                                  sizeMap.min, sizeMap.max),
                   sizeMap.min, sizeMap.max, SIZE_STEPS, sizeMap.baseline);

  const voiced = ev.pitch_hz > 0 && ev.voiced_frac >= CFG.min_voiced_frac;
  // An unvoiced word holds the speaker's baseline instead of snapping to
  // Regular: for a deep voice already sitting near wght 950, a drop to 400
  // mid-line reads as a different speaker rather than a quieter word.
  // Before any history exists the word anchors to itself, so an utterance
  // does not open on a default weight and then jump to the speaker's.
  const base = baselinePitch() ?? (ev.pitch_hz > 0 ? ev.pitch_hz : null);
  const wm = M.pitch_to;
  // Live legibility clamp (documented deviation from the absolute CWI
  // anchors): the speaker's RESTING weight/width stay in a readable band;
  // deviations from it still reach the full range.
  const wBand = EX.anchor_wght || [350, 700];
  const wAnchor = clamp(base === null ? 400 : pitchAxis(wm, base),
                        wBand[0], wBand[1]);
  const wTarget = voiced
    ? towardBaseline(pitchAxis(wm, ev.pitch_hz), wAnchor, EX.weight_response,
                     wm.min, wm.max)
    : wAnchor;
  // Bound the RENDERED weight, not just the anchor. The response curve leaves
  // values sitting exactly at the pitch-domain edge uncompressed, so a very
  // high voice rendered at wght 100 (hairline) beside normal text.
  const wRange = EX.wght_range || [wm.min, wm.max];
  const wght = Math.round(clamp(step(state, "wght", wTarget, wm.min, wm.max,
                              WGHT_STEPS, wAnchor), wRange[0], wRange[1]));

  let wdth = 100;
  if (M.harmonics_to) {
    const hm = M.harmonics_to;
    const hBand = EX.anchor_wdth || [88, 112];
    const hAnchor = clamp(base === null ? 100 : pitchAxis(hm, base),
                          hBand[0], hBand[1]);
    const hTarget = voiced
      ? towardBaseline(pitchAxis(hm, ev.pitch_hz), hAnchor, EX.width_response,
                       hm.min, hm.max)
      : hAnchor;
    const hRange = EX.wdth_range || [hm.min, hm.max];
    wdth = Math.round(clamp(step(state, "wdth", hTarget, hm.min, hm.max,
                           WDTH_STEPS, hAnchor), hRange[0], hRange[1]));
  }

  const resolved = {pct: pct, wght: wght, wdth: wdth};
  typeCache.set(key, resolved);
  if (typeCache.size > 400) typeCache.delete(typeCache.keys().next().value);
  return resolved;
}
function sizePx(ev) {
  return expressionFor(ev).pct / 100 * stage.clientHeight;
}
function weight(ev) { return expressionFor(ev).wght; }
function widthAxis(ev) { return expressionFor(ev).wdth; }
function applyTypography(el, ev, advance) {
  const type = expressionFor(ev, advance);
  // Frozen on the node: a painted word is never re-resolved, so verification
  // cannot resize it and a resize only rescales what was already decided.
  el._type = type;
  el.style.fontSize = (type.pct / 100 * stage.clientHeight).toFixed(1) + "px";
  el.style.fontVariationSettings = '"opsz" 14, "wght" ' + type.wght +
    ', "wdth" ' + type.wdth;
}
function motionDuration(ev) {
  const spoken = ev ? Math.max(0, ev.end - ev.start) * 1000 : 0;
  const requested = spoken > 0 ? spoken : CFG.motion_duration_ms;
  return Math.min(CFG.motion_max_duration_ms,
    Math.max(CFG.motion_min_duration_ms, requested));
}
// The official AE template animates Position and Fill Color only — there is no
// scale animator in it. Type size already carries loudness, so lifting the word
// is the channel that stays free to guide the eye.
function playLift(el, ev, amplitude, durationScale) {
  const glyph = el && el.querySelector(".cwi-glyph");
  if (!glyph || reducedMotion.matches || !(amplitude > 0)) return;
  if (glyph._liftAnimation) glyph._liftAnimation.cancel();
  const peak = "translate3d(0,-" +
    (CFG.motion_elevation_em * amplitude).toFixed(4) + "em,0)";
  glyph._liftAnimation = glyph.animate([
    {transform: "translate3d(0,0,0)", offset: 0, easing: CFG.motion_easing},
    {transform: peak, offset: .28, easing: "linear"},
    {transform: peak, offset: .55, easing: "cubic-bezier(.4,0,.2,1)"},
    {transform: "translate3d(0,0,0)", offset: 1}
  ], {
    duration: motionDuration(ev) * (durationScale || 1),
    easing: "linear",
    iterations: 1
  });
}
// CWI 2.2.4. The server only attaches `syllables` to words that are drawn out
// enough to qualify and that the recognizer gave distinct sub-word onsets, so
// ordinary speech keeps the clean whole-word turn and this stays rare.
const activeFills = new Set();
let fillFrame = 0;
function fillAt(stops, p) {
  for (let i = 1; i < stops.length; i++) {
    if (p <= stops[i].t) {
      const a = stops[i - 1], b = stops[i];
      return a.c + (b.c - a.c) * ((p - a.t) / Math.max(1e-6, b.t - a.t));
    }
  }
  return 1;
}
function stepFills(now) {
  fillFrame = 0;
  activeFills.forEach(fill => {
    const p = (now - fill.started) / fill.duration;
    if (p >= 1 || !fill.glyph.isConnected) {
      fill.glyph.style.setProperty("--fill", "100%");
      activeFills.delete(fill);
      return;
    }
    fill.glyph.style.setProperty(
      "--fill", (fillAt(fill.stops, Math.max(0, p)) * 100).toFixed(2) + "%");
  });
  if (activeFills.size) fillFrame = requestAnimationFrame(stepFills);
}
// Fills depend on a live rAF chain, and a stalled chain froze words at
// --fill 0% (solid white) permanently. Sweep periodically: anything past its
// duration, or syllabic without an active fill, is finalized to full colour.
window.setInterval(() => {
  const now = performance.now();
  activeFills.forEach(fill => {
    if (now - fill.started >= fill.duration) {
      fill.glyph.style.setProperty("--fill", "100%");
      activeFills.delete(fill);
    }
  });
  document.querySelectorAll(".cwi-glyph.syllabic").forEach(glyph => {
    let active = false;
    activeFills.forEach(fill => { if (fill.glyph === glyph) active = true; });
    if (!active) {
      glyph.classList.remove("syllabic");
      glyph.style.removeProperty("--fill");
      const el = glyph.parentElement;
      if (el && el._captionEvent) el.style.color = colorFor(el._captionEvent.speaker);
    }
  });
}, 1500);
function startSyllableFill(el, ev) {
  const glyph = el.querySelector(".cwi-glyph");
  if (!glyph) return false;
  const duration = Math.max(0, ev.end - ev.start) * 1000;
  if (!(duration > 0)) return false;
  glyph.style.setProperty("--spoken", colorFor(ev.speaker));
  glyph.style.setProperty("--unspoken", "rgba(255,255,255,.9)");
  glyph.style.setProperty("--fill", "0%");
  glyph.classList.add("syllabic");
  activeFills.forEach(fill => { if (fill.glyph === glyph) activeFills.delete(fill); });
  activeFills.add({glyph: glyph, stops: ev.syllables,
                   started: performance.now(), duration: duration});
  if (!fillFrame) fillFrame = requestAnimationFrame(stepFills);
  return true;
}
// Every place a word turns to its speaker colour goes through here, so the
// syllable path and the plain path can never drift apart.
//
// `animate` is false for any word that is already on screen and settled. A
// word animates once, when it is spoken; re-colouring it later (an endpoint
// verification re-states the whole phrase) must not replay anything.
function applySpokenColor(el, ev, animate) {
  const glyph = el.querySelector(".cwi-glyph");
  // A running fill may finish on its own — unless this is a FINAL statement
  // of the word (animate === false, i.e. verification): then it must end
  // fully coloured now. Screenshots caught fills stuck mid-word forever,
  // leaving white or two-tone words on settled lines.
  if (glyph && activeFills.size) {
    let running = false;
    activeFills.forEach(fill => { if (fill.glyph === glyph) running = true; });
    if (running) {
      if (animate !== false) return;
      activeFills.forEach(fill => { if (fill.glyph === glyph) activeFills.delete(fill); });
    }
  }
  const settled = el.dataset.turned === "true";
  if (animate !== false && !settled && !SENTENCE && !ev.verified &&
      ev.syllables && ev.syllables.length > 1 && !reducedMotion.matches) {
    if (startSyllableFill(el, ev)) { el.dataset.turned = "true"; return; }
  }
  if (glyph) {
    glyph.classList.remove("syllabic");
    glyph.style.removeProperty("--fill");
  }
  // One colour per word, for life. A later speaker relabel must not re-hue
  // text the reader has already passed — attribution that arrives late is
  // worth less than text that holds still.
  if (el.dataset.turned !== "true") el.style.color = colorFor(ev.speaker);
  el.dataset.turned = "true";
}
function playWordMotion(el, ev) {
  // Only the word being spoken moves. A word that is already on screen is
  // finished: it must not be disturbed by its neighbours turning, because a
  // settled word twitching while the reader is still reading it is exactly
  // what CWI's read-ahead is for.
  if (el.dataset.moved === "true" || SENTENCE) return;
  el.dataset.moved = "true";
  playLift(el, ev, 1, 1);
  if (!current || !(CFG.motion_neighbor_bleed > 0)) return;
  // The template sweeps a one-word-wide Range Selector with Ease High/Low set,
  // so the words on either side are partially displaced as it passes and the
  // line reads as one travelling wave rather than isolated twitches. Leading
  // the *next* word is the template's "Antecipate" animator: motion arrives at
  // a word before its color does, pulling the eye forward. Doing it this way
  // round keeps the color turn itself exactly on the spoken onset (2.2.2).
  const words = Array.from(current.div.querySelectorAll(".cwi-word"));
  const i = words.indexOf(el);
  if (i < 0) return;
  const bleed = CFG.motion_neighbor_bleed;
  const lead = CFG.motion_anticipation_ms / Math.max(1, motionDuration(ev));
  // Only forward. The trailing word has already been read; displacing it puts
  // motion on settled text. `motion.neighbor_bleed: 0` disables this entirely.
  const next = words[i + 1];
  if (next && next.dataset.turned !== "true") {
    playLift(next, ev, bleed, Math.max(.35, Math.min(1, lead * 2)));
  }
}

let current = null;
let partialHost = null;
let lastFinalT = -1e9;
function retire(line, delay) {
  window.setTimeout(() => {
    if (!line.div.isConnected) return;
    line.div.classList.add("gone");
    window.setTimeout(() => line.div.remove(), 500);
  }, delay);
}
function newLine(speaker, carryTail) {
  const tail = carryTail && partialHost ? Array.from(partialHost.children) : [];
  if (partialHost && !carryTail) partialHost.replaceChildren();
  if (current && !OVERFLOW_RETAIN) retire(current, CFG.line_linger_s * 1000);
  const div = document.createElement("div");
  div.className = "cwi-line";
  div.style.background = "rgba(0,0,0," + CFG.box_opacity + ")";
  rack.appendChild(div);
  if (OVERFLOW_RETAIN) {
    // Lines stay readable until the rack no longer fits the stage; then the
    // oldest are pushed off the top and the rest reflow upward, like a scroll.
    while (rack.firstElementChild !== div &&
           rack.scrollHeight > stage.clientHeight * 0.92) {
      rack.firstElementChild.remove();
    }
  } else {
    // CWI 2.4.2: at most this many captions boxes on screen at once. Evicting
    // fades rather than snapping the text out of existence.
    while (rack.children.length > CFG.max_lines) {
      const oldest = rack.firstElementChild;
      if (oldest.dataset.leaving === "true") { oldest.remove(); continue; }
      oldest.dataset.leaving = "true";
      oldest.classList.add("gone");
      window.setTimeout(() => oldest.remove(), 500);
      break;
    }
  }
  current = {div: div, count: 0, speaker: speaker, timer: null, circle: null};
  partialHost = document.createElement("span");
  partialHost.style.display = "contents";
  div.appendChild(partialHost);
  if (INTENT_CIRCLE) {
    // Appended after partialHost so it stays the last thing on the line.
    const circle = document.createElement("i");
    circle.className = "intent-circle";
    circle.style.setProperty("--c", colorFor(speaker));
    const px = Math.max(8, Math.round(stage.clientHeight * 0.018));
    circle.style.width = circle.style.height = px + "px";
    div.appendChild(circle);
    current.circle = circle;
  }
  tail.forEach(node => partialHost.appendChild(node));
  normalizeWordSpacing(current);
  return current;
}
function ensureLine(ev) {
  if (!current) newLine(ev.speaker, false);
  else if (current.speaker !== ev.speaker ||
           (current.count > 0 && ev.t - lastFinalT > CFG.line_break_gap_s)) {
    newLine(ev.speaker, false);
  } else if (current.count >= CFG.max_words) {
    // A CWI line break must not duplicate its already-rendered read-ahead
    // tail. Move those exact nodes into the new box before promoting finals.
    newLine(ev.speaker, true);
  }
  return current;
}
function wordElement(ev, final) {
  const el = document.createElement("span");
  el.className = "cwi-word " + (final ? "final" : "partial");
  // A tentative word may be deleted moments later; it must not get a vote in
  // the smoothing state, only a projection against it.
  const glyph = document.createElement("span");
  glyph.className = "cwi-glyph";
  glyph.textContent = ev.text;
  el.appendChild(glyph);
  applyTypography(el, ev, final);
  // CWI 2.2.2 is explicit that colour arrives at the spoken ONSET. Gating that
  // on an authoritative speaker label suppressed it almost entirely (measured:
  // 48/48 cues and 39/46 commits blocked), so words only turned at the
  // endpoint — seconds late. Colour now turns on time with the best-known
  // speaker; the no-flip rule below keeps it from being re-hued afterwards.
  if (final || cuedSlots.has(slotKey(ev))) {
    applySpokenColor(el, ev);
    if (!final) {
      el.dataset.cued = "true";
      el.classList.add("cued");
    }
  }
  el.title = escTitle(ev);
  el._captionEvent = ev;
  return el;
}
function normalizeWordSpacing(line) {
  // The tentative words live inside a display:contents host. A CSS sibling
  // selector cannot see across that boundary, so assign gaps by visual order.
  // This also keeps the gap unchanged when a node is promoted to final.
  // Index-INDEPENDENT: a margin that depends on position means dropping any
  // earlier word re-flows settled text. Every word owns a trailing gap, so
  // re-running this is a genuine no-op.
  Array.from(line.div.querySelectorAll(".cwi-word")).forEach(el => {
    el.style.marginRight = ".27em";
  });
}
function sameWord(node, ev) {
  const old = node && node._captionEvent;
  const canonical = text => text.toLocaleLowerCase("en-US").replace(/[.,!?;:]+$/, "");
  return !!old && canonical(old.text) === canonical(ev.text) && old.speaker === ev.speaker &&
    Math.abs(old.t - ev.t) < .09;
}
function sameSlot(node, ev) {
  // Time-only: live diarization can relabel a word's speaker between its
  // provisional commit and the endpoint pass, and a relabel must reconcile
  // in place (colour update) rather than read as a delete + insert.
  const old = node && node._captionEvent;
  return !!old && Math.abs(old.t - ev.t) < .22;
}
function promotePartial(ev) {
  const candidates = partialHost ? Array.from(partialHost.children) : [];
  const index = candidates.findIndex(node => sameSlot(node, ev));
  if (index < 0) return null;
  candidates.slice(0, index).forEach(node => node.remove());
  const candidate = candidates[index];
  // Keep the exact geometry measured when this word first appeared. Only its
  // content, color, and inner-glyph transform may change, matching CWI's fixed read-ahead
  // line even when the recognizer corrects spelling at the lock boundary.
  const wasCued = candidate.dataset.cued === "true";
  // The word is committing: let it vote in the smoothing state for subsequent
  // words, but keep the geometry it was painted with (expressionFor is
  // first-write-wins, so this returns the cached value).
  expressionFor(ev, true);
  candidate._captionEvent = ev;
  candidate.querySelector(".cwi-glyph").textContent = ev.text;
  candidate.title = escTitle(ev);
  applySpokenColor(candidate, ev);
  candidate.classList.remove("partial");
  candidate.classList.remove("cued");
  candidate.classList.add("final");
  current.div.insertBefore(candidate, partialHost);
  normalizeWordSpacing(current);
  if (!wasCued) playWordMotion(candidate, ev);
  return candidate;
}
function lineOverflows(line) {
  // nowrap lines cannot self-limit: a caption box whose words vary in size
  // must break on measured width, not on a word count.
  const limit = rack.clientWidth * 0.96;
  return line.div.scrollWidth > limit && line.count > 0;
}
function addFinalWord(ev) {
  hint.style.opacity = 0;
  const line = ensureLine(ev);
  const promoted = promotePartial(ev);
  if (!promoted) {
    const added = wordElement(ev, true);
    line.div.insertBefore(added, partialHost);
    playWordMotion(added, ev);
  }
  normalizeWordSpacing(line);
  line.count += 1;
  // If that word pushed the box past the stage, move it to a fresh line.
  if (lineOverflows(line)) {
    // :scope > — querySelectorAll descends into partialHost (display:contents),
    // so an unscoped query could move a tentative read-ahead word and leave the
    // freshly committed one behind.
    const overflowing = line.div.querySelectorAll(":scope > .cwi-word");
    const moved = overflowing[overflowing.length - 1];
    if (!moved) return;
    line.count -= 1;
    const next = newLine(ev.speaker, false);
    next.div.insertBefore(moved, partialHost);
    next.count = 1;
    normalizeWordSpacing(line);
    normalizeWordSpacing(next);
  }
  lastFinalT = ev.t + (ev.end - ev.start);
  if (!OVERFLOW_RETAIN) {
    if (line.timer) clearTimeout(line.timer);
    line.timer = window.setTimeout(() => {
      if (current === line) { retire(line, 0); current = null; partialHost = null; }
    }, CFG.line_linger_s * 1000);
  }
  notePitch(ev);
  finalHistory.push(ev);
  if (finalHistory.length > 18) finalHistory.shift();
  updateDesignSystem(ev);
}
function cueWord(ev) {
  cuedSlots.add(slotKey(ev));
  const candidates = partialHost ? Array.from(partialHost.children) : [];
  const candidate = candidates.find(node => sameSlot(node, ev));
  if (!candidate || candidate.dataset.cued === "true") return;
  candidate.dataset.cued = "true";
  candidate.classList.add("cued");
  applySpokenColor(candidate, ev);
  playWordMotion(candidate, ev);
  revisionState.textContent = "synchronized · final text pending";
  revisionState.classList.add("live");
  updateDesignSystem(ev, true);
}
const READ_AHEAD = CFG.display_mode === "readahead";
// fast: committed words render settled as in stable mode, plus the ACCURATE
// stream's not-yet-committed tail as white read-ahead. The 160 ms draft (the
// churn source: 55 rewrites / 16 deletions per 48 words) stays off the stage.
const FAST = CFG.display_mode === "fast";
// Sentence (turn-taking) mode: nothing reaches the stage until a whole
// utterance is finalized, then the complete line appears at once. It trades
// per-word immediacy for stability — the reader gets a settled sentence rather
// than words trickling in and revising.
const SENTENCE = CFG.display_mode === "sentence";
function renderReadAhead(incoming) {
  if (incoming.length) {
    hint.style.opacity = 0;
    ensureLine(incoming[0]);
  }
  if (!partialHost && incoming.length) newLine(incoming[0].speaker, false);
  const capacity = current ? Math.max(0, CFG.max_words - current.count) : 0;
  const words = incoming.slice(0, capacity);
  if (partialHost) {
    const old = Array.from(partialHost.children);
    let stablePrefix = 0;
    while (stablePrefix < old.length && stablePrefix < words.length &&
           sameWord(old[stablePrefix], words[stablePrefix])) stablePrefix += 1;
    old.slice(stablePrefix).forEach(node => node.remove());
    words.slice(stablePrefix).forEach(ev => partialHost.appendChild(wordElement(ev, false)));
    normalizeWordSpacing(current);
    // Trim tentative tail words that would overflow the stage rather than
    // letting the white read-ahead run off the edge.
    while (current && current.div.scrollWidth > rack.clientWidth * 0.96 &&
           partialHost.lastElementChild) {
      partialHost.lastElementChild.remove();
    }
  }
  return words;
}
function showHypothesis(message) {
  const incoming = message.words || [];
  // In stable mode the speculative layer never reaches the stage. It still
  // drives the sidebar timeline and the status line, so the read-ahead the
  // recognizer is working on remains visible without rewriting the captions.
  let words;
  if (READ_AHEAD) words = renderReadAhead(incoming);
  else if (FAST) words = renderReadAhead(incoming.filter(w => w.src !== "draft"));
  else words = incoming.slice(0, 4);
  currentPartials = words;
  if (message.resync) {
    const gap = Number(message.dropped_s || 0).toFixed(1);
    revisionState.textContent = "input recovered · " + gap + "s capture gap";
    statusText.textContent = "live · input recovered";
    window.setTimeout(() => { if (status.classList.contains("on")) statusText.textContent = "live"; }, 1600);
  } else {
    revisionState.textContent = words.length ?
      (READ_AHEAD ? "listening · words may revise" :
       FAST ? "listening · accurate read-ahead" : "listening · stable words only") :
      (message.endpoint && verifiedUtterances.has(message.utterance) ?
        "verified locally · phrase locked" : (message.endpoint ? "phrase locked" : "listening"));
  }
  revisionState.classList.toggle("live", words.length > 0);
  renderSync(words);
}

const finalHistory = [];
const verifiedUtterances = new Set();
let currentPartials = [];
function renderSync(partials) {
  const items = finalHistory.slice(-7).map(ev => ({ev: ev, partial: false}));
  (partials || []).slice(0, 4).forEach(ev => items.push({
    ev: ev, partial: true, cued: cuedSlots.has(slotKey(ev))
  }));
  syncTokens.replaceChildren();
  items.forEach(item => {
    const el = document.createElement("div");
    el.className = "sync-token" + (item.cued ? " cued" : (item.partial ? " partial" : ""));
    el.textContent = item.ev.text;
    el.title = item.ev.text + " at " + item.ev.t.toFixed(2) + "s";
    el.style.setProperty("--duration", Math.max(.35, item.ev.end - item.ev.start));
    el.style.setProperty("--color", colorFor(item.ev.speaker));
    syncTokens.appendChild(el);
  });
}
function updateDesignSystem(ev, provisional) {
  const color = colorFor(ev.speaker);
  document.getElementById("voiceSwatch").style.background = color;
  document.getElementById("speakerName").textContent = ev.speaker === "S1" ? "Speaker 01" : ev.speaker;
  const bars = paletteEl.children;
  for (let i = 0; i < bars.length; i++) bars[i].classList.toggle("active", CFG.palette[i] === color);

  const v = clamp01(ev.loudness);
  const pitchDomain = M.pitch_to.domain_hz || [80, 250];
  const p = clamp01((ev.pitch_hz - pitchDomain[0]) / (pitchDomain[1] - pitchDomain[0]));
  document.getElementById("volumeMeter").style.width = (v * 100).toFixed(1) + "%";
  document.getElementById("pitchMeter").style.width = (p * 100).toFixed(1) + "%";
  document.getElementById("dbValue").textContent = ev.loudness_db.toFixed(1) + " dB";
  document.getElementById("hzValue").textContent = ev.pitch_hz > 0 ? Math.round(ev.pitch_hz) + " Hz" : "unvoiced";
  const sample = document.getElementById("typeSample");
  sample.style.color = color;
  sample.style.fontSize = lerp(24, 49, v).toFixed(1) + "px";
  const sampleType = expressionFor(ev, false);   // sidebar never votes
  sample.style.fontVariationSettings = '"opsz" 14, "wght" ' + sampleType.wght +
    ', "wdth" ' + sampleType.wdth;
  document.getElementById("confidenceValue").textContent = provisional ?
    "fast timing cue · accuracy final pending" : (ev.conf_available === false ?
      "confidence not exposed by model" : Math.round(ev.conf * 100) + "% recognition confidence");
  renderSync(currentPartials);
}

// Sentence (turn-taking) mode. A finalized utterance is split into sentences
// at terminal punctuation — which the verifier supplies but the streaming words
// do not — and each sentence is revealed as a whole settled line, one after the
// next, with no per-word motion. The reader gets clean turns instead of words
// trickling in and revising.
const _TERMINAL = /[.?!]["')\]]?$/;
function splitSentences(words) {
  const out = [];
  let cur = [];
  for (const w of words) {
    cur.push(w);
    // A sentence ends at terminal punctuation; an over-long run is also broken
    // so it never exceeds one caption box.
    if (_TERMINAL.test(w.text) || cur.length >= CFG.max_words) {
      out.push(cur);
      cur = [];
    }
  }
  if (cur.length) out.push(cur);
  return out;
}
const sentenceQueue = [];
let sentenceTimer = null;
function enqueueSentences(words) {
  if (!words || !words.length) return;
  for (const sentence of splitSentences(words)) {
    for (let i = 0; i < sentence.length; i += CFG.max_words) {
      sentenceQueue.push(sentence.slice(i, i + CFG.max_words));
    }
  }
  if (!sentenceTimer) revealNextSentence();
}
function revealNextSentence() {
  const chunk = sentenceQueue.shift();
  if (!chunk) { sentenceTimer = null; return; }
  renderSentenceLine(chunk);
  // A short stagger between turns so they read as a flowing exchange rather
  // than a block dumped at once.
  sentenceTimer = window.setTimeout(revealNextSentence, CFG.sentence_stagger_ms);
}
function renderSentenceLine(words) {
  hint.style.opacity = 0;
  const line = newLine(words[0].speaker, false);
  line.div.style.opacity = 0;             // the whole box eases in
  requestAnimationFrame(() => { line.div.style.opacity = 1; });
  words.forEach(word => {
    const node = wordElement(word, true);
    node.classList.add("verified");
    node.dataset.verified = "true";
    node.dataset.turned = "true";         // settled: never re-coloured or moved
    node.dataset.moved = "true";
    line.div.insertBefore(node, partialHost);
  });
  line.count = words.length;
  normalizeWordSpacing(line);
  const last = words[words.length - 1];
  lastFinalT = last.t + (last.end - last.start);
  if (current === line && !OVERFLOW_RETAIN) {
    if (current.timer) clearTimeout(current.timer);
    current.timer = window.setTimeout(() => {
      if (current === line) { retire(line, 0); current = null; partialHost = null; }
    }, CFG.line_linger_s * 1000);
  }
  finalHistory.push(...words);
  while (finalHistory.length > 18) finalHistory.shift();
  updateDesignSystem(last, false);
  revisionState.textContent = "turn complete";
  revisionState.classList.remove("live");
}
// Fallback for a no-verifier configuration: per-word finals are buffered and
// flushed when the utterance changes. With the bundled verifier the
// authoritative `verification` event drives turns directly.
let sentenceBuf = [];
let sentenceUtt = null;
function bufferSentenceWord(ev) {
  if (sentenceUtt !== null && ev.utterance !== sentenceUtt) flushSentence();
  sentenceUtt = ev.utterance;
  sentenceBuf.push(ev);
}
function flushSentence() {
  if (sentenceBuf.length && !verifiedUtterances.has(sentenceUtt)) {
    enqueueSentences(sentenceBuf.slice());
  }
  sentenceBuf = [];
  sentenceUtt = null;
}

function applyVerification(message) {
  const words = message.words || [];
  verifiedUtterances.add(message.utterance);
  const live = Array.from(document.querySelectorAll(".cwi-word")).filter(el =>
    el._captionEvent && el._captionEvent.utterance === message.utterance
  );
  // Per-word reconciliation in time order: matches are corrected in place,
  // deletions dropped, insertions (typically the one word held back from
  // committing until the endpoint) added at their spoken position. The
  // utterance is never torn down and re-rendered, so a sentence that built
  // word-by-word cannot flash into a discrete block at the pause.
  const touched = new Set();
  const settle = (node, word) => {
    node.querySelector(".cwi-glyph").textContent = word.text;
    node._captionEvent = word;
    node.title = escTitle(word);
    // Deliberately NO typography here. A settled word's size is not
    // verification's business — re-applying it was the single largest source
    // of on-screen churn (it resized the word and re-fed the smoothing median).
    // The server now reports identical loudness for a slot, so there is
    // nothing to correct anyway.
    // These words are already on screen. Verification corrects their text,
    // never their motion.
    applySpokenColor(node, word, false);
    node.classList.remove("partial", "cued");
    node.classList.add("final", "verified");
    node.dataset.verified = "true";
    if (node.parentElement === partialHost && current) {
      current.div.insertBefore(node, partialHost);
      current.count += 1;
    }
    touched.add(node.closest(".cwi-line"));
  };
  const drop = node => {
    const line = node.closest(".cwi-line");
    if (current && line === current.div) current.count -= 1;
    node.remove();
    if (line) touched.add(line);
  };
  let i = 0;
  words.forEach(word => {
    while (i < live.length && !sameSlot(live[i], word) &&
           live[i]._captionEvent.t < word.t - 0.11) {
      drop(live[i]);
      i += 1;
    }
    if (i < live.length && sameSlot(live[i], word)) {
      settle(live[i], word);
      i += 1;
    } else if (i < live.length) {
      // Insertion mid-utterance: place it at its spoken position, settled.
      const anchor = live[i];
      const node = wordElement(word, true);
      node.classList.add("verified");
      node.dataset.verified = "true";
      node.dataset.turned = "true";
      node.dataset.moved = "true";
      anchor.parentElement.insertBefore(node, anchor);
      if (current && anchor.closest(".cwi-line") === current.div) current.count += 1;
      touched.add(node.closest(".cwi-line"));
    } else {
      // Tail: the endpoint-held word arrives through the normal word path, so
      // it appears and animates exactly like every committed word before it.
      addFinalWord(word);
    }
  });
  while (i < live.length) {
    drop(live[i]);
    i += 1;
  }
  touched.forEach(line => {
    if (!line) return;
    if (!line.querySelector(".cwi-word")) line.remove();
    else normalizeWordSpacing({div: line});
  });
  // Nothing tentative may outlive its utterance's verification: a stray
  // partial that failed every slot match stays white forever otherwise.
  document.querySelectorAll(".cwi-word.partial").forEach(node => {
    if (node._captionEvent && node._captionEvent.utterance === message.utterance) {
      node.remove();
    }
  });
  const retained = finalHistory.filter(ev => ev.utterance !== message.utterance);
  finalHistory.splice(0, finalHistory.length, ...retained, ...words);
  while (finalHistory.length > 18) finalHistory.shift();
  if (words.length) {
    lastFinalT = words[words.length - 1].t +
      (words[words.length - 1].end - words[words.length - 1].start);
    updateDesignSystem(words[words.length - 1], false);
  }
  if (current && !OVERFLOW_RETAIN) {
    if (current.timer) clearTimeout(current.timer);
    current.timer = window.setTimeout(() => {
      if (current) { retire(current, 0); current = null; partialHost = null; }
    }, CFG.line_linger_s * 1000);
  }
  revisionState.textContent = "verified locally · phrase locked";
  revisionState.classList.remove("live");
}

rack.style.paddingBottom = (CFG.bottom_margin_pct / 100 * stage.clientHeight) + "px";
addEventListener("resize", () => {
  rack.style.paddingBottom = (CFG.bottom_margin_pct / 100 * stage.clientHeight) + "px";
  document.querySelectorAll(".cwi-word").forEach(el => {
    // Rescale only — re-resolving here would re-run the smoothing for every
    // word on screen and change sizes that were already decided.
    if (el._type) {
      el.style.fontSize = (el._type.pct / 100 * stage.clientHeight).toFixed(1) + "px";
    }
  });
});

// Final words from a legacy pause-segmented recognizer can still arrive in a
// burst. Preserve spoken spacing when the queue is short and catch up quickly
// when it grows, while true-streaming single words render immediately.
const pendingFinals = [];
let draining = false;
let heldHypothesis = null;
function drain() {
  if (!pendingFinals.length) {
    draining = false;
    if (heldHypothesis) {
      const message = heldHypothesis;
      heldHypothesis = null;
      showHypothesis(message);
    }
    return;
  }
  const ev = pendingFinals.shift();
  addFinalWord(ev);
  let delay = 0;
  if (pendingFinals.length) {
    const gap = (pendingFinals[0].t - ev.t) * 1000;
    delay = Math.min(120, Math.max(20, gap * .3));
    if (pendingFinals.length > 8) delay = 10;
  }
  window.setTimeout(drain, delay);
}
function scheduleDrain() {
  if (draining) return;
  draining = true;
  // One frame lets words committed in the same decoder update collect so
  // their pops can retain spoken order instead of firing simultaneously.
  requestAnimationFrame(drain);
}

// Post-paint churn counter (display.debug_churn). Counts mutations to words
// that are already SETTLED — the ones a reader may be mid-sentence through.
// window.__cwiChurn.report() -> {settled, mutations, perWord, byKind}
if (CFG.debug_churn) {
  const byKind = {text: 0, size: 0, axes: 0, colour: 0, spacing: 0, move: 0, remove: 0};
  const settledWord = node => {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const word = el && el.closest && el.closest(".cwi-word");
    return word && word.dataset.turned === "true" ? word : null;
  };
  new MutationObserver(records => {
    for (const r of records) {
      if (r.type === "characterData") {
        if (settledWord(r.target)) byKind.text += 1;
      } else if (r.type === "attributes") {
        const w = settledWord(r.target);
        if (!w) continue;
        const now = r.target.getAttribute("style") || "";
        const was = r.oldValue || "";
        const changed = prop => {
          const grab = t => (t.match(new RegExp(prop + ":[^;]*")) || [""])[0];
          return grab(now) !== grab(was);
        };
        if (changed("font-size")) byKind.size += 1;
        if (changed("font-variation-settings")) byKind.axes += 1;
        if (changed("color") || changed("--fill")) byKind.colour += 1;
        if (changed("margin")) byKind.spacing += 1;
      } else if (r.type === "childList") {
        r.removedNodes.forEach(n => {
          if (n.nodeType === 1 && n.classList && n.classList.contains("cwi-word") &&
              n.dataset.turned === "true") byKind.remove += 1;
        });
        r.addedNodes.forEach(n => {
          if (n.nodeType === 1 && n.classList && n.classList.contains("cwi-word") &&
              n.dataset.turned === "true") byKind.move += 1;
        });
      }
    }
  }).observe(rack, {subtree: true, childList: true, characterData: true,
                    attributes: true, attributeFilter: ["style"],
                    attributeOldValue: true, characterDataOldValue: true});
  window.__cwiChurn = {byKind: byKind, report() {
    const settled = document.querySelectorAll('.cwi-word[data-turned="true"]').length;
    const mutations = Object.values(byKind).reduce((a, b) => a + b, 0);
    return {settled: settled, mutations: mutations,
            perWord: settled ? +(mutations / settled).toFixed(2) : 0, byKind: byKind};
  }};
}

const status = document.getElementById("status");
const statusText = document.getElementById("statusText");
const es = new EventSource("/events");
es.onopen = () => { status.classList.add("on"); statusText.textContent = "live"; };
es.onerror = () => { status.classList.remove("on"); statusText.textContent = "reconnecting"; };
es.onmessage = message => {
  const ev = JSON.parse(message.data);
  if (ev.type === "boot") {
    // Server comes up before the models load; say so instead of implying we
    // can hear anything yet.
    statusText.textContent = ev.stage;
    if (ev.stage === "listening") status.classList.add("on");
    return;
  }
  if (ev.type === "level") {
    updateInputLevel(ev);
    updateIntentCircle(ev);
  } else if (ev.type === "hypothesis") {
    if (ev.resync) {
      // A real capture-device gap invalidates queued timing from before it.
      pendingFinals.length = 0;
      heldHypothesis = null;
      cuedSlots.clear();
      showHypothesis(ev);
    } else if (draining || pendingFinals.length) heldHypothesis = ev;
    else showHypothesis(ev);
  } else if (ev.type === "cue") {
    cueWord(ev);
  } else if (ev.type === "verification") {
    // Replay can deliver many commits faster than the animation drain. Once an
    // authoritative phrase arrives, discard queued provisional words from the
    // same utterance so they cannot render over the corrected endpoint state.
    for (let i = pendingFinals.length - 1; i >= 0; i--) {
      if (pendingFinals[i].utterance === ev.utterance) pendingFinals.splice(i, 1);
    }
    verifiedUtterances.add(ev.utterance);
    if (SENTENCE) enqueueSentences(ev.words);
    else applyVerification(ev);
  } else if (ev.type === "commit" &&
             !verifiedUtterances.has(ev.utterance)) {
    // Provisional per-word commits are the incremental layer; sentence mode
    // waits for the whole utterance and ignores them.
    if (!SENTENCE) { pendingFinals.push(ev); scheduleDrain(); }
  } else if (ev.type === "word" && ev.final &&
             !verifiedUtterances.has(ev.utterance)) {
    if (SENTENCE) bufferSentenceWord(ev);
    else { pendingFinals.push(ev); scheduleDrain(); }
  }
};
</script>
</body>
</html>
''')
