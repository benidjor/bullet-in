# fmkorea 퍼가기 정책 개정 (E안) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 퍼가기 금지 표식이 붙은 글도 게시글 본문을 재료로 삼아 재작성해 서빙하고, 그 재작성이 원문에 없는 내용을 만들지 않도록 결정적 게이트 4축으로 막는다.

**Architecture:** 수집 계열에서 재료 채택 규칙을 고치고 (금지 표식 글의 본문 수집 · 원문이 200 으로 돌려주는 오류 안내 거부), 재작성 계열에서 프롬프트를 정보 단위 2단 구조로 바꾼 뒤 게이트를 네 축 (구단 · 인명 · 수치 · 인용) 으로 넓힌다. 게이트 위반은 폐기가 아니라 재생성 트리거로 쓰며, 이미 저장된 79행은 별도 CLI 로 소급 재작성한다.

**Tech Stack:** Python 3.11 · httpx + BeautifulSoup (수집) · google-genai (재작성) · SQLAlchemy + MariaDB (저장) · pytest + respx (테스트).

## Global Constraints

- 산출물 본문 · 커밋 본문 · PR 본문은 한국어로 쓴다.
- 문서 서식은 컨벤션 §2.2 를 따른다 — `→` · `—` 는 줄 시작 · 한 줄 한 문장 · `·` 와 여는 괄호 양옆 띄우기.
- 커밋은 `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러.
- git 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>` 다.
- PR 생성까지만 하고 머지는 사용자가 직접 한다.
- 이 트랙의 소유 필드는 수집 · 번역 계열이다 — `body_source` · `body_level` · `title_ko` · `summary_ko` · `summary3_ko` · `body_ko` · `rewrite_retention` · 어댑터. `transfer_stage` · `transfer_direction` 은 읽기만 한다.
- fmkorea 접촉 전에는 직전 회차 로그로 430 여부를 먼저 본다. 접촉 명령은 `tee` 로 출력을 남기고, 출력 확인 목적의 재실행은 하지 않는다.

---

## 배경 — 확정된 결정과 실측

### 사용자 확정 사항 (2026-08-03)

- 게이트가 오염을 검출하면 **재생성 트리거로 통일**한다. 사유를 프롬프트에 붙여 다시 만들고 최선을 채택하며 본문을 버리지 않는다.
- fmkorea 430 은 **배치에만 요청 간격을 넣고** 회차는 그대로 두며 배치 빈도도 유지한다.
- 새 프롬프트 도입 후 기존 **79행을 전건 소급 재작성**한다.
- PR 은 계열별 **3개로 나눈다**.

### 트랙 미결 하나의 해소 — 적용 범위

트랙 메모리는 "금지 표식 글만 vs 페이월 재작성 전체" 를 착수 시 결정할 미결로 남겨 두고 전체를 권장했다.
**전체로 간다.** 권장과 같기도 하지만 코드 구조가 이미 그렇게 생겼다.

- 재작성 경로는 `partition_by_body_level` 이 `body_level == 1` 로 가른다 — 즉 게시글 본문을 재료로 쓴 모든 행이 한 갈래다.
- 금지 표식 여부는 DB 에 남지 않는다.
둘을 갈라 다루려면 표식 상태를 저장할 컬럼을 새로 만들어야 하는데, 얻는 것이 없다.
- Task 1 이 금지 표식 글을 등급 1 로 보내므로 두 모집단은 어차피 합쳐진다.

### 실측 (2026-08-03 · 배포판 475행 기준)

| 항목 | 값 |
| --- | --- |
| 게시글 본문 기반 행 (`body_level = 1`) | 79 — 소급 재작성 대상 |
| 헤드라인만 남은 행 (`body_level = 0` · fmkorea) | 3 — ESPN 2 · 더 타임스 1 |
| The Athletic 행 | 49 — 전부 `body_level = 1` · 즉 금지 표식이 없어 이미 게시글 본문 수집 중 |
| 오류 안내가 본문이 된 행 | 2 — `5a91615a` 97자 · `cc294b1b` 99자 |
| 등급 2 본문 중 200자 미만 | 위 2건뿐 · 그다음으로 짧은 정상 본문이 251자 |
| 재작성 잔존율 (33행 측정) | 평균 0.471 · 최대 0.958 · 임계 0.75 초과 2건 |

`97e82280` 은 이미 정상 행이다 — 트랙 메모리의 "오염 요약 서빙 중" 은 낡은 정보이고 이 계획의 대상이 아니다.

### 이미 구현돼 있는 것

E안 의 뼈대는 번역 신뢰성 트랙 (#159~#164) 에서 이미 들어왔다.

- `enrich.rewrite_rows_guarded` 가 게이트 → 사유 첨부 재생성 → 최선 채택 루프를 돌린다.
- `fidelity.gate_verdict` 가 숫자 누락 축과 원문 복제 축을 판정한다.
- `enrich.detect_club_injection` 이 게이트 4축 중 구단 축이다.

그래서 이 계획의 실제 델타는 수집 규칙 2건 · 게이트 3축 추가 · 프롬프트 교체 · 소급 CLI 다.

---

## 파일 구조

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/adapters/fmkorea.py` | 재료 채택 규칙 (금지 표식 · 원문 사용 가능성) | 수정 |
| `src/bullet_in/fidelity.py` | 규칙 기반 충실도 판정 (숫자 · 인용 · 복제) | 수정 |
| `src/bullet_in/enrich.py` | 프롬프트 · 인명 주입 축 · 재작성 루프 | 수정 |
| `src/bullet_in/run.py` | 사전 로딩 위치 · 재작성 루프 인자 | 수정 |
| `src/bullet_in/storage/mariadb.py` | 소급 대상 행 조회 | 수정 |
| `src/bullet_in/backfill_rewrite.py` | 소급 재작성 CLI | 신규 |
| `src/bullet_in/watchlist_fmkorea.py` | 배치 요청 간격 | 수정 |
| `tests/test_fmkorea_adapter.py` | 수집 규칙 테스트 | 수정 |
| `tests/test_fidelity.py` | 숫자 · 인용 축 테스트 | 수정 |
| `tests/test_enrich.py` | 인명 축 · 재작성 루프 테스트 | 수정 |
| `tests/test_backfill_rewrite.py` | 소급 CLI 테스트 | 신규 |
| `tests/test_watchlist_fmkorea.py` | 배치 간격 테스트 | 수정 |

## PR 분할

| PR | 계열 | 태스크 |
| --- | --- | --- |
| ① | 수집 | 1 · 2 |
| ② | 재작성 | 3 · 4 · 5 · 6 · 7 · 8 |
| ③ | 운영 · 문서 | 9 · 10 |

PR ① 을 먼저 머지하면 오류 안내가 본문이 되는 유입을 그 시점부터 막는다.
PR ② 는 게이트와 프롬프트가 한 덩어리다 — 게이트 없이 재작성 강도만 올리면 검증 수단 없이 위험만 커진다.

---

### Task 1: 금지 표식 글도 게시글 본문을 채택한다

지금은 퍼가기 금지 표식이 보이면 본문을 통째로 버리고 제목만 남긴다.
그 결과 재료가 없는 행이 되어 상세 페이지에 본문이 없다.
E안 은 본문을 받아 재작성해 서빙하되 게시글 이미지는 계속 복제하지 않는다 — 이미지는 재작성할 수 없어 리스크의 성격이 다르다.

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:289-320`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: `_is_repost_blocked(html)` · `_body_text(html, selector)` · `extract_body_images` (기존).
- Produces: 없음 — 어댑터 외부 계약은 그대로다. `RawItem.raw_payload` 의 `body_level` 이 금지 표식 글에서 0 대신 1 로 바뀐다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.

```python
BLOCKED_PAY_BODY = ('<div class="rd_body"><strong>퍼가기가 금지된 글입니다</strong>'
                    '<div class="xe_content"><p>아스날이 영입에 근접했다.</p>'
                    '<p><img src="/p.jpg"></p>'
                    '<p>https://www.nytimes.com/athletic/9/b</p></div></div>')


@respx.mock
def test_blocked_paywalled_post_keeps_body_without_images():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=(
            '<a class="hx" href="/index.php?document_srl=222">'
            '[디 애슬레틱] 아스날 B</a>')))
    respx.get("https://www.fmkorea.com/222").mock(
        return_value=httpx.Response(200, text=BLOCKED_PAY_BODY))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(
        return_value=httpx.Response(200, text=""))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    item = asyncio.run(a.fetch())[0]
    assert "아스날이 영입에 근접했다." in item.raw_payload["body"]
    assert item.raw_payload["body_level"] == 1
    assert item.raw_payload["images"] == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_blocked_paywalled_post_keeps_body_without_images -v`
Expected: FAIL — `body` 가 빈 문자열이고 `body_level` 이 0 이다.

- [ ] **Step 3: 페이월 분기를 고친다**

`src/bullet_in/adapters/fmkorea.py` 의 `if outlet in PAYWALLED_OUTLETS:` 블록을 아래로 바꾼다.

```python
            if outlet in PAYWALLED_OUTLETS:
                body = _body_text(html, self.body_selector)
                if _is_repost_blocked(html):
                    # E안: 본문은 재작성해 서빙하되 게시글 이미지는 복제하지 않는다
                    # — 이미지는 재작성이 불가능해 리스크의 성격이 다르다.
                    log.info("fmkorea 퍼가기 금지 + 페이월 — 본문 채택 · 이미지 제외 url=%s", url)
                    images = []
                else:
                    # 게시글 이미지 ≈ 원문 기사 이미지 재게재 (spec 확정 결정)
                    images = extract_body_images(html, self.body_selector, base_url=url)
                image = await _fetch_og_image(c, orig)
                lang = "ko"
                material_level = 1        # 채택한 재료 = 커뮤니티가 옮긴 게시글 본문
```

- [ ] **Step 4: 원문 접속 실패 분기의 금지 표식 예외를 없앤다**

같은 파일의 `except httpx.HTTPError:` 블록을 아래로 바꾼다.
금지 표식 글만 본문 없이 진행하던 예외가 사라져 폴백이 한 갈래가 된다.

```python
                except httpx.HTTPError:
                    # 원문 차단 (실측 26건 중 25건이 406 · 403 · 페이월) — 게시글 본문으로 폴백.
                    log.info("fmkorea 원문 접속 실패 — 게시글 본문 채택 url=%s", orig)
                    image, images = None, []
                    body = _body_text(html, self.body_selector)
                    lang, material_level = "ko", 1
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS — 신규 1건 포함 전부 통과.

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 7: 커밋한다**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -F - <<'EOF'
feat(collect): 퍼가기 금지 글의 게시글 본문 채택

헤드라인만 남기던 처리를 본문 채택으로 바꾼다. 재료가 없어 상세 페이지가
비어 있던 글도 재작성 경로를 타게 된다.

- 페이월 분기: 금지 표식이어도 본문 수집 · 게시글 이미지만 제외
- 원문 실패 분기: 금지 표식 예외 삭제로 폴백을 한 갈래로 통일
- 등급: 금지 표식 글이 0 에서 1 (게시글 본문) 로 이동

Refs: #85
EOF
```

---

### Task 2: 원문이 200 으로 돌려준 오류 안내를 거부한다

원문 URL 이 정상 응답과 함께 "이 블로그는 이용할 수 없다" 는 안내를 돌려주면 그 문장이 언론사 본문 (등급 2) 으로 저장된다.
게시글 본문으로 물러서는 폴백이 `httpx.HTTPError` 에만 걸려 있어 예외가 없으면 발동하지 않기 때문이다.
길이로 거른다 — 배포판 등급 2 본문 273건 중 200자 미만은 문제의 2건뿐이고 그다음으로 짧은 정상 본문이 251자라 경계가 넉넉하다.
거부돼도 손실이 아니라 등급 하락이다 (게시글 본문으로 물러선다).

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py`
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Produces: `origin_body_usable(body: str) -> bool` · 모듈 상수 `ORIGIN_BODY_MIN_CHARS = 200`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
ERROR_PAGE = ('<html><body><article><p>Friday 24 July 2026 23:47, UK</p>'
              '<p>Sorry, this blog is currently unavailable. '
              'Please try again later.</p></article></body></html>')


@respx.mock
def test_origin_error_page_falls_back_to_post_body():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        return_value=httpx.Response(200, text=(
            '<a class="hx" href="/index.php?document_srl=111">[BBC] 아스날 A</a>')))
    respx.get("https://www.fmkorea.com/111").mock(
        return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(
        return_value=httpx.Response(200, text=ERROR_PAGE))
    a = FmkoreaAdapter(source_id="fmkorea",
                       search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    item = asyncio.run(a.fetch())[0]
    assert item.raw_payload["body_level"] == 1
    assert item.raw_payload["lang"] == "ko"
    assert "아스날 본문." in item.raw_payload["body"]
    assert "unavailable" not in item.raw_payload["body"]


def test_origin_body_usable_boundary():
    from bullet_in.adapters.fmkorea import origin_body_usable
    assert not origin_body_usable("Sorry, this blog is currently unavailable.")
    assert not origin_body_usable("  " + "가" * 199 + "  ")
    assert origin_body_usable("가" * 200)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py::test_origin_error_page_falls_back_to_post_body tests/test_fmkorea_adapter.py::test_origin_body_usable_boundary -v`
Expected: FAIL — `origin_body_usable` 이 없고 등급이 2 로 저장된다.

- [ ] **Step 3: 판정 함수를 추가한다**

`src/bullet_in/adapters/fmkorea.py` 의 `_BODY_MAX_CHARS` 아래에 넣는다.

```python
ORIGIN_BODY_MIN_CHARS = 200


def origin_body_usable(body: str) -> bool:
    """원문 URL 이 돌려준 본문을 등급 2 재료로 채택해도 되는지 판정한다.

    상태 코드만으로는 부족하다 — 만료된 라이브 블로그가 200 과 함께 안내 문구를
    돌려주고, 그 문장이 언론사 본문으로 저장된 실사례가 있다
    (docs/troubleshooting/2026-08-02-origin-error-page-stored-as-body.md).
    길이 기준은 배포판 실측이다 (2026-08-03 · 등급 2 본문 273건 중 200자 미만은
    오류 안내 2건뿐 · 그다음으로 짧은 정상 본문이 251자).
    거부는 손실이 아니라 등급 하락이다 — 게시글 본문 (등급 1) 으로 물러선다."""
    return len((body or "").strip()) >= ORIGIN_BODY_MIN_CHARS
```

- [ ] **Step 4: 비페이월 분기를 재료 판정 구조로 바꾼다**

`else:` 블록 (원문 URL 을 받는 쪽) 전체를 아래로 바꾼다.

```python
            else:
                body, lang, material_level = "", "ko", 1
                image, images = None, []
                try:
                    ro = await c.get(orig)
                    ro.raise_for_status()
                except httpx.HTTPError:
                    # 원문 차단 (실측 26건 중 25건이 406 · 403 · 페이월) — 게시글 본문으로 폴백.
                    log.info("fmkorea 원문 접속 실패 — 게시글 본문 채택 url=%s", orig)
                else:
                    origin_body = extract_article_body(ro.text)
                    if origin_body_usable(origin_body):
                        body, lang, material_level = origin_body, "en", 2
                        image = extract_og_image(ro.text)
                        images = extract_body_images(ro.text, base_url=orig)
                        pub = extract_published_at(ro.text)
                    else:
                        log.info("fmkorea 원문이 오류 안내로 보임 (%d자) — 게시글 본문 채택 url=%s",
                                 len((origin_body or "").strip()), orig)
                if material_level == 1:
                    body = _body_text(html, self.body_selector)
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS.

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 7: 커밋하고 PR ① 을 연다**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -F - <<'EOF'
fix(collect): 원문이 200 으로 준 오류 안내를 본문으로 채택하지 않음

폴백이 HTTP 예외에만 걸려 있어, 만료된 라이브 블로그가 정상 응답과 함께 돌려준
안내 문구가 언론사 본문으로 저장됐다. 길이로 재료 사용 가능성을 판정한다.

- 판정: origin_body_usable — 200자 미만이면 원문 채택 포기
- 폴백: 게시글 본문 (등급 1) 으로 하락 · 예외 경로와 같은 처리
- 근거: 등급 2 본문 273건 중 200자 미만은 오류 안내 2건뿐

Refs: #85
EOF
```

---

### Task 3: 수치 신규 주입 축을 만든다

기존 게이트는 원문 숫자가 산출물에서 **빠진 것**만 본다.
E안 은 반대 방향도 필요하다 — 원문에 없는 금액 · 나이 · 연도를 재작성이 만들어내는 것을 잡아야 한다.
보정 3종 (URL 제거 · 발행 표기 제거 · 단위 환산 동일시) 은 기존 함수를 그대로 재사용한다.

**Files:**
- Modify: `src/bullet_in/fidelity.py`
- Test: `tests/test_fidelity.py`

**Interfaces:**
- Consumes: `number_tokens(text)` · `_variants(tok)` (기존 · 같은 모듈).
- Produces: `extra_numbers(source: str, output: str) -> list[str]`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fidelity.py` 끝에 추가한다. import 줄에 `extra_numbers` 를 더한다.

```python
def test_extra_numbers_flags_invented_figure():
    src = "아스날이 5,000만 파운드를 제안했다."
    out = "아스날이 5,000만 파운드를 제안했고 계약 기간은 3년이다."
    assert extra_numbers(src, out) == ["3"]


def test_extra_numbers_allows_unit_conversion():
    src = "아스날이 £50m 을 제안했다."
    out = "아스날이 5,000만 파운드를 제안했다."
    assert extra_numbers(src, out) == []


def test_extra_numbers_ignores_url_and_publish_date():
    src = "아스날 소식."
    out = "아스날 소식. https://ex.test/2026/07/31 July 24, 2026 기준이다."
    assert extra_numbers(src, out) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_fidelity.py -v -k extra_numbers`
Expected: FAIL — `ImportError: cannot import name 'extra_numbers'`.

- [ ] **Step 3: 함수를 추가한다**

`src/bullet_in/fidelity.py` 의 `missing_numbers` 바로 아래에 넣는다.

```python
def extra_numbers(source: str, output: str) -> list[str]:
    """산출물에 있고 원문에 없는 숫자 — 재작성이 만들어낸 수치.

    missing_numbers 의 역방향이고 보정 3종을 똑같이 적용한다.
    단위 환산 후보가 원문에 있으면 주입으로 보지 않는다 (£50m ↔ 5,000만)."""
    src_tokens = set(number_tokens(source))
    extra: list[str] = []
    for tok in number_tokens(output):
        if tok in extra:
            continue
        if not (_variants(tok) & src_tokens):
            extra.append(tok)
    return extra
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_fidelity.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/fidelity.py tests/test_fidelity.py
git commit -F - <<'EOF'
feat(enrich): 재작성 산출물의 신규 수치 주입 검출

기존 게이트는 원문 숫자의 누락만 봤다. 게이트 4축 중 수치 축은 반대 방향
(원문에 없는 금액 · 나이 · 연도 생성) 도 잡아야 한다.

- 함수: extra_numbers — missing_numbers 의 역방향
- 보정: URL · 발행 표기 제거와 단위 환산 동일시를 그대로 재사용

Refs: #85
EOF
```

---

### Task 4: 인용 보존 축을 만든다

E안 은 인용문 (따옴표 안 발화) 을 재작성 대상에서 제외하고 원형을 보존하기로 했다.
그래서 원문 인용문이 산출물에 글자 그대로 남았는지 결정적으로 대조할 수 있다.
공백만 정규화해 비교한다 — 재작성이 줄바꿈이나 띄어쓰기를 바꾸는 것은 훼손이 아니다.

**Files:**
- Modify: `src/bullet_in/fidelity.py`
- Test: `tests/test_fidelity.py`

**Interfaces:**
- Consumes: `_WS_RE` (기존 · 같은 모듈).
- Produces: `quote_spans(text: str) -> list[str]` · `missing_quotes(source: str, output: str) -> list[str]`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

import 줄에 `missing_quotes` · `quote_spans` 를 더한다.

```python
def test_quote_spans_collects_both_quote_marks():
    text = '그는 "우리는 준비됐다" 고 했고 감독은 “시간이 필요하다” 고 했다.'
    assert quote_spans(text) == ["우리는 준비됐다", "시간이 필요하다"]


def test_missing_quotes_flags_rewritten_quote():
    src = '아르테타는 "우리는 더 나은 선수가 필요하다" 고 말했다.'
    out = '아르테타는 "더 좋은 선수가 있어야 한다" 고 말했다.'
    assert missing_quotes(src, out) == ["우리는 더 나은 선수가 필요하다"]


def test_missing_quotes_passes_preserved_quote():
    src = '아르테타는 "우리는 더 나은 선수가 필요하다" 고 말했다.'
    out = '감독은 "우리는 더 나은 선수가 필요하다" 는 말을 남겼다.'
    assert missing_quotes(src, out) == []


def test_missing_quotes_ignores_whitespace_change():
    src = '그는 "우리는  준비됐다" 고 했다.'
    out = '그는 "우리는 준비됐다" 고 했다.'
    assert missing_quotes(src, out) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_fidelity.py -v -k quote`
Expected: FAIL — `ImportError: cannot import name 'missing_quotes'`.

- [ ] **Step 3: 함수를 추가한다**

`src/bullet_in/fidelity.py` 의 `char_ngram_retention` 위에 넣는다.

```python
# 짧은 따옴표 쌍 (강조 표기 · 약어) 은 발화로 보지 않는다 — 4자 이상만 인용으로 센다.
_QUOTE_RE = re.compile(r'["“]([^"“”]{4,}?)["”]')


def quote_spans(text: str) -> list[str]:
    """따옴표 안 발화 목록 — 공백을 하나로 줄인 비교용 정규형."""
    return [_WS_RE.sub(" ", m.group(1)).strip()
            for m in _QUOTE_RE.finditer(text or "")]


def missing_quotes(source: str, output: str) -> list[str]:
    """원문 인용문 중 산출물에 원형으로 남지 않은 것.

    인용문은 재작성 대상에서 제외이므로 (E안 요소 ②) 글자 그대로 남아야 한다.
    공백 차이는 훼손으로 보지 않는다."""
    out = _WS_RE.sub(" ", output or "")
    return [q for q in quote_spans(source) if q not in out]
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_fidelity.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/fidelity.py tests/test_fidelity.py
git commit -F - <<'EOF'
feat(enrich): 재작성 산출물의 인용문 보존 검출

인용문은 재작성 대상에서 제외하기로 했으므로 원형 보존 여부를 결정적으로
대조할 수 있다. 게이트 4축 중 인용 축이다.

- 함수: quote_spans (따옴표 안 발화 수집) · missing_quotes (보존 대조)
- 비교: 공백만 정규화 — 줄바꿈 · 띄어쓰기 변화는 훼손으로 보지 않음
- 범위: 4자 이상만 발화로 인정 (강조 표기 오탐 차단)

Refs: #85
EOF
```

---

### Task 5: 인명 주입 축을 만든다

구단 축 (`detect_club_injection`) 은 산출물 4필드를 보는데, 인명 축은 제목만 본다 (`detect_title_hallucination`).
그래서 본문에만 주입된 인명이 잡히지 않는다.
구단 축과 같은 모양으로 4필드 전체를 보는 함수를 더한다.

**Files:**
- Modify: `src/bullet_in/enrich.py:259-289`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `_ko_present(text, name)` · `_fold_latin(text)` · `_GATE_FIELDS` (기존 `_CLUB_FIELDS` 의 새 이름).
- Produces: `detect_name_injection(parsed: dict, source_text: str, name_map: dict[str, str]) -> list[str]`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_enrich.py` 의 구단 축 테스트들 아래에 추가한다.

```python
def test_detect_name_injection_flags_body_only_name():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "아스날, 미드필더 영입 임박",
              "summary_ko": "아스날이 영입에 근접했다.",
              "summary3_ko": "", "body_ko": "외데고르가 주장으로 남는다."}
    src = "Arsenal are closing in on a midfielder."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == ["외데고르"]


def test_detect_name_injection_passes_korean_source():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "외데고르 잔류", "summary_ko": "",
              "summary3_ko": "", "body_ko": ""}
    src = "외데고르가 아스날에 남는다."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == []


def test_detect_name_injection_passes_english_source():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "아스날 소식", "summary_ko": "",
              "summary3_ko": "", "body_ko": "외데고르가 주장으로 남는다."}
    src = "Odegaard stays as captain."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == []


def test_detect_name_injection_empty_map_is_off():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "외데고르", "summary_ko": "",
              "summary3_ko": "", "body_ko": ""}
    assert detect_name_injection(parsed, "", {}) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_enrich.py -v -k name_injection`
Expected: FAIL — `ImportError: cannot import name 'detect_name_injection'`.

- [ ] **Step 3: 상수를 개명하고 함수를 추가한다**

`src/bullet_in/enrich.py` 에서 `_CLUB_FIELDS` 를 `_GATE_FIELDS` 로 바꾼다 (정의 1곳 · 사용 1곳).
두 축이 같은 필드 집합을 공유하므로 이름에서 구단 색을 뺀다.

```python
_GATE_FIELDS = ("title_ko", "summary_ko", "summary3_ko", "body_ko")
```

`detect_club_injection` 바로 아래에 함수를 넣는다.

```python
def detect_name_injection(parsed: dict, source_text: str,
                          name_map: dict[str, str]) -> list[str]:
    """산출물 4필드의 등재 인명이 원문에 근거 없으면 의심 목록 반환 (게이트 4축).

    detect_title_hallucination 과 같은 이중 대조 (한글 표기 or 영문 성) 를
    제목이 아니라 4필드 전체에 적용한다 — 본문에만 주입된 인명을 잡는다.
    사전 밖 인명은 미검출이다 (구단 축과 같은 점진 확장)."""
    if not name_map:
        return []
    joined = " ".join(filter(None, (parsed.get(k) for k in _GATE_FIELDS)))
    if not joined:
        return []
    src = source_text or ""
    folded_src = _fold_latin(src)
    suspects = []
    for ko, en in name_map.items():
        if not _ko_present(joined, ko):
            continue
        if _ko_present(src, ko):
            continue
        if re.search(rf"\b{re.escape(_fold_latin(en))}\b", folded_src):
            continue
        suspects.append(ko)
    return suspects
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: PASS — 기존 구단 축 테스트도 그대로 통과한다.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -F - <<'EOF'
feat(enrich): 산출물 4필드의 인명 주입 검출

인명 축이 제목만 보고 있어 본문에만 주입된 인물이 통과했다. 구단 축과 같은
모양으로 4필드 전체를 보는 축을 더한다.

- 함수: detect_name_injection — 한글 표기 · 영문 성 이중 대조
- 개명: _CLUB_FIELDS 를 _GATE_FIELDS 로 (두 축이 공유하는 필드 집합)

Refs: #85
EOF
```

---

### Task 6: 네 축을 재작성 루프의 재생성 트리거로 묶는다

사용자 확정에 따라 게이트 위반은 폐기가 아니라 재생성 트리거다.
위반 사유를 프롬프트에 붙여 다시 만들고, 최대 시도 후에는 위반이 가장 적은 결과를 채택한다.
`gate_verdict` 는 사전이 필요 없는 두 축 (수치 · 인용) 을 맡고, 사전이 필요한 두 축 (구단 · 인명) 은 재작성 루프가 직접 부른다.

**Files:**
- Modify: `src/bullet_in/fidelity.py` (`gate_verdict` · `select_best`)
- Modify: `src/bullet_in/enrich.py` (`rewrite_rows_guarded` · 재시도 문구)
- Modify: `src/bullet_in/run.py:106-147`
- Test: `tests/test_fidelity.py` · `tests/test_enrich.py`

**Interfaces:**
- Consumes: `extra_numbers` · `missing_quotes` (Task 3 · 4) · `detect_name_injection` (Task 5) · `detect_club_injection` (기존).
- Produces: `gate_verdict` 반환에 `extra` · `quotes` 키 추가 · `rewrite_rows_guarded(rows, client, model, threshold=..., max_attempts=3, name_map=None, club_map=None)` · 리포트에 `extra` · `quotes` · `names` · `clubs` 키 추가.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fidelity.py` 에 추가한다.

```python
def test_gate_verdict_fails_on_invented_number():
    src = "아스날이 £50m 을 제안했다."
    out = "아스날이 5,000만 파운드를 제안했고 계약은 3년이다."
    v = gate_verdict(src, out)
    assert v["extra"] == ["3"]
    assert v["ok"] is False


def test_gate_verdict_fails_on_broken_quote():
    src = '그는 "우리는 준비가 됐다" 고 말했다.'
    out = '그는 "준비는 끝났다" 고 밝혔다.'
    v = gate_verdict(src, out)
    assert v["quotes"] == ["우리는 준비가 됐다"]
    assert v["ok"] is False


def test_select_best_prefers_fewest_violations():
    a = {"parsed": "a", "missing": [], "extra": ["3"], "quotes": [],
         "names": [], "clubs": [], "retention": 0.1}
    b = {"parsed": "b", "missing": [], "extra": [], "quotes": [],
         "names": [], "clubs": [], "retention": 0.6}
    assert select_best([a, b])["parsed"] == "b"
```

`tests/test_enrich.py` 에 추가한다.

```python
def test_rewrite_retries_with_reason_notes_and_reports_axes():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Models:
        def __init__(self):
            self.prompts = []

        def generate_content(self, model, contents, config):
            self.prompts.append(contents)
            # 1차는 원문에 없는 구단 (첼시) 과 숫자 (5) 를 만든다 · 2차는 깨끗하다.
            # 2차 본문을 원문과 다른 문장으로 두어야 잔존율 축에 걸리지 않는다.
            if len(self.prompts) == 1:
                body = '아스날이 첼시에서 5년 계약으로 영입한다.'
            else:
                body = '영입이 곧 마무리될 전망이다.'
            return _Msg('{"title_ko":"제목","summary_ko":"요약",'
                        '"summary3_ko":["1","2","3"],"body_ko":"' + body + '",'
                        '"players":[]}')

    class _Client:
        def __init__(self):
            self.models = _Models()

    client = _Client()
    rows = [{"content_hash": "h1", "title_original": "아스날 영입",
             "body_source": "아스날이 영입을 마무리한다."}]
    results, reports = rewrite_rows_guarded(
        rows, client, "m", club_map={"첼시": ["Chelsea"]})
    assert "[구단 주입]" in client.models.prompts[1]
    assert "[신규 수치]" in client.models.prompts[1]
    assert reports["h1"]["clubs"] == []
    assert reports["h1"]["attempts"] == 2
    assert results["h1"]["body_ko"] == "영입이 곧 마무리될 전망이다."
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_fidelity.py tests/test_enrich.py -v -k "gate_verdict or select_best or retries_with_reason"`
Expected: FAIL — `gate_verdict` 에 `extra` 키가 없고 `rewrite_rows_guarded` 가 `club_map` 인자를 받지 않는다.

- [ ] **Step 3: `gate_verdict` 와 `select_best` 를 넓힌다**

`src/bullet_in/fidelity.py` 의 두 함수를 바꾼다.

```python
def gate_verdict(source: str, output: str,
                 threshold: float = RETENTION_THRESHOLD) -> dict:
    """사전이 필요 없는 축의 판정 — 숫자 누락 · 신규 수치 · 인용 훼손 · 원문 복제.
    사전이 필요한 축 (구단 · 인명) 은 호출측이 따로 대조해 합친다."""
    missing = missing_numbers(source, output)
    extra = extra_numbers(source, output)
    quotes = missing_quotes(source, output)
    retention = char_ngram_retention(source, output)
    return {"missing": missing, "extra": extra, "quotes": quotes,
            "retention": retention,
            "ok": not missing and not extra and not quotes
            and retention <= threshold}


def select_best(attempts: list[dict]) -> dict:
    """위반이 가장 적은 시도 — 동률이면 잔존율이 낮은 것.
    본문을 버리지 않으므로 항상 하나를 돌려준다.
    축 키가 없는 시도도 받는다 (누락 축만 쓰던 호출측 호환)."""
    def violations(a: dict) -> int:
        return sum(len(a.get(k) or []) for k in
                   ("missing", "extra", "quotes", "names", "clubs"))
    return min(attempts, key=lambda a: (violations(a), a["retention"]))
```

- [ ] **Step 4: 재시도 문구 3종을 더한다**

`src/bullet_in/enrich.py` 의 `DUPLICATE_RETRY` 아래에 넣는다.

```python
EXTRA_RETRY = (
    "\n\n[신규 수치] 직전 시도는 원문에 없는 숫자를 만들었다 — {tokens}.\n"
    "원문에 없는 수치는 쓰지 않는다.")
QUOTE_RETRY = (
    "\n\n[인용 훼손] 직전 시도는 원문 인용문을 바꿔 썼다 — {quotes}.\n"
    "따옴표 안 발화는 원문 그대로 옮긴다.")
INJECTION_RETRY = (
    "\n\n[구단 주입] 직전 시도는 원문에 없는 구단을 넣었다 — {clubs}.\n"
    "\n[인명 주입] 직전 시도는 원문에 없는 인물을 넣었다 — {names}.\n"
    "원문에 나오지 않는 구단 · 인물은 쓰지 않는다.")
```

- [ ] **Step 5: 재작성 루프를 넓힌다**

`rewrite_rows_guarded` 를 아래로 바꾼다.

```python
def rewrite_rows_guarded(rows: list[dict], client, model: str,
                         threshold: float = RETENTION_THRESHOLD,
                         max_attempts: int = 3,
                         name_map: dict[str, str] | None = None,
                         club_map: dict[str, list[str]] | None = None
                         ) -> tuple[dict[str, dict], dict[str, dict]]:
    """게시글 본문 재작성 — 게이트 4축에 걸리면 사유를 붙여 재생성하고 최선을 채택한다.

    게이트는 재생성 트리거이지 폐기 조건이 아니다 (스펙 §4.4 · 사용자 확정 2026-08-03).
    네 축 = 구단 · 인명 · 수치 (누락 · 신규) · 인용 보존.
    반환: (결과, 리포트) — 리포트는 잔존율 · 축별 잔존 기록 · ops 노출용."""
    name_map, club_map = name_map or {}, club_map or {}
    results: dict[str, dict] = {}
    reports: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        source = r.get("body_source") or r.get("body_excerpt") or ""
        base = PARAPHRASE_PROMPT.format(title=r["title_original"], body=source)
        attempts: list[dict] = []
        rate_limited = False
        for i in range(max_attempts):
            note = ""
            if attempts:
                last = attempts[-1]
                if last["missing"]:
                    note += MISSING_RETRY.format(tokens=", ".join(last["missing"]))
                if last["extra"]:
                    note += EXTRA_RETRY.format(tokens=", ".join(last["extra"]))
                if last["quotes"]:
                    note += QUOTE_RETRY.format(quotes=" / ".join(last["quotes"]))
                if last["clubs"] or last["names"]:
                    note += INJECTION_RETRY.format(
                        clubs=", ".join(last["clubs"]) or "없음",
                        names=", ".join(last["names"]) or "없음")
                if last["retention"] > threshold:
                    note += DUPLICATE_RETRY
            try:
                msg = client.models.generate_content(
                    model=model, contents=base + note,
                    config={"max_output_tokens": 8192,
                            "response_mime_type": "application/json"})
            except Exception as e:
                if _is_rate_limit(e):
                    log.warning("Gemini rate limit(429), 재작성 중단 — 남은 행 다음 사이클")
                    rate_limited = True
                    break
                log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
                break
            parsed = _extract_full(msg.text)
            if parsed is None:
                log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
                break
            v = gate_verdict(source, parsed["body_ko"] or "", threshold)
            names = detect_name_injection(parsed, source, name_map)
            clubs = detect_club_injection(parsed, source, club_map)
            attempts.append({"parsed": parsed, "missing": v["missing"],
                             "extra": v["extra"], "quotes": v["quotes"],
                             "names": names, "clubs": clubs,
                             "retention": v["retention"]})
            if v["ok"] and not names and not clubs:
                break
        if rate_limited:
            break
        if not attempts:
            continue
        best = select_best(attempts)
        results[h] = best["parsed"]
        reports[h] = {"retention": best["retention"], "missing": best["missing"],
                      "extra": best["extra"], "quotes": best["quotes"],
                      "names": best["names"], "clubs": best["clubs"],
                      "attempts": len(attempts)}
        if (best["retention"] > threshold or best["missing"] or best["extra"]
                or best["quotes"] or best["names"] or best["clubs"]):
            log.warning("재작성 게이트 잔존 content_hash=%s 잔존율=%.3f 누락=%s "
                        "신규수치=%s 인용훼손=%s 인명=%s 구단=%s 시도=%d",
                        h, best["retention"], best["missing"], best["extra"],
                        best["quotes"], best["names"], best["clubs"], len(attempts))
    return results, reports
```

- [ ] **Step 6: `run.py` 가 사전을 넘기게 한다**

`src/bullet_in/run.py` 에서 `glossary` · `name_map` · `club_map` 을 읽는 블록 (현재 138~145줄) 을 `missing = mart.rows_missing_translation()` 바로 위로 옮긴다.
그리고 재작성 호출에 사전을 넘긴다.

```python
    rewritten, gate_reports = rewrite_rows_guarded(
        rewrite_rows, client, GEMINI_MODEL, name_map=name_map, club_map=club_map)
```

옮긴 자리에는 아무것도 남기지 않는다 — `finals` 계산은 같은 변수를 그대로 쓴다.

- [ ] **Step 7: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 8: 커밋한다**

```bash
git add src/bullet_in/fidelity.py src/bullet_in/enrich.py src/bullet_in/run.py \
        tests/test_fidelity.py tests/test_enrich.py
git commit -F - <<'EOF'
feat(enrich): 재작성 게이트를 4축으로 넓히고 재생성 트리거로 통일

구단 축만 있던 게이트에 인명 · 신규 수치 · 인용 보존을 더한다. 위반은 폐기가
아니라 재생성 사유로 프롬프트에 붙고, 최대 시도 후에는 위반이 가장 적은
결과를 채택한다.

- 판정: gate_verdict 에 extra · quotes 추가 · 사전 축 2종은 루프가 직접 대조
- 채택: select_best 를 축 위반 총합 기준으로 변경
- 재시도: 축별 사유 문구 3종 추가
- 배선: run.py 가 사전 로딩을 재작성 앞으로 옮겨 name_map · club_map 전달

Refs: #85
EOF
```

---

### Task 7: 프롬프트를 정보 단위 2단 구조로 바꾼다

현행 `PARAPHRASE_PROMPT` 는 문장 단위 대응 재작성이다.
그래서 표현이 남아 텍스트 매칭에 걸리고 (실측 잔존율 최대 0.958), 문장을 옮기다 뉘앙스가 이동한다.
E안 은 사실 단위를 먼저 뽑고 그 목록만 재료로 구조를 다시 짜게 한다.
목록 밖 내용이 나오면 스스로 버리라고 지시하고, 인용문은 재작성에서 제외한다.

**Files:**
- Modify: `src/bullet_in/enrich.py:65-100`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Produces: `PARAPHRASE_PROMPT` — JSON 계약은 그대로다 (`title_ko` · `summary_ko` · `summary3_ko` · `body_ko` · `players`).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_paraphrase_prompt_is_information_unit_two_stage():
    from bullet_in.enrich import PARAPHRASE_PROMPT
    # 1단계 = 사실 단위 추출 · 2단계 = 목록만 재료로 재편
    assert "사실 단위" in PARAPHRASE_PROMPT
    assert "문장 단위로 대응" in PARAPHRASE_PROMPT
    assert "목록에 없는" in PARAPHRASE_PROMPT
    # 인용문은 재작성 제외 — 게이트 인용 축과 계약이 같아야 한다
    assert "인용문" in PARAPHRASE_PROMPT
    # JSON 계약 유지
    for key in ("title_ko", "summary_ko", "summary3_ko", "body_ko", "players"):
        assert key in PARAPHRASE_PROMPT
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_enrich.py -v -k information_unit`
Expected: FAIL — `"사실 단위" in PARAPHRASE_PROMPT` 가 거짓이다.

- [ ] **Step 3: 프롬프트를 교체한다**

`src/bullet_in/enrich.py` 의 `PARAPHRASE_PROMPT` 를 아래로 바꾼다.

```python
PARAPHRASE_PROMPT = (
    "다음은 한국어로 옮겨진 아스날 FC 축구 기사다. 두 단계로 다시 쓴다.\n"
    "1단계 — 원문에서 사실 단위를 모두 뽑는다: 누가 · 무엇을 · 얼마에 · 언제 · "
    "어느 구단과 · 어떤 상태인지. 평가와 전망도 원문이 말한 것이면 사실 단위다.\n"
    "2단계 — 그 목록만 재료로 삼아 글을 새로 구성하고 표현을 전부 바꾼다. "
    "원문 문장을 하나씩 문장 단위로 대응해 옮기지 않는다. "
    "쓰다가 목록에 없는 내용이 나오면 그 문장을 버린다.\n"
    "규칙:\n"
    "- title_ko: 제목을 간결한 기사 제목체로 다시 쓴다 (말머리 대괄호 제거).\n"
    "- summary_ko: 한 문장 요약, 평어체.\n"
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
    "- body_ko: 사실 단위를 하나도 빠뜨리지 않고 전부 담는다. 요약이 아니다. "
    "2~4문장 단위 문단으로 나누고 문단 사이는 줄바꿈 문자(\\n)로 구분한다.\n"
    "- body_ko 지문은 신문 평어체(종결어미 '~다'): '관심을 갖고 있습니다' ❌ → "
    "'관심을 갖고 있다' ⭕.\n"
    "- 인용문(따옴표 안 발화)은 재작성 대상이 아니다. 큰따옴표를 포함해 원문 "
    "글자 그대로 옮긴다. 줄이거나 다듬지 않는다.\n"
    "- 사실 · 수치 · 고유명사 · 평가 · 인과를 새로 만들지 않는다. 원문에 없는 "
    "구단명 · 사람 이름 · 숫자를 쓰면 안 된다.\n"
    "- 원문에 나오는 모든 숫자 (금액 · 나이 · 연도 · 경기 수 · 기록) 를 하나도 "
    "빠뜨리지 않는다.\n"
    "- 숫자는 원문 표기를 그대로 쓴다 (£50m 을 5,000만 파운드로 바꾸지 않는다).\n"
    "- 원문에 없는 수식어 · 부사 · 역할 명칭 (미드필더 · 공격수 · 감독 등) 을 "
    "붙이지 않는다.\n"
    "- 원문에 없는 시간 · 정도 표현 (즉시 · 이미 · 크게 · 확고히 · 전격 등) 을 "
    "넣지 않는다.\n"
    "- 원문이 단정한 것을 추측으로, 추측한 것을 단정으로 바꾸지 않는다.\n"
    "- 구독·앱 설치·댓글 유도, SNS 팔로우 요청, 팟캐스트·뉴스레터 홍보 등 "
    "기사 내용과 무관한 문구는 body_ko에서 제외.\n"
    "- body_ko 경량 마크다운: 원문의 소제목은 '### ', 원문이 강조한 구절만 "
    "'**굵게**', 인용 블록은 '> '. 원문에 없는 소제목 · 장식은 만들지 않는다.\n"
    "- players: 이 기사에서 아스날의 이적 · 거취 · 계약과 관련해 다뤄진 선수 · 감독 "
    "목록. 아스날과 무관한 타 구단 간 소식의 인물은 넣지 않는다. 각 항목은 "
    '{{"full_name":"영문 풀네임","ko":"이 기사에서 쓴 한글 표기","stage":"단계"}}.\n'
    "- stage 는 rumour · interest · negotiating · personal_terms · medical · agreed · "
    "other 중 하나. 경기 · 근황만 다뤄진 인물은 other, 기사에 없는 인물은 넣지 않는다.\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],'
    '"body_ko":"...","players":[{{"full_name":"...","ko":"...","stage":"..."}}]}}'
    "\n\nTitle: {title}\nBody: {body}")
```

- [ ] **Step 4: 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -F - <<'EOF'
feat(enrich): 재작성 프롬프트를 정보 단위 2단 구조로 교체

문장 단위로 대응해 옮기던 방식이라 표현이 남고 (실측 잔존율 최대 0.958)
뉘앙스가 이동했다. 사실 단위를 먼저 뽑고 그 목록만 재료로 다시 구성하게 한다.

- 1단계: 사실 단위 추출 — 누가 · 무엇을 · 얼마에 · 언제 · 어느 구단과
- 2단계: 목록만 재료로 재구성 · 목록 밖 문장은 자체 폐기
- 인용문: 재작성 제외 · 원형 보존 (게이트 인용 축과 같은 계약)
- 금지: 사실 · 수치 · 고유명사 · 평가 · 인과의 신규 생성

Refs: #85
EOF
```

---

### Task 8: 소급 재작성 CLI 를 만든다

새 프롬프트와 게이트를 이미 저장된 79행에 적용한다.
번역 4필드를 NULL 로 비우고 회차를 기다리는 방식은 쓰지 않는다 — 비우는 창에 재렌더가 겹치면 빈 페이지가 공개된다 (2026-08-02 실사고).
행별로 계산을 마친 뒤 갱신하므로 NULL 창이 없다.

**Files:**
- Create: `src/bullet_in/backfill_rewrite.py`
- Modify: `src/bullet_in/storage/mariadb.py`
- Test: `tests/test_backfill_rewrite.py`

**Interfaces:**
- Consumes: `rewrite_rows_guarded` · `finalize_translation` · `MartStore.set_translation` · `MartStore.set_rewrite_retention`.
- Produces: `MartStore.rows_rewritten() -> list[dict]` · `backfill_rewrite.run(mart, pstore, client, model, limit, dry_run) -> tuple[int, int]`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backfill_rewrite.py` 를 만든다.

```python
from bullet_in.backfill_rewrite import run


class _Mart:
    def __init__(self, rows):
        self._rows = rows
        self.saved = {}
        self.retentions = {}

    def rows_rewritten(self):
        return list(self._rows)

    def set_translation(self, h, t, s, s3, b):
        self.saved[h] = (t, s, s3, b)

    def set_rewrite_retention(self, h, r):
        self.retentions[h] = r


class _Msg:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self):
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        return _Msg('{"title_ko":"새 제목","summary_ko":"새 요약",'
                    '"summary3_ko":["1","2","3"],'
                    '"body_ko":"아스날이 영입을 마무리한다.","players":[]}')


class _Client:
    def __init__(self):
        self.models = _Models()


ROWS = [{"content_hash": "h1", "source_id": "fmkorea", "title_original": "아스날 영입",
         "body_source": "아스날이 영입을 마무리한다.", "body_level": 1,
         "summary_ko": "옛 요약", "body_excerpt": None, "url": "u", "outlet": "BBC"},
        {"content_hash": "h2", "source_id": "fmkorea", "title_original": "아스날 잔류",
         "body_source": "아스날이 잔류를 확정한다.", "body_level": 1,
         "summary_ko": "옛 요약", "body_excerpt": None, "url": "u", "outlet": "BBC"}]


def test_backfill_rewrites_and_saves():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={})
    assert (done, total) == (2, 2)
    assert mart.saved["h1"][0] == "새 제목"
    assert "h1" in mart.retentions


def test_backfill_limit_caps_rows():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={},
                      limit=1)
    assert (done, total) == (1, 1)
    assert list(mart.saved) == ["h1"]


def test_backfill_dry_run_saves_nothing():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={},
                      dry_run=True)
    assert (done, total) == (2, 2)
    assert mart.saved == {}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_backfill_rewrite.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.backfill_rewrite'`.

- [ ] **Step 3: 대상 조회 메서드를 더한다**

`src/bullet_in/storage/mariadb.py` 의 `rows_missing_translation` 아래에 넣는다.

```python
    def rows_rewritten(self) -> list[dict]:
        """재작성 경로로 이미 채워진 행 — 소급 재작성 대상 선정용.
        rows_missing_translation 과 같은 컬럼을 돌려준다 (같은 함수들이 소비한다)."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,url,source_id,title_original,body_excerpt,"
                "body_source,body_level,outlet,summary_ko "
                "FROM articles WHERE body_level=1 AND title_ko IS NOT NULL "
                "ORDER BY content_hash")).mappings().all()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: CLI 를 만든다**

`src/bullet_in/backfill_rewrite.py` 를 만든다.

```python
"""게시글 본문 기반 행의 소급 재작성 — 정보 단위 프롬프트 · 게이트 4축 재적용.

번역 4필드를 NULL 로 비우고 회차를 기다리지 않는다.
비우는 창에 재렌더가 겹치면 빈 페이지가 공개되기 때문이다 (2026-08-02 실사고).
행별로 계산을 마친 뒤 갱신하므로 NULL 창이 없다.
"""
from __future__ import annotations
import argparse, logging, os
from pathlib import Path

import yaml
from google import genai
from sqlalchemy import create_engine

from bullet_in.enrich import finalize_translation, rewrite_rows_guarded
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)


