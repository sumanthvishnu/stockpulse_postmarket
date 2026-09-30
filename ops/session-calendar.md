# Reviewed exchange session exceptions

The website collector accepts `--session-calendar PATH` for a local reviewed registry. This option does not discover, approve or download exchange circulars. The caller must supply authentic original NSE circular bytes and record a review of their dates, segment and open/closed meaning. No registry is installed by this change.

Registry schema:

```json
{
  "schemaVersion": 1,
  "validFrom": "YYYY-MM-DD",
  "validThrough": "YYYY-MM-DD",
  "reviewedAt": "YYYY-MM-DDTHH:MM:SS+05:30",
  "reviewedBy": "review identity",
  "exceptions": [
    {
      "date": "YYYY-MM-DD",
      "state": "open",
      "publishedAt": "YYYY-MM-DDTHH:MM:SS+05:30",
      "sourceUrl": "https://nsearchives.nseindia.com/path/to/original/circular.pdf",
      "document": "circular.pdf",
      "sha256": "64 lowercase hexadecimal characters"
    }
  ]
}
```

This is a schema example, not real calendar evidence. `closed` is the other permitted state. Dates must lie within a reviewed window of at most 366 days, which must cover both recent history and upcoming T+2 dates for the requested run. The reviewer must verify the cash-market segment and all applicable exceptions in that window; an empty list must not be manufactured as evidence of no special sessions.

The loader checks source host, publication/review cutoff, duplicate dates, bounded local document paths, byte size and original SHA-256. It preserves registry and circular bytes in the worker artifact. Those checks protect integrity; they do not substitute for reviewing the circular's meaning. A supplied registry that expires anywhere in the needed history/next-session window blocks the run. A historical reconstruction rejects a review made after its cutoff.

Overrides take precedence over both weekends and the exchange holiday master and are shared by corporate-action dates, next-session/ban logic and historical session selection. Without a registry, ordinary dated holiday-master operation remains; an attempted weekend report is blocked as unverified rather than being asserted closed. No new exception, scheduler change or production configuration is activated automatically. Installing a reviewed registry and wiring the scheduled invocation are a separate explained, approved change.
