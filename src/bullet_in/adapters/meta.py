from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

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
    <p> 텍스트를 이어붙인다. 알 수 없는 도메인용 폴백 (등록 소스는 body_selector 사용)."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "aside", "footer", "header",
                   "figure", "figcaption"]):
        t.decompose()
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return ""
    paras = [p.get_text(" ", strip=True) for p in root.find_all("p")]
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
