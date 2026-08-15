from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ReelHarbor"
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite:///./reelharbor.db"
    redis_url: str = "redis://redis:6379/0"
    video_dir: Path = Path("/data/videos")
    thumbnail_dir: Path = Path("/data/thumbnails")
    public_url: str = "http://localhost:8080"
    allow_private_networks: bool = False
    demo_mode: bool = True
    max_pages: int = 1000
    max_file_size_gb: int = 50
    max_storage_percent: int = 90
    concurrent_downloads: int = 2
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

