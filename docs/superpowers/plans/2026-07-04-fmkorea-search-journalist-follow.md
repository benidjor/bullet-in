# fmkorea 검색 경로 전환 · 아스날 전담기자 팔로우 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fmkorea 어댑터를 첫 페이지 스캔에서 검색 엔드포인트 union 으로 바꿔 밀림 없이 아스날 글을 수집하고, Ornstein · de Roché 정확구문 검색으로 Athletic 전담기자를 팔로우한다.

**Architecture:** 어댑터의 발굴 (discovery) 단계만 다중 키워드 검색 union 으로 교체하고, 글 fetch · 말머리 파싱 · 페이월 라우팅 등 처리 (process) 단계는 재사용한다. Athletic 말머리 변종 매핑과 de Roché credibility 등록을 더해 tier 귀속을 맞춘다.

**Tech Stack:** Python 3.11 · httpx · BeautifulSoup · respx (테스트 HTTP 모킹) · pytest.

## Global Constraints

- Python 3.11 · uv 로 실행 (`uv run pytest -q`) .
- 테스트 HTTP 모킹은 `respx` · 비동기 실행은 `asyncio.run` (기존 `tests/test_fmkorea_adapter.py` 패턴) .
- 커밋 컨벤션 — `<type>(<scope>): 한국어 제목` + 본문 (왜) + `Refs:` + co-author 트레일러 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` .
- git 신원 — `benidjor <94089198+benidjor@users.noreply.github.com>` .
- credibility alias 는 로더가 소문자화해 매칭한다 (`resolve_tier` fmkorea 분기는 제목 + 본문 substring) .
- docs/ 아래 .md 저장 시 서식 훅 검사 — `·` 양옆 공백 · 여는 괄호 앞 공백 · `→`/`—` 줄끝 금지.
- karpathy 4원칙 — 최소 변경 · 투기 금지 · 내 변경이 만든 고아만 제거.

---

## File Structure

- Modify: `src/bullet_in/adapters/fmkorea.py` — 발굴을 검색 union 으로 · 처리 단계 추출 · 변종 매핑 · 고아 (`_matches` · `urljoin`) 제거.
- Modify: `src/bullet_in/adapters/factory.py:34-39` — fmkorea 생성자 새 시그니처 배선.
- Modify: `config/sources.yaml` — fmkorea `config` 를 검색 키로 교체.
- Modify: `config/credibility.yaml` — Art de Roché 등록.
- Modify: `tests/test_fmkorea_adapter.py` — 발굴 테스트를 검색 엔드포인트로 · 신규 union · 헬퍼 · 변종 테스트.
- Modify: `tests/test_adapter_factory.py:13-21` — fmkorea 팩토리 테스트 새 시그니처.
- Modify: `tests/test_credibility.py` — de Roché tier 테스트.

---

### Task 1: Athletic 말머리 변종 매핑

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`OUTLET_MAP`)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: 기존 `parse_bracket(title) -> (outlet, journalist, is_excl)` .
- Produces: 없음 (동작 확장만) .

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가:

```python
def test_parse_bracket_athletic_rae_variant():
    # '디 애슬래틱'(래) 변종도 The Athletic 으로 정규화
    assert parse_bracket("[디 애슬래틱] 아스날 0-2 맨시티")[0] == "The Athletic"

def test_parse_bracket_athletic_english_literal():
    assert parse_bracket("[The Athletic] 아스날 재계약")[0] == "The Athletic"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_parse_bracket_athletic_rae_variant -v`
Expected: FAIL (`'디 애슬래틱'` 이 매핑 안 돼 그대로 반환) .

- [ ] **Step 3: OUTLET_MAP 에 변종 추가**

`src/bullet_in/adapters/fmkorea.py` 의 `OUTLET_MAP` 을 교체:

```python
OUTLET_MAP = {
    "디 애슬레틱": "The Athletic", "디애슬레틱": "The Athletic",
    "디 애슬래틱": "The Athletic", "디애슬래틱": "The Athletic",  # '래' 변종
    "The Athletic": "The Athletic",                              # 리터럴 명시
    "골닷컴": "Goal", "르퀴프": "L'Équipe",
}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k athletic -v`
Expected: PASS (2건) .

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
fix(adapters): fmkorea Athletic 말머리 변종 매핑 (디 애슬래틱·The Athletic)

'디 애슬래틱'(래) 및 리터럴 The Athletic 이 OUTLET_MAP 부재로 페이월
분기를 못 타 Athletic 글이 무료 분기로 새거나 드롭되던 것을 수정.

Refs: docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 검색결과 href → 정규 글 URL 헬퍼

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (신규 `_post_url_from_href`)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Produces: `_post_url_from_href(href: str, base_url: str) -> str | None` — `document_srl` 을 뽑아 `{base_url}/{srl}` 반환, 없으면 None. Task 3 discovery 가 사용.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_fmkorea_adapter.py` 상단 import 부근에 추가:

```python
from bullet_in.adapters.fmkorea import _post_url_from_href

def test_post_url_from_document_srl_query():
    href = "/index.php?mid=football_news&document_srl=10035196191&search_keyword=x&page=1"
    assert _post_url_from_href(href, "https://www.fmkorea.com") == \
        "https://www.fmkorea.com/10035196191"

def test_post_url_from_clean_path():
    assert _post_url_from_href("/10035196191", "https://www.fmkorea.com") == \
        "https://www.fmkorea.com/10035196191"

def test_post_url_none_when_no_srl():
    assert _post_url_from_href("/index.php?mid=football_news&act=dispBoard",
                               "https://www.fmkorea.com") is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k post_url -v`
Expected: FAIL (`ImportError: cannot import name '_post_url_from_href'`) .

- [ ] **Step 3: 헬퍼 구현**

`src/bullet_in/adapters/fmkorea.py` 의 `_URL_RE` 정의 아래에 추가:

```python
_SRL_RE = re.compile(r"document_srl=(\d+)")

def _post_url_from_href(href: str, base_url: str) -> str | None:
    """검색결과 앵커 href → 정규 글 URL. document_srl 우선 · /NNNNN 폴백 · 없으면 None."""
    m = _SRL_RE.search(href or "") or re.match(r"/(\d{6,})", href or "")
    return f"{base_url.rstrip('/')}/{m.group(1)}" if m else None
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k post_url -v`
Expected: PASS (3건) .

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): fmkorea 검색결과 href → 정규 글 URL 헬퍼

검색 결과 앵커는 /index.php?...document_srl=NNNNN 형태라, srl 을 뽑아
fmkorea.com/{srl} 정규 URL 로 만들어 dedup·저장 키를 안정화한다.

Refs: docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 검색 엔드포인트 union 전환 (생성자 · discovery · fetch)

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py` (`FmkoreaAdapter` 생성자 · `fetch` · 신규 `_discover`/`_process` · 고아 `_matches`/`urljoin` 제거)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: Task 2 `_post_url_from_href` · 기존 `parse_bracket` · `_extract_original_url` · `_body_text` · `_fetch_og_image` · `PAYWALLED_OUTLETS` .
- Produces: `FmkoreaAdapter(source_id, search_url, search_keywords, item_selector="a.hx", base_url="https://www.fmkorea.com", body_selector=".xe_content", max_posts=15)` — Task 4 팩토리가 사용. `search_url` 은 `{keyword}` 자리표시를 포함한다.

- [ ] **Step 1: union · dedup 실패 테스트 작성**

`tests/test_fmkorea_adapter.py` 에 추가 (ascii 키워드로 인코딩 회피):

```python
SEARCH_KW1 = ('<a class="hx" href="/index.php?document_srl=111">[BBC] 아스날 A</a>'
              '<a class="replyNum" href="/index.php?document_srl=111#c">3</a>'
              '<a class="hx" href="/index.php?document_srl=222">[디 애슬레틱] 아스날 B</a>')
SEARCH_KW2 = ('<a class="hx" href="/index.php?document_srl=222">[디 애슬레틱] 아스날 B</a>'
              '<a class="hx" href="/index.php?document_srl=333">[더 선] 아스날 C</a>')
FREE_BODY = ('<div class="xe_content"><p>아스날 본문.</p>'
             '<p>https://ex.test/a</p></div>')
PAY_BODY = ('<div class="xe_content"><p>아스날 본문.</p>'
            '<p>https://www.nytimes.com/athletic/9/b</p></div>')
FREE_ART = '<html><body><article><p>Arsenal news.</p></article></body></html>'

