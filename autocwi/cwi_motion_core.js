// CWI MOTION CORE — the single source of truth for the Caption-with-Intention
// motion MATH, shared verbatim by the closed-caption renderer (`ccpage.py`) and
// the live/open-caption renderer (`livepage.py`). Neither keeps its own copy, so
// the two can never drift: the numbers a word swells, lifts, pops and colours by
// are computed HERE for both.
//
// What is shared: the pure design-system math (§2.2 synchronization, §2.3
// intonation) — typeOf, syncAt, intonationAt, scaleOf, liftOf, wghtOf, the
// per-character colour/synchronization sweep, and the analytic neighbour-push. What each page
// keeps: its own DOM/clock ORCHESTRATION — cc drives every function off the
// global media clock `t` with read-ahead line selection; live re-bases the same
// shapes onto a per-word local clock started at the word's colour turn (a word
// arrives around/after its acoustic onset, so it cannot be a pure function of
// source `t` the way an authored caption is).
//
// `create(ctx)` binds the math to a mutable `ctx`:
//   ctx.cfg            resolved motion config (sync_pop, color_turn_ms, ...)
//   ctx.mapping        CFG.mapping (M)
//   ctx.expression     CFG.expression (EX)
//   ctx.medianLoudness number   (read every call — live updates it as it learns)
//   ctx.medianPitch    number|null
//   ctx.charSweep      bool     (per-character colour sweep vs whole-word turn)
//   ctx.waveOn         bool     (the intonation/lift wave is active)
//   ctx.reduced        bool     (prefers-reduced-motion)
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CWIMotion = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---- pure helpers (identical shape for both renderers) -------------------
  function lerp(a, b, f) { return a + (b - a) * f; }
  function clamp01(f) { return Math.min(1, Math.max(0, f)); }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  // Smoothstep: zero slope at BOTH ends, so an envelope never starts or stops
  // with a visible kick.
  function ease(f) { f = clamp01(f); return f * f * (3 - 2 * f); }
  // Single-humped pulse fitted to the recordings: leaves 0 with a positive
  // slope, peaks at `peak` s, back to 0 at `dur`.
  function pulse(d, dur, peak) {
    if (d <= 0 || d >= dur) return 0;
    const xp = clamp(peak / dur, 0.02, 0.48);
    const k = Math.PI / Math.tan(Math.PI * xp);
    const norm = Math.sin(Math.PI * xp) * Math.exp(-k * xp);
    return Math.sin(Math.PI * (d / dur)) * Math.exp(-k * (d / dur)) / norm;
  }
  // The crouch a letter holds while unspoken: down, then back to baseline
  // exactly as it turns (a plateau, not a hump).
  function crouch(d, lead) {
    if (d >= 0 || d <= -lead) return 0;
    const u = -d / lead;
    return ease((1 - u) / 0.32) * ease(u / 0.22);
  }
  function parseColor(c) {
    c = String(c).trim();
    if (c[0] === "#") {
      const h = c.length === 4
        ? c[1] + c[1] + c[2] + c[2] + c[3] + c[3] : c.slice(1);
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16),
              parseInt(h.slice(4, 6), 16), 1];
    }
    const n = c.replace(/^rgba?\(|\)$/g, "").split(",").map(parseFloat);
    return [n[0], n[1], n[2], n.length > 3 ? n[3] : 1];
  }

  function create(ctx) {
    const REST_RGBA = parseColor(ctx.cfg.rest_color || "rgba(255,255,255,.9)");
    const _mixCache = new Map();

    const cfg = () => ctx.cfg;
    const M = () => ctx.mapping;
    const EX = () => ctx.expression;

    function colorFor(s) { return (ctx.cfg.speakers || {})[s] || "#E5E517"; }
    // Quantized to 32 steps: the eye cannot resolve finer, and it keeps the
    // written colour string stable across frames so most writes become no-ops.
    function mixColor(speaker, f) {
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
    // Unknown speakers stay white; provisional gets a subdued share of colour.
    function wordColor(w, f) {
      const status = speakerStatus(w);
      const strength = status === "unknown" ? 0 :
        (status === "provisional" ? ctx.cfg.provisional_color_strength : 1);
      return mixColor(w.speaker, f * strength);
    }

    function pitchAxis(m, hz) {
      const d = m.domain_hz || M().pitch_to.domain_hz;
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

    // EVERY word rests at the SAME baseline size/weight. Prosody is only the
    // amplitude of the envelope it swells through while spoken — emphScale is a
    // ratio against the common rest, so a median word is ~1.0, a loud word
    // larger, a quiet one smaller. Nothing is baked in: after the envelope
    // decays a word is identical in size/weight to its neighbours.
    function typeOf(w) {
      const C = cfg(), m = M(), ex = EX();
      const sm = m.loudness_to;
      const anchorPct = C.size_pct || sm.baseline;
      const k = anchorPct / sm.baseline;
      const smMin = sm.min * k, smMax = sm.max * k;
      const rawSize = lerp(smMin, smMax, clamp01(w.loudness));
      const medSize = lerp(smMin, smMax, ctx.medianLoudness);
      const emphPct = towardBaseline(rawSize - medSize + anchorPct, anchorPct,
                                     ex.size_response, smMin, smMax);
      const isVoiced = w.pitch_hz > 0 && w.voiced_frac >= C.min_voiced_frac;
      const wm = m.pitch_to;
      const wBand = ex.anchor_wght || [350, 700];
      const wAnchor = clamp(ctx.medianPitch === null ? 400 : pitchAxis(wm, ctx.medianPitch),
                            wBand[0], wBand[1]);
      const wRange = ex.wght_range || [wm.min, wm.max];
      const wght = Math.round(clamp(clamp(isVoiced
        ? towardBaseline(pitchAxis(wm, w.pitch_hz), wAnchor, ex.weight_response, wm.min, wm.max)
        : wAnchor, wm.min, wm.max), wRange[0], wRange[1]));
      let wdth = 100;
      if (m.harmonics_to) {
        const hm = m.harmonics_to;
        const hBand = ex.anchor_wdth || [88, 112];
        const hAnchor = clamp(ctx.medianPitch === null ? 100 : pitchAxis(hm, ctx.medianPitch),
                              hBand[0], hBand[1]);
        const hRange = ex.wdth_range || [hm.min, hm.max];
        wdth = Math.round(clamp(clamp(isVoiced
          ? towardBaseline(pitchAxis(hm, w.pitch_hz), hAnchor, ex.width_response, hm.min, hm.max)
          : hAnchor, hm.min, hm.max), hRange[0], hRange[1]));
      }
      let emphScale = emphPct / Math.max(1e-6, anchorPct);
      // A quiet word should barely deform rather than visibly shrink.
      if (emphScale < 1) emphScale = 1 - (1 - emphScale) * C.quiet_deformation;
      // Deadband: ordinary delivery is pinned to exactly 1 (no envelope, no
      // writes); only a genuine deviation animates.
      const dev = Math.abs(emphScale - 1);
      emphScale = dev <= C.emphasis_deadband ? 1
        : 1 + Math.sign(emphScale - 1) * (dev - C.emphasis_deadband);
      return {restPct: anchorPct, emphScale: emphScale,
              restWght: Math.round(wAnchor / 4) * 4, emphWght: wght, wdth: wdth};
    }

    // §2.2.3 SYNCHRONIZATION cue: one envelope, identical for every word,
    // centred on the moment it changes colour — rises, peaks just past the turn,
    // returns to rest. Zero slope at both ends.
    function syncAt(t, tTurn) {
      const C = cfg();
      const d = t - (tTurn + C.sync_peak_s);
      if (d < 0) {
        const rise = Math.max(1e-3, C.sync_rise_s + C.sync_peak_s);
        return d <= -rise ? 0 : ease(1 + d / rise);
      }
      const fall = Math.max(1e-3, C.sync_fall_s);
      return d >= fall ? 0 : 1 - ease(d / fall);
    }
    function turnOf(node) { return node.w.start; }

    // §2.3 INTONATION: word-level envelope, uniform over every letter. Begins to
    // swell `emphasis_lead_s` before the spoken onset, peaks near the stressed
    // portion, holds while spoken, then decays back to the common rest.
    function intonationAt(t, w) {
      const C = cfg();
      const span = Math.max(1e-3, w.end - w.start);
      const peak = w.start + 0.3 * span;
      const tail = Math.max(1e-3, C.emphasis_tail_s);
      const from = w.start - Math.max(1e-3, C.emphasis_lead_s);
      if (t < peak) return ease((t - from) / Math.max(1e-3, peak - from));
      const held = Math.max(peak + C.emphasis_hold_s, w.end);
      if (t <= held) return 1;
      return 1 - ease((t - held) / tail);
    }

    // MEASURED replay: when a word carries baked `motion`, replay it verbatim.
    function sampleMotion(mm, ch, t, rest) {
      const a = mm[ch], n = a.length;
      const f = (t - mm.t0) / mm.dt;
      if (!n || f < 0 || f > n - 1) return rest;
      if (f === 0) return a[0];
      if (f === n - 1) return a[n - 1];
      const i = f | 0;
      return a[i] + (a[i + 1] - a[i]) * (f - i);
    }
    function isReplay() { return cfg().motion_source === "measured"; }

    // The three animated channels. Each takes the measured curve when the word
    // has one, else the parametric envelope. INTONATION (word amplitude) and
    // SYNCHRONIZATION (the fixed +15% pop) are composed, never collapsed.
    function scaleOf(t, node) {
      const mo = node.w.motion;
      if (isReplay() && mo) return sampleMotion(mo, "scale", t, 1);
      const env = 1 + (node.el._type.emphScale - 1) * intonationAt(t, node.w);
      return env * (1 + cfg().sync_pop * syncAt(t, turnOf(node)));
    }
    function liftOf(t, node) {
      const mo = node.w.motion;
      if (isReplay() && mo) return cfg().glyph_height_em * sampleMotion(mo, "lift", t, 0);
      return cfg().sync_elevation_em * syncAt(t, turnOf(node));
    }
    function wghtOf(t, node, env) {
      const ty = node.el._type, mo = node.w.motion, ex = EX();
      const w = (isReplay() && mo) ? ty.restWght + sampleMotion(mo, "dwght", t, 0)
                                   : lerp(ty.restWght, ty.emphWght, env);
      return Math.round(clamp(w, ex.wght_range ? ex.wght_range[0] : 100,
                              ex.wght_range ? ex.wght_range[1] : 1000) / 4) * 4;
    }

    // The moment a letter turns colour. The character sweep spreads the turns
    // across the word's own span (the mid-word colour split, "Roya|le"); a
    // whole-word turn fires them together.
    function turnAt(node, c) {
      const span = Math.max(1e-3, node.w.end - node.w.start);
      return ctx.charSweep
        ? node.w.start + (c + 0.5) / node.chars.length * span
        : node.w.start;
    }
    // Soft turn: the letter crossfades over color_turn_ms instead of flipping.
    function charColorAt(node, c, t) {
      const turnS = Math.max(1e-3, cfg().color_turn_ms / 1000);
      return wordColor(node.w, ease((t - turnAt(node, c)) / turnS));
    }

    // The website reference is not a rigid word-only bounce. Intonation
    // (scale/weight) is uniform on the word wrapper, while synchronization has
    // a second, character-local hand-off: each letter crouches slightly before
    // its own turn, rises/pops just after it, then returns to the shared
    // baseline. All letters are already visible; this is motion, not a
    // typewriter reveal.
    function charLiftOf(t, node, c) {
      if (ctx.reduced || !ctx.waveOn) return 0;
      const C = cfg();
      const reach = Number(C.char_sync_reach ?? 1);
      if (!(reach > 0)) return 0;
      const d = t - turnAt(node, c);
      const lift = Number(C.char_sync_lift_em ?? 0.10) *
        pulse(d, Math.max(1e-3, Number(C.char_sync_fall_s ?? 0.26)),
              Math.max(1e-3, Number(C.char_sync_peak_s ?? 0.10)));
      const crouchLift = Number(C.char_sync_crouch_em ?? 0.025) *
        crouch(d, Math.max(1e-3, Number(C.char_sync_lead_s ?? 0.14)));
      return reach * (lift - crouchLift);
    }
    function charScaleOf(t, node, c) {
      if (ctx.reduced || !ctx.waveOn) return 1;
      const C = cfg();
      const reach = Number(C.char_sync_reach ?? 1);
      if (!(reach > 0)) return 1;
      const d = t - turnAt(node, c);
      const pop = Number(C.char_sync_pop ?? 0.07) *
        pulse(d, Math.max(1e-3, Number(C.char_sync_pop_fall_s ??
                                      C.char_sync_fall_s ?? 0.26)),
              Math.max(1e-3, Number(C.char_sync_pop_peak_s ??
                                    C.char_sync_peak_s ?? 0.10)));
      const dip = Number(C.char_sync_dip ?? 0) *
        crouch(d, Math.max(1e-3, Number(C.char_sync_lead_s ?? 0.14)));
      return Math.max(0.5, 1 + reach * (pop - dip));
    }
    function charTransform(lift, scale) {
      if (Math.abs(lift) < 0.00005 && Math.abs(scale - 1) < 0.00005) {
        return "none";
      }
      return "translate3d(0," + (-lift).toFixed(4) +
             "em,0) scale(" + scale.toFixed(4) + ")";
    }

    function wordTransform(shift, lift, scale) {
      return "translate3d(" + shift.toFixed(2) + "px," + (-lift).toFixed(4)
           + "em,0) scale(" + scale.toFixed(4) + ")";
    }
    function varSettings(ty, wght) {
      return '"opsz" 14, "wght" ' + wght + ', "wdth" ' + ty.wdth;
    }

    // Analytic neighbour-push. A word at scale S widens by dW = restW*(S-1),
    // spilling dW/2 past each resting edge; word i's shift is everything that
    // grew before it plus half its own growth, minus half the row's total growth
    // (re-centres the row). Pure arithmetic on measurements taken once — never
    // touches the layout path. `nodes` each need {restRow, restW, el, w}; writes
    // node.shift and node._dW. Rows keyed on resting offsetTop resolve
    // independently. Pass a getScale(t,node) so live can share cc's scaleOf.
    function resolveNeighborPush(nodes, t, getScale) {
      const rows = new Map();
      for (const node of nodes) {
        const s = (getScale || scaleOf)(t, node);
        node._dW = node.restW * (s - 1);
        rows.set(node.restRow, (rows.get(node.restRow) || 0) + node._dW);
      }
      const acc = new Map();
      for (const node of nodes) {
        const before = acc.get(node.restRow) || 0;
        node.shift = before + node._dW / 2 - rows.get(node.restRow) / 2;
        acc.set(node.restRow, before + node._dW);
      }
    }

    return {
      lerp, clamp01, clamp, ease, pulse, crouch, parseColor,
      colorFor, mixColor, speakerStatus, wordColor,
      pitchAxis, towardBaseline, typeOf,
      syncAt, turnOf, intonationAt, sampleMotion,
      scaleOf, liftOf, wghtOf, turnAt, charColorAt,
      charLiftOf, charScaleOf, charTransform,
      wordTransform, varSettings, resolveNeighborPush
    };
  }

  return Object.freeze({ create, parseColor, lerp, clamp, clamp01, ease, pulse, crouch });
}));
