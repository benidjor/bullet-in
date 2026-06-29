# Tier 1 데이터 · 신호 품질 정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 뉴스 소스에 이적 키워드 필터를 걸고, BBC 가십 소스를 추가하며, 관측 데이터 (dup_count · source_counts)를 정확히 기록하고, arsenal 과거 데이터 정리 절차를 문서화한다.

**Architecture:** `HtmlAdapter.title_contains`를 리스트 지원으로 일반화해 config로 이적 키워드를 부여하고, bbc_gossip은 기존 어댑터를 config로만 추가한다. `to_articles`가 중복 · 소스별 신규 수를 집계해 `run.py`가 `pipeline_runs`에 실제 값을 적재한다.

**Tech Stack:** Python 3.11, httpx + BeautifulSoup, pydantic v2, SQLAlchemy, pytest (+respx), PyYAML.

## Global Constraints

- 변경 파일은 `src/bullet_in/adapters/html.py`, `src/bullet_in/pipeline.py`, `src/bullet_in/run.py`, `config/sources.yaml`, `tests/test_html_adapter.py`, `tests/test_pipeline.py`, `docs/runbook/`(신규)에 국한. enrich · credibility · storage 스키마 · serve 무변경.
- `title_contains`는 `str | list[str] | None`. 리스트면 제목 (소문자) substring 중 **하나라도** 포함 시 통과. 단일 문자열 · None은 현행 동작 유지 (하위호환).
- 이적 키워드 (영어, verbatim): `transfer, sign, signed, signing, deal, loan, bid, fee, medical, agree, agreed, join, joins, target, linked, links, contract, swap, move, talks`.
- bbc_gossip: `tier: 4`, 필터 없음, `enabled: true`, item_selector `a[href*='/sport/football/articles/']`.
- `to_articles` 반환은 `tuple[list[Article], dict]`, `dict = {"dup_count": int, "source_counts": {source_id: int}}`.
- 테스트: `uv run pytest -q`. 커밋 트레일러 (verbatim): `Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>`.

---

### Task 1: HtmlAdapter title_contains 리스트 일반화

**Files:**
- Modify: `src/bullet_in/adapters/html.py`
- Test: `tests/test_html_adapter.py`

**Interfaces:**
- Produces: `HtmlAdapter(__init__)`가 `title_contains: str | list[str] | None`를 받음. 리스트면 키워드 중 하나라도 제목 (소문자)에 substring으로 있으면 통과. 단일 문자열 · None은 현행대로.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_html_adapter.py` 끝에 추가:

```python
@respx.mock
def test_html_adapter_filters_by_keyword_list():
    html = ('<a class="card" href="/a">Arsenal agree deal for Gyokeres</a>'
            '<a class="card" href="/b">Match preview vs Spurs</a>'
            '<a class="card" href="/c">Saka injury update</a>'
            '<a class="card" href="/d">Rice loan talks collapse</a>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    title_contains=["transfer", "deal", "loan", "talks"])
    titles = [it.raw_payload["title"] for it in asyncio.run(a.fetch())]
    assert titles == ["Arsenal agree deal for Gyokeres", "Rice loan talks collapse"]

@respx.mock
def test_html_adapter_no_filter_returns_all():
    html = ('<a class="card" href="/a">Anything one</a>'
            '<a class="card" href="/b">Anything two</a>')
    respx.get("https://a.test/all").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/all",
                    item_selector="a.card", base_url="https://a.test")
    assert len(asyncio.run(a.fetch())) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py -k "keyword_list or no_filter" -v`
Expected: FAIL (`test_html_adapter_filters_by_keyword_list`에서 리스트가 `.lower()` 호출돼 AttributeError, 또는 매칭 불일치)

- [ ] **Step 3: 최소 구현**

`src/bullet_in/adapters/html.py`의 `__init__`에서 `self.title_contains = ...` 줄과 fetch의 필터 줄을 교체.

`__init__` 내 `title_contains` 처리:
```python
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
```
(생성자 시그니처도 `title_contains: str | list[str] | None = None`로.)

`fetch()`의 필터 줄 교체:
```python
            if self.title_keywords and not any(
                    k in title.lower() for k in self.title_keywords):
                continue
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py -v`
Expected: PASS (신규 2개 + 기존 단일 문자열 · 매칭 테스트 전부)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/html.py tests/test_html_adapter.py
git commit -m "feat(adapters): HtmlAdapter title_contains 리스트 지원(이적 키워드 다중)

Refs: docs/superpowers/specs/2026-06-28-tier1-signal-quality-design.md (§1)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 2: to_articles 중복 · 소스별 신규 수 집계

**Files:**
- Modify: `src/bullet_in/pipeline.py` (`to_articles`)
- Modify: `src/bullet_in/run.py` (호출부 + pipeline_runs INSERT)
- Test: `tests/test_pipeline.py` (기존 3개 unpack 수정 + 신규 1개)

**Interfaces:**
- Produces: `to_articles(...) -> tuple[list[Article], dict]`. `dict = {"dup_count": int, "source_counts": {source_id: int}}`. `source_counts`는 실제 append된 Article의 source_id별 수.
- Consumes (run.py): `arts, stats = to_articles(...)`.

- [ ] **Step 1: 기존 테스트 unpack 수정 + 실패 테스트 작성**

`tests/test_pipeline.py`의 기존 3개 테스트에서 `arts = to_articles(...)` 를 `arts, _ = to_articles(...)` 로 변경 (3곳). 그리고 끝에 신규 테스트 추가:

```python
def test_to_articles_returns_dup_and_source_counts():
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/a",
                fetched_at=now, raw_payload={"title": "Arsenal sign Rice"}),
        RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/a?utm_source=x",
                fetched_at=now, raw_payload={"title": "Arsenal sign Rice"}),  # 중복
        RawItem(source_id="football_london", source_type="html", url="https://y.test/b",
                fetched_at=now, raw_payload={"title": "Saka deal"}),
    ]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2},
               "football_london": {"source_id": "football_london", "tier": 4}}
    arts, stats = to_articles(raw, sources, seen={})
    assert len(arts) == 2
    assert stats["dup_count"] == 1
    assert stats["source_counts"] == {"bbc_sport": 1, "football_london": 1}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `to_articles`가 아직 리스트를 반환하므로 `arts, _ =`/`arts, stats =` unpack이 모두 `ValueError`(또는 길이 불일치)로 실패. 신규 테스트 포함 4개 에러