@respx.mock
def test_fmkorea_search_union_dedup():
    respx.get("https://fm.test/s?kw=kw1").mock(return_value=httpx.Response(200, text=SEARCH_KW1))
    respx.get("https://fm.test/s?kw=kw2").mock(return_value=httpx.Response(200, text=SEARCH_KW2))
    respx.get("https://www.fmkorea.com/111").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/222").mock(return_value=httpx.Response(200, text=PAY_BODY))
    respx.get("https://www.fmkorea.com/333").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?kw={keyword}",
                       search_keywords=["kw1", "kw2"], base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    # 222 는 두 키워드에 걸려도 1건 → 총 3건 (111·222·333), replyNum 제외
    assert len(items) == 3
    pay = next(i for i in items if "athletic" in i.url)
    assert pay.raw_payload["outlet"] == "The Athletic"
    assert pay.raw_payload["lang"] == "ko"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_fmkorea_search_union_dedup -v`
Expected: FAIL (`TypeError` — 생성자가 `list_url` 을 기대) .

- [ ] **Step 3: 생성자 · _discover · _process · fetch 재구성**

`src/bullet_in/adapters/fmkorea.py` 상단 import 를 교체:

```python
from urllib.parse import quote
```

(`from urllib.parse import urljoin` 을 위 줄로 대체 — urljoin 은 이 변경으로 미사용) .

`_matches` 함수 정의를 삭제 (검색 키워드가 relevance 라 미사용 고아) .

`FmkoreaAdapter` 클래스 전체를 교체:

```python
class FmkoreaAdapter:
    source_type = "html"
    def __init__(self, source_id: str, search_url: str, search_keywords: list[str],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15):
        self.source_id = source_id
        self.search_url = search_url            # {keyword} 자리표시 포함
        self.search_keywords = search_keywords
        self.item_selector = item_selector
        self.base_url = base_url
        self.body_selector = body_selector
        self.max_posts = max_posts

    async def _discover(self, c: httpx.AsyncClient) -> list[tuple[str, str]]:
        """키워드별 검색 → a.hx 파싱 → 정규 글 URL union·dedup. (title, url) 목록."""
        matched, seen = [], set()
        for kw in self.search_keywords:
            url = self.search_url.format(keyword=quote(kw))
            try:
                r = await c.get(url)
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    log.warning("fmkorea 검색 429(rate limit) kw=%s — 스킵", kw)
                    continue
                raise
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select(self.item_selector):
                title = a.get_text(strip=True)
                post_url = _post_url_from_href(a.get("href", ""), self.base_url)
                if not title or not post_url or post_url in seen:
                    continue
                seen.add(post_url)
                matched.append((title, post_url))
                if len(matched) >= self.max_posts:
                    return matched
        return matched

    async def _process(self, c: httpx.AsyncClient,
                       matched: list[tuple[str, str]]) -> list[RawItem]:
        """글별 fetch → 말머리 파싱 → 페이월/무료 라우팅 → RawItem."""
        from bullet_in.adapters.meta import extract_og_image, extract_article_body
        now, out = datetime.now(timezone.utc), []
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
                body = _body_text(html, self.body_selector)
                image = await _fetch_og_image(c, orig)
                lang = "ko"
            else:
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

    async def fetch(self) -> list[RawItem]:
        headers = {"User-Agent": "Mozilla/5.0 bullet-in/0.1"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers) as c:
            matched = await self._discover(c)
            return await self._process(c, matched)
```

- [ ] **Step 4: union 테스트 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_fmkorea_search_union_dedup -v`
Expected: PASS.

- [ ] **Step 5: max_posts · 429 테스트 작성**

```python
@respx.mock
def test_fmkorea_search_respects_max_posts():
    html = ('<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 1</a>'
            '<a class="hx" href="/index.php?document_srl=2">[BBC] 아스날 2</a>'
            '<a class="hx" href="/index.php?document_srl=3">[BBC] 아스날 3</a>')
    respx.get("https://fm.test/s?kw=kw1").mock(return_value=httpx.Response(200, text=html))
    for n in (1, 2, 3):
        respx.get(f"https://www.fmkorea.com/{n}").mock(
            return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?kw={keyword}",
                       search_keywords=["kw1"], base_url="https://www.fmkorea.com", max_posts=2)
    assert len(asyncio.run(a.fetch())) == 2

@respx.mock
def test_fmkorea_search_429_skips_keyword_continues(caplog):
    respx.get("https://fm.test/s?kw=kw1").mock(return_value=httpx.Response(429))
    respx.get("https://fm.test/s?kw=kw2").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=9">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/9").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?kw={keyword}",
                       search_keywords=["kw1", "kw2"], base_url="https://www.fmkorea.com")
    with caplog.at_level("WARNING"):
        items = asyncio.run(a.fetch())
    assert len(items) == 1  # kw1 429 스킵 · kw2 수집
    assert any("429" in r.message for r in caplog.records)
```

