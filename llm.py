#!/usr/bin/env python3
"""Minimal LLM client over any OpenAI-compatible /chat/completions endpoint.

Defaults to OpenAI, but the base URL + model are env-swappable, so Kimi
(Moonshot), DeepSeek, Groq or any OpenAI-compatible API drops in later with
zero code changes:

    LLM_BASE_URL=https://api.moonshot.ai/v1   LLM_MODEL=kimi-k2-...   # later
"""
import os
import re
import time

import requests


def _retry_after_seconds(r):
    """Best-effort wait time from an HTTP 429 (rate limit) response.

    OpenAI's per-minute token budget (TPM) resets each minute and the error
    body carries the exact wait ("Please try again in 38.738s"); some
    providers send a Retry-After header instead. Capped so a run can never
    hang for long.
    """
    ra = r.headers.get("Retry-After")
    if ra:
        try:
            return min(max(float(ra), 5.0), 90.0)
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)\s*s", r.text)
    if m:
        return min(max(float(m.group(1)) + 2.0, 10.0), 90.0)
    return 45.0


def chat(system, user, max_tokens=12000, temperature=0.3, attempts=3,
         model=None):
    # Empty-string env vars (an unset GitHub secret is injected as "") must
    # fall back to defaults, else the URL becomes "/chat/completions".
    base = (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    # A caller (e.g. the carousel prose pass) can pin a stronger model via
    # LLM_MODEL_CAROUSEL without touching the report model. Default is gpt-4o:
    # the report/carousel copy is brand-facing, so quality beats the ~20x cost
    # delta of mini at this volume (one report + one carousel per day). Set
    # LLM_MODEL=gpt-4o-mini in the workflow to downgrade later.
    model = (model or os.environ.get("LLM_MODEL") or "gpt-4o")
    key = ((os.environ.get("OPENAI_API_KEY") or "").strip()
           or (os.environ.get("LLM_API_KEY") or "").strip())
    if not key:
        raise RuntimeError(
            "no API key: set OPENAI_API_KEY (or LLM_API_KEY) in the environment")

    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last = "unknown"
    rate_waits = 0
    i = 0
    while i < attempts:
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=600)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429 and rate_waits < 3:
                # Per-minute token budget (TPM) exhausted. The window resets
                # within a minute, so wait the server-specified time and
                # retry WITHOUT consuming a content attempt. Instant retries
                # all land in the same window and fail identically (this is
                # what made the carousel stage lose all 3 retries to 429s).
                rate_waits += 1
                wait = _retry_after_seconds(r)
                print(f"  [llm] rate-limited (429); waiting {wait:.0f}s for "
                      f"the per-minute window to reset "
                      f"(wait {rate_waits}/3)", flush=True)
                time.sleep(wait)
                continue
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        i += 1
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"LLM call failed after {attempts} attempts: {last}")
