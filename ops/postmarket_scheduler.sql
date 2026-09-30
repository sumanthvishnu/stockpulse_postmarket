-- Install in the existing StockPulse Supabase project's SQL editor as postgres.
-- First create Vault secret stockpulse_postmarket_github_dispatch using the
-- dashboard. Its value is a fine-grained GitHub token restricted to
-- sumanthvishnu/stockpulse_postmarket, Actions: write, with an expiry.
-- Do not put the credential in this file or SQL history.
begin;
create extension if not exists pg_cron;
create extension if not exists pg_net;
create schema if not exists stockpulse_ops;
revoke all on schema stockpulse_ops from public, anon, authenticated;

create table if not exists stockpulse_ops.postmarket_dispatch (
  session date primary key,
  dispatched_at timestamptz not null default now(),
  request_id bigint not null
);
revoke all on stockpulse_ops.postmarket_dispatch from public, anon, authenticated;

create or replace function stockpulse_ops.dispatch_postmarket()
returns bigint language plpgsql security definer
set search_path = pg_catalog
as $function$
declare
  report_date date := (now() at time zone 'Asia/Kolkata')::date;
  dispatch_token text;
  request_id bigint;
begin
  -- One dispatch per Indian date, including concurrent scheduler invocations.
  perform pg_advisory_xact_lock(8302026);
  if exists (select 1 from stockpulse_ops.postmarket_dispatch where session=report_date) then
    return null;
  end if;
  select decrypted_secret into dispatch_token
    from vault.decrypted_secrets where name='stockpulse_postmarket_github_dispatch';
  if dispatch_token is null or length(dispatch_token)<20 then
    raise exception 'Post-market dispatch credential is missing from Vault';
  end if;
  select net.http_post(
    url := 'https://api.github.com/repos/sumanthvishnu/stockpulse_postmarket/actions/workflows/website.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization','Bearer ' || dispatch_token,
      'Accept','application/vnd.github+json',
      'Content-Type','application/json',
      'X-GitHub-Api-Version','2022-11-28',
      'User-Agent','StockPulse-Supabase-Scheduler'
    ),
    body := jsonb_build_object('ref','main','inputs',jsonb_build_object('date',report_date::text)),
    timeout_milliseconds := 10000
  ) into request_id;
  insert into stockpulse_ops.postmarket_dispatch(session,request_id)
    values(report_date,request_id);
  return request_id;
end;
$function$;
revoke all on function stockpulse_ops.dispatch_postmarket() from public, anon, authenticated;
grant execute on function stockpulse_ops.dispatch_postmarket() to postgres;

-- Fail without enabling a half-configured schedule.
do $check$
begin
  if not exists (select 1 from vault.decrypted_secrets
                 where name='stockpulse_postmarket_github_dispatch'
                   and length(decrypted_secret)>=20) then
    raise exception 'Create the restricted dispatch credential in Vault first';
  end if;
end;
$check$;
-- pg_cron normally runs in UTC. Refuse a different timezone.
do $timezone$
begin
  if coalesce(current_setting('cron.timezone',true),'GMT') not in ('GMT','UTC','Etc/UTC') then
    raise exception 'Cron timezone must be UTC for the 20:30 IST schedule';
  end if;
end;
$timezone$;
select cron.schedule('stockpulse-postmarket-2030-ist','0 15 * * *',
                     'select stockpulse_ops.dispatch_postmarket();');
commit;

-- Verify:
-- select jobid,jobname,schedule,active from cron.job
-- where jobname='stockpulse-postmarket-2030-ist';
-- select d.session,d.dispatched_at,r.status_code,r.timed_out,r.error_msg
-- from stockpulse_ops.postmarket_dispatch d
-- left join net._http_response r on r.id=d.request_id
-- order by d.session desc limit 7;
-- HTTP 204 means dispatch accepted, not report published. Verify workflow
-- outcome and website-reports/manifest.json separately. HTTP response records
-- have short retention. No automatic paid retries are enabled.
-- Pause: select cron.unschedule('stockpulse-postmarket-2030-ist');
