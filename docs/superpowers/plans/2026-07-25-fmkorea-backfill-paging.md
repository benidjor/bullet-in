# fmkorea 소급 백필 (검색 페이징) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fmkorea 검색을 여러 페이지까지 읽고 이미 적재된 글을 건너뛰어, IP 차단 기간 (2026-07-19 ~ 07-23) 에 놓친 글을 소급 적재한다.

**Architecture:** `FmkoreaAdapter` 에 페이지 순회 · 요청 간격 · 제목 배제 세 가지 선택 인자를 더한다 (기본값은 현행 동작 그대로).
새 진입점 `bullet_in.backfill_fmkorea` 가 DB 의 기존 제목을 배제 집합으로 넘겨 신규 글만 받아오고, 맥 릴레이 프록시 · 접촉 간격 가드는 `collect_fmkorea` 의 것을 그대로 재사용한다.
적재까지만 하고 번역 · 분류 · 렌더는 다음 정기 회차가 흡수한다.

**Tech Stack:** Python 3.11 · httpx + BeautifulSoup · respx (테스트) · SQLAlchemy · pytest.

## Global Constraints

- 적재 범위: 이 백필은 Mongo raw · MariaDB mart 적재까지만 한다 (번역 · 요약 · 분류 · 렌더 금지 — 다음 정기 회차가 흡수).
- 접촉 예산: fmkorea 요청 간격은 `REQUEST_GAP_SEC = 1.5` 초 · 직전 접촉 후 3시간 가드 (`should_supplement`) 를 지킨다.
- 프록시: fmkorea 접촉은 전부 `FMKOREA_PROXY` (맥 릴레이 SOCKS) 를 탄다 · 터널 미접속이면 접촉 없이 중단한다.
- 기본값 불변: 어댑터에 더하는 인자는 전부 선택 인자이고, 기본값일 때 정기 회차 동작 · 요청 수 · URL 이 지금과 완전히 같아야 한다.
- 멱등: 같은 명령을 두 번 실행해도 새 행이 생기지 않아야 한다 (제목 배제 + `url` UNIQUE + `seen_map` 이중 방어).
- 실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
- 문서 서식은 컨벤션 §2.2 를 따른다 · 커밋은 `<type>(<scope>): 한국어 제목` + 본문 도입 1–2문장 + 명사형 불릿.
- 커밋 트레일러 (§1.3): 모든 커밋 본문 끝에 아래 두 줄을 붙인다 (계획 설계 = Opus 5 · 구현 subagent = Sonnet).
  리뷰 전용 모델 (Fable 5 최종 리뷰) 은 co-author 에서 제외한다.
  `Co-Authored-By: Claude Opus 5 (설계) <noreply@anthropic.com>`
  `Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>`

## 착수 시점 실측 (2026-07-25 · 이 계획의 근거)

- VM DB 의 fmkorea 행 분포 — 발행일 기준 07-19 이후 1건 (07-21) · 5건 (07-23) · 3건 (07-24) 뿐이고 07-20 · 07-22 는 0건이다.
- 수집일 기준으로는 07-19 다음이 07-24 로, 그 사이 닷새가 통째로 비어 있다.
- 검색 페이징 라이브 확인 (주거 IP 직접 접속 · 3요청) — `&page=2` 는 200 · `a.hx` 20건 · 최신순으로 더 과거 글을 준다.
- `&page=1` 은 페이지 인자가 없을 때와 결과가 같다 (정기 회차 URL 에 `page` 를 넣어도 안전하다는 근거).
- 페이지당 20건인데 현행 `max_posts` 는 15 이고 키워드 3개가 라운드로빈으로 나눠 가지므로, 키워드당 실제로 5건만 적재된다.
  1페이지 안에서도 누락이 생기고 있었다는 뜻이라, 페이지 확장만으로는 부족하고 상한 · 배제 집합이 함께 필요하다.
- "아스날" 제목 검색 2페이지가 07-18 글까지 닿는다 — 차단 구간 전체가 3페이지 안에 들어온다.
- 라이브 확인은 `target=title` 만 했다 — `title_content` 키워드 (de roche · 온스테인) 의 페이징은 dry-run 에서 확인한다.

## 파일 구조

