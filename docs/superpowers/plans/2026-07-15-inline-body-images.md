# 본문 인라인 이미지 구현 계획 (2026-07-15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집 단계에서 기사 본문의 인라인 이미지 URL을 추출 · 저장하고, 상세 페이지 본문 문단 사이에 렌더한다.

**Architecture:** 공통 파서 `extract_body_images` (meta.py) 가 본문 컨테이너 안의 `<img>`를 필터링해 URL 목록으로 반환하고, 원문 HTML을 확보하는 5개 경로 (html 6곳 · fmkorea 2경로 · 백트래킹 승격 · Guardian) 가 이를 `raw_payload["images"]`로 싣는다.
저장은 `articles.images_json` 컬럼 1개 (JSON 배열), 렌더는 순수 함수 `interleave_body`가 번역 문단과 이미지를 2문단 간격으로 교차 배치한다.
enrich (Gemini) 는 완전 무접촉.

**Tech Stack:** Python 3.11 · uv · pytest · respx · BeautifulSoup · SQLAlchemy (MariaDB) · Jinja2.

**Spec:** `docs/superpowers/specs/2026-07-15-inline-body-images-design.md`

**Branch:** `feat/inline-body-images` — 이미 존재 (spec 커밋 `855d2cf` 포함), 그대로 이어서 작업한다.

## Global Constraints

- 이미지는 부가 정보 — 추출 실패는 기사 수집을 절대 막지 않는다 (파서가 빈 목록 폴백).
- enrich (Gemini) · 기존 `body_ko` 데이터 무접촉. 번역 프롬프트를 건드리지 않는다.
- 저장 상한 10장 (파서 `limit=10`), 렌더 간격 2문단, 잔여 이미지는 버린다.
- 핫링크만 — 이미지 다운로드 코드 금지. `<img>`는 `loading="lazy"` · `referrerpolicy="no-referrer"` · `onerror` 숨김을 반드시 포함한다.
- 백필 없음 — 기존 행은 `images_json` NULL → 빈 목록으로 취급한다.
- 기존 스타일 준수: 어댑터 테스트는 respx 모킹 (tests/test_html_adapter.py 패턴), MartStore DB 테스트는 tests/integration/ (DB 없으면 skip).
- fmkorea 라이브 접근은 2h 간격 규칙 — Task 8 라이브 검증에서 1회만.
- 커밋: 컨벤션 §1.1 (도입 1–2문장 + 명사형 불릿) · §1.3 (트레일러 = 실제 작업 모델).
  아래 커밋 블록의 트레일러는 실제 실행 모델로 맞춘다 (설계 · 구현이 같은 모델이면 라벨 없이 한 줄).

---

### Task 1: 공통 파서 `extract_body_images` (meta.py)

**Files:**
- Modify: `src/bullet_in/adapters/meta.py`
- Test: `tests/test_meta.py`

**Interfaces:**
- Produces: `extract_body_images(html: str, container_selector: str | None = None, base_url: str | None = None, limit: int = 10) -> list[str]`
  — 본문 컨테이너 안의 `<img>` URL을 원문 등장 순서로 반환. 이후 모든 태스크가 이 함수를 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_meta.py` 끝에 추가:

```python
from bullet_in.adapters.meta import extract_body_images

IMG_PAGE = ('<html><body><div class="story">'
            '<p>One.</p><img src="https://cdn.test/a.jpg">'
            '<p>Two.</p><img src="https://cdn.test/b.jpg">'
            '</div><img src="https://cdn.test/outside.jpg"></body></html>')

