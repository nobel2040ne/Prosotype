"""Wire protocol for the hardware node — framing, resync, and gap detection.

Fully offline: synthetic frames, and a loopback socket for the capture path
itself. No device, no LAN, no models. The hardware is checked by the
`scripts/hw/` probes, which are manual and need the Pi.
"""

import json
import socket
import threading

import numpy as np
import pytest

from autocwi import netaudio as na
from autocwi.live import SR, NodeLink


def _drain(reader: na.FrameReader, data: bytes) -> list[na.Frame]:
    return list(reader.feed(data))


def test_audio_round_trips_bit_exact():
    """float32 is on the wire precisely so prosody reads the captured level.

    `AudioChunk.samples` must stay at the true captured level because
    `loudness_db` is measured from it; a lossy transport would flatten whisper
    and shout toward each other before the pipeline ever saw them.
    """
    samples = np.array([0.0, 1.0, -1.0, 1e-7, -0.3333333], dtype=np.float32)
    frames = _drain(na.FrameReader(), na.pack_audio(7, samples))
    assert len(frames) == 1
    assert frames[0].kind == na.KIND_AUDIO
    assert frames[0].seq == 7
    np.testing.assert_array_equal(frames[0].samples(), samples)


def test_a_block_split_across_reads_yields_one_frame():
    """A socket read returns whatever arrived, not whole frames."""
    wire = na.pack_audio(1, np.zeros(1024, dtype=np.float32))
    reader = na.FrameReader()
    # Split inside the header, then inside the payload.
    assert _drain(reader, wire[:5]) == []
    assert _drain(reader, wire[5:40]) == []
    frames = _drain(reader, wire[40:])
    assert len(frames) == 1
    assert len(frames[0].samples()) == 1024


def test_several_frames_coalesced_into_one_read_all_arrive():
    reader = na.FrameReader()
    wire = b"".join(
        na.pack_audio(i, np.full(4, i, dtype=np.float32)) for i in range(5)
    )
    frames = _drain(reader, wire)
    assert [f.seq for f in frames] == [0, 1, 2, 3, 4]


def test_corrupt_frame_costs_one_frame_not_the_capture():
    """One bad frame must not end the stream — the reader scans for the next
    MAGIC. A capture that dies on a single corrupt byte is worse than a gap."""
    good = na.pack_audio(2, np.ones(8, dtype=np.float32))
    reader = na.FrameReader()
    frames = _drain(reader, b"\x00\x01\x02garbage" + good)
    assert [f.seq for f in frames] == [2]
    assert reader.resyncs == 1


def test_magic_split_across_reads_is_not_lost():
    """The resync path must not discard a partial MAGIC at the buffer tail."""
    good = na.pack_audio(3, np.ones(4, dtype=np.float32))
    reader = na.FrameReader()
    assert _drain(reader, b"junk" + good[:2]) == []
    frames = _drain(reader, good[2:])
    assert [f.seq for f in frames] == [3]


def test_control_frames_carry_json():
    reader = na.FrameReader()
    wire = (na.pack_hello(16_000, 1024)
            + na.pack_doa(41, 91.5, confidence=0.8)
            + na.pack_cue(3, "speaker_change", 270.0, 0.6))
    hello, doa, cue = _drain(reader, wire)

    assert hello.kind == na.KIND_HELLO
    assert hello.json()["sample_rate"] == 16_000

    assert doa.kind == na.KIND_DOA
    assert doa.seq == 41                      # references the audio block
    assert doa.json()["doa_deg"] == 91.5

    assert cue.kind == na.KIND_CUE
    assert cue.json() == {
        "flag": "speaker_change", "intensity": 0.6, "direction_deg": 270.0,
    }


def test_a_cue_without_direction_omits_the_field_rather_than_inventing_one():
    """`never fabricate direction` applies to the motors too: a word with no
    measured bearing must reach the node as absent, not as 0 degrees."""
    body = json.loads(na.pack_cue(1, "emphasis", None, 0.5)[na.HEADER_SIZE:])
    assert "direction_deg" not in body


@pytest.mark.parametrize("given, expected", [
    (-90.0, 270.0),     # the array reports signed bearings either side of front
    (450.0, 90.0),
    (360.0, 0.0),
    (0.0, 0.0),
])
def test_direction_wraps_into_0_360(given, expected):
    """The compass renders `--direction-angle` straight into a CSS rotation, so
    a bearing has to arrive already normalised rather than as -90 or 450."""
    frame, = _drain(na.FrameReader(), na.pack_doa(0, given))
    assert frame.json()["doa_deg"] == expected


