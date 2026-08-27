#!/usr/bin/env python3
"""StockPulse automated daily pipeline (Stage 2).

Chain: fetch datapack -> trading-day gate -> LLM report (linted) ->
LLM carousel (linted) -> render PDF -> write site/ -> Telegram notify.

Env knobs:
    TRADE_DATE        DD-MM-YYYY (default: today IST)
    MOCK_LLM=1        skip the LLM, use canned HTML (for dry runs)
    DRY_RUN=1         don't send Telegram, just print what would be sent
    GH_PAGES_BASE     https://<owner>.github.io/<repo>  (builds links)
    OPENAI_API_KEY / LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone

import compliance
import llm
import stockpulse_data_fetcher as fetcher

IST = timezone(timedelta(hours=5, minutes=30))
REPO = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(REPO, "site")
DATA = os.path.join(REPO, "data")
MOCK = os.environ.get("MOCK_LLM", "") == "1"
DRY = os.environ.get("DRY_RUN", "") == "1"


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- dates ---
def parse_trade_date():
    s = (os.environ.get("TRADE_DATE") or "").strip()
    if s:
        return datetime.strptime(s, "%d-%m-%Y").date()
    return datetime.now(IST).date()


def pdf_name(tdate):
    return f"StockPulse_PostMarket_Report_{tdate.strftime('%d_%b_%Y')}.pdf"


def site_url(rel):
    base = os.environ.get("GH_PAGES_BASE", "").rstrip("/")
    return f"{base}/{rel}" if base else rel


# ----------------------------------------------------------------- state ---
def restore_state():
    """Copy archived datapacks into CWD so the fetcher's ban-list diff can see
    the prior session's pack."""
    os.makedirs(DATA, exist_ok=True)
    for fn in os.listdir(DATA):
        if fn.startswith("stockpulse_datapack_") and fn.endswith(".json"):
            dst = os.path.join(REPO, fn)
            if not os.path.exists(dst):
                shutil.copy(os.path.join(DATA, fn), dst)


def archive_pack(tdate):
    src = os.path.join(REPO, f"stockpulse_datapack_{tdate.isoformat()}_compiler.json")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(DATA, os.path.basename(src)))


# ---------------------------------------------------------------- render ---
def render_pdf(html, out):
    try:
        from weasyprint import HTML
    except ImportError:
        raise SystemExit("weasyprint missing - run: pip install weasyprint "
                         "(and on ubuntu: apt install libpango-1.0-0 "
                         "libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 shared-mime-info)")
    HTML(string=html).write_pdf(out)


def inject_footer(html):
    """Add an @page footer (disclaimer on every page) deterministically."""
    css = ('<style>@page { size: A4; margin: 16mm 14mm 20mm; '
           '@bottom-center { content: "StockPulse \u00b7 For education only. '
           'Not investment advice."; font-size: 8pt; color: #64748B; } }</style>')
    if "<head>" in html:
        return html.replace("<head>", "<head>" + css, 1)
    return css + html


# ----------------------------------------------------------- generation ---
def pack_json(pack):
    return json.dumps(pack, ensure_ascii=False, default=str)


def generate_with_lint(kind, pack):
    """Generate report/carousel HTML, lint it, retry with feedback."""
    system = open(os.path.join(REPO, "skills", f"{kind}.md"),
                  encoding="utf-8").read()
    what = ("post-market report HTML" if kind == "report"
            else "post-market carousel HTML")
    base_user = (f"Here is today's datapack (JSON). Build the {what}.\n\n"
                 + pack_json(pack))
    issues = None
    for attempt in range(1, 4):
        user = base_user
        if issues:
            user += ("\n\nYour previous draft was REJECTED by the compliance "
                     "linter. Return the FULL corrected document (not a diff), "
                     "fixing exactly these issues:\n- " + "\n- ".join(issues))
        if MOCK:
            html = mock_doc(kind, pack)
        else:
            html = llm.chat(
                system, user,
                max_tokens=12000 if kind == "report" else 10000,
                temperature=0.3 if kind == "report" else 0.4)
        issues = compliance.lint(html, kind)
        if not issues:
            return html, []
        log(f"  [{kind}] lint attempt {attempt}: {issues}")
    log(f"  [warn] {kind}: still failing after retries: {issues}")
    return html, issues


