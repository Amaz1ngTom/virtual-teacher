from __future__ import annotations

import re


_CLOSING_MARKS = set('"\'”’」』）》】〕〉')
_SENTENCE_ENDS = set("。！？!?")
_CLAUSE_ENDS = set("，,、；;：:")


def _join_units(left: str, right: str) -> str:
    if not left:
        return right
    # Stripping around boundaries is useful for Chinese and newlines, but
    # adjacent English fragments still need their conventional separator.
    separator = " " if left[-1].isascii() and right[0].isascii() else ""
    return left + separator + right


def _split_at_marks(text: str, marks: set[str]) -> list[str]:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] not in marks:
            index += 1
            continue
        end = index + 1
        while end < len(text) and text[end] in _CLOSING_MARKS:
            end += 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = end
        index = end
    remainder = text[start:].strip()
    if remainder:
        parts.append(remainder)
    return parts


def split_complete_sentences(text: str) -> list[str]:
    """Split text at natural sentence boundaries while retaining punctuation.

    A newline is also treated as a boundary. ASCII periods only end a sentence
    when followed by whitespace (or the end of the text), so version numbers
    and decimal values such as ``Python 3.10`` remain intact.
    """

    normalized = re.sub(r"[ \t]+", " ", text.strip())
    if not normalized:
        return []

    sentences: list[str] = []
    start = 0
    index = 0
    length = len(normalized)
    while index < length:
        char = normalized[index]
        boundary = char in _SENTENCE_ENDS or char == "\n"
        if char == ".":
            previous_is_digit = index > 0 and normalized[index - 1].isdigit()
            next_is_digit = index + 1 < length and normalized[index + 1].isdigit()
            next_is_space_or_end = index + 1 == length or normalized[index + 1].isspace()
            boundary = not (previous_is_digit and next_is_digit) and next_is_space_or_end

        if not boundary:
            index += 1
            continue

        end = index + 1
        while end < length and normalized[end] in _CLOSING_MARKS:
            end += 1
        sentence = normalized[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
        while start < length and normalized[start].isspace():
            start += 1
        index = start

    remainder = normalized[start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences


def segment_for_avatar(text: str, max_chars: int = 110) -> list[str]:
    """Pack complete sentences into memory-safe avatar rendering segments.

    A sentence over the soft limit falls back to Chinese/English comma,
    semicolon and colon boundaries. A clause without any safe punctuation is
    still kept whole instead of being cut at an arbitrary character.
    """

    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    sentences = split_complete_sentences(text)
    if not sentences:
        return []

    units: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            units.append(sentence)
        else:
            units.extend(_split_at_marks(sentence, _CLAUSE_ENDS))

    segments: list[str] = []
    current = ""
    for unit in units:
        candidate = _join_units(current, unit)
        if current and len(candidate) > max_chars:
            segments.append(current)
            current = unit
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments
