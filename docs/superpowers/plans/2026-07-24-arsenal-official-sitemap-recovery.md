# arsenal_official sitemap 복구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동결된 GraphQL 리스트 대신 sitemap 으로 공홈 기사를 발견하고, 확장 GetArticle 로 수집하며, 커버리지 알림 · precision 라벨 · 6/1 재검증 백필을 붙인다.

**Architecture:** 발견 = `sitemaps/articles/1/sitemap.xml` 48h 창 (최신 기사가 맨 앞 — 실측), 메타 · 본문 = 확장 `GetArticle` 1콜 → 기존 `_accept` · `_body_payload` 재사용. 퍼널 (후보 · Men · accept) 을 어댑터가 집계해 run.py 가 불변식 위반 (후보 0 · Men 소멸) 시 Discord 알림.

**Tech Stack:** Python 3.11 · httpx · respx (테스트 모킹) · SQLAlchemy · 기존 notify/quality 모듈.

**Spec (SoT):** `docs/superpowers/specs/2026-07-24-arsenal-official-sitemap-recovery-design.md`

## Global Constraints

- 창 상수 `WINDOW_HOURS = 48` — config 미노출, 생성자 인자 `window_hours` 로만 조정 (spec §4.1).
- sitemap URL 은 상수 `https://www.arsenal.com/sitemaps/articles/1/sitemap.xml` — 인덱스 체인을 걷지 않는다 (spec §4.1).
- `_accept` 채택 조건 불변: `articleType == "News"` AND `"Men"` AND (`"Transfer news"` OR `"Contract news"`).
- getArticle null · HTTP 에러 · glideId 추출 실패 = 항목별 예외 격리 + WARNING (조용한 스킵 금지, spec §4.2).
- accept 0 은 알림 금지 — 알림은 후보 0 · Men 소멸 2축만 (spec §5).
- fmkorea · X 무접촉. 테스트는 `uv run pytest -q` (통합은 DB 없으면 skip).
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + `Co-Authored-By: Claude …` 트레일러.
- docs 산문은 §2.2 서식 (`→` `—` 줄 시작 · 한 줄 = 한 문장 · `·` 양옆 띄우기).

---

### Task 1: sitemap 후보 · glideId 순수 헬퍼

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py`
- Test: `tests/test_arsenal_api_adapter.py`

**Interfaces:**
- Produces: `_sitemap_candidates(xml: str, now: datetime, window_hours: float) -> list[str]` — `/news/` 경로 · `lastmod ≥ now − window` 인 URL 목록 (sitemap 등장 순서 유지). `_glide_id(url: str) -> str | None` — URL 끝 `-<토큰>` 추출. `SITEMAP_URL` · `WINDOW_HOURS` 상수.

- [ ] **Step 1: Write the failing tests**

`tests/test_arsenal_api_adapter.py` 에 추가:

```python
from datetime import datetime, timezone
from bullet_in.adapters.arsenal_api import _sitemap_candidates, _glide_id

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.arsenal.com/news/christos-tzolis-signs-for-arsenal-axDM85b0dBUW</loc><lastmod>2026-07-23T12:10:38.401Z</lastmod></url>
  <url><loc>https://www.arsenal.com/gallery/christos-tzolis.-in-arsenal-colours.-af95S4s4Avgu</loc><lastmod>2026-07-23T12:41:00.000Z</lastmod></url>
  <url><loc>https://www.arsenal.com/news/old-article-aOLD11111111</loc><lastmod>2026-07-01T09:00:00.000Z</lastmod></url>
  <url><loc>https://www.arsenal.com/news/broken-lastmod-aBRK22222222</loc><lastmod>not-a-date</lastmod></url>
