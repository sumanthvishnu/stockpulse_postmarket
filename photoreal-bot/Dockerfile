# Always-on Telegram bot (no GPU). Deploy this on Railway.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py runpod_client.py safety.py presets.py ./

CMD ["python", "-u", "bot.py"]