def test_images_scoped_to_container_in_order():
    assert extract_body_images(IMG_PAGE, ".story") == [
        "https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]

def test_images_heuristic_root_when_no_selector():
    html = ('<html><body><article><img src="https://cdn.test/in.jpg"></article>'
            '<img src="https://cdn.test/out.jpg"></body></html>')
    assert extract_body_images(html) == ["https://cdn.test/in.jpg"]

def test_images_excludes_ad_hosts():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<img src="https://ads.doubleclick.net/x.jpg">'
            '<img src="https://images.taboola.com/y.jpg">'
            '<img src="https://widgets.outbrain.com/z.jpg"></article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_excludes_aside_and_related_blocks():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<aside><img src="https://cdn.test/side.jpg"></aside>'
            '<div class="related-articles"><img src="https://cdn.test/rel.jpg"></div>'
            '</article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_excludes_tiny_data_uri_and_svg():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<img src="https://cdn.test/icon.png" width="24" height="24">'
            '<img src="data:image/gif;base64,R0lGOD">'
            '<img src="https://cdn.test/logo.svg"></article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_resolves_lazyload_and_srcset():
    html = ('<article>'
            '<img data-src="https://cdn.test/lazy.jpg">'
            '<img srcset="https://cdn.test/s.jpg 320w, https://cdn.test/l.jpg 1280w">'
            '</article>')
    assert extract_body_images(html) == [
        "https://cdn.test/lazy.jpg", "https://cdn.test/l.jpg"]

def test_images_absolutizes_relative_and_dedups():
    html = '<article><img src="/img/a.jpg"><img src="https://cdn.test/img/a.jpg"></article>'
    assert extract_body_images(html, base_url="https://cdn.test/article/1") == [
        "https://cdn.test/img/a.jpg"]

def test_images_caps_at_limit():
    imgs = "".join(f'<img src="https://cdn.test/{i}.jpg">' for i in range(15))
    assert len(extract_body_images(f"<article>{imgs}</article>")) == 10

def test_images_empty_on_missing_container_or_blank():
    assert extract_body_images("<p>no container</p>", ".story") == []
    assert extract_body_images("") == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_meta.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_body_images'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/meta.py` — 상단 import를 확장하고 파일 끝에 추가:

```python
# 상단 (기존 from bs4 import BeautifulSoup 아래에 추가)
import re
from urllib.parse import urljoin, urlparse
```

```python
# 파일 끝에 추가
_AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "taboola.com",
             "outbrain.com", "adsystem", "scorecardresearch.com")
_RELATED_CLASS = re.compile(r"related", re.I)

def _img_url(img, base_url: str | None) -> str | None:
    """<img>의 실제 URL — lazy-load(data-src) · srcset(최대 해상도) 해석, 상대 URL 절대화."""
    src = (img.get("src") or "").strip()
    if not src or src.startswith("data:"):
        src = (img.get("data-src") or "").strip()
    if not src and img.get("srcset"):
        cands = [c.strip().split()[0] for c in img["srcset"].split(",") if c.strip()]
        src = cands[-1] if cands else ""
    if not src or src.startswith("data:"):
        return None
    return urljoin(base_url, src) if base_url else src

def _too_small(img) -> bool:
    """width/height 속성이 있고 한 변이 120px 미만이면 아이콘·트래커로 간주."""
    for attr in ("width", "height"):
        v = str(img.get(attr) or "").rstrip("px")
        if v.isdigit() and int(v) < 120:
            return True
    return False

def extract_body_images(html: str, container_selector: str | None = None,
                        base_url: str | None = None, limit: int = 10) -> list[str]:
    """본문 컨테이너 안의 <img> URL을 원문 등장 순서로 수집한다.
    광고 도메인·aside/관련기사 블록·초소형·data:/svg 는 제외.
    이미지는 부가 정보 — 어떤 실패도 빈 목록으로 폴백해 수집을 막지 않는다."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        root = (soup.select_one(container_selector) if container_selector
                else soup.find("article") or soup.find("main") or soup.body or soup)
        if root is None:
            return []
        out: list[str] = []
        for img in root.find_all("img"):
            if img.find_parent("aside") or img.find_parent(class_=_RELATED_CLASS):
                continue
            if _too_small(img):
                continue
            url = _img_url(img, base_url)
            if not url or not url.lower().startswith(("http://", "https://")):
                continue
            p = urlparse(url)
            host = (p.hostname or "").lower()
            if any(h in host for h in _AD_HOSTS) or p.path.lower().endswith(".svg"):
                continue
            if url not in out:
                out.append(url)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_meta.py -v`
Expected: 기존 7 + 신규 9 = 16 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/meta.py tests/test_meta.py
git commit -m "$(cat <<'EOF'
feat(adapters): 본문 인라인 이미지 공통 파서 extract_body_images

인라인 이미지 트랙의 첫 단계로, 모든 원문 HTML 경로가 공유할
이미지 수집 순수 함수를 meta.py 에 추가한다.

- 컨테이너 스코프: selector 지정 시 그 안만, 미지정 시 article/main/body 휴리스틱
- 필터: 광고 도메인·aside/관련기사 블록·120px 미만·data: URI·svg 제외
- lazy-load 해석: src → data-src → srcset 최대 해상도 순, 상대 URL 절대화
- 실패 폴백: 어떤 예외도 빈 목록 — 이미지가 수집을 막지 않는 계약
- 테스트 9종: 스코프·순서·필터 4종·lazy/srcset·절대화·dedup·상한·빈 입력

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: HtmlAdapter 연결 (html 6곳)

**Files:**
- Modify: `src/bullet_in/adapters/html.py:26,61`
- Test: `tests/test_html_adapter.py`

**Interfaces:**
- Consumes: `extract_body_images(html, container_selector, base_url=...)` (Task 1)
- Produces: `raw_payload["images"]: list[str]` — body_selector 있는 소스의 기사 페이지에서 수집.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_html_adapter.py` 끝에 추가:

```python
@respx.mock
def test_html_adapter_collects_body_images():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><body><div class="article-body"><p>One.</p>'
              '<img src="https://img.test/1.jpg"><p>Two.</p>'
              '<img src="https://img.test/2.jpg"></div>'
              '<img src="https://img.test/outside.jpg"></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == [
        "https://img.test/1.jpg", "https://img.test/2.jpg"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py::test_html_adapter_collects_body_images -v`
Expected: FAIL — `KeyError: 'images'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/html.py` — 26행 import 확장:

```python
        from bullet_in.adapters.meta import extract_og_image, extract_body_images
```

61행 `payload["image_url"] = ...` 바로 아래에 추가:

```python
                        payload["images"] = extract_body_images(
                            rb.text, self.body_selector, base_url=url)
```

(HTTPError 분기는 무변경 — images 키 부재는 pipeline 의 `.get()`이 빈 목록으로 처리.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py -v`
Expected: 9 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/html.py tests/test_html_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): HtmlAdapter 기사 페이지에서 인라인 이미지 수집

