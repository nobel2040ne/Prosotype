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


def _live_sync_cfg(ls: dict) -> dict:
    """Resolve the live CWI-motion knobs with defaults (see config.yaml)."""
    return {
        "enabled": ls.get("enabled", True),
        "sync_pop": ls.get("sync_pop", 0.10),
        "sync_elevation_em": ls.get("sync_elevation_em", 0.20),
        "rise_s": ls.get("rise_s", 0.18),
        "peak_s": ls.get("peak_s", 0.14),
        "fall_s": ls.get("fall_s", 0.34),
        "prosody_strength": ls.get("prosody_strength", 0.78),
        "min_emphasis_scale": ls.get("min_emphasis_scale", 0.78),
        "max_emphasis_scale": ls.get("max_emphasis_scale", 1.34),
        "size_response": ls.get("size_response", 0.78),
        "pitch_response": ls.get("pitch_response", 1.0),
        "width_response": ls.get("width_response", 0.75),
        "font_weight_strength": ls.get("font_weight_strength", 1.70),
        "active_weight_range": ls.get("active_weight_range", [180, 700]),
        "font_width_strength": ls.get("font_width_strength", 0.90),
        # The three voice axes deliberately do not share one temporal pulse.
        # Fractions are measured over the word's bounded first-paint window.
        "size_attack_fraction": ls.get("size_attack_fraction", 0.42),
        "size_hold_fraction": ls.get("size_hold_fraction", 0.62),
        "weight_attack_fraction": ls.get("weight_attack_fraction", 0.30),
        "weight_hold_fraction": ls.get("weight_hold_fraction", 0.48),
        "weight_release_fraction": ls.get("weight_release_fraction", 0.90),
        "width_attack_fraction": ls.get("width_attack_fraction", 0.50),
        "width_hold_fraction": ls.get("width_hold_fraction", 0.68),
        "width_release_fraction": ls.get("width_release_fraction", 0.96),
        "slow_delivery_curve_delay": ls.get("slow_delivery_curve_delay", 0.06),
        "lift_base_gain": ls.get("lift_base_gain", 0.82),
        "lift_prosody_gain": ls.get("lift_prosody_gain", 2.8),
        "lift_min_gain": ls.get("lift_min_gain", 0.28),
        "lift_max_gain": ls.get("lift_max_gain", 1.40),
        "emphasis_deadband": ls.get("emphasis_deadband", 0.02),
        # Website-style synchronization travels through the visible letters.
        # This is distinct from the optional character-entry/typewriter effect.
        "character_wave_enabled": ls.get("character_wave_enabled", True),
        "character_wave_lift_em": ls.get("character_wave_lift_em", 0.055),
        "character_wave_pop": ls.get("character_wave_pop", 0.018),
        "character_wave_crouch_em": ls.get("character_wave_crouch_em", 0.0),
        "character_wave_lead_s": ls.get("character_wave_lead_s", 0.18),
        "character_wave_peak_s": ls.get("character_wave_peak_s", 0.18),
        "character_wave_fall_s": ls.get("character_wave_fall_s", 0.48),
        "character_wave_spatial_smoothing": ls.get(
            "character_wave_spatial_smoothing", 0.72
        ),
        "character_wave_step_s": ls.get("character_wave_step_s", 0.18),
        "character_wave_max_span_s": ls.get("character_wave_max_span_s", 2.20),
        "fast_speech_motion_gain": ls.get("fast_speech_motion_gain", 0.58),
        "neighbor_push": ls.get("neighbor_push", False),
        "display_on_create": ls.get("display_on_create", True),
        "character_entry_enabled": ls.get("character_entry_enabled", False),
        "character_entry_duration_s": ls.get("character_entry_duration_s", 0.24),
        "character_entry_stagger_s": ls.get("character_entry_stagger_s", 0.018),
        "character_entry_slide_em": ls.get("character_entry_slide_em", 0.22),
        "character_entry_rise_em": ls.get("character_entry_rise_em", 0.08),
        "character_entry_start_scale": ls.get("character_entry_start_scale", 0.92),
        "character_entry_start_opacity": ls.get(
            "character_entry_start_opacity", 0.0
        ),
        "clock_smoothing": ls.get("clock_smoothing", 0.18),
        "clock_reset_threshold_s": ls.get("clock_reset_threshold_s", 0.75),
    }


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
    speaker_attribution = config.get("live", {}).get("speaker_attribution", {}) or {}
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
        "live_sync": _live_sync_cfg(motion.get("live_sync", {}) or {}),
        "expression": config["expression"],
        "min_voiced_frac": config["normalization"]["min_voiced_frac"],
        "display_mode": display.get("mode", "fast"),
        "display_align": display.get("align", "left"),
        "display_retention": display.get("retention", "overflow"),
        "intent_circle": display.get("intent_circle", False),
        "intent_circle_size_pct": display.get("intent_circle_size_pct", 2.3),
        "intent_circle_volume_db": display.get(
            "intent_circle_volume_db", [-60, -15]
        ),
        "intent_circle_pitch_hz": display.get(
            "intent_circle_pitch_hz", [80, 250]
        ),
        "intent_circle_brightness_hz": display.get(
            "intent_circle_brightness_hz", [500, 3500]
        ),
        "intent_circle_smoothing": display.get(
            "intent_circle_smoothing", 0.24
        ),
        "line_break_gap_s": display.get("line_break_gap_s", 2.0),
        "max_words": display.get("max_words", 8),
        "max_simultaneous_reveals": display.get(
            "max_simultaneous_reveals", 2
        ),
        "word_reveal_gap_ms": round(
            display.get("word_reveal_gap_s", 0.14) * 1000
        ),
        "word_reveal_gap_min_ms": round(
            display.get("word_reveal_gap_min_s", 0.08) * 1000
        ),
        "word_reveal_gap_max_ms": round(
            display.get("word_reveal_gap_max_s", 0.26) * 1000
        ),
        "word_reveal_timing_strength": display.get(
            "word_reveal_timing_strength", 0.75
        ),
        "word_reveal_catchup_gap_ms": round(
            display.get("word_reveal_catchup_gap_s", 0.06) * 1000
        ),
        "word_motion_duration_ms": round(
            display.get("word_motion_duration_s", 0.52) * 1000
        ),
        "word_motion_max_duration_ms": round(
            display.get("word_motion_max_duration_s", 0.72) * 1000
        ),
        "word_motion_span_stretch": display.get("word_motion_span_stretch", 0.42),
        "onset_motion_duration_ms": round(
            display.get("onset_motion_duration_s", 0.68) * 1000
        ),
        "word_motion_source_span_s": display.get(
            "word_motion_source_span_s", 0.14
        ),
        "word_reveal_fade_ms": round(
            display.get("word_reveal_fade_s", 0.22) * 1000
        ),
        "max_lines": box.get("max_lines", 2),
        "line_linger_s": display.get("line_linger_s", 9.0),
        "sentence_stagger_ms": round(display.get("sentence_stagger_s", 0.7) * 1000),
        "debug_churn": display.get("debug_churn", False),
        "debug_render": display.get("debug_render", False),
        "render_queue_limit": display.get("render_queue_limit", 512),
        "diagnostic_interval_ms": round(
            display.get("diagnostic_interval_s", 1.0) * 1000
        ),
        "provisional_color_strength": speaker_attribution.get(
            "provisional_color_strength", 0.55
        ),
    }

    # Live and `cc` share the pure CWI motion math, not the presentation tuning.
    # A completed CC line can carry the stronger reference wave; a stacked live
    # transcript must remain calm and must never displace words somebody is
    # still reading. `motion.live_sync` therefore owns live-only amplitude and
    # timing values. `closed_caption` remains untouched.
    cc = config.get("closed_caption", {}) or {}
    live_sync = page_cfg["live_sync"]
    page_cfg["motion_core"] = {
        "sync_pop": live_sync["sync_pop"],
        "sync_elevation_em": live_sync["sync_elevation_em"],
        "sync_rise_s": live_sync["rise_s"],
        "sync_peak_s": live_sync["peak_s"],
        "sync_fall_s": live_sync["fall_s"],
        "color_turn_ms": motion.get("color_turn_ms", 90),
        "emphasis_lead_s": cc.get("emphasis_lead_s", 0.18),
        "emphasis_hold_s": cc.get("emphasis_hold_s", 0.08),
        "emphasis_tail_s": cc.get("emphasis_tail_s", 0.30),
        "quiet_deformation": cc.get("quiet_deformation", 1.0),
        "emphasis_deadband": live_sync["emphasis_deadband"],
        "size_pct": cc.get("size_pct", 5.0),
        "min_voiced_frac": config["normalization"]["min_voiced_frac"],
        "provisional_color_strength": speaker_attribution.get(
            "provisional_color_strength", 0.55
        ),
        "glyph_height_em": cc.get("glyph_height_em", 0.70),
        "motion_source": cc.get("motion_source", "spec"),
        "rest_color": cc.get("rest_color", "rgba(255,255,255,.9)"),
        "char_sync_reach": 1.0 if live_sync["character_wave_enabled"] else 0.0,
        "char_sync_lift_em": live_sync["character_wave_lift_em"],
        "char_sync_pop": live_sync["character_wave_pop"],
        "char_sync_crouch_em": live_sync["character_wave_crouch_em"],
        "char_sync_lead_s": live_sync["character_wave_lead_s"],
        "char_sync_peak_s": live_sync["character_wave_peak_s"],
        "char_sync_fall_s": live_sync["character_wave_fall_s"],
    }
    render_core = (_REPO_ROOT / "autocwi" / "live_render_core.js").read_text(
        encoding="utf-8"
    )
    motion_core = (_REPO_ROOT / "autocwi" / "cwi_motion_core.js").read_text(
        encoding="utf-8"
    )
    html = _TEMPLATE.safe_substitute(
        FONT_B64=font_b64,
        CFG_JSON=json.dumps(page_cfg),
        RENDER_CORE=render_core,
        MOTION_CORE=motion_core,
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
    position: relative; z-index: 2; padding-inline: 4%;
  }
  .cwi-line {
    /* One captions box is one visual line (§2.4.2). Width overflow is measured
       in JS and the last word moves into a new box; flex wrapping a single box
       produced an unbounded multi-row transcript inside the lower work area. */
    display: flex; align-items: baseline; flex-wrap: nowrap; white-space: nowrap;
    max-width: 96%;
    padding: .04em .42em; margin-top: .10em;
    background: rgba(0,0,0,.9); transition: opacity .35s ease;
  }
  .cwi-line.gone { opacity: 0; }
  .cwi-word {
    line-height: 1.05; display: inline-block;
    font-optical-sizing: none; font-synthesis: none; text-rendering: geometricPrecision;
    font-kerning: normal; font-variant-ligatures: none;
    /* The motion loop animates font-variation weight per frame (the transient
       intonation swell), which is ON the layout path. The box is frozen at its
       resting width (JS sets el.style.width) and its content overflows it
       symmetrically. CC may add analytic neighbour-push; stacked live captions
       leave it disabled so previously written words stay fixed. */
    text-align: center; white-space: nowrap;
    /* The live CWI-motion loop (below) writes `transform` here per frame while
       a word is in its active window: scale = the 2.2.3 pop, translateY = the
       elevation, optional translateX = the neighbour-push shift. Growing from the
       baseline centre (not the box centre) keeps letters sitting on the line,
       and transform is off the layout path, so the pop never reflows the row.
       No transform TRANSITION: the loop owns each frame; a transition would lag
       it. */
    transform-origin: 50% 100%;
    /* §2.2.2 eases the per-word colour turn. Settled intonation axes are
       assigned once before activation; transitioning font-size or `wdth`
       would put a revision back on the layout path and can re-wrap a line. */
    transition:
      color var(--turn, 90ms) linear,
      opacity var(--reveal-fade, 220ms) cubic-bezier(.22,.78,.24,1);
  }
  .cwi-word.partial { color: rgba(255,255,255,.9); }
  .cwi-word[data-speaker-status="unknown"] {
    color: rgba(255,255,255,.9);
  }
  .cwi-word[data-speaker-status="provisional"] {
    text-decoration: underline dotted rgba(255,255,255,.38);
    text-decoration-thickness: .045em;
    text-underline-offset: .14em;
  }
  .cwi-word[data-speaker-status="corrected"] {
    text-decoration: none;
  }
  .cwi-word[data-moving="true"] { will-change: transform; }
  .cwi-glyph {
    display: inline-block; color: inherit; transform: translate3d(0,0,0);
    transform-origin: 50% 100%; will-change: transform; backface-visibility: hidden;
  }
  /* `cc` builds character spans because the CWI range-selector hand-off is
     word-timed but character-shaped. Live now keeps the same division:
     intonation is word-wide; synchronization travels through these already
     visible spans. This is not the optional opacity/slide typewriter entry. */
  .cwi-ch {
    display: inline-block; position: relative; white-space: pre;
    color: inherit; transform-origin: 50% 100%;
    backface-visibility: hidden;
  }
  /* A phoneme prefix can arrive while its final sound is still held. Preserve
     the stable letters and paint duration into the empty future with a calm
     horizontal trail; never shake, duplicate, or stretch the actual glyph. */
  .cwi-word[data-sustain-active="true"] .cwi-ch:last-child::after {
    content: ""; position: absolute; left: 92%; bottom: .04em;
    width: var(--sustain-width, .16em); height: .055em; border-radius: 99px;
    background: linear-gradient(90deg, currentColor 0 35%, transparent 100%);
    opacity: .68; transform-origin: 0 50%; pointer-events: none;
    transition: width 120ms cubic-bezier(.22,.78,.24,1);
  }
  /* The outer pulse is true captured volume. The bead's height is F0, while
     the translucent inner oval shows periodicity and spectral brightness.
     These continuous cues stay outside the letterforms so settled text remains
     perfectly still and readable. */
  .intent-circle {
    display: inline-block; position: relative; flex: 0 0 auto;
    box-sizing: border-box; overflow: visible; border-radius: 50%;
    margin: 0 .10em 0 -.06em; align-self: center;
    color: var(--c, #e5e517);
    border: 1.5px solid currentColor;
    background: #09090b;
    box-shadow: 0 0 var(--voice-halo, 0px)
      color-mix(in srgb, currentColor 46%, transparent);
    opacity: var(--voice-opacity, .30);
    transform:
      scale(var(--voice-scale, .72))
      scaleX(var(--voice-x, 1))
      scaleY(var(--voice-y, 1));
    transform-origin: 50% 50%;
    transition:
      transform 140ms cubic-bezier(.22,.78,.24,1),
      opacity 180ms ease, box-shadow 140ms ease;
  }
  .intent-circle::before {
    content: ""; position: absolute; z-index: 2;
    left: 50%; top: var(--pitch-y, 50%);
    width: 22%; aspect-ratio: 1; border-radius: 50%;
    background: currentColor;
    transform: translate(-50%, -50%);
    transition: top 130ms cubic-bezier(.22,.78,.24,1);
  }
  .intent-circle::after {
    content: ""; position: absolute; z-index: 1;
    inset: 29% 18%; box-sizing: border-box; border-radius: 50%;
    border: 1px solid currentColor; background: transparent;
    opacity: var(--texture-opacity, .18);
    transform:
      scaleX(var(--texture-x, .8))
      rotate(var(--texture-angle, 0deg));
    transition:
      transform 150ms cubic-bezier(.22,.78,.24,1), opacity 150ms ease;
  }
  #renderDiagnostics {
    position: absolute; z-index: 8; left: 10px; top: 34px; width: min(720px, 92%);
    max-height: 42%; overflow: auto; margin: 0; padding: 8px 10px;
    background: rgba(0,0,0,.82); border: 1px solid rgba(255,255,255,.2);
    color: #b8f5c7; font: 10px/1.35 ui-monospace, SFMono-Regular, monospace;
    white-space: pre-wrap; pointer-events: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .cwi-word, .cwi-glyph, .cwi-ch, .intent-circle, .voice-compass,
    .compass-core, .compass-pitch, .compass-direction, .cwi-line {
      animation: none !important;
      transition-duration: 0.01ms !important;
    }
    .cwi-word, .cwi-ch { transform: none !important; }
  }
  /* CWI 2.2.4 syllable variation is painted on the existing `.cwi-ch` spans
     in JS. Do not use background-clip:text on `.cwi-glyph`: Chrome composites
     each inline child at the glyph origin while the clip is active, visibly
     piling every letter into one corrupted symbol. */

  /* NON-SPEECH LANE (paralinguistic descriptors: laughter, applause, music,
     environmental). A DISTINCT band at the top of the stage — never inline in
     the speech flow, so a sound descriptor cannot enter the flex row, the
     smoothing median, or the settled-word churn accounting. Category is coded
     by the border/dot colour (a neutral, non-speaker hue so it never reads as
     a voice) and the bracketed label follows captioning convention. */
  #nonspeechLane {
    position: absolute; top: 12px; left: 0; right: 0; z-index: 3;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    pointer-events: none;
  }
  .ns-chip {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 5px 13px; border-radius: 999px; font-size: 13px; font-style: italic;
    color: #e2e2e8; background: rgba(16,16,20,.86);
    border: 1px solid var(--ns-c, #6a6a72);
    box-shadow: 0 0 20px -8px var(--ns-c, #6a6a72);
    opacity: 0; transform: translateY(-7px);
    transition: opacity .28s ease, transform .28s ease;
  }
  .ns-chip.on { opacity: 1; transform: translateY(0); }
  .ns-chip .ns-dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--ns-c);
    box-shadow: 0 0 8px var(--ns-c);
  }
  .ns-chip.live .ns-dot { animation: nsPulse 1.05s ease-in-out infinite; }
  .ns-chip .ns-cat {
    font-style: normal; font-size: 8px; letter-spacing: .13em; text-transform: uppercase;
    color: #9a9aa2;
  }
  @keyframes nsPulse { 0%,100%{opacity:.45;transform:scale(.78)} 50%{opacity:1;transform:scale(1.15)} }

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

  .compass-body {
    display: grid; grid-template-columns: 124px 1fr; align-items: center;
    gap: 14px; margin-top: 13px;
  }
  .voice-compass {
    --c: var(--yellow); position: relative; width: 118px; aspect-ratio: 1;
    box-sizing: border-box; border: 1px solid color-mix(in srgb, var(--c) 72%, #fff);
    border-radius: 50%; color: var(--c); background:
      radial-gradient(circle, transparent 0 24%, rgba(255,255,255,.08) 25% 26%,
                      transparent 27% 48%, rgba(255,255,255,.08) 49% 50%,
                      transparent 51%),
      linear-gradient(90deg, transparent 49.5%, rgba(255,255,255,.08) 50%,
                      transparent 50.5%),
      linear-gradient(transparent 49.5%, rgba(255,255,255,.08) 50%,
                      transparent 50.5%);
    box-shadow: 0 0 var(--compass-halo, 0px)
      color-mix(in srgb, currentColor 42%, transparent);
    transform: scale(var(--compass-scale, .94));
    transition: transform 140ms cubic-bezier(.22,.78,.24,1),
                box-shadow 140ms ease, border-color 180ms ease;
  }
  .voice-compass::before {
    content: "FRONT"; position: absolute; left: 50%; top: -11px;
    transform: translateX(-50%); color: #696971; font-size: 6px;
    letter-spacing: .12em;
  }
  .compass-direction {
    position: absolute; inset: 5px; border-radius: 50%;
    transform: rotate(var(--direction-angle, 0deg));
    transition: transform 180ms cubic-bezier(.22,.78,.24,1);
  }
  .compass-direction i {
    position: absolute; left: 50%; top: -1px; width: 9px; height: 9px;
    border-radius: 50%; background: currentColor;
    box-shadow: 0 0 10px currentColor; transform: translateX(-50%);
    opacity: 0; transition: opacity 180ms ease;
  }
  .voice-compass[data-direction="known"] .compass-direction i { opacity: 1; }
  .compass-pitch {
    position: absolute; z-index: 2; left: 50%; top: var(--pitch-y, 50%);
    width: 9px; height: 9px; border-radius: 50%; background: currentColor;
    border: 2px solid #0b0b0e; transform: translate(-50%, -50%);
    transition: top 130ms cubic-bezier(.22,.78,.24,1);
  }
  .compass-core {
    position: absolute; z-index: 1; inset: 37% 28%; border-radius: 50%;
    border: 1.5px solid currentColor; opacity: var(--texture-opacity, .18);
    transform:
      scale(var(--texture-size, 1))
      scaleX(var(--texture-x, .8))
      rotate(var(--texture-angle, 0deg));
    transition: transform 150ms cubic-bezier(.22,.78,.24,1),
                opacity 150ms ease;
  }
  .compass-meta { display: grid; gap: 9px; min-width: 0; }
  .compass-meta p { margin: 0; }
  .compass-value {
    color: #e5e5e8; font-size: 12px; line-height: 1.15;
    font-variant-numeric: tabular-nums;
  }
  .compass-label {
    color: #707078; font-size: 8px; line-height: 1.35;
    text-transform: uppercase; letter-spacing: .08em;
  }
  #compassDirection[data-known="true"] { color: var(--yellow); }

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
        <pre id="renderDiagnostics" hidden aria-hidden="true"></pre>
        <div id="hint"><strong>Speak naturally.</strong><span>Words will appear while you talk</span></div>
        <div id="nonspeechLane" aria-live="polite" aria-label="Non-speech sounds"></div>
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

      <section class="system-card" id="directionCard">
        <div class="card-head"><h2>VOICE COMPASS</h2><span>Where the voice is</span></div>
        <div class="compass-body">
          <div id="voiceCompass" class="voice-compass" role="img"
               aria-label="Voice compass; direction sensor not connected">
            <span class="compass-direction"><i></i></span>
            <span class="compass-pitch"></span>
            <span class="compass-core"></span>
          </div>
          <div class="compass-meta">
            <p><span class="compass-value" id="compassLevel">— dB</span><br>
               <span class="compass-label">volume</span></p>
            <p><span class="compass-value" id="compassPitch">— Hz</span><br>
               <span class="compass-label">frequency</span></p>
            <p><span class="compass-value" id="compassDirection"
                     data-known="false">awaiting array</span><br>
               <span class="compass-label">direction-ready · 2+ mics</span></p>
          </div>
        </div>
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
$RENDER_CORE
</script>
<script>
$MOTION_CORE
</script>
<script>
"use strict";
const CFG = JSON.parse(document.getElementById("cfg").textContent);
const RenderCore = window.CWIRenderCore;
const M = CFG.mapping;
const stage = document.getElementById("stage");
const rack = document.getElementById("captionRack");
const hint = document.getElementById("hint");
const paletteEl = document.getElementById("palette");
const syncTokens = document.getElementById("syncTokens");
const revisionState = document.getElementById("revisionState");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const cuedSlots = new Set();

// Non-speech lane. Category -> a NEUTRAL, non-speaker hue (the CWI palette is
// reserved for voices, so a descriptor must never borrow a speaker colour).
const nsLane = document.getElementById("nonspeechLane");
const NS_COLORS = { vocal: "#E8A23C", reaction: "#5AD1A0",
                    music: "#9A7BE8", environmental: "#8A9BB0" };
const nsChips = new Map();           // category -> {el, timer}
const NS_LINGER_MS = 2600;           // a finalized descriptor stays this long
function soundChip(ev) {
  if (!nsLane || !ev.category) return;
  const label = "[ " + ev.label + " ]";
  let entry = nsChips.get(ev.category);
  if (ev.state === "start") {
    if (!entry) {
      const el = document.createElement("span");
      el.className = "ns-chip";
      el.style.setProperty("--ns-c", NS_COLORS[ev.category] || "#8a8a92");
      const dot = document.createElement("i");
      dot.className = "ns-dot";
      const category = document.createElement("span");
      category.className = "ns-cat";
      const text = document.createElement("span");
      text.className = "ns-label";
      el.append(dot, category, text);
      nsLane.appendChild(el);
      entry = { el: el, timer: null };
      nsChips.set(ev.category, entry);
      requestAnimationFrame(() => el.classList.add("on"));
    }
    if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; }
    entry.el.classList.add("live");                // pulsing dot while ongoing
    entry.el.querySelector(".ns-cat").textContent = ev.category;
    entry.el.querySelector(".ns-label").textContent = label;
  } else {                                          // "end": finalize + linger
    if (!entry) return;
    entry.el.classList.remove("live");
    entry.el.querySelector(".ns-label").textContent = label;
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = window.setTimeout(() => {
      entry.el.classList.remove("on");
      window.setTimeout(() => entry.el.remove(), 320);
      nsChips.delete(ev.category);
    }, NS_LINGER_MS);
  }
}

