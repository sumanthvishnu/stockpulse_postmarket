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


# Emoji per sector, used by the deterministic fallback so even a no-LLM run
# gets iconography that matches the actual day's drivers.
SECTOR_EMOJI = {
    "IT": "💻", "Bank": "🏦", "Financials": "💳", "Auto": "🚗",
    "Metal": "🏭", "FMCG": "🧴", "Realty": "🏠", "Pharma": "💊",
    "Healthcare": "🏥", "Energy": "⚡", "Oil & Gas": "🛢️",
    "PSU Bank": "🏛️", "Private Bank": "🏦", "Media": "📡",
    "Consumer Durables": "🛋️", "Infra": "🏗️",
}


# ------------------------------------------------------------- day facts ---
def day_facts(pack):
    """Deterministic narrative facts computed from the locked datapack.

    Shared by the story-brief fallback (pipeline.deterministic_brief) and the
    carousel fallback prose, so a no-LLM run still tells THAT day's story -
    computed from real numbers, never a static canned text."""
    d = pack["derived"]
    idx = d["indices"]
    nifty = idx["Nifty 50"]
    gm = d.get("global_markets", {}).get("markets", {})
    breadth = d["breadth"]
    cash = d.get("fii_dii_cash_summary") or {}
    f5 = d.get("five_day_change_pct") or {}

    present = [(k, idx[k]["pct_chg"]) for k in SECTORAL
               if k in idx and idx[k].get("pct_chg") is not None]
    present.sort(key=lambda x: -x[1])

    def short(name):
        return SECTOR_SHORT.get(name, name.replace("Nifty ", ""))

    mv = d.get("nifty50_movers") or {}

    def _names(rows):
        out = []
        for row in (rows or [])[:2]:
            sym = row.get("symbol")
            if sym and sym != "-":
                out.append(NIFTY50_NAMES.get(sym, sym))
        return out

    return {
        "nifty_close": nifty["close"], "nifty_pct": nifty["pct_chg"],
        "nifty_pts": nifty["pts_chg"], "nifty_up": (nifty["pct_chg"] or 0) >= 0,
        "bank_pct": idx["Nifty Bank"]["pct_chg"],
        "vix": d.get("vix", {}).get("current"),
        "vix_pct": idx.get("India VIX", {}).get("pct_chg"),
        "sensex_pct": (gm.get("Sensex") or {}).get("pct_chg"),
        "small_pct": _idx_pct(idx, "Nifty Smallcap 250"),
        "mid_pct": _idx_pct(idx, "Nifty Midcap 150"),
        "advances": breadth["advances"], "declines": breadth["declines"],
        "breadth_pos": breadth["advances"] >= breadth["declines"],
        "fii": cash.get("fii_net_cr"), "dii": cash.get("dii_net_cr"),
        "top_sectors": [(short(n), p) for n, p in present[:3]],
        "bottom_sectors": [(short(n), p) for n, p in present[-3:][::-1]],
        "streak": d.get("nifty_streak") or {},
        "week_pct": f5.get("Nifty 50"),
        "support": (d.get("options_NIFTY") or {}).get("max_put_oi_strike"),
        "resistance": (d.get("options_NIFTY") or {}).get("max_call_oi_strike"),
        "nifty_expiry": (d.get("options_NIFTY") or {}).get("expiry"),
        "gainer_names": _names(mv.get("gainers")),
        "loser_names": _names(mv.get("losers")),
    }


def _flows_line(f):
    """Human phrase for the FII/DII combination."""
    fii, dii = f["fii"], f["dii"]
    if fii is None and dii is None:
        return "Flow data was unavailable"
    if fii is not None and dii is not None:
        if fii >= 0 and dii >= 0:
            return "FII and DII both bought"
        if fii < 0 and dii < 0:
            return "FII and DII both sold"
        return ("FII bought while DII sold" if fii >= 0
                else "FII sold while DII bought")
    who = "FII" if fii is not None else "DII"
    v = fii if fii is not None else dii
    return f"{who} were net {'buyers' if v >= 0 else 'sellers'}"


def _idx_pct(idx, name):
    row = idx.get(name) or {}
    return row.get("pct_chg")


def next_session(pack):
    """Next-session facts from the pack, with the weekend fallback."""
    s = (pack.get("derived") or {}).get("next_trading_session")
    if isinstance(s, dict) and s.get("weekday"):
        return s
    return compliance._weekend_next_session(pack)


def sector_board(pack, weekly=False):
    """The six sector rows the slide will show: top 3 then bottom 3.

    Returns (full_name, short_name, pct) in display order. Weekly edition
    ranks by five-day change when those values exist."""
    d = pack.get("derived") or {}
    idx = d.get("indices") or {}
    f5 = d.get("five_day_change_pct") or {}
    if weekly and any(k in f5 for k in SECTORAL):
        present = [(k, f5[k]) for k in SECTORAL if f5.get(k) is not None]
    else:
        present = [(k, idx[k]["pct_chg"]) for k in SECTORAL
                   if k in idx and idx[k].get("pct_chg") is not None]
    present.sort(key=lambda x: -x[1])
    if len(present) >= 6:
        picks = present[:3] + present[-3:][::-1]
    else:
        picks = present
    out = []
    for name, pct in picks:
        short = SECTOR_SHORT.get(name, name.replace("Nifty ", ""))
        out.append((name, short, pct))
    return out


