import json, unittest
from datetime import date, datetime
from website_enrichment import IST, announcements,results_calendar,gift_quote,trend_news,calendar_ics,central_bank_events
from website_assets import treasury_yield,india_yield
class EnrichmentTests(unittest.TestCase):
    def setUp(self):self.day=date(2026,9,25);self.cutoff=datetime(2026,9,25,20,30,tzinfo=IST)
    def test_announcement_cutoff_and_original_url(self):
        good={"symbol":"ABC","an_dt":"25-Sep-2026 15:45:00","desc":"Order win","attchmntText":"Company announced an order","attchmntFile":"https://nsearchives.nseindia.com/corporate/test.pdf"}
        late={**good,"symbol":"LATE","exchdisstime":"25-Sep-2026 21:00:00"}
        unsafe={**good,"symbol":"BAD","attchmntFile":"javascript:alert(1)"}
        result,_=announcements([good,late,unsafe],self.day,self.cutoff)
        self.assertEqual([x["symbol"] for x in result],["ABC"])
    def test_results_only_preannounced_unique_rows(self):
        r={"bm_symbol":"ABC","bm_date":"28-Sep-2026","bm_timestamp":"24-Sep-2026 15:00:00","bm_purpose":"Financial Results","bm_desc":"Quarterly financial results"}
        future={**r,"bm_symbol":"FUTURE","bm_timestamp":"26-Sep-2026 10:00:00"}
        self.assertEqual(len(results_calendar([r,r,future],"2026-09-28","2026-09-29",self.cutoff)),1)
    def test_gift_contract_timestamp_and_not_spot(self):
        r={"SYMBOL":"NIFTY","INSTRUMENTTYPE":"FUTIDX","EXPIRYDATE":"29-Sep-2026","LASTPRICE":"23,200","LTT":"25-Sep-2026 20:20:00"}
        payload={"MBP_data_Market_Watch":[{"token_data":[r,r]}]}
        result=gift_quote(payload,self.day,self.cutoff,23140.5)
        self.assertEqual(result["spotDifference"],59.5)
        for changed in [{"LTT":"26-Sep-2026 02:30:00"},{"LTT":"25-Sep-2026 15:30:00"},{"EXPIRYDATE":"24-Sep-2026"},{"INSTRUMENTTYPE":"Index Options"}]:
            with self.assertRaises(ValueError):gift_quote({"MBP_data_Market_Watch":[{"token_data":[{**r,**changed}]}]},self.day,self.cutoff,23140.5)
    def test_trendlyne_header_binding_timezone_and_premium(self):
        header="NSEcode | pubDate | title | url | isPremium"
        good="ABC | 2026-09-24T20:00:00+00:00 | Order filing | https://www.bseindia.com/file.pdf | False"
        late="ABC | 2026-09-25T20:00:00+00:00 | Later | https://www.bseindia.com/file.pdf | False"
        self.assertEqual(len(trend_news(header+"\n"+good+"\n"+late,"ABC",self.day,self.cutoff)),1)
        self.assertEqual(trend_news(header+"\n"+good.replace("False","True"),"ABC",self.day,self.cutoff),[])
    def test_calendar_dst_and_ist_date_filter(self):
        raw=b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nDTSTART;TZID=America/New_York:20260925T160000\nSUMMARY:Late US release\nEND:VEVENT\nBEGIN:VEVENT\nDTSTART;TZID=America/New_York:20260929T083000\nSUMMARY:Next release\nEND:VEVENT\nEND:VCALENDAR"
        rows=calendar_ics(raw,self.cutoff,"2026-09-29")
        self.assertEqual(rows[0]["dateTime"],"2026-09-26T01:30:00+05:30")
        winter=raw.replace(b"20260925T160000",b"20261201T160000").replace(b"20260929T083000",b"20261202T083000")
        rows=calendar_ics(winter,datetime(2026,12,1,20,30,tzinfo=IST),"2026-12-02")
        self.assertEqual(rows[0]["dateTime"],"2026-12-02T02:30:00+05:30")
    def test_calendar_outside_coverage_and_no_timezone(self):
        raw=b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nDTSTART:20260925T160000\nSUMMARY:Ambiguous\nEND:VEVENT\nEND:VCALENDAR"
        with self.assertRaises(ValueError):calendar_ics(raw,self.cutoff,"2026-09-29")
    def test_us_yield_excludes_current_us_session(self):
        raw=b'<feed><properties><NEW_DATE>2026-09-24T00:00:00</NEW_DATE><BC_10YEAR>5.18</BC_10YEAR></properties><properties><NEW_DATE>2026-09-25T00:00:00</NEW_DATE><BC_10YEAR>5.20</BC_10YEAR></properties></feed>'
        self.assertEqual(treasury_yield(raw,self.cutoff)["value"],5.18)
    def test_india_yield_binds_instrument_and_version(self):
        data={"@graph":[{"@type":"Dataset","url":"https://tradingeconomics.com/india/government-bond-yield","version":"20260925","dateModified":"20260925T12:00:00.00Z"}]}
        raw=('TEChartsMeta = [{"symbol":"WRONG","value":999},{"symbol":"GIND10YR:IND","value":7.112}];<script type="application/ld+json">'+json.dumps(data)+'</script>').encode()
        self.assertEqual(india_yield(raw,self.day,self.cutoff)["value"],7.112)
        with self.assertRaises(ValueError):india_yield(raw.replace(b"20260925",b"20260926"),self.day,self.cutoff)
if __name__=="__main__":unittest.main()
