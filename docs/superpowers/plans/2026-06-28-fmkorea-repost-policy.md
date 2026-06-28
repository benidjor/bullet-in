# fmkorea 퍼가기 금지 정책 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fmkorea '축구 소식통'의 '퍼가기 금지' 글을 감지해 번역 본문을 복제하지 않고, 본문에 박힌 원 출처 링크와 그 og 메타 기반 한국어 요약으로 대체 서빙한다.

**Architecture:** `adapters/fmkorea.py` 단일 어댑터에 순수 헬퍼(감지·URL 추출)와 og fetch를 추가하고 `fetch()` 분기를 확장한다. 분기①(원문 대체)은 제목을 fmkorea 한국어 헤드라인으로, 요약 입력을 원문 og:description으로 두어 **기존 ko 경로에 그대로 올라탄다** → 스키마·enrich·models·pipeline 무변경.

**Tech Stack:** Python 3.11, httpx(AsyncClient), BeautifulSoup4, pydantic v2(RawItem), pytest+respx.

## Global Constraints

- 변경 파일은 `src/bullet_in/adapters/fmkorea.py`, `config/sources.yaml`, `tests/test_fmkorea_adapter.py`에 국한. 스키마·`enrich.py`·`models.py`·`pipeline.py` 무변경.
- 차단글의 fmkorea **번역 본문(body)은 저장하지 않는다**(raw_payload에도 미포함).
- 모든 fmkorea RawItem은 `raw_payload["lang"] == "ko"`.
- 퍼가기 금지 표식 문자열(verbatim): `퍼가기가 금지된 글입니다`.
- 커밋 트레일러(verbatim): `Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>`.
- 테스트 실행: `uv run pytest -q`. 단일: `uv run pytest tests/test_fmkorea_adapter.py::<name> -v`.

---

### Task 1: 퍼가기 금지 감지 + 원문 URL 추출 헬퍼

순수 함수 2개. 모듈 상단 헬퍼로 추가(기존 `_matches`/`_body_text` 옆).

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (모듈 레벨 헬퍼 추가)
- Test: `tests/test_fmkorea_adapter.py` (신규 테스트 함수 추가)

**Interfaces:**
- Consumes: `BeautifulSoup`(이미 import됨)
- Produces:
  - `_REPOST_MARK: str = "퍼가기가 금지된 글입니다"`
  - `_is_repost_blocked(html: str) -> bool`
  - `_extract_original_url(html: str, body_selector: str) -> str | None` — `body_selector` 요소 내부에서 첫 외부 http(s) URL(평문 텍스트 또는 `<a href>`), `fmkorea.com` 도메인 제외. 없으면 `None`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가:

```python
from bullet_in.adapters.fmkorea import _is_repost_blocked, _extract_original_url

BLOCKED = (
    '<div class="xe_content"><p>유벤투스가 루쿠미를 원한다.</p><p></p>'
    '<p>https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366</p></div>'
    '<!--AfterDocument(1,2)--></article>'
    '<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
    '아이디/아이피가 자동으로 표기됩니다]</strong>'
)
NORMAL = '<div class="xe_content"><p>일반 글 본문.</p></div>'

def test_is_repost_blocked_detects_marker():
    assert _is_repost_blocked(BLOCKED) is True
    assert _is_repost_blocked(NORMAL) is False

def test_extract_original_url_from_plaintext_body():
    assert _extract_original_url(BLOCKED, ".xe_content") == \
        "https://m.gianlucadimarzio.com/calciomercato/juve-lucumi-493366"

def test_extract_original_url_none_when_no_external_link():
    assert _extract_original_url(NORMAL, ".xe_content") is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_is_repost_blocked_detects_marker tests/test_fmkorea_adapter.py::test_extract_original_url_from_plaintext_body tests/test_fmkorea_adapter.py::test_extract_original_url_none_when_no_external_link -v`
Expected: FAIL (`ImportError`: cannot import name `_is_repost_blocked`)

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/fmkorea.py`의 `_body_text` 아래에 추가:

```python
import re

