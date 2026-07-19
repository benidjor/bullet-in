# 발행 시각 정확화 구현 계획 (2026-07-20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서빙 "최신순" 이 실제 발행 시각 순이 되도록 어댑터 추출 · 폴백 · 정밀도 정렬을 구현한다.

**Architecture:** 트랙 A (Task 1~6 · PR 1) 는 발행 시각 추출과 폴백 · 동률 결정화, 트랙 B (Task 7~9 · PR 2) 는 정밀도 컬럼 · 수집순 보간 · 표시.
spec: `docs/superpowers/specs/2026-07-20-published-at-accuracy-design.md`.

**Tech Stack:** Python 3.11 · BeautifulSoup · dateutil · pydantic v2 · respx (테스트 모킹) · Jinja2.

## Global Constraints

- 커밋 본문은 도입 1~2문장 + 명사형 불릿 (컨벤션 §1.1) · 트레일러는 실제 작업 모델 (§1.3).
- 발행 시각은 부가 정보 — 추출의 어떤 실패도 수집 · 번역 경로를 막지 않는다 (None → 폴백).
- 모든 datetime 은 UTC aware 로 정규화 후 비교한다 (naive 값은 UTC 간주 — spec §6).
- 트랙 B 의 `published_precision` 값은 `'time'` | `'day'` 두 가지뿐 (NULL = `'time'` 취급).
- 클라이언트 정렬 계약: `data-published` (= `_published_iso`) 는 **정렬용 유효 시각**이다
— app.js `sortCards()` 가 이 값으로 재정렬하므로 서버 정렬 키와 항상 같은 값이어야 한다.

---

## 트랙 A — 추출 · 폴백 · 동률 결정화 (PR 1)

### Task 1: `meta.extract_published_at` 순수 함수

**Files:**
- Modify: `src/bullet_in/adapters/meta.py` (파일 끝에 추가)
- Test: `tests/test_published_extraction.py` (신규)

**Interfaces:**
- Produces: `extract_published_at(html: str) -> tuple[datetime, str] | None`
— (UTC aware datetime, precision `'time'`|`'day'`) 또는 None. Task 2 · 3 이 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_published_extraction.py
from datetime import datetime, timezone
from bullet_in.adapters.meta import extract_published_at

LD_TOP = ('<script type="application/ld+json">'
          '{"@type":"NewsArticle","datePublished":"2026-07-19T14:30:00+01:00"}'
          '</script>')
LD_GRAPH = ('<script type="application/ld+json">'
            '{"@graph":[{"@type":"WebPage"},'
            '{"@type":"NewsArticle","datePublished":"2026-07-19T09:15:00Z"}]}'
            '</script>')
LD_BROKEN = '<script type="application/ld+json">{broken json</script>'
META_TAG = ('<meta property="article:published_time" '
            'content="2026-07-19T07:40:00+00:00">')
TIME_TAG = '<time datetime="2026-07-18T22:00:00Z">yesterday</time>'

def test_jsonld_top_level_normalizes_to_utc():
    dt, prec = extract_published_at(f"<html><head>{LD_TOP}</head></html>")
    assert dt == datetime(2026, 7, 19, 13, 30, tzinfo=timezone.utc)  # +01:00 → UTC
    assert prec == "time"

def test_jsonld_graph_nested():
    dt, prec = extract_published_at(f"<html>{LD_GRAPH}</html>")
    assert dt == datetime(2026, 7, 19, 9, 15, tzinfo=timezone.utc)
    assert prec == "time"

def test_meta_tag_fallback_when_no_jsonld():
    dt, prec = extract_published_at(f"<html><head>{META_TAG}</head></html>")
    assert dt == datetime(2026, 7, 19, 7, 40, tzinfo=timezone.utc)

def test_time_tag_last_fallback():
    dt, _ = extract_published_at(f"<html><body>{TIME_TAG}</body></html>")
    assert dt == datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc)

