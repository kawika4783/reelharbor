import hashlib, json, re
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup

MEDIA_RE=re.compile(r"https?://[^\s'\"<>]+?\.(?:mp4|webm|mov|m3u8|mpd)(?:\?[^\s'\"<>]*)?",re.I)

@dataclass
class VideoCandidate:
    title: str; source_page: str; media_url: str; thumbnail_url: str|None=None; duration: float|None=None; width: int|None=None; height: int|None=None; format: str|None=None; codec: str|None=None; estimated_size: int|None=None; detection_method: str="html"; download_supported: bool=True; drm_detected: bool=False
    @property
    def fingerprint(self):
        p=urlsplit(self.media_url); canonical=urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,p.query,"")); return hashlib.sha256(canonical.encode()).hexdigest()
    def dict(self): return {**asdict(self),"fingerprint":self.fingerprint}

class Detector:
    name="base"
    def detect(self, html: str, page_url: str) -> list[VideoCandidate]: return []

class HtmlVideoDetector(Detector):
    name="html_video"
    def detect(self, html,page_url):
        soup=BeautifulSoup(html,"html.parser"); out=[]
        for node in soup.select("video, audio"):
            poster=urljoin(page_url,node.get("poster")) if node.get("poster") else None
            sources=([node.get("src")] if node.get("src") else [])+[x.get("src") for x in node.select("source[src]")]
            for src in filter(None,sources): out.append(VideoCandidate(node.get("title") or soup.title.string if soup.title else "Untitled video",page_url,urljoin(page_url,src),poster,detection_method=self.name))
        return out

class OpenGraphDetector(Detector):
    name="open_graph"
    def detect(self,html,page_url):
        soup=BeautifulSoup(html,"html.parser"); title=(soup.select_one('meta[property="og:title"]') or {}).get("content","Untitled video"); thumb=(soup.select_one('meta[property="og:image"]') or {}).get("content"); out=[]
        for node in soup.select('meta[property^="og:video"]'):
            if node.get("property") in {"og:video","og:video:url","og:video:secure_url"} and node.get("content"): out.append(VideoCandidate(title,page_url,urljoin(page_url,node["content"]),urljoin(page_url,thumb) if thumb else None,detection_method=self.name))
        return out

class JsonLdDetector(Detector):
    name="json_ld"
    def detect(self,html,page_url):
        soup=BeautifulSoup(html,"html.parser"); out=[]
        def walk(v):
            if isinstance(v,list):
                for x in v: walk(x)
            elif isinstance(v,dict):
                if v.get("@type") in {"VideoObject","MediaObject"}:
                    media=v.get("contentUrl") or v.get("embedUrl"); thumb=v.get("thumbnailUrl"); thumb=thumb[0] if isinstance(thumb,list) and thumb else thumb
                    if media: out.append(VideoCandidate(v.get("name","Untitled video"),page_url,urljoin(page_url,media),urljoin(page_url,thumb) if thumb else None,detection_method=self.name))
                for x in v.values(): walk(x)
        for node in soup.select('script[type="application/ld+json"]'):
            try: walk(json.loads(node.string or ""))
            except (json.JSONDecodeError,TypeError): pass
        return out

class ScriptMediaDetector(Detector):
    name="script_media"
    def detect(self,html,page_url): return [VideoCandidate("Discovered media",page_url,m.group(0),detection_method=self.name) for m in MEDIA_RE.finditer(html)]

class IframeDetector(Detector):
    name="iframe"
    def detect(self,html,page_url):
        soup=BeautifulSoup(html,"html.parser"); return [VideoCandidate(i.get("title","Embedded video"),page_url,urljoin(page_url,i["src"]),detection_method=self.name) for i in soup.select("iframe[src]") if any(x in i["src"].lower() for x in ("youtube","vimeo","player","video"))]

class ManifestDetector(Detector):
    name="manifest"
    def detect(self,html,page_url):
        out=[]
        for m in MEDIA_RE.finditer(html):
            url=m.group(0); fmt="HLS" if ".m3u8" in url.lower() else "DASH" if ".mpd" in url.lower() else None
            if fmt: out.append(VideoCandidate(f"{fmt} stream",page_url,url,format=fmt,detection_method=self.name))
        return out

REGISTRY=[HtmlVideoDetector(),OpenGraphDetector(),JsonLdDetector(),IframeDetector(),ManifestDetector(),ScriptMediaDetector()]

def detect_all(html: str,page_url: str):
    merged={}
    for detector in REGISTRY:
        for item in detector.detect(html,page_url):
            if item.fingerprint not in merged or (item.thumbnail_url and not merged[item.fingerprint].thumbnail_url): merged[item.fingerprint]=item
    return list(merged.values())

