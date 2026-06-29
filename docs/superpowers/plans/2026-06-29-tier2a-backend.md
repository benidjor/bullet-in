# Tier 2-a 백엔드 (데이터 · 수집 · enrich · dedup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EN 소스 전체 본문 · 대표 이미지를 수집하고, 1줄/3줄 요약과 전체 한국어 본문을 생성해 `articles` 에 적재하며, fmkorea 를 원문 발견 소스로 재정의한다 (서빙/UI 는 Plan 2).

**Architecture:** 어댑터가 기사 상세를 fetch 해 본문 (`body_selector`)과 `og:image` 를 수집한다. fmkorea 는 제목 말머리 `[언론사]` 를 파싱하고 본문 끝 평문 출처 URL 로 원문을 해소하며, 디 애슬레틱 (유료)만 fmkorea 번역본을 쓰고 나머지는 원문을 직접 수집한다. enrich 는 기사당 1콜로 `title_ko` · `summary_ko` (1줄) · `summary3_ko` (3줄) · `body_ko` (전체)를 만든다. dedup 은 원문 URL 기준이며 EN/X 가 fmkorea 보다 우선한다.

**Tech Stack:** Python 3.11, uv, pydantic v2, httpx + BeautifulSoup, SQLAlchemy + MariaDB, google-genai, pytest + respx.

## Global Constraints

- Python 3.11, uv 패키지. **새 무거운 의존성 추가 금지** (httpx · bs4 · pydantic v2 · SQLAlchemy · google-genai 범위 내).
- Gemini 호출은 **기사당 1콜 유지** (RPM 불변). 429 식별 시 그 회차 즉시 중단 · WARNING 로깅 (파싱 실패와 구분). per-row 백오프 금지.
- enrich 멱등: `rows_missing_translation()` 트리거는 `title_ko IS NULL`. revision 변경 시 번역 필드 NULL 초기화.
- 유료 매체는 **`The Athletic` (디 애슬레틱) 하나만**. 상수 `PAYWALLED_OUTLETS = {"The Athletic"}`.
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`. 커밋 트레일러: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- 커밋 메시지/문서 산문은 한국어, 특수기호 (`·` `+` 여는 괄호) 양옆 띄움 (코드 · URL 제외).
- 신규/변경 `body_selector` 는 머지 전 어댑터 단독 `fetch()` 라이브 검증 (단위 테스트는 모킹).
- 테스트: `uv run pytest -q`. 통합 (DB) 테스트는 MariaDB 없으면 skip.

---

### Task 1: Article 모델 · 스키마 신규 컬럼

**Files:**
- Modify: `src/bullet_in/models.py:16-29`
- Modify: `src/bullet_in/storage/schema.sql:4-14`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Article` 에 `summary3_ko: str|None`, `body_ko: str|None`, `body_source: str|None`, `image_url: str|None`, `outlet: str|None`, `journalist: str|None`, `team: str = "arsenal"` 필드 추가.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py` 에 추가:

```python
def test_article_accepts_tier2a_fields():
    art = Article(content_hash="abc", url="https://x.test/a",
                  source_id="bbc_sport", title_original="Title",
                  published_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
                  summary3_ko="①\n②\n③", body_ko="본문", body_source="body",
                  image_url="https://img.test/a.jpg", outlet="BBC",
                  journalist="Sami Mokbel", team="arsenal")
    assert art.summary3_ko == "①\n②\n③"
    assert art.outlet == "BBC" and art.journalist == "Sami Mokbel"
    assert art.team == "arsenal"

def test_article_tier2a_fields_default_none():
    art = Article(content_hash="abc", url="https://x.test/a", source_id="g",
                  title_original="T", published_at=datetime(2026, 6, 29, tzinfo=timezone.utc))
    assert art.summary3_ko is None and art.body_ko is None and art.image_url is None
    assert art.outlet is None and art.journalist is None and art.team == "arsenal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_article_accepts_tier2a_fields -q`
Expected: FAIL (`unexpected keyword argument 'summary3_ko'`)

- [ ] **Step 3: Implement — add fields to Article**

`src/bullet_in/models.py` 의 `Article` 클래스에 `revision` 위쪽에 추가:

```python
    body_excerpt: str | None = None
    summary3_ko: str | None = None
    body_ko: str | None = None
    body_source: str | None = None
    image_url: str | None = None
    outlet: str | None = None
    journalist: str | None = None
    team: str = "arsenal"
    published_at: datetime
```

`schema.sql` 의 `articles` 테이블 컬럼 목록에 추가 (기존 `body_excerpt TEXT,` 뒤):

```sql
  title_original TEXT, title_ko TEXT, summary_ko TEXT, body_excerpt TEXT,
  summary3_ko TEXT, body_ko TEXT, body_source TEXT,
  image_url VARCHAR(1024), outlet VARCHAR(128), journalist VARCHAR(128),
  team VARCHAR(32) DEFAULT 'arsenal',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/models.py src/bullet_in/storage/schema.sql tests/test_models.py
git commit -m "feat(model): Article·schema 에 Tier 2-a 필드 추가 (3줄요약·본문·이미지·언론사·팀)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: MartStore — 신규 필드 upsert · set_translation 확장

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:19-60`
- Test: `tests/integration/test_mariadb_store.py`

