from __future__ import annotations

import re


# Bump this value whenever pronunciation rules change. It is part of the
# course-video cache key, so an old video can never mask a corrected reading.
PRONUNCIATION_LEXICON_VERSION = "python-v2"


_TERM_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?<![A-Za-z0-9_])type\s*\(\s*x\s*\)\s*\.\s*__name__(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        "type x 的类型名称",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])2name(?![A-Za-z0-9_])", re.IGNORECASE),
        "数字二开头的 name",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])str(?![A-Za-z0-9_])", re.IGNORECASE),
        "string",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])int(?![A-Za-z0-9_])", re.IGNORECASE),
        "integer",
    ),
    (
        re.compile(r"(?<![A-Za-z0-9_])bool(?![A-Za-z0-9_])", re.IGNORECASE),
        "boolean",
    ),
)

_DUNDER_NAME = re.compile(
    r"(?<![A-Za-z0-9_])__([A-Za-z][A-Za-z0-9]*)__(?![A-Za-z0-9_])"
)
_UNDERSCORED_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)"
    r"(?![A-Za-z0-9_])"
)


def prepare_speech_text(display_text: str) -> str:
    """Convert visible teaching text into a TTS-friendly pronunciation form.

    Display text and LangGraph memory remain untouched. Only the string sent to
    the speech provider is transformed.
    """

    speech_text = display_text.replace("`", "")
    for pattern, replacement in _TERM_RULES:
        speech_text = pattern.sub(replacement, speech_text)
    speech_text = _DUNDER_NAME.sub(
        lambda match: f"双下划线 {match.group(1)} 双下划线",
        speech_text,
    )
    speech_text = _UNDERSCORED_IDENTIFIER.sub(
        lambda match: "，下划线，".join(match.group(1).split("_")),
        speech_text,
    )
    return speech_text