# Models routinely key sector_reasons with the full index name ("Nifty IT")
# or a near-alias. The renderer looks up the SHORT name ("IT"). This table
# is the single contract for both.
_SECTOR_ALIAS = {}
for _full, _short in SECTOR_SHORT.items():
    _SECTOR_ALIAS[_full.lower()] = _short
    _SECTOR_ALIAS[_short.lower()] = _short
    _SECTOR_ALIAS[_full.lower().replace("nifty ", "", 1)] = _short
_SECTOR_ALIAS.update({
    "information technology": "IT",
    "it services": "IT",
    "banks": "Bank",
    "banking": "Bank",
    "bank nifty": "Bank",
    "financial services": "Financials",
    "financial service": "Financials",
    "automobile": "Auto",
    "automobiles": "Auto",
    "metals": "Metal",
    "real estate": "Realty",
    "pharmaceutical": "Pharma",
    "pharmaceuticals": "Pharma",
    "healthcare index": "Healthcare",
    "oil and gas": "Oil & Gas",
    "oil gas": "Oil & Gas",
    "psu banks": "PSU Bank",
    "private banks": "Private Bank",
    "consumer durable": "Consumer Durables",
    "infrastructure": "Infra",
})


def normalize_sector_key(key):
    """Map a model-written sector label onto the short name, or None.

    Unknown labels (Nifty Midcap 150, Nifty INR, Nifty Health) are dropped
    rather than guessed."""
    if not isinstance(key, str):
        return None
    low = re.sub(r"\s+", " ", key).strip().strip(" .:").lower()
    if low in _SECTOR_ALIAS:
        return _SECTOR_ALIAS[low]
    if low.startswith("nifty "):
        return _SECTOR_ALIAS.get(low[6:].strip())
    return None


def normalize_sector_reasons(reasons):
    """Return sector_reasons keyed only by short names.

    An already-short key wins over a 'Nifty …' alias for the same sector.
    Blank and unknown keys are dropped."""
    if not isinstance(reasons, dict):
        return {}
    out, rank = {}, {}
    for key, val in reasons.items():
        short = normalize_sector_key(key)
        if not short or not isinstance(val, str) or not val.strip():
            continue
        pref = 2 if key.strip().lower() == short.lower() else 1
        if short in out and pref <= rank.get(short, 0):
            continue
        out[short] = val.strip()
        rank[short] = pref
    return out


_RANK_STUBS = {
    "strongest sector", "second strongest", "third strongest",
    "biggest drag", "second weakest", "weakest sector",
    "led the day", "lagged the day",
}

# Phrases that showed up as the entire sector note when the model had nothing
# causal to say. A reason that is only one of these is not shippable.
FILLER_REASON = re.compile(
    r"\b(global cues|market sentiment|volatile markets|sector-specific|"
    r"risk-off sentiment|broader market)\b",
    re.I,
)


def is_rank_stub(text):
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower().rstrip(".")
    return t in _RANK_STUBS


def computed_sector_reason(short, pct, i):
    """Day-specific sector note from the locked percent. Used when the model
    omits a key or writes a rank stub. States the relative move, not a label
    like 'strongest sector'."""
    if pct is None:
        return "Move unavailable for this session."
    if abs(pct) < 0.2:
        return f"Nearly flat, closed {pct:+.2f}%."
    if i == 0:
        if pct >= 0:
            return f"Led the session, closed {pct:+.2f}%."
        return f"Smallest loss, closed {pct:+.2f}%."
    if i < 3:
        if pct >= 0:
            return f"Firm beside the leader, {pct:+.2f}%."
        return f"Held up better than most, {pct:+.2f}%."
    if i == 3:
        if pct < 0:
            return f"Deepest loss, closed {pct:+.2f}%."
        return f"Smallest gain, closed {pct:+.2f}%."
    if pct < 0:
        return f"Lagged the tape, closed {pct:+.2f}%."
    return f"Trailed the leaders, {pct:+.2f}%."