def test_day_only_string_gives_day_precision_utc_midnight():
    html = ('<script type="application/ld+json">'
            '{"datePublished":"2026-07-19"}</script>')
    dt, prec = extract_published_at(html)
    assert dt == datetime(2026, 7, 19, tzinfo=timezone.utc)
    assert prec == "day"

def test_broken_jsonld_skipped_meta_used():
    dt, _ = extract_published_at(f"<html>{LD_BROKEN}{META_TAG}</html>")
    assert dt == datetime(2026, 7, 19, 7, 40, tzinfo=timezone.utc)

def test_none_when_nothing_found():
    assert extract_published_at("<html><body><p>hi</p></body></html>") is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_published_extraction.py -q`
Expected: ImportError (extract_published_at 부재).

- [ ] **Step 3: 최소 구현**

`meta.py` 상단 import 에 추가: `from datetime import datetime, timezone` · `from dateutil import parser as dtparser`.
파일 끝에:

```python
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

_TIME_COMPONENT_RE = re.compile(r"[T ]\d{1,2}:")

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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_published_extraction.py -q`
Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/meta.py tests/test_published_extraction.py
git commit -m "feat(adapters): extract_published_at — JSON-LD·meta·time 3단 발행 시각 추출

정렬 정확화 (spec 2026-07-20 §3.1) 의 추출 계층.

- JSON-LD datePublished 재귀 수집 (@graph·리스트, strict=False 재시도 기존 패턴)
- 폴백 순서: meta article:published_time → time[datetime]
- naive = UTC 간주·시각 성분 부재 = 'day' 정밀도

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 2: HtmlAdapter 배선

**Files:**
- Modify: `src/bullet_in/adapters/html.py:58-77`
- Test: `tests/test_html_adapter.py` (기존 파일 끝에 추가)

**Interfaces:**
- Consumes: `extract_published_at(html)` (Task 1).
- Produces: `raw_payload["published"]` (ISO 문자열) · `raw_payload["published_precision"]` — Task 4 · 7 이 소비.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_html_adapter.py` 끝에 추가)

```python
ART_WITH_PUB = ('<html><head><script type="application/ld+json">'
                '{"@type":"NewsArticle","datePublished":"2026-07-19T10:00:00Z"}'
                '</script></head><body><article><p>Body text.</p></article></body></html>')

@respx.mock
def test_html_body_path_extracts_published():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(200, text=ART_WITH_PUB))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", body_selector="article")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["published"] == "2026-07-19T10:00:00+00:00"
    assert items[0].raw_payload["published_precision"] == "time"

@respx.mock
def test_html_thumbnail_only_path_extracts_published():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(200, text=ART_WITH_PUB))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["published"] == "2026-07-19T10:00:00+00:00"

@respx.mock
def test_html_no_published_leaves_payload_clean():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(
        200, text="<html><body><article><p>x</p></article></body></html>"))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", body_selector="article")
    items = asyncio.run(a.fetch())
    assert "published" not in items[0].raw_payload
```

주의: 기존 파일의 import (`asyncio` · `respx` · `httpx` · `HtmlAdapter`) 를 재사용 — 새로 추가하지 않는다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py -q`
Expected: 신규 3건 FAIL (`KeyError: 'published'` 계열), 기존 테스트는 PASS 유지.

- [ ] **Step 3: 구현**

`html.py` fetch 의 meta import 에 `extract_published_at` 추가:

```python
from bullet_in.adapters.meta import (extract_og_image, extract_body_images,
                                     extract_authors, extract_published_at)
