# SP1 — Playwright afcstuff 리더 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 깨진 twikit을 Playwright 기반 X 어댑터로 대체하고, `[ @handle ]` 인용 afcstuff 트윗을 2순위 항목으로 파이프라인에 흘린다.

**Architecture:** 신규 `x_playwright` 어댑터가 쿠키주입 Playwright로 afcstuff 타임라인을 읽어 인용 트윗만 `RawItem`으로 방출한다. tier는 `resolve_tier`의 `x_mentions` 모드가 인용 기자 레지스트리에서 도출하되, 미등록 인용은 config `fallback_tier`로 생존시킨다. 순수 파서 (테스트 가능)와 브라우저 I/O (라이브 검증)를 분리한다.

**Tech Stack:** Python 3.11 · uv · Playwright (async, chromium) · pydantic · pytest.

**Spec:** `docs/superpowers/specs/2026-07-01-sp1-afcstuff-playwright-reader-design.md`

## Global Constraints

- **브랜치**: `feat/sp1-afcstuff-playwright`에서 작업, 태스크별 커밋, 종료 시 squash PR (GitHub Flow).
- **커밋 컨벤션**: `<type>(<scope>): 한국어 제목` + 본문 (왜). scope는 `adapters`/`credibility`/`sources` 등. 트레일러 필수:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **git 신원**: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- **karpathy 수술적 변경**: 바뀐 모든 줄이 이 목표에 직접 추적돼야 함. 인접 코드 · 주석을 "개선"하지 말 것.
- **문서 서식 §2.2**: 이 플랜을 포함한 모든 생성 문서에 적용 (→ · — 줄 시작 · 기호 간격). docs/ 저장 시 훅이 검사.
- **RawItem 계약** (`src/bullet_in/models.py`): `RawItem(source_id, source_type, url, fetched_at, raw_payload)`. afcstuff는 `source_type="x"`.
- **매핑은 기존 `to_articles`가 처리**: `title←raw_payload["text"]` · `published_at←_published(created_at)` · `journalist←raw_payload["journalist"]` · `image_url`. 어댑터는 raw_payload 키만 채운다.
- 테스트: `uv run pytest -q` 전건 통과 유지.
- **라이브 검증 (머지 전 필수)**: 유효 `x_cookies.json`으로 어댑터 `fetch()` 단독 실행 — 셀렉터 드리프트 상습 함정.

---

### Task 1: `resolve_tier` x_mentions에 `fallback_tier` 추가

**Files:**
- Modify: `src/bullet_in/credibility.py:35-41` (`resolve_tier`의 `x_mentions` 분기)
- Test: `tests/test_credibility.py` (파일 끝에 추가)

**Interfaces:**
- Produces: `x_mentions` 모드에서 등록 기자 미매칭 시 `src.get("fallback_tier")`가 있으면 그 값 (float), 없으면 `None` (기존 동작).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_credibility.py` 끝에 추가)

```python
def test_resolve_x_mentions_fallback_tier_when_unregistered():
    from bullet_in.models import RawItem
    from datetime import datetime, timezone
    r = load_registry("config/credibility.yaml")
    it = RawItem(source_id="x_afcstuff", source_type="x", url="u",
                 fetched_at=datetime.now(timezone.utc),
                 raw_payload={"text": "[@NobodyKnows] 루머"})
    # fallback_tier 있으면 그 값으로 생존
    src_fb = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}
    assert resolve_tier(it, src_fb, r) == 4.0
    # fallback_tier 없으면 종전대로 None (drop)
    src_no = {"x_afcstuff": {"credibility": "x_mentions"}}
    assert resolve_tier(it, src_no, r) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_credibility.py::test_resolve_x_mentions_fallback_tier_when_unregistered -q`
Expected: FAIL — `assert None == 4.0`

- [ ] **Step 3: 구현** — `credibility.py`의 `x_mentions` 분기 (현재 35-41행)를 아래로 교체

```python
    if mode == "x_mentions":
        if registry is None:
            return None
        text = item.raw_payload.get("text", "")
        handles = {("@" + h).lower() for h in _HANDLE_RE.findall(text)}
        tiers = [registry.journalists[k] for k in handles if k in registry.journalists]
        if tiers:
            return min(tiers)
        fb = src.get("fallback_tier")
        return float(fb) if fb is not None else None