document.documentElement.style.setProperty("--turn", CFG.motion_color_turn_ms + "ms");
document.documentElement.style.setProperty("--type-ms", CFG.expression.transition_ms + "ms");
// Live is a stacked transcript by default: boxes grow upward and the oldest
// one leaves only when the stage is full. `linger` remains available for the
// bounded two-box presentation.
const OVERFLOW_RETAIN = CFG.display_retention === "overflow";
const INTENT_CIRCLE = CFG.intent_circle === true;
if (CFG.display_align === "left") {
  rack.style.alignItems = "flex-start";
  rack.style.paddingInline = "4%";
}

function lerp(a, b, f) { return a + (b - a) * f; }
function clamp01(f) { return Math.min(1, Math.max(0, f)); }
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

// Opt-in render diagnostics. `display.debug_render: true` logs one compact
// report per second; `?renderdiag=1` also exposes it in the stage so a headless
// browser dump can capture structural metrics without telemetry.
const renderDiagEl = document.getElementById("renderDiagnostics");
const renderDiagVisible = new URLSearchParams(location.search).get("renderdiag") === "1";
const renderDiagEnabled = CFG.debug_render || renderDiagVisible;
const renderMetrics = {
  startedAt: performance.now(),
  events: {},
  wordUpdatesReceived: 0,
  wordUpdatesRendered: 0,
  updatesCoalesced: 0,
  updatesDiscarded: 0,
  staleRevisionsIgnored: 0,
  domNodesCreated: 0,
  domNodesReplaced: 0,
  fullLineRenders: 0,
  fullStageRenders: 0,
  animationStarts: 0,
  animationRestarts: 0,
  displayMotionStarts: 0,
  sequentialRevealStarts: 0,
  revealQueueDelayTotalMs: 0,
  revealQueueDelaySamples: 0,
  revealQueueDelayMaxMs: 0,
  maxSimultaneousReveals: 0,
  sourceMotionStarts: 0,
  characterEntryStarts: 0,
  characterEntryRestarts: 0,
  characterAnimationsStarted: 0,
  eventToRenderDelayTotalMs: 0,
  eventToRenderDelaySamples: 0,
  eventToRenderDelayMaxMs: 0,
  longTasks: 0,
  longTaskTotalMs: 0,
  queueDepth: 0,
  maxQueueDepth: 0,
  layoutStyleUpdates: 0,
  speakerRecolors: 0,
  textReplacements: 0,
  levelFrames: 0,
  motionTrace: []
};
function countMetric(name, amount) {
  renderMetrics[name] = (renderMetrics[name] || 0) + (amount === undefined ? 1 : amount);
}
function noteRenderedEvent(ev) {
  if (!(ev && ev._received_perf >= 0)) return;
  const delay = Math.max(0, performance.now() - ev._received_perf);
  renderMetrics.eventToRenderDelayTotalMs += delay;
  renderMetrics.eventToRenderDelaySamples += 1;
  renderMetrics.eventToRenderDelayMaxMs =
    Math.max(renderMetrics.eventToRenderDelayMaxMs, delay);
}
function setNodeText(node, value) {
  const text = String(value);
  if (node && node.textContent !== text) {
    node.textContent = text;
    countMetric("textReplacements");
    return true;
  }
  return false;
}
function setGlyphText(glyph, value) {
  const text = String(value);
  if (!glyph || glyph.textContent === text) return false;
  const letters = Array.from(text);
  const nodes = Array.from(glyph.children);
  letters.forEach((letter, index) => {
    let node = nodes[index];
    if (!node) {
      node = document.createElement("span");
      node.className = "cwi-ch";
      glyph.appendChild(node);
    }
    if (node.textContent !== letter) node.textContent = letter;
  });
  for (let index = nodes.length - 1; index >= letters.length; index -= 1) {
    nodes[index].remove();
  }
  countMetric("textReplacements");
  return true;
}
function setLayoutStyle(node, property, value) {
  if (!node) return false;
  const cache = node._layoutStyles || (node._layoutStyles = {});
  if (cache[property] === value) return false;
  cache[property] = value;
  node.style[property] = value;
  countMetric("layoutStyleUpdates");
  return true;
}
function renderDiagnosticReport() {
  const elapsed = Math.max(0.001, (performance.now() - renderMetrics.startedAt) / 1000);
  const samples = renderMetrics.eventToRenderDelaySamples;
  return {
    seconds: +elapsed.toFixed(2),
    events: Object.assign({}, renderMetrics.events),
    wordUpdatesReceived: renderMetrics.wordUpdatesReceived,
    wordUpdatesRendered: renderMetrics.wordUpdatesRendered,
    updatesCoalesced: renderMetrics.updatesCoalesced,
    updatesDiscarded: renderMetrics.updatesDiscarded,
    staleRevisionsIgnored: renderMetrics.staleRevisionsIgnored,
    domNodesCreated: renderMetrics.domNodesCreated,
    domNodesReplaced: renderMetrics.domNodesReplaced,
    fullLineRenders: renderMetrics.fullLineRenders,
    fullStageRenders: renderMetrics.fullStageRenders,
    animationStarts: renderMetrics.animationStarts,
    animationRestarts: renderMetrics.animationRestarts,
    displayMotionStarts: renderMetrics.displayMotionStarts,
    sequentialRevealStarts: renderMetrics.sequentialRevealStarts,
    revealQueueDelayMeanMs: renderMetrics.revealQueueDelaySamples ?
      +(renderMetrics.revealQueueDelayTotalMs /
        renderMetrics.revealQueueDelaySamples).toFixed(2) : 0,
    revealQueueDelayMaxMs: +renderMetrics.revealQueueDelayMaxMs.toFixed(2),
    maxSimultaneousReveals: renderMetrics.maxSimultaneousReveals,
    sourceMotionStarts: renderMetrics.sourceMotionStarts,
    characterEntryStarts: renderMetrics.characterEntryStarts,
    characterEntryRestarts: renderMetrics.characterEntryRestarts,
    characterAnimationsStarted: renderMetrics.characterAnimationsStarted,
    wordColorSweeps: renderMetrics.wordColorSweeps || 0,
    syllableColorSweeps: renderMetrics.syllableColorSweeps || 0,
    eventToRenderDelayMeanMs: samples ?
      +(renderMetrics.eventToRenderDelayTotalMs / samples).toFixed(2) : 0,
    eventToRenderDelayMaxMs: +renderMetrics.eventToRenderDelayMaxMs.toFixed(2),
    longTasks: renderMetrics.longTasks,
    longTaskTotalMs: +renderMetrics.longTaskTotalMs.toFixed(2),
    queueDepth: renderMetrics.queueDepth,
    maxQueueDepth: renderMetrics.maxQueueDepth,
    layoutStyleUpdates: renderMetrics.layoutStyleUpdates,
    speakerRecolors: renderMetrics.speakerRecolors,
    textReplacements: renderMetrics.textReplacements,
    levelFrames: renderMetrics.levelFrames,
    motionTrace: renderMetrics.motionTrace.slice()
  };
}
window.__cwiRenderDiag = {
  metrics: renderMetrics,
  report: renderDiagnosticReport
};
if (renderDiagEnabled) {
  if (renderDiagVisible) renderDiagEl.hidden = false;
  window.setInterval(() => {
    const report = renderDiagnosticReport();
    if (renderDiagVisible) renderDiagEl.textContent = JSON.stringify(report, null, 2);
    if (CFG.debug_render) console.debug("[cwi-render]", report);
  }, Math.max(250, CFG.diagnostic_interval_ms || 1000));
  if (typeof PerformanceObserver !== "undefined") {
    try {
      new PerformanceObserver(list => {
        list.getEntries().forEach(entry => {
          countMetric("longTasks");
          countMetric("longTaskTotalMs", entry.duration);
        });
      }).observe({type: "longtask", buffered: true});
    } catch (_) {
      // Long Task API is optional. All structural counters remain available.
    }
  }
}

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
const levelFill = document.getElementById("levelFill");
const levelFloor = document.getElementById("levelFloor");
const levelDb = document.getElementById("levelDb");
const levelGain = document.getElementById("levelGain");
const inputStatus = document.getElementById("inputStatus");
const voiceCompass = document.getElementById("voiceCompass");
const compassLevel = document.getElementById("compassLevel");
const compassPitch = document.getElementById("compassPitch");
const compassDirection = document.getElementById("compassDirection");
const mediaClock = RenderCore.createMediaClock({
  smoothing: (CFG.live_sync || {}).clock_smoothing,
  resetThreshold: (CFG.live_sync || {}).clock_reset_threshold_s
});
function updateInputLevel(ev) {
  const pct = db => (clamp01((db + 72) / 72) * 100).toFixed(1) + "%";
  levelFill.style.width = pct(ev.rms_db);
  levelFloor.style.left = pct(ev.floor_db);
  levelDb.textContent = ev.rms_db.toFixed(1) + " dBFS";
  levelGain.textContent =
    (ev.gain_db > 0 ? "+" : "") + ev.gain_db.toFixed(1) + " dB to ASR";
  inputCard.dataset.status = ev.status;
  inputStatus.textContent = INPUT_LABEL[ev.status] || ev.status;
  noteRealtimePitch(ev);
}
let pendingLevel = null;
let levelFrame = 0;
function flushLevelFrame() {
  levelFrame = 0;
  const latest = pendingLevel;
  pendingLevel = null;
  if (!latest) return;
  updateInputLevel(latest);
  updateIntentCircle(latest);
  countMetric("levelFrames");
}
function queueLevelEvent(ev) {
  mediaClock.observe(ev.t, ev._received_perf);
  pendingLevel = ev;
  if (levelFrame) return;
  levelFrame = requestAnimationFrame(flushLevelFrame);
}
function speakerStatus(ev) {
  if (ev.speaker_status) return ev.speaker_status;
  return ev.speaker_known === false ? "unknown" : "stable";
}
function escTitle(ev) {
  return ev.loudness_db + " dB · " + ev.pitch_hz + " Hz · " +
    Math.round(ev.conf * 100) + "% · speaker " + speakerStatus(ev);
}