```

`body_selector` 분기 (`payload["authors"] = …` 다음 줄) 와 `thumbnail_only` 분기 (`payload["image_url"] = …` 다음 줄) 각각에:

```python
                        pub = extract_published_at(rb.text)
                        if pub:
                            payload["published"] = pub[0].isoformat()
                            payload["published_precision"] = pub[1]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py -q`
Expected: 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/html.py tests/test_html_adapter.py
git commit -m "feat(adapters): HtmlAdapter 기사 페이지에서 발행 시각 추출

이미 fetch 하는 기사 페이지 (body_selector·thumbnail_only 경로) 에서
extract_published_at 을 호출해 payload 에 싣는다 (spec §3.2).

- 성공 시 payload published (ISO)·published_precision
- 미발견·실패 시 키 자체를 넣지 않음 (폴백은 pipeline 몫)

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: fmkorea 경로별 발행 시각

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`_extract_original_url` 위에 헬퍼 추가 · `_process` 수정)
- Test: `tests/test_fmkorea_adapter.py` (끝에 추가)

**Interfaces:**
- Consumes: `extract_published_at` (Task 1).
- Produces: `_post_published(html) -> datetime | None` · `raw_payload["published"]`/`["published_precision"]`.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_fmkorea_adapter.py` 끝에 추가)

```python
from datetime import datetime, timezone
from bullet_in.adapters.fmkorea import _post_published

RD_HD = ('<div class="rd_hd"><div class="board clear">'
         '<span class="date m_no">2026.06.11 10:04</span></div></div>')

def test_post_published_parses_kst_to_utc():
    html = f'<html><body>{RD_HD}</body></html>'
    assert _post_published(html) == datetime(2026, 6, 11, 1, 4, tzinfo=timezone.utc)

def test_post_published_none_when_absent():
    assert _post_published("<html><body></body></html>") is None

@respx.mock
def test_fmkorea_free_path_uses_original_published():
    art = ('<html><head><script type="application/ld+json">'
           '{"datePublished":"2026-07-19T08:00:00Z"}</script></head>'
           '<body><article><p>Arsenal news.</p></article></body></html>')
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(
        200, text=f'{RD_HD}<div class="xe_content"><p>본문.</p><p>https://ex.test/a</p></div>'))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=art))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    assert it.raw_payload["published"] == "2026-07-19T08:00:00+00:00"
    assert it.raw_payload["published_precision"] == "time"

@respx.mock
def test_fmkorea_paywalled_path_uses_post_time():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=2">[디 애슬레틱] 아스날</a>'))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(
        200, text=f'{RD_HD}<div class="xe_content"><p>본문.</p>'
                  '<p>https://www.nytimes.com/athletic/9/b</p></div>'))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text="<html></html>"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    it = asyncio.run(a.fetch())[0]
    # KST 2026.06.11 10:04 → UTC 01:04
    assert it.raw_payload["published"] == "2026-06-11T01:04:00+00:00"
    assert it.raw_payload["published_precision"] == "time"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q`
Expected: ImportError (`_post_published` 부재).

- [ ] **Step 3: 구현**

`fmkorea.py` 상단 import 수정: `from datetime import datetime, timezone, timedelta` ·
meta import 에 `extract_published_at` 추가 (Step 4 의 `_process` 안 import 라인).
`_extract_original_url` 위에:

```python
_KST = timezone(timedelta(hours=9))
_POST_DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})")

def _post_published(html: str) -> datetime | None:
    """fmkorea 게시 시각 — 실측 (2026-07-20) `.rd_hd .date` 'YYYY.MM.DD HH:MM' KST → UTC.
    목록 위젯의 .date 다중 매칭 (실측 7개) 이 있어 반드시 .rd_hd 스코프."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".rd_hd .date")
    m = _POST_DATE_RE.search(el.get_text(strip=True)) if el else None
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=_KST).astimezone(timezone.utc)
```

`_process` 수정 — 분기 진입 전 `pub: tuple | None = None` 초기화,
무료 분기의 `ro` fetch 성공 블록 (`images = extract_body_images(…)` 다음) 에 `pub = extract_published_at(ro.text)`,
両분기 합류 후 (RawItem 생성 직전):

```python
            if pub is None:
                post_dt = _post_published(html)
                pub = (post_dt, "time") if post_dt else None
            extra = ({"published": pub[0].isoformat(), "published_precision": pub[1]}
                     if pub else {})
```