- `src/bullet_in/adapters/fmkorea.py` — 페이지 순회 · 요청 간격 · 제목 배제 · 후보만 반환하는 공개 메서드 추가.
- `config/sources.yaml` — fmkorea `search_url` 에 `&page={page}` 자리표시 추가.
- `src/bullet_in/collect_fmkorea.py` — 어댑터 팩토리에 선택 인자 전달 통로 · 적재 블록을 `persist()` 로 분리 (새 스크립트와 공용).
- `src/bullet_in/backfill_fmkorea.py` — 신규 진입점 (`--pages` · `--limit` · `--dry-run` · `--force`).
- `tests/test_fmkorea_adapter.py` — 페이징 · 간격 · 배제 단위 테스트 추가.
- `tests/test_collect_fmkorea.py` — 팩토리 선택 인자 테스트 추가.
- `tests/test_backfill_fmkorea.py` — 신규 · 배제 집합 조회 · `{page}` 자리표시 가드.
- `docs/runbook/2026-07-25-fmkorea-backfill-paging.md` — 실행 절차 · 접촉 예산 · 실측 결과.

---

### Task 1: 어댑터 페이지 순회

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:125-168` (`__init__` · `_discover`)
- Modify: `config/sources.yaml:121`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크).
- Produces: `FmkoreaAdapter(..., pages: int = 1)` — `_discover` 가 키워드마다 `page=1..pages` 를 순회한다.
  `search_url.format(keyword=..., target=..., page=...)` 호출 규약 (자리표시가 없는 템플릿도 그대로 동작).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.

```python
@respx.mock
def test_fmkorea_discovers_across_pages():
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(200, text=p2))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2)
    found = asyncio.run(a.discover())
    assert [t for t, _ in found] == ["[BBC] 아스날 1", "[BBC] 아스날 2"]


@respx.mock
def test_fmkorea_single_page_by_default():
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    route = respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=p1))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    found = asyncio.run(a.discover())
    assert route.call_count == 1
    assert len(found) == 1


@respx.mock
def test_fmkorea_page_error_keeps_earlier_pages_and_next_keyword(caplog):
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=9">[BBC] 아스날 9</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(429))
    respx.get("https://fm.test/s?t=title&kw=kw2&p=1").mock(return_value=httpx.Response(200, text=p2))
    respx.get("https://fm.test/s?t=title&kw=kw2&p=2").mock(return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2)
    found = asyncio.run(a.discover())
    titles = {t for t, _ in found}
    assert titles == {"[BBC] 아스날 1", "[BBC] 아스날 9"}
    assert "429" in caplog.text
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "pages or single_page or page_error" -v`
Expected: FAIL — `AttributeError: 'FmkoreaAdapter' object has no attribute 'discover'`.

- [ ] **Step 3: 최소 구현**

`__init__` 시그니처에 `pages` 를 더한다 (기존 인자 · 순서 불변).

```python
    def __init__(self, source_id: str, search_url: str, search_keywords: list[dict],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15,
                 proxy: str | None = None, pages: int = 1):
        ...
        self.proxy = proxy
        self.pages = pages
```

`_discover` 를 페이지 순회로 확장한다 (키워드 루프 안에 페이지 루프).

```python
    async def _discover(self, c: httpx.AsyncClient) -> list[tuple[str, str]]:
        """키워드 × 페이지 검색 → a.hx 파싱 → 정규 글 URL.
        키워드별 결과를 라운드로빈으로 max_posts 배분한다."""
        per_kw, seen = [], set()
        for kw in self.search_keywords:
            results = []
            for page in range(1, self.pages + 1):
                url = self.search_url.format(keyword=quote(kw["keyword"]),
                                             target=kw["target"], page=page)
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        log.warning("fmkorea 검색 429(rate limit) kw=%s p=%s — 스킵",
                                    kw["keyword"], page)
                    else:
                        log.warning("fmkorea 검색 HTTP %s kw=%s p=%s — 스킵",
                                    e.response.status_code, kw["keyword"], page)
                    break                       # 이 키워드의 남은 페이지도 중단
                except httpx.HTTPError as e:
                    log.warning("fmkorea 검색 실패 kw=%s p=%s err=%s — 스킵",
                                kw["keyword"], page, e)
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select(self.item_selector):
                    title = a.get_text(strip=True)
                    post_url = _post_url_from_href(a.get("href", ""), self.base_url)
                    if not title or not post_url or post_url in seen:
                        continue
                    seen.add(post_url)
                    results.append((title, post_url))
            per_kw.append(results)
        return _round_robin(per_kw, self.max_posts)
```

`fetch()` 의 클라이언트 생성을 헬퍼로 빼고 `discover()` 를 공개한다.

```python
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"},
                                 proxy=self.proxy)

    async def discover(self) -> list[tuple[str, str]]:
        """검색 페이지만 읽어 후보 (제목 · 글 URL) 를 반환한다 — 글 본문은 받지 않는다."""
        async with self._client() as c:
            return await self._discover(c)

    async def fetch(self) -> list[RawItem]:
        async with self._client() as c:
            matched = await self._discover(c)
            return await self._process(c, matched)
