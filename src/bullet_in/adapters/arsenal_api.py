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
ARTICLE_QUERY = """query GetArticle($articleId: String = "", $glideId: String = "", $glidePath: String = "") {
  getArticle(articleId: $articleId, glideId: $glideId, glidePath: $glidePath) {
    title publicationDate taxonomies articleType articleBody
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

    def __init__(self, source_id: str, window_hours: float = WINDOW_HOURS):
        self.source_id = source_id
        self.window_hours = window_hours
        self.coverage: dict = {}

    async def _gql(self, client: httpx.AsyncClient, operation: str,
                   query: str, variables: dict) -> dict:
        r = await client.post(GRAPHQL_URL, json={
            "operationName": operation, "query": query, "variables": variables})
        r.raise_for_status()
        return r.json()["data"]

    async def fetch(self) -> list[RawItem]:
        now = datetime.now(timezone.utc)
        out: list[RawItem] = []
        men = 0
        urls: list[str] = []
        async with httpx.AsyncClient(timeout=20,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(SITEMAP_URL)
            r.raise_for_status()  # sitemap 장애 = 에러로 전파 (조용한 폴백 없음)
            urls = _sitemap_candidates(r.text, now, self.window_hours)
            for url in urls:
                gid = _glide_id(url)
                if gid is None:
                    log.warning("%s: glideId 추출 실패 — %s", self.source_id, url)
                    continue
                try:
                    art = (await self._gql(c, "GetArticle", ARTICLE_QUERY, {
                        "articleId": "", "glideId": gid, "glidePath": ""}
                        )).get("getArticle")
                except httpx.HTTPError as e:
                    log.warning("%s: GetArticle 실패 (%s) — %s", self.source_id, e, url)
                    continue
                if not art:
                    log.warning("%s: GetArticle 응답 없음 — %s", self.source_id, url)
                    continue
                if "Men" in (art.get("taxonomies") or []):
                    men += 1
                if not _accept(art):
                    continue
                payload = {"title": art.get("title"),
                           "published": art.get("publicationDate"),
                           "published_precision": "time",
                           **_body_payload(art.get("articleBody") or [])}
                out.append(RawItem(source_id=self.source_id, source_type="api",
                                   url=url, fetched_at=now, raw_payload=payload))
        self.coverage = {"candidates": len(urls), "men_tagged": men,
                         "accepted": len(out)}
        log.info("%s: 창 후보 %d · Men %d · accept %d",
                 self.source_id, len(urls), men, len(out))
        return out