def run(mart, client, model: str, *, glossary: dict, name_map: dict,
        club_map: dict, limit: int | None = None,
        dry_run: bool = False) -> tuple[int, int]:
    """대상 행을 한 건씩 재작성해 저장한다 → (저장 건수, 대상 건수).

    한 건씩 도는 이유는 429 로 중단돼도 이미 처리한 행이 온전히 남게 하기
    위해서다. 재작성은 멱등이 아니므로 (표현이 매번 달라진다) 중단 후
    재실행하면 남은 행부터가 아니라 처음부터 다시 돈다 — --limit 으로 나눠 돈다.
    """
    rows = mart.rows_rewritten()
    if limit is not None:
        rows = rows[:limit]
    done = 0
    for r in rows:
        results, reports = rewrite_rows_guarded(
            [r], client, model, name_map=name_map, club_map=club_map)
        v = results.get(r["content_hash"])
        if v is None:
            log.warning("재작성 실패 — 건너뜀 content_hash=%s", r["content_hash"])
            continue
        title_ko, s_ko, s3_ko, body_ko, _ = finalize_translation(
            v, r, glossary, name_map, club_map)
        if dry_run:
            log.info("[dry-run] %s 제목=%s 잔존율=%.3f",
                     r["content_hash"][:8], title_ko,
                     reports[r["content_hash"]]["retention"])
            done += 1
            continue
        mart.set_translation(r["content_hash"], title_ko, s_ko, s3_ko, body_ko)
        mart.set_rewrite_retention(r["content_hash"],
                                   reports[r["content_hash"]]["retention"])
        done += 1
    return done, len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처리할 행 수 상한")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    a = ap.parse_args()

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.run import GEMINI_MODEL

    def _cfg(path: str, key: str) -> dict:
        return (yaml.safe_load(Path(path).read_text()) or {}).get(key, {})

    done, total = run(mart, client, GEMINI_MODEL,
                      glossary=_cfg("config/glossary.yaml", "replacements"),
                      name_map=PlayerStore(engine).gate_name_map(),
                      club_map=_cfg("config/club_map.yaml", "clubs"),
                      limit=a.limit, dry_run=a.dry_run)
    print(f"소급 재작성: {done} / {total} 행")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `uv run pytest tests/test_backfill_rewrite.py -v`