- [ ] **Step 6: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k "max_posts or 429_skips" -v`
Expected: PASS (2건) .

- [ ] **Step 7: 기존 처리 테스트를 검색 엔드포인트로 갱신**

아래 3개 테스트를 검색 시그니처로 수정한다.
`test_fmkorea_paywalled_keeps_korean_body_and_outlet` · `test_fmkorea_free_outlet_fetches_original_english_body` · `test_fmkorea_skips_when_no_original_url` 에서 리스트 mock · 생성자를 교체 (예시는 paywalled) :

```python
@respx.mock
def test_fmkorea_paywalled_keeps_korean_body_and_outlet():
    search_html = '<a class="hx" href="/index.php?document_srl=1">[디 애슬레틱 - 온스테인] 아스날 수비수 보강</a>'
    body = ('<div class="xe_content"><p>아스날이 센터백을 원한다.</p>'
            '<p>https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/</p></div>')
    respx.get("https://fm.test/s?kw=kw1").mock(return_value=httpx.Response(200, text=search_html))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=body))
    respx.get("https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?kw={keyword}",
                       search_keywords=["kw1"], base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://www.nytimes.com/athletic/7374647/2026/06/28/arsenal-cb/"
    assert it.raw_payload["outlet"] == "The Athletic"
    assert it.raw_payload["journalist"] == "온스테인"
    assert it.raw_payload["lang"] == "ko"
    assert "센터백" in it.raw_payload["body"]
```

무료 아웃렛 테스트 (`..._free_outlet...`) 는 `document_srl=1` 검색 mock + `fmkorea.com/1` 본문 mock 으로 동일 패턴 적용 (원문 `https://www.bbc.com/sport/football/articles/gyo` · 영어 본문 mock 유지) .
`..._skips_when_no_original_url` 도 검색 mock + `fmkorea.com/1` 본문 (출처 URL 없음) 으로 교체.

그리고 더 이상 유효하지 않은 구 발굴 테스트를 삭제한다.
`test_fmkorea_filters_by_keyword_and_fetches_body` (제목 키워드 필터 제거로 전제 무효) · `test_fmkorea_skips_post_when_body_fetch_fails` (검색 시그니처로 재작성: 아래) · `test_fetch_returns_empty_on_list_429` (검색 429 테스트로 대체됨 — 삭제) .

body fetch 실패 재작성:

```python
@respx.mock
def test_fmkorea_skips_post_when_body_fetch_fails():
    respx.get("https://fm.test/s?kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날 속보</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(500))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?kw={keyword}",
                       search_keywords=["kw1"], base_url="https://www.fmkorea.com")
    assert asyncio.run(a.fetch()) == []
```

- [ ] **Step 8: 전체 fmkorea 테스트 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS (전부, `parse_bracket`/`_extract_original_url` 순수 테스트 포함) .

- [ ] **Step 9: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): fmkorea 첫 페이지 스캔 → 다중 키워드 검색 union 전환

고회전 게시판 첫 페이지만 보던 발굴을 검색 엔드포인트(title_content)
union 으로 교체. 키워드별 a.hx 파싱·document_srl dedup·max_posts 캡·
키워드별 429 스킵. 처리(파싱·페이월 라우팅) 단계는 _process 로 추출해
재사용. 제목 키워드 필터(_matches)·미사용 urljoin 은 고아라 제거.

Refs: docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 팩토리 · sources.yaml 배선

**Files:**
- Modify: `src/bullet_in/adapters/factory.py:34-39`
- Modify: `config/sources.yaml` (fmkorea `config`)
- Test: `tests/test_adapter_factory.py:13-21`

**Interfaces:**
- Consumes: Task 3 `FmkoreaAdapter` 새 시그니처.

- [ ] **Step 1: 팩토리 테스트 갱신 (실패)**

`tests/test_adapter_factory.py` 의 `test_factory_builds_fmkorea_adapter` 를 교체:

```python
def test_factory_builds_fmkorea_adapter():
    cfg = {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"search_url": "https://fm.test/s?kw={keyword}",
                    "search_keywords": ["아스날", "온스테인"],
                    "item_selector": "a.hx"}},
    ]}
    adapters = build_adapters(cfg)
    assert adapters[0].source_id == "fmkorea"
    assert adapters[0].search_keywords == ["아스날", "온스테인"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_adapter_factory.py::test_factory_builds_fmkorea_adapter -v`
