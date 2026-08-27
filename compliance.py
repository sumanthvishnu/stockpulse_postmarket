#!/usr/bin/env python3
"""StockPulse compliance linter (handover spec section 6).

Runs on the LLM's HTML output before render/publish. Hard rules fail the
build (with retry); the linter returns the list of violations so the pipeline
can feed them back to the model.
"""
import re

BANNED_GLYPHS = ("\u20b9",)                      # rupee glyph
BANNED_DASHES = ("\u2014", "\u2013", "\u2015")   # em / en / horizontal bar

# Advice lexicon that has no legitimate use in this report. Word-boundary
# matched, so "accumulation" (allowed, delivery% interpretation) is NOT
# flagged by "accumulate", and "recommendation" is NOT flagged by "recommend".
ADVICE_LEXICON = (
    "target price", "stop loss", "stop-loss", "strong buy", "strong sell",
    "accumulate", "recommend", "should buy", "should sell", "buy now",
    "sell now", "you should invest",
)


def _strip_markup(html):
    """Drop <style>/<script> blocks so CSS calc() etc. is not linted."""
    return re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html,
                  flags=re.I | re.S)


def lint(html, kind="report"):
    """Return a list of violation strings (empty list = clean)."""
    issues = []
    text = _strip_markup(html)

    for g in BANNED_GLYPHS:
        if g in text:
            issues.append(f"banned currency glyph '{g}' - use 'Rs'")

    for d in BANNED_DASHES:
        if d in text:
            issues.append(f"banned dash '{d}' - no em/en dashes")

    if re.search(r" - ", text):
        issues.append("spaced hyphen ' - ' used as a connector")

    if re.search(r"~\s*\d", text) or re.search(r"\d\s*~", text):
        issues.append("'~' adjacent to a numeral (no estimated figures)")

    if re.search(r"\b(?:est\.|approx\.)\s*\d", text, re.I):
        issues.append("'est.'/'approx.' adjacent to a numeral")

    low = text.lower()
    for w in ADVICE_LEXICON:
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            issues.append(f"advice lexicon: '{w}'")

    if kind == "report":
        if not re.search(r"not investment advice", low):
            issues.append("missing 'Not investment advice' disclaimer in body")

    return issues
