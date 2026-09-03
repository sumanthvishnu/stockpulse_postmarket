"""Adult-only prompt check. Blocks explicit underage *requests*, not 'looks 18' guesses."""

from __future__ import annotations

import re


class PromptBlocked(ValueError):
    pass


_BLOCKED = re.compile(
    r"\b("
    r"child|children|kid|kids|toddler|infant|baby|preteen|underage|minor|"
    r"loli|lolita|shota|pedophile|pedo|"
    r"schoolgirl|schoolboy|young girl|young boy|"
    r"11[- ]year|12[- ]year|13[- ]year|14[- ]year|15[- ]year|16[- ]year|17[- ]year|"
    r"under 18|under18"
    r")\b",
    re.IGNORECASE,
)


def assert_adult_prompt(text: str) -> None:
    if text and _BLOCKED.search(text):
        raise PromptBlocked(
            "That prompt asks for a minor. This bot only generates adults."
        )
