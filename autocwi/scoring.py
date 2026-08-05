"""Shared transcript scoring.

Lives in the package, not in a script, because both benchmarks need it and a
script importing another script was fragile. Korean scores by CHARACTER: word
tokenization matches `[A-Z0-9']+` and drops every Hangul codepoint, which makes
a Korean pair score as a perfect empty-vs-empty match.

Korean additionally canonicalizes before scoring -- see `canonical_korean`.
FLEURS writes `2011년`, every Korean recognizer here says `이천십일년`, and
scoring those as 4 substitutions measures a WRITING CONVENTION, not
recognition. MEASURED on the 8-clip FLEURS ko slice: 26 of 44 edits (59%) sat
within six characters of a digit. Without this, any provider or checkpoint A/B
is decided by whose formatting matches the reference's, which is exactly the
comparison the benchmark exists to avoid.
"""

from __future__ import annotations

import re

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# Sino-Korean, which is what is read for years, dates, counts and measurements
# -- the whole of what FLEURS writes in digits. Native Korean numerals
# (하나/둘/셋, used with counters like 개·명·살·시) are deliberately NOT generated.
# MEASURED over the 120-clip ko reference set: of 48 digit runs, only 5 sit
# beside a counter at all (`13개`, `25개`, `78개`, `19명`, `6 대`) and every one
# of those takes the Sino reading regardless, because native numerals give way
# to Sino above ~20 and `대` here is a score ("육 대 육"). A native reader would
# therefore add a second numeral system, and its own errors, for no measured
# gain. The known gap is small counts with 시/개/명 -- `3시` is `세시`, not the
# `삼시` produced here. Both sides get the same treatment, so this can only
# leave a real difference in place, never manufacture agreement.
SINO_DIGITS = "영일이삼사오육칠팔구"
SMALL_UNITS = ("", "십", "백", "천")
BIG_UNITS = ("", "만", "억", "조", "경")
DIGIT_RUN = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Anything neither Hangul nor alphanumeric is unspoken and cannot be recognized
# or missed, so it must not score. FLEURS ko clip 0006 carries four `"` and a
# `.`; against a recognizer that emits no punctuation at all those were five
# free deletions.
KOREAN_KEEP = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏0-9A-Za-z]")


def is_korean(text: str) -> bool:
    return bool(HANGUL.search(text))


def _sino_below_myriad(value: int) -> str:
    """Read 0 < value < 10_000. The leading 1 of 십/백/천 is silent."""

    parts = []
    for position in range(3, -1, -1):
        digit = (value // 10 ** position) % 10
        if not digit:
            continue
        # 15 is 십오 and 1940 is 천구백사십 -- never 일십오 / 일천구백사십.
        # The ones place keeps its digit, so 1 alone stays 일 (hence 10_000
        # reading 일만 with no special case here).
        head = "" if digit == 1 and position else SINO_DIGITS[digit]
        parts.append(head + SMALL_UNITS[position])
    return "".join(parts)


def sino_korean(value: int) -> str:
    """Spell an integer the way it is read aloud."""

    if value < 0:
        return "마이너스" + sino_korean(-value)
    if value == 0:
        return "영"
    groups, index = [], 0
    while value:
        group, value = value % 10_000, value // 10_000
        if group:
            groups.append(_sino_below_myriad(group) + BIG_UNITS[index])
        index += 1
        if index >= len(BIG_UNITS):
            break
    if value:  # beyond 경 -- read the remainder digit by digit rather than lie
        groups.append("".join(SINO_DIGITS[int(ch)] for ch in str(value)))
    return "".join(reversed(groups))


def expand_korean_numbers(text: str) -> str:
    """Rewrite Arabic digit runs as their spoken Sino-Korean reading."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0).replace(",", "")
        whole, _, fraction = raw.partition(".")
        # A year written 2011 is 이천십일; a bare digit string that cannot be a
        # quantity (a serial, a phone number) is not distinguishable here, and
        # reading it as a quantity is the far commoner case in read speech.
        spoken = sino_korean(int(whole)) if whole else ""
        if fraction:
            spoken += "점" + "".join(SINO_DIGITS[int(ch)] for ch in fraction)
        return spoken

    return DIGIT_RUN.sub(replace, text)


def canonical_korean(text: str) -> str:
    """Put Korean text into the form it is SPOKEN in, for scoring only.

    Digits become their reading and unspoken punctuation is dropped. Applied to
    reference and hypothesis alike, so it can only remove a formatting
    difference, never invent agreement about a phoneme.
    """

    return "".join(KOREAN_KEEP.findall(expand_korean_numbers(text)))


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[A-Z0-9']+", text.upper())


def normalized_characters(text: str) -> list[str]:
    return [ch for ch in text if not ch.isspace()]


def scored_units(text: str, lang: str | None = None,
                 normalize: bool = True) -> list[str]:
    """Pick the scoring unit from the TEXT, not just the caller's flag.

    A mislabelled Korean clip scored as English would otherwise come out a
    perfect 0%. `normalize=False` returns the pre-2026-08-05 raw units, which
    is what the historical 12.54% CER was measured on -- keep it available so
    the two numbers can be printed side by side rather than silently swapped.
    """

    if lang == "ko" or is_korean(text):
        if normalize:
            return normalized_characters(canonical_korean(text))
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