def mock_doc(kind, pack):
    """Canned output for dry runs (no API key needed)."""
    d = pack["derived"]
    n50 = d["indices"]["Nifty 50"]
    bnk = d["indices"]["Nifty Bank"]
    vix = d["vix"]["current"]
    fii = d["fii_dii_cash_summary"]["fii_net_cr"]
    dii = d["fii_dii_cash_summary"]["dii_net_cr"]
    tdate = pack["meta"]["trading_date"]
    if kind == "report":
        return ("<!doctype html><html><head><style>"
                "body{font-family:sans-serif;margin:40px}"
                "h1{color:#0F2744}h2{color:#F97316;border-bottom:2px solid #F97316}"
                "</style></head><body>"
                f"<h1>StockPulse Post-Market Report · {tdate}</h1>"
                "<h2>1. Cover</h2><p>MOCK REPORT (dry run).</p>"
                f"<h2>2. Executive Summary</h2><p>Nifty 50 closed at Rs {n50['close']:,.2f} "
                f"({n50['pct_chg']:+.2f}%). Bank Nifty Rs {bnk['close']:,.2f} "
                f"({bnk['pct_chg']:+.2f}%). India VIX at {vix}. "
                f"FII net Rs {fii:,.2f} Cr, DII net Rs {dii:,.2f} Cr.</p>"
                "<h2>14. Data Gaps Register</h2><p>No gaps (mock run).</p>"
                "<p style='margin-top:60px;color:#64748B'>For education only. "
                "Not investment advice.</p>"
                "</body></html>")
    slides = []
    for i, (bg, wm) in enumerate([("#0F2744", "CLOSE"), ("#FFFFFF", ""),
                                  ("#0F2744", "WHY"), ("#FFFFFF", ""),
                                  ("#0F2744", "MOVE"), ("#FFFFFF", ""),
                                  ("#0F2744", "NEXT"), ("#FFFFFF", "")], 1):
        slides.append(
            f'<div style="width:1080px;height:1080px;background:{bg};'
            f'color:{"#fff" if bg=="#0F2744" else "#0F2744"};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:48px">Slide {i} MOCK</div>')
    return ("<!doctype html><html><head><meta charset='utf-8'><style>"
            "body{font-family:sans-serif}.deck{display:flex;flex-direction:column;gap:24px}"
            "textarea{width:100%;height:120px}</style></head><body>"
            f"<h1>StockPulse Post-Market Carousel · {tdate} (MOCK)</h1>"
            "<div class='deck'>" + "".join(slides) + "</div>"
            "<h2>CAPTIONS · TAP COPY</h2>"
            "<p>Caption A</p><textarea>Nifty closed near Rs "
            f"{n50['close']:,.2f}, up {n50['pct_chg']:+.2f}%. Not investment "
            "advice. #Nifty #IndianStockMarket #StockMarket #Trading #Investing"
            "</textarea><p>Caption B</p><textarea>FII sold Rs "
            f"{abs(fii):,.2f} Cr while DII bought Rs {dii:,.2f} Cr. Daily wrap "
            "every evening @getstockpulse. Not investment advice. #Nifty "
            "#IndianStockMarket #FII #DII #StockMarket</textarea>"
            "</body></html>")


# ------------------------------------------------------------- telegram ---
def tg(method, **data):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                      data=data, timeout=120)
    r.raise_for_status()
    return r.json()


