from __future__ import annotations
from bs4 import BeautifulSoup

def extract_og_image(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
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
