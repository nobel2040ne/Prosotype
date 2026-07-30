"""Opt-in cloud endpoint verifier.

Fully offline, like every other test here: the cloud client is injected, so
these never need the openai package, an API key, or a network.
"""

import numpy as np
import pytest

from autocwi.cloud_verifier import CloudEndpointVerifier

SR = 16_000


class FakeLocal:
    """Stand-in for the offline `EndpointVerifier`."""

    def __init__(self, text="local text"):
        self.text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


class FakeClient:
    """Minimal shape of `client.audio.transcriptions.create`."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.audio = self

    @property
    def transcriptions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def build(local, client, **options):
    cfg = {"live": {"lang": "en", "openai_verifier": {"min_duration_s": 0.4,
                                                      **options}}}
    return CloudEndpointVerifier(local, cfg, client=client)


def speech(seconds=2.0):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def test_cloud_text_replaces_local_when_the_call_succeeds():
    local = FakeLocal("their a test")
    verifier = build(local, FakeClient(result="They're a test."))

    assert verifier.transcribe(speech()) == "They're a test."
    assert verifier.stats.cloud_used == 1
    assert verifier.stats.disagreements == 1


def test_network_failure_falls_back_to_the_local_transcript():
    local = FakeLocal("offline transcript")
    client = FakeClient(error=TimeoutError("uplink stalled"))
    verifier = build(local, client)

    # A booth demo must never lose an utterance because the link hiccuped.
    assert verifier.transcribe(speech()) == "offline transcript"
    assert verifier.stats.fell_back == 1
    assert "TimeoutError" in verifier.stats.last_error


def test_empty_cloud_response_falls_back_rather_than_blanking_the_caption():
    local = FakeLocal("offline transcript")
    verifier = build(local, FakeClient(result="   "))

    assert verifier.transcribe(speech()) == "offline transcript"
    assert verifier.stats.fell_back == 1
    assert verifier.stats.cloud_used == 0


def test_short_buffer_skips_the_round_trip_entirely():
    local = FakeLocal("hm")
    client = FakeClient(result="should not be requested")
    verifier = build(local, client)

    assert verifier.transcribe(speech(0.2)) == "hm"
    assert client.calls == []
    assert verifier.stats.skipped_short == 1


def test_sdk_object_response_is_unwrapped():
    class Result:
        text = "from an object"

    verifier = build(FakeLocal(), FakeClient(result=Result()))
    assert verifier.transcribe(speech()) == "from an object"


def test_shipped_config_default_stays_fully_offline(monkeypatch):
    """The DEFAULT in config.yaml must not reach the cloud path at all."""

    from autocwi.config import load_config
    from autocwi.live import apply_verifier_backend

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "autocwi.cloud_verifier.CloudEndpointVerifier",
        lambda *a, **k: pytest.fail("cloud built for the offline default"),
    )
    local = FakeLocal()

    assert apply_verifier_backend(local, load_config()) is local


def test_enabling_the_cloud_backend_without_a_key_refuses_to_start(monkeypatch):
    """Must fail loudly rather than silently fall through to the offline path
    and leave the operator believing audio is being uploaded (or not)."""

    from autocwi.live import apply_verifier_backend

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        apply_verifier_backend(FakeLocal(), {"live": {"verifier_backend": "openai"}})
