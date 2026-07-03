# SP2-a afcstuff 기자 역추적 · 무료 아웃렛 1순위 승격 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** afcstuff 2순위 인용 트윗을 기자 타임라인 역추적으로 무료 아웃렛 원 기사에 연결해 제자리에서 1순위로 승격.

**Architecture:** 순수 로직 (엔티티 추출 · 매칭 · 라우팅 · 승격 조립)은 신규 `x_backtrack.py`에 모아 단위 테스트, 브라우저 스크레이프 · 오케스트레이션은 기존 `x_playwright.py` 확장, tier는 fmkorea 규칙 재사용으로 `credibility.py` 확장. backtrack은 `backtrack_config` 설정 유무로 켜지는 feature flag.

**Tech Stack:** Python 3.11 · Playwright · httpx · BeautifulSoup · pydantic v2 · PyYAML.

## Global Constraints

- **신규 의존성 금지** — 기존 `httpx` · `bs4` · `yaml` · Playwright만 사용, `extract_article_body`는 기존 것 재사용.
- **Python 3.11** — dict 삽입 순서 · `str | None` 타입 표기 사용.
- **문서 서식 §2.2** — 생성 문서는 명사형 불릿 · 기호 간격 · `→`/`—` 줄 시작, 저장 시 `check-doc-format.py` 통과.
- **커밋 컨벤션** — `<type>(<scope>): 한국어 제목` + 트레일러 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **git 신원** — `benidjor <94089198+benidjor@users.noreply.github.com>`.
- **수술적 변경** — 무관 코드 리팩터 금지, `_scroll_collect` 추출은 afcstuff 기존 동작 보존 (SP1.5와 동일).

---

### Task 1: 엔티티 추출 (`x_backtrack.extract_entities`)

**Files:**
- Create: `src/bullet_in/adapters/x_backtrack.py`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Produces: `extract_entities(text: str) -> list[str]` — 대문자 시작 연속 단어 (2어 이상) 목록, 악센트 보존.

- [ ] **1단계 — 실패 테스트 작성**

```python
# tests/test_x_backtrack.py
from bullet_in.adapters.x_backtrack import extract_entities

def test_extract_entities_multiword():
    assert "Jeremy Monga" in extract_entities("Man City working to sign Jeremy Monga")

def test_extract_entities_keeps_accent():
    ents = extract_entities("Arsenal hope to sign Bruno Guimarães this summer")
    assert "Bruno Guimarães" in ents

def test_extract_entities_skips_single_word():
    assert extract_entities("Arsenal are active") == []
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: FAIL — `ModuleNotFoundError: bullet_in.adapters.x_backtrack`

- [ ] **3단계 — 최소 구현**

```python
# src/bullet_in/adapters/x_backtrack.py
from __future__ import annotations
import re

_NAME_RE = re.compile(r"[A-Z][A-Za-zÀ-ÿ'’.\-]*(?:\s+[A-Z][A-Za-zÀ-ÿ'’.\-]*)+")

def extract_entities(text: str) -> list[str]:
    """대문자로 시작하는 연속 단어 (2어 이상) = 인명 · 구단명 후보. 악센트 보존."""
    return _NAME_RE.findall(text or "")
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: PASS (3 passed)

- [ ] **5단계 — 커밋**

```bash
git add src/bullet_in/adapters/x_backtrack.py tests/test_x_backtrack.py
git commit -m "feat(adapters): SP2 엔티티 추출 (악센트 보존 정규식)

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 매처 (`x_backtrack.match_original_tweet`)

**Files:**
- Modify: `src/bullet_in/adapters/x_backtrack.py`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Consumes: (Task 1과 같은 모듈)
- Produces:
  - `match_original_tweet(af_text: str, af_dt: datetime | None, journ_tweets: list[dict], window_min: int, overlap_min: int) -> dict | None` — 4단계 ①~③ 적용, 매칭 트윗 dict 또는 `None`.
  - 내부: `_sig_tokens(text) -> set[str]` · `_parse_dt(s) -> datetime | None`.
  - 입력 트윗 dict은 `text` · `created_at` (ISO) 키 사용.

- [ ] **1단계 — 실패 테스트 작성**

```python
# tests/test_x_backtrack.py (추가)
from datetime import datetime, timezone, timedelta
from bullet_in.adapters.x_backtrack import match_original_tweet

