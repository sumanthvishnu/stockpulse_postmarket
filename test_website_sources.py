import tempfile
import unittest
import calendar
from datetime import date,datetime
from types import SimpleNamespace
from unittest.mock import Mock,patch
from website_enrichment import IST,Sources,ons_events,ecb_events
from website_verification import nasdaq_composite,comparison,verify
from website_filings import document_evidence,permitted_url,run

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.cutoff=datetime(2026,9,30,20,30,tzinfo=IST)
        self.event={"symbol":"ABC","companyName":"ABC Limited","publishedAt":"2026-09-30T14:00:00+05:30","url":"https://nsearchives.nseindia.com/corporate/example.pdf"}

    def test_ons_publisher_timezone_and_cutoff(self):
        raw=b'BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Office for National Statistics//EN\nBEGIN:VEVENT\nDTSTART:20261001T083000Z\nSUMMARY:UK GDP release\nEND:VEVENT\nEND:VCALENDAR'
        rows=ons_events(raw,self.cutoff,"2026-10-01")
        self.assertEqual(rows[0]["country"],"UK")
        self.assertEqual(rows[0]["dateTime"],"2026-10-01T14:00:00+05:30")
        with self.assertRaises(ValueError):ons_events(raw.replace(b'Office for National Statistics',b'Unknown'),self.cutoff,"2026-10-01")

    def test_ecb_bound_dates_and_incomplete_schema(self):
        raw=('Schedules for the meetings of the Governing Council<dl>'+''.join('<dt>'+str(day)+'/10/2026</dt><dd>ECB policy meeting</dd>' for day in range(1,9))+'</dl>').encode()
        rows=ecb_events(raw,self.cutoff,"2026-10-02")
        self.assertEqual(len(rows),2)
        self.assertIn("Frankfurt date",rows[0]["dateTime"])
        with self.assertRaises(ValueError):ecb_events(raw.replace(b'<dd>ECB policy meeting</dd>',b'',1),self.cutoff,"2026-10-02")

    def test_boj_columns_release_time_and_unparsed_rows(self):
        from website_calendars import boj_events
        rows=[]
        for month in ("Jan.","Mar.","Apr.","June","July","Sept.","Oct.","Dec."):
            rows.append('<tr><td>'+month+' 17 (Thurs.), 18 (Fri.)</td><td>-</td><td>Oct. 1 (Thurs.)</td><td>Nov. 5 (Thurs.)</td></tr>')
        raw=('Monetary Policy Meetings 8:50 a.m. 8:50 a.m.<table><caption>Table : 2026</caption><tbody>'+''.join(rows)+'</tbody></table>').encode()
        parsed=boj_events(raw,self.cutoff,'2026-10-02')
        self.assertTrue(parsed)
        self.assertTrue(all(row['event']=='BOJ Summary of Opinions' and row['dateTime']=='2026-10-01T05:20:00+05:30' for row in parsed))
        with self.assertRaises(ValueError):boj_events(raw.replace(rows[0].encode(),b''),self.cutoff,'2026-10-02')
        with self.assertRaises(ValueError):boj_events(raw.replace(b'Oct. 1 (Thurs.)',b'Unknown date',1),self.cutoff,'2026-10-02')

    def nyfed(self,year,month,event_day):
        cells=[]
        for day in range(1,calendar.monthrange(year,month)[1]+1):
            if date(year,month,day).weekday()>=5:continue
            event='<a href="https://www.bls.gov/news.release/empsit.toc.htm">Employment Situation</a> (08:30)' if day==event_day else ''
            cells.append('<td class="dirCol'+('R' if date(year,month,day).weekday()==4 else 'L')+'">'+str(day)+' '+event+'</td>')
        return (calendar.month_name[month]+' '+str(year)+' all Eastern Time <table>'+''.join(cells)+'</table>').encode()

    def test_nyfed_all_weekdays_and_dst(self):
        from website_calendars import nyfed_events
        raw=self.nyfed(2026,10,2)
        rows=nyfed_events(raw,2026,10,self.cutoff,'2026-10-05')
        self.assertEqual(rows[0]['dateTime'],'2026-10-02T18:00:00+05:30')
        self.assertIn('secondary',rows[0]['basis'])
        winter=nyfed_events(self.nyfed(2026,12,4),2026,12,datetime(2026,12,1,20,30,tzinfo=IST),'2026-12-05')
        self.assertEqual(winter[0]['dateTime'],'2026-12-04T19:00:00+05:30')
        with self.assertRaises(ValueError):nyfed_events(raw.replace(b'<td class="dirColL">1 </td>',b''),2026,10,self.cutoff,'2026-10-05')
        with self.assertRaises(ValueError):nyfed_events(raw.replace(b'(08:30)',b''),2026,10,self.cutoff,'2026-10-05')
        with self.assertRaises(ValueError):nyfed_events(raw,2025,10,self.cutoff,'2026-10-05')

    def test_nyfed_month_boundary_primary_precedence_and_no_backfill(self):
        from website_calendars import collect_nyfed
        with tempfile.TemporaryDirectory() as folder:
            sources=Sources({},folder)
            with patch.object(sources,'get',side_effect=[self.nyfed(2026,9,30),self.nyfed(2026,10,2)]):
                rows,ids=collect_nyfed(sources,date(2026,9,30),self.cutoff,'2026-10-05',date(2026,9,30),{'bls':'unavailable'})
            self.assertEqual(ids,['nyfed:2026-09','nyfed:2026-10'])
            self.assertEqual(len(rows),1)
            with patch.object(sources,'get',side_effect=[self.nyfed(2026,9,30),self.nyfed(2026,10,2)]):
                rows,_=collect_nyfed(sources,date(2026,9,30),self.cutoff,'2026-10-05',date(2026,9,30),{'bls':'available'})
            self.assertEqual(rows,[])
            with patch.object(sources,'get') as fetch,self.assertRaises(ValueError):
                collect_nyfed(sources,date(2026,9,30),self.cutoff,'2026-10-05',date(2026,10,1),{})
            fetch.assert_not_called()

    def nasdaq(self,value="26797.54"):
        return ('<section id="hero"><h1>NASDAQ Composite</h1><time>DATA AS OF 9/29/2026</time><data data-parent="COMP" data-current-value="'+value+'">'+value+'</data><data id="pctChange">-0.09%</data></section>').encode()

    def test_original_publisher_identity_date_and_rounding(self):
        original=nasdaq_composite(self.nasdaq(),"2026-09-29")
        vendor={"ticker":"^IXIC","session":"2026-09-29","close":26797.5390625,"pctChange":-0.09}
        self.assertEqual(comparison(vendor,original),"matched")
        self.assertEqual(comparison({**vendor,"close":26800},original),"conflicted")
        with self.assertRaises(ValueError):nasdaq_composite(self.nasdaq(),"2026-09-28")
        with self.assertRaises(ValueError):nasdaq_composite(self.nasdaq().replace(b'data-parent="COMP"',b'data-parent="NDX"'),"2026-09-29")

    def test_conflict_quarantines_but_keeps_audit(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(Sources,"get",return_value=self.nasdaq()):
            output={"global":[{"name":"Nasdaq Composite","ticker":"^IXIC","sourceId":"global:^IXIC","session":"2026-09-29","close":1,"pctChange":-0.09}],"gaps":[]}
            verify(output,{},folder)
            self.assertEqual(output["global"],[])
            self.assertEqual(output["verifications"][0]["state"],"conflicted")
            self.assertEqual(output["verifications"][0]["vendor"]["close"],1)
            self.assertEqual(output["verifications"][0]["publisher"]["close"],26797.54)

    def reader(self,texts):
        return SimpleNamespace(is_encrypted=False,pages=[SimpleNamespace(extract_text=lambda text=text:text) for text in texts])

    def test_filing_full_pages_identity_and_exact_passage(self):
        sentence="ABC Limited has acquired the entire equity share capital of Example Company, subject to the disclosed regulatory conditions."
        with patch('pypdf.PdfReader',return_value=self.reader([sentence])):
            evidence=document_evidence(b'%PDF-example',self.event)
            self.assertEqual(evidence["pagesRead"],1)
            self.assertEqual(evidence["excerpts"],[{"page":1,"text":sentence}])
            with self.assertRaises(ValueError):document_evidence(b'%PDF-example',{**self.event,"companyName":"Other Limited","symbol":"OTHER"})
        with patch('pypdf.PdfReader',return_value=self.reader([sentence,""])):
            with self.assertRaises(ValueError):document_evidence(b'%PDF-example',self.event)

    def test_original_url_and_historical_no_fetch(self):
        self.assertFalse(permitted_url('https://user:password@nsearchives.nseindia.com/a.pdf'))
        self.assertFalse(permitted_url('https://example.org/a.pdf'))
        fetch=Mock()
        with tempfile.TemporaryDirectory() as folder:
            result=run([self.event],Sources({},folder),date(2026,9,30),self.cutoff,date(2026,10,1),fetch)
        fetch.assert_not_called()
        self.assertEqual(result["state"],"unavailable")

    def test_filing_failures_not_promoted_to_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            sources=Sources({},folder)
            result=run([dict(self.event)],sources,date(2026,9,30),self.cutoff,date(2026,9,30),lambda url:b'<html>Not a PDF</html>')
            self.assertEqual(result["read"],0)
            self.assertEqual(sources.receipts["filing:1"]["status"],"retrieved")

if __name__=='__main__':unittest.main()
