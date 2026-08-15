import hashlib, hmac, ipaddress, secrets, socket
from urllib.parse import urlsplit, urlunsplit
from fastapi import HTTPException, Request
from passlib.context import CryptContext
from .config import settings

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
BLOCKED_HOSTS={"localhost","localhost.localdomain","metadata.google.internal","169.254.169.254"}

def hash_password(value: str) -> str: return pwd.hash(value)
def verify_password(value: str, hashed: str) -> bool: return pwd.verify(value, hashed)

def validate_public_url(raw: str) -> str:
    try: parts=urlsplit(raw.strip())
    except ValueError as exc: raise ValueError("Invalid URL") from exc
    if parts.scheme not in {"http","https"}: raise ValueError("Only HTTP and HTTPS URLs are allowed")
    if not parts.hostname or parts.username or parts.password: raise ValueError("URL credentials are not allowed")
    host=parts.hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTS: raise ValueError("This host is blocked")
    try: addresses={item[4][0] for item in socket.getaddrinfo(host, parts.port or (443 if parts.scheme=="https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc: raise ValueError("Host could not be resolved") from exc
    if not settings.allow_private_networks:
        for value in addresses:
            ip=ipaddress.ip_address(value)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise ValueError("Private and special-use network addresses are blocked")
    netloc=host + ((":"+str(parts.port)) if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))

def make_session(user_id: str) -> str:
    nonce=secrets.token_urlsafe(16); body=f"{user_id}.{nonce}"; sig=hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest(); return f"{body}.{sig}"

def session_user(token: str|None) -> str|None:
    if not token: return None
    try: user, nonce, sig=token.split(".",2); body=f"{user}.{nonce}"; expected=hmac.new(settings.secret_key.encode(),body.encode(),hashlib.sha256).hexdigest(); return user if hmac.compare_digest(sig,expected) else None
    except ValueError: return None

def csrf_token(session: str) -> str: return hmac.new(settings.secret_key.encode(), ("csrf:"+session).encode(), hashlib.sha256).hexdigest()

def require_user(request: Request) -> str:
    user=session_user(request.cookies.get("rh_session"))
    if not user: raise HTTPException(401,"Authentication required")
    return user

def require_csrf(request: Request):
    session=request.cookies.get("rh_session",""); supplied=request.headers.get("x-csrf-token","")
    if not session or not hmac.compare_digest(supplied, csrf_token(session)): raise HTTPException(403,"Invalid CSRF token")