```

- [ ] **Step 4: 통과 확인 · 회귀 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: 신규 3건 PASS · 기존 fmkorea 테스트 전부 PASS (특히 `test_fmkorea_search_429_skips_keyword_continues` · `test_fmkorea_fetch_passes_proxy_to_client`).

- [ ] **Step 5: config 에 자리표시 추가**

`config/sources.yaml` 의 fmkorea `search_url` 을 바꾼다.
`&page=1` 이 인자 없는 요청과 같은 결과라는 것은 2026-07-25 라이브로 확인했다.

```yaml
      search_url: "https://www.fmkorea.com/search.php?mid=football_news&search_target={target}&search_keyword={keyword}&page={page}"
```

- [ ] **Step 6: 설정 회귀 확인**

Run: `uv run pytest tests/test_serving_config.py tests/test_adapter_factory.py tests/test_score.py -v`
Expected: PASS.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py config/sources.yaml tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(collect): fmkorea 검색 페이지 순회 지원

차단 기간에 놓친 글은 검색 1페이지 밖으로 밀려나 정기 회차로는 닿지 않는다.
페이지 인자를 받도록 검색 URL 과 발견 경로를 넓혀 소급 복원 통로를 연다.

- pages 인자: 키워드마다 1페이지부터 지정 페이지까지 순회 (기본 1 = 현행 동작)
- discover(): 글 본문을 받지 않고 후보 제목 · URL 만 반환하는 공개 메서드
- search_url: page 자리표시 추가 (page=1 은 인자 없는 요청과 동일 · 라이브 확인)
- 페이지 실패: 해당 키워드의 남은 페이지만 중단 · 앞 페이지 결과와 다음 키워드는 유지

Refs: docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md §6
EOF
)"
```

---

### Task 2: 요청 간격 · 제목 배제

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`__init__` · `_discover` · `_process`)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: Task 1 의 `pages` · `discover()` · `_client()`.
- Produces: `FmkoreaAdapter(..., request_gap_sec: float = 0.0, exclude_titles: set[str] | None = None)`.
  `exclude_titles` 에 든 제목은 후보에서 빠지고, 따라서 글 본문 요청도 일어나지 않는다.
  `request_gap_sec` 이 0 이면 `asyncio.sleep` 을 아예 호출하지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.

```python
@respx.mock
def test_fmkorea_excludes_known_titles_without_fetching():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    known = respx.get("https://www.fmkorea.com/1").mock(
        return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com",
                       exclude_titles={"[BBC] 아스날 1"})
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert known.call_count == 0          # 이미 있는 글은 접촉하지 않는다


@respx.mock
def test_fmkorea_exclusion_frees_max_posts_slots():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
            '<a class="hx" href="/index.php?document_srl=3">[BBC] 아스날 3</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", max_posts=2,
                       exclude_titles={"[BBC] 아스날 1"})
    found = asyncio.run(a.discover())
    assert [t for t, _ in found] == ["[BBC] 아스날 2", "[BBC] 아스날 3"]


@respx.mock
def test_fmkorea_sleeps_between_requests(monkeypatch):
    slept = []
    async def fake_sleep(sec):
        slept.append(sec)
    monkeypatch.setattr("bullet_in.adapters.fmkorea.asyncio.sleep", fake_sleep)
    p1 = '<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
    p2 = '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
    respx.get("https://fm.test/s?t=title&kw=kw1&p=1").mock(return_value=httpx.Response(200, text=p1))
    respx.get("https://fm.test/s?t=title&kw=kw1&p=2").mock(return_value=httpx.Response(200, text=p2))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}&p={page}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com", pages=2, request_gap_sec=1.5)
    asyncio.run(a.fetch())
    # 검색 2페이지 사이 1회 + 글 2건 사이 1회
    assert slept == [1.5, 1.5]


@respx.mock
def test_fmkorea_no_sleep_when_gap_zero(monkeypatch):
    slept = []
    async def fake_sleep(sec):
        slept.append(sec)
    monkeypatch.setattr("bullet_in.adapters.fmkorea.asyncio.sleep", fake_sleep)
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert slept == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "exclu or sleep" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'exclude_titles'`.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/fmkorea.py` 상단 import 에 `asyncio` 를 더한다 (`_gap` 이 처음 쓰는 시점).

```python
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
```

`__init__` 에 두 인자를 더한다.

```python
                 proxy: str | None = None, pages: int = 1,
                 request_gap_sec: float = 0.0,
                 exclude_titles: set[str] | None = None):
        ...
        self.pages = pages
        self.request_gap_sec = request_gap_sec
        self.exclude_titles = exclude_titles or set()