</urlset>"""

def test_sitemap_candidates_window_and_news_filter():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    urls = _sitemap_candidates(SITEMAP_XML, now, 48)
    # /news/ 경로 + 48h 창 안 + lastmod 파싱 실패 제외 → Tzolis 1건
    assert urls == ["https://www.arsenal.com/news/"
                    "christos-tzolis-signs-for-arsenal-axDM85b0dBUW"]

def test_sitemap_candidates_wide_window_keeps_order():
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    urls = _sitemap_candidates(SITEMAP_XML, now, 24 * 60)
    assert [u.rsplit("-", 1)[1] for u in urls] == ["axDM85b0dBUW", "aOLD11111111"]

def test_glide_id_extraction():
    assert _glide_id("https://www.arsenal.com/news/"
                     "christos-tzolis-signs-for-arsenal-axDM85b0dBUW") == "axDM85b0dBUW"
    assert _glide_id("https://www.arsenal.com/news/no-token") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_arsenal_api_adapter.py -q -k "sitemap or glide"`
Expected: FAIL — `ImportError: cannot import name '_sitemap_candidates'`

- [ ] **Step 3: Implement the helpers**

`src/bullet_in/adapters/arsenal_api.py` 에 추가 (모듈 상단 import 에 `re` · `timedelta` 보충):

```python
import re
from datetime import datetime, timedelta, timezone

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_arsenal_api_adapter.py -q -k "sitemap or glide"`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/arsenal_api.py tests/test_arsenal_api_adapter.py
git commit -m "feat(collect): arsenal sitemap 후보 · glideId 순수 헬퍼"
```

---

### Task 2: fetch 개편 — sitemap 발견 + 확장 GetArticle + coverage

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py` (fetch 전면 개편 · 리스트 쿼리 삭제)
- Test: `tests/test_arsenal_api_adapter.py` (모킹 구조 개편)

**Interfaces:**
- Consumes: Task 1 의 `_sitemap_candidates` · `_glide_id` · `SITEMAP_URL` · `WINDOW_HOURS`.
- Produces: `ArsenalApiAdapter(source_id, window_hours: float = WINDOW_HOURS)` — `pages` 인자 제거. `fetch()` 후 `self.coverage = {"candidates": int, "men_tagged": int, "accepted": int}`. payload 에 `published_precision: "time"` 포함. `ARTICLE_QUERY` 는 `title publicationDate taxonomies articleType articleBody` 요청. `LIST_QUERY` · `GetArticlesByTaxonomy` 경로 삭제.

- [ ] **Step 1: Rewrite the test module's mocks and cases**

`tests/test_arsenal_api_adapter.py` 전면 개편 — 기존 목록 쿼리 모킹 (`_mock_graphql` 의 `GetArticlesByTaxonomy` 분기 · `test_pages_config_paginates` · `test_null_list_response_returns_empty` · `test_body_fetch_failure_keeps_title_only`) 을 제거하고 아래로 대체한다. Task 1 의 헬퍼 테스트 (`SITEMAP_XML` 포함) 는 유지.

```python
import asyncio, json
import httpx, respx
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter, GRAPHQL_URL, SITEMAP_URL

def _sitemap_entry(slug, lastmod="2026-07-23T12:10:38.401Z"):
    return (f"<url><loc>https://www.arsenal.com/news/{slug}</loc>"
            f"<lastmod>{lastmod}</lastmod></url>")

def _sitemap(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries) + "</urlset>")

def _gql_article(title, taxonomies, article_type="News",
                 published="2026-07-23T12:10:38.401Z", body_texts=("본문",)):
    blocks = [{"type": "HEADER", "image": "https://assets.arsenal.com/h.webp",
               "author": "Arsenal Media"}]
    blocks += [{"type": "TEXT", "innerText": t} for t in body_texts]
    return {"title": title, "publicationDate": published,
            "taxonomies": taxonomies, "articleType": article_type,
            "articleBody": blocks}

def _mock_backend(sitemap_xml, articles_by_gid, article_status=200):
    """sitemap GET + GetArticle POST 모킹. articles_by_gid: glideId → 응답 (None = data null)."""
    respx.get(SITEMAP_URL).mock(return_value=httpx.Response(200, text=sitemap_xml))
    def responder(request):
        gid = json.loads(request.content)["variables"]["glideId"]
        if article_status != 200:
            return httpx.Response(article_status)
        return httpx.Response(200, json={"data": {"getArticle":
                                                  articles_by_gid.get(gid)}})
    return respx.post(GRAPHQL_URL).mock(side_effect=responder)

FIXED_NOW_ENTRIES = [_sitemap_entry("christos-tzolis-signs-for-arsenal-axDM85b0dBUW")]

@respx.mock
def test_accept_maps_payload_with_time_precision():
    _mock_backend(_sitemap(FIXED_NOW_ENTRIES), {
        "axDM85b0dBUW": _gql_article(
            "Christos Tzolis signs for Arsenal",
            ["Men", "News", "Transfer news"],
            body_texts=("Tzolis has signed.", "Welcome."))})
    items = asyncio.run(ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert len(items) == 1
    p = items[0].raw_payload
    assert items[0].url.endswith("-axDM85b0dBUW")
    assert p["title"] == "Christos Tzolis signs for Arsenal"
    assert p["published"] == "2026-07-23T12:10:38.401Z"
    assert p["published_precision"] == "time"
    assert p["body"] == "Tzolis has signed.\n\nWelcome."
    assert p["image_url"] == "https://assets.arsenal.com/h.webp"
    assert p["authors"] == ["Arsenal Media"]

@respx.mock
def test_taxonomy_filter_rules_via_getarticle():
    entries = [_sitemap_entry(f"a-{g}") for g in
               ["aOK1ok1ok1ok", "aOK2ok2ok2ok", "aNO1no1no1no",
                "aNO2no2no2no", "aNO3no3no3no", "aNO4no4no4no"]]
    _mock_backend(_sitemap(entries), {
        "aOK1ok1ok1ok": _gql_article("Terms agreed", ["Transfer news", "Men", "News"]),
        "aOK2ok2ok2ok": _gql_article("Men renewal", ["Contract news", "Men", "News"]),
        "aNO1no1no1no": _gql_article("Academy pro", ["Contract news", "Academy", "News"]),
        "aNO2no2no2no": _gql_article("Women signing", ["Transfer news", "Women", "News"]),
        "aNO3no3no3no": _gql_article("Match report", ["Men", "News"]),
        "aNO4no4no4no": _gql_article("Transfer video", ["Transfer news", "Men", "Video"],
                                     article_type="Video")})
    adapter = ArsenalApiAdapter("arsenal_official", window_hours=24 * 365)
    items = asyncio.run(adapter.fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed", "Men renewal"]
    assert adapter.coverage == {"candidates": 6, "men_tagged": 5, "accepted": 2}

@respx.mock
def test_getarticle_null_is_isolated_and_others_survive(caplog):
    entries = [_sitemap_entry("good-aOK1ok1ok1ok"), _sitemap_entry("gone-aNO1no1no1no")]
    _mock_backend(_sitemap(entries), {
        "aOK1ok1ok1ok": _gql_article("Terms agreed", ["Transfer news", "Men", "News"])})
    with caplog.at_level("WARNING"):
        items = asyncio.run(
            ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert [i.raw_payload["title"] for i in items] == ["Terms agreed"]
    assert any("GetArticle 응답 없음" in r.message for r in caplog.records)

@respx.mock
def test_getarticle_http_error_is_isolated(caplog):
    _mock_backend(_sitemap(FIXED_NOW_ENTRIES), {}, article_status=500)
    with caplog.at_level("WARNING"):
        items = asyncio.run(
            ArsenalApiAdapter("arsenal_official", window_hours=24 * 365).fetch())
    assert items == []
    assert any("GetArticle 실패" in r.message for r in caplog.records)

@respx.mock
def test_sitemap_failure_propagates():
    respx.get(SITEMAP_URL).mock(return_value=httpx.Response(503))
    import pytest
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ArsenalApiAdapter("arsenal_official").fetch())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_arsenal_api_adapter.py -q`
Expected: FAIL — `ImportError: cannot import name 'GRAPHQL_URL'` 은 아님 (기존 존재), `SITEMAP_URL` 은 Task 1 에서 추가됨. 실패 지점 = `window_hours` 인자 미지원 · sitemap 미사용 fetch.

- [ ] **Step 3: Rewrite the adapter**

`src/bullet_in/adapters/arsenal_api.py` — `LIST_QUERY` · `PAGE_SIZE` 삭제, `ARTICLE_QUERY` 교체, 클래스 개편:

```python
ARTICLE_QUERY = """query GetArticle($articleId: String = "", $glideId: String = "", $glidePath: String = "") {
  getArticle(articleId: $articleId, glideId: $glideId, glidePath: $glidePath) {
    title publicationDate taxonomies articleType articleBody
  }
}"""

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
```

주의: `urls` 는 `async with` 블록 안에서 정의되므로 coverage 집계를 블록 밖에 두려면 초기화 (`urls: list[str] = []`) 를 fetch 시작부에 둘 것. sitemap 실패 시 예외 전파로 coverage 는 갱신되지 않는다 (fetch 에러 = gather_all 이 errors 로 집계).

- [ ] **Step 4: Run the full adapter test module**

Run: `uv run pytest tests/test_arsenal_api_adapter.py -q`
Expected: 8 passed (헬퍼 3 + fetch 5)

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/arsenal_api.py tests/test_arsenal_api_adapter.py
git commit -m "feat(collect): arsenal 발견 경로를 sitemap + 확장 GetArticle 로 전환"
```

---

### Task 3: quality.evaluate_coverage + notify.build_coverage_alert

**Files:**
- Modify: `src/bullet_in/quality.py` · `src/bullet_in/notify.py`
- Test: `tests/test_quality.py` · `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 2 의 `coverage` dict 형태 (`candidates` · `men_tagged` · `accepted`).
- Produces: `evaluate_coverage(coverage: dict) -> list[str]` — 위반 종류 `"no_candidates"` · `"no_men_tag"` (후보 0 이면 Men 판정 생략 = 중복 알림 방지, 빈 dict 는 빈 목록). `build_coverage_alert(breaches: list[str], coverage: dict, *, run_id: str) -> dict` — `send_alert(**…)` 로 펼칠 embed kwargs.

- [ ] **Step 1: Write the failing tests**

`tests/test_quality.py` 에 추가:

```python
from bullet_in.quality import evaluate_coverage

def test_evaluate_coverage_no_candidates():
    assert evaluate_coverage({"candidates": 0, "men_tagged": 0,
                              "accepted": 0}) == ["no_candidates"]

def test_evaluate_coverage_men_vanished():
    assert evaluate_coverage({"candidates": 12, "men_tagged": 0,
                              "accepted": 0}) == ["no_men_tag"]

def test_evaluate_coverage_quiet_window_is_normal():
    # accept 0 은 비수기 정상 — 알림 축이 아니다 (spec §5)
    assert evaluate_coverage({"candidates": 12, "men_tagged": 5,
                              "accepted": 0}) == []

def test_evaluate_coverage_empty_dict_is_normal():
    assert evaluate_coverage({}) == []
```

`tests/test_notify.py` 에 추가:

```python
from bullet_in.notify import build_coverage_alert, COLOR_ANOMALY

def test_build_coverage_alert_embed_shape():
    kwargs = build_coverage_alert(
        ["no_men_tag"], {"candidates": 12, "men_tagged": 0, "accepted": 0},
        run_id="abcdef12-0000")
    assert kwargs["color"] == COLOR_ANOMALY
    assert "arsenal_official" in kwargs["title"]
    names = [f["name"] for f in kwargs["fields"]]
    assert "Men 태그 소멸" in names
    funnel = next(f for f in kwargs["fields"] if f["name"] == "퍼널")
    assert funnel["value"] == "후보 12 · Men 0 · accept 0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quality.py tests/test_notify.py -q -k coverage`
Expected: FAIL — `ImportError: cannot import name 'evaluate_coverage'`

- [ ] **Step 3: Implement**

`src/bullet_in/quality.py` 에 추가:

```python
def evaluate_coverage(coverage: dict) -> list[str]:
    """공홈 퍼널 불변식 위반 목록 — 후보 0 = 발견 경로 장애 · Men 소멸 = taxonomy 드리프트.
    accept 0 은 비수기 정상이라 판정하지 않는다 (spec 2026-07-24 §5)."""
    if not coverage:
        return []
    if coverage.get("candidates", 0) == 0:
        return ["no_candidates"]
    if coverage.get("men_tagged", 0) == 0:
        return ["no_men_tag"]
    return []
```

`src/bullet_in/notify.py` 에 추가:

```python
COVERAGE_BREACH_FIELDS = {
    "no_candidates": ("창 후보 0", "sitemap 경로 변경 · 발견 경로 장애 의심"),
    "no_men_tag": ("Men 태그 소멸", "taxonomy 어휘 변경 — 필터 기아 재발 위험"),
}

def build_coverage_alert(breaches: list[str], coverage: dict, *, run_id: str) -> dict:
    fields = []
    for b in breaches:
        name, hint = COVERAGE_BREACH_FIELDS[b]
        fields.append({"name": name, "value": f"- 원인 후보: {hint}", "inline": False})
    fields.append({"name": "퍼널",
                   "value": (f"후보 {coverage.get('candidates', 0)} · "
                             f"Men {coverage.get('men_tagged', 0)} · "
                             f"accept {coverage.get('accepted', 0)}"),
                   "inline": True})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": "🏟️ 공홈 커버리지 경고 — arsenal_official",
            "description": "수집 창 퍼널 불변식 위반 — 조용한 기아 신호",
            "color": COLOR_ANOMALY, "fields": fields}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quality.py tests/test_notify.py -q`
Expected: 전부 passed (기존 + 신규 5)

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/quality.py src/bullet_in/notify.py tests/test_quality.py tests/test_notify.py
git commit -m "feat(quality): 공홈 커버리지 퍼널 불변식 판정 · 알림 빌더"
```

---

### Task 4: run.py 알림 배선 + factory · config `pages` 제거

**Files:**
- Modify: `src/bullet_in/run.py` · `src/bullet_in/adapters/factory.py` · `config/sources.yaml`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: Task 2 `adapter.coverage` · Task 3 `evaluate_coverage` · `build_coverage_alert`.
- Produces: 회차마다 coverage 위반 시 Discord 알림. factory 는 `ArsenalApiAdapter(sid)` 만 생성.

- [ ] **Step 1: Update the factory test (failing first)**

`tests/test_adapter_factory.py` 의 `test_factory_builds_arsenal_api_with_pages` 를 교체:

```python
def test_factory_builds_arsenal_api_default_window():
    from bullet_in.adapters.arsenal_api import ArsenalApiAdapter, WINDOW_HOURS
    cfg = {"sources": [{"source_id": "arsenal_official", "adapter": "arsenal_api",
                        "enabled": True, "config": {}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, ArsenalApiAdapter) and a.window_hours == WINDOW_HOURS
```

Run: `uv run pytest tests/test_adapter_factory.py -q`
Expected: FAIL — factory 가 `pages` 를 전달 (`TypeError` 또는 `a.window_hours` 부재)

- [ ] **Step 2: Update factory and config**

`src/bullet_in/adapters/factory.py`:

```python
        elif kind == "arsenal_api":
            out.append(ArsenalApiAdapter(sid))
```

`config/sources.yaml` arsenal 항목 — `config.pages` 줄 제거 · 주석 교체:

```yaml
    adapter: arsenal_api
    config: {}
      # 2026-07 리스트 피드 동결 → sitemap 발견 (48h 창) + GetArticle 전환 (spec 2026-07-24).
      # 필터는 어댑터 내 taxonomy 판별 (Transfer news · Contract news + Men)
```

주의: YAML 에서 `config: {}` 와 주석 배치가 어색하면 `config: {}` 한 줄 + 주석은 그 위로 올린다.

- [ ] **Step 3: Run factory tests**

Run: `uv run pytest tests/test_adapter_factory.py -q`
Expected: 전부 passed

- [ ] **Step 4: Wire the alert in run.py**

`src/bullet_in/run.py` — import 에 `evaluate_coverage` 추가 (기존 quality import 줄 확장):

```python
from bullet_in.quality import success_rate, volume_anomalies, evaluate_freshness, evaluate_coverage
```

SLO-6 블록 (`# 수집량 이상탐지 (SLO-6)`) 바로 앞에 추가:

```python
    # 공홈 커버리지 감시: 창 후보 · Men 퍼널 불변식 위반 시 알림 (spec 2026-07-24 §5)
    for a in adapters:
        breaches = evaluate_coverage(getattr(a, "coverage", {}) or {})
        if breaches:
            notify.send_alert(**notify.build_coverage_alert(
                breaches, a.coverage, run_id=run_id))
```

- [ ] **Step 5: Sanity check and full test run**

Run: `uv run python -m py_compile src/bullet_in/run.py && uv run pytest -q`
Expected: 컴파일 통과 · 전체 테스트 passed (통합 skip 허용)

- [ ] **Step 6: Commit**

```bash
git add src/bullet_in/run.py src/bullet_in/adapters/factory.py config/sources.yaml tests/test_adapter_factory.py
git commit -m "feat(run): 공홈 커버리지 알림 배선 · pages 설정 제거"
```

---

### Task 5: 백필 모듈 — label (precision 5행) + reverify (6/1 재검증)

**Files:**
- Create: `src/bullet_in/backfill_arsenal.py`
- Test: 실행은 dry-run 기본 — 코드 검증은 `py_compile` + 라이브 dry-run (Task 7). 순수 로직은 기존 태스크에서 이미 테스트됨 (어댑터 창 · dedup · rule_stage).

**Interfaces:**
- Consumes: `ArsenalApiAdapter(source_id, window_hours=…)` (Task 2) · `RawStore` · `MartStore` · `to_articles` · `transfer_stage.rule_stage` (기존).
- Produces: `python -m bullet_in.backfill_arsenal --phase label|reverify [--apply]` CLI.

- [ ] **Step 1: Write the module**

`src/bullet_in/backfill_arsenal.py` (backfill_journalist 선례 구조):

```python
"""arsenal_official 커버리지 백필 (1회성 · spec 2026-07-24 §6 §7).

