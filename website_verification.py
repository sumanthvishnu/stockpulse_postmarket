"""Direct publisher verification of vendor context; no second-vendor claim."""
import re
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser

NASDAQ="https://indexes.nasdaq.com/Index/Overview/COMP"


def nasdaq_composite(raw,expected_session):
    class Hero(HTMLParser):
        def __init__(self):super().__init__();self.active=False;self.parts=[];self.values=[];self.percent=False;self.pct=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=="section" and attrs.get("id")=="hero":self.active=True
            if self.active and tag=="data":
                if attrs.get("data-parent")=="COMP" and attrs.get("data-current-value"):
                    self.values.append(attrs["data-current-value"])
                self.percent=attrs.get("id")=="pctChange"
        def handle_endtag(self,tag):
            if tag=="section":self.active=False
            if tag=="data":self.percent=False
        def handle_data(self,data):
            if self.active:self.parts.append(data)
            if self.active and self.percent:self.pct.append(data)
    p=Hero();p.feed(raw.decode("utf-8"))
    text=" ".join(p.parts)
    dates=re.findall(r"DATA AS OF\s+(\d{1,2}/\d{1,2}/\d{4})",text)
    if "NASDAQ Composite" not in text or len(dates)!=1 or len(p.values)!=1:
        raise ValueError("Nasdaq Composite publisher identity/schema missing")
    session=datetime.strptime(dates[0],"%m/%d/%Y").date().isoformat()
    if session!=expected_session:raise ValueError("Nasdaq publisher observation does not match completed vendor session")
    pct="".join(p.pct).strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%",pct):raise ValueError("Nasdaq percentage change missing")
    close=Decimal(p.values[0].replace(",",""));change=Decimal(pct[:-1])
    if not close.is_finite() or close<=0 or not change.is_finite():raise ValueError("Invalid Nasdaq publisher value")
    return {"instrument":"Nasdaq Composite","symbol":"COMP","session":session,"close":float(close),"pctChange":float(change),"unit":"index points","publisher":"Nasdaq"}


def comparison(vendor,publisher):
    if vendor["ticker"]!="^IXIC" or publisher["symbol"]!="COMP" or vendor["session"]!=publisher["session"]:
        raise ValueError("Publisher/vendor instrument or session mismatch")
    close_delta=abs(Decimal(str(vendor["close"]))-Decimal(str(publisher["close"])))
    pct_delta=abs(Decimal(str(vendor["pctChange"]))-Decimal(str(publisher["pctChange"])))
    # Both display at two decimals; never use a broad percent-level tolerance.
    return "matched" if close_delta<=Decimal("0.01") and pct_delta<=Decimal("0.01") else "conflicted"


def verify(output,receipts,archives):
    from website_enrichment import Sources
    sources=Sources(receipts,archives)
    output["verifications"]=[]
    for row in list(output["global"]):
        row["verification"]="No direct publisher comparison available"
        if row.get("ticker")!="^IXIC":continue
        key="publisher:nasdaq-comp"
        record={"instrument":row["name"],"vendorSourceId":row["sourceId"],"publisherSourceId":key,
                "basis":"Direct Nasdaq publisher check; Yahoo may share this upstream, not independent market measurement"}
        try:
            raw=sources.get(key,"Nasdaq Composite original publisher",NASDAQ,row["session"])
            original=nasdaq_composite(raw,row["session"])
            state=comparison(row,original)
            record.update(state=state,publisher=original,vendor=dict(row))
            if state=="conflicted":
                output["global"].remove(row)
                output["gaps"].append("Nasdaq Composite quarantined: original publisher and vendor disagree for the same completed session. Both inputs retained; no averaging.")
            else:
                row["verification"]="Matched direct Nasdaq publisher close/change; common upstream possible"
                row["publisherSourceId"]=key
        except Exception as error:
            receipts.pop(key,None)
            record.update(state="unavailable",reason=str(error)[:180])
            output["gaps"].append("Nasdaq Composite publisher verification unavailable: "+record["reason"])
        output["verifications"].append(record)
    output["verificationAttempts"]=sources.attempts
