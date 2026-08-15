import asyncio, hashlib, json, os, shutil, subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from .config import settings
from .database import SessionLocal
from .detectors import detect_all, VideoCandidate
from .models import AuditLog, CrawlPage, DetectedVideo, Download, DownloadAttempt, DownloadStatus, LibraryItem, ScanJob, ScanStatus
from .security import validate_public_url
from .utils import sanitize_filename

class EventBus:
    def __init__(self): self.listeners={}
    async def publish(self,channel,payload):
        for q in self.listeners.get(channel,[]): await q.put(payload)
    async def subscribe(self,channel):
        q=asyncio.Queue(); self.listeners.setdefault(channel,[]).append(q)
        try:
            while True: yield await q.get()
        finally: self.listeners[channel].remove(q)
bus=EventBus()

def log(db,event,message,level="info",**context): db.add(AuditLog(event=event,message=message,level=level,context=context))

def allowed(url,start,scope,include,exclude):
    a,b=urlsplit(url),urlsplit(start)
    if a.hostname!=b.hostname:return False
    if any(pattern and pattern in a.path for pattern in exclude):return False
    if include and not any(pattern in url for pattern in include):return False
    if scope=="page":return url.split("#")[0]==start.split("#")[0]
    if scope=="directory":return a.path.startswith(b.path.rsplit("/",1)[0]+"/")
    return True

def enrich_headers(candidate,headers):
    length=headers.get("content-length"); ctype=headers.get("content-type","")
    if length and length.isdigit(): candidate.estimated_size=int(length)
    if not candidate.format:
        candidate.format=("HLS" if "mpegurl" in ctype else "DASH" if "dash+xml" in ctype else candidate.media_url.split("?")[0].rsplit(".",1)[-1].upper())

async def run_scan(scan_id):
    db=SessionLocal(); scan=db.get(ScanJob,scan_id)
    try:
        scan.status=ScanStatus.running.value; scan.started_at=datetime.now(timezone.utc); log(db,"crawl_started",f"Scan started for {scan.start_url}",scan_id=scan.id); db.commit()
        if scan.mode=="browser": await browser_scan(db,scan)
        else: await fast_scan(db,scan)
        db.refresh(scan)
        if scan.status not in {ScanStatus.cancelled.value,ScanStatus.failed.value}: scan.status=ScanStatus.completed.value
        scan.finished_at=datetime.now(timezone.utc); log(db,"crawl_completed",f"Scan finished with {scan.videos_found} videos",scan_id=scan.id); db.commit()
        await bus.publish(scan.id,{"type":"complete","status":scan.status})
    except Exception as exc:
        scan.status=ScanStatus.failed.value; scan.errors+=1; scan.finished_at=datetime.now(timezone.utc); log(db,"crawl_failed",str(exc),"error",scan_id=scan.id); db.commit(); await bus.publish(scan.id,{"type":"error","message":str(exc)})
    finally: db.close()

async def fast_scan(db,scan):
    queue=deque([(scan.start_url,0)]); seen=set(); limits=httpx.Limits(max_connections=5); timeout=httpx.Timeout(20,connect=10)
    async with httpx.AsyncClient(timeout=timeout,limits=limits,follow_redirects=False,headers={"User-Agent":"ReelHarbor/1.0 (+self-hosted crawler)"}) as client:
        while queue and scan.pages_scanned<scan.max_pages:
            db.refresh(scan)
            if scan.status==ScanStatus.cancelled.value:return
            while scan.status==ScanStatus.paused.value: await asyncio.sleep(.5); db.refresh(scan)
            url,depth=queue.popleft()
            if url in seen:continue
            seen.add(url); scan.current_url=url; scan.pages_queued=len(queue); db.commit()
            try:
                safe=validate_public_url(url); response=await client.get(safe)
                if response.is_redirect:
                    target=urljoin(url,response.headers.get("location","")); validate_public_url(target); queue.appendleft((target,depth)); continue
                response.raise_for_status(); content=response.content[:5_000_000]; html=content.decode(response.encoding or "utf-8",errors="replace")
                db.add(CrawlPage(scan_id=scan.id,url=url,status_code=response.status_code,depth=depth)); scan.pages_scanned+=1
                for item in detect_all(html,url):
                    existing=db.scalar(select(DetectedVideo).where(DetectedVideo.scan_id==scan.id,DetectedVideo.fingerprint==item.fingerprint))
                    if not existing:
                        try:
                            head=await client.head(validate_public_url(item.media_url)); enrich_headers(item,head.headers)
                        except Exception: pass
                        previous=db.scalar(select(DetectedVideo).where(DetectedVideo.site_id==scan.site_id,DetectedVideo.fingerprint==item.fingerprint))
                        db.add(DetectedVideo(scan_id=scan.id,site_id=scan.site_id,title=item.title[:500],source_page=item.source_page,media_url=item.media_url,thumbnail_url=item.thumbnail_url,duration_seconds=item.duration,width=item.width,height=item.height,format=item.format,video_codec=item.codec,size_bytes=item.estimated_size,size_estimated=item.format in {"HLS","DASH"},detection_method=item.detection_method,fingerprint=item.fingerprint,drm_detected=item.drm_detected,download_supported=item.download_supported,duplicate_of=previous.id if previous else None)); scan.videos_found+=1; log(db,"media_discovered",item.title,scan_id=scan.id,method=item.detection_method)
                if depth<scan.max_depth and scan.scope!="page":
                    soup=BeautifulSoup(html,"html.parser")
                    for link in soup.select("a[href]"):
                        target=urljoin(url,link["href"]).split("#")[0]
                        if target not in seen and allowed(target,scan.start_url,scan.scope,scan.include_patterns,scan.exclude_patterns): queue.append((target,depth+1))
                db.commit(); await bus.publish(scan.id,{"type":"progress","pages_scanned":scan.pages_scanned,"pages_queued":len(queue),"videos_found":scan.videos_found,"current_url":url})
            except Exception as exc:
                scan.errors+=1; scan.pages_skipped+=1; db.add(CrawlPage(scan_id=scan.id,url=url,depth=depth,error=str(exc)[:1000])); db.commit()