Expected: PASS.

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 7: 커밋하고 PR ② 를 연다**

```bash
git add src/bullet_in/backfill_rewrite.py src/bullet_in/storage/mariadb.py \
        tests/test_backfill_rewrite.py
git commit -F - <<'EOF'
feat(enrich): 게시글 본문 기반 행의 소급 재작성 CLI

새 프롬프트와 게이트를 이미 저장된 행에 적용한다. 번역 필드를 비우고 회차를
기다리는 방식은 쓰지 않는다 — 비우는 창에 재렌더가 겹치면 빈 페이지가 공개된다.

- 대상: MartStore.rows_rewritten — body_level 1 이면서 번역이 있는 행
- 처리: 행별로 계산을 마친 뒤 갱신 · NULL 창 없음
- 인자: --limit 으로 나눠 돌기 · --dry-run 으로 저장 없이 확인

Refs: #85
EOF
```

---

### Task 9: 워치리스트 배치에 요청 간격을 넣는다

배치는 검색 10건과 글 fetch 를 17초에 몰아 보낸다 (분당 약 56요청).
정기 회차는 24요청을 43초에 보낸다 (분당 약 35요청).
배치 밀도가 회차의 1.6배이고 실패율도 4회 중 2회로 회차의 18% 보다 높다.
표본이 작아 단정할 수는 없지만, 간격을 넣을 근거가 있는 유일한 지점이다.
2초를 주면 배치 밀도가 회차와 같아진다.

