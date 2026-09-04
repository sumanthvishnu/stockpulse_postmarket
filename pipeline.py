#!/usr/bin/env python3
"""StockPulse automated daily pipeline (Stage 2).

Chain: fetch datapack -> trading-day gate -> LLM report (linted) ->
LLM carousel (linted) -> render PDF -> write site/ -> Telegram notify.

Env knobs:
    TRADE_DATE        DD-MM-YYYY (default: today IST)
    MOCK_LLM=1        skip the LLM, use canned HTML (for dry runs)
    DRY_RUN=1         don't send Telegram, just print what would be sent
    GH_PAGES_BASE     https://<owner>.github.io/<repo>  (builds links)
    OPENAI_API_KEY / LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone

import compliance
import enrich
import llm
import carousel
import stockpulse_data_fetcher as fetcher

IST = timezone(timedelta(hours=5, minutes=30))
REPO = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(REPO, "site")
DATA = os.path.join(REPO, "data")
MOCK = os.environ.get("MOCK_LLM", "") == "1"
DRY = os.environ.get("DRY_RUN", "") == "1"


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- dates ---
def parse_trade_date():
    s = (os.environ.get("TRADE_DATE") or "").strip()
    if s:
        return datetime.strptime(s, "%d-%m-%Y").date()
    return datetime.now(IST).date()


def pdf_name(tdate):
    return f"StockPulse_PostMarket_Report_{tdate.strftime('%d_%b_%Y')}.pdf"


def site_url(rel):
    base = os.environ.get("GH_PAGES_BASE", "").rstrip("/")
    return f"{base}/{rel}" if base else rel


# ------------------------------------------------------------- staleness ---
def next_session_info(pack):
    """Next-session calendar facts from the datapack (fetched, holiday-aware),
    falling back to weekend-only math for archived packs that predate the
    field. Used to brief the LLM and to run the calendar lock."""
    s = (pack.get("derived") or {}).get("next_trading_session")
    if isinstance(s, dict) and s.get("label"):
        return s
    return compliance._weekend_next_session(pack)


def calendar_brief(pack):
    """Hard-fact block appended to the LLM prompt: which session is next, and
    that 'tomorrow' wording is banned when the market is closed the next day.
    The linter enforces this deterministically (models cannot be trusted to
    remember the weekday — see the 28-Aug-2026 'Watch tomorrow' blunder)."""
    s = next_session_info(pack)
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    today = tdate.strftime("%A, %d %B %Y")
    lines = [
        "CALENDAR (hard fact, not a suggestion): today's trading date is "
        f"{today} (the session the datapack describes).",
        f"The NEXT trading session is {s['label']} "
        f"({s['cal_days_ahead']} calendar days later).",
    ]
    if s.get("holiday_notes"):
        lines.append("Market is CLOSED in between: "
                     + "; ".join(s["holiday_notes"]) + ".")
    if s.get("is_imminent"):
        lines.append("'tomorrow' IS a trading session, so 'tomorrow' and "
                     "'next morning' wording is factually fine.")
    else:
        lines.append(f"NEVER write 'tomorrow', 'tomorrow's ...', or 'next "
                     f"morning': the market is closed the next calendar day. "
                     f"Refer to the next session as '{s['weekday']}', "
                     f"'{s['label']}' or 'the next session'.")
    return "\n\n" + "\n".join(lines)


def scrub_stale(pack):
    """Null out every value the fetcher flagged as not belonging to the target
    session, so the LLM can never quote it.

    Several NSE/wire endpoints are UNDATED and always serve "latest": the
    FII/DII cash API, fo_secban.csv, the rolling bulk-deals window and the
    Trading Economics 10Y quote. On a backfill they return a later session's
    numbers. Blanking only `derived` is not enough - the whole pack (including
    `data.*`) is serialised into the prompt, so the raw block has to go too.

    Returns the list of human-readable notes describing what was dropped.
    """
    d = pack.setdefault("derived", {})
    raw = pack.setdefault("data", {})
    dropped = []

    cash = d.get("fii_dii_cash_summary") or {}
    if cash.get("stale_warning"):
        labels = cash.get("date_labels")
        note = ("FII/DII cash figures are not for the target date (stale) - "
                "omitted rather than published wrong.")
        d["fii_dii_cash_summary"] = {
            "stale_warning": True, "fii_net_cr": None, "dii_net_cr": None,
            "date_labels": labels, "note": note}
        # the prompt sees data.* too - strip the raw netValue rows as well
        if isinstance(raw.get("fii_dii_cash"), dict):
            raw["fii_dii_cash"] = {
                "source": raw["fii_dii_cash"].get("source"),
                "date_labels": labels, "stale_warning": True,
                "raw": None, "note": note}
        dropped.append((f"FII/DII cash (labels {labels})", note))

    ban = d.get("fo_ban") or {}
    if ban.get("stale_warning"):
        note = ban.get("note") or ("F&O ban list is not the session after the "
                                   "target date (stale) - omitted.")
        d["fo_ban"] = {"stale_warning": True, "trade_date": None,
                       "count": None, "symbols": None, "diff_vs_prior": False,
                       "note": note}
        dropped.append(("F&O ban list", note))

    bulk = d.get("bulk_deals_today") or {}
    if bulk.get("stale_warning"):
        note = bulk.get("note") or ("bulk-deals window does not cover the "
                                    "target date - coverage unavailable.")
        d["bulk_deals_today"] = {"stale_warning": True, "count": None,
                                 "rows": [], "note": note}
        d["bulk_deals_signals"] = {"stale_warning": True, "count": None,
                                   "signals": [], "note": note}
        dropped.append(("bulk deals", note))

    y10 = d.get("india_10y") or {}
    if y10.get("stale_warning"):
        note = y10.get("note") or ("India 10Y wire quote is not for the "
                                   "target session (stale) - omitted.")
        d["india_10y"] = {"stale_warning": True, "yield_pct": None,
                          "direction": None,
                          "asof_text": y10.get("asof_text"),
                          "source": y10.get("source"), "note": note}
        dropped.append((f"India 10Y (as of {y10.get('asof_text')})", note))

    # --- global wire block: Yahoo serves the latest bar it has, and its
    # NSE-index feed can lag a full session (observed: a 03-Sep backfill got
    # the 02-Sep Sensex close, 76,570.35 instead of 76,152.86). The Indian
    # entries must carry the TARGET date's bar; anything else is nulled so a
    # wrong-session number can never reach the report or carousel. Asia
    # routinely lags 1-2 sessions even on good runs, so non-Indian entries
    # get a wide window and rely on the bar_date label. The Nifty50 wire
    # level is also cross-checked against the NSE primary close, which
    # catches a same-date-but-wrong bar.
    gm = d.get("global_markets") or {}
    markets = gm.get("markets")
    tdate_s = (pack.get("meta") or {}).get("trading_date") or ""
    try:
        t0 = date.fromisoformat(tdate_s)
    except ValueError:
        t0 = None
    if isinstance(markets, dict) and t0:
        nse_close = ((d.get("indices") or {}).get("Nifty 50") or {}).get("close")
        for label, entry in list(markets.items()):
            if not isinstance(entry, dict):
                continue
            bd = entry.get("bar_date")
            try:
                bdate = date.fromisoformat(str(bd)) if bd else None
            except ValueError:
                bdate = None
            stale_note = None
            if label in ("Sensex", "Nifty50", "IndiaVIX"):
                if bdate != t0:
                    stale_note = (f"{label} wire bar is dated {bd}, not the "
                                  f"trading date {tdate_s} (feed lag or "
                                  "backfill) - omitted rather than published "
                                  "wrong.")
            elif bdate is None or bdate > t0 or (t0 - bdate).days > 7:
                stale_note = (f"{label} wire bar dated {bd} is outside the "
                              f"valid window for {tdate_s} - omitted.")
            if (not stale_note and label == "Nifty50"
                    and isinstance(nse_close, (int, float))
                    and isinstance(entry.get("level"), (int, float))
                    and abs(entry["level"] - nse_close) > 0.005 * nse_close):
                stale_note = (f"Nifty50 wire level {entry['level']:,.2f} "
                              f"disagrees with the NSE primary close "
                              f"{nse_close:,.2f} by more than 0.5% - wire "
                              "entry omitted.")
            if stale_note:
                markets[label] = {"ticker": entry.get("ticker"),
                                  "level": None, "prev_close": None,
                                  "pts_chg": None, "pct_chg": None,
                                  "bar_date": bd, "stale_warning": True,
                                  "note": stale_note}
                dropped.append((f"{label} wire (bar {bd})", stale_note))

    if dropped:
        # Surface each dropped item in the Data Gaps Register. Section 14 of
        # the report skill enumerates every `failures` entry, so registering
        # them here makes the disclosure deterministic instead of relying on
        # the model to notice each stale_warning flag.
        fails = pack.setdefault("failures", [])
        for item, note in dropped:
            fails.append({"source": f"stale:{item}", "reason": note,
                          "checked_ist": datetime.now(IST).strftime("%H:%M IST")})
        log("  [stale] dropped as not-for-target-date: "
            + "; ".join(i for i, _ in dropped))
    return dropped


# ----------------------------------------------------------------- state ---
def restore_state():
    """Copy archived datapacks into CWD so the fetcher's ban-list diff can see
    the prior session's pack."""
    os.makedirs(DATA, exist_ok=True)
    for fn in os.listdir(DATA):
        if fn.startswith("stockpulse_datapack_") and fn.endswith(".json"):
            dst = os.path.join(REPO, fn)
            if not os.path.exists(dst):
                shutil.copy(os.path.join(DATA, fn), dst)