const CIRCLE_VOLUME_DB = CFG.intent_circle_volume_db || [-60, -15];
const CIRCLE_PITCH_HZ = CFG.intent_circle_pitch_hz || [80, 250];
const CIRCLE_BRIGHTNESS_HZ = CFG.intent_circle_brightness_hz || [500, 3500];
const CIRCLE_SMOOTHING = clamp01(Number(CFG.intent_circle_smoothing ?? 0.24));
let latestVoiceEvent = null;
function domain01(value, domain, fallback) {
  const lo = Number(domain[0]), hi = Number(domain[1]);
  if (!Number.isFinite(value) || !(hi > lo)) return fallback;
  return clamp01((value - lo) / (hi - lo));
}
function paintVoiceIndicator(circle, ev, large) {
  if (!circle) return;
  const target = {
    volume: domain01(Number(ev.rms_db), CIRCLE_VOLUME_DB, 0),
    pitch: domain01(Number(ev.pitch_hz), CIRCLE_PITCH_HZ, 0.5),
    brightness: domain01(
      Number(ev.spectral_centroid_hz), CIRCLE_BRIGHTNESS_HZ, 0.35
    ),
    periodicity: clamp01(Number(ev.pitch_confidence || 0))
  };
  const state = circle._voiceState || {
    volume: target.volume, pitch: target.pitch,
    brightness: target.brightness, periodicity: target.periodicity
  };
  for (const key of Object.keys(target)) {
    state[key] += (target[key] - state[key]) * CIRCLE_SMOOTHING;
  }
  circle._voiceState = state;
  const speaking = ev.speech === true;
  const scale = 0.72 + state.volume * 0.68;
  const pitchY = 79 - state.pitch * 58; // high voice rises; low voice settles
  const textureX = 0.62 + state.brightness * 0.90;
  const voiceX = 0.96 + state.brightness * 0.10;
  const voiceY = 1.06 - state.brightness * 0.10;
  if (large) {
    circle.style.setProperty(
      "--compass-scale", (0.82 + state.volume * 0.32).toFixed(3)
    );
    circle.style.setProperty(
      "--compass-halo",
      (state.volume * state.periodicity * 34).toFixed(1) + "px"
    );
    circle.style.setProperty(
      "--texture-size", (0.72 + state.volume * 0.50).toFixed(3)
    );
  } else {
    circle.style.setProperty("--voice-scale", scale.toFixed(3));
    circle.style.setProperty("--voice-x", voiceX.toFixed(3));
    circle.style.setProperty("--voice-y", voiceY.toFixed(3));
    circle.style.setProperty("--voice-opacity", speaking ? ".96" : ".30");
    circle.style.setProperty(
      "--voice-halo", (state.volume * state.periodicity * 11).toFixed(1) + "px"
    );
  }
  circle.style.setProperty("--pitch-y", pitchY.toFixed(1) + "%");
  circle.style.setProperty("--texture-x", textureX.toFixed(3));
  circle.style.setProperty(
    "--texture-angle", (-18 + state.brightness * 36).toFixed(1) + "deg"
  );
  circle.style.setProperty(
    "--texture-opacity", (0.10 + state.periodicity * 0.46).toFixed(3)
  );
  const pitchLabel = ev.pitch_hz > 0
    ? Math.round(ev.pitch_hz) + " Hz"
    : "unvoiced";
  const label = "Voice: " + Number(ev.rms_db).toFixed(1) +
    " dB, " + pitchLabel;
  circle.title = label;
  circle.setAttribute("aria-label", label);
}

// The active line indicator stays physically next to the text. The larger
// sidebar compass mirrors the same live voice and reserves its angular channel
// for a future multi-microphone azimuth; no angle is fabricated on mono input.
function updateIntentCircle(ev) {
  latestVoiceEvent = ev;
  paintVoiceIndicator(current && current.circle, ev, false);
  paintVoiceIndicator(voiceCompass, ev, true);
  if (compassLevel) {
    compassLevel.textContent = Number(ev.rms_db).toFixed(1) + " dB";
  }
  if (compassPitch) {
    compassPitch.textContent = ev.pitch_hz > 0
      ? Math.round(ev.pitch_hz) + " Hz"
      : "unvoiced";
  }
  const rawDirection = ev.direction_deg ?? ev.azimuth_deg;
  const direction = Number(rawDirection);
  const known = Number.isFinite(direction);
  if (voiceCompass) {
    voiceCompass.dataset.direction = known ? "known" : "unknown";
    if (known) {
      voiceCompass.style.setProperty(
        "--direction-angle", (((direction % 360) + 360) % 360).toFixed(1) + "deg"
      );
    }
  }
  if (compassDirection) {
    compassDirection.dataset.known = known ? "true" : "false";
    compassDirection.textContent = known
      ? Math.round(((direction % 360) + 360) % 360) + "°"
      : "awaiting array";
  }
}

