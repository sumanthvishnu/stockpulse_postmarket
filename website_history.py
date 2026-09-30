"""Build context from contiguous, dated exchange sessions only."""
from datetime import timedelta
from pathlib import Path

def validated_history(pack,receipts,archives,target,holidays,fetcher):
    expected=[];day=target
    while len(expected)<21:
        from website_session_calendar import session_open
        calendar=pack.get('meta',{}).get('sessionCalendar',{})
        if calendar.get('state')=='unconfigured':calendar={}
        if session_open(day,holidays,calendar):expected.append(day)
        day-=timedelta(days=1)
    rows={};ids=[]
    for day in expected:
        key="indices" if day==target else "history:"+day.isoformat()
        rec=receipts.get(key,{})
        if rec.get("status")!="validated" or rec.get("effectiveDate")!=day.isoformat():break
        payload=(Path(archives)/(rec["sha256"]+".source")).read_text(encoding="utf-8")
        rows[day]=fetcher.parse_ind_close_all(payload);ids.append(key)
    out={"sessions":len(rows),"sourceIds":ids,"fiveSessionChange":{},"vix":None}
    if len(rows)>=6:
        first,last=rows[expected[5]],rows[target]
        for name,r in last.items():
            previous=first.get(name,{}).get("close")
            current=r.get("close")
            if isinstance(previous,(float,int)) and previous>0 and isinstance(current,(float,int)):
                out["fiveSessionChange"][name]=round((current/previous-1)*100,2)
    if len(rows)==21:
        vals=[rows[day].get("India VIX",{}).get("close") for day in expected]
        if all(isinstance(v,(float,int)) and v>0 for v in vals):
            low,high=min(vals),max(vals)
            out["vix"]={"current":vals[0],"low":low,"high":high,"sessions":21,"rangePosition":round((vals[0]-low)/(high-low)*100,1) if high>low else None}
    out["series"]=[{"date":day.isoformat(),"nifty":rows[day].get("Nifty 50",{}).get("close"),"vix":rows[day].get("India VIX",{}).get("close")} for day in sorted(rows)]
    out["twentySessionChange"]={}
    if len(rows)==21:
        for name,r in rows[target].items():
            previous=rows[expected[20]].get(name,{}).get("close");current=r.get("close")
            if isinstance(previous,(int,float)) and previous>0 and isinstance(current,(int,float)):
                out["twentySessionChange"][name]=round((current/previous-1)*100,2)
    pack["derived"]["website_history"]=out
    return out

def participant_positions(payload):
    import csv,io
    reader=csv.reader(io.StringIO(payload.decode("utf-8")));header=None;out={}
    fields=["Future Index Long","Future Index Short","Future Stock Long","Future Stock Short"]
    for cells in reader:
        cells=[c.strip() for c in cells]
        if cells and cells[0]=="Client Type":header=cells;continue
        if not header or not cells or cells[0] not in ("Client","DII","FII","Pro"):continue
        values=[]
        for name in fields:
            raw=cells[header.index(name)].replace(",","")
            number=float(raw)
            if number<0 or not number.is_integer():raise ValueError("Invalid participant contract count")
            values.append(int(number))
        if cells[0] in out:raise ValueError("Duplicate participant")
        out[cells[0]]=dict(zip(["indexLong","indexShort","stockLong","stockShort"],values))
    if len(out)!=4:raise ValueError("Incomplete participant table")
    for long,short in [("indexLong","indexShort"),("stockLong","stockShort")]:
        if sum(v[long] for v in out.values())!=sum(v[short] for v in out.values()):raise ValueError("Participant contracts do not balance")
    return out
