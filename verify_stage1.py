#!/usr/bin/env python3
"""Stage-1 verification: exercise every new/changed function."""
import json
import sys
from datetime import date

sys.path.insert(0, "/home/user/stockpulse")
import stockpulse_data_fetcher as f  # noqa: E402

pack = json.load(open("/home/user/stockpulse/stockpulse_datapack_2026-08-21.json",
                      encoding="utf-8"))

# --- 1) participant OI (new derived table) -------------------------------
print("=== derived.participant_oi ===")
poi = f.derive_participant_oi(pack["data"]["participant_oi"])
for k, v in poi.items():
    print(f"  {k:8s} net_index_fut={v['net_index_futures']:>9}  "
          f"net_stock_fut={v['net_stock_futures']:>9}  "
          f"total_long={v['total_long']:>9}  total_short={v['total_short']:>9}  "
          f"net_total={v['net_total']:>9}")

assert set(poi) == {"Client", "DII", "FII", "Pro"}, "cohorts missing"
assert poi["FII"]["net_index_futures"] == 26060 - 235915
assert poi["FII"]["net_stock_futures"] == 3655491 - 2973732
assert poi["DII"]["net_stock_futures"] == 366957 - 4485936
assert poi["Client"]["total_long"] == 13182329
assert poi["Pro"]["total_short"] == 5171785
assert poi["FII"]["net_total"] == 5928107 - 5280923
print("  OK: hand-checked arithmetic matches\n")

# --- 2) India 10Y (live) -------------------------------------------------
print("=== india_10y (live) ===")
y, err = f.fetch_india_10y()
print("  ", y if y else f"GAP: {err}")

# --- 3) corporate actions per-day (live) ---------------------------------
print("\n=== corporate actions per-day (live) ===")
target = date(2026, 8, 21)
days = [target] + f.next_trading_days(target, 2)
ca_raw, seen = [], set()
for d in days:
    ds = d.strftime("%d-%m-%Y")
    url = (f"https://www.nseindia.com/api/corporates-corporateActions"
           f"?index=equities&from_date={ds}&to_date={ds}")
    r = f.impersonate_get(url, headers={
        "User-Agent": f.HEADERS["User-Agent"],
        "Accept": "application/json"}, timeout=25)
    chunk = r.json()
    print(f"  {d.isoformat()}: {len(chunk)} actions")
    for x in chunk:
        k = (x.get("symbol"), x.get("exDate"), x.get("subject"))
        if k not in seen:
            seen.add(k)
            ca_raw.append(x)

constituents = pack["derived"]["nifty50_constituents"]["symbols"]
buckets = f.derive_corp_actions(ca_raw, target, constituents)
print(f"  buckets -> ex_today={len(buckets['ex_today'])}, "
      f"ex_t1={len(buckets['ex_t1'])}, ex_t2={len(buckets['ex_t2'])}, "
      f"nifty50_ex_t1_t2={len(buckets['nifty50_ex_t1_t2'])}")
assert len(buckets["ex_t1"]) > 0 and len(buckets["ex_t2"]) > 0, \
    "T+1/T+2 still empty after fix!"
print("  OK: T+1 and T+2 buckets populate (the sample pack had 0/0)\n")

print("ALL STAGE-1 CHECKS PASSED")
