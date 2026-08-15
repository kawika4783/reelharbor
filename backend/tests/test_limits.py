from app.schemas import ScanIn,DownloadIn,SettingsIn
from pydantic import ValidationError
import pytest
def test_crawl_limits():
    with pytest.raises(ValidationError):ScanIn(url='https://example.com',mode='fast',scope='page',max_pages=5001,max_depth=2)
def test_queue_limit():
    with pytest.raises(ValidationError):DownloadIn(video_ids=[str(x) for x in range(101)])
def test_storage_limit():
    with pytest.raises(ValidationError):SettingsIn(concurrent_downloads=2,max_storage_percent=99)
