"""Evidence-bound editorial briefing and liquid movers. No model or network calls."""
import csv,io,math
from datetime import date
from website_report import finite,fmt
from website_enrichment import official_url,stamp
def market_movers(pack,all_rows=False):
    text=pack.get("data",{}).get("bhavdata_full","")
    rows=[];seen=set();session=pack["meta"]["trading_date"]
    for raw in csv.DictReader(io.StringIO(text.strip())):
        r={k.strip():str(v or "").strip() for k,v in raw.items() if k}
        if r.get("SERIES")!="EQ":continue
        symbol=r.get("SYMBOL")
        if not symbol or symbol in seen:continue
        try:
            close=float(r["CLOSE_PRICE"].replace(",",""));previous=float(r["PREV_CLOSE"].replace(",",""))
            turnover=float(r["TURNOVER_LACS"].replace(",",""))/100
            delivery=float(r.get("DELIV_PER","").replace(",",""))
        except ValueError:delivery=None
        except KeyError:continue
        try:
            close=float(r["CLOSE_PRICE"].replace(",",""));previous=float(r["PREV_CLOSE"].replace(",",""));turnover=float(r["TURNOVER_LACS"].replace(",",""))/100
        except (ValueError,KeyError):continue
        if not all(finite(x) for x in (close,previous,turnover)) or min(close,previous)<=0 or turnover<100:continue
        from website_report import parse_date
        if parse_date(r.get("DATE1"))!=session:continue
        seen.add(symbol);rows.append({"symbol":symbol,"close":close,"change":round((close/previous-1)*100,2),"turnover":turnover,"delivery":delivery if finite(delivery) and 0<=delivery<=100 else None})
    if all_rows:return rows
    gain=sorted([r for r in rows if r["change"]>0],key=lambda r:(-r["change"],r["symbol"]))[:5]
    loss=sorted([r for r in rows if r["change"]<0],key=lambda r:(r["change"],r["symbol"]))[:5]
    events=pack.get("derived",{}).get("website_enrichment",{}).get("catalysts",[])
    out=[]
    for r in gain+loss:
        matching=[e for e in events if e.get("symbol")==r["symbol"] and official_url(e.get("url",""))]
        # Materiality is an editorial selection rule, not an investment score.
        event=max(matching,key=lambda e:(event_priority(e),e.get("publishedAt","")),default=None)
        note="No verified catalyst identified in reviewed filings."
        if event:
            ts=stamp(event.get("publishedAt"));after=bool(ts and (ts.hour,ts.minute)>(15,30))
            note=event["event"]+"; disclosed "+event["publishedAt"]+(". After the cash-market close; not an explanation of the earlier move." if after else ". Event documented; price causation is not established.")
        out.append({**r,"event":note,"url":event.get("url") if event else None})
    return out

def event_priority(e):
    import re
    kind=e.get("event","").lower()
    text=(kind+" "+e.get("detail","")).lower()
    if "reply to clarification" in kind or "substantial acquisition of shares and takeovers" in text:return 0
    if any(w in kind for w in ("financial result","acquisition","merger","demerger","default","insolvency","fraud","penalt")):return 3
    if any(w in text for w in ("order","contract","approval","buyback","rights issue","fund rais","capacity","acquisition of")):return 2
    return 1

def summary(pack,sections):
    d=pack["derived"];n=d["indices"]["Nifty 50"];b=d["breadth"];h=d.get("website_history",{}).get("fiveSessionChange",{})
    direction="rose" if n["pct_chg"]>0 else "fell" if n["pct_chg"]<0 else "was unchanged"
    text=f"Nifty 50 {direction} {fmt(abs(n['pct_chg']))}% to {fmt(n['close'])}."
    title="The session in context"
    if finite(h.get("Nifty 50")):
        text+=f" Its five-session change was {fmt(h['Nifty 50'],signed=True)}%."
        if n["pct_chg"]>0 and h["Nifty 50"]<0:title="A positive day within a weaker five-session period"
        elif n["pct_chg"]<0 and h["Nifty 50"]>0:title="A decline within a stronger five-session period"
        text+=" One session alone does not establish a change in trend."
    first={"title":title,"text":text,"refs":["derived.indices.Nifty 50","derived.website_history.fiveSessionChange.Nifty 50"]}
    relation="more securities advanced than declined" if b["advances"]>b["declines"] else "more securities declined than advanced" if b["advances"]<b["declines"] else "advances and declines were balanced"
    text=f"In the NSE EQ universe, {relation}: {fmt(b['advances'],0)} advances and {fmt(b['declines'],0)} declines."
    internals=d.get("internals_52wk",{}) if any(s["id"]=="internals" and s["status"]=="available" for s in sections) else {}
    if isinstance(internals.get("new_highs"),int) and isinstance(internals.get("new_lows"),int):
        text+=f" The separate adjusted 52-week measure recorded {internals['new_highs']} new highs and {internals['new_lows']} new lows."
        if b["advances"]>b["declines"] and internals["new_lows"]>internals["new_highs"]:text+=" Daily participation was stronger than this longer-horizon measure; the two describe different aspects of the market."
    second={"title":"A divergence to note" if (n["pct_chg"]>0 and b["advances"]<b["declines"]) or (n["pct_chg"]<0 and b["advances"]>b["declines"]) else "Look beneath the headline index","text":text,"refs":["derived.breadth","derived.internals_52wk"]}
    from website_report import SECTORS
    sectors=[(k,d["indices"][k]["pct_chg"]) for k in SECTORS if k in d["indices"] and finite(d["indices"][k].get("pct_chg"))]
    text="Sector observations are descriptive; no causal explanation is inferred."
    if sectors:
        top=max(sectors,key=lambda x:x[1]);bottom=min(sectors,key=lambda x:x[1])
        text=f"Among configured sectors, {top[0]} had the strongest daily change ({fmt(top[1],signed=True)}%); {bottom[0]} had the weakest ({fmt(bottom[1],signed=True)}%)."
        if all(finite(h.get(x[0])) for x in (top,bottom)):text+=f" Their five-session changes were {fmt(h[top[0]],signed=True)}% and {fmt(h[bottom[0]],signed=True)}%, respectively."
        text+=" This comparison shows relative performance, not an investment ranking."
    return [first,second,{"title":"Where performance differed","text":text,"refs":["derived.indices","derived.website_history.fiveSessionChange"]}]
