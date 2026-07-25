# 온스테인 X 직접 수집 (PR 2) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** David Ornstein 의 X 계정을 직접 수집 소스로 추가해, afcstuff 인용에 의존하지 않고 아스날 딜 속보를 확보한다.

**Architecture:** 기존 `XPlaywrightAdapter` 에 `self_source` 플래그를 추가해 본인 트윗 파싱 경로 (`parse_self_tweets`) 를 신설한다.
인용 없는 트윗도 RawItem 으로 만들되 `#AFC` 해시태그가 있는 것만 남기고, `journalist` 는 config handle 로 고정한다.
리트윗은 status 링크의 작성자 세그먼트를 계정 주인 handle 과 대조해 걸러낸다 (tier 1 오귀속 가드 · 사용자 확정 A안 2026-07-26).
tier 는 `sources.yaml` 의 고정 `tier: 1` 로 산출된다 (`resolve_tier` 고정 소스 경로 · 코드 변경 불필요).
afcstuff 의 "인용만" 경로는 건드리지 않는다 (수술적 변경).

**Tech Stack:** Python 3.11 · pydantic v2 · Playwright (기존 X 어댑터 재사용) · pytest.

## Global Constraints

- spec: `docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md` §5 (§5.1~5.4) · §7 · §10 · §13.
- afcstuff 경로 (`parse_afcstuff_tweets` · backtrack) 는 수정 금지 — 기존 테스트가 회귀 가드.
- 온스테인은 backtrack 을 쓰지 않는다 (본인 트윗이 곧 원문 · `backtrack_config` 미전달)
  — The Athletic 링크는 승격 경로 자체가 돌지 않아 트윗 텍스트만 저장된다 (spec §5.3 충족).
- X 라이브 접촉은 쿠키 소모 최소화 — 단독 fetch 1회만, 명령은 tee 필수 · 출력 확인 목적 재실행 금지.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + Refs + co-author 트레일러 (컨벤션 §1).
- 새 의존성 없음 · DB 스키마 변경 없음.

---

### Task 1: `parse_self_tweets` — 본인 트윗 파싱 함수

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py` (함수 추가 + `_TWEET_JS` 에 `author` 필드 추가 — afcstuff 파싱은 이 키를 읽지 않아 무영향)
- Test: `tests/test_x_playwright.py` (테스트 추가 · 기존 테스트 무수정)

**Interfaces:**
- Consumes: `RawItem` (`bullet_in.models`) · 기존 `_rt` 테스트 헬퍼 · `NOW` 상수.
- Produces: `parse_self_tweets(source_id: str, handle: str, raw_tweets: list[dict], now: datetime) -> list[RawItem]`.
  raw_payload 키는 `text` · `created_at` · `journalist` (= `"@" + handle` 고정) · `image_url`.
  Task 2 의 어댑터 분기가 이 함수를 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_x_playwright.py` 끝에 추가한다.

