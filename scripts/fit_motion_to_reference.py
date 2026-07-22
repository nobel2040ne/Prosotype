"""Measure the AVERAGE per-glyph motion curve out of a reference recording.

Usage (frames first, at the recording's true rate)::

    ffmpeg -i docs/reference/synchronization.mov \
        -vf "crop=3456:210:0:1075" -vsync 0 /tmp/sync/n_%04d.png
    python scripts/fit_motion_to_reference.py "/tmp/sync/n_*.png" 57.1256 sync

Add ``--scroll`` for a recording whose caption line travels horizontally;
without it, nearest-centre tracking fragments into thousands of one-frame
tracks. The frame rate is nframes/duration -- these are ~57 fps screen
captures, not the 120 fps the container claims.

NOTE ON WHAT THIS IS FOR NOW. It used to fit the renderer's motion constants.
It no longer does: the design system states the amplitudes outright (2.2.3,
+15% type size and 25% elevation, per word at the colour turn) and those are
what ship, so only the cue's TIMING is still taken from here -- the rise, the
peak offset past the turn, and the fall, which feed `closed_caption.sync_*_s`.

It also averages over EVERY glyph in the recording, which is exactly what makes
it useless for per-word work: the average of a word that swells and a word that
does not is a word that moves a little, and handing that to every word is how
motion ended up on words the reference leaves still. Per-word measurement is
`scripts/derive_reference_spec.py`.

Tracks individual glyphs frame to frame, finds each one's colour turn from its
saturation (unspoken text is white/grey = unsaturated; spoken text takes the
speaker's colour), and aligns that glyph's vertical trajectory and size to its
own turn. The measurement itself lives in ``autocwi.refmeasure`` so every
caller segments pixels with byte-identical code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autocwi.refmeasure import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), sys.argv[3],
         scroll="--scroll" in sys.argv)
