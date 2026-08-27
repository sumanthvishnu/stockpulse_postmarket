# StockPulse — Automated Daily Post-Market Report + Carousel

One pipeline, on a schedule, no manual steps:

```
21:00 IST (Mon-Fri, GitHub Actions cron)
  ├─ fetch NSE datapack (fixed v3.5 fetcher, 0 gaps)
  ├─ OpenAI compiles the report HTML (SEBI-compliant)  → PDF
  ├─ OpenAI builds the carousel HTML (8 slides + PNG download + captions)
  └─ Telegram message: links to the carousel + PDF, plus the PDF attached
```

You open the carousel link in your browser, review the slides, download the
PNGs, and post. Nothing is posted automatically.

---

## What's in this repo

| Path | What it is |
|---|---|
| `stockpulse_data_fetcher.py` | Fetcher v3.5 — NSE archives + derived metrics |
| `pipeline.py` | Orchestrator (fetch → LLM → lint → PDF → site → Telegram) |
| `llm.py` | OpenAI-compatible LLM client (Kimi/DeepSeek-swappable) |
| `compliance.py` | SEBI/house-style linter (spec §6) |
| `skills/report.md` | System prompt = your post-market report skill |
| `skills/carousel.md` | System prompt = your carousel skill |
| `trim_datapack.py` | Shrinks a full pack for manual Claude use |
| `.github/workflows/daily.yml` | The 9 PM IST scheduler |
| `data/` | Archived daily packs (state for ban-list diff) |
| `site/` | Rendered output, published to GitHub Pages |

---

## Setup (one time, ~10 minutes)

### 1. Create the GitHub repo
Create a new repo (e.g. `stockpulse`) on github.com, then push this folder:

```
git init
git add .
git commit -m "stockpulse pipeline"
git branch -M main
git remote add origin https://github.com/<you>/stockpulse.git
git push -u origin main
```

### 2. Enable GitHub Pages
Repo → **Settings → Pages → Source: Deploy from a branch → Branch: `gh-pages`**
(the workflow pushes the site there via `peaceiris/actions-gh-pages`).

### 3. Create the Telegram bot
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → you get
   a **token** like `123456:ABC...`.
2. Send any message to your new bot (e.g. "hi").
3. Get your chat id:
   ```
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Find `"chat":{"id": 123456789, ...}` — that number is your `TELEGRAM_CHAT_ID`.

### 4. Add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `OPENAI_API_KEY` | your OpenAI key (`sk-...`) |
| `TELEGRAM_BOT_TOKEN` | bot token from BotFather |
| `TELEGRAM_CHAT_ID` | numeric chat id from step 3 |

Optional (defaults used if unset): `LLM_BASE_URL` (default OpenAI), `LLM_MODEL`
(default `gpt-4o-mini`). For Kimi later, set `LLM_BASE_URL=https://api.moonshot.ai/v1`
and `LLM_MODEL` to a Kimi model — no code change.

### 5. Test it
Repo → **Actions → "StockPulse Daily Post-Market" → Run workflow** (leave the
date blank for today IST, or type a past date like `21-08-2026`). The first
run takes a few minutes (installs dependencies). You should get a Telegram
message with the carousel + report links.

---

## Cost & timing notes

- **Cost:** `gpt-4o-mini` on a ~60 KB pack costs roughly **Rs 0.5-1 per day**
  (well under Rs 30/month). The pack is already trimmed to ~6% of its raw size.
- **Time:** the whole run is ~2-4 minutes (fetch ~30s, two LLM calls, PDF
  render, Telegram).
- **Trading days only:** the pipeline checks the NSE holiday calendar and
  sends "markets closed" instead of a report on holidays.
- **Weekends:** the cron is Mon-Fri; a manual run on a weekend for a past
  weekday works fine (archives stay up).

---

## Local dry-run (no keys needed)

```
pip install -r requirements.txt
MOCK_LLM=1 DRY_RUN=1 TRADE_DATE=21-08-2026 python pipeline.py
```
Runs the whole chain with canned HTML, builds `site/`, and prints the Telegram
message instead of sending it.

---

## Known limitations (disclosed, by design)

In the automated run the LLM has no web access, so the report's **Data Gaps
Register** lists these as unavailable rather than inventing them:

- Next-session economic calendar
- Analyst support/resistance levels (the report uses option-chain-derived
  strikes instead — primary data)
- Dated news driver attribution (falls back to "No identifiable catalyst")
- GIFT Nifty evening level

These can be added later as small enrichment fetches (most have free APIs).

---

## Manual workflow (Stage 1, still available)

If you ever want the old manual flow: run the fetcher yourself and upload the
`*_compiler.json` to Claude/Kimi:

```
python stockpulse_data_fetcher.py              # today
python stockpulse_data_fetcher.py --date 21-08-2026
```