```

간격 헬퍼를 더한다.

```python
    async def _gap(self) -> None:
        """fmkorea 요청 사이 간격 — 0 이면 대기 없음 (정기 회차 동작 불변)."""
        if self.request_gap_sec:
            await asyncio.sleep(self.request_gap_sec)
```

`_discover` 의 페이지 루프에 간격 · 배제를 넣는다.
`first` 는 첫 요청 앞에서 기다리지 않기 위한 표시다.

```python
        per_kw, seen, first = [], set(), True
        for kw in self.search_keywords:
            results = []
            for page in range(1, self.pages + 1):
                url = self.search_url.format(keyword=quote(kw["keyword"]),
                                             target=kw["target"], page=page)
                if not first:
                    await self._gap()
                first = False
                try:
                    ...
```

같은 루프의 후보 수집 부분에 배제를 넣는다 (`seen` 에는 넣되 결과에서 뺀다).

```python
                    seen.add(post_url)
                    if title in self.exclude_titles:
                        continue            # 이미 적재된 글 — 본문 접촉 없이 건너뛴다
                    results.append((title, post_url))
```

`_process` 의 글 루프 앞에도 간격을 넣는다.

```python
        for i, (title, url) in enumerate(matched):
            if i:
                await self._gap()
            pub: tuple | None = None
```

- [ ] **Step 4: 통과 확인 · 회귀 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 전체 테스트**

Run: `uv run pytest -q`
Expected: PASS (DB · Airflow 없는 통합 테스트는 skip).

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(collect): fmkorea 요청 간격 · 기존 제목 배제 인자

여러 페이지를 한 번에 읽으면 요청이 몰리고, 이미 적재한 글까지 다시 받아
차단 이력이 있는 사이트에 불필요한 부담을 준다.
간격과 배제 집합을 어댑터가 직접 받도록 해 백필 회차의 접촉량을 신규분으로 좁힌다.

- request_gap_sec: 검색 페이지 사이 · 글 사이 대기 (기본 0 = 정기 회차 동작 불변)
- exclude_titles: 이미 적재된 제목을 후보에서 제외 · 본문 요청 자체를 막음
- max_posts 상한이 신규 글에만 쓰이도록 배제를 라운드로빈 앞에 배치

Refs: docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md §6 · §10
EOF
)"
```

---

### Task 3: 적재 블록 공용화 · 팩토리 인자 통로

**Files:**
- Modify: `src/bullet_in/collect_fmkorea.py:53-107`
- Test: `tests/test_collect_fmkorea.py`

**Interfaces:**
- Consumes: Task 2 의 `pages` · `request_gap_sec` · `exclude_titles`.
- Produces:
  `build_fmkorea_adapter(cfg, proxy, *, pages=1, request_gap_sec=0.0, exclude_titles=None, max_posts=None) -> FmkoreaAdapter`
  `persist(raw: list[RawItem], mart: MartStore) -> tuple[int, int]` — `(적재 수, 중복 수)` 를 돌려준다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_collect_fmkorea.py` 끝에 추가한다.

```python
def test_build_fmkorea_adapter_passes_backfill_options():
    a = build_fmkorea_adapter(_CFG, None, pages=3, request_gap_sec=1.5,
                              exclude_titles={"[BBC] 기존"}, max_posts=60)
    assert a.pages == 3
    assert a.request_gap_sec == 1.5
    assert a.exclude_titles == {"[BBC] 기존"}
    assert a.max_posts == 60


def test_build_fmkorea_adapter_defaults_match_regular_round():
    a = build_fmkorea_adapter(_CFG, None)
    assert (a.pages, a.request_gap_sec, a.exclude_titles) == (1, 0.0, set())
    assert a.max_posts == 15          # config 값 유지
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -k backfill_options -v`
Expected: FAIL — `TypeError: build_fmkorea_adapter() got an unexpected keyword argument 'pages'`.

- [ ] **Step 3: 팩토리 확장**

`src/bullet_in/collect_fmkorea.py` 의 `build_fmkorea_adapter` 를 바꾼다.

```python
def build_fmkorea_adapter(cfg: dict, proxy: str | None, *, pages: int = 1,
                          request_gap_sec: float = 0.0,
                          exclude_titles: set[str] | None = None,
                          max_posts: int | None = None) -> FmkoreaAdapter:
    """config 에서 fmkorea 소스 블록을 읽어 어댑터를 만든다 (factory 와 동일 인자).
    선택 인자는 백필 회차 전용이고, 기본값이면 정기 회차와 같은 어댑터가 된다."""
    s = next(x for x in cfg["sources"] if x["source_id"] == "fmkorea")
    c = s["config"]
    return FmkoreaAdapter(
        "fmkorea", c["search_url"], c["search_keywords"],
        item_selector=c.get("item_selector", "a.hx"),
        base_url=c.get("base_url", "https://www.fmkorea.com"),
        body_selector=c.get("body_selector", ".xe_content"),
        max_posts=max_posts if max_posts is not None else c.get("max_posts", 15),
        proxy=proxy, pages=pages, request_gap_sec=request_gap_sec,
        exclude_titles=exclude_titles)
