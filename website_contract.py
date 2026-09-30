"""Explicit report-cell bindings and conservative required-coverage acceptance."""
import math,re
from decimal import Decimal,ROUND_HALF_UP

# Product scope from v4 and the 27 September coverage review. Optional context
# never becomes a hard core-publication gate merely because an adapter exists.
OPTIONAL={'global','assets','gift','history','vix-context','nifty-trend','vix-trend'}
CORE={'snapshot','breadth'}
REQUIRED={'snapshot','sectors','breadth','nifty50_movers','broader_movers','internals','cash','positioning','position-detail','fii-fno','options','watchlist','ban','catalysts','filing-content','results','calendar','blocks','deals','liquid-movers'}
NUMERIC={
 'snapshot':{0:('index points',2),1:('index points',2),2:('percent',2)},
 'sectors':{0:('index points',2),1:('percent',2)},
 'history':{0:('percent',2),1:('percent',2)},
 'vix-context':{0:('index points',2),1:('index points',2),2:('index points',2),3:('percent',1)},
 'breadth':{0:('securities',0)},'internals':{0:('securities',0)},'cash':{0:('INR crore',2)},
 'nifty50_movers':{0:('INR',2),1:('percent',2),2:('percent',2),3:('INR crore',1)},
 'broader_movers':{0:('INR',2),1:('percent',2),2:('percent',2),3:('INR crore',1)},
 'positioning':{0:('contracts',0),1:('contracts',0)},
 'position-detail':{i:('contracts',0) for i in range(4)},
 'fii-fno':{i:('INR crore',2) for i in range(3)},
 'options':{1:('ratio',3),**{i:('index points',2) for i in range(2,6)}},
 'global':{1:('index points',2),2:('percent',2)},
 'gift':{2:('index points',2),3:('index points',2)},'assets':{0:('source-specified',3)},
 'blocks':{2:('shares',0),3:('INR',2),4:('INR crore',2)},
 'deals':{2:('shares',0),3:('INR',2),4:('INR crore',2)},
 'liquid-movers':{0:('INR',2),1:('percent',2),2:('percent',2),3:('INR crore',1)},
 'nifty-trend':{0:('index points',2)},'vix-trend':{0:('index points',2)},
}
FIELDS={'vix-context':['current','low','high','rangePosition'],
 'position-detail':['indexLong','indexShort','stockLong','stockShort'],
 'global':{1:'close',2:'pctChange'},'gift':{2:'level',3:'spotDifference'},
 'assets':{0:'value'},'liquid-movers':['close','change','delivery','turnover']}

def resolve(pack,path):
    current=pack;remaining=path
    while remaining:
        if isinstance(current,list):
            part,_,remaining=remaining.partition('.')
            current=current[int(part)]
        elif isinstance(current,dict):
            matches=[k for k in current if remaining==k or remaining.startswith(k+'.')]
            if not matches:raise ValueError('Unresolved metric path: '+path)
            key=max(matches,key=len);current=current[key];remaining=remaining[len(key):].removeprefix('.')
        else:raise ValueError('Non-container metric path: '+path)
    return current

