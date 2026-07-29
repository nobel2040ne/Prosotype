from collections import deque
import json

import numpy as np

from autocwi.config import load_config
from autocwi.live import (
    HypothesisWord,
    Broadcaster,
    SpeakerAttribution,
    SpeakerTracker,
    SortformerHybridSpeakerTracker,
    StreamingCaptioner,
    reconstruct_durable_words,
)
from autocwi.livepage import render_live
from autocwi.sortformer import (
    SortformerDecision,
    select_sortformer_decision,
)


A = np.array([1.0, 0.0], dtype=np.float32)
B = np.array([0.0, 1.0], dtype=np.float32)
C = np.array([0.25, -np.sqrt(0.9375)], dtype=np.float32)


def manager(**overrides) -> SpeakerTracker:
    settings = dict(
        min_enrollment_duration_s=0.8,
        min_assignment_duration_s=0.25,
        stable_after_observations=2,
        assignment_threshold=0.72,
        provisional_threshold=0.58,
        new_speaker_threshold=0.42,
        centroid_ema_alpha=0.15,
        switch_hysteresis_s=0.35,
        short_turn_max_duration_s=0.4,
        retain_threshold=0.64,
        switch_threshold=0.72,
        min_confidence_margin=0.08,
    )
    settings.update(overrides)
    return SpeakerTracker(lambda samples: None, **settings)


def stabilize_first_speaker(tracker: SpeakerTracker) -> None:
    assert tracker.observe(A, 0.0, 1.0).status == "provisional"
    result = tracker.observe(A, 1.0, 2.0)
    assert (result.speaker_id, result.status) == ("S1", "stable")


def test_repeated_observations_make_one_speaker_stable():
    tracker = manager()
    first = tracker.observe(A, 0.0, 1.0, observation_key="w1")
    second = tracker.observe(A, 1.0, 2.0, observation_key="w2")
    assert (first.speaker_id, first.status) == ("S1", "provisional")
    assert (second.speaker_id, second.status) == ("S1", "stable")
    assert tracker.counts == [2]
    assert tracker.enrolled_durations == [2.0]


def test_two_clearly_separated_speakers_get_distinct_ids():
    tracker = manager()
    stabilize_first_speaker(tracker)
    new = tracker.observe(B, 2.0, 2.8)
    switched = tracker.observe(B, 2.8, 3.6)
    assert (new.speaker_id, new.status) == ("S2", "provisional")
    assert (switched.speaker_id, switched.status) == ("S2", "stable")
    assert tracker.metrics()["speaker_id_switches"] == 1


def test_short_weak_backchannel_is_provisional_recent_speaker():
    tracker = manager()
    stabilize_first_speaker(tracker)
    result = tracker.observe(B, 2.0, 2.3, update=False)
    assert (result.speaker_id, result.status) == ("S1", "provisional")
    assert result.switch_decision == "retained-short-turn"


def test_low_confidence_observation_returns_unknown():
    tracker = manager()
    stabilize_first_speaker(tracker)
    weak = np.array([0.5, np.sqrt(0.75)], dtype=np.float32)
    result = tracker.observe(weak, 2.0, 2.6, update=False)
    assert (result.speaker_id, result.status) == (None, "unknown")
    assert result.reason == "best candidate below provisional threshold"


def test_short_turn_can_match_stable_profile_below_provisional_threshold():
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    weak_a = np.array(
        [0.197, 0.0, np.sqrt(1.0 - 0.197**2)],
        dtype=np.float32,
    )
    tracker = manager(
        stable_after_observations=1,
        assignment_threshold=0.38,
        provisional_threshold=0.20,
        new_speaker_threshold=0.30,
        short_stable_threshold=0.18,
        short_stable_min_margin=0.12,
        short_stable_max_duration_s=1.3,
    )
    assert tracker.observe(a, 0.0, 1.0).status == "stable"
    assert tracker.observe(b, 1.0, 2.0).status == "stable"

    result = tracker.observe(weak_a, 2.0, 2.4, update=False)

    assert (result.speaker_id, result.status) == ("S1", "stable")
    assert result.switch_decision == "accepted-short-stable"


