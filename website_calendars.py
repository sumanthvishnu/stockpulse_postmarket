"""Additional official publisher calendars with explicit date/column binding."""
import re
import calendar
from datetime import date,datetime,time
from zoneinfo import ZoneInfo
from urllib.parse import urljoin,urlparse
from website_enrichment import IST,safe_text,untimed_in_window

BOJ="https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
NYFED="https://www.newyorkfed.org/research/calendars/"


def nyfed_events(raw,year,month,cutoff,end):
    """Parse the Fed's separately published, selected weekday indicator calendar."""
    text=raw.decode("utf-8")
    title=calendar.month_name[month]+" "+str(year)
    if title not in safe_text(text,300000) or "all Eastern Time" not in text:
        raise ValueError("NY Fed calendar month or timezone identity missing")
    cells=re.findall(r'<td\b[^>]*class=["\'][^"\']*\bdirCol[LR]\b[^"\']*["\'][^>]*>(.*?)</td>',text,re.S)
    seen=set();rows=[]
    for cell in cells:
        plain=safe_text(cell,20000)
        if not plain:continue
        day_match=re.match(r"^(\d{1,2})\b",plain)
        if not day_match:raise ValueError("NY Fed calendar day binding failed")
        day=int(day_match.group(1));dated=date(year,month,day)
        if day in seen:raise ValueError("Duplicate NY Fed calendar day")
        seen.add(day)
        anchors=list(re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',cell,re.S))
        times=re.findall(r"\((\d{2}):(\d{2})\)",plain)
        if len(times)!=len(anchors):raise ValueError("NY Fed event/time parse incomplete")
        for index,anchor in enumerate(anchors):
            fragment=cell[anchor.start():anchors[index+1].start() if index+1<len(anchors) else len(cell)]
            matched=re.findall(r"\((\d{2}):(\d{2})\)",safe_text(fragment,3000))
            if len(matched)!=1:raise ValueError("NY Fed event has ambiguous or missing time")
            hour,minute=map(int,matched[0])
            observed=datetime.combine(dated,time(hour,minute),ZoneInfo("America/New_York")).astimezone(IST)
            event=re.sub(r"\(\d{2}:\d{2}\)","",safe_text(anchor.group(2),300)).strip()
            publisher_url=urljoin(NYFED,anchor.group(1));host=urlparse(publisher_url).hostname
            if not event or urlparse(publisher_url).scheme not in ("https","http"):
                raise ValueError("NY Fed linked publisher identity missing")
            if cutoff<observed and observed.date()<=date.fromisoformat(end):
                rows.append({"event":event,"dateTime":observed.isoformat(),"country":"US",
                    "basis":"New York Fed selected weekday calendar; secondary schedule, tentative; original publisher "+str(host),
                    "publisherHost":host,"publisherUrl":publisher_url})
    expected={d for d in range(1,calendar.monthrange(year,month)[1]+1) if date(year,month,d).weekday()<5}
    if seen!=expected:raise ValueError("NY Fed month weekday coverage incomplete")
    return rows


def collect_nyfed(sources,target,cutoff,end,collection_day,coverage):
    if target!=collection_day:raise ValueError("Historical NY Fed calendar revision not archived; no backdating")
    start=cutoff.astimezone(ZoneInfo("America/New_York")).date().replace(day=1)
    last=date.fromisoformat(end).replace(day=1)
    months=[];current=start
    while current<=last:
        months.append(current)
        if len(months)>3:raise ValueError("NY Fed window exceeds three-month collection budget")
        current=date(current.year+1,1,1) if current.month==12 else date(current.year,current.month+1,1)
    rows=[];source_ids=[]
    for month in months:
        key="nyfed:"+month.strftime("%Y-%m")
        url=NYFED+"i-"+calendar.month_abbr[month.month].lower()+month.strftime("%y")+".html"
        raw=sources.get(key,"New York Fed selected indicator calendar: "+month.strftime("%Y-%m"),url,target.isoformat())
        try:parsed=nyfed_events(raw,month.year,month.month,cutoff,end)
        except Exception:
            sources.receipts[key]["status"]="unavailable"
            raise
        source_ids.append(key)
        for row in parsed:
            # Primary publisher schedules take precedence when available.
            primary="bls" if row["publisherHost"]=="www.bls.gov" else "bea" if row["publisherHost"]=="www.bea.gov" else None
            if primary and coverage.get(primary)=="available":continue
            rows.append({**row,"sourceId":key})
    return rows,source_ids


def boj_events(raw,cutoff,end):
    text=raw.decode("utf-8")
    if "Monetary Policy Meetings" not in text or safe_text(text,200000).count("8:50 a.m.")<2:
        raise ValueError("BOJ schedule identity or publication-time rule missing")
    months={"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"June":6,"July":7,"Aug":8,"Sept":9,"Oct":10,"Nov":11,"Dec":12}
    def parse_day(cell,year,meeting=False):
        explicit=re.search(r",\s*(20\d{2})\b",cell)
        if explicit:year=int(explicit.group(1))
        match=re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})\s*\(",cell)
        if not match or match.group(1) not in months:raise ValueError("BOJ publication date could not be parsed")
        day=int(match.group(2))
        if meeting:
            second=re.search(r"\),\s*(\d{1,2})\s*\(",cell)
            if not second:raise ValueError("BOJ meeting conclusion date missing")
            day=int(second.group(1))
        return date(year,months[match.group(1)],day)
    tables={}
    for table in re.findall(r"<table\b[^>]*>(.*?)</table>",text,re.S):
        year=re.search(r"<caption[^>]*>\s*Table\s*:\s*(20\d{2})\s*</caption>",table)
        if year:tables[int(year.group(1))]=table
    years=range(cutoff.year,date.fromisoformat(end).year+1)
    if any(year not in tables for year in years):raise ValueError("BOJ calendar year coverage missing")
    output=[]
    for year in years:
        body=re.search(r"<tbody[^>]*>(.*?)</tbody>",tables[year],re.S)
        if not body:raise ValueError("BOJ schedule rows missing")
        rows=re.findall(r"<tr[^>]*>(.*?)</tr>",body.group(1),re.S)
        if len(rows)!=8:raise ValueError("BOJ annual meeting parse incomplete")
        for row in rows:
            cells=[safe_text(cell,1000) for cell in re.findall(r"<td[^>]*>(.*?)</td>",row,re.S)]
            if len(cells)!=4:raise ValueError("BOJ schedule column binding failed")
            meeting_day=parse_day(cells[0],year,True)
            if meeting_day>date.fromisoformat(end):continue
            for i,label in enumerate(("BOJ monetary policy meeting concludes","BOJ Outlook Report: Bank's View","BOJ Summary of Opinions","BOJ MPM minutes")):
                if cells[i]=="-":continue
                day=meeting_day if i==0 else parse_day(cells[i],year)
                if i>=2:
                    observed=datetime.combine(day,time(8,50),ZoneInfo("Asia/Tokyo")).astimezone(IST)
                    if not cutoff<observed or observed.date()>date.fromisoformat(end):continue
                    display=observed.isoformat();basis="BOJ published schedule; in-principle 08:50 JST release time"
                else:
                    if not untimed_in_window(day,cutoff,end,ZoneInfo("Asia/Tokyo")):continue
                    display=day.isoformat()+" (Tokyo date; time unpublished, may already have occurred)"
                    basis="Official BOJ schedule; Outlook Bank's View follows the meeting, exact time not inferred"
                output.append({"event":label,"dateTime":display,"country":"Japan","basis":basis})
    return output