def archive_pack(tdate):
    src = os.path.join(REPO, f"stockpulse_datapack_{tdate.isoformat()}_compiler.json")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(DATA, os.path.basename(src)))


# ---------------------------------------------------------------- render ---
def render_pdf(html, out):
    try:
        from weasyprint import HTML
    except ImportError:
        raise SystemExit("weasyprint missing - run: pip install weasyprint "
                         "(and on ubuntu: apt install libpango-1.0-0 "
                         "libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 shared-mime-info)")
    HTML(string=html).write_pdf(out)


def inject_footer(html):
    """Add an @page footer (disclaimer on every page) deterministically."""
    css = ('<style>@page { size: A4; margin: 16mm 14mm 20mm; '
           '@bottom-center { content: "StockPulse \u00b7 For education only. '
           'Not investment advice."; font-size: 8pt; color: #64748B; } }</style>')
    if "<head>" in html:
        return html.replace("<head>", "<head>" + css, 1)
    return css + html


# ----------------------------------------------------------- generation ---
def pack_json(pack):
    return json.dumps(pack, ensure_ascii=False, default=str)


def strip_code_fence(html):
    """Remove a markdown code fence wrapping the whole document.

    The report path feeds LLM output straight into WeasyPrint, so a stray
    ```html ... ``` wrapper renders as literal text on page 1 and a trailing
    ``` on the last page. The carousel's JSON path already strips fences in
    parse_json_lenient; this is the HTML equivalent.
    """
    if not isinstance(html, str):
        return html
    t = html.strip()
    if not t.startswith("```"):
        return html
    # drop the opening fence line (```html / ```HTML / ```) ...
    t = re.sub(r"\A```[^\n]*\n?", "", t)
    # ... and the matching closing fence at the very end
    t = re.sub(r"\n?```\s*\Z", "", t)
    return t.strip()


