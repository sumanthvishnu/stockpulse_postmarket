#!/usr/bin/env python3
"""StockPulse carousel renderer (deterministic core + LLM prose).

build(pack, prose) -> HTML
    numbers/names are computed here from the locked datapack (they cannot be
    invented); prose (headlines, lessons, captions, notes) comes from the LLM.

The design lives in carousel_template.html (your golden 26-Aug carousel with
{{TOKENS}} in every content slot).
"""
import json
import os
import re
from datetime import date

import compliance

REPO = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(REPO, "carousel_template.html")

SECTORAL = ["Nifty IT", "Nifty Bank", "Nifty Financial Services", "Nifty Auto",
            "Nifty Metal", "Nifty FMCG", "Nifty Realty", "Nifty Pharma",
            "Nifty Healthcare Index", "Nifty Energy", "Nifty Oil & Gas",
            "Nifty PSU Bank", "Nifty Private Bank", "Nifty Media",
            "Nifty Consumer Durables", "Nifty Infrastructure"]

SECTOR_SHORT = {
    "Nifty IT": "IT", "Nifty Bank": "Bank", "Nifty Auto": "Auto",
    "Nifty Metal": "Metal", "Nifty FMCG": "FMCG", "Nifty Realty": "Realty",
    "Nifty Pharma": "Pharma", "Nifty Healthcare Index": "Healthcare",
    "Nifty Energy": "Energy", "Nifty Oil & Gas": "Oil & Gas",
    "Nifty PSU Bank": "PSU Bank", "Nifty Private Bank": "Private Bank",
    "Nifty Media": "Media", "Nifty Consumer Durables": "Consumer Durables",
    "Nifty Infrastructure": "Infra", "Nifty Financial Services": "Financials",
}

NIFTY50_NAMES = {
    "ADANIENT": "Adani Enterprises", "ADANIPORTS": "Adani Ports",
    "APOLLOHOSP": "Apollo Hospitals", "ASIANPAINT": "Asian Paints",
    "AXISBANK": "Axis Bank", "BAJAJ-AUTO": "Bajaj Auto",
    "BAJFINANCE": "Bajaj Finance", "BAJAJFINSV": "Bajaj Finserv",
    "BEL": "Bharat Electronics", "BHARTIARTL": "Bharti Airtel",
    "CIPLA": "Cipla", "COALINDIA": "Coal India", "DRREDDY": "Dr Reddy's",
    "EICHERMOT": "Eicher Motors", "ETERNAL": "Eternal",
    "GRASIM": "Grasim", "HCLTECH": "HCL Tech", "HDFCBANK": "HDFC Bank",
    "HDFCLIFE": "HDFC Life", "HEROMOTOCO": "Hero MotoCorp",
    "HINDALCO": "Hindalco", "HINDUNILVR": "Hindustan Unilever",
    "ICICIBANK": "ICICI Bank", "INDUSINDBK": "IndusInd Bank", "INFY": "Infosys",
    "ITC": "ITC", "JIOFIN": "Jio Financial", "JSWSTEEL": "JSW Steel",
    "KOTAKBANK": "Kotak Bank", "LT": "L&T", "M&M": "M&M",
    "MARUTI": "Maruti Suzuki", "NESTLEIND": "Nestle", "NTPC": "NTPC",
    "ONGC": "ONGC", "POWERGRID": "Power Grid", "RELIANCE": "Reliance",
    "SBILIFE": "SBI Life", "SBIN": "SBI", "SHRIRAMFIN": "Shriram Finance",
    "SUNPHARMA": "Sun Pharma", "TCS": "TCS", "TATACONSUM": "Tata Consumer",
    "TATAMOTORS": "Tata Motors", "TATASTEEL": "Tata Steel", "TECHM": "Tech M",
    "TITAN": "Titan", "TRENT": "Trent", "ULTRACEMCO": "UltraTech",
    "WIPRO": "Wipro", "MAXHEALTH": "Max Healthcare", "INDIGO": "IndiGo",
    "TMPV": "TMPV",
}

MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
          "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