def snapshot_emphasis(pack, weekly=False):
    """Pick a snapshot label and bonus framing the datapack actually supports.

    The 8-slide chrome stays put. Only the existing hero label and the
    fallback bonus copy change, so two different sessions do not wear the
    same 'THE DAY IN ONE LINE' emphasis when the tape says otherwise."""
    f = day_facts(pack)
    nifty = f["nifty_pct"] if f["nifty_pct"] is not None else 0.0
    small, mid = f.get("small_pct"), f.get("mid_pct")
    gap = None
    if small is not None:
        gap = small - nifty
    elif mid is not None:
        gap = mid - nifty
    vix = f.get("vix_pct")
    fii, dii = f.get("fii"), f.get("dii")
    flows_split = (fii is not None and dii is not None and (fii * dii) < 0
                   and abs(fii) >= 100 and abs(dii) >= 100)
    fear = vix is not None and abs(vix) >= 5
    broader = gap is not None and abs(gap) >= 0.75
    top = f["top_sectors"][0][0] if f["top_sectors"] else "Leaders"
    bot = f["bottom_sectors"][0][0] if f["bottom_sectors"] else "Laggards"

    if weekly:
        hero_label = "THE WEEK IN ONE LINE"
    elif broader:
        hero_label = "THE BROADER MARKET"
    elif fear:
        hero_label = "THE FEAR GAUGE"
    elif flows_split:
        hero_label = "THE FLOW SPLIT"
    else:
        hero_label = "THE DAY IN ONE LINE"

    # Candidates in priority order. The bonus takes the first angle that is
    # not already the snapshot label, so a fear day does not also wear a
    # fear card when flows or breadth can carry the sector slide.
    candidates = []
    if broader:
        candidates.append((
            "THE SPLIT",
            f"{top} carried the board. {bot} was the pocket that lagged.",
            "The broader tape diverged from Nifty. hero_text should say so. "
            "If the bonus is THE SPLIT, name the leading and lagging sectors.",
        ))
    if fear:
        way = "fell" if vix < 0 else "jumped"
        candidates.append((
            "FEAR CHECK",
            f"India VIX {way} {abs(vix):.2f}% on the session.",
            "India VIX moved hard. hero_text should say whether fear rose "
            "or fell. Use the locked VIX change, not a slogan.",
        ))
    if flows_split:
        candidates.append((
            "THE FLOWS",
            _flows_line(f) + ".",
            "FII and DII cash pointed opposite ways. One of hero_text or "
            "the bonus should name that split.",
        ))
    candidates.append((
        "BREADTH CHECK",
        f"{f['advances']:,} stocks rose and {f['declines']:,} fell.",
        "Keep the snapshot on the close, and let the bonus state the "
        "advance/decline split.",
    ))
    hero_twin = {
        "THE BROADER MARKET": "THE SPLIT",
        "THE FEAR GAUGE": "FEAR CHECK",
        "THE FLOW SPLIT": "THE FLOWS",
    }.get(hero_label)
    bonus_title, bonus_text, hint = next(
        (c for c in candidates if c[0] != hero_twin), candidates[0])
    return {
        "hero_label": hero_label,
        "bonus_title": bonus_title,
        "bonus_text": bonus_text,
        "hint": hint,
        "broader": broader,
        "fear": fear,
        "flows_split": flows_split,
    }


# ------------------------------------------------------------- prose model --
def _breadth_lesson(f):
    adv, dec = f["advances"] or 0, f["declines"] or 0
    if adv >= 2 and dec >= 1 and adv >= dec:
        n = int(round(adv / dec))
        if n >= 2:
            return (f"Breadth backed the move. About {n} stocks rose "
                    f"for every 1 that fell.")
        return "Breadth was only slightly positive. The index did not run alone."
    if dec >= 2 and adv >= 1 and dec > adv:
        n = int(round(dec / adv))
        if n >= 2:
            return (f"Breadth was the tell. About {n} stocks fell "
                    f"for every 1 that rose.")
        return "Breadth was only slightly negative. The decline was narrow."
    return "Breadth was too thin to pick a side."


def _broader_lesson(f):
    nifty = f["nifty_pct"] if f["nifty_pct"] is not None else 0.0
    small, mid = f.get("small_pct"), f.get("mid_pct")
    if small is not None and abs(small - nifty) >= 0.75:
        if small > nifty:
            return ("The broader market led. Smallcaps finished ahead "
                    "of the frontline.")
        return "The frontline held up. Smallcaps finished behind Nifty."
    if mid is not None and abs(mid - nifty) >= 0.75:
        if mid > nifty:
            return ("Midcaps ran ahead. The move was wider than the "
                    "Nifty close.")
        return "Midcaps lagged. The frontline did not speak for the tape."
    return "The frontline and the broader market finished on the same side."


def _flows_lesson(f):
    line = _flows_line(f)
    if "both bought" in line or "both sold" in line:
        return f"Cash flows agreed. {line}."
    if "while" in line:
        return f"{line}. The cash tape was split."
    return line + "."


def _sector_lesson(f):
    if not f["top_sectors"] or not f["bottom_sectors"]:
        return "Leadership was hard to separate from the index."
    top, bot = f["top_sectors"][0][0], f["bottom_sectors"][0][0]
    return f"One pocket lagged the rest. {bot} trailed while {top} led."


def _streak_lesson(f):
    streak = f.get("streak") or {}
    sessions = streak.get("sessions") or 0
    direction = streak.get("direction")
    if sessions >= 3 and direction in ("up", "down"):
        return f"The {direction} close extended a {sessions} session run."
    return None


def _pair_note(names, side):
    if len(names) >= 2:
        return f"{names[0]} and {names[1]} led the {side}."
    if names:
        return f"{names[0]} led the {side}."
    return f"The {side} list was thin."


