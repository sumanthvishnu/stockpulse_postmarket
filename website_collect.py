"""Run the existing collector with source receipts, then publish a validated snapshot."""
from __future__ import annotations
import argparse, copy, hashlib, io, json, os, re, sys, zipfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from website_report import IST, build_report, canonical, parse_date, write_report

def source_key(url, target):
    path=urlparse(url).path
    dd=target.strftime("%d%m%Y")
    mapping={f"ind_close_all_{dd}.csv":"indices",f"sec_bhavdata_full_{dd}.csv":"bhavcopy",f"fao_participant_oi_{dd}.csv":"participant",f"CM_52_wk_High_low_{dd}.csv":"highlow",f"BhavCopy_NSE_FO_0_0_0_{target:%Y%m%d}_F_0000.csv.zip":"options","ind_nifty50list.csv":"constituents","fo_secban.csv":"ban","bulk.csv":"bulk","fiidiiTradeReact":"cash","holiday-master":"calendar",f"fii_stats_{target:%d-%b-%Y}.xls":"fii_fno"}
    for suffix,key in mapping.items():
        if path.endswith(suffix):
            return key
    if path.endswith("corporates-corporateActions"):
        val=parse_qs(urlparse(url).query).get("from_date",[""])[0]
        return "actions:"+str(parse_date(val))
    return None

def validate_source(key, payload, target, fetcher):
    text=payload.decode("utf-8",errors="replace")
    session=target.isoformat()
    if key in ("indices","bhavcopy"):
        rows=fetcher.clean_rows(text)
        field="Index Date" if key=="indices" else "DATE1"
        dates={parse_date(r.get(field)) for r in rows}
        if dates!={session}:
            raise ValueError(key+" body date mismatch or unknown")
        if len(rows)<(6 if key=="indices" else 100):
            raise ValueError(key+" incomplete source")
    elif key=="options":
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names=[n for n in z.namelist() if n.endswith(".csv")]
            if len(names)!=1 or z.getinfo(names[0]).file_size>100_000_000:
                raise ValueError("Unexpected options archive")
            rows=fetcher.clean_rows(z.read(names[0]).decode("utf-8"))
        dates={parse_date(r.get("TradDt")) for r in rows}
        if dates!={session}: raise ValueError("Options date mismatch")
    elif key=="participant":
        # The exchange CSV has a dated title above its column headings.
        matches=re.findall(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4}|[A-Za-z]{3} \d{1,2}, \d{4}", text.splitlines()[0])
        if session not in [parse_date(x) for x in matches]: raise ValueError("Participant title date missing")
    elif key=="calendar":
        obj=json.loads(text)
        if not isinstance(obj,dict) or not isinstance(obj.get("CM"),list) or not obj["CM"]:
            raise ValueError("Holiday master coverage missing")
        years={parse_date(x.get("tradingDate",""))[:4] for x in obj["CM"] if parse_date(x.get("tradingDate",""))}
        if str(target.year) not in years: raise ValueError("Holiday calendar year missing")
    elif key.startswith("actions:"):
        values=json.loads(text)
        day=key.split(":",1)[1]
        if not isinstance(values,list) or any(not isinstance(x,dict) or parse_date(x.get("exDate"))!=day for x in values):
            raise ValueError("Corporate actions response invalid")
    elif key=="cash":
        values=json.loads(text)
        values=values if isinstance(values,list) else values.get("data",[])
        if not values or {parse_date(x.get("date")) for x in values}!={session}: raise ValueError("Cash date mismatch")
    elif key=="constituents":
        symbols=fetcher.parse_nifty50_list(text)
        if len(symbols)!=50 or len(set(symbols))!=50: raise ValueError("Constituent coverage mismatch")
        # An undated current membership file cannot establish historical membership.
        if target!=datetime.now(IST).date(): raise ValueError("Historical membership not established by current file")
    elif key=="highlow":
        lines=text.splitlines()
        match=re.search(r"Effective for (\d{1,2}-[A-Za-z]{3}-\d{4})", "\n".join(lines[:3]))
        if not match or parse_date(match.group(1))!=session or "adjusted for corporate actions" not in lines[0].lower():
            raise ValueError("Adjusted reference metadata missing or wrong date")
        rows=fetcher.clean_rows("\n".join(lines[2:]))
        if len(rows)<100 or not {"SYMBOL","SERIES","Adjusted_52_Week_High","Adjusted_52_Week_Low"}.issubset(rows[0]):
            raise ValueError("Adjusted reference columns missing")
    elif key=="fii_fno":
        import xlrd
        sheet=xlrd.open_workbook(file_contents=payload).sheet_by_index(0)
        dates=[]
        for row in range(min(sheet.nrows,6)):
            for col in range(sheet.ncols):
                value=str(sheet.cell_value(row,col))
                dates.extend(re.findall(r"\d{1,2}-[A-Za-z]{3}-\d{4}|\d{1,2}/\d{1,2}/\d{4}",value))
        if session not in [parse_date(x) for x in dates]: raise ValueError("FII derivatives body date missing")
    elif key=="bulk":
        rows=fetcher.clean_rows(text)
        if not rows or not any(parse_date(r.get("Date"))==session for r in rows):
            raise ValueError("No dated bulk-deal coverage for the session")
    elif key=="ban":
        result=fetcher.parse_ban_list(text)
        if not parse_date(result.get("trade_date")): raise ValueError("Ban date missing")

