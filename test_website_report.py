import copy, hashlib, json, tempfile, unittest
from datetime import datetime
from pathlib import Path
from website_report import IST, build_report, canonical, fmt, write_report
from website_collect import source_key, validate_source

def fixture():
    pack={"meta":{"trading_date":"2026-09-25"},"data":{"holiday_check":{"is_holiday":False}},"derived":{"indices_date":"2026-09-25","indices":{"Nifty 50":{"close":10100,"pts_chg":100,"pct_chg":1},"Nifty Bank":{"close":19800,"pts_chg":-200,"pct_chg":-1}},"breadth":{"advances":40,"declines":60,"unchanged":0,"universe":100,"ad_ratio":.667},"sanity_flags":[]},"failures":[]}
    receipts={key:{"status":"validated","effectiveDate":"2026-09-25","retrievedAt":"2026-09-25T20:30:00+05:30","sha256":"a"*64,"url":"https://nsearchives.nseindia.com/"+key+".csv"} for key in ("indices","bhavcopy","calendar")}
    return pack,receipts

class ReportTests(unittest.TestCase):
    def build(self,p,r): return build_report(p,r,datetime(2026,9,25,20,30,tzinfo=IST))
    def test_global_row_requires_its_own_validated_dated_source(self):
        for fault in ('missing','retrieved','wrong-date','bad-hash','missing-url','missing-time','future-session'):
            p,r=fixture()
            p['derived']['website_context']={'global':[{'name':'Nasdaq Composite','ticker':'^IXIC','session':'2026-09-24','close':100,'pctChange':1,'sourceId':'global:^IXIC'}]}
            receipt={**r['indices'],'effectiveDate':'2026-09-24'}
            if fault!='missing':r['global:^IXIC']=receipt
            if fault=='retrieved':receipt['status']='retrieved'
            if fault=='wrong-date':receipt['effectiveDate']='2026-09-23'
            if fault=='bad-hash':receipt['sha256']='z'*64
            if fault=='missing-url':receipt.pop('url')
            if fault=='missing-time':receipt.pop('retrievedAt')
            if fault=='future-session':
                p['derived']['website_context']['global'][0]['session']='2026-09-26'
                receipt['effectiveDate']='2026-09-26'
            with self.subTest(fault=fault),self.assertRaisesRegex(ValueError,'Global source'):
                self.build(p,r)

    def test_prior_completed_global_session_and_publisher_receipt(self):
        p,r=fixture()
        observation={'name':'Nasdaq Composite','ticker':'^IXIC','session':'2026-09-24','close':100,'pctChange':1,'sourceId':'global:^IXIC'}
        p['derived']['website_context']={'global':[observation]}
        r['global:^IXIC']={**r['indices'],'effectiveDate':'2026-09-24'}
        report=self.build(p,r)
        self.assertEqual(len(next(s for s in report['sections'] if s['id']=='global')['rows']),1)
        observation['publisherSourceId']='publisher:nasdaq-comp'
        with self.assertRaisesRegex(ValueError,'Global.*source'):self.build(p,r)
        r['publisher:nasdaq-comp']={**r['global:^IXIC']}
        self.assertEqual(next(s for s in self.build(p,r)['sections'] if s['id']=='global')['sourceIds'],['global:^IXIC','publisher:nasdaq-comp'])

    def test_named_signed_fields_and_divergence(self):
        p,r=fixture();report=self.build(p,r)
        self.assertIn("rose 1.00%",report["summary"][0]["text"])
        self.assertTrue(any(x["title"]=="A divergence to note" for x in report["summary"]))
        p["derived"]["indices"]["Nifty 50"]={"close":9900,"pts_chg":-100,"pct_chg":-1}
        self.assertIn("fell 1.00%",self.build(p,r)["summary"][0]["text"])
        self.assertEqual(fmt(-3693.93,signed=True),"-3,693.93")
    def test_missing_or_wrong_core_receipt_blocks(self):
        for key in ("indices","bhavcopy","calendar"):
            p,r=fixture();r[key]["effectiveDate"]="2026-09-24"
            with self.assertRaises(ValueError):self.build(p,r)
    def test_unknown_trading_session_cannot_publish(self):
        for status in (None,"false",0):
            p,r=fixture();p["data"]["holiday_check"]["is_holiday"]=status
            with self.subTest(status=status),self.assertRaises(ValueError):self.build(p,r)

    def test_zero_declines_is_not_zero_ratio(self):
        p,r=fixture();p["derived"]["breadth"]={"advances":100,"declines":0,"unchanged":0,"universe":100,"ad_ratio":0}
        with self.assertRaises(ValueError):self.build(p,r)
        p["derived"]["breadth"]["ad_ratio"]=None
        self.assertEqual(self.build(p,r)["status"],"available_with_gaps")

    def test_calendar_claim_requires_receipts_and_discloses_truncation(self):
        p,r=fixture()
        from website_enrichment import CALENDAR_KEYS
        coverage={k:"available" for k in CALENDAR_KEYS}
        p["derived"]["website_enrichment"]={"coverage":coverage,"calendar":[]}
        calendar=lambda:next(s for s in self.build(p,r)["sections"] if s["id"]=="calendar")
        self.assertEqual(calendar()["status"],"unavailable")
        for k in coverage:r[k]=copy.deepcopy(r["indices"])
        p["derived"]["website_enrichment"]["nyfedSourceIds"]=["nyfed"]
        self.assertEqual(calendar()["status"],"available")
        p["derived"]["website_enrichment"]["calendar"]=[{"event":"Release "+str(i),"country":"US","dateTime":"2026-09-28","basis":"Official schedule","sourceId":"bea"} for i in range(31)]
        report=self.build(p,r)
        self.assertEqual(next(s for s in report["sections"] if s["id"]=="calendar")["status"],"partial")
        self.assertTrue(any("first 30 of 31" in g["reason"] for g in report["gaps"]))
    def test_bad_index_arithmetic_blocks(self):
        p,r=fixture();p["derived"]["indices"]["Nifty 50"]["pct_chg"]=42
        with self.assertRaises(ValueError):self.build(p,r)
    def test_exchange_vix_rounding_does_not_block(self):
        # Original NSE 29 September archive: rounded close/point change differ
        # from the percentage calculated from underlying higher precision.
        p,r=fixture()
        p["derived"]["indices"]["India VIX"]={"close":13.41,"pts_chg":-0.23,"pct_chg":-1.65}
        report=self.build(p,r)
        row=next(x for x in next(s for s in report["sections"] if s["id"]=="snapshot")["rows"] if x["label"]=="India VIX")
        self.assertIn("-1.65%",row["values"])
        p["derived"]["indices"]["India VIX"]["pct_chg"]=-1.50
        with self.assertRaises(ValueError):self.build(p,r)

    def test_rounding_bound_is_not_a_broad_percentage_waiver(self):
        from website_report import index_change_consistent
        self.assertTrue(index_change_consistent({"close":13.64,"pts_chg":1.48,"pct_chg":12.15}))
        self.assertFalse(index_change_consistent({"close":10100,"pts_chg":100,"pct_chg":1.02}))
        self.assertFalse(index_change_consistent({"close":0,"pts_chg":1,"pct_chg":100}))

    def test_breadth_inconsistency_blocks(self):
        p,r=fixture();p["derived"]["breadth"]["universe"]=99
        with self.assertRaises(ValueError):self.build(p,r)
    def test_failed_empty_actions_are_unavailable(self):
        p,r=fixture();p["derived"]["corp_actions"]={"ex_t2":[],"t2_date":"2026-09-29"}
        report=self.build(p,r);section=next(s for s in report["sections"] if s["id"]=="watchlist")
        self.assertEqual(section["status"],"unavailable")
        self.assertNotIn("No EQ-series",canonical(section))
    def test_ban_receipt_requires_next_trading_date(self):
        p,r=fixture()
        p["derived"]["next_trading_session"]={"date":"2026-09-28","calendar_verified":True}
        p["derived"]["fo_ban"]={"trade_date":"28-Sep-2026","symbols":["ABC"],"stale_warning":False}
        r["calendar"]=copy.deepcopy(r["indices"])
        r["ban"]=copy.deepcopy(r["indices"])
        get=lambda:next(s for s in self.build(p,r)["sections"] if s["id"]=="ban")
        self.assertEqual(get()["rows"],[])
        r["ban"]["effectiveDate"]="2026-09-28"
        self.assertEqual(get()["rows"][0]["label"],"2026-09-28")
    def test_undated_and_stale_cash_withheld(self):
        p,r=fixture();p["derived"]["fii_dii_cash_summary"]={"fii_net_cr":123456,"dii_net_cr":-123456,"date_labels":["24-Sep-2026"]}
        r["cash"]=copy.deepcopy(r["indices"])
        report=self.build(p,r)
        self.assertEqual(next(s for s in report["sections"] if s["id"]=="cash")["rows"],[])
    def test_no_core_data_is_not_zero(self):
        p,r=fixture();del p["derived"]["breadth"]["advances"]
        with self.assertRaises(ValueError):self.build(p,r)
    def test_immutable_payload_and_digest(self):
        p,r=fixture();report=self.build(p,r)
        with tempfile.TemporaryDirectory() as folder:
            entry=write_report(report,folder);path=Path(folder)/entry["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),entry["sha256"])
            altered=copy.deepcopy(report);altered["headline"]="changed"
            with self.assertRaises(ValueError):write_report(altered,folder)
    def test_future_holiday_and_sanity_blocks(self):
        for mutate in (lambda p:p["meta"].update(trading_date="2026-09-26"),lambda p:p["data"]["holiday_check"].update(is_holiday=True),lambda p:p["derived"].update(sanity_flags=[{"check":"outlier"}])):
            p,r=fixture();mutate(p)
            with self.assertRaises(ValueError):self.build(p,r)
    def test_zero_declines_remains_undefined_ratio(self):
        p,r=fixture();p["derived"]["breadth"]={"advances":100,"declines":0,"unchanged":0,"universe":100,"ad_ratio":None}
        section=next(s for s in self.build(p,r)["sections"] if s["id"]=="breadth")
        self.assertEqual(section["rows"][-1]["values"],["Unavailable"])
    def test_source_content_date_not_filename_only(self):
        from types import SimpleNamespace
        f=SimpleNamespace(clean_rows=lambda text:[{"Index Date":"24-09-2026"}]*6)
        with self.assertRaises(ValueError):validate_source("indices",b"fixture",datetime(2026,9,25).date(),f)
    def test_valid_empty_actions_not_transport_failure(self):
        validate_source("actions:2026-09-28",b"[]",datetime(2026,9,25).date(),None)
        with self.assertRaises(ValueError):validate_source("actions:2026-09-28",b"{}",datetime(2026,9,25).date(),None)

    def test_exchange_participant_title_and_adjusted_reference(self):
        import csv, io
        from types import SimpleNamespace
        title=b'""Participant wise Open Interest as on Sep 25, 2026"",,,,'
        validate_source("participant",title,datetime(2026,9,25).date(),None)
        with self.assertRaises(ValueError):validate_source("participant",title,datetime(2026,9,24).date(),None)
        f=SimpleNamespace(clean_rows=lambda text:list(csv.DictReader(io.StringIO(text))))
        header='"Disclaimer: adjusted for corporate actions (bonus, splits & rights)"\n"Effective for 25-Sep-2026"\nSYMBOL,SERIES,Adjusted_52_Week_High,Adjusted_52_Week_Low\n'
        body=(header+"TEST,EQ,150,100\n"*100).encode()
        validate_source("highlow",body,datetime(2026,9,25).date(),f)
        with self.assertRaises(ValueError):validate_source("highlow",body,datetime(2026,9,24).date(),f)


if __name__=="__main__":unittest.main()
