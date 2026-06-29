# 소스 재구성 + 공신력 레지스트리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **방법론 오버레이 (karpathy 가드레일):** 구현·리뷰 서브에이전트는 4원칙을 지킨다 — ① 가정·트레이드오프 표면화(불명확하면 질문) ② 단순함 우선(요청된 것만, 투기적 추상화 금지) ③ 수술적 변경(무관한 코드·주석 불간섭) ④ 목표주도(테스트 통과로 자체 루프).

**Goal:** Guardian을 제거하고, X 수집을 afcstuff(애그리게이터)로 교체해 인용된 `@계정` 기반 동적 공신력을 부여하며, fmkorea '축구 소식통' 보드를 아스날 키워드로 크롤링해 대괄호 매체 기반 공신력으로 통합한다.

**Architecture:** 기자/매체 별칭→tier를 담은 공유 레지스트리(`config/credibility.yaml`)를 `credibility.py`가 로드하고, `resolve_tier(item, sources, registry)`가 항목별 tier를 산출한다(고정/`x_mentions`/`fmkorea` 3모드). `to_articles`가 이를 호출해 tier·confidence를 채우고 `None`이면 항목을 버린다. fmkorea는 전용 어댑터가 제목 키워드 필터 + 본문 수집을 수행하고, 한국어 소스는 Gemini 번역을 건너뛴다.

**Tech Stack:** Python 3.11, pydantic v2, httpx + BeautifulSoup, pytest(+respx), PyYAML, asyncio.

**전체 테스트 실행:** `uv run pytest -q` (개별: `uv run pytest tests/<file>::<test> -v`)

---

## File Structure

| 파일 | 역할 |
|---|---|
| `config/credibility.yaml` | 신규 — 기자/매체 별칭·tier 레지스트리 |
| `src/bullet_in/credibility.py` | 신규 — `Registry`, `load_registry`, `resolve_tier` |
| `src/bullet_in/score.py` | `confidence_from_tier` 추가 |
| `src/bullet_in/pipeline.py` | `to_articles`가 `resolve_tier` 사용 + body 폴백 |
| `src/bullet_in/adapters/fmkorea.py` | 신규 — 키워드 필터 + 본문 수집 어댑터 |
| `src/bullet_in/adapters/factory.py` | `fmkorea` 분기 추가, guardian 분기 유지 |
| `src/bullet_in/enrich.py` | `partition_translation_rows` 추가 |
| `src/bullet_in/storage/mariadb.py` | `rows_missing_translation`에 `source_id` 포함 |
| `src/bullet_in/run.py` | registry 주입 + ko/en 번역 분기 |
| `config/sources.yaml` | guardian 삭제, afcstuff·fmkorea 반영 |
| `.env.example` | `GUARDIAN_API_KEY` 제거 |

---

## Task 1: 공신력 레지스트리 설정 + 로더

**Files:**
- Create: `config/credibility.yaml`
- Create: `src/bullet_in/credibility.py`
- Test: `tests/test_credibility.py`

- [ ] **Step 1: 레지스트리 설정 작성**

Create `config/credibility.yaml`:

