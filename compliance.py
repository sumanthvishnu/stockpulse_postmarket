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

# The brand is NOT SEBI registered, so any registration claim (or a claim
# about a third party we cannot verify) is a false statement and is banned.
# The explicit denial "Not SEBI registered." is allowed.
def _false_registration_issues(low):
    out = []
    if re.search(r"(?<!not )(?:sebi[- ]registered|registered with sebi)", low):
        out.append("false SEBI registration claim: 'sebi registered'")
    for w in ("sebi registration", "sebi reg no", "sebi regn"):
        if w in low:
            out.append(f"false SEBI registration claim: '{w}'")
    return out


def _strip_markup(html):
    """Drop <style>/<script> blocks so CSS calc() etc. is not linted."""
    return re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html,
                  flags=re.I | re.S)


# ---------------------------------------------------------------------------
# Number lock: post-LLM verification that every numeral in the output traces
# to the datapack (handover spec section 4B: "re-assert that every numeral in
# the output still matches the locked payload"). Catches invented numbers
# (e.g. a fabricated option strike or a prior-day close) deterministically.
# ---------------------------------------------------------------------------

# Methodology / interpretation constants the report legitimately cites but
# which are not stored as datapack values.
RULE_CONSTANTS = {
    10,     # 52-week min close (Rs)
    15,     # delivery % band / max ban-list size
    20,     # bulk-deal threshold (Rs Cr)
    60,     # delivery % band
    100,    # broader-mover turnover floor (Rs Cr)
    300,    # 52-week new-high sanity bound
    25000,  # FII/DII single-day sanity bound (Rs Cr)
    0.5, 0.7, 1.3, 1.5,   # A/D + PCR interpretation bands
    3.5, 3.4, 3.3, 3.2, 3.1, 3.0, 2.1, 2.0, 1.4, 1.0, 0.9,  # version numbers
    # HTTP status codes the model may mention in a data-gap note
    200, 201, 202, 204, 301, 302, 400, 401, 403, 404, 408,
    409, 429, 500, 502, 503,
}

def _within(x, w):
    """Two-tier tolerance: ~1% for small ratios (PCR, A/D, small %), ~0.3%
    for large figures (closes, strikes, Rs Cr). Tolerates harmless rounding
    (0.593 -> 0.59, Rs 4,977 -> Rs 4,977.17) while flagging fabrications."""
    ax, aw = abs(x), abs(w)
    ref = max(ax, aw)
    tol = max(0.01 * ref, 0.005) if ref < 2.0 else 0.003 * ref
    return abs(ax - aw) <= tol

# The indices the report is allowed to cite (snapshot + sectoral tables).
# The other ~140 theme/strategy indices in derived.indices are excluded so a
# fabricated number cannot hide behind an unrelated index close.
MAIN_INDEX_NAMES = {
    "Nifty 50", "Nifty Bank", "Nifty Midcap 150", "Nifty Smallcap 250",
    "Nifty Next 50", "India VIX",
}
SECTORAL_NAMES = {
    "Nifty IT", "Nifty Bank", "Nifty Financial Services", "Nifty Auto",
    "Nifty Metal", "Nifty FMCG", "Nifty Realty", "Nifty Pharma",
    "Nifty Healthcare Index", "Nifty Energy", "Nifty Oil & Gas",
    "Nifty PSU Bank", "Nifty Private Bank", "Nifty Media",
    "Nifty Consumer Durables", "Nifty Infrastructure",
}


