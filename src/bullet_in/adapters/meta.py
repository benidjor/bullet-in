from __future__ import annotations
import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dtparser

def extract_og_image(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None

def extract_og_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": "og:title"})
    if tag and tag.get("content"):
        return tag["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None

def extract_article_body(html: str, max_chars: int = 8000) -> str:
    """임의 도메인 기사 본문을 휴리스틱으로 추출: <article>/<main>/<body> 안의
    <p> 텍스트를 이어붙인다. 알 수 없는 도메인용 폴백 (등록 소스는 body_selector 사용).

    문단이 통째로 <a> 안에 들어 있으면 관련기사 · 프로모 카드로 보고 버린다.
    기사 본문은 문단 안에 링크를 두지 문단 자체를 링크로 감싸지 않는데, 관련기사
    블록은 카드 전체가 링크라 이 구조로 갈린다 (실측 4개 도메인 — 더 선 ·
    BBC · 데일리 메일 · 스탠더드). 남겨 두면 다른 기사의 제목이 본문에 섞여
    들어가 그 기사에 없는 선수가 소제목으로 붙는다."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "aside", "footer", "header",
                   "figure", "figcaption"]):
        t.decompose()
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return ""
    paras = [p.get_text(" ", strip=True) for p in root.find_all("p")
             if not p.find_parent("a")]
    text = "\n\n".join(p for p in paras if p)
    return text[:max_chars]


_AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "taboola.com",
             "outbrain.com", "adsystem", "scorecardresearch.com")
_RELATED_CLASS = re.compile(r"related", re.I)

def _img_url(img, base_url: str | None) -> str | None:
    """<img>의 실제 URL — lazy-load(data-src) · srcset(최대 해상도) 해석, 상대 URL 절대화."""
    src = (img.get("src") or "").strip()
    if not src or src.startswith("data:"):
        src = (img.get("data-src") or "").strip()
    if not src and img.get("srcset"):
        cands = [c.strip().split()[0] for c in img["srcset"].split(",") if c.strip()]
        src = cands[-1] if cands else ""
    if not src or src.startswith("data:"):
        return None
    return urljoin(base_url, src) if base_url else src

def _too_small(img) -> bool:
    """width/height 속성이 있고 한 변이 120px 미만이면 아이콘·트래커로 간주."""
    for attr in ("width", "height"):
        v = str(img.get(attr) or "").rstrip("px")
        if v.isdigit() and int(v) < 120:
            return True
    return False

def extract_body_images(html: str, container_selector: str | None = None,
                        base_url: str | None = None, limit: int = 10) -> list[str]:
    """본문 컨테이너 안의 <img> URL을 원문 등장 순서로 수집한다.
    광고 도메인·aside/관련기사 블록·초소형·data:/svg 는 제외.
    이미지는 부가 정보 — 어떤 실패도 빈 목록으로 폴백해 수집을 막지 않는다."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        root = (soup.select_one(container_selector) if container_selector
                else soup.find("article") or soup.find("main") or soup.body or soup)
        if root is None:
            return []
        out: list[str] = []
        for img in root.find_all("img"):
            if img.find_parent("aside") or img.find_parent(class_=_RELATED_CLASS):
                continue
            if _too_small(img):
                continue
            url = _img_url(img, base_url)
            if not url or not url.lower().startswith(("http://", "https://")):
                continue
            p = urlparse(url)
            host = (p.hostname or "").lower()
            if any(h in host for h in _AD_HOSTS) or p.path.lower().endswith(".svg"):
                continue
            if url not in out:
                out.append(url)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def _walk_authors(node) -> list[str]:
    """JSON-LD 트리를 재귀 탐색해 author 값을 등장 순서로 수집한다."""
    found: list[str] = []
    if isinstance(node, dict):
        if "author" in node:
            a = node["author"]
            for it in (a if isinstance(a, list) else [a]):
                if isinstance(it, dict):
                    name = it.get("name")
                    if isinstance(name, str):
                        found.append(name)
                elif isinstance(it, str):
                    found.append(it)
        for v in node.values():
            found += _walk_authors(v)
    elif isinstance(node, list):
        for v in node:
            found += _walk_authors(v)
    return found

_AUTHOR_SPLIT_RE = re.compile(r"\s*[,&]\s*|\s+and\s+")

def _normalize_authors(names: list[str]) -> list[str]:
    """저자 목록을 정규화: 빈 문자열 · URL 형태 배제 · 중복 제거 · 순서 보존.
    HTML 엔티티를 풀고, 결합 저자 (쉼표 · & · and 구분) 를 개별 저자로 분리한다."""
    out: list[str] = []
    for n in names:
        n = (n or "").strip()
        # HTML 엔티티 (&amp; · &#39; 등) 을 풀기
        n = _html.unescape(n)
        # Sky Sports: 영어 나열 관례 'A, B & C' · 'A and B' 로 공저 결합.
        # and 는 앞뒤 공백을 요구한다 — 낱말 안의 and (Alexander) 를 자르지 않기 위함.
        for part in _AUTHOR_SPLIT_RE.split(n):
            part = part.strip()
            # URL 형태 (article:author 의 SNS 링크 등) 는 저자명이 아니다
            if not part or part.lower().startswith(("http://", "https://")):
                continue
            if part not in out:
                out.append(part)
    return out

def split_authors(value: str) -> list[str]:
    """결합 저자 문자열 하나를 개별 저자로 쪼갠다.
    저장된 합성 journalist ('잭 로서, 사이먼 콜링스') 를 소급할 때도 쓴다."""
    return _normalize_authors([value])

def extract_authors(html: str) -> list[str]:
    """기사 저자명을 JSON-LD → meta[name=author] 순으로 추출한다.
    라이브 실측 (2026-07-16) 상 html 5소스 모두 JSON-LD 로 저자를 노출한다.
    기자는 부가 정보 — 어떤 실패도 빈 목록으로 폴백해 수집을 막지 않는다."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        names: list[str] = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
            except json.JSONDecodeError:
                # Sky Sports 실측: JSON-LD 문자열 안에 raw 제어 문자 → strict 모드 거부
                # strict=False 로 재시도 (제어 문자 허용)
                try:
                    data = json.loads(s.string or "", strict=False)
                except (json.JSONDecodeError, TypeError):
                    continue      # 그것마저 실패하면 이 블록을 버린다
            except TypeError:
                continue          # 깨진 LD 하나가 나머지를 막지 않는다
            names += _walk_authors(data)
        out = _normalize_authors(names)
        # JSON-LD 에서 유효 저자를 찾지 못했다면 meta[name=author] 폴백
        if not out:
            tag = soup.find("meta", attrs={"name": "author"})
            if tag and tag.get("content"):
                out = _normalize_authors([tag["content"]])
        return out
    except Exception:
        return []


def _walk_published(node) -> list[str]:
    """JSON-LD 트리를 재귀 탐색해 datePublished 값을 등장 순서로 수집한다."""
    found: list[str] = []
    if isinstance(node, dict):
        v = node.get("datePublished")
        if isinstance(v, str):
            found.append(v)
        for val in node.values():
            found += _walk_published(val)
    elif isinstance(node, list):
        for val in node:
            found += _walk_published(val)
    return found

_TIME_COMPONENT_RE = re.compile(r"[T ]\d{1,2}:|T\d{4}")

def _parse_published(raw: str) -> tuple[datetime, str] | None:
    """날짜 문자열 → (UTC datetime, precision). 시각 성분 없으면 'day' · naive 는 UTC 간주."""
    try:
        dt = dtparser.parse(raw)
    except (ValueError, OverflowError, TypeError):
        return None
    precision = "time" if _TIME_COMPONENT_RE.search(raw.strip()) else "day"
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt, precision

def extract_published_at(html: str) -> tuple[datetime, str] | None:
    """기사 발행 시각 — JSON-LD datePublished → meta article:published_time → <time datetime>.
    발행 시각은 부가 정보 — 어떤 실패도 None 폴백으로 수집을 막지 않는다."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[str] = []
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
            except json.JSONDecodeError:
                try:
                    data = json.loads(s.string or "", strict=False)
                except (json.JSONDecodeError, TypeError):
                    continue
            except TypeError:
                continue
            candidates += _walk_published(data)
        if not candidates:
            tag = soup.find("meta", attrs={"property": "article:published_time"})
            if tag and tag.get("content"):
                candidates.append(tag["content"])
        if not candidates:
            t = soup.find("time", attrs={"datetime": True})
            if t:
                candidates.append(t["datetime"])
        for raw in candidates:
            parsed = _parse_published(raw)
            if parsed:
                return parsed
        return None
    except Exception:
        return None