```python
from bullet_in.adapters.x_playwright import parse_self_tweets

def test_self_source_keeps_uncited_afc_tweet():
    # 온스테인 본인 트윗: 인용([ @handle ]) 없음 — afcstuff 경로라면 버려질 형태 (spec §5.2)
    rts = [_rt(text="🚨 EXCL: Arsenal agree £60m deal for X #AFC", status_id="21")]
    items = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://x.com/David_Ornstein/status/21"
    assert it.source_type == "x"
    assert it.raw_payload["journalist"] == "@David_Ornstein"
    assert it.raw_payload["text"].startswith("🚨 EXCL")

def test_self_source_drops_tweets_without_afc_tag():
    # 관련성 필터 (spec §5.4): #AFC 없는 타 클럽 · 유사 태그(#AFCB 본머스 · #AFCON)는 드롭
    rts = [
        _rt(text="Chelsea close in on midfielder #CFC", status_id="22"),
        _rt(text="Bournemouth complete signing #AFCB", status_id="23"),
        _rt(text="AFCON squads announced #AFCON", status_id="24"),
    ]
    assert parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW) == []

def test_self_source_matches_afc_tag_mid_text():
    rts = [_rt(text="Arsenal + Sporting agree Gyokeres fee. #AFC latest on @TheAthleticFC", status_id="25")]
    items = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)
    assert len(items) == 1

def test_self_source_passes_image_and_created_at():
    rts = [_rt(text="Team news #AFC", image_url="https://img/o.jpg",
               created_at="2026-07-01T02:00:00.000Z", status_id="26")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["image_url"] == "https://img/o.jpg"
    assert it.raw_payload["created_at"] == "2026-07-01T02:00:00.000Z"

def test_self_source_drops_retweet_by_author_mismatch():
    # 리트윗 가드 (A안): status 링크 작성자가 계정 주인이 아니면 #AFC 가 있어도 드롭
    # — 리트윗은 원작자 status URL 이 잡히므로 author 세그먼트로 판별된다
    rts = [_rt(text="Arsenal have agreed a deal #AFC", status_id="27",
               author="SamiMokbel_BBC")]
    assert parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW) == []

def test_self_source_keeps_own_author_case_insensitive():
    rts = [_rt(text="Arsenal latest #AFC", status_id="28", author="david_ornstein")]
    assert len(parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)) == 1

def test_self_source_missing_author_passes_through():
    # DOM 이 author 를 못 뽑은 경우 (빈 문자열) 는 가드를 통과시킨다 — 실 DOM 에선 항상 존재
    rts = [_rt(text="Arsenal latest #AFC", status_id="29", author="")]
    assert len(parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_self_tweets'`.

- [ ] **Step 3: 최소 구현**

`_TWEET_JS` 에 작성자 세그먼트 캡처를 추가한다 (기존 `m` 정의 다음 줄 + 반환 객체에 `author` 키).
afcstuff 경로 (`parse_afcstuff_tweets`) 는 이 키를 읽지 않으므로 무영향이다.

```javascript
  const am = href ? href.match(/^\/([A-Za-z0-9_]+)\/status\//) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    author: am ? am[1] : '',
    image_url: img ? img.src : null
  };
```

`parse_afcstuff_tweets` 아래에 추가한다 (`_CITE_RE` 정의부 옆에 정규식 상수).

```python
_AFC_TAG_RE = re.compile(r"#AFC\b", re.IGNORECASE)
```

```python
def parse_self_tweets(source_id: str, handle: str,
                      raw_tweets: list[dict], now: datetime) -> list[RawItem]:
    """본인 트윗 파싱(self_source) — 인용 불요, #AFC 태그 있는 것만 RawItem (spec §5.2·§5.4).
    #AFCB(본머스)·#AFCON 은 \\b 경계로 자연 배제. journalist 는 계정 주인으로 고정.
    리트윗은 status 링크 작성자(author)가 계정 주인과 달라 드롭된다 (tier 1 오귀속 가드)."""
    out: list[RawItem] = []
    for t in raw_tweets:
        author = t.get("author") or ""
        if author and author.lower() != handle.lower():
            continue
        text = t.get("text") or ""
        if not _AFC_TAG_RE.search(text):
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": "@" + handle,
                         "image_url": t.get("image_url")}))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: PASS (기존 afcstuff 테스트 포함 전부).

- [ ] **Step 5: 커밋**

```bash
git add tests/test_x_playwright.py src/bullet_in/adapters/x_playwright.py
git commit  # feat(adapters): 온스테인 본인 트윗 파싱 함수 — #AFC 관련성 필터
```

---

### Task 2: 어댑터 `self_source` 분기 · factory 스레딩

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py:97-101` (`__init__`) · `:120-121` (`fetch` 파싱 지점)
- Modify: `src/bullet_in/adapters/factory.py:41-45` (`x_playwright` 분기)
- Test: `tests/test_x_playwright.py` · `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: Task 1 의 `parse_self_tweets`.
- Produces: `XPlaywrightAdapter(source_id, handle, max_tweets=20, cookies_path="x_cookies.json", backtrack_config_path=None, self_source=False)`.
  파서 선택은 `_parse_tweets(self, raw_tweets: list[dict], now: datetime) -> list[RawItem]` 메서드로 노출 (playwright 없이 단위 테스트 가능).
  factory 는 config 의 `self_source` (기본 False) 를 그대로 전달한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_x_playwright.py` 에 추가한다.

