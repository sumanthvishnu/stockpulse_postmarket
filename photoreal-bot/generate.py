"""Z-Image-Turbo img2img worker. Loaded once, then reused for every Telegram job."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Iterable

import torch
from PIL import Image

from safety import PromptBlocked, assert_adult_prompt

log = logging.getLogger("photoreal")

MODEL_ID = os.environ.get("MODEL_ID", "Tongyi-MAI/Z-Image-Turbo")
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


def _patch_diffusers_nn() -> None:
    """Some diffusers builds use `nn.*` in lora_pipeline.py without importing nn."""
    try:
        import diffusers

        path = os.path.join(os.path.dirname(diffusers.__file__), "loaders", "lora_pipeline.py")
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "from torch import nn" in text:
            return
        if "import torch" not in text:
            return
        text = text.replace("import torch\n", "import torch\nfrom torch import nn\n", 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        log.info("Patched diffusers lora_pipeline.py missing `nn` import")
    except Exception:
        log.exception("Could not patch diffusers nn import")


@lru_cache(maxsize=1)
def load_pipeline():
    """First call downloads ~12–20 GB onto the RunPod volume, then reuses it."""
    if os.path.isdir("/runpod-volume"):
        os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface")
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", "/runpod-volume/huggingface")

    _patch_diffusers_nn()
    try:
        from diffusers import ZImageImg2ImgPipeline
    except Exception as exc:
        raise RuntimeError(f"Could not load Z-Image pipeline: {exc}") from exc

    if not torch.cuda.is_available():
        raise RuntimeError("No NVIDIA GPU visible on this worker.")

    dtype = torch.bfloat16
    log.info("Loading %s on %s ...", MODEL_ID, torch.cuda.get_device_name(0))
    pipe = ZImageImg2ImgPipeline.from_pretrained(MODEL_ID, torch_dtype=dtype)
    pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)

    if LORA_PATH:
        log.info("Loading LoRA %s", LORA_PATH)
        pipe.load_lora_weights(LORA_PATH)

    log.info("Pipeline ready")
    return pipe


def generate_batch(
    image: Image.Image,
    prompt: str,
    extra: str = "",
    strength: float = 0.58,
    count: int = 4,
    seed: int | None = None,
) -> list[Image.Image]:
    assert_adult_prompt(f"{prompt} {extra}")
    full = prompt.strip()
    if extra.strip():
        full = f"{full}. {extra.strip()}"

    init = fit_size(image)
    pipe = load_pipeline()
    strength = min(0.95, max(0.25, float(strength)))
    count = min(8, max(1, int(count)))

    if seed is None:
        seed = int.from_bytes(os.urandom(4), "little")

    out: list[Image.Image] = []
    for i in range(count):
        g = torch.Generator(device="cuda").manual_seed(seed + i)
        result = pipe(
            prompt=full,
            image=init,
            strength=strength,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE,
            generator=g,
        ).images[0]
        out.append(result)
        log.info("Generated %s/%s seed=%s", i + 1, count, seed + i)
    return out


def jpeg_batch(images: Iterable[Image.Image]) -> list[bytes]:
    return [image_to_jpeg_bytes(im) for im in images]