def parse_json_lenient(text):
    """Extract a JSON object from LLM output; tolerant of code fences and the
    most common LLM slips (trailing commas, surrounding prose)."""
    import re
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty LLM output")
    t = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("no JSON object found in output")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # trailing commas before } or ] are the most common LLM mistake
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))


def _prose_text(prose):
    """Flatten all prose strings (captions live in <script>, so the HTML
    number-lock cannot see them; check them here directly)."""
    acc = []

    def walk(node):
        if isinstance(node, str):
            acc.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(prose)
    return " ".join(acc)


# ----------------------------------------------------------- story brief ---
def deterministic_brief(pack):
    """Story brief computed from the locked datapack. Used when MOCK_LLM=1 and
    as the fallback if the brief LLM call keeps failing - so the carousel
    still tells THAT day's story even with no model available."""
    f = carousel.day_facts(pack)
    drivers = []
    for name, pct in f["top_sectors"][:2]:
        drivers.append({"emoji": carousel.SECTOR_EMOJI.get(name, "📈"),
                        "title": f"{name} led",
                        "detail": f"{name} was among the strongest sectors.",
                        "stat": f"{name} {pct:+.2f}%"})
    if f["bottom_sectors"]:
        name, pct = f["bottom_sectors"][0]
        drivers.append({"emoji": carousel.SECTOR_EMOJI.get(name, "📉"),
                        "title": f"{name} dragged",
                        "detail": f"{name} was the weakest pocket.",
                        "stat": f"{name} {pct:+.2f}%"})
    br_word = "positive" if f["breadth_pos"] else "weak"
    drivers.append({"emoji": "📊", "title": f"Breadth stayed {br_word}",
                    "detail": (f"{f['advances']:,} advances versus "
                               f"{f['declines']:,} declines."),
                    "stat": f"{f['advances']:,} : {f['declines']:,}"})
    return {
        "one_liner": (f"Nifty closed {'up' if f['nifty_up'] else 'down'} "
                      f"{abs(f['nifty_pct']):.2f}% at "
                      f"{f['nifty_close']:,.2f}."),
        "mood": ("risk-on" if f["nifty_up"] and f["breadth_pos"] else
                 "risk-off" if not f["nifty_up"] and not f["breadth_pos"] else
                 "mixed"),
        "drivers": drivers[:4],
        "flows_line": carousel._flows_line(f),
        "watch_next": (f"Support {f['support']:,.0f}, resistance "
                       f"{f['resistance']:,.0f}."
                       if f["support"] and f["resistance"] else ""),
        "week_pct": f["week_pct"],
        "lesson_seeds": [],
        "source": "deterministic",
    }


def generate_story_brief(pack, report_html):
    """Stage 2b: distill the day's report into a compact story brief that the
    carousel pass then compresses into slides. This is what makes the carousel
    follow THAT day's report instead of re-interpreting the raw pack.

    Returns (brief_dict, fell_back_bool)."""
    if MOCK:
        return deterministic_brief(pack), False
    system = open(os.path.join(REPO, "skills", "brief.md"),
                  encoding="utf-8").read()
    base_user = ("DATAPACK (JSON):\n" + pack_json(pack) +
                 "\n\nPOST-MARKET REPORT (HTML, already compiled and linted "
                 "from the same datapack):\n" + report_html)
    base_user += calendar_brief(pack)
    issues = []
    for attempt in range(1, 4):
        user = base_user
        if issues:
            user += ("\n\nYour previous response had problems. Return the FULL "
                     "corrected JSON object, fixing exactly these issues:\n- " +
                     "\n- ".join(issues))
        try:
            brief = parse_json_lenient(llm.chat(
                system, user, max_tokens=2500, temperature=0.3))
            flat = _prose_text(brief)
            issues = (compliance.number_lock(flat, pack) +
                      compliance.calendar_lock(flat, pack))
            if not issues:
                brief["source"] = "llm"
                log("  [brief] story brief extracted from report")
                return brief, False
        except Exception as e:  # noqa: BLE001
            issues = [f"brief generation error: {e}"]
        log(f"  [brief] attempt {attempt}: {issues}")
    log("  [brief] falling back to deterministic brief from the datapack")
    return deterministic_brief(pack), True


# ------------------------------------------------------ anti-repetition ----
def _prose_path(tdate):
    return os.path.join(DATA, f"prose_{tdate.isoformat()}.json")


def save_prose(tdate, prose):
    """Persist each day's carousel prose so future runs can ban repeats."""
    os.makedirs(DATA, exist_ok=True)
    with open(_prose_path(tdate), "w", encoding="utf-8") as f:
        json.dump(prose, f, ensure_ascii=False, indent=1)