```python
from bullet_in.adapters.x_playwright import XPlaywrightAdapter

def test_adapter_parse_tweets_self_source_branch():
    a = XPlaywrightAdapter("x_ornstein", "David_Ornstein", self_source=True)
    rts = [_rt(text="Deal done #AFC", status_id="31"),
           _rt(text="News [ @SamiMokbel_BBC ]", status_id="32")]  # 인용은 있으나 #AFC 없음 → 드롭
    items = a._parse_tweets(rts, NOW)
    assert [i.raw_payload["journalist"] for i in items] == ["@David_Ornstein"]
    assert items[0].url == "https://x.com/David_Ornstein/status/31"

def test_adapter_parse_tweets_default_afcstuff_branch():
    # 회귀 가드: 기본값(self_source 미지정)은 기존 "인용만" 경로 그대로 (spec §5.2)
    a = XPlaywrightAdapter("x_afcstuff", "afcstuff")
    rts = [_rt(text="Deal done #AFC", status_id="31"),
           _rt(text="News [ @SamiMokbel_BBC ]", status_id="32")]
    items = a._parse_tweets(rts, NOW)
    assert [i.raw_payload["journalist"] for i in items] == ["@SamiMokbel_BBC"]
```

`tests/test_adapter_factory.py` 에 추가한다.

```python
def test_factory_passes_self_source_to_x_playwright():
    cfg = {"sources": [{"source_id": "x_ornstein", "adapter": "x_playwright", "enabled": True,
                        "config": {"handle": "David_Ornstein", "self_source": True}}]}
    a = build_adapters(cfg)[0]
    assert a.self_source is True

def test_factory_x_playwright_defaults_to_cited_path():
    cfg = {"sources": [{"source_id": "x_afcstuff", "adapter": "x_playwright", "enabled": True,
                        "config": {"handle": "afcstuff"}}]}
    a = build_adapters(cfg)[0]
    assert a.self_source is False
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_playwright.py tests/test_adapter_factory.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'self_source'`.

- [ ] **Step 3: 최소 구현**

`x_playwright.py` `__init__` 시그니처 확장과 저장:

```python
    def __init__(self, source_id: str, handle: str, max_tweets: int = 20,
                 cookies_path: str = "x_cookies.json", backtrack_config_path: str | None = None,
                 self_source: bool = False):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path
        self.backtrack_config_path = backtrack_config_path
        self.self_source = self_source
```

`fetch` 의 `items = parse_afcstuff_tweets(...)` 한 줄을 메서드 호출로 교체하고, 메서드를 추가한다:

```python
            items = self._parse_tweets(raw_tweets, now)
```

```python
    def _parse_tweets(self, raw_tweets: list[dict], now: datetime) -> list[RawItem]:
        """파서 선택 — self_source 면 본인 트윗 경로, 아니면 기존 인용 경로 (spec §5.2)."""
        if self.self_source:
            return parse_self_tweets(self.source_id, self.handle, raw_tweets, now)
        return parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets, now)
```

`factory.py` 의 `x_playwright` 분기에 전달 인자 추가:

```python
        elif kind == "x_playwright":
            out.append(XPlaywrightAdapter(sid, c["handle"],
                                          c.get("max_tweets", 20),
                                          c.get("cookies_path", "x_cookies.json"),
                                          c.get("backtrack_config"),
                                          self_source=c.get("self_source", False)))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_x_playwright.py tests/test_adapter_factory.py tests/test_x_backtrack.py -q`
Expected: PASS (backtrack 포함 회귀 무결).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/x_playwright.py src/bullet_in/adapters/factory.py \
        tests/test_x_playwright.py tests/test_adapter_factory.py