RawItem 의 `raw_payload={…}` 에 `**extra` 병합:

```python
                raw_payload={"title": title, "body": body, "lang": lang,
                             "outlet": outlet, "journalist": journalist,
                             "image_url": image, "images": images, **extra}))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -q`
Expected: 전체 PASS (기존 36 + 신규 4).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(adapters): fmkorea 경로별 발행 시각 — 원문 추출·게시 시각 폴백

무료 경로는 원문 페이지 발행 시각, 페이월·퍼가기·실패 경로는 게시
시각 (.rd_hd .date, KST 실측) 을 쓴다 (spec §3.3).

- _post_published: .rd_hd 스코프 (목록 위젯 .date 7개 오매칭 방어)·KST→UTC
- 원문 추출 실패 시에도 게시 시각 폴백 (수집 시각보다 정확)

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: pipeline 폴백 = fetched_at · 미래 시각 방어

**Files:**
- Modify: `src/bullet_in/pipeline.py:20-25` (`_published`) · `:86` (호출부)
- Test: `tests/test_pipeline.py` (기존 파일 끝에 추가 — `_published` 기존 테스트가 있으면 시그니처에 맞춰 수정)

**Interfaces:**
- Consumes: `raw_payload["published"]` (Task 2 · 3) · `RawItem.fetched_at`.
- Produces: `_published(payload: dict, fetched_at: datetime) -> datetime` — 항상 UTC aware.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_pipeline.py` 끝에 추가)

```python
from datetime import datetime, timezone, timedelta
from bullet_in.pipeline import _published

_FETCH = datetime(2026, 7, 19, 13, 36, tzinfo=timezone.utc)

def test_published_uses_payload_value():
    assert _published({"published": "2026-07-19T08:00:00+00:00"}, _FETCH) == \
        datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)

def test_published_fallback_is_fetched_at_not_now():
    assert _published({}, _FETCH) == _FETCH

def test_published_naive_value_treated_as_utc():
    assert _published({"published": "2026-07-19T08:00:00"}, _FETCH) == \
        datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)

def test_published_future_beyond_1h_discarded_to_fetched_at():
    future = (_FETCH + timedelta(hours=2)).isoformat()
    assert _published({"published": future}, _FETCH) == _FETCH
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: TypeError (인자 1개 시그니처) 또는 assert 실패.

- [ ] **Step 3: 구현**

```python
def _published(payload: dict, fetched_at: datetime) -> datetime:
    """발행 시각 — payload 추출값 우선, 실패 시 수집 시각 폴백 (처리 시각 now() 아님).
    naive 는 UTC 간주 · fetched_at+1h 초과 미래값은 오파싱으로 보고 폴백."""
    raw = payload.get("published") or payload.get("created_at")
    try:
        dt = dtparser.parse(raw)
    except (TypeError, ValueError):
        return fetched_at
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    if dt > fetched_at + timedelta(hours=1):
        return fetched_at
    return dt
```

상단 import 에 `timedelta` 추가 (`from datetime import datetime, timezone, timedelta`).
호출부 (`to_articles` 내부):

```python
            published_at=_published(item.raw_payload, item.fetched_at), fetched_at=item.fetched_at,
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest tests/test_pipeline.py -q && uv run pytest -q`
Expected: 전체 PASS (기존 `_published` 구시그니처 테스트가 있으면 이 시그니처로 갱신).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/pipeline.py tests/test_pipeline.py
git commit -m "fix(pipeline): 발행 시각 폴백 now()→fetched_at·미래 시각 방어

처리 시각 폴백이 회차 내 전 행 동률을 만들어 적재 순서가 노출
순서가 되던 원인 축 (spec §1·§3.4).

