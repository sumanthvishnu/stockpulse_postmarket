"""Supplemental bonds, FX and explicitly identified commodity contracts."""
import io,json,re
import xml.etree.ElementTree as ET
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from website_report import IST,finite
from website_enrichment import stamp

TREASURY="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
INDIA="https://tradingeconomics.com/india/government-bond-yield"

def treasury_yield(raw,cutoff):
    rows=[]
    for prop in ET.fromstring(raw).iter():
        if prop.tag.split("}")[-1]!="properties":continue
        fields={e.tag.split("}")[-1]:e.text for e in prop}
        try:
            day=date.fromisoformat(fields["NEW_DATE"][:10]);value=float(fields["BC_10YEAR"])
        except (KeyError,ValueError,TypeError):continue
        # Daily US observations become eligible only after that New York calendar day
        # ends. This conservative rule excludes the current/live US session.
        eligible=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZoneInfo("America/New_York"))
        if eligible<=cutoff and finite(value) and value>=0:rows.append((day,value))
    if not rows:raise ValueError("No completed US day in Treasury feed")
    day,value=max(rows)
    if (cutoff.date()-day).days>4:raise ValueError("Treasury feed older than bounded holiday allowance")
    return {"name":"US Treasury 10-year par yield","value":value,"unit":"percent per annum","observedAt":day.isoformat()+" (completed US day)","basis":"Official daily par yield; not an intraday quote"}

def india_yield(raw,target,cutoff):
    text=raw.decode("utf-8")
    match=re.search(r"TEChartsMeta\s*=\s*(\[.*?\]);",text,re.S)
    if not match:raise ValueError("India yield instrument metadata absent")
    rows=json.loads(match.group(1))
    item=next((r for r in rows if r.get("symbol")=="GIND10YR:IND"),None)
    if not item or not finite(item.get("value")):raise ValueError("India 10Y instrument value missing")
    scripts=re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',text,re.S)
    dataset=None
    for script in scripts:
        try:obj=json.loads(script)
        except ValueError:continue
        for r in obj.get("@graph",[]):
            if r.get("@type")=="Dataset" and r.get("url")==INDIA:dataset=r
    if not dataset:raise ValueError("India yield dated dataset absent")
    modified=stamp(dataset.get("dateModified"))
    version=str(dataset.get("version",""))
    if version!=target.strftime("%Y%m%d") or not modified or modified>cutoff:raise ValueError("India yield does not match report cutoff")
    return {"name":"India 10-year government yield","value":item["value"],"unit":"percent per annum","observedAt":target.isoformat()+" (vendor daily observation)","basis":"Trading Economics indicative OTC yield; not independently cross-verified"}

def run(pack,receipts,sources,target,cutoff):
    d=pack["derived"];out={"rows":[],"gaps":[]}
    for key,label,url,parser in [
        ("us10y","US Treasury daily par yield",TREASURY+"?data=daily_treasury_yield_curve&field_tdr_date_value="+str(target.year),lambda raw:treasury_yield(raw,cutoff)),
        ("india10y","Trading Economics India 10-year indicative yield",INDIA,lambda raw:india_yield(raw,target,cutoff))]:
        try:
            raw=sources.get(key,label,url,target.isoformat());row=parser(raw);row["sourceId"]=key;out["rows"].append(row)
        except Exception as e:receipts.pop(key,None);out["gaps"].append({"section":label,"reason":str(e)[:180]})
    import yfinance as yf
    from website_context import store_source
    # Contracts must carry a stated expiry. No silent assignment of today's front
    # contract to a historical day across a possible roll.
    for label,ticker,unit,contract in [("USD/INR","INR=X","Rs per USD",False),("Brent","BZ=F","USD per barrel",True),("WTI","CL=F","USD per barrel",True),("Gold","GC=F","USD per troy ounce",True)]:
        key="asset:"+ticker
        try:
            t=yf.Ticker(ticker);expiry=None;name=label
            if contract:
                if target!=datetime.now(IST).date():raise ValueError("Historical contract identity requires an archived contract snapshot")
                info=t.get_info()
                expiry=info.get("expireDate");contract_name=info.get("shortName") or info.get("longName")
                if not isinstance(expiry,int) or not contract_name:raise ValueError("Vendor did not identify contract expiry")
                expiry=datetime.fromtimestamp(expiry,IST).date().isoformat()
                if expiry<target.isoformat():raise ValueError("Expired vendor contract")
                name=contract_name
            bars=t.history(start=target.isoformat(),end=(target+timedelta(days=1)).isoformat(),interval="5m",auto_adjust=False,timeout=12)
            candidates=[]
            for index,row in bars.iterrows():
                observed=index.to_pydatetime().astimezone(IST)+timedelta(minutes=5)
                value=float(row["Close"])
                if observed.date()==target and observed<=cutoff and 0<=(cutoff-observed).total_seconds()<=5400 and finite(value) and value>0:candidates.append((observed,value))
            if not candidates:raise ValueError("No completed 5-minute vendor bar within 90 minutes of cutoff")
            observed,value=max(candidates)
            quote={"name":name+(" / expiry "+expiry if expiry else ""),"value":value,"unit":unit,"observedAt":observed.isoformat(),"basis":"Vendor indicative 5-minute bar; not an official settlement","sourceId":key}
            store_source(receipts,sources.folder,key,"Yahoo Finance vendor: "+name,"https://finance.yahoo.com/quote/"+ticker.replace("=","%3D")+"/",quote,target.isoformat())
            out["rows"].append(quote)
        except Exception as e:out["gaps"].append({"section":label,"reason":str(e)[:180]})
    d["website_assets"]=out
    return out
