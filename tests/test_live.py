import copy
import json
import http.server
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from collections import deque

from autocwi.config import load_config
from autocwi.live import (
    AdaptiveSpeechGate,
    AudioChunk,
    Broadcaster,
    DualStreamingCaptioner,
    EndpointVerifier,
    HypothesisWord,
    StreamingCaptioner,
    coalesce_audio_chunks,
    InputGain,
    LiveLanguageSession,
    SR,
    _configure_live_language,
    _normalized_token,
    _realtime_voice_features,
    _rms_db,
    _studio_runtime_config,
    _word_delivery_features,
    common_prefix_len,
    conservative_verified_words,
    repair_verified_tail_timing,
    file_blocks,
    sample_clip_path,
    hypothesis_words,
    make_handler,
    mic_blocks,
)
from autocwi.livepage import render_live
from autocwi.onset import PhoneCandidate, PhonemeOnsetDetector


def result(tokens, timestamps, probs=None, text=""):
    return SimpleNamespace(
        tokens=tokens,
        timestamps=timestamps,
        ys_probs=probs or [-0.1] * len(tokens),
        text=text,
    )


def test_transducer_pieces_collapse_to_timestamped_words():
    words = hypothesis_words(
        result([" THE", " YE", "LL", "OW", " LIGHT"],
               [0.2, 0.5, 0.6, 0.7, 1.0]),
        audio_duration=1.4,
    )
    assert [w.text for w in words] == ["THE", "YELLOW", "LIGHT"]
    assert [round(w.start, 1) for w in words] == [0.2, 0.5, 1.0]
    assert words[0].end == 0.5
    assert words[-1].end == 1.4


def test_korean_transducer_pieces_preserve_eojeol_boundaries_and_syllables():
    words = hypothesis_words(
        result(
            [" 걔는", " 괜찮은", " 척", "하", "려", "구", " 애", " 쓰는"],
            [0.52, 0.96, 1.28, 1.44, 1.52, 1.84, 2.28, 2.48],
        ),
        audio_duration=3.0,
    )
    assert [word.text for word in words] == [
        "걔는", "괜찮은", "척하려구", "애", "쓰는",
    ]
    assert words[2].syllables() == [
        ("척", 1.28), ("하", 1.44), ("려", 1.52), ("구", 1.84),
    ]


def test_verifier_normalization_preserves_hangul_and_removes_punctuation():
    assert _normalized_token("괜찮은!") == "괜찮은"
    assert _normalized_token("보여 주시겠어요?") == "보여주시겠어요"
    assert _normalized_token("Hello, 2026.") == "hello2026"


def test_endpoint_verifier_restores_korean_spaces_from_piece_boundaries():
    result_value = SimpleNamespace(
        text="그는괜찮은척하려고애쓰는것같았다.",
        tokens=[
            " 그", "는", " 괜찮은", " 척", "하", "려고",
            " 애", "쓰", "는", " 것", " 같", "았", "다", ".",
        ],
    )

    class Stream:
        result = result_value

        def accept_waveform(self, sample_rate, audio):
            pass

    recognizer = SimpleNamespace(
        create_stream=Stream,
        decode_stream=lambda stream: None,
    )
    verifier = EndpointVerifier(recognizer)
    assert verifier.transcribe(np.zeros(160, dtype=np.float32)) == (
        "그는 괜찮은 척하려고 애쓰는 것 같았다."
    )


def test_korean_live_profile_uses_korean_models_only():
    cfg = _configure_live_language(load_config(), "ko")
    live = cfg["live"]
    assert live["lang"] == "ko"
    assert live["streaming_model_dir"].endswith("streaming-zipformer-ko-174m")
    assert live["streaming_files"]["encoder"].endswith(".int8.onnx")
    assert "chunk-16" in live["streaming_files"]["encoder"]
    assert live["draft_enabled"] is False
    assert live["verifier_enabled"] is False
    assert live["decoding_method"] == "greedy_search"
    assert live["streaming_max_active_paths"] == 8
    assert live["onset_prefix"]["enabled"] is False
    assert live["diarization"]["backend"] == "auto"
    assert live["diarization"]["model"].endswith(
        "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
    )
    assert live["diarization"]["segmentation_model"].endswith(
        "speaker-segmentation-en/model.int8.onnx"
    )
    assert live["speaker_attribution"]["assignment_threshold"] == 0.42
    assert live["speaker_attribution"]["min_enrollment_duration_s"] == 0.8


def test_missing_model_confidence_is_marked_unavailable():
    decoded = SimpleNamespace(
        tokens=[" A", " WORD"],
        timestamps=[0.1, 0.4],
        ys_probs=[],
        text="A WORD",
    )
    words = hypothesis_words(decoded, audio_duration=0.8)
    assert [word.conf for word in words] == [0.5, 0.5]
    assert all(not word.conf_available for word in words)


def test_standalone_space_starts_the_next_word():
    words = hypothesis_words(
        result([" S", "QUA", "LI", "D", " ", "QUA", "R", "TER"],
               [0.1, 0.2, 0.3, 0.4, 0.7, 0.72, 0.8, 0.9]),
        audio_duration=1.2,
    )
    assert [w.text for w in words] == ["SQUALID", "QUARTER"]
    assert words[1].start == 0.7


def _captioner():
    c = StreamingCaptioner.__new__(StreamingCaptioner)
    c.cfg = load_config()
    return c


def test_sub_word_pieces_are_retained_for_syllable_variation():
    words = hypothesis_words(
        result([" S", "QUA", "LI", "D"], [4.56, 4.56, 4.64, 4.72]),
        audio_duration=5.2,
    )
    assert [w.text for w in words] == ["SQUALID"]
    # Pieces sharing an encoder frame are one group: the transducer emitted
    # " S" and "QUA" on the same 80 ms frame, so they have no distinct onset.
    assert words[0].syllables() == [("SQUA", 4.56), ("LI", 4.64), ("D", 4.72)]


def test_syllable_stops_are_monotonic_and_start_at_word_onset():
    word = HypothesisWord("SQUALID", 4.56, 5.20, 0.9, True,
                          (("S", 4.56), ("QUA", 4.56), ("LI", 4.64), ("D", 4.72)))
    stops = _captioner()._syllable_stops(word)
    # 2.2.2 requires colour to start at the spoken onset, never later.
    assert stops[0] == {"t": 0.0, "c": 0.0}
    assert stops[-1] == {"t": 1.0, "c": 1.0}
    assert [s["t"] for s in stops] == sorted(s["t"] for s in stops)
    assert [s["c"] for s in stops] == sorted(s["c"] for s in stops)


def test_short_and_single_onset_words_get_no_syllable_fill():
    # Every piece on one encoder frame: no internal timing exists to animate.
    flat = HypothesisWord("YELLOW", 2.24, 2.80, 0.9, True,
                          (("YE", 2.24), ("LL", 2.24), ("OW", 2.24)))
    assert _captioner()._syllable_stops(flat) is None
    # Distinct onsets but too brief to count as drawn-out delivery.
    brief = HypothesisWord("OF", 5.12, 5.20, 0.9, True,
                           (("O", 5.12), ("F", 5.16)))
    assert _captioner()._syllable_stops(brief) is None


def test_syllable_fill_can_be_disabled_in_config():
    captioner = _captioner()
    captioner.cfg = {**captioner.cfg,
                     "motion": {**captioner.cfg["motion"],
                                "syllable_fill": {"enabled": False}}}
    word = HypothesisWord("SQUALID", 4.56, 5.20, 0.9, True,
                          (("SQUA", 4.56), ("LI", 4.64), ("D", 4.72)))
    assert captioner._syllable_stops(word) is None


def test_common_prefix_waits_through_a_word_revision():
    old = [HypothesisWord("THE", 0, 0.2, 1), HypothesisWord("YE", 0.2, 0.4, 0.6)]
    new = [HypothesisWord("THE", 0, 0.2, 1), HypothesisWord("YELLOW", 0.2, 0.7, 0.8)]
    assert common_prefix_len(old, new) == 1


def test_endpoint_verifier_completes_prefixes_but_preserves_dialect_spelling():
    streaming = [
        HypothesisWord("dishonoured", 0.0, 0.4, 0.9),
        HypothesisWord("des", 0.4, 0.7, 0.6),
        HypothesisWord("apprehens", 0.7, 1.1, 0.6),
    ]
    verified = conservative_verified_words(
        streaming, "dishonored descent apprehension"
    )
    assert [word.text for word in verified] == [
        "dishonoured", "descent", "apprehension",
    ]


def test_endpoint_verifier_retimes_insertions_and_deletes_extra_words():
    streaming = [
        HypothesisWord("we", 0.0, 0.3, 0.9),
        HypothesisWord("really", 0.3, 0.6, 0.7),
        HypothesisWord("talk", 0.6, 1.0, 0.9),
    ]
    verified = conservative_verified_words(streaming, "we need to talk")
    assert [word.text for word in verified] == ["we", "need", "to", "talk"]
    assert all(word.end > word.start for word in verified)
    assert all(left.start <= right.start for left, right in zip(verified, verified[1:]))

    deleted = conservative_verified_words(streaming, "we talk")
    assert [word.text for word in deleted] == ["we", "talk"]


