# Tier 1 후속: BBC 수집 드리프트 교정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bbc_sport 가 main-content 기사 카드만, 깨끗한 제목으로 수집하도록 어댑터·설정을 교정하고, 그로 인해 적재된 기존 잡음을 정리한다.

**Architecture:** 범용 `HtmlAdapter` 에 선택적 `title_selector`(매칭 요소 안 헤드라인 sub-selector)를 추가하고, `bbc_sport` 의 `item_selector` 를 `[data-testid='main-content']` 로 좁힌다. 기존 잡음은 라이브 MariaDB 에서 런북 절차(COUNT → DELETE → 재수집)로 정리한다.

**Tech Stack:** Python 3.11 · uv · httpx + BeautifulSoup(soupsieve) · respx(테스트) · MariaDB.

## Global Constraints

- 테스트 실행: `uv run pytest -q` (통합 테스트는 DB/Airflow 없으면 skip).
- 산출물 본문은 한국어. 문서·커밋·PR 에서 `·` 및 괄호 양옆 띄우기(코드·URL 제외).
- 커밋: `<type>(<scope>): 한국어 제목` + 본문(왜) + `Refs:` + 트레일러. type/scope 는 영어.
- co-author 트레일러: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- karpathy 4원칙: 단순함 우선 · 수술적 변경 · 요청 범위 밖 기능 없음.
- 셀렉터 드리프트는 모킹으로 못 잡음 → 머지 전 어댑터 단독 `fetch()` 라이브 검증 필수.
- DB 접속: `set -a; source .env; set +a` 후 `docker compose ps` 로 mariadb running 확인.
- 브랜치: `fix/tier1-bbc-collection-drift` (이미 생성됨, spec 커밋 `b34d5b7` 존재).

---

### Task 1: HtmlAdapter `title_selector` 지원

매칭된 `item_selector` 요소 안에서 sub-selector 로 제목을 추출한다. sub-요소가 없으면 그 항목을 skip(제목 없는 항목 적재 방지). `title_selector` 미지정 시 기존 `get_text()` 동작 유지(하위호환).

**Files:**
- Modify: `src/bullet_in/adapters/html.py` (`__init__` 시그니처 · `fetch()` 제목 추출부)
- Test: `tests/test_html_adapter.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `HtmlAdapter(..., title_selector: str | None = None)` — 인스턴스 속성 `self.title_selector`. `fetch()` 동작: `title_selector` 지정 시 매칭 요소의 `select_one(title_selector)` 텍스트를 제목으로 사용, 미발견 시 항목 skip.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_html_adapter.py` 파일 끝에 추가:

```python
@respx.mock
def test_html_adapter_title_selector_extracts_clean_headline_and_scopes():
    # content-post(임베드 인라인 링크)는 item_selector 스코프 밖 → 제외,
    # main-content 카드만 수집하고 LinkPostHeadline 헤드라인만 추출(timestamp·visually-hidden 제거)
    html = (
        '<div data-testid="content-post">'
        '<a href="/sport/football/articles/junk">Want more transfer stories? Read gossip column</a>'
        '</div>'
        '<div data-testid="main-content">'
        '<a href="/sport/football/articles/abc">'
        '<span class="ssrcss-1-Timestamp">21:19 BST 29 June</span>'
        '<span class="visually-hidden ssrcss-2-VisuallyHidden">Bournemouth reject Arsenal interest, published at 21:19</span>'
        '<span class="ssrcss-3-LinkPostHeadline">Bournemouth reject Arsenal interest</span>'
        '</a>'
        '</div>'
    )
    respx.get("https://bbc.test/arsenal").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://bbc.test/arsenal",
                    item_selector="[data-testid='main-content'] a[href*='/sport/football/articles/']",
                    base_url="https://bbc.test",
                    title_selector="span[class*='LinkPostHeadline']")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].url == "https://bbc.test/sport/football/articles/abc"
    assert items[0].raw_payload["title"] == "Bournemouth reject Arsenal interest"


@respx.mock
def test_html_adapter_skips_item_when_title_selector_not_found():
    html = (
        '<div data-testid="main-content">'
        '<a href="/sport/football/articles/abc"><span class="other">no headline span</span></a>'
        '</div>'
    )
    respx.get("https://bbc.test/arsenal").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://bbc.test/arsenal",
                    item_selector="[data-testid='main-content'] a[href*='/sport/football/articles/']",
                    base_url="https://bbc.test",
                    title_selector="span[class*='LinkPostHeadline']")
    assert asyncio.run(a.fetch()) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py::test_html_adapter_title_selector_extracts_clean_headline_and_scopes tests/test_html_adapter.py::test_html_adapter_skips_item_when_title_selector_not_found -v`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument 'title_selector'`)

- [ ] **Step 3: `__init__` 에 `title_selector` 추가**

`src/bullet_in/adapters/html.py` 의 `__init__` 시그니처와 본문 수정:

```python
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, title_contains: str | list[str] | None = None,
                 body_selector: str | None = None, title_selector: str | None = None):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.base_url = base_url or list_url
        self.body_selector = body_selector
        self.title_selector = title_selector
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
```

- [ ] **Step 4: `fetch()` 제목 추출부 수정**

`src/bullet_in/adapters/html.py` 의 `fetch()` 안, 현재의

```python
                title = a.get_text(strip=True)
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