**Files:**
- Modify: `src/bullet_in/watchlist_fmkorea.py`
- Test: `tests/test_watchlist_fmkorea.py`

**Interfaces:**
- Consumes: `build_fmkorea_adapter(cfg, proxy, *, request_gap_sec=...)` (기존 인자).
- Produces: 모듈 상수 `REQUEST_GAP_SEC = 2.0`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_watchlist_batch_uses_request_gap():
    import yaml
    from pathlib import Path
    from bullet_in.collect_fmkorea import build_fmkorea_adapter
    from bullet_in.watchlist_fmkorea import REQUEST_GAP_SEC

    # 회차 밀도 (분당 약 35요청) 수준으로 낮추는 값이어야 한다
    assert REQUEST_GAP_SEC >= 1.0
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    a = build_fmkorea_adapter(cfg, None, request_gap_sec=REQUEST_GAP_SEC,
                              search_keywords=[{"keyword": "k", "target": "title"}])
    assert a.request_gap_sec == REQUEST_GAP_SEC
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -v -k request_gap`
Expected: FAIL — `ImportError: cannot import name 'REQUEST_GAP_SEC'`.

- [ ] **Step 3: 상수를 더하고 어댑터에 넘긴다**

`src/bullet_in/watchlist_fmkorea.py` 의 `MAX_POSTS` 아래에 상수를 넣는다.

```python
REQUEST_GAP_SEC = 2.0   # 검색 · 글 fetch 사이 간격 — 배치 밀도를 정기 회차 수준으로
```

어댑터 생성부를 바꾼다.

```python
    adapter = build_fmkorea_adapter(cfg, proxy, search_keywords=kws,
                                    max_posts=MAX_POSTS,
                                    request_gap_sec=REQUEST_GAP_SEC)
