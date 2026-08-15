import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)


class ScanStatus(str, enum.Enum):
    queued="queued"; running="running"; paused="paused"; completed="completed"; failed="failed"; cancelled="cancelled"

class DownloadStatus(str, enum.Enum):
    queued="queued"; downloading="downloading"; processing="processing"; completed="completed"; failed="failed"; cancelled="cancelled"; paused="paused"; drm="drm_protected"; unsupported="unsupported"

class User(Base):
    __tablename__="users"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str]=mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    is_admin: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)

class Site(Base):
    __tablename__="sites"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    base_url: Mapped[str]=mapped_column(String(2048), unique=True)
    domain: Mapped[str]=mapped_column(String(255), index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)

class ScanJob(Base):
    __tablename__="scan_jobs"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    site_id: Mapped[str]=mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    start_url: Mapped[str]=mapped_column(String(2048))
    mode: Mapped[str]=mapped_column(String(20), default="fast")
    scope: Mapped[str]=mapped_column(String(30), default="page")
    status: Mapped[str]=mapped_column(String(24), default=ScanStatus.queued.value, index=True)
    max_pages: Mapped[int]=mapped_column(Integer, default=100)
    max_depth: Mapped[int]=mapped_column(Integer, default=3)
    include_patterns: Mapped[list]=mapped_column(JSON, default=list)
    exclude_patterns: Mapped[list]=mapped_column(JSON, default=list)
    pages_scanned: Mapped[int]=mapped_column(Integer, default=0)
    pages_queued: Mapped[int]=mapped_column(Integer, default=0)
    pages_skipped: Mapped[int]=mapped_column(Integer, default=0)
    errors: Mapped[int]=mapped_column(Integer, default=0)
    videos_found: Mapped[int]=mapped_column(Integer, default=0)
    current_url: Mapped[str|None]=mapped_column(String(2048))
    started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now, index=True)
    site: Mapped[Site]=relationship()
    videos: Mapped[list["DetectedVideo"]]=relationship(back_populates="scan", cascade="all, delete-orphan")

class CrawlPage(Base):
    __tablename__="crawl_pages"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    scan_id: Mapped[str]=mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str]=mapped_column(String(2048))
    status_code: Mapped[int|None]=mapped_column(Integer)
    depth: Mapped[int]=mapped_column(Integer, default=0)
    error: Mapped[str|None]=mapped_column(Text)
    processed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint("scan_id","url"),)

class DetectedVideo(Base):
    __tablename__="detected_videos"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    scan_id: Mapped[str]=mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[str]=mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str]=mapped_column(String(500))
    source_page: Mapped[str]=mapped_column(String(2048))
    media_url: Mapped[str]=mapped_column(String(4096))
    thumbnail_url: Mapped[str|None]=mapped_column(String(4096))
    duration_seconds: Mapped[float|None]=mapped_column(Float)
    width: Mapped[int|None]=mapped_column(Integer); height: Mapped[int|None]=mapped_column(Integer)
    format: Mapped[str|None]=mapped_column(String(30)); video_codec: Mapped[str|None]=mapped_column(String(80)); audio_codec: Mapped[str|None]=mapped_column(String(80))
    fps: Mapped[float|None]=mapped_column(Float); bitrate: Mapped[int|None]=mapped_column(BigInteger)
    size_bytes: Mapped[int|None]=mapped_column(BigInteger); size_estimated: Mapped[bool]=mapped_column(Boolean, default=False)
    detection_method: Mapped[str]=mapped_column(String(80)); fingerprint: Mapped[str]=mapped_column(String(64), index=True)
    drm_detected: Mapped[bool]=mapped_column(Boolean, default=False); download_supported: Mapped[bool]=mapped_column(Boolean, default=True)
    duplicate_of: Mapped[str|None]=mapped_column(String(36)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now, index=True)
    scan: Mapped[ScanJob]=relationship(back_populates="videos")
    variants: Mapped[list["VideoVariant"]]=relationship(cascade="all, delete-orphan")
    __table_args__=(UniqueConstraint("scan_id","fingerprint"), Index("ix_video_filters","height","size_bytes","duration_seconds"))

class VideoVariant(Base):
    __tablename__="video_variants"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str]=mapped_column(ForeignKey("detected_videos.id", ondelete="CASCADE"), index=True)
    label: Mapped[str]=mapped_column(String(80)); media_url: Mapped[str]=mapped_column(String(4096))
    width: Mapped[int|None]=mapped_column(Integer); height: Mapped[int|None]=mapped_column(Integer); size_bytes: Mapped[int|None]=mapped_column(BigInteger)

class Download(Base):
    __tablename__="downloads"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str]=mapped_column(ForeignKey("detected_videos.id"), index=True)
    status: Mapped[str]=mapped_column(String(30), default=DownloadStatus.queued.value, index=True)
    quality: Mapped[str]=mapped_column(String(50), default="best")
    progress: Mapped[float]=mapped_column(Float, default=0); bytes_downloaded: Mapped[int]=mapped_column(BigInteger, default=0); total_bytes: Mapped[int|None]=mapped_column(BigInteger)
    speed: Mapped[float|None]=mapped_column(Float); eta_seconds: Mapped[int|None]=mapped_column(Integer); destination: Mapped[str|None]=mapped_column(String(2048)); error: Mapped[str|None]=mapped_column(Text)
    retries: Mapped[int]=mapped_column(Integer, default=0); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now)
    video: Mapped[DetectedVideo]=relationship()

class DownloadAttempt(Base):
    __tablename__="download_attempts"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid); download_id: Mapped[str]=mapped_column(ForeignKey("downloads.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); error: Mapped[str|None]=mapped_column(Text)

class LibraryItem(Base):
    __tablename__="video_library"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid); video_id: Mapped[str]=mapped_column(ForeignKey("detected_videos.id"), unique=True); local_path: Mapped[str]=mapped_column(String(2048)); file_size: Mapped[int]=mapped_column(BigInteger); file_hash: Mapped[str]=mapped_column(String(64), unique=True); downloaded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now); video: Mapped[DetectedVideo]=relationship()

class VideoThumbnail(Base):
    __tablename__="video_thumbnails"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid); video_id: Mapped[str]=mapped_column(ForeignKey("detected_videos.id", ondelete="CASCADE"), index=True); kind: Mapped[str]=mapped_column(String(30), default="thumbnail"); path: Mapped[str]=mapped_column(String(2048))

class Schedule(Base):
    __tablename__="schedules"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid); site_id: Mapped[str]=mapped_column(ForeignKey("sites.id")); interval_hours: Mapped[int]=mapped_column(Integer, default=24); enabled: Mapped[bool]=mapped_column(Boolean, default=True); auto_download: Mapped[bool]=mapped_column(Boolean, default=False); next_run: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class Setting(Base):
    __tablename__="application_settings"
    key: Mapped[str]=mapped_column(String(120), primary_key=True); value: Mapped[dict]=mapped_column(JSON)

class AuditLog(Base):
    __tablename__="audit_logs"
    id: Mapped[str]=mapped_column(String(36), primary_key=True, default=uid); level: Mapped[str]=mapped_column(String(20), index=True); event: Mapped[str]=mapped_column(String(100), index=True); message: Mapped[str]=mapped_column(Text); context: Mapped[dict]=mapped_column(JSON, default=dict); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=now, index=True)