- 폴백 = 수집 시각 (의미 고정·소스별 fetch 순서 보존)
- naive = UTC 간주·fetched_at+1h 초과 미래값 폐기 (오파싱 방어)

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 5: 정렬 동률 결정화 · 서빙 SELECT 에 fetched_at

**Files:**
- Modify: `src/bullet_in/serve/render.py:451-454` (`_sorted_latest`) · `src/bullet_in/run.py:133-135` (SELECT)
- Test: `tests/test_serve_render.py` (기존 파일 끝에 추가)

**Interfaces:**
- Consumes: row dict 의 `published_at` · `fetched_at` (naive UTC — DB 왕복 값).
- Produces: `_sorted_latest` 정렬 키 `(published_at, fetched_at)` 내림차순.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from datetime import datetime
from bullet_in.serve.render import _sorted_latest

def test_sorted_latest_ties_broken_by_fetched_at():
    same = datetime(2026, 7, 19, 13, 37, 2)
    rows = [
        {"content_hash": "sky", "published_at": same,
         "fetched_at": datetime(2026, 7, 19, 13, 36, 28)},
        {"content_hash": "fmk", "published_at": same,
         "fetched_at": datetime(2026, 7, 19, 13, 36, 36)},
    ]
    assert [r["content_hash"] for r in _sorted_latest(rows)] == ["fmk", "sky"]