def test_endpoint_verifier_anchors_trailing_insertions_to_active_audio():
    streaming = [HypothesisWord("okay?", 0.6, 1.0, 0.9)]
    audio = np.zeros(round(2.8 * SR), dtype=np.float32)
    audio[round(1.30 * SR):round(1.85 * SR)] = 0.08
    # A later non-speech event must not stretch the verified words.
    audio[round(2.40 * SR):round(2.62 * SR)] = 0.10

    verified = conservative_verified_words(
        streaming,
        "okay? something without sugar",
        audio=audio,
    )

    tail = verified[1:]
    assert [word.text for word in tail] == ["something", "without", "sugar"]
    assert 1.20 <= tail[0].start <= 1.35
    assert 1.80 <= tail[-1].end <= 1.95
    assert all(left.end <= right.start for left, right in zip(tail, tail[1:]))


def test_endpoint_verifier_repairs_equal_but_silence_aligned_tail():
    words = [
        HypothesisWord("okay?", 0.7, 1.0, 0.9),
        HypothesisWord("something", 1.0, 1.15, 0.8),
        HypothesisWord("without", 1.15, 1.30, 0.8),
        HypothesisWord("sugar.", 1.30, 1.45, 0.8),
    ]
    audio = np.zeros(round(2.8 * SR), dtype=np.float32)
    audio[round(1.75 * SR):round(2.55 * SR)] = 0.08

    repaired = repair_verified_tail_timing(words, audio)

    assert repaired[0] == words[0]
    assert repaired[1].start >= 1.65
    assert repaired[-1].end >= 2.50
    assert all(
        left.end <= right.start
        for left, right in zip(repaired[1:], repaired[2:])
    )


def test_adaptive_gate_counts_speech_but_not_quiet_blocks():
    cfg = load_config()["live"]
    gate = AdaptiveSpeechGate(cfg)
    gate.accept(np.zeros(1024, dtype=np.float32))
    assert gate.speech_s == 0
    gate.accept(np.full(1024, 0.1, dtype=np.float32))
    assert gate.speech_s > 0


def test_capture_blocks_batch_without_creating_a_gap():
    first = AudioChunk(np.zeros(1024, dtype=np.float32), 0.0)
    second = AudioChunk(np.zeros(1024, dtype=np.float32), 1024 / 16_000)
    batch = coalesce_audio_chunks([first, second], previous_end=0.0)
    assert len(batch.samples) == 2048
    assert batch.source_start == 0.0
    assert not batch.discontinuity


def test_capture_backlog_is_batched_without_losing_audio():
    half_second = np.zeros(8000, dtype=np.float32)
    chunks = [AudioChunk(half_second, start) for start in (0.0, 0.5, 1.0)]
    batch = coalesce_audio_chunks(chunks, previous_end=0.0)
    assert batch.source_start == 0
    assert round(len(batch.samples) / 16_000, 2) == 1.5
    assert not batch.discontinuity
    assert batch.dropped_s == 0


def test_microphone_callback_overload_batches_every_block(monkeypatch):
    class InputStream:
        def __init__(self, callback, **kwargs):
            self.callback = callback

        def __enter__(self):
            # PortAudio produces 768 ms before the decoder asks for its first
            # block. Every sample must survive the temporary backlog.
            for _ in range(12):
                self.callback(np.zeros((1024, 1), dtype=np.float32), 1024, None, None)
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setitem(sys.modules, "sounddevice",
                        SimpleNamespace(InputStream=InputStream))
    blocks = mic_blocks(threading.Event())
    caught_up = next(blocks)
    blocks.close()
    assert not caught_up.discontinuity
    assert caught_up.source_start == 0
    assert len(caught_up.samples) == 12 * 1024


def test_file_source_uses_wall_clock_and_losslessly_catches_up(tmp_path):
    import soundfile as sf

    wav = tmp_path / "one-second.wav"
    sf.write(wav, np.zeros(16_384, dtype=np.float32), 16_000)
    now = [100.0]

    def clock():
        return now[0]

    sleeps = []
    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    blocks = file_blocks(wav, realtime=True, _clock=clock, _sleep=sleep)
    first = next(blocks)
    now[0] += 0.5  # simulate a decoder that took 500 ms for one 64 ms block
    caught_up = next(blocks)
    assert first.source_start == 0
    assert caught_up.source_start == 1024 / 16_000
    assert not caught_up.discontinuity
    assert sleeps == []  # decoder runs flat-out until it reaches source time
    remaining = list(blocks)
    assert sum(len(chunk.samples) for chunk in [first, caught_up, *remaining]) == 16_384


def _speech_like(seconds, amplitude, seed=0):
    """Speech-shaped audio with real pauses, so the noise floor is trackable."""

    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * 16_000)) / 16_000
    tone = np.sin(2 * np.pi * 140 * t) + 0.4 * np.sin(2 * np.pi * 420 * t)
    # Gate to roughly 1.2 s of speech per 2 s, leaving quiet gaps between them.
    gate = (np.sin(2 * np.pi * 0.5 * t) > -0.3).astype(np.float64)
    signal = tone * gate + rng.normal(0, 2e-4, len(t))
    return (signal / np.max(np.abs(signal)) * amplitude).astype(np.float32)


def _feed(gain, signal, block=1024):
    out = None
    for i in range(0, len(signal) - block, block):
        out = gain.process(AudioChunk(signal[i:i + block], i / 16_000))
    return out


def _gain_config(**overrides):
    cfg = load_config()
    gain = {**cfg["live"]["input_gain"], **overrides}
    return {**cfg, "live": {**cfg["live"], "input_gain": gain}}


def test_quiet_input_is_amplified_for_the_recognizer_only():
    # The failure this guards: a quiet talker produced no captions at all,
    # because the transducer had too little signal to decode.
    gain = InputGain(_gain_config())
    quiet = _speech_like(10.0, 0.004)
    out = _feed(gain, quiet)
    assert gain.gain_db > 12.0
    # The recognizer copy is lifted...
    assert np.max(np.abs(out.recognizer_samples)) > np.max(np.abs(out.samples)) * 4
    # ...while the samples prosody measures keep the true captured level, so a
    # whisper still renders small.
    assert _rms_db(out.samples) < -40.0


def test_gain_is_held_through_silence_so_room_tone_is_not_amplified():
    gain = InputGain(_gain_config())
    silence = (np.random.default_rng(1).normal(0, 1e-4, 16_000 * 8)).astype(np.float32)
    _feed(gain, silence)
    assert gain.gain_db == 0.0
    assert gain.status() in {"no-signal", "idle"}


def test_pinned_gain_is_peak_limited_into_headroom():
    # `live --gain 30` on an already-healthy source must not clip the encoder.
    gain = InputGain(_gain_config(min_gain_db=30.0, max_gain_db=30.0,
                                  initial_gain_db=30.0))
    loud = _speech_like(4.0, 0.5, seed=2)
    out = _feed(gain, loud)
    ceiling = 10 ** (gain.headroom_dbfs / 20.0)
    assert np.max(np.abs(out.recognizer_samples)) <= ceiling + 1e-6


def test_level_event_survives_sse_serialization():
    # numpy scalars leaked into the payload and crashed the server on the first
    # published level event: np.bool_ is not JSON serializable.
    for enabled in (True, False):
        gain = InputGain(_gain_config(enabled=enabled))
        for signal in (_speech_like(3.0, 0.4, seed=5),
                       np.zeros(16_000, dtype=np.float32)):
            _feed(gain, signal)
            event = gain.level_event(1.0)
            json.dumps(event)
            assert isinstance(event["speech"], bool)
            assert isinstance(event["pitch_hz"], float)
            assert isinstance(event["pitch_confidence"], float)
            assert isinstance(event["spectral_centroid_hz"], float)
            assert isinstance(event["delivery_contour"], float)
            assert isinstance(event["delivery_profile"], str)
            assert event["status"] in {
                "no-signal", "idle", "good", "too-quiet", "clipping",
            }


def test_realtime_voice_features_track_frequency_without_a_model():
    t = np.arange(BLOCK := 1024) / SR
    signal = (0.35 * np.sin(2 * np.pi * 180.0 * t)).astype(np.float32)
    pitch, confidence, centroid = _realtime_voice_features(signal)
    assert abs(pitch - 180.0) < 4.0
    assert confidence > 0.8
    assert 100.0 < centroid < 300.0
    assert _realtime_voice_features(np.zeros(BLOCK, dtype=np.float32)) == (
        0.0, 0.0, 0.0
    )


def test_word_delivery_distinguishes_rising_and_falling_contours():
    cfg = load_config()
    duration = 0.6
    t = np.arange(int(SR * duration)) / SR

    def chirp(start_hz, end_hz):
        rate = (end_hz - start_hz) / duration
        phase = 2 * np.pi * (start_hz * t + 0.5 * rate * t**2)
        voiced = (0.20 * np.sin(phase)).astype(np.float32)
        return np.concatenate([
            np.zeros(int(0.1 * SR), dtype=np.float32),
            voiced,
            np.zeros(int(0.1 * SR), dtype=np.float32),
        ])

    word = HypothesisWord("voice", 0.1, 0.7, 0.9)
    rising = _word_delivery_features(word, chirp(120, 240), cfg)
    falling = _word_delivery_features(word, chirp(240, 120), cfg)
    assert rising["delivery_profile"] == "rising"
    assert rising["delivery_contour"] > 0.7
    assert falling["delivery_profile"] == "falling"
    assert falling["delivery_contour"] < -0.7