const speakerColor = {};
function colorFor(spk) {
  if (!(spk in speakerColor)) speakerColor[spk] = CFG.palette[Object.keys(speakerColor).length % CFG.palette.length];
  return speakerColor[spk];
}
function mixHex(from, to, amount) {
  const rgb = value => [1, 3, 5].map(i => parseInt(value.slice(i, i + 2), 16));
  const a = rgb(from), b = rgb(to), f = clamp01(amount);
  return "#" + a.map((v, i) =>
    Math.round(v + (b[i] - v) * f).toString(16).padStart(2, "0")
  ).join("");
}
function attributionColor(ev) {
  const status = speakerStatus(ev);
  if (status === "unknown") return "#F4F2EA";
  if (status === "provisional") {
    return mixHex("#F4F2EA", colorFor(ev.speaker), CFG.provisional_color_strength);
  }
  return colorFor(ev.speaker);
}
function applyAttributionState(el, ev) {
  const status = speakerStatus(ev);
  // Ensure this speaker owns a palette colour before the shared sweep reads it
  // (mixColor looks the speaker up in motionCtx.cfg.speakers === speakerColor).
  if (status !== "unknown" && ev.speaker) colorFor(ev.speaker);
  const revision = String(ev.speaker_revision_id || 0);
  if (el.dataset.speakerStatus !== status) el.dataset.speakerStatus = status;
  if (el.dataset.speakerRevision !== revision) el.dataset.speakerRevision = revision;
  el.classList.toggle("speaker-unknown", status === "unknown");
  el.classList.toggle("speaker-provisional", status === "provisional");
  el.classList.toggle("speaker-stable", status === "stable");
  el.classList.toggle("speaker-corrected", status === "corrected");
  const label = status === "unknown" ? "speaker uncertain" :
    ev.speaker + " speaker attribution " + status;
  const aria = ev.text + " · " + label;
  if (el.getAttribute("aria-label") !== aria) el.setAttribute("aria-label", aria);
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
const realtimePitchHistory = [];
function noteRealtimePitch(ev) {
  if (!(ev.pitch_hz > 0) || Number(ev.pitch_confidence || 0) < 0.32) return;
  realtimePitchHistory.push(Number(ev.pitch_hz));
  if (realtimePitchHistory.length > 32) realtimePitchHistory.shift();
  // Level frames exist before the first read-ahead word. Seeding the baseline
  // here prevents early words from anchoring to their own pitch and therefore
  // producing no temporary weight change at all.
  if (typeof motionCtx !== "undefined") {
    motionCtx.medianPitch = baselinePitch();
  }
}
function notePitch(ev) {
  if (!(ev.pitch_hz > 0) || ev.voiced_frac < CFG.min_voiced_frac) return;
  pitchHistory.push(ev.pitch_hz);
  if (pitchHistory.length > EX.baseline_words) pitchHistory.shift();
}
function baselinePitch() {
  const values = pitchHistory.length >= 3
    ? pitchHistory.concat(realtimePitchHistory.slice(-16))
    : realtimePitchHistory.concat(pitchHistory);
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[sorted.length >> 1];
}
// ---------------------------------------------------------------------------
// THE SHARED CWI MOTION ENGINE. Live and cc share the acoustic-to-type map,
// synchronization primitive, per-character sweep and neighbour math from
// cwi_motion_core.js. They deliberately do not share presentation timing:
// authored cc knows every word up front and plays the reference envelope off
// the media clock; stacked live uses independent size/weight/width envelopes
// on the bounded first-paint clock below. `motionCtx` is mutable because live
// keeps its running medians and reduced-motion state on it.
// ---------------------------------------------------------------------------
const loudnessHistory = [];
const motionCtx = {
  cfg: Object.assign({}, CFG.motion_core, {speakers: speakerColor}),
  mapping: CFG.mapping,
  // Live uses the deliberately compressed live response. Applying cc's full
  // reference-only axis overrides here made ordinary connected speech explode
  // to shout size (for example "without" in the bundled sample).
  expression: Object.assign({}, CFG.expression, {
    // Resting transcript typography stays neutral; while a word is active,
    // retain enough of pitch/harmonics to make high/thin and low/full voices
    // visibly distinct. The global expression values remain the calmer
    // long-lived/sidebar mapping.
    size_response: Number(CFG.live_sync.size_response ?? 0.78),
    weight_response: Number(CFG.live_sync.pitch_response ?? 1.0),
    width_response: Number(CFG.live_sync.width_response ?? 0.75)
  }),
  medianLoudness: 0.5,
  medianPitch: null,
  charSweep: true,      // live always sweeps colour per character (2.2.4)
  waveOn: !reducedMotion.matches,
  reduced: reducedMotion.matches
};
const MO = window.CWIMotion.create(motionCtx);
reducedMotion.addEventListener?.("change", () => {
  motionCtx.reduced = reducedMotion.matches;
  motionCtx.waveOn = !reducedMotion.matches;
});
// A word's loudness/pitch feed the running medians ONLY when it commits, so a
// tentative read-ahead word that may be revised away never biases the scale a
// settled word was measured against. Medians move the ANCHOR for words not yet
// frozen; a word's own `_type` is first-write-wins, so a later median shift can
// never restyle it (THE CAPTION INVARIANT).
function noteProsody(ev) {
  const l = clamp01(ev.loudness);
  loudnessHistory.push(l);
  if (loudnessHistory.length > EX.baseline_words) loudnessHistory.shift();
  const sorted = loudnessHistory.slice().sort((a, b) => a - b);
  motionCtx.medianLoudness = sorted.length ? sorted[sorted.length >> 1] : 0.5;
  motionCtx.medianPitch = baselinePitch();
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
  if (ev.word_id) return String(ev.word_id);
  return "legacy:" + Number(ev.utterance || 0) + ":" +
    Math.round(Number(ev.t || ev.start || 0) * 1000) + ":" +
    String(ev.text || "").toLocaleLowerCase();
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
  // relabels landed — the within-line size ping-pong. Cache by semantic word
  // ID so simultaneous decoder slots do not accidentally share one voice
  // shape, while a speaker relabel still cannot re-derive geometry.
  // FIRST WRITE WINS. The old graded cache re-resolved a word at verification,
  // which both resized it on screen AND pushed the same word into the running
  // median a second time — corrupting the size of every word after it.
  const key = slotKey(ev);
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
// The word's cc `_type` = {restPct, emphScale, emphWght, restWght, wdth}.
// First-write-wins per semantic word: its resting typography and envelope
// amplitudes are frozen when first painted, so neither a later median shift nor
// a revision can restyle a settled word (THE CAPTION INVARIANT). The key is not
// speaker-dependent, so a later attribution decision remains geometry-neutral.
const ccTypeCache = new Map();
function ccTypeOf(ev) {
  const key = slotKey(ev);
  let t = ccTypeCache.get(key);
  if (t) return t;
  const source = MO.typeOf(ev);
  // Live-only presentation: measured variation exists only while the word is
  // active. Every completed word returns to one neutral font, so the stacked
  // transcript carries no persistent size, weight or width effect.
  const strength = clamp01(Number(LS.prosody_strength ?? 0.78));
  // Live weight must remain visible inside a short transient. Unlike a
  // normalized interpolation fraction, this is intentionally allowed above
  // 1.0 to expand the measured pitch delta around Regular 400.
  const weightStrength = clamp(
    Number(LS.font_weight_strength ?? 1.70), 0, 2
  );
  const widthStrength = clamp01(Number(LS.font_width_strength ?? 0.90));
  const restPct = Number(motionCtx.cfg.size_pct || 5);
  const restWght = 400;
  const restWdth = 100;
  // The transcript's narrow range is a RESTING legibility rule. During the
  // one permitted motion window, allow a wider transient excursion so weight
  // is actually audible; the frame loop still lands at Regular 400 exactly.
  const weightRange = LS.active_weight_range || [180, 700];
  const widthRange = EX.wdth_range || [75, 125];
  const minEmphasisScale = Number(LS.min_emphasis_scale ?? 0.78);
  const maxEmphasisScale = Number(LS.max_emphasis_scale ?? 1.34);
  const emphScale = clamp(
    1 + (source.emphScale - 1) * strength,
    minEmphasisScale,
    maxEmphasisScale
  );
  const liftGain = clamp(
    Number(LS.lift_base_gain ?? 0.82) +
      (emphScale - 1) * Number(LS.lift_prosody_gain ?? 2.8),
    Number(LS.lift_min_gain ?? 0.28),
    Number(LS.lift_max_gain ?? 1.40)
  );
  t = Object.assign({}, source, {
    restPct: restPct,
    restWght: restWght,
    restWdth: restWdth,
    wdth: restWdth,
    emphScale: emphScale,
    emphWght: Math.round(clamp(
      restWght + (source.emphWght - restWght) * weightStrength,
      weightRange[0], weightRange[1]
    ) / 4) * 4,
    emphWdth: Math.round(clamp(
      restWdth + (source.wdth - restWdth) * widthStrength,
      widthRange[0], widthRange[1]
    )),
    liftGain: liftGain,
    motionKind: emphScale < 0.96 ? "quiet" :
      (emphScale > 1.10 ? "strong" :
       (source.emphWght < 360 ? "bright" :
        (source.emphWght > 450 ? "grounded" : "neutral")))
  });
  ccTypeCache.set(key, t);
  if (ccTypeCache.size > 400) ccTypeCache.delete(ccTypeCache.keys().next().value);
  return t;
}
function applyTypography(el, ev, advance) {
  // All resting words share normal typography. Prosody modifies transform and
  // weight only inside the one-time motion window.
  const t = ccTypeOf(ev);
  el._type = t;
  setLayoutStyle(
    el, "fontSize",
    (t.restPct / 100 * stage.clientHeight).toFixed(1) + "px"
  );
  setLayoutStyle(
    el, "fontVariationSettings",
    '"opsz" 14, "wght" ' + t.restWght + ', "wdth" ' + t.wdth
  );
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
function paintSynchronizedColorFill(fill, boundary) {
  const chars = fill.chars;
  const n = Math.max(1, chars.length);
  for (let i = 0; i < chars.length; i++) {
    // Move a soft boundary through the existing glyph spans. A character near
    // the boundary crossfades instead of flipping, while every span keeps its
    // own layout box—unlike the broken parent background-clip implementation.
    const local = clamp01(boundary * n - i);
    setStyle(
      chars[i],
      "color",
      "_c",
      mixHex("#F4F2EA", fill.spoken, local)
    );
  }
}
function finishSynchronizedColorFill(fill) {
  paintSynchronizedColorFill(fill, 1);
  fill.glyph.classList.remove("syllabic");
}
function stepFills(now) {
  fillFrame = 0;
  activeFills.forEach(fill => {
    const p = (now - fill.started) / fill.duration;
    if (p >= 1 || !fill.glyph.isConnected) {
      if (fill.glyph.isConnected) finishSynchronizedColorFill(fill);
      activeFills.delete(fill);
      return;
    }
    paintSynchronizedColorFill(
      fill,
      fillAt(fill.stops, Math.max(0, p))
    );
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
      finishSynchronizedColorFill(fill);
      activeFills.delete(fill);
    }
  });
  document.querySelectorAll(".cwi-glyph.syllabic").forEach(glyph => {
    let active = false;
    activeFills.forEach(fill => { if (fill.glyph === glyph) active = true; });
    if (!active) {
      glyph.classList.remove("syllabic");
      const el = glyph.parentElement;
      if (el && el._captionEvent) {
        const color = attributionColor(el._captionEvent);
        glyph.querySelectorAll(".cwi-ch").forEach(char => {
          setStyle(char, "color", "_c", color);
        });
      }
    }
  });
}, 1500);
function startSynchronizedColorFill(el, ev) {
  const glyph = el.querySelector(".cwi-glyph");
  if (!glyph) return false;
  const syllabic = Array.isArray(ev.syllables) && ev.syllables.length >= 2;
  const duration = syllabic
    ? clamp(Math.max(0, ev.end - ev.start) * 1000, 180, 900)
    : clamp(
        CFG.motion_color_turn_ms + Math.max(70, glyph.textContent.length * 12),
        150,
        280
      );
  if (!(duration > 0)) return false;
  const stops = syllabic
    ? ev.syllables
    : [{t: 0, c: 0}, {t: 1, c: 1}];
  glyph.classList.add("syllabic");
  activeFills.forEach(fill => { if (fill.glyph === glyph) activeFills.delete(fill); });
  const fill = {
    glyph: glyph,
    chars: Array.from(glyph.querySelectorAll(".cwi-ch")),
    spoken: attributionColor(ev),
    stops: stops,
    started: performance.now(),
    duration: duration
  };
  paintSynchronizedColorFill(fill, 0);
  activeFills.add(fill);
  if (!fillFrame) fillFrame = requestAnimationFrame(stepFills);
  countMetric(syllabic ? "syllableColorSweeps" : "wordColorSweeps");
  return true;
}
function stopSynchronizedColorFill(el) {
  const glyph = el && el.querySelector(".cwi-glyph");
  if (!glyph) return;
  activeFills.forEach(fill => {
    if (fill.glyph === glyph) activeFills.delete(fill);
  });
  glyph.classList.remove("syllabic");
}
// Colour has its own clock and never owns geometry. If attribution arrives
// during the one allowed real-time motion, its white→speaker-colour boundary
// travels through the word immediately; a drawn-out word uses its measured
// syllable stops. A late decision on an already-settled word is a direct colour
// write. Neither path can start or restart motion.
function applySpokenColor(el, ev, animate) {
  applyAttributionState(el, ev);
  if (el.dataset.revealPending === "true") {
    el._pendingSpokenEvent = ev;
    el.dataset.colorPending = "true";
    return;
  }
  const moving = el.dataset.moving === "true";
  if (!moving) {
    // A delayed attribution decision is strictly a colour operation. Seal an
    // already-visible word at rest so no later path can reinterpret it as
    // first paint.
    consumeWordMotion(el, ev);
    el.dataset.moved = "true";
    setTf(el, MO.wordTransform(0, 0, 1));
    stopSynchronizedColorFill(el);
  }
  el.dataset.turned = "true";
  el.dataset.colorPending = "";
  el._pendingSpokenEvent = null;
  if (moving && startSynchronizedColorFill(el, ev)) return;
  const node = ccNodeOf(el);
  const vt = (node.w.end || 0) + 999;         // fully past its turn = full colour
  let wrote = false;
  for (let ci = 0; ci < node.chars.length; ci++) {
    const before = node.chars[ci]._c;
    setStyle(node.chars[ci], "color", "_c", MO.charColorAt(node, ci, vt));
    if (node.chars[ci]._c !== before) wrote = true;
  }
  if (wrote) countMetric("speakerRecolors");
}
function flushPendingSpokenColor(el) {
  if (!el || el.dataset.colorPending !== "true" ||
      el.dataset.revealPending === "true") return;
  applySpokenColor(el, el._pendingSpokenEvent || el._captionEvent, false);
}
// ---------------------------------------------------------------------------
// Live CWI motion (2.2.3), built on the pure `cc` motion engine. A single rAF
// loop animates ONLY the active-word window. The wrapper carries word-wide
// intonation plus the base synchronization cue; its already-visible character
// spans carry the left-to-right synchronization hand-off measured in
// synchronization.mov. Stacked live captions disable neighbour-push, so each
// new word moves by itself and every previously written word remains fixed.
// Transforms stay off the layout path and every wrapper/character returns to
// exact rest once.
const LS = CFG.live_sync || {enabled: false};
const LIVE_MOTION = !!LS.enabled;
const motionRecs = new Set();       // {el, line} for words in their active window
const motionLines = new Set();
let motionRAF = 0;
const MAX_SIMULTANEOUS_REVEALS = Math.max(
  1, Number(CFG.max_simultaneous_reveals || 2)
);
const WORD_REVEAL_GAP_MS = Math.max(16, Number(CFG.word_reveal_gap_ms || 140));
const WORD_REVEAL_GAP_MIN_MS = Math.max(
  16, Number(CFG.word_reveal_gap_min_ms || 80)
);
const WORD_REVEAL_GAP_MAX_MS = Math.max(
  WORD_REVEAL_GAP_MIN_MS, Number(CFG.word_reveal_gap_max_ms || 260)
);
const WORD_REVEAL_TIMING_STRENGTH = clamp01(
  Number(CFG.word_reveal_timing_strength ?? 0.75)
);
const WORD_REVEAL_CATCHUP_GAP_MS = Math.max(
  16, Number(CFG.word_reveal_catchup_gap_ms || 60)
);
const WORD_MOTION_DURATION_MS = Math.max(
  WORD_REVEAL_GAP_MS, Number(CFG.word_motion_duration_ms || 520)
);
const WORD_MOTION_MAX_DURATION_MS = Math.max(
  WORD_MOTION_DURATION_MS,
  Number(CFG.word_motion_max_duration_ms || 720)
);
const WORD_MOTION_SPAN_STRETCH = Math.max(
  0, Number(CFG.word_motion_span_stretch ?? 0.42)
);
const ONSET_MOTION_DURATION_MS = Math.max(
  WORD_MOTION_DURATION_MS, Number(CFG.onset_motion_duration_ms || 680)
);
const WORD_MOTION_SOURCE_SPAN_S = Math.max(
  0.04, Number(CFG.word_motion_source_span_s || 0.14)
);
const CHARACTER_WAVE_STEP_S = Math.max(
  0.02, Number(LS.character_wave_step_s || 0.11)
);
const CHARACTER_WAVE_MAX_SPAN_S = Math.max(
  WORD_MOTION_SOURCE_SPAN_S,
  Number(LS.character_wave_max_span_s || 1.10)
);
const CHARACTER_WAVE_SPATIAL_SMOOTHING = clamp01(
  Number(LS.character_wave_spatial_smoothing ?? 0.72)
);
const WORD_REVEAL_FADE_MS = Math.max(
  0, Number(CFG.word_reveal_fade_ms || 220)
);
const sequentialRevealQueue = [];
let sequentialRevealTimer = 0;
let nextSequentialRevealAt = 0;
// `dataset.moved` protects one DOM node. Endpoint verification can legitimately
// replace that node, though, so remember the semantic word as well. Otherwise a
// correction that recreates uN:wM can make an old caption move a second time.
const consumedMotionWordIds = new Set();
const MOTION_HISTORY_LIMIT = Math.max(
  256, Number(CFG.render_queue_limit || 512) * 4
);

function motionHistoryKey(el, ev) {
  if (el && el.dataset && el.dataset.wordId) return el.dataset.wordId;
  return ev ? RenderCore.wordKey(ev) : "";
}
function motionWasConsumed(el, ev) {
  const key = motionHistoryKey(el, ev);
  return key ? consumedMotionWordIds.has(key) : false;
}
function consumeWordMotion(el, ev) {
  const key = motionHistoryKey(el, ev);
  if (!key || consumedMotionWordIds.has(key)) return key;
  consumedMotionWordIds.add(key);
  while (consumedMotionWordIds.size > MOTION_HISTORY_LIMIT) {
    const oldest = consumedMotionWordIds.values().next().value;
    if (oldest === undefined) break;
    consumedMotionWordIds.delete(oldest);
  }
  return key;
}

function activeRevealCount() {
  let count = 0;
  motionRecs.forEach(rec => {
    if (rec.el.isConnected && rec.el.dataset.moving === "true") count += 1;
  });
  return count;
}
function scheduleSequentialReveal(delayMs) {
  if (sequentialRevealTimer || !sequentialRevealQueue.length) return;
  sequentialRevealTimer = window.setTimeout(() => {
    sequentialRevealTimer = 0;
    drainSequentialReveal();
  }, Math.max(0, delayMs || 0));
}
function revealGapBetween(currentEvent, nextEvent) {
  if (!currentEvent || !nextEvent ||
      Number(currentEvent.utterance) !== Number(nextEvent.utterance)) {
    return WORD_REVEAL_GAP_MS;
  }
  const from = Number(currentEvent.t ?? currentEvent.start);
  const to = Number(nextEvent.t ?? nextEvent.start);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) {
    return WORD_REVEAL_GAP_MS;
  }
  const acoustic = clamp(
    (to - from) * 1000,
    WORD_REVEAL_GAP_MIN_MS,
    WORD_REVEAL_GAP_MAX_MS
  );
  return lerp(WORD_REVEAL_GAP_MS, acoustic, WORD_REVEAL_TIMING_STRENGTH);
}
function queueSequentialReveal(el, ev, animate) {
  if (!el || el.dataset.revealed === "true") return;
  const existing = sequentialRevealQueue.find(item => item.el === el);
  if (existing) {
    existing.ev = ev;
    // Verification can demote a pending live activation to a settled reveal;
    // no later event may turn it back into delayed motion.
    if (animate === false) existing.animate = false;
    return;
  }
  el.dataset.revealPending = "true";
  // Visibility preserves the measured line width while preventing a decoder
  // batch from flashing all of its words onto the stage together.
  el.style.visibility = "hidden";
  el.style.opacity = "0";
  sequentialRevealQueue.push({el: el, ev: ev, animate: animate !== false});
  sequentialRevealQueue.sort((a, b) =>
    Number(a.ev.t ?? a.ev.start ?? 0) - Number(b.ev.t ?? b.ev.start ?? 0)
  );
  scheduleSequentialReveal(0);
}
function settleQueuedReveal(el, ev) {
  if (!el || el.dataset.revealed === "true") return;
  consumeWordMotion(el, ev || el._captionEvent);
  el.dataset.moved = "true";
  setTf(el, MO.wordTransform(0, 0, 1));
  queueSequentialReveal(el, ev || el._captionEvent, false);
}
function drainSequentialReveal() {
  while (sequentialRevealQueue.length &&
         !sequentialRevealQueue[0].el.isConnected) {
    sequentialRevealQueue.shift();
  }
  if (!sequentialRevealQueue.length) return;
  const now = performance.now();
  if (now < nextSequentialRevealAt) {
    scheduleSequentialReveal(nextSequentialRevealAt - now);
    return;
  }
  const next = sequentialRevealQueue[0];
  const motionEvent = next.el._captionEvent || next.ev;
  // Eligibility belongs to first visual appearance, not the event stage. At
  // startup the first sentence may arrive as commit/verification before any
  // hypothesis; it still deserves its one motion. A visible word has `moved`
  // sealed and its semantic ID is consumed, so even a replacement node can
  // never enter this path again when colour or verification arrives later.
  let animateNow = next.animate &&
    next.el.dataset.moved !== "true" &&
    !motionWasConsumed(next.el, motionEvent) &&
    motionEvent && motionEvent._replay !== true;
  const activeCount = activeRevealCount();
  if (animateNow && activeCount >= MAX_SIMULTANEOUS_REVEALS) {
    // The fixed motion window ends naturally at the same time the third word
    // becomes eligible. If its final rAF has not landed yet, wait one frame
    // instead of snapping the oldest word to rest. This is the smooth handoff.
    scheduleSequentialReveal(16);
    return;
  }
  sequentialRevealQueue.shift();
  const el = next.el;
  if (!el.isConnected) {
    scheduleSequentialReveal(0);
    return;
  }
  el.style.visibility = "";
  el.style.setProperty("--reveal-fade", WORD_REVEAL_FADE_MS + "ms");
  el.dataset.revealPending = "";
  el.dataset.revealed = "true";
  if (animateNow) {
    playWordMotion(el, motionEvent, {displayOnCreate: true});
  } else {
    consumeWordMotion(el, motionEvent);
    el.dataset.moved = "true";
    setTf(el, MO.wordTransform(0, 0, 1));
  }
  flushPendingSpokenColor(el);
  requestAnimationFrame(() => {
    if (el.dataset.revealed === "true") el.style.opacity = "1";
  });
  countMetric("sequentialRevealStarts");
  renderMetrics.revealQueueDelayTotalMs += queueDelay;
  renderMetrics.revealQueueDelaySamples += 1;
  renderMetrics.revealQueueDelayMaxMs =
    Math.max(renderMetrics.revealQueueDelayMaxMs, queueDelay);
  const nextEvent = sequentialRevealQueue.length
    ? (sequentialRevealQueue[0].el._captionEvent ||
       sequentialRevealQueue[0].ev)
    : null;
  const nextGap = revealGapBetween(motionEvent, nextEvent);
  const currentDeadline = nextSequentialRevealAt > 0
    ? nextSequentialRevealAt
    : now;
  if (sequentialRevealQueue.length) {
    // Preserve the original deadline even when this word started late. The
    // former `performance.now() + gap` compounded every wait behind the
    // two-motion cap. A small minimum interval keeps catch-up sequential.
    nextSequentialRevealAt = RenderCore.nextRevealDeadline(
      currentDeadline,
      performance.now(),
      nextGap,
      WORD_REVEAL_CATCHUP_GAP_MS
    );
    scheduleSequentialReveal(nextSequentialRevealAt - performance.now());
  } else {
    // Do not carry a stale gap into a later decoder update.
    nextSequentialRevealAt = 0;
  }
}
function resetSequentialReveals() {
  if (sequentialRevealTimer) clearTimeout(sequentialRevealTimer);
  sequentialRevealTimer = 0;
  sequentialRevealQueue.forEach(item => {
    const el = item.el;
    if (!el.isConnected) return;
    el.style.visibility = "";
    el.style.opacity = "1";
    el.dataset.revealPending = "";
    el.dataset.revealed = "true";
    consumeWordMotion(el, el._captionEvent);
    el.dataset.moved = "true";
    setTf(el, MO.wordTransform(0, 0, 1));
    flushPendingSpokenColor(el);
  });
  sequentialRevealQueue.length = 0;
  nextSequentialRevealAt = 0;
}
function setTf(el, s) {
  if (el._mt !== s) {
    el._mt = s;
    el.style.transform = s;
  }
}
// A cached style write: writing an unchanged value still forces a style recalc,
// and font-variation-settings recalcs relay out the (frozen-width) box. Skip.
function setStyle(el, prop, key, value) {
  if (el[key] === value) return;
  el[key] = value;
  el.style[prop] = value;
}
function settleCharacterGeometry(el) {
  if (!el) return;
  el.querySelectorAll(".cwi-ch").forEach(char => {
    setStyle(char, "transform", "_tf", "none");
  });
}
function smoothCharacterChannel(values) {
  if (values.length < 2 || CHARACTER_WAVE_SPATIAL_SMOOTHING <= 0) {
    return values;
  }
  const blurred = values.map((value, index) => {
    const left = values[Math.max(0, index - 1)];
    const right = values[Math.min(values.length - 1, index + 1)];
    return (left + value * 2 + right) / 4;
  });
  return values.map((value, index) => lerp(
    value, blurred[index], CHARACTER_WAVE_SPATIAL_SMOOTHING
  ));
}
// Each word carries a `cc node` view {el, w, chars} that the shared engine
// consumes, plus its measured resting width/row for optional neighbour-push. Rebuilt
// whenever the word's text (and so its char spans) changes.
function ccNodeOf(el) {
  const chars = el.querySelectorAll(".cwi-ch");
  let node = el._ccNode;
  if (!node || node.w !== el._captionEvent || node.chars.length !== chars.length) {
    node = el._ccNode = {el: el, w: el._captionEvent, chars: Array.from(chars)};
  }
  return node;
}
function displayMotionWord(el) {
  const source = el._captionEvent;
  let motion = el._displayMotionWord;
  if (!motion || motion._source !== source) {
    motion = Object.assign({}, source, {
      // The wrapper clock stays compact and independent of spelling length.
      // Feeding the alphabet span into this clock compressed the wrapper's
      // attack on long words and made it look like a hard jab.
      end: Number(source.start) + WORD_MOTION_SOURCE_SPAN_S,
      motion: null,
      _source: source
    });
    el._displayMotionWord = motion;
  }
  return motion;
}
function displayCharacterMotionWord(el) {
  const source = el._captionEvent;
  let motion = el._displayCharacterMotionWord;
  if (!motion || motion._source !== source) {
    const letterCount = Math.max(1, Array.from(String(source.text || "")).length);
    const characterSpan = clamp(
      Math.max(WORD_MOTION_SOURCE_SPAN_S, letterCount * CHARACTER_WAVE_STEP_S),
      WORD_MOTION_SOURCE_SPAN_S,
      CHARACTER_WAVE_MAX_SPAN_S
    );
    motion = Object.assign({}, source, {
      end: Number(source.start) + characterSpan,
      motion: null,
      _characterSpan: characterSpan,
      _source: source
    });
    el._displayCharacterMotionWord = motion;
  }
  return motion;
}
function motionDurationFor(ev) {
  if (ev && ev.src === "onset") return ONSET_MOTION_DURATION_MS;
  const span = ev
    ? Math.max(0, Number(ev.end) - Number(ev.start))
    : WORD_MOTION_SOURCE_SPAN_S;
  const stretched = WORD_MOTION_DURATION_MS +
    Math.max(0, span - WORD_MOTION_SOURCE_SPAN_S) *
      1000 * WORD_MOTION_SPAN_STRETCH;
  return clamp(
    stretched,
    WORD_MOTION_DURATION_MS,
    WORD_MOTION_MAX_DURATION_MS
  );
}
// Motion and colour have separate clocks in live mode. The motion clock starts
// on the word's first real DOM paint, which is the earliest honest instant an
// ASR-created caption can move. A later cue/commit only turns colour; it must
// never start or restart geometry.
function virtualT(el, now) {
  const w = displayMotionWord(el);
  if (el._turnPerf === undefined) return w.start - 999;
  // Decoder words have widely varying acoustic spans. Playing that raw span
  // on the display clock made long words get cut off when the third sequential
  // word arrived. Map the whole shared rise/peak/return into one fixed compact
  // window instead: it reaches rest naturally, so hand-offs stay smooth.
  const C = motionCtx.cfg;
  const from = w.start - Math.max(C.emphasis_lead_s, C.sync_rise_s);
  const to = wordSettleT(w);
  const duration = Number(el._motionDurationMs || WORD_MOTION_DURATION_MS);
  const progress = clamp01((now - el._turnPerf) / duration);
  return lerp(from, to, progress);
}
function virtualCharacterT(el, now) {
  const w = displayCharacterMotionWord(el);
  if (el._turnPerf === undefined) return w.start - 999;
  const C = motionCtx.cfg;
  const from = w.start - Math.max(
    1e-3, Number(C.char_sync_lead_s || 0.14)
  );
  const to = w.end + Math.max(
    1e-3, Number(C.char_sync_fall_s || 0.26)
  ) + 0.12;
  const duration = Number(el._motionDurationMs || WORD_MOTION_DURATION_MS);
  const progress = clamp01((now - el._turnPerf) / duration);
  return lerp(from, to, progress);
}
// The virtualT past which a word is fully back at rest: its spoken end plus the
// longest tail (intonation decay or the sync fall).
function wordSettleT(w) {
  const C = motionCtx.cfg;
  return w.end + Math.max(C.emphasis_tail_s, C.sync_fall_s) + 0.12;
}
// A voice does not change size, weight and resonance in one identical pulse.
// Use independent zero-velocity envelopes over the same honest first-paint
// window: loudness breathes through size, pitch articulates weight earlier,
// and the available resonance proxy opens/closes width later. `deliveryPace`
// comes from the acoustic word span. A drawn-out word therefore takes longer
// in milliseconds and reaches each peak later inside that longer window.
function liveEnvelope(progress, attackEnd, holdEnd, releaseEnd) {
  const p = clamp01(progress);
  const attack = clamp(attackEnd, 1e-3, 0.92);
  const hold = clamp(holdEnd, attack, 0.98);
  const release = clamp(releaseEnd, hold + 1e-3, 1);
  if (p < attack) return MO.ease(p / attack);
  if (p <= hold) return 1;
  if (p < release) return 1 - MO.ease((p - hold) / (release - hold));
  return 0;
}
function liveMotionProgress(el, now) {
  if (el._turnPerf === undefined) return 0;
  const duration = Math.max(
    1, Number(el._motionDurationMs || WORD_MOTION_DURATION_MS)
  );
  return clamp01((now - el._turnPerf) / duration);
}
function liveChannelEnvelopes(el, now) {
  const p = liveMotionProgress(el, now);
  const delivery = clamp01(Number(el._motionDeliveryPace ?? 0));
  const slowDelay = Math.max(
    0, Number(LS.slow_delivery_curve_delay ?? 0.06)
  ) * delivery;
  return {
    progress: p,
    size: liveEnvelope(
      p,
      Number(LS.size_attack_fraction ?? 0.42) + slowDelay,
      Number(LS.size_hold_fraction ?? 0.62) + slowDelay * 0.8,
      1
    ),
    weight: liveEnvelope(
      p,
      Number(LS.weight_attack_fraction ?? 0.30) + slowDelay * 0.65,
      Number(LS.weight_hold_fraction ?? 0.48) + slowDelay * 0.8,
      Number(LS.weight_release_fraction ?? 0.90) + slowDelay * 0.8
    ),
    width: liveEnvelope(
      p,
      Number(LS.width_attack_fraction ?? 0.50) + slowDelay * 0.85,
      Number(LS.width_hold_fraction ?? 0.68) + slowDelay * 0.8,
      Number(LS.width_release_fraction ?? 0.96) + slowDelay * 0.5
    )
  };
}
function liveScaleAt(el, node, vt, channels) {
  const ty = el._type;
  const paceGain = Number(el._motionPaceGain ?? 1);
  const sizeScale = 1 +
    (Number(ty.emphScale ?? 1) - 1) * channels.size * paceGain;
  const syncScale = 1 + motionCtx.cfg.sync_pop *
    MO.syncAt(vt, node.w.start) * paceGain;
  return sizeScale * syncScale;
}
function registerMotion(el, ev) {
  const line = el.closest(".cwi-line");
  if (!line) return;
  if (el.dataset.moving === "true") { countMetric("animationRestarts"); return; }
  el._turnPerf = performance.now();
  el._motionDurationMs = motionDurationFor(ev);
  const durationRange = Math.max(
    1, WORD_MOTION_MAX_DURATION_MS - WORD_MOTION_DURATION_MS
  );
  const pace = clamp01(
    (el._motionDurationMs - WORD_MOTION_DURATION_MS) / durationRange
  );
  el._motionDeliveryPace = pace;
  // Fast speech cannot afford a longer animation without making captions lag.
  // Reduce the distance travelled instead: same readable first-paint latency,
  // lower pixels/second. Slower/drawn-out words retain the full reference cue.
  el._motionPaceGain = lerp(
    clamp01(Number(LS.fast_speech_motion_gain ?? 0.58)), 1, MO.ease(pace)
  );
  el._ccNode = null;                  // rebuild against the turning text
  el.dataset.moving = "true";
  motionRecs.add({el: el, line: line});
  motionLines.add(line);
  renderMetrics.maxSimultaneousReveals = Math.max(
    renderMetrics.maxSimultaneousReveals, activeRevealCount()
  );
  countMetric("animationStarts");
  countMetric("displayMotionStarts");
  const characterMotionWord = displayCharacterMotionWord(el);
  const characterSpan = Number(characterMotionWord._characterSpan || 0);
  const characterCount = Math.max(
    1, Array.from(String(ev.text || "")).length
  );
  const characterClockSpan =
    Number(motionCtx.cfg.char_sync_lead_s || 0.18) +
    characterSpan +
    Number(motionCtx.cfg.char_sync_fall_s || 0.34) + 0.12;
  const wordClockSpan =
    Math.max(motionCtx.cfg.emphasis_lead_s, motionCtx.cfg.sync_rise_s) +
    WORD_MOTION_SOURCE_SPAN_S +
    Math.max(motionCtx.cfg.emphasis_tail_s, motionCtx.cfg.sync_fall_s) + 0.12;
  const trace = {
    wordId: RenderCore.wordKey(ev), targetOnset: Number(ev.t),
    renderStage: String(ev._render_stage || ""),
    colourAppliedAtStart: el.dataset.turned === "true",
    eventArrivalMs: Number(ev._received_perf || performance.now()),
    scheduledAnimationStartMs: el._turnPerf, actualAnimationStartMs: el._turnPerf,
    animationCompletionMs: null, restarts: 0, state: "active", trigger: "display",
    durationMs: el._motionDurationMs,
    acousticSpanMs: +(
      Math.max(0, Number(ev.end) - Number(ev.start)) * 1000
    ).toFixed(2),
    deliveryPace: +pace.toFixed(4),
    sizeAttackMs: +(el._motionDurationMs * (
      Number(LS.size_attack_fraction ?? 0.42) +
      Number(LS.slow_delivery_curve_delay ?? 0.06) * pace
    )).toFixed(2),
    weightAttackMs: +(el._motionDurationMs * (
      Number(LS.weight_attack_fraction ?? 0.30) +
      Number(LS.slow_delivery_curve_delay ?? 0.06) * pace * 0.65
    )).toFixed(2),
    widthAttackMs: +(el._motionDurationMs * (
      Number(LS.width_attack_fraction ?? 0.50) +
      Number(LS.slow_delivery_curve_delay ?? 0.06) * pace * 0.85
    )).toFixed(2),
    peakScale: +((1 + (el._type.emphScale - 1) * el._motionPaceGain) *
      (1 + motionCtx.cfg.sync_pop * el._motionPaceGain)).toFixed(4),
    peakSizeScale: +(1 + (
      el._type.emphScale - 1
    ) * el._motionPaceGain).toFixed(4),
    peakLiftEm: +(motionCtx.cfg.sync_elevation_em *
      Number(el._type.liftGain ?? 1) * el._motionPaceGain).toFixed(4),
    peakCharacterLiftEm: +Number(
      motionCtx.cfg.char_sync_lift_em * el._motionPaceGain || 0
    ).toFixed(4),
    peakCharacterScale: +(1 + Number(
      motionCtx.cfg.char_sync_pop * el._motionPaceGain || 0
    )).toFixed(4),
    characterWaveSpanS: +characterSpan.toFixed(4),
    characterTurnStepMs: +(
      el._motionDurationMs * (characterSpan / characterCount) /
      Math.max(1e-3, characterClockSpan)
    ).toFixed(2),
    wordAttackMs: +(
      el._motionDurationMs *
      (motionCtx.cfg.sync_rise_s + motionCtx.cfg.sync_peak_s) /
      Math.max(1e-3, wordClockSpan)
    ).toFixed(2),
    motionPaceGain: +el._motionPaceGain.toFixed(4),
    peakWeight: el._type.emphWght,
    weightDelta: Math.round(
      (el._type.emphWght - el._type.restWght) * el._motionPaceGain
    ),
    peakWidth: el._type.emphWdth ?? el._type.wdth,
    widthDelta: Math.round(
      (Number(el._type.emphWdth ?? el._type.wdth) -
       Number(el._type.restWdth ?? 100)) * el._motionPaceGain
    ),
    motionKind: el._type.motionKind || "neutral",
    loudness: Number(ev.loudness),
    pitchHz: Number(ev.pitch_hz || 0)
  };
  el._motionTrace = trace;
  renderMetrics.motionTrace.push(trace);
  if (renderMetrics.motionTrace.length > 128) renderMetrics.motionTrace.shift();
  if (!motionRAF) motionRAF = requestAnimationFrame(motionTick);
}
function stopCharacterEntry(el) {
  if (!el || !el._entryAnimations) return;
  el._entryAnimations.forEach(animation => animation.cancel());
  el._entryAnimations = null;
}
function startCharacterEntry(el, plan) {
  if (!el || !plan || plan.trigger !== "display" ||
      LS.character_entry_enabled === false || reducedMotion.matches) return false;
  if (el.dataset.entryStarted === "true") {
    countMetric("characterEntryRestarts");
    return false;
  }
  const chars = Array.from(el.querySelectorAll(".cwi-ch"));
  if (!chars.length) return false;
  el.dataset.entryStarted = "true";
  el.dataset.entryMotion = "active";
  const delays = RenderCore.characterEntryDelays(
    chars.map(char => char.textContent).join(""),
    LS.character_entry_stagger_s
  );
  const entryNumber = (value, fallback) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  };
  const duration = Math.max(
    1, entryNumber(LS.character_entry_duration_s, 0.24) * 1000
  );
  const startOpacity = clamp01(
    entryNumber(LS.character_entry_start_opacity, 0)
  );
  const from = "translate3d(" +
    entryNumber(LS.character_entry_slide_em, 0.22).toFixed(4) + "em," +
    entryNumber(LS.character_entry_rise_em, 0.08).toFixed(4) + "em,0) scale(" +
    Math.max(0, entryNumber(LS.character_entry_start_scale, 0.92)).toFixed(4) +
    ")";
  el._entryAnimations = chars.map((char, index) => char.animate([
    {
      opacity: String(startOpacity),
      transform: from
    },
    {
      opacity: "1",
      transform: "translate3d(0,0,0) scale(1)"
    }
  ], {
    duration: duration,
    delay: (delays[index] || 0) * 1000,
    easing: "cubic-bezier(0.18, 0.82, 0.24, 1)",
    fill: "backwards",
    iterations: 1
  }));
  countMetric("characterEntryStarts");
  countMetric("characterAnimationsStarted", chars.length);
  Promise.allSettled(el._entryAnimations.map(animation => animation.finished))
    .then(() => {
      if (el.dataset.entryMotion === "active") {
        el.dataset.entryMotion = "completed";
        el._entryAnimations = null;
      }
    });
  return true;
}
// Run the live composition for every word in a line, using the shared CWI
// primitives on each word's own virtual clock. Reads all resting widths first,
// then writes: word transform (neighbour shift + independent size × sync pop),
// transient weight/width on their own envelopes, the per-character
// synchronization wave, and the independent colour sweep. Returns true while
// any word is still animating. A settled word
// computes to rest and its writes are cache-skipped — so its only per-frame
// mutation is a position shift when a live neighbour swells (the one allowed
// relaxation of THE CAPTION INVARIANT), which the churn instrument does not
// count. The row key remains part of the shared engine contract, although a
// live caption box is nowrap and overflowing words move into a new box.
function resolveCCLine(line, now) {
  const els = Array.from(line.querySelectorAll(".cwi-word"));
  if (!els.length) return false;
  const nodes = els.map(el => {
    const node = ccNodeOf(el);
    if (el._ccRestW == null) {
      el._ccRestW = el.getBoundingClientRect().width;
      el.style.width = el._ccRestW.toFixed(2) + "px";  // freeze the box
    }
    node.restW = el._ccRestW;
    node.restRow = el.offsetTop;
    node._vt = virtualT(el, now);
    node._motionW = displayMotionWord(el);
    node._cvt = virtualCharacterT(el, now);
    node._characterMotionW = displayCharacterMotionWord(el);
    node._liveChannels = liveChannelEnvelopes(el, now);
    return node;
  });
  if (LS.neighbor_push !== false) {
    MO.resolveNeighborPush(nodes, 0, (t, n) => {
      const source = n.w;
      n.w = n._motionW;
      const scale = liveScaleAt(
        n.el, n, n._vt, n._liveChannels
      );
      n.w = source;
      return scale;
    });
  } else {
    // A new word may move only itself. Never write a transform to an older
    // settled caption merely because it shares the same stacked line.
    nodes.forEach(node => { node.shift = 0; });
  }
  let anyActive = false;
  for (const node of nodes) {
    const el = node.el, vt = node._vt, ty = el._type;
    const source = node.w;
    node.w = node._motionW;
    const paceGain = Number(el._motionPaceGain ?? 1);
    const channels = node._liveChannels;
    const scale = liveScaleAt(el, node, vt, channels);
    const lift = motionCtx.waveOn
      ? MO.liftOf(vt, node) * Number(ty.liftGain ?? 1) * paceGain
      : 0;
    const width = lerp(
      Number(ty.restWdth ?? ty.wdth ?? 100),
      Number(ty.emphWdth ?? ty.wdth ?? 100),
      channels.width * paceGain
    );
    const weight = Math.round(lerp(
      Number(ty.restWght), Number(ty.emphWght),
      channels.weight * paceGain
    ) / 4) * 4;
    setTf(el, MO.wordTransform(node.shift, lift, scale));
    setStyle(el, "fontVariationSettings", "_vf",
             '"opsz" 14, "wght" ' + weight +
             ', "wdth" ' + Math.round(width));
    // SYNCHRONIZATION.MOV: the motion boundary lands between letters. All
    // letters are present from first paint; only their baseline/pop phase is
    // staggered. Intonation above remains uniform over the whole word.
    node.w = node._characterMotionW;
    // The reference reads as one travelling ribbon, not an alternating set of
    // independent letter springs. Remove the below-baseline tooth and blend
    // adjacent samples before painting; this keeps the alphabet-level handoff
    // visible without the zipper/ziggle artifact.
    const rawLifts = node.chars.map((_, ci) =>
      Math.max(0, MO.charLiftOf(node._cvt, node, ci) * paceGain)
    );
    const rawPops = node.chars.map((_, ci) =>
      (MO.charScaleOf(node._cvt, node, ci) - 1) * paceGain
    );
    const charLifts = smoothCharacterChannel(rawLifts);
    const charPops = smoothCharacterChannel(rawPops);
    for (let ci = 0; ci < node.chars.length; ci++) {
      const charLift = charLifts[ci];
      const charScale = 1 + charPops[ci];
      setStyle(node.chars[ci], "transform", "_tf",
               MO.charTransform(charLift, charScale));
    }
    node.w = source;
    // Geometry and colour have independent clocks. When the explicit
    // synchronized fill is active it exclusively owns character colour;
    // otherwise keep read-ahead white or write the completed speaker colour.
    if (!el.querySelector(".cwi-glyph")?.classList.contains("syllabic")) {
      const colorT = el.dataset.turned === "true" ? node.w.end + 999 :
        node.w.start - 999;
      for (let ci = 0; ci < node.chars.length; ci++) {
        setStyle(node.chars[ci], "color", "_c",
                 MO.charColorAt(node, ci, colorT));
      }
    }
    if (el._turnPerf !== undefined && vt < wordSettleT(node._motionW)) anyActive = true;
  }
  return anyActive;
}
// Write a word to its final rest exactly once when its window passes. Colour
// remains white until its independent cue/commit arrives.
function settleWord(el) {
  const node = ccNodeOf(el);
  const vt = el.dataset.turned === "true" ? node.w.end + 999 :
    node.w.start - 999;
  setTf(el, MO.wordTransform(0, 0, 1));
  settleCharacterGeometry(el);
  setStyle(el, "fontVariationSettings", "_vf",
           '"opsz" 14, "wght" ' + el._type.restWght +
           ', "wdth" ' + Number(el._type.restWdth ?? 100));
  if (!el.querySelector(".cwi-glyph")?.classList.contains("syllabic")) {
    for (let ci = 0; ci < node.chars.length; ci++) {
      setStyle(node.chars[ci], "color", "_c", MO.charColorAt(node, ci, vt));
    }
  }
}
function motionTick(now) {
  motionRAF = 0;
  const active = new Set();
  motionLines.forEach(line => {
    if (line.isConnected && resolveCCLine(line, now)) active.add(line);
  });
  motionRecs.forEach(rec => {
    const el = rec.el;
    if (!el.isConnected) {
      // A tentative line can be replaced while its word is active. Seal that
      // detached node at the common rest immediately; verification may reuse
      // the same DOM slot later, and it must not inherit a stale `moving` flag.
      settleWord(el);
      el.dataset.moving = "";
      flushPendingSpokenColor(el);
      if (el._motionTrace && el._motionTrace.animationCompletionMs === null) {
        el._motionTrace.animationCompletionMs = now;
        el._motionTrace.state = "removed";
      }
      el._motionTrace = null;
      motionRecs.delete(rec);
      return;
    }
    if (el._turnPerf !== undefined &&
        virtualT(el, now) + 1e-6 >= wordSettleT(displayMotionWord(el))) {
      settleWord(el);
      el.dataset.moving = "";
      flushPendingSpokenColor(el);
      // Verification may revise a word's semantic ID while its one allowed
      // first-paint motion is still running. Keep the trace on the visual node
      // instead of looking it up by that mutable identity.
      const trace = el._motionTrace;
      if (trace) { trace.animationCompletionMs = now; trace.state = "completed"; }
      el._motionTrace = null;
      motionRecs.delete(rec);
    }
  });
  // A line stays live while any word animates so CC-style optional
  // neighbour-push can resolve; stacked live keeps settled words fixed.
  motionLines.forEach(line => {
    let has = active.has(line);
    if (!has) motionRecs.forEach(rec => { if (rec.line === line) has = true; });
    if (!has) motionLines.delete(line);
  });
  if (sequentialRevealQueue.length) scheduleSequentialReveal(0);
  if (motionRecs.size) motionRAF = requestAnimationFrame(motionTick);
}
// Start the word's one-time geometry on its first real paint. Colour is owned
// by cue/commit and is deliberately not changed here.
function playWordMotion(el, ev, options) {
  if (el.dataset.moved === "true" || motionWasConsumed(el, ev)) {
    consumeWordMotion(el, ev);
    el.dataset.moved = "true";
    setTf(el, MO.wordTransform(0, 0, 1));
    return "already";
  }
  consumeWordMotion(el, ev);
  if (SENTENCE) return "sentence";
  el.dataset.moved = "true";
  el._captionEvent = ev;
  if (reducedMotion.matches || ev._replay === true || !LIVE_MOTION) {
    // Reduced motion / reconnect replay / motion disabled: settle geometry
    // directly. The independent colour lifecycle still applies normally.
    setTf(el, MO.wordTransform(0, 0, 1));
    return "settled";
  }
  registerMotion(el, ev);
  return "active";
}

