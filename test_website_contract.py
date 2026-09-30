import copy,hashlib,json,tempfile,unittest
from datetime import date,datetime
from pathlib import Path
from website_report import IST,build_report
from website_contract import bind_metrics,accepted_complete,REQUIRED
from website_evidence import validate_enrichment
from website_session_calendar import load_calendar,next_sessions,session_open
from test_website_report import fixture

class ContractTests(unittest.TestCase):
    def build(self,p,r):return build_report(p,r,datetime(2026,9,25,20,30,tzinfo=IST))
    def test_sensex_snapshot_is_vendor_bound_not_inferred(self):
        p,r=fixture();observation={'name':'Sensex','ticker':'^BSESN','session':'2026-09-25','close':101,'pctChange':1,'sourceId':'global:^BSESN'}
        p['derived']['website_context']={'global':[observation]};r['global:^BSESN']=dict(r['indices'])
        report=self.build(p,r);row=next(x for x in report['sections'][0]['rows'] if x['label']=='Sensex (vendor)')
        self.assertEqual(row['values'][1],'Unavailable')
        observation.update(previousSession='2026-09-24',previousClose=100,ptsChange=1)
        report=self.build(p,r);binding=next(b for b in report['metricBindings'] if b['entity']=='Sensex (vendor)' and b['column']==1)
        self.assertEqual(binding['sourceIds'],['global:^BSESN']);self.assertEqual(binding['basis'],'calculated-from-vendor')
        observation['ptsChange']=2
        with self.assertRaisesRegex(ValueError,'arithmetic'):self.build(p,r)
    def test_bound_raw_field_sign_unit_and_mutation(self):
        p,r=fixture();report=self.build(p,r)
        b=next(b for b in report['metricBindings'] if b['id']=='snapshot:0:0')
        self.assertEqual((b['entity'],b['rawValue'],b['unit'],b['paths']),('Nifty 50',10100,'index points',['derived.indices.Nifty 50.close']))
        self.assertEqual(report['cutoff'],'2026-09-25T20:30:00+05:30')
        report['sections'][0]['rows'][0]['values'][0]='-10,100.00'
        with self.assertRaisesRegex(ValueError,'Rendered metric'):bind_metrics(report,p,r)
    def test_missing_configured_rows_and_optional_roles(self):
        p,r=fixture();report=self.build(p,r)
        self.assertTrue(any('Sensex' in g['reason'] for g in report['gaps']))
        roles={x['sectionId']:x['requirement'] for x in report['acceptance']['coverage']}
        self.assertEqual(roles['gift'],'optional');self.assertEqual(roles['global'],'optional')
        self.assertEqual(roles['breadth'],'core');self.assertEqual(roles['calendar'],'required')
        self.assertEqual(report['status'],'available_with_gaps')
    def test_no_vacuous_or_downgraded_complete(self):
        self.assertFalse(accepted_complete([],[]))
        checks=[{'sectionId':s,'requirement':'required','state':'validated'} for s in REQUIRED]
        self.assertTrue(accepted_complete(checks,[]))
        checks[0]['state']='unavailable';self.assertFalse(accepted_complete(checks,[]))
        checks[0]['state']='validated';self.assertFalse(accepted_complete(checks,[{'reason':'unresolved'}]))
        checks[0]['requirement']='optional';self.assertFalse(accepted_complete(checks,[]))
    def test_all_enrichment_rows_need_receipts(self):
        examples=[('catalysts',[{'symbol':'X'}]),('results',[{'symbol':'X'}]),('blocks',[{'Symbol':'X'}]),('gift',{'level':1}),('calendar',[{'sourceId':'bls'}])]
        for key,value in examples:
            p,r=fixture();p['derived']['website_enrichment']={key:value}
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'source receipt'):validate_enrichment(p,r,'2026-09-25')
        p,r=fixture();p['derived']['website_assets']={'rows':[{'sourceId':'us10y'}]}
        with self.assertRaisesRegex(ValueError,'Asset source receipt'):validate_enrichment(p,r,'2026-09-25')
        p,r=fixture();p['derived']['website_history']={'fiveSessionChange':{'Nifty 50':1}}
        with self.assertRaisesRegex(ValueError,'History source receipts'):validate_enrichment(p,r,'2026-09-25')
    def test_failed_empty_is_not_claimed_empty(self):
        p,r=fixture();p['derived']['website_enrichment']={'coverage':{'catalysts':'available','results':'available'}}
        report=self.build(p,r)
        for key in ('catalysts','results'):
            self.assertEqual(next(s for s in report['sections'] if s['id']==key)['status'],'unavailable')
    def test_reviewed_special_session_and_next_dates(self):
        calendar={'validFrom':'2026-09-01','validThrough':'2026-10-31','exceptions':{'2026-09-26':'open','2026-09-28':'closed'}}
        self.assertTrue(session_open(date(2026,9,26),['2026-09-26'],calendar))
        self.assertEqual(next_sessions(date(2026,9,25),2,[],calendar),[date(2026,9,26),date(2026,9,29)])
        with self.assertRaisesRegex(ValueError,'expired'):next_sessions(date(2026,10,31),1,[],calendar)
    def test_circular_identity_hash_cutoff_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'evidence').mkdir();raw=b'Reviewed original exchange circular fixture';(root/'circular.pdf').write_bytes(raw)
            item={'date':'2026-09-26','state':'open','publishedAt':'2026-09-24T10:00:00+05:30','sourceUrl':'https://nsearchives.nseindia.com/circular.pdf','sha256':hashlib.sha256(raw).hexdigest(),'document':'circular.pdf'}
            config={'schemaVersion':1,'validFrom':'2026-09-01','validThrough':'2026-10-31','reviewedAt':'2026-09-24T12:00:00+05:30','reviewedBy':'test fixture reviewer','exceptions':[item]}
            path=root/'calendar.json';path.write_text(json.dumps(config));r={}
            result=load_calendar(path,date(2026,9,25),datetime(2026,9,25,20,30,tzinfo=IST),root/'evidence',r)
            self.assertEqual(result['exceptions']['2026-09-26'],'open');self.assertTrue(r['session-override:2026-09-26']['sha256'])
            for field,bad in [('sha256','a'*64),('document','../outside.pdf'),('publishedAt','2026-09-25T12:00:00+05:30'),('sourceUrl','https://evil.example/circular.pdf')]:
                bad_config=copy.deepcopy(config);bad_config['exceptions'][0][field]=bad;path.write_text(json.dumps(bad_config))
                with self.subTest(field=field),self.assertRaises(ValueError):load_calendar(path,date(2026,9,25),datetime(2026,9,25,20,30,tzinfo=IST),root/'evidence',{})

if __name__=='__main__':unittest.main()
