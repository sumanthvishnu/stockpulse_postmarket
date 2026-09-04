"""RunPod serverless handler. Loads Z-Image once per worker, converts a whole album."""

from __future__ import annotations

import base64
import logging
import os
import sys

# generate.py lives one directory up; Docker copies it next to this file.
sys.path.insert(0, os.path.dirname(__file__))

import builtins

import torch.nn as nn

builtins.nn = nn

import runpod

from generate import PromptBlocked, generate_batch, image_from_bytes, jpeg_batch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

if os.path.isdir("/runpod-volume"):
    os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface")
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/runpod-volume/huggingface")
    os.environ.setdefault("HF_HUB_CACHE", "/runpod-volume/huggingface")


def handler(event):
    inp = (event or {}).get("input") or {}
    images = inp.get("images") or []
    prompt = inp.get("prompt") or ""
    extra = inp.get("extra") or ""
    strength = float(inp.get("strength") or 0.58)
    if not images:
        return {"error": "No images in request"}

    out = []
    try:
        for i, b64 in enumerate(images, start=1):
            log.info("Converting %s/%s", i, len(images))
            raw = base64.b64decode(b64)
            image = image_from_bytes(raw)
            frames = generate_batch(
                image=image,
                prompt=prompt,
                extra=extra,
                strength=strength,
                count=1,
            )
            out.append(base64.b64encode(jpeg_batch(frames)[0]).decode("ascii"))
    except PromptBlocked as exc:
        return {"error": str(exc)}
    except Exception as exc:
        log.exception("convert failed")
        return {"error": str(exc)}
    return {"images": out}


runpod.serverless.start({"handler": handler})
