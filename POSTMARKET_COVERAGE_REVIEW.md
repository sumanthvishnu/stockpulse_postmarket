# StockPulse post-market: coverage and competitor review
Reviewed 27 September 2026. The comparison is an editorial and coverage assessment, not a ranking of investment performance.

## What the competitors do well

| Publication examined | Observed strengths | What StockPulse should adopt |
|---|---|---|
| [Zerodha Aftermarket, 25 September 2026](https://aftermarketreport.zerodha.com/p/nifty-finds-some-relief-ends-a-difficult) | A coherent session narrative; sector and historical context; linked company/global developments; delivery and derivatives context; upcoming events. | A short executive story, multi-session context and a clearly dated next-session watchlist. Do not infer investor identity from delivery or copy unsupported causal claims. |
| [ICICI Direct daily wrap, 25 September 2026](https://www.icicidirect.com/share-market-today/market-news-commentary/local-stocks-ended-on-a-mildly-positive-note/5022762) | Concise index, sector, broader-market and global coverage, with comparative periods and actively traded securities. | A readable summary before the detailed evidence tables; clearly distinguish NSE breadth from BSE breadth. |
| [HDFC Securities Prime Daily, 7 October 2025](https://www.hdfcsec.com/hsl.docs/HSL%20Prime%20Research%20-%20%20Prime%20Daily%20-%20071025-202510070956280487637.pdf) | A 22-page research pack combining macro/global tables, company news, charts and derivatives context. This is an older morning report, used only as a format/depth benchmark. | Richer historical charts and derivative-position history are worthwhile later additions. Its trade recommendations are outside StockPulse's factual daily-wrap scope. |

StockPulse already has a useful differentiator: immutable editions, source timestamps and hashes, explicitly identified universes, withheld unsupported claims, and the same facts in website and PDF. It is not yet as polished or editorially rich as the strongest sampled publication. Adding tables alone will not close that gap.

The sampled publishers sometimes use different breadth universes and 52-week-high methods. Their counts cannot validate ours without reconciling the exchange, security series, price floor, adjusted levels and observation method. Agreement on a headline close does not validate every other table.

## Recommended source architecture

Use original NSE archives for cash/F&O numbers, NSE issuer disclosures and board-meeting calendars for company events, NSE IX for official GIFT futures, and official statistical/central-bank calendars for their own releases. Use Trendlyne as a bounded fallback for relevant company filing metadata and as a discovery aid.

Trendlyne is useful, but it is not a universal replacement for all these feeds. The GIFT search result inspected resolved to a CFD/proxy instrument; it must not silently replace official futures with an identified expiry and trade timestamp. Corporate-event dates also need announcement timestamps and coverage checks.

For broad international macro coverage and publication-grade redundancy, [Trading Economics' economic-calendar API](https://docs.tradingeconomics.com/economic_calendar/) is a reasonable candidate to evaluate. It documents country/date queries and point-in-time coverage. This is a recommendation to evaluate it, not a tested integration or an assertion that every instrument is covered. Confirm redistribution rights, exact instruments, observation timestamps, historical revisions, geography and service guarantees before selecting one. No new subscription is necessary for the official-source integrations implemented here.

## Which gaps matter

| Coverage | Importance to this product | Treatment |
|---|---|---|
| Correct session, Nifty close and breadth | Essential | Block publication if validation fails. Preserve the last accepted report. |
| Company disclosures and next-session results/events | High | Fill from original announcements/calendars; show known scope. An event is not proof of a price catalyst. |
| GIFT evening futures | Useful overnight context | Require official instrument, expiry and a fresh pre-cutoff observation. Its absence does not invalidate the Indian cash-market recap. |
| Global indices, crude, FX and yields | Useful context | Show dated observations and vendor status. Do not claim a second independent verification unless it happened. |
| Historical Nifty membership | Essential to a labelled historical Nifty-movers table | Withhold that table when only an undated current membership file is available. Daily snapshots prevent the same backfill problem going forward. |
| ATM IV, authored technical levels, positioning changes | Optional specialist context | Omit from the short summary if unverified. Keep a concise scope note in the detail; do not invent IV, brokerage levels or short-covering narratives. |
| Historical calendar/contract snapshots | Required only for faithful historical reconstruction | Do not backdate current information. Preserve snapshots from each new daily run. |

## Implemented coverage additions

- Dated NSE issuer events with original filing metadata; up to three non-retrying Trendlyne data fallbacks on same-day runs.
- NSE results-related board meetings through T+2, excluding announcements after cutoff.
- MoSPI, BLS, BEA, RBI and Federal Reserve calendar adapters, including timezone/DST handling and coverage validation.
- Official NSE IX GIFT futures adapter, with expiry, evening time, cutoff and freshness checks.
- Official US Treasury 10-year par yields; explicitly labelled India 10-year vendor observations; USD/INR and commodity adapters that require contract identity.
- Separate NSE block-deal coverage.
- Consecutive-session index history and 21-session VIX context from dated archive receipts.
- Summary cards for selected disclosed company events and upcoming economic releases.

Implementation does not mean every upstream response will always be available. The September 25 edition is a reconstruction: later GIFT quotes and current calendar revisions cannot honestly fill its missing cells. A historical commodity value is acceptable only from the explicitly identified contract's own dated bars, labelled as a reconstruction selection rather than the historical front month.

## Operating controls

The separate data workflow remains scheduled for 20:30 IST. GitHub schedules are best effort and can run late. Publication is conditional on core validation; empty, blocked or stale feeds never become invented zeroes. Reopening and PDF download do not rerun research. Original editions remain saved.

No language-model calls are needed for this factual version. Trendlyne fallback calls have a separate bounded data-call budget and do not automatically retry. The SwarmIQ workflow, quota and production branch are outside this change.

## Live access findings
The scheduled worker parsed MoSPI, BEA, RBI and Federal Reserve calendars and the official NSE IX contract/timestamp payload. BLS returned HTTP 403; the report must not treat that as no upcoming US labour/inflation releases. A permitted licensed fallback or publisher-approved access is needed to close this operational gap. [BLS' public schedule](https://www.bls.gov/schedule/) remains available for manual verification.

The browser can download and reopen the saved report without extra research. First fresh trading-day validation of the newly added evening feeds remains a separate acceptance step; a Sunday diagnostic is not evidence of a successful Monday 20:30 publication.