async def browser_scan(db,scan):
    from playwright.async_api import async_playwright
    validate_public_url(scan.start_url); captured=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True, executable_path=os.getenv("CHROMIUM_PATH","/usr/bin/chromium"), args=["--no-sandbox"]); page=await browser.new_page()
        async def response_handler(response):
            ct=response.headers.get("content-type","")
            if any(x in ct for x in ("video/","mpegurl","dash+xml")) or any(x in response.url.lower() for x in (".mp4",".m3u8",".mpd",".webm")): captured.append(response.url)
        page.on("response",response_handler); await page.goto(scan.start_url,wait_until="networkidle",timeout=45000); await page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); await page.wait_for_timeout(1500); html=await page.content(); await browser.close()
    for url in captured: html+=f'\n<video src="{url}"></video>'
    # Feed the rendered page to the same normalized detector path.
    scan.pages_scanned=1; scan.current_url=scan.start_url; db.add(CrawlPage(scan_id=scan.id,url=scan.start_url,status_code=200,depth=0))
    for item in detect_all(html,scan.start_url):
        if not db.scalar(select(DetectedVideo).where(DetectedVideo.scan_id==scan.id,DetectedVideo.fingerprint==item.fingerprint)):
            db.add(DetectedVideo(scan_id=scan.id,site_id=scan.site_id,title=item.title[:500],source_page=item.source_page,media_url=item.media_url,thumbnail_url=item.thumbnail_url,detection_method="network_media" if item.media_url in captured else item.detection_method,fingerprint=item.fingerprint,format=item.format,drm_detected=False,download_supported=True)); scan.videos_found+=1
    db.commit(); await bus.publish(scan.id,{"type":"progress","pages_scanned":1,"pages_queued":0,"videos_found":scan.videos_found,"current_url":scan.start_url})

async def run_download(download_id):
    db=SessionLocal(); job=db.get(Download,download_id); video=job.video; attempt=DownloadAttempt(download_id=job.id); db.add(attempt)
    try:
        usage=shutil.disk_usage(settings.video_dir if settings.video_dir.exists() else "/")
        if usage.used/usage.total*100>=settings.max_storage_percent: raise RuntimeError(f"Downloads paused — disk is {usage.used/usage.total:.0%} full")
        if video.drm_detected or not video.download_supported: job.status=DownloadStatus.drm.value if video.drm_detected else DownloadStatus.unsupported.value; db.commit(); return
        domain=urlsplit(video.source_page).hostname or "unknown"; folder=settings.video_dir/sanitize_filename(domain); folder.mkdir(parents=True,exist_ok=True); template=str(folder/(sanitize_filename(video.title)+".%(ext)s")); job.status=DownloadStatus.downloading.value; job.destination=template; log(db,"download_started",video.title,download_id=job.id); db.commit()
        cmd=["yt-dlp","--newline","--no-playlist","--no-write-comments","--restrict-filenames","-f", "bestaudio/best" if job.quality=="audio" else "bestvideo+bestaudio/best", "--merge-output-format","mp4","-o",template,video.media_url]
        process=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        async for raw in process.stdout:
            line=raw.decode(errors="replace"); match=__import__("re").search(r"(\d+(?:\.\d+)?)%",line)
            if match: job.progress=float(match.group(1)); job.updated_at=datetime.now(timezone.utc); db.commit(); await bus.publish("downloads",{"id":job.id,"progress":job.progress,"status":job.status})
        code=await process.wait()
        if code: raise RuntimeError("Downloader failed; source may have expired or returned an error")
        candidates=sorted(folder.glob(sanitize_filename(video.title)+".*"),key=lambda p:p.stat().st_mtime,reverse=True)
        if not candidates: raise RuntimeError("Download completed without an output file")
        path=candidates[0]; digest=hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda:fh.read(1024*1024),b""): digest.update(chunk)
        job.status=DownloadStatus.completed.value; job.progress=100; job.destination=str(path); job.total_bytes=path.stat().st_size; db.add(LibraryItem(video_id=video.id,local_path=str(path),file_size=path.stat().st_size,file_hash=digest.hexdigest())); attempt.finished_at=datetime.now(timezone.utc); log(db,"download_completed",video.title,download_id=job.id); db.commit(); await bus.publish("downloads",{"id":job.id,"progress":100,"status":"completed"})
    except Exception as exc:
        job.status=DownloadStatus.failed.value; job.error=str(exc); attempt.error=str(exc); attempt.finished_at=datetime.now(timezone.utc); log(db,"download_failed",str(exc),"error",download_id=job.id); db.commit(); await bus.publish("downloads",{"id":job.id,"status":"failed","error":str(exc)})
    finally: db.close()
