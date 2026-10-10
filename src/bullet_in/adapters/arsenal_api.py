"""공홈 비공식 GraphQL API 어댑터 (spec: 2026-07-19-arsenal-official-api-recovery-design).

2026-07 사이트 개편으로 목록이 클라이언트 렌더링이라 정적 HTML 파싱이 불가하다.
프론트엔드가 쓰는 GraphQL 엔드포인트를 직접 호출한다 — 인증 불요 (라이브 실측).
채택은 taxonomy 판별이 기본이다: 방출 오피셜 ("joins Besiktas") 도 Transfer news
태그로 잡히고, 재계약은 Contract news + Men 한정으로 포함한다 (아카데미 차단).
구단이 태그를 빠뜨리는 일이 있어 (2026-08-05 뇌르고르) 제목 어휘 갈래를 함께 둔다
— 두 경로의 구분은 단계 규칙이 쓴다 (스펙 2026-08-12 §3.2).
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import re
import time
import httpx
from bullet_in.models import RawItem
from bullet_in.quality import TRANSFER_TITLE_RE
from bullet_in.scope import ScopeRule, record

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://afc-prd.graph.arsenal.com/graphql"
SITEMAP_URL = "https://www.arsenal.com/sitemaps/articles/1/sitemap.xml"
WINDOW_HOURS = 48.0

# 사이트맵이 가끔 20초를 넘기거나 503 · 404 를 준다 (설계 2026-10-05 §1.3 · 627회 중 8회).
# 일시 장애만 한 번 더 묻는다 — 최악 소요 20 + 10 + 20 = 50초 (설계 §2.2).
# 바꾸면 _sitemap 의 경고 문구 「10초 뒤 재시도」 도 함께 바꾼다.
SITEMAP_RETRY_WAIT_SEC = 10.0


def _error_label(e: httpx.HTTPError) -> str:
    """기록 · 로그용 짧은 사유 — 상태 오류는 코드 (`503`), 전송 오류는 예외 이름 (`ReadTimeout`)."""
    if isinstance(e, httpx.HTTPStatusError):
        return str(e.response.status_code)
    return type(e).__name__


def _retryable(e: httpx.HTTPError) -> bool:
    """시간 초과 · 연결 오류와 5xx 만 다시 묻는다.

    4xx 는 주소가 바뀐 구조적 신호일 수 있어 재시도로 덮지 않는다 (설계 §2.1)."""
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code >= 500
    return isinstance(e, httpx.TransportError)

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

# 수집 범위 확대 (설계 2026-10-07 §3.2) — 1군 뉴스 중 이적 경로 밖의 선수 · 팀 소식.
# 제외는 사진 모음 · 영상 · 옛 경기 · 투표 · 다큐 · 선수 차 안 인터뷰 영상이고,
# 선수의 팬 질의응답 (AMA) 은 태그로 구별되지 않아 제목으로 거른다.
SCOPE_TAG = "Internationals"
EXCLUDE_TAGS = {"Compilation", "Photos", "Match gallery", "Video", "Full match",
                "From the vault", "Gamification", "Behind the Scenes", "3rd Party",
                "Colney Carpool"}
_EXCLUDE_TITLE_RE = re.compile(r"Ask Me Anything|\bAMA\b")

_TAG_RE = re.compile(r"<[^>]+>")

def _accept(article: dict, scope: ScopeRule | None = None) -> str | None:
    """채택 경로 — 'tag' (구단이 이적 태그를 붙임) · 'title' (제목 어휘) ·
    'scope' (선수 · 팀 소식) · None (비채택).

    구단이 이적 태그를 빠뜨린 발표가 실재해 (2026-08-05 뇌르고르) 제목 갈래를 둔다.
    두 경로를 구분해 두는 것은 단계 규칙이 태그 채택분에만 official 을 고정하기
    때문이다 (공홈 수집 개정 스펙 2026-08-12 §3.2 · §3.3).

    scope 는 규칙을 받았을 때만 본다 (설계 2026-10-07 §3.2) — 백필처럼 규칙 없이
    만든 어댑터는 종전 두 경로만 쓴다."""
    tax = set(article.get("taxonomies") or [])
    if article.get("articleType") != "News" or REQUIRED_TAXONOMY not in tax:
        return None
    if ANY_TAXONOMIES & tax:
        return "tag"
    title = article.get("title") or ""
    if TRANSFER_TITLE_RE.search(title):
        return "title"
    if scope is None or EXCLUDE_TAGS & tax or _EXCLUDE_TITLE_RE.search(title):
        return None
    if SCOPE_TAG in tax or scope.match(title):
        return "scope"
    return None

def _block_text(block: dict) -> str:
    """TEXT 블록의 본문 — innerText 가 비면 html 에서 태그를 벗겨 쓴다.

    링크 · 볼드가 든 문단은 innerText 가 비고 내용이 html 에만 있어, 첫 문단을
    볼드로 강조하는 구단 편집 관행 탓에 리드 문장이 매번 빠졌다 (스펙 §1.3)."""
    inner = (block.get("innerText") or "").strip()
    if inner:
        return inner
    return _TAG_RE.sub("", block.get("html") or "").strip()

def _body_payload(blocks: list[dict]) -> dict:
    """articleBody 블록 배열 → body 텍스트 · 헤더 이미지 · 저자."""
    texts = [t for b in blocks
             if b.get("type") == "TEXT" and (t := _block_text(b))]
    header = next((b for b in blocks if b.get("type") == "HEADER"), {})
    return {"body": "\n\n".join(texts),
            "image_url": header.get("image"),
            "authors": [header["author"]] if header.get("author") else []}

class ArsenalApiAdapter:
    source_type = "api"

    def __init__(self, source_id: str, window_hours: float = WINDOW_HOURS,
                 scope: ScopeRule | None = None):
        self.source_id = source_id
        self.window_hours = window_hours
        self.scope = scope   # 수집 범위 판정 (설계 2026-10-07 §3) — 없으면 종전 두 경로만
        self.coverage: dict = {}
        self.men_news_rejects: list[dict] = []   # 관측용 — Men + News 인데 비채택 (스펙 2026-08-07 §3.3)
        self.funnel: dict = {}   # 사이트맵 시도 기록 — run.adapter_funnels 가 실행 행에 남긴다 (설계 §3.1)

    async def _gql(self, client: httpx.AsyncClient, operation: str,
                   query: str, variables: dict) -> dict:
        r = await client.post(GRAPHQL_URL, json={
            "operationName": operation, "query": query, "variables": variables})
        r.raise_for_status()
        return r.json()["data"]

    async def _get_sitemap(self, client: httpx.AsyncClient) -> str:
        r = await client.get(SITEMAP_URL)
        r.raise_for_status()
        return r.text

    async def _sitemap(self, client: httpx.AsyncClient) -> str:
        """사이트맵 본문 — 일시 장애면 10초 뒤 한 번 더 묻는다.

        끝내 실패하면 예외를 그대로 낸다 (조용한 폴백 없음). 기록은 예외를 내기 전에
        채워 실패한 실행에도 남는다 (설계 §3.1)."""
        t0 = time.perf_counter()
        self.funnel = {"sitemap_attempts": 1}
        ok = False
        try:
            try:
                text = await self._get_sitemap(client)
                ok = True
                return text
            except httpx.HTTPError as e:
                self.funnel["sitemap_first_error"] = _error_label(e)
                if not _retryable(e):
                    raise
                # 문구는 리터럴이다 — 테스트가 대기를 0 으로 바꿔도 설계 §3.2 문구를 검사할 수 있게
                log.warning("%s: 사이트맵 1차 실패 (%s) — 10초 뒤 재시도", self.source_id,
                            self.funnel["sitemap_first_error"])
            await asyncio.sleep(SITEMAP_RETRY_WAIT_SEC)
            self.funnel["sitemap_attempts"] = 2
            text = await self._get_sitemap(client)
            ok = True
            return text
        finally:
            self.funnel["sitemap_sec"] = round(time.perf_counter() - t0, 1)
            log.info("%s: 사이트맵 %.1f초 · 시도 %d%s", self.source_id,
                     self.funnel["sitemap_sec"], self.funnel["sitemap_attempts"],
                     "" if ok else " · 실패")

    async def fetch(self) -> list[RawItem]:
        now = datetime.now(timezone.utc)
        out: list[RawItem] = []
        men = 0
        urls: list[str] = []
        self.men_news_rejects = []
        async with httpx.AsyncClient(timeout=20,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            # sitemap 장애 = 일시 장애면 한 번 더, 그래도 실패면 에러로 전파 (조용한 폴백 없음)
            urls = _sitemap_candidates(await self._sitemap(c), now, self.window_hours)
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
                accept_path = _accept(art, self.scope)
                tax = art.get("taxonomies") or []
                if art.get("articleType") == "News" and "Men" in tax:
                    # 1군 뉴스만 기록한다 — 받은 경로 수와 버린 제목 (설계 2026-10-07 §5.1)
                    record(self.funnel, art.get("title") or "", accept_path)
                if accept_path is None:
                    if art.get("articleType") == "News" and "Men" in tax:
                        self.men_news_rejects.append({
                            "title": art.get("title"), "url": url,
                            "published": art.get("publicationDate"),
                            "taxonomies": tax})
                    continue
                payload = {"title": art.get("title"),
                           "published": art.get("publicationDate"),
                           "published_precision": "time",
                           "accept_path": accept_path,
                           **_body_payload(art.get("articleBody") or [])}
                out.append(RawItem(source_id=self.source_id, source_type="api",
                                   url=url, fetched_at=now, raw_payload=payload))
        self.coverage = {"candidates": len(urls), "men_tagged": men,
                         "accepted": len(out)}
        log.info("%s: 창 후보 %d · Men %d · accept %d",
                 self.source_id, len(urls), men, len(out))
        return out