```yaml
journalists:
  - {name: David Ornstein,    tier: 1,   aliases: ["@David_Ornstein", "온스테인", "Ornstein"]}
  - {name: Sami Mokbel,       tier: 1,   aliases: ["@SamiMokbel1_DM", "목벨", "Mokbel"]}
  - {name: Fabrizio Romano,   tier: 1.5, aliases: ["@FabrizioRomano", "로마노", "Romano"]}
  - {name: James McNicholas,  tier: 1.5, aliases: ["@_JamesMcNicholas", "맥니콜라스", "McNicholas"]}
  - {name: handofarsnal,      tier: 1.5, aliases: ["@handofarsnal"]}
  - {name: Charles Watts,     tier: 2,   aliases: ["@charles_watts", "찰스 와츠", "Watts"]}
  - {name: Amy Lawrence,      tier: 2,   aliases: ["@amylawrence71", "에이미 로런스", "Lawrence"]}
  - {name: Teamnewsandtix,    tier: 2,   aliases: ["@Teamnewsandtix", "팀뉴스앤틱스"]}
  - {name: James Olley,       tier: 2,   aliases: ["@JamesOlley", "올리", "Olley"]}
  - {name: Gary Jacob,        tier: 3,   aliases: ["게리 제이콥", "Jacob"]}
  - {name: Simon Collings,    tier: 3,   aliases: ["사이먼 콜링스", "Collings"]}
  - {name: Gianluca Di Marzio,tier: 3,   aliases: ["디 마르지오", "Di Marzio"]}
outlets:
  - {name: The Athletic,    tier: 1,   aliases: ["디 애슬레틱", "애슬레틱", "The Athletic"]}
  - {name: BBC,             tier: 1,   aliases: ["BBC"]}
  - {name: The Guardian,    tier: 1.5, aliases: ["가디언", "The Guardian"]}
  - {name: Sky Sports,      tier: 1.5, aliases: ["스카이 스포츠", "스카이", "Sky Sports"]}
  - {name: Goal.com,        tier: 2,   aliases: ["골닷컴", "Goal"]}
  - {name: ESPN,            tier: 2,   aliases: ["ESPN"]}
  - {name: The Times,       tier: 3,   aliases: ["더 타임스", "타임스", "The Times"]}
  - {name: Evening Standard,tier: 3,   aliases: ["이브닝 스탠다드", "Evening Standard"]}
  - {name: The Telegraph,   tier: 3,   aliases: ["텔레그래프", "The Telegraph"]}
  - {name: Daily Mail,      tier: 3,   aliases: ["데일리 메일", "Daily Mail"]}
  - {name: Sky Italia,      tier: 3,   aliases: ["스카이 이탈리아", "Sky Italia"]}
  - {name: The Sun,         tier: 4,   aliases: ["더 선", "The Sun"]}
  - {name: Mirror,          tier: 4,   aliases: ["미러", "Mirror"]}
  - {name: Express,         tier: 4,   aliases: ["익스프레스", "Express"]}
  - {name: football.london, tier: 4,   aliases: ["풋볼런던", "football.london"]}
  - {name: 90min,           tier: 4,   aliases: ["90min"]}
  - {name: HITC,            tier: 4,   aliases: ["HITC"]}
```

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/test_credibility.py`:

```python
from pathlib import Path
from bullet_in.credibility import load_registry

REG = Path("config/credibility.yaml")

def test_load_registry_maps_aliases_lowercased():
    r = load_registry(REG)
    assert r.journalists["@david_ornstein"] == 1.0
    assert r.journalists["온스테인"] == 1.0
    assert r.outlets["디 애슬레틱"] == 1.0
    assert r.outlets["데일리 메일"] == 3.0

def test_load_registry_rejects_duplicate_alias(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: A, tier: 1, aliases: ["dup"]}\n'
        '  - {name: B, tier: 2, aliases: ["dup"]}\n'
        "outlets: []\n", encoding="utf-8")
    try:
        load_registry(p)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_credibility.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.credibility'`

- [ ] **Step 4: 최소 구현 작성**

Create `src/bullet_in/credibility.py`:

```python
from __future__ import annotations
import re
from pathlib import Path
import yaml

_HANDLE_RE = re.compile(r"@(\w+)")

class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float]):
        self.journalists = journalists  # alias(lower) -> tier
        self.outlets = outlets

def _build(entries: list[dict], dest: dict[str, float]) -> None:
    for e in entries or []:
        tier = float(e["tier"])
        for alias in e["aliases"]:
            key = alias.lower()
            if key in dest:
                raise ValueError(f"duplicate alias: {alias}")
            dest[key] = tier

def load_registry(path) -> Registry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jour: dict[str, float] = {}
    out: dict[str, float] = {}
    _build(data.get("journalists", []), jour)
    _build(data.get("outlets", []), out)
    return Registry(jour, out)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_credibility.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 커밋**

```bash
git add config/credibility.yaml src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "feat(credibility): 공신력 레지스트리 설정·로더 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: resolve_tier — 고정 / x_mentions / fmkorea

**Files:**
- Modify: `src/bullet_in/credibility.py` (append `resolve_tier`)
- Test: `tests/test_credibility.py` (append)

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_credibility.py`:

```python
from datetime import datetime, timezone
from bullet_in.credibility import resolve_tier
from bullet_in.models import RawItem