body_selector 로 이미 받아오는 기사 HTML 에서 이미지만 추가 수집한다
— 신규 네트워크 요청 없음, html 6개 소스 공통 적용.

- payload["images"]: extract_body_images(본문 컨테이너 스코프) 결과
- 본문 fetch 실패 분기 무변경: images 키 부재 = 빈 목록 처리

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: fmkorea 두 경로 연결 (비페이월 원문 + 페이월 게시글)

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:133-169` (`_process`)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: `extract_body_images` (Task 1)
- Produces: `raw_payload["images"]: list[str]` — 비페이월은 원문 기사에서, 페이월 (Athletic) 은 fmkorea 게시글 (`.xe_content`) 에서.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fmkorea_adapter.py` 끝에 추가 (기존 상수 `FREE_BODY` 재사용):

```python
FREE_ART_IMG = ('<html><body><article><p>Arsenal news.</p>'
                '<img src="https://art.test/1.jpg"></article></body></html>')
PAY_BODY_IMG = ('<div class="xe_content"><p>아스날 본문.</p>'
                '<img src="https://fmimg.test/p.jpg">'
                '<p>https://www.nytimes.com/athletic/9/b</p></div>')

@respx.mock
def test_fmkorea_free_path_collects_original_article_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=1">[BBC] 아스날</a>'))
    respx.get("https://www.fmkorea.com/1").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART_IMG))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://art.test/1.jpg"]

@respx.mock
def test_fmkorea_paywalled_path_collects_post_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(
        200, text='<a class="hx" href="/index.php?document_srl=2">[디 애슬레틱] 아스날</a>'))
    respx.get("https://www.fmkorea.com/2").mock(return_value=httpx.Response(200, text=PAY_BODY_IMG))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text="<html></html>"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://fmimg.test/p.jpg"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v -k images`
Expected: 2 FAIL — `KeyError: 'images'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/fmkorea.py` `_process` — 136행 import 확장:

```python
        from bullet_in.adapters.meta import extract_og_image, extract_article_body, extract_body_images
```

150–162행 페이월/무료 분기를 다음과 같이 수정:

```python
            if outlet in PAYWALLED_OUTLETS:
                body = _body_text(html, self.body_selector)
                image = await _fetch_og_image(c, orig)
                # 게시글 이미지 ≈ 원문 기사 이미지 재게재 (spec 확정 결정)
                images = extract_body_images(html, self.body_selector, base_url=url)
                lang = "ko"
            else:
                try:
                    ro = await c.get(orig)
                    ro.raise_for_status()
                    body = extract_article_body(ro.text)
                    image = extract_og_image(ro.text)
                    images = extract_body_images(ro.text, base_url=orig)
                except httpx.HTTPError:
                    body, image, images = "", None, []
                lang = "en"
```

166–168행 raw_payload에 images 추가:

```python
                raw_payload={"title": title, "body": body, "lang": lang,
                             "outlet": outlet, "journalist": journalist,
                             "image_url": image, "images": images}))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: 전체 passed (기존 + 신규 2)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): fmkorea 두 경로에 인라인 이미지 수집 연결

비페이월은 이미 fetch 하는 원문 기사에서, 페이월 (Athletic) 은
게시글 본문에서 수집한다 — 게시글 이미지는 원문 이미지 재게재라는
판단 (spec 확정 결정).

- 비페이월: extract_body_images(원문 HTML, 휴리스틱 컨테이너)
- 페이월: extract_body_images(게시글, .xe_content 스코프)
- 원문 fetch 실패 시 images=[] — 기존 폴백과 동형

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 백트래킹 승격 경로 연결 (x_backtrack)

**Files:**
- Modify: `src/bullet_in/adapters/x_backtrack.py:78-99,124,134`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Consumes: `extract_body_images` (Task 1)
- Produces: `resolve_and_fetch(...) -> tuple[str | None, str, str | None, str | None, list[str]]` (5-튜플로 확장),
  `promote_cited_item(..., images: list[str] | None = None)` — 승격 항목의 `raw_payload["images"]`.

주의: `resolve_and_fetch` 반환이 4-튜플 → 5-튜플로 바뀌므로 **기존 테스트 2곳의 언패킹도 이 태스크에서 갱신**한다.

- [ ] **Step 1: 실패하는 테스트 작성 + 기존 테스트 갱신**

`tests/test_x_backtrack.py` — 기존 `test_resolve_and_fetch_follows_redirect`의 83행 언패킹을 5-튜플로 수정:

```python
    url, body, title, _img, _images = asyncio.run(run())
