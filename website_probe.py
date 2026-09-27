"""Read-only provider diagnostics. Never publishes a market report or calls a model."""
import json
from pathlib import Path
from datetime import datetime,timedelta
from website_enrichment import IST,Sources,MOSPI,BLS,BEA,GIFT,mospi_events,calendar_ics,central_bank_events
def main():
    now=datetime.now(IST);end=(now.date()+timedelta(days=14)).isoformat()
    folder=Path("website-output");folder.mkdir(exist_ok=True)
    receipts={};sources=Sources(receipts,folder/"probe-evidence");result={}
    checks=[
      ("mospi",MOSPI,lambda raw:mospi_events(raw,now,end)),
      ("bls",BLS,lambda raw:calendar_ics(raw,now,end)),
      ("bea",BEA,lambda raw:calendar_ics(raw,now,end)),
      ("rbi","https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422",lambda raw:central_bank_events(raw,now,end,"RBI")),
      ("fed","https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",lambda raw:central_bank_events(raw,now,end,"Fed")),
      ("gift",GIFT,lambda raw:[r for block in json.loads(raw).get("MBP_data_Market_Watch",[]) for r in block.get("token_data",[]) if r.get("SYMBOL")=="NIFTY" and r.get("INSTRUMENTTYPE")=="FUTIDX"][:2])]
    for key,url,parser in checks:
        try:result[key]={"status":"parsed","rows":parser(sources.get(key,key,url,now.date().isoformat()))}
        except Exception as exc:result[key]={"status":"unavailable","reason":str(exc)[:180]}
    import yfinance as yf
    for ticker in ["BZ=F","CL=F","GC=F"]:
        try:
            info=yf.Ticker(ticker).get_info()
            result[ticker]={k:info.get(k) for k in ["symbol","shortName","longName","expireDate","underlyingSymbol","regularMarketTime"]}
        except Exception as exc:result[ticker]={"status":"unavailable","reason":type(exc).__name__}
    (folder/"provider-probe.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result))
if __name__=="__main__":main()