```

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `uv run pytest tests/test_credibility.py -q`
Expected: PASS (신규 + 기존 `test_resolve_x_mentions_drops_when_no_journalist` 등 전건)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(credibility): x_mentions에 fallback_tier 추가

미등록 기자 인용도 drop 대신 config fallback_tier(예: 4)로 생존시켜
2순위 루머를 담는다. 플래그 없으면 종전대로 None(drop) — 회귀 없음.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `config/credibility.yaml` 레지스트리 정합화

**Files:**
- Modify: `config/credibility.yaml` (`journalists` 목록)
- Test: `tests/test_credibility.py` (파일 끝에 추가)

**Interfaces:**
- Produces: afcstuff가 인용하는 핸들이 레지스트리에서 조회됨 — 특히 `@samimokbel_bbc → 1.0`.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_credibility.py` 끝에 추가)

```python
def test_registry_has_afcstuff_cited_handles():
    r = load_registry("config/credibility.yaml")
    assert r.journalists["@samimokbel_bbc"] == 1.0      # BBC 현행 핸들
    assert "@gunnerblog" in r.journalists
    assert "@matt_law_dt" in r.journalists
    assert "@lattefirm" in r.journalists                 # 팟캐스트 (2순위)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_credibility.py::test_registry_has_afcstuff_cited_handles -q`
Expected: FAIL — `KeyError: '@samimokbel_bbc'`

- [ ] **Step 3: 구현** — `config/credibility.yaml`의 `journalists` 목록 수정

`Sami Mokbel` 항목의 `aliases`에 `@SamiMokbel_BBC`를 추가 (기존 유지):

```yaml
  - {name: Sami Mokbel,       tier: 1,   aliases: ["@SamiMokbel1_DM", "@SamiMokbel_BBC", "목벨", "Mokbel"]}
```

그리고 `journalists` 목록에 신규 3건 추가 (기존 항목들 아래, 중복 별칭 없음):

```yaml
  - {name: gunnerblog,        tier: 2,   aliases: ["@gunnerblog"]}
  - {name: Matt Law,          tier: 2,   aliases: ["@Matt_Law_DT"]}
  - {name: LatteFirm,         tier: 3,   aliases: ["@LatteFirm"]}
```

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `uv run pytest tests/test_credibility.py -q`
Expected: PASS (신규 + 기존. `_build`의 중복 별칭 검사도 통과 = 새 별칭 충돌 없음)

- [ ] **Step 5: 커밋**

```bash
git add config/credibility.yaml tests/test_credibility.py
git commit -m "$(cat <<'EOF'
feat(sources): credibility 레지스트리에 afcstuff 인용 핸들 정합화

Sami Mokbel 현행 @SamiMokbel_BBC 별칭 추가(구 @SamiMokbel1_DM만 있어
실제 항목이 fallback 4로 오분류되던 것 교정) + gunnerblog · Matt Law ·
LatteFirm(팟캐스트) 신규 등록. tier 정확도용.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 순수 파서 `parse_afcstuff_tweets`

**Files:**
- Create: `src/bullet_in/adapters/x_playwright.py` (이 태스크는 순수 함수만)
- Test: `tests/test_x_playwright.py`

**Interfaces:**
- Produces: `parse_afcstuff_tweets(source_id: str, handle: str, raw_tweets: list[dict], now: datetime) -> list[RawItem]`.
  입력 dict 키: `text` · `created_at` · `status_id` · `image_url`. `[ @handle ]` 인용 ≥1개인 트윗만 통과.
  `raw_payload = {text, created_at, journalist=마지막 핸들, handles=[전체], image_url}`, `url=https://x.com/<handle>/status/<status_id>`.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_x_playwright.py`)

```python
from datetime import datetime, timezone
from bullet_in.adapters.x_playwright import parse_afcstuff_tweets

NOW = datetime(2026, 7, 1, 3, 30, tzinfo=timezone.utc)

def _rt(**kw):
    base = {"text": "", "created_at": "2026-07-01T03:18:00.000Z",
            "status_id": "111", "image_url": None}
    base.update(kw); return base

def test_keeps_only_cited_tweets():
    rts = [
        _rt(text="Arsenal eye Barcola. [ @SamiMokbel_BBC ]", status_id="1"),
        _rt(text="GOAL!! France 3-0", status_id="2"),   # 무인용 → drop
    ]
    items = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://x.com/afcstuff/status/1"
    assert it.source_type == "x"
    assert it.raw_payload["journalist"] == "@SamiMokbel_BBC"
    assert it.raw_payload["handles"] == ["@SamiMokbel_BBC"]
    assert it.raw_payload["text"].startswith("Arsenal eye")

def test_multi_handle_primary_is_last():
    rts = [_rt(text="News [ @David_Ornstein ] via [ @SamiMokbel_BBC ]", status_id="9")]
    items = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)
    assert items[0].raw_payload["handles"] == ["@David_Ornstein", "@SamiMokbel_BBC"]
    assert items[0].raw_payload["journalist"] == "@SamiMokbel_BBC"

def test_passes_image_and_created_at():
    rts = [_rt(text="x [ @gunnerblog ]", image_url="https://img/x.jpg",
               created_at="2026-07-01T02:00:00.000Z")]
    it = parse_afcstuff_tweets("x_afcstuff", "afcstuff", rts, NOW)[0]
    assert it.raw_payload["image_url"] == "https://img/x.jpg"
    assert it.raw_payload["created_at"] == "2026-07-01T02:00:00.000Z"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: FAIL — `ModuleNotFoundError` / `parse_afcstuff_tweets` 없음

- [ ] **Step 3: 구현** — `src/bullet_in/adapters/x_playwright.py` 생성 (순수 함수 부분)

```python
from __future__ import annotations
import re
from datetime import datetime
from bullet_in.models import RawItem

