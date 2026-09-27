"""Build context from contiguous, dated exchange sessions only."""
from datetime import timedelta
from pathlib import Path

def validated_history(pack,receipts,archives,target,holidays,fetcher):
    expected=[];day=target
    while len(expected)<21:
        if day.weekday()<5 and day.isoformat() not in holidays:expected.append(day)
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
    pack["derived"]["website_history"]=out
    return out
