#!/usr/bin/env python3
"""Minimal LLM client over any OpenAI-compatible /chat/completions endpoint.

Defaults to OpenAI, but the base URL + model are env-swappable, so Kimi
(Moonshot), DeepSeek, Groq or any OpenAI-compatible API drops in later with
zero code changes:

    LLM_BASE_URL=https://api.moonshot.ai/v1   LLM_MODEL=kimi-k2-...   # later
"""
import os
import time

import requests


def chat(system, user, max_tokens=12000, temperature=0.3, attempts=3,
         model=None):
    # Empty-string env vars (an unset GitHub secret is injected as "") must
    # fall back to defaults, else the URL becomes "/chat/completions".
    base = (os.environ.get("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    # A caller (e.g. the carousel prose pass) can pin a stronger model via
    # LLM_MODEL_CAROUSEL without touching the report model.
    model = (model or os.environ.get("LLM_MODEL") or "gpt-4o-mini")
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
    for i in range(attempts):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=600)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"LLM call failed after {attempts} attempts: {last}")
