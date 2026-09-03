#!/usr/bin/env bash
# First-time (or new machine) setup on a Vast/RunPod GPU box.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export HF_HUB_ENABLE_HF_TRANSFER=1
export PYTHONUNBUFFERED=1

python3 -m pip install -U pip
# Do NOT pip-install torch from PyPI — the Vast/RunPod PyTorch image already has CUDA torch.
python3 -m pip install -r requirements.txt

python3 - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit(
        "No GPU found. Destroy this instance and rent an RTX 3090 PyTorch template."
    )
print("GPU:", torch.cuda.get_device_name(0), "VRAM", round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1), "GB")
PY

if [ ! -f .env ]; then
  echo
  echo "Paste the Telegram bot token from @BotFather, then Enter:"
  read -r TOKEN
  echo "Paste your numeric user id from @userinfobot, then Enter:"
  read -r UID
  cat > .env <<EOF
TELEGRAM_BOT_TOKEN=$TOKEN
ALLOWED_USER_ID=$UID
EOF
  echo "Wrote .env"
fi

echo
echo "Starting the bot. First launch downloads Z-Image-Turbo (~12–20 GB)."
echo "Leave this terminal open. When you see 'Bot is ready', send a photo in Telegram."
echo
exec python3 bot.py