def _session_bits(pack):
    s = next_session(pack)
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    weekday = s.get("weekday") or "the next session"
    label = s.get("label") or weekday
    # "Monday, 21 September 2026" -> "Monday 21 September"
    short_label = re.sub(r",", "", label)
    short_label = re.sub(r"\s+\d{4}$", "", short_label).strip()
    expiry_note = ""
    exp = (pack.get("derived") or {}).get("options_NIFTY", {}).get("expiry")
    if isinstance(exp, str) and len(exp) >= 10:
        try:
            ed = date.fromisoformat(exp[:10])
        except ValueError:
            ed = None
        if ed is not None and 0 <= (ed - tdate).days <= 6:
            expiry_note = f"Nifty expiry lands {ed.strftime('%A')}."
    return weekday, short_label, expiry_note


def fallback_prose(pack, weekly=False):
    """Computed-from-the-pack prose for a no-LLM run.

    Every line names something true of THIS session (a contrast, a sector,
    a flow split, the next weekday). Static filler such as 'Gainers closed
    firm' or 'Stay informed' is not used."""
    f = day_facts(pack)
    emphasis = snapshot_emphasis(pack, weekly=weekly)
    top1 = f["top_sectors"][0] if f["top_sectors"] else ("the leaders", 0.0)
    bot1 = f["bottom_sectors"][0] if f["bottom_sectors"] else ("the laggards", 0.0)
    weekday, short_label, expiry_note = _session_bits(pack)
    wk = f["week_pct"]
    nifty_pct = f["nifty_pct"] or 0.0

    if weekly and wk is not None and (wk >= 0) != (nifty_pct >= 0):
        headline = ("The week fell while *Friday closed higher*"
                    if wk < 0 else
                    "The week rose while *Friday closed lower*")
        hero_text = (f"Nifty {'lost' if wk < 0 else 'gained'} {abs(wk):.2f}% "
                     f"on the week, yet Friday closed "
                     f"{'up' if nifty_pct >= 0 else 'down'} {abs(nifty_pct):.2f}%.")
    elif emphasis["broader"] and nifty_pct >= 0 and (f.get("small_pct") or 0) > nifty_pct:
        headline = "Nifty rose while the *broader market ran ahead*"
        hero_text = (f"Smallcaps led. Nifty closed up {abs(nifty_pct):.2f}% "
                     f"at {fnum(f['nifty_close'])}, behind the broader tape.")
    elif emphasis["broader"] and nifty_pct < 0 and (f.get("small_pct") or 0) > nifty_pct:
        headline = "Nifty fell while *smallcaps held up*"
        hero_text = (f"Nifty closed down {abs(nifty_pct):.2f}% at "
                     f"{fnum(f['nifty_close'])}. Smallcaps finished ahead of it.")
    elif emphasis["broader"] and nifty_pct >= 0:
        headline = "Nifty rose while the *broader market lagged*"
        hero_text = (f"Nifty closed up {abs(nifty_pct):.2f}% at "
                     f"{fnum(f['nifty_close'])}. The broader tape did not follow.")
    elif emphasis["broader"]:
        headline = "Nifty fell and the *broader market fell harder*"
        hero_text = (f"Nifty closed down {abs(nifty_pct):.2f}% at "
                     f"{fnum(f['nifty_close'])}. Smallcaps finished weaker still.")
    elif emphasis["fear"]:
        jumped = (f.get("vix_pct") or 0) >= 0
        if emphasis["flows_split"]:
            headline = ("Fear jumped while the *flows stayed split*" if jumped
                        else "Fear fell while the *flows stayed split*")
        elif f["nifty_up"]:
            headline = ("Nifty rose even as *fear jumped*" if jumped
                        else "Nifty rose as *fear fell hard*")
        else:
            headline = ("Nifty fell as *fear jumped*" if jumped
                        else "Nifty fell even as *fear fell*")
        hero_text = (f"Nifty closed {'up' if f['nifty_up'] else 'down'} "
                     f"{abs(nifty_pct):.2f}% at {fnum(f['nifty_close'])}. "
                     f"India VIX {'rose' if jumped else 'fell'} "
                     f"{abs(f.get('vix_pct') or 0):.2f}%.")
    elif emphasis["flows_split"]:
        headline = (f"Nifty closed {'up' if f['nifty_up'] else 'down'} "
                    f"on a *split in the flows*")
        hero_text = (f"Nifty closed {'up' if f['nifty_up'] else 'down'} "
                     f"{abs(nifty_pct):.2f}% at {fnum(f['nifty_close'])}. "
                     f"{_flows_line(f)}.")
    else:
        headline = (f"*Nifty* closed {'up' if f['nifty_up'] else 'down'} "
                    f"as {top1[0]} {'led' if (top1[1] or 0) >= 0 else 'held up'}.")
        hero_text = (f"Nifty closed {'up' if f['nifty_up'] else 'down'} "
                     f"{abs(nifty_pct):.2f}% at {fnum(f['nifty_close'])}. "
                     f"{top1[0]} led while {bot1[0]} lagged.")

    if emphasis["fear"] and (f.get("vix_pct") or 0) < 0:
        subline = f"{top1[0]} led the tape. Fear fell hard."
    elif emphasis["fear"]:
        subline = f"{top1[0]} led the tape. Fear jumped."
    elif emphasis["broader"]:
        subline = "Midcaps and smallcaps led. Breadth stayed with the move."
    else:
        br = "positive" if f["breadth_pos"] else "weak"
        subline = f"{_flows_line(f)}. Breadth stayed {br}."

    why = []
    for i, (name, pct) in enumerate(f["top_sectors"][:2]):
        kind = "led" if (pct or 0) >= 0 else "held up"
        why.append({
            "emoji": SECTOR_EMOJI.get(name, "📈"),
            "title": f"{name} {kind}",
            "desc": computed_sector_reason(name, pct, i),
            "badge": f"{name} {pct:+.2f}%",
        })
    if f["bottom_sectors"]:
        name, pct = f["bottom_sectors"][0]
        why.append({
            "emoji": SECTOR_EMOJI.get(name, "📉"),
            "title": f"{name} lagged",
            "desc": computed_sector_reason(name, pct, 3),
            "badge": f"{name} {pct:+.2f}%",
        })
    br_word = "positive" if f["breadth_pos"] else "weak"
    why.append({
        "emoji": "📊",
        "title": f"Breadth stayed {br_word}",
        "desc": ("More names rose than fell." if f["breadth_pos"]
                 else "More names fell than rose."),
        "badge": f"{f['advances']:,} : {f['declines']:,}",
    })
    why = why[:4]

    lessons = [_breadth_lesson(f), _broader_lesson(f), _flows_lesson(f)]
    streak_lesson = _streak_lesson(f)
    lessons.append(streak_lesson or _sector_lesson(f))
    lessons = lessons[:4]

    reasons = {}
    for i, (_full, short, pct) in enumerate(sector_board(pack, weekly=weekly)):
        reasons[short] = computed_sector_reason(short, pct, i)

    if f["support"] and f["resistance"]:
        watch = (f"Support at {f['support']:,.0f} and resistance at "
                 f"{f['resistance']:,.0f} frame {weekday}'s open.")
    else:
        watch = f"The option chain levels frame {weekday}'s open."

    if f["nifty_up"] and f["breadth_pos"] and emphasis["broader"]:
        tone = "A broad up day"
    elif (not f["nifty_up"]) and (not f["breadth_pos"]):
        tone = "A down day"
    else:
        tone = "A split close"
    cta_headline = f"{tone}. *Save it for the open*."
    cta_sub = f"Full wrap every evening. Next bell is {weekday}."
    alert_text = f"{short_label} opens next."
    if expiry_note:
        alert_text = f"{short_label} opens next. {expiry_note}"
    next_text = f"Next bell is {weekday}."
    if expiry_note:
        next_text = f"Next bell is {weekday}. {expiry_note}"

    dirw = "up" if f["nifty_up"] else "down"
    pct_s = f"{abs(nifty_pct):.2f}%"
    tag = re.sub(r"[^A-Za-z0-9]", "", top1[0]) or "Market"
    caption_a = (
        f"Nifty closed {dirw} {pct_s} at {fnum(f['nifty_close'])}, "
        f"while {top1[0]} led and {bot1[0]} lagged.\n\n"
        f"Breadth: {f['advances']:,} advances vs {f['declines']:,} declines.\n\n"
        f"Daily wrap every evening @getstockpulse\n\n"
        f"Not investment advice.\n\n"
        f"#Nifty #IndianStockMarket #Nifty{tag} #MarketWrap #Sensex"
    )
    caption_b = (
        f"{_flows_line(f)}.\n\n"
        f"Watch {weekday}'s open. {top1[0]} led the sectors.\n\n"
        f"Daily wrap every evening @getstockpulse\n\n"
        f"Not investment advice.\n\n"
        f"#Nifty #IndianStockMarket #BankNifty #MarketWrap #FII"
    )

    return {
        "headline": headline,
        "subline": subline,
        "hero_text": hero_text,
        "why_head": ("Why the week closed this way" if weekly
                     else ("Why the market rose" if f["nifty_up"]
                           else "Why the market fell")),
        "why": why,
        "sector_reasons": reasons,
        "bonus_title": emphasis["bonus_title"],
        "bonus_text": emphasis["bonus_text"],
        "movers_note_gainers": _pair_note(f["gainer_names"], "gainers"),
        "movers_note_losers": _pair_note(f["loser_names"], "losers"),
        "watch_text": watch,
        "lessons": lessons,
        "alert_title": "Next up",
        "alert_text": alert_text,
        "cta_headline": cta_headline,
        "cta_sub": cta_sub,
        "next_text": next_text,
        "caption_a": caption_a,
        "caption_b": caption_b,
    }