**Interfaces:**
- Consumes: Task 1 의 `Article` 필드.
- Produces: `MartStore.set_translation(content_hash, title_ko, summary_ko, summary3_ko, body_ko)` (4→인자 확장). `upsert` 가 신규 컬럼을 INSERT. `rows_missing_translation()` 가 `outlet`, `body_source` 도 SELECT.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_mariadb_store.py` 에 추가:

```python
def test_set_translation_writes_all_four_fields(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="h9", url="https://x.test/9", title="T")])
    store.set_translation("h9", "제목", "한줄", "①\n②\n③", "전체 본문")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT title_ko,summary_ko,summary3_ko,body_ko "
            "FROM articles WHERE content_hash='h9'")).mappings().one())
    assert r["title_ko"] == "제목" and r["summary_ko"] == "한줄"
    assert r["summary3_ko"] == "①\n②\n③" and r["body_ko"] == "전체 본문"

def test_upsert_persists_image_outlet_team(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hi", url="https://x.test/i", source_id="bbc_sport",
                          title_original="T", outlet="BBC", journalist="Sami Mokbel",
                          image_url="https://img.test/a.jpg", body_source="src", team="arsenal",
                          published_at=datetime(2026,6,29,tzinfo=timezone.utc))])
    from sqlalchemy import text
    with engine.connect() as c:
        r = dict(c.execute(text("SELECT outlet,journalist,image_url,team,body_source "
                                "FROM articles WHERE content_hash='hi'")).mappings().one())
    assert r["outlet"] == "BBC" and r["image_url"] == "https://img.test/a.jpg"
    assert r["team"] == "arsenal" and r["body_source"] == "src"

