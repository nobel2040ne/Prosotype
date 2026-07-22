"""Capture the JS prosody map into a golden fixture.

``autocwi/ccprosody.py`` mirrors ``typeOf()`` from ``ccpage.py`` in Python so a
reference spec can be derived by inverting it. A hand-written mirror of code in
another language WILL drift, so this captures the real thing:

    .venv/bin/python scripts/dump_forward_map.py

renders a probe page, evaluates the page's own ``typeOf`` over a grid of
(loudness, pitch_hz), reads it back through headless Chrome, and writes
``tests/fixtures/forward_map_golden.json`` together with the ``mapping`` /
``expression`` / ``closed_caption`` values it was captured under.

``tests/test_reference.py`` then asserts (a) Python reproduces every entry and
(b) that stored config still matches ``config.yaml`` — so changing, say,
``expression.size_response`` fails with "re-run dump_forward_map.py" instead of
letting the two implementations diverge in silence.

Run by hand after touching `mapping`, `expression` or `typeOf`. Never run by
the test suite (it needs Chrome).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autocwi.ccpage import render_cc          # noqa: E402
from autocwi.config import load_config        # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
N = 21

PROBE = """
<script>addEventListener("load",()=>{ try{
  const out=[];
  for (let i=0;i<%d;i++){
    for (let j=0;j<%d;j++){
      const loudness = i/(%d-1);
      const hz = 80 + (250-80)*j/(%d-1);
      // medians are module state in the page; drive typeOf through a word and
      // read what the renderer would actually use.
      const t = typeOf({text:"x", start:0, end:1, speaker:"S1",
                        loudness: loudness, pitch_hz: hz, voiced_frac: 0.9});
      out.push([loudness, hz, t.emphScale, t.emphWght, t.restWght, t.wdth,
                t.restPct]);
    }
  }
  document.title = "GOLDEN " + JSON.stringify({
      median_loudness: medianLoudness,
      median_pitch: medianPitch,
      grid: out});
 }catch(e){ document.title = "GOLDEN ERR " + e.message; }});</script>
""" % (N, N, N, N)


def main() -> None:
    cfg = load_config()
    # One word at each end so medianLoudness/medianPitch are deterministic and
    # the golden records exactly what they were.
    spec = {
        "version": "1.0",
        "media": {"path": "probe", "duration": 2.0, "fps": 30.0},
        "speakers": {"S1": {"color": cfg["palette"][0]}},
        "words": [{"text": "probe", "start": 0.1, "end": 0.9, "speaker": "S1",
                   "loudness": 0.5, "pitch": 0.5, "loudness_db": -24.0,
                   "pitch_hz": 165.0, "voiced_frac": 0.9, "conf": 0.95}],
        "mapping": cfg["mapping"],
    }
    tmp = Path(tempfile.mkdtemp())
    page = Path(render_cc(cfg, spec, tmp))
    probe = tmp / "probe.html"
    probe.write_text(page.read_text(encoding="utf-8").replace("</body>", PROBE + "</body>"),
                     encoding="utf-8")
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--window-size=1200,700",
         "--timeout=20000", "--dump-dom", probe.resolve().as_uri()],
        capture_output=True, text=True).stdout
    marker = "<title>GOLDEN "
    if marker not in dom:
        raise SystemExit("probe did not report; is Chrome present?")
    payload = dom.split(marker, 1)[1].split("</title>", 1)[0]
    if payload.startswith("ERR"):
        raise SystemExit("probe failed in page: " + payload)
    data = json.loads(payload.replace("&quot;", '"').replace("&amp;", "&"))
    data["config"] = {
        "mapping": cfg["mapping"],
        "expression": cfg["expression"],
        "closed_caption": {k: cfg["closed_caption"][k]
                           for k in ("size_pct", "quiet_deformation",
                                     "emphasis_deadband")},
        "normalization": {"min_voiced_frac": cfg["normalization"]["min_voiced_frac"]},
    }
    out = ROOT / "tests" / "fixtures" / "forward_map_golden.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {out} ({len(data['grid'])} points, "
          f"median_loudness={data['median_loudness']}, "
          f"median_pitch={data['median_pitch']})")


if __name__ == "__main__":
    main()