def _item(source_id, payload):
    return RawItem(source_id=source_id, source_type="x", url="u",
                   fetched_at=datetime.now(timezone.utc), raw_payload=payload)

def test_resolve_fixed_source_returns_static_tier():
    sources = {"bbc_sport": {"tier": 1}}
    it = _item("bbc_sport", {"title": "Saka"})
    assert resolve_tier(it, sources, registry=None) == 1.0

def test_resolve_x_mentions_picks_highest_credibility():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "Per @David_Ornstein and @FabrizioRomano, deal close"})
    assert resolve_tier(it, sources, r) == 1.0  # min(1, 1.5)

def test_resolve_x_mentions_drops_when_no_journalist():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "huge news coming soon @nobody_here"})
    assert resolve_tier(it, sources, r) is None

def test_resolve_fmkorea_journalist_beats_outlet():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[데일리 메일] 루머", "body": "온스테인에 따르면 사실이다"})
    assert resolve_tier(it, sources, r) == 1.0  # 기자(1) > 매체 데일리메일(3)

def test_resolve_fmkorea_outlet_bracket():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[디 애슬레틱] 사카 재계약", "body": "내용"})
    assert resolve_tier(it, sources, r) == 1.0

def test_resolve_fmkorea_fallback_tier_four():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[무명 블로그] 카더라", "body": "출처 불명"})
    assert resolve_tier(it, sources, r) == 4.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_credibility.py -v -k resolve`
Expected: FAIL — `ImportError: cannot import name 'resolve_tier'`

- [ ] **Step 3: resolve_tier 구현 추가**

Append to `src/bullet_in/credibility.py`:

```python
def resolve_tier(item, sources: dict, registry: "Registry | None") -> float | None:
    """항목 1건의 tier 를 산출. None 이면 호출측에서 그 항목을 버린다."""
    src = sources.get(item.source_id, {})
    mode = src.get("credibility")

    if mode == "x_mentions":
        if registry is None:
            return None
        text = item.raw_payload.get("text", "")
        tiers = [registry.journalists[k]
                 for h in _HANDLE_RE.findall(text)
                 if (k := ("@" + h).lower()) in registry.journalists]
        return min(tiers) if tiers else None

    if mode == "fmkorea":
        if registry is None:
            return 4.0
        title = (item.raw_payload.get("title") or "").lower()
        body = (item.raw_payload.get("body") or "").lower()
        text = title + " " + body
        jt = [t for a, t in registry.journalists.items() if a in text]
        if jt:
            return min(jt)
        ot = [t for a, t in registry.outlets.items() if a in title]
        if ot:
            return min(ot)
        return 4.0

    # 고정 소스
    tier = src.get("tier")
    return float(tier) if tier is not None else None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_credibility.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/credibility.py tests/test_credibility.py
git commit -m "feat(credibility): resolve_tier 고정·x_mentions·fmkorea 모드 구현

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: confidence_from_tier 헬퍼

**Files:**
- Modify: `src/bullet_in/score.py`
- Test: `tests/test_score.py` (append)

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_score.py`:

```python
from bullet_in.score import confidence_from_tier

def test_confidence_from_tier_linear():
    assert confidence_from_tier(0) == 1.0
    assert confidence_from_tier(1) == 0.75
    assert confidence_from_tier(1.5) == 0.625
    assert confidence_from_tier(4) == 0.0
    assert confidence_from_tier(None) == 0.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_score.py::test_confidence_from_tier_linear -v`
Expected: FAIL — `ImportError: cannot import name 'confidence_from_tier'`

- [ ] **Step 3: 구현 추가 + 기존 confidence() DRY 리팩터**

Append `confidence_from_tier` to `src/bullet_in/score.py`:

```python
def confidence_from_tier(tier: float | None) -> float:
    """tier 0..4 를 confidence 1.0..0.0 로 선형 매핑. None 은 0.0."""
    if tier is None:
        return 0.0
    return round(max(0.0, 1.0 - float(tier) / 4.0), 3)
```

그리고 기존 `confidence()` 의 본문을 새 헬퍼에 위임하도록 교체(산술 중복 제거). 기존 시그니처·동작은 그대로 유지된다:

```python
def confidence(source_id: str, sources: dict[str, dict]) -> float:
    """tier 0..4 를 confidence 1.0..0.0 로 선형 매핑. 미지의 소스는 0.0."""
    src = sources.get(source_id)
    return confidence_from_tier(None if src is None else src["tier"])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_score.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/score.py tests/test_score.py
