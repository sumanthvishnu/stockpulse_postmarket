import copy, hashlib, json, tempfile, unittest
from datetime import datetime
from pathlib import Path
from website_report import IST, build_report, canonical, fmt, write_report
from website_collect import source_key, validate_source

def fixture():
    pack={"meta":{"trading_date":"2026-09-25"},"data":{"holiday_check":{"is_holiday":False}},"derived":{"indices_date":"2026-09-25","indices":{"Nifty 50":{"close":10100,"pts_chg":100,"pct_chg":1},"Nifty Bank":{"close":19800,"pts_chg":-200,"pct_chg":-1}},"breadth":{"advances":40,"declines":60,"unchanged":0,"universe":100,"ad_ratio":.667},"sanity_flags":[]},"failures":[]}
    receipts={key:{"status":"validated","effectiveDate":"2026-09-25","retrievedAt":"2026-09-25T20:30:00+05:30","sha256":"a"*64,"url":"https://nsearchives.nseindia.com/"+key+".csv"} for key in ("indices","bhavcopy")}
    return pack,receipts

class ReportTests(unittest.TestCase):
    def build(self,p,r): return build_report(p,r,datetime(2026,9,25,20,30,tzinfo=IST))
    def test_named_signed_fields_and_divergence(self):
        p,r=fixture();report=self.build(p,r)
        self.assertIn("rose 1.00%",report["summary"][0]["text"])
        self.assertTrue(any(x["title"]=="A divergence to note" for x in report["summary"]))
        p["derived"]["indices"]["Nifty 50"]={"close":9900,"pts_chg":-100,"pct_chg":-1}
        self.assertIn("fell 1.00%",self.build(p,r)["summary"][0]["text"])
        self.assertEqual(fmt(-3693.93,signed=True),"-3,693.93")
    def test_missing_or_wrong_core_receipt_blocks(self):
        for key in ("indices","bhavcopy"):
            p,r=fixture();r[key]["effectiveDate"]="2026-09-24"
            with self.assertRaises(ValueError):self.build(p,r)
    def test_bad_index_arithmetic_blocks(self):
        p,r=fixture();p["derived"]["indices"]["Nifty 50"]["pct_chg"]=42
        with self.assertRaises(ValueError):self.build(p,r)
    def test_breadth_inconsistency_blocks(self):
        p,r=fixture();p["derived"]["breadth"]["universe"]=99
        with self.assertRaises(ValueError):self.build(p,r)
    def test_failed_empty_actions_are_unavailable(self):
        p,r=fixture();p["derived"]["corp_actions"]={"ex_t2":[],"t2_date":"2026-09-29"}
        report=self.build(p,r);section=next(s for s in report["sections"] if s["id"]=="watchlist")
        self.assertEqual(section["status"],"unavailable")
        self.assertNotIn("No EQ-series",canonical(section))
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

if __name__=="__main__":unittest.main()