def test_borderline_observation_does_not_switch_immediately():
    tracker = manager()
    stabilize_first_speaker(tracker)
    tracker.observe(B, 2.0, 3.0)
    tracker.observe(B, 3.0, 4.0)
    tracker.observe(A, 4.0, 5.0)
    tracker.observe(A, 5.0, 6.0)
    assert tracker.last_confidently_active_speaker == "S1"

    borderline = np.array([0.70, 0.71414284], dtype=np.float32)
    result = tracker.observe(borderline, 6.0, 6.5, update=False)
    assert (result.speaker_id, result.status) == (None, "unknown")
    assert result.switch_decision == "rejected-ambiguous"
    assert tracker.last_confidently_active_speaker == "S1"


def test_persistent_new_speaker_eventually_switches():
    tracker = manager()
    stabilize_first_speaker(tracker)
    first = tracker.observe(B, 2.0, 2.8)
    second = tracker.observe(B, 2.8, 3.6)
    assert first.status == "provisional"
    assert second.status == "stable"
    assert second.switch_decision == "accepted-switch"
    assert tracker.last_confidently_active_speaker == "S2"


def test_short_observation_does_not_update_centroid():
    tracker = manager()
    stabilize_first_speaker(tracker)
    centroid = tracker.centroids[0].copy()
    count = tracker.counts[0]
    result = tracker.observe(A, 2.0, 2.3)
    assert result.centroid_updated is False
    assert tracker.counts[0] == count
    assert np.array_equal(tracker.centroids[0], centroid)


def test_overlap_observation_does_not_update_centroid():
    tracker = manager()
    stabilize_first_speaker(tracker)
    centroid = tracker.centroids[0].copy()
    count = tracker.counts[0]
    result = tracker.observe(A, 2.0, 3.0, overlap=True)
    assert result.centroid_updated is False
    assert tracker.counts[0] == count
    assert np.array_equal(tracker.centroids[0], centroid)


def test_provisional_assignment_becomes_stable_and_queues_revision():
    tracker = manager()
    first = tracker.observe(A, 0.0, 1.0, observation_key="u0:w0")
    second = tracker.observe(A, 1.0, 2.0, observation_key="u1:w0")
    revisions = dict(tracker.drain_revisions())
    assert first.status == "provisional"
    assert second.status == "stable"
    assert revisions["u0:w0"].status == "stable"
    assert revisions["u0:w0"].revision_id > first.revision_id


def test_provisional_assignment_can_be_corrected():
    tracker = manager()
    stabilize_first_speaker(tracker)
    provisional = tracker.observe(
        B, 2.0, 2.3, update=False, observation_key="u1:w0"
    )
    corrected = tracker.observe(
        B, 2.0, 4.0, update=True, observation_key="u1:w0"
    )
    assert (provisional.speaker_id, provisional.status) == ("S1", "provisional")
    assert (corrected.speaker_id, corrected.status) == ("S2", "corrected")
    assert corrected.revision_id > provisional.revision_id
    assert tracker.metrics()["corrections"] == 1


def test_terminal_punctuation_exposes_clean_speaker_turns():
    # Adjacent one-second embedding windows overlap heavily and can smooth a
    # real turn. Endpoint punctuation supplies a clean comparison boundary;
    # the embeddings still decide whether the speaker actually changed.
    def embed(samples):
        return A if float(np.mean(samples)) >= 0 else B

    tracker = SpeakerTracker(
        embed,
        window_s=1.0,
        hop_s=0.25,
        change_below=-1.0,  # disable acoustic change points for this regression
        min_enrollment_duration_s=0.8,
        min_assignment_duration_s=0.25,
        stable_after_observations=1,
        assignment_threshold=0.38,
        provisional_threshold=0.25,
        new_speaker_threshold=0.20,
        retain_threshold=0.30,
        switch_threshold=0.38,
    )
    audio = np.concatenate((
        np.full(32_000, 0.1, dtype=np.float32),
        np.full(32_000, -0.1, dtype=np.float32),
    ))
    words = [
        HypothesisWord("Hello.", 0.0, 1.9, 0.9),
        HypothesisWord("Goodbye.", 2.0, 4.0, 0.9),
    ]

    labels = tracker.label_words(audio, words)

    assert [label.speaker_id for label in labels] == ["S1", "S2"]
    assert all(label.status == "stable" for label in labels)