label — 기존 행의 published_precision NULL 을 'time' 으로 라벨
  (대상 5행 전부 raw 에 발행 시각 실재 — 2026-07-24 감사 확인).
reverify — sitemap 기준으로 2026-06-01 이후 공홈 뉴스를 재검증해
  놓친 오피셜을 표준 경로 (RawStore → to_articles → upsert → rule_stage) 로 적재.

실행 전 `set -a; source .env; set +a` 필수 (dotenv 미사용).
VM 반영 절차 (타이머 창 · 스냅샷) 는 docs/runbook/2026-07-24-vm-live-reprocess-deploy.md.
    uv run python -m bullet_in.backfill_arsenal --phase label            # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase label --apply
    uv run python -m bullet_in.backfill_arsenal --phase reverify         # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase reverify --apply
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from bullet_in import transfer_stage
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
from bullet_in.canonical import canonical_url
from bullet_in.dedup import content_hash
from bullet_in.credibility import load_registry
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.mongo import RawStore

log = logging.getLogger(__name__)

REVERIFY_SINCE = datetime(2026, 6, 1, tzinfo=timezone.utc)

_LABEL_SELECT = text(
    "SELECT content_hash, title_original, published_at FROM articles "
    "WHERE source_id='arsenal_official' AND published_precision IS NULL")
