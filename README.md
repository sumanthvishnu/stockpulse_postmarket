# StockPulse — Automated Daily Post-Market Report + Carousel

One pipeline, on a schedule, no manual steps:

```
21:00 IST (Mon-Fri, GitHub Actions cron)
  ├─ fetch NSE datapack (fixed v3.5 fetcher, 0 gaps)
  ├─ ENRICH the pack (Trendlyne MCP: Nifty/Bank Nifty pivot levels + RSI,
  │    GIFT Nifty evening cue, dated mover news; ForexFactory econ calendar)
  ├─ OpenAI compiles the report HTML (SEBI-compliant)  → PDF
  ├─ OpenAI distills a STORY BRIEF from the report (JSON)
  ├─ OpenAI writes carousel prose FROM THE BRIEF (+ anti-repeat memory)
  │    → code renders it through the fixed template (8 slides)
  ├─ headless-Chrome layout check (overflow/clipping per slide, warns on Telegram)
  ├─ publish site → gh-pages
  └─ Telegram message (only AFTER the carousel URL is verified live, so
     links can never 404): carousel + PDF links, PDF attached
```

Quality gates every run must pass: compliance lint, number lock (every
numeral traces to the datapack), calendar lock (no "tomorrow" before a closed
day), anti-repeat check vs the last 5 days, per-field character budgets, and
a rendered overflow/clipping check on all 8 slides. Failures retry with
feedback; persistent failures ship computed-from-the-pack output with a loud
Telegram warning.

The carousel follows the day's report, not a fresh reading of the raw pack:
the report is distilled into a story brief (drivers, mood, one-liner, what to
watch), and the carousel prose must compress THAT. Every Friday the carousel
ships the WEEKLY MARKET WRAP edition (week-level numbers from
`derived.five_day_change_pct`, Friday as the closing act).

Each day's prose JSON is archived in `data/prose_YYYY-MM-DD.json`; the next
run gets the last 5 days as a DO-NOT-REPEAT block (headlines, row titles,
lessons, emojis) plus a code-level repeat check that forces a rewrite. This
is what keeps the text and emojis from going stale.

You open the carousel link in your browser, review the slides, download the
PNGs, and post. Nothing is posted automatically.

---

## What's in this repo

| Path | What it is |
|---|---|
| `stockpulse_data_fetcher.py` | Fetcher v3.5 — NSE archives + derived metrics |
| `enrich.py` | Enrichment stage — adds `derived.enrichment` (Trendlyne levels/news, GIFT Nifty, econ calendar) |
| `trendlyne_mcp.py` | Trendlyne MCP client (streamable HTTP, browser UA, SSE parsing) |
| `pipeline.py` | Orchestrator (fetch → enrich → report → story brief → carousel → PDF → site → Telegram) |
| `carousel.py` | Carousel renderer (deterministic numbers + LLM prose + computed fallback) |
| `layout_check.py` | Headless-Chrome overflow/clipping check on all 8 slides |
| `llm.py` | OpenAI-compatible LLM client (Kimi/DeepSeek-swappable) |
| `compliance.py` | SEBI/house-style linter (spec §6) |
| `skills/report.md` | System prompt = your post-market report skill |
| `skills/brief.md` | System prompt = story-brief distiller (report → JSON brief) |
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
| `TRENDLYNE_MCP_TOKEN` | your Trendlyne MCP token (the long hex string from your MCP URL, after `?token=`) |
| `TELEGRAM_BOT_TOKEN` | bot token from BotFather |
| `TELEGRAM_CHAT_ID` | numeric chat id from step 3 |

Optional (defaults used if unset): `LLM_BASE_URL` (default OpenAI), `LLM_MODEL`
(default `gpt-4o`), `LLM_MODEL_CAROUSEL` (default: same as `LLM_MODEL`).

Without `TRENDLYNE_MCP_TOKEN` the run still works: index levels, the GIFT
Nifty cue and mover catalysts are logged as gaps and the report's Data Gaps
Register discloses them, exactly as before.

