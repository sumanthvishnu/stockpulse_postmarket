#!/usr/bin/env python3
"""Trendlyne MCP client (streamable HTTP, JSON-RPC 2.0).

The pipeline is not an MCP host, so we speak to the server directly. The
endpoint sits behind UA-filtering and a redirect, hence the browser UA and
redirect-following. Token comes from TRENDLYNE_MCP_TOKEN (GitHub secret);
if unset, every function degrades to None and the caller logs a gap.
"""
import json
import os
import time

import requests

MCP_URL = "https://mcp.trendlyne.com/mcp/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def _endpoint():
    tok = (os.environ.get("TRENDLYNE_MCP_TOKEN") or "").strip()
    return (MCP_URL + "?token=" + tok) if tok else None


def call(tool, arguments, timeout=120):
    """One tools/call round-trip. Returns the result text, or None on any
    failure (transport, WAF, tool error). Caller decides how to log the gap."""
    url = _endpoint()
    if not url:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    try:
        r = requests.post(url, json=payload, timeout=timeout,
                          allow_redirects=True,
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json, text/event-stream",
                                   "User-Agent": UA})
        if r.status_code != 200:
            return None
        body = r.text
        if "data:" in body:  # SSE framing
            body = next(l[5:].strip() for l in body.splitlines()
                        if l.startswith("data:"))
        msg = json.loads(body)
        if "error" in msg:
            return None
        content = (msg.get("result") or {}).get("content") or []
        return "\n".join(c.get("text", "") for c in content
                         if c.get("type") == "text") or None
    except Exception:  # noqa: BLE001 - enrichment must never break the run
        return None


def available():
    url = _endpoint()
    if not url:
        return False
    try:
        r = requests.post(url, timeout=30, allow_redirects=True,
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json, text/event-stream",
                                   "User-Agent": UA},
                          json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-03-26",
                                           "capabilities": {},
                                           "clientInfo": {"name": "stockpulse",
                                                          "version": "1.0"}}})
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- parsers --
def parse_kv_table(text, section):
    """Trendlyne answers are pipe-labelled plain text. Extract a section's
    'key: value' pairs loosely; callers pick what they need and tolerate
    missing keys."""
    if not text:
        return {}
    out = {}
    grab = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(section + ":"):
            grab = True
            continue
        if grab and s and not s.startswith(" ") and s.endswith(":"):
            break
        if grab and ":" in s:
            k, _, v = s.partition(":")
            out[k.strip()] = v.strip()
    return out


def parse_pivots(text):
    """pivotData block from a 'technical' call -> float levels."""
    if not text:
        return None
    sec = parse_kv_table(text, "pivotData")
    if not sec:
        # fallback: regex the raw text
        import re
        sec = {}
        for m in re.finditer(r"(pivotPoint|firstResistanceR1|firstSupportS1|"
                             r"secondResistanceR2|secondSupportS2|"
                             r"thirdResistanceR3|thirdSupportS3):\s*([\d.]+)",
                             text):
            sec[m.group(1)] = m.group(2)
    def f(k):
        try:
            return float(sec.get(k, ""))
        except (TypeError, ValueError):
            return None
    piv = {"pivot": f("pivotPoint"), "r1": f("firstResistanceR1"),
           "s1": f("firstSupportS1"), "r2": f("secondResistanceR2"),
           "s2": f("secondSupportS2"), "r3": f("thirdResistanceR3"),
           "s3": f("thirdSupportS3")}
    return piv if piv["pivot"] is not None else None


def parse_rsi(text):
    import re
    m = re.search(r"Relative Strength Index\s*\|\s*([\d.]+)", text or "")
    return float(m.group(1)) if m else None


def parse_sma_insight(text):
    import re
    m = re.search(r"insight:\s*(.+?)\n\s*insightColor", text or "", re.S)
    return m.group(1).strip() if m else None


def parse_price(text):
    """Latest traded level from an overview/technical payload."""
    import re
    for pat in (r"currentPrice\s*\|\s*([\d,]+(?:\.\d+)?)",
                r"\"current_price\":\s*([\d.]+)",
                r"lastPrice\s*[:|]\s*([\d,]+(?:\.\d+)?)"):
        m = re.search(pat, text or "")
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def parse_news(text, max_items=3):
    """news feed -> [{title, pubDate, source}] newest first."""
    if not text or "newsList:" not in text:
        return []
    items = []
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.strip().startswith("NSEcode |")), None)
    if start is None:
        return []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s or s.endswith(":") and "|" not in s:
            if items:
                break
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) < 18:
            continue
        try:
            items.append({"title": parts[16], "pubDate": parts[15],
                          "source": parts[23] if len(parts) > 23 else ""})
        except IndexError:
            continue
        if len(items) >= max_items:
            break
    return items


def polite_pause(seconds=0.8):
    time.sleep(seconds)   # MCP endpoint is a paid API; don't hammer it