```

- [ ] **Step 4: 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: 실패 0.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/watchlist_fmkorea.py tests/test_watchlist_fmkorea.py
git commit -F - <<'EOF'
fix(watchlist): 배치 검색 사이에 요청 간격 도입

배치가 정기 회차보다 분당 요청 밀도가 1.6배 높다. 간격 2초를 주면 회차와
같은 밀도가 된다. 회차와 배치 빈도는 그대로 둔다.

- 상수: REQUEST_GAP_SEC 2.0 초
- 근거: 배치 16요청 / 17초 대 회차 24요청 / 43초
- 범위: 배치만 — 회차는 차단이 첫 요청보다 먼저 성립해 간격이 무효

Refs: #191
EOF
```

---

### Task 10: 430 실측과 오류 페이지 처리를 문서로 남긴다

430 의 원인을 배치로 지목한 기존 기록이 실측과 어긋난다.
기준값 (회차의 18%) 을 남겨 두면 나중에 어떤 조치를 하든 효과를 판정할 수 있다.

**Files:**
- Create: `docs/troubleshooting/2026-08-03-fmkorea-430-not-explained-by-our-requests.md`
- Modify: `docs/troubleshooting/2026-08-02-origin-error-page-stored-as-body.md`
- Modify: `docs/runbook/2026-07-19-enrich-only-pass.md`

