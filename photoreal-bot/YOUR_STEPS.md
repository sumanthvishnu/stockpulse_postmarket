# What you do (beginner walkthrough)

You are **renting a computer with a graphics card in the cloud** for an hour or two.  
That rented computer runs the bot. Telegram is only the remote control.

Do **A → B → C → D** in order.  
A is once. B–D you repeat every time you want images.

You do **not** need a GPU at home. You do **not** install Python on your laptop.

---

# A. Do this once (about 10 minutes)

## A1. Create your Telegram bot

1. Open **Telegram** on your phone or computer.
2. In the search bar, type **`BotFather`**.
3. Open **BotFather** with the **blue checkmark**.
4. Tap **Start** if needed, then type `/newbot` and send it.
5. It asks for a **name**. Type anything, e.g. `My Photo Bot`, and send.
6. It asks for a **username**. Must end with `bot`, e.g. `myphoto_gen_bot`. If taken, try another.
7. BotFather replies with a long **token**. It looks like:
   `8123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxx`
8. Copy that whole token into Notes. **Do not share it.** Anyone with it controls your bot.

Keep Telegram open. You will come back to this bot later.

## A2. Get your Telegram user id

This makes the bot answer **only you**.

1. In Telegram search, type **`userinfobot`**.
2. Open it and tap **Start**.
3. It replies with something like `Id: 123456789`.
4. Copy **only the number**. That is your user id.

You now have two pieces of paper:

- bot token (long, has a colon)
- user id (only digits)

## A3. Put money on Vast.ai (the GPU shop)

Think of Vast like a vending machine for graphics cards. You add credit first, then rent.