def tg_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def notify(tdate, pack, pdf_path, carousel_url, pdf_url, issues):
    import requests
    d = pack["derived"]
    n50 = d["indices"]["Nifty 50"]
    bnk = d["indices"]["Nifty Bank"]
    vix = d["vix"]["current"]
    fii = d["fii_dii_cash_summary"]["fii_net_cr"]
    dii = d["fii_dii_cash_summary"]["dii_net_cr"]
    wday = tdate.strftime("%A")
    lines = [
        f"<b>📊 StockPulse Post-Market · {wday}, {tdate.strftime('%d %b %Y')}</b>",
        f"Nifty {n50['close']:,.2f} ({n50['pct_chg']:+.2f}%) · "
        f"Bank Nifty {bnk['close']:,.2f} ({bnk['pct_chg']:+.2f}%)",
        f"VIX {vix} · FII Rs {fii:,.2f} Cr · DII Rs {dii:,.2f} Cr",
        "",
        f"🎠 <a href=\"{tg_escape(carousel_url)}\">Carousel (open in browser, download slides)</a>",
        f"📄 <a href=\"{tg_escape(pdf_url)}\">Report (PDF)</a>",
    ]
    if issues:
        lines.append("")
        lines.append("⚠️ Lint warnings: " + "; ".join(issues[:4]))
    text = "\n".join(lines)
    if DRY:
        log(f"[dry] would send to Telegram:\n{text}\n[dry] + PDF {pdf_path}")
        return
    tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"],
       text=text, parse_mode="HTML", disable_web_page_preview=False)
    with open(pdf_path, "rb") as fh:
        requests.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
            f"/sendDocument",
            data={"chat_id": os.environ["TELEGRAM_CHAT_ID"]},
            files={"document": (os.path.basename(pdf_path), fh)}, timeout=120)


def notify_generic(text):
    if DRY:
        log(f"[dry] would send: {text}")
        return
    tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text)


# ----------------------------------------------------------------- main ---
def main():
    os.chdir(REPO)
    tdate = parse_trade_date()
    log(f"StockPulse pipeline - trading date {tdate} "
        f"(mock={MOCK}, dry={DRY})")

    restore_state()
    log("== stage 1/4: fetch datapack ==")
    fetcher.collect(tdate)

    cpath = os.path.join(REPO, f"stockpulse_datapack_{tdate.isoformat()}_compiler.json")
    if not os.path.exists(cpath):
        notify_generic(f"⚠️ StockPulse: no datapack produced for {tdate} - "
                       "likely a market holiday or archive not yet published.")
        return
    pack = json.load(open(cpath, encoding="utf-8"))

    hol = pack.get("data", {}).get("holiday_check", {})
    if hol.get("is_holiday"):
        detail = hol.get("detail") or "market holiday"
        notify_generic(f"📭 StockPulse: markets closed today ({detail}). "
                       "No report generated.")
        return
    if "indices" not in pack.get("derived", {}):
        notify_generic("⚠️ StockPulse: index data missing from datapack - "
                       "report aborted. Check fetcher logs.")
        return

    log("== stage 2/4: compile report (LLM + lint) ==")
    report_html, report_issues = generate_with_lint("report", pack)
    log("== stage 3/4: build carousel (LLM + lint) ==")
    carousel_html, carousel_issues = generate_with_lint("carousel", pack)
    all_issues = report_issues + carousel_issues

    log("== stage 4/4: render + publish + notify ==")
    day_dir = os.path.join(SITE, tdate.isoformat())
    os.makedirs(day_dir, exist_ok=True)
    pdf_path = os.path.join(day_dir, pdf_name(tdate))
    render_pdf(inject_footer(report_html), pdf_path)
    with open(os.path.join(day_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(report_html)
    with open(os.path.join(day_dir, "carousel.html"), "w", encoding="utf-8") as f:
        f.write(carousel_html)
    shutil.copy(cpath, os.path.join(day_dir, "datapack.json"))

    archive_pack(tdate)

    carousel_url = site_url(f"{tdate.isoformat()}/carousel.html")
    pdf_url = site_url(f"{tdate.isoformat()}/{pdf_name(tdate)}")
    notify(tdate, pack, pdf_path, carousel_url, pdf_url, all_issues)

    log(f"\nDone. PDF: {pdf_path}\nCarousel: {day_dir}/carousel.html"
        f"\nCarousel URL: {carousel_url}\nReport URL: {pdf_url}")


if __name__ == "__main__":
    main()
