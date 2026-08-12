"""Read direction of arrival off a stock ReSpeaker XVF3800.

No host binary and no firmware change: every value here is a USB control
transfer on EP0, the same protocol `xvf_host` speaks.

Two things this file exists to get right:

- **`DOA_VALUE` is a little-endian uint16, not a byte.** Read as one byte it
  wraps at 256, which looks correct at the ~133 deg a board reports at rest
  and puts a talker behind the array in front of it past 255.
- **A bearing is only a fact while speech is detected.** The board holds its
  last bearing when the room goes quiet, so ignoring the speech flag reports a
  confident direction at whoever spoke last, indefinitely. `read_bearing()`
  returns None: never fabricate direction.
"""

from __future__ import annotations

import struct

VID = 0x2886
PID = 0x001A
TIMEOUT_MS = 5000

# name -> (resid, cmdid, payload_bytes, kind) Payload is in BYTES here.
PARAMETERS = {
    "VERSION": (48, 0, 3, "u8"),
    # payload[0] = bearing 0..359, payload[1] = 1 if speech detected
    "DOA_VALUE": (20, 18, 4, "u16x2"),
    "AEC_AZIMUTH_VALUES": (33, 75, 16, "f32x4"),
    # "Any value above 0 indicates speech." A four-way SPATIAL VAD, and a much
    # richer diarization cue than the single auto-selected bearing.
    "AEC_SPENERGY_VALUES": (33, 80, 16, "f32x4"),
    # [0] processed DoA (speech-energy-selected across the fixed beams),
    # [1] the auto-select beam's DoA. NaN when no fixed beam holds speech.
    "AUDIO_MGR_SELECTED_AZIMUTHS": (35, 11, 8, "f32x2"),
}


class XvfControl:
    """A stock XVF3800's control lane. Construct via :func:`open_array`."""

    def __init__(self, dev):
        self.dev = dev

    def read(self, name: str):
        import usb.util

        resid, cmdid, length, kind = PARAMETERS[name]
        raw = self.dev.ctrl_transfer(
            usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR
            | usb.util.CTRL_RECIPIENT_DEVICE,
            0, 0x80 | cmdid, resid, length + 1, TIMEOUT_MS)
        body = raw.tobytes()[1:]          # byte 0 is status, not data
        if kind == "u8":
            return list(body)
        if kind == "u16x2":
            return list(struct.unpack("<HH", body))
        if kind == "f32x2":
            return list(struct.unpack("<ff", body))
        return list(struct.unpack("<ffff", body))

    # Speech energy of a few units is normal; the corrupted reads described in
    # `beam_speech_energy` come back in the tens of thousands.
    ENERGY_CEILING = 1000.0

    # Beam azimuths arrive in radians; anything outside +-2pi is a corrupt read.
    MAX_AZIMUTH_RAD = 7.0

    def read_beam_bearing(self) -> float | None:
        """Bearing from the auto-select beam, gated on that beam's speech energy.

        Ten times the recall of `read_bearing`, which is gated on the board's
        VAD: measured over 371 polls, 50% of reads carry a bearing here against
        5% there. That matters when direction is meant to separate a speaker
        the voice lane has not decided on yet -- a signal present 5% of the
        time cannot do that however good it is when present.

        It is looser evidence, and the numbers say so: circular concentration
        0.83 against the VAD gate's 1.00 over the same window. One dominant
        direction plus outliers, not a clean point. Callers that need
        precision over recall should still use `read_bearing`.

        The energy threshold is deliberately just above zero. Sweeping it
        changes nothing until the signal disappears entirely -- coverage runs
        50%, 49%, 49%, 48%, 48% for thresholds 0, 0.5, 1, 2, 4 and then nothing
        at 8 -- so there is no threshold that buys concentration, and a larger
        one would only look like tuning.
        """
        energies = self.beam_speech_energy()
        if energies is None or energies[3] <= 0.0:
            return None
        azimuths = self.read("AEC_AZIMUTH_VALUES")
        if any(abs(a) > self.MAX_AZIMUTH_RAD for a in azimuths):
            return None                      # corrupt interleaved read
        import math

        return math.degrees(azimuths[3]) % 360.0

    def beam_speech_energy(self) -> list[float] | None:
        """Per-beam speech energy, or None if the read came back corrupt.

        Beam order: beam 1, beam 2, free-running, auto-select. Above zero
        means speech on that beam. Two talkers at different bearings light
        different beams, which is spatial evidence for diarization that no
        single-bearing reading can express.

        **Validate, do not space.** Reading two DIFFERENT commands in quick
        succession intermittently returns one command's data for the other:
        measured 3/12 corrupt at no gap and 1/12 at 150 ms, but 0/12 at both
        50 ms and 300 ms -- so the corruption does not fall off with spacing
        and no delay makes it safe. Values of 89562 and 228089 turned up where
        a few units were expected. Range-check every read instead.
        """
        values = self.read("AEC_SPENERGY_VALUES")
        if any(not 0.0 <= v < self.ENERGY_CEILING for v in values):
            return None
        return values

    def version(self) -> str:
        return ".".join(str(v) for v in self.read("VERSION"))

    def read_bearing(self) -> float | None:
        """Degrees if speech is being heard right now, else None.

        None is the honest answer, not a failure: the field is meant to be
        ABSENT when nothing was measured, so that the compass shows
        `awaiting array` rather than pointing at a stale talker.

        **Out-of-range readings are rejected, not wrapped.** The firmware
        documents 0..359, and this board intermittently returns a corrupted
        response when different commands are read close together. `% 360` on a
        corrupt value yields a perfectly plausible bearing -- a confident wrong
        claim about the room, which is the one thing direction must never make.
        """
        degrees, speech = self.read("DOA_VALUE")
        if not speech:
            return None
        if not 0 <= degrees <= 359:
            return None
        return float(degrees)

    def beam_azimuths_deg(self) -> list[float]:
        """The four beams' azimuths. The last is the auto-selected beam."""
        import math

        return [math.degrees(a) for a in self.read("AEC_AZIMUTH_VALUES")]

    def close(self) -> None:
        import usb.util

        usb.util.dispose_resources(self.dev)


def open_array(vid: int = VID, pid: int = PID) -> XvfControl | None:
    """The array's control lane, or None with the reason printed by caller."""
    try:
        import usb.core
    except ImportError:
        return None
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        return None
    return XvfControl(dev)