Expected: FAIL (`KeyError: 'list_url'`) .

- [ ] **Step 3: 팩토리 분기 교체**

`src/bullet_in/adapters/factory.py` 의 fmkorea 분기 (34-39) 를 교체:

```python
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["search_url"], c["search_keywords"],
                item_selector=c.get("item_selector", "a.hx"),
                base_url=c.get("base_url", "https://www.fmkorea.com"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 15)))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_adapter_factory.py -v`
Expected: PASS.

- [ ] **Step 5: sources.yaml fmkorea config 교체**

`config/sources.yaml` 의 fmkorea `config` 블록을 교체:

```yaml
    config:
      search_url: "https://www.fmkorea.com/search.php?mid=football_news&search_target=title_content&search_keyword={keyword}"
      search_keywords: ["아스날", '"de roche"', "온스테인"]
      item_selector: "a.hx"
      base_url: "https://www.fmkorea.com"
      body_selector: ".xe_content"
      max_posts: 15
```

- [ ] **Step 6: 설정 로드 확인**

Run: `uv run python -c "from bullet_in.adapters.factory import build_adapters; import yaml; a=[x for x in build_adapters(yaml.safe_load(open('config/sources.yaml'))) if x.source_id=='fmkorea'][0]; print(a.search_keywords)"`
Expected: `['아스날', '"de roche"', '온스테인']` .

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/adapters/factory.py config/sources.yaml tests/test_adapter_factory.py
git commit -m "$(cat <<'EOF'
feat(config): fmkorea 검색 키워드 배선 (아스날·"de roche"·온스테인)

팩토리를 새 어댑터 시그니처로 배선하고, sources.yaml fmkorea config 를
검색 엔드포인트 키워드 3종으로 교체. "de roche" 는 토큰 분리 오탐을
막는 따옴표 정확구문.

Refs: docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: credibility.yaml — Art de Roché 등록

**Files:**
- Modify: `config/credibility.yaml` (journalists)
- Test: `tests/test_credibility.py`

**Interfaces:**
- Consumes: 기존 `resolve_tier` fmkorea 분기 (제목 + 본문 substring alias 매칭) .

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_credibility.py` 에 추가:

```python
def test_resolve_fmkorea_de_roche_journalist_tier():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[디 애슬레틱] 아스날 공격진 분석",
                           "body": "By 드 로셰. 아스날의 하베르츠 복귀."})
    assert resolve_tier(it, sources, r) == 1.5
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_credibility.py::test_resolve_fmkorea_de_roche_journalist_tier -v`
Expected: FAIL (de Roché 미등록 → outlet The Athletic tier 1.0 반환) .

- [ ] **Step 3: credibility.yaml 에 de Roché 추가**

`config/credibility.yaml` 의 `journalists:` 목록에 한 줄 추가 (LatteFirm 항목 아래) :

```yaml
  - {name: Art de Roché,     tier: 1.5, aliases: ["드 로셰", "드로셰", "de roche"]}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_credibility.py -v`
Expected: PASS (전부 · 기존 테스트 회귀 없음) .

- [ ] **Step 5: 커밋**

```bash
git add config/credibility.yaml tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(config): credibility 에 Art de Roché(The Athletic 아스날 전담) 등록

fmkorea tier 는 본문 바이라인 substring 으로 매칭하므로 '드 로셰' 등
alias 로 tier 1.5 귀속. bare '로셰'는 '로셰인' 오탐이라 제외.

Refs: docs/superpowers/specs/2026-07-04-fmkorea-search-journalist-follow-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 라이브 검증 · Part 2 브리핑

제품 코드 변경 없음. 새 어댑터를 실 fetch 해 수집을 경로별로 브리핑한다 (셀렉터 · 검색 드리프트는 모킹이 못 잡음) .

**Files:**
- Create: scratchpad 검증 스크립트 (커밋 안 함) .

- [ ] **Step 1: 전체 단위 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: PASS (통합은 DB 없으면 skip) .

- [ ] **Step 2: 라이브 브리핑 스크립트 작성 · 실행**

scratchpad 에 스크립트를 만들어 실행:

```python
import asyncio, yaml, logging, sys
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "fmkorea"][0]
items = asyncio.run(adp.fetch())
from collections import Counter
print("총 수집:", len(items))
print("아웃렛 분포:", Counter(i.raw_payload["outlet"] for i in items))
print("페이월(ko) 건수:", sum(1 for i in items if i.raw_payload["lang"] == "ko"))
for i in items:
    p = i.raw_payload
    print(f"  [{p['outlet']}] {p['title'][:60]} · lang={p['lang']} · {len(p.get('body') or '')}자")
```

