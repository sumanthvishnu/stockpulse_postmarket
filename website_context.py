"""Optional vendor context. Failures remain gaps. No model calls."""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from website_report import IST, canonical, finite

def store_source(receipts, archives, key, label, url, payload, effective):
    data=canonical(payload).encode()
    digest=hashlib.sha256(data).hexdigest()
    (Path(archives)/(digest+".source")).write_bytes(data)
    receipts[key]={"status":"validated","label":label,"url":url,"sha256":digest,"effectiveDate":effective,"retrievedAt":datetime.now(IST).isoformat()}

def context(pack,receipts,archives,target):
    import pandas_market_calendars as calendars
    import yfinance as yf
    cutoff=datetime(target.year,target.month,target.day,20,30,tzinfo=IST)
    if target==datetime.now(IST).date():cutoff=min(cutoff,datetime.now(IST))
    output={"global":[],"gaps":[]}
    instruments=[("S&P 500","^GSPC","NYSE"),("Dow","^DJI","NYSE"),("Nasdaq Composite","^IXIC","NASDAQ"),("Nikkei 225","^N225","JPX"),("Hang Seng","^HSI","HKEX"),("Shanghai Composite","000001.SS","SSE"),("Kospi","^KS11","XKRX"),("FTSE 100","^FTSE","LSE"),("DAX","^GDAXI","XETR"),("Sensex","^BSESN","BSE")]
    for label,ticker,calendar in instruments:
        try:
            schedule=calendars.get_calendar(calendar).schedule(start_date=(target-timedelta(days=20)).isoformat(),end_date=target.isoformat())
            completed=schedule[schedule["market_close"]<=cutoff]
            if len(completed)<2:raise ValueError("Completed sessions unavailable")
            expected=completed.index[-1].date();previous=completed.index[-2].date()
            bars=yf.Ticker(ticker).history(start=previous.isoformat(),end=(target+timedelta(days=1)).isoformat(),auto_adjust=False,timeout=10)
            values={index.date():float(row["Close"]) for index,row in bars.iterrows() if finite(float(row["Close"]))}
            if expected not in values or previous not in values or values[previous]<=0:raise ValueError("Vendor bar not current for venue")
            close,prev=values[expected],values[previous]
            key="global:"+ticker
            observation={"name":label,"ticker":ticker,"session":expected.isoformat(),"close":close,"pctChange":round((close/prev-1)*100,2),"sourceId":key,"sessionClose":completed.iloc[-1]["market_close"].isoformat()}
            store_source(receipts,archives,key,"Yahoo Finance vendor: "+label,"https://finance.yahoo.com/quote/"+quote(ticker,safe="")+"/history/",observation,expected.isoformat())
            output["global"].append(observation)
        except Exception:
            output["gaps"].append(label+": a matching completed-session vendor bar was unavailable.")
    from website_verification import verify
    verify(output,receipts,archives)
    output["gaps"].append("Direct original-publisher checking is limited to Nasdaq Composite when matching dated data is available. Other vendor indices lack a second-source check; common upstream providers are not independent measurements.")
    pack["derived"]["website_context"]=output
