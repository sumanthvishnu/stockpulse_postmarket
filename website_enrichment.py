"""Dated source enrichment for the website edition. No language-model calls."""
from __future__ import annotations
import csv, hashlib, html, io, json, os, re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo
from website_report import IST, canonical, finite, parse_date

NSE="https://www.nseindia.com"
GIFT="https://www.nseix.com/api/streamer-market-watch/"
MOSPI="https://www.mospi.gov.in/uploads/documents/releaseCalender/1770293210621-ADVANCE%20RELEASE%20CALENDAR%202026-27%20FINAL%2005.02.2026.pdf"
BLS="https://www.bls.gov/schedule/news_release/bls.ics"
BEA="https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
MATERIAL=re.compile(r"order|contract|acqui|merger|demerger|approval|regulat|results|litigation|penalt|fund rais|rights|buyback|rating|dividend|capacity|agreement",re.I)

def stamp(value):
    if not value: return None
    for fmt in ("%d-%b-%Y %H:%M:%S","%d-%b-%Y %H:%M","%Y-%m-%d %H:%M:%S"):
        try:return datetime.strptime(str(value),fmt).replace(tzinfo=IST)
        except ValueError:pass
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.astimezone(IST) if d.tzinfo else None
    except ValueError:return None

def safe_text(value,limit=280):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>","",str(value or "")))).strip()[:limit]

def excerpt(value):
    words=safe_text(value,1000).split()
    return " ".join(words[:24])+("..." if len(words)>24 else "")

def official_url(value):
    try:
        u=urlparse(value)
        return u.scheme=="https" and u.hostname in ("nsearchives.nseindia.com","www.nseindia.com","www.bseindia.com")
    except (ValueError,TypeError):return False

def announcements(records,target,cutoff):
    if not isinstance(records,list):raise ValueError("Announcement response is not a complete list")
    selected=[];eligible=0
    for r in records:
        published=stamp(r.get("exchdisstime") or r.get("an_dt"))
        if not published or published.date()!=target or published>cutoff:continue
        eligible+=1
        description=safe_text(r.get("desc"))
        if re.search(r"shareholders|trading window|loss of share|certificate|voting|annual report|investor meet|analyst meet",description,re.I):continue
        if not MATERIAL.search(description+" "+str(r.get("attchmntText",""))):continue
        if not official_url(r.get("attchmntFile")):continue
        selected.append({"symbol":safe_text(r.get("symbol"),40),"publishedAt":published.isoformat(),
                         "event":description,"detail":excerpt(r.get("attchmntText")),
                         "url":r["attchmntFile"],"basis":"NSE issuer announcement; not a causal attribution"})
    selected.sort(key=lambda r:r["publishedAt"],reverse=True)
    unique=[];seen=set()
    for r in selected:
        key=(r["symbol"],r["event"])
        if key not in seen:unique.append(r);seen.add(key)
    return unique,eligible

def results_calendar(records,start,end,cutoff):
    if not isinstance(records,list):raise ValueError("Board-meeting response is not a complete list")
    rows=[];seen=set()
    for r in records:
        day=parse_date(r.get("bm_date"));announced=stamp(r.get("bm_timestamp"))
        if not day or not start<=day<=end or not announced or announced>cutoff:continue
        desc=safe_text(r.get("bm_purpose"))+" "+safe_text(r.get("bm_desc"),1500)
        if not re.search(r"financial results|quarterly results|audited results|accounts",desc,re.I):continue
        symbol=safe_text(r.get("bm_symbol"),40)
        if (symbol,day) in seen:continue
        seen.add((symbol,day))
        rows.append({"symbol":symbol,"date":day,"purpose":excerpt(r.get("bm_desc") or r.get("bm_purpose")),"announcedAt":announced.isoformat(),"url":r.get("attachment") if official_url(r.get("attachment")) else NSE+"/companies-listing/corporate-filings-board-meetings"})
    return sorted(rows,key=lambda x:(x["date"],x["symbol"]))

def gift_quote(payload,target,cutoff,spot):
    rows=payload.get("MBP_data_Market_Watch") if isinstance(payload,dict) else None
    if not isinstance(rows,list):raise ValueError("Official GIFT market-watch schema changed")
    candidates=[]
    for group in rows:
        for r in group.get("token_data",[]):
            if r.get("SYMBOL")!="NIFTY" or r.get("INSTRUMENTTYPE") not in ("FUTIDX","Index Futures"):continue
            expiry=parse_date(r.get("EXPIRYDATE"));observed=stamp(r.get("LTT"))
            try:price=float(str(r.get("LASTPRICE")).replace(",",""))
            except (TypeError,ValueError):continue
            if not expiry or expiry<target.isoformat() or not observed or observed.date()!=target or observed>cutoff:continue
            if observed.hour<18 or (cutoff-observed).total_seconds()>5400 or not finite(price) or price<=0:continue
            candidates.append({"expiry":expiry,"observedAt":observed.isoformat(),"level":price,"spotDifference":round(price-spot,2),"instrument":"NSE IX NIFTY index futures","unit":"index points"})
    if not candidates:raise ValueError("No official evening futures quote within cutoff and 90-minute freshness limit")
    candidates.sort(key=lambda r:(r["expiry"],-datetime.fromisoformat(r["observedAt"]).timestamp()))
    return candidates[0]