MONTHS_SHORT = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
WDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
         "FRIDAY", "SATURDAY", "SUNDAY"]


# ------------------------------------------------------------------ utils ---
def fnum(v, dec=2):
    return "n/a" if v is None else f"{v:,.{dec}f}"


def up_down(v):
    if v is None:
        return "flat"
    return "up" if v >= 0 else "down"


def chg_word(v):
    if v is None:
        return "n/a"
    return "up" if v >= 0 else "down"


def pct_text(v):
    if v is None:
        return "n/a"
    return f"{chg_word(v)} {abs(v):.2f}%"


def signed(v, dec=2):
    return "n/a" if v is None else f"{v:+.{dec}f}%"


def hl(text):
    """*word* markers -> <span class=hl>word</span> (first match)."""
    if not text:
        return ""
    m = re.search(r"\*([^*]+)\*", text)
    if not m:
        return text
    return (text[:m.start()] + '<span class="hl">' + m.group(1) +
            "</span>" + text[m.end():])


# ------------------------------------------------------------- prose model --
def default_prose():
    """Neutral prose so a failed LLM still yields a valid, correct carousel."""
    return {
        "headline": "*Nifty* ended the day lower.",
        "subline": "A muted session for Indian equities.",
        "hero_text": "A quiet day for the indices.",
        "why_head": "Why the market moved",
        "why": [
            {"emoji": "📉", "title": "Index drifted lower",
             "desc": "Frontline stocks closed in the red.", "badge": "Soft close"},
            {"emoji": "🏦", "title": "Banking stocks weighed",
             "desc": "Financial names led the drag.", "badge": "Banks weak"},
            {"emoji": "🌍", "title": "Global cues muted",
             "desc": "Mixed signals from overseas markets.", "badge": "Mixed cues"},
            {"emoji": "📊", "title": "Breadth stayed thin",
             "desc": "Declines outnumbered advances on the day.", "badge": "Weak breadth"},
        ],
        "sector_reasons": {},
        "bonus_title": "Quiet outperformers",
        "bonus_text": "A few sectors bucked the trend.",
        "movers_note_gainers": "Gainers led on steady delivery.",
        "movers_note_losers": "Losers slipped on light volumes.",
        "watch_text": "Watch the option chain levels for the next session.",
        "lessons": [
            "A red index can hide pockets of strength.",
            "Delivery data separates real moves from noise.",
            "Breadth tells the fuller market story.",
            "Flows set the tone for the next session.",
        ],
        "alert_title": "Watch tomorrow",
        "alert_text": "Fresh global cues arrive before the open.",
        "cta_headline": "Save this and *check back at the close*.",
        "cta_sub": "Follow for the full picture every evening.",
        "next_text": "Global cues and corporate actions land tomorrow.",
        "caption_a": "Nifty closed lower today. Daily wrap every evening "
                     "@getstockpulse. Not investment advice. #Nifty "
                     "#IndianStockMarket #StockMarket #Trading #Investing",
        "caption_b": "Follow the flows, not just the headline. Daily wrap "
                     "every evening @getstockpulse. Not investment advice. "
                     "#Nifty #IndianStockMarket #FII #DII #MarketWrap",
    }


