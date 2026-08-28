#!/usr/bin/env python3
"""
StockPulse India Post-Market Data Fetcher - v3.5 (with Kite Connect)
====================================================================
v3.5: closes the recurring "data gap" complaints:
  - corporate actions fetched per-day (today / T+1 / T+2) with from_date/
    to_date, so derived.corp_actions.ex_t1 / ex_t2 populate instead of
    coming back empty by non-coverage (handover spec 9C).
  - ENABLE_YFINANCE now defaults True: Sensex + US/Asia/Europe/commodities/
    FX lock into derived.global_markets instead of being left to the model.
  - derived.participant_oi: the four-cohort OI net table (Client/DII/FII/
    Pro) is computed here. Previously it was the one table left to the
    compiler to parse.
  - derived.india_10y: best-effort India 10Y G-sec yield (Trading
    Economics, tagged wire) so the bond-yield gap closes on most days.
  - a trimmed *_compiler.json is written alongside the full pack (drops the
    raw bhavcopy / 52-week / FII .xls blobs the compiler never reads, which
    cuts the token payload roughly 85-90%).
v3.1: whitespace-tolerant CSV parsing; Nifty-50 endpoint retry.
v3.2: fii_stats xls stored base64-encoded (binary survives JSON).
v3.4: FIX for the wall of HTTP 403s. NSE/BSE now sit behind Akamai Bot
      Manager, which fingerprints the TLS ClientHello (JA3/JA4) before it
      reads any header - so plain `requests` is flagged as a bot on every
      call regardless of cookies or User-Agent. v3.4 routes all NSE/BSE
      traffic through curl_cffi with a real Chrome TLS+HTTP2 fingerprint,
      warms the Akamai sensor cookies over two landing pages, re-warms on a
      mid-run 403, and stops the stale hardcoded User-Agent from clashing
      with the impersonated fingerprint. REQUIRES:  pip install curl_cffi
      (Kite stays on plain requests - api.kite.trade is not Akamai-gated.)
v3.3: pushes the numeric work that the LLM used to get wrong into
      deterministic Python. New computed sections so the model only
      writes prose around locked numbers:
        - derived.internals_52wk    : new 52-wk highs/lows COMPUTED from
          the bhavcopy x 52-wk-reference join (not left to the model,
          which previously misread the reference file as 0/0)
        - derived.nifty50_movers    : Nifty-50 breadth + top gainers/
          losers WITH delivery %, computed from bhavcopy filtered to the
          live ind_nifty50list constituents
        - derived.broader_movers    : non-Nifty-50 movers, turnover >=
          Rs 100 Cr, with delivery %
        - derived.bulk_deals_signals: round-trip market-making legs
          removed, one-sided deals >= Rs 20 Cr surfaced with value in Cr
        - derived.fii_fno_stats     : the binary FII derivatives .xls
          PARSED to a table (needs xlrd; base64 still stored as fallback)
        - derived.corp_actions      : ex-today / T+1 / T+2 buckets with
          Nifty-50 constituents flagged for the dividend-capture check
        - derived.fo_ban            : parsed ban list + entry/exit diff
          vs the prior session's pack if one is present locally
        - derived.vix_context       : VIX 20-day range + Nifty streak
        - derived.sanity_flags      : Section-I plausibility bounds run
          BEFORE the model sees the numbers
        - derived.global_markets    : OPTIONAL yfinance snapshot of US/
          Asia/Europe/commodities/USDINR (guarded import, off by default)
Run this on YOUR machine (in India) after market close. Writes ONE JSON
"data pack" file. Upload that file back to the chat.

v3 adds OPTIONAL Zerodha Kite Connect integration:
  - full NIFTY + BANKNIFTY option chain quotes (OI, LTP per strike)
  - ATM IV computed locally via Black-Scholes inversion
  - index quote cross-verification (Nifty 50, Bank Nifty, India VIX)
If you do not configure Kite, the script works exactly like v2.

SETUP (one time):
    1. python -m pip install requests curl_cffi
       (curl_cffi is what gets you past NSE's 403 wall - do not skip it.)
    2. (optional Kite) create an app at developers.kite.trade, pay the
       Rs 2,000/month Connect plan, then fill in the two lines below.

USAGE:
    python stockpulse_data_fetcher.py                  # today
    python stockpulse_data_fetcher.py --date 05-08-2026

DAILY KITE LOGIN (only if Kite is configured):
    Zerodha requires a fresh login each day (SEBI-mandated). On the
    first run of the day the script prints a login link - open it, log
    in, and paste the full redirect URL back into the terminal. The
    token is cached for the rest of the day. ~30 seconds.

TIMING: best run window is 19:00-21:00 IST.
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone, date as _date
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  python -m pip install requests")

# NSE (and BSE) now sit behind Akamai Bot Manager, which fingerprints the TLS
# ClientHello (JA3/JA4) BEFORE it looks at a single HTTP header. A plain
# `requests`/urllib3 handshake produces a fingerprint that Akamai flags on
# sight, so every NSE call returns HTTP 403 no matter how good the headers or
# cookies are. curl_cffi replays a real Chrome TLS + HTTP/2 fingerprint, which
# is what actually gets us past the 403 wall. Strongly recommended:
#     python -m pip install curl_cffi
# Without it the script falls back to plain requests and will very likely 403.
try:
    from curl_cffi import requests as cffi_requests
    HAVE_CFFI = True
except ImportError:
    cffi_requests = None
    HAVE_CFFI = False

# Which Chrome fingerprint curl_cffi impersonates. "chrome" tracks the latest
# supported build; pin to e.g. "chrome131" only if a future curl_cffi default
# starts getting flagged.
IMPERSONATE = "chrome"

# ============================ CONFIG ======================================
# Leave blank to run without Kite (everything else still works).
KITE_API_KEY = ""
KITE_API_SECRET = ""
RISK_FREE_RATE = 0.065   # used for Black-Scholes IV; near the RBI repo rate

# Optional yfinance global-markets snapshot (US/Asia/Europe/commodities/FX).
# On by default: locks Sensex + US/Asia/Europe/commodities/FX into the
# pack so the model never has to web-search them. Requires: pip install
# yfinance. Set False to run without that dependency (the block then becomes
# a logged gap instead of locked numbers).
ENABLE_YFINANCE = True

# How many weekday sessions of index history to pull. 6 is the minimum for
# the 5-session change; ~22 gives a real 20-day VIX range and Nifty streak.
HISTORY_SESSIONS = 22

# Bulk-deal thresholds and known market-making counterparties whose legs are
# treated as round-trip noise (tagged, and dropped when they round-trip).
BULK_MIN_VALUE_CR = 20.0
KNOWN_MM_CLIENTS = ("MICROCURVES", "JUNOMONETA", "QE SECURITIES", "HRTI",
                    "GRAVITON", "NK SECURITIES", "AINA", "SHRIRAM")
# ==========================================================================

IST = timezone(timedelta(hours=5, minutes=30))
BASE = "https://www.nseindia.com"
ARCH = "https://nsearchives.nseindia.com"
KITE = "https://api.kite.trade"
TOKEN_FILE = "kite_token.json"

# App-level headers that are safe on BOTH transport paths. When curl_cffi is
# impersonating Chrome it already supplies a browser-consistent User-Agent,
# sec-ch-ua, sec-fetch-* and Accept set; we must NOT overwrite the User-Agent
# with a hardcoded/stale one, because a UA that disagrees with the impersonated
# TLS fingerprint is itself a bot signal. So the base set here carries only the
# non-conflicting hints; per-request Referer/Accept are added in Client.get().
APP_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}

# Full header set used ONLY on the plain-requests fallback path (no curl_cffi).
FALLBACK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
                   "Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Referenced by the Kite path and BSE fallback for a User-Agent string.
HEADERS = FALLBACK_HEADERS

# Names must match the "Index Name" column in ind_close_all exactly, or the
# 5-day / history joins silently drop the row (v3.2 had "Nifty Infra", which
# never matched "Nifty Infrastructure").
SECTORAL = ["Nifty IT", "Nifty Bank", "Nifty Financial Services", "Nifty Auto",
            "Nifty Metal", "Nifty FMCG", "Nifty Realty", "Nifty Pharma",
            "Nifty Healthcare Index", "Nifty Energy", "Nifty Oil & Gas",
            "Nifty PSU Bank", "Nifty Private Bank", "Nifty Media",
            "Nifty Consumer Durables", "Nifty Infrastructure"]
MAIN_IDX = ["Nifty 50", "Nifty Bank", "Nifty Midcap 150", "Nifty Smallcap 250",
            "Nifty Next 50", "India VIX"]

# Fallback Nifty-50 constituents, used ONLY if the live ind_nifty50list.csv
# fetch fails. Index composition changes at reviews, so this is flagged in the
# pack as unverified when used; the archive file is always preferred.
N50_FALLBACK = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"]

pack = {"meta": {}, "data": {}, "derived": {}, "failures": []}

# Raw archive blobs the compiler never reads (fully superseded by derived.*).
# The *_compiler.json output drops these to cut the token payload ~85-90%.
COMPILER_DROP_KEYS = ("bhavdata_full", "high_low_52wk", "fo_ban_list",
                      "fii_fno_stats_b64", "corporate_actions_raw")


def compiler_pack(full):
    """Deep copy of the pack with the heavy raw blobs removed."""
    trimmed = json.loads(json.dumps(_sanitize(full), default=str))
    for k in COMPILER_DROP_KEYS:
        trimmed.get("data", {}).pop(k, None)
    return trimmed


def now_ist():
    return datetime.now(IST)


def record(key, ok, detail=""):
    print(f"  [{'OK  ' if ok else 'GAP'}] {key}{(' - ' + detail) if detail else ''}")
    if not ok:
        pack["failures"].append({"source": key, "reason": detail[:150],
                                 "checked_ist": now_ist().strftime("%H:%M IST")})


# --------------------------------------------------------------- helpers ---
def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _sanitize(x):
    """Replace non-finite floats (NaN/Inf from yfinance etc.) with None so the
    pack always dumps as strict, valid JSON (NaN is invalid JSON and breaks
    downstream parsers)."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _sanitize(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_sanitize(v) for v in x]
    return x