def _blank(value):
    return value is None or value == "" or value == [] or value == {}


def finalize_prose(pack, prose, weekly=False):
    """Fill gaps from the datapack fallback, then force short sector keys.

    A missing field used to inherit mock canned copy ('Gainers closed firm',
    'Stay informed'). Those strings never ship. Rank-stub and filler sector
    notes are replaced with the computed line for that sector's own percent."""
    base = fallback_prose(pack, weekly=weekly)
    out = dict(base)
    for key, val in (prose or {}).items():
        if key == "sector_reasons":
            continue
        if _blank(val):
            continue
        if key == "why" and isinstance(val, list):
            rows = [r for r in val if isinstance(r, dict) and r.get("title")]
            if not rows:
                continue
            if len(rows) < 4:
                rows = (rows + base["why"])[:4]
            out["why"] = rows[:4]
            continue
        if key == "lessons" and isinstance(val, list):
            rows = [x for x in val if isinstance(x, str) and x.strip()]
            if not rows:
                continue
            if len(rows) < 4:
                rows = (rows + base["lessons"])[:4]
            out["lessons"] = rows[:4]
            continue
        out[key] = val
    reasons = normalize_sector_reasons((prose or {}).get("sector_reasons"))
    if not reasons:
        reasons = dict(base["sector_reasons"])
    for i, (_full, short, pct) in enumerate(sector_board(pack, weekly=weekly)):
        text = reasons.get(short) or ""
        if (not text.strip()) or is_rank_stub(text) or FILLER_REASON.search(text):
            reasons[short] = computed_sector_reason(short, pct, i)
    out["sector_reasons"] = reasons
    return out