_AF = datetime(2026, 7, 2, 21, 0, tzinfo=timezone.utc)

def _jt(text, minutes_before):
    return {"text": text, "created_at": (_AF - timedelta(minutes=minutes_before)).isoformat()}

def test_matcher_picks_highest_overlap_in_window():
    tweets = [
        _jt("Man City working to complete signing of Leicester winger Jeremy Monga proposed fee", 13),
        _jt("Man City pushing hard to sign Jeremy Monga from Leicester", 108),
    ]
    af = "Manchester City are working to complete a deal for Jeremy Monga fee region Leicester winger"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is tweets[0]

def test_matcher_none_below_threshold():
    tweets = [_jt("Newcastle eye Felix Nmecha midfielder shortlist", 20)]
    af = "Arsenal monitoring William Saliba fitness back problem"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None

def test_matcher_excludes_later_tweets():
    tweets = [_jt("Arsenal agree Bruno Guimaraes deal Newcastle package worth", -30)]
    af = "Arsenal agree Bruno Guimaraes deal Newcastle package worth"
    assert match_original_tweet(af, _AF, tweets, 180, 4) is None
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -k matcher -q`
Expected: FAIL — `ImportError: cannot import name 'match_original_tweet'`

- [ ] **3단계 — 최소 구현**

```python
# src/bullet_in/adapters/x_backtrack.py (추가)
from datetime import datetime

_STOP = frozenset(
    "the a an and or to of in on for with set are is has have been will would "
    "from that this over amid could into out at as by".split())

def _sig_tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]+", text or "")
    return {w for w in words if len(w) > 3 and w.lower() not in _STOP}

def _parse_dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def match_original_tweet(af_text, af_dt, journ_tweets, window_min, overlap_min):
    """4단계 ①~③ : 기자 트윗 중 afcstuff 원본을 특정. 없으면 None."""
    af_sig = _sig_tokens(af_text)
    best, best_score, best_dt = None, -1, None
    for jt in journ_tweets:
        jdt = _parse_dt(jt.get("created_at"))
        if jdt is None or af_dt is None or jdt > af_dt:
            continue
        if (af_dt - jdt).total_seconds() > window_min * 60:
            continue
        score = len(af_sig & _sig_tokens(jt.get("text", "")))
        if score > best_score or (score == best_score and best_dt is not None and jdt > best_dt):
            best, best_score, best_dt = jt, score, jdt
    return best if best_score >= overlap_min else None
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: PASS (6 passed)

- [ ] **5단계 — 커밋**

```bash
git add src/bullet_in/adapters/x_backtrack.py tests/test_x_backtrack.py
git commit -m "feat(adapters): SP2 매처 (엔티티 겹침 · 시간창 · 기자 선행)

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: backtrack 설정 · 도메인 라우팅

**Files:**
- Create: `config/backtrack.yaml`
- Modify: `src/bullet_in/adapters/x_backtrack.py`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Produces:
  - `load_backtrack_config(path: str) -> dict`
  - `outlet_for_domain(url: str, domains: dict[str, str]) -> str | None`
  - `is_paywalled(url: str) -> bool`

- [ ] **1단계 — 설정 파일 작성**

```yaml
# config/backtrack.yaml
params:
  window_min: 180        # afcstuff가 기자 원본을 인용하기까지 시간창 (분)
  overlap_min: 4         # 매칭 최소 토큰 겹침
  timeline_depth: 25     # 기자당 스크레이프 트윗 수
  max_journalists: 15    # 실행당 기자 스크레이프 상한
skip_handles:            # 기사 없는 트윗-only 핸들 (역추적 제외)
  - LatteFirm
domains:                 # 무료 아웃렛 도메인 → 아웃렛명 (credibility.yaml outlet과 일치)
  bbc.co.uk: BBC
  standard.co.uk: Evening Standard
  thesun.co.uk: The Sun
  dailymail.co.uk: Daily Mail
  telegraph.co.uk: The Telegraph
  thetimes.co.uk: The Times
  theguardian.com: The Guardian
  skysports.com: Sky Sports
  football.london: football.london
  90min.com: 90min
  hitc.com: HITC
  espn.com: ESPN
  espn.co.uk: ESPN
  goal.com: Goal.com
  arseblog.com: arseblog