```

- [ ] **Step 4: 적재 블록 분리**

같은 파일에 `persist` 를 더한다 (`main` 의 적재 부분을 그대로 옮긴다).

```python
def persist(raw: list[RawItem], mart: MartStore) -> tuple[int, int]:
    """수집 결과를 raw (Mongo) · mart (MariaDB) 에 적재한다.
    번역 · 분류 · 렌더는 하지 않는다 — 다음 정기 회차가 흡수한다."""
    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or "", canonical_url(it.url))
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    return mart.upsert(arts), stats["dup_count"]
```

`RawItem` import 를 더한다.

```python
from bullet_in.models import RawItem
```

`main` 에서 같은 일을 하던 부분을 호출로 바꾸고, 위로 올라가 있던 `sources` · `registry` 로딩 두 줄은 지운다 (`persist` 안으로 들어갔다).

```python
    adapter = build_fmkorea_adapter(cfg, proxy)
    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)  # 신규 0 이어도 접촉 스탬프 (15분 재접촉 방지)
    if not raw:
        log.info("fmkorea 보충 수집 — 신규 0 (새 글 없음 · 전부 스킵)")
        return
    n, dup = persist(raw, mart)
    log.info("fmkorea 보충 수집 완료 — 적재 %d · 중복 %d (번역 · 렌더는 다음 정기 회차)",
             n, dup)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_collect_fmkorea.py -v && uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/collect_fmkorea.py tests/test_collect_fmkorea.py
git commit -m "$(cat <<'EOF'
refactor(collect): fmkorea 어댑터 팩토리 · 적재 블록을 백필과 공용화

보충 수집과 소급 백필은 같은 config 블록을 읽고 같은 적재 경로를 쓴다.
설정 기본값과 적재 순서가 두 곳으로 갈라지지 않도록 팩토리와 적재를 한곳에 둔다.

- build_fmkorea_adapter: pages · request_gap_sec · exclude_titles · max_posts 선택 인자
- persist(): 해시 계산 · Mongo 적재 · mart upsert 를 묶어 (적재 수, 중복 수) 반환
- 기본값 호출은 정기 회차 어댑터와 동일 (회귀 테스트로 고정)

Refs: docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md §6
EOF
)"
```

---

### Task 4: 백필 스크립트

**Files:**
- Create: `src/bullet_in/backfill_fmkorea.py`
- Test: `tests/test_backfill_fmkorea.py`

**Interfaces:**
- Consumes: Task 3 의 `build_fmkorea_adapter` · `persist` · `collect_fmkorea` 의 `STATE_PATH` · `read_last_contact` · `write_last_contact` · `should_supplement` · `tunnel_alive`.
- Produces: `python -m bullet_in.backfill_fmkorea [--pages N] [--limit N] [--dry-run] [--force]`
  · `existing_titles(engine) -> set[str]` · `check_page_placeholder(search_url, pages) -> None`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_backfill_fmkorea.py` 를 만든다.

```python
import pytest
from sqlalchemy import create_engine, text
from bullet_in.backfill_fmkorea import check_page_placeholder, existing_titles


def test_page_placeholder_ok_when_present():
    check_page_placeholder("https://fm.test/s?kw={keyword}&page={page}", 3)  # 예외 없음


def test_page_placeholder_ok_when_single_page():
    check_page_placeholder("https://fm.test/s?kw={keyword}", 1)              # 예외 없음


def test_page_placeholder_rejects_multipage_without_placeholder():
    with pytest.raises(SystemExit):
        check_page_placeholder("https://fm.test/s?kw={keyword}", 3)


def test_existing_titles_returns_only_fmkorea_and_skips_null():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE articles (source_id TEXT, title_original TEXT)"))
        c.execute(text("INSERT INTO articles VALUES ('fmkorea', '[BBC] 아스날 1')"))
        c.execute(text("INSERT INTO articles VALUES ('fmkorea', NULL)"))
        c.execute(text("INSERT INTO articles VALUES ('bbc_sport', '[BBC] 다른 소스')"))
    assert existing_titles(engine) == {"[BBC] 아스날 1"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backfill_fmkorea.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.backfill_fmkorea'`.