def test_sse_word_revision_replaces_existing_word(tmp_path):
    initial = {
        "type": "word",
        "final": True,
        "word_id": "u0:w0",
        "text": "hello",
        "speaker": "S1",
        "speaker_status": "provisional",
        "speaker_revision_id": 1,
    }
    correction = {
        **initial,
        "speaker": "S2",
        "speaker_status": "corrected",
        "speaker_revision_id": 2,
        "correction": True,
    }
    reconstructed = reconstruct_durable_words([initial, correction])
    assert len(reconstructed) == 1
    assert reconstructed[0]["speaker"] == "S2"
    assert reconstructed[0]["speaker_revision_id"] == 2

    broadcaster = Broadcaster()
    broadcaster.publish(initial)
    broadcaster.publish(correction)
    replay = broadcaster.register(last_event_id=0)
    replayed = []
    while not replay.empty():
        payload = replay.get_nowait().decode()
        replayed.append(json.loads(payload.split("data: ", 1)[1]))
    assert len(reconstruct_durable_words(replayed)) == 1

    page = open(render_live(load_config(), tmp_path), encoding="utf-8").read()
    assert "function applySpeakerRevision(ev)" in page
    assert "wordNodes.get(RenderCore.wordKey(ev))" in page
    assert "addFinalWord(ev);  // bounded replay" in page


def test_haptic_speaker_change_ignores_provisional_assignment():
    captioner = StreamingCaptioner.__new__(StreamingCaptioner)
    captioner.cfg = load_config()
    captioner.db_history = deque([-30.0] * 8, maxlen=120)
    captioner.prosody_cache = {}
    captioner.speaker = "S1"
    captioner.utterance = 0
    captioner.stream_base = 0.0
    captioner._last_final_speaker = None
    captioner._word_slots = []
    captioner._final_word_events = {}
    audio = np.full(16_000, 0.03, dtype=np.float32)
    stable_s1 = SpeakerAttribution("S1", "stable", 0.95, 0.0, 1)
    provisional_s2 = SpeakerAttribution("S2", "provisional", 0.65, 0.7, 2)
    stable_s2 = SpeakerAttribution("S2", "stable", 0.95, 0.9, 3)

    captioner._word_event(
        HypothesisWord("one", 0.0, 0.3, 0.9), audio, True, stable_s1
    )
    tentative = captioner._word_event(
        HypothesisWord("hm", 0.3, 0.6, 0.9), audio, True, provisional_s2
    )
    accepted = captioner._word_event(
        HypothesisWord("two", 0.6, 0.9, 0.9), audio, True, stable_s2
    )
    assert "speaker_change" not in tentative
    assert accepted["speaker_change"] is True


def test_attribution_is_deterministic_across_repeated_runs():
    def run():
        tracker = manager()
        observations = [
            (A, 0.0, 1.0),
            (A, 1.0, 2.0),
            (B, 2.0, 2.3),
            (B, 2.0, 4.0),
            (A, 4.0, 5.0),
        ]
        return [
            (
                result.speaker_id,
                result.status,
                result.confidence,
                result.revision_id,
                result.reason,
            )
            for embedding, start, end in observations
            for result in [tracker.observe(embedding, start, end)]
        ]

    assert run() == run()


def test_sortformer_word_decision_uses_activity_weighted_overlap():
    decision = select_sortformer_decision(
        [
            {
                "speaker": 0,
                "start": 1.0,
                "end": 1.35,
                "finalized": True,
                "activity": 0.8,
            },
            {
                "speaker": 1,
                "start": 1.25,
                "end": 2.0,
                "finalized": False,
                "activity": 0.9,
            },
        ],
        1.2,
        1.8,
        processed_through=2.0,
    )

    assert decision is not None
    assert decision.speaker_index == 1
    assert np.isclose(decision.coverage, 0.9166666666666666)
    assert decision.finalized is False


def test_sortformer_word_decision_rejects_longer_faint_overlap():
    decision = select_sortformer_decision(
        [
            {
                "speaker": 0,
                "start": 0.0,
                "end": 1.0,
                "finalized": True,
                "activity": 0.2,
            },
            {
                "speaker": 1,
                "start": 0.3,
                "end": 0.8,
                "finalized": True,
                "activity": 0.9,
            },
        ],
        0.0,
        1.0,
        processed_through=1.0,
    )

    assert decision is not None
    assert decision.speaker_index == 1
    assert decision.coverage == 0.5