- [ ] **Step 3: 최소 구현**

`src/bullet_in/pipeline.py`의 `to_articles` 본문 교체 (시그니처 반환형 + 집계):

```python
def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]],
                registry: "Registry | None" = None) -> tuple[list[Article], dict]:
    out: list[Article] = []
    local_seen = dict(seen)
    dup_count = 0
    source_counts: dict[str, int] = {}
    for item in raw:
        tier = resolve_tier(item, sources, registry)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            dup_count += 1
            continue
        local_seen[url] = (h, rev)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            published_at=_published(item.raw_payload), fetched_at=item.fetched_at,
            revision=rev))
        source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
    return out, {"dup_count": dup_count, "source_counts": source_counts}
```

`src/bullet_in/run.py` 수정:
- 호출부 (현재 `arts = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)`):
```python
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
```
- pipeline_runs INSERT의 VALUES에서 `,:new,0,:err,` → `,:new,:dup,:err,` 로, 파라미터 dict에서 `"counts": json.dumps({a.source_id: 0 for a in adapters})` → `"counts": json.dumps(stats["source_counts"])` 로, 그리고 `"new": len(arts),` 다음에 `"dup": stats["dup_count"],` 추가.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline.py -v && uv run pytest -q`
Expected: PASS (전체 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/pipeline.py src/bullet_in/run.py tests/test_pipeline.py
git commit -m "fix(pipeline): to_articles가 dup_count·source_counts 집계·기록

Refs: docs/superpowers/specs/2026-06-28-tier1-signal-quality-design.md (§3)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 3: config 적용 (이적 필터 + bbc_gossip) + 라이브 스모크

**Files:**
- Modify: `config/sources.yaml`

**Interfaces:** (설정 · 검증 태스크)

- [ ] **Step 1: 이적 키워드 필터 적용**

`config/sources.yaml`의 `bbc_sport` config와 `football_london` config 각각에 아래 줄 추가 (들여쓰기는 같은 config 블록의 `item_selector`와 동일 레벨):
```yaml
      title_contains: ["transfer", "sign", "signed", "signing", "deal", "loan", "bid", "fee", "medical", "agree", "agreed", "join", "joins", "target", "linked", "links", "contract", "swap", "move", "talks"]