def recent_prose_memory(tdate, n=5):
    """Load the last n days' prose (before tdate) and build a DO-NOT-REPEAT
    block for the prompt plus sets for the code-level repeat check."""
    past = []
    if os.path.isdir(DATA):
        for fn in sorted(os.listdir(DATA)):
            m = re.fullmatch(r"prose_(\d{4}-\d{2}-\d{2})\.json", fn)
            if not m or m.group(1) >= tdate.isoformat():
                continue
            try:
                past.append((m.group(1), json.load(
                    open(os.path.join(DATA, fn), encoding="utf-8"))))
            except Exception:  # noqa: BLE001 - a corrupt memory file is skippable
                continue
    past = past[-n:]
    headlines, emojis, titles, lessons = set(), set(), set(), set()
    for _, p in past:
        h = re.sub(r"\s+", " ", re.sub(r"[*_]", "",
                                       str(p.get("headline", "")))).strip().lower()
        if h:
            headlines.add(h)
        for row in (p.get("why") or []):
            if row.get("emoji"):
                emojis.add(row["emoji"])
            if row.get("title"):
                titles.add(row["title"].strip().lower())
        for l in (p.get("lessons") or []):
            if l:
                lessons.add(l.strip().lower())
    if not past:
        return "", headlines, emojis
    lines = ["ANTI-REPETITION (hard rule): these come from your previous "
             f"{len(past)} carousel(s). Do NOT reuse or lightly paraphrase "
             "any of them - same meaning in different words counts as a "
             "repeat. Today's drivers decide today's wording."]
    if headlines:
        lines.append("Headlines already used: " + " | ".join(sorted(headlines)))
    if titles:
        lines.append("'Why' row titles already used: "
                     + " | ".join(sorted(titles)))
    if lessons:
        lines.append("Lessons already used: " + " | ".join(sorted(lessons)))
    if emojis:
        lines.append("Emojis already used (avoid unless the driver genuinely "
                     "repeats): " + " ".join(sorted(emojis)))
    return "\n\n" + "\n".join(lines), headlines, emojis


def generate_carousel(pack, brief, weekly=False):
    """LLM writes prose JSON, guided by the day's story brief (distilled from
    the report) and an anti-repetition memory of recent days; code renders it
    through the fixed template.

    Never crashes the run: any LLM/parse error is retried with feedback, and
    after 3 attempts it falls back to prose COMPUTED from the datapack (not a
    static canned text). Returns (html, prose, issues, fell_back)."""
    system = open(os.path.join(REPO, "skills", "carousel.md"),
                  encoding="utf-8").read()
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    memory_block, seen_headlines, seen_emojis = recent_prose_memory(tdate)

    base_user = ("Here is today's datapack (JSON), followed by THE DAY'S "
                 "STORY - the brief distilled from today's post-market "
                 "report. Your prose must be a compression of that story, "
                 "not a fresh interpretation of the raw numbers.\n\n"
                 "DATAPACK:\n" + pack_json(pack) +
                 "\n\nTHE DAY'S STORY (from the report, authoritative "
                 "narrative):\n" + json.dumps(brief, ensure_ascii=False,
                                              indent=1))
    if weekly:
        base_user += ("\n\nEDITION: today is Friday, so this is the WEEKLY "
                      "MARKET WRAP edition. Frame the headline, hero text, "
                      "lessons and captions around the WEEK (the datapack's "
                      "five_day_change_pct), with Friday's session as the "
                      "closing act. Movers and levels stay Friday's.")
    base_user += calendar_brief(pack)
    base_user += memory_block
    issues = []
    for attempt in range(1, 4):
        user = base_user
        if issues:
            user += ("\n\nYour previous response had problems. Return the FULL "
                     "corrected JSON object, fixing exactly these issues:\n- " +
                     "\n- ".join(issues))
        try:
            if MOCK:
                # Dry runs exercise the computed prose (prose27.json belongs to
                # a past session and would fail the number-lock anyway).
                prose = carousel.fallback_prose(pack, weekly=weekly)
            else:
                prose = parse_json_lenient(llm.chat(
                    system, user, max_tokens=8000, temperature=0.85,
                    model=(os.environ.get("LLM_MODEL_CAROUSEL") or None)))
            html, leftover = carousel.build(pack, prose, weekly=weekly)
            issues = carousel.validate(html, pack)
            issues += carousel.budget_issues(prose)
            prose_flat = _prose_text(prose)
            issues += compliance.number_lock(prose_flat, pack)
            issues += compliance.calendar_lock(prose_flat, pack)
            if leftover:
                issues += [f"unfilled template tokens: {leftover}"]
            # code-level repeat check (the prompt ban alone is not reliable)
            h = re.sub(r"\s+", " ", re.sub(
                r"[*_]", "", str(prose.get("headline", "")))).strip().lower()
            if h and h in seen_headlines:
                issues += [f"headline repeats a previous day: '{h}' - write a "
                           "fresh one from today's drivers"]
            day_emojis = {r.get("emoji") for r in (prose.get("why") or [])
                          if r.get("emoji")}
            if day_emojis and day_emojis == seen_emojis:
                issues += ["the exact emoji set was already used - pick emojis "
                           "that depict today's specific drivers"]
            if not issues:
                return html, prose, [], False
        except Exception as e:  # noqa: BLE001 - LLM/parse failure must not kill the run
            issues = [f"carousel generation error: {e}"]
        log(f"  [carousel] attempt {attempt}: {issues}")
    log("  [carousel] LLM failed - using computed fallback prose "
        "(numbers AND story from the datapack)")
    prose = carousel.fallback_prose(pack, weekly=weekly)
    html, _ = carousel.build(pack, prose, weekly=weekly)
    return html, prose, (issues or ["used fallback prose"]), True