**Interfaces:** 없음 — 문서 태스크다.

- [ ] **Step 1: 430 트러블슈팅 문서를 쓴다**

`docs/troubleshooting/2026-08-03-fmkorea-430-not-explained-by-our-requests.md` 에 아래를 담는다.

- 증상 — 08-03 06시 회차와 07:32 배치가 검색 전량 430 · 알림은 없었다.
- 반박된 가설 — 워치리스트 배치가 원인이라는 해석.
근거는 배치 첫 실행이 08-02 13:34 인데 430 은 07-28 부터 있었고, 배치 없는 기간 회차 44회 중 8회가 430 이었다는 것이다.
- 실측표 — 07-28 ~ 08-03 회차별 200 · 430 목록.
- 결정적 관찰 두 가지 — 성공 회차는 예외 없이 24요청 전량 200 이고 430 회차는 첫 요청부터 막힌다.
입력이 상수인데 출력만 갈린다.
- 기존 문서와의 관계 — `2026-07-30-fmkorea-contact-budget-and-search-reach.md` 의 "누적 접촉량" 결론은 3시간 가드를 우회해 몰아 쓴 백필의 얘기이고, 몰아 쓰지 않아도 18% 는 걸린다는 것이 이번에 더해진 사실이다.
- 조치 — 배치에만 간격 도입 · 회차와 빈도는 유지 (Task 9).
- 기준값 — 정기 회차 430 비율 18% (51회 중 9회 · 두 독립 표본이 일치).
- 알림 공백 — 이번에도 사람이 로그를 읽어 발견했다. 보강은 세션 F 몫이다.