- [ ] **Step 3: 스크립트 작성**

`src/bullet_in/backfill_fmkorea.py` 를 만든다.

```python
"""fmkorea 소급 백필 — 검색 페이징으로 차단 기간 누락 글 복원 (멱등).

정기 회차는 검색 1페이지만 읽으므로, 수집이 끊겼던 기간의 글은 페이지 밖으로
밀려나 다시 닿지 않는다. 이 스크립트는 여러 페이지를 읽되 이미 적재된 제목을
빼고 신규분만 받아온다. 적재까지만 하고 번역 · 분류 · 렌더는 다음 정기 회차가
흡수한다 (번역 전 상태 노출 방지).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_fmkorea --pages 3 --dry-run
    uv run python -m bullet_in.backfill_fmkorea --pages 3 --limit 5
    uv run python -m bullet_in.backfill_fmkorea --pages 3
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter, persist,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5   # backfill_journalist 와 같은 기준 (라이브 사이트 부담 회피)
DEFAULT_PAGES = 3       # 실측 2026-07-25 — 페이지당 20건 · 2페이지가 07-18 까지 도달
MAX_POSTS = 60          # 한 회차 신규 처리 상한 (키워드 3 × 페이지당 20)

_TITLES_SQL = text(
    "SELECT title_original FROM articles WHERE source_id='fmkorea'")


def existing_titles(engine: Engine) -> set[str]:
    """이미 적재된 fmkorea 글 제목 — 어댑터에 넘길 배제 집합.
    fmkorea 행의 title_original 은 게시글 제목 그대로라 후보 제목과 직접 비교된다."""
    with engine.connect() as c:
        return {t for (t,) in c.execute(_TITLES_SQL).all() if t}


def check_page_placeholder(search_url: str, pages: int) -> None:
    """자리표시 없이 여러 페이지를 돌면 같은 URL 을 반복 접촉하게 된다 — 미리 막는다."""
    if pages > 1 and "{page}" not in search_url:
        raise SystemExit(
            "config 의 fmkorea search_url 에 {page} 자리표시가 없다 "
            "— 같은 페이지 반복 접촉 위험 (--pages 1 로 실행하거나 config 를 고칠 것)")


async def main(pages: int, limit: int | None, dry_run: bool, force: bool) -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 백필 중단")
        return
    check_page_placeholder(src["config"]["search_url"], pages)

    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 백필 중단 (접촉 없음)")
        return

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now):
        log.info("fmkorea 백필 중단 — 마지막 접촉 %s (3h 이내 · --force 로 우회)", last)
        return

    known = existing_titles(engine)
    adapter = build_fmkorea_adapter(
        cfg, proxy, pages=pages, request_gap_sec=REQUEST_GAP_SEC,
        exclude_titles=known, max_posts=limit if limit is not None else MAX_POSTS)

    if dry_run:
        found = await adapter.discover()
        write_last_contact(STATE_PATH, now)
        log.info("[dry-run] 기존 %d건 배제 · 신규 후보 %d건 (페이지 %d · 상한 %d)",
                 len(known), len(found), pages, adapter.max_posts)
        for title, url in found:
            print(f"  {title}  {url}")
        return

    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)     # 신규 0 이어도 접촉 스탬프
    if not raw:
        log.info("fmkorea 백필 — 신규 0건 (기존 %d건 배제 후 남은 글 없음)", len(known))
        return
    n, dup = persist(raw, mart)
    log.info("fmkorea 백필 완료 — 적재 %d · 중복 %d (번역 · 렌더는 다음 정기 회차)", n, dup)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="fmkorea 소급 백필 (검색 페이징 · 멱등)")
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                    help=f"키워드당 읽을 검색 페이지 수 (기본 {DEFAULT_PAGES})")
    ap.add_argument("--limit", type=int, default=None,
                    help="신규 글 처리 상한 (소규모 검증용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="검색만 하고 글 본문 · DB 는 건드리지 않는다")
    ap.add_argument("--force", action="store_true", help="3시간 접촉 가드 우회")
    a = ap.parse_args()
    asyncio.run(main(a.pages, a.limit, a.dry_run, a.force))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_backfill_fmkorea.py -v && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/backfill_fmkorea.py tests/test_backfill_fmkorea.py
git commit -m "$(cat <<'EOF'
feat(collect): fmkorea 소급 백필 스크립트

IP 차단으로 수집이 끊겼던 2026-07-19 ~ 07-23 구간의 글은 검색 1페이지 밖에 있어
정기 회차로는 복원되지 않는다.
DB 에 있는 제목을 배제한 채 여러 페이지를 읽어 신규분만 적재하는 진입점을 만든다.

- 진입점: python -m bullet_in.backfill_fmkorea (--pages · --limit · --dry-run · --force)
- dry-run: 검색 페이지만 읽어 신규 후보를 세고 출력 · 글 본문 · DB 미접촉
- 배제 집합: articles 의 fmkorea title_original 로 재접촉 · 재적재 차단 (멱등)
- 가드 재사용: enabled 플래그 · 터널 선체크 · 3시간 접촉 간격 · 접촉 스탬프
- page 자리표시 누락 시 중단 — 같은 페이지 반복 접촉 방지

Refs: docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md §6 · §10
EOF
)"
```

