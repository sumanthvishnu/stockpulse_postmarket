#!/usr/bin/env python3
"""Enrichment stage: fills the datapack's wire-only gaps before compilation.

Adds `derived.enrichment` with four blocks, each independently optional -
every gap lands in pack['failures'] and the report's Data Gaps Register,
never silently:

  index_levels       Trendlyne technical desk pivots (R1/S1...) for NIFTY and
                     BANKNIFTY - the 'analyst levels' slot, attributed to a
                     named source instead of model reasoning.
  gift_nifty         Evening GIFT Nifty level with capture timestamp.
  mover_catalysts    Dated Trendlyne news for the day's top Nifty 50 movers,
                     filtered to the trading date - real driver attribution
                     instead of 'No identifiable catalyst'.
  econ_calendar      Next-session high/medium impact events (ForexFactory
                     weekly XML), times converted to IST.

Backfill safety: live items (GIFT Nifty, index technicals, calendar) reflect
TODAY, so on a backfill run they are skipped with a stale note. Dated news
is filtered by publication date and stays valid for backfills.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import requests

import trendlyne_mcp as tly

IST = timezone(timedelta(hours=5, minutes=30))
ET = timezone(timedelta(hours=-4))   # FF calendar publishes US Eastern (EDT)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"


def _now():
    return datetime.now(IST)


def _gap(pack, source, reason):
    pack.setdefault("failures", []).append(
        {"source": source, "reason": reason,
         "checked_ist": _now().strftime("%H:%M IST")})


# ------------------------------------------------------------------ blocks -
def _index_levels(enr, pack, is_today):
    out = {}
    for label, code in (("NIFTY", "NIFTY"), ("BANKNIFTY", "NIFTY BANK")):
        text = tly.call("get_overview_news_corp_events",
                        {"stock_code": code, "type": "technical"})
        tly.polite_pause()
        if not text:
            _gap(pack, f"trendlyne:technicals:{label}",
                 "Trendlyne MCP unreachable or returned no technicals")
            continue
        piv = tly.parse_pivots(text)
        if piv:
            piv["rsi"] = tly.parse_rsi(text)
            piv["sma_insight"] = tly.parse_sma_insight(text)
            piv["source"] = "Trendlyne technical desk"
            piv["asof_ist"] = _now().strftime("%Y-%m-%d %H:%M IST")
            out[label] = piv
        else:
            _gap(pack, f"trendlyne:technicals:{label}",
                 "technicals returned but pivot block not found")
    if not is_today and out:
        for v in out.values():
            v["stale_warning"] = True
            v["note"] = ("technicals are latest-close based; backfill run, "
                         "so these may reflect a later session")
    if out:
        enr["index_levels"] = out


def _gift_nifty(enr, pack, is_today):
    if not is_today:
        return   # live cue is meaningless for a past date
    text = (tly.call("get_overview_news_corp_events",
                     {"stock_code": "SGXNIFTY-CFD", "type": "technical"}) or
            tly.call("get_overview_news_corp_events",
                     {"stock_code": "SGXNIFTY-CFD", "type": "overview"}))
    tly.polite_pause()
    if not text:
        _gap(pack, "trendlyne:gift_nifty",
             "GIFT Nifty (SGXNIFTY-CFD) not reachable via Trendlyne MCP")
        return
    level = tly.parse_price(text)
    if level is None:
        m = re.search(r"lastTradedPrice\s*[:|]\s*([\d,]+(?:\.\d+)?)", text)
        if m:
            level = float(m.group(1).replace(",", ""))
    if level is None:
        _gap(pack, "trendlyne:gift_nifty",
             "GIFT Nifty payload had no readable level")
        return
    nifty_close = (pack.get("derived", {}).get("indices", {})
                   .get("Nifty 50", {}).get("close"))
    enr["gift_nifty"] = {
        "level": level,
        "captured_ist": _now().strftime("%Y-%m-%d %H:%M IST"),
        "premium_pts": (round(level - nifty_close, 2)
                        if nifty_close else None),
        "source": "Trendlyne (GIFT Nifty CFD feed)",
        "note": "evening cue for the next session only"}


def _mover_catalysts(enr, pack, tdate):
    mv = pack.get("derived", {}).get("nifty50_movers", {})
    symbols = [m["symbol"] for m in (mv.get("gainers", [])[:3]
                                     + mv.get("losers", [])[:3])
               if m.get("symbol") and m["symbol"] != "-"]
    if not symbols:
        return
    cats = {}
    for sym in symbols:
        text = tly.call("get_overview_news_corp_events",
                        {"stock_code": sym, "type": "news"})
        tly.polite_pause()
        if not text:
            _gap(pack, f"trendlyne:news:{sym}", "news call failed")
            continue
        day_items = []
        for it in tly.parse_news(text, max_items=6):
            d = (it.get("pubDate") or "")[:10]
            try:
                # pubDate is UTC; compare on the IST calendar date
                dt = datetime.fromisoformat(d)
                ist_date = dt.strftime("%Y-%m-%d")  # date part only
            except ValueError:
                continue
            if ist_date == tdate.isoformat():
                day_items.append(it)
        if day_items:
            cats[sym] = {"news": day_items[:2],
                         "source": "Trendlyne news feed"}
    if cats:
        enr["mover_catalysts"] = cats
    else:
        _gap(pack, "trendlyne:mover_news",
             "no same-day news found for top movers")


def _econ_calendar(enr, pack, next_session_iso):
    """ForexFactory weekly XML -> next-session events, ET -> IST."""
    try:
        r = requests.get(FF_CALENDAR, headers={"User-Agent": UA}, timeout=45)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        _gap(pack, "forexfactory:calendar", f"calendar fetch failed: {e}")
        return
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        _gap(pack, "forexfactory:calendar", f"calendar XML parse failed: {e}")
        return
    events = []
    for ev in root.iter("event"):
        def tag(name):
            el = ev.find(name)
            return (el.text or "").strip() if el is not None else ""
        dstr, tstr = tag("date"), tag("time")
        try:
            d = datetime.strptime(dstr, "%m-%d-%Y").date()
        except ValueError:
            continue
        if d.isoformat() != next_session_iso:
            continue
        country, impact = tag("country"), tag("impact")
        if impact not in ("High", "Medium"):
            continue
        if country not in ("INR", "USD", "EUR", "CNY", "JPY", "GBP", "All"):
            continue
        ist = ""
        if tstr and tstr.lower() not in ("all day", "tentative"):
            m = re.match(r"(\d+):(\d+)(am|pm)", tstr.lower())
            if m:
                hh = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
                dt = datetime(d.year, d.month, d.day, hh, int(m.group(2)),
                              tzinfo=ET).astimezone(IST)
                ist = dt.strftime("%H:%M IST")
        events.append({"title": tag("title"), "country": country,
                       "impact": impact, "time_ist": ist or tstr or "all day",
                       "forecast": tag("forecast"), "previous": tag("previous")})
    if events:
        enr["econ_calendar"] = {
            "for_session": next_session_iso, "events": events,
            "source": "ForexFactory weekly calendar (times converted ET>IST)",
            "checked_ist": _now().strftime("%H:%M IST")}
    else:
        enr["econ_calendar"] = {
            "for_session": next_session_iso, "events": [],
            "source": "ForexFactory weekly calendar",
            "note": "no high/medium impact events found for the session"}


# -------------------------------------------------------------------- main -
def run(pack):
    """Populate derived.enrichment in place. Never raises."""
    d = pack.setdefault("derived", {})
    tdate = date.fromisoformat(pack["meta"]["trading_date"])
    is_today = tdate == _now().date()
    nxt = (d.get("next_trading_session") or {}).get("date")
    enr = {"checked_ist": _now().strftime("%Y-%m-%d %H:%M IST"),
           "backfill_run": not is_today}

    if not tly.available():
        _gap(pack, "trendlyne:mcp",
             "Trendlyne MCP unavailable or TRENDLYNE_MCP_TOKEN unset - "
             "skipping index levels, GIFT Nifty and mover catalysts")
    else:
        _index_levels(enr, pack, is_today)
        _gift_nifty(enr, pack, is_today)
        _mover_catalysts(enr, pack, tdate)

    if nxt and is_today:
        _econ_calendar(enr, pack, nxt)
    elif not is_today:
        enr["econ_calendar"] = {"note": "skipped on backfill (weekly feed "
                                        "only covers the current week)"}

    d["enrichment"] = enr
    got = [k for k in ("index_levels", "gift_nifty", "mover_catalysts",
                       "econ_calendar") if k in enr]
    print(f"  [enrich] filled: {got or 'nothing (see failures)'}", flush=True)
    return enr


if __name__ == "__main__":
    import sys
    p = json.load(open(sys.argv[1], encoding="utf-8"))
    run(p)
    json.dump(p, open(sys.argv[1], "w", encoding="utf-8"),
              ensure_ascii=False, default=str)
    print("enrichment written into", sys.argv[1])