```

기존 `test_resolve_and_fetch_returns_empty_on_http_error`의 95행 기대값 수정:

```python
    assert asyncio.run(run()) == (None, "", None, None, [])
```

파일 끝에 신규 테스트 추가:

```python
def test_resolve_and_fetch_extracts_inline_images():
    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"},
                              html=('<article><p>Body text here.</p>'
                                    '<img src="https://cdn.test/a.jpg"></article>'))
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as c:
            return await resolve_and_fetch(c, "https://bbc.co.uk/x")
    _url, _body, _title, _img, images = asyncio.run(run())
    assert images == ["https://cdn.test/a.jpg"]

def test_promote_carries_images():
    it = RawItem(source_id="x_afcstuff", source_type="x",
                 url="https://x.com/afcstuff/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Arsenal sign X [ @gunnerblog ]",
                              "journalist": "@gunnerblog",
                              "created_at": "2026-07-02T20:00:00Z"})
    p = promote_cited_item(it, "https://arseblog.com/a", "arseblog", "T", "B", None,
                           images=["https://cdn.test/a.jpg"])
    assert p.raw_payload["images"] == ["https://cdn.test/a.jpg"]

def test_promote_images_default_empty():
    it = RawItem(source_id="x_afcstuff", source_type="x", url="https://x.com/a/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Tweet", "journalist": "@x"})
    p = promote_cited_item(it, "https://bbc.co.uk/a", "BBC", None, "B", None)
    assert p.raw_payload["images"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -v`
Expected: FAIL — 언패킹 개수 불일치 (`ValueError: not enough values to unpack`) 및 `TypeError` (images 인자)

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/x_backtrack.py` — 8행 import 확장:

```python
from bullet_in.adapters.meta import extract_article_body, extract_og_title, extract_og_image, extract_body_images
```

`resolve_and_fetch` (92–99행) 를 5-튜플로:

```python
async def resolve_and_fetch(client: httpx.AsyncClient, url: str
                            ) -> tuple[str | None, str, str | None, str | None, list[str]]:
    """t.co (또는 실 URL) → 최종 URL · 본문 · 제목 · 이미지 · 인라인 이미지 목록.
    실패 시 (None, '', None, None, [])."""
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None, "", None, None, []
    return (str(r.url), extract_article_body(r.text), extract_og_title(r.text),
            extract_og_image(r.text), extract_body_images(r.text, base_url=str(r.url)))
```

`promote_cited_item` (78–90행) 에 images 파라미터 추가:

```python
def promote_cited_item(item: RawItem, article_url: str, outlet: str, title: str | None,
                       body: str, image: str | None,
                       images: list[str] | None = None) -> RawItem:
    """인용 RawItem을 무료 기사로 제자리 승격. raw_payload를 fmkorea 무료 경로와 동형으로."""
    return RawItem(
        source_id=item.source_id, source_type="html", url=article_url,
        fetched_at=item.fetched_at,
        raw_payload={
            "title": title or item.raw_payload.get("text", ""),
            "text": item.raw_payload.get("text", ""),
            "body": body, "lang": "en", "outlet": outlet,
            "journalist": item.raw_payload.get("journalist"),
            "image_url": image,
            "images": images or [],
            "created_at": item.raw_payload.get("created_at"),
        })
```

`backtrack_promote` 내 호출부 (124행 · 134행) 갱신:

```python
                final_url, body, title, image, images = await resolve_and_fetch(c, card)
```

```python
                out.append(promote_cited_item(it, final_url, outlet, title, body, image, images))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py tests/test_x_playwright.py -v`
Expected: 전체 passed (x_playwright 포함 — 호출 경로 회귀 확인)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/x_backtrack.py tests/test_x_backtrack.py
git commit -m "$(cat <<'EOF'
feat(adapters): 백트래킹 승격 항목에 인라인 이미지 전달

기자 트윗 링크 카드로 fetch 하는 원문 기사 HTML 에서 이미지를 수집해
승격 RawItem 에 싣는다 — fmkorea 무료 경로와 동형 payload 유지.

- resolve_and_fetch: 4-튜플 → 5-튜플 (인라인 이미지 목록 추가)
- promote_cited_item: images 파라미터 (기본 빈 목록)
- 기존 테스트 2곳 언패킹 갱신 + 신규 3종

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Guardian `body` 필드 추가

**Files:**
- Modify: `src/bullet_in/adapters/guardian_api.py:15,42-43`
- Test: `tests/test_guardian_adapter.py`

**Interfaces:**
- Consumes: `extract_body_images` (Task 1)
- Produces: `raw_payload["images"]` — API `body` (HTML) 필드에서 수집. `bodyText` 본문 경로는 무변경.

주의: 기존 `test_guardian_adapter_requests_tag_and_fields`의 show-fields 단언을 이 태스크에서 갱신한다.

- [ ] **Step 1: 실패하는 테스트 작성 + 기존 단언 갱신**

`tests/test_guardian_adapter.py` — 33행 단언 수정:

```python
    assert q["show-fields"] == "trailText,bodyText,body,thumbnail"
```

파일 끝에 추가 (`_resp` 헬퍼 재사용):

```python
@respx.mock
def test_guardian_adapter_extracts_body_images():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://guard.test/a",
         "webPublicationDate": "2026-07-15T10:00:00Z",
         "fields": {"trailText": "t", "bodyText": "plain body",
                    "body": ('<p>One.</p><figure>'
                             '<img src="https://media.test/1.jpg"></figure>'),
                    "thumbnail": "https://media.test/t.jpg"}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://media.test/1.jpg"]
    assert items[0].raw_payload["body"] == "plain body"  # bodyText 경로 무변경
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_guardian_adapter.py -v`
Expected: 2 FAIL — show-fields 불일치 · `KeyError: 'images'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/guardian_api.py` — 상단에 import 추가:

```python
from bullet_in.adapters.meta import extract_body_images
```

15행 show-fields 갱신:

```python
                       "show-fields": "trailText,bodyText,body,thumbnail",
```

42–43행 raw_payload에 images 추가:

```python
                                            "body": f.get("bodyText", ""),
                                            "image_url": f.get("thumbnail"),
                                            "images": extract_body_images(
                                                f.get("body", ""), base_url=x["webUrl"])}))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_guardian_adapter.py -v`
Expected: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/guardian_api.py tests/test_guardian_adapter.py
git commit -m "$(cat <<'EOF'
feat(adapters): Guardian API body 필드로 인라인 이미지 수집

show-fields 에 body (HTML) 를 추가해 이미지만 뽑는다 — 본문 텍스트는
기존 bodyText 그대로라 번역 경로 무영향.

- show-fields: trailText,bodyText,body,thumbnail
- images: body HTML 프래그먼트에서 extract_body_images
- bodyText 무변경 계약을 테스트로 고정

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 모델 · 파이프라인 · 스키마 · 저장 · 서빙 SELECT

**Files:**
- Modify: `src/bullet_in/models.py:30`, `src/bullet_in/pipeline.py:44`, `src/bullet_in/storage/schema.sql:12,26`, `src/bullet_in/storage/mariadb.py:22-58`, `src/bullet_in/run.py:87-89`
- Test: `tests/test_pipeline.py`, Create: `tests/test_mart_row.py`

**Interfaces:**
- Consumes: `raw_payload["images"]` (Task 2–5)
- Produces: `Article.images: list[str]` (pydantic 필드), `articles.images_json` 컬럼,
  `_article_row(a: Article) -> dict` (mariadb.py 모듈 함수 — upsert 파라미터 행), 서빙 SELECT의 `images_json` 컬럼.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pipeline.py` 끝에 추가:

```python
def test_to_articles_passes_inline_images():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://x.test/g", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign G", "body": "B",
                                "images": ["https://img.test/1.jpg"]})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].images == ["https://img.test/1.jpg"]

