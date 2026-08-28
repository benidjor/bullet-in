import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "smid", "source",
                      "unlocked_article_code")

# 같은 기사가 주소만 갈려 두 행이 되던 자리 넷 (안건 ρ · 920행 전량 대조 · 과잉 병합 0).
_SKY_SECTION = re.compile(r"^(/football/(?:news|live-blog))/\d+/(\d+)(/.*)?$")
_ATHLETIC_SLUG = re.compile(r"^(/athletic/\d+/\d{4}/\d{2}/\d{2})/.*$")

def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.endswith("bbc.co.uk"):
        host = host.replace("bbc.co.uk", "bbc.com")
    path = parts.path.rstrip("/") or "/"
    if path == "/":
        path = ""
    m = _SKY_SECTION.match(path)
    if m and "skysports" in host:      # 섹션 번호는 같은 기사를 여러 갈래로 싣는다
        path = f"{m.group(1)}/{m.group(2)}"
    m = _ATHLETIC_SLUG.match(path)
    if m and "nytimes" in host:        # 슬러그는 오타까지 갈린다 (aston-vila ↔ aston-villa)
        path = m.group(1)
    kept = [(k, v) for k, v in parse_qsl(parts.query)
            if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)]
    query = urlencode(sorted(kept))
    return urlunsplit((parts.scheme, host, path, query, ""))

def content_hash(title: str, url: str) -> str:
    norm_title = " ".join(title.split())
    payload = f"{norm_title}|{canonical_url(url)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