def test_sortformer_hybrid_is_provisional_live_and_stable_at_endpoint():
    class Bridge:
        latency_s = 1.04

        def decision(self, start, end, wait_ms=0):
            return SortformerDecision(1, 0.8, 0.9, True, end)

        def feed(self, samples, source_start, discontinuity=False):
            pass

        def finish(self):
            pass

        def close(self):
            pass

    fallback = manager(stable_after_observations=1)
    fallback.embed = lambda samples: A
    hybrid = SortformerHybridSpeakerTracker(
        Bridge(), fallback, min_word_coverage=0.24
    )
    audio = np.full(16_000, 0.1, dtype=np.float32)

    live = hybrid.classify_span(
        audio,
        0.0,
        0.8,
        observation_key="u0:w0",
    )
    endpoint = hybrid.label_words(
        audio,
        [HypothesisWord("hello", 0.0, 0.8, 0.9)],
        observation_keys=["u0:w0"],
    )[0]

    assert (live.speaker_id, live.status) == ("S2", "provisional")
    assert (endpoint.speaker_id, endpoint.status) == ("S1", "corrected")
    assert endpoint.revision_id > live.revision_id
    mapped_live = hybrid.classify_span(
        audio,
        1.0,
        1.8,
        observation_key="u0:w1",
    )
    assert (mapped_live.speaker_id, mapped_live.status) == ("S1", "provisional")


def test_additional_embedding_identity_waits_for_repeated_endpoints():
    tracker = manager()
    stabilize_first_speaker(tracker)
    assert tracker.observe(B, 2.0, 3.0).speaker_id == "S2"
    assert tracker.observe(B, 3.0, 4.0).status == "stable"
    tracker.embed = lambda samples: C
    audio = np.full(32_000, 0.1, dtype=np.float32)
    split_turn = [
        HypothesisWord("third.", 0.0, 0.9, 0.9),
        HypothesisWord("continues", 1.1, 2.0, 0.9),
    ]

    candidates = tracker.label_words(
        audio,
        split_turn,
        observation_keys=["u2:w0", "u2:w1"],
        timestamp_offset=4.0,
    )
    # Two clean punctuation segments in one endpoint are still only one
    # independent observation and cannot promote S3.
    assert tracker.counts[2] == 2
    assert tracker.profile_stable[2] is False
    confirmed = tracker.label_words(
        audio[:16_000],
        [HypothesisWord("third", 0.0, 1.0, 0.9)],
        observation_keys=["u3:w0"],
        timestamp_offset=6.0,
    )[0]
    revisions = dict(tracker.drain_revisions())

    assert all(
        (candidate.speaker_id, candidate.status) == (None, "unknown")
        for candidate in candidates
    )
    assert all(
        candidate.switch_decision
        == "pending-additional-speaker-confirmation"
        for candidate in candidates
    )
    assert (confirmed.speaker_id, confirmed.status) == ("S3", "stable")
    assert {
        key: (revisions[key].speaker_id, revisions[key].status)
        for key in ("u2:w0", "u2:w1")
    } == {
        "u2:w0": ("S3", "stable"),
        "u2:w1": ("S3", "stable"),
    }


def test_unverified_extra_sortformer_slot_never_becomes_visible_speaker():
    class Bridge:
        latency_s = 1.04

        def decision(self, start, end, wait_ms=0):
            return SortformerDecision(4, 0.8, 0.9, True, end)

        def feed(self, samples, source_start, discontinuity=False):
            pass

        def finish(self):
            pass

        def close(self):
            pass

    fallback = manager(stable_after_observations=1)
    fallback.embed = lambda samples: A
    hybrid = SortformerHybridSpeakerTracker(
        Bridge(), fallback, min_word_coverage=0.24
    )
    audio = np.full(16_000, 0.1, dtype=np.float32)

    live_before_endpoint = hybrid.classify_span(
        audio,
        0.0,
        0.8,
        observation_key="u0:w0",
    )
    endpoint = hybrid.label_words(
        audio,
        [HypothesisWord("hello", 0.0, 0.8, 0.9)],
        observation_keys=["u0:w0"],
    )[0]
    live_after_endpoint = hybrid.classify_span(
        audio,
        1.0,
        1.8,
        observation_key="u0:w1",
    )

    assert (live_before_endpoint.speaker_id, live_before_endpoint.status) == (
        None,
        "unknown",
    )
    assert endpoint.speaker_id == "S1"
    assert (live_after_endpoint.speaker_id, live_after_endpoint.status) == (
        "S1",
        "provisional",
    )