def collect_report(target, output):
    import stockpulse_data_fetcher as fetcher
    receipts={}
    archives=Path(output)/"evidence"; archives.mkdir(parents=True,exist_ok=True)
    OriginalClient=fetcher.Client
    class RecordingClient(OriginalClient):
        def __init__(self,*args,**kwargs):
            super().__init__(timeout=20,retries=1,pause=1)
        def get(self,url,referer=None,headers=None):
            # Accept a valid JSON [] corporate-action response; short transport bodies
            # are not universally errors. One bounded request, no bypass or identity change.
            if not self._primed: self.prime()
            response=self._raw_get(url,headers={"Referer":referer or fetcher.BASE,**(headers or {})})
            if response.status_code!=200: raise RuntimeError("HTTP "+str(response.status_code))
            payload=response.content
            if not payload: raise RuntimeError("Empty body")
            key=source_key(url,target)
            if key:
                digest=hashlib.sha256(payload).hexdigest()
                (archives/(digest+".source")).write_bytes(payload)
                receipt={"label":key,"url":url,"sha256":digest,"retrievedAt":datetime.now(IST).isoformat(),"effectiveDate":key.split(":",1)[1] if key.startswith("actions:") else target.isoformat(),"status":"unavailable"}
                try:
                    validate_source(key,payload,target,fetcher)
                    receipt["status"]="validated"
                    if key=="ban":
                        receipt["effectiveDate"]=parse_date(fetcher.parse_ban_list(payload.decode("utf-8"))["trade_date"])
                except (ValueError,TypeError,KeyError,IndexError) as e:
                    receipt["reason"]=str(e)
                receipts[key]=receipt
            return payload
    fetcher.Client=RecordingClient
    fetcher.pack={"meta":{},"data":{},"derived":{},"failures":[]}
    fetcher.KITE_API_KEY=""
    fetcher.KITE_API_SECRET=""
    # Unvalidated vendor snapshots are not needed by this data-led edition.
    fetcher.ENABLE_YFINANCE=False
    fetcher.fetch_india_10y=lambda:(None,"Not collected: vendor session validation pending")
    fetcher.collect(target)
    pack=copy.deepcopy(fetcher.pack)
    if receipts.get("calendar",{}).get("status")!="validated":
        raise ValueError("Trading calendar unavailable")
    holidays=[parse_date(h.get("tradingDate")) for h in json.loads((archives/(receipts["calendar"]["sha256"]+".source")).read_text())["CM"]]
    if pack.get("data",{}).get("holiday_check",{}).get("is_holiday"):
        return {"state":"market_closed","session":target.isoformat(),"reason":pack["data"]["holiday_check"].get("detail") or "Exchange holiday"}
    if target.weekday()>=5:
        raise ValueError("Special weekend session is not independently configured")
    # Match all next-session logic to the same exchange holiday master.
    pack["derived"]["next_trading_session"]=fetcher.next_trading_session(target,holidays)
    ban=pack["derived"].get("fo_ban",{})
    ban["stale_warning"]=parse_date(ban.get("trade_date"))!=pack["derived"]["next_trading_session"]["date"]
    pack["derived"]["fo_ban"]=ban
    for key,r in receipts.items():
        if r["status"]!="validated":
            pack["failures"].append({"source":key,"reason":r.get("reason","Unverified source")})
    if receipts.get("bulk",{}).get("status")=="validated":
        bulk_text=(archives/(receipts["bulk"]["sha256"]+".source")).read_text(encoding="utf-8")
        pack["derived"]["website_bulk"]=[r for r in fetcher.clean_rows(bulk_text) if parse_date(r.get("Date"))==target.isoformat()]
    from website_context import context
    context(pack,receipts,archives,target)
    report=build_report(pack,receipts)
    # Keep receipt and original datapack with the workflow evidence artifact.
    (Path(output)/"datapack.json").write_text(canonical(pack),encoding="utf-8")
    (Path(output)/"receipts.json").write_text(canonical(receipts),encoding="utf-8")
    entry=write_report(report,output)
    return {"state":"available","session":target.isoformat(),"report":entry}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--output",default="website-output")
    args=parser.parse_args()
    target=date.fromisoformat(args.date) if args.date else datetime.now(IST).date()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    # Weekend default runs record market closure without downloading dozens of archives.
    if not args.date and target.weekday()>=5:
        status={"state":"market_closed","session":target.isoformat(),"reason":"Weekend; special-session support requires an exchange calendar override"}
    else:
        try:
            status=collect_report(target,output)
        except Exception as e:
            status={"state":"blocked","session":target.isoformat(),"reason":str(e)[:240]}
    status["checkedAt"]=datetime.now(IST).isoformat()
    (output/"status.json").write_text(canonical(status),encoding="utf-8")
    print(canonical({"state":status["state"],"session":target.isoformat(),"modelCalls":0}))
    if status["state"]=="blocked": sys.exit(2)

if __name__=="__main__": main()