```

- [ ] **2단계 — 실패 테스트 작성**

```python
# tests/test_x_backtrack.py (추가)
from bullet_in.adapters.x_backtrack import outlet_for_domain, is_paywalled, load_backtrack_config

_DOMAINS = {"bbc.co.uk": "BBC", "thesun.co.uk": "The Sun"}

def test_outlet_for_domain_exact_and_subdomain():
    assert outlet_for_domain("https://www.bbc.co.uk/sport/x", _DOMAINS) == "BBC"
    assert outlet_for_domain("https://thesun.co.uk/a", _DOMAINS) == "The Sun"

def test_outlet_for_domain_unknown():
    assert outlet_for_domain("https://example.com/a", _DOMAINS) is None

def test_is_paywalled_athletic():
    assert is_paywalled("https://www.nytimes.com/athletic/123/") is True
    assert is_paywalled("https://theathletic.com/123/") is True
    assert is_paywalled("https://www.bbc.co.uk/x") is False

def test_load_backtrack_config():
    cfg = load_backtrack_config("config/backtrack.yaml")
    assert cfg["domains"]["bbc.co.uk"] == "BBC"
    assert cfg["params"]["overlap_min"] == 4
```

- [ ] **3단계 — 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -k "domain or paywall or config" -q`
Expected: FAIL — `ImportError: cannot import name 'outlet_for_domain'`

- [ ] **4단계 — 최소 구현**

```python
# src/bullet_in/adapters/x_backtrack.py (추가)
from urllib.parse import urlparse
import yaml

def load_backtrack_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h

def outlet_for_domain(url: str, domains: dict[str, str]) -> str | None:
    host = _host(url)
    for dom, name in domains.items():
        if host == dom or host.endswith("." + dom):
            return name
    return None

def is_paywalled(url: str) -> bool:
    return "theathletic.com" in url or "nytimes.com/athletic" in url
```

- [ ] **5단계 — 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: PASS (10 passed)

- [ ] **6단계 — 커밋**

```bash
git add config/backtrack.yaml src/bullet_in/adapters/x_backtrack.py tests/test_x_backtrack.py
git commit -m "feat(config): SP2 backtrack 설정 · 도메인 아웃렛 라우팅

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: og:title 추출 · t.co 해석 · 본문 fetch

**Files:**
- Modify: `src/bullet_in/adapters/meta.py`
- Modify: `src/bullet_in/adapters/x_backtrack.py`
- Test: `tests/test_meta.py` · `tests/test_x_backtrack.py`

**Interfaces:**
- Produces:
  - `meta.extract_og_title(html: str) -> str | None`
  - `x_backtrack.resolve_and_fetch(client: httpx.AsyncClient, url: str) -> tuple[str | None, str, str | None, str | None]` — `(final_url, body, title, image)`, 실패 시 `(None, "", None, None)`.

- [ ] **1단계 — 실패 테스트 작성**

```python
# tests/test_meta.py (없으면 생성, 있으면 추가)
from bullet_in.adapters.meta import extract_og_title

def test_extract_og_title_prefers_og():
    html = '<meta property="og:title" content="Arsenal sign X"><title>ignored</title>'
    assert extract_og_title(html) == "Arsenal sign X"

def test_extract_og_title_fallback_title_tag():
    assert extract_og_title("<title>Fallback</title>") == "Fallback"

def test_extract_og_title_none():
    assert extract_og_title("<p>no title</p>") is None
```

```python
# tests/test_x_backtrack.py (추가)
import asyncio, httpx
from bullet_in.adapters.x_backtrack import resolve_and_fetch

