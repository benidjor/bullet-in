from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import yaml
import httpx
from bullet_in.adapters.meta import extract_article_body, extract_og_title, extract_og_image

_NAME_RE = re.compile(r"[A-Z][A-Za-zÀ-ÿ''.\-]*(?:\s+[A-Z][A-Za-zÀ-ÿ''.\-]*)+")

_STOP = frozenset(
    "the a an and or to of in on for with set are is has have been will would "
    "from that this over amid could into out at as by".split())

def extract_entities(text: str) -> list[str]:
    """대문자로 시작하는 연속 단어 (2어 이상) = 인명 · 구단명 후보. 악센트 보존."""
    return _NAME_RE.findall(text or "")

def _sig_tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ''\-]+", text or "")
    return {w for w in words if len(w) > 3 and w.lower() not in _STOP}

def _parse_dt(s: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def match_original_tweet(af_text, af_dt, journ_tweets, window_min, overlap_min):
    """4단계 ①~③ : 기자 트윗 중 afcstuff 원본을 특정. 없으면 None."""
    af_sig = _sig_tokens(af_text)
    best, best_score, best_dt = None, -1, None
    for jt in journ_tweets:
        jdt = _parse_dt(jt.get("created_at"))
        if jdt is None or af_dt is None or jdt > af_dt:
            continue
        if (af_dt - jdt).total_seconds() > window_min * 60:
            continue
        score = len(af_sig & _sig_tokens(jt.get("text", "")))
        if score > best_score or (score == best_score and best_dt is not None and jdt > best_dt):
            best, best_score, best_dt = jt, score, jdt
    return best if best_score >= overlap_min else None

def load_backtrack_config(path: str) -> dict:
    """backtrack.yaml → 딕셔너리. 빈 파일이면 빈 딕셔너리."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _host(url: str) -> str:
    """URL hostname → www. 제거 후 소문자."""
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h

def outlet_for_domain(url: str, domains: dict[str, str]) -> str | None:
    """URL 도메인 → domains 딕셔너리 lookup. subdomain 포함, 없으면 None."""
    host = _host(url)
    for dom, name in domains.items():
        if host == dom or host.endswith("." + dom):
            return name
    return None

def is_paywalled(url: str) -> bool:
    """URL이 유료 아웃렛 (The Athletic · nytimes.com/athletic)이면 True."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path.lower()
    if host == "theathletic.com" or host.endswith(".theathletic.com"):
        return True
    return host.endswith("nytimes.com") and (path == "/athletic" or path.startswith("/athletic/"))

async def resolve_and_fetch(client: httpx.AsyncClient, url: str) -> tuple[str | None, str, str | None, str | None]:
    """t.co (또는 실 URL) → 최종 URL · 본문 · 제목 · 이미지. 실패 시 (None, '', None, None)."""
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None, "", None, None
    return str(r.url), extract_article_body(r.text), extract_og_title(r.text), extract_og_image(r.text)