# ------------------------------------------------------------------- build --
def build(pack, prose):
    d = pack["derived"]
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    prose = {**default_prose(), **(prose or {})}
    wd = WDAYS[tdate.weekday()]
    m = {k: None for k in ("")}  # noop
    idx = d["indices"]
    gm = d.get("global_markets", {}).get("markets", {})

    nifty = idx["Nifty 50"]
    bank = idx["Nifty Bank"]
    vix = idx["India VIX"]
    sensex = gm.get("Sensex", {})
    breadth = d["breadth"]
    cash = d.get("fii_dii_cash_summary") or {}
    fii, dii = cash.get("fii_net_cr"), cash.get("dii_net_cr")
    on50 = d["options_NIFTY"]
    obnk = d["options_BANKNIFTY"]
    mv = d["nifty50_movers"]

    def cash_s(v):
        return "n/a" if v is None else f"{v:+,.2f} Cr"

    def cash_short(v):
        return "n/a" if v is None else f"{v:+,.0f} Cr"

    # --- cover ----------------------------------------------------------
    stat_class = up_down(nifty["pct_chg"])
    cover_pill = (f"Nifty {fnum(nifty['close'])} · "
                  f"{chg_word(nifty['pct_chg'])} "
                  f"{abs(nifty['pts_chg']):.2f} pts "
                  f"({abs(nifty['pct_chg']):.2f}%)")

    # --- snapshot -------------------------------------------------------
    cards = [
        ("Nifty 50", nifty["close"], nifty["pct_chg"]),
        ("Sensex", sensex.get("level"), sensex.get("pct_chg")),
        ("Bank Nifty", bank["close"], bank["pct_chg"]),
    ]

    tiles = [
        ("India VIX", fnum(vix["close"]), up_down(vix["pct_chg"]),
         f"{chg_word(vix['pct_chg'])} {abs(vix['pct_chg']):.2f}%"),
        ("Advances vs Declines", f"{breadth['advances']:,} : {breadth['declines']:,}",
         up_down(breadth['advances'] - breadth['declines']),
         ("more stocks rose than fell" if breadth["advances"] >= breadth["declines"]
          else "more stocks fell than rose")),
        ("FII net (cash)", cash_s(fii), up_down(fii if fii is not None else 0),
         "foreign inflows" if (fii or 0) >= 0 else "foreign outflows"),
        ("DII net (cash)", cash_s(dii), up_down(dii if dii is not None else 0),
         "domestic inflows" if (dii or 0) >= 0 else "domestic outflows"),
    ]

    # --- sectors (top 3 + bottom 3 by daily % change) --------------------
    present = [(k, idx[k]["pct_chg"]) for k in SECTORAL
               if k in idx and idx[k].get("pct_chg") is not None]
    present.sort(key=lambda x: -x[1])
    picks = present[:3] + present[-3:][::-1]
    reasons = prose.get("sector_reasons") or {}

    def sec_row(name, pct, i):
        short = SECTOR_SHORT.get(name, name.replace("Nifty ", ""))
        reason = reasons.get(short) or (
            "led the day" if pct >= 0 else "lagged the day")
        return short, up_down(pct), reason, signed(pct)

    secs = [sec_row(n, p, i) for i, (n, p) in enumerate(picks)]

    # --- movers ---------------------------------------------------------
    gain = mv.get("gainers", [])[:4]
    lose = mv.get("losers", [])[:4]
    while len(gain) < 4:
        gain.append({"symbol": "-", "chg_pct": 0.0})
    while len(lose) < 4:
        lose.append({"symbol": "-", "chg_pct": 0.0})

    def mover_name(sym):
        return NIFTY50_NAMES.get(sym, sym)

    # --- levels ---------------------------------------------------------
    nsup, nres = on50.get("max_put_oi_strike"), on50.get("max_call_oi_strike")
    bclose, bpivot = bank["close"], obnk.get("max_pain")

    # --- CTA stats (match slide 2) --------------------------------------
    cta_stats = [
        ("Nifty close", f"{nifty['close']:,.0f} · {signed(nifty['pct_chg'], 2)}",
         up_down(nifty["pct_chg"])),
        ("India VIX", fnum(vix["close"]), up_down(vix["pct_chg"])),
        ("FII net", cash_short(fii), up_down(fii if fii is not None else 0)),
        ("DII net", cash_short(dii), up_down(dii if dii is not None else 0)),
    ]

    why = (prose.get("why") or [])[:4]
    while len(why) < 4:
        why.append({"emoji": "•", "title": "", "desc": "", "badge": ""})
    lessons = (prose.get("lessons") or [])[:4]
    while len(lessons) < 4:
        lessons.append("")

    model = {
        "PAGEHEAD_DATE": f"{wd.capitalize()}, {tdate.day} {MONTHS[tdate.month - 1]} {tdate.year}",
        "DATE_PILL": f"{wd} · {MONTHS[tdate.month - 1]} {tdate.day}, {tdate.year}",
        "HEADLINE": hl(prose.get("headline")),
        "SUBLINE": prose.get("subline") or "",
        "STAT_PILL_CLASS": stat_class,
        "STAT_DOT_CLASS": stat_class,
        "STAT_PILL_TEXT": cover_pill,
        # snapshot
        "IDX1_NAME": cards[0][0], "IDX1_VAL": fnum(cards[0][1]), "IDX1_CLASS": up_down(cards[0][2]), "IDX1_CHG": pct_text(cards[0][2]),
        "IDX2_NAME": cards[1][0], "IDX2_VAL": fnum(cards[1][1]), "IDX2_CLASS": up_down(cards[1][2]), "IDX2_CHG": pct_text(cards[1][2]),
        "IDX3_NAME": cards[2][0], "IDX3_VAL": fnum(cards[2][1]), "IDX3_CLASS": up_down(cards[2][2]), "IDX3_CHG": pct_text(cards[2][2]),
        "T1_LABEL": tiles[0][0], "T1_VAL": tiles[0][1], "T1_CLASS": tiles[0][2], "T1_NOTE": tiles[0][3],
        "T2_LABEL": tiles[1][0], "T2_VAL": tiles[1][1], "T2_CLASS": tiles[1][2], "T2_NOTE": tiles[1][3],
        "T3_LABEL": tiles[2][0], "T3_VAL": tiles[2][1], "T3_CLASS": tiles[2][2], "T3_NOTE": tiles[2][3],
        "T4_LABEL": tiles[3][0], "T4_VAL": tiles[3][1], "T4_CLASS": tiles[3][2], "T4_NOTE": tiles[3][3],
        "HERO_TEXT": prose.get("hero_text") or "",
        # why
        "WHY_HEAD": prose.get("why_head") or "Why the market moved",
        "WHY1_EMOJI": why[0]["emoji"], "WHY1_TITLE": why[0]["title"], "WHY1_DESC": why[0]["desc"], "WHY1_BADGE": why[0]["badge"],
        "WHY2_EMOJI": why[1]["emoji"], "WHY2_TITLE": why[1]["title"], "WHY2_DESC": why[1]["desc"], "WHY2_BADGE": why[1]["badge"],
        "WHY3_EMOJI": why[2]["emoji"], "WHY3_TITLE": why[2]["title"], "WHY3_DESC": why[2]["desc"], "WHY3_BADGE": why[2]["badge"],
        "WHY4_EMOJI": why[3]["emoji"], "WHY4_TITLE": why[3]["title"], "WHY4_DESC": why[3]["desc"], "WHY4_BADGE": why[3]["badge"],
        # sectors
        "SEC1_NAME": secs[0][0], "SEC1_CLASS": secs[0][1], "SEC1_REASON": secs[0][2], "SEC1_PCT": secs[0][3],
        "SEC2_NAME": secs[1][0], "SEC2_CLASS": secs[1][1], "SEC2_REASON": secs[1][2], "SEC2_PCT": secs[1][3],
        "SEC3_NAME": secs[2][0], "SEC3_CLASS": secs[2][1], "SEC3_REASON": secs[2][2], "SEC3_PCT": secs[2][3],
        "SEC4_NAME": secs[3][0], "SEC4_CLASS": secs[3][1], "SEC4_REASON": secs[3][2], "SEC4_PCT": secs[3][3],
        "SEC5_NAME": secs[4][0], "SEC5_CLASS": secs[4][1], "SEC5_REASON": secs[4][2], "SEC5_PCT": secs[4][3],
        "SEC6_NAME": secs[5][0], "SEC6_CLASS": secs[5][1], "SEC6_REASON": secs[5][2], "SEC6_PCT": secs[5][3],
        "BONUS_TITLE": prose.get("bonus_title") or "Quiet outperformers",
        "BONUS_TEXT": prose.get("bonus_text") or "",
        # movers
        "G1_NAME": mover_name(gain[0]["symbol"]), "G1_PCT": signed(gain[0]["chg_pct"]),
        "G2_NAME": mover_name(gain[1]["symbol"]), "G2_PCT": signed(gain[1]["chg_pct"]),
        "G3_NAME": mover_name(gain[2]["symbol"]), "G3_PCT": signed(gain[2]["chg_pct"]),
        "G4_NAME": mover_name(gain[3]["symbol"]), "G4_PCT": signed(gain[3]["chg_pct"]),
        "L1_NAME": mover_name(lose[0]["symbol"]), "L1_PCT": signed(lose[0]["chg_pct"]),
        "L2_NAME": mover_name(lose[1]["symbol"]), "L2_PCT": signed(lose[1]["chg_pct"]),
        "L3_NAME": mover_name(lose[2]["symbol"]), "L3_PCT": signed(lose[2]["chg_pct"]),
        "L4_NAME": mover_name(lose[3]["symbol"]), "L4_PCT": signed(lose[3]["chg_pct"]),
        "MOVERS_NOTE_GAINERS": prose.get("movers_note_gainers") or "",
        "MOVERS_NOTE_LOSERS": prose.get("movers_note_losers") or "",
        # levels
        "LVL_NIFTY_CLOSE": fnum(nifty["close"]),
        "LVL_SUPPORT": f"{nsup:,.0f}" if nsup else "-",
        "LVL_MAXPAIN": f"{on50.get('max_pain'):,.0f}" if on50.get("max_pain") else "-",
        "LVL_RESISTANCE": f"{nres:,.0f}" if nres else "-",
        "NIFTY_SUPPORT": f"{nsup:,.0f}" if nsup else "-",
        "NIFTY_RESISTANCE": f"{nres:,.0f}" if nres else "-",
        "BANK_CLOSE": fnum(bclose),
        "BANK_PIVOT": f"{bpivot:,.0f}" if bpivot else "-",
        "WATCH_TEXT": prose.get("watch_text") or "",
        # lessons
        "LESSON1": lessons[0], "LESSON2": lessons[1],
        "LESSON3": lessons[2], "LESSON4": lessons[3],
        "ALERT_TITLE": prose.get("alert_title") or "Watch tomorrow",
        "ALERT_TEXT": prose.get("alert_text") or "",
        # CTA
        "CTA_HEADLINE": hl(prose.get("cta_headline")),
        "CTA_SUB": prose.get("cta_sub") or "",
        "CS1_LABEL": cta_stats[0][0], "CS1_VAL": cta_stats[0][1], "CS1_CLASS": cta_stats[0][2],
        "CS2_LABEL": cta_stats[1][0], "CS2_VAL": cta_stats[1][1], "CS2_CLASS": cta_stats[1][2],
        "CS3_LABEL": cta_stats[2][0], "CS3_VAL": cta_stats[2][1], "CS3_CLASS": cta_stats[2][2],
        "CS4_LABEL": cta_stats[3][0], "CS4_VAL": cta_stats[3][1], "CS4_CLASS": cta_stats[3][2],
        "NEXT_TEXT": prose.get("next_text") or "",
        # captions (JS strings)
        "CAPTION_A": json.dumps(prose.get("caption_a") or ""),
        "CAPTION_B": json.dumps(prose.get("caption_b") or ""),
        "DL_PREFIX": f"stockpulse-postmarket-{tdate.day}{MONTHS_SHORT[tdate.month - 1]}-",
    }

    html = open(TEMPLATE, encoding="utf-8").read()
    for k, v in model.items():
        html = html.replace("{{" + k + "}}", str(v))
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
    return html, leftover


def validate(html, pack):
    """Structural + house-style checks. Returns list of issues."""
    issues = []
    slides = re.findall(r'class="slide (dark|light)" id="slide\d"', html)
    if len(slides) != 8:
        issues.append(f"expected 8 slides, found {len(slides)}")
    if html.count("Download PNG") != 8:
        issues.append("expected 8 download buttons")
    if '>Stock</span><spanstyle="color:#F97316">Pulse</span>' not in html.replace(" ", ""):
        issues.append("wordmark missing")
    if "Not investment advice." not in html:
        issues.append("disclaimer missing on slide 8")
    issues += compliance.lint(html, kind="carousel")
    return issues