def test_resolve_and_fetch_follows_redirect():
    def handler(request):
        if request.url.host == "t.co":
            return httpx.Response(301, headers={"location": "https://www.bbc.co.uk/sport/article"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              html='<meta property="og:title" content="Head"><article><p>Body text here.</p></article>')
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as c:
            return await resolve_and_fetch(c, "https://t.co/abc")
    url, body, title, _img = asyncio.run(run())
    assert url == "https://www.bbc.co.uk/sport/article"
    assert "Body text" in body
    assert title == "Head"
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_meta.py tests/test_x_backtrack.py -k "og_title or resolve" -q`
Expected: FAIL — `ImportError` (`extract_og_title` · `resolve_and_fetch` 미정의)

- [ ] **3단계 — 최소 구현**

```python
# src/bullet_in/adapters/meta.py (추가)
def extract_og_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("meta", attrs={"property": "og:title"})
    if tag and tag.get("content"):
        return tag["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None
```

```python
# src/bullet_in/adapters/x_backtrack.py (추가)
import httpx
from bullet_in.adapters.meta import extract_article_body, extract_og_title, extract_og_image

async def resolve_and_fetch(client, url):
    """t.co (또는 실 URL) → 최종 URL · 본문 · 제목 · 이미지. 실패 시 (None, '', None, None)."""
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None, "", None, None
    return str(r.url), extract_article_body(r.text), extract_og_title(r.text), extract_og_image(r.text)
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_meta.py tests/test_x_backtrack.py -q`
Expected: PASS (전체 그린)

- [ ] **5단계 — 커밋**

```bash
git add src/bullet_in/adapters/meta.py src/bullet_in/adapters/x_backtrack.py tests/test_meta.py tests/test_x_backtrack.py
git commit -m "feat(adapters): SP2 og:title 추출 · t.co 해석 후 본문 fetch

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: credibility 아웃렛 폴백 (fmkorea 규칙 재사용)

**Files:**
- Modify: `src/bullet_in/credibility.py:35-44`
- Test: `tests/test_credibility.py`

**Interfaces:**
- Modify: `resolve_tier` 의 `x_mentions` 분기 — 등록 기자 없고 `raw_payload["outlet"]`이 등록 아웃렛이면 아웃렛 tier 반환, 아니면 기존 `fallback_tier`.

- [ ] **1단계 — 실패 테스트 작성**

```python
# tests/test_credibility.py (없으면 생성, 있으면 추가)
from bullet_in.credibility import resolve_tier, Registry

def _reg():
    return Registry(journalists={"@samimokbel_bbc": 1.0}, outlets={"bbc": 1.0, "the sun": 4.0})

_SOURCES = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}

class _Item:
    def __init__(self, payload):
        self.source_id = "x_afcstuff"
        self.raw_payload = payload

def test_tier_journalist_first():
    it = _Item({"text": "[ @SamiMokbel_BBC ] news", "outlet": "BBC"})
    assert resolve_tier(it, _SOURCES, _reg()) == 1.0

def test_tier_outlet_fallback_for_unregistered_journalist():
    # 미등록 기자 + known 아웃렛(BBC=1) → 아웃렛 tier(1), fallback(4) 아님
    it = _Item({"text": "[ @UnknownGuy ] news", "outlet": "BBC"})
    assert resolve_tier(it, _SOURCES, _reg()) == 1.0

def test_tier_fallback_when_neither():
    it = _Item({"text": "[ @UnknownGuy ] news"})
    assert resolve_tier(it, _SOURCES, _reg()) == 4.0
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_credibility.py -k outlet_fallback -q`
Expected: FAIL — 현재는 `4.0` 반환 (아웃렛 폴백 미구현)

- [ ] **3단계 — 최소 구현**

```python
# src/bullet_in/credibility.py — x_mentions 분기 (기존 41-44행 교체)
        if tiers:
            return min(tiers)
        outlet = (item.raw_payload.get("outlet") or "").lower()
        if outlet and outlet in registry.outlets:   # 승격 항목 : 아웃렛 폴백
            return registry.outlets[outlet]
        fb = src.get("fallback_tier")
        return float(fb) if fb is not None else None
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_credibility.py -q`
Expected: PASS

- [ ] **5단계 — 회귀 확인**

Run: `uv run pytest tests/test_x_playwright.py tests/test_credibility.py -q`
Expected: PASS (기존 x_mentions 동작 무회귀 — outlet 없으면 종전대로 fallback)

- [ ] **6단계 — 커밋**

```bash
git add src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "feat(credibility): x_mentions 아웃렛 폴백 (승격 항목 tier)

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 승격 조립 (`x_backtrack.promote_cited_item`)

**Files:**
- Modify: `src/bullet_in/adapters/x_backtrack.py`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Produces: `promote_cited_item(item: RawItem, article_url: str, outlet: str, title: str | None, body: str, image: str | None) -> RawItem` — fmkorea 무료 경로와 동형 `raw_payload` (`title` · `body` · `lang="en"` · `outlet` · `journalist` · `image_url` · `created_at`), `source_type="html"`, `url`=기사 URL.

- [ ] **1단계 — 실패 테스트 작성**

```python
# tests/test_x_backtrack.py (추가)
from datetime import datetime, timezone
from bullet_in.models import RawItem
from bullet_in.adapters.x_backtrack import promote_cited_item

def test_promote_builds_html_item():
    it = RawItem(source_id="x_afcstuff", source_type="x",
                 url="https://x.com/afcstuff/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Arsenal sign X [ @gunnerblog ]",
                              "journalist": "@gunnerblog",
                              "created_at": "2026-07-02T20:00:00Z"})
    p = promote_cited_item(it, "https://arseblog.com/a", "arseblog", "Arsenal sign X", "Body.", "https://img")
    assert p.url == "https://arseblog.com/a"
    assert p.source_type == "html"
    assert p.raw_payload["outlet"] == "arseblog"
    assert p.raw_payload["lang"] == "en"
    assert p.raw_payload["journalist"] == "@gunnerblog"
    assert p.raw_payload["title"] == "Arsenal sign X"
    assert p.raw_payload["body"] == "Body."

def test_promote_title_falls_back_to_tweet_text():
    it = RawItem(source_id="x_afcstuff", source_type="x", url="https://x.com/a/status/1",
                 fetched_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                 raw_payload={"text": "Tweet headline", "journalist": "@x"})
    p = promote_cited_item(it, "https://bbc.co.uk/a", "BBC", None, "B", None)
    assert p.raw_payload["title"] == "Tweet headline"
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -k promote -q`
Expected: FAIL — `ImportError: cannot import name 'promote_cited_item'`

- [ ] **3단계 — 최소 구현**

```python
# src/bullet_in/adapters/x_backtrack.py (추가)
from bullet_in.models import RawItem

def promote_cited_item(item, article_url, outlet, title, body, image):
    """인용 RawItem을 무료 기사로 제자리 승격. raw_payload를 fmkorea 무료 경로와 동형으로."""
    return RawItem(
        source_id=item.source_id, source_type="html", url=article_url,
        fetched_at=item.fetched_at,
        raw_payload={
            "title": title or item.raw_payload.get("text", ""),
            "body": body, "lang": "en", "outlet": outlet,
            "journalist": item.raw_payload.get("journalist"),
            "image_url": image,
            "created_at": item.raw_payload.get("created_at"),
        })
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: PASS

- [ ] **5단계 — 커밋**

```bash
git add src/bullet_in/adapters/x_backtrack.py tests/test_x_backtrack.py
git commit -m "feat(adapters): SP2 승격 조립 (fmkorea 무료 경로 동형 RawItem)

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: 기자 타임라인 스크레이퍼 · 오케스트레이션 · 배선

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py`
- Modify: `src/bullet_in/adapters/x_backtrack.py`
- Modify: `src/bullet_in/adapters/factory.py:29-32`
- Modify: `config/sources.yaml:62`
- Test: `tests/test_x_backtrack.py`

**Interfaces:**
- Consumes: `match_original_tweet` · `outlet_for_domain` · `is_paywalled` · `resolve_and_fetch` · `promote_cited_item` · `load_backtrack_config` (Task 2 – 6) · `_accumulate_tweets` (SP1.5) · `_x_cookies` (SP1).
- Produces:
  - `x_playwright._scroll_collect(page, js: str, max_items: int) -> list[dict]` — 스크롤 · `status_id` 누적 (afcstuff · 기자 공용).
  - `x_playwright._JOURN_JS` — 기자 트윗 + link-card 추출 JS.
  - `XPlaywrightAdapter._scrape_journalists(ctx, items, cfg) -> dict[str, list[dict]]` — 핸들 (소문자) → 타임라인.
  - `x_backtrack.backtrack_promote(items: list[RawItem], timelines: dict, cfg: dict) -> list[RawItem]` — 매칭 · 해석 · fetch · 승격 오케스트레이션.
  - `XPlaywrightAdapter.__init__` 에 `backtrack_config_path: str | None = None` 추가.

**참고 — TDD 예외:** Playwright 스크레이프 · 오케스트레이션 글루는 라이브로만 검증되므로 (모킹 시 mock 자체를 테스트) Task 8 라이브 실행 + 기존 스위트 그린으로 검증한다. 순수 로직은 Task 1 – 6에서 이미 단위 테스트했다. `backtrack_promote`의 폴백 분기만 아래에서 단위 테스트한다.

- [ ] **1단계 — `backtrack_promote` 폴백 실패 테스트 작성**

```python
# tests/test_x_backtrack.py (추가)
import asyncio
from datetime import datetime, timezone
from bullet_in.models import RawItem
from bullet_in.adapters.x_backtrack import backtrack_promote

def _cited(handle, text, created):
    return RawItem(source_id="x_afcstuff", source_type="x",
                   url="https://x.com/afcstuff/status/9", fetched_at=datetime(2026,7,3,tzinfo=timezone.utc),
                   raw_payload={"text": text, "journalist": handle, "created_at": created})

_CFG = {"params": {"window_min": 180, "overlap_min": 4}, "domains": {"bbc.co.uk": "BBC"}}

def test_backtrack_keeps_item_when_no_timeline():
    # 기자 타임라인 없음 → 2순위 그대로
    it = _cited("@gunnerblog", "Arsenal sign X", "2026-07-02T20:00:00Z")
    out = asyncio.run(backtrack_promote([it], {}, _CFG))
    assert out[0] is it

def test_backtrack_keeps_item_when_matched_tweet_has_no_card():
    # 정책 Y : 매칭돼도 카드 없으면 승격 안 함
    it = _cited("@gunnerblog", "Arsenal sign Bruno Guimaraes Newcastle package worth", "2026-07-02T20:00:00Z")
    timelines = {"gunnerblog": [{"text": "Arsenal sign Bruno Guimaraes Newcastle package worth",
                                 "created_at": "2026-07-02T19:30:00Z", "card_href": ""}]}
    out = asyncio.run(backtrack_promote([it], timelines, _CFG))
    assert out[0] is it
```

- [ ] **2단계 — 실패 확인**

Run: `uv run pytest tests/test_x_backtrack.py -k backtrack_keeps -q`
Expected: FAIL — `ImportError: cannot import name 'backtrack_promote'`

- [ ] **3단계 — `backtrack_promote` 구현**

```python
# src/bullet_in/adapters/x_backtrack.py (추가)
import logging
log = logging.getLogger(__name__)

async def backtrack_promote(items, timelines, cfg):
    """인용 항목별 매칭 · 해석 · fetch · 승격. 실패는 2순위 유지 + 로깅."""
    params = cfg.get("params", {})
    domains = cfg.get("domains", {})
    wmin, omin = params.get("window_min", 180), params.get("overlap_min", 4)
    out = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"}) as c:
        for it in items:
            handle = (it.raw_payload.get("journalist") or "").lstrip("@").lower()
            tl = timelines.get(handle)
            if not tl:
                out.append(it); continue
            af_dt = _parse_dt(it.raw_payload.get("created_at"))
            m = match_original_tweet(it.raw_payload.get("text", ""), af_dt, tl, wmin, omin)
            card = (m or {}).get("card_href")
            if not m or not card:
                if m:
                    log.info("backtrack near-miss (카드 없음) handle=%s", handle)
                out.append(it); continue
            final_url, body, title, image = await resolve_and_fetch(c, card)
            if final_url is None or not body:
                out.append(it); continue
            if is_paywalled(final_url):
                log.info("backtrack 페이월 (Athletic) url=%s", final_url)
                out.append(it); continue
            outlet = outlet_for_domain(final_url, domains)
            if outlet is None:
                log.info("backtrack 미등록 도메인 url=%s", final_url)
                out.append(it); continue
            out.append(promote_cited_item(it, final_url, outlet, title, body, image))
    return out
```

- [ ] **4단계 — 통과 확인**

Run: `uv run pytest tests/test_x_backtrack.py -q`
Expected: PASS (전체 그린)

- [ ] **5단계 — `x_playwright.py` 스크레이퍼 · 오케스트레이션 구현**

```python
# src/bullet_in/adapters/x_playwright.py — 기존 _TWEET_JS 아래에 추가
_JOURN_JS = """
els => els.map(a => {
  const t = a.querySelector('[data-testid="tweetText"]');
  const time = a.querySelector('time');
  const card = a.querySelector('[data-testid="card.wrapper"]');
  const ca = card ? card.querySelector('a[href]') : null;
  const link = a.querySelector('a[href*="/status/"]');
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    card_href: ca ? ca.getAttribute('href') : ''
  };
})
"""

async def _scroll_collect(page, js, max_items):
    """스크롤하며 status_id로 누적 (SP1.5 로직 일반화 · afcstuff · 기자 공용)."""
    acc: dict[str, dict] = {}
    stagnant = 0
    for _ in range(12):
        batch = await page.eval_on_selector_all('article[data-testid="tweet"]', js)
        before = len(acc)
        _accumulate_tweets(acc, batch)
        if len(acc) >= max_items:
            break
        if len(acc) == before:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(800)
    return list(acc.values())[:max_items]
```

```python
# src/bullet_in/adapters/x_playwright.py — XPlaywrightAdapter 교체
class XPlaywrightAdapter:
    source_type = "x"

    def __init__(self, source_id, handle, max_tweets=20,
                 cookies_path="x_cookies.json", backtrack_config_path=None):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path
        self.backtrack_config_path = backtrack_config_path

    async def fetch(self):
        from datetime import timezone
        import logging
        log = logging.getLogger(__name__)
        cookies = _x_cookies(self.cookies_path)
        bt = None
        if self.backtrack_config_path:
            from bullet_in.adapters.x_backtrack import load_backtrack_config
            bt = load_backtrack_config(self.backtrack_config_path)
        now = datetime.now(timezone.utc)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            await page.goto(f"https://x.com/{self.handle}", wait_until="domcontentloaded")
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            raw_tweets = await _scroll_collect(page, _TWEET_JS, self.max_tweets)
            items = parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets, now)
            timelines = {}
            if bt:
                timelines = await self._scrape_journalists(ctx, items, bt, log)
            await browser.close()
        if bt:
            from bullet_in.adapters.x_backtrack import backtrack_promote
            items = await backtrack_promote(items, timelines, bt)
        return items

    async def _scrape_journalists(self, ctx, items, cfg, log):
        skip = {h.lower() for h in cfg.get("skip_handles", [])}
        depth = cfg.get("params", {}).get("timeline_depth", 25)
        cap = cfg.get("params", {}).get("max_journalists", 15)
        handles, seen = [], set()
        for it in items:
            h = (it.raw_payload.get("journalist") or "").lstrip("@")
            hl = h.lower()
            if h and hl not in seen and hl not in skip:
                seen.add(hl)
                handles.append(h)
        if len(handles) > cap:
            log.info("backtrack 기자 상한 초과 %d → %d (드롭 로깅)", len(handles), cap)
            handles = handles[:cap]
        timelines = {}
        for h in handles:
            try:
                page = await ctx.new_page()
                await page.goto(f"https://x.com/{h}", wait_until="domcontentloaded")
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
                timelines[h.lower()] = await _scroll_collect(page, _JOURN_JS, depth)
                await page.close()
            except Exception as e:  # 소스 격리 : 한 핸들 실패는 그 인용만 2순위로 강등
                log.warning("backtrack 타임라인 실패 handle=%s err=%s", h, e)
        return timelines
```

- [ ] **6단계 — 배선 (factory · sources.yaml)**

```python
# src/bullet_in/adapters/factory.py:29-32 교체
        elif kind == "x_playwright":
            out.append(XPlaywrightAdapter(sid, c["handle"],
                                          c.get("max_tweets", 20),
                                          c.get("cookies_path", "x_cookies.json"),
                                          c.get("backtrack_config")))
```

```yaml
# config/sources.yaml:62 — x_afcstuff config 교체 (backtrack_config 추가)
    config: { handle: "afcstuff", max_tweets: 30, cookies_path: "x_cookies.json", backtrack_config: "config/backtrack.yaml" }
```

- [ ] **7단계 — 회귀 확인**

Run: `uv run pytest -q`
Expected: PASS (기존 스위트 무회귀 — `_scroll_collect` 리팩터가 afcstuff 동작 보존, backtrack은 설정 있을 때만)

- [ ] **8단계 — 커밋**

```bash
git add src/bullet_in/adapters/x_playwright.py src/bullet_in/adapters/x_backtrack.py src/bullet_in/adapters/factory.py config/sources.yaml tests/test_x_backtrack.py
git commit -m "feat(adapters): SP2 기자 타임라인 역추적 · 제자리 승격 배선

Refs: docs/superpowers/specs/2026-07-03-sp2a-afcstuff-backtrack-design.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: 라이브 종단 검증

**Files:**
- (코드 변경 없음 — 라이브 실행 · 관측)

**참고:** 셀렉터 드리프트 · 실 카드 · t.co · 실 본문 추출은 모킹이 못 잡으므로 실 X · httpx로 검증한다. `x_cookies.json` 유효 필요 (만료 시 런북대로 재추출).

- [ ] **1단계 — 라이브 fetch 실행**

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import asyncio, yaml, logging
logging.basicConfig(level=logging.INFO)
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
adp = [a for a in build_adapters(cfg) if a.source_id == "x_afcstuff"][0]
items = asyncio.run(adp.fetch())
promoted = [it for it in items if it.source_type == "html"]
secondary = [it for it in items if it.source_type == "x"]
print(f"총 {len(items)} · 승격(1순위) {len(promoted)} · 2순위 {len(secondary)}")
for it in promoted[:5]:
    rp = it.raw_payload
    print("  [1순위]", rp.get("outlet"), "|", it.url, "| body", len(rp.get("body") or ""), "자")
for it in secondary[:5]:
    print("  [2순위]", it.raw_payload.get("journalist"), "|", it.raw_payload.get("text","")[:50])
PY
```

- [ ] **2단계 — 성공 기준 확인 (spec §9.2)**

- **(a) 최소 1건 승격** — `promoted` ≥ 1, 각 항목 `url`=기사 URL · `outlet` 설정 · `body` 길이 > 0.
- **(b) 실패건 2순위 유지** — Athletic · 카드 없음 · 매칭 실패가 `secondary`에 남음 (로그의 near-miss · 페이월 · 미등록 확인).
- **(c) 로깅** — `INFO` 로그에 near-miss · 페이월 · 미등록 도메인 · 상한 드롭이 남음.

- [ ] **3단계 — 실 파이프라인 dedup 확인 (선택)**

```bash
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8
```
Expected: 승격 URL이 직접 BBC 수집과 같으면 한 행으로 병합 (`pipeline_runs` · mart 확인), 크래시 없음.

- [ ] **4단계 — 관측 기록**

- **승격 비율** — `promoted / (promoted + secondary)` 를 런북 · 상태 메모리에 기록 (SP2-b 필요성 입력, 합격 판정엔 미사용).
- **미등록 도메인 로그** — 자주 등장하는 도메인을 `config/backtrack.yaml` domains에 추가 후보로 기록.

---

## Self-Review

- **Spec coverage:** §3.1 스크레이퍼 → Task 7 · §3.2 추출 → Task 1 · §3.3 매처 → Task 2 · §3.4 라우터 → Task 3 · §3.5 fetcher → Task 4 · §3.6 tier → Task 5 · §3.7 승격 → Task 6 · §2.1 오케스트레이션 → Task 7 · §7 격리 → Task 7 (`_scrape_journalists` try/except) · §8 중복 제거 → Task 6 (og:title 안정화) + Task 8 · §9 성공 기준 → Task 1 – 8. 커버 확인.
- **Placeholder scan:** TBD · TODO 없음, 모든 스텝에 실제 코드 · 명령 · 기대 출력 포함.
- **Type consistency:** `resolve_and_fetch` 4-튜플 반환이 Task 4 정의 · Task 7 소비에서 일치, `promote_cited_item` 시그니처가 Task 6 정의 · Task 7 호출에서 일치, `backtrack_promote(items, timelines, cfg)` 시그니처가 Task 7 정의 · 소비에서 일치.
