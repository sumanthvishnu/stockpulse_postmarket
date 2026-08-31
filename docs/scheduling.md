# Scheduling: why 21:00 IST needs an external trigger

## The problem

`.github/workflows/daily.yml` carries `schedule: cron: "27 15 * * 1-5"`, but
**GitHub's `schedule` event must not be relied on for punctual delivery.**

Evidence from this repository:

| Trigger | Asked for | Actually fired | Delay |
| --- | --- | --- | --- |
| `schedule` (only one ever) | 15:30 UTC Fri 28 Aug | 00:04 UTC Sat 29 Aug | **8h 34m** |
| `workflow_dispatch` (14 runs) | on demand | within seconds | none |

This is documented behaviour, not a misconfiguration:

> The `schedule` event can be delayed during periods of high loads of GitHub
> Actions workflow runs. High load times include the start of every hour. If the
> load is sufficiently high enough, some queued jobs may be dropped.
>
> — <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule>

Two details make this repo a worst case:

- **New, low-traffic, free-tier repos are deprioritised hardest.** The scheduler
  sweeps that queue group once or twice a day rather than at the cron minute.
- **Moving the cron minute does not fix it.** The drift happens *before* the job
  enters any runner queue, so staggering off `:00`/`:30` only takes the edge off.

`workflow_dispatch` goes through a **different queue** and is picked up almost
immediately. So: keep the pipeline exactly where it is, and drive the clock from
outside.

## The fix — external cron calls `workflow_dispatch`

One-time setup, ~5 minutes. Free.

### 1. Create a fine-grained personal access token

<https://github.com/settings/personal-access-tokens/new>

- **Repository access** → Only select repositories → `stockpulse_postmarket`
- **Permissions** → Repository permissions → **Actions: Read and write**
- Set a long expiry (or no expiry) so it does not silently lapse
- Copy the token (`github_pat_...`)

### 2. Point a free scheduler at the dispatch API

Sign up at <https://cron-job.org> (free) and create a job:

| Field | Value |
| --- | --- |
| URL | `https://api.github.com/repos/sumanthvishnu/stockpulse_postmarket/actions/workflows/daily.yml/dispatches` |
| Method | `POST` |
| Schedule | `21:00`, Mon–Fri, timezone **Asia/Kolkata** |
| Header | `Authorization: Bearer github_pat_...` |
| Header | `Accept: application/vnd.github+json` |
| Header | `X-GitHub-Api-Version: 2022-11-28` |
| Body | `{"ref":"main"}` |

A success is **HTTP 204 No Content** with an empty body. Anything else (401 bad
token, 403 missing Actions permission, 404 wrong path) means it will not fire.

Verify from a terminal first:

```bash
curl -i -X POST \
  -H "Authorization: Bearer github_pat_..." \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/sumanthvishnu/stockpulse_postmarket/actions/workflows/daily.yml/dispatches \
  -d '{"ref":"main"}'
```

### 3. Leave the built-in `schedule` alone

It stays as a backstop. If the external trigger ever dies, GitHub will still get
around to running the job eventually — late, but the report goes out.

## Why duplicate triggers are safe

Because there are now two clocks, `daily.yml` opens with a guard step that skips
the run when:

- it is **Sat/Sun IST** — stops a Friday slot that slipped to Saturday morning
  from generating a bogus weekend report, and
- `data/stockpulse_datapack_<today-IST>_compiler.json` **already exists** — the
  datapack is committed only after a successful run, so this means today is done.

Manual dispatch with an explicit `date`, or with `force: true`, bypasses the
guard.

## If a night is missed

The workflow's last step fires **only on failure** and sends a Telegram message
with a link to the run log. Silence now means success. If you get an alert, or no
message at all by ~21:15 IST, trigger it by hand:

Actions → *StockPulse Daily Post-Market* → **Run workflow** → `force: true`.