_LABEL_UPDATE = text(
    "UPDATE articles SET published_precision='time' "
    "WHERE source_id='arsenal_official' AND published_precision IS NULL")

def phase_label(apply: bool) -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = c.execute(_LABEL_SELECT).mappings().all()
    for r in rows:
        log.info("label 대상: %s %s %s",
                 r["content_hash"][:9], r["published_at"], r["title_original"][:50])
    if not apply:
        log.info("dry-run — 대상 %d행 (적용하려면 --apply)", len(rows))
        return
    with engine.begin() as c:
        res = c.execute(_LABEL_UPDATE)
    log.info("label 적용 — %d행 갱신", res.rowcount)

def phase_reverify(apply: bool) -> None:
    hours = (datetime.now(timezone.utc) - REVERIFY_SINCE).total_seconds() / 3600
    adapter = ArsenalApiAdapter("arsenal_official", window_hours=hours)
    raw = asyncio.run(adapter.fetch())
    log.info("재검증 퍼널: %s", adapter.coverage)
    for it in raw:
        it.content_hash = content_hash(it.raw_payload.get("title") or "",
                                       canonical_url(it.url))
        log.info("accept: %s %s", it.raw_payload.get("published"),
                 it.raw_payload.get("title"))
    if not apply:
        log.info("dry-run — accept %d건 (적용하려면 --apply)", len(raw))
        return
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)
    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    mart.upsert(arts)
    ruled = transfer_stage.rule_stage("arsenal_official")
    for r in mart.rows_missing_stage():
        if r["source_id"] == "arsenal_official" and ruled:
            mart.set_stage(r["content_hash"], ruled)
    log.info("적재 — 신규 %d · 중복 %d (번역은 정규 회차가 흡수)",
             len(arts), stats["dup_count"])

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["label", "reverify"], required=True)
    ap.add_argument("--apply", action="store_true", help="미지정 시 dry-run")
    args = ap.parse_args()
    (phase_label if args.phase == "label" else phase_reverify)(args.apply)