git commit -m "feat(score): tier→confidence 헬퍼 confidence_from_tier 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: pipeline.to_articles 가 resolve_tier 사용

**Files:**
- Modify: `src/bullet_in/pipeline.py`
- Test: `tests/test_pipeline.py` (modify 기존 + append)

- [ ] **Step 1: 실패하는 테스트 작성 (동적 tier 드롭/폴백)**

Append to `tests/test_pipeline.py`:

```python
from pathlib import Path
from bullet_in.credibility import load_registry

REG = load_registry(Path("config/credibility.yaml"))

def test_to_articles_drops_x_item_without_journalist():
    raw = [RawItem(source_id="x_afcstuff", source_type="x",
                   url="https://x.test/t1", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"text": "no journalist here"})]
    sources = {"x_afcstuff": {"source_id": "x_afcstuff", "credibility": "x_mentions"}}
    arts = to_articles(raw, sources, seen={}, registry=REG)
    assert arts == []

def test_to_articles_fmkorea_uses_body_as_excerpt_and_fallback_tier():
    raw = [RawItem(source_id="fmkorea", source_type="html",
                   url="https://fm.test/1", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "[무명] 카더라", "body": "본문 내용",
                                "published": "2026-06-11T10:00:00Z"})]
    sources = {"fmkorea": {"source_id": "fmkorea", "credibility": "fmkorea"}}
    arts = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1
    assert arts[0].tier == 4.0 and arts[0].confidence_score == 0.0
    assert arts[0].body_excerpt == "본문 내용"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `to_articles() got an unexpected keyword argument 'registry'`

- [ ] **Step 3: pipeline.py 수정**

Replace the contents of `src/bullet_in/pipeline.py` with:

```python
from __future__ import annotations
from datetime import datetime, timezone
from dateutil import parser as dtparser
from bullet_in.models import RawItem, Article
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.dedup import classify
from bullet_in.credibility import resolve_tier
from bullet_in.score import confidence_from_tier

def _published(payload: dict) -> datetime:
    raw = payload.get("published") or payload.get("created_at")
    try:
        return dtparser.parse(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)

def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]], registry=None) -> list[Article]:
    out: list[Article] = []
    local_seen = dict(seen)
    for item in raw:
        tier = resolve_tier(item, sources, registry)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            continue
        local_seen[url] = (h, rev)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            published_at=_published(item.raw_payload), fetched_at=item.fetched_at,
            revision=rev))
    return out
```

- [ ] **Step 4: 기존 테스트가 여전히 통과하는지 확인**

기존 `test_to_articles_assigns_hash_tier_confidence_and_dedups`는 고정 소스(`tier: 0`)에 `registry` 인자를 주지 않는다. `resolve_tier`는 고정 소스에서 registry를 보지 않으므로 그대로 통과한다.

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): to_articles 가 resolve_tier 로 동적 공신력 부여·드롭

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: fmkorea 어댑터 (키워드 필터 + 본문 수집)

**Files:**
- Create: `src/bullet_in/adapters/fmkorea.py`
- Test: `tests/test_fmkorea_adapter.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_fmkorea_adapter.py`:

```python
import asyncio, respx, httpx
from bullet_in.adapters.fmkorea import FmkoreaAdapter

LIST = '''
<a class="title" href="/1">[디 애슬레틱] 아스날 사카 재계약 임박</a>
<a class="title" href="/2">[BBC] 첼시 이적 소식</a>
<a class="title" href="/3">Arsenal target identified</a>
'''
BODY1 = '<div class="xe_content">온스테인에 따르면 사카가 재계약한다.</div>'
BODY3 = '<div class="xe_content">Arsenal scout report.</div>'