_CITE_RE = re.compile(r"\[\s*@([A-Za-z0-9_]{1,15})\s*\]")


def parse_afcstuff_tweets(source_id: str, handle: str,
                          raw_tweets: list[dict], now: datetime) -> list[RawItem]:
    """DOM에서 뽑은 트윗 dict → 인용(`[ @handle ]`) 있는 것만 RawItem."""
    out: list[RawItem] = []
    for t in raw_tweets:
        text = t.get("text") or ""
        cited = ["@" + h for h in _CITE_RE.findall(text)]
        if not cited:
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": cited[-1], "handles": cited,
                         "image_url": t.get("image_url")}))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: PASS (3건)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/x_playwright.py tests/test_x_playwright.py
git commit -m "$(cat <<'EOF'
feat(adapters): afcstuff 인용 트윗 순수 파서

[ @handle ] 인용 있는 트윗만 통과시켜 RawItem 생성. 주 핸들=마지막 인용,
전체 핸들·text·created_at·image_url을 raw_payload에 담음(SP2 전방 호환).
브라우저 I/O와 분리해 단위 테스트 가능.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `XPlaywrightAdapter.fetch()` + 쿠키 헬퍼 + 배선

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py` (어댑터 클래스 · 쿠키 헬퍼 추가)
- Modify: `src/bullet_in/adapters/factory.py` (`x_playwright` 분기 추가)
- Modify: `config/sources.yaml` (`x_afcstuff` 갱신)

**Interfaces:**
- Consumes: Task 3의 `parse_afcstuff_tweets`.
- Produces: `XPlaywrightAdapter(source_id, handle, max_tweets=20, cookies_path="x_cookies.json")` — `fetch() -> list[RawItem]` (`SourceAdapter` 계약).

- [ ] **Step 1: 어댑터 · 쿠키 헬퍼 구현** — `x_playwright.py`에 아래 추가

```python
import json
import os
from playwright.async_api import async_playwright

_TWEET_JS = """
els => els.map(a => {
  const t = a.querySelector('[data-testid="tweetText"]');
  const time = a.querySelector('time');
  const link = a.querySelector('a[href*="/status/"]');
  const img = a.querySelector('[data-testid="tweetPhoto"] img');
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    image_url: img ? img.src : null
  };
})
"""


def _x_cookies(cookies_path: str) -> list[dict]:
    """x_cookies.json({auth_token, ct0}) → Playwright 쿠키 목록(.x.com · .twitter.com). SP2 재사용."""
    if not os.path.exists(cookies_path):
        raise FileNotFoundError(f"X 쿠키 파일 없음: {cookies_path}")
    raw = json.load(open(cookies_path, encoding="utf-8"))
    out = []
    for dom in (".x.com", ".twitter.com"):
        for name in ("auth_token", "ct0"):
            if raw.get(name):
                out.append({"name": name, "value": raw[name],
                            "domain": dom, "path": "/"})
    return out


class XPlaywrightAdapter:
    source_type = "x"

    def __init__(self, source_id: str, handle: str, max_tweets: int = 20,
                 cookies_path: str = "x_cookies.json"):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path

    async def fetch(self) -> list[RawItem]:
        from datetime import datetime, timezone
        cookies = _x_cookies(self.cookies_path)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            await page.goto(f"https://x.com/{self.handle}",
                            wait_until="domcontentloaded")
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            seen = 0
            for _ in range(6):  # max_tweets 채울 때까지 소폭 스크롤
                raw_tweets = await page.eval_on_selector_all(
                    'article[data-testid="tweet"]', _TWEET_JS)
                if len(raw_tweets) >= self.max_tweets or len(raw_tweets) == seen:
                    break
                seen = len(raw_tweets)
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(800)
            await browser.close()
        raw_tweets = raw_tweets[: self.max_tweets]
        return parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets,
                                     datetime.now(timezone.utc))
