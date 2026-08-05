"""Cloud backend message parsers and the timing metrics.

Offline: these exercise the pure parsers against recorded-shape frames. The
socket layers are deliberately NOT covered -- they need real keys and a network,
and pretending otherwise would be the same self-referential testing the eval set
already suffered from.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from asr_backends import (  # noqa: E402
    TimedWord,
    collapse_revisions,
    parse_soniox,
    parse_speechmatics,
)
from benchmark import align_words, onset_gaps  # noqa: E402

from autocwi.scoring import (  # noqa: E402
    normalized_words,
    scored_units,
    sino_korean,
)


# -- Speechmatics -----------------------------------------------------------


def sm_word(content, start, end, speaker=None):
    alternative = {"content": content}
    if speaker is not None:
        alternative["speaker"] = speaker
    return {"type": "word", "start_time": start, "end_time": end,
            "alternatives": [alternative]}


def test_speechmatics_words_carry_their_spans():
    words = parse_speechmatics([
        {"message": "AddTranscript", "results": [
            sm_word("hello", 0.10, 0.45),
            sm_word("world", 0.52, 0.90),
        ]},
    ])

    assert [w.text for w in words] == ["hello", "world"]
    assert words[0].start == pytest.approx(0.10)
    assert words[1].end == pytest.approx(0.90)


def test_speechmatics_partials_are_ignored():
    """Partials are provisional; consuming them would double-count."""

    words = parse_speechmatics([
        {"message": "AddPartialTranscript", "results": [sm_word("hel", 0.1, 0.2)]},
        {"message": "AddTranscript", "results": [sm_word("hello", 0.1, 0.45)]},
    ])

    assert [w.text for w in words] == ["hello"]


def test_speechmatics_punctuation_is_dropped():
    """Punctuation has no acoustic span and would pollute onset gaps."""

    words = parse_speechmatics([
        {"message": "AddTranscript", "results": [
            sm_word("hello", 0.1, 0.45),
            {"type": "punctuation", "start_time": 0.45, "end_time": 0.45,
             "alternatives": [{"content": "."}]},
        ]},
    ])

    assert [w.text for w in words] == ["hello"]


def test_speechmatics_speaker_labels_survive_and_unknown_is_none():
    words = parse_speechmatics([
        {"message": "AddTranscript", "results": [
            sm_word("hi", 0.0, 0.2, speaker="S1"),
            sm_word("there", 0.3, 0.6, speaker="UU"),
        ]},
    ])

    assert words[0].speaker == "S1"
    assert words[1].speaker is None


# -- Soniox -----------------------------------------------------------------


def sx(text, start_ms, end_ms, is_final=True, speaker=None):
    token = {"text": text, "start_ms": start_ms, "end_ms": end_ms,
             "is_final": is_final}
    if speaker is not None:
        token["speaker"] = speaker
    return token


def test_soniox_subword_tokens_merge_into_words():
    """Leading-space tokens mark word starts, as the Korean export also does."""

    words = parse_soniox([
        {"tokens": [sx("Beau", 300, 420), sx("ti", 420, 540),
                    sx("ful", 540, 780), sx(" day", 800, 1000)]},
    ])

    assert [w.text for w in words] == ["Beautiful", "day"]
    assert words[0].start == pytest.approx(0.300)
    # The merged word spans its first token's start to its last token's end.
    assert words[0].end == pytest.approx(0.780)
    assert words[1].start == pytest.approx(0.800)


def test_soniox_non_final_tokens_are_discarded():
    """Non-final text 'may change, disappear, or be replaced'."""

    words = parse_soniox([
        {"tokens": [sx("Hel", 100, 200, is_final=False)]},
        {"tokens": [sx("Hello", 100, 400, is_final=True)]},
    ])

    assert [w.text for w in words] == ["Hello"]


# -- local event collapsing -------------------------------------------------


def word_event(text, start, end, word_id=None, speaker=None):
    event = {"type": "word", "text": text, "start": start, "end": end}
    if word_id is not None:
        event["word_id"] = word_id
    if speaker is not None:
        event["speaker"] = speaker
    return event


def test_a_revised_word_is_not_a_second_word():
    """Speaker/text revisions reuse the word_id; counting both duplicated
    whole phrases on sample.mp4 (59 -> 64 words)."""

    words = collapse_revisions([
        word_event("River", 1.0, 1.4, "uN:w0"),
        word_event("River", 1.0, 1.4, "uN:w0", speaker="S2"),
    ])

    assert len(words) == 1
    assert words[0].speaker == "S2"  # last revision wins


def test_revision_keeps_its_original_position():
    words = collapse_revisions([
        word_event("one", 0.0, 0.2, "w0"),
        word_event("two", 0.3, 0.5, "w1"),
        word_event("ONE", 0.0, 0.2, "w0"),
    ])

    assert [w.text for w in words] == ["ONE", "two"]


def test_events_without_an_id_never_collapse_together():
    words = collapse_revisions([
        word_event("a", 0.0, 0.2),
        word_event("a", 0.3, 0.5),
    ])

    assert len(words) == 2


def test_non_word_events_are_ignored():
    words = collapse_revisions([
        {"type": "commit", "text": "x", "start": 0.0, "end": 0.1},
        {"type": "level", "rms": 0.4},
        word_event("real", 0.0, 0.2, "w0"),
    ])

    assert [w.text for w in words] == ["real"]


# -- metrics ----------------------------------------------------------------


def test_onset_gaps_sort_by_start_before_measuring():
    """Backends may emit out of order; the gaps must still be acoustic, since
    this is the signal the motion clock is selected from."""

    words = [TimedWord("c", 0.9, 1.1), TimedWord("a", 0.0, 0.2),
             TimedWord("b", 0.5, 0.7)]

    assert onset_gaps(words) == pytest.approx([0.5, 0.4])


def test_align_words_pairs_only_exact_matches():
    left = [TimedWord("the", 0.0, 0.1), TimedWord("cat", 0.2, 0.4),
            TimedWord("sat", 0.5, 0.7)]
    right = [TimedWord("the", 0.05, 0.15), TimedWord("bat", 0.2, 0.4),
             TimedWord("sat", 0.55, 0.75)]

    pairs = align_words(left, right)

    assert [a.text for a, _ in pairs] == ["the", "sat"]
    assert pairs[1][1].start == pytest.approx(0.55)


def test_align_words_handles_insertions():
    left = [TimedWord("a", 0.0, 0.1), TimedWord("b", 0.2, 0.3)]
    right = [TimedWord("a", 0.0, 0.1), TimedWord("x", 0.15, 0.18),
             TimedWord("b", 0.2, 0.3)]

    assert [a.text for a, _ in align_words(left, right)] == ["a", "b"]


def test_korean_is_scored_by_character_even_when_mislabelled_as_english():
    """The hazard: `normalized_words` matches [A-Z0-9']+ and drops all Hangul,
    so a Korean pair scored as English comes out empty-vs-empty -- a perfect 0%.
    `scored_units` must sniff the text rather than trust the flag."""

    korean = "다리 밑 수직 간격은"

    assert normalized_words(korean) == []                          # the trap
    assert scored_units(korean, "ko") == list("다리밑수직간격은")
    assert scored_units(korean, "en") == list("다리밑수직간격은")   # guarded
    assert scored_units("the cat sat", "en") == ["THE", "CAT", "SAT"]


def test_sino_korean_drops_the_silent_leading_one():
    """15 is 십오, never 일십오; 1940 is 천구백사십, never 일천구백사십.

    The ones place keeps its digit, which is what makes 10_000 read 일만
    without a special case.
    """

    assert sino_korean(15) == "십오"
    assert sino_korean(1940) == "천구백사십"
    assert sino_korean(2011) == "이천십일"
    assert sino_korean(100) == "백"
    assert sino_korean(10_000) == "일만"
    assert sino_korean(0) == "영"
    assert sino_korean(305) == "삼백오"


def test_korean_scoring_ignores_number_formatting_and_punctuation():
    """FLEURS writes `2011년`; every recognizer here says `이천십일년`.

    Scoring those as substitutions measures a WRITING CONVENTION. MEASURED on
    the 8-clip FLEURS ko slice, 26 of 44 edits sat within six characters of a
    digit, which is enough to decide a checkpoint A/B on formatting alone.
    """

    reference = '"1940년 8월 15일 연합군은 남부를 침략했다.'
    hypothesis = "천구백사십 년 팔월 십오일 연합군은 남부를 침략했다"

    assert scored_units(reference, "ko") == scored_units(hypothesis, "ko")
    # ...and the raw column still sees the difference, so a regression against
    # the pre-normalization records stays visible instead of being hidden.
    assert (scored_units(reference, "ko", normalize=False)
            != scored_units(hypothesis, "ko", normalize=False))


def test_korean_normalization_cannot_invent_phoneme_agreement():
    """It may only remove formatting -- a real substitution must still score."""

    # 드래군 -> 드래곤 is a genuine recognition error next to a digit-free span.
    assert (scored_units("드래군 작전", "ko")
            != scored_units("드래곤 작전", "ko"))
    # A dropped leading word stays a deletion.
    assert (scored_units("염소 사육은", "ko")
            != scored_units("소 사육은", "ko"))