def test_to_articles_defaults_images_empty():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://x.test/h", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign H"})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].images == []
```

`tests/test_mart_row.py` 신규:

```python
import json
from datetime import datetime
from bullet_in.models import Article
from bullet_in.storage.mariadb import _article_row

def _article(**kw):
    base = dict(content_hash="h1", url="https://x/1", source_id="s",
                title_original="T", published_at=datetime(2026, 7, 15, 10, 0))
    base.update(kw)
    return Article(**base)

def test_article_row_serializes_images_json():
    row = _article_row(_article(images=["https://a/1.jpg", "https://a/2.jpg"]))
    assert json.loads(row["images_json"]) == ["https://a/1.jpg", "https://a/2.jpg"]
    assert "images" not in row  # SQL 파라미터에 미지의 키 금지

def test_article_row_empty_images_is_null():
    assert _article_row(_article())["images_json"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py tests/test_mart_row.py -v`
Expected: FAIL — `Article has no field 'images'` · `ImportError: _article_row`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/models.py` — 30행 `image_url` 아래에 추가:

```python
    images: list[str] = []
```

`src/bullet_in/pipeline.py` — 44행 `image_url=...` 아래에 추가:

```python
            images=item.raw_payload.get("images") or [],
```

`src/bullet_in/storage/schema.sql` — 12행을 다음으로 교체:

```sql
  image_url VARCHAR(1024), images_json TEXT, outlet VARCHAR(128), journalist VARCHAR(128),
```

26행 (`transfer_stage` ALTER) 아래에 추가:

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS images_json TEXT;
```

`src/bullet_in/storage/mariadb.py` — `MartStore` 클래스 위 모듈 레벨에 추가:

```python
def _article_row(a: Article) -> dict:
    """Article → upsert 파라미터 행. images 는 JSON 직렬화, 빈 목록은 NULL."""
    row = a.model_dump(exclude={"images"})
    row["images_json"] = json.dumps(a.images) if a.images else None
    return row
```

`upsert`의 SQL — INSERT 컬럼 · VALUES · ON DUPLICATE 세 곳에 `images_json` 추가:

```python
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,
             summary3_ko,body_ko,body_source,image_url,images_json,outlet,journalist,team,
             transfer_stage,
             published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,
             :summary3_ko,:body_ko,:body_source,:image_url,:images_json,:outlet,:journalist,:team,
             :transfer_stage,
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
             images_json=VALUES(images_json),
             outlet=VALUES(outlet),
             journalist=VALUES(journalist),
             team=VALUES(team),
             published_at=VALUES(published_at),
             tier=VALUES(tier),
             confidence_score=VALUES(confidence_score),
             fetched_at=VALUES(fetched_at),
             revision=VALUES(revision),
             content_hash=VALUES(content_hash)""")
        rows = [_article_row(a) for a in articles]
```

`src/bullet_in/run.py` — 87–89행 서빙 SELECT에 `images_json` 추가:

```python
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,transfer_stage,tier,"
            "confidence_score,published_at "
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline.py tests/test_mart_row.py tests/test_models.py -v && uv run pytest tests/integration -q`
Expected: 단위 전체 passed, integration은 DB 없으면 skip (DB 떠 있으면 passed — `ensure_schema`가 신규 ALTER 멱등 적용)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/models.py src/bullet_in/pipeline.py src/bullet_in/storage/schema.sql src/bullet_in/storage/mariadb.py src/bullet_in/run.py tests/test_pipeline.py tests/test_mart_row.py
git commit -m "$(cat <<'EOF'
feat(pipeline): 인라인 이미지 저장 경로 — Article.images · images_json 컬럼

어댑터가 실은 raw_payload["images"] 를 mart 까지 나른다.
기존 행은 NULL = 빈 목록으로 취급 (백필 없음, spec 확정).

- Article.images: list[str] 기본 빈 목록
- pipeline.to_articles: raw_payload images 매핑
- schema.sql: images_json TEXT (CREATE + 멱등 ALTER, 기존 패턴)
- MartStore.upsert: _article_row 로 JSON 직렬화 (빈 목록 → NULL),
  ON DUPLICATE 갱신 포함 (revision 시 최신 이미지 반영)
- run.py 서빙 SELECT 에 images_json

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 렌더 — 인터리브 · 히어로 중복 제거 · 승격 · 템플릿

**Files:**
- Modify: `src/bullet_in/serve/render.py` (import · `_decorate` · `render_article` · 신규 순수 함수 2개), `src/bullet_in/serve/templates/detail.html.j2:26-28`, `src/bullet_in/serve/static/style.css` (`.body figcaption` 아래)
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: `images_json` 컬럼 (Task 6)
- Produces: `interleave_body(paras: list[str], images: list[str], every: int = 2) -> list[dict]` (블록 시퀀스 `{"type": "p"|"img", ...}`),
  `_decorate` 결과의 `_images` (검증 · dedup · 승격 반영) 와 `image_url` (승격 반영 — 인덱스 카드 썸네일도 이 값이라 자동 적용),
  `render_article`이 주입하는 `a._body_blocks`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_render.py` 끝에 추가:

```python
from bullet_in.serve.render import interleave_body, _decorate as _dec, render_article as _ra

def test_interleave_every_two_paragraphs():
    blocks = interleave_body(["p1", "p2", "p3", "p4"], ["i1", "i2"])
    assert [b["type"] for b in blocks] == ["p", "p", "img", "p", "p", "img"]
    assert blocks[2]["url"] == "i1"

def test_interleave_images_exhausted_then_paragraphs_only():
    blocks = interleave_body(["p1", "p2", "p3", "p4", "p5", "p6"], ["i1"])
    assert [b["type"] for b in blocks].count("img") == 1

def test_interleave_surplus_images_dropped():
    blocks = interleave_body(["p1", "p2"], ["i1", "i2", "i3"])
    assert [b["type"] for b in blocks].count("img") == 1

def test_interleave_empty_inputs():
    assert interleave_body([], ["i1"]) == []
    assert [b["type"] for b in interleave_body(["p1"], [])] == ["p"]

def test_decorate_dedups_hero_from_inline_images():
    row = _row(image_url="https://img/x.jpg",
               images_json='["https://img/x.jpg?w=1200", "https://img/y.jpg"]')
    a = _dec(row, SOURCES, NOW)
    assert a["_images"] == ["https://img/y.jpg"]

def test_decorate_promotes_first_inline_to_hero():
    row = _row(image_url=None,
               images_json='["https://img/a.jpg", "https://img/b.jpg"]')
    a = _dec(row, SOURCES, NOW)
    assert a["image_url"] == "https://img/a.jpg"
    assert a["_images"] == ["https://img/b.jpg"]

def test_decorate_rejects_invalid_inline_urls_and_bad_json():
    row = _row(image_url="https://img/hero.jpg",
               images_json='["javascript:alert(1)", "https://img/ok.jpg"]')
    assert _dec(row, SOURCES, NOW)["_images"] == ["https://img/ok.jpg"]
    row2 = _row(image_url="https://img/hero.jpg", images_json="not json")
    assert _dec(row2, SOURCES, NOW)["_images"] == []

def test_detail_interleaves_inline_images_with_defenses():
    row = _row(body_ko="문단1\n문단2\n문단3", image_url="https://img/hero.jpg",
               images_json='["https://img/in1.jpg"]')
    a = _dec(row, SOURCES, NOW)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert '<img src="https://img/in1.jpg"' in html
    assert 'loading="lazy"' in html and 'referrerpolicy="no-referrer"' in html
    assert "onerror" in html
    assert html.index("문단2") < html.index("in1.jpg") < html.index("문단3")

def test_css_has_inline_image_style():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".body figure img" in css
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -v -k "interleave or inline or promotes or dedups"`
Expected: FAIL — `ImportError: cannot import name 'interleave_body'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/serve/render.py` — 상단 import에 `json` 추가:

```python
import json
import re
import shutil
```

`_decorate` 위 모듈 레벨에 순수 함수 2개 추가:

```python
def _norm_img(url: str) -> str:
    """CDN 리사이즈 변형 (쿼리스트링) 을 무시한 이미지 동일성 비교 키."""
    return url.split("?", 1)[0]


def interleave_body(paras: list[str], images: list[str], every: int = 2) -> list[dict]:
    """번역 문단과 인라인 이미지의 교차 블록 시퀀스.
    every 문단마다 이미지 1장, 이미지 소진 후엔 문단만, 남는 이미지는 버린다."""
    blocks, qi = [], 0
    for i, p in enumerate(paras, 1):
        blocks.append({"type": "p", "text": p})
        if qi < len(images) and i % every == 0:
            blocks.append({"type": "img", "url": images[qi]})
            qi += 1
    return blocks
```

`_decorate` — 229행 `a["image_url"] = ...` 바로 아래에 추가:

```python
    try:
        parsed = json.loads(row.get("images_json") or "[]")
    except (TypeError, ValueError):
        parsed = []
    imgs = [u for u in parsed
            if isinstance(u, str) and re.match(r"^https?://[^\s'\"()]+$", u)]
    if a["image_url"]:
        hero = _norm_img(a["image_url"])
        imgs = [u for u in imgs if _norm_img(u) != hero]
    elif imgs:
        a["image_url"] = imgs[0]  # og:image 부재 → 인라인 1번을 히어로·카드 썸네일로 승격
        imgs = imgs[1:]
    a["_images"] = imgs
```

`render_article` — return 직전에 블록 주입 추가:

```python
def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)},
                  "total": 0, "stage": {}, "other": 0}
    article = dict(article)
    paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
    article["_body_blocks"] = interleave_body(paras, article.get("_images") or [])
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets)
```

`src/bullet_in/serve/templates/detail.html.j2` — 26–28행 body 블록 교체:

```jinja
    <div class="body">
      {% for b in a._body_blocks %}{% if b.type == 'p' %}<p>{{ b.text }}</p>
      {% else %}<figure><img src="{{ b.url }}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'"></figure>
      {% endif %}{% endfor %}
    </div>
```

`src/bullet_in/serve/static/style.css` — `.body figcaption` 규칙 아래에 추가 (목업 `.imgph`의 16:9 · 라운드를 실제 이미지용으로):

```css
.body figure img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;display:block}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py tests/test_serve_layout.py -v`
Expected: 전체 passed (기존 상세 페이지 테스트 포함 — `_body_blocks` 미주입 경로가 없어졌는지 회귀 확인)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/serve/templates/detail.html.j2 src/bullet_in/serve/static/style.css tests/test_serve_render.py
git commit -m "$(cat <<'EOF'
feat(serve): 상세 페이지 본문에 인라인 이미지 렌더

번역 문단 2개마다 이미지 1장을 교차 배치하고, 히어로와의 중복
노출·빈 히어로를 함께 정리한다.

- interleave_body: 순수 함수 — 2문단 간격·소진 중단·잔여 버림
- _decorate: images_json 검증 (URL 허용목록 정규식 재사용)·히어로
  중복 제거 (쿼리스트링 정규화 비교)·og:image 부재 시 인라인 1번
  승격 (인덱스 카드 썸네일 자동 포함)
- detail.html.j2: figure/img — lazy·no-referrer·onerror 숨김 방어
- style.css: .body figure img 16:9·라운드 (목업 .imgph 이식)

Refs: docs/superpowers/specs/2026-07-15-inline-body-images-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 전체 회귀 + 라이브 검증 (머지 게이트)

**Files:**
- 수정 없음 (검증 결과에 따라 필터 · 셀렉터 조정 시에만 해당 파일 + 테스트 갱신 커밋)

**Interfaces:**
- Consumes: Task 1–7 전체.
- Produces: 머지 판단 근거 — 소스별 라이브 이미지 수집 실측, 상세 페이지 실렌더 확인.

- [ ] **Step 1: 전체 테스트 스위트**

Run: `uv run pytest -q`
Expected: 전체 passed (기존 246 + 신규 ~25), integration은 DB 없으면 skip

- [ ] **Step 2: 어댑터 단독 라이브 fetch (셀렉터 드리프트 함정 대응)**

fmkorea는 직전 접근 후 2h 경과를 확인하고 1회만 실행한다.
Guardian은 `.env`의 `GUARDIAN_API_KEY`가 필요하다.

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters

cfg = yaml.safe_load(open("config/sources.yaml"))
adapters = [a for a in build_adapters(cfg) if a.source_id != "x_afcstuff"]

async def main():
    for a in adapters:
        try:
            items = await a.fetch()
        except Exception as e:
            print(f"{a.source_id}: FETCH FAIL {e}")
            continue
        with_imgs = [i for i in items if i.raw_payload.get("images")]
        sample = with_imgs[0].raw_payload["images"][:2] if with_imgs else "—"
        print(f"{a.source_id}: {len(items)}건 / 이미지 보유 {len(with_imgs)}건 / 예시 {sample}")

asyncio.run(main())
EOF
```

Expected: html 6곳 (arsenal_official · bbc_sport · bbc_gossip · goal · football_london · skysports) + guardian + fmkorea 각각 이미지 보유 기사 ≥ 1건, 예시 URL이 기사 이미지 (광고 · 아이콘 아님).
0건인 소스는 해당 기사 원문을 열어 원인 (이미지 없는 기사 vs 필터 과잉 vs lazy-load 미해석) 을 판별하고, 필터 조정 시 단위 테스트 케이스로 고정 후 별도 커밋.

- [ ] **Step 3: 라이브 종단 1회 + 상세 페이지 확인**

```bash
docker compose up -d
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8
grep -l '<figure><img' site/article/*.html | head -5
```

Expected: run 성공 (success_rate 1.0), grep이 1개 이상의 상세 페이지를 출력 — 트랙 완료 기준 (상세 페이지 본문 이미지 표시) 충족.
브라우저로 해당 상세 페이지를 열어 이미지 렌더 · 히어로 중복 없음 · 깨진 이미지 숨김을 눈으로 확인한다.

- [ ] **Step 4: 검증 결과 기록**

소스별 실측 수치를 PR 본문 검증 섹션에 기입한다 (캡처는 트랙 ③에서 1회 촬영 — 이 트랙에서 찍지 않는다).

---

## Self-Review 결과 (계획 작성 시 수행)

- spec 커버리지: 스키마 (Task 6) · 추출 + 필터 (Task 1) · 소스 연결 5경로 (Task 2–5) · 저장 (Task 6) · 렌더 + 승격 + 방어 (Task 7) · 에러 폴백 (Task 1 · 3) · 라이브 검증 (Task 8) — 전 섹션 대응.
- spec "열어 둔 판단" 해소: 광고 도메인 목록 = Task 1 `_AD_HOSTS` 6종 (테스트로 고정), 본문 컨테이너 공유 = `extract_body_images`가 `extract_article_body`와 동일한 휴리스틱 (article/main/body) 을 자체 구현 — 기존 함수 무수정 (수술적 변경).
- 타입 일관성: `raw_payload["images"]` (list[str]) → `Article.images` → `images_json` (JSON TEXT) → `_images` → `_body_blocks` 체인 확인.
