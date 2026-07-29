"""Run a deterministic live-render trace in the repository's headless Chrome.

This does not load speech models or contact a service. It injects synthetic SSE
records into the generated local page, then reports coalescing, DOM, revision,
motion, and geometry metrics for every display mode.

    .venv/bin/python scripts/live_render_probe.py
"""

from __future__ import annotations

import copy
import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autocwi.config import load_config  # noqa: E402
from autocwi.livepage import render_live  # noqa: E402


CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
MODES = ("stable", "fast", "readahead", "sentence")

PROBE = r"""
<script>
addEventListener("load", () => {
  const renderer = window.__cwiRenderer;
  const base = {
    type: "word", word_id: "u0:w0", utterance: 0, text: "hello",
    t: 0.05, start: 0.05, end: 0.35,
    text_revision_id: 3, timing_revision_id: 1,
    speaker: "S1", speaker_known: true, speaker_status: "provisional",
    speaker_confidence: 0.65, speaker_revision_id: 1,
    loudness: 0.5, pitch: 0.5, loudness_db: -30,
    pitch_hz: 180, voiced_frac: 0.9, conf: 0.9, conf_available: true,
    final: false, verified: false
  };
  for (let i = 0; i < 20; i++) {
    renderer.dispatch({
      type: "level", t: i * 0.001, rms_db: -35 + i / 10,
      floor_db: -60, gain_db: 0, status: "good", speech: true,
      pitch_hz: 180 + i * 2, pitch_confidence: .82,
      spectral_centroid_hz: 1400 + i * 30
    }, i + 1);
  }
  renderer.flushLevel();
  const onset = {
    ...base, text: "Hel", text_revision_id: 0, timing_revision_id: 4,
    src: "onset", sustain_active: true, sustain_s: 1.1
  };
  renderer.dispatch({type: "hypothesis", utterance: 0, onset: true,
                     words: [onset]}, 28);
  renderer.flush();
  const onsetNode = document.querySelector("#captionRack .cwi-word");
  const sustainBeforeAuthoritative = onsetNode ? {
    active: onsetNode.dataset.sustainActive,
    width: onsetNode.style.getPropertyValue("--sustain-width"),
    text: onsetNode.textContent
  } : null;
  const draft = {...base, text: "hel", text_revision_id: 1, src: "draft"};
  const accurate = {...base, text: "hello", text_revision_id: 3, src: "accurate"};
  renderer.dispatch({type: "hypothesis", utterance: 0, words: [draft]}, 30);
  renderer.dispatch({type: "hypothesis", utterance: 0, words: [accurate]}, 31);
  renderer.flush();
  const firstMotionStarts =
    window.__cwiRenderDiag.report().displayMotionStarts;
  const firstEntryStarts =
    window.__cwiRenderDiag.report().characterEntryStarts;
  const firstNode = document.querySelector("#captionRack .cwi-word");
  const firstType = firstNode ? {
    restWeight: firstNode._type.restWght,
    peakWeight: firstNode._type.emphWght,
    weightDelta: firstNode._type.emphWght - firstNode._type.restWght
  } : null;
  const firstChars = firstNode ? Array.from(
    firstNode.querySelectorAll(".cwi-ch")
  ) : [];
  const entryShape = firstChars.slice(0, 2).map(char => {
    const animation = char.getAnimations()[0];
    return animation ? {
      delay: animation.effect.getTiming().delay,
      keyframes: animation.effect.getKeyframes().map(frame => ({
        opacity: frame.opacity,
        transform: frame.transform
      }))
    } : null;
  });
  renderer.dispatch({
    type: "hypothesis", utterance: 0,
    words: [{...accurate, text: "Hello", text_revision_id: 4}]
  }, 32);
  renderer.flush();
  const startsAfterTextRevision =
    window.__cwiRenderDiag.report().displayMotionStarts;
  const entryStartsAfterTextRevision =
    window.__cwiRenderDiag.report().characterEntryStarts;
  renderer.dispatch({...base, type: "cue"}, 32);
  renderer.dispatch({...base, type: "commit", provisional: true}, 33);
  renderer.flushLevel();
  renderer.flush();
  const afterColor = window.__cwiRenderDiag.report();
  const circle = document.querySelector(".intent-circle");
  const circleState = circle ? {
    scale: circle.style.getPropertyValue("--voice-scale"),
    pitchY: circle.style.getPropertyValue("--pitch-y"),
    textureX: circle.style.getPropertyValue("--texture-x"),
    textureOpacity: circle.style.getPropertyValue("--texture-opacity")
  } : null;
  const compass = document.getElementById("voiceCompass");
  const compassState = compass ? {
    scale: compass.style.getPropertyValue("--compass-scale"),
    pitchY: compass.style.getPropertyValue("--pitch-y"),
    textureX: compass.style.getPropertyValue("--texture-x"),
    textureSize: compass.style.getPropertyValue("--texture-size"),
    direction: compass.dataset.direction
  } : null;
  renderer.advanceMotion(performance.now() + 100);
  const node = document.querySelector("#captionRack .cwi-word");
  const before = node ? {width: node.offsetWidth, height: node.offsetHeight} : null;
  const stable = {
    ...base, type: "word", final: true, verified: true, provisional: false,
    speaker_status: "stable", speaker_confidence: 0.9,
    text_revision_id: 3, speaker_revision_id: 2
  };
  renderer.dispatch({
    type: "verification", utterance: 0, text: "hello", words: [stable]
  }, 34);
  renderer.dispatch({
    ...stable, speaker: "S2", speaker_status: "corrected",
    speaker_revision_id: 3, correction: true
  }, 35);
  // Delayed provisional attribution must not roll the correction back.
  renderer.dispatch({
    ...base, speaker: "S3", speaker_status: "provisional",
    speaker_revision_id: 1
  }, 29);
  renderer.flush();
  renderer.advanceMotion(performance.now() + 1000);
  // A direct accurate commit with no preceding tail and an expired acoustic
  // window exercises the sample's common path. Its first paint gets the same
  // fixed CWI cue; old acoustic timing does not suppress visible activation.
  renderer.dispatch({
    ...base, type: "commit", word_id: "u1:w0", utterance: 1, text: "world",
    t: -1, start: -1, end: -0.7, speaker_status: "stable",
    speaker_revision_id: 4
  }, 36);
  renderer.flush();
  const settled = document.querySelector("#captionRack .cwi-word");
  const after = settled ?
    {width: settled.offsetWidth, height: settled.offsetHeight} : null;
  const report = {
    mode: CFG.display_mode,
    nodeCount: renderer.nodeCount(),
    word: renderer.wordState("u0:w0"),
    firstType: firstType,
    sustainBeforeAuthoritative: sustainBeforeAuthoritative,
    circle: circleState,
    compass: compassState,
    latencyPolicy: {
      lateNextDeadline: RenderCore.nextRevealDeadline(220, 520, 140, 60)
    },
    geometry: {
      before: before,
      after: after
    },
    displayMotion: {
      startsAfterFirstPaint: firstMotionStarts,
      startsAfterTextRevision: startsAfterTextRevision,
      startsAfterColor: afterColor.displayMotionStarts
    },
    characterEntry: {
      startsAfterFirstPaint: firstEntryStarts,
      startsAfterTextRevision: entryStartsAfterTextRevision,
      startsAfterColor: afterColor.characterEntryStarts,
      firstTwoCharacters: entryShape
    },
    metrics: window.__cwiRenderDiag.report()
  };
  document.title = "LIVE_RENDER_PROBE " + JSON.stringify(report);
});
</script>
"""


def run_mode(mode: str) -> dict:
    config = copy.deepcopy(load_config())
    config["display"]["mode"] = mode
    tmp = Path(tempfile.mkdtemp(prefix=f"autocwi-render-{mode}-"))
    page = Path(render_live(config, tmp))
    probe = tmp / "probe.html"
    probe.write_text(
        page.read_text(encoding="utf-8").replace("</body>", PROBE + "</body>"),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--window-size=1440,900",
            "--timeout=5000",
            "--dump-dom",
            probe.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    marker = "<title>LIVE_RENDER_PROBE "
    if marker not in completed.stdout:
        raise RuntimeError(
            f"Chrome probe failed for {mode} (exit {completed.returncode}):\n"
            + completed.stderr[-2000:]
        )
    payload = completed.stdout.split(marker, 1)[1].split("</title>", 1)[0]
    return json.loads(html.unescape(payload))


def main() -> None:
    if not CHROME.is_file():
        raise SystemExit(f"Chrome not found at {CHROME}")
    reports = [run_mode(mode) for mode in MODES]
    print(json.dumps(reports, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
