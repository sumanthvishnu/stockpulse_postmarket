"""Bounded original-document reading. Extractive evidence, never price causation."""
import io
import re
from datetime import datetime
from urllib.parse import urlparse

MAX_DOCUMENTS=12
MAX_BYTES=8_000_000
MAX_PAGES=40
MATERIAL=re.compile(r"acquir|acquisit|order|contract|penalt|settlement|merger|capacity|approval|buyback|fund.?rais|investment|default|litigation|rumou?r|transaction",re.I)


def permitted_url(url):
    try:
        u=urlparse(url)
        return u.scheme=="https" and u.hostname in ("nsearchives.nseindia.com","www.nseindia.com","www.bseindia.com") and not u.username and not u.password and u.port in (None,443) and not u.fragment
    except ValueError:return False


def document_evidence(raw,event):
    from pypdf import PdfReader
    if len(raw)>MAX_BYTES or not raw.startswith(b"%PDF-"):raise ValueError("Original filing is not a bounded PDF")
    reader=PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:raise ValueError("Encrypted filing requires separate review")
    if not 1<=len(reader.pages)<=MAX_PAGES:raise ValueError("Filing exceeds full-document page budget")
    raw_pages=[page.extract_text() or "" for page in reader.pages]
    pages=[re.sub(r"\s+"," ",text).strip() for text in raw_pages]
    if any(len(text)<60 for text in pages):raise ValueError("Some filing pages lack readable text; OCR review required")
    if sum(map(len,pages))>500_000:raise ValueError("Filing text exceeds bounded review budget")
    combined=" ".join(pages)
    normalize=lambda value:re.sub(r"[^a-z0-9]","",value.lower())
    company=normalize(event.get("companyName",""))
    symbol=event["symbol"]
    if not re.fullmatch(r"[A-Z0-9&.\-]{1,40}",symbol):raise ValueError("Invalid issuer symbol")
    isin=event.get("isin","")
    if not ((len(company)>6 and company in normalize(combined)) or
            re.search(r"(?<![A-Z0-9])"+re.escape(symbol)+r"(?![A-Z0-9])",combined) or
            (isin and isin in combined)):
        raise ValueError("Original document issuer identity not matched")
    candidates=[]
    for page,raw_text in enumerate(raw_pages,1):
        # Preserve paragraph boundaries before normalization. A PDF's letterhead
        # and subject may have no sentence terminator; never join them to prose.
        lines=[line.strip() for line in raw_text.splitlines() if line.strip()]
        word_spaced=len(lines)>40 and sum(len(line.split())<=2 for line in lines)>len(lines)*.75
        paragraphs=[raw_text] if word_spaced else re.split(r"\n\s*\n|\n(?=(?:The aforesaid|The documentation|In continuation|Pursuant to|We (?:bring|inform|confirm))\b)",raw_text)
        for paragraph in paragraphs:
          text=re.sub(r"\s+"," ",paragraph).strip()
          for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])",text):
            # Preserve whole prose sentences; never assemble table cells or trim a
            # qualification midway. No model interprets these quotations.
            if 40<=len(sentence)<=800 and len(sentence.split())<=110 and MATERIAL.search(sentence):
                if re.search(r"(?:registered office|www\.|digitally signed)",sentence,re.I):continue
                if sentence.endswith('?') or re.match(r"(?:Sub\s*[:.]|Whether\b|Particulars\b)",sentence,re.I):continue
                candidates.append({"page":page,"text":sentence})
    if not candidates:raise ValueError("No bounded material prose passage; manual document review required")
    # Prefer explicit current updates/denials over a letter's acquisition history.
    # Preserve source order and whole qualifications within the selected passages.
    ranked=sorted(enumerate(candidates),key=lambda pair:(not bool(re.search(r"\brumou?r\b|still underway|documentation.*expected",pair[1]['text'],re.I)),pair[0]))[:2]
    excerpts=[item for _,item in sorted(ranked)]
    return {"method":"original-pdf-extractive-v2","pageCount":len(pages),"pagesRead":len(pages),
            "issuerMatched":True,"excerpts":excerpts,
            "limitation":"Selected issuer statements, not independently verified facts or a causal explanation; full document linked"}


def fetch_pdf(url):
    import requests
    if not permitted_url(url):raise ValueError("Filing URL outside permitted original exchanges")
    # Do not follow a source-controlled redirect to an unreviewed host.
    with requests.get(url,timeout=(10,20),stream=True,allow_redirects=False,
                      headers={"User-Agent":"StockPulseResearch/4.1","Accept":"application/pdf"}) as response:
        response.raise_for_status()
        if response.status_code!=200:raise ValueError("Filing redirect requires source review")
        chunks=[];size=0
        for chunk in response.iter_content(65536):
            size+=len(chunk)
            if size>MAX_BYTES:raise ValueError("Filing exceeds byte budget")
            chunks.append(chunk)
        return b"".join(chunks)


def run(events,sources,target,cutoff,collection_day,fetch=fetch_pdf):
    from website_enrichment import stamp
    result={"method":"original-pdf-extractive-v2","attempted":0,"read":0,"gaps":[],"maxDocuments":MAX_DOCUMENTS}
    seen={}
    for event in events:
        key="filing:"+str(len(seen)+1)
        url=event.get("url","")
        try:
            if target!=collection_day:raise ValueError("Historical document bytes not archived at cutoff; no retrospective content claim")
            published=stamp(event.get("publishedAt"))
            if not published or published>cutoff or published.date()!=target:raise ValueError("Filing publication not within session cutoff")
            if not permitted_url(url):raise ValueError("Filing URL outside permitted original exchanges")
            if url in seen:
                # A duplicate attachment bound to a different issuer must be checked
                # independently; never lend another issuer's validated content.
                raw,source_id=seen[url]
            else:
                if result["attempted"]>=MAX_DOCUMENTS:raise ValueError("Original filing read budget exhausted")
                result["attempted"]+=1
                raw=fetch(url);source_id=key
                sources.save(source_id,"Original exchange filing: "+event["symbol"],url,raw,target.isoformat())
                sources.receipts[source_id]["status"]="retrieved"
                seen[url]=(raw,source_id)
            evidence=document_evidence(raw,event)
            sources.receipts[source_id]["status"]="validated"
            evidence["sourceId"]=source_id
            event["documentEvidence"]=evidence
            result["read"]+=1
        except Exception as error:
            reason=str(error)[:180] if isinstance(error,ValueError) else type(error).__name__
            result["gaps"].append({"section":"Filing content: "+event.get("symbol","unknown"),"reason":reason})
    result["state"]="available" if events and result["read"]==len(events) else "partial" if result["read"] else "unavailable"
    return result