- [ ] **Step 2: 오류 페이지 문서에 계통 처리 결과를 더한다**

`docs/troubleshooting/2026-08-02-origin-error-page-stored-as-body.md` §4 를 고친다.
"E안 몫" 이라고 미뤄 둔 자리에 실제 처리를 적는다.

- 판정은 길이 기준이다 (`origin_body_usable` · 200자).
- 근거는 등급 2 본문 273건 중 200자 미만이 오류 안내 2건뿐이라는 실측이다.
- 거부는 손실이 아니라 등급 하락이다.
- 제목 고유명사 대조는 넣지 않았다 — fmkorea 제목은 한국어이고 원문 본문은 영어라 대조에 사전 배선이 더 필요한데, 길이 축이 실측 사례를 모두 잡아 필요가 서지 않았다.

- [ ] **Step 3: 런북에 소급 재작성 절차를 더한다**

`docs/runbook/2026-07-19-enrich-only-pass.md` 에 `## 5.5. 소급 재작성 — 재작성 프롬프트를 바꿨을 때` 를 넣는다.

- §5 (번역 모델 교체) 와 다른 점은 번역 필드를 비우지 않는다는 것이다.
- 명령은 `uv run python -m bullet_in.backfill_rewrite --limit N` 이다.
- 재작성은 멱등이 아니다 — 중단 후 재실행하면 처음부터 다시 돈다.
- 스냅샷은 §5.1 을 그대로 쓴다.
- 끝나면 §4 로 사이트를 다시 만든다.

- [ ] **Step 4: 문서 서식 훅을 통과시킨다**

Run: `uv run pytest -q`
Expected: 실패 0.
문서 저장 시 PostToolUse 훅 (`.claude/hooks/check-doc-format.py`) 이 §2.2 서식을 검사한다 — 지적이 나오면 고친다.

- [ ] **Step 5: 커밋하고 PR ③ 을 연다**

```bash
git add docs/
git commit -F - <<'EOF'
docs: fmkorea 430 실측 · 오류 페이지 계통 처리 · 소급 재작성 절차

430 의 원인을 워치리스트 배치로 지목한 기록이 실측과 어긋나 바로잡는다.
나중에 조치 효과를 판정할 수 있도록 기준값을 함께 남긴다.

- 트러블슈팅: 배치 도입 전 회차 44회 중 8회가 430 · 인과 반박
- 기준값: 정기 회차 430 비율 18% (두 독립 표본 일치)
- 오류 페이지: 길이 기준 판정으로 계통 처리 · 고유명사 축 미도입 사유
- 런북: 소급 재작성 절차 (번역 필드를 비우지 않는 이유 포함)

Refs: #85, #191
EOF
```

---

## 운영 절차 (코드 밖 · PR 머지 후)

계획된 코드가 다 들어간 뒤 사람이 판단하며 도는 순서다.
각 단계는 앞 단계의 확인을 전제로 한다.

### A. 430 해소 확인

접촉 전에 직전 회차 로그를 읽는다. 접촉 0회로 상태를 알 수 있다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'sudo journalctl -u bullet-in --since "1 hour ago" --no-pager' \
  | grep "fmkorea.com/search" | grep -c "200 OK"
```

0 이 아니면 예산이 정상이다. 0 이면 다음 회차를 기다린다.

### B. 오류 페이지 2건 복구

대상은 `5a91615a` · `cc294b1b` 다.
절차는 트러블슈팅 문서 §3 의 `5afe41a2` 선례를 그대로 쓴다.

1. 게시글 본문을 회수한다 — `backfill_fmkorea_body.py --by-title --limit 1` 로 한 건씩 · 출력은 `tee` 로 남긴다.
2. `body_source` 를 교체하고 `body_level` 을 2 에서 1 로 내린다.
3. 번역 4필드와 분류 2필드를 NULL 로 되돌린다.
4. enrich 전용 패스로 재생성한다 (런북 §3).
5. 상세 페이지 본문이 실제 기사 내용인지 확인한다.

### C. 소급 재작성 79행

VM 이 새 코드에 있어야 한다 — `git pull` 을 먼저 한다.
정기 회차 시각 (KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21) 을 피한다.

```bash
uv run python -m bullet_in.backfill_rewrite --dry-run --limit 3   # 표본 확인
uv run python -m bullet_in.backfill_rewrite --limit 20            # 나눠 실행
```

먼저 `--dry-run --limit 3` 으로 표본을 눈으로 본다.
재작성 강도가 기대와 다르면 프롬프트를 다시 손보고 소급은 그다음이다.

### D. 재렌더 · 배포

런북 §4 의 실행 전 점검을 그대로 밟는다 — 도는 배치가 없는지 · 단계 빈 행이 0 인지 확인한 뒤 렌더한다.

### E. 검수 (E안 확정 조건)

재작성 표본을 원문과 사실 단위로 대조하는 수동 검수를 1회 한다.
평가 · 인과 창작은 코드 게이트로 못 잡는다 — 프롬프트 금지와 표본 검수로 낮추되 0 은 아니다.
이 한계는 트랙 메모리에 사용자가 극도로 경계한다고 적혀 있는 항목이라 검수 결과를 반드시 보고한다.