# ------------------------------------------------------------------- build --
def build(pack, prose, weekly=False):
    d = pack["derived"]
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    # Gaps are filled from today's datapack. A missing key must not inherit
    # a static line ("Gainers closed firm", "Stay informed", "strongest sector").
    prose = finalize_prose(pack, prose, weekly=weekly)
    wd = WDAYS[tdate.weekday()]
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

    def cash_note(v, pos, neg):
        return "n/a" if v is None else (pos if v >= 0 else neg)

    # --- cover ----------------------------------------------------------
    stat_class = up_down(nifty["pct_chg"])
    cover_pill = (f"Nifty {fnum(nifty['close'])} · "
                  f"{chg_word(nifty['pct_chg'])} "
                  f"{abs(nifty['pts_chg']):.2f} pts "
                  f"({abs(nifty['pct_chg']):.2f}%)")
    week_pct = (d.get("five_day_change_pct") or {}).get("Nifty 50")
    if weekly and week_pct is not None:
        cover_pill += f" · week {week_pct:+.2f}%"

    # --- weekly-wrap header labels (Friday edition) ----------------------
    headers = {
        "BANNER_TITLE": "WEEKLY MARKET WRAP" if weekly else "POST MARKET ANALYSIS",
        "S2_TITLE": "Where the market closed",
        "HERO_LABEL": "THE WEEK IN ONE LINE" if weekly else "THE DAY IN ONE LINE",
        "S4_TITLE": "The week by sector" if weekly else "Sector scorecard",
        "S5_TITLE": ("Friday's big movers" if weekly
                     else "The day's big movers"),
        "S6_TITLE": "Levels that matter",
        "S7_TITLE": ("What this week taught us" if weekly
                     else "What today taught us"),
    }
    date_pill = (f"WEEKLY WRAP · {MONTHS_SHORT[tdate.month - 1]} "
                 f"{tdate.day}, {tdate.year}" if weekly else
                 f"{wd} · {MONTHS[tdate.month - 1]} {tdate.day}, {tdate.year}")

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
        ("FII net (cash)", cash_s(fii), up_down(fii),
         cash_note(fii, "foreign inflows", "foreign outflows")),
        ("DII net (cash)", cash_s(dii), up_down(dii),
         cash_note(dii, "domestic inflows", "domestic outflows")),
    ]

    # --- sectors (top 3 + bottom 3; weekly edition ranks by 5-day move) ---
    board = sector_board(pack, weekly=weekly)
    reasons = prose.get("sector_reasons") or {}
    emphasis = snapshot_emphasis(pack, weekly=weekly)
    headers["HERO_LABEL"] = emphasis["hero_label"]

    def sec_row(name, pct, i):
        short = SECTOR_SHORT.get(name, name.replace("Nifty ", ""))
        reason = reasons.get(short) or ""
        if (not reason.strip()) or is_rank_stub(reason) or FILLER_REASON.search(reason):
            reason = computed_sector_reason(short, pct, i)
        return short, up_down(pct), reason, signed(pct)

    secs = [sec_row(n, p, i) for i, (_full, n, p) in enumerate(board)]
    while len(secs) < 6:
        secs.append(("-", "flat", "Move unavailable for this session.", "n/a"))

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
        "PAGE_TITLE_DATE": (f"{tdate.day} {MONTHS_SHORT[tdate.month - 1].title()} "
                            f"{tdate.year}"),
        "PAGEHEAD_DATE": f"{wd.capitalize()}, {tdate.day} {MONTHS[tdate.month - 1]} {tdate.year}",
        "DATE_PILL": date_pill,
        **headers,
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
        "ALERT_TITLE": prose.get("alert_title") or "Watch the next session",
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
        "DL_PREFIX": (f"stockpulse-weeklywrap-{tdate.day}{MONTHS_SHORT[tdate.month - 1]}-"
                      if weekly else
                      f"stockpulse-postmarket-{tdate.day}{MONTHS_SHORT[tdate.month - 1]}-"),
    }

    with open(TEMPLATE, encoding="utf-8") as fh:
        html = fh.read()
    for k, v in model.items():
        html = html.replace("{{" + k + "}}", str(v))
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", html)
    return html, leftover