def test_word_delivery_deadband_rejects_shallow_or_under_evidenced_contour():
    cfg = load_config()

    def chirp(duration, start_hz, end_hz, amplitude=0.08):
        t = np.arange(int(SR * duration)) / SR
        rate = (end_hz - start_hz) / duration
        phase = 2 * np.pi * (start_hz * t + 0.5 * rate * t**2)
        return (amplitude * np.sin(phase)).astype(np.float32)

    shallow = chirp(0.4, 170, 185)
    shallow_result = _word_delivery_features(
        HypothesisWord("ordinary", 0.0, 0.4, 0.9),
        shallow,
        cfg,
    )
    assert abs(shallow_result["delivery_contour"]) < 0.45
    assert shallow_result["delivery_profile"] == "steady"

    short = chirp(0.06, 120, 240)
    short_result = _word_delivery_features(
        HypothesisWord("a", 0.0, 0.06, 0.9),
        short,
        cfg,
    )
    assert short_result["delivery_contour"] == 0
    assert short_result["delivery_contour_confidence"] == 0


def test_onset_prefix_advances_one_stable_phone_at_a_time():
    # Exercise the state machine without loading Torch/model weights. A decoder
    # already seeing /hh eh l/ must still paint H -> He -> Hel sequentially.
    detector = PhonemeOnsetDetector.__new__(PhonemeOnsetDetector)
    detector.hop_samples = 1024
    detector.min_audio_samples = 1024
    detector.right_context_samples = 0
    detector.max_audio_samples = SR * 3
    detector.activation_db = -60.0
    detector.silence_db = -70.0
    detector.reset_samples = SR
    detector.min_confidence = 0.6
    detector.max_prefix_chars = 8
    detector.prefix_stability_updates = 2
    detector.sustain_update_samples = 2048
    detector._decode_candidates = lambda _samples: [
        PhoneCandidate("hh", "H", 0.96),
        PhoneCandidate("eh", "E", 0.94),
        PhoneCandidate("l", "L", 0.92),
    ]
    detector.reset()
    block = np.full(1024, 0.1, dtype=np.float32)
    events = []
    for index in range(5):
        events.extend(detector.feed(block, index * 1024 / SR, 7))
    words = [message["words"][0] for message in events]
    assert [word["text"] for word in words] == ["H", "He", "Hel"]
    changed = []
    for word in words:
        if not changed or word["text"] != changed[-1]:
            changed.append(word["text"])
    assert changed == ["H", "He", "Hel"]
    assert {word["word_id"] for word in words} == {"u7:w0"}
    assert all(word["sustain_active"] for word in words)
    assert words[-1]["sustain_s"] > words[0]["sustain_s"]


def test_disabled_gain_passes_audio_through_untouched():
    gain = InputGain(_gain_config(enabled=False))
    quiet = _speech_like(2.0, 0.004, seed=3)
    out = _feed(gain, quiet)
    assert out.asr_samples is None
    assert np.array_equal(out.recognizer_samples, out.samples)


def test_loudness_channel_is_measured_before_gain():
    # A whisper and a shout must still differ in loudness_db even after the
    # gain has normalized both for the recognizer.
    measured = []
    for amplitude in (0.5, 0.01):
        gain = InputGain(_gain_config())
        captioner = StreamingCaptioner.__new__(StreamingCaptioner)
        captioner.cfg = load_config()
        captioner.db_history = deque(maxlen=120)
        captioner.prosody_cache = {}
        captioner.speaker = "S1"
        captioner.utterance = 0
        captioner.stream_base = 0.0
        captioner._last_final_speaker = None
        chunk = _feed(gain, _speech_like(6.0, amplitude, seed=4))
        assert gain.gain_db > 0 if amplitude == 0.01 else True
        word = HypothesisWord("A", 0.0, 0.06, 0.9)
        measured.append(
            captioner._word_event(word, chunk.samples, final=True)["loudness_db"]
        )
    assert measured[0] - measured[1] > 20.0


def test_quiet_recognized_phrase_is_committed_at_endpoint():
    decoded = result([" QUIET", " WORDS"], [0.1, 0.5])

    class Recognizer:
        def create_stream(self):
            return object()

        def get_result_all(self, stream):
            return decoded

    captioner = StreamingCaptioner(Recognizer(), load_config())
    captioner.audio_blocks = [np.zeros(16_000, dtype=np.float32)]
    captioner._word_event = lambda word, audio, final, speaker=None, word_id=None: {
        "type": "word", "text": word.text, "final": final,
        "start": word.start, "end": word.end,
    }
    events = list(captioner._process_result(endpoint=True))
    assert [event["text"] for event in events if event["type"] == "word"] == [
        "QUIET", "WORDS",
    ]

    draft = StreamingCaptioner(Recognizer(), load_config(), draft_only=True)
    draft.audio_blocks = [np.zeros(16_000, dtype=np.float32)]
    draft._word_event = captioner._word_event
    draft_events = list(draft._process_result(endpoint=True))
    assert not any(event["type"] == "word" for event in draft_events)
    assert [word["text"] for word in draft_events[-1]["words"]] == [
        "QUIET", "WORDS",
    ]


def test_no_text_verifier_still_finalizes_speakers_at_endpoint():
    decoded = result([" 안녕", " 하세요"], [0.1, 0.5])

    class Recognizer:
        def create_stream(self):
            return object()

        def get_result_all(self, stream):
            return decoded

    class Tracker:
        def __init__(self):
            self.label_calls = 0

        def label_words(self, audio, words, **kwargs):
            self.label_calls += 1
            return [
                SimpleNamespace(speaker_id="S1", status="stable")
                for _ in words
            ]

    tracker = Tracker()
    captioner = StreamingCaptioner(
        Recognizer(),
        load_config(),
        speaker_tracker=tracker,
    )
    captioner.audio_blocks = [np.zeros(16_000, dtype=np.float32)]
    captioner._word_event = (
        lambda word, audio, final, speaker=None, word_id=None: {
            "type": "word",
            "word_id": word_id,
            "text": word.text,
            "final": final,
            "speaker": speaker.speaker_id,
            "speaker_status": speaker.status,
        }
    )

    events = list(captioner._process_result(endpoint=True))

    assert tracker.label_calls == 1
    assert [
        (event["text"], event["speaker"], event["speaker_status"])
        for event in events
        if event["type"] == "word"
    ] == [
        ("안녕", "S1", "stable"),
        ("하세요", "S1", "stable"),
    ]


def test_endpoint_verifier_owns_durable_words():
    decoded = result([" APPREHENS"], [0.1])

    class Recognizer:
        def create_stream(self):
            return object()

        def get_result_all(self, stream):
            return decoded

    verifier = SimpleNamespace(transcribe=lambda audio: "apprehension")
    captioner = StreamingCaptioner(
        Recognizer(), load_config(), verifier=verifier
    )
    captioner.audio_blocks = [np.zeros(16_000, dtype=np.float32)]
    captioner._word_event = lambda word, audio, final, speaker=None, word_id=None: {
        "type": "word", "text": word.text, "final": final,
        "start": word.start, "end": word.end,
    }
    events = list(captioner._process_result(endpoint=True))
    assert events[0]["type"] == "verification"
    assert events[0]["words"][0]["text"] == "apprehension"
    assert [(event["text"], event["verified"])
            for event in events if event["type"] == "word"] == [
                ("apprehension", True),
            ]


def test_dual_merge_prefers_accurate_words_and_keeps_fast_tail():
    dual = DualStreamingCaptioner.__new__(DualStreamingCaptioner)
    dual.accurate = SimpleNamespace(
        stream_base=0.0,
        utterance=0,
        committed=[HypothesisWord("LOCKED", 0.0, 0.3, 1.0)],
    )
    dual.accurate_words = [{
        "text": "accurate", "t": 0.32, "start": 0.32, "end": 0.58,
    }]
    dual.draft_words = [
        {"text": "wrong", "t": 0.33, "start": 0.33, "end": 0.56},
        {"text": "accurate", "t": 1.10, "start": 1.10, "end": 1.28},
        {"text": "tail", "t": 0.65, "start": 0.65, "end": 0.85},
    ]
    dual.last_merged_key = ()
    merged = dual._merged_hypothesis()
    assert [word["text"] for word in merged["words"]] == ["accurate", "tail"]


def test_accurate_partial_cues_each_word_once_even_on_same_encoder_frame():
    dual = DualStreamingCaptioner.__new__(DualStreamingCaptioner)
    dual.cued_slots = set()
    words = [
        {
            "type": "word", "final": False, "text": "steady", "speaker": "S1",
            "word_id": "u0:w0", "t": 0.4, "start": 0.4, "end": 0.7,
        },
        {
            "type": "word", "final": False, "text": "tail", "speaker": "S1",
            "word_id": "u0:w1", "t": 0.4, "start": 0.4, "end": 1.0,
        },
    ]

    cues = dual._provisional_cues(words, utterance=0)
    assert [(cue["type"], cue["text"], cue["provisional"], cue["final"])
            for cue in cues] == [
                ("cue", "steady", True, False),
                ("cue", "tail", True, False),
            ]
    assert dual._provisional_cues(words, utterance=0) == []