를 다음으로 교체:

```python
                if self.title_selector:
                    el = a.select_one(self.title_selector)
                    if el is None:
                        continue  # 헤드라인 sub-요소 없음 → 제목 없는 항목 적재 방지
                    title = el.get_text(strip=True)
                else:
                    title = a.get_text(strip=True)
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
```

- [ ] **Step 5: 신규 테스트 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py -v`
Expected: PASS (신규 2건 + 기존 6건 모두 통과 — `title_selector` 미지정 기존 테스트가 하위호환 보장)

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/html.py tests/test_html_adapter.py
git commit -F - <<'EOF'
feat(adapter): HtmlAdapter에 title_selector 추가

매칭 요소 안에서 sub-selector로 헤드라인만 추출해, BBC 카드의
timestamp·visually-hidden 텍스트가 제목에 섞이는 드리프트를 막는다.
sub-요소 미발견 시 항목 skip, 미지정 시 기존 get_text() 폴백(하위호환).

Refs: docs/superpowers/specs/2026-06-30-tier1-collection-filter-refinement-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: factory 연결 · bbc_sport 설정 교정 · 라이브 검증

`title_selector` 를 config → factory → 어댑터로 흘려보내고, `bbc_sport` 의 `item_selector` 를 main-content 로 좁힌 뒤 `title_selector` 를 지정한다. 셀렉터 드리프트는 머지 전 라이브 `fetch()` 로 검증한다.

**Files:**
- Modify: `src/bullet_in/adapters/factory.py` (HtmlAdapter 생성부)
- Modify: `config/sources.yaml` (`bbc_sport` 항목)
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: Task 1 의 `HtmlAdapter(..., title_selector=...)`.
- Produces: `build_adapters` 가 html config 의 `title_selector` 키를 어댑터로 전달.

- [ ] **Step 1: 실패하는 factory 테스트 작성**

`tests/test_adapter_factory.py` 파일 끝에 추가:

```python
def test_factory_passes_title_selector_to_html():
    from bullet_in.adapters.html import HtmlAdapter
    cfg = {"sources": [{"source_id": "bbc_sport", "adapter": "html", "enabled": True,
            "config": {"list_url": "https://b.test",
                       "item_selector": "[data-testid='main-content'] a",
                       "title_selector": "span[class*='LinkPostHeadline']"}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.title_selector == "span[class*='LinkPostHeadline']"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_adapter_factory.py::test_factory_passes_title_selector_to_html -v`
Expected: FAIL (`assert None == "span[class*='LinkPostHeadline']"` — factory 가 title_selector 미전달)

- [ ] **Step 3: factory 에 title_selector 전달**

`src/bullet_in/adapters/factory.py` 의 html 분기 수정:

```python
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector"),
                                   title_selector=c.get("title_selector")))
```

- [ ] **Step 4: factory 테스트 통과 확인**

Run: `uv run pytest tests/test_adapter_factory.py -v`
Expected: PASS (신규 1건 + 기존 모두 통과)

- [ ] **Step 5: bbc_sport config 교정**

`config/sources.yaml` 의 `bbc_sport` 항목에서 `item_selector` 를 교체하고 `title_selector` 를 추가. 교정 후 해당 블록은 다음과 같다:

```yaml
  - source_id: bbc_sport
    display_name: BBC Sport
    tier: 2
    medium: newspaper
    adapter: html
    config:
      list_url: "https://www.bbc.com/sport/football/teams/arsenal"
      item_selector: "[data-testid='main-content'] a[href*='/sport/football/articles/']"
      title_selector: "span[class*='LinkPostHeadline']"
      title_contains: ["transfer", "sign", "signed", "signing", "deal", "loan", "bid", "fee", "medical", "agree", "agreed", "join", "joins", "target", "linked", "links", "contract", "swap", "move", "talks"]
      body_selector: "article"
    enabled: true
```

- [ ] **Step 6: 라이브 검증 (셀렉터 드리프트 — 머지 전 필수)**

Run:
```bash
uv run python - <<'PY'
import yaml, asyncio
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
cfg["sources"] = [s for s in cfg["sources"] if s["source_id"] == "bbc_sport"]
a = build_adapters(cfg)[0]
items = asyncio.run(a.fetch())
print("count:", len(items))
for it in items:
    print("-", it.raw_payload["title"][:90])
PY
```
Expected: 소수(수 건) 의 항목, 제목이 깨끗(앞에 `HH:MM BST` timestamp 없음, `, published at` 없음), `Want more transfer stories` · `Read more` · nav 링크 없음.
검증 실패 시(0건 또는 여전히 깨진 제목): BBC DOM 드리프트 → `data-testid` · `span[class*='LinkPostHeadline']` 를 라이브 HTML 로 재확인 후 셀렉터 갱신. 이 단계가 통과해야 다음으로 진행.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/adapters/factory.py tests/test_adapter_factory.py config/sources.yaml
git commit -F - <<'EOF'
fix(sources): bbc_sport 셀렉터를 main-content로 좁히고 title_selector 지정

BBC team 페이지의 content-post 인라인 링크(teaser·read-more·nav)가
수집되고 카드 제목이 timestamp로 깨지던 드리프트를 교정한다.
factory가 config의 title_selector를 어댑터로 전달.

Refs: docs/superpowers/specs/2026-06-30-tier1-collection-filter-refinement-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: 기존 데이터 정리 런북

라이브 MariaDB 의 bbc_sport 잡음(비-기사 · 깨진 제목)과 football.london 뉴스레터 legacy 를 정리하는 절차를 문서화한다. ③ 이적무관 실제 기사는 보존. 실행은 COUNT 확인 → DELETE → 재수집 순으로 신중히(파괴적 작업이므로 COUNT 결과를 사람이 확인한 뒤 DELETE).

**Files:**
- Create: `docs/runbook/2026-06-30-bbc-collection-cleanup.md`
- Modify: `docs/runbook/2026-06-28-arsenal-stale-cleanup.md` (무효 메모 추가)

**Interfaces:**
- Consumes: Task 2 의 교정된 어댑터(재수집이 깨끗한 bbc 데이터를 채움).
- Produces: 없음(문서).

- [ ] **Step 1: 정리 런북 작성**

`docs/runbook/2026-06-30-bbc-collection-cleanup.md` 생성:

````markdown
# 런북 — BBC 수집 드리프트 정리 (2026-06-30)

bbc_sport 셀렉터 교정(`fix/tier1-bbc-collection-drift`) 이전 적재된 비-기사 · 깨진-제목 행과
football.london 뉴스레터 legacy 링크를 일회성으로 정리한다.
**실행은 라이브 MariaDB 가 떠 있는 상태에서 직접 수행하며, COUNT 확인 후 DELETE 한다.**

## 선행
- bbc_sport 어댑터 교정(셀렉터 · title_selector)이 머지 · 배포돼 있어야 한다(재수집이 깨끗해야 의미 있음).
- 접속 준비:
  ```bash
  set -a; source .env; set +a
  docker compose ps   # mariadb running 확인
  ```

## 절차
1. 대상 수 확인(삭제 전 반드시):
   ```sql
   SELECT source_id, COUNT(*) FROM articles
   WHERE source_id = 'bbc_sport'
      OR (source_id = 'football_london'
          AND (LOWER(title_original) LIKE '%sent to your inbox%'
               OR LOWER(title_original) LIKE '%newsletter%'))
   GROUP BY source_id;
   ```
2. 삭제:
   ```sql
   DELETE FROM articles WHERE source_id = 'bbc_sport';
   DELETE FROM articles WHERE source_id = 'football_london'
     AND (LOWER(title_original) LIKE '%sent to your inbox%'
          OR LOWER(title_original) LIKE '%newsletter%');
   ```
3. 재수집 · 서빙 재생성:
   ```bash
   uv run python -m bullet_in.run
   ```
4. 검증:
   ```sql
   SELECT source_id, COUNT(*) FROM articles GROUP BY source_id;
   ```
   - bbc_sport: 깨끗한 제목의 main-content 기사만(소수).
   - football_london 뉴스레터: 0건.

## 주의
- **③ 이적무관 실제 기사(football.london 경기리포트 · 평점 · 킷 등)는 이번 정리 대상이 아니다(보존).**
  football.london DELETE 는 뉴스레터 패턴으로 한정한다.
- bbc_sport 전건 삭제는 현재 페이지 밖 과거 기사 유실을 수반한다(대부분 쓰레기라 수용).
- 3단계 `run` 은 전체 소스 재수집 + 신규 enrich(Gemini) 를 트리거한다. 무료 티어 429 시
  남은 건은 다음 사이클 누적(정상 동작).
````

- [ ] **Step 2: arsenal stale-cleanup 런북에 무효 메모 추가**

`docs/runbook/2026-06-28-arsenal-stale-cleanup.md` 의 제목(첫 줄) 바로 다음에 한 줄 삽입:

```markdown
> **상태(2026-06-30): 무효 — `articles` 의 `arsenal_official` 행 0건이라 정리 대상 없음.** ([[2026-06-30-bbc-collection-cleanup]] 참조)
```

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-06-30-bbc-collection-cleanup.md docs/runbook/2026-06-28-arsenal-stale-cleanup.md
git commit -F - <<'EOF'
docs(runbook): BBC 수집 드리프트 정리 런북 추가

bbc_sport 비-기사·깨진-제목 행과 football.london 뉴스레터 legacy를
COUNT→DELETE→재수집으로 정리하는 절차를 문서화한다. ③ 이적무관 실제
기사는 보존. arsenal stale-cleanup 런북은 대상 0건이라 무효 메모.

Refs: docs/superpowers/specs/2026-06-30-tier1-collection-filter-refinement-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: 정리 실행 (라이브 DB — 사용자 확인 후)**

런북 절차를 실행한다. **파괴적 작업이므로 1단계 COUNT 결과를 사용자에게 보고하고 확인을 받은 뒤** 2단계 DELETE 를 진행한다.
- 1단계 COUNT 실행 → 결과 보고(예상: bbc_sport ~34, football_london 뉴스레터 ~1).
- 사용자 확인 후 2단계 DELETE → 3단계 `uv run python -m bullet_in.run` → 4단계 검증 COUNT.
- 검증 결과(소스별 건수, bbc 제목 클린 여부)를 보고.

이 단계는 커밋을 생성하지 않는다(라이브 DB · 서빙 재생성).

---

## 검증 (전체)

- [ ] `uv run pytest -q` — 신규 3건 포함 전체 통과, 기존 회귀 없음.
- [ ] Task 2 Step 6 라이브 검증 통과(bbc_sport 가 깨끗한 main-content 기사만).
- [ ] Task 3 실행 후: 소스별 건수에서 bbc 쓰레기 · football.london 뉴스레터 제거 확인, ③ 보존.

## PR (GitHub Flow · squash)
- 브랜치 `fix/tier1-bbc-collection-drift` → PR.
- PR 본문 7섹션 한국어 구조, `--body-file` 로 전달, Claude 서명 금지.
- 포함 커밋: spec/roadmap(`b34d5b7`) · Task 1 · Task 2 · Task 3 런북.