def test_oversized_payload_is_refused():
    with pytest.raises(na.ProtocolError):
        na.pack(na.KIND_AUDIO, 0, b"\x00" * (na.MAX_PAYLOAD + 1))


def test_multichannel_audio_is_refused():
    """The array is multi-channel; the pipeline is mono. Downmixing belongs on
    the node, and a stereo block reaching the framer means it did not happen."""
    with pytest.raises(na.ProtocolError):
        na.pack_audio(0, np.zeros((64, 4), dtype=np.float32))


# --- gap detection -------------------------------------------------------
# TCP does not lose data mid-stream, so a sequence gap means the NODE dropped
# blocks. Live capture is lossless by rule, so that has to surface.


def test_contiguous_sequence_reports_no_gap():
    t = na.SequenceTracker()
    assert [t.observe(i) for i in range(5)] == [False] * 5
    assert t.dropped == 0 and t.gaps == 0


def test_first_block_of_a_stream_is_never_a_gap():
    """A capture may legitimately start at any sequence number."""
    t = na.SequenceTracker()
    assert t.observe(9_000) is False
    assert t.gaps == 0


def test_dropped_blocks_are_counted_and_flagged():
    t = na.SequenceTracker()
    t.observe(0)
    t.observe(1)
    assert t.observe(6) is True      # 2,3,4,5 never arrived
    assert t.dropped == 4
    assert t.gaps == 1
    assert t.observe(7) is False     # and the stream recovers


def test_a_backwards_sequence_is_treated_as_a_node_restart():
    """Reordering cannot happen over TCP, so a counter going backwards means
    the node restarted. Trusting it would make every later block look dropped."""
    t = na.SequenceTracker()
    t.observe(500)
    assert t.observe(0) is True
    assert t.observe(1) is False
    assert t.dropped == 0            # a restart lost nothing measurable


# --- NodeLink over a loopback socket -------------------------------------
# Still offline: no device, no LAN, no models. This is the capture path the
# hardware actually uses, so it is worth exercising for real rather than
# faking the socket.


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fake_node(port: int, frames: list[bytes], done: threading.Event) -> None:
    """Stand in for the Pi: connect, send frames, hold the socket open."""
    for _ in range(80):
        try:
            conn = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            break
        except OSError:
            threading.Event().wait(0.05)
    else:
        return
    with conn:
        for frame in frames:
            conn.sendall(frame)
        done.wait(timeout=3.0)


def _collect(link: NodeLink, stop: threading.Event, want: int) -> list:
    chunks = []
    for chunk in link.blocks(stop):
        chunks.append(chunk)
        if len(chunks) >= want:
            break
    stop.set()
    return chunks


def test_node_audio_becomes_audiochunks_with_a_continuous_source_clock():
    port = _free_port()
    block = np.full(1024, 0.25, dtype=np.float32)
    frames = [na.pack_hello(SR, 1024)]
    frames += [na.pack_audio(i, block) for i in range(3)]

    stop, done = threading.Event(), threading.Event()
    link = NodeLink(host="127.0.0.1", port=port)
    node = threading.Thread(target=_fake_node, args=(port, frames, done),
                            daemon=True)
    node.start()
    try:
        chunks = _collect(link, stop, 3)
    finally:
        done.set()

    assert len(chunks) == 3
    np.testing.assert_array_equal(chunks[0].samples, block)
    # The source clock advances by one block each time, so downstream timing is
    # identical to a local mic.
    assert chunks[0].source_start == pytest.approx(0.0)
    assert chunks[1].source_start == pytest.approx(1024 / SR)
    assert chunks[2].source_start == pytest.approx(2048 / SR)
    assert not any(c.discontinuity for c in chunks)


def test_a_node_side_drop_surfaces_as_a_discontinuity():
    """Live capture is lossless by rule. TCP cannot lose data mid-stream, so a
    sequence gap means the Pi itself dropped blocks — a real capture gap, which
    must reach the captioner rather than being silently concatenated."""
    port = _free_port()
    block = np.zeros(1024, dtype=np.float32)
    frames = [na.pack_audio(0, block),
              na.pack_audio(5, block)]        # 1..4 never sent

    stop, done = threading.Event(), threading.Event()
    link = NodeLink(host="127.0.0.1", port=port)
    threading.Thread(target=_fake_node, args=(port, frames, done),
                     daemon=True).start()
    try:
        chunks = _collect(link, stop, 2)
    finally:
        done.set()

    assert chunks[0].discontinuity is False
    assert chunks[1].discontinuity is True
    assert chunks[1].dropped_s == pytest.approx(4 * 1024 / SR)