# ------------------------------------------------------- text-fit budgets --
# The slides are a fixed 1080x1080 with clamp guards; these budgets keep the
# LLM inside the space so the clamps never have to fire. Checked in code
# (pipeline feeds violations back into the retry loop), not left to the model.
BUDGETS = {
    "headline": 70, "subline": 90, "hero_text": 150, "why_head": 40,
    "bonus_title": 40, "bonus_text": 120,
    "movers_note_gainers": 110, "movers_note_losers": 110,
    "watch_text": 130, "alert_title": 45, "alert_text": 130,
    "cta_headline": 60, "cta_sub": 90, "next_text": 110,
    "caption_a": 500, "caption_b": 500,
}


def budget_issues(prose):
    """Return one issue per prose field that exceeds its character budget."""
    issues = []
    for field, limit in BUDGETS.items():
        v = str((prose or {}).get(field) or "")
        if len(v) > limit:
            issues.append(f"'{field}' is {len(v)} chars (budget {limit}) - "
                          "shorten it; the slide has fixed space")
    for i, row in enumerate((prose or {}).get("why") or [], 1):
        if len(str(row.get("title", ""))) > 30:
            issues.append(f"why[{i}].title over 30 chars - shorten")
        if len(str(row.get("desc", ""))) > 90:
            issues.append(f"why[{i}].desc over 90 chars - shorten")
        if len(str(row.get("badge", ""))) > 24:
            issues.append(f"why[{i}].badge over 24 chars - shorten")
    for i, l in enumerate((prose or {}).get("lessons") or [], 1):
        if len(str(l)) > 100:
            issues.append(f"lessons[{i}] over 100 chars - shorten")
    for key, text in ((prose or {}).get("sector_reasons") or {}).items():
        if len(str(text)) > 90:
            issues.append(f"sector_reasons[{key}] is {len(str(text))} chars "
                          "(budget 90) - shorten the note")
    # calendar emojis render with 'JULY 17' printed on the glyph on phones
    flat = _flat(prose)
    for e in ("\U0001F4C5", "\U0001F4C6", "\U0001F5D3"):
        if e in flat:
            issues.append(f"calendar emoji {e} renders a printed 'July 17' "
                          "date on phones - pick a different emoji")
    return issues


# Stock phrases that have shipped as if they were written for the day.
# Matched case-insensitively, asterisks ignored, against the prose text.
CANNED_PHRASES = (
    "gainers closed firm into the close",
    "losers stayed under pressure all session",
    "gainers led on steady delivery",
    "losers slipped on light volumes",
    "fresh global cues arrive before the next open",
    "global cues and corporate actions land next session",
    "check back at the close",
    "full picture every evening",
    "a muted session for indian equities",
    "a quiet day for the indices",
    "a few sectors bucked the trend",
    "quiet outperformers",
    "was among the strongest sectors",
    "was the weakest pocket",
    "stay informed",
    "stay updated",
    "daily updates",
    "follow us for concise",
    "a risk-off sentiment gripped",
)

GENERIC_WHY_TITLES = {
    "market downturn", "global pressure", "volatility rise",
    "fii outflows", "market sentiment", "global cues",
    "volatility spike", "dii inflows",
}

AI_WORDS = (
    "worth noting", "furthermore", "moreover", "in conclusion",
    "delve", "leverage", "robust", "pivotal",
    "it is important to highlight",
)

_PCT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent)", re.I)
_RELATION_RE = re.compile(
    r"\b(while|whereas|versus|vs\.?|but|only|ahead|behind|outpac|outran|"
    r"for every|breadth|split|streak|cluster|unlike|held|capped|lagged|"
    r"led|against|together|both|diverg)\b",
    re.I,
)
_CONTRAST_RE = re.compile(
    r"\b(while|but|ahead|behind|versus|vs\.?|outran|outpaced|split|only|as)\b",
    re.I,
)
_EVERGREEN_CTA = re.compile(
    r"stay informed|stay updated|daily updates|follow us for|"
    r"check back at the close|full picture every evening|"
    r"market insights|keep up with daily|track every",
    re.I,
)


def norm_phrase(text):
    t = re.sub(r"[*_]", "", str(text or ""))
    return re.sub(r"\s+", " ", t).strip().lower()