def trend_news(text,symbol,target,cutoff):
    lines=text.splitlines();header=None;out=[]
    for line in lines:
        cells=[x.strip() for x in line.split(" | ")]
        if cells and cells[0]=="NSEcode" and "pubDate" in cells:header=cells;continue
        if not header or len(cells)!=len(header):continue
        r=dict(zip(header,cells))
        if r.get("NSEcode")!=symbol:continue
        ts=stamp(r.get("pubDate"))
        if not ts or ts.date()!=target or ts>cutoff:continue
        if r.get("isPremium","").lower()=="true":continue
        url=r.get("url","")
        if not official_url(url):continue
        out.append({"symbol":symbol,"publishedAt":ts.isoformat(),"event":"Exchange filing indexed by Trendlyne","detail":excerpt(r.get("title")),"url":url,"basis":"Trendlyne-indexed filing metadata; not independently fetched"})
    return out[:1]

def calendar_ics(payload,cutoff,end):
    from icalendar import Calendar
    events=[];all_dates=[]
    for e in Calendar.from_ical(payload).walk("VEVENT"):
        if not e.get("DTSTART"):continue
        dt=e.decoded("DTSTART")
        if isinstance(dt,datetime):
            if not dt.tzinfo:raise ValueError("Calendar timestamp has no timezone")
            observed=dt.astimezone(IST);day=observed.date();display=observed.isoformat()
        else:day=dt;observed=None;display=dt.isoformat()+" (time not published)"
        all_dates.append(day)
        if day>date.fromisoformat(end) or (observed is not None and observed<=cutoff) or (observed is None and day<=cutoff.date()):continue
        events.append({"event":safe_text(e.get("SUMMARY"),160),"dateTime":display,"basis":"Official release calendar","country":"US"})
    if not all_dates or max(all_dates)<date.fromisoformat(end):raise ValueError("Official calendar does not cover the requested window")
    return events