def minimal_report(pack):
    """Deterministic fallback report built from locked numbers. Used only if
    the LLM is down or persistently fails the number-lock, so the nightly run
    still ships a correct-numbers report instead of nothing."""
    d = pack["derived"]
    tdate = pack["meta"]["trading_date"]
    n50 = d["indices"]["Nifty 50"]
    bnk = d["indices"]["Nifty Bank"]
    vix = d["vix"]["current"]
    br = d["breadth"]
    cash = d.get("fii_dii_cash_summary") or {}
    fii = cash.get("fii_net_cr")
    dii = cash.get("dii_net_cr")
    fii_s = f"Rs {fii:,.2f} Cr" if fii is not None else "n/a"
    dii_s = f"Rs {dii:,.2f} Cr" if dii is not None else "n/a"
    rows = "".join(
        f"<tr><td>{k}</td><td>{v['close']:,.2f}</td><td>{v['pct_chg']:+.2f}%</td></tr>"
        for k, v in [("Nifty 50", n50), ("Nifty Bank", bnk)])
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"body{{font-family:sans-serif;margin:40px;color:#0F2744}}"
            f"h1{{color:#0F2744}}table{{border-collapse:collapse;width:60%}}"
            f"td,th{{border:1px solid #ccc;padding:6px 12px;text-align:right}}"
            f"th:first-child,td:first-child{{text-align:left}}"
            f"</style></head><body>"
            f"<h1>StockPulse Post-Market Report · {tdate}</h1>"
            f"<table><tr><th>Index</th><th>Close</th><th>Change</th></tr>{rows}</table>"
            f"<p>India VIX {vix}. Breadth: {br['advances']} advances vs "
            f"{br['declines']} declines. FII net {fii_s}, DII net {dii_s}.</p>"
            f"<p>For education only. Not investment advice.</p>"
            f"</body></html>")


def derivatives_snippet(pack):
    """Pre-built derivatives table (section 12) so the LLM embeds correct
    strikes instead of transcribing them (it previously dropped digits:
    24500 -> 4500)."""
    d = pack["derived"]

    def row(label, o):
        if not o:
            return ""
        return (f"<tr><td>{label}</td><td>{o.get('expiry', '')}</td>"
                f"<td>{o.get('pcr_oi')}</td><td>{o.get('max_pain'):,.0f}</td>"
                f"<td>{o.get('max_put_oi_strike'):,.0f}</td>"
                f"<td>{o.get('max_call_oi_strike'):,.0f}</td>"
                f"<td>{o.get('atm_strike'):,.0f}</td></tr>")

    return ("<table class='deriv'><tr><th>Index</th><th>Expiry</th><th>PCR</th>"
            "<th>Max Pain</th><th>Support (max Put OI)</th>"
            "<th>Resistance (max Call OI)</th><th>ATM</th></tr>"
            + row("NIFTY", d.get("options_NIFTY"))
            + row("BANKNIFTY", d.get("options_BANKNIFTY"))
            + "</table>")


def global_snippet(pack):
    """Pre-built global-markets table (section 10) so the LLM embeds correct
    levels/points changes instead of computing them (it previously wrote
    'down 184.16 points' for a true -183.16)."""
    gm = pack["derived"].get("global_markets", {}).get("markets", {})
    order = ["Dow", "SP500", "Nasdaq", "US10Y_yield", "DXY",
             "Nikkei", "HangSeng", "Shanghai", "Kospi",
             "FTSE", "DAX", "Brent", "WTI", "Gold", "USDINR",
             "IndiaVIX", "Sensex", "Nifty50"]
    rows = ""
    for k in order:
        v = gm.get(k)
        if not v or not isinstance(v, dict):
            continue
        pts = v.get("pts_chg")
        pts_s = f"{pts:+,.2f}" if isinstance(pts, (int, float)) else "n/a"
        pct = v.get("pct_chg")
        pct_s = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "n/a"
        lvl = v.get("level")
        lvl_s = f"{lvl:,.2f}" if isinstance(lvl, (int, float)) else "n/a"
        rows += (f"<tr><td>{k}</td><td>{v.get('bar_date', '')}</td>"
                 f"<td>{lvl_s}</td><td>{pts_s}</td><td>{pct_s}</td></tr>")
    return ("<table class='glob'><tr><th>Market</th><th>As of</th><th>Level"
            "</th><th>Chg (pts)</th><th>Chg %</th></tr>" + rows + "</table>")


