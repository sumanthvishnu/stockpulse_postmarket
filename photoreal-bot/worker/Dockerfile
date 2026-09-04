# Built by RunPod from GitHub. Context = repo root.
# Dockerfile path in the console: photoreal-bot/worker/Dockerfile
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV HF_HUB_ENABLE_HF_TRANSFER=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/runpod-volume/huggingface \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/huggingface

COPY photoreal-bot/worker/requirements.txt /app/requirements.txt
COPY photoreal-bot/worker/patch_diffusers.py /app/patch_diffusers.py
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && python /app/patch_diffusers.py \
    && pip uninstall -y flash-attn flash_attn 2>/dev/null || true

COPY photoreal-bot/generate.py photoreal-bot/safety.py photoreal-bot/presets.py /app/
COPY photoreal-bot/worker/handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