def _extract_numbers(html):
    """Yield (float, raw_string, context) for every numeral in the text."""
    t = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.I | re.S)
    t = re.sub(r"<script[^>]*>.*?</script>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<svg[^>]*>.*?</svg>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<link[^>]*>", " ", t, flags=re.I)   # Google Fonts etc.
    t = re.sub(r'(?:href|src)="[^"]*"', " ", t, flags=re.I)
    t = re.sub(r"(?:href|src)='[^']*'", " ", t, flags=re.I)
    t = re.sub(r'style="[^"]*"', " ", t, flags=re.I)
    t = re.sub(r"style='[^']*'", " ", t, flags=re.I)
    t = re.sub(r"#[0-9a-fA-F]{3,8}\b", " ", t)   # hex colours (#0F2744)
    t = re.sub(r"&#\d+;", " ", t)
    t = re.sub(r"&#x[0-9a-fA-F]+;", " ", t)
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", t):
        raw = m.group(0).rstrip(",")
        if not raw.replace(",", "").replace(".", "").isdigit():
            continue
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        ctx = t[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
        yield val, raw, ctx


def _collect_numbers(node, acc):
    """Walk the pack collecting every numeric value + list lengths."""
    if isinstance(node, dict):
        for v in node.values():
            _collect_numbers(v, acc)
    elif isinstance(node, list):
        acc.add(len(node))
        for v in node:
            _collect_numbers(v, acc)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        acc.add(float(node))
    elif isinstance(node, str):
        # Collect numbers embedded in strings too (e.g. "Dividend - Rs 3.65
        # Per Share" in a corporate-action subject), so a report that quotes a
        # dividend amount passes the lock instead of being flagged.
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", node):
            try:
                acc.add(float(m.group(0).replace(",", "")))
            except ValueError:
                pass


# Words that mark a technical level; numbers next to them must be actual
# option-chain strikes / max pain / ATM from the pack (targets the classic
# failure of inventing round support/resistance levels).
LEVEL_LABELS = ("support", "resistance", "max pain", "pivot", "atm",
                "at-the-money", "strike")


def _levels_lock(html, pack):
    """Every round number adjacent to a level label must be an actual
    option-chain level from the datapack."""
    on = pack.get("derived", {}).get("options_NIFTY", {})
    ob = pack.get("derived", {}).get("options_BANKNIFTY", {})
    allowed = set()
    for o in (on, ob):
        for k in ("max_put_oi_strike", "max_call_oi_strike", "max_pain",
                  "atm_strike"):
            v = o.get(k)
            if isinstance(v, (int, float)):
                allowed.add(float(v))
    if not allowed:
        return []
    t = _strip_markup(html)
    low = t.lower()
    issues = []
    seen = set()
    for label in LEVEL_LABELS:
        for m in re.finditer(r"\b" + re.escape(label) + r"\b", low):
            a, b = m.start(), m.end()
            win = t[max(0, a - 50):b + 50]
            for nm in re.finditer(r"\d[\d,]*(?:\.\d+)?", win):
                raw = nm.group(0).rstrip(",")
                try:
                    val = float(raw.replace(",", ""))
                except ValueError:
                    continue
                if val < 1000 or val != int(val) or val % 50 != 0:
                    continue  # only round strike-scale numbers
                key = (label, raw)
                if key in seen:
                    continue
                seen.add(key)
                if not any(abs(val - w) <= 0.001 * max(val, abs(w), 0.5)
                           for w in allowed):
                    issues.append(
                        f"level '{label}' cites unverified level '{raw}' "
                        f"(\"...{win.strip()}...\")")
    return issues


def _named_close_lock(html, pack):
    """A number written as an index's close must match that index's close
    (catches e.g. 'Bank Nifty closed at 58,000' hiding near another index)."""
    idx = pack.get("derived", {}).get("indices", {})
    gm = pack.get("derived", {}).get("global_markets", {}).get("markets", {})

    def close_of(name):
        v = idx.get(name, {}).get("close")
        return float(v) if isinstance(v, (int, float)) else None

    named = [
        ("bank nifty", close_of("Nifty Bank")),
        ("nifty 50", close_of("Nifty 50")),
        ("nifty next 50", close_of("Nifty Next 50")),
        ("midcap 150", close_of("Nifty Midcap 150")),
        ("smallcap 250", close_of("Nifty Smallcap 250")),
        ("sensex", (gm.get("Sensex") or {}).get("level")),
    ]
    t = _strip_markup(html)
    low = t.lower()
    verb = (r"(?:clos(?:ed|es|ing)?(?:\s+(?:at|above|below|near|around))?"
            r"|ended(?:\s+at)?|settled(?:\s+at)?)")
    issues = []
    seen = set()
    for label, expected in named:
        if expected is None:
            continue
        pat = (r"\b" + re.escape(label) + r"\b[^0-9]{0,60}?" + verb +
               r"[^0-9]{0,12}?(\d[\d,]*(?:\.\d+)?)")
        for m in re.finditer(pat, low):
            raw = m.group(1).rstrip(",")
            try:
                val = float(raw.replace(",", ""))
            except ValueError:
                continue
            if val < 1000:        # points-move / change figures, not closes
                continue
            if (label, raw) in seen:
                continue
            seen.add((label, raw))
            # 0.05%: close values are copied from the JSON, so anything
            # beyond rounding-to-nearest-100 is a different (e.g. prior-day)
            # number and must fail.
            if abs(val - expected) > 0.0005 * max(val, expected):
                ctx = t[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")
                issues.append(
                    f"'{label}' close stated as '{raw}' but datapack close is "
                    f"{expected:,.2f} (\"...{ctx.strip()}...\")")
    return issues


def number_lock(html, pack):
    """Return a list of violation strings; empty means every numeral is
    traceable to the datapack (or an allowed constant/count/year)."""
    wl = set(RULE_CONSTANTS)
    d = pack.get("derived", {})
    indices = d.get("indices", {})
    for name, val in indices.items():
        if name in MAIN_INDEX_NAMES or name in SECTORAL_NAMES:
            _collect_numbers(val, wl)          # OHLC + pts + pct
            for m in re.findall(r"\d+", name):  # "Nifty Smallcap 250" -> 250
                wl.add(float(m))
    wl.add(len(indices))                       # e.g. "164 indices"
    for key, val in d.items():
        if key == "indices":
            continue
        _collect_numbers(val, wl)
    _collect_numbers(pack.get("data", {}), wl)
    # Global-market entries carry level + prev_close but NOT the points change,
    # which the report legitimately writes as "down 183.15 points". Add that
    # derivation (and the reverse) so it is not misread as an invented number.
    for mk in d.get("global_markets", {}).get("markets", {}).values():
        lvl, prev = mk.get("level"), mk.get("prev_close")
        if isinstance(lvl, (int, float)) and isinstance(prev, (int, float)):
            wl.add(float(lvl) - float(prev))
            wl.add(float(prev) - float(lvl))
    # The report sometimes writes "Total OI" as call + put OI; that sum is
    # legitimately derivable from two adjacent pack values, so allow it.
    for key in ("options_NIFTY", "options_BANKNIFTY"):
        o = d.get(key, {})
        if o.get("total_call_oi") and o.get("total_put_oi"):
            wl.add(float(o["total_call_oi"]) + float(o["total_put_oi"]))
    issues = []
    for val, raw, ctx in _extract_numbers(html):
        if val == int(val) and 0 <= val <= 99:       # counts, sections, times
            continue
        if val == int(val) and 1900 <= val <= 2100:  # years
            continue
        if any(_within(val, w) for w in wl):
            continue
        issues.append(f"unverified number '{raw}' (\"...{ctx.strip()}...\")")
    issues += _levels_lock(html, pack)
    issues += _named_close_lock(html, pack)
    # dedupe while preserving order
    out, seen = [], set()
    for i in issues:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


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

    if re.search(r"[A-Za-z] - (?!Rs\b|Re\b|Bonus\b|Rights\b|Split\b)", text):
        issues.append("spaced hyphen ' - ' used as a connector")

    if re.search(r"~\s*\d", text) or re.search(r"\d\s*~", text):
        issues.append("'~' adjacent to a numeral (no estimated figures)")

    if re.search(r"\b(?:est\.|approx\.)\s*\d", text, re.I):
        issues.append("'est.'/'approx.' adjacent to a numeral")

    low = text.lower()
    for w in ADVICE_LEXICON:
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            issues.append(f"advice lexicon: '{w}'")

    issues += _false_registration_issues(low)

    if kind == "report":
        if not re.search(r"not investment advice", low):
            issues.append("missing 'Not investment advice' disclaimer in body")

    # A markdown code fence around the document renders as literal "```html"
    # text in the PDF. pipeline.strip_code_fence() removes the wrapping case;
    # this catches any fence that survives (e.g. mid-document).
    if "```" in html:
        issues.append("markdown code fence '```' in output - return raw HTML "
                      "only, with no fence")

    return issues