git commit  # feat(adapters): X 어댑터 self_source 분기 — factory 스레딩
```

---

### Task 3: `x_ornstein` 소스 등록 · 실제 config 계약 테스트

**Files:**
- Modify: `config/sources.yaml` (x_afcstuff 항목 바로 아래에 신규 소스)
- Modify: `tests/test_serving_config.py:7-9` (`FULL_SOURCES` 집합에 `x_ornstein` 추가 — 정확 일치 검증이라 누락 시 실패)
- Test: `tests/test_credibility.py` (실 config 고정 tier 계약 테스트 추가)

**Interfaces:**
- Consumes: Task 2 의 factory `self_source` 전달.
- Produces: `load_sources("config/sources.yaml")` 결과에 `x_ornstein` (tier 1 · adapter x_playwright) 존재.
  파이프라인 (`to_articles` → `resolve_tier`) 은 코드 변경 없이 이 config 만으로 tier 1 을 산출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_credibility.py` 에 추가한다 (파일 상단의 기존 import 재사용).

```python
def test_live_config_x_ornstein_fixed_tier_one():
    """spec 2026-07-25 §5.1 — 본인 트윗엔 @핸들이 없어 x_mentions 판정 불가, 고정 tier 1."""
    from datetime import datetime, timezone
    from bullet_in.models import RawItem
    from bullet_in.score import load_sources
    sources = load_sources("config/sources.yaml")
    assert sources["x_ornstein"]["tier"] == 1
    assert sources["x_ornstein"]["config"]["self_source"] is True
    registry = load_registry("config/credibility.yaml")
    it = RawItem(source_id="x_ornstein", source_type="x",
                 url="https://x.com/David_Ornstein/status/1",
                 fetched_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
                 raw_payload={"text": "Arsenal deal #AFC", "journalist": "@David_Ornstein"})
    assert resolve_tier(it, sources, registry, journalist="@David_Ornstein") == 1.0
```

`tests/test_serving_config.py` 의 집합을 갱신한다.

```python
FULL_SOURCES = {"arsenal_official", "x_afcstuff", "x_ornstein", "fmkorea",
                "bbc_sport", "bbc_gossip", "skysports", "guardian",
                "goal", "football_london"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_credibility.py tests/test_serving_config.py -q`
Expected: FAIL — `KeyError: 'x_ornstein'` · serving 집합 불일치.

- [ ] **Step 3: config 작성**

`config/sources.yaml` 의 `x_afcstuff` 항목 바로 아래에 추가한다.

```yaml
  - source_id: x_ornstein
    display_name: David Ornstein (X)
    serving: full      # 상세 페이지 서빙 범위 (spec §2.3) — 트윗 원문은 수십 단어 = 인용 수준
    medium: x
    adapter: x_playwright
    tier: 1            # 고정 tier — 본인 트윗엔 @핸들이 없어 x_mentions 판정 불가 (spec 2026-07-25 §5.1)
    freshness_hours: 24   # X 는 고빈도 소스 — 전역 48h 보다 좁게 감시 (afcstuff 와 동일)
    config: { handle: "David_Ornstein", max_tweets: 30, cookies_path: "x_cookies.json", self_source: true }
    enabled: true
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest -q`
Expected: 전체 PASS (통합은 DB 없으면 skip).

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml tests/test_credibility.py tests/test_serving_config.py
git commit  # feat(collect): x_ornstein 소스 등록 — 고정 tier 1 · self_source
```

---

### Task 4: 라이브 표본 검증 (컨트롤러 직접 · X 접촉 1회)

**Files:**
- Create: 없음 (스크래치패드 1회용 스크립트 · 리포지토리에 남기지 않음)
- 결과 반영: 필요 시 `src/bullet_in/adapters/x_playwright.py` 의 `_AFC_TAG_RE` 보강 + Task 1 테스트 갱신

**Interfaces:**
- Consumes: Task 1~3 의 전체 조립 (`_x_cookies` · `_scroll_collect` · `_TWEET_JS` · `parse_self_tweets`).
- Produces: spec §5.4 의 라이브 확정 두 가지 — `#AFC` 중의성 (타 AFC 클럽 태깅 방식) · 태깅 일관성 (누락률).
  판정 결과는 PR 본문 §4 검증에 표본 수치로 기록한다.

- [ ] **Step 1: 사전 조건 확인**

로컬에 `x_cookies.json` 이 있는지 확인한다 (없으면 사용자에게 위치 질문 — X 접촉 전에 멈춤).

- [ ] **Step 2: 단독 라이브 fetch 1회 (tee 필수)**

