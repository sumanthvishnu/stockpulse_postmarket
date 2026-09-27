# Website post-market edition
The website reads the immutable `website-reports` branch, produced by `.github/workflows/website.yml`. This is separate from the existing carousel/Telegram pipeline.

## Schedule and scope
The job is configured for 15:00 UTC / 20:30 IST daily. GitHub schedules run only when the workflow is on the default branch and are best effort; the website does not promise an exact-minute publication. Weekend runs record closure; regular exchange holidays are confirmed with the holiday master. Unconfigured special weekend sessions are not assumed to be ordinary trading days.

The collector uses the existing Python archive downloader, records original source hashes and retrieval times, checks source body dates, and then produces a deterministic summary. Normal viewing, changing saved editions and downloading PDF make zero model requests. The website edition makes zero paid AI calls.

A prior accepted edition for the same session prevents duplicate automatic collection. An explicitly supplied historical date can produce a new immutable correction. A blocked new session updates the attempt status while retaining previous accepted reports.

## Current coverage
Implemented: closing snapshot, sectors, EQ breadth, Nifty/broader movers when same-session membership is verified, adjusted 52-week counts, provisional cash flows, participant futures positions, FII derivatives activity, options concentrations, corporate actions and ban lists. The summary explains observed participation and sector divergence without inventing causes.

Completed-session global indices are included as Yahoo Finance vendor observations with venue calendars; independent second-source verification is absent. Dated bulk transaction legs of at least Rs 20 Cr are included without inferring market-making or investment intent. The v4 coverage extension adds NSE issuer disclosures and results meetings, MoSPI/BLS/BEA/RBI/Fed calendar adapters, official NSE IX GIFT futures, explicit commodity contracts/FX/yields, separate block deals, contiguous five-session history, 21-session VIX context and participant futures long/short counts. Trendlyne is a bounded same-day fallback for dated primary-filing metadata (maximum three data calls, no retries). The product is a data-led daily edition, not a claim that every v4 source integration is complete. Historical replays with no dated membership withhold Nifty-specific mover classifications.

## States and audit
Reports are `available_with_gaps`; fields never silently become zero. Missing core source dates, invalid index arithmetic, invalid breadth, unresolved sanity flags or an unknown holiday calendar block publication. The manifest is a read pointer; reports remain immutable and the website verifies SHA-256 before rendering. The detailed PDF is rendered from the exact selected saved report, without AI.

Original downloads and the input datapack/receipts are retained in the validation workflow artifact for 90 days. Long-term report JSON, source digests, original archive URLs and prior revisions remain in the feed branch. This does not promise indefinite storage of the original source bytes. The feed uses the existing public data repository; website pages and PDF routes require the existing subscription.

## Operation
- Inspect the website workflow result and manifest `latestAttempt` when a new edition is absent.
- Do not reset SwarmIQ allowances or change its saved checkpoints.
- Fix failed validation before requesting another deliberate run; do not bypass gates.
- To reconstruct a date, dispatch this workflow with YYYY-MM-DD. The edition is labelled reconstructed.
- A newer failed report must not delete or overwrite previously accepted history.
- No Telegram, email or carousel is sent by this workflow.

## API recommendation
Keep numerical collection and computation in Python. A language model should be optional for sourced narrative, never required for the numeric summary.

For a later narrative layer, my current first candidate is the direct Claude API with `claude-sonnet-5`, subject to a small report-specific evaluation and available account access. Anthropic's current announcement lists $2 per million input tokens and $10 per million output tokens, with the introductory rate made permanent in its August update. At an illustrative 20,000 input and 2,000 output tokens, one call is about $0.06 before tools, taxes and retries. This is an estimate, not measured report usage. No such call is enabled here.

Source checked 27 September 2026: https://www.anthropic.com/news/claude-sonnet-5
The existing SwarmIQ model remains unchanged. The current website edition needs no additional AI API key.

## Acceptance evidence, 27 September 2026
A September 25 archive replay passed and published the website feed. Fourteen offline validation tests cover dated source bodies, arithmetic, empty-versus-failed action responses, ban-list applicability and immutable report hashes. The web application passed its regression/build checks and authenticated desktop/mobile browser acceptance, including saved-edition reopening and a real 15-page PDF download. Browser verification blocks research/AI mutations. The global/deal edition was exercised in website workflow run 36319045702 and browser acceptance run 36319049923. The latest source-caption correction keeps the ban-list evidence date aligned with the next trading session.

Owner explicitly authorized activation on 27 September 2026. PR #3 merged as 75989a2555ef210d420653eace2d20650f32de1c; the website workflow is present on main and GitHub reports it active. Its daily target is 20:30 IST. The first scheduled invocation has not yet been observed. StockPulse web remains on its testing preview; no web-main merge or production promotion occurred.

## V4 coverage extension, 27 September 2026
[Data acceptance 36321962235](https://github.com/sumanthvishnu/stockpulse_postmarket/actions/runs/36321962235) passed 27 offline tests and real September 25 archive collection. Accepted edition: `2026-09-25-d38f5c14c25bee25`, 23 sections, with 12 company-event rows, five results meetings, six bond/commodity/FX observations and six block transaction legs. The final replay used zero model calls and zero Trendlyne calls. A preceding bounded integration probe used three Trendlyne data requests; no automatic retries.

[Current provider diagnostics](https://github.com/sumanthvishnu/stockpulse_postmarket/actions/runs/36321665566) parsed MoSPI, BEA, RBI, Fed, NSE IX and named commodity-contract metadata. BLS returned HTTP 403 from the worker, so US labour/inflation-calendar completeness is not established. No access bypass or unlicensed replacement was installed. The annual MoSPI/RBI source URLs must be updated when their published fiscal-year scope expires; validation fails closed outside that scope.

Remaining limitations: the September 25 reconstruction has no pre-cutoff archived GIFT quote, dated Nifty membership or contemporaneous BLS/BEA/Fed calendar revision. Current snapshots are not backdated. Global vendor observations have no independent second-source verification. ATM IV and attributed technical levels remain optional omissions. Daily first-fresh-session validation remains outstanding; Sunday provider diagnostics do not establish next-session availability. Named commodity contracts in reconstructions are explicitly selected during reconstruction and are not claimed to be the historical front month.

PR #4 retains the existing 20:30 IST website scheduler and activates this extension when merged. The Telegram/carousel workflow is unchanged. See [coverage and competitor review](POSTMARKET_COVERAGE_REVIEW.md) for priority, comparison and API recommendations.