def levels_snippet(pack):
    """Pre-built technical-levels table (section 12) from the enrichment
    block's Trendlyne pivots. Without this the model sometimes skipped the
    levels entirely even when they were present in the pack (observed on the
    04-Sep run). Returns '' when nothing usable was retrieved, so the caller
    can omit the embed instruction."""
    il = ((pack.get("derived") or {}).get("enrichment") or {}).get(
        "index_levels") or {}
    rows = ""
    for label, name in (("NIFTY", "Nifty 50"), ("BANKNIFTY", "Bank Nifty")):
        v = il.get(label) or {}
        if v.get("stale_warning") or not isinstance(v.get("pivot"), (int, float)):
            continue
        def f(x):
            return f"{x:,.2f}" if isinstance(x, (int, float)) else "n/a"
        rows += (f"<tr><td>{name}</td><td>{f(v.get('pivot'))}</td>"
                 f"<td>{f(v.get('s1'))}</td><td>{f(v.get('s2'))}</td>"
                 f"<td>{f(v.get('r1'))}</td><td>{f(v.get('r2'))}</td>"
                 f"<td>{f(v.get('rsi'))}</td>"
                 f"<td>{v.get('sma_insight') or ''}</td>"
                 f"<td>{v.get('source', 'Trendlyne technical desk')}, "
                 f"{v.get('asof_ist', '')}</td></tr>")
    if not rows:
        return ""
    return ("<table class='levels'><tr><th>Index</th><th>Pivot</th>"
            "<th>S1</th><th>S2</th><th>R1</th><th>R2</th><th>RSI(14)</th>"
            "<th>SMA insight</th><th>Source</th></tr>" + rows + "</table>")


def generate_with_lint(kind, pack):
    """Generate report/carousel HTML, lint it, retry with feedback."""
    system = open(os.path.join(REPO, "skills", f"{kind}.md"),
                  encoding="utf-8").read()
    what = ("post-market report HTML" if kind == "report"
            else "post-market carousel HTML")
    base_user = (f"Here is today's datapack (JSON). Build the {what}.\n\n"
                 + pack_json(pack))
    base_user += calendar_brief(pack)
    if kind == "report":
        base_user += (
            "\n\nTwo pre-computed tables are provided below. Embed them "
            "VERBATIM (copy-paste, do not retype or alter any number) in "
            "your report: the derivatives table in section 12, the global "
            "markets table in section 10.\n\n"
            "DERIVATIVES DASHBOARD:\n" + derivatives_snippet(pack) +
            "\n\nGLOBAL MARKETS TABLE:\n" + global_snippet(pack) + "\n")
        lvl = levels_snippet(pack)
        if lvl:
            base_user += (
                "\nA third pre-computed table is provided below. Embed it "
                "VERBATIM in section 12 after the derivatives dashboard - it "
                "carries the day's technical levels retrieved from the "
                "Trendlyne technical desk (keep the Source column as-is; it "
                "is the attribution). If it is absent from this prompt, no "
                "levels were retrieved today and section 12 uses the "
                "option-chain levels only.\n\n"
                "TECHNICAL LEVELS (Trendlyne technical desk):\n" + lvl + "\n")
    html = None
    issues = []
    for attempt in range(1, 6):
        user = base_user
        if issues:
            user += ("\n\nYour previous draft was REJECTED by the compliance "
                     "linter. Return the FULL corrected document (not a diff), "
                     "fixing exactly these issues:\n- " + "\n- ".join(issues))
        if MOCK:
            html = mock_doc(kind, pack)
        else:
            try:
                html = llm.chat(
                    system, user,
                    max_tokens=12000 if kind == "report" else 10000,
                    temperature=0.3 if kind == "report" else 0.4)
            except Exception as e:  # noqa: BLE001 - transient API failure
                issues = [f"LLM call failed: {e}"]
                log(f"  [{kind}] attempt {attempt}: {issues}")
                continue
        html = strip_code_fence(html)
        issues = compliance.lint(html, kind)
        if kind == "report":
            issues += compliance.number_lock(html, pack)
        issues += compliance.calendar_lock(html, pack)
        if not issues:
            return html, []
        log(f"  [{kind}] lint attempt {attempt}: {issues}")
    log(f"  [warn] {kind}: still failing after retries: {issues}")
    if html is None or (kind == "report" and any(
            ("unverified number" in i) or ("close stated" in i) or
            ("level '" in i) for i in issues)):
        html = minimal_report(pack)
        log(f"  [{kind}] shipped minimal number-locked report instead")
    return html, issues


