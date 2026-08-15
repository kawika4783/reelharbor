from pydantic import BaseModel, Field, HttpUrl

class SetupIn(BaseModel): username: str=Field(min_length=3,max_length=80); password: str=Field(min_length=10,max_length=128); download_folder: str="/data/videos"; max_storage_percent: int=Field(ge=20,le=98); concurrent_downloads: int=Field(ge=1,le=10)
class LoginIn(BaseModel): username: str; password: str
class ScanIn(BaseModel): url: HttpUrl; mode: str=Field(pattern="^(fast|browser)$"); scope: str=Field(pattern="^(page|pagination|directory|domain|pattern)$"); max_pages: int=Field(default=100,ge=1,le=1000); max_depth: int=Field(default=3,ge=0,le=10); include_patterns: list[str]=[]; exclude_patterns: list[str]=[]
class DownloadIn(BaseModel): video_ids: list[str]=Field(min_length=1,max_length=100); quality: str="best"; force: bool=False
class SettingsIn(BaseModel): concurrent_downloads: int=Field(ge=1,le=10); max_storage_percent: int=Field(ge=20,le=98); allow_private_networks: bool=False; filename_template: str=Field(default="/{domain}/{title}/{title}.{ext}",max_length=500)