def mospi_events(payload,cutoff,end):
    from pypdf import PdfReader
    text="\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(payload)).pages)
    match=re.search(r"CALENDAR\s*\(?(20\d{2})[-–](\d{2})",text)
    if not match:raise ValueError("MoSPI calendar fiscal-year header not found")
    year=int(match.group(1))
    if not date(year,4,1)<=date.fromisoformat(end)<=date(year+1,3,31):raise ValueError("MoSPI release calendar expired")
    # Bind each explicit printed date to its text up to the next printed date.
    months={"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    pattern=r"(\d{1,2})\s*(?:st|nd|rd|th)\s*(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
    matches=list(re.finditer(pattern,text,re.I));out=[]
    if len(matches)<20:raise ValueError("MoSPI calendar parse coverage insufficient")
    for i,m in enumerate(matches):
        mon=months[m.group(2)[:3].lower()];day=date(year+(mon<4),mon,int(m.group(1)))
        description=text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        wanted=re.search(r"(All India Consumer Price Index\s*\(CPI\)|All India Index of Industrial Production\s*\(IIP\)|[^\n]*Estimates of[^\n]*(?:GDP|Gross Domestic Product)[^\n]*)",description,re.I)
        if not wanted:continue
        if day.weekday()>=5:
            while day.weekday()>=5:day+=timedelta(days=1)
        if cutoff.date()<day<=date.fromisoformat(end):
            out.append({"event":safe_text(wanted.group(1),180),"dateTime":day.isoformat()+" (time unconfirmed)","country":"India","basis":"MoSPI planned date; publisher holiday/revision rules apply"})
    return out

def central_bank_events(raw,cutoff,end,bank):
    text=raw.decode("utf-8")
    output=[]
    if bank=="RBI":
        plain=safe_text(text,200000)
        fiscal=re.search(r"Meeting Schedule of the Monetary Policy Committee for (20\d{2})-(20\d{2})",plain)
        if not fiscal or not date(int(fiscal.group(1)),4,1)<=date.fromisoformat(end)<=date(int(fiscal.group(2)),3,31):raise ValueError("RBI calendar outside fiscal-year coverage")
        matches=re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*\d{1,2}\s+and\s+(\d{1,2}),?\s+(20\d{2})",plain)
        if len(matches)!=6:raise ValueError("RBI MPC schedule parse incomplete")
        for month,start,last,year in matches:
            day=datetime.strptime(f"{last} {month} {year}","%d %B %Y").date()
            if cutoff.date()<day<=date.fromisoformat(end):
                output.append({"event":"RBI MPC meeting concludes","country":"India","dateTime":day.isoformat()+" (time not confirmed)","basis":"Official annual RBI meeting schedule"})
    else:
        year=date.fromisoformat(end).year
        m=re.search(str(year)+r" FOMC Meetings(.*?)(?:</div>\s*</div>\s*<div class=\"panel|<h4>|$)",text,re.S)
        if not m:raise ValueError("Federal Reserve calendar year missing")
        # Restrict to the selected annual panel, before the next year heading.
        block=text[text.index(str(year)+" FOMC Meetings"):]
        pos=re.search(r"20\d{2} FOMC Meetings",block[len(str(year)+" FOMC Meetings"):])
        if pos:block=block[:pos.start()+len(str(year)+" FOMC Meetings")]
        months=re.findall(r'fomc-meeting__month[^>]*>\s*<strong>(.*?)</strong>',block,re.S)
        days=re.findall(r'fomc-meeting__date[^>]*>(.*?)</div>',block,re.S)
        if len(months)<8 or len(months)!=len(days):raise ValueError("Federal Reserve calendar parse incomplete")
        for month,ds in zip(months,days):
            numbers=re.findall(r"\d+",safe_text(ds));month=safe_text(month).split("/")[-1]
            if not numbers:continue
            for fmt in ("%d %B %Y","%d %b %Y"):
                try:day=datetime.strptime(numbers[-1]+" "+month+" "+str(year),fmt).date();break
                except ValueError:day=None
            if day and cutoff.date()<day<=date.fromisoformat(end):
                output.append({"event":"FOMC meeting concludes","country":"US","dateTime":day.isoformat()+" (US date; release time unconfirmed)","basis":"Official Federal Reserve meeting schedule"})
    return output

class Sources:
    def __init__(self,receipts,folder,nse_client=None):
        self.receipts=receipts;self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.nse_client=nse_client
        self.attempts=[]
    def save(self,key,label,url,raw,effective):
        digest=hashlib.sha256(raw).hexdigest();(self.folder/(digest+".source")).write_bytes(raw)
        self.receipts[key]={"status":"validated","label":label,"url":url,"sha256":digest,"effectiveDate":effective,"retrievedAt":datetime.now(IST).isoformat()}
        return raw
    def get(self,key,label,url,effective):
        import requests
        try:
            if self.nse_client and urlparse(url).hostname=="www.nseindia.com":raw=self.nse_client.get(url)
            else:
                response=requests.get(url,timeout=20,headers={"User-Agent":"StockPulseResearch/4.1","Accept":"application/json,text/calendar,application/pdf,text/html,*/*"})
                response.raise_for_status();raw=response.content
            if not raw or len(raw)>15_000_000:raise ValueError("Empty or oversized response")
            self.save(key,label,url,raw,effective)
            self.attempts.append({"key":key,"state":"retrieved","checkedAt":datetime.now(IST).isoformat()})
            return raw
        except Exception as e:
            self.attempts.append({"key":key,"state":"unavailable","reason":type(e).__name__,"checkedAt":datetime.now(IST).isoformat()})
            raise ValueError(label+": source retrieval failed ("+type(e).__name__+")") from None

def run(pack,receipts,archives,nse_client=None,now=None):
    now=now or datetime.now(IST);target=date.fromisoformat(pack["meta"]["trading_date"])
    cutoff=min(datetime.combine(target,time(20,30),IST),now)
    d=pack["derived"];next_day=d["next_trading_session"]["date"];end=d.get("corp_actions",{}).get("t2_date") or next_day
    sources=Sources(receipts,archives,nse_client)
    output={"cutoff":cutoff.isoformat(),"catalysts":[],"results":[],"calendar":[],"gift":None,"blocks":[],"coverage":{},"gaps":[],"trendlyneCalls":0}
    def gap(key,reason):
        output["gaps"].append({"section":key,"reason":reason})
        output["coverage"][key]="unavailable"
    def stage(key,fn):
        try:fn();output["coverage"][key]="available"
        except Exception as e:
            receipts.pop(key,None);gap(key,str(e)[:200])
    def catalyst_stage():
        url=NSE+"/api/corporate-announcements?"+urlencode({"index":"equities","from_date":target.strftime("%d-%m-%Y"),"to_date":target.strftime("%d-%m-%Y")})
        rows,count=announcements(json.loads(sources.get("catalysts","NSE issuer announcements",url,target.isoformat())),target,cutoff)
        symbols=[r.get("symbol") for k in ("nifty50_movers","broader_movers") for side in ("gainers","losers") for r in d.get(k,{}).get(side,[])[:3]]
        from website_briefing import event_priority, market_movers
        symbols+= [r["symbol"] for r in market_movers(pack)]
        liquidity={r["symbol"]:r["turnover"] for r in market_movers(pack,all_rows=True)}
        ranked=sorted([r for r in rows if event_priority(r)>0],key=lambda r:(r["symbol"] not in symbols,-event_priority(r),-liquidity.get(r["symbol"],0),-datetime.fromisoformat(r["publishedAt"]).timestamp()))
        output["catalysts"]=ranked[:12];output["announcementCount"]=count;output["catalystMatches"]=len(rows)
    stage("catalysts",catalyst_stage)
    # At most three fallback paid data calls. No automatic retry and no broad search.
    if os.environ.get("TRENDLYNE_MCP_TOKEN") and target==now.date():
        symbols=list(dict.fromkeys(r.get("symbol") for side in ("gainers","losers") for r in d.get("nifty50_movers",{}).get(side,[])[:3] if r.get("symbol")))
        present={r["symbol"] for r in output["catalysts"]}
        import trendlyne_mcp as tly
        for sym in [s for s in symbols if s not in present][:3]:
            output["trendlyneCalls"]+=1
            value=tly.call("get_overview_news_corp_events",{"stock_code":sym,"type":"news"},timeout=35)
            if not value:
                sources.attempts.append({"key":"trendlyne:"+sym,"state":"unavailable","reason":"No response from bounded data call","checkedAt":datetime.now(IST).isoformat()})
                continue
            rows=trend_news(value,sym,target,cutoff)
            sources.attempts.append({"key":"trendlyne:"+sym,"state":"matched" if rows else "no_eligible_filing","checkedAt":datetime.now(IST).isoformat()})
            if rows:
                key="trendlyne:"+sym;sources.save(key,"Trendlyne indexed issuer filings: "+sym,"https://trendlyne.com/",value.encode(),target.isoformat())
                for row in rows:row["sourceId"]=key
                output["catalysts"].extend(rows)
    def results_stage():
        url=NSE+"/api/corporate-board-meetings?"+urlencode({"index":"equities","from_date":date.fromisoformat(next_day).strftime("%d-%m-%Y"),"to_date":date.fromisoformat(end).strftime("%d-%m-%Y")})
        output["results"]=results_calendar(json.loads(sources.get("results","NSE results board-meeting calendar",url,target.isoformat())),next_day,end,cutoff)
    stage("results",results_stage)
    def gift_stage():
        raw=json.loads(sources.get("gift","NSE IX official futures market watch",GIFT,target.isoformat()))
        output["gift"]=gift_quote(raw,target,cutoff,d["indices"]["Nifty 50"]["close"])
    stage("gift",gift_stage)
    def calendar_stage(key,label,url,parser):
        if target!=now.date() and key in ("bls","bea","fed"):
            raise ValueError("Historical calendar revision not archived; current schedule is not backdated")
        raw=sources.get(key,label,url,target.isoformat())
        rows=parser(raw,cutoff,end)
        for r in rows:r["sourceId"]=key
        output["calendar"].extend(rows)
    for key,label,url,parser in (("mospi","MoSPI official advance release calendar",MOSPI,mospi_events),("bls","US BLS official release calendar",BLS,calendar_ics),("bea","US BEA official release calendar",BEA,calendar_ics)):
        stage(key,lambda k=key,l=label,u=url,p=parser:calendar_stage(k,l,u,p))
    for key,label,url,bank in [("rbi","RBI official MPC schedule","https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422","RBI"),("fed","Federal Reserve official FOMC calendar","https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm","Fed")]:
        stage(key,lambda k=key,l=label,u=url,b=bank:calendar_stage(k,l,u,lambda raw,c,e:central_bank_events(raw,c,e,b)))
    def block_stage():
        raw=sources.get("blocks","NSE block-deal disclosures","https://nsearchives.nseindia.com/content/equities/block.csv",target.isoformat())
        rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows or not any(parse_date(r.get("Date"))==target.isoformat() for r in rows):raise ValueError("Block-deal file has no validated session coverage")
        output["blocks"]=[r for r in rows if parse_date(r.get("Date"))==target.isoformat()]
    stage("blocks",block_stage)
    from website_assets import run as asset_run
    asset_run(pack,receipts,sources,target,cutoff)
    output["calendar"].sort(key=lambda r:r["dateTime"])
    output["attempts"]=sources.attempts
    d["website_enrichment"]=output
    return output
