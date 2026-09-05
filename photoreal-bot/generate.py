"""Photoreal SDXL img2img worker. Z-Image is not used (East Asian face prior)."""

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

# Photoreal SDXL — not Tongyi Z-Image (that model defaults to Chinese faces).
MODEL_CANDIDATES = [
    os.environ.get("MODEL_ID", "SG161222/RealVisXL_V5.0"),
    "RunDiffusion/Juggernaut-XL-v9",
    "stabilityai/stable-diffusion-xl-base-1.0",
]
LORA_PATH = os.environ.get("NSFW_LORA_PATH", "").strip()
STEPS = int(os.environ.get("INFER_STEPS", "24"))
GUIDANCE = float(os.environ.get("GUIDANCE_SCALE", "6.0"))
MAX_SIDE = int(os.environ.get("MAX_SIDE", "1024"))
NEGATIVE = (
    "cartoon, anime, illustration, cgi, 3d render, plastic skin, "
    "deformed, extra fingers, blurry, different person, face swap"
)

IDENTITY_LOCK = (
    "Keep the exact same person as the uploaded photograph: same face, "
    "same facial structure, same eyes nose and mouth, same ethnicity, "
    "same age, same skin tone, same gender. Do not replace the person."
)


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


def _load_sdxl(model_id: str, dtype):
    from diffusers import StableDiffusionXLImg2ImgPipeline

    kwargs = dict(torch_dtype=dtype, use_safetensors=True)
    try:
        pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            model_id, variant="fp16", **kwargs
        )
    except Exception:
        pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(model_id, **kwargs)
    pipe._photoreal_kind = "sdxl"
    pipe._photoreal_model = model_id
    return pipe


@lru_cache(maxsize=1)
def load_pipeline():
    if os.path.isdir("/runpod-volume"):
        os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface")
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/runpod-volume/huggingface")

    if not torch.cuda.is_available():
        raise RuntimeError("No NVIDIA GPU visible on this worker.")

    dtype = torch.float16
    last_err = None
    seen = []
    for model_id in MODEL_CANDIDATES:
        if not model_id or model_id in seen:
            continue
        seen.append(model_id)
        try:
            log.info("Loading %s on %s ...", model_id, torch.cuda.get_device_name(0))
            pipe = _load_sdxl(model_id, dtype)
            pipe.to("cuda")
            pipe.set_progress_bar_config(disable=True)
            if LORA_PATH:
                try:
                    pipe.load_lora_weights(LORA_PATH)
                except Exception:
                    log.exception("LoRA load failed")
            log.info("Pipeline ready (%s)", model_id)
            return pipe
        except Exception as exc:
            last_err = exc
            log.exception("Failed to load %s", model_id)

    raise RuntimeError(f"Could not load any SDXL model: {last_err}") from last_err


def generate_batch(
    image: Image.Image,
    prompt: str,
    extra: str = "",
    strength: float = 0.40,
    count: int = 4,
    seed: int | None = None,
) -> list[Image.Image]:
    assert_adult_prompt(f"{prompt} {extra}")
    full = f"{IDENTITY_LOCK} {prompt.strip()}"
    if extra.strip():
        full = f"{full}. {extra.strip()}"

    init = fit_size(image)
    pipe = load_pipeline()
    strength = min(0.55, max(0.22, float(strength)))
    count = min(8, max(1, int(count)))

    if seed is None:
        seed = int.from_bytes(os.urandom(4), "little")

    out: list[Image.Image] = []
    for i in range(count):
        g = torch.Generator(device="cuda").manual_seed(seed + i)
        result = pipe(
            prompt=full,
            negative_prompt=NEGATIVE,
            image=init,
            strength=strength,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE,
            generator=g,
        ).images[0]
        out.append(result)
        log.info(
            "Generated %s/%s seed=%s model=%s",
            i + 1,
            count,
            seed + i,
            getattr(pipe, "_photoreal_model", "?"),
        )
    return out


def jpeg_batch(images: Iterable[Image.Image]) -> list[bytes]:
    return [image_to_jpeg_bytes(im) for im in images]