---

### Task 5: 라이브 검증 · 런북

> **착수 중 수정 (2026-07-25 · 사용자 확정)**: dry-run 실측에서 config 광역 키워드 (온스테인 · de roche = title_content) 가
> 타 구단 완결 딜 · 옛 분석 글을 대량 동반하고, 라운드로빈이 창 구간 글을 뒤로 밀어내는 것이 확인됐다.
> 백필 스크립트에 `--keyword` · `--target` (키워드 직접 지정) 을 추가하고,
> 실행은 `--keyword 아스날 --keyword 디오망데 --keyword 알바레스 --keyword 크루피` (아스날 = 창 복원 · 선수 3명 = 활성 링크,
> 제목에 아스날 없는 글 커버) 로 한다. 접촉량은 검색 12건 (키워드 4 × 3페이지) + 본문 ~50건으로 갱신.
> 링크 선수 리스트의 시스템화 (파일 · 큐레이션 · 정기 수집 통합) 는 워치리스트 트랙 (spec 2026-07-04 §미해결) 으로 분리 유지.

**Files:**
- Create: `docs/runbook/2026-07-25-fmkorea-backfill-paging.md`
- 실행 대상: VM `/home/ubuntu/bullet-in` (운영 SoT)

**Interfaces:**
- Consumes: Task 4 의 진입점 · 옵션.
- Produces: 실측 수치 (신규 후보 수 · 적재 수 · 접촉 수) 와 PR 본문에 넣을 검증 결과.

**접촉 예산 (실행 전 사전 명시):**

- dry-run 1회 — 검색 요청 = 키워드 3 × 페이지 3 = **9건** · 간격 1.5초 · 소요 약 13초 · 글 본문 요청 0건.
- 소규모 적용 (`--limit 5`) — 검색 9건 + 글 본문 5건 = fmkorea **14건** · 원문 사이트 요청 최대 5건.
- 전체 적용 — 검색 9건 + 신규 글 수 (dry-run 실측치 · 상한 60) · 실측 예상 20건 안팎 → fmkorea 약 **29건** · 소요 약 45초.
- 세 단계 사이에는 3시간 접촉 가드가 걸리므로 `--force` 로 이어서 돌린다.
  감독하는 한 회차의 연속 작업으로 취급한다 — 2시간 규칙은 이 묶음과 정기 회차 사이에 적용한다.
- 시작 시점은 정기 회차 직후 (KST 0x:02 회차 완료 후 10분 안팎) 로 잡는다.
  다음 회차까지 약 3시간이 비어 정기 접촉과 겹치지 않고, 배제 집합도 가장 최신 상태다.
- 맥이 깨어 있어야 한다 (터널 필요) · 실행 전 `launchctl list | grep com.bulletin` 으로 터널 확인.

- [ ] **Step 1: VM 을 최신 main 으로 올린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && git fetch origin && git checkout feat/fmkorea-backfill-paging && git pull && uv sync"'
```

- [ ] **Step 2: dry-run 으로 누락 실측**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.backfill_fmkorea --pages 3 --dry-run --force"'
```

확인할 것 — 신규 후보 수 · 후보 제목의 발행 시기가 07-19 ~ 07-23 을 덮는지 · 이미 있는 글이 후보에 섞이지 않는지.
후보가 3페이지 끝까지 꽉 차 있으면 `--pages` 를 늘려 한 번 더 본다 (차단 구간보다 과거까지 닿았는지가 기준).

