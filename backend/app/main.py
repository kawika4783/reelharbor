import asyncio, csv, io, json, secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .config import settings
from .database import Base, SessionLocal, db_session, engine
from .models import AuditLog, DetectedVideo, Download, LibraryItem, ScanJob, ScanStatus, Setting, Site, User
from .schemas import DownloadIn, LoginIn, ScanIn, SettingsIn, SetupIn
from .security import csrf_token, hash_password, make_session, require_csrf, require_user, validate_public_url, verify_password
from .utils import format_duration, format_size
from .worker import bus, run_download, run_scan

app=FastAPI(title="ReelHarbor API",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[settings.public_url],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine); settings.video_dir.mkdir(parents=True,exist_ok=True); settings.thumbnail_dir.mkdir(parents=True,exist_ok=True)
    if settings.demo_mode:
        with SessionLocal() as db:
            if not db.scalar(select(User)):
                user=User(username="demo",password_hash=hash_password("reelharbor-demo")); db.add(user); db.commit()
            if not db.scalar(select(ScanJob)):
                seed_demo(db)

def seed_demo(db):
    site=Site(base_url="https://media.example.org/documentaries",domain="media.example.org"); db.add(site); db.flush()
    scan=ScanJob(site_id=site.id,start_url=site.base_url,status="completed",mode="fast",scope="domain",max_pages=500,max_depth=4,pages_scanned=128,videos_found=20,started_at=datetime.now(timezone.utc),finished_at=datetime.now(timezone.utc)); db.add(scan); db.flush()
    titles=["Lost Cities of the Maya","The Alps: Nature's Fortress","Ocean Giants","Volcano Islands","Night Sky Atlas","Coral Kingdoms","Ancient Trade Routes","Wild Pacific","Life Below Ice","Desert Bloom","Rainforest Canopy","Deep Sea Discoveries","River of Time","Mountain Weather","Island Voices","Hidden Caves","Coastal Flight","Northern Lights","Forest After Dark","Wayfinder Stories"]
    for i,title in enumerate(titles):
        heights=[2160,1080,720,480][i%4]; sizes=[7_301_444_608,1_879_048_192,912_261_120,178_257_920][i%4]
        db.add(DetectedVideo(scan_id=scan.id,site_id=site.id,title=title,source_page=f"https://media.example.org/documentaries/{i+1}",media_url=f"https://cdn.example.org/video/{i+1}.mp4",thumbnail_url=f"https://images.unsplash.com/photo-{['1500530855697-b586d89ba3ee','1469474968028-56623f02e42e','1470770841072-f978cf4d019e','1441974231531-c6227db76b6e'][i%4]}?auto=format&fit=crop&w=640&q=80",duration_seconds=620+i*157,width=3840 if heights==2160 else heights*16//9,height=heights,format="MP4",video_codec="H.264",audio_codec="AAC",fps=29.97,size_bytes=sizes,size_estimated=False,detection_method=["html_video","open_graph","network_media","HLS"][i%4],fingerprint=__import__("hashlib").sha256(str(i).encode()).hexdigest(),download_supported=i%9!=0,drm_detected=i%9==0))
    db.commit()

def video_out(v):
    return {"id":v.id,"title":v.title,"source_page":v.source_page,"media_url":v.media_url,"thumbnail_url":v.thumbnail_url,"duration_seconds":v.duration_seconds,"duration":format_duration(v.duration_seconds),"width":v.width,"height":v.height,"resolution":f"{v.height}p" if v.height else "Unknown","format":v.format or "Unknown","video_codec":v.video_codec,"audio_codec":v.audio_codec,"fps":v.fps,"bitrate":v.bitrate,"size_bytes":v.size_bytes,"size":format_size(v.size_bytes,v.size_estimated),"size_estimated":v.size_estimated,"detection_method":v.detection_method,"drm_detected":v.drm_detected,"download_supported":v.download_supported,"duplicate":bool(v.duplicate_of),"created_at":v.created_at}

@app.get("/health")
def health(): return {"status":"ok","service":"reelharbor-api"}

@app.get("/api/auth/status")
def auth_status(request:Request,db:Session=Depends(db_session)):
    count=db.scalar(select(func.count()).select_from(User)); user_id=None
    try:user_id=require_user(request)
    except HTTPException:pass
    return {"setup_required":count==0,"authenticated":bool(user_id),"demo_mode":settings.demo_mode,"csrf_token":csrf_token(request.cookies.get("rh_session","")) if user_id else None}

def set_auth(response,user_id):
    token=make_session(user_id); response.set_cookie("rh_session",token,httponly=True,secure=settings.cookie_secure,samesite="lax",max_age=86400*7); response.set_cookie("rh_csrf",csrf_token(token),httponly=False,secure=settings.cookie_secure,samesite="lax",max_age=86400*7)

@app.post("/api/auth/setup",status_code=201)
def setup(data:SetupIn,response:Response,db:Session=Depends(db_session)):
    if db.scalar(select(User)):raise HTTPException(409,"Setup is already complete")
    user=User(username=data.username,password_hash=hash_password(data.password)); db.add(user); db.add(Setting(key="system",value={"download_folder":data.download_folder,"max_storage_percent":data.max_storage_percent,"concurrent_downloads":data.concurrent_downloads})); db.commit(); set_auth(response,user.id); return {"ok":True}

@app.post("/api/auth/login")
def login(data:LoginIn,response:Response,db:Session=Depends(db_session)):
    user=db.scalar(select(User).where(User.username==data.username))
    if not user or not verify_password(data.password,user.password_hash):raise HTTPException(401,"Invalid username or password")
    set_auth(response,user.id); return {"ok":True}

@app.post("/api/auth/logout",status_code=204)
def logout(response:Response): response.delete_cookie("rh_session"); response.delete_cookie("rh_csrf")

@app.get("/api/dashboard")
def dashboard(request:Request,db:Session=Depends(db_session)):
    require_user(request); scans=db.scalars(select(ScanJob).order_by(ScanJob.created_at.desc()).limit(5)).all(); videos=db.scalars(select(DetectedVideo).order_by(DetectedVideo.created_at.desc()).limit(5)).all(); downloads=db.scalars(select(Download).order_by(Download.created_at.desc()).limit(5)).all(); library_count=db.scalar(select(func.count()).select_from(LibraryItem)) or 0; total_size=db.scalar(select(func.sum(LibraryItem.file_size))) or 0
    return {"stats":{"videos_detected":db.scalar(select(func.count()).select_from(DetectedVideo)) or 0,"videos_downloaded":library_count,"downloads_active":db.scalar(select(func.count()).select_from(Download).where(Download.status.in_(["queued","downloading","processing"]))) or 0,"storage_used":total_size,"sites_monitored":db.scalar(select(func.count()).select_from(Site)) or 0},"scans":[scan_dict(x) for x in scans],"videos":[video_out(x) for x in videos],"downloads":[download_dict(x) for x in downloads]}

def scan_dict(s): return {"id":s.id,"url":s.start_url,"domain":urlsplit(s.start_url).hostname,"status":s.status,"mode":s.mode,"scope":s.scope,"max_pages":s.max_pages,"max_depth":s.max_depth,"pages_scanned":s.pages_scanned,"pages_queued":s.pages_queued,"pages_skipped":s.pages_skipped,"errors":s.errors,"videos_found":s.videos_found,"current_url":s.current_url,"created_at":s.created_at,"started_at":s.started_at,"finished_at":s.finished_at}
def download_dict(d): return {"id":d.id,"video_id":d.video_id,"title":d.video.title,"thumbnail_url":d.video.thumbnail_url,"status":d.status,"quality":d.quality,"progress":d.progress,"bytes_downloaded":d.bytes_downloaded,"total_bytes":d.total_bytes,"speed":d.speed,"eta_seconds":d.eta_seconds,"destination":d.destination,"retries":d.retries,"error":d.error}

@app.post("/api/scans",status_code=202)
def create_scan(data:ScanIn,request:Request,tasks:BackgroundTasks,db:Session=Depends(db_session)):
    require_user(request); require_csrf(request)
    try:url=validate_public_url(str(data.url))
    except ValueError as exc:raise HTTPException(422,str(exc))
    domain=urlsplit(url).hostname; site=db.scalar(select(Site).where(Site.domain==domain))
    if not site:site=Site(base_url=url,domain=domain);db.add(site);db.flush()
    scan=ScanJob(site_id=site.id,start_url=url,mode=data.mode,scope=data.scope,max_pages=min(data.max_pages,settings.max_pages),max_depth=data.max_depth,include_patterns=data.include_patterns,exclude_patterns=data.exclude_patterns);db.add(scan);db.commit();tasks.add_task(run_scan,scan.id);return scan_dict(scan)

@app.get("/api/scans")
def scans(request:Request,db:Session=Depends(db_session)):require_user(request);return [scan_dict(x) for x in db.scalars(select(ScanJob).order_by(ScanJob.created_at.desc())).all()]
@app.get("/api/scans/{scan_id}")
def scan(scan_id:str,request:Request,db:Session=Depends(db_session)):require_user(request);item=db.get(ScanJob,scan_id);return scan_dict(item) if item else (_ for _ in ()).throw(HTTPException(404,"Scan not found"))
@app.post("/api/scans/{scan_id}/{action}")
def scan_action(scan_id:str,action:str,request:Request,tasks:BackgroundTasks,db:Session=Depends(db_session)):
    require_user(request);require_csrf(request);item=db.get(ScanJob,scan_id)
    if not item:raise HTTPException(404,"Scan not found")
    if action not in {"pause","resume","cancel"}:raise HTTPException(404)
    item.status={"pause":"paused","resume":"running","cancel":"cancelled"}[action];db.commit()
    if action=="resume" and not item.started_at:tasks.add_task(run_scan,item.id)
    return scan_dict(item)

@app.get("/api/scans/{scan_id}/events")
async def scan_events(scan_id:str,request:Request):
    require_user(request)
    async def stream():
        async for event in bus.subscribe(scan_id):yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache"})

@app.get("/api/scans/{scan_id}/videos")
def scan_videos(scan_id:str,request:Request,q:str="",resolution:int|None=None,max_size:int|None=None,min_duration:int|None=None,db:Session=Depends(db_session)):
    require_user(request);stmt=select(DetectedVideo).where(DetectedVideo.scan_id==scan_id)
    if q:stmt=stmt.where(DetectedVideo.title.ilike(f"%{q}%"))
    if resolution:stmt=stmt.where(DetectedVideo.height>=resolution)
    if max_size:stmt=stmt.where(DetectedVideo.size_bytes<=max_size)
    if min_duration:stmt=stmt.where(DetectedVideo.duration_seconds>=min_duration)
    return [video_out(x) for x in db.scalars(stmt.order_by(DetectedVideo.created_at.desc())).all()]
@app.get("/api/videos/{video_id}")
def video(video_id:str,request:Request,db:Session=Depends(db_session)):require_user(request);v=db.get(DetectedVideo,video_id);return video_out(v) if v else (_ for _ in ()).throw(HTTPException(404,"Video not found"))

@app.get("/api/scans/{scan_id}/export.{kind}")
def export(scan_id:str,kind:str,request:Request,db:Session=Depends(db_session)):
    require_user(request);items=[video_out(x) for x in db.scalars(select(DetectedVideo).where(DetectedVideo.scan_id==scan_id)).all()];fields=["title","source_page","media_url","duration","size","resolution","format","detection_method","download_supported","drm_detected"]
    if kind=="json":return StreamingResponse(iter([json.dumps([{k:x.get(k) for k in fields} for x in items],default=str)]),media_type="application/json",headers={"Content-Disposition":"attachment; filename=scan-results.json"})
    if kind!="csv":raise HTTPException(404)
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader();writer.writerows([{k:x.get(k) for k in fields} for x in items]);return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=scan-results.csv"})

@app.post("/api/downloads",status_code=202)
def create_downloads(data:DownloadIn,request:Request,tasks:BackgroundTasks,db:Session=Depends(db_session)):
    require_user(request);require_csrf(request);created=[]
    for video_id in data.video_ids:
        video=db.get(DetectedVideo,video_id)
        if not video:continue
        if not data.force and db.scalar(select(LibraryItem).where(LibraryItem.video_id==video_id)):continue
        job=Download(video_id=video_id,quality=data.quality);db.add(job);db.flush();created.append(job.id)
    db.commit()
    for job_id in created:tasks.add_task(run_download,job_id)
    return {"created":created}
@app.get("/api/downloads")
def downloads(request:Request,db:Session=Depends(db_session)):require_user(request);return [download_dict(x) for x in db.scalars(select(Download).order_by(Download.created_at.desc())).all()]
@app.post("/api/downloads/{download_id}/{action}")
def download_action(download_id:str,action:str,request:Request,tasks:BackgroundTasks,db:Session=Depends(db_session)):
    require_user(request);require_csrf(request);job=db.get(Download,download_id)
    if not job:raise HTTPException(404,"Download not found")
    if action=="cancel":job.status="cancelled"
    elif action=="pause":job.status="paused"
    elif action in {"resume","retry"}:job.status="queued";job.retries+=action=="retry";tasks.add_task(run_download,job.id)
    elif action=="remove":db.delete(job);db.commit();return {"ok":True}
    else:raise HTTPException(404)
    db.commit();return download_dict(job)

@app.get("/api/library")
def library(request:Request,q:str="",db:Session=Depends(db_session)):
    require_user(request);stmt=select(LibraryItem).join(DetectedVideo)
    if q:stmt=stmt.where(DetectedVideo.title.ilike(f"%{q}%"))
    return [{"id":x.id,"video":video_out(x.video),"local_path":x.local_path,"file_size":x.file_size,"downloaded_at":x.downloaded_at} for x in db.scalars(stmt.order_by(LibraryItem.downloaded_at.desc())).all()]
@app.delete("/api/library/{item_id}",status_code=204)
def delete_library(item_id:str,request:Request,delete_file:bool=False,db:Session=Depends(db_session)):
    require_user(request);require_csrf(request);item=db.get(LibraryItem,item_id)
    if not item:raise HTTPException(404)
    if delete_file:
        path=Path(item.local_path).resolve();root=settings.video_dir.resolve()
        if root in path.parents and path.is_file():path.unlink()
    db.delete(item);db.commit()

@app.get("/api/logs")
def logs(request:Request,db:Session=Depends(db_session)):require_user(request);return [{"id":x.id,"level":x.level,"event":x.event,"message":x.message,"context":x.context,"created_at":x.created_at} for x in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)).all()]
@app.get("/api/settings")
def get_settings(request:Request,db:Session=Depends(db_session)):require_user(request);row=db.get(Setting,"system");return row.value if row else {"concurrent_downloads":settings.concurrent_downloads,"max_storage_percent":settings.max_storage_percent,"allow_private_networks":settings.allow_private_networks,"filename_template":"/{domain}/{title}/{title}.{ext}"}
@app.put("/api/settings")
def put_settings(data:SettingsIn,request:Request,db:Session=Depends(db_session)):
    require_user(request);require_csrf(request);row=db.get(Setting,"system") or Setting(key="system",value={});row.value=data.model_dump();db.add(row);db.commit();return row.value