def mock_doc(kind, pack):
    """Canned output for dry runs (no API key needed)."""
    d = pack["derived"]
    n50 = d["indices"]["Nifty 50"]
    bnk = d["indices"]["Nifty Bank"]
    vix = d["vix"]["current"]
    cash = d.get("fii_dii_cash_summary") or {}
    fii = cash.get("fii_net_cr")
    dii = cash.get("dii_net_cr")
    fii_txt = f"Rs {fii:,.2f} Cr" if fii is not None else "n/a"
    dii_txt = f"Rs {dii:,.2f} Cr" if dii is not None else "n/a"
    tdate = pack["meta"]["trading_date"]
    if kind == "report":
        return ("<!doctype html><html><head><style>"
                "body{font-family:sans-serif;margin:40px}"
                "h1{color:#0F2744}h2{color:#F97316;border-bottom:2px solid #F97316}"
                "</style></head><body>"
                f"<h1>StockPulse Post-Market Report · {tdate}</h1>"
                "<h2>1. Cover</h2><p>MOCK REPORT (dry run).</p>"
                f"<h2>2. Executive Summary</h2><p>Nifty 50 closed at Rs {n50['close']:,.2f} "
                f"({n50['pct_chg']:+.2f}%). Bank Nifty Rs {bnk['close']:,.2f} "
                f"({bnk['pct_chg']:+.2f}%). India VIX at {vix}. "
                f"FII net {fii_txt}, DII net {dii_txt}.</p>"
                "<h2>14. Data Gaps Register</h2><p>No gaps (mock run).</p>"
                "<p style='margin-top:60px;color:#64748B'>For education only. "
                "Not investment advice.</p>"
                "</body></html>")
    slides = []
    for i, (bg, wm) in enumerate([("#0F2744", "CLOSE"), ("#FFFFFF", ""),
                                  ("#0F2744", "WHY"), ("#FFFFFF", ""),
                                  ("#0F2744", "MOVE"), ("#FFFFFF", ""),
                                  ("#0F2744", "NEXT"), ("#FFFFFF", "")], 1):
        slides.append(
            f'<div style="width:1080px;height:1080px;background:{bg};'
            f'color:{"#fff" if bg=="#0F2744" else "#0F2744"};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:48px">Slide {i} MOCK</div>')
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            "body{font-family:sans-serif}.deck{display:flex;flex-direction:column;gap:24px}"
            "textarea{width:100%;height:120px}</style></head><body>"
            f"<h1>StockPulse Post-Market Carousel · {tdate} (MOCK)</h1>"
            "<div class='deck'>" + "".join(slides) + "</div>"
            "<h2>CAPTIONS · TAP COPY</h2>"
            "<p>Caption A</p><textarea>Nifty closed near Rs "
            f"{n50['close']:,.2f}, up {n50['pct_chg']:+.2f}%. Not investment "
            "advice. #Nifty #IndianStockMarket #StockMarket #Trading #Investing"
            "</textarea><p>Caption B</p><textarea>FII sold "
            f"{fii_txt} while DII bought {dii_txt}. Daily wrap "
            "every evening @getstockpulse. Not investment advice. #Nifty "
            "#IndianStockMarket #FII #DII #StockMarket</textarea>"
            "</body></html>")


# ------------------------------------------------------------- telegram ---
def tg(method, **data):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                      data=data, timeout=120)
    r.raise_for_status()
    return r.json()


def tg_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def notify(tdate, pack, pdf_path, carousel_url, pdf_url, issues,
           carousel_fallback=False, brief_fallback=False):
    import requests
    d = pack["derived"]
    n50 = d["indices"]["Nifty 50"]
    bnk = d["indices"]["Nifty Bank"]
    vix = d["vix"]["current"]
    cash = d.get("fii_dii_cash_summary") or {}
    fii = cash.get("fii_net_cr")
    dii = cash.get("dii_net_cr")
    fii_s = f"Rs {fii:,.2f} Cr" if fii is not None else "n/a"
    dii_s = f"Rs {dii:,.2f} Cr" if dii is not None else "n/a"
    wday = tdate.strftime("%A")
    lines = [
        f"<b>📊 StockPulse Post-Market · {wday}, {tdate.strftime('%d %b %Y')}</b>",
        f"Nifty {n50['close']:,.2f} ({n50['pct_chg']:+.2f}%) · "
        f"Bank Nifty {bnk['close']:,.2f} ({bnk['pct_chg']:+.2f}%)",
        f"VIX {vix} · FII {fii_s} · DII {dii_s}",
        "",
        f"🎠 <a href=\"{tg_escape(carousel_url)}\">Carousel (open in browser, download slides)</a>",
        f"📄 <a href=\"{tg_escape(pdf_url)}\">Report (PDF)</a>",
    ]
    if carousel_fallback:
        # Loud, not buried: fallback prose means yesterday's-style generic
        # wording is exactly what you must NOT post without a look.
        lines.append("")
        lines.append("‼️ CAROUSEL USED FALLBACK PROSE (LLM failed all "
                     "retries). Text was computed from the datapack - correct "
                     "but plain. Review before posting.")
    if brief_fallback:
        lines.append("⚠️ Story brief fell back to datapack-computed (report "
                     "distillation failed); carousel may be less narrative.")
    if issues:
        lines.append("")
        # issue strings contain report HTML fragments (<td>, <tr>...), which
        # Telegram's HTML parser rejects -> escape them or sendMessage 400s.
        lines.append("⚠️ Alerts: " + tg_escape("; ".join(issues[:4])))
    text = "\n".join(lines)
    if DRY:
        log(f"[dry] would send to Telegram:\n{text}\n[dry] + PDF {pdf_path}")
        return
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is empty - add the secret")
    try:
        tg("sendMessage", chat_id=chat_id, text=text,
           parse_mode="HTML", disable_web_page_preview=False)
    except Exception as e:  # noqa: BLE001 - don't let a Telegram hiccup fail the run
        log(f"  [telegram] HTML send failed ({e}); retrying as plain text")
        plain = re.sub(r"<[^>]+>", " ", text)
        tg("sendMessage", chat_id=chat_id, text=plain)
    try:
        with open(pdf_path, "rb") as fh:
            requests.post(
                f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN', '')}"
                f"/sendDocument",
                data={"chat_id": chat_id},
                files={"document": (os.path.basename(pdf_path), fh)}, timeout=120)
    except Exception as e:  # noqa: BLE001
        log(f"  [telegram] sendDocument failed: {e}")


def notify_generic(text):
    if DRY:
        log(f"[dry] would send: {text}")
        return
    tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text)


