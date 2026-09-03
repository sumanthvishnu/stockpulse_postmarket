# What you need to do

Do these in order. The bot code is already in this folder.
You only create a Telegram bot, add a little GPU credit, and paste two values.

You do **not** need a GPU at home. You do **not** need to train a model.

---

## Step 1 — Create the Telegram bot (3 minutes, free)

1. Open Telegram.
2. Search **`@BotFather`** and open it (blue checkmark).
3. Send `/newbot`.
4. Name: anything, e.g. `My Photo Bot`.
5. Username: must end in `bot`, e.g. `myphoto_gen_bot`.
6. BotFather replies with a **token**. It looks like:
   `123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxx`
7. Copy the whole token and keep it private. That token **is** the bot.

## Step 2 — Get your Telegram user id (1 minute, free)

This locks the bot so **only you** can use it.

1. In Telegram, search **`@userinfobot`** and tap Start.
2. It replies with `Id: 123456789`.
3. Copy the number. That is your user id.

## Step 3 — Add GPU credit (5 minutes, about $5)

You rent a GPU only while you generate, then you delete it.

1. Sign up at [https://cloud.vast.ai](https://cloud.vast.ai) (cheapest)  
   Backup option: [https://www.runpod.io](https://www.runpod.io)
2. Add **$5 to $10** in credits.
3. **Do not** turn on auto-billing / auto-pay.
4. Stop here until you want to generate. Credit just sits there.

First evening of use is usually well under $1 if you destroy the machine when you are done.

## Step 4 — Each time you want to generate

### 4a. Rent the GPU

On Vast.ai:

1. Open **Templates** → pick a plain **PyTorch** template (CUDA 12.x).
2. Open **Search / Create**.
3. Filters:
   - GPU: **RTX 3090** (24 GB)
   - Disk: **80 GB or more** (the model is large)
   - Reliability: **0.95+** if you can
   - Type: **On-demand** (not interruptible) for your first try
   - Price: about **$0.12–0.25 / hr** is fine
4. Click **Rent**.
5. Wait until the instance is running (often under a minute). If it sits there more than ~2 minutes, destroy it and rent another host.

### 4b. Open a terminal on that machine

On the instance row, open **Terminal** (or Jupyter → Terminal). You should get a Linux prompt.

### 4c. Install and start the bot (copy-paste)

First time on a **new** machine (downloads the model, 10–20 minutes):

```bash
git clone --branch arena/01a068be-stockpulse-postmarket --single-branch https://github.com/sumanthvishnu/stockpulse_postmarket.git
cd stockpulse_postmarket/photoreal-bot
bash scripts/setup_pod.sh
```

It will ask for:

1. **Telegram bot token** (from Step 1)
2. **Your user id** (from Step 2)

Then it downloads **Z-Image-Turbo** and starts the bot. Leave this terminal open.

When the terminal prints `Bot is ready`, go to Telegram, open **your** bot, tap Start, send a **photo**.

### 4d. When you are done — this matters

On Vast: **Destroy** the instance (not just Stop).

- **Destroy** = billing for the GPU stops.
- **Stop** can still charge for disk.

If you forget this, it keeps charging by the hour.

## Step 5 — Optional, saves 15 minutes next time

After the bot works once, on Vast use **Save as template** (or snapshot) on that instance **before** you destroy it.

Next session: rent from **your** template instead of a blank PyTorch image. The model is already there, so startup is a couple of minutes, not 20.

---

## How to use the bot

1. Send a **photo** of an adult (clear face, decent light).
2. Optional: write a caption on the photo (`red dress, hotel window, night`).
3. Tap a **preset**.
4. Wait. You get a batch of 4 photoreal images back as an album.
5. Buttons under the result: keep likeness / restyle / again / batch of 8.

Default is photo-to-image (Jork-style): same person, new scene/look.

---

## Money / time cheat sheet

| What | Typical |
|---|---|
| Vast minimum top-up | $5 |
| RTX 3090 | ~$0.12–0.22 per hour |
| First boot (download model) | 10–20 min, a few cents |
| Later boots from your template | 2–4 min |
| One batch of 4 images | about 30–90 seconds |
| An evening of generating | usually well under $1 |
| Leave the pod running overnight | **don't** — destroy it |

---

## If something breaks

- Bot ignores you → user id in `.env` does not match `@userinfobot`.
- `No GPU` in the terminal → you rented a CPU-only box. Destroy and rent an **RTX 3090**.
- Instance never opens → dud host. Destroy, rent a different one.
- Telegram says bot stopped → the terminal/pod died. Start the pod again.
- You got charged after you finished → instance was Stopped, not Destroyed.

You should never need to edit Python. Token + user id + rent/destroy the 3090 is the whole job from your side.
