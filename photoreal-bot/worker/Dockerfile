# Built by RunPod from GitHub. Context = repo root.
# Dockerfile path in the console: photoreal-bot/worker/Dockerfile
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

ENV HF_HUB_ENABLE_HF_TRANSFER=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/runpod-volume/huggingface \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/huggingface \
    FLASH_ATTENTION_DISABLED=1

COPY photoreal-bot/worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip uninstall -y flash-attn flash_attn sageattention sageattn 2>/dev/null || true

COPY photoreal-bot/generate.py photoreal-bot/safety.py photoreal-bot/presets.py photoreal-bot/attn_stub.py /app/
COPY photoreal-bot/worker/handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