def lesson_skeleton(text):
    """Lesson shape with numbers removed, so 'drop of 1.56%' matches
    'drop of 0.40%'."""
    t = norm_phrase(text)
    t = re.sub(r"\d[\d,]*(?:\.\d+)?", "#", t)
    t = re.sub(r"%|percent", "", t)
    t = re.sub(r"[^a-z# ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def prose_quality_issues(prose, pack, weekly=False, memory=None):
    """Voice and sameness checks. The pipeline feeds these back into the
    carousel retry. Empty list means the prose is allowed to ship.

    Sector keys are normalized first, so 'Nifty IT' counts as 'IT'. Rank
    stubs and filler notes do not count as coverage."""
    issues = []
    prose = prose or {}
    flat_norm = norm_phrase(_flat(prose))
    for phrase in CANNED_PHRASES:
        if phrase in flat_norm:
            issues.append(
                f"canned filler '{phrase}' - replace it with a line that "
                "could only be written for this session")

    for word in AI_WORDS:
        if word in flat_norm:
            issues.append(f"banned AI wording '{word}'")

    headline = str(prose.get("headline") or "")
    h_norm = norm_phrase(headline)
    if "amid global cues" in h_norm:
        issues.append("headline uses the 'amid global cues' cliche - lead "
                      "with today's contrast instead")
    elif _PCT_RE.search(h_norm) and not _CONTRAST_RE.search(h_norm):
        issues.append("headline restates a percent with no contrast - name "
                      "what diverged (breadth, sector, flows)")

    for i, row in enumerate(prose.get("why") or [], 1):
        title = norm_phrase((row or {}).get("title"))
        if title in GENERIC_WHY_TITLES:
            issues.append(
                f"why[{i}].title '{title}' is a category label - use a "
                "causal clause that names the driver")

    reasons = normalize_sector_reasons(prose.get("sector_reasons"))
    board = sector_board(pack, weekly=weekly)
    shorts = [short for _n, short, _p in board]
    usable = []
    for short in shorts:
        text = reasons.get(short) or ""
        if not text:
            continue
        if is_rank_stub(text) or FILLER_REASON.search(text):
            issues.append(
                f"sector_reasons['{short}'] is a rank stub or filler "
                f"('{text}') - state a cause, and key it '{short}' not "
                "'Nifty …'")
            continue
        usable.append(short)
    if len(shorts) >= 4 and len(usable) < 4:
        missing = [s for s in shorts if s not in usable]
        issues.append(
            f"sector_reasons covered {len(usable)} of {len(shorts)} "
            f"displayed sectors after normalizing to short keys {shorts}. "
            f"Missing or unusable: {missing}. Use those exact short names, "
            "never a 'Nifty ' prefix.")

    for i, lesson in enumerate(prose.get("lessons") or [], 1):
        text = str(lesson or "")
        if _PCT_RE.search(text) and not _RELATION_RE.search(text):
            issues.append(
                f"lessons[{i}] restates a percent with no relationship - "
                "say what diverged, not the figure already on the slides")

    skeletons = [lesson_skeleton(x) for x in (prose.get("lessons") or [])]
    seen_sk = {}
    for i, sk in enumerate(skeletons, 1):
        if len(sk) < 12:
            continue
        if sk in seen_sk:
            issues.append(
                f"lessons[{i}] repeats the pattern of lessons[{seen_sk[sk]}]")
        else:
            seen_sk[sk] = i

    for field in ("cta_headline", "cta_sub"):
        text = str(prose.get(field) or "")
        if _EVERGREEN_CTA.search(text):
            issues.append(
                f"{field} is an evergreen marketing line - name this close "
                "or the next session's weekday")

    memory = memory or {}
    if h_norm and h_norm in (memory.get("headlines") or ()):
        issues.append(f"headline repeats a previous day: '{h_norm}' - write "
                      "a fresh one from today's contrast")
    day_emojis = {r.get("emoji") for r in (prose.get("why") or [])
                  if isinstance(r, dict) and r.get("emoji")}
    seen_emojis = memory.get("emojis") or set()
    if day_emojis and seen_emojis and day_emojis == seen_emojis:
        issues.append("the exact emoji set was already used - pick emojis "
                      "that depict today's specific drivers")
    prior_sk = memory.get("lesson_skeletons") or set()
    for i, sk in enumerate(skeletons, 1):
        if len(sk) >= 12 and sk in prior_sk:
            issues.append(
                f"lessons[{i}] matches a previous day's lesson pattern "
                f"('{sk}') - find a different relationship")
    for field, bucket in (
        ("movers_note_gainers", "movers"),
        ("movers_note_losers", "movers"),
        ("cta_headline", "ctas"),
        ("cta_sub", "ctas"),
        ("bonus_title", "bonus_titles"),
    ):
        val = norm_phrase(prose.get(field))
        if val and val in (memory.get(bucket) or ()):
            issues.append(f"{field} repeats a previous day: '{val}'")
    for i, row in enumerate(prose.get("why") or [], 1):
        if not isinstance(row, dict):
            continue
        title = norm_phrase(row.get("title"))
        if title and title in (memory.get("why_titles") or ()):
            issues.append(f"why[{i}].title repeats a previous day: '{title}'")
    return issues


def _flat(node):
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return " ".join(_flat(v) for v in node.values())
    if isinstance(node, list):
        return " ".join(_flat(v) for v in node)
    return ""


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
    issues += compliance.number_lock(html, pack)
    return issues
