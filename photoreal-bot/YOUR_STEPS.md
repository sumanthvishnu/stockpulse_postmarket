# What you do (one time, then just Telegram)

You will **not** rent a GPU each session. You will **not** pick PyTorch, wait for a blue Open button, or Destroy anything.

Do these **four things once**. After that, open Telegram whenever you want images.

You need:

1. Telegram
2. A [RunPod](https://www.runpod.io) account (pays the GPU **only while it generates**)
3. A [Railway](https://railway.app) account (keeps the bot awake, usually a few dollars a month)

---

## 1. Telegram — 3 minutes

1. Open Telegram → search **`BotFather`** (blue check) → `/newbot`.
2. Give it a name, then a username ending in `bot`.
3. Copy the **token** (`123456:AAH...`). Keep it private.
4. Search **`userinfobot`** → Start → copy your **Id** number.

---

## 2. RunPod — the GPU that wakes on its own

1. Sign up at [https://www.runpod.io](https://www.runpod.io) and add **$10** credit. Leave auto-pay off if you can.
2. Top-right **Settings** (or user menu) → **API Keys** → create a key → **copy it**.
3. Left menu **Storage** → **Network Volume** → create:
   - Name: `photoreal`
   - Size: **50 GB**
   - Region: pick one that has GPUs (US is fine). Remember the region.
4. Left menu **Serverless** → **New Endpoint** → **Import Git Repository**.
   - Connect GitHub if asked.
   - Repo: `sumanthvishnu/stockpulse_postmarket`
   - Branch: `arena/01a068be-stockpulse-postmarket`
   - **Dockerfile path:** `photoreal-bot/worker/Dockerfile`
5. On the endpoint form, set:
   - Name: `photoreal`
   - GPU: a **24 GB** card (RTX 4090, RTX 3090, or A5000)
   - **Max workers:** 1
   - **Min workers:** 0   ← this is “sleep when I’m not using it”
   - **Idle timeout:** 60 seconds
   - **FlashBoot:** on
   - **Execution timeout:** 1200 seconds
   - **Network volume:** the `photoreal` volume from step 3 (same region)
6. Click **Deploy**.
7. Open the endpoint. Copy the **Endpoint ID** (a short id on that page).

The first GitHub build can take 10–20 minutes. Wait until the endpoint shows it is ready / the build succeeded. You do this **once**.

---

## 3. Railway — keeps the Telegram bot awake

The GPU sleeps. Something still has to *listen* to Telegram. That’s Railway.

1. Sign up at [https://railway.app](https://railway.app) with **GitHub**.
2. **New Project** → **Deploy from GitHub repo** → `stockpulse_postmarket`.
3. Settings:
   - **Branch:** `arena/01a068be-stockpulse-postmarket`
   - **Root directory:** `photoreal-bot`
4. **Variables** (add these four):

   | Name | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | token from BotFather |
   | `ALLOWED_USER_ID` | number from userinfobot |
   | `RUNPOD_API_KEY` | key from RunPod |
   | `RUNPOD_ENDPOINT_ID` | endpoint id from RunPod |

5. Deploy. Wait until the service is **Running**.

If Railway asks for a start command, use: `python bot.py`

That’s the last setup screen you should ever need.

---

## 4. Use it

1. In Telegram, open **your** bot → Start.
2. Send **up to 10 photos as one album**.
3. Tap a preset.
4. Wait. Results come back as an album.

After this, you never open RunPod or Railway unless something breaks.

### What waiting feels like

| When | Wait |
|---|---|
| **Very first photo ever** | 10–20 min once (model downloads onto your volume). Send **one** test photo, leave it. |
| First photo after you’ve been away | about **1 minute** (GPU waking up) |
| More photos in the same session | usually **30 seconds–3 minutes** for a batch of 10 |

You do **not** Destroy anything. The GPU goes to sleep by itself about a minute after it finishes.

---

## Money

| Thing | Typical |
|---|---|
| RunPod credit to start | $10 |
| GPU while generating | a few cents per batch |
| GPU while you sleep / work | **$0** (min workers = 0) |
| Railway to keep the bot online | free trial, then ~$5/month if they require a hobby plan |

If you forget the bot for a month, you should only see Railway’s small monthly fee, not GPU time.

---

## If it doesn’t answer

- Bot ignores you → `ALLOWED_USER_ID` is not the number from `@userinfobot`. Fix the Railway variable, redeploy.
- “Waking the GPU” forever → RunPod endpoint build failed, or volume not attached. Open RunPod → Serverless → that endpoint → **Logs**.
- First photo errors after 2 minutes → it is still downloading the model. Wait and send **one** photo again.
- Railway service crashed → open Railway logs; usually a typo in one of the four variables.

You should never need a Linux terminal, PyTorch, or a blue Open button.