```

- [ ] **Step 2: bbc_gossip 소스 추가**

`config/sources.yaml`의 `sources:` 목록에 항목 추가 (기존 `bbc_sport` 블록 형식을 따름):
```yaml
  - source_id: bbc_gossip
    display_name: BBC Football Gossip
    tier: 4
    medium: newspaper
    adapter: html
    config:
      list_url: "https://www.bbc.com/sport/football/gossip"
      item_selector: "a[href*='/sport/football/articles/']"
    enabled: true
```

- [ ] **Step 3: 라이브 스모크 (수동)**

Run:
```bash
set -a; source .env; set +a
uv run python -c "
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
ads = {a.source_id: a for a in build_adapters(cfg)}
for sid in ['bbc_gossip', 'bbc_sport', 'football_london']:
    items = asyncio.run(ads[sid].fetch())
    print(sid, 'fetched', len(items))
    for it in items[:5]: print('   -', it.raw_payload['title'][:60])
"
```
Expected: `bbc_gossip` >0건 (아스날 · 타구단 가십 섞임). `bbc_sport` · `football_london`은 이적 키워드가 든 제목만 (없으면 0건일 수 있음 — 정상). 셀렉터로 0건이면 실제 DOM 재확인 (`docs/troubleshooting/2026-06-12-live-source-selector-drift.md`).

- [ ] **Step 4: 전체 테스트 회귀 확인**

Run: `uv run pytest -q`
Expected: PASS (통합은 DB 없으면 skip).

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml
git commit -m "feat(adapters): 이적 키워드 필터(bbc·football.london)·bbc_gossip 소스 추가

라이브 fetch 스모크로 가십 수집·이적 필터 동작 확인.

Refs: docs/superpowers/specs/2026-06-28-tier1-signal-quality-design.md (§1,§2)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

### Task 4: arsenal 과거 데이터 정리 런북

**Files:**
- Create: `docs/runbook/2026-06-28-arsenal-stale-cleanup.md`

**Interfaces:** (문서 전용)

- [ ] **Step 1: 런북 작성**

`docs/runbook/2026-06-28-arsenal-stale-cleanup.md` 생성:

```markdown
# 런북 — arsenal 과거(비-영입) 데이터 정리

arsenal_official이 "영입(sign) 전용 고정밀 소스"로 재정의되기 전 적재된 비-영입 기사
(여자팀·잡다, 약 31건)가 `articles`·서빙 페이지에 잔존한다. 일회성으로 정리한다.
**실행은 라이브 MariaDB가 떠 있는 상태에서 직접 수행한다.**

## 절차
1. DB 접속 준비:
   ```bash
   set -a; source .env; set +a
   docker compose ps   # mariadb running 확인
   ```
2. 대상 수 확인(삭제 전 반드시):
   ```sql
   SELECT COUNT(*) FROM articles
   WHERE source_id = 'arsenal_official'
     AND LOWER(title_original) NOT LIKE '%sign%'
     AND (title_ko IS NULL OR LOWER(title_ko) NOT LIKE '%sign%');
   ```
3. 삭제:
   ```sql
   DELETE FROM articles
   WHERE source_id = 'arsenal_official'
     AND LOWER(title_original) NOT LIKE '%sign%'
     AND (title_ko IS NULL OR LOWER(title_ko) NOT LIKE '%sign%');
   ```
4. 서빙 페이지 재생성: 다음 파이프라인 실행(`uv run python -m bullet_in.run`)이
   `articles` 기준으로 `site/index.html`을 다시 쓴다.

## 주의
- 2단계 COUNT 결과가 예상(약 31건)과 크게 다르면 멈추고 기준을 재검토한다.
- 'sign' substring 기준이라 'design'·'resign' 등은 보존될 수 있다(현 'sign' 필터와 동일 기준이라 일관).
```

- [ ] **Step 2: 커밋**

```bash
git add docs/runbook/2026-06-28-arsenal-stale-cleanup.md
git commit -m "docs(runbook): arsenal 과거 비-영입 데이터 정리 절차

Refs: docs/superpowers/specs/2026-06-28-tier1-signal-quality-design.md (§4)
Co-Authored-By: Claude Opus 4.8 (1M context) <94089198+benidjor@users.noreply.github.com>"
```

---

## 성공 기준 (전체)
- `uv run pytest -q` 전체 통과 (기존 회귀 없음, 신규 테스트 포함).
- 라이브 스모크: bbc_gossip 수집 >0, bbc_sport · football_london 이적 키워드 필터 동작.
- `to_articles`가 dup_count · source_counts 반환, run.py가 pipeline_runs에 실제 값 적재.
- arsenal 정리 런북 존재 (실행은 사용자).