def bind_metrics(report,pack,receipts):
    bindings=[];d=pack['derived']
    for section in report['sections']:
        sid=section['id']
        for ri,row in enumerate(section['rows']):
            for col,(unit,places) in NUMERIC.get(sid,{}).items():
                display=row['values'][col]
                if display in ('Unavailable','Constant range'):continue
                refs=row['refs'];calculation='identity';paths=[]
                if sid in FIELDS:
                    path=refs[0]+'.'+FIELDS[sid][col];raw=resolve(pack,path);paths=[path]
                elif sid in ('blocks','deals'):
                    obj=resolve(pack,refs[0]);qpath=refs[0]+'.Quantity Traded';ppath=refs[0]+'.Trade Price / Wght. Avg. Price'
                    quantity=float(str(obj['Quantity Traded']).replace(',',''));price=float(str(obj['Trade Price / Wght. Avg. Price']).replace(',',''))
                    raw=quantity if col==2 else price if col==3 else quantity*price/10_000_000
                    paths=[qpath] if col==2 else [ppath] if col==3 else [qpath,ppath]
                    calculation='quantity-times-price-divided-by-10000000' if col==4 else 'decimal-source-normalization'
                else:
                    paths=[refs[col]];raw=resolve(pack,paths[0])
                if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw):raise ValueError('Invalid bound numeric value: '+paths[0])
                if sid=='breadth' and paths[0].endswith('.ad_ratio'):unit='ratio';places=3
                if sid=='assets':unit=resolve(pack,refs[0])['unit']
                expected=Decimal(str(raw)).quantize(Decimal(10)**-places,rounding=ROUND_HALF_UP)
                if not re.fullmatch(r'[+-]?[0-9,]+(?:\.[0-9]+)?%?',display) or Decimal(display.rstrip('%').replace(',',''))!=expected:
                    raise ValueError('Rendered metric differs from bound field: '+paths[0])
                keys=list(section['sourceIds']);effective=report['session'];observed=None
                snapshot_vendor=sid=='snapshot' and paths[0].startswith('derived.website_context.global.')
                if snapshot_vendor:
                    obj=resolve(pack,paths[0].rsplit('.',1)[0]);keys=[obj['sourceId']];effective=obj['session'];observed=obj.get('sessionClose')
                elif sid=='snapshot':keys=['indices']
                elif sid=='global':
                    obj=resolve(pack,refs[0]);keys=[obj['sourceId']];effective=obj['session'];observed=obj.get('sessionClose')
                elif sid=='assets':
                    obj=resolve(pack,refs[0]);keys=[obj['sourceId']];observed=obj.get('observedAt')
                    if observed and re.match(r'^\d{4}-\d{2}-\d{2}',observed):effective=observed[:10]
                elif sid in ('history','vix-context','nifty-trend','vix-trend'):
                    keys=d.get('website_history',{}).get('sourceIds',[])
                    if sid=='history':
                        ordered=sorted(keys,key=lambda k:receipts[k]['effectiveDate'],reverse=True)
                        span=5 if col==0 else 20
                        if len(ordered)<=span:raise ValueError('Historical metric window incomplete')
                        keys=[ordered[0],ordered[span]]
                    elif sid in ('nifty-trend','vix-trend'):
                        keys=[k for k in keys if receipts[k]['effectiveDate']==row['label']]
                elif sid=='gift':observed=d['website_enrichment']['gift']['observedAt']
                if sid in ('nifty-trend','vix-trend'):effective=row['label']
                if not keys:raise ValueError('Bound metric has no source receipts: '+paths[0])
                source_dates={key:receipts[key]['effectiveDate'] for key in keys}
                period={'start':min(source_dates.values()),'end':effective} if sid in ('history','vix-context','nifty-trend','vix-trend') else {'start':effective,'end':effective}
                basis='exchange-or-publisher-reported'
                if snapshot_vendor:basis='vendor-reported' if col==0 else 'calculated-from-vendor'
                elif sid=='global':basis='vendor-reported' if col==1 else 'calculated-from-vendor'
                elif sid=='assets' and 'us10y' not in keys:basis='vendor-reported'
                elif sid in ('history','vix-context','breadth','internals','positioning','options') or (sid in ('deals','blocks') and col==4) or (sid=='gift' and col==3) or (sid=='liquid-movers' and col in (1,3)) or (sid=='fii-fno' and col==2):basis='calculated-from-exchange'
                bindings.append({'id':sid+':'+str(ri)+':'+str(col),'sectionId':sid,'row':ri,'column':col,
                    'entity':row['label'],'paths':paths,'rawValue':raw,'display':display,'unit':unit,
                    'basis':basis,'period':period,
                    'currency':'INR' if unit.startswith('INR') else 'USD' if unit.startswith('USD') else None,
                    'scale':10000000 if unit=='INR crore' else 1,'precision':places,'session':effective,
                    'observedAt':observed,'sourceIds':keys,'sourceDates':source_dates,'calculation':calculation,
                    'calculationVersion':'postmarket-cell-bindings-v1','quality':'provisional' if sid=='cash' else 'validated',
                    'limitation':'Exact source observation time not supplied; dated archive observation.' if not observed else ''})
    return bindings

def coverage(report):
    output=[]
    for s in report['sections']:
        role='core' if s['id'] in CORE else 'required' if s['id'] in REQUIRED else 'optional'
        state='validated' if s['status']=='available' else s['status']
        if s['id']=='cash' and state=='validated':state='provisional'
        output.append({'sectionId':s['id'],'requirement':role,'state':state,'reason':s['note']})
    return output

def accepted_complete(items,gaps):
    required={x['sectionId'] for x in items if x['requirement'] in ('core','required')}
    return REQUIRED.issubset(required) and all(x['state'] in ('validated','provisional') for x in items if x['requirement']!='optional') and not gaps

def attach_contract(report,pack,receipts):
    from website_report import IST
    from datetime import datetime,time,date
    cutoff=pack['derived'].get('website_enrichment',{}).get('cutoff')
    if not cutoff:cutoff=datetime.combine(date.fromisoformat(report['session']),time(20,30),IST).isoformat()
    cutoff_time=datetime.fromisoformat(cutoff)
    if cutoff_time.tzinfo is None or cutoff_time.astimezone(IST).date().isoformat()!=report['session'] or cutoff_time>datetime.fromisoformat(report['generatedAt']):
        raise ValueError('Invalid report cutoff')
    report['cutoff']=cutoff
    report['metricBindings']=bind_metrics(report,pack,receipts)
    for claim in report['summary']:
        claim['metricIds']=list(dict.fromkeys(b['id'] for path in claim['refs'] for b in report['metricBindings'] if path in b['paths']))
        if any(not any(path in b['paths'] for b in report['metricBindings']) for path in claim['refs']):
            raise ValueError('Narrative metric reference is not bound')
    report['acceptance']={'version':1,'profile':'postmarket-v4','coverage':coverage(report)}
    report['status']='complete' if accepted_complete(report['acceptance']['coverage'],report['gaps']) else 'available_with_gaps'
