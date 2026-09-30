"""Compiler boundary checks. Derived values never authorize their own evidence."""
from datetime import datetime,date
import re,math
from urllib.parse import urlparse

SOURCE_HOSTS={'nsearchives.nseindia.com','archives.nseindia.com','www.nseindia.com','www.bseindia.com','api.bseindia.com','finance.yahoo.com','www.nseix.com','www.mospi.gov.in','www.bls.gov','www.bea.gov','www.rbi.org.in','www.federalreserve.gov','home.treasury.gov','tradingeconomics.com','trendlyne.com','www.ons.gov.uk','www.ecb.europa.eu','www.boj.or.jp','www.newyorkfed.org','indexes.nasdaq.com'}


def require_receipt(receipts,key,effective,context):
    r=receipts.get(key,{}) if isinstance(key,str) else {}
    try:
        observed=datetime.fromisoformat(r.get('retrievedAt',''))
        day=date.fromisoformat(effective)
        url=urlparse(r.get('url',''))
        permitted=url.scheme=='https' and url.hostname in SOURCE_HOSTS and not url.username and not url.password and url.port in (None,443)
    except (ValueError,TypeError):observed=None;day=None;permitted=False
    if (r.get('status')!='validated' or r.get('effectiveDate')!=effective or day is None
        or not re.fullmatch(r'[a-f0-9]{64}',str(r.get('sha256','')))
        or not permitted
        or observed is None or observed.tzinfo is None):
        raise ValueError(context+' source receipt missing, unusable or mismatched: '+str(key))
    return r


def validate_enrichment(pack,receipts,session):
    d=pack['derived'];enr=d.get('website_enrichment',{})
    for observation in d.get('website_context',{}).get('global',[]):
        effective=observation.get('session')
        if not isinstance(effective,str) or effective>session:raise ValueError('Global source observation session invalid')
        require_receipt(receipts,observation.get('sourceId'),effective,'Global')
        if 'previousClose' in observation:
            close,previous,points,change=(observation.get(k) for k in ('close','previousClose','ptsChange','pctChange'))
            if (not all(type(v) in (int,float) and math.isfinite(v) for v in (close,previous,points,change))
                or min(close,previous)<=0 or not isinstance(observation.get('previousSession'),str)
                or observation['previousSession']>=effective
                or not math.isclose(points,close-previous,rel_tol=1e-12,abs_tol=1e-8)
                or abs(change-round((close/previous-1)*100,2))>1e-8):
                raise ValueError('Global source bar arithmetic or prior session mismatch')
        if observation.get('publisherSourceId') is not None:
            require_receipt(receipts,observation['publisherSourceId'],effective,'Global publisher')
    for event in enr.get('catalysts',[]):
        require_receipt(receipts,event.get('sourceId','catalysts'),session,'Company event')
        evidence=event.get('documentEvidence')
        if evidence:require_receipt(receipts,evidence.get('sourceId'),session,'Filing content')
    for key in ('results','blocks','gift'):
        if enr.get(key):require_receipt(receipts,key,session,key.title())
    for event in enr.get('calendar',[]):
        require_receipt(receipts,event.get('sourceId'),session,'Economic calendar')
    for value in d.get('website_assets',{}).get('rows',[]):
        require_receipt(receipts,value.get('sourceId'),session,'Asset')
    history=d.get('website_history',{})
    if any(history.get(k) for k in ('fiveSessionChange','twentySessionChange','vix','series')):
        keys=history.get('sourceIds',[])
        if not keys:raise ValueError('History source receipts missing')
        for key in keys:
            effective=session if key=='indices' else key.removeprefix('history:')
            if effective>session:raise ValueError('History source date is in the future')
            require_receipt(receipts,key,effective,'History')
