import unittest
from website_briefing import market_movers,summary
from test_website_report import fixture
from website_report import build_report,IST
from datetime import datetime
class BriefingTests(unittest.TestCase):
    def test_current_day_and_recent_direction_are_distinct(self):
        p,r=fixture();p["derived"]["website_history"]={"fiveSessionChange":{"Nifty 50":-2}}
        result=summary(p,[])
        self.assertIn("positive day",result[0]["title"]);self.assertIn("-2.00%",result[0]["text"])
        self.assertEqual(result[1]["title"],"A divergence to note")
    def test_unverified_internals_are_not_narrated(self):
        p,r=fixture();p["derived"]["internals_52wk"]={"new_highs":999,"new_lows":999}
        self.assertNotIn("999",str(summary(p,[])))
    def test_liquid_movers_date_series_threshold_and_after_close(self):
        p,r=fixture()
        p["data"]["bhavdata_full"]="SYMBOL,SERIES,DATE1,CLOSE_PRICE,PREV_CLOSE,TURNOVER_LACS,DELIV_PER\nABC,EQ,25-Sep-2026,110,100,20000,65\nILLQ,EQ,25-Sep-2026,150,100,100,80\nOLD,EQ,24-Sep-2026,200,100,20000,60\nOTHER,BE,25-Sep-2026,200,100,20000,60\nDOWN,EQ,25-Sep-2026,90,100,30000,-\n"
        p["derived"]["website_enrichment"]={"catalysts":[{"symbol":"ABC","publishedAt":"2026-09-25T16:00:00+05:30","event":"Order win","detail":"Announced a contract","url":"https://nsearchives.nseindia.com/corporate/abc.pdf"}]}
        rows=market_movers(p);self.assertEqual([x["symbol"] for x in rows],["ABC","DOWN"])
        self.assertEqual(rows[0]["change"],10);self.assertIn("After the cash-market close",rows[0]["event"])
        self.assertIsNone(rows[1]["delivery"]);self.assertIn("No verified catalyst",rows[1]["event"])
        r["catalysts"]=dict(r["indices"])
        report=build_report(p,r,datetime(2026,9,25,20,30,tzinfo=IST))
        movers=next(s for s in report["sections"] if s["id"]=="liquid-movers")
        self.assertEqual(movers["rows"][0]["href"],"https://nsearchives.nseindia.com/corporate/abc.pdf")
        self.assertEqual(len(report["summary"]),3)
    def test_statutory_acquisition_words_do_not_rank_as_deals(self):
        from website_briefing import event_priority
        self.assertEqual(event_priority({"event":"Updates","detail":"SEBI Substantial Acquisition of Shares and Takeovers Regulations"}),0)
        self.assertEqual(event_priority({"event":"Reply to Clarification- Financial results"}),0)
        self.assertEqual(event_priority({"event":"Acquisition","detail":"Purchase of a business"}),3)
    def test_live_gift_uses_capture_time_but_backfill_keeps_cutoff(self):
        from website_enrichment import gift_observation_cutoff,gift_quote
        from datetime import date
        target=date(2026,9,25);core=datetime(2026,9,25,20,30,tzinfo=IST)
        captured="2026-09-25T20:34:00+05:30"
        live=gift_observation_cutoff(target,core,captured,target)
        payload={"MBP_data_Market_Watch":[{"token_data":[{"SYMBOL":"NIFTY","INSTRUMENTTYPE":"FUTIDX","EXPIRYDATE":"29-Sep-2026","LASTPRICE":"23200","LTT":"25-Sep-2026 20:33:00"}]}]}
        self.assertEqual(gift_quote(payload,target,live,23140.5)["level"],23200)
        historical=gift_observation_cutoff(target,core,captured,date(2026,9,27))
        self.assertEqual(historical,core)
        with self.assertRaises(ValueError):gift_quote(payload,target,historical,23140.5)
if __name__=="__main__":unittest.main()
