#!/usr/bin/env python3
"""StockPulse datapack trimmer.

Squeezes a full fetcher JSON into the compiler-ready subset. The raw archive
blobs (bhavcopy, 52-week reference, FII .xls base64, raw corporate actions)
are fully superseded by the derived.* sections the report compiler reads, so
dropping them cuts the token payload ~85-90% when the pack is pasted to an
LLM. Keeps meta, derived, failures, and the small data.* items the skill
still references (participant OI/vol, holiday check, FII/DII cash).

Usage:
    python trim_datapack.py stockpulse_datapack_2026-08-21.json
    python trim_datapack.py in.json out.json
"""
import json
import os
import sys

DROP_KEYS = ("bhavdata_full", "high_low_52wk", "fo_ban_list",
             "fii_fno_stats_b64", "corporate_actions_raw")


def human(n):
    return f"{n/1024:,.0f} KB" if n >= 1024 else f"{n:,} B"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".json", "_compiler.json")
    pack = json.load(open(src, encoding="utf-8"))
    data = pack.get("data", {})
    def size_of(v):
        if isinstance(v, str):
            return human(len(v))
        if isinstance(v, (list, dict)):
            return f"{len(v)} items"
        return "present"
    dropped = {k: size_of(v) for k, v in data.items() if k in DROP_KEYS}
    for k in DROP_KEYS:
        data.pop(k, None)
    json.dump(pack, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
    before, after = os.path.getsize(src), os.path.getsize(dst)
    print(f"Full pack      : {human(before)}")
    print(f"Compiler pack  : {human(after)}  ({after/before*100:.1f}% of original)")
    print(f"Dropped blobs  : {', '.join(dropped) or 'none'}")
    print(f"Derived kept   : {len(pack.get('derived', {}))} sections")
    print(f"Failures kept  : {len(pack.get('failures', []))} entries")
    print(f"Written        : {dst}")


if __name__ == "__main__":
    main()