if __name__ == "__main__":
    main()
```

주의: `rows_missing_stage` · `seen_map` · `RawStore.insert_many` 시그니처는 run.py (44~104행) 사용례와 동일해야 한다 — 구현 전 확인.

- [ ] **Step 2: Compile check**

Run: `uv run python -m py_compile src/bullet_in/backfill_arsenal.py && uv run python -m bullet_in.backfill_arsenal --help`
Expected: 컴파일 통과 · usage 출력 (`--phase {label,reverify}`)

- [ ] **Step 3: Commit**

```bash
git add src/bullet_in/backfill_arsenal.py
git commit -m "feat(backfill): arsenal precision 라벨 · 6/1 sitemap 재검증 모듈"
```

---

### Task 6: 트러블슈팅 정정 — 피드 동결 원인 추가

**Files:**
- Modify: `docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md`

**Interfaces:** 없음 (문서).

- [ ] **Step 1: Append the correction section**

"## 해결 방향" 절 앞에 추가 (§2.2 서식 준수 — `→` `—` 줄 시작 · 한 줄 = 한 문장):

```markdown
## 정정 — 원인 추가 (2026-07-24 커버리지 감사)

- 위 "원인" 은 창 도배 하나로 서술했으나, 감사 라이브 실측으로 **리스트 피드 동결**이 추가 확인됐다.
피드 최신 항목이 07-22 14:01 UTC 에서 멈췄고 (31시간+ 지속), `sortField` 변경도 무효였다.
- `total` 은 46,895 → 46,896 으로 증가
→ 인덱스는 새 기사를 아는데 리스트가 내주지 않는 상태.
- 공홈 프론트엔드 (`/news`) 도 같은 `GetArticlesByTaxonomy` 를 사용
→ 공홈 자체 뉴스 목록도 동일하게 동결돼 있었고, 수리 시점을 외부에서 예측할 수 없다.
- 해결은 발견 경로를 sitemap 으로 교체하는 것으로 확정
— spec `docs/superpowers/specs/2026-07-24-arsenal-official-sitemap-recovery-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md
git commit -m "docs(troubleshooting): arsenal 기아 원인에 리스트 피드 동결 추가"
```