def test_accurate_snapshot_and_cue_precede_its_durable_word():
    dual = DualStreamingCaptioner.__new__(DualStreamingCaptioner)
    dual.accurate = SimpleNamespace(stream_base=0.0, utterance=0, committed=[])
    dual.draft_words = []
    dual.accurate_words = []
    dual.cued_slots = set()
    dual.last_merged_key = ()
    partial = {
        "type": "word", "final": False, "text": "ready", "speaker": "S1",
        "t": 0.2, "start": 0.2, "end": 0.5,
    }
    durable = dict(partial, type="word", final=True)
    snapshot = {
        "type": "hypothesis", "utterance": 0, "endpoint": False,
        "words": [partial],
    }

    output = list(dual._handle_accurate_events([durable, snapshot]))
    assert [event["type"] for event in output] == ["hypothesis", "cue", "word"]
    assert output[0]["words"][0]["src"] == "accurate"
    assert output[1]["src"] == "accurate"
    assert output[2]["src"] == "accurate"


def test_streaming_captioner_resets_on_source_discontinuity():
    class Stream:
        def accept_waveform(self, sample_rate, samples):
            self.accepted = len(samples)

    class Recognizer:
        def __init__(self):
            self.streams = 0

        def create_stream(self):
            self.streams += 1
            return Stream()

        def is_ready(self, stream):
            return False

        def is_endpoint(self, stream):
            return False

    recognizer = Recognizer()
    captioner = StreamingCaptioner(recognizer, load_config())
    events = list(captioner.accept(
        AudioChunk(np.zeros(1024, dtype=np.float32), 3.0, True, 2.5)
    ))
    assert recognizer.streams == 2
    assert captioner.stream_base == 3.0
    assert events == [{
        "type": "hypothesis", "utterance": 1, "endpoint": True,
        "resync": True, "dropped_s": 2.5, "words": [],
    }]


def test_browser_queue_retains_every_final_event():
    broadcaster = Broadcaster()
    client = broadcaster.register()
    for i in range(50):
        broadcaster.publish({"type": "word", "final": True, "n": i})
    assert client.qsize() == 50
    assert b'"n": 0' in client.get_nowait()
    for _ in range(48):
        client.get_nowait()
    assert b'"n": 49' in client.get_nowait()


def test_browser_queue_replays_durable_events_after_last_event_id():
    broadcaster = Broadcaster()
    first = broadcaster.register()
    broadcaster.publish({"type": "hypothesis", "words": []})  # id 1
    broadcaster.publish({"type": "commit", "text": "one"})   # id 2
    broadcaster.publish({"type": "word", "final": True, "text": "one"})  # id 3
    broadcaster.unregister(first)
    broadcaster.publish({"type": "word", "final": True, "text": "two"})  # id 4

    replay = broadcaster.register(last_event_id=2)
    chunks = [replay.get_nowait(), replay.get_nowait()]
    assert chunks[0].startswith(b"id: 3\n")
    assert chunks[1].startswith(b"id: 4\n")
    assert all(b'"_replay": true' in chunk for chunk in chunks)
    assert all(b'"_first_presentation": false' in chunk for chunk in chunks)
    assert replay.empty()


def test_first_browser_presents_startup_backlog_once():
    broadcaster = Broadcaster()
    broadcaster.publish({
        "type": "commit",
        "word_id": "u0:w0",
        "text": "hello",
    })

    opening = broadcaster.register(last_event_id=0)
    opening_chunk = opening.get_nowait()
    assert b'"_replay": true' in opening_chunk
    assert b'"_first_presentation": true' in opening_chunk
    broadcaster.unregister(opening)

    reconnect = broadcaster.register(last_event_id=0)
    reconnect_chunk = reconnect.get_nowait()
    assert b'"_replay": true' in reconnect_chunk
    assert b'"_first_presentation": false' in reconnect_chunk