def parse_dt(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _parse_long_date(s):
    """Parse the wire 'August 28, 2026' / '28 August 2026' forms that the
    compact parse_dt() formats do not cover."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def last_weekdays(n, end=None):
    days, d = [], (end or now_ist().date())
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "CE":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def implied_vol(price, S, K, T, r, kind):
    """Bisection inversion of Black-Scholes. Returns IV or None."""
    intrinsic = max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    if price is None or price < intrinsic or T <= 0:
        return None
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, r, mid, kind) > price:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 4)


# ------------------------------------------------------------------ http ---
class Client:
    def __init__(self, timeout=25, retries=3, pause=2.0):
        if HAVE_CFFI:
            # impersonate at the session level so every request replays the
            # same Chrome TLS/HTTP2 fingerprint and shares one cookie jar.
            self.s = cffi_requests.Session(impersonate=IMPERSONATE)
            self.s.headers.update(APP_HEADERS)
            self.engine = "curl_cffi/" + IMPERSONATE
        else:
            self.s = requests.Session()
            self.s.headers.update(FALLBACK_HEADERS)
            self.engine = "requests (no TLS impersonation - 403s likely)"
        self.timeout, self.retries, self.pause = timeout, retries, pause
        self._primed = False
        self.primed_ok = False

    def _raw_get(self, url, headers=None):
        # curl_cffi's Session.get already carries the session-level impersonate;
        # requests.Session.get ignores it. Same call signature either way.
        return self.s.get(url, headers=headers, timeout=self.timeout)

    def prime(self):
        """Warm the Akamai session: pick up the _abck / bm_sv sensor cookies by
        visiting the homepage and one report landing page before hitting the
        archive/api hosts. Retries, and reports whether cookies were actually
        set so a silent prime failure no longer looks like 40 downstream 403s."""
        warm_urls = [BASE, f"{BASE}/all-reports", f"{BASE}/market-data/live-equity-market"]
        for attempt in range(1, self.retries + 1):
            try:
                for u in warm_urls:
                    r = self._raw_get(u, headers={"Referer": BASE})
                    time.sleep(self.pause)
                # Consider the prime successful once Akamai has planted cookies.
                names = set(self.s.cookies.keys()) if hasattr(self.s, "cookies") else set()
                if any(n in names for n in ("_abck", "bm_sv", "nsit", "nseappid")) \
                        or getattr(r, "status_code", None) == 200:
                    self.primed_ok = True
                    break
            except Exception:
                pass
            time.sleep(self.pause * attempt)
        self._primed = True
        cookie_n = len(self.s.cookies.keys()) if hasattr(self.s, "cookies") else 0
        print(f"  [prime] engine={self.engine}; "
              f"cookies={cookie_n}; ok={self.primed_ok}")
        if not self.primed_ok and not HAVE_CFFI:
            print("  [prime] curl_cffi is NOT installed - NSE will almost certainly")
            print("          return 403. Install it:  python -m pip install curl_cffi")

    def get(self, url, referer=None, headers=None):
        if not self._primed:
            self.prime()
        h = {"Referer": referer or BASE}
        if headers:
            h.update(headers)
        last = "unknown"
        for attempt in range(1, self.retries + 1):
            try:
                r = self._raw_get(url, headers=h)
                if r.status_code == 200 and r.content and len(r.content) > 40:
                    return r.content
                if r.status_code == 200:
                    # A 200 with an empty/stub body is not a transport error;
                    # reporting it as bare "HTTP 200" made the gaps register
                    # read like a mystery failure.
                    last = (f"HTTP 200 but empty/short body "
                            f"({len(r.content or b'')} bytes) - endpoint "
                            "returned no data for this query")
                else:
                    last = f"HTTP {r.status_code}"
                # A 403 mid-run means the Akamai cookie decayed - re-warm once.
                if r.status_code in (401, 403) and attempt < self.retries:
                    self._primed = False
                    self.prime()
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(self.pause * attempt)
        raise RuntimeError(last)

    def get_json(self, url, referer=None):
        content = self.get(url, referer=referer, headers={
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest"})
        return json.loads(content.decode("utf-8", errors="replace"))


def impersonate_get(url, headers=None, timeout=20):
    """One-off GET that uses a Chrome TLS fingerprint when curl_cffi is present
    (BSE is Akamai-protected too), else falls back to plain requests."""
    if HAVE_CFFI:
        return cffi_requests.get(url, headers=headers, timeout=timeout,
                                 impersonate=IMPERSONATE)
    return requests.get(url, headers=headers, timeout=timeout)


def loads_lenient(text):
    """json.loads that tolerates a UTF-8 BOM / leading whitespace, and gives a
    readable error (a snippet of the body) when the response is not JSON at all
    - e.g. an Akamai/HTML block page, which was the old 'Expecting value: line 3
    column 1' failure on the BSE fallback."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.lstrip("\ufeff").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        snippet = " ".join(text[:120].split())
        raise RuntimeError(f"non-JSON response (looks like a block/HTML page): "
                           f"{snippet!r}")


# --------------------------------------------------------- kite connect ---
def kite_login():
    """Returns an access token, doing the daily browser login if needed."""
    if os.path.exists(TOKEN_FILE):
        try:
            saved = json.load(open(TOKEN_FILE))
            if saved.get("date") == now_ist().date().isoformat() and saved.get("token"):
                return saved["token"]
        except Exception:
            pass
    login_url = f"https://kite.trade/connect/login?api_key={KITE_API_KEY}&v=3"
    print("\n  KITE LOGIN REQUIRED (once per day):")
    print(f"  1. Open this link in your browser:\n     {login_url}")
    print("  2. Log in with your Zerodha credentials.")
    print("  3. The browser will redirect to a 127.0.0.1 address that may show")
    print("     an error page - that is fine. Copy the FULL address-bar URL.")
    pasted = input("  4. Paste that full URL here: ").strip()
    rt = parse_qs(urlparse(pasted).query).get("request_token", [None])[0]
    if not rt:
        raise RuntimeError("no request_token found in the pasted URL")
    checksum = hashlib.sha256(
        (KITE_API_KEY + rt + KITE_API_SECRET).encode()).hexdigest()
    r = requests.post(f"{KITE}/session/token",
                      data={"api_key": KITE_API_KEY, "request_token": rt,
                            "checksum": checksum},
                      headers={"X-Kite-Version": "3"}, timeout=20)
    token = r.json()["data"]["access_token"]
    json.dump({"date": now_ist().date().isoformat(), "token": token},
              open(TOKEN_FILE, "w"))
    print("  Kite login successful, token cached for today.\n")
    return token


def kite_get(path, params=None):
    token = getattr(kite_get, "_token", None)
    if token is None:
        token = kite_get._token = kite_login()
    h = {"Authorization": f"token {KITE_API_KEY}:{token}",
         "X-Kite-Version": "3"}
    r = requests.get(f"{KITE}{path}", params=params, headers=h, timeout=40)
    if r.status_code == 403:  # token died - relogin once
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        token = kite_get._token = kite_login()
        h["Authorization"] = f"token {KITE_API_KEY}:{token}"
        r = requests.get(f"{KITE}{path}", params=params, headers=h, timeout=40)
    r.raise_for_status()
    return r


def kite_option_chain(name, spot):
    """Full option chain for NIFTY/BANKNIFTY from Kite instruments+quotes."""
    csv_text = kite_get("/instruments/NFO").text
    rows = [r for r in clean_rows(csv_text)
            if r.get("name") == name and r.get("segment") == "NFO-OPT"
            and r.get("instrument_type") in ("CE", "PE")]
    if not rows:
        raise RuntimeError(f"no {name} options in instruments dump")
    expiries = sorted({parse_dt(r["expiry"]) for r in rows if parse_dt(r["expiry"])})
    today = now_ist().date()
    live = [e for e in expiries if e >= today]
    expiry = live[0] if live else expiries[-1]
    chain = [r for r in rows if parse_dt(r["expiry"]) == expiry]
    band = spot * 0.07
    chain = [r for r in chain if abs(num(r["strike"]) - spot) <= band]

    syms = [f"NFO:{r['tradingsymbol']}" for r in chain]
    quotes = {}
    for i in range(0, len(syms), 400):
        chunk = syms[i:i + 400]
        q = kite_get("/quote", params=[("i", s) for s in chunk]).json()["data"]
        quotes.update(q)
        time.sleep(0.4)

    T = max((expiry - today).days, 0) / 365 or 1 / 365
    strikes = {}
    for r in chain:
        k = num(r["strike"])
        q = quotes.get(f"NFO:{r['tradingsymbol']}", {})
        slot = strikes.setdefault(k, {})
        slot[r["instrument_type"]] = {
            "ltp": q.get("last_price"), "oi": q.get("oi"),
            "iv": implied_vol(q.get("last_price"), spot, k, T,
                              RISK_FREE_RATE, r["instrument_type"])}
    ce_oi = {k: v["CE"]["oi"] or 0 for k, v in strikes.items() if "CE" in v}
    pe_oi = {k: v["PE"]["oi"] or 0 for k, v in strikes.items() if "PE" in v}
    pain = {k: sum((k - s) * o for s, o in ce_oi.items() if k > s)
            + sum((s - k) * o for s, o in pe_oi.items() if k < s)
            for k in set(ce_oi) | set(pe_oi)}
    atm_k = min(strikes, key=lambda k: abs(k - spot))
    atm_ivs = [iv for leg in strikes[atm_k].values()
               for iv in [leg.get("iv")] if iv]
    tce, tpe = sum(ce_oi.values()), sum(pe_oi.values())
    return {"symbol": name, "expiry": expiry.isoformat(), "spot": spot,
            "pcr_oi": round(tpe / tce, 3) if tce else None,
            "total_call_oi": tce, "total_put_oi": tpe,
            "max_call_oi_strike": max(ce_oi, key=ce_oi.get) if ce_oi else None,
            "max_put_oi_strike": max(pe_oi, key=pe_oi.get) if pe_oi else None,
            "max_pain": min(pain, key=pain.get) if pain else None,
            "atm_strike": atm_k,
            "atm_iv_pct": round(sum(atm_ivs) / len(atm_ivs) * 100, 2) if atm_ivs else None,
            "next_expiries": [e.isoformat() for e in (live or expiries)[:4]],
            "source": "Kite Connect",
            "strikes_kept": len(strikes)}


# ------------------------------------------------- derived from archives ---
def clean_rows(text):
    """DictReader rows with whitespace-tolerant headers (NSE pads headers
    like ' CLOSE_PRICE' - strip both keys and values)."""
    return [{k.strip(): (v.strip() if isinstance(v, str) else v)
             for k, v in r.items() if k is not None}
            for r in csv.DictReader(io.StringIO(text), skipinitialspace=True)]


def derive_from_bhavdata(text):
    rows = [r for r in clean_rows(text)
            if (r.get("SERIES") or "").strip() == "EQ"]
    adv = dec = unc = 0
    movers = []
    for r in rows:
        close, prev = num(r.get("CLOSE_PRICE")), num(r.get("PREV_CLOSE"))
        if close is None or prev in (None, 0):
            continue
        chg = (close / prev - 1) * 100
        adv += chg > 0
        dec += chg < 0
        unc += chg == 0
        qty = num(r.get("TTL_TRD_QNTY")) or 0
        if qty >= 10000:
            movers.append({"symbol": (r.get("SYMBOL") or "").strip(),
                           "close": round(close, 2), "chg_pct": round(chg, 2),
                           "traded_qty": int(qty),
                           "deliv_pct": num(r.get("DELIV_PER"))})
    movers.sort(key=lambda m: m["chg_pct"], reverse=True)
    return {"breadth": {"advances": adv, "declines": dec, "unchanged": unc,
                        "ad_ratio": round(adv / dec, 3) if dec else None,
                        "universe": adv + dec + unc},
            "market_top_gainers": movers[:10],
            "market_top_losers": movers[-10:][::-1]}


def derive_option_metrics(zip_bytes, symbol):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        with z.open(z.namelist()[0]) as f:
            text = f.read().decode("utf-8", errors="replace")
    rows = [r for r in clean_rows(text)
            if (r.get("TckrSymb") or "").strip() == symbol
            and (r.get("FinInstrmTp") or "").strip() == "IDO"]
    if not rows:
        raise RuntimeError(f"no index-option rows for {symbol}")
    by_exp = {}
    for r in rows:
        exp = parse_dt(r.get("XpryDt"))
        if exp:
            by_exp.setdefault(exp, []).append(r)
    nearest = min(by_exp)
    rows = by_exp[nearest]
    ce_oi, pe_oi, spot = {}, {}, None
    for r in rows:
        k = num(r.get("StrkPric"))
        oi = num(r.get("OpnIntrst")) or 0
        if k is None:
            continue
        if (r.get("OptnTp") or "").strip() == "CE":
            ce_oi[k] = ce_oi.get(k, 0) + oi
        elif (r.get("OptnTp") or "").strip() == "PE":
            pe_oi[k] = pe_oi.get(k, 0) + oi
        if spot is None:
            spot = num(r.get("UndrlygPric"))
    strikes = sorted(set(ce_oi) | set(pe_oi))
    pain = {k: sum((k - s) * o for s, o in ce_oi.items() if k > s)
            + sum((s - k) * o for s, o in pe_oi.items() if k < s)
            for k in strikes}
    tce, tpe = sum(ce_oi.values()), sum(pe_oi.values())
    return {"symbol": symbol, "expiry": nearest.isoformat(), "spot": spot,
            "pcr_oi": round(tpe / tce, 3) if tce else None,
            "total_call_oi": int(tce), "total_put_oi": int(tpe),
            "max_call_oi_strike": max(ce_oi, key=ce_oi.get) if ce_oi else None,
            "max_put_oi_strike": max(pe_oi, key=pe_oi.get) if pe_oi else None,
            "max_pain": min(pain, key=pain.get) if pain else None,
            "atm_strike": min(strikes, key=lambda k: abs(k - spot)) if spot else None,
            "next_expiries": [d.isoformat() for d in sorted(by_exp)[:4]],
            "source": "NSE FO bhavcopy"}


def parse_ind_close_all(text):
    out = {}
    for r in clean_rows(text):
        name = (r.get("Index Name") or r.get("Index") or "").strip()
        if name:
            out[name] = {"open": num(r.get("Open Index Value")),
                         "high": num(r.get("High Index Value")),
                         "low": num(r.get("Low Index Value")),
                         "close": num(r.get("Closing Index Value")),
                         "pts_chg": num(r.get("Points Change")),
                         "pct_chg": num(r.get("Change(%)") or r.get("Change (%)"))}
    return out


# --------------------------------------------- new v3.3 deterministic work ---
def parse_nifty50_list(text):
    """Constituent symbols from ind_nifty50list.csv (archive, authoritative)."""
    syms = []
    for r in clean_rows(text):
        s = (r.get("Symbol") or r.get("SYMBOL") or "").strip()
        if s:
            syms.append(s)
    return syms


def eq_bhav_index(text):
    """One-pass index of EQ-series bhavcopy rows keyed by symbol."""
    idx = {}
    for r in clean_rows(text):
        if (r.get("SERIES") or "").strip() == "EQ":
            idx[(r.get("SYMBOL") or "").strip()] = r
    return idx


def _row_metrics(r):
    C, P = num(r.get("CLOSE_PRICE")), num(r.get("PREV_CLOSE"))
    trn = num(r.get("TURNOVER_LACS")) or 0.0
    if C is None or P in (None, 0):
        return None
    return {"symbol": (r.get("SYMBOL") or "").strip(),
            "close": round(C, 2), "prev_close": round(P, 2),
            "chg_pct": round((C / P - 1) * 100, 2),
            "deliv_pct": num(r.get("DELIV_PER")),
            "turnover_cr": round(trn / 100, 1)}


def derive_nifty50_movers(eqidx, constituents):
    """Nifty-50 breadth + top-5 gainers/losers WITH delivery %, from bhavcopy."""
    rows = []
    for s in constituents:
        r = eqidx.get(s)
        m = _row_metrics(r) if r else None
        if m:
            rows.append(m)
    rows.sort(key=lambda x: x["chg_pct"], reverse=True)
    adv = sum(1 for x in rows if x["chg_pct"] > 0)
    dec = sum(1 for x in rows if x["chg_pct"] < 0)
    return {"constituents_matched": len(rows),
            "advances": adv, "declines": dec,
            "unchanged": len(rows) - adv - dec,
            "gainers": rows[:5], "losers": rows[-5:][::-1]}


def derive_broader_movers(text, constituents, min_turnover_cr=100.0, n=8):
    """Non-Nifty-50 movers filtered to turnover >= Rs 100 Cr, with delivery %."""
    cset = set(constituents)
    out = []
    for r in clean_rows(text):
        if (r.get("SERIES") or "").strip() != "EQ":
            continue
        s = (r.get("SYMBOL") or "").strip()
        if s in cset:
            continue
        m = _row_metrics(r)
        if m and m["turnover_cr"] >= min_turnover_cr:
            out.append(m)
    out.sort(key=lambda x: x["chg_pct"], reverse=True)
    return {"min_turnover_cr": min_turnover_cr,
            "gainers": out[:n], "losers": out[-n:][::-1]}


def derive_52wk_internals(raw52, text_bhav, min_close=10.0, quality_turnover_cr=100.0):
    """New 52-week highs/lows COMPUTED from the bhavcopy x 52-wk-reference join.

    The reference file lists adjusted 52-wk high/low LEVELS per symbol; it is
    NOT a list of 'today's new highs'. A new high = today's HIGH_PRICE reaching
    the adjusted 52-wk high (0.9999 tol); a new low = today's LOW_PRICE reaching
    the adjusted 52-wk low (1.0001 tol). close >= Rs 10 filters penny noise.
    """
    lines = raw52.split("\n")
    body = "\n".join(lines[2:])          # skip disclaimer + 'Effective for' lines
    hi, lo = {}, {}
    for r in csv.DictReader(io.StringIO(body)):
        if (r.get("SERIES") or "").strip() != "EQ":
            continue
        s = (r.get("SYMBOL") or "").strip()
        hi[s] = num(r.get("Adjusted_52_Week_High"))
        lo[s] = num(r.get("Adjusted_52_Week_Low"))
    nh, nl = [], []
    for r in clean_rows(text_bhav):
        if (r.get("SERIES") or "").strip() != "EQ":
            continue
        s = (r.get("SYMBOL") or "").strip()
        C = num(r.get("CLOSE_PRICE"))
        H = num(r.get("HIGH_PRICE"))
        L = num(r.get("LOW_PRICE"))
        trn = (num(r.get("TURNOVER_LACS")) or 0) / 100
        if C is None or C < min_close:
            continue
        if hi.get(s) and H and H >= hi[s] * 0.9999:
            nh.append((s, round(C, 2), round(trn, 1)))
        if lo.get(s) and L and L <= lo[s] * 1.0001:
            nl.append((s, round(C, 2), round(trn, 1)))
    def sample(lst):
        return [{"symbol": s, "close": c, "turnover_cr": t}
                for s, c, t in sorted(lst, key=lambda x: -x[2])
                if t >= quality_turnover_cr][:12]
    return {"new_highs": len(nh), "new_lows": len(nl),
            "quality_high_sample": sample(nh),
            "quality_low_sample": sample(nl),
            "note": "computed from bhavcopy x CM_52_wk_High_low join, close>=Rs10"}


def derive_bulk_signals(rows, target):
    """Remove round-trip market-making legs; surface one-sided deals >= 20 Cr."""
    from collections import defaultdict
    agg = defaultdict(lambda: {"BUY": [0.0, 0.0], "SELL": [0.0, 0.0]})
    for r in rows:
        sym = (r.get("Symbol") or "").strip()
        side = (r.get("Buy/Sell") or "").strip().upper()
        q = num(r.get("Quantity Traded"))
        p = num(r.get("Trade Price / Wght. Avg. Price"))
        if not sym or side not in ("BUY", "SELL") or q is None or p is None:
            continue
        cl = (r.get("Client Name") or "").strip()
        agg[(sym, cl)][side][0] += q
        agg[(sym, cl)][side][1] += q * p
    signals, roundtrips = [], 0
    for (sym, cl), v in agg.items():
        bq, bv = v["BUY"]
        sq, sv = v["SELL"]
        is_rt = bq > 0 and sq > 0 and abs(bq - sq) / max(bq, sq) < 0.20
        if is_rt:
            roundtrips += 1
            continue
        val_cr = max(bv, sv) / 1e7
        if val_cr >= BULK_MIN_VALUE_CR:
            signals.append({
                "symbol": sym, "client": cl,
                "side": "BUY" if bv >= sv else "SELL",
                "value_cr": round(val_cr, 1),
                "is_known_mm": any(mm in cl.upper() for mm in KNOWN_MM_CLIENTS)})
    signals.sort(key=lambda x: -x["value_cr"])
    return {"one_sided_min_cr": BULK_MIN_VALUE_CR,
            "roundtrip_pairs_removed": roundtrips,
            "count": len(signals), "signals": signals}


def parse_fii_fno_stats(xls_bytes):
    """Parse the binary FII derivatives .xls into a table. Needs xlrd."""
    try:
        import xlrd
    except ImportError:
        return None
    sh = xlrd.open_workbook(file_contents=xls_bytes).sheet_by_index(0)
    want = {"INDEX FUTURES", "INDEX OPTIONS", "STOCK FUTURES", "STOCK OPTIONS"}
    out = {}
    for r in range(sh.nrows):
        label = str(sh.cell_value(r, 0)).strip().upper()
        if label in want:
            g = lambda c: num(sh.cell_value(r, c))
            buy, sell = g(2), g(4)
            out[label.title().replace("Index", "Index").replace("Stock", "Stock")] = {
                "buy_cr": buy, "sell_cr": sell,
                "net_cr": round((buy or 0) - (sell or 0), 2),
                "oi_contracts": int(g(5) or 0), "oi_cr": g(6)}
    return out or None


def next_trading_days(target, n):
    days, d = [], target
    while len(days) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return days


def derive_corp_actions(ca_raw, target, constituents):
    """Bucket ex-dividend/action dates into today / T+1 / T+2, flag Nifty-50."""
    if not isinstance(ca_raw, list):
        return None
    t1, t2 = next_trading_days(target, 2)
    cset = set(constituents)
    buckets = {"ex_today": [], "ex_t1": [], "ex_t2": []}
    for r in ca_raw:
        if not isinstance(r, dict) or (r.get("series") or "") != "EQ":
            continue
        ed = parse_dt(r.get("exDate"))
        if not ed:
            continue
        sym = (r.get("symbol") or "").strip()
        rec = {"symbol": sym, "subject": (r.get("subject") or "").strip(),
               "is_nifty50": sym in cset}
        if ed == target:
            buckets["ex_today"].append(rec)
        elif ed == t1:
            buckets["ex_t1"].append(rec)
        elif ed == t2:
            buckets["ex_t2"].append(rec)
    buckets["t1_date"] = t1.isoformat()
    buckets["t2_date"] = t2.isoformat()
    buckets["nifty50_ex_t1_t2"] = [x for x in buckets["ex_t1"] + buckets["ex_t2"]
                                   if x["is_nifty50"]]
    return buckets


def parse_ban_list(raw, prior_symbols=None, target=None):
    """Parse fo_secban into {trade_date, symbols} plus entry/exit diff.

    fo_secban.csv is a single UNDATED file that always describes the NEXT
    trading session from *now*, not from `target`. On a backfill that makes it
    silently wrong, so when `target` is supplied we compare the file's own
    trade date against the session that should follow `target` and set
    `stale_warning` when they disagree (pipeline then degrades to
    "unavailable" instead of publishing the current ban list under a past
    date).
    """
    trade_date, syms = None, []
    for ln in raw.split("\n"):
        ln = ln.strip()
        if ln.lower().startswith("securities in ban"):
            trade_date = ln.split("Trade Date")[-1].strip().rstrip(":").strip()
        elif "," in ln:
            parts = ln.split(",")
            if len(parts) >= 2 and parts[1].strip():
                syms.append(parts[1].strip())
    out = {"trade_date": trade_date, "count": len(syms), "symbols": syms}
    if target is not None:
        expected = next_trading_days(target, 1)[0]
        got = parse_dt(trade_date)
        stale = bool(got and got != expected)
        out["stale_warning"] = stale
        out["expected_trade_date"] = expected.isoformat()
        if stale:
            out["note"] = ("fo_secban.csv is undated and always describes the "
                           "next session from now; this file is for "
                           f"{trade_date}, not the session after {target}.")
    if prior_symbols is not None:
        prior = set(prior_symbols)
        out["entries"] = sorted(set(syms) - prior)
        out["exits"] = sorted(prior - set(syms))
        out["diff_vs_prior"] = True
    else:
        out["diff_vs_prior"] = False
    return out


def derive_vix_and_streak(idx_series, days_sorted):
    """VIX 20-day range + position, and the Nifty consecutive-session streak."""
    vix = [(d, idx_series[d].get("India VIX", {}).get("close"))
           for d in days_sorted if idx_series[d].get("India VIX")]
    vix = [(d, v) for d, v in vix if v is not None]
    out = {}
    if vix:
        vals = [v for _, v in vix]
        cur = vals[-1]
        lo, hi = min(vals), max(vals)
        pos = round((cur - lo) / (hi - lo) * 100, 1) if hi > lo else None
        out["vix"] = {"current": cur, "window_sessions": len(vals),
                      "low": lo, "high": hi, "pct_of_range": pos}
    nifty = [(d, idx_series[d].get("Nifty 50", {}).get("close"))
             for d in days_sorted if idx_series[d].get("Nifty 50")]
    nifty = [(d, v) for d, v in nifty if v is not None]
    if len(nifty) >= 2:
        streak, direction = 0, None
        for i in range(len(nifty) - 1, 0, -1):
            step = nifty[i][1] - nifty[i - 1][1]
            sign = "up" if step > 0 else "down" if step < 0 else "flat"
            if direction is None:
                direction = sign
            if sign == direction and sign != "flat":
                streak += 1
            else:
                break
        out["nifty_streak"] = {"direction": direction, "sessions": streak,
                               "latest_close": nifty[-1][1]}
    return out


def run_sanity_checks(pack):
    """Section-I plausibility bounds, run before the model sees the numbers."""
    flags = []
    der = pack["derived"]
    idx = der.get("indices", {})

    def bound(name, val, lo, hi, msg):
        if val is not None and (val < lo or val > hi):
            flags.append({"check": name, "value": val, "note": msg})

    n50 = idx.get("Nifty 50", {})
    bound("nifty_pct_move", n50.get("pct_chg"), -3, 3,
          "move beyond +/-3% - re-verify; if genuine it is the lead story")
    vix = idx.get("India VIX", {})
    bound("india_vix_level", vix.get("close"), 9, 35, "VIX outside 9-35 band")
    for name in SECTORAL:
        s = idx.get(name, {})
        bound(f"sector_move:{name}", s.get("pct_chg"), -5, 5,
              "sectoral move beyond +/-5% - re-verify")
    fii = der.get("fii_dii_cash_summary", {})
    for who in ("fii_net_cr", "dii_net_cr"):
        v = fii.get(who)
        if v is not None and abs(v) > 25000:
            flags.append({"check": who, "value": v,
                          "note": "single-day cash beyond Rs 25,000 Cr - re-verify"})
    intl = der.get("internals_52wk", {})
    hc = intl.get("new_highs")
    if hc is not None and (hc > 300 or hc < 5):
        flags.append({"check": "new_52wk_high_count", "value": hc,
                      "note": "count >300 or <5 - re-verify join logic"})
    ban = der.get("fo_ban", {})
    if ban.get("count", 0) > 15:
        flags.append({"check": "fo_ban_size", "value": ban["count"],
                      "note": "more than 15 names in ban - unusual, re-verify"})
    br = der.get("breadth", {})
    ad = br.get("ad_ratio")
    if ad is not None and n50.get("pct_chg") is not None:
        if n50["pct_chg"] < -0.5 and ad > 1.5:
            flags.append({"check": "breadth_vs_index", "value": ad,
                          "note": "index down but A/D strongly positive - re-check"})
        if n50["pct_chg"] > 0.5 and ad < 0.5:
            flags.append({"check": "breadth_vs_index", "value": ad,
                          "note": "index up but A/D strongly negative - re-check"})
    return flags


def fetch_global_yfinance(target=None):
    """OPTIONAL: US/Asia/Europe/commodities/FX snapshot. Guarded import.

    Selects the last bar ON OR BEFORE `target` (default: today IST) so a
    backfill run quotes the target date's close, not the current live level
    (yfinance otherwise returns the latest bar regardless of target date).
    """
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance not installed"
    import pandas as pd
    end = target or now_ist().date()
    tickers = {
        "SP500": "^GSPC", "Dow": "^DJI", "Nasdaq": "^IXIC",
        "US10Y_yield": "^TNX", "DXY": "DX-Y.NYB",
        "Nikkei": "^N225", "HangSeng": "^HSI", "Shanghai": "000001.SS",
        "Kospi": "^KS11", "FTSE": "^FTSE", "DAX": "^GDAXI",
        "Brent": "BZ=F", "WTI": "CL=F", "Gold": "GC=F",
        "USDINR": "INR=X", "IndiaVIX": "^INDIAVIX",
        "Nifty50": "^NSEI", "Sensex": "^BSESN"}
    out = {}
    for label, tk in tickers.items():
        try:
            h = yf.Ticker(tk).history(period="1mo")
            if h is None or len(h) < 2:
                continue
            # normalise the index to naive dates (Asia/Kolkata) to compare
            # against the target trading date
            dates = h.index
            if dates.tz is not None:
                dates = dates.tz_convert("Asia/Kolkata").tz_localize(None)
            date_s = pd.Series([d.date() for d in dates], index=h.index)
            sel = h[date_s <= end]
            if len(sel) < 2:
                continue
            last, prev = sel["Close"].iloc[-1], sel["Close"].iloc[-2]
            lastf, prevf = float(last), float(prev)
            if not (math.isfinite(lastf) and math.isfinite(prevf)):
                continue  # e.g. Shanghai/Kospi can return NaN
            out[label] = {
                "ticker": tk, "level": round(lastf, 4),
                "prev_close": round(prevf, 4),
                "pts_chg": round(lastf - prevf, 2),
                "pct_chg": round((lastf / prevf - 1) * 100, 2),
                "bar_date": str(date_s.loc[sel.index[-1]])}
        except Exception:
            continue
    return out, f"{len(out)}/{len(tickers)} tickers"


def fetch_india_10y():
    """Best-effort India 10Y G-sec closing yield (wire, no API key).

    Trading Economics publishes the latest value in the page's JSON-LD; the
    meta-description sentence supplies the as-of date and direction. This is
    a wire item: the compiler still cross-verifies against a second source.
    """
    import re
    url = "https://tradingeconomics.com/india/government-bond-yield"
    try:
        html = impersonate_get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept-Language": "en-US,en;q=0.9"}, timeout=25).text
    except Exception as e:
        return None, f"fetch failed: {e}"
    m = re.search(r'"value"\s*:\s*"?([0-9]+\.[0-9]+)', html)
    if not m:
        return None, "no yield value found in page"
    desc = re.search(r'name="description"\s+content="([^"]+)"', html)
    dtext = desc.group(1) if desc else ""
    direction = ("rose" if "rose" in dtext else
                 "fell" if ("fell" in dtext or "dropped" in dtext
                            or "declined" in dtext) else None)
    asof = re.search(r'on ([A-Za-z]+ \d{1,2}, \d{4})', dtext)
    return {"yield_pct": round(float(m.group(1)), 3),
            "direction": direction,
            "asof_text": asof.group(1) if asof else None,
            "source": "Trading Economics (wire)",
            "checked_ist": now_ist().strftime("%H:%M IST")}, None


def derive_participant_oi(raw_text):
    """Four-cohort net OI table from the raw participant-wise OI CSV.

    For each of Client/DII/FII/Pro: net index futures, net stock futures,
    total long, total short and net total (contracts).
    """
    reader = csv.reader(io.StringIO(raw_text.strip()))
    header, cohorts, out = None, ("CLIENT", "DII", "FII", "PRO"), {}
    for row in reader:
        cells = [c.strip() for c in row] if row else []
        if not cells or not any(cells):
            continue
        if cells[0] == "Client Type":
            header = cells
            continue
        if header is None or cells[0].upper() not in cohorts:
            continue

        def col(name):
            try:
                return num(cells[header.index(name)])
            except (ValueError, IndexError):
                return None

        fil, fis = col("Future Index Long"), col("Future Index Short")
        fsl, fss = col("Future Stock Long"), col("Future Stock Short")
        tl, ts = col("Total Long Contracts"), col("Total Short Contracts")
        out[cells[0]] = {
            "net_index_futures": int(fil - fis) if fil is not None and fis is not None else None,
            "net_stock_futures": int(fsl - fss) if fsl is not None and fss is not None else None,
            "total_long": int(tl) if tl is not None else None,
            "total_short": int(ts) if ts is not None else None,
            "net_total": int(tl - ts) if tl is not None and ts is not None else None,
        }
    return out or None


# ------------------------------------------------------------- collector ---
def collect(target):
    ddmmyyyy, ymd = target.strftime("%d%m%Y"), target.strftime("%Y%m%d")
    pack["meta"] = {"trading_date": target.isoformat(),
                    "generated_at_ist": now_ist().strftime("%Y-%m-%d %H:%M:%S IST"),
                    "fetcher_version": "3.5", "mode": "archive-first + kite",
                    "tls_engine": "curl_cffi/" + IMPERSONATE if HAVE_CFFI else "requests",
                    "kite_enabled": bool(KITE_API_KEY)}
    c = Client()
    print(f"\nStockPulse fetcher v3.5 - {target:%d %b %Y} - priming NSE session...")
    if not HAVE_CFFI:
        print("  [warn] curl_cffi not installed - expect HTTP 403 on every NSE call.")
        print("         Fix:  python -m pip install curl_cffi")
    c.prime()

    # ---- archives --------------------------------------------------------
    dated = {
        "bhavdata_full": f"{ARCH}/products/content/sec_bhavdata_full_{ddmmyyyy}.csv",
        "ind_close_all": f"{ARCH}/content/indices/ind_close_all_{ddmmyyyy}.csv",
        "participant_oi": f"{ARCH}/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv",
        "participant_vol": f"{ARCH}/content/nsccl/fao_participant_vol_{ddmmyyyy}.csv",
        "fo_bhavcopy_zip": f"{ARCH}/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip",
        "high_low_52wk": f"{ARCH}/content/CM_52_wk_High_low_{ddmmyyyy}.csv",
        "fo_ban_list": f"{ARCH}/content/fo/fo_secban.csv",
        "bulk_deals": f"{ARCH}/content/equities/bulk.csv",
        "nifty50_list": f"{ARCH}/content/indices/ind_nifty50list.csv",
    }
    fetched = {}
    holiday_suspected = False
    for key, url in dated.items():
        try:
            fetched[key] = c.get(url, referer=f"{BASE}/all-reports")
            record(key, True, f"{len(fetched[key]):,} bytes")
        except Exception as e:
            record(key, False, str(e))
            if key == "ind_close_all":
                holiday_suspected = True

    # ---- indices + sectoral 5-day series + VIX 20-day window -------------
    idx_series = {}
    for d in last_weekdays(HISTORY_SESSIONS, target):
        if d == target and "ind_close_all" in fetched:
            idx_series[d] = parse_ind_close_all(
                fetched["ind_close_all"].decode("utf-8", errors="replace"))
            continue
        try:
            raw = c.get(f"{ARCH}/content/indices/ind_close_all_{d.strftime('%d%m%Y')}.csv",
                        referer=f"{BASE}/all-reports")
            idx_series[d] = parse_ind_close_all(raw.decode("utf-8", errors="replace"))
        except Exception:
            pass
    days_found = sorted(idx_series)
    if days_found:
        latest = days_found[-1]
        pack["derived"]["indices"] = idx_series[latest]
        pack["derived"]["indices_date"] = latest.isoformat()
        # 5-session change = latest vs the close 5 sessions back (fixed window,
        # not days_found[0], which now spans ~22 sessions).
        five_day = {}
        if len(days_found) >= 6:
            base_d = days_found[-6]
            for name in MAIN_IDX + SECTORAL:
                a, b = idx_series[base_d].get(name), idx_series[latest].get(name)
                if a and b and a.get("close") and b.get("close"):
                    five_day[name] = round((b["close"] / a["close"] - 1) * 100, 2)
        pack["derived"]["five_day_change_pct"] = five_day
        pack["derived"].update(derive_vix_and_streak(idx_series, days_found))
        record("derived:indices+5day+vix", True,
               f"{len(idx_series[latest])} indices, {len(days_found)} sessions")
    if holiday_suspected and not idx_series:
        pack["meta"]["note"] = ("No index close file for target date - likely a "
                                "trading holiday or file not yet published.")

    # ---- Nifty-50 constituents (archive first, embedded fallback) ---------
    constituents, n50_source = N50_FALLBACK, "embedded_fallback_UNVERIFIED"
    if "nifty50_list" in fetched:
        try:
            got = parse_nifty50_list(
                fetched["nifty50_list"].decode("utf-8", errors="replace"))
            if len(got) >= 45:
                constituents, n50_source = got, "ind_nifty50list.csv"
        except Exception:
            pass
    pack["derived"]["nifty50_constituents"] = {"source": n50_source,
                                               "count": len(constituents),
                                               "symbols": constituents}
    if n50_source.startswith("embedded"):
        record("nifty50_list", False,
               "archive list unavailable - using embedded fallback, verify")

    # ---- breadth + movers + N50 movers + broader movers + 52wk -----------
    if "bhavdata_full" in fetched:
        bhav_text = fetched["bhavdata_full"].decode("utf-8", errors="replace")
        try:
            d = derive_from_bhavdata(bhav_text)
            pack["derived"].update(d)
            record("derived:breadth+movers", True,
                   f"A/D {d['breadth']['advances']}/{d['breadth']['declines']}")
        except Exception as e:
            record("derived:breadth+movers", False, str(e))
        try:
            eqidx = eq_bhav_index(bhav_text)
            pack["derived"]["nifty50_movers"] = derive_nifty50_movers(
                eqidx, constituents)
            record("derived:nifty50_movers", True,
                   f"{pack['derived']['nifty50_movers']['constituents_matched']} matched")
        except Exception as e:
            record("derived:nifty50_movers", False, str(e))
        try:
            pack["derived"]["broader_movers"] = derive_broader_movers(
                bhav_text, constituents)
            record("derived:broader_movers", True)
        except Exception as e:
            record("derived:broader_movers", False, str(e))
        if "high_low_52wk" in fetched:
            try:
                raw52 = fetched["high_low_52wk"].decode("utf-8", errors="replace")
                intl = derive_52wk_internals(raw52, bhav_text)
                pack["derived"]["internals_52wk"] = intl
                record("derived:internals_52wk", True,
                       f"{intl['new_highs']} highs / {intl['new_lows']} lows")
            except Exception as e:
                record("derived:internals_52wk", False, str(e))

    # ---- option metrics from FO bhavcopy (EOD baseline) -------------------
    if "fo_bhavcopy_zip" in fetched:
        for sym in ("NIFTY", "BANKNIFTY"):
            try:
                m = derive_option_metrics(fetched["fo_bhavcopy_zip"], sym)
                pack["derived"][f"options_{sym}"] = m
                record(f"derived:options_{sym}", True,
                       f"expiry {m['expiry']}, PCR {m['pcr_oi']}, max pain {m['max_pain']}")
            except Exception as e:
                record(f"derived:options_{sym}", False, str(e))

    # ---- bulk deals (round-trip filtered, signals from the FULL list) -----
    if "bulk_deals" in fetched:
        try:
            rows = clean_rows(fetched["bulk_deals"].decode("utf-8", errors="replace"))
            dc = next((k for k in (rows[0].keys() if rows else []) if "Date" in k), None)
            todays = [r for r in rows if dc and parse_dt(r.get(dc)) == target]
            # bulk.csv is a ROLLING window, not a per-date archive. If the file
            # covers a date range that excludes the target, "0 deals today" is
            # not a fact about the target session - it just fell out of the
            # window. Distinguish the two so the report can say "unavailable"
            # rather than "no bulk deals reported today".
            covered = sorted({d for d in (parse_dt(r.get(dc)) for r in rows)
                              if d} ) if dc else []
            in_window = bool(covered) and covered[0] <= target <= covered[-1]
            stale = bool(covered) and not in_window
            bulk = {"count": len(todays), "rows": todays[:80]}
            if covered:
                bulk["window"] = [covered[0].isoformat(), covered[-1].isoformat()]
            if stale:
                bulk["stale_warning"] = True
                bulk["note"] = ("bulk.csv is a rolling window covering "
                                f"{covered[0]} to {covered[-1]}; it does not "
                                f"include {target}, so bulk-deal coverage for "
                                "the target session is unavailable (not zero).")
            pack["derived"]["bulk_deals_today"] = bulk
            sig = derive_bulk_signals(todays, target)
            if stale:
                sig["stale_warning"] = True
                sig["note"] = bulk["note"]
            pack["derived"]["bulk_deals_signals"] = sig
            record("derived:bulk_deals", True,
                   f"{len(todays)} raw, {sig['count']} one-sided >= "
                   f"Rs {BULK_MIN_VALUE_CR:.0f} Cr"
                   + (f" - WARNING: window {covered[0]}..{covered[-1]} excludes "
                      f"{target} (stale)" if stale else ""))
        except Exception as e:
            record("derived:bulk_deals", False, str(e))

    # ---- F&O ban list parsed + entry/exit diff vs prior session ----------
    if "fo_ban_list" in fetched:
        try:
            prior_syms = None
            # scan back up to 4 days for the most recent prior pack (accepts
            # both the full pack and the trimmed *_compiler.json)
            for back in range(1, 5):
                prev = target - timedelta(days=back)
                candidates = [f"stockpulse_datapack_{prev.isoformat()}.json",
                              f"stockpulse_datapack_{prev.isoformat()}_compiler.json"]
                for p in candidates:
                    if os.path.exists(p):
                        try:
                            pj = json.load(open(p))
                            prior_syms = (pj.get("derived", {})
                                          .get("fo_ban", {}).get("symbols"))
                        except Exception:
                            prior_syms = None
                        if prior_syms is not None:
                            break
                if prior_syms is not None:
                    break
            pack["derived"]["fo_ban"] = parse_ban_list(
                fetched["fo_ban_list"].decode("utf-8", errors="replace"),
                prior_syms, target)
            _ban = pack["derived"]["fo_ban"]
            record("derived:fo_ban", True,
                   f"{_ban['count']} names for {_ban['trade_date']}"
                   + (" - WARNING: not the session after the target date "
                      "(stale)" if _ban.get("stale_warning") else ""))
        except Exception as e:
            record("derived:fo_ban", False, str(e))

    for key in ("participant_oi", "participant_vol", "high_low_52wk",
                "fo_ban_list", "bhavdata_full"):
        if key in fetched:
            pack["data"][key] = fetched[key].decode("utf-8", errors="replace")

    # ---- participant-wise OI: compute the four-cohort net table ------------
    if "participant_oi" in fetched:
        try:
            poi = derive_participant_oi(
                fetched["participant_oi"].decode("utf-8", errors="replace"))
            if poi:
                pack["derived"]["participant_oi"] = poi
                record("derived:participant_oi", True,
                       f"{len(poi)} cohorts (Client/DII/FII/Pro)")
            else:
                record("derived:participant_oi", False, "no cohort rows parsed")
        except Exception as e:
            record("derived:participant_oi", False, str(e))

    # ---- Kite Connect (optional) ------------------------------------------
    if KITE_API_KEY and KITE_API_SECRET:
        try:
            ohlc = kite_get("/quote/ohlc", params=[
                ("i", "NSE:NIFTY 50"), ("i", "NSE:NIFTY BANK"),
                ("i", "NSE:INDIA VIX")]).json()["data"]
            pack["data"]["kite_index_quotes"] = ohlc
            record("kite:index_quotes", True)
            spots = {}
            for key, idx in (("NIFTY", "NSE:NIFTY 50"), ("BANKNIFTY", "NSE:NIFTY BANK")):
                q = ohlc.get(idx, {})
                spots[key] = (q.get("last_price")
                              or (q.get("ohlc") or {}).get("close"))
            for sym, spot in spots.items():
                if not spot:
                    continue
                try:
                    m = kite_option_chain(sym, spot)
                    pack["derived"][f"options_{sym}_kite"] = m
                    record(f"kite:options_{sym}", True,
                           f"expiry {m['expiry']}, PCR {m['pcr_oi']}, "
                           f"ATM IV {m['atm_iv_pct']}%")
                except Exception as e:
                    record(f"kite:options_{sym}", False, str(e))
        except Exception as e:
            record("kite:session", False, str(e))
    else:
        print("  [SKIP] Kite Connect - no API key configured (optional)")

    # ---- FII/DII cash -----------------------------------------------------
    fii_done = False
    try:
        c.s.get(f"{BASE}/reports/fii-dii", timeout=c.timeout, headers={"Referer": BASE})
        time.sleep(1.5)
        data = c.get_json(f"{BASE}/api/fiidiiTradeReact", referer=f"{BASE}/reports/fii-dii")
        entries = data if isinstance(data, list) else data.get("data", [])
        labels = sorted({e.get("date") for e in entries
                         if isinstance(e, dict) and e.get("date")})
        stale = labels and not any(parse_dt(l) == target for l in labels)
        pack["data"]["fii_dii_cash"] = {"source": "NSE", "date_labels": labels,
                                        "stale_warning": bool(stale), "raw": data}
        record("fii_dii_cash", True,
               f"labels {labels}{' - WARNING: not today, may be stale' if stale else ''}")
        fii_done = True
    except Exception as e:
        record("fii_dii_cash (NSE)", False, str(e))
    if not fii_done:
        try:
            d = target.strftime("%d%%2F%m%%2F%Y")
            r = impersonate_get(
                f"https://api.bseindia.com/BseIndiaAPI/api/PseudoData/w"
                f"?strForType=1&strForFrom={d}&strForTo={d}",
                headers={"Referer": "https://www.bseindia.com/markets/"
                                    "equities/fii-dii.aspx",
                         "Accept": "application/json, text/plain, */*"},
                timeout=20)
            pack["data"]["fii_dii_cash"] = {"source": "BSE",
                                            "raw": loads_lenient(r.text)}
            record("fii_dii_cash (BSE fallback)", True)
        except Exception as e:
            record("fii_dii_cash (BSE fallback)", False, str(e))

    # ---- FII/DII net summary (for commentary + sanity bounds) -------------
    try:
        cash = pack["data"].get("fii_dii_cash", {})
        raw = cash.get("raw")
        entries = raw if isinstance(raw, list) else (raw or {}).get("data", [])
        summ = {}
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            cat = (e.get("category") or "").upper()
            net = num(e.get("netValue"))
            if net is None:
                continue
            if cat.startswith("FII") or cat.startswith("FPI"):
                summ["fii_net_cr"] = round(net, 2)
            elif cat.startswith("DII"):
                summ["dii_net_cr"] = round(net, 2)
        if summ:
            summ["date_labels"] = cash.get("date_labels")
            summ["stale_warning"] = cash.get("stale_warning", False)
            pack["derived"]["fii_dii_cash_summary"] = summ
    except Exception:
        pass

    # (Nifty-50 gainers/losers are now computed from the bhavcopy in
    #  derived.nifty50_movers above; the flaky live /api/equity-stockIndices
    #  endpoint has been dropped so it no longer pollutes the gaps register.)

    # ---- holiday + corporate actions ---------------------------------------
    try:
        hol = c.get_json(f"{BASE}/api/holiday-master?type=trading",
                         referer=f"{BASE}/resources/exchange-communication-holidays")
        today_hol = [h for h in hol.get("CM", []) if parse_dt(h.get("tradingDate")) == target]
        pack["data"]["holiday_check"] = {
            "is_holiday": bool(today_hol),
            "detail": today_hol[0].get("description") if today_hol else None}
        record("holiday_check", True,
               f"HOLIDAY: {today_hol[0].get('description')}" if today_hol else "trading day")
    except Exception as e:
        record("holiday_check", False, str(e))

    try:
        # Per-day fetches (today / T+1 / T+2) so all three buckets populate.
        # A single undated call only ever returned the current ex-date, which
        # left ex_t1/ex_t2 empty by non-coverage (handover spec 9C).
        ca_raw, seen = [], set()
        for d in [target, *next_trading_days(target, 2)]:
            ds = d.strftime("%d-%m-%Y")
            try:
                chunk = c.get_json(
                    f"{BASE}/api/corporates-corporateActions?index=equities"
                    f"&from_date={ds}&to_date={ds}",
                    referer=f"{BASE}/companies-listing/corporate-filings-actions")
                if isinstance(chunk, list):
                    for r in chunk:
                        k = (r.get("symbol"), r.get("exDate"), r.get("subject"))
                        if k not in seen:
                            seen.add(k)
                            ca_raw.append(r)
            except Exception as e:
                record(f"corporate_actions:{d.isoformat()}", False, str(e))
        pack["data"]["corporate_actions_raw"] = ca_raw
        buckets = derive_corp_actions(ca_raw, target, constituents)
        if buckets is not None:
            pack["derived"]["corp_actions"] = buckets
            record("corporate_actions", True,
                   f"ex-today {len(buckets['ex_today'])}, T+1 {len(buckets['ex_t1'])}, "
                   f"T+2 {len(buckets['ex_t2'])}, "
                   f"Nifty50 in T+1/T+2 {len(buckets['nifty50_ex_t1_t2'])}")
        else:
            record("corporate_actions", True)
    except Exception as e:
        record("corporate_actions", False, str(e))

    # ---- FII F&O stats (binary xls - base64 so it survives JSON transit) ----
    for d in last_weekdays(6, target):
        try:
            raw = c.get(f"{ARCH}/content/fo/fii_stats_{d.strftime('%d-%b-%Y')}.xls",
                        referer=f"{BASE}/all-reports-derivatives")
            pack["data"]["fii_fno_stats_b64"] = base64.b64encode(raw[:600000]).decode("ascii")
            pack["data"]["fii_fno_stats_encoding"] = "base64/xls"
            pack["data"]["fii_fno_stats_date"] = d.isoformat()
            parsed = parse_fii_fno_stats(raw)
            if parsed:
                pack["derived"]["fii_fno_stats"] = {"date": d.isoformat(),
                                                    "segments": parsed}
                record("fii_fno_stats", True,
                       f"dated {d.isoformat()}, parsed {len(parsed)} segments")
            else:
                record("fii_fno_stats", True,
                       f"dated {d.isoformat()}, {len(raw):,} bytes "
                       "(base64 only - install xlrd to parse)")
            break
        except Exception:
            continue
    else:
        record("fii_fno_stats", False, "no file in last 6 sessions")

    # ---- optional yfinance global snapshot --------------------------------
    if ENABLE_YFINANCE:
        try:
            g, detail = fetch_global_yfinance(target)
            if g:
                pack["derived"]["global_markets"] = {
                    "note": ("US/Asia bars may be the prior session; Europe/US "
                             "may be intraday depending on capture time IST"),
                    "captured_ist": now_ist().strftime("%H:%M IST"),
                    "markets": g}
                record("derived:global_markets", True, detail)
            else:
                record("derived:global_markets", False, detail)
        except Exception as e:
            record("derived:global_markets", False, str(e))
    else:
        print("  [SKIP] yfinance global snapshot - ENABLE_YFINANCE is False (optional)")

    # ---- India 10Y G-sec yield (wire, best-effort) --------------------------
    try:
        y10, y10_err = fetch_india_10y()
        if y10:
            # Trading Economics serves the LATEST quote, not the target date's.
            # On a backfill the as-of date is a later session, so flag it.
            asof = parse_dt(y10.get("asof_text") or "") or _parse_long_date(
                y10.get("asof_text"))
            if asof and asof != target:
                y10["stale_warning"] = True
                y10["note"] = (f"wire quote is as of {y10.get('asof_text')}, "
                               f"not the target session {target}.")
            pack["derived"]["india_10y"] = y10
            record("india_10y", True,
                   f"{y10['yield_pct']}% ({y10.get('asof_text') or 'as of today'}, wire)"
                   + (" - WARNING: not the target date (stale)"
                      if y10.get("stale_warning") else ""))
        else:
            record("india_10y", False, y10_err or "no value parsed")
    except Exception as e:
        record("india_10y", False, str(e))

    # ---- sanity bounds (Section I, run before the model sees anything) -----
    try:
        flags = run_sanity_checks(pack)
        pack["derived"]["sanity_flags"] = flags
        record("derived:sanity_flags", True,
               "all bounds passed" if not flags else f"{len(flags)} breach(es) flagged")
    except Exception as e:
        record("derived:sanity_flags", False, str(e))

    # ---- save ---------------------------------------------------------------
    out = f"stockpulse_datapack_{target.isoformat()}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(_sanitize(pack), f, ensure_ascii=False, default=str)
    tout = f"stockpulse_datapack_{target.isoformat()}_compiler.json"
    with open(tout, "w", encoding="utf-8") as f:
        json.dump(_sanitize(compiler_pack(pack)), f, ensure_ascii=False, default=str)
    print(f"""
Done.
  Derived sections : {len(pack['derived'])}
  Raw sections     : {len(pack['data'])}
  Gaps             : {len(pack['failures'])} (logged in the pack - not fatal)
  Output file      : {out}
  Compiler file    : {tout}   <-- upload THIS to the chat (raw blobs removed)

Upload '{tout}' back to the chat and ask for today's post-market analysis.
""")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="StockPulse data fetcher v3")
    ap.add_argument("--date", help="trade date DD-MM-YYYY (default: today IST)")
    a = ap.parse_args()
    tgt = (datetime.strptime(a.date, "%d-%m-%Y").date()
           if a.date else now_ist().date())
    collect(tgt)