---

### Task 7: 라이브 검증 (머지 게이트) + 전체 테스트

**Files:** 없음 (검증 전용).

**Interfaces:** Consumes: Task 2 어댑터 · Task 5 모듈.

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: 전부 passed (통합은 DB · Airflow 없으면 skip — 기존과 동일)

- [ ] **Step 2: Live 단독 fetch — Tzolis 실수집 (셀렉터 드리프트 관례 · 머지 전 필수)**

```bash
set -a; source .env; set +a
uv run python -c "
import asyncio
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
a = ArsenalApiAdapter('arsenal_official', window_hours=168)
items = asyncio.run(a.fetch())
print('coverage:', a.coverage)
for i in items: print(i.raw_payload['published'], i.url)
"
```

Expected: `coverage` 의 candidates 수십 건 · accept ≥ 1 · Tzolis URL (`christos-tzolis-signs-for-arsenal-axDM85b0dBUW`) 출현 · published = `2026-07-23T12:10:…` · 로그에 `창 후보 N · Men K · accept M` 한 줄.

- [ ] **Step 3: Live reverify dry-run (로컬 — 적재 없음)**

```bash
uv run python -m bullet_in.backfill_arsenal --phase reverify
```

Expected: 퍼널 로그 (후보 약 351+) · accept 목록에 기존 5건 + Tzolis (총 6건 안팎) · "dry-run — accept N건" 마무리. 신규 놓침이 더 있으면 여기서 드러난다.

- [ ] **Step 4: Commit any doc fixes and report**

라이브 결과가 기대와 다르면 (accept 목록에 예상 밖 기사 · 셀렉터 이상) 멈추고 사용자에게 보고한다.

---

## 라이브 반영 절차 (머지 후 · VM — 계획 밖 참고)

- 순서: PR 머지 (사용자) → VM `git pull` → 타이머 창 확인 · 스냅샷 → `--phase label --apply` → `--phase reverify --apply` → 재생성 · 배포 → 타이머 재가동.
- 절차 SoT: `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md`.
- 번역 (title_ko NULL) 은 다음 정규 회차가 멱등 흡수.