def test_direction_expires_rather_than_freezing_a_stale_bearing():
    """`never fabricate direction`: an array that stops reporting must fall
    back to the compass's `awaiting array`, not hold its last answer."""
    port = _free_port()
    frames = [na.pack_doa(0, 137.0), na.pack_audio(0, np.zeros(64, "f4"))]

    stop, done = threading.Event(), threading.Event()
    link = NodeLink(host="127.0.0.1", port=port, doa_ttl_s=0.25)
    threading.Thread(target=_fake_node, args=(port, frames, done),
                     daemon=True).start()
    try:
        _collect(link, stop, 1)
        assert link.direction_deg == pytest.approx(137.0)
        threading.Event().wait(0.35)
        assert link.direction_deg is None
    finally:
        done.set()


def test_direction_is_none_before_any_array_reports():
    assert NodeLink(host="127.0.0.1", port=_free_port()).direction_deg is None


def test_send_cue_without_a_node_is_a_no_op_not_an_error():
    """A dead haptic link degrades to no vibration; it must never interrupt
    captions."""
    link = NodeLink(host="127.0.0.1", port=_free_port())
    assert link.send_cue("speaker_change", 90.0, 0.7) is False


# --- direction as attribution evidence -----------------------------------

def test_bearing_for_span_reads_the_word_not_the_latest_reading():
    """Attribution scores a WORD SPAN, so it needs the bearing during that
    span. Using the newest reading would score every word of an utterance
    against wherever the array was pointing when the endpoint fired."""
    port = _free_port()
    block = np.zeros(1024, dtype=np.float32)
    frames = [na.pack_hello(SR, 1024)]
    for i in range(4):
        frames.append(na.pack_doa(i, 10.0 + 90.0 * i))
        frames.append(na.pack_audio(i, block))

    stop, done = threading.Event(), threading.Event()
    link = NodeLink(host="127.0.0.1", port=port)
    threading.Thread(target=_fake_node, args=(port, frames, done),
                     daemon=True).start()
    try:
        _collect(link, stop, 4)
    finally:
        done.set()

    step = 1024 / SR
    # Each bearing is stamped where the NEXT block lands, so block i's bearing
    # sits at i * step.
    assert link.bearing_for_span(0.0, step * 0.5) == pytest.approx(10.0)
    assert link.bearing_for_span(step * 1.5, step * 2.5) == pytest.approx(190.0)
    # ...and the newest reading is a different answer entirely.
    assert link.direction_deg == pytest.approx(280.0)


def test_bearing_for_span_averages_circularly_across_north():
    """Bearings are angles: 359 and 1 average to 0, not 180. Straight ahead of
    the case is exactly where a naive mean is worst."""
    link = NodeLink(host="127.0.0.1", port=_free_port())
    link._doa_history.extend([(1.0, 359.0), (1.1, 1.0), (1.2, 359.5)])
    got = link.bearing_for_span(0.9, 1.3)
    assert got == pytest.approx(359.83, abs=0.2) or got == pytest.approx(0.0, abs=0.3)
    assert not 90.0 < got < 270.0      # a naive mean would land near 240


def test_bearing_for_span_is_absent_when_the_array_said_nothing():
    """A word spoken while the array reported nothing has no direction.
    Borrowing a neighbouring bearing is the fabrication `omit it` forbids."""
    link = NodeLink(host="127.0.0.1", port=_free_port())
    link._doa_history.extend([(1.0, 90.0), (5.0, 90.0)])
    assert link.bearing_for_span(2.0, 3.0) is None
    assert NodeLink(host="127.0.0.1", port=_free_port()
                    ).bearing_for_span(0.0, 9.0) is None


def test_opposed_bearings_are_undefined_rather_than_straight_ahead():
    """Two readings 180 apart cancel. Their mean is undefined, and 0 degrees
    would be a confident claim that the talker is directly in front."""
    link = NodeLink(host="127.0.0.1", port=_free_port())
    link._doa_history.extend([(1.0, 0.0), (1.1, 180.0)])
    assert link.bearing_for_span(0.5, 1.5) is None