**Model recommendation.** Both stages default to `gpt-4o` — the report and
the carousel prose are brand-facing writing, and at one report + one carousel
per day the cost delta vs mini is small (see Cost notes). Test it for a few
days; to downgrade later set the `LLM_MODEL` secret to `gpt-4o-mini`. For
Kimi later, set `LLM_BASE_URL=https://api.moonshot.ai/v1` and the models
to Kimi ones — no code change.

**Fallback behaviour (loud, not silent).** If the carousel LLM fails all
retries, the run no longer ships a static canned text: prose is COMPUTED from
the datapack (real top/bottom sectors, breadth, flows, streak, option
levels), and the Telegram message carries a prominent "CAROUSEL USED
FALLBACK PROSE" warning so you know to review before posting.

### 5. Test it
Repo → **Actions → "StockPulse Daily Post-Market" → Run workflow** (leave the
date blank for today IST, or type a past date like `21-08-2026`). The first
run takes a few minutes (installs dependencies). You should get a Telegram
message with the carousel + report links.

---

## Cost & timing notes

- **Cost:** `gpt-4o` on a ~60 KB pack costs roughly **Rs 15-25 per day**
  (~Rs 400-600/month). Downgrade path: set `LLM_MODEL=gpt-4o-mini` to go back
  to ~Rs 0.5-1 per day. The pack is already trimmed to ~6% of its raw size.
- **Time:** the whole run is ~4-6 minutes (fetch ~30s, enrichment ~1 min,
  three LLM calls, PDF render, Telegram).
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

## Enrichment feeds (what closed the old "wire-only" gaps)

The enrichment stage (`enrich.py`) runs right after the fetch and adds
`derived.enrichment` to the pack before the LLM sees it:

| Feed | Source | Used for |
|---|---|---|
| Nifty / Bank Nifty pivot levels + RSI + SMA insight | Trendlyne MCP | Section 12 technical levels ("Trendlyne technical desk") |
| GIFT Nifty evening level + premium vs Nifty close | Trendlyne MCP (SGXNIFTY-CFD) | Sections 10/13 next-day cue, with capture time |
| Dated news for the top Nifty 50 movers | Trendlyne MCP | Section 4/7 "Why" column, story brief drivers |
| Next-session economic calendar (IST times) | ForexFactory weekly XML | Section 13 watchlist |

Same-day live cues (GIFT Nifty, the econ calendar) are skipped on backfill
runs and disclosed as gaps instead of being backfilled from stale data. Every
gap lands in `failures` and surfaces in the Data Gaps Register. The
Trendlyne pivots are also registered with the compliance levels-lock, so a
real pivot that lands on a round number is never misread as an invented
level.

## Remaining limitations (disclosed, by design)

- Yahoo's wire feed (Sensex, global markets) can lag a session, especially
  for NSE indices on backfill runs. The pipeline validates every wire bar's
  date against the trading date (and cross-checks the Nifty wire level
  against the NSE primary close); a mismatched entry is nulled and disclosed
  in the Data Gaps Register rather than published wrong.
- ATM implied volatility needs Zerodha Kite keys (optional in the fetcher).
- Results calendar for the next session is not fetched (Trendlyne has it;
  can be added to `enrich.py` later).
- FII/DII cash history beyond today stays limited to what the pack holds.

**Calendar wording is locked, not left to the model.** The fetcher computes
`derived.next_trading_session` (next trading day = weekends + the NSE holiday
master skipped) and the prompt gets a CALENDAR block naming that session. The
linter then rejects any "tomorrow" phrasing in the carousel/report when the
next session is not literally the next calendar day — so a Friday run must
reference Monday, never Saturday (this caught a real "Watch tomorrow" blunder
on the 28-Aug-2026 carousel). The same lock guards the LLM-fallback prose.

---

## Manual workflow (Stage 1, still available)

If you ever want the old manual flow: run the fetcher yourself and upload the
`*_compiler.json` to Claude/Kimi:

```
python stockpulse_data_fetcher.py              # today
python stockpulse_data_fetcher.py --date 21-08-2026
```