let current = null;
let partialHost = null;
let lastFinalT = -1e9;
const wordNodes = new Map();

function setTentativeState(el, active) {
  if (!el) return;
  el.dataset.interpreting = active ? "true" : "false";
  el.setAttribute("aria-busy", active ? "true" : "false");
}

function applySustainState(el, ev) {
  if (!el) return;
  const active = !!(
    ev && ev.src === "onset" && ev.sustain_active === true
  );
  el.dataset.sustainActive = active ? "true" : "false";
  if (!active) {
    el.style.removeProperty("--sustain-width");
    return;
  }
  // Continue into empty space instead of repeatedly deforming the last glyph.
  // The trail approaches a bounded width as the detected prefix is held.
  const held = Math.max(0, Number(ev.sustain_s || 0));
  const widthEm = 0.14 + 0.54 * (1 - Math.exp(-held / 0.85));
  el.style.setProperty("--sustain-width", widthEm.toFixed(3) + "em");
}

function removeTentativeNode(node) {
  stopCharacterEntry(node);
  node.remove();
}

function rememberWordNode(key, node) {
  wordNodes.set(key, node);
  if (wordNodes.size <= CFG.render_queue_limit * 2) return;
  for (const [oldKey, oldNode] of wordNodes) {
    if (!oldNode.isConnected) wordNodes.delete(oldKey);
    if (wordNodes.size <= CFG.render_queue_limit) break;
  }
}
function mergeNodeEvent(el, incoming) {
  const merged = RenderCore.mergeWordUpdate(el._captionEvent, incoming);
  if (merged.stale) countMetric("staleRevisionsIgnored");
  if (!merged.changed) {
    countMetric("updatesDiscarded");
    return merged;
  }
  const ev = merged.value;
  const priorMotionWord = el._displayMotionWord;
  const priorCharacterMotionWord = el._displayCharacterMotionWord;
  const glyph = el.querySelector(".cwi-glyph");
  if (merged.changes.text && glyph) {
    setGlyphText(glyph, ev.text);
    // A corrected spelling must get its natural normal-font width. Keeping the
    // old slot width made longer verified words overflow into their neighbours.
    el._ccNode = null;
    el._ccRestW = null;
    el.style.width = "";
  }
  el._captionEvent = ev;
  applySustainState(el, ev);
  if (el.dataset.moving === "true") {
    if (priorMotionWord) {
      priorMotionWord._source = ev;
      el._displayMotionWord = priorMotionWord;
    }
    if (priorCharacterMotionWord) {
      priorCharacterMotionWord._source = ev;
      el._displayCharacterMotionWord = priorCharacterMotionWord;
    }
  }
  if (merged.changes.speaker) {
    applyAttributionState(el, ev);
    if (el.dataset.turned === "true") applySpokenColor(el, ev, false);
  }
  el.dataset.textRevision = String(ev.text_revision_id || 0);
  el.dataset.timingRevision = String(ev.timing_revision_id || 0);
  setTentativeState(el, !(ev.final || ev.verified));
  el.title = escTitle(ev);
  countMetric("wordUpdatesRendered");
  noteRenderedEvent(incoming);
  return merged;
}
function replaceNodeEventInPlace(el, incoming) {
  // A non-1:1 endpoint correction can change word identity. Reuse a visual
  // slot that the reader already saw without replaying it, but preserve an
  // unseen slot's place in the first-paint queue. Verification often arrives
  // before that queue drains; treating such a slot as already revealed made
  // corrected words appear later with no motion at all.
  const wasRevealed = el.dataset.revealed === "true";
  const wasMoving = el.dataset.moving === "true";
  const wasMoved = el.dataset.moved === "true";
  const priorMotionWord = el._displayMotionWord;
  const priorCharacterMotionWord = el._displayCharacterMotionWord;
  const oldKey = RenderCore.wordKey(el._captionEvent);
  const newKey = RenderCore.wordKey(incoming);
  const glyph = el.querySelector(".cwi-glyph");
  if (glyph && glyph.textContent !== incoming.text) {
    setGlyphText(glyph, incoming.text);
    el._ccNode = null;
  }
  el._ccRestW = null;
  el.style.width = "";
  if (wordNodes.get(oldKey) === el) wordNodes.delete(oldKey);
  el._captionEvent = Object.assign({}, incoming);
  applySustainState(el, el._captionEvent);
  if (wasMoving && priorMotionWord) {
    // Keep the current motion clock and envelope continuous through a spelling
    // or endpoint correction. Only the semantic source attached to it changes.
    priorMotionWord._source = el._captionEvent;
    el._displayMotionWord = priorMotionWord;
  } else {
    el._displayMotionWord = null;
  }
  if (wasMoving && priorCharacterMotionWord) {
    priorCharacterMotionWord._source = el._captionEvent;
    el._displayCharacterMotionWord = priorCharacterMotionWord;
  } else {
    el._displayCharacterMotionWord = null;
  }
  el.dataset.wordId = newKey;
  el.dataset.textRevision = String(incoming.text_revision_id || 0);
  el.dataset.timingRevision = String(incoming.timing_revision_id || 0);
  el.classList.remove("partial", "cued", "verification-vacancy");
  el.classList.add("final", "verified");
  el.dataset.verified = "true";
  setTentativeState(el, false);
  applyAttributionState(el, el._captionEvent);
  el.title = escTitle(el._captionEvent);
  if (!wasRevealed) {
    // This word has never had a visible frame. Keep it hidden and update the
    // existing queue record so its verified text receives the same one-time
    // entrance it would have received as a hypothesis.
    el.dataset.revealPending = "true";
    el.dataset.revealed = "";
    el.dataset.moved = wasMoved ? "true" : "";
    el.dataset.moving = "";
    el.style.visibility = "hidden";
    el.style.opacity = "0";
    setTf(el, MO.wordTransform(0, 0, 1));
    queueSequentialReveal(el, el._captionEvent, true);
    applySpokenColor(el, el._captionEvent, false);
  } else {
    // A visible slot has already spent its single entrance. Consume the revised
    // identity too, so no future reconciliation can replay it.
    consumeWordMotion(el, incoming);
    el.dataset.revealPending = "";
    el.dataset.revealed = "true";
    el.dataset.moved = "true";
    el.dataset.moving = wasMoving ? "true" : "";
    el.style.visibility = "";
    el.style.opacity = "1";
    el.removeAttribute("aria-hidden");
    if (wasMoving) {
      // The trace follows the visual slot through an in-flight correction.
      if (el._motionTrace) {
        if (!el._motionTrace.revisedFromWordId) {
          el._motionTrace.revisedFromWordId = oldKey;
        }
        el._motionTrace.wordId = newKey;
      }
    } else {
      setTf(el, MO.wordTransform(0, 0, 1));
    }
    applySpokenColor(el, el._captionEvent, false);
  }
  rememberWordNode(newKey, el);
  countMetric("wordUpdatesRendered");
  noteRenderedEvent(incoming);
  return el;
}
function retire(line, delay) {
  window.setTimeout(() => {
    if (!line.div.isConnected) return;
    line.div.classList.add("gone");
    window.setTimeout(() => line.div.remove(), 500);
  }, delay);
}
function stableSpeaker(ev) {
  return ["stable", "corrected"].includes(speakerStatus(ev)) ? ev.speaker : null;
}
function paragraphSpeaker(ev) {
  // A provisional label is uncertain in colour strength, but it is still the
  // best real-time turn boundary available. Use it to start a separate box;
  // later stable/corrected evidence can refine the paragraph without replaying
  // any word. Unknown speech remains attached until a label exists.
  return ev && ev.speaker && speakerStatus(ev) !== "unknown" ? ev.speaker : null;
}
function captionLineElement(speaker) {
  const div = document.createElement("div");
  div.className = "cwi-line";
  div.style.background = "rgba(0,0,0," + CFG.box_opacity + ")";
  if (speaker) div.dataset.speaker = speaker;
  return div;
}
function newLine(speaker, carryTail, utterance) {
  const tail = carryTail && partialHost ? Array.from(partialHost.children) : [];
  if (partialHost && !carryTail) {
    while (partialHost.firstChild) removeTentativeNode(partialHost.firstChild);
  }
  if (current && !OVERFLOW_RETAIN) retire(current, CFG.line_linger_s * 1000);
  const div = captionLineElement(speaker);
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
    // synchronously keeps an outgoing third box from occupying the lower work
    // area for another transition frame.
    while (rack.children.length > CFG.max_lines) {
      const oldest = rack.firstElementChild;
      if (oldest === div) break;
      oldest.remove();
    }
  }
  current = {
    div: div, count: 0, speaker: speaker, utterance: utterance,
    timer: null, circle: null
  };
  partialHost = document.createElement("span");
  partialHost.className = "cwi-partial-host";
  partialHost.style.display = "contents";
  div.appendChild(partialHost);
  if (INTENT_CIRCLE) {
    // Appended after partialHost so it stays the last thing on the line.
    const circle = document.createElement("i");
    circle.className = "intent-circle";
    circle.style.setProperty("--c", speaker ? colorFor(speaker) : "#F4F2EA");
    const sizePct = Math.max(0.8, Number(CFG.intent_circle_size_pct || 2.3));
    const px = Math.max(12, Math.round(stage.clientHeight * sizePct / 100));
    circle.style.width = circle.style.height = px + "px";
    circle.setAttribute("role", "img");
    circle.setAttribute("aria-label", "Voice activity");
    div.appendChild(circle);
    current.circle = circle;
    if (latestVoiceEvent) paintVoiceIndicator(circle, latestVoiceEvent, false);
  }
  tail.forEach(node => partialHost.appendChild(node));
  normalizeWordSpacing(current);
  return current;
}
function splitCaptionLineAt(line, startNode, speaker, utterance) {
  if (!line || !startNode || startNode.closest(".cwi-line") !== line) return line;
  const finals = Array.from(
    line.querySelectorAll(":scope > .cwi-word.final")
  );
  const at = finals.indexOf(startNode);
  if (at <= 0) {
    if (speaker) line.dataset.speaker = speaker;
    return line;
  }
  const moved = finals.slice(at);
  const next = captionLineElement(speaker);
  line.insertAdjacentElement("afterend", next);
  moved.forEach(node => next.appendChild(node));

  // If this is the active paragraph, its read-ahead host belongs after the
  // newest speaker run. Moving the host does not recreate any word or motion.
  if (current && current.div === line) {
    if (partialHost) next.appendChild(partialHost);
    if (current.circle) next.appendChild(current.circle);
    current.div = next;
    current.count = moved.length;
    current.speaker = speaker;
    current.utterance = utterance;
  }

  // An endpoint speaker decision can land while one of the moved words is
  // still in its first-paint envelope. Keep that exact clock alive on the new
  // paragraph rather than freezing or restarting it.
  let movedActive = false;
  motionRecs.forEach(rec => {
    if (!moved.includes(rec.el)) return;
    rec.line = next;
    movedActive = true;
  });
  if (movedActive) motionLines.add(next);

  normalizeWordSpacing({div: line});
  normalizeWordSpacing({div: next});
  if (OVERFLOW_RETAIN) {
    while (rack.firstElementChild !== next &&
           rack.scrollHeight > stage.clientHeight * 0.92) {
      rack.firstElementChild.remove();
    }
  } else {
    while (rack.children.length > CFG.max_lines) rack.firstElementChild.remove();
  }
  return next;
}
function enforceSpeakerParagraphs(utterance) {
  // Diarization often becomes stable only after the words already share a
  // provisional box. Split stable speaker runs in place at that point. This is
  // a paragraph operation only: nodes, motion history, and active clocks stay
  // intact.
  const lines = Array.from(rack.querySelectorAll(":scope > .cwi-line"));
  lines.forEach(original => {
    const words = Array.from(
      original.querySelectorAll(":scope > .cwi-word.final")
    ).filter(node =>
      !node.classList.contains("verification-vacancy") &&
      node._captionEvent &&
      Number(node._captionEvent.utterance) === Number(utterance)
    );
    if (!words.length) return;
    let line = original;
    let activeSpeaker = line.dataset.speaker || null;
    words.forEach(node => {
      const speaker = paragraphSpeaker(node._captionEvent);
      if (!speaker) return;
      if (!activeSpeaker) {
        activeSpeaker = speaker;
        line.dataset.speaker = speaker;
        if (current && current.div === line) current.speaker = speaker;
        return;
      }
      if (speaker === activeSpeaker) return;
      line = splitCaptionLineAt(
        line,
        node,
        speaker,
        node._captionEvent.utterance
      );
      activeSpeaker = speaker;
    });
  });
  mergeAdjacentSpeakerParagraphs(utterance);
}
function captionLineRun(line, utterance) {
  const words = Array.from(
    line.querySelectorAll(":scope > .cwi-word.final")
  ).filter(node =>
    !node.classList.contains("verification-vacancy") &&
    node._captionEvent &&
    (utterance == null ||
     Number(node._captionEvent.utterance) === Number(utterance))
  );
  const speakers = Array.from(new Set(
    words.map(node => paragraphSpeaker(node._captionEvent)).filter(Boolean)
  ));
  const utterances = Array.from(new Set(
    words.map(node => Number(node._captionEvent.utterance))
  ));
  return {
    words: words,
    speaker: speakers.length === 1 ? speakers[0] : null,
    utterance: utterances.length === 1 ? utterances[0] : null
  };
}
function mergeAdjacentSpeakerParagraphs(utterance) {
  // Speaker stabilization can split a provisional line into several small
  // boxes over successive revisions ("You" / "want a Pepsi"). Join adjacent
  // runs back into one readable paragraph when they belong to the same speaker
  // and still fit the normal line constraints.
  let changed = true;
  while (changed) {
    changed = false;
    const lines = Array.from(rack.querySelectorAll(":scope > .cwi-line"));
    for (let i = 0; i + 1 < lines.length; i++) {
      const first = lines[i], second = lines[i + 1];
      const a = captionLineRun(first, null);
      const b = captionLineRun(second, null);
      const lastA = a.words[a.words.length - 1]?._captionEvent;
      const firstB = b.words[0]?._captionEvent;
      const acrossEndpointContinuation = !!(
        lastA && firstB &&
        a.utterance !== b.utterance &&
        !/[.?!]["')\]]?$/.test(lastA.text || "") &&
        Number(firstB.t) - (
          Number(lastA.t) + Math.max(0, Number(lastA.end) - Number(lastA.start))
        ) <= Math.max(0.35, Number(CFG.line_break_gap_s || 0))
      );
      if (!a.words.length || !b.words.length ||
          !a.speaker || a.speaker !== b.speaker ||
          (a.utterance !== b.utterance && !acrossEndpointContinuation) ||
          a.words.length + b.words.length > CFG.max_words) continue;
      const orphanTail = second.querySelector(
        ":scope > .cwi-partial-host > .cwi-word"
      );
      if (orphanTail && !(current && current.div === second)) continue;
      const sample = a.words[0] || b.words[0];
      const gap = sample
        ? parseFloat(getComputedStyle(sample).fontSize || "0") * 0.27
        : 0;
      const combinedWidth = a.words.concat(b.words).reduce(
        (sum, node) => sum + Number(node._ccRestW || node.scrollWidth || 0) + gap,
        0
      );
      if (combinedWidth > rack.clientWidth * 0.90) continue;

      let host = first.querySelector(":scope > .cwi-partial-host");
      const secondIsCurrent = current && current.div === second;
      if (secondIsCurrent) {
        if (host && host !== partialHost) host.remove();
        host = null;
      }
      b.words.forEach(node => first.insertBefore(node, host || null));
      if (secondIsCurrent) {
        if (partialHost) first.appendChild(partialHost);
        if (current.circle) first.appendChild(current.circle);
        current.div = first;
        current.count = a.words.length + b.words.length;
        current.speaker = a.speaker;
        current.utterance = b.utterance;
      }
      motionRecs.forEach(rec => {
        if (b.words.includes(rec.el)) rec.line = first;
      });
      if (motionLines.has(second)) motionLines.add(first);
      second.remove();
      first.dataset.speaker = a.speaker;
      normalizeWordSpacing({div: first});
      changed = true;
      break;
    }
  }
}
function pruneEmptyCaptionLines() {
  Array.from(rack.querySelectorAll(":scope > .cwi-line")).forEach(line => {
    if (line.querySelector(".cwi-word:not(.verification-vacancy)")) return;
    if (current && current.div === line) {
      current = null;
      partialHost = null;
    }
    line.remove();
  });
}
function ensureLine(ev) {
  const speaker = paragraphSpeaker(ev);
  const previous = current && Array.from(
    current.div.querySelectorAll(":scope > .cwi-word.final")
  ).at(-1);
  const sentenceEnded = previous &&
    /[.?!]["')\]]?$/.test(previous._captionEvent.text || "");
  if (!current) newLine(speaker, false, ev.utterance);
  else if (speaker && current.speaker && current.speaker !== speaker ||
           (current.count > 0 && current.utterance !== ev.utterance) ||
           (current.count > 0 && sentenceEnded) ||
           (current.count > 0 && ev.t - lastFinalT > CFG.line_break_gap_s)) {
    newLine(speaker, false, ev.utterance);
  } else if (speaker && !current.speaker) {
    current.speaker = speaker;
    if (current.circle) current.circle.style.setProperty("--c", colorFor(speaker));
  } else if (current.count >= CFG.max_words) {
    // A CWI line break must not duplicate its already-rendered read-ahead
    // tail. Move those exact nodes into the new box before promoting finals.
    newLine(speaker, true, ev.utterance);
  }
  return current;
}
function wordElement(ev, final) {
  const key = RenderCore.wordKey(ev);
  const existing = wordNodes.get(key);
  if (existing) {
    mergeNodeEvent(existing, ev);
    return existing;
  }
  const el = document.createElement("span");
  el.className = "cwi-word " + (final ? "final" : "partial");
  // A tentative word may be deleted moments later; it must not get a vote in
  // the smoothing state, only a projection against it.
  const glyph = document.createElement("span");
  glyph.className = "cwi-glyph";
  el.appendChild(glyph);
  setGlyphText(glyph, ev.text);
  countMetric("domNodesCreated");
  applyAttributionState(el, ev);
  applyTypography(el, ev, final);
  el.dataset.wordId = key;
  if (motionWasConsumed(el, ev)) {
    // The same semantic word may be recreated after provisional reconciliation.
    // Its letters can change in place, but its first-paint motion is spent.
    el.dataset.moved = "true";
    setTf(el, MO.wordTransform(0, 0, 1));
  }
  el.dataset.textRevision = String(ev.text_revision_id || 0);
  el.dataset.timingRevision = String(ev.timing_revision_id || 0);
  el.title = escTitle(ev);
  el._captionEvent = ev;
  applySustainState(el, ev);
  setTentativeState(el, !final);
  rememberWordNode(key, el);
  countMetric("wordUpdatesRendered");
  noteRenderedEvent(ev);
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
    setLayoutStyle(el, "marginRight", ".27em");
  });
}
function sameSlot(node, ev) {
  // Time-only: live diarization can relabel a word's speaker between its
  // provisional commit and the endpoint pass, and a relabel must reconcile
  // in place (colour update) rather than read as a delete + insert.
  const old = node && node._captionEvent;
  return !!old && (
    (old.word_id && ev.word_id && old.word_id === ev.word_id) ||
    Math.abs(old.t - ev.t) < .22
  );
}
function promotePartial(ev) {
  const direct = wordNodes.get(RenderCore.wordKey(ev));
  const candidates = partialHost ? Array.from(partialHost.children) : [];
  const candidate = direct && direct.parentElement === partialHost ? direct :
    candidates.find(node => sameSlot(node, ev));
  if (!candidate) return null;
  const index = candidates.indexOf(candidate);
  candidates.slice(0, Math.max(0, index)).forEach(removeTentativeNode);
  // Keep the exact geometry measured when this word first appeared. Only its
  // content, color, and inner-glyph transform may change, matching CWI's fixed read-ahead
  // line even when the recognizer corrects spelling at the lock boundary.
  // The word is committing: let it vote in the smoothing state for subsequent
  // words, but keep the geometry it was painted with (expressionFor is
  // first-write-wins, so this returns the cached value).
  expressionFor(ev, true);
  mergeNodeEvent(candidate, ev);
  setTentativeState(candidate, false);
  candidate.classList.remove("partial");
  candidate.classList.remove("cued");
  candidate.classList.add("final");
  current.div.insertBefore(candidate, partialHost);
  normalizeWordSpacing(current);
  // First paint already owned the one-time motion. Commit is colour/text only.
  applySpokenColor(candidate, candidate._captionEvent, false);
  return candidate;
}
function lineOverflows(line) {
  // nowrap lines cannot self-limit: a caption box whose words vary in size
  // must break on measured width, not on a word count.
  const limit = rack.clientWidth * 0.96;
  return line.div.scrollWidth > limit && line.count > 0;
}
function addFinalWord(ev, options) {
  const settleLate = Boolean(options && options.settleLate);
  hint.style.opacity = 0;
  const existing = wordNodes.get(RenderCore.wordKey(ev));
  if (existing && existing.classList.contains("final")) {
    const merged = mergeNodeEvent(existing, ev);
    if (merged.changed) enforceSpeakerParagraphs(ev.utterance);
    const historyIndex = finalHistory.findIndex(
      word => RenderCore.wordKey(word) === RenderCore.wordKey(ev)
    );
    if (historyIndex >= 0) finalHistory[historyIndex] = existing._captionEvent;
    return existing;
  }
  const line = ensureLine(ev);
  const promoted = promotePartial(ev);
  if (!promoted) {
    const added = wordElement(ev, true);
    line.div.insertBefore(added, partialHost);
    // A new visual word owns one first-paint motion regardless of whether
    // startup supplied it as hypothesis, commit or verification. Only
    // historical replay/correction insertions explicitly request settlement.
    if (settleLate) {
      added.dataset.moved = "true";
      setTf(added, MO.wordTransform(0, 0, 1));
      queueSequentialReveal(added, ev, false);
    } else {
      queueSequentialReveal(added, ev, true);
    }
    applySpokenColor(added, added._captionEvent, false);
  }
  normalizeWordSpacing(line);
  line.count += 1;
  // If that word pushed the box past the stage, move it to a fresh line.
  // A promoted hypothesis is already at a position the reader has seen.
  // Verification/commit may change its letters or colour, but must not move
  // that existing node into another row. Only an unseen final insertion may
  // choose a fresh line before it is revealed.
  if (!promoted && lineOverflows(line)) {
    // :scope > — querySelectorAll descends into partialHost (display:contents),
    // so an unscoped query could move a tentative read-ahead word and leave the
    // freshly committed one behind.
    const overflowing = line.div.querySelectorAll(":scope > .cwi-word");
    const moved = overflowing[overflowing.length - 1];
    if (!moved) return;
    line.count -= 1;
    const next = newLine(paragraphSpeaker(ev), false, ev.utterance);
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
  noteProsody(ev);
  finalHistory.push((promoted || wordNodes.get(RenderCore.wordKey(ev)))._captionEvent);
  if (finalHistory.length > 18) finalHistory.shift();
  updateDesignSystem(ev);
  return promoted || wordNodes.get(RenderCore.wordKey(ev));
}
function cueWord(ev) {
  cuedSlots.add(slotKey(ev));
  const candidates = partialHost ? Array.from(partialHost.children) : [];
  const direct = wordNodes.get(RenderCore.wordKey(ev));
  const candidate = direct || candidates.find(node => sameSlot(node, ev));
  if (!candidate || candidate.dataset.cued === "true") return;
  mergeNodeEvent(candidate, ev);
  candidate.dataset.cued = "true";
  candidate.classList.add("cued");
  // Cue owns colour only. Geometry already ran when this node first appeared.
  applySpokenColor(candidate, candidate._captionEvent, false);
  if (candidate.classList.contains("final")) {
    enforceSpeakerParagraphs(candidate._captionEvent.utterance);
    return;
  }
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
  if (!partialHost && incoming.length) {
    newLine(paragraphSpeaker(incoming[0]), false, incoming[0].utterance);
  }
  const capacity = current ? Math.max(0, CFG.max_words - current.count) : 0;
  const settled = new Set(
    Array.from(document.querySelectorAll(".cwi-word.final"))
      .map(node => RenderCore.wordKey(node._captionEvent))
  );
  const words = RenderCore.reduceTentativeTail(
    incoming, CFG.display_mode, settled, capacity
  );
  if (partialHost) {
    const desired = [];
    words.forEach(ev => {
      const node = wordElement(ev, false);
      if (!node.classList.contains("final")) desired.push(node);
    });
    const keep = new Set(desired);
    Array.from(partialHost.children).forEach(node => {
      if (!keep.has(node)) removeTentativeNode(node);
    });
    let cursor = partialHost.firstElementChild;
    desired.forEach(node => {
      if (node === cursor) {
        cursor = cursor.nextElementSibling;
      } else {
        partialHost.insertBefore(node, cursor);
      }
      if (cuedSlots.has(slotKey(node._captionEvent))) {
        node.dataset.cued = "true";
        node.classList.add("cued");
      }
      // Every word owns its one motion at the earliest moment it exists on the
      // stage, but decoder batches enter that stage one word at a time.
      // Re-renders are harmless because dataset.revealed/moved are once-only.
      queueSequentialReveal(node, node._captionEvent, true);
      if (node.dataset.cued === "true") {
        applySpokenColor(node, node._captionEvent, false);
      }
    });
    if (desired.length) normalizeWordSpacing(current);
    // Trim tentative tail words that would overflow the stage rather than
    // letting the white read-ahead run off the edge.
    while (current && current.div.scrollWidth > rack.clientWidth * 0.96 &&
           partialHost.lastElementChild) {
      removeTentativeNode(partialHost.lastElementChild);
    }
  }
  pruneEmptyCaptionLines();
  return words.filter(word => {
    const node = wordNodes.get(RenderCore.wordKey(word));
    return node && node.isConnected;
  });
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
let syncSignature = "";
function renderSync(partials) {
  const items = finalHistory.slice(-7).map(ev => ({ev: ev, partial: false}));
  (partials || []).slice(0, 4).forEach(ev => items.push({
    ev: ev, partial: true, cued: cuedSlots.has(slotKey(ev))
  }));
  const signature = items.map(item =>
    (item.partial ? "p:" : "f:") + RenderCore.wordKey(item.ev) + ":" +
    item.ev.text + ":" + Boolean(item.cued) + ":" + speakerStatus(item.ev)
  ).join("|");
  if (signature === syncSignature) return;
  syncSignature = signature;
  const existing = new Map(
    Array.from(syncTokens.children).map(node => [node.dataset.key, node])
  );
  const keep = new Set();
  let cursor = syncTokens.firstElementChild;
  items.forEach(item => {
    const key = (item.partial ? "p:" : "f:") + RenderCore.wordKey(item.ev);
    let el = existing.get(key);
    if (!el) {
      el = document.createElement("div");
      el.dataset.key = key;
    }
    keep.add(el);
    el.className = "sync-token" +
      (item.cued ? " cued" : (item.partial ? " partial" : ""));
    setNodeText(el, item.ev.text);
    el.title = item.ev.text + " at " + item.ev.t.toFixed(2) + "s";
    el.style.setProperty("--duration", Math.max(.35, item.ev.end - item.ev.start));
    el.style.setProperty("--color", attributionColor(item.ev));
    if (el === cursor) cursor = cursor.nextElementSibling;
    else syncTokens.insertBefore(el, cursor);
  });
  Array.from(syncTokens.children).forEach(node => {
    if (!keep.has(node)) node.remove();
  });
}
function updateDesignSystem(ev, provisional) {
  const status = speakerStatus(ev);
  const color = attributionColor(ev);
  document.getElementById("voiceSwatch").style.background = color;
  if (voiceCompass) voiceCompass.style.setProperty("--c", color);
  document.getElementById("speakerName").textContent =
    status === "unknown" ? "Speaker uncertain" :
    (ev.speaker === "S1" ? "Speaker 01" : ev.speaker) +
      (status === "provisional" ? " · tentative" : "");
  const bars = paletteEl.children;
  for (let i = 0; i < bars.length; i++) {
    bars[i].classList.toggle(
      "active",
      ["stable", "corrected"].includes(status) &&
        CFG.palette[i] === colorFor(ev.speaker)
    );
  }

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
  countMetric("fullLineRenders");
  const line = newLine(
    stableSpeaker(words[0]), false, words[0].utterance
  );
  line.div.style.opacity = 0;             // the whole box eases in
  requestAnimationFrame(() => { line.div.style.opacity = 1; });
  words.forEach(word => {
    const node = wordElement(word, true);
    applySpokenColor(node, node._captionEvent, false);
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
  // Per-word reconciliation in time order. Matching words update in place.
  // Non-1:1 corrections reuse existing DOM slots and never replay motion;
  // unused slots become invisible spacers. Corrected glyphs are remeasured at
  // the normal resting font so longer words cannot overlap their neighbours.
  const touched = new Set();
  const vacancies = [];
  const settle = (node, word) => {
    mergeNodeEvent(node, word);
    setTentativeState(node, false);
    // Deliberately NO typography here. A settled word's size is not
    // verification's business — re-applying it was the single largest source
    // of on-screen churn (it resized the word and re-fed the smoothing median).
    // The server now reports identical loudness for a slot, so there is
    // nothing to correct anyway.
    // Existing words keep their one-time motion state. A word that has never
    // reached first paint still owns one sequential reveal, including startup
    // verification words from the first sentence.
    if (node.dataset.moved !== "true") {
      if (node.dataset.revealed !== "true") {
        queueSequentialReveal(node, word, true);
      } else {
        // Defensive invariant: if an older renderer/state left a visible word
        // without a motion marker, verification freezes it at rest. A caption
        // the reader has already seen must never acquire a delayed animation.
        consumeWordMotion(node, word);
        node.dataset.moved = "true";
        setTf(node, MO.wordTransform(0, 0, 1));
      }
    }
    applySpokenColor(node, node._captionEvent, false);
    node.classList.remove("partial", "cued");
    node.classList.add("final", "verified");
    node.dataset.verified = "true";
    if (node.parentElement === partialHost && current) {
      current.div.insertBefore(node, partialHost);
      current.count += 1;
    }
    touched.add(node.closest(".cwi-line"));
  };
  const vacate = node => {
    const line = node.closest(".cwi-line");
    const key = RenderCore.wordKey(node._captionEvent);
    // Preserve whether this visual slot actually reached first paint. Accurate
    // verification frequently vacates a still-hidden decoder word and reuses
    // the box immediately. Erasing that distinction here caused the verified
    // replacement to skip its only motion.
    const wasRevealed = node.dataset.revealed === "true";
    const wasMoved = node.dataset.moved === "true";
    if (wordNodes.get(key) === node) wordNodes.delete(key);
    stopCharacterEntry(node);
    for (let q = sequentialRevealQueue.length - 1; q >= 0; q--) {
      if (sequentialRevealQueue[q].el === node) sequentialRevealQueue.splice(q, 1);
    }
    motionRecs.forEach(rec => {
      if (rec.el !== node) return;
      if (node._motionTrace && node._motionTrace.animationCompletionMs === null) {
        node._motionTrace.animationCompletionMs = performance.now();
        node._motionTrace.state = "replaced";
      }
      node._motionTrace = null;
      motionRecs.delete(rec);
    });
    node.dataset.revealPending = "";
    node.dataset.revealed = wasRevealed ? "true" : "";
    node.dataset.moving = "";
    consumeWordMotion(node, node._captionEvent);
    node.dataset.moved = (wasRevealed || wasMoved) ? "true" : "";
    setTf(node, MO.wordTransform(0, 0, 1));
    node.classList.remove("partial", "cued");
    node.classList.add("final", "verification-vacancy");
    node.style.visibility = "hidden";
    node.style.opacity = "1";
    node.setAttribute("aria-hidden", "true");
    vacancies.push(node);
    if (line) touched.add(line);
  };
  let i = 0;
  words.forEach(word => {
    while (i < live.length && !sameSlot(live[i], word) &&
           live[i]._captionEvent.t < word.t - 0.11) {
      vacate(live[i]);
      i += 1;
    }
    if (i < live.length && sameSlot(live[i], word)) {
      settle(live[i], word);
      i += 1;
    } else if (i < live.length) {
      // Fill an earlier inaccurate slot before considering a new DOM box.
      // Reusing it preserves every settled word's screen coordinates.
      const vacancy = vacancies.shift();
      if (vacancy) {
        const node = replaceNodeEventInPlace(vacancy, word);
        touched.add(node.closest(".cwi-line"));
      } else {
        // Substitute the next visual slot instead of inserting before it.
        // Subsequent verified words continue through subsequent slots.
        const node = replaceNodeEventInPlace(live[i], word);
        i += 1;
        touched.add(node.closest(".cwi-line"));
      }
    } else {
      const vacancy = vacancies.shift();
      if (vacancy) {
        const node = replaceNodeEventInPlace(vacancy, word);
        touched.add(node.closest(".cwi-line"));
      } else {
        // It has never been visible, so this is first paint rather than replay.
        addFinalWord(word, {settleLate: false});
      }
    }
  });
  while (i < live.length) {
    vacate(live[i]);
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
      removeTentativeNode(node);
    }
  });
  enforceSpeakerParagraphs(message.utterance);
  pruneEmptyCaptionLines();
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

function applySpeakerRevision(ev) {
  // Durable attribution revisions are complete word events. Match the stable
  // word id first, then its acoustic slot. A diarization decision is never a
  // new visual word and therefore can never own motion.
  const incomingKey = RenderCore.wordKey(ev);
  let node = wordNodes.get(incomingKey);
  if (!node || !node.isConnected) {
    node = Array.from(document.querySelectorAll(".cwi-word"))
      .find(candidate => sameSlot(candidate, ev)) || null;
  }
  if (!node) {
    // A reconnect may begin at a correction whose original is no longer in
    // the DOM. It is still history, so show it already settled.
    addFinalWord(ev, {settleLate: true});
    return;
  }
  const currentKey = RenderCore.wordKey(node._captionEvent);
  const compatible = currentKey === incomingKey ? ev :
    Object.assign({}, ev, {word_id: node._captionEvent.word_id});
  const merged = mergeNodeEvent(node, compatible);
  if (currentKey !== incomingKey) rememberWordNode(incomingKey, node);
  if (!merged.changed) return;
  applySpokenColor(node, node._captionEvent, false);
  enforceSpeakerParagraphs(node._captionEvent.utterance);
  const index = finalHistory.findIndex(word =>
    word.word_id === ev.word_id ||
    RenderCore.wordKey(word) === currentKey
  );
  if (index >= 0) finalHistory[index] = node._captionEvent;
  else finalHistory.push(node._captionEvent);
  revisionState.textContent = speakerStatus(node._captionEvent) === "corrected" ?
    "speaker attribution corrected" : "speaker attribution stabilized";
  revisionState.classList.remove("live");
  updateDesignSystem(node._captionEvent, false);
}

rack.style.paddingBottom = (CFG.bottom_margin_pct / 100 * stage.clientHeight) + "px";
addEventListener("resize", () => {
  rack.style.paddingBottom = (CFG.bottom_margin_pct / 100 * stage.clientHeight) + "px";
  document.querySelectorAll(".cwi-word").forEach(el => {
    // Browser chrome/scrollbar changes can emit resize while a speaker or
    // verification decision updates the page. Never remeasure or rescale a
    // caption the reader has already seen; doing so made the colour decision
    // appear to move whole rows. Only an unseen queued word may adapt.
    if (el._type && el.dataset.revealed !== "true") {
      setLayoutStyle(
        el, "fontSize",
        (el._type.restPct / 100 * stage.clientHeight).toFixed(1) + "px"
      );
      el._ccRestW = null;
      el.style.width = "";
    }
  });
});

// All caption-bearing SSE consumers converge here. One animation frame reduces
// a burst to the newest state per stable word id, while `level` remains on its
// own meter-only frame. There is no timer train to fall behind inference.
const pendingWordUpdates = RenderCore.createFrameReducer(CFG.render_queue_limit);
const pendingVerifications = new Map();
const latestVerificationIds = new Map();
let pendingHypothesis = null;
let latestHypothesisId = 0;
let captionFrame = 0;
function updateQueueMetrics() {
  renderMetrics.queueDepth = pendingWordUpdates.size +
    pendingVerifications.size + (pendingHypothesis ? 1 : 0) +
    sequentialRevealQueue.length;
  renderMetrics.maxQueueDepth =
    Math.max(renderMetrics.maxQueueDepth, renderMetrics.queueDepth);
}
function scheduleCaptionFrame() {
  updateQueueMetrics();
  if (!captionFrame) captionFrame = requestAnimationFrame(flushCaptionFrame);
}
function queueWordUpdate(ev) {
  countMetric("wordUpdatesReceived");
  // Never evict a required commit/final merely to enforce the memory bound.
  // An exceptional >limit burst is drained in bounded chunks instead.
  if (pendingWordUpdates.size >= CFG.render_queue_limit &&
      !pendingWordUpdates.has(RenderCore.wordKey(ev))) {
    flushCaptionFrame();
  }
  const before = Object.assign({}, pendingWordUpdates.stats);
  pendingWordUpdates.enqueue(ev);
  countMetric(
    "updatesCoalesced",
    pendingWordUpdates.stats.coalesced - before.coalesced
  );
  countMetric(
    "updatesDiscarded",
    pendingWordUpdates.stats.discarded - before.discarded
  );
  countMetric(
    "staleRevisionsIgnored",
    pendingWordUpdates.stats.stale - before.stale
  );
  scheduleCaptionFrame();
}
function queueHypothesisEvent(ev) {
  countMetric("wordUpdatesReceived", (ev.words || []).length);
  const id = Number(ev._sse_id || 0);
  if (id && id < latestHypothesisId) {
    countMetric("updatesDiscarded");
    countMetric("staleRevisionsIgnored");
    return;
  }
  latestHypothesisId = Math.max(latestHypothesisId, id);
  if (!pendingHypothesis ||
      id >= Number(pendingHypothesis._sse_id || 0)) {
    if (pendingHypothesis) countMetric("updatesCoalesced");
    pendingHypothesis = ev;
  } else {
    countMetric("updatesDiscarded");
    countMetric("staleRevisionsIgnored");
  }
  scheduleCaptionFrame();
}
function queueVerificationEvent(ev) {
  countMetric("wordUpdatesReceived", (ev.words || []).length);
  const id = Number(ev._sse_id || 0);
  const latest = Number(latestVerificationIds.get(ev.utterance) || 0);
  if (id && id < latest) {
    countMetric("updatesDiscarded");
    countMetric("staleRevisionsIgnored");
    return;
  }
  latestVerificationIds.set(ev.utterance, Math.max(latest, id));
  if (pendingVerifications.size >= 64 &&
      !pendingVerifications.has(ev.utterance)) {
    flushCaptionFrame();
  }
  const prior = pendingVerifications.get(ev.utterance);
  if (!prior || id >= Number(prior._sse_id || 0)) {
    if (prior) countMetric("updatesCoalesced");
    pendingVerifications.set(ev.utterance, ev);
  } else {
    countMetric("updatesDiscarded");
    countMetric("staleRevisionsIgnored");
  }
  scheduleCaptionFrame();
}
function resetCaptionQueue() {
  pendingWordUpdates.reset();
  pendingVerifications.clear();
  pendingHypothesis = null;
  cuedSlots.clear();
  resetSequentialReveals();
  motionRecs.forEach(rec => {
    setTf(rec.el, "");
    rec.el.dataset.moving = "";
  });
  motionRecs.clear();
  motionLines.clear();
  document.querySelectorAll(".cwi-word").forEach(stopCharacterEntry);
  if (motionRAF) cancelAnimationFrame(motionRAF);
  motionRAF = 0;
  document.querySelectorAll(".cwi-word.partial").forEach(
    node => setTentativeState(node, false)
  );
  mediaClock.reset();
  updateQueueMetrics();
}
function flushCaptionFrame() {
  if (captionFrame) cancelAnimationFrame(captionFrame);
  captionFrame = 0;
  const verifications = Array.from(pendingVerifications.values())
    .sort((a, b) => Number(a._sse_id || 0) - Number(b._sse_id || 0));
  pendingVerifications.clear();
  verifications.forEach(ev => {
    verifiedUtterances.add(ev.utterance);
    if (SENTENCE) enqueueSentences(ev.words);
    else applyVerification(ev);
  });

  pendingWordUpdates.drain().forEach(ev => {
    if (ev.type === "cue") {
      if (!verifiedUtterances.has(ev.utterance)) cueWord(ev);
    } else if (ev.type === "word" && ev.final && ev.correction) {
      applySpeakerRevision(ev);
    } else if (ev.type === "commit") {
      if (!SENTENCE && !verifiedUtterances.has(ev.utterance)) addFinalWord(ev);
    } else if (ev.type === "word" && ev.final &&
               !verifiedUtterances.has(ev.utterance)) {
      if (SENTENCE) bufferSentenceWord(ev);
      else addFinalWord(ev);  // bounded replay
    }
  });

  const hypothesis = pendingHypothesis;
  pendingHypothesis = null;
  if (hypothesis) showHypothesis(hypothesis);
  updateQueueMetrics();
}

// Post-paint churn counter (display.debug_churn). Counts mutations to words
// that are already SETTLED — the ones a reader may be mid-sentence through.
// window.__cwiChurn.report() -> {settled, mutations, perWord, byKind}
if (CFG.debug_churn) {
  const byKind = {text: 0, size: 0, axes: 0, colour: 0, spacing: 0, move: 0, remove: 0};
  const settledWord = node => {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const word = el && el.closest && el.closest(".cwi-word");
    // Settled = turned AND past its motion window. The live CWI-motion loop
    // writes transform every frame while a word is active; those writes are
    // expected, so a word only counts as settled once dataset.moving clears.
    return word && word.dataset.turned === "true" &&
           word.dataset.moving !== "true" ? word : null;
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
let replayThrough = 0;
let openingReplayUtterance = null;
let openingReplayClosed = false;
function handleSSEMessage(message) {
  const ev = JSON.parse(message.data);
  const received = performance.now();
  const sseId = Number(message.lastEventId || 0);
  if (ev.type === "replay") {
    replayThrough = Math.max(replayThrough, Number(ev.through || 0));
    renderMetrics.events.replay = (renderMetrics.events.replay || 0) + 1;
    return;
  }
  ev._sse_id = sseId;
  ev._received_perf = received;
  const markedReplay = ev._replay === true ||
    (sseId > 0 && sseId <= replayThrough);
  // Models may produce the opening utterance before the browser's first SSE
  // connection. Animate that one startup sentence as first paint. Once a
  // different utterance is observed, all retained events are true reconnect
  // history and remain settled.
  if (markedReplay && openingReplayUtterance === null &&
      ev.utterance !== undefined && ev.utterance !== null) {
    openingReplayUtterance = ev.utterance;
  } else if (markedReplay && openingReplayUtterance !== null &&
             ev.utterance !== undefined &&
             ev.utterance !== openingReplayUtterance) {
    openingReplayClosed = true;
  }
  ev._replay = markedReplay && !(
    !openingReplayClosed &&
    openingReplayUtterance !== null &&
    ev.utterance === openingReplayUtterance
  );
  renderMetrics.events[ev.type] = (renderMetrics.events[ev.type] || 0) + 1;
  const prepareWords = (words, stage) => (words || []).forEach(word => {
    word._sse_id = sseId;
    word._received_perf = received;
    word._replay = ev._replay;
    word._render_stage = stage;
  });
  if (ev.type === "boot") {
    // Server comes up before the models load; say so instead of implying we
    // can hear anything yet.
    statusText.textContent = ev.stage;
    if (ev.stage === "listening") status.classList.add("on");
    return;
  }
  if (ev.type === "level") {
    queueLevelEvent(ev);
  } else if (ev.type === "hypothesis") {
    prepareWords(ev.words, "hypothesis");
    if (ev.resync) {
      // A real capture-device gap invalidates queued timing from before it.
      resetCaptionQueue();
    }
    queueHypothesisEvent(ev);
  } else if (ev.type === "cue") {
    ev._render_stage = "cue";
    queueWordUpdate(ev);
  } else if (ev.type === "sound") {
    soundChip(ev);
  } else if (ev.type === "word" && ev.final && ev.correction) {
    ev._render_stage = "word";
    queueWordUpdate(ev);
  } else if (ev.type === "verification") {
    prepareWords(ev.words, "verification");
    queueVerificationEvent(ev);
  } else if (ev.type === "commit") {
    ev._render_stage = "commit";
    queueWordUpdate(ev);
  } else if (ev.type === "word" && ev.final) {
    ev._render_stage = "word";
    queueWordUpdate(ev);
  }
}
window.__cwiRenderer = {
  dispatch(event, eventId) {
    handleSSEMessage({
      data: JSON.stringify(event),
      lastEventId: String(eventId || 0)
    });
  },
  flush: flushCaptionFrame,
  flushLevel() {
    if (levelFrame) cancelAnimationFrame(levelFrame);
    flushLevelFrame();
  },
  advanceMotion(performanceMs) {
    if (motionRAF) cancelAnimationFrame(motionRAF);
    motionRAF = 0;
    motionTick(Number(performanceMs));
  },
  nodeCount() {
    return document.querySelectorAll("#captionRack .cwi-word").length;
  },
  wordState(wordId) {
    const node = wordNodes.get(String(wordId));
    return node ? Object.assign({}, node._captionEvent) : null;
  }
};
try {
  const es = new EventSource("/events");
  es.onopen = () => {
    status.classList.add("on");
    statusText.textContent = "live";
  };
  es.onerror = () => {
    status.classList.remove("on");
    statusText.textContent = "reconnecting";
  };
  es.onmessage = handleSSEMessage;
} catch (_) {
  // `file://` is used only by the deterministic local render probe. The live
  // HTTP page always constructs EventSource normally.
}
</script>
</body>
</html>
''')
