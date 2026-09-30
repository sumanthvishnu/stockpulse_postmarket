"""Calendar regressions: never turn an incomplete parse into no events."""
import unittest
from datetime import datetime
from website_enrichment import IST, calendar_ics, central_bank_events


def ics(*events):
    return ("BEGIN:VCALENDAR\nVERSION:2.0\n"+"".join(
        "BEGIN:VEVENT\n"+event+"\nEND:VEVENT\n" for event in events
    )+"END:VCALENDAR").encode()


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.cutoff=datetime(2026,9,30,20,30,tzinfo=IST)
        self.later="DTSTART;TZID=America/New_York:20261002T083000\nSUMMARY:Later release"

    def test_cutoff_inclusive_and_late_same_day_release(self):
        raw=ics("DTSTART:20260930T150000Z\nSUMMARY:At cutoff",
                "DTSTART:20260930T180000Z\nSUMMARY:After cutoff",self.later)
        rows=calendar_ics(raw,self.cutoff,"2026-10-02")
        self.assertEqual([r["event"] for r in rows],["After cutoff","Later release"])
        self.assertEqual(rows[0]["dateTime"],"2026-09-30T23:30:00+05:30")

    def test_date_only_same_day_is_uncertain_not_absent(self):
        rows=calendar_ics(ics("DTSTART;VALUE=DATE:20260930\nSUMMARY:Untimed release",self.later),self.cutoff,"2026-10-02")
        self.assertEqual(len(rows),2)
        self.assertIn("may already have occurred",rows[0]["dateTime"])

    def test_us_date_overlaps_following_ist_day(self):
        cutoff=datetime(2026,10,1,2,0,tzinfo=IST)
        rows=calendar_ics(ics("DTSTART;VALUE=DATE:20260930\nSUMMARY:US untimed",self.later),cutoff,"2026-10-02")
        self.assertEqual(rows[0]["event"],"US untimed")

    def test_cancelled_event_is_not_upcoming(self):
        rows=calendar_ics(ics("STATUS:CANCELLED\nSUMMARY:Cancelled",self.later),self.cutoff,"2026-10-02")
        self.assertEqual([r["event"] for r in rows],["Later release"])

    def test_malformed_and_unexpanded_events_block_calendar(self):
        for event in ("SUMMARY:Missing date", "DTSTART:20261001T140000Z",
                      "DTSTART:20261001T140000Z\nSUMMARY:Repeating\nRRULE:FREQ=DAILY;COUNT=3",
                      "DTSTART:20261001T140000\nSUMMARY:No timezone"):
            with self.subTest(event=event),self.assertRaises(ValueError):
                calendar_ics(ics(event,self.later),self.cutoff,"2026-10-02")

    def test_same_day_fed_meeting_kept_with_time_caveat(self):
        block="2026 FOMC Meetings"+"".join(
            '<div class="fomc-meeting__month"><strong>'+month+'</strong></div>'
            '<div class="fomc-meeting__date">'+days+'</div>'
            for month,days in [("January","27-28"),("March","17-18"),("April","28-29"),
                ("June","16-17"),("July","28-29"),("September","29-30"),
                ("October","27-28"),("December","8-9")])
        rows=central_bank_events(block.encode(),self.cutoff,"2026-10-02","Fed")
        self.assertEqual(len(rows),1)
        self.assertIn("2026-09-30",rows[0]["dateTime"])
        self.assertIn("time unconfirmed",rows[0]["dateTime"])


if __name__=="__main__":unittest.main()