def test_sorted_latest_published_still_primary():
    rows = [
        {"content_hash": "old", "published_at": datetime(2026, 7, 18, 9, 0),
         "fetched_at": datetime(2026, 7, 19, 23, 0)},
        {"content_hash": "new", "published_at": datetime(2026, 7, 19, 9, 0),
         "fetched_at": datetime(2026, 7, 19, 1, 0)},
    ]
    assert [r["content_hash"] for r in _sorted_latest(rows)] == ["new", "old"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: 첫 테스트 FAIL (동률 시 입력 순서 유지 → "sky" 먼저).

- [ ] **Step 3: 구현**

```python
def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles,
                  key=lambda a: (a.get("published_at") or datetime.min,
                                 a.get("fetched_at") or datetime.min),
                  reverse=True)
```

`run.py` SELECT 에 `fetched_at` 추가:

```python
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,transfer_stage,tier,"
            "confidence_score,published_at,fetched_at "
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest -q`
Expected: 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py tests/test_serve_render.py
git commit -m "feat(serve): 최신순 동률을 fetched_at 으로 결정화

published_at 동률 (폴백 행·기존 데이터) 시 적재 순서가 노출되던
것을 수집 시각 보조 키로 결정화한다 (spec §3.4).

- _sorted_latest 키 (published_at, fetched_at) 내림차순
- run.py 서빙 SELECT 에 fetched_at 추가 (render 행 계약)

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 6: 트랙 A 검증 · PR 1

**Files:**
- 없음 (검증 · PR)

- [ ] **Step 1: 전체 스위트**

Run: `uv run pytest -q`
Expected: 전체 PASS (기준 443+ 신규분).

- [ ] **Step 2: 라이브 스팟 — 실기사 추출 확인** (skysports · bbc 각 1건, fmkorea 는 접촉 없이 저장 실DOM 재사용)

```bash
uv run python - <<'EOF'
import httpx
from bullet_in.adapters.meta import extract_published_at
for url in ("https://www.skysports.com/football/news/11661/13564260/",
            "https://www.bbc.com/sport/football/articles/c93kqjy1lxko"):
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20,
                      headers={"User-Agent": "bullet-in/0.1"})
        print(url[:50], "→", extract_published_at(r.text))
    except httpx.HTTPError as e:
        print(url[:50], "→ fetch 실패", e)
EOF
```

Expected: 두 건 모두 `(datetime UTC, 'time')` — None 이면 해당 사이트 마크업 재확인 후 함정 기록.
(bbc URL 은 죽었을 수 있음 — 그 경우 서빙 중인 임의 bbc_sport 기사 URL 로 대체.)

- [ ] **Step 3: 재렌더 순서 확인** — 기존 DB (published_at 동률 4건) 에서 fmkorea 가 최상단으로 오는지

```bash
set -a; source .env; set +a
uv run python -m bullet_in.run --serve-only 2>/dev/null || uv run python - <<'EOF'
# run.py 에 serve-only 옵션이 없으므로 write_site 직접 호출
import os, json
from sqlalchemy import create_engine, text
from bullet_in.serve.render import write_site, _sorted_latest
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
import yaml
engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
        "summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,transfer_stage,tier,"
        "confidence_score,published_at,fetched_at FROM articles")).mappings().all()]
top = _sorted_latest(rows)[:4]
for r in top:
    print(r["source_id"], r["published_at"], r["fetched_at"], (r.get("title_ko") or r["title_original"])[:40])
EOF
```

Expected: 첫 행 = fmkorea (fetched 13:36:36) — 스크린샷 사고의 즉시 교정 확인.

- [ ] **Step 4: PR 1 생성 · 머지**

컨벤션 7섹션 본문 (`--body-file`) 으로 `feat/published-at-accuracy` → main. squash 머지 후 main 동기화.
제목: `feat(collect·serve): 발행 시각 추출·폴백 fetched_at·동률 결정화 — 정렬 정확화 트랙 A`

---

## 트랙 B — 정밀도 컬럼 · 보간 정렬 · 표시 (PR 2)

트랙 B 는 PR 1 머지 후 main 에서 새 브랜치 (`feat/published-precision`) 로 시작한다 (분기 전 `origin/main..main` 확인).

### Task 7: published_precision 영속화

**Files:**
- Modify: `src/bullet_in/storage/schema.sql` (ALTER 블록) · `src/bullet_in/models.py` (Article) ·
  `src/bullet_in/pipeline.py` (Article 생성) · `src/bullet_in/storage/mariadb.py` (upsert)
- Test: `tests/test_pipeline.py` (끝에 추가)

**Interfaces:**
- Consumes: `raw_payload["published_precision"]` (Task 2 · 3).
- Produces: `Article.published_precision: str | None` · `articles.published_precision` 컬럼 — Task 8 이 소비.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_pipeline.py` — 기존 to_articles 테스트의 픽스처 생성 방식을 그대로 따라 작성; 아래는 형태 예시로, 기존 헬퍼 시그니처에 맞춘다)

```python
def test_to_articles_carries_published_precision():
    item = RawItem(source_id="skysports", source_type="html",
                   url="https://ex.test/a", fetched_at=_FETCH,
                   raw_payload={"title": "Arsenal sign", "body": "b",
                                "published": "2026-07-19T08:00:00+00:00",
                                "published_precision": "day"})
    arts, _ = to_articles([item], SOURCES_FIXTURE, registry=None)
    assert arts[0].published_precision == "day"

def test_to_articles_precision_none_when_absent():
    item = RawItem(source_id="skysports", source_type="html",
                   url="https://ex.test/a", fetched_at=_FETCH,
                   raw_payload={"title": "Arsenal sign", "body": "b"})
    arts, _ = to_articles([item], SOURCES_FIXTURE, registry=None)
    assert arts[0].published_precision is None
```

(`SOURCES_FIXTURE` · import 는 기존 테스트 파일의 것을 재사용.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: pydantic ValidationError 또는 AttributeError (필드 부재).

- [ ] **Step 3: 구현**

`models.py` Article 에 (published_at 근처):

```python
    published_precision: str | None = None
```

`schema.sql` ALTER 블록 끝에:

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_precision VARCHAR(4);
```

`pipeline.py` Article 생성에 (published_at 라인 인접):

```python
            published_precision=item.raw_payload.get("published_precision"),
```

`mariadb.py` upsert — INSERT 컬럼 목록 `published_at,fetched_at,revision` → `published_at,published_precision,fetched_at,revision`,
VALUES 목록도 `:published_at,:published_precision,:fetched_at,:revision`,
ON DUPLICATE 에 `published_at=VALUES(published_at),` 다음 줄로 `published_precision=VALUES(published_precision),` 추가.
upsert 파라미터 dict 생성부가 model_dump 기반인지 확인 — 명시 dict 면 `"published_precision": a.published_precision` 추가.

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest -q`
Expected: 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/models.py src/bullet_in/storage/schema.sql \
        src/bullet_in/storage/mariadb.py src/bullet_in/pipeline.py tests/test_pipeline.py
git commit -m "feat(storage): published_precision 영속화 — time/day 정밀도 컬럼

day 정밀도 기사를 정렬·표시에서 구분하기 위한 저장 계층 (spec §4.1).

- articles.published_precision VARCHAR(4)·멱등 ALTER·nullable
- pipeline 전달·upsert VALUES 갱신 (revision 시 최신값)
- NULL = 'time' 취급 (기존 행·폴백 행 무영향)

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 8: 수집순 보간 정렬 · day 표시

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`_sort_ts` 신설 · `_sorted_latest` · `_decorate`) · `src/bullet_in/run.py` (SELECT 에 published_precision)
- Test: `tests/test_serve_render.py` (Task 5 와 동일 파일) 끝에 추가

**Interfaces:**
- Consumes: row 의 `published_at` · `fetched_at` · `published_precision` (Task 7).
- Produces: `_sort_ts(row) -> tuple[datetime, datetime]` (정렬 키 · [0] 이 유효 시각) ·
  `_published_iso` = 유효 시각 ISO (data-published 계약) · `_when` day 표시.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from bullet_in.serve.render import _sort_ts, _fmt_day_only

def test_sort_ts_day_interpolates_by_fetched_within_day():
    row = {"published_at": datetime(2026, 7, 19),        # day 00:00
           "fetched_at": datetime(2026, 7, 19, 11, 2),
           "published_precision": "day"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 11, 2)

def test_sort_ts_day_clamps_late_fetch_into_published_day():
    row = {"published_at": datetime(2026, 7, 19),
           "fetched_at": datetime(2026, 7, 22, 9, 0),    # 수일 뒤 수집
           "published_precision": "day"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 23, 59, 59)

def test_sort_ts_time_precision_passthrough():
    row = {"published_at": datetime(2026, 7, 19, 14, 30),
           "fetched_at": datetime(2026, 7, 19, 15, 0),
           "published_precision": "time"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 14, 30)

def test_sort_ts_null_precision_passthrough():
    row = {"published_at": datetime(2026, 7, 19, 14, 30),
           "fetched_at": datetime(2026, 7, 19, 15, 0)}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 14, 30)

def test_fmt_day_only_current_year_omits_year():
    now = datetime(2026, 7, 20)
    assert _fmt_day_only(datetime(2026, 7, 19), now) == "7월 19일"
    assert _fmt_day_only(datetime(2025, 7, 19), now) == "2025년 7월 19일"
```

`_decorate` day 표시 · data-published 계약 (기존 `_decorate` 테스트 픽스처 방식 재사용):

```python
def test_decorate_day_precision_shows_date_not_relative():
    now = datetime(2026, 7, 20, 12, 0)
    row = {"published_at": datetime(2026, 7, 19),
           "fetched_at": datetime(2026, 7, 19, 11, 2),
           "published_precision": "day", "tier": 2}
    d = _decorate(row, {}, now)
    assert d["_when"] == "7월 19일"                       # "N시간 전" 아님
    assert d["_published_iso"] == "2026-07-19T11:02:00"   # 유효 시각 (보간) — data-published 계약
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: ImportError (`_sort_ts` · `_fmt_day_only` 부재).

- [ ] **Step 3: 구현**

`render.py` — 상단 import 에 `timedelta` 추가 (`from datetime import datetime, timedelta`).
`humanize_when` 아래에:

```python
def _fmt_day_only(dt: datetime, now: datetime) -> str:
    """day 정밀도 표시 — 상대 시각 대신 날짜만 (실제보다 정밀한 척 금지)."""
    if dt.year == now.year:
        return f"{dt.month}월 {dt.day}일"
    return f"{dt.year}년 {dt.month}월 {dt.day}일"


def _sort_ts(row: dict) -> tuple[datetime, datetime]:
    """정렬 키. day 정밀도는 fetched_at 을 발행일 [00:00, 23:59:59] 로 클램프해 보간."""
    pub = row.get("published_at") or datetime.min
    fet = row.get("fetched_at") or datetime.min
    if row.get("published_precision") == "day" and pub is not datetime.min:
        start = pub.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return (min(max(fet, start), end), fet)
    return (pub, fet)
```

`_sorted_latest` 를 `_sort_ts` 사용으로:

```python
def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles, key=_sort_ts, reverse=True)
```

`_decorate` 의 published 블록 교체:

```python
    pub = row.get("published_at")
    if pub and row.get("published_precision") == "day":
        a["_when"] = _fmt_day_only(pub, now)
    else:
        a["_when"] = humanize_when(pub, now) if pub else ""
    a["_published_iso"] = _sort_ts(row)[0].isoformat() if pub else ""
    a["_date"] = fmt_date(pub) if pub else ""