```

- [ ] **Step 2: factory 배선** — `factory.py`에 import 추가 · 분기 추가

import 라인 (기존 x_twikit import 아래 등):

```python
from bullet_in.adapters.x_playwright import XPlaywrightAdapter
```

`build_adapters`의 분기에 추가 (기존 `x_twikit` 분기는 Task 5에서 제거):

```python
        elif kind == "x_playwright":
            out.append(XPlaywrightAdapter(sid, c["handle"],
                                          c.get("max_tweets", 20),
                                          c.get("cookies_path", "x_cookies.json")))
```

- [ ] **Step 3: sources.yaml 갱신** — `x_afcstuff` 블록을 아래로 교체

```yaml
  - source_id: x_afcstuff
    display_name: afcstuff (aggregator)
    medium: x
    adapter: x_playwright
    credibility: x_mentions
    fallback_tier: 4
    config: { handle: "afcstuff", max_tweets: 30, cookies_path: "x_cookies.json" }
    enabled: true
```

- [ ] **Step 4: 배선 회귀 확인** (import · 팩토리 파싱 깨지지 않는지)

Run: `uv run pytest -q`
Expected: PASS (전건. 어댑터 fetch는 브라우저라 단위 테스트 없음 — 파싱 경로는 Task 3이 커버)

- [ ] **Step 5: 라이브 검증** (유효 `x_cookies.json` 필요, CLAUDE.md 함정)

```bash
uv run python - <<'PY'
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "x_afcstuff"][0]
items = asyncio.run(adp.fetch())
print("수집:", len(items))
for it in items[:8]:
    print(" ", it.raw_payload["journalist"], "|", it.raw_payload["text"][:70])
PY
```

- [ ] 인용 트윗이 수집되고 각 항목에 `journalist` (@핸들)가 붙는지 · 월드컵 반응 등 무인용은 빠졌는지 육안 확인.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/adapters/x_playwright.py src/bullet_in/adapters/factory.py config/sources.yaml
git commit -m "$(cat <<'EOF'
feat(adapters): Playwright afcstuff 리더 어댑터 · 배선

쿠키주입 headless 브라우저로 afcstuff 타임라인을 읽어 인용 트윗 수집.
쿠키 헬퍼(_x_cookies)는 SP2 기자 검색이 재사용. factory에 x_playwright
배선 + sources.yaml x_afcstuff 활성(fallback_tier 4).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 죽은 `x_twikit` 제거

**Files:**
- Delete: `src/bullet_in/adapters/x_twikit.py`, `tests/test_x_adapter.py`
- Modify: `src/bullet_in/adapters/factory.py` (x_twikit import · 분기 제거)

**Interfaces:**
- Consumes: 없음. Produces: 없음 (고아 제거).

- [ ] **Step 1: 제거** — 파일 삭제 · factory에서 x_twikit 흔적 제거

```bash
git rm src/bullet_in/adapters/x_twikit.py tests/test_x_adapter.py
```

`factory.py`에서 아래 두 줄 제거:

```python
from bullet_in.adapters.x_twikit import XAdapter
```
```python
        elif kind == "x_twikit":
            out.append(XAdapter(sid, c["handle"], c.get("max_tweets", 20)))
```

- [ ] **Step 2: 전건 회귀 확인**

Run: `uv run pytest -q`
Expected: PASS (전건. x_twikit 참조 · 테스트가 사라져도 다른 소스 무영향)

- [ ] **Step 3: 커밋**

```bash
git add -A src/bullet_in/adapters/factory.py
git commit -m "$(cat <<'EOF'
refactor(adapters): 깨진 x_twikit 제거

Playwright 어댑터로 대체돼 factory 참조가 사라진 고아. 어댑터 · 테스트
삭제 + factory 분기 제거.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## 완료 후

전건 `uv run pytest -q` 통과 + Task 4 라이브 검증 (인용 트윗 수집 · 무인용 배제) 확인 후, `feat/sp1-afcstuff-playwright`를 squash PR (7섹션 한국어 본문 · `--body-file` · Claude 서명 금지)로 올린다.
SP1 라이브 후 비-월드컵 구간에서 1순위/2순위 라우팅 비율을 관찰해 SP2 착수 판단에 쓴다.