Run: `set -a; source .env; set +a; uv run python <스크립트>`
Expected: Athletic 페이월 건 포함 · de Roché · Ornstein 아스날 글 캡처.

- [ ] **Step 3: 사용자에게 브리핑 보고**

수집 총계 · 아웃렛 분포 · 페이월 보존 건수 · 키워드 경로별 예시 (아스날 vs 기자) · de Roché · Ornstein 캡처 예시를 정리해 보고한다.

---

### Task 7: Part 3 — 프론트엔드 반영 미리보기

제품 코드 변경 없음. Task 6 수집분을 실제 렌더러로 화면에 반영한다.

**Files:**
- Create: scratchpad 렌더 스크립트 · `site-preview/` (커밋 안 함) .

- [ ] **Step 1: 미리보기 렌더 스크립트 작성**

수집 RawItem 을 `write_site` 입력 행으로 변환해 렌더한다. `write_site(rows, sources, out_dir)` 는 `content_hash` · `title_original`/`title_ko` · `outlet` · `url` · `published_at` 등을 읽는다.

```python
import asyncio, yaml, os
from datetime import datetime, timezone
from google import genai
from bullet_in.adapters.factory import build_adapters
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.enrich import enrich_rows, partition_by_paywall
from bullet_in.score import load_sources
from bullet_in.serve.render import write_site

cfg = yaml.safe_load(open("config/sources.yaml"))
sources = load_sources("config/sources.yaml")
adp = [a for a in build_adapters(cfg) if a.source_id == "fmkorea"][0]
items = asyncio.run(adp.fetch())

rows = []
for it in items:
    p = it.raw_payload
    rows.append({
        "content_hash": content_hash(p.get("title") or "", canonical_url(it.url)),
        "url": it.url, "source_id": it.source_id,
        "title_original": p.get("title"), "title_ko": p.get("title"),
        "summary_ko": None, "summary3_ko": None, "body_ko": p.get("body"),
        "image_url": p.get("image_url"), "outlet": p.get("outlet"),
        "journalist": p.get("journalist"), "team": "arsenal",
        "transfer_stage": None, "tier": None, "confidence_score": None,
        "published_at": datetime.now(timezone.utc)})

# 3줄 요약: 이 소량 건에만 Gemini paraphrase (선택 · 429 시 스킵)
try:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    _, tr = partition_by_paywall(rows)
    res = enrich_rows(tr, client, "gemini-2.5-flash-lite", mode="paraphrase")
    for h, v in res.items():
        for r in rows:
            if r["content_hash"] == h:
                r["summary3_ko"] = v.get("summary3_ko"); r["summary_ko"] = v.get("summary_ko")
except Exception as e:
    print("enrich 스킵:", e)

write_site(rows, sources, "site-preview")
print("렌더 완료: site-preview/index.html", len(rows), "건")
```

Run: `set -a; source .env; set +a; uv run python <스크립트>`
Expected: `site-preview/index.html` · `site-preview/article/*.html` 생성.

- [ ] **Step 2: 화면 확인 · 스크린샷**

Run: `open site-preview/index.html` (또는 헤드리스 캡처)
Expected: fmkorea 수집 글 (Athletic 포함) 이 인덱스 · 상세로 렌더된 화면.

- [ ] **Step 3: 사용자에게 화면 제시**

인덱스 · 상세 화면 스크린샷을 제시하고, de Roché · Ornstein · Athletic 글이 반영됐음을 확인한다.

---

## Self-Review

- **Spec coverage** — 검색 union (Task 3) · Athletic 변종 (Task 1) · de Roché credibility (Task 5) · 배선 (Task 4) · Part 2 브리핑 (Task 6) · Part 3 화면 (Task 7) · document_srl 헬퍼 (Task 2) 모두 태스크로 커버.
- **Placeholder scan** — 모든 코드 단계에 실제 코드 · 명령 · 기대값 명시. TBD 없음.
- **Type consistency** — `FmkoreaAdapter(source_id, search_url, search_keywords, item_selector, base_url, body_selector, max_posts)` 시그니처가 Task 3 정의 · Task 4 팩토리 호출 · 테스트에서 일치. `_post_url_from_href(href, base_url) -> str | None` Task 2 정의 · Task 3 사용 일치.
