"""Photoreal img2img worker. Prefers Z-Image-Turbo; falls back to SDXL."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Iterable

import builtins

import torch
import torch.nn as nn
from PIL import Image

builtins.torch = torch
builtins.nn = nn

from safety import PromptBlocked, assert_adult_prompt

log = logging.getLogger("photoreal")

MODEL_ID = os.environ.get("MODEL_ID", "Tongyi-MAI/Z-Image-Turbo")
FALLBACK_MODEL_ID = os.environ.get(
    "FALLBACK_MODEL_ID", "stabilityai/sdxl-turbo"
)
LORA_PATH = os.environ.get("NSFW_LORA_PATH", "").strip()
STEPS = int(os.environ.get("INFER_STEPS", "9"))
GUIDANCE = float(os.environ.get("GUIDANCE_SCALE", "0.0"))
MAX_SIDE = int(os.environ.get("MAX_SIDE", "1024"))


def fit_size(image: Image.Image, max_side: int = MAX_SIDE, multiple: int = 16) -> Image.Image:
    image = image.convert("RGB")
    w, h = image.size
    scale = max_side / max(w, h)
    if scale < 1:
        w, h = int(w * scale), int(h * scale)
    w = max(multiple, (w // multiple) * multiple)
    h = max(multiple, (h // multiple) * multiple)
    if image.size != (w, h):
        image = image.resize((w, h), Image.Resampling.LANCZOS)
    return image


def image_from_bytes(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGB")


def image_to_jpeg_bytes(image: Image.Image, quality: int = 92) -> bytes:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _load_zimage(dtype):
    from diffusers import ZImageImg2ImgPipeline

    pipe = ZImageImg2ImgPipeline.from_pretrained(MODEL_ID, torch_dtype=dtype)
    pipe._photoreal_kind = "zimage"
    return pipe


def _load_sdxl(dtype):
    from diffusers import AutoPipelineForImage2Image

    pipe = AutoPipelineForImage2Image.from_pretrained(
        FALLBACK_MODEL_ID,
        torch_dtype=dtype,
        variant="fp16",
        use_safetensors=True,
    )
    pipe._photoreal_kind = "sdxl"
    return pipe


@lru_cache(maxsize=1)
def load_pipeline():
    """First call downloads weights onto the RunPod volume, then reuses them."""
    if os.path.isdir("/runpod-volume"):
        os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface")
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/runpod-volume/huggingface")

    try:
        from attn_stub import disable_broken_attn

        disable_broken_attn()
    except Exception:
        log.exception("attn stub failed")

    if not torch.cuda.is_available():
        raise RuntimeError("No NVIDIA GPU visible on this worker.")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    log.info("Loading model on %s ...", torch.cuda.get_device_name(0))

    try:
        pipe = _load_zimage(dtype)
        log.info("Loaded Z-Image-Turbo")
    except Exception:
        log.exception("Z-Image failed; using SDXL img2img fallback")
        dtype = torch.float16
        pipe = _load_sdxl(dtype)
        log.info("Loaded fallback %s", FALLBACK_MODEL_ID)

    pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    if LORA_PATH:
        try:
            pipe.load_lora_weights(LORA_PATH)
        except Exception:
            log.exception("LoRA load failed")
    log.info("Pipeline ready (%s)", getattr(pipe, "_photoreal_kind", "?"))
    return pipe


IDENTITY_LOCK = (
    "Keep the exact same person as the uploaded photograph: same face, "
    "same facial structure, same eyes nose and mouth, same ethnicity, "
    "same age, same skin tone, same gender. Do not replace the person. "
    "Do not default to a different ethnicity or a Chinese/East Asian face "
    "unless that is who is in the photo."
)


def generate_batch(
    image: Image.Image,
    prompt: str,
    extra: str = "",
    strength: float = 0.58,
    count: int = 4,
    seed: int | None = None,
) -> list[Image.Image]:
    assert_adult_prompt(f"{prompt} {extra}")
    full = f"{IDENTITY_LOCK} {prompt.strip()}"
    if extra.strip():
        full = f"{full}. {extra.strip()}"

    init = fit_size(image)
    pipe = load_pipeline()
    # High denoise lets Z-Image redraw the face as its Chinese prior.
    strength = min(0.55, max(0.22, float(strength)))
    count = min(8, max(1, int(count)))
    kind = getattr(pipe, "_photoreal_kind", "zimage")
    if kind == "sdxl":
        steps = int(os.environ.get("SDXL_STEPS", "6"))
        guidance = float(os.environ.get("SDXL_GUIDANCE", "0.0"))
    else:
        steps = STEPS
        guidance = GUIDANCE

    if seed is None:
        seed = int.from_bytes(os.urandom(4), "little")

    out: list[Image.Image] = []
    for i in range(count):
        g = torch.Generator(device="cuda").manual_seed(seed + i)
        result = pipe(
            prompt=full,
            image=init,
            strength=strength,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=g,
        ).images[0]
        out.append(result)
        log.info("Generated %s/%s seed=%s kind=%s", i + 1, count, seed + i, kind)
    return out


def jpeg_batch(images: Iterable[Image.Image]) -> list[bytes]:
    return [image_to_jpeg_bytes(im) for im in images]
