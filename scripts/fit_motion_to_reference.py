"""Fit cc's per-character motion constants to the reference recordings.

Usage (frames first, at the recording's true rate)::

    ffmpeg -i "docs/Screen Recording ... 11.38.00 PM.mov" \
        -vf "crop=3456:210:0:1050" -vsync 0 /tmp/f38/n_%04d.png
    python scripts/fit_motion_to_reference.py "/tmp/f38/n_*.png" 57.11 sync

Add ``--scroll`` for the two recordings whose caption line travels
horizontally; without it, nearest-centre tracking fragments them.

The crop is the caption band; find it by looking for the rows with the most
bright pixels. The frame rate is nframes/duration -- these are ~57 fps screen
captures, not the 120 fps the container claims.

Tracks individual glyphs frame to frame, finds each one's colour turn from its
saturation (unspoken text is white/grey = unsaturated; spoken text takes the
speaker's colour), and aligns that glyph's vertical trajectory and size to its
own turn. Averaging over every tracked glyph gives the empirical per-letter
curve that `closed_caption`'s constants are fitted to.

The measurement itself lives in ``autocwi.refmeasure`` so that the comparison
harness scores our own render with byte-identical code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autocwi.refmeasure import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), sys.argv[3],
         scroll="--scroll" in sys.argv)