- [ ] **Step 3: 소규모 적용**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.backfill_fmkorea --pages 3 --limit 5 --force"'
```

확인할 것 — "적재 N · 중복 M" 로그 · 말머리 파싱 실패 경고 비율 · 원문 URL 해소 실패 건수.

- [ ] **Step 4: 멱등 확인**

Step 3 을 그대로 한 번 더 실행한다.
기대 — 방금 적재한 5건이 배제 집합에 들어가 후보에서 빠지고, 그다음 신규분이 처리된다 (같은 글 재적재 0).

- [ ] **Step 5: 전체 적용**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.backfill_fmkorea --pages 3 --force"'
```

- [ ] **Step 6: 적재 결과 확인**

VM 에서 발행일 분포를 다시 뽑아 07-19 ~ 07-23 이 채워졌는지 본다.

```sql
SELECT DATE(published_at), COUNT(*) FROM articles
WHERE source_id='fmkorea' AND published_at >= '2026-07-14'
GROUP BY 1 ORDER BY 1;
```

- [ ] **Step 7: 수렴 확인 (다음 정기 회차 후)**

다음 정기 회차가 돈 뒤 `title_ko IS NULL` 인 fmkorea 행이 0 인지 확인한다.
남아 있으면 enrich 만 재실행한다 (`docs/runbook/2026-07-19-enrich-only-pass.md`).

- [ ] **Step 8: 런북 작성**

`docs/runbook/2026-07-25-fmkorea-backfill-paging.md` 에 다음을 담는다.
컨벤션 §2.2 서식을 적용하고, 게시 전 humanize-korean 스킬 (fast) 문체 점검을 1회 통과시킨다.

- 언제 쓰는가 — 수집이 며칠 끊긴 뒤 소급 복원이 필요할 때.
- 사전 확인 — 맥 깨어 있음 · 터널 살아 있음 · 마지막 접촉 시각.
- 절차 — dry-run 으로 실측 → `--limit` 소규모 → 전체 → 발행일 분포 확인 → 다음 회차 수렴 확인.
- 접촉 예산 표 (위 수치) 와 `--pages` 를 늘릴 때의 판단 기준.
- 주의 — 백필 행은 과거 발행일 자리에 들어가므로 렌더 전에 수렴 패스가 필요하다.
- 실측 결과 (Step 2 · 5 · 6 의 수치) 를 그대로 남긴다.

- [ ] **Step 9: 커밋**

```bash
git add docs/runbook/2026-07-25-fmkorea-backfill-paging.md
git commit -m "$(cat <<'EOF'
docs(runbook): fmkorea 소급 백필 절차 · 접촉 예산

백필은 차단 이력이 있는 사이트를 한 회차에 여러 번 접촉하므로,
실행 전에 무엇을 확인하고 몇 건을 요청하는지 미리 적어 둔다.

- 절차: dry-run 실측 → limit 소규모 → 전체 → 발행일 분포 · 수렴 확인
- 접촉 예산: 단계별 요청 수 · 간격 · 예상 소요
- 판단 기준: 페이지를 더 파야 하는지 가르는 조건
- 실측: 2026-07-25 회차의 신규 후보 · 적재 · 중복 수치

Refs: docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md §6 · §10
EOF
)"
```

- [ ] **Step 10: VM 을 main 으로 복귀 (PR 머지 후)**

머지는 사용자가 직접 한다. 머지 확인 후 VM 을 브랜치에서 main 으로 되돌린다
— 정기 타이머가 이 체크아웃에서 돌므로, 브랜치가 삭제된 채 남아 있으면 pull 이 깨진다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && git checkout main && git pull && uv sync"'
```

---

## 완료 기준

- `uv run pytest -q` 통과 · 기존 fmkorea 테스트 회귀 없음.
- 기본값 호출 (`build_fmkorea_adapter(cfg, proxy)`) 이 정기 회차와 동일한 어댑터를 만든다는 테스트가 있다.
- dry-run 이 글 본문을 한 건도 받지 않는다 (로그 · respx 호출 수로 확인).
- 같은 백필 명령을 두 번 돌려도 같은 글이 다시 적재되지 않는다.
- VM 에서 07-19 ~ 07-23 발행 fmkorea 행이 늘었고, 다음 정기 회차 후 한국어 필드가 채워진다.
- 런북에 접촉 예산과 실측 수치가 남았다.

## 하지 않는 것

- 번역 · 요약 · 분류 · 렌더 (다음 정기 회차가 흡수).
- 정기 회차의 `max_posts` · 주기 · 키워드 변경.
- 백필 자동화 (스케줄 등록) — 필요할 때 손으로 돌리는 1회성 도구로 둔다.
- 온스테인 X 소스 (spec §5 · 다음 PR).
- `[공홈]` 말머리 글의 발견 단계 사전 제외 — 지금처럼 본문 단계에서 버린다 (회차당 두어 건의 낭비는 감수).