@respx.mock
def test_fmkorea_filters_by_keyword_and_fetches_body():
    respx.get("https://fm.test/football_news").mock(
        return_value=httpx.Response(200, text=LIST))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(200, text=BODY1))
    respx.get("https://fm.test/3").mock(return_value=httpx.Response(200, text=BODY3))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날", "Arsenal"],
                       base_url="https://fm.test", body_selector=".xe_content")
    items = asyncio.run(a.fetch())
    urls = {i.url for i in items}
    assert urls == {"https://fm.test/1", "https://fm.test/3"}  # [BBC] 첼시 글 제외
    one = next(i for i in items if i.url == "https://fm.test/1")
    assert one.raw_payload["title"].startswith("[디 애슬레틱]")
    assert "온스테인" in one.raw_payload["body"]
    assert one.raw_payload["lang"] == "ko"
    assert one.source_type == "html"

@respx.mock
def test_fmkorea_skips_post_when_body_fetch_fails():
    respx.get("https://fm.test/football_news").mock(
        return_value=httpx.Response(200, text='<a class="title" href="/1">아스날 속보</a>'))
    respx.get("https://fm.test/1").mock(return_value=httpx.Response(500))
    a = FmkoreaAdapter(source_id="fmkorea", list_url="https://fm.test/football_news",
                       item_selector="a.title", keywords=["아스날"],
                       base_url="https://fm.test", body_selector=".xe_content")
    assert asyncio.run(a.fetch()) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.adapters.fmkorea'`

- [ ] **Step 3: 어댑터 구현 작성**

Create `src/bullet_in/adapters/fmkorea.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

def _matches(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(k.lower() in t for k in keywords)

def _body_text(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True)[:2000] if el else ""

class FmkoreaAdapter:
    source_type = "html"
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 keywords: list[str], base_url: str | None = None,
                 body_selector: str = ".xe_content", max_posts: int = 10):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.keywords = keywords
        self.base_url = base_url or list_url
        self.body_selector = body_selector
        self.max_posts = max_posts

    async def fetch(self) -> list[RawItem]:
        now, out, seen = datetime.now(timezone.utc), [], set()
        headers = {"User-Agent": "Mozilla/5.0 bullet-in/0.1"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers) as c:
            r = await c.get(self.list_url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            matched = []
            for a in soup.select(self.item_selector):
                title = a.get_text(strip=True)
                href = a.get("href")
                if not href or not title or not _matches(title, self.keywords):
                    continue
                url = urljoin(self.base_url, href)
                if url in seen:
                    continue
                seen.add(url)
                matched.append((title, url))
                if len(matched) >= self.max_posts:
                    break
            for title, url in matched:
                try:
                    rb = await c.get(url)
                    rb.raise_for_status()
                except httpx.HTTPError:
                    continue  # 해당 글만 스킵, 배치 지속
                out.append(RawItem(
                    source_id=self.source_id, source_type="html", url=url,
                    fetched_at=now,
                    raw_payload={"title": title,
                                 "body": _body_text(rb.text, self.body_selector),
                                 "lang": "ko"}))
        return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -m "feat(adapter): fmkorea 키워드 필터·본문 수집 어댑터 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: factory 에 fmkorea 분기 등록

**Files:**
- Modify: `src/bullet_in/adapters/factory.py`
- Test: `tests/test_adapter_factory.py` (append)

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_adapter_factory.py`:

```python
def test_factory_builds_fmkorea_adapter():
    cfg = {"sources": [
        {"source_id": "fmkorea", "adapter": "fmkorea", "enabled": True,
         "config": {"list_url": "https://fm.test/football_news",
                    "item_selector": "a.title", "keywords": ["아스날", "Arsenal"]}},
    ]}
    adapters = build_adapters(cfg)
    assert adapters[0].source_id == "fmkorea"
    assert adapters[0].keywords == ["아스날", "Arsenal"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_adapter_factory.py::test_factory_builds_fmkorea_adapter -v`
Expected: FAIL — `ValueError: unknown adapter: fmkorea`

- [ ] **Step 3: factory.py 수정**

In `src/bullet_in/adapters/factory.py`, add the import near the other adapter imports:

```python
from bullet_in.adapters.fmkorea import FmkoreaAdapter
```

Then add this branch before the final `else:` in `build_adapters`:

```python
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["list_url"], c["item_selector"], c["keywords"],
                base_url=c.get("base_url"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 10)))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_adapter_factory.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/factory.py tests/test_adapter_factory.py
git commit -m "feat(factory): fmkorea 어댑터 분기 등록

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 한국어 소스 번역 분기 + mariadb source_id

**Files:**
- Modify: `src/bullet_in/enrich.py` (append `partition_translation_rows`)
- Modify: `src/bullet_in/storage/mariadb.py` (`rows_missing_translation`)
- Test: `tests/test_enrich.py` (append)

- [ ] **Step 1: 실패하는 테스트 추가**

Append to `tests/test_enrich.py`:

```python
from bullet_in.enrich import partition_translation_rows

def test_partition_splits_ko_and_en_by_source_lang():
    rows = [
        {"content_hash": "k", "source_id": "fmkorea", "title_original": "한글", "body_excerpt": "본문"},
        {"content_hash": "e", "source_id": "bbc_sport", "title_original": "Eng", "body_excerpt": "b"},
    ]
    sources = {"fmkorea": {"lang": "ko"}, "bbc_sport": {"tier": 1}}
    ko, en = partition_translation_rows(rows, sources)
    assert [r["content_hash"] for r in ko] == ["k"]
    assert [r["content_hash"] for r in en] == ["e"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_enrich.py::test_partition_splits_ko_and_en_by_source_lang -v`
Expected: FAIL — `ImportError: cannot import name 'partition_translation_rows'`

- [ ] **Step 3: enrich.py 에 구현 추가**

Append to `src/bullet_in/enrich.py`:

```python
def partition_translation_rows(rows: list[dict], sources: dict[str, dict]
                               ) -> tuple[list[dict], list[dict]]:
    """소스 lang 기준으로 (ko_rows, en_rows) 로 분리. lang 미지정은 en 취급."""
    ko, en = [], []
    for r in rows:
        lang = sources.get(r.get("source_id"), {}).get("lang", "en")
        (ko if lang == "ko" else en).append(r)
    return ko, en
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: mariadb 쿼리에 source_id 추가**

In `src/bullet_in/storage/mariadb.py`, find `rows_missing_translation` and change its SELECT to include `source_id`:

```python
    def rows_missing_translation(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(text(
                "SELECT content_hash,source_id,title_original,body_excerpt FROM articles "
                "WHERE title_ko IS NULL")).mappings().all()]
```

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `uv run pytest -q`
Expected: 기존 전체 + 신규 통과 (실패 0). MariaDB 변경은 SELECT 컬럼 추가뿐이라 단위 테스트 영향 없음.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/enrich.py src/bullet_in/storage/mariadb.py tests/test_enrich.py
git commit -m "feat(enrich): 한국어 소스 번역 분기 + 누락쿼리에 source_id 포함

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: sources.yaml · run.py · .env 통합 배선

**Files:**
- Modify: `config/sources.yaml`
- Modify: `src/bullet_in/run.py`
- Modify: `.env.example`
- Test: `tests/test_dag_import.py` (전체 스위트로 회귀 확인)

- [ ] **Step 1: sources.yaml 갱신**

Replace the contents of `config/sources.yaml` with:

```yaml
sources:
  - source_id: arsenal_official
    display_name: Arsenal.com
    tier: 0
    medium: official
    adapter: rss
    config: { feed_url: "https://www.arsenal.com/rss-feeds/news" }
    enabled: true
  - source_id: bbc_sport
    display_name: BBC Sport
    tier: 2
    medium: newspaper
    adapter: html
    config:
      list_url: "https://www.bbc.com/sport/football/teams/arsenal"
      item_selector: "a[href*='/sport/football/articles/']"
    enabled: true
  - source_id: goal
    display_name: Goal.com
    tier: 2
    medium: newspaper
    adapter: playwright
    config:
      list_url: "https://www.goal.com/en/team/arsenal/news/4dsgumo7d4ztgmgmcwzj0scnv"
      item_selector: "a[data-testid='article-link']"
    enabled: true
  - source_id: football_london
    display_name: football.london
    tier: 4
    medium: newspaper
    adapter: html
    config:
      list_url: "https://www.football.london/arsenal-fc/"
      item_selector: "a.headline"
    enabled: true
  - source_id: x_afcstuff
    display_name: afcstuff (aggregator)
    medium: x
    adapter: x_twikit
    credibility: x_mentions
    config: { handle: "afcstuff", max_tweets: 20 }
    enabled: true
  - source_id: fmkorea
    display_name: fmkorea 축구 소식통
    medium: community
    adapter: fmkorea
    credibility: fmkorea
    lang: ko
    config:
      list_url: "https://www.fmkorea.com/football_news"
      item_selector: "h3.title a"
      keywords: ["아스날", "Arsenal"]
      body_selector: ".xe_content"
      base_url: "https://www.fmkorea.com"
      max_posts: 10
    enabled: true
```

> 참고: fmkorea 의 `item_selector`·`body_selector` 는 라이브 페이지 구조에 맞춰
> 실제 크롤 테스트로 확정한다. 정적 httpx 가 차단되면 별도 Playwright 폴백을 검토한다.

- [ ] **Step 2: run.py 에 registry 주입 + ko/en 분기 배선**

In `src/bullet_in/run.py`:

(a) imports 블록에 추가:

```python
from bullet_in.credibility import load_registry
from bullet_in.enrich import enrich_rows, partition_translation_rows
```

기존 `from bullet_in.enrich import enrich_rows` 줄은 위 줄로 대체(중복 제거).

(b) `sources = load_sources("config/sources.yaml")` 다음 줄에 추가:

```python
    registry = load_registry("config/credibility.yaml")
```

(c) `arts = to_articles(...)` 호출을 다음으로 교체:

```python
    arts = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
```

(d) 번역 블록을 다음으로 교체:

```python
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ko_rows, en_rows = partition_translation_rows(
        mart.rows_missing_translation(), sources)
    for r in ko_rows:
        mart.set_translation(r["content_hash"], r["title_original"],
                             (r.get("body_excerpt") or "")[:200])
    translations = enrich_rows(en_rows, client, "gemini-2.5-flash-lite")
    for h, (tk, sk) in translations.items():
        mart.set_translation(h, tk, sk)
```

- [ ] **Step 3: .env.example 에서 GUARDIAN_API_KEY 제거**

In `.env.example`, delete the line:

```
GUARDIAN_API_KEY=REPLACE
```

- [ ] **Step 4: DAG import·전체 스위트 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 통과(실패 0). `tests/test_dag_import.py` 의 DagBag import 도 통과.

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml src/bullet_in/run.py .env.example
git commit -m "feat(sources): Guardian 제거·afcstuff·fmkorea 반영 + run 배선

- guardian 소스/ENV 제거(어댑터 코드는 보존)
- x_afcstuff(credibility: x_mentions), fmkorea(lang: ko) 추가
- run.py: load_registry 주입, ko/en 번역 분기

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 문서 정리 (runbook Guardian 참조)

**Files:**
- Modify: `docs/runbook/2026-05-27-daily-operations.md`

- [ ] **Step 1: Guardian 참조 확인**

Run: `grep -n "GUARDIAN\|Guardian\|가디언" docs/runbook/2026-05-27-daily-operations.md`
Expected: 자격증명 표/소스 목록에 Guardian 항목이 보임.

- [ ] **Step 2: 참조 갱신**

해당 줄에서 `GUARDIAN_API_KEY` 자격증명 항목과 Guardian 소스 언급을 제거하고,
소스 목록을 현재 구성(arsenal_official·bbc_sport·goal·football_london·x_afcstuff·fmkorea)으로 맞춘다. (문서 본문은 한국어 유지.)

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-05-27-daily-operations.md
git commit -m "docs(runbook): Guardian 제거·afcstuff·fmkorea 반영

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 완료 기준

- [ ] `uv run pytest -q` 전체 통과(실패 0)
- [ ] `config/sources.yaml` 에 guardian 없음, x_afcstuff·fmkorea 존재
- [ ] `resolve_tier` 3모드 단위 테스트 통과
- [ ] fmkorea 어댑터가 키워드 필터·본문 수집·본문 실패 스킵을 처리
- [ ] ko 소스가 Gemini 호출 없이 원제목/본문발췌로 채워짐(`partition_translation_rows`)
- [ ] `.env.example` 에 `GUARDIAN_API_KEY` 없음

> 라이브 검증(실제 fmkorea/afcstuff 크롤, 셀렉터 확정, SLO 측정, 캡처 슬롯)은
> feat/live-e2e 트랙에서 수행한다. 이 계획은 코드/구성/단위테스트까지를 범위로 한다.
