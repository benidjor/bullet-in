"""공홈 비공식 GraphQL API 어댑터 (spec: 2026-07-19-arsenal-official-api-recovery-design).

2026-07 사이트 개편으로 목록이 클라이언트 렌더링이라 정적 HTML 파싱이 불가하다.
프론트엔드가 쓰는 GraphQL 엔드포인트를 직접 호출한다 — 인증 불요 (라이브 실측).
'sign' 제목 필터 대신 taxonomy 판별: 방출 오피셜 ("joins Besiktas") 도 Transfer news
태그로 잡히고, 재계약은 Contract news + Men 한정으로 포함한다 (아카데미 차단).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import logging
import re
import httpx
from bullet_in.models import RawItem

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://afc-prd.graph.arsenal.com/graphql"
BASE_URL = "https://www.arsenal.com"
PAGE_SIZE = 50
SITEMAP_URL = "https://www.arsenal.com/sitemaps/articles/1/sitemap.xml"
WINDOW_HOURS = 48.0

# <loc>·<lastmod> 인접 쌍 — 실측 sitemap 구조 (2026-07-24). 구조가 바뀌면 후보 0 알림으로 드러난다.
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
_GLIDE_RE = re.compile(r"-([A-Za-z0-9]{10,})$")

def _sitemap_candidates(xml: str, now: datetime, window_hours: float) -> list[str]:
    """sitemap XML → 창 안 /news/ URL 목록 (등장 순서 = 최신순 유지)."""
    cutoff = now - timedelta(hours=window_hours)
    out: list[str] = []
    for url, lastmod in _LOC_RE.findall(xml):
        if "/news/" not in url:
            continue
        try:
            lm = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
        except ValueError:
            continue
        if lm >= cutoff:
            out.append(url)
    return out

def _glide_id(url: str) -> str | None:
    """기사 URL 끝 토큰 = glideId (Tzolis 실증). 미검출 None."""
    m = _GLIDE_RE.search(url)
    return m.group(1) if m else None

# 프론트엔드 번들에서 추출한 쿼리 — 필드 드리프트 시 validation 에러로 fetch 가 실패한다
# (구 셀렉터의 조용한 0건과 달리 에러로 드러남).
LIST_QUERY = """query GetArticlesByTaxonomy($taxonomy: String = "", $pageNumber: Float = 1, $pageSize: Float = 50, $sortField: String = "", $sort: String = "", $articleTypes: String = "", $excludedArticles: [Float!]! = []) {
  getArticlesByTaxonomy(taxonomy: $taxonomy, pageNumber: $pageNumber, pageSize: $pageSize, articleTypes: $articleTypes, excludedArticles: $excludedArticles, sortField: $sortField, sort: $sort) {
    total
    articles { articleId glideId title path publicationDate taxonomies articleType }
  }
}"""
ARTICLE_QUERY = """query GetArticle($articleId: String = "", $glideId: String = "", $glidePath: String = "") {
  getArticle(articleId: $articleId, glideId: $glideId, glidePath: $glidePath) {
    articleBody
  }
}"""

REQUIRED_TAXONOMY = "Men"
ANY_TAXONOMIES = {"Transfer news", "Contract news"}

def _accept(article: dict) -> bool:
    tax = set(article.get("taxonomies") or [])
    return (article.get("articleType") == "News"
            and REQUIRED_TAXONOMY in tax
            and bool(ANY_TAXONOMIES & tax))

def _body_payload(blocks: list[dict]) -> dict:
    """articleBody 블록 배열 → body 텍스트 · 헤더 이미지 · 저자."""
    texts = [b["innerText"] for b in blocks
             if b.get("type") == "TEXT" and b.get("innerText")]
    header = next((b for b in blocks if b.get("type") == "HEADER"), {})
    return {"body": "\n\n".join(texts),
            "image_url": header.get("image"),
            "authors": [header["author"]] if header.get("author") else []}

class ArsenalApiAdapter:
    source_type = "api"

    def __init__(self, source_id: str, pages: int = 1):
        self.source_id = source_id
        self.pages = pages

    async def _gql(self, client: httpx.AsyncClient, operation: str,
                   query: str, variables: dict) -> dict:
        r = await client.post(GRAPHQL_URL, json={
            "operationName": operation, "query": query, "variables": variables})
        r.raise_for_status()
        return r.json()["data"]

    async def fetch(self) -> list[RawItem]:
        now = datetime.now(timezone.utc)
        out: list[RawItem] = []
        async with httpx.AsyncClient(timeout=20,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            matched: list[dict] = []
            for page in range(1, self.pages + 1):
                data = await self._gql(c, "GetArticlesByTaxonomy", LIST_QUERY, {
                    "taxonomy": "", "pageNumber": page, "pageSize": PAGE_SIZE,
                    "sortField": "publishedDate", "sort": "desc",
                    "articleTypes": "", "excludedArticles": []})
                listing = data.get("getArticlesByTaxonomy")
                if not listing:
                    log.warning("%s: 목록 응답 비어 있음 (page %d) — API 인자 드리프트 의심",
                                self.source_id, page)
                    break
                matched.extend(a for a in listing["articles"] if _accept(a))
            for a in matched:
                payload = {"title": a["title"], "published": a.get("publicationDate")}
                try:
                    art = (await self._gql(c, "GetArticle", ARTICLE_QUERY, {
                        "articleId": "", "glideId": a["glideId"], "glidePath": ""}
                        )).get("getArticle") or {}
                    payload.update(_body_payload(art.get("articleBody") or []))
                except httpx.HTTPError:
                    payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
                out.append(RawItem(source_id=self.source_id, source_type="api",
                                   url=BASE_URL + a["path"], fetched_at=now,
                                   raw_payload=payload))
        return out