1. On your **computer browser** (easier than phone), open [https://cloud.vast.ai](https://cloud.vast.ai)
2. Sign up (Google / email is fine).
3. Open **Billing** / **Add Credit**.
4. Add **$5 to $10**. That is plenty.
5. If you see **auto-pay / auto-billing**, leave it **OFF**.
6. Confirm the balance shows a few dollars. Stop. Do not rent anything yet.

If a card is declined, try [RunPod](https://www.runpod.io) instead and tell me — the idea is the same, buttons have different names.

---

# B. Each time you want to generate — rent the GPU

You will do this every session. First time is the slowest.

## B1. Pick the software (template)

A **template** = the operating system on the rental PC. We want **PyTorch** (it already has the GPU drivers).

1. On Vast, click **Templates** in the left menu.  
   Direct link: [https://cloud.vast.ai/templates/](https://cloud.vast.ai/templates/)
2. In the search box, type **`pytorch`**.
3. Pick a **plain PyTorch** template (CUDA 12.x if you see it).  
   Do **not** pick ComfyUI / Automatic1111 / video templates for this first run.
4. On that template card, click the **Play** button (bottom of the card).

You are now on a list of **offers** — people renting out their GPUs.

## B2. Filter the list so you don’t pick the wrong machine

On the offers page:

1. At the top / left filters, set:
   - **GPU:** `RTX 3090` (24 GB). If 3090 is missing, `RTX 4090` is fine, a bit more expensive.
   - **Disk:** `80` GB or higher (the AI model is large; 16 GB disk will fail).
   - **Interruptible:** **OFF**. You want **On-demand** / uninterruptible for the first try.  
     Interruptible is cheaper but the host can kick you off mid-generation.
2. Ignore CPU, RAM, country. Don’t worry about them.
3. Look at the **$/hr** column. **$0.12 to $0.25 per hour** is a good 3090.  
   Skip anything over ~$0.40/hr unless nothing cheaper exists.
4. If you see a **reliability** number, prefer **0.95+** (95%+).

You are choosing **one row**, like picking one hotel room.

## B3. Rent it

1. On a cheap RTX 3090 row, click **RENT**.
2. If it asks disk size, set **80** (or leave 80+). Confirm.
3. Go to **Instances**: [https://cloud.vast.ai/instances/](https://cloud.vast.ai/instances/)
4. You should see **one** instance. Status will go from loading → running.
5. Wait until you see a blue **Open** button. Usually under 2 minutes.
6. If it sits there **more than 3 minutes** with no Open button:  
   trash/destroy that instance, go back, **RENT a different row**. Some hosts are duds. This is normal.

You are now paying by the hour. The clock is running. That’s OK.

## B4. Open a terminal on that machine

This is a black text window **on the rented PC**, not on your laptop.

1. Click the blue **Open** button.
2. You may land on an “Instance Portal” or Jupyter page.
3. Find **Terminal**. Common paths:
   - a **Terminal** button / icon, or
   - **Jupyter** → top menu **New** → **Terminal**
4. You should see a line like `root@xxxxx:~#` and a blinking cursor.

If you only see Jupyter notebooks and no Terminal: in Jupyter click **File → New → Terminal**.

You type in **that** window from now on, not Windows PowerShell / Mac Terminal.

## B5. Paste these three lines (first boot)

Click in the Vast terminal, paste **exactly** this, press Enter:

```bash
git clone --branch arena/01a068be-stockpulse-postmarket --single-branch https://github.com/sumanthvishnu/stockpulse_postmarket.git
cd stockpulse_postmarket/photoreal-bot
bash scripts/setup_pod.sh
```

What happens:

1. It copies the bot code.
2. It installs Python packages (a few minutes).
3. It asks: **Telegram bot token** → paste the token from A1, Enter.
4. It asks: **user id** → paste the number from A2, Enter.
5. It downloads the AI model (**10–20 minutes** the first time). Text will scroll. Let it.

When it prints **`Bot is ready`**, leave that terminal **open**. Do not close the browser tab. Closing it can kill the bot.

If it says **`No GPU`**: you rented a CPU box. Destroy it (section D) and rent an **RTX 3090** again.

---

# C. Use it in Telegram

1. In Telegram, search the **username you gave BotFather** (e.g. `myphoto_gen_bot`).
2. Open it, tap **Start**.
3. Tap the paperclip / gallery.
4. Select **up to 10 photos**, send them **together as one album** (not 10 separate messages if you can avoid it).
5. Optional: type a caption before sending, e.g. `hotel room, night, red dress`.
6. Wait until the bot says `Got 10/10 photos`.
7. Tap a **preset**.
8. It will say `Converting 1/10…` then send the results as an album.

10 photos in → 10 photos out. First batch of 10 is often **2–4 minutes**.

`/clear` empties the queue if you want to start over.

---

# D. When you are done — turn the rental OFF

This is the step people miss, and then they get billed.

1. Go back to [https://cloud.vast.ai/instances/](https://cloud.vast.ai/instances/)
2. On your instance, open the trash / **Destroy** control.  
   The exact icon is a trash can or a menu with **Destroy**.
3. Confirm **Destroy**.

| Button | What it does | Use it? |
|---|---|---|
| **Destroy** | GPU **and** disk gone. Billing stops. | **Yes. Always.** |
| Stop | GPU off, disk may still cost money | Don’t use this |
| Close browser only | Machine **keeps running and charging** | Never “just close the tab” |

Check Billing: the instance should be gone. If anything is still listed as running, destroy it.

A 2-hour session at $0.20/hr is about **40 cents**. Overnight forgotten is **several dollars**.

---

# E. Next time you want to generate

1. Vast → Templates → PyTorch → Play → RENT a 3090 again (B1–B3).
2. Open Terminal (B4).
3. If this is a **brand new** machine, run the same three lines as B5.  
   It will download the model again (10–20 min) unless you saved a template.
4. If `.env` already exists it may not ask for the token again.
5. Wait for `Bot is ready`, use Telegram, then **Destroy** (D).

Optional later (skip on day one): before Destroy, Vast has **Save as template**. That snapshot makes the next boot skip the 20-minute download. Only do this after the bot has worked once.

---

# If something feels wrong

| What you see | What to do |
|---|---|
| Bot ignores your photos | User id in setup ≠ `@userinfobot`. Destroy, rent again, paste the id carefully. |
| `No GPU` in the terminal | Not a 3090. Destroy, rent **RTX 3090**. |
| Instance never gets a blue Open button | Dud host. Destroy, rent a **different** row. |
| `Bot is ready` never appears | First download can take 20 min. If 30+ min, copy the last error lines and send them to me. |
| Telegram says bot is offline | Vast terminal closed or instance died. Open terminal, `cd stockpulse_postmarket/photoreal-bot` then `bash scripts/start.sh` |
| Still charged after you finished | Instance was Stopped, not Destroyed. Destroy it. |
| git clone asks for a password | You shouldn’t need one (repo is public). Copy the three lines again; don’t type a GitHub password. |

You should never need to edit code. From your side it is: **BotFather → user id → add $5 → rent 3090 → paste 3 lines → send album in Telegram → Destroy.**
