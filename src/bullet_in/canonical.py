import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "smid", "source",
                      "unlocked_article_code")

# 같은 기사가 주소만 갈려 두 행이 되던 자리 (안건 ρ · 920행 전량 대조 · 과잉 병합 0).
#
# 스카이 섹션 번호 제거는 2026-08-29 에 걷어냈다 (안건 2ζ).
# 이 컬럼은 중복 판정 키이면서 화면의 「원문 기사 보기」 주소인데, 섹션 번호를 지운
# 주소는 기사에 못 가고 축구 섹션 첫 화면으로 떨어진다 (실측 8건 전부).
# 규칙이 들어간 뒤 적재된 스카이 행은 예외 없이 죽은 링크였고, 반대로 규칙이 막아 준
# 실물은 없었다 — 기사 번호 48종 중 겹친 3묶음이 둘은 「섹션 있음 ↔ 없음」 이고
# 나머지 하나는 postid 가 달라 규칙이 있어도 안 겹쳤다.
# 정본 = docs/troubleshooting/2026-08-29-the-rule-moved-but-the-stored-addresses-did-not.md
_ATHLETIC_SLUG = re.compile(r"^(/athletic/\d+/\d{4}/\d{2}/\d{2})/.*$")

def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.endswith("bbc.co.uk"):
        host = host.replace("bbc.co.uk", "bbc.com")
    path = parts.path.rstrip("/") or "/"
    if path == "/":
        path = ""
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