_REPOST_MARK = "퍼가기가 금지된 글입니다"
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

def _is_repost_blocked(html: str) -> bool:
    return _REPOST_MARK in html

def _extract_original_url(html: str, body_selector: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(body_selector)
    if el is None:
        return None
    # href 우선, 없으면 본문 텍스트의 평문 URL
    for a in el.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("http") and "fmkorea.com" not in href:
            return href
    for m in _URL_RE.finditer(el.get_text(" ", strip=True)):
        if "fmkorea.com" not in m.group(0):
            return m.group(0)
    return None
```

(파일 상단에 이미 `import` 블록이 있으면 `import re`는 거기로 합쳐도 된다.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "repost_blocked or extract_original" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 퍼가기 금지 감지·원문 URL 추출 헬퍼

Refs: docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md (§2,§3.1)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 2: 원문 og:description fetch 헬퍼

원문 URL을 fetch(리다이렉트 추적)해 한국어 요약 입력으로 쓸 텍스트를 얻는다.

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient`(`fetch()`가 생성하는 클라이언트를 전달)
- Produces:
  - `async _fetch_og_description(client: httpx.AsyncClient, url: str) -> str | None` — `og:description` 우선, 없으면 `<meta name="description">`. fetch 실패(`httpx.HTTPError`)·둘 다 없음 → `None`. HTML 엔티티는 디코드한다.

- [ ] **Step 1: 실패 테스트 작성**

```python
from bullet_in.adapters.fmkorea import _fetch_og_description

OG_HTML = (
    '<html><head>'
    '<meta property="og:title" content="La Juventus vuole Lucum&iacute;">'
    '<meta property="og:description" content="I bianconeri vogliono il '
    'difensore colombiano del Bologna.">'
    '</head><body></body></html>'
)
META_ONLY = ('<html><head><meta name="description" content="Solo meta desc.">'
             '</head></html>')

@respx.mock
def test_fetch_og_description_prefers_og():
    respx.get("https://orig.test/a").mock(return_value=httpx.Response(200, text=OG_HTML))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/a")
    assert asyncio.run(run()) == "I bianconeri vogliono il difensore colombiano del Bologna."

@respx.mock
def test_fetch_og_description_falls_back_to_meta():
    respx.get("https://orig.test/b").mock(return_value=httpx.Response(200, text=META_ONLY))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/b")
    assert asyncio.run(run()) == "Solo meta desc."

@respx.mock
def test_fetch_og_description_none_on_http_error():
    respx.get("https://orig.test/c").mock(return_value=httpx.Response(404))
    async def run():
        async with httpx.AsyncClient() as c:
            return await _fetch_og_description(c, "https://orig.test/c")
    assert asyncio.run(run()) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k og_description -v`
Expected: FAIL (`ImportError`: cannot import name `_fetch_og_description`)

- [ ] **Step 3: 최소 구현**

```python
async def _fetch_og_description(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    tag = (soup.find("meta", property="og:description")
           or soup.find("meta", attrs={"name": "description"}))
    content = tag.get("content") if tag else None
    return content.strip() if content else None
```

(`BeautifulSoup`는 `content` 속성의 HTML 엔티티 `&iacute;` 등을 자동 디코드한다.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k og_description -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 원문 og:description fetch 헬퍼

Refs: docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md (§3.3)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 3: fetch() 분기 통합 (분기①/②/현행)

차단 여부에 따라 RawItem 구성을 분기한다.

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`fetch()`의 본문 fetch 루프)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: Task1 `_is_repost_blocked`/`_extract_original_url`, Task2 `_fetch_og_description`
- Produces: `FmkoreaAdapter.fetch()` 동작 변경:
  - 차단 + 원문URL + og 성공 → `RawItem.url=원문`, `raw_payload={"title": fmkorea헤드라인, "body": og_description, "lang": "ko"}`
  - 차단 + (URL 없음 또는 og 실패) → `RawItem.url=원문URL or fmkorea URL`, `raw_payload={"title": 헤드라인, "body": "", "lang": "ko"}`
  - 비차단 → 현행(`url=fmkorea`, `body=_body_text(html, body_selector)`)

- [ ] **Step 1: 실패 테스트 작성**

```python
@respx.mock
def test_fetch_blocked_replaces_with_original_og():
    list_html = '<a class="title" href="/1">[디 마르지오] 아스날 수비수 노린다</a>'
    blocked_body = (
        '<div class="xe_content"><p>아스날이 수비수를 원한다.</p>'
        '<p>https://orig.test/x</p></div><!--AfterDocument(1,2)--></article>'
        '<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
        '아이디/아이피가 자동으로 표기됩니다]</strong>'
    )
    og = ('<meta property="og:description" content="Arsenal want a defender.">')
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=blocked_body))
    respx.get("https://orig.test/x").mock(return_value=httpx.Response(200, text=og))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://orig.test/x"                 # 원 출처로 치환
    assert it.raw_payload["title"].startswith("[디 마르지오]")  # fmkorea 헤드라인 유지
    assert it.raw_payload["body"] == "Arsenal want a defender."  # og:description
    assert "아스날이 수비수를 원한다" not in it.raw_payload["body"]  # fmkorea 번역 본문 미저장
    assert it.raw_payload["lang"] == "ko"

@respx.mock
def test_fetch_blocked_without_og_falls_back_to_headline_only():
    list_html = '<a class="title" href="/1">[ITK] 아스날 영입 임박</a>'
    blocked_body = (
        '<div class="xe_content"><p>본문 번역.</p><p>https://orig.test/y</p></div>'
        '<strong>[퍼가기가 금지된 글입니다 - 캡처 방지 위해 글 열람 사용자 '
        '아이디/아이피가 자동으로 표기됩니다]</strong>'
    )
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=blocked_body))
    respx.get("https://orig.test/y").mock(return_value=httpx.Response(404))  # og fetch 실패
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://orig.test/y"   # 원문 URL은 있으므로 링크는 원 출처
    assert it.raw_payload["body"] == ""       # 본문 미복제, 헤드라인만
    assert it.raw_payload["title"].startswith("[ITK]")
```

(비차단 현행 동작은 기존 `test_fmkorea_filters_by_keyword_and_fetches_body`가 이미 검증.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "blocked_replaces or without_og" -v`
Expected: FAIL (현재 fetch는 무조건 fmkorea url·본문 저장이라 assert 불일치)

- [ ] **Step 3: 최소 구현**

`fetch()`의 `for title, url in matched:` 루프 본문을 아래로 교체:

```python
            for title, url in matched:
                try:
                    rb = await c.get(url)
                    rb.raise_for_status()
                except httpx.HTTPError:
                    continue  # 해당 글만 스킵, 배치 지속
                html = rb.text
                if _is_repost_blocked(html):
                    orig = _extract_original_url(html, self.body_selector)
                    desc = await _fetch_og_description(c, orig) if orig else None
                    if orig and desc:                 # 분기①: 원문 대체
                        item_url, body = orig, desc
                    else:                             # 분기②: 헤드라인만
                        item_url, body = orig or url, ""
                else:                                 # 현행: fmkorea 본문 요약
                    item_url = url
                    body = _body_text(html, self.body_selector)
                out.append(RawItem(
                    source_id=self.source_id, source_type="html", url=item_url,
                    fetched_at=now,
                    raw_payload={"title": title, "body": body, "lang": "ko"}))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS (기존 2개 + 신규 전부)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 퍼가기 금지 글을 원 출처 og 요약으로 대체

Refs: docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md (§3)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 4: 리스트 fetch 429 가드

레이트 제한을 정상 실패가 아닌 빈 결과로 구분(enrich 429 철학과 일관).

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (모듈 상단 logger, 리스트 fetch try)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Produces: 리스트 fetch가 HTTP 429를 받으면 예외를 던지지 않고 `WARNING` 로깅 후 `[]` 반환. 그 외 상태 에러는 기존대로 전파.

- [ ] **Step 1: 실패 테스트 작성**

```python
@respx.mock
def test_fetch_returns_empty_on_list_429(caplog):
    respx.get("https://fm.test/football_news").mock(return_value=httpx.Response(429))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    with caplog.at_level("WARNING"):
        assert asyncio.run(a.fetch()) == []
    assert any("429" in r.message for r in caplog.records)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_fetch_returns_empty_on_list_429 -v`
Expected: FAIL (`raise_for_status()`가 `HTTPStatusError` 전파)

- [ ] **Step 3: 최소 구현**

모듈 상단(`import` 블록 직후)에 logger 추가:

```python
import logging
log = logging.getLogger(__name__)
```

`fetch()`의 리스트 fetch 부분 교체:

```python
            try:
                r = await c.get(self.list_url)
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    log.warning("fmkorea 리스트 429(rate limit) — 이번 회차 스킵")
                    return []
                raise
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(fmkorea): 리스트 429를 빈 결과로 처리(배치 보호)

Refs: docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md (§5)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 5: config 셀렉터 드리프트 수정 + 라이브 스모크 + 활성화

`item_selector`를 실DOM에 맞추고, 어댑터 단독 라이브 fetch로 검증한 뒤 활성화한다.

**Files:**
- Modify: `config/sources.yaml` (fmkorea 블록)

**Interfaces:** (없음 — 설정·검증 태스크)

- [ ] **Step 1: 셀렉터 수정**

`config/sources.yaml`의 fmkorea 블록에서:

```yaml
      item_selector: "h3.title a"
```
를
```yaml
      item_selector: "a.title"
```
로 변경. `enabled`는 아직 `false` 유지.

- [ ] **Step 2: 어댑터 단독 라이브 스모크 (수동)**

Run:
```bash
set -a; source .env; set +a
uv run python -c "
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
# fmkorea만 임시 활성화하여 빌드
for s in cfg['sources']:
    if s['source_id']=='fmkorea': s['enabled']=True
a = [x for x in build_adapters(cfg) if x.source_id=='fmkorea'][0]
items = asyncio.run(a.fetch())
print('fetched:', len(items))
for it in items[:5]:
    print(it.url, '|', it.raw_payload['title'][:40], '| body_len', len(it.raw_payload['body']))
"
```
Expected: `fetched: N`(N>0)이고, 차단 글은 `url`이 fmkorea가 아닌 원 출처 도메인으로, 비차단 글은 fmkorea url로 나온다. fmkorea 번역 본문이 차단 글 body에 들어있지 않은지 육안 확인.

> 0건이면 셀렉터가 또 드리프트된 것 — 실제 페이지 DOM을 다시 확인해 `item_selector`를 갱신하고 Step 2 반복(`docs/troubleshooting/2026-06-12-live-source-selector-drift.md` 참조).

- [ ] **Step 3: 활성화**

스모크가 정상이면 `config/sources.yaml`의 fmkorea `enabled: false` → `enabled: true`.

- [ ] **Step 4: 전체 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 PASS(통합 테스트는 DB 없으면 skip).

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml
git commit -m "feat(fmkorea): 셀렉터 드리프트 수정(a.title)·소스 활성화

라이브 fetch 스모크로 퍼가기 금지 정책 동작 확인 후 enabled=true.

Refs: docs/superpowers/specs/2026-06-28-fmkorea-repost-policy-design.md (§6,§8)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

## 성공 기준 (전체)

- `uv run pytest tests/test_fmkorea_adapter.py -v` 신규/기존 테스트 전부 통과.
- 라이브 스모크: 차단 아스날 글이 원 출처 링크로 치환되고 fmkorea 번역 본문이 body에 없음.
- `enabled: true` 상태로 종단 실행(`uv run python -m bullet_in.run`) 시 fmkorea 글이 서빙 페이지에 원 출처 링크로 노출.