스크래치패드에 아래 스크립트를 쓰고 1회만 실행한다.
출력이 잘려도 재실행하지 않는다 — tee 파일로 확인하고, 수치는 근사치로 기록해도 된다.

```python
# scratchpad/ornstein_live_sample.py — 원시 타임라인 vs #AFC 통과분 대조 (spec §5.4)
import asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from bullet_in.adapters.x_playwright import (_x_cookies, _scroll_collect,
                                             _TWEET_JS, parse_self_tweets)

async def main():
    cookies = _x_cookies("x_cookies.json")
    now = datetime.now(timezone.utc)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.goto("https://x.com/David_Ornstein", wait_until="domcontentloaded")
        await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
        raw = await _scroll_collect(page, _TWEET_JS, 30)
        await browser.close()
    print(f"원시 트윗 {len(raw)}건")
    for t in raw:
        print("-", (t.get("text") or "").replace("\n", " ")[:110])
    items = parse_self_tweets("x_ornstein", "David_Ornstein", raw, now)
    print(f"#AFC 통과 {len(items)}건")
    for it in items:
        print("+", it.url, "|", it.raw_payload["text"][:90].replace("\n", " "))

asyncio.run(main())
```

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in && \
uv run python <scratchpad>/ornstein_live_sample.py 2>&1 | tee <scratchpad>/ornstein-live-sample.log
```

- [ ] **Step 3: 표본 판정 (spec §5.4 두 항목)**

- 오탐: `+` 목록에 타 클럽 · 대표팀 트윗이 섞였는가 (섞였으면 태그 정규식 재검토).
- 누락: `-` 목록의 아스날 관련 트윗 중 `#AFC` 없이 떨어진 것이 있는가.
- 누락이 크면 (표본 기준 아스날 트윗의 다수가 무태그) `_AFC_TAG_RE` 를 Arsenal 키워드 OR 로 보강한다:

```python
_AFC_TAG_RE = re.compile(r"#AFC\b|\bArsenal\b", re.IGNORECASE)
```

- 보강 시 Task 1 의 드롭 테스트에 Arsenal 무언급 표본을 유지한 채, 키워드 매치 테스트를 추가하고 별도 커밋한다.
- 리트윗 가드 실측 (A안): 원시 표본에 리트윗이 있으면 author 대조로 걸러졌는지 확인한다.
- 스레드 혼재 (spec §13) 표본도 함께 기록 — 판별 이상이 보이면 사용자와 논의 후 처리.

- [ ] **Step 4: 판정 기록**

표본 수치 (원시 N건 · 통과 M건 · 오탐 0 여부 · 누락 사례) 를 PR 본문 §4 에 기록할 형태로 정리한다.

---

### Task 5: 전체 검증 · PR 생성

**Files:**
- Create: PR 본문 (스크래치패드 · `--body-file`)

- [ ] **Step 1: 전체 테스트 · 최종 리뷰**

Run: `uv run pytest -q`
Expected: 전체 PASS.
superpowers:requesting-code-review 로 최종 리뷰 (리뷰 모델은 co-author 제외).

- [ ] **Step 2: PR 본문 작성 (7섹션 · 템플릿 주석 세칙 대조)**

- §2 의사결정: #AFC 필터 채택 근거 (본문 키워드 대비 정밀 · LLM 판별 비채택) · backtrack 미전달 (본인 트윗 = 원문) · 고정 tier 근거.
- §4 검증: 단위 테스트 결과 + Task 4 라이브 표본 수치.
- §5 롤백: `x_ornstein.enabled: false` 한 줄 (spec §11).
- 관찰 항목: cluster 대표 역전 (spec §13) 은 라이브 후 확인으로 명시.

- [ ] **Step 3: humanize-korean fast 문체 점검 1회 → PR 생성**

```bash
gh pr create --title "feat(collect): 온스테인 X 직접 수집 — self_source 파싱 분기 · #AFC 필터" \
  --body-file <scratchpad>/pr-body-ornstein-x.md
```

머지는 사용자 직접 (gh pr merge 금지).
머지 후 VM 반영 · 다음 회차에서 x_ornstein 수집 · cluster 대표 확인은 후속 세션 몫으로 PR 본문에 기록한다.
