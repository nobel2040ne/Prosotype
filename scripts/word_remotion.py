"""Does a word that has already settled MOVE AGAIN?

    .venv/bin/python -m autocwi live --sample --lang en --no-open &
    .venv/bin/python scripts/word_remotion.py 34

Everything is frozen at first sight by rule — duration, axes, sweep, hold gap
and turn moment — so a settled word must stay settled. Restarting one is the
bug this project re-commits most.

It caught a real defect: the 2.3 voice axes were recomputed on every render,
and the speaker's running register keeps moving, so a finished word was
re-derived minutes later and visibly re-ran its motion.

TWO TRAPS, both of which gave confident wrong answers first:

  A PRE-TURN REMOUNT IS NOT A RE-MOTION. A word waiting to turn sits at rest in
  its `backwards` fill, and a row re-break rebuilds it there. Filtering on a
  negative `--turn-delay` took 14 false positives to 1 real one.

  READ THE ANIMATION INPUTS, not just the geometry. Knowing a word moved says
  nothing about why; capturing the phase, scale, pop and weight at that moment
  named the cause on the first run.

A word counts as settled once it has been at rest for several consecutive
samples AFTER having moved. Keyed by word id — keying by text merges repeats.
"""
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from motion_trace import CHROME, wait_for_debugger

PROBE = r"""
(() => [...document.querySelectorAll('.caption-word')].map((w) => {
  /* STAMP THE ELEMENT. A re-motion has two possible causes and they need
     different fixes: the element was REMOUNTED (React rebuilt it, so its
     animation-delay counts from the new mount), or the same element had its
     animation restarted in place (a changed animation-name or delay). The
     stamp survives only the second, so it tells them apart. */
  if (!w.dataset.probeStamp) { w.dataset.probeStamp = String(Math.random()); }
  const ink = w.querySelector('.word-ink') || w;
  const glyph = w.querySelector('.word-glyph') || w;
  const m = getComputedStyle(glyph).transform;
  let sy = 1, ty = 0;
  if (m && m.startsWith('matrix(')) {
    const p = m.slice(7, -1).split(',').map(Number);
    sy = Math.abs(p[3]); ty = p[5];
  }
  const cs = getComputedStyle(w);
  const vars = {};
  for (const k of ['--voice-envelope', '--sync-envelope', '--motion-duration',
                   '--crest-duration', '--voice-scale', '--sync-pop',
                   '--hold-lift', '--voice-weight', '--turn-delay',
                   '--crest-lag', '--sweep-duration', '--word-lift-em']) {
    vars[k] = cs.getPropertyValue(k).trim();
  }
  vars['animName'] = getComputedStyle(glyph).animationName;
  vars['animDur'] = getComputedStyle(glyph).animationDuration;
  vars['inkAnim'] = getComputedStyle(ink).animationName;
  return {vars, stamp: w.dataset.probeStamp,
          armed: w.dataset.armed,
          delay: w.style.getPropertyValue('--turn-delay'),
          id: w.dataset.wordId || (w.textContent || ''),
          text: (w.textContent || '').trim(),
          fs: parseFloat(getComputedStyle(ink).fontSize),
          sy, ty,
          wt: getComputedStyle(ink).fontWeight};
}))()
"""
proc = subprocess.Popen(
    [str(CHROME), "--headless=new", "--remote-debugging-port=9229",
     "--window-size=1280,720", "--no-first-run", "--disable-gpu",
     "--user-data-dir=/tmp/remotion-profile", "http://127.0.0.1:7337/"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
hist = {}
try:
    url = wait_for_debugger(9229)
    from websockets.sync.client import connect
    with connect(url, max_size=None) as ws:
        n = 0
        def ev(e):
            global n
            n += 1
            ws.send(json.dumps({"id": n, "method": "Runtime.evaluate",
                                "params": {"expression": e, "returnByValue": True}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == n:
                    return m["result"]["result"].get("value")
        end = time.time() + float(sys.argv[1])
        while time.time() < end:
            for w in ev(PROBE) or []:
                hist.setdefault(w["id"], []).append(w)
            time.sleep(0.03)
finally:
    proc.terminate()

# HOW LONG A WORD MUST BE STILL BEFORE A SECOND MOVE COUNTS AS A RE-MOTION.
REST_RUN = 3
offenders = []
for wid, samples in hist.items():
    if len(samples) < 20:
        continue
    base = min(s["fs"] for s in samples)
    def moving(s):
        return abs(s["sy"] - 1) > 0.004 or abs(s["ty"]) > 0.4 or s["fs"] > base * 1.004
    flags = [moving(s) for s in samples]
    if not any(flags):
        continue
    settled_at, run = None, 0
    for i, f in enumerate(flags):
        if f:
            if settled_at is not None:
                peak = max(s["sy"] * s["fs"] / base for s in samples[i:i + 12])
                remount = samples[i]["stamp"] != samples[settled_at]["stamp"]
                a, b = samples[settled_at]["vars"], samples[i]["vars"]
                # ONLY A WORD THAT HAS ALREADY TURNED CAN RE-MOTION.
                def turned(v):
                    d = (v.get('--turn-delay') or '0ms').replace('ms', '')
                    try: return float(d) < 0
                    except ValueError: return False
                if not (turned(a) and turned(b)):
                    break
                changed = {k: (a.get(k), b.get(k)) for k in a if a.get(k) != b.get(k)}
                offenders.append((samples[0]["text"], wid, i - settled_at, peak,
                                  "REMOUNTED" if remount else "restarted in place",
                                  changed))
                break
            run = 0
        else:
            run += 1
            if run >= REST_RUN and settled_at is None and any(flags[:i]):
                settled_at = i
# A WORD THAT PLAYS BACKWARDS.
backwards = []
for wid, samples in hist.items():
    if len(samples) < 12:
        continue
    base = min(s["fs"] for s in samples)
    sizes = [s["sy"] * s["fs"] / base for s in samples]
    peak = max(range(len(sizes)), key=lambda i: sizes[i])
    if sizes[peak] < 1.02:
        continue
    # How much of the climb was actually on screen, against the fall.
    rise = sizes[peak] - min(sizes[:peak + 1])
    fall = sizes[peak] - min(sizes[peak:])
    if fall > 0.02 and rise < fall * 0.25:
        backwards.append((samples[0]["text"], round(rise, 3), round(fall, 3),
                          peak))

print(f"\n{len(hist)} words watched, {sum(1 for v in hist.values() if len(v) >= 20)} long enough to judge")
print(f"words that played BACKWARDS (fell without having risen): {len(backwards)}")
for text, rise, fall, at in backwards[:8]:
    print(f"   {text!r:24} rose {rise:.3f} then fell {fall:.3f}, peak at sample {at}")
print(f"words that moved AGAIN after settling: {len(offenders)}")
for text, wid, gap, peak, how, changed in offenders[:12]:
    print(f"   {text!r:22} re-moved after {gap*0.03:5.2f}s to {peak:.3f}x  [{how}]")
    if not changed:
        print("      NOTHING CHANGED on the element -- not an input to its own animation")
    for k, (v0, v1) in changed.items():
        print(f"      {k:20} {v0!r} -> {v1!r}")
print("\n" + ("PASS — no settled word moved again." if not offenders
              else f"FAIL — {len(offenders)} words re-ran their motion"))