```

`run.py` SELECT: `…,published_at,published_precision,fetched_at `.

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest -q`
Expected: 전체 PASS. Task 5 의 동률 테스트도 `_sort_ts` 경유로 계속 성립.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py tests/test_serve_render.py
git commit -m "feat(serve): day 정밀도 수집순 보간·날짜만 표시

발행 시각이 날짜뿐인 기사를 그날 카드 사이에 수집 시점으로 보간
배치하고, 상대 시각 대신 날짜만 표시한다 (spec §4.2·§4.3 채택 결정).

- _sort_ts: fetched_at 을 발행일 [00:00, 23:59:59] 클램프
- data-published = 유효 시각 (app.js 재정렬과 서버 순서 일치 계약)
- _fmt_day_only: 당해 연도 생략

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 9: 트랙 B 검증 · PR 2

**Files:**
- 없음 (검증 · PR)

- [ ] **Step 1: 전체 스위트 + 스키마 멱등 적용 확인**

```bash
uv run pytest -q
set -a; source .env; set +a
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
m = MartStore(create_engine(os.environ["MARIADB_URL"]))
m.ensure_schema()
from sqlalchemy import text
with m.engine.connect() as c:
    print([r[0] for r in c.execute(text("SHOW COLUMNS FROM articles LIKE 'published_precision'"))])
EOF
```

Expected: 전체 PASS · `['published_precision']`.

- [ ] **Step 2: 재렌더 스모크** — Task 6 Step 3 스니펫 재실행 (SELECT 에 published_precision 추가) · 순서 불변 확인 (기존 행 전부 NULL = time 취급이라 트랙 A 순서와 동일해야 함).

- [ ] **Step 3: PR 2 생성 · 머지**

컨벤션 7섹션 본문으로 `feat/published-precision` → main. squash 머지.
제목: `feat(serve): published_precision — day 정밀도 보간 정렬·날짜 표시 — 정렬 정확화 트랙 B`

## Self-Review 결과 (계획 작성 시 반영)

- spec §3.2 의 thumbnail_only 경로도 기사 페이지를 fetch 하므로 추출 대상에 포함 (Task 2) — "미fetch 경로 비목표" 는 bbc_gossip 라운드업처럼 상세 방문이 없는 구성만 해당.
- app.js `data-published` 재정렬이 서버 보간 순서를 되돌리는 함정 → `_published_iso` = 유효 시각 계약으로 해소 (Task 8, Global Constraints).
- run.py 서빙 SELECT 에 `fetched_at` (Task 5) · `published_precision` (Task 8) 추가 누락 주의 — render 행 계약.