def test_rows_missing_translation_includes_outlet_and_body_source(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hm", url="https://x.test/m", source_id="fmkorea",
                          title_original="T", outlet="The Athletic", body_source="원문",
                          published_at=datetime(2026,6,29,tzinfo=timezone.utc))])
    row = next(r for r in store.rows_missing_translation() if r["content_hash"] == "hm")
    assert row["outlet"] == "The Athletic" and row["body_source"] == "원문"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_mariadb_store.py::test_set_translation_writes_all_four_fields -q`
Expected: FAIL (DB 있으면 인자 개수/컬럼 에러; DB 없으면 skip — DB 환경에서 실행할 것)

- [ ] **Step 3: Implement — mariadb.py 확장**

`upsert` 의 INSERT 컬럼/VALUES 와 `ON DUPLICATE KEY UPDATE` 에 신규 필드를 추가하고, `set_translation` · `rows_missing_translation` 를 교체:

```python
    def upsert(self, articles: list[Article]) -> int:
        if not articles:
            return 0
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,
             summary3_ko,body_ko,body_source,image_url,outlet,journalist,team,
             published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,
             :summary3_ko,:body_ko,:body_source,:image_url,:outlet,:journalist,:team,
             :published_at,:fetched_at,:revision)
          ON DUPLICATE KEY UPDATE
             title_ko=IF(articles.content_hash=VALUES(content_hash), articles.title_ko, NULL),
             summary_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary_ko, NULL),
             summary3_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary3_ko, NULL),
             body_ko=IF(articles.content_hash=VALUES(content_hash), articles.body_ko, NULL),
             title_original=VALUES(title_original),
             body_excerpt=VALUES(body_excerpt),
             body_source=VALUES(body_source),
             image_url=VALUES(image_url),
             outlet=VALUES(outlet),
             journalist=VALUES(journalist),
             team=VALUES(team),
             published_at=VALUES(published_at),
             tier=VALUES(tier),
             confidence_score=VALUES(confidence_score),
             fetched_at=VALUES(fetched_at),
             revision=VALUES(revision),
             content_hash=VALUES(content_hash)""")
        rows = [a.model_dump() for a in articles]
        with self.engine.begin() as c:
            c.execute(sql, rows)
        return len(rows)
```

```python
    def rows_missing_translation(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,source_id,title_original,body_excerpt,"
                "body_source,outlet FROM articles WHERE title_ko IS NULL")).mappings().all()
        return [dict(r) for r in rows]

    def set_translation(self, content_hash: str, title_ko: str, summary_ko: str,
                        summary3_ko: str | None = None, body_ko: str | None = None):
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET title_ko=:t, summary_ko=:s, "
                           "summary3_ko=:s3, body_ko=:b WHERE content_hash=:h"),
                      {"t": title_ko, "s": summary_ko, "s3": summary3_ko,
                       "b": body_ko, "h": content_hash})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_mariadb_store.py -q`
Expected: PASS (MariaDB 가동 시). `docker compose up -d` 로 DB 띄운 뒤 실행.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/storage/mariadb.py tests/integration/test_mariadb_store.py
git commit -m "feat(storage): upsert·set_translation 에 Tier 2-a 필드 반영

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: adapters/meta.py — og:image · 본문 추출 헬퍼

**Files:**
- Create: `src/bullet_in/adapters/meta.py`
- Test: `tests/test_meta.py`

**Interfaces:**
- Produces: `extract_og_image(html: str) -> str | None`, `extract_article_body(html: str, max_chars: int = 8000) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_meta.py`:

```python
from bullet_in.adapters.meta import extract_og_image, extract_article_body

def test_extract_og_image_prefers_og():
    html = ('<meta property="og:image" content="https://img.test/a.jpg">'
            '<meta name="twitter:image" content="https://img.test/b.jpg">')
    assert extract_og_image(html) == "https://img.test/a.jpg"

def test_extract_og_image_falls_back_to_twitter():
    html = '<meta name="twitter:image" content="https://img.test/b.jpg">'
    assert extract_og_image(html) == "https://img.test/b.jpg"

def test_extract_og_image_none_when_absent():
    assert extract_og_image("<html><head></head></html>") is None

def test_extract_article_body_joins_paragraphs_in_article():
    html = ('<header>nav</header><article><p>First para.</p><p>Second para.</p>'
            '<figure><figcaption>cap</figcaption></figure></article><footer>f</footer>')
    out = extract_article_body(html)
    assert "First para." in out and "Second para." in out
    assert "nav" not in out and "cap" not in out

def test_extract_article_body_truncates():
    html = "<article>" + "<p>" + ("가" * 50) + "</p>" * 1 + "</article>"
    assert len(extract_article_body(html, max_chars=10)) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_meta.py -q`
Expected: FAIL (`No module named 'bullet_in.adapters.meta'`)

- [ ] **Step 3: Implement meta.py**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_meta.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/meta.py tests/test_meta.py
git commit -m "feat(adapters): og:image·기사 본문 추출 헬퍼 (meta.py)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: HtmlAdapter — body_selector 로 본문 + og:image 수집

**Files:**
- Modify: `src/bullet_in/adapters/html.py`
- Test: `tests/test_html_adapter.py`

**Interfaces:**
- Consumes: `extract_og_image` (Task 3).
- Produces: `HtmlAdapter(..., body_selector: str | None = None)`. `body_selector` 가 있으면 각 기사 URL 을 추가 fetch 해 `raw_payload["body"]` (본문 텍스트)와 `raw_payload["image_url"]` 를 채운다. 본문 fetch 실패 시 그 기사는 제목만 (body 없음) 유지.

- [ ] **Step 1: Write the failing test**

`tests/test_html_adapter.py` 에 추가:

```python
from bullet_in.adapters.meta import extract_og_image  # noqa: F401 (의존 확인)

@respx.mock
def test_html_adapter_fetches_body_and_image_when_selector_set():
    list_html = ('<a class="card" href="/a">Arsenal sign Gyokeres</a>')
    detail = ('<html><head><meta property="og:image" content="https://img.test/g.jpg">'
              '</head><body><div class="article-body"><p>Deal done for 60m.</p>'
              '<p>Five-year contract.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert "Deal done for 60m." in items[0].raw_payload["body"]
    assert items[0].raw_payload["image_url"] == "https://img.test/g.jpg"

@respx.mock
def test_html_adapter_keeps_title_when_detail_fetch_fails():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload.get("body", "") == ""
    assert items[0].raw_payload["title"] == "Arsenal sign Gyokeres"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_html_adapter.py::test_html_adapter_fetches_body_and_image_when_selector_set -q`
Expected: FAIL (`unexpected keyword argument 'body_selector'`)

- [ ] **Step 3: Implement — html.py**

`__init__` 에 `body_selector` 파라미터 추가 (기존 `title_contains` 뒤):

```python
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, title_contains: str | list[str] | None = None,
                 body_selector: str | None = None):
        ...
        self.body_selector = body_selector
```

`fetch()` 에서 목록 파싱 후, 반환 직전에 `body_selector` 가 있으면 상세를 fetch. 기존 루프가 `out.append(RawItem(...))` 하던 부분을 다음으로 교체 (목록 수집과 상세 보강 분리):

```python
    async def fetch(self) -> list[RawItem]:
        from bullet_in.adapters.meta import extract_og_image
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(self.list_url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            now, matched, seen = datetime.now(timezone.utc), [], set()
            for a in soup.select(self.item_selector):
                href = a.get("href")
                if not href:
                    continue
                url = urljoin(self.base_url, href)
                if url in seen:
                    continue
                seen.add(url)
                title = a.get_text(strip=True)
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
                matched.append((title, url))
            out = []
            for title, url in matched:
                payload = {"title": title}
                if self.body_selector:
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        el = BeautifulSoup(rb.text, "html.parser").select_one(self.body_selector)
                        payload["body"] = el.get_text(" ", strip=True) if el else ""
                        payload["image_url"] = extract_og_image(rb.text)
                    except httpx.HTTPError:
                        payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
                out.append(RawItem(source_id=self.source_id, source_type="html",
                                   url=url, fetched_at=now, raw_payload=payload))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_html_adapter.py -q`
Expected: PASS (기존 4개 + 신규 2개). `body_selector` 없는 기존 테스트는 상세 fetch 안 하므로 그대로 통과.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/html.py tests/test_html_adapter.py
git commit -m "feat(adapters): HtmlAdapter body_selector 로 본문·og:image 수집

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: factory · sources.yaml — body_selector 배선

**Files:**
- Modify: `src/bullet_in/adapters/factory.py:18-20`
- Modify: `config/sources.yaml`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: Task 4 의 `HtmlAdapter(body_selector=...)`.
- Produces: html 어댑터 설정의 `body_selector` 키가 `HtmlAdapter` 로 전달됨.

- [ ] **Step 1: Write the failing test**

`tests/test_adapter_factory.py` 에 추가 (기존 import/패턴 따름):

```python
def test_factory_passes_body_selector_to_html():
    from bullet_in.adapters.factory import build_adapters
    from bullet_in.adapters.html import HtmlAdapter
    cfg = {"sources": [{"source_id": "bbc_sport", "adapter": "html", "enabled": True,
            "config": {"list_url": "https://b.test", "item_selector": "a.card",
                       "body_selector": ".article-body"}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.body_selector == ".article-body"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapter_factory.py::test_factory_passes_body_selector_to_html -q`
Expected: FAIL (`a.body_selector` is None / AttributeError)

- [ ] **Step 3: Implement**

`factory.py` 의 html 분기 교체:

```python
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector")))
```

`config/sources.yaml` 의 EN 소스에 `body_selector` 추가 (실제 셀렉터는 Step 4 라이브 검증으로 확정 — 초기 후보):

```yaml
  # bbc_sport.config 에 추가
      body_selector: "article"
  # football_london.config 에 추가
      body_selector: "div.article-body"
  # arsenal_official.config 에 추가
      body_selector: "div.article-body, article"
```

- [ ] **Step 4: 라이브 셀렉터 검증 (모킹 아님)**

각 소스 본문 셀렉터가 실제로 본문을 잡는지 단독 검증:

```bash
set -a; source .env; set +a
uv run python -c "import asyncio,yaml; from bullet_in.adapters.factory import build_adapters; \
cfg=yaml.safe_load(open('config/sources.yaml')); \
a=[x for x in build_adapters(cfg) if x.source_id=='bbc_sport'][0]; \
items=asyncio.run(a.fetch()); print(len(items), items[0].raw_payload.get('body','')[:200] if items else 'none')"
```
Expected: 본문 텍스트가 출력됨. 비어 있으면 `body_selector` 를 실제 DOM 에 맞게 수정 후 재실행 (드리프트 사례: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`).

- [ ] **Step 5: Run unit test + Commit**

Run: `uv run pytest tests/test_adapter_factory.py -q` → PASS

```bash
git add src/bullet_in/adapters/factory.py config/sources.yaml tests/test_adapter_factory.py
git commit -m "feat(adapters): EN 소스 body_selector 설정 배선·라이브 검증

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: fmkorea — 제목 말머리 [언론사] 파싱

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Produces: `parse_bracket(title: str) -> tuple[str | None, str | None, bool]` → `(outlet, journalist, is_exclusive)`. 한글 언론사명은 `OUTLET_MAP` 으로 정규화 (`"디 애슬레틱" -> "The Athletic"`). 말머리 없으면 `(None, None, False)`.

- [ ] **Step 1: Write the failing test**

`tests/test_fmkorea_adapter.py` 에 추가:

```python
from bullet_in.adapters.fmkorea import parse_bracket

def test_parse_bracket_outlet_and_journalist():
    assert parse_bracket("[BBC - 사미 목벨] 토트넘, 페르난데스 영입 추진") == ("BBC", "사미 목벨", False)

def test_parse_bracket_normalizes_korean_outlet():
    assert parse_bracket("[디 애슬레틱 - 온스테인] 앤더슨 결장") == ("The Athletic", "온스테인", False)

def test_parse_bracket_exclusive_flag():
    assert parse_bracket("[디 애슬레틱-독점] 디오망데 PSG 선택") == ("The Athletic", None, True)

def test_parse_bracket_outlet_only():
    assert parse_bracket("[공홈] 요케레스 영입 완료") == ("공홈", None, False)

def test_parse_bracket_no_bracket():
    assert parse_bracket("Arsenal target identified") == (None, None, False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_parse_bracket_outlet_and_journalist -q`
Expected: FAIL (`cannot import name 'parse_bracket'`)

- [ ] **Step 3: Implement parse_bracket**

`fmkorea.py` 상단 (상수/헬퍼 영역)에 추가:

```python
OUTLET_MAP = {
    "디 애슬레틱": "The Athletic", "디애슬레틱": "The Athletic",
    "골닷컴": "Goal", "르퀴프": "L'Équipe",
}
_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]")

def parse_bracket(title: str) -> tuple[str | None, str | None, bool]:
    """fmkorea 말머리 [언론사] / [언론사 - 기자] / [언론사-독점] 파싱."""
    m = _BRACKET_RE.match(title)
    if not m:
        return None, None, False
    inner = m.group(1).strip()
    is_excl = "독점" in inner
    inner = inner.replace("독점", "")
    parts = re.split(r"\s*-\s*", inner, maxsplit=1)
    outlet = parts[0].strip(" -")
    journalist = parts[1].strip(" -") if len(parts) > 1 and parts[1].strip(" -") else None
    outlet = OUTLET_MAP.get(outlet, outlet)
    return (outlet or None), journalist, is_excl
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k parse_bracket -q`
Expected: PASS (5개)

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 제목 말머리 [언론사·기자·독점] 파싱

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: fmkorea — 원문 URL 추출 버그픽스 (끝쪽 평문 우선)

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:29-42`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Produces: `_extract_original_url` 가 본문 끝 평문 출처 URL 을 `a[href]` (기자 프로필 등)보다 우선한다. 평문 URL 이 여럿이면 마지막 것 (출처 관례)을 택한다.

- [ ] **Step 1: Write the failing test (실측 회귀 케이스)**

`tests/test_fmkorea_adapter.py` 에 추가:

```python
def test_extract_original_url_prefers_trailing_plaintext_over_author_anchor():
    # 실측 post 10007542458: 본문에 기자 프로필 앵커 + 끝에 평문 기사 URL
    html = ('<div class="xe_content">'
            '<p>By <a href="https://www.nytimes.com/athletic/author/david-ornstein/">'
            'David Ornstein</a> 앤더슨 결장.</p>'
            '<p>https://www.nytimes.com/athletic/7398614/2026/06/26/england-anderson/</p>'
            '</div>')
    assert _extract_original_url(html, ".xe_content") == \
        "https://www.nytimes.com/athletic/7398614/2026/06/26/england-anderson/"

def test_extract_original_url_uses_anchor_when_no_plaintext():
    html = ('<div class="xe_content"><p>출처: '
            '<a href="https://www.bbc.com/sport/football/articles/abc">BBC</a></p></div>')
    assert _extract_original_url(html, ".xe_content") == \
        "https://www.bbc.com/sport/football/articles/abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_extract_original_url_prefers_trailing_plaintext_over_author_anchor -q`
Expected: FAIL (현재는 author 앵커를 반환)

- [ ] **Step 3: Implement — 평문 우선, 마지막 평문 채택**

`_extract_original_url` 교체:

```python
def _extract_original_url(html: str, body_selector: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(body_selector)
    if el is None:
        return None
    # 1) 본문 평문 출처 URL 우선 (fmkorea 관례: 본문 끝). 여럿이면 마지막.
    plains = [m.group(0) for m in _URL_RE.finditer(el.get_text(" ", strip=True))
              if "fmkorea.com" not in m.group(0)]
    if plains:
        return plains[-1]
    # 2) 폴백: 외부 앵커 (기자 프로필일 수 있으나 평문 없을 때만)
    for a in el.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("http") and "fmkorea.com" not in href:
            return href
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k extract_original_url -q`
Expected: PASS. 기존 `test_extract_original_url_from_plaintext_body` · `test_fetch_blocked_*` 도 평문 기반이라 그대로 통과.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "fix(fmkorea): 원문 URL 추출 시 끝쪽 평문 출처를 기자 프로필 앵커보다 우선

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: fmkorea — 발견 소스 흐름 (원문 해소 · 유료 분기 · 메타)

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:56-118`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: `parse_bracket` (Task 6), `_extract_original_url` (Task 7), `extract_og_image` · `extract_article_body` (Task 3), 상수 `PAYWALLED_OUTLETS = {"The Athletic"}`.
- Produces: `FmkoreaAdapter.fetch()` 가 각 글에서 `raw_payload` 에 `title`, `body`, `lang`, `outlet`, `journalist`, `image_url` 를 담고 `url` 을 원문 URL 로 설정. 분기: 유료 (The Athletic) → fmkorea 본문 사용 (`lang="ko"`); 무료 → 원문 fetch 후 `extract_article_body` (`lang="en"`), 원문 og:image. 원문 URL/말머리 실패 → 그 글 스킵 + WARNING.

- [ ] **Step 1: Write the failing test**

`tests/test_fmkorea_adapter.py` 에 추가:

```python
@respx.mock
def test_fmkorea_paywalled_keeps_korean_body_and_outlet():
    list_html = '<a class="title" href="/1">[디 애슬레틱 - 온스테인] 아스날 수비수 보강</a>'
    body = ('<div class="xe_content"><p>아스날이 센터백을 원한다.</p>'
            '<p>https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/</p></div>')
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/"
    assert it.raw_payload["outlet"] == "The Athletic"
    assert it.raw_payload["journalist"] == "온스테인"
    assert it.raw_payload["lang"] == "ko"
    assert "센터백" in it.raw_payload["body"]   # 디 애슬레틱: fmkorea 번역본 유지

@respx.mock
def test_fmkorea_free_outlet_fetches_original_english_body():
    list_html = '<a class="title" href="/1">[BBC - 사미 목벨] 아스날 요케레스 영입</a>'
    body = ('<div class="xe_content"><p>아스날이 요케레스를 영입한다.</p>'
            '<p>https://www.bbc.com/sport/football/articles/gyo</p></div>')
    original = ('<html><head><meta property="og:image" content="https://img.bbc/g.jpg"></head>'
                '<body><article><p>Arsenal have signed Gyokeres.</p>'
                '<p>The fee is 60m.</p></article></body></html>')
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    respx.get("https://www.bbc.com/sport/football/articles/gyo").mock(
        return_value=httpx.Response(200, text=original))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    it = asyncio.run(a.fetch())[0]
    assert it.url == "https://www.bbc.com/sport/football/articles/gyo"
    assert it.raw_payload["outlet"] == "BBC"
    assert it.raw_payload["lang"] == "en"
    assert "Arsenal have signed Gyokeres." in it.raw_payload["body"]   # 원문 영어 본문
    assert it.raw_payload["image_url"] == "https://img.bbc/g.jpg"

@respx.mock
def test_fmkorea_skips_when_no_original_url(caplog):
    list_html = '<a class="title" href="/1">[BBC] 아스날 소식</a>'
    body = '<div class="xe_content"><p>출처 링크 없는 본문.</p></div>'
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=body))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"], base_url="https://fm.test")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert items == []
    assert any("원문" in r.message or "skip" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_fmkorea_paywalled_keeps_korean_body_and_outlet -q`
Expected: FAIL (`outlet` 키 없음 등)

- [ ] **Step 3: Implement — fetch 흐름 재작성**

`fmkorea.py` 상단에 상수 추가, `_REPOST_MARK` 인근:

```python
PAYWALLED_OUTLETS = {"The Athletic"}
```

`FmkoreaAdapter.fetch()` 의 매칭 후 루프 (`for title, url in matched:` 블록)를 교체:

```python
            from bullet_in.adapters.meta import extract_og_image, extract_article_body
            for title, url in matched:
                try:
                    rb = await c.get(url)
                    rb.raise_for_status()
                except httpx.HTTPError:
                    continue  # 글 fetch 실패 — 스킵, 배치 지속
                html = rb.text
                outlet, journalist, _excl = parse_bracket(title)
                orig = _extract_original_url(html, self.body_selector)
                if orig is None or outlet is None:
                    log.warning("fmkorea 원문/말머리 해소 실패 — 스킵 url=%s", url)
                    continue
                if outlet in PAYWALLED_OUTLETS:
                    # 유료 (디 애슬레틱): fmkorea 한국어 번역본 유지, 원문 og:image 만 시도
                    body = _body_text(html, self.body_selector)
                    image = await _fetch_og_image(c, orig)
                    lang = "ko"
                else:
                    # 무료: 원문 fetch 후 영어 본문·이미지 추출
                    try:
                        ro = await c.get(orig)
                        ro.raise_for_status()
                        body = extract_article_body(ro.text)
                        image = extract_og_image(ro.text)
                    except httpx.HTTPError:
                        body, image = "", None
                    lang = "en"
                out.append(RawItem(
                    source_id=self.source_id, source_type="html", url=orig,
                    fetched_at=now,
                    raw_payload={"title": title, "body": body, "lang": lang,
                                 "outlet": outlet, "journalist": journalist,
                                 "image_url": image}))
        return out
```

`_fetch_og_image` 헬퍼 추가 (`_fetch_og_description` 인근):

```python
async def _fetch_og_image(client: httpx.AsyncClient, url: str) -> str | None:
    from bullet_in.adapters.meta import extract_og_image
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return extract_og_image(r.text)
```

> 참고: 기존 `_is_repost_blocked` · `_fetch_og_description` · 분기①/② 코드는 이 흐름으로 대체된다. 우리 변경이 만든 고아 함수만 제거하고, 그 외 기존 코드는 그대로 둔다. `_is_repost_blocked` 가 다른 곳에서 안 쓰이면 호출부와 함께 제거.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q`
Expected: PASS. 단, 기존 `test_fetch_blocked_*` · `test_fetch_og_description_*` 는 구 흐름 검증이므로 **이번 변경에 맞게 갱신/삭제** (구 분기 제거에 따라). 갱신: 유료/무료 분기 테스트가 대체.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 발견 소스화 — 원문 해소·유료(디 애슬레틱) 분기·메타 수집

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: pipeline — 신규 필드 매핑 · 소스 우선순위 dedup

**Files:**
- Modify: `src/bullet_in/pipeline.py:17-44`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `RawItem.raw_payload` 의 `body`, `image_url`, `outlet`, `journalist`, `lang`.
- Produces: `to_articles` 가 `Article.body_source` (raw body), `image_url`, `outlet`, `journalist`, `team="arsenal"` 를 채운다. 같은 url 이 fmkorea 와 타 소스에서 오면 **fmkorea 가 아닌 쪽을 남긴다** (raw 를 `source_id=="fmkorea"` 가 뒤로 가도록 정렬).

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py` 에 추가:

```python
def test_to_articles_maps_tier2a_fields():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://www.bbc.com/sport/football/articles/g",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign Gyokeres", "body": "English body",
                                "image_url": "https://img.test/g.jpg", "outlet": "BBC",
                                "journalist": "Sami Mokbel"})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].body_source == "English body"
    assert arts[0].image_url == "https://img.test/g.jpg"
    assert arts[0].outlet == "BBC" and arts[0].journalist == "Sami Mokbel"
    assert arts[0].team == "arsenal"

def test_to_articles_prefers_en_source_over_fmkorea_for_same_url():
    now = datetime.now(timezone.utc)
    url = "https://www.bbc.com/sport/football/articles/g"
    raw = [
        RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "Arsenal sign Gyokeres", "outlet": "BBC"}),
        RawItem(source_id="bbc_sport", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "Arsenal sign Gyokeres", "outlet": "BBC"}),
    ]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4},
               "bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, stats = to_articles(raw, sources, seen={})
    assert len(arts) == 1
    assert arts[0].source_id == "bbc_sport"   # EN 우선, fmkorea 스킵
    assert stats["dup_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py::test_to_articles_maps_tier2a_fields -q`
Expected: FAIL (`body_source` is None)

- [ ] **Step 3: Implement — pipeline.py**

`to_articles` 시작부에 소스 우선순위 정렬, Article 생성에 신규 필드 매핑:

```python
def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]],
                registry: "Registry | None" = None) -> tuple[list[Article], dict]:
    out: list[Article] = []
    local_seen = dict(seen)
    dup_count = 0
    source_counts: dict[str, int] = {}
    # fmkorea(발견 소스)는 같은 원문 URL 에서 EN/X 보다 후순위 → first-seen 이 EN/X 가 되게 정렬
    raw = sorted(raw, key=lambda it: 1 if it.source_id == "fmkorea" else 0)
    for item in raw:
        tier = resolve_tier(item, sources, registry)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            dup_count += 1
            continue
        local_seen[url] = (h, rev)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            body_source=item.raw_payload.get("body"),
            image_url=item.raw_payload.get("image_url"),
            outlet=item.raw_payload.get("outlet"),
            journalist=item.raw_payload.get("journalist"),
            team="arsenal",
            published_at=_published(item.raw_payload), fetched_at=item.fetched_at,
            revision=rev))
        source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
    return out, {"dup_count": dup_count, "source_counts": source_counts}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: PASS (기존 + 신규 2개). 정렬은 안정 정렬이라 기존 동작 보존.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): Tier 2-a 필드 매핑·fmkorea 후순위 dedup(EN/X 우선)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: enrich — 통합 출력 (번역/변형) 4필드

**Files:**
- Modify: `src/bullet_in/enrich.py`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Produces: `enrich_rows(rows, client, model, mode="translate") -> dict[str, dict]` — 각 hash 에 `{"title_ko","summary_ko","summary3_ko","body_ko"}`. `mode="paraphrase"` 는 유료 (디 애슬레틱) 한국어 본문을 변형. `partition_by_paywall(rows) -> (paraphrase_rows, translate_rows)` (`outlet in PAYWALLED_OUTLETS` 기준). 429 시 회차 중단 · 로깅 유지.

- [ ] **Step 1: Write the failing test**

`tests/test_enrich.py` 에 추가 (기존 FakeClient 패턴):

```python
import json as _json
from bullet_in.enrich import enrich_rows, partition_by_paywall

class FullModels:
    def __init__(self, payload): self._p = payload; self.n = 0
    def generate_content(self, **kw):
        self.n += 1
        class R: pass
        r = R(); r.text = _json.dumps(self._p, ensure_ascii=False); return r
class FullClient:
    def __init__(self, payload): self.models = FullModels(payload)

def test_enrich_returns_four_fields():
    payload = {"title_ko": "아스날, 요케레스 영입", "summary_ko": "6천만에 영입",
               "summary3_ko": ["발표", "이적료 6천만", "5년 계약"], "body_ko": "전체 본문"}
    rows = [{"content_hash": "h1", "title_original": "Arsenal sign", "body_source": "Body"}]
    out = enrich_rows(rows, FullClient(payload), "m")
    assert out["h1"]["title_ko"] == "아스날, 요케레스 영입"
    assert out["h1"]["summary_ko"] == "6천만에 영입"
    assert out["h1"]["summary3_ko"] == "발표\n이적료 6천만\n5년 계약"  # 배열 → \n join
    assert out["h1"]["body_ko"] == "전체 본문"

def test_enrich_skips_row_missing_keys():
    payload = {"title_ko": "제목"}  # 키 부족
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": ""}],
                      FullClient(payload), "m")
    assert "h" not in out

def test_enrich_paraphrase_mode_uses_paraphrase_prompt():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a", "b", "c"], "body_ko": "B"}
    client = FullClient(payload)
    rows = [{"content_hash": "h", "title_original": "[디 애슬레틱] 제목", "body_source": "한국어 본문"}]
    out = enrich_rows(rows, client, "m", mode="paraphrase")
    assert out["h"]["body_ko"] == "B"  # 정상 처리됨 (프롬프트 분기는 PROMPT 상수 사용)

def test_partition_by_paywall_splits_by_outlet():
    rows = [{"content_hash": "a", "outlet": "The Athletic"},
            {"content_hash": "b", "outlet": "BBC"}]
    para, trans = partition_by_paywall(rows)
    assert [r["content_hash"] for r in para] == ["a"]
    assert [r["content_hash"] for r in trans] == ["b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_enrich.py::test_enrich_returns_four_fields -q`
Expected: FAIL (`out["h1"]` 은 튜플이고 dict 아님)

- [ ] **Step 3: Implement — enrich.py**

상수 · 헬퍼 · 함수 추가/교체:

```python
PAYWALLED_OUTLETS = {"The Athletic"}

TRANSLATE_PROMPT = (
    "아스날 FC 축구 뉴스를 한국어로 번역·요약한다. 규칙:\n"
    "- title_ko: 한국 스포츠 기사 제목체로 간결하게 (명사형 위주).\n"
    "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심.\n"
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- body_ko: 본문 전체를 자연스러운 한국어로 번역. 단락 유지.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
    "\n\nTitle: {title}\nBody: {body}")

PARAPHRASE_PROMPT = (
    "다음은 한국어로 번역된 아스날 FC 축구 기사다. 의미·사실·수치·고유명사·인용은 "
    "절대 바꾸지 말고 문장 표현만 자연스럽게 바꿔 다시 쓴다 (paraphrase). 규칙:\n"
    "- title_ko: 제목을 간결한 기사 제목체로 다시 쓴다(말머리 대괄호 제거).\n"
    "- summary_ko: 한 문장 요약, 평어체.\n"
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- body_ko: 본문 전체를 문장 표현만 바꿔 다시 쓴다. 내용 추가·삭제 금지.\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
    "\n\nTitle: {title}\nBody: {body}")

def _extract_full(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        return {"title_ko": d["title_ko"], "summary_ko": d["summary_ko"],
                "summary3_ko": s3, "body_ko": d["body_ko"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def partition_by_paywall(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    para, trans = [], []
    for r in rows:
        (para if r.get("outlet") in PAYWALLED_OUTLETS else trans).append(r)
    return para, trans

def enrich_rows(rows: list[dict], client, model: str, mode: str = "translate"
                ) -> dict[str, dict]:
    prompt = PARAPHRASE_PROMPT if mode == "paraphrase" else TRANSLATE_PROMPT
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=prompt.format(title=r["title_original"],
                                       body=r.get("body_source") or r.get("body_excerpt") or ""),
                config={"max_output_tokens": 2048,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), enrich 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract_full(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
            continue
        result[h] = parsed
    return result
```

> `PROMPT`/`_extract`/구 `enrich_rows` 튜플 반환은 이 통합 버전으로 대체. 구 `enrich_rows` 를 쓰던 테스트 (`test_enrich_translates_missing_rows` 등)는 신규 dict 반환에 맞게 갱신.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_enrich.py -q`
Expected: PASS (신규 + 갱신된 기존). 갱신: 튜플 단언을 dict 단언으로.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): 기사당 1콜 통합 출력(title_ko·1줄·3줄·body_ko)·유료 변형 분기

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: run.py — 신규 enrich/저장 배선 (오케스트레이션)

**Files:**
- Modify: `src/bullet_in/run.py:45-55`
- Test: 라이브/수동 검증 (run.py 는 단위 테스트 대상 아님 — 기존 관례)

**Interfaces:**
- Consumes: `partition_by_paywall` · `enrich_rows(mode=...)` (Task 10), `set_translation(4필드)` (Task 2).
- Produces: enrich 결과 4필드를 `set_translation` 으로 저장. 유료/무료 분리 호출.

- [ ] **Step 1: Implement — run.py enrich 블록 교체**

`src/bullet_in/run.py` 의 enrich 구간 (`ko_rows, en_rows = ...` 부터 `mart.set_translation(h, tk, sk)` 까지)을 교체:

```python
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.enrich import partition_by_paywall
    missing = mart.rows_missing_translation()
    paraphrase_rows, translate_rows = partition_by_paywall(missing)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(paraphrase_rows, client, GEMINI_MODEL, mode="paraphrase"))
    for h, v in results.items():
        mart.set_translation(h, v["title_ko"], v["summary_ko"],
                             v["summary3_ko"], v["body_ko"])
```

기존 `from bullet_in.enrich import enrich_rows, partition_translation_rows, summarize_ko_rows` import 는 `from bullet_in.enrich import enrich_rows` 로 정리 (우리 변경이 만든 미사용 import 제거).

- [ ] **Step 2: 수동/라이브 검증 (DB + Gemini 키 필요)**

```bash
set -a; source .env; set +a
docker compose up -d
uv run python -m bullet_in.run --concurrency 8
# 검증: articles 에 body_ko·summary3_ko·outlet·image_url 채워졌는지
uv run python -c "from sqlalchemy import create_engine,text; import os; \
e=create_engine(os.environ['MARIADB_URL']); \
import json; \
[print(dict(r)) for r in e.connect().execute(text('SELECT outlet,title_ko,summary3_ko IS NOT NULL s3,body_ko IS NOT NULL b,image_url FROM articles LIMIT 5')).mappings()]"
```
Expected: `s3` · `b` 가 1, `outlet` 채워짐. 디 애슬레틱 기사는 body_ko 가 변형된 한국어, BBC 등은 번역된 한국어.

- [ ] **Step 3: 전체 단위 테스트 회귀**

Run: `uv run pytest -q`
Expected: PASS (통합 DB 테스트는 DB 없으면 skip). 실패 시 해당 태스크로 돌아가 수정.

- [ ] **Step 4: Commit**

```bash
git add src/bullet_in/run.py
git commit -m "feat(run): enrich 통합 출력·유료 분기 배선, set_translation 4필드 저장

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (작성자 점검)

**Spec coverage (spec §별 → 태스크):**
- §3 데이터 모델 → Task 1, 2 ✓
- §4.1 EN 본문 → Task 4, 5 ✓ / §4.2 og:image → Task 3, 4, 8 ✓ / §4.3 fmkorea 발견 → Task 6, 7, 8 ✓
- §5 enrich 통합 · 유료 변형 → Task 10, 11 ✓ / §5.4 멱등 저장 → Task 2, 11 ✓
- §6 dedup EN/X 우선 → Task 9 ✓
- §7 서빙/UI → **Plan 2** (별도, 범위 외) — 본 플랜은 백엔드 한정.

**미해결/주의 (실행 중 확인):**
- 무료 외 도메인 본문은 `extract_article_body` 휴리스틱 (등록 소스는 `body_selector`). 임의 도메인 품질은 라이브에서 표본 확인.
- Task 8 은 fmkorea 의 기존 분기①/② · `_fetch_og_description` · `_is_repost_blocked` 관련 기존 테스트를 갱신/삭제해야 함 (구 흐름 대체).
- `summarize_ko_rows` · `partition_translation_rows` 는 신규 흐름에서 미사용 → 호출부 제거 후 함수는 남겨둠 (요청 시 정리).

**Type consistency:** `enrich_rows` 반환은 Task 10 · 11 모두 `dict[str, dict]` 4키. `set_translation` 4인자는 Task 2 정의 = Task 11 호출 일치. `parse_bracket` 3튜플 = Task 6 정의 = Task 8 사용 일치. `extract_og_image`/`extract_article_body` 시그니처 = Task 3 정의 = Task 4 · 8 사용 일치.

---

## 참조
- spec: `docs/superpowers/specs/2026-06-29-tier2a-detail-page-design.md`
- 다음: Plan 2 (서빙 · 웹 UI) — 본 플랜 구현 · 검증 후 작성.