def test_live_page_accepts_local_diagnostics_query(tmp_path):
    page = tmp_path / "live.html"
    page.write_text("<title>live diagnostics</title>", encoding="utf-8")
    handler = make_handler(page, Broadcaster())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/?renderdiag=1", timeout=2
        ) as response:
            assert response.status == 200
            assert b"live diagnostics" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_live_handler_serves_next_export_runtime_and_legacy(tmp_path):
    static_root = tmp_path / "studio"
    asset = static_root / "_next" / "static" / "app.js"
    asset.parent.mkdir(parents=True)
    page = static_root / "index.html"
    page.write_text("<title>Next studio</title>", encoding="utf-8")
    asset.write_text("window.STUDIO=true", encoding="utf-8")
    legacy = tmp_path / "legacy.html"
    legacy.write_text("<title>Legacy</title>", encoding="utf-8")
    font = tmp_path / "RobotoFlex.ttf"
    font.write_bytes(b"font")
    korean_font = tmp_path / "NotoSansKR.ttf"
    korean_font.write_bytes(b"korean-font")
    runtime = {"displayMode": "fast", "maxWords": 8}
    handler = make_handler(
        page,
        Broadcaster(),
        static_root=static_root,
        legacy_page_path=legacy,
        font_path=font,
        korean_font_path=korean_font,
        runtime_config=runtime,
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = f"http://127.0.0.1:{server.server_address[1]}"
        assert b"Next studio" in urllib.request.urlopen(root + "/", timeout=2).read()
        assert b"Legacy" in urllib.request.urlopen(root + "/legacy", timeout=2).read()
        assert json.loads(
            urllib.request.urlopen(root + "/runtime-config.json", timeout=2).read()
        ) == runtime
        with urllib.request.urlopen(root + "/_next/static/app.js", timeout=2) as response:
            assert response.headers["Cache-Control"].endswith("immutable")
            assert b"STUDIO" in response.read()
        assert urllib.request.urlopen(root + "/RobotoFlex.ttf", timeout=2).read() == b"font"
        assert (
            urllib.request.urlopen(root + "/NotoSansKR.ttf", timeout=2).read()
            == b"korean-font"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_live_handler_accepts_one_language_choice_before_capture(tmp_path):
    page = tmp_path / "live.html"
    page.write_text("<title>language picker</title>", encoding="utf-8")
    languages = [
        {"id": "en", "label": "English", "nativeLabel": "English"},
        {"id": "ko", "label": "Korean", "nativeLabel": "한국어"},
    ]
    session = LiveLanguageSession(languages)
    handler = make_handler(page, Broadcaster(), language_session=session)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = f"http://127.0.0.1:{server.server_address[1]}"
        before = json.loads(
            urllib.request.urlopen(root + "/session", timeout=2).read()
        )
        assert before["state"] == "selecting"
        assert before["language"] is None

        preflight = urllib.request.Request(
            root + "/session/language",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
            method="OPTIONS",
        )
        with urllib.request.urlopen(preflight, timeout=2) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Methods"] == "POST, OPTIONS"

        request = urllib.request.Request(
            root + "/session/language",
            data=json.dumps({"language": "ko"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            selected = json.loads(response.read())
            assert response.status == 202
        assert selected["state"] == "loading"
        assert session.wait_for_language() == "ko"

        conflict = urllib.request.Request(
            root + "/session/language",
            data=json.dumps({"language": "en"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(conflict, timeout=2)
            assert False, "changing a live session language must be rejected"
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_next_runtime_config_reuses_caption_scheduler_values():
    cfg = load_config()
    runtime = _studio_runtime_config(cfg)
    # The light stage recolors the same speakers; a missing entry would silently
    # fall back to the CI color, which measures 1.19:1 on a light surface.
    assert len(runtime["paletteLight"]) == len(runtime["palette"])
    assert runtime["displayMode"] == cfg["display"]["mode"]
    assert runtime["maxWords"] == cfg["display"]["max_words"]
    assert runtime["paragraphWordLimit"] == 0
    assert runtime["stageParagraphHistory"] == 6
    assert runtime["stageWordsPerBlock"] == 8
    # CWI 2.2.1. The playhead trails the acoustic clock by this much, which is
    # what leaves recognized-but-uncoloured text on screen to read ahead into.
    # It has to exceed the recognizer's own latency (~1.1 s for the 1120 ms
    # accurate stream) or it buys no read-ahead at all.
    assert runtime["readAheadDelayMs"] == 1200
    # It must still clear the median time for a word's TEXT to arrive (~0.62 s
    # measured), or words land past their own onset and never animate.
    assert runtime["readAheadDelayMs"] > 620
    # 2.2.1 again: "full white at 90% opacity".
    assert runtime["readAheadColor"] == "#FFFFFF"
    assert runtime["readAheadOpacity"] == 0.9
    # 2.2.2's turn eases with the lift; it is never a hard cut.
    assert runtime["colorTurnMs"] > 0
    # THESE ARE THE TWO ENDS OF A RAMP, NOT A CLOCK. Size and duration are ONE
    # channel: peak size vs motion FWHM measures r = +0.69 over the 48
    # reference words with baked curves, the strongest relationship in that
    # data. Its own FWHM by crest band is 0.160s / 0.240s / 1.560s, against a
    # FLAT 0.69-1.02s measured on ours at every crest. The PDF settles nothing
    # here -- it specifies no timing at all.
    assert runtime["wordMotionMinMs"] < runtime["wordMotionMaxMs"]
    assert runtime["wordMotionBaseMs"] == 420
    assert runtime["wordMotionMaxMs"] == 1050
    assert runtime["wordMotionMinMs"] == 320
    # The reveal queue and its concurrency slots, catch-up gap, backlog target,
    # rate headroom and staleness ceiling are gone: the playhead schedules every
    # word from its own recorded onset, so none of them has anything to decide.
    for retired in (
        "revealGapMs",
        "maxActiveMotions",
        "wordMotionBacklogTargetMs",
        "wordMotionRateHeadroom",
        "wordMotionCatchupScale",
        "motionBacklogCeilingMs",
    ):
        assert retired not in runtime
    assert runtime["syncPop"] == 0.15
    # CWI 2.2.3 verbatim -- a 15% type-size increase. ONE transient, per word,
    # and nothing else moves. There is deliberately no elevation term: the word
    # grows from its baseline rather than translating upward, which is what the
    # reference recording shows and what the diagram's "25% elevation" label
    # describes as a consequence.
    assert "syncElevationEm" not in runtime
    # CWI 2.3 shapes the transient crest from absolute anchors; the client never
    # re-centres these on a speaker's own median.
    # 2.3.6 specifies 0.6x..2.4x around the 5% baseline. Live cannot use all of
    # it while rows reserve each word's crest footprint, but the band must stay
    # wide enough that a shout and a whisper are plainly different sizes -- at
    # [0.90, 1.20] they were within a third of each other and the channel read
    # as absent. Assert the SPAN, not the exact numbers, so tuning stays free.
    low, high = runtime["voiceScaleRange"]
    assert low < 1 < high, "2.3.5's baseline must sit strictly inside the band"
    assert high / low >= 2.0, "whisper and shout must be visibly different"
    assert 0 < runtime["voiceScaleResponse"] <= 1
    # 2.3.8's Regular 400 and 2.3.10's 100% must sit strictly inside both bands,
    # or the neutral band cannot be expressed at all.
    # The floor is set from the reference's own worst lightening (-53 from
    # Regular), not from the type's available axis: the motion may lighten a
    # word, but only about as far as the design system's renderer does.
    assert 320 <= runtime["weightRange"][0] < 400 < runtime["weightRange"][1]
    assert runtime["widthRange"][0] < 100 < runtime["widthRange"][1]
    assert runtime["deliveryMotionEnabled"] is True
    assert runtime["deliveryMinConfidence"] == 0.38
    assert [item["id"] for item in runtime["languages"]] == ["en", "ko"]


def test_stalled_browser_is_disconnected_for_lossless_replay():
    broadcaster = Broadcaster(max_queue=2)
    stalled = broadcaster.register()
    broadcaster.publish({"type": "word", "final": True, "n": 1})
    broadcaster.publish({"type": "word", "final": True, "n": 2})
    broadcaster.publish({"type": "word", "final": True, "n": 3})
    assert stalled.get_nowait() is None
    replay = broadcaster.register(last_event_id=0)
    assert replay.qsize() == 2
    assert b'"n": 2' in replay.get_nowait()
    assert b'"n": 3' in replay.get_nowait()

def test_display_mode_config_values_are_valid():
    # Display mode and its layout constants live in config (they were once
    # hardcoded in livepage.py). The rendered wiring for each mode is exercised
    # behaviourally by scripts/live_render_probe.py and the render-core suite.
    cfg = load_config()
    # Fast is the public default: accurate read-ahead stays close to speech.
    # The 160 ms draft is reserved for explicit readahead mode.
    assert cfg["display"]["mode"] == "fast"
    assert cfg["display"]["mode"] in {"stable", "fast", "sentence", "readahead"}
    # These were hardcoded in livepage.py; mapping values belong in config.
    assert cfg["display"]["line_linger_s"] == 9.0
    assert cfg["display"]["max_words"] == 8


def test_median_pivots_to_cwi_baseline_size():
    # CWI 2.3.5: normal speaking volume = 5% of frame height. A plain lo..hi
    # normalization put the MEDIAN word at mid-scale (renders 6.5%), so every
    # ordinary word read as slightly shouted and the on-screen size ratio blew
    # out to 3x. The scale is pivoted on the median instead.
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    # A speaker whose words spread widely below the median, as real speech does.
    captioner.db_history = deque([-60, -52, -46, -40, -37, -36, -34, -32, -30],
                                 maxlen=120)
    mapping = captioner.cfg["mapping"]["loudness_to"]
    pivot = (mapping["baseline"] - mapping["min"]) / (mapping["max"] - mapping["min"])

    def loudness_at(db):
        audio = np.full(16_000, 10 ** (db / 20), dtype=np.float32)
        captioner.prosody_cache = {}
        return captioner._word_event(
            HypothesisWord("w", 0.0, 0.5, 0.9), audio, final=False)["loudness"]

    # The median-loudness word lands on the CWI baseline, not mid-scale.
    assert abs(loudness_at(-37) - pivot) < 0.12
    # Quiet words stay below it, loud words above — expression is preserved.
    assert loudness_at(-55) < pivot < loudness_at(-31)


def test_a_slot_reports_identical_styling_on_every_re_emission():
    """THE INVARIANT: a word that has been shown must stop changing.

    Before this, 42/59 slots reported a different `loudness` at verification
    than at commit (and 13/59 a different `pitch_hz`), because `_word_event`
    re-normalized against a db_history that had grown in between. The renderer
    faithfully turned that into text resizing itself a second after appearing.
    """
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    # A calibrated scale (>= 6 words) is the regime where freezing applies.
    captioner.db_history = deque([-46, -40, -37, -36, -34, -32, -30], maxlen=120)
    word = HypothesisWord("hello", 0.40, 0.90, 0.9)
    audio = np.full(16_000, 0.02, dtype=np.float32)

    first = captioner._word_event(word, audio, final=False)
    # Simulate the utterance continuing: db_history grows, so an unfrozen
    # scale would normalize this same word differently.
    for db in (-60, -58, -25, -24):
        captioner.db_history.append(db)
    # The verifier also respells words, which used to miss a text-keyed cache.
    respelled = HypothesisWord("Hello,", 0.40, 0.90, 0.9)
    second = captioner._word_event(respelled, audio, final=True)

    assert second["loudness"] == first["loudness"]
    assert second["pitch_hz"] == first["pitch_hz"]
    assert second["loudness_db"] == first["loudness_db"]
    for field in (
        "delivery_force",
        "delivery_attack",
        "delivery_contour",
        "delivery_contour_confidence",
        "delivery_flow",
        "delivery_texture",
        "delivery_profile",
    ):
        assert second[field] == first[field]


def test_word_text_and_timing_revisions_are_monotonic():
    """One stable word id has independent comparable revision channels."""

    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    captioner.db_history = deque([-40.0] * 8, maxlen=120)
    captioner._word_slots = []
    captioner._word_revisions = {}
    captioner._final_word_events = {}
    captioner._prosody = lambda *_args: (-40.0, 180.0, 0.9)

    original = captioner._word_event(
        HypothesisWord("helo", 0.5, 0.9, 0.8),
        np.zeros(16_000, dtype=np.float32),
        final=False,
        word_id="u0:w0",
    )
    unchanged = captioner._word_event(
        HypothesisWord("helo", 0.5, 0.9, 0.8),
        np.zeros(16_000, dtype=np.float32),
        final=False,
        word_id="u0:w0",
    )
    respelled = captioner._word_event(
        HypothesisWord("hello", 0.5, 0.9, 0.8),
        np.zeros(16_000, dtype=np.float32),
        final=True,
        word_id="u0:w0",
    )
    retimed = captioner._word_event(
        HypothesisWord("hello", 0.54, 0.94, 0.8),
        np.zeros(16_000, dtype=np.float32),
        final=True,
        word_id="u0:w0",
    )

    assert unchanged["text_revision_id"] == original["text_revision_id"] == 1
    assert unchanged["timing_revision_id"] == original["timing_revision_id"] == 1
    assert respelled["text_revision_id"] == 2
    assert respelled["timing_revision_id"] == 1
    assert retimed["text_revision_id"] == 2
    assert retimed["timing_revision_id"] == 2

def test_closed_caption_renderer_implements_full_cwi_motion():
    """The CC renderer is the reference: text is known in advance, so every
    behaviour live mode can only approximate becomes exact."""
    from autocwi.ccpage import render_cc, _lines

    cfg = load_config()
    spec = {
        "version": "1.0",
        "media": {"path": "x.mp4", "duration": 6.0, "fps": 30.0},
        "speakers": {"S1": {"color": "#E5E517"}, "S2": {"color": "#17E517"}},
        "words": [
            {"text": "hello", "start": 0.5, "end": 1.0, "speaker": "S1",
             "loudness": 0.3, "pitch": 0.5, "loudness_db": -30.0,
             "pitch_hz": 180.0, "voiced_frac": 0.8, "conf": 0.9},
            {"text": "there", "start": 1.1, "end": 1.6, "speaker": "S1",
             "loudness": 0.4, "pitch": 0.5, "loudness_db": -28.0,
             "pitch_hz": 175.0, "voiced_frac": 0.8, "conf": 0.9},
            # A speaker change must break the line (CWI 2.1 attribution).
            {"text": "hi", "start": 3.0, "end": 3.4, "speaker": "S2",
             "loudness": 0.5, "pitch": 0.5, "loudness_db": -26.0,
             "pitch_hz": 210.0, "voiced_frac": 0.9, "conf": 0.9},
        ],
        "mapping": cfg["mapping"],
    }
    # A speaker change breaks the line (CWI 2.1 attribution).
    assert len(_lines(spec["words"], 8, 2.0)) == 2

    # Smoke: the renderer produces one self-contained document with the spec
    # embedded. The MOTION itself is behaviour, not a source string -- it is
    # covered by tests/cwi_motion_core.test.js and, at the DOM level, by
    # scripts/live_render_probe.py.
    page = open(render_cc(cfg, spec, tempfile.mkdtemp()), encoding="utf-8").read()
    assert page.lstrip().startswith("<!DOCTYPE html>")
    assert "hello" in page and "there" in page and "hi" in page

    # The values below are what the DESIGN SYSTEM states outright, asserted
    # against its section numbers. These are the numbers a refactor must not
    # quietly change; the PDF wins over the AE template wherever they disagree.
    cc = cfg["closed_caption"]
    assert cc["sync_pop"] == 0.15                       # 2.2.3, exactly
    assert cc["sync_elevation_em"] == 0.25              # 2.2.3, exactly
    assert cc["sync_granularity"] == "character"
    assert cc["max_lines"] == 1
    # The measured per-word curves stay available for checking the derivation
    # against the recordings, but the design system is what ships.
    assert cc["motion_source"] == "spec"
    # 2.3.5 baseline 5% of screen height; 2.3.6 range 3%..12%, so the reachable
    # intonation envelope is exactly 0.6x .. 2.4x the resting size.
    assert cc["size_pct"] == 5.0
    assert cfg["mapping"]["loudness_to"]["baseline"] == 5
    assert cfg["mapping"]["loudness_to"]["min"] == 3
    assert cfg["mapping"]["loudness_to"]["max"] == 12
    # 2.3.8: a 160-200 Hz voice is Roboto Regular 400. 2.3.9 runs the whole
    # weight axis over the vocal range (80 Hz -> 1000, 250 Hz -> 100).
    lo, hi = cc["anchor_wght"]
    assert lo <= 400 <= hi
    assert cc["wght_range"] == [100, 1000]
    # The colour turn is a crossfade, never a per-frame flip.
    assert cfg["motion"]["color_turn_ms"] > 0
    for k in ("sync_rise_s", "sync_peak_s", "sync_fall_s",
              "weight_deadband", "weight_full_dev",
              "emphasis_lead_s", "emphasis_hold_s", "emphasis_tail_s",
              "emphasis_deadband"):
        assert cc[k] > 0, k
    assert 0.12 <= cc["emphasis_lead_s"] <= 0.22
    assert 0.20 <= cc["emphasis_tail_s"] <= 0.40


def test_live_stage_defaults_to_stacked_captioning():
    cfg = load_config()
    assert cfg["display"]["align"] == "left"
    assert cfg["display"]["retention"] == "overflow"
    assert cfg["display"]["intent_circle"] is True
    # Renders without raising; its behaviour is covered by the render-core Node
    # suite and scripts/live_render_probe.py.
    assert Path(render_live(cfg, tempfile.mkdtemp())).stat().st_size > 0


def test_sentence_split_breaks_on_terminal_punctuation():
    # The verifier supplies punctuation the streaming words lack; sentence mode
    # splits a finalized utterance into turns on it. This mirrors the page's
    # splitSentences so the behaviour is pinned without a browser.
    import re

    terminal = re.compile(r"[.?!][\"')\]]?$")

    def split(words, max_words=8):
        out, cur = [], []
        for w in words:
            cur.append(w)
            if terminal.search(w) or len(cur) >= max_words:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    words = "Uh yeah. Give me a tab tab? I can't.".split()
    assert [" ".join(s) for s in split(words)] == [
        "Uh yeah.", "Give me a tab tab?", "I can't.",
    ]
    # A run with no punctuation is still capped at one caption box.
    assert all(len(s) <= 8 for s in split(["w"] * 20))


def test_file_loop_restarts_with_monotonic_clock_and_reset(tmp_path):
    import soundfile as sf

    wav = tmp_path / "half-second.wav"
    sf.write(wav, np.zeros(8000, dtype=np.float32), 16_000)
    boundaries = []
    last = -1.0
    seen = 0
    for chunk in file_blocks(wav, realtime=False, loop=True):
        assert chunk.source_start >= last  # clock never rewinds across a loop
        last = chunk.source_start
        if chunk.discontinuity:
            seen += 1
            boundaries.append(round(chunk.source_start, 2))
        if seen >= 2:
            break
    # Each new pass starts a source-clock multiple of the 0.5 s clip and is
    # flagged as a discontinuity so the captioner resets.
    assert boundaries == [0.5, 1.0]


def _fake_embed(samples):
    # Deterministic stand-in for the ONNX extractor: the DC offset of the span
    # picks the "voice", so tests stay fully offline.
    if len(samples) < 100:
        return None
    v = (np.array([1.0, 0.0], dtype=np.float32) if float(np.mean(samples)) >= 0
         else np.array([0.0, 1.0], dtype=np.float32))
    return v


def _tracker(**kw):
    from autocwi.live import SpeakerTracker

    defaults = dict(similarity=0.35, max_speakers=6, window_s=1.0,
                    hop_s=0.5, min_span_s=0.3, change_below=0.3, merge_at=0.5)
    defaults.update(kw)
    return SpeakerTracker(_fake_embed, **defaults)


def test_speaker_tracker_discovers_and_reuses_speakers():
    tracker = _tracker()
    voice_a = np.full(16_000, 0.1, dtype=np.float32)
    voice_b = np.full(16_000, -0.1, dtype=np.float32)
    words_a = [HypothesisWord("hi", 0.0, 1.0, 0.9)]
    words_b = [HypothesisWord("yo", 0.0, 1.0, 0.9)]
    first_a = tracker.label_words(voice_a, words_a)
    first_b = tracker.label_words(voice_b, words_b)
    assert [(r.speaker_id, r.status) for r in first_a] == [("S1", "provisional")]
    assert [(r.speaker_id, r.status) for r in first_b] == [("S2", "provisional")]
    # The same voices keep their labels on later utterances.
    assert [r.speaker_id for r in tracker.label_words(voice_a, words_a)] == ["S1"]
    assert [r.speaker_id for r in tracker.label_words(voice_b, words_b)] == ["S2"]


def test_speaker_tracker_votes_per_word_across_a_turn_change():
    tracker = _tracker()
    # 0..2s voice A, 2..4s voice B in one utterance.
    audio = np.concatenate([np.full(32_000, 0.1, dtype=np.float32),
                            np.full(32_000, -0.1, dtype=np.float32)])
    words = [HypothesisWord("aa", 0.2, 1.0, 0.9),
             HypothesisWord("ab", 1.1, 1.9, 0.9),
             HypothesisWord("ba", 2.1, 2.9, 0.9),
             HypothesisWord("bb", 3.0, 3.8, 0.9)]
    results = tracker.label_words(audio, words)
    assert [result.speaker_id for result in results] == ["S1", "S1", "S2", "S2"]
    assert all(result.status in {"stable", "corrected"} for result in results)


def test_speaker_tracker_classify_never_invents_a_speaker():
    tracker = _tracker()
    voice = np.full(32_000, 0.1, dtype=np.float32)
    # Before any endpoint has established centroids, commits stay unlabeled
    # (captioner falls back to its default speaker).
    assert tracker.classify_span(voice, 0.5, 1.5).status == "unknown"
    tracker.label_words(voice, [HypothesisWord("hi", 0.0, 2.0, 0.9)])
    classified = tracker.classify_span(voice, 0.5, 1.5)
    assert (classified.speaker_id, classified.status) == ("S1", "provisional")
    # A known voice classifies; classify never updates the centroids.
    counts = list(tracker.counts)
    tracker.classify_span(voice, 0.5, 1.5)
    assert tracker.counts == counts


def test_speaker_tracker_caps_at_max_speakers():
    from autocwi.live import SpeakerTracker

    vectors = iter([np.array([1.0, 0, 0], dtype=np.float32),
                    np.array([0, 1.0, 0], dtype=np.float32),
                    np.array([0, 0, 1.0], dtype=np.float32)])
    tracker = SpeakerTracker(lambda s: next(vectors), similarity=0.35,
                             max_speakers=2, window_s=10.0, hop_s=10.0,
                             min_span_s=0.1)
    word = [HypothesisWord("w", 0.0, 1.0, 0.9)]
    audio = np.zeros(16_000, dtype=np.float32)
    assert tracker.label_words(audio, word)[0].speaker_id == "S1"
    assert tracker.label_words(audio, word)[0].speaker_id == "S2"
    # At the cap, a low-confidence third voice stays unknown rather than being
    # forced onto an unrelated existing profile.
    third = tracker.label_words(audio, word)[0]
    assert (third.speaker_id, third.status) == (None, "unknown")


def test_durable_words_carry_haptic_salience_flags():
    # Haptics research (Haptic-Captioning CHI'23, Tactile Emotions CHI'25):
    # actuate selectively — speaker changes and strong emphasis only.
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.db_history = deque([-30.0] * 8, maxlen=120)
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    loud = np.concatenate([
        np.full(8000, 0.02, dtype=np.float32),   # ~-34 dB: ordinary
        np.full(8000, 0.30, dtype=np.float32),   # ~-10 dB: emphatic
    ])
    first = captioner._word_event(
        HypothesisWord("calm", 0.0, 0.5, 0.9), loud, final=True, speaker="S1")
    assert "speaker_change" not in first and "emphasis" not in first
    second = captioner._word_event(
        HypothesisWord("LOUD", 0.5, 1.0, 0.9), loud, final=True, speaker="S2")
    assert second["speaker_change"] is True
    assert second["emphasis"] is True
    # Provisional (non-final) words never carry salience.
    third = captioner._word_event(
        HypothesisWord("hm", 0.5, 1.0, 0.9), loud, final=False, speaker="S1")
    assert "speaker_change" not in third and "emphasis" not in third


def test_classify_span_skips_embedding_before_first_endpoint():
    calls = []

    def counting_embed(samples):
        calls.append(len(samples))
        return np.array([1.0, 0.0], dtype=np.float32)

    from autocwi.live import SpeakerTracker

    tracker = SpeakerTracker(counting_embed, similarity=0.35, max_speakers=6,
                             window_s=1.0, hop_s=0.5, min_span_s=0.3,
                             change_below=0.3, merge_at=0.5)
    audio = np.zeros(32_000, dtype=np.float32)
    assert tracker.classify_span(audio, 0.5, 1.5).status == "unknown"
    assert calls == []   # no centroids yet -> the embedding is never computed


def test_bundled_sample_clip_resolves_and_loads():
    import librosa

    path = sample_clip_path()
    assert Path(path).exists()
    audio, sr = librosa.load(path, sr=16_000, mono=True)
    assert sr == 16_000 and len(audio) > 16_000  # more than a second of audio


def test_bundled_korean_sample_is_language_specific():
    import librosa

    path = Path(sample_clip_path("ko"))
    assert path.name == "sample-ko.wav"
    audio, sr = librosa.load(path, sr=16_000, mono=True)
    assert sr == 16_000 and len(audio) > 16_000


def test_neighbour_motion_is_off_by_default():
    # Live captions accumulate and stay on screen, unlike the AE template's
    # played-through line, so a settled word must not be displaced.
    assert load_config()["motion"]["neighbor_bleed"] == 0.0


def test_accuracy_first_streaming_profile_is_configured():
    assert load_config()["live"]["streaming_model_dir"].endswith("1120ms")
    assert load_config()["live"]["verifier_model_dir"].endswith("offline")
    assert load_config()["live"]["verifier_decoding_method"] == "modified_beam_search"


def test_motion_tuner_is_opt_in_and_drives_the_real_constants():
    """`--tune` adds a live control panel; the shipped page never carries it."""
    from autocwi.ccpage import render_cc
    from autocwi.cli import tuner_spec

    cfg = load_config()
    spec = tuner_spec(cfg)
    # The built-in line must exercise every knob at once, or the tuner cannot
    # show what a change does: a long word for the character sweep, two-letter
    # words to check the ripple's rate against, one clearly loud and one quiet
    # word to bracket the intonation envelope, and a second speaker.
    texts = [w["text"] for w in spec["words"]]
    assert max(len(t) for t in texts) >= 8
    assert any(len(t) == 2 for t in texts)
    loud = max(spec["words"], key=lambda w: w["loudness"])
    quiet = min(spec["words"], key=lambda w: w["loudness"])
    assert loud["loudness"] - quiet["loudness"] > 0.5
    assert len({w["speaker"] for w in spec["words"]}) == 2

    plain = Path(render_cc(cfg, spec, tempfile.mkdtemp()))
    assert plain.name == "captions.html"
    assert "id=\"tuner\"" not in plain.read_text(encoding="utf-8")

    tuned = Path(render_cc(cfg, spec, tempfile.mkdtemp(), tune=True))
    assert tuned.name == "tuner.html"          # never overwrites the real page
    page = tuned.read_text(encoding="utf-8")
    assert 'id="tuner"' in page
    # The tuner is a string.Template-free append, so a stray "$" in it would
    # have been eaten by safe_substitute at render time.
    assert "$" not in page.split('id="tuner"')[1]


def test_derived_reference_specs_replay_the_recordings():
    """The three specs in assets/reference_specs/ are derived from docs/*.mov.

    Offline: they are checked-in JSON, so this never decodes a video.
    """
    from autocwi.schema import CaptionSpec, load_model

    root = Path(__file__).resolve().parent.parent
    expected = {
        "synchronization": (["S1"], "Synchronization"),
        "intonation": (["S1"], "Intonation"),
        "character_identification": (["S1", "S2"], "Character Identification"),
    }
    # ...and one united demo concatenating all three, in the site's order.
    demo = load_model(CaptionSpec, root / "assets" / "reference_specs" / "demo.json")
    lines, cur = [], []
    for w in demo.words:
        if w.line_break and cur:
            lines.append(" ".join(cur)); cur = []
        cur.append(w.text)
    lines.append(" ".join(cur))
    # The trimmed recordings capture all three section titles, and each section
    # opens on its own -- exactly the order the site presents them in.
    assert lines == [
        "Character Identification",
        "Now, colors will distinguish characters,",
        "so Deaf people instantly know who's speaking.",
        "Synchronization",
        "Caption with Intention uses",
        "dynamic text animation",
        "so captions are synchronized",
        "precisely as each word is spoken.",
        "Intonation",
        "This system brings in varying",
        "types sizes, weights and animation,",
        "so you can feel when my voice gets louder or softer.",
    ]
    # every section keeps its own speakers, so two sections cannot collide
    assert len({w.speaker for w in demo.words}) == 4

    for name, (speakers, opening) in expected.items():
        spec = load_model(CaptionSpec, root / "assets" / "reference_specs" / f"{name}.json")
        assert sorted({w.speaker for w in spec.words}) == speakers, name
        # first caption line, reconstructed
        first = []
        for w in spec.words:
            if w.line_break and first:
                break
            first.append(w.text)
        assert " ".join(first) == opening, name
        # timings must be monotone and non-degenerate
        for a, b in zip(spec.words, spec.words[1:]):
            assert a.end > a.start and b.start >= a.start
            assert a.end - a.start >= 0.02
        # PROSODY MUST VARY. Both channels were silently constant at one point
        # -- every word at loudness 0.5 / pitch 165 -- so the size and weight
        # envelopes could not fire at all and the renderer looked unimplemented.
        assert len({round(w.loudness, 3) for w in spec.words}) >= 3, name
        # ...and every word carries its own MEASURED motion curves, so the
        # derivation can be replayed and checked against the recording even
        # though the design system's own model is what ships.
        # A word whose glyphs never turn on camera (the clip opens mid-caption)
        # has nothing to measure, so require most rather than all.
        got = [w for w in spec.words if w.motion]
        assert len(got) >= 0.7 * len(spec.words), name
        for w in got:
            m = w.motion
            assert len(m.lift) == len(m.scale) == len(m.dwght) >= 4
            # t0 may be NEGATIVE: the window opens a lead before the word is
            # spoken, and the first word of a spec starts at t=0.
            assert m.dt > 0
    # Pitch drives WEIGHT, and a section with no weight emphasis legitimately
    # has one value -- the synchronization recording demonstrates timing, not
    # intonation, and its words really are uniform in weight. So require the
    # variation across the whole demo rather than within every section.
    assert len({round(w.pitch_hz, 2) for w in demo.words}) >= 3


def test_cc_bounds_the_rendered_type_axes():
    """`expression.wght_range`/`wdth_range` must clamp the RENDERED axis.

    The response curve leaves values at the pitch-domain edge uncompressed, so
    an 80 Hz voice resolved to wght 1000 and a 250 Hz one to 100 -- ultra-black
    and hairline beside ordinary text. Live mode always clamped; `cc` did not.
    """
    from autocwi.ccprosody import forward, merged_expression

    cfg = load_config()
    # `cc` may override the axis bounds; live keeps expression's calmer ones.
    lo, hi = merged_expression(cfg)["wght_range"]
    assert [lo, hi] != cfg["expression"]["wght_range"], (
        "this test is only meaningful while cc overrides the range")
    got = [forward(0.5, hz, 0.5, 165.0, cfg)["emphWght"] for hz in range(80, 251, 2)]
    assert min(got) >= lo and max(got) <= hi
    assert max(got) > min(got)        # ...but still actually varies


def _bare_captioner():
    """The established bare-instance pattern for exercising `_word_event`."""
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    captioner.db_history = deque(maxlen=120)
    return captioner


def _emit_db_word(captioner, index, db, final=False, text=None):
    """One synthetic word at its own slot, with a controlled span dB."""
    start = index * 0.6
    end = start + 0.5
    word = HypothesisWord(text or f"w{index}", start, end, 0.9)
    audio = np.full(int((end + 0.1) * SR), 10 ** (db / 20), dtype=np.float32)
    return captioner._word_event(word, audio, final=final)


def test_first_utterance_cues_calibrate_from_the_bootstrap():
    """A long first utterance must not saturate against the config range.

    `db_history` holds FINAL words only, and a first utterance finalizes all
    at once at its endpoint — on the PR film's 24 s opening monologue that
    left ~60 words normalizing against the static `db_range` fallback, where
    the narration read as loudness ≈ 1.0 and every ordinary word rendered at
    the crest clamp. Non-final emissions now bootstrap the window.
    """
    dbs = [-60, -52, -46, -40, -37, -36, -34, -32, -30, -28]

    def run():
        captioner = _bare_captioner()
        return [
            _emit_db_word(captioner, i, db)["loudness"]
            for i, db in enumerate(dbs)
        ]

    first, second = run(), run()
    # Deterministic: the same event sequence yields the same styling.
    assert first == second

    mapping = load_config()["mapping"]["loudness_to"]
    pivot = ((mapping["baseline"] - mapping["min"])
             / (mapping["max"] - mapping["min"]))
    # Before the bootstrap has six words there is no speaker scale to place a
    # word on: unmeasured is NEUTRAL (the 2.3.5 baseline), never the raw
    # config-range guess that rendered a session's first words at the clamp.
    for early in first[:5]:
        assert abs(early - pivot) < 1e-3  # events round loudness to 4 places
    captioner = _bare_captioner()
    for i, db in enumerate(dbs):
        _emit_db_word(captioner, i, db)
    assert not captioner.db_history          # nothing finalized yet
    # A median-loud word cues onto the CWI baseline, not the saturated top.
    probe = _emit_db_word(captioner, len(dbs), -36)["loudness"]
    assert abs(probe - pivot) < 0.12
    # Expression survives in both directions without saturating.
    quiet = _emit_db_word(captioner, len(dbs) + 1, -55)["loudness"]
    loud = _emit_db_word(captioner, len(dbs) + 2, -30)["loudness"]
    assert quiet < probe < loud
    assert loud < 0.98


def test_bootstrap_ignores_re_emissions_of_one_slot():
    """A pending word re-emitted on every hypothesis is ONE observation."""
    captioner = _bare_captioner()
    # One word re-emitted 20 times, then five distinct words: six slots.
    for _ in range(20):
        _emit_db_word(captioner, 0, -30)
    for i, db in enumerate((-60, -52, -46, -40, -36), start=1):
        _emit_db_word(captioner, i, db)
    assert len(captioner.db_bootstrap) == 6

    control = _bare_captioner()
    _emit_db_word(control, 0, -30)
    for i, db in enumerate((-60, -52, -46, -40, -36), start=1):
        _emit_db_word(control, i, db)

    probe = _emit_db_word(captioner, 7, -38)["loudness"]
    assert probe == _emit_db_word(control, 7, -38)["loudness"]


def test_calibrated_history_ignores_bootstrap():
    """Once durable calibration exists, the bootstrap must not perturb it."""
    history = [-46, -40, -37, -36, -34, -32, -30]

    control = _bare_captioner()
    control.db_history = deque(history, maxlen=120)
    expected = _emit_db_word(control, 0, -38)["loudness"]

    poisoned = _bare_captioner()
    poisoned.db_history = deque(history, maxlen=120)
    poisoned.db_bootstrap = {("§slot", 0, 999): -999.0,
                             ("§slot", 0, 998): 0.0}
    got = _emit_db_word(poisoned, 0, -38)["loudness"]
    assert got == expected
    # The hand-off is explicit: durable calibration clears the bootstrap.
    assert not poisoned.db_bootstrap


def _voiced_word(captioner, index, db, tilt_hz_energy, final=True):
    """A synthetic voiced word: controlled LEVEL and controlled spectral tilt.

    `tilt_hz_energy` scales the 1-5 kHz band only, so level and vocal effort
    move independently -- which is the whole point of the channel under test.
    """
    start = index * 0.6
    end = start + 0.5
    t = np.arange(int((end + 0.1) * SR)) / SR
    low = sum(np.sin(2 * np.pi * f * t) for f in (150, 300, 600))
    high = sum(np.sin(2 * np.pi * f * t) for f in (1500, 2500, 3500))
    signal = low + tilt_hz_energy * high
    signal *= (10 ** (db / 20)) / max(1e-9, float(np.sqrt(np.mean(signal ** 2))))
    word = HypothesisWord(f"w{index}", start, end, 0.9)
    return captioner._word_event(word, signal.astype(np.float32), final=final)


def test_pressed_voice_reads_louder_than_level_alone():
    """CWI 2.3.5 asks for VOLUME, and mastered audio destroys LEVEL.

    Measured on the PR film: the drill sergeant shouts at full effort and
    lands 1.6 dB QUIETER than the calm narration, so ranking his words by
    level scores AUC 0.367 -- worse than chance. Pressed phonation still
    flattens the spectrum, so equal level plus more effort must render larger.
    """
    captioner = _bare_captioner()
    for i in range(10):                       # calm baseline, same level
        _voiced_word(captioner, i, -20, 0.05)

    calm = _voiced_word(captioner, 10, -20, 0.05)
    pressed = _voiced_word(captioner, 11, -20, 1.6)

    # The LEVEL measurement itself must not move: prosody still reports what
    # the microphone heard, and haptics threshold on it.
    assert calm["loudness_db"] == pytest.approx(pressed["loudness_db"], abs=0.6)
    assert pressed["loudness"] > calm["loudness"]


def test_vocal_effort_is_one_sided_and_gated():
    """A breathy word must not SHRINK, and the channel must be switchable."""
    captioner = _bare_captioner()
    for i in range(10):
        _voiced_word(captioner, i, -20, 0.6)
    calm = _voiced_word(captioner, 10, -20, 0.6)
    breathy = _voiced_word(captioner, 11, -20, 0.02)
    # Low effort already reads quiet through `db`; subtracting would penalize
    # a soft voice twice, so the lift is strictly one-sided.
    assert breathy["loudness"] == pytest.approx(calm["loudness"], abs=1e-9)

    off = _bare_captioner()
    off.cfg = copy.deepcopy(off.cfg)
    off.cfg["live"]["vocal_effort"]["enabled"] = False
    for i in range(10):
        _voiced_word(off, i, -20, 0.05)
    flat_calm = _voiced_word(off, 10, -20, 0.05)
    flat_pressed = _voiced_word(off, 11, -20, 1.6)
    assert flat_pressed["loudness"] == pytest.approx(flat_calm["loudness"], abs=1e-9)


def test_one_stressed_word_survives_the_effort_mean():
    """A single stressed word is an EVENT; the smoothing mean deletes it.

    This is why "louder" never moved. `smoothing_words` exists because
    sustained pressed phonation is a speaking STYLE and a causal mean reads it
    far better than one word does -- but the six words before "louder" are calm
    narration, so the mean lands below the median and the lift is exactly 0.000
    however the rest is tuned. `emphasis_blend` is how much of the word's own
    tilt survives that mean.
    """
    stressed = StreamingCaptioner.__new__(StreamingCaptioner)
    cfg = {"emphasis_blend": 0.75, "smoothing_words": 6,
           "pitch_gain": 0.0, "length_gain": 0.0}
    calm = [(-14.0, 150.0, 0.06)] * 5
    # One word with a much stronger tilt, at the end of calm speech.
    scores = stressed._prominence(calm + [(2.0, 150.0, 0.06)], (150.0, 0.06), cfg)
    assert scores[-1] > scores[0] + 8, scores

    # At blend 0 -- the pre-2026-08-02 behaviour -- the same word is erased:
    # a sixth of the excursion survives, which is inside the deadband.
    flat = stressed._prominence(
        calm + [(2.0, 150.0, 0.06)], (150.0, 0.06), {**cfg, "emphasis_blend": 0.0},
    )
    assert flat[-1] - flat[0] < 3, flat


def test_prominence_reads_pitch_and_lengthening_not_syllable_count():
    """The two cues that separate "louder", and the trap in the second one."""
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    cfg = {"emphasis_blend": 1.0, "smoothing_words": 1,
           "pitch_gain": 1.0, "length_gain": 0.5}
    baseline = (150.0, 0.06)
    plain = captioner._prominence([(-10.0, 150.0, 0.06)], baseline, cfg)[0]
    high = captioner._prominence([(-10.0, 260.0, 0.06)], baseline, cfg)[0]
    held = captioner._prominence([(-10.0, 150.0, 0.12)], baseline, cfg)[0]
    assert high > plain and held > plain

    # Unvoiced (0 Hz) contributes NOTHING rather than reading as an impossibly
    # low voice -- the same rule `voiceTone` follows on the client.
    assert captioner._prominence([(-10.0, 0.0, 0.06)], baseline, cfg)[0] == plain

    # Length is per CHARACTER, so a long word said at ordinary pace scores the
    # same as a short one. Raw duration would rank "identification." above
    # every shout in the film.
    assert captioner._prominence([(-10.0, 150.0, 0.06)], baseline, cfg)[0] == plain
