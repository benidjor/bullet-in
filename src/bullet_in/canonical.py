import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid")

def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    if path == "/":
        path = ""
    kept = [(k, v) for k, v in parse_qsl(parts.query)
            if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)]
    query = urlencode(sorted(kept))
    return urlunsplit((parts.scheme, host, path, query, ""))

def content_hash(title: str, url: str) -> str:
    norm_title = " ".join(title.split())
    payload = f"{norm_title}|{canonical_url(url)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
