import socket
import pytest
from app.detectors import detect_all
from app.security import validate_public_url
from app.utils import format_duration,format_size,sanitize_filename

def test_html_media_detection():
    items=detect_all('<html><head><title>Demo</title></head><body><video poster="p.jpg"><source src="/movie.mp4"></video></body></html>','https://example.com/page')
    assert any(x.media_url=='https://example.com/movie.mp4' and x.thumbnail_url=='https://example.com/p.jpg' for x in items)
def test_hls_detection_and_deduplication():
    items=detect_all('<video src="https://cdn.example.com/main.m3u8"></video><script>"https://cdn.example.com/main.m3u8"</script>','https://example.com')
    assert len([x for x in items if x.media_url.endswith('main.m3u8')])==1
def test_runtime_and_size_formatting():
    assert format_duration(5534)=='01:32:14';assert format_duration(None)=='Unknown';assert format_size(1024**3)=='1.0 GB';assert format_size(None)=='Unknown'
def test_filename_sanitization(): assert sanitize_filename('bad:name?.mp4')=='bad_name_.mp4'
def test_ssrf_blocks_localhost():
    with pytest.raises(ValueError):validate_public_url('http://127.0.0.1/video')
def test_url_rejects_credentials():
    with pytest.raises(ValueError):validate_public_url('https://user:pass@example.com')
def test_url_rejects_non_http():
    with pytest.raises(ValueError):validate_public_url('file:///etc/passwd')
