"""Shared transcript scoring.

Lives in the package, not in a script, because both benchmarks need it and a
script importing another script was fragile. Korean scores by CHARACTER: word
tokenization matches `[A-Z0-9']+` and drops every Hangul codepoint, which makes
a Korean pair score as a perfect empty-vs-empty match.
"""

from __future__ import annotations

import re

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")


def is_korean(text: str) -> bool:
    return bool(HANGUL.search(text))


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[A-Z0-9']+", text.upper())


def normalized_characters(text: str) -> list[str]:
    return [ch for ch in text if not ch.isspace()]


def scored_units(text: str, lang: str | None = None) -> list[str]:
    """Pick the scoring unit from the TEXT, not just the caller's flag.

    A mislabelled Korean clip scored as English would otherwise come out a
    perfect 0%.
    """

    if lang == "ko" or is_korean(text):
        return normalized_characters(text)
    return normalized_words(text)


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left != right),
            ))
        previous = current
    return previous[-1]


def has_digits(text: str) -> bool:
    """Digit-vs-spelled-out is a formatting convention, not a recognition error.

    It silently rigs a cross-backend A/B toward whichever backend matches the
    reference's style, so callers warn when references contain digits.
    """

    return any(ch.isdigit() for ch in text)
