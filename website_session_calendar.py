"""Reviewed, evidence-backed exchange session overrides; no inferred exceptions."""
import hashlib,json
from datetime import date,datetime,timedelta
from pathlib import Path
from urllib.parse import urlparse


def load_calendar(path,target,cutoff,archives,receipts):
    if path is None:return {}
    path=Path(path).resolve();config=json.loads(path.read_text(encoding='utf-8'))
    if config.get('schemaVersion')!=1:raise ValueError('Unsupported session calendar version')
    start=date.fromisoformat(config['validFrom']);end=date.fromisoformat(config['validThrough'])
    reviewed=datetime.fromisoformat(config['reviewedAt'])
    if not start<=target<=end or (end-start).days>366 or reviewed.tzinfo is None or reviewed>cutoff:
        raise ValueError('Session calendar review/coverage invalid')
    if not config.get('reviewedBy'):raise ValueError('Session calendar requires recorded review')
    overrides={}
    for i,item in enumerate(config['exceptions']):
        day=date.fromisoformat(item['date']);state=item.get('state')
        if not start<=day<=end or state not in ('open','closed') or day.isoformat() in overrides:
            raise ValueError('Invalid or duplicate exchange exception')
        published=datetime.fromisoformat(item['publishedAt']);url=urlparse(item['sourceUrl'])
        if published.tzinfo is None or published>reviewed or url.scheme!='https' or url.hostname not in ('nsearchives.nseindia.com','archives.nseindia.com','www.nseindia.com') or url.username or url.password or url.port not in (None,443):
            raise ValueError('Exchange exception provenance invalid')
        document=(path.parent/item['document']).resolve()
        if not document.is_relative_to(path.parent) or document==path:raise ValueError('Exchange evidence path outside calendar folder')
        raw=document.read_bytes()
        if not raw or len(raw)>8_000_000 or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ValueError('Exchange circular bytes/hash mismatch')
        (Path(archives)/(item['sha256']+'.source')).write_bytes(raw)
        key='session-override:'+day.isoformat()
        receipts[key]={'status':'validated','label':'Reviewed NSE session circular','url':item['sourceUrl'],
            'sha256':item['sha256'],'effectiveDate':day.isoformat(),'retrievedAt':reviewed.isoformat()}
        overrides[day.isoformat()]=state
    # Reviewed configuration is retained verbatim alongside the original circulars.
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    (Path(archives)/(digest+'.session-calendar.json')).write_bytes(raw)
    return {'validFrom':start.isoformat(),'validThrough':end.isoformat(),'reviewedAt':reviewed.isoformat(),
        'reviewedBy':str(config['reviewedBy']),'sha256':digest,'exceptions':overrides}


def session_open(day,holidays,calendar):
    if calendar:
        if not calendar['validFrom']<=day.isoformat()<=calendar['validThrough']:raise ValueError('Session override calendar expired')
        state=calendar['exceptions'].get(day.isoformat())
        if state:return state=='open'
    return day.weekday()<5 and day.isoformat() not in {x.isoformat() if isinstance(x,date) else str(x)[:10] for x in holidays}


def next_sessions(target,count,holidays,calendar):
    result=[];day=target
    for _ in range(370):
        day+=timedelta(days=1)
        if session_open(day,holidays,calendar):result.append(day)
        if len(result)==count:return result
    raise ValueError('No validated next session in bounded calendar window')
