"""Validated, deterministic website reports. No model, publishing or network calls."""
from __future__ import annotations
import hashlib
import json
import math
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

VERSION = 1
IST = timezone(timedelta(hours=5, minutes=30))
SECTORS = ["Nifty IT", "Nifty Bank", "Nifty Financial Services", "Nifty Auto", "Nifty Metal", "Nifty FMCG", "Nifty Realty", "Nifty Pharma", "Nifty Healthcare Index", "Nifty Energy", "Nifty Oil & Gas", "Nifty PSU Bank", "Nifty Private Bank", "Nifty Media", "Nifty Consumer Durables", "Nifty Infrastructure"]
MAIN = ["Nifty 50", "Nifty Bank", "Nifty Next 50", "Nifty Midcap 150", "Nifty Smallcap 250", "India VIX"]

def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)

def fmt(value, places=2, signed=False):
    if not finite(value):
        return "Unavailable"
    n = Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return ("+" if signed and n > 0 else "") + f"{n:,.{places}f}"

def exact_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None

def parse_date(value):
    for pattern in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date().isoformat()
        except ValueError:
            pass
    return None

def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))

def build_report(pack, receipts, now=None):
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError("Timezone is required")
    d = pack.get("derived", {})
    raw = pack.get("data", {})
    session = exact_date(pack.get("meta", {}).get("trading_date"))
    if not session or session > now.astimezone(IST).date().isoformat():
        raise ValueError("Invalid or future trading session")
    if raw.get("holiday_check", {}).get("is_holiday"):
        raise ValueError("Market closed")
    if d.get("indices_date") != session:
        raise ValueError("Index session mismatch")
    def usable(key):
        r = receipts.get(key, {})
        return r.get("status") == "validated" and r.get("effectiveDate") == session and isinstance(r.get("sha256"), str) and len(r["sha256"]) == 64
    if not usable("indices") or not usable("bhavcopy"):
        raise ValueError("Original dated index and bhavcopy evidence required")
    indices = d.get("indices", {})
    nifty = indices.get("Nifty 50", {})
    if not all(finite(nifty.get(k)) for k in ("close", "pts_chg", "pct_chg")) or nifty["close"] <= 0:
        raise ValueError("Invalid Nifty snapshot")
    for name, row in indices.items():
        if not isinstance(row, dict):
            raise ValueError("Invalid index row")
        if all(finite(row.get(k)) for k in ("close", "pts_chg", "pct_chg")):
            previous = row["close"] - row["pts_chg"]
            if previous <= 0 or abs((row["close"] / previous - 1) * 100 - row["pct_chg"]) > .025:
                raise ValueError("Index change inconsistent: " + name)
    breadth = d.get("breadth", {})
    if not all(type(breadth.get(k)) is int and breadth[k] >= 0 for k in ("advances", "declines", "unchanged", "universe")):
        raise ValueError("Invalid breadth")
    if breadth["universe"] < 1 or sum(breadth[k] for k in ("advances", "declines", "unchanged")) != breadth["universe"]:
        raise ValueError("Breadth universe mismatch")
    expected_ad = breadth["advances"] / breadth["declines"] if breadth["declines"] else None
    if expected_ad is not None and (not finite(breadth.get("ad_ratio")) or abs(expected_ad - breadth["ad_ratio"]) > .0006):
        raise ValueError("Breadth ratio mismatch")
    if d.get("sanity_flags"):
        raise ValueError("Unresolved source plausibility flags")
    gaps, sections, sources = [], [], []
    source_ids = {}
    for key, rec in receipts.items():
        if rec.get("status") == "validated":
            source_ids[key] = len(sources)
            sources.append({"id":key,"label":rec.get("label",key),"url":rec["url"],"effectiveDate":rec["effectiveDate"],"retrievedAt":rec["retrievedAt"],"sha256":rec["sha256"]})
    def gap(section, reason):
        gaps.append({"section":section,"reason":reason})
    def section(key, title, columns, rows, source=None, note="", unavailable=None):
        status = "available" if rows else "unavailable"
        if unavailable:
            status = "partial" if rows else "unavailable"
            gap(title, unavailable)
        if not rows and not unavailable:
            gap(title, "No validated data available.")
        sections.append({"id":key,"title":title,"status":status,"columns":columns,"rows":rows,"sourceIds":[source] if source in source_ids else [],"note":note or unavailable or ""})
    def row(label, values, refs):
        return {"label":str(label),"values":values,"refs":refs}
    snapshot = [row(n,[fmt(indices.get(n,{}).get("close")),fmt(indices.get(n,{}).get("pts_chg"),signed=True),fmt(indices.get(n,{}).get("pct_chg"),signed=True)+"%"],["derived.indices."+n+"."+k for k in ("close","pts_chg","pct_chg")]) for n in MAIN if n in indices]
    section("snapshot","Market snapshot",["Index","Close","Change (pts)","Change (%)"],snapshot,"indices","NSE closing observations for "+session+". India VIX is an index, not a price.")
    section("sectors","Sector performance",["Index","Close","Change (%)"],[row(n,[fmt(indices[n].get("close")),fmt(indices[n].get("pct_chg"),signed=True)+"%"],["derived.indices."+n+".close","derived.indices."+n+".pct_chg"]) for n in SECTORS if n in indices],"indices","Configured NSE sector indices. No causal explanation is inferred from price changes.")
    history=d.get("website_history",{})
    changes=history.get("fiveSessionChange",{})
    hrows=[row(n,[fmt(changes[n],signed=True)+"%"],["derived.website_history.fiveSessionChange."+n]) for n in dict.fromkeys(MAIN+SECTORS) if finite(changes.get(n))]
    section("history","Five-session market context",["Index","Five-session change (%)"],hrows,None,"Five completed exchange sessions; only consecutive, dated archive coverage is used.")
    sections[-1]["sourceIds"]=[key for key in history.get("sourceIds",[])[:6] if key in source_ids]
    v=history.get("vix");vrows=[]
    if v:
        vrows=[row("India VIX",[fmt(v.get("current")),fmt(v.get("low")),fmt(v.get("high")),fmt(v.get("rangePosition"),1)+"%" if finite(v.get("rangePosition")) else "Constant range"],["derived.website_history.vix"])]
    section("vix-context","Volatility context",["Index","Current","21-session low","21-session high","Position in range"],vrows,"indices","Range position is not a percentile and does not predict future volatility. All 21 consecutive archive receipts are retained with the datapack.")
    section("breadth","Market breadth",["Measure","Count / ratio"],[row(k.replace("_"," ").title(),[fmt(breadth.get(k),3 if k=="ad_ratio" else 0)],["derived.breadth."+k]) for k in ("advances","declines","unchanged","universe","ad_ratio")],"bhavcopy","NSE EQ-series securities with valid current and previous closing prices. Delivery does not identify investor type.")
    constituents = d.get("nifty50_constituents", {})
    verified_members = usable("constituents") and constituents.get("count") == 50 and len(set(constituents.get("symbols",[]))) == 50
    for key,title in (("nifty50_movers","Nifty 50 movers"),("broader_movers","Broader-market movers")):
        moves=d.get(key,{})
        rows=[]
        if verified_members:
            for direction in ("gainers","losers"):
                for i,m in enumerate(moves.get(direction,[])[:5 if key=="nifty50_movers" else 8]):
                    if not all(finite(m.get(k)) for k in ("close","chg_pct","turnover_cr")) or m["close"] <= 0 or m["turnover_cr"] < 0:
                        continue
                    delivery=m.get("deliv_pct")
                    if finite(delivery) and not 0 <= delivery <= 100:
                        raise ValueError("Invalid delivery percentage")
                    prev=m.get("prev_close")
                    if finite(prev) and prev>0 and abs((m["close"]/prev-1)*100-m["chg_pct"])>.025:
                        raise ValueError("Mover change mismatch")
                    prefix=f"derived.{key}.{direction}.{i}."
                    rows.append(row(m["symbol"],[fmt(m["close"]),fmt(m["chg_pct"],signed=True)+"%",fmt(delivery)+"%" if finite(delivery) else "Unavailable",fmt(m["turnover_cr"],1)],[prefix+k for k in ("close","chg_pct","deliv_pct","turnover_cr")]))
        section(key,title,["Security","Close (Rs)","Change (%)","Delivery (%)","Turnover (Rs Cr)"],rows,"bhavcopy","Gainers followed by losers. Broader movers exclude Nifty 50 and require turnover of at least Rs 100 Cr.",None if verified_members else "Dated, complete Nifty 50 membership is unavailable.")
    internals=d.get("internals_52wk", {})
    rows=[]
    if usable("highlow"):
        for k in ("new_highs","new_lows"):
            if type(internals.get(k)) is int and internals[k]>=0:
                rows.append(row(k.replace("_"," ").title(),[fmt(internals[k],0)],["derived.internals_52wk."+k]))
    section("internals","52-week internals",["Measure","Count"],rows,"highlow","Adjusted reference-level join; closing price floor Rs 10. Counts are descriptive, not investment ratings.")
    cash=d.get("fii_dii_cash_summary",{})
    labels=[parse_date(x) for x in cash.get("date_labels") or []]
    rows=[]
    if usable("cash") and labels and all(x==session for x in labels) and not cash.get("stale_warning"):
        for k,label in (("fii_net_cr","FII / FPI"),("dii_net_cr","DII")):
            if finite(cash.get(k)):
                rows.append(row(label,[fmt(cash[k],signed=True)],["derived.fii_dii_cash_summary."+k]))
    section("cash","Institutional cash flows",["Participant","Net (Rs Cr)"],rows,"cash","Provisional cash-segment observations. These do not establish investment intent.")
    rows=[]
    if usable("participant"):
        poi=d.get("participant_oi",{})
        for label in ("Client","DII","FII","Pro"):
            v=poi.get(label,{})
            if all(type(v.get(k)) is int for k in ("net_index_futures","net_stock_futures")):
                rows.append(row(label,[fmt(v["net_index_futures"],0,True),fmt(v["net_stock_futures"],0,True)],["derived.participant_oi."+label+"."+k for k in ("net_index_futures","net_stock_futures")]))
        if len(rows)!=4:
            rows=[]
        elif sum(poi[x]["net_index_futures"] for x in poi)!=0 or sum(poi[x]["net_stock_futures"] for x in poi)!=0:
            raise ValueError("Participant net positions do not balance")
    section("positioning","Derivatives positioning",["Participant","Net index futures (contracts)","Net stock futures (contracts)"],rows,"participant","Outstanding positions, not daily flows. Client is not exclusively retail. No hedging or directional motive is inferred.")
    rows=[]
    stats=d.get("fii_fno_stats",{})
    if usable("fii_fno") and stats.get("date")==session:
        for label, v in stats.get("segments",{}).items():
            if all(finite(v.get(k)) for k in ("buy_cr","sell_cr","net_cr")):
                if abs(v["buy_cr"]-v["sell_cr"]-v["net_cr"])>.025:
                    raise ValueError("FII derivatives net mismatch")
                rows.append(row(label,[fmt(v["buy_cr"]),fmt(v["sell_cr"]),fmt(v["net_cr"],signed=True)],["derived.fii_fno_stats.segments."+label+"."+k for k in ("buy_cr","sell_cr","net_cr")]))
    section("fii-fno","FII derivatives activity",["Segment","Buy (Rs Cr)","Sell (Rs Cr)","Net (Rs Cr)"],rows,"fii_fno","Options turnover does not establish directional exposure.")
    rows=[]
    if usable("options"):
        for label in ("NIFTY","BANKNIFTY"):
            v=d.get("options_"+label,{})
            expiry=exact_date(v.get("expiry"))
            ce,pe=v.get("total_call_oi"),v.get("total_put_oi")
            if not expiry or expiry<session or not finite(ce) or ce<=0 or not finite(pe) or pe<0:
                continue
            if not finite(v.get("pcr_oi")) or abs(pe/ce-v["pcr_oi"])>.0006:
                raise ValueError("Options PCR mismatch")
            rows.append(row(label,[expiry,fmt(v["pcr_oi"],3),fmt(v.get("max_call_oi_strike")),fmt(v.get("max_put_oi_strike")),fmt(v.get("max_pain")),fmt(v.get("atm_strike"))],["derived.options_"+label+"."+k for k in ("expiry","pcr_oi","max_call_oi_strike","max_put_oi_strike","max_pain","atm_strike")]))
    section("options","Options dashboard",["Index","Expiry","OI PCR","Largest call OI strike","Largest put OI strike","Max pain","ATM"],rows,"options","Nearest expiry in the dated archive. OI concentrations and calculated payout minima are not forecasts or guaranteed support/resistance. ATM IV is not available.")
    calendar=receipts.get("calendar",{})
    next_session=d.get("next_trading_session",{}).get("date")
    calendar_ok=usable("calendar") and exact_date(next_session) and next_session>session
    actions=d.get("corp_actions",{})
    rows=[]
    action_gaps=[]
    for key,dk in (("ex_t1","t1_date"),("ex_t2","t2_date")):
        day=actions.get(dk)
        receipt=receipts.get("actions:"+str(day),{})
        valid=calendar_ok and receipt.get("status")=="validated" and receipt.get("effectiveDate")==day
        if not valid:
            action_gaps.append(str(day or key)+": corporate-action coverage unavailable")
        else:
            bucket=actions.get(key)
            if not isinstance(bucket,list):
                action_gaps.append(str(day)+": malformed action list")
            elif not bucket:
                rows.append(row(day,["No EQ-series actions found in validated coverage",""],["derived.corp_actions."+key]))
            else:
                for i,a in enumerate(bucket):
                    rows.append(row(day,[str(a.get("symbol","")),str(a.get("subject",""))],["derived.corp_actions."+key+"."+str(i)]))
    section("watchlist","Next-session watchlist",["Ex-date","Security / coverage","Corporate action"],rows,"calendar","Next trading session: "+(next_session if calendar_ok else "unverified")+". Upcoming actions are context, not evidence of dividend-capture activity.", "; ".join(action_gaps) or None)
    sections[-1]["sourceIds"]=[key for key in ("calendar","actions:"+str(actions.get("t1_date")),"actions:"+str(actions.get("t2_date"))) if key in source_ids]
    ban=d.get("fo_ban",{})
    ban_date=parse_date(ban.get("trade_date"))
    rows=[]
    if receipts.get("ban",{}).get("status")=="validated" and receipts["ban"].get("effectiveDate")==ban_date and calendar_ok and ban_date==next_session and not ban.get("stale_warning") and isinstance(ban.get("symbols"),list):
        rows=[row(ban_date,[", ".join(ban["symbols"]) or "No securities in the validated list"],["derived.fo_ban.symbols"])]
    section("ban","F&O ban list",["Trading date","Securities"],rows,"ban","Applies to the stated next trading session. Entry/exit changes are omitted unless prior comparable evidence is available.")
    context=d.get("website_context",{})
    globals=context.get("global",[])
    global_rows=[row(x["name"],[x["session"],fmt(x["close"]),fmt(x["pctChange"],signed=True)+"%"],["derived.website_context.global."+str(i)]) for i,x in enumerate(globals) if finite(x.get("close")) and finite(x.get("pctChange"))]
    section("global","Global context",["Index","Completed venue session","Close","Change (%)"],global_rows,None,"Vendor quotes for the latest completed local session available by the reporting cutoff. No live US quote is labelled a close.","Independent second-source verification is unavailable.")
    sections[-1]["sourceIds"]=[x["sourceId"] for x in globals if x.get("sourceId") in source_ids]
    enr=d.get("website_enrichment",{})
    coverage=enr.get("coverage",{})
    cats=enr.get("catalysts",[])
    rows=[row(x["symbol"],[x["publishedAt"],x["event"],x["detail"]],[f"derived.website_enrichment.catalysts.{i}"]) for i,x in enumerate(cats)]
    if not rows and coverage.get("catalysts")=="available":
        rows=[row("Reviewed NSE announcements",["By the report cutoff","No matching material event","No verified catalyst identified in the reviewed announcements."],["derived.website_enrichment.announcementCount"])]
    section("catalysts","Documented company events",["Security","Published (IST)","Event","Issuer disclosure"],rows,"catalysts","Selected dated issuer announcements, prioritising covered movers. These establish events, not why a share price moved.")
    sections[-1]["sourceIds"]+=list(dict.fromkeys(x["sourceId"] for x in cats if x.get("sourceId") in source_ids))[:3]
    results=enr.get("results",[])
    rows=[row(x["symbol"],[x["date"],x["purpose"]],[f"derived.website_enrichment.results.{i}"]) for i,x in enumerate(results[:30])]
    if not rows and coverage.get("results")=="available":
        rows=[row("NSE board-meeting calendar",["Through T+2","No results meetings found in the validated window"],["derived.website_enrichment.results"])]
    section("results","Upcoming results meetings",["Security","Meeting date","Published purpose"],rows,"results","Results-related NSE equity board meetings announced by cutoff. This is a meeting calendar, not a guarantee of a result release time. BSE-only issuers are outside this scope.")
    events=enr.get("calendar",[])
    rows=[row(x["event"],[x["country"],x["dateTime"],x["basis"]],[f"derived.website_enrichment.calendar.{i}"]) for i,x in enumerate(events[:30])]
    checked=[k for k in ("mospi","bls","bea","rbi","fed") if coverage.get(k)=="available"]
    if not rows and len(checked)==5:
        rows=[row("Configured official publishers",["India / US","Through T+2","No scheduled releases found in the checked window"],["derived.website_enrichment.calendar"])]
    section("calendar","Economic release watch",["Release","Economy","Date/time (IST)","Basis"],rows,None,"MoSPI macro releases plus US BLS and BEA. Dates are publisher schedules, not predictions. RBI MPC and Federal Reserve meetings are also checked. Other economies and private surveys are outside the configured coverage.",None if len(checked)==5 else "Some configured official calendars could not be validated.")
    sections[-1]["sourceIds"]=[k for k in checked if k in source_ids]
    gift=enr.get("gift");rows=[]
    if gift:
        rows=[row(gift["instrument"],[gift["expiry"],gift["observedAt"],fmt(gift["level"]),fmt(gift["spotDifference"],signed=True)],["derived.website_enrichment.gift"])]
    section("gift","GIFT Nifty evening futures",["Instrument","Expiry","Trade time (IST)","Level (points)","Difference vs Nifty close"],rows,"gift","Official NSE IX futures; the difference compares different observation times and is not a forecast of the next opening gap.")
    assets=d.get("website_assets",{})
    rows=[row(x["name"],[fmt(x["value"],3),x["unit"],x["observedAt"],x["basis"]],[f"derived.website_assets.rows.{i}"]) for i,x in enumerate(assets.get("rows",[]))]
    section("assets","Bonds, commodities and FX",["Instrument","Value","Unit","Observed","Basis"],rows,None,"Official US Treasury par yield and explicitly labelled vendor observations. Futures expiry is required; no continuous series is silently called a specific contract.","Some configured asset feeds are unavailable." if assets.get("gaps") else None)
    sections[-1]["sourceIds"]=[x["sourceId"] for x in assets.get("rows",[]) if x.get("sourceId") in source_ids][:10]
    for item in enr.get("gaps",[])+assets.get("gaps",[]):gap(item["section"],item["reason"])
    block_rows=[]
    for i,b in enumerate(enr.get("blocks",[])[:30]):
        try:q=float(str(b["Quantity Traded"]).replace(",",""));p=float(str(b["Trade Price / Wght. Avg. Price"]).replace(",",""))
        except (TypeError,ValueError,KeyError):continue
        if not finite(q) or not finite(p) or q<0 or p<0:continue
        block_rows.append(row(b.get("Symbol",""),[b.get("Client Name",""),b.get("Buy/Sell",""),fmt(q,0),fmt(p),fmt(q*p/10_000_000)],["derived.website_enrichment.blocks."+str(i)]))
    section("blocks","Disclosed block deals",["Security","Disclosed client","Side","Quantity","Price (Rs)","Value (Rs Cr)"],block_rows,"blocks","Dated NSE block transaction legs, maximum thirty rows. A transaction does not establish investor intent.")
    bulk_rows=[]
    if usable("bulk"):
        for i,b in enumerate(d.get("website_bulk",[])):
            try:
                quantity=float(str(b.get("Quantity Traded","")).replace(",",""));price=float(str(b.get("Trade Price / Wght. Avg. Price","")).replace(",",""))
            except ValueError:continue
            if not finite(quantity) or not finite(price) or quantity<=0 or price<=0 or b.get("Buy/Sell") not in ("BUY","SELL"):continue
            value=quantity*price/10_000_000
            if value<20:continue
            bulk_rows.append((value,row(b.get("Symbol",""),[b.get("Client Name",""),b["Buy/Sell"],fmt(quantity,0),fmt(price),fmt(value,2)],["derived.website_bulk."+str(i)])))
        bulk_rows.sort(key=lambda x:-x[0])
    section("deals","Disclosed bulk deals",["Security","Disclosed client","Side","Quantity","Price (Rs)","Value (Rs Cr)"],[r for _,r in bulk_rows[:20]],"bulk","Largest disclosed transaction legs of at least Rs 20 Cr, capped at twenty rows. Both buy and sell legs may appear. No market-making, round-trip or investment-intent inference is made.",None if coverage.get("blocks")=="available" else "Separate block-deal coverage could not be validated.")
    for reason in context.get("gaps",[]):gap("Context",reason)
    for failure in pack.get("failures",[]):
        gap(str(failure.get("source","Source")),str(failure.get("reason","Unavailable")))
    # No broad numeric whitelist: all copy is composed only from named validated fields.
    direction = "rose" if nifty["pct_chg"]>0 else "fell" if nifty["pct_chg"]<0 else "was unchanged"
    summary=[{"title":"The close","text":f"Nifty 50 {direction} {fmt(abs(nifty['pct_chg']))}% to {fmt(nifty['close'])}.","refs":["derived.indices.Nifty 50.close","derived.indices.Nifty 50.pct_chg"]}]
    advances,declines=breadth["advances"],breadth["declines"]
    if advances>declines:
        breadth_read="More EQ-series securities advanced than declined."
    elif advances<declines:
        breadth_read="More EQ-series securities declined than advanced."
    else:
        breadth_read="Advances and declines were balanced."
    summary.append({"title":"Participation","text":f"{breadth_read} Advances: {fmt(advances,0)}; declines: {fmt(declines,0)}; unchanged: {fmt(breadth['unchanged'],0)}.","refs":["derived.breadth.advances","derived.breadth.declines","derived.breadth.unchanged"]})
    if (nifty["pct_chg"]>0 and advances<declines) or (nifty["pct_chg"]<0 and advances>declines):
        summary.append({"title":"A divergence to note","text":"The headline index and the count of advancing versus declining securities pointed in opposite directions. Index weights and the equal-count breadth measure describe different aspects of the session.","refs":["derived.indices.Nifty 50.pct_chg","derived.breadth.advances","derived.breadth.declines"]})
    sector_values=[(n,indices[n]["pct_chg"]) for n in SECTORS if n in indices and finite(indices[n].get("pct_chg"))]
    if sector_values:
        top=max(sector_values,key=lambda x:x[1]); bottom=min(sector_values,key=lambda x:x[1])
        summary.append({"title":"Sector spread","text":f"Among the covered sector indices, {top[0]} had the strongest change ({fmt(top[1],signed=True)}%) and {bottom[0]} the weakest ({fmt(bottom[1],signed=True)}%).","refs":["derived.indices."+top[0]+".pct_chg","derived.indices."+bottom[0]+".pct_chg"]})
    if any(s["id"]=="cash" and len(s["rows"])==2 for s in sections):
        summary.append({"title":"Provisional institutional flows","text":f"FII / FPI net cash flow was Rs {fmt(cash['fii_net_cr'],signed=True)} Cr; DII net cash flow was Rs {fmt(cash['dii_net_cr'],signed=True)} Cr. These describe cash activity, not the motive behind derivatives positions.","refs":["derived.fii_dii_cash_summary.fii_net_cr","derived.fii_dii_cash_summary.dii_net_cr"]})
    if any(s["id"]=="internals" and len(s["rows"])==2 for s in sections):
        summary.append({"title":"Highs and lows","text":f"The adjusted reference join identified {fmt(internals['new_highs'],0)} new highs and {fmt(internals['new_lows'],0)} new lows among eligible securities. This breadth measure is descriptive, not a recommendation.","refs":["derived.internals_52wk.new_highs","derived.internals_52wk.new_lows"]})
    if cats:
        summary.append({"title":"Documented issuer events","text":"Selected disclosed events: "+ "; ".join(x["symbol"]+": "+x["event"] for x in cats[:3])+". The full table lists publication times; these events do not establish price causation.","refs":["derived.website_enrichment.catalysts"]})
    if events:
        summary.append({"title":"Upcoming economic releases","text":"; ".join(x["event"]+" — "+x["dateTime"] for x in events[:2])+". Check the detailed calendar for coverage and scheduling caveats.","refs":["derived.website_enrichment.calendar"]})
    summary.append({"title":"Read with the gaps","text":"This edition describes the validated market data. Any missing context, events and causal evidence are listed below; no investment recommendation or opening prediction is implied.","refs":[]})
    report={"schemaVersion":VERSION,"session":session,"generatedAt":now.isoformat(),"status":"available_with_gaps","edition":"reconstructed" if session!=now.astimezone(IST).date().isoformat() else "evening","title":"India post-market analysis","headline":"Nifty 50 "+direction+"; participation and sector performance in focus","summary":summary,"sections":sections,"sources":sources,"gaps":gaps,"nextSession":next_session if calendar_ok else None,"methodology":"StockPulse post-market v4: deterministic summary from named, dated datasets. Original archive identity and numeric consistency checks are recorded. Data completeness is separate from publication success. No model-generated facts or paid AI calls.","datapackSha256":hashlib.sha256(canonical(pack).encode()).hexdigest(),"modelCalls":0}
    body=canonical(report).encode()
    report["id"]=session+"-"+hashlib.sha256(body).hexdigest()[:16]
    return report

def write_report(report, output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    payload=canonical(report).encode()
    name=report["id"]+".json"
    reports=output/"reports"; reports.mkdir(exist_ok=True)
    path=reports/name
    if path.exists() and path.read_bytes()!=payload:
        raise ValueError("Immutable report collision")
    path.write_bytes(payload)
    return {"id":report["id"],"session":report["session"],"generatedAt":report["generatedAt"],"sha256":hashlib.sha256(payload).hexdigest(),"path":"reports/"+name,"status":report["status"]}