# ----------------------------------------------------------------- main ---
def main():
    os.chdir(REPO)
    tdate = parse_trade_date()
    log(f"StockPulse pipeline - trading date {tdate} "
        f"(mock={MOCK}, dry={DRY})")

    restore_state()
    log("== stage 1/4: fetch datapack ==")
    fetcher.collect(tdate)

    cpath = os.path.join(REPO, f"stockpulse_datapack_{tdate.isoformat()}_compiler.json")
    if not os.path.exists(cpath):
        notify_generic(f"⚠️ StockPulse: no datapack produced for {tdate} - "
                       "likely a market holiday or archive not yet published.")
        return
    pack = json.load(open(cpath, encoding="utf-8"))

    hol = pack.get("data", {}).get("holiday_check", {})
    if hol.get("is_holiday"):
        detail = hol.get("detail") or "market holiday"
        notify_generic(f"📭 StockPulse: markets closed today ({detail}). "
                       "No report generated.")
        return

    scrub_stale(pack)

    if "indices" not in pack.get("derived", {}):
        notify_generic("⚠️ StockPulse: index data missing from datapack - "
                       "report aborted. Check fetcher logs.")
        return
    idx_date = (pack.get("derived", {}).get("indices_date") or "")[:10]
    if idx_date and idx_date < tdate.isoformat():
        notify_generic(
            f"⚠️ StockPulse: datapack indices are dated {idx_date}, older than "
            f"trading date {tdate.isoformat()}. NSE end-of-day archives for "
            "today are not published yet (gates open ~18:00-19:00 IST), so the "
            "run is aborted rather than publishing stale numbers. Re-run after "
            "19:00 IST, or use a past trading date.")
        return

    weekly = tdate.weekday() == 4   # Friday -> WEEKLY MARKET WRAP edition
    log("== stage 1b/4: enrichment (Trendlyne MCP + econ calendar) ==")
    enrich.run(pack)
    log("== stage 2/4: compile report (LLM + lint) ==")
    report_html, report_issues = generate_with_lint("report", pack)
    log("== stage 2b/4: distill story brief from the report ==")
    brief, brief_fallback = generate_story_brief(pack, report_html)
    log("== stage 3/4: build carousel (story brief + anti-repeat memory) ==")
    carousel_html, carousel_prose, carousel_issues, carousel_fallback = \
        generate_carousel(pack, brief, weekly=weekly)
    all_issues = report_issues + carousel_issues
    save_prose(tdate, carousel_prose)

    log("== stage 4/4: render + publish + notify ==")
    day_dir = os.path.join(SITE, tdate.isoformat())
    os.makedirs(day_dir, exist_ok=True)
    pdf_path = os.path.join(day_dir, pdf_name(tdate))
    render_pdf(inject_footer(report_html), pdf_path)
    with open(os.path.join(day_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(report_html)
    with open(os.path.join(day_dir, "carousel.html"), "w", encoding="utf-8") as f:
        f.write(carousel_html)
    with open(os.path.join(day_dir, "report_issues.json"), "w",
              encoding="utf-8") as f:
        json.dump({"report_issues": report_issues,
                   "carousel_issues": carousel_issues}, f)
    # Publish the SCRUBBED pack, not the on-disk original: shutil.copy would
    # re-expose the stale FII/DII rows that scrub_stale() just removed.
    with open(os.path.join(day_dir, "datapack.json"), "w",
              encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, default=str)
    with open(os.path.join(day_dir, "story_brief.json"), "w",
              encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=1)

    archive_pack(tdate)

    carousel_url = site_url(f"{tdate.isoformat()}/carousel.html")
    pdf_url = site_url(f"{tdate.isoformat()}/{pdf_name(tdate)}")
    if os.environ.get("NOTIFY", "1") == "1":
        notify(tdate, pack, pdf_path, carousel_url, pdf_url, all_issues,
               carousel_fallback=carousel_fallback, brief_fallback=brief_fallback)
    else:
        # Deferral mode (workflow sets NOTIFY=0): the message is sent by the
        # post-publish step via --notify-only, after the site is verified
        # live, so the links in the message can never 404.
        payload = {"pdf_name": pdf_name(tdate), "carousel_url": carousel_url,
                   "pdf_url": pdf_url, "issues": all_issues,
                   "carousel_fallback": carousel_fallback,
                   "brief_fallback": brief_fallback}
        with open(os.path.join(day_dir, "notify_payload.json"), "w",
                  encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        log("  [notify] deferred until the site is verified live")

    log(f"\nDone. PDF: {pdf_path}\nCarousel: {day_dir}/carousel.html"
        f"\nCarousel URL: {carousel_url}\nReport URL: {pdf_url}")


def notify_only():
    """Post-publish entry point: send the Telegram message for TRADE_DATE
    using the payload the main run left in site/<date>/. Called by the
    workflow only AFTER the pages deploy is confirmed live."""
    tdate = parse_trade_date()
    day_dir = os.path.join(SITE, tdate.isoformat())
    payload = json.load(open(os.path.join(day_dir, "notify_payload.json"),
                             encoding="utf-8"))
    pack = json.load(open(os.path.join(day_dir, "datapack.json"),
                          encoding="utf-8"))
    notify(tdate, pack, os.path.join(day_dir, payload["pdf_name"]),
           payload["carousel_url"], payload["pdf_url"], payload["issues"],
           carousel_fallback=payload.get("carousel_fallback", False),
           brief_fallback=payload.get("brief_fallback", False))


if __name__ == "__main__":
    if "--notify-only" in sys.argv:
        notify_only()
    else:
        main()
