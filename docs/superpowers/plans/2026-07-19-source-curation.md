# 수집 · 소스 트랙 (트랙 ②) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bbc_gossip 썸네일 (og:image 경량 상세 방문 + 기존 45건 백필) 과 football.london Tom Canton 제한 (pipeline drop + 기존 157건 삭제 절차) 을 구현한다.

**Architecture:** 어댑터는 수집만 · 정책은 pipeline 이라는 기존 경계를 유지한다.
`HtmlAdapter` 에 `thumbnail_only` 경량 경로를 추가하고, `to_articles` 에 `journalist_allowlist` drop 을 여자팀 필터 선례대로 넣는다.
기존 행 백필은 `backfill_journalist.py` 패턴의 신규 모듈로 처리한다.

**Tech Stack:** Python 3.11 · httpx + BeautifulSoup · SQLAlchemy · pytest + respx (모킹).

**Spec:** `docs/superpowers/specs/2026-07-19-source-curation-design.md` (승인됨 — 충돌 시 spec 이 우선, 단 충돌 발견 시 구현하지 말고 질문할 것).

## Global Constraints

- 라이브 fetch 금지 (모든 태스크는 모킹 테스트만 — 라이브 검증은 Task 5 에서 컨트롤러가 수행).
  특히 fmkorea 는 어떤 경로로도 접촉하지 않는다.
- 커밋: `<type>(<scope>): 한국어 제목` (50자 이하) + 본문 도입 1–2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러 2줄 (설계 Fable 5 · 구현 실제 모델, `docs/conventions/2026-06-11-commit-pr-convention.md` §1.1 · §1.3).
- 커밋 전 자기 위치 검증: `git branch --show-current` 가 `feat/source-curation` 인지 확인 후 커밋.
- 문서 (.md) 는 컨벤션 §2.2 서식 (한 줄 = 한 문장 · `→` `—` 줄 시작 · `·` 와 여는 괄호 양옆 띄우기, 코드 · URL · 경로 제외).
- 테스트는 `uv run pytest -q` 로 실행 (DB · Airflow 없는 환경에서 통합 테스트는 자동 skip).
- 기존 코드의 주석 밀도 · 네이밍 · 한국어 주석 스타일을 따른다.

---

### Task 1: pipeline journalist_allowlist drop

**Files:**
- Modify: `src/bullet_in/pipeline.py` (to_articles — journalist 확정 직후 drop)
- Modify: `config/sources.yaml` (football_london 에 `journalist_allowlist`)
- Test: `tests/test_pipeline.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: `select_journalist(item, src, registry)` (기존 — 등재 기자 우선 대표 1명 선정).
- Produces: `to_articles` stats dict 에 `"author_drop_count": int` 키 추가 (기존 키 유지 — 소비처는 추가 키에 안전).
  sources dict 의 소스 최상위 필드 `journalist_allowlist: list[str] | None`.

- [ ] **Step 1: 실패하는 테스트 4건 작성** — `tests/test_pipeline.py` 끝에 추가

```python
def test_to_articles_allowlist_drops_other_journalists():
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="football_london", source_type="html", url="https://y.test/c1",
                fetched_at=now, raw_payload={"title": "Arsenal transfer latest",
                                             "authors": ["Tom Canton"]}),
        RawItem(source_id="football_london", source_type="html", url="https://y.test/c2",
                fetched_at=now, raw_payload={"title": "Arsenal deal news",
                                             "authors": ["Jake Stokes"]}),
    ]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert [a.url for a in arts] == ["https://y.test/c1"]
    assert stats["author_drop_count"] == 1

def test_to_articles_allowlist_coauthor_with_canton_survives():
    # select_journalist 가 등재 기자(Canton, credibility.yaml)를 우선 선정 → 공저 생존
    now = datetime.now(timezone.utc)
    raw = [RawItem(source_id="football_london", source_type="html", url="https://y.test/c3",
                   fetched_at=now, raw_payload={"title": "Arsenal news",
                                                "authors": ["Jake Stokes", "Tom Canton"]})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1 and arts[0].journalist == "Tom Canton"

def test_to_articles_allowlist_drops_journalist_none():
    # 상세 fetch 실패 · 저자 부재 → Canton 확인 불가 → drop (seen 미기록 → 다음 회차 재시도)
    raw = [RawItem(source_id="football_london", source_type="html", url="https://y.test/c4",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal transfer latest"})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert arts == [] and stats["author_drop_count"] == 1

def test_to_articles_no_allowlist_source_unaffected():
    raw = [RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/b1",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign Rice",
                                "authors": ["Alastair Telfer"]})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 1}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1
    assert stats["author_drop_count"] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: 신규 4건 FAIL (`KeyError: 'author_drop_count'` 또는 drop 미동작으로 개수 불일치), 기존 전건 PASS.

- [ ] **Step 3: 구현** — `src/bullet_in/pipeline.py`

`to_articles` 의 카운터 초기화에 한 줄 추가:

```python
    dup_count = 0
    women_count = 0
    author_drop_count = 0
```

루프 안 `select_journalist` 직후 · `resolve_tier` 이전에 drop 삽입 (기존 줄 사이에 3줄):

```python
        journalist = select_journalist(item, src, registry)
        allowlist = src.get("journalist_allowlist")
        if allowlist and journalist not in allowlist:
            author_drop_count += 1     # 전담 외 기자 · 저자 미상 drop (spec §3.1)
            continue
        tier = resolve_tier(item, sources, registry, journalist=journalist)
```

반환 stats 에 키 추가:

```python
    return out, {"dup_count": dup_count, "source_counts": source_counts,
                 "women_count": women_count, "author_drop_count": author_drop_count}
```

`config/sources.yaml` 의 football_london 항목에 소스 최상위 필드 추가 (`adapter: html` 줄 아래):

```yaml
    adapter: html
    journalist_allowlist: ["Tom Canton"]   # 아스날 전담 외 기자 drop (spec §3.1)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline.py tests/test_adapter_factory.py -q`
Expected: 전건 PASS (factory 는 소스 최상위 키를 읽지 않아 무영향 — 회귀 확인용).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/pipeline.py config/sources.yaml tests/test_pipeline.py
git commit  # 제목: feat(pipeline): football.london 기자 allowlist drop
```

---

### Task 2: HtmlAdapter thumbnail_only 경량 상세 방문

**Files:**
- Modify: `src/bullet_in/adapters/html.py`
- Modify: `src/bullet_in/adapters/factory.py` (html 분기)
- Modify: `config/sources.yaml` (bbc_gossip config 에 `thumbnail_only: true`)
- Test: `tests/test_html_adapter.py` · `tests/test_adapter_factory.py` (각 파일 끝에 추가)

**Interfaces:**
- Consumes: `extract_og_image(html) -> str | None` (기존, `bullet_in.adapters.meta`).
- Produces: `HtmlAdapter.__init__(..., thumbnail_only: bool = False)` · 인스턴스 속성 `self.thumbnail_only`.
  config 키 `thumbnail_only` (Task 3 의 대상 소스 산출이 이 키를 읽는다).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_html_adapter.py` 끝에 3건

```python
@respx.mock
def test_html_adapter_thumbnail_only_fetches_og_image_only():
    list_html = '<a class="card" href="/a">Gossip roundup</a>'
    detail = ('<html><head><meta property="og:image" content="https://img.test/t.jpg">'
              '</head><body><article><p>Body text.</p>'
              '<script type="application/ld+json">{"@type":"NewsArticle",'
              '"author":{"@type":"Person","name":"Some Writer"}}</script>'
              '</article></body></html>')
    respx.get("https://a.test/gossip").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/gossip",
                    item_selector="a.card", base_url="https://a.test",
                    thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload["image_url"] == "https://img.test/t.jpg"
    # 본문 · 인라인 이미지 · 저자는 추출하지 않는다 (spec §3.3 — 번역 비용 무변경)
    assert "body" not in items[0].raw_payload
    assert "images" not in items[0].raw_payload
    assert "authors" not in items[0].raw_payload

@respx.mock
def test_html_adapter_thumbnail_only_keeps_title_on_detail_failure():
    list_html = '<a class="card" href="/a">Gossip roundup</a>'
    respx.get("https://a.test/gossip").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/gossip",
                    item_selector="a.card", base_url="https://a.test",
                    thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload["title"] == "Gossip roundup"
    assert "image_url" not in items[0].raw_payload

@respx.mock
def test_html_adapter_body_selector_takes_precedence_over_thumbnail_only():
    # body_selector 가 있으면 풀 수집 경로 그대로 — thumbnail_only 는 무시 (spec §3.3)
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><head><meta property="og:image" content="https://img.test/g.jpg">'
              '</head><body><div class="article-body"><p>Deal done.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body", thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["body"] == "Deal done."
    assert items[0].raw_payload["image_url"] == "https://img.test/g.jpg"
```

`tests/test_adapter_factory.py` 끝에 1건 (기존 `test_factory_passes_body_selector_to_html` 스타일):

```python
def test_factory_passes_thumbnail_only_to_html():
    cfg = {"sources": [{"source_id": "bbc_gossip", "adapter": "html",
                        "config": {"list_url": "https://x", "item_selector": "a",
                                   "thumbnail_only": True}}]}
    a = build_adapters(cfg)[0]
    assert isinstance(a, HtmlAdapter) and a.thumbnail_only is True
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_html_adapter.py tests/test_adapter_factory.py -q`
Expected: 신규 4건 FAIL (`TypeError: unexpected keyword argument 'thumbnail_only'`), 기존 전건 PASS.

- [ ] **Step 3: 구현**

`src/bullet_in/adapters/html.py` — `__init__` 시그니처 · 속성:

```python
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, title_contains: str | list[str] | None = None,
                 body_selector: str | None = None, title_selector: str | None = None,
                 thumbnail_only: bool = False):
```

```python
        self.body_selector = body_selector
        self.title_selector = title_selector
        self.thumbnail_only = thumbnail_only
```

`fetch()` 의 상세 방문 분기 — 기존 `if self.body_selector:` 블록 뒤에 `elif` 추가:

```python
                if self.body_selector:
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        el = BeautifulSoup(rb.text, "html.parser").select_one(self.body_selector)
                        payload["body"] = el.get_text(" ", strip=True) if el else ""
                        payload["image_url"] = extract_og_image(rb.text)
                        payload["images"] = extract_body_images(
                            rb.text, self.body_selector, base_url=url)
                        payload["authors"] = extract_authors(rb.text)
                    except httpx.HTTPError:
                        payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
                elif self.thumbnail_only:
                    # 경량 상세 방문 — og:image 만 (본문 · 저자 미추출 = 번역 비용 무변경)
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        payload["image_url"] = extract_og_image(rb.text)
                    except httpx.HTTPError:
                        pass  # 상세 실패 — 제목만 적재, 놓친 이미지는 백필 몫
```

`src/bullet_in/adapters/factory.py` — html 분기에 키 전달:

```python
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector"),
                                   title_selector=c.get("title_selector"),
                                   thumbnail_only=c.get("thumbnail_only", False)))
```

`config/sources.yaml` — bbc_gossip 의 config 에 추가:

```yaml
    config:
      list_url: "https://www.bbc.com/sport/football/gossip"
      item_selector: "a[href*='/sport/football/articles/']"
      thumbnail_only: true   # og:image 만 경량 상세 방문 (spec §3.3)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_html_adapter.py tests/test_adapter_factory.py -q`
Expected: 전건 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/html.py src/bullet_in/adapters/factory.py \
        config/sources.yaml tests/test_html_adapter.py tests/test_adapter_factory.py
git commit  # 제목: feat(adapter): bbc_gossip 썸네일 경량 상세 방문
```

---

### Task 3: backfill_image 모듈 (기존 45건 백필)

**Files:**
- Create: `src/bullet_in/backfill_image.py`
- Test: `tests/test_backfill_image.py`

**Interfaces:**
- Consumes: config 키 `thumbnail_only` (Task 2) · `extract_og_image` · `load_sources` (기존).
- Produces: `python -m bullet_in.backfill_image [--limit N] [--dry-run]` CLI.
  `thumbnail_source_ids(sources: dict) -> list[str]` · `backfill(limit, dry_run) -> dict[str, int]` (`{"ok": n, "fail": n}`).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_backfill_image.py` 신규

```python
import asyncio
import httpx, respx
from bullet_in import backfill_image as bi

def test_thumbnail_source_ids_picks_flagged_sources():
    sources = {
        "bbc_gossip": {"source_id": "bbc_gossip",
                       "config": {"list_url": "x", "thumbnail_only": True}},
        "bbc_sport": {"source_id": "bbc_sport",
                      "config": {"list_url": "x", "body_selector": "article"}},
        "guardian": {"source_id": "guardian", "config": {}},
    }
    assert bi.thumbnail_source_ids(sources) == ["bbc_gossip"]

# --- backfill() 루프 — DB · 네트워크 전부 모킹 (test_backfill_journalist 선례) ---

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows

class _FakeConn:
    def __init__(self, eng):
        self._eng = eng
    def execute(self, sql, params=None):
        if params and "img" in params:
            self._eng.updates.append(params)
        return _FakeResult(self._eng.rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class _FakeEngine:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
    def connect(self):
        return _FakeConn(self)
    def begin(self):
        return _FakeConn(self)

@respx.mock
def test_backfill_updates_only_rows_with_og_image(monkeypatch):
    rows = [{"content_hash": "h1", "url": "https://b.test/1"},
            {"content_hash": "h2", "url": "https://b.test/2"}]
    eng = _FakeEngine(rows)
    monkeypatch.setattr(bi, "create_engine", lambda *a, **k: eng)
    monkeypatch.setattr(bi, "load_sources", lambda *_: {
        "bbc_gossip": {"source_id": "bbc_gossip", "config": {"thumbnail_only": True}}})
    monkeypatch.setattr(bi, "REQUEST_GAP_SEC", 0)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    respx.get("https://b.test/1").mock(return_value=httpx.Response(
        200, text='<meta property="og:image" content="https://img.test/1.jpg">'))
    respx.get("https://b.test/2").mock(return_value=httpx.Response(200, text="<html></html>"))
    stats = asyncio.run(bi.backfill())
    assert stats == {"ok": 1, "fail": 1}          # og:image 부재는 fail · NULL 유지
    assert eng.updates == [{"img": "https://img.test/1.jpg", "h": "h1"}]

@respx.mock
def test_backfill_dry_run_writes_nothing(monkeypatch):
    rows = [{"content_hash": "h1", "url": "https://b.test/1"}]
    eng = _FakeEngine(rows)
    monkeypatch.setattr(bi, "create_engine", lambda *a, **k: eng)
    monkeypatch.setattr(bi, "load_sources", lambda *_: {
        "bbc_gossip": {"source_id": "bbc_gossip", "config": {"thumbnail_only": True}}})
    monkeypatch.setattr(bi, "REQUEST_GAP_SEC", 0)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    respx.get("https://b.test/1").mock(return_value=httpx.Response(
        200, text='<meta property="og:image" content="https://img.test/1.jpg">'))
    stats = asyncio.run(bi.backfill(dry_run=True))
    assert stats == {"ok": 1, "fail": 0}
    assert eng.updates == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backfill_image.py -q`
Expected: FAIL (`ModuleNotFoundError: bullet_in.backfill_image`).

- [ ] **Step 3: 구현** — `src/bullet_in/backfill_image.py` 신규 (전문)

```python
"""thumbnail_only 소스의 기존 행 image_url 백필 (1회성).

raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.
멱등 — 재실행 시 image_url IS NULL 인 행만 다시 시도한다.
대상 소스는 config 의 thumbnail_only 로 도출한다 (현재 bbc_gossip —
fmkorea 등 2h 규칙 소스가 섞이지 않는 구조).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_image --limit 5 --dry-run
    uv run python -m bullet_in.backfill_image
"""
from __future__ import annotations
import argparse, asyncio, logging, os
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_og_image
from bullet_in.score import load_sources

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 순차 · 요청 간격 (라이브 사이트 부담 회피)

def thumbnail_source_ids(sources: dict) -> list[str]:
    return [sid for sid, s in sources.items()
            if s.get("config", {}).get("thumbnail_only")]

_SELECT_SQL = text(
    "SELECT content_hash, url FROM articles "
    "WHERE image_url IS NULL AND source_id IN :sids ORDER BY published_at DESC"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수
_UPDATE_SQL = text("UPDATE articles SET image_url=:img WHERE content_hash=:h")

async def backfill(limit: int | None = None, dry_run: bool = False) -> dict[str, int]:
    sources = load_sources("config/sources.yaml")
    sids = thumbnail_source_ids(sources)
    stats = {"ok": 0, "fail": 0}
    if not sids:
        log.info("thumbnail_only 소스 없음 — 종료")
        return stats
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": sids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("재fetch 대상 %d건 (소스 %s)", len(rows), ", ".join(sids))
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    stats["fail"] += 1        # 404 · 타임아웃 → NULL 유지 · 재실행 가능
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                img = extract_og_image(r.text)
                if not img:
                    stats["fail"] += 1
                    log.warning("og:image 부재 %s", row["url"])
                    continue
                if dry_run:
                    log.info("[dry-run] %s → %s", row["url"], img)
                else:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"img": img, "h": row["content_hash"]})
                stats["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="thumbnail_only 소스 image_url 백필 (멱등)")
    ap.add_argument("--limit", type=int, default=None, help="재fetch 대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    args = ap.parse_args()
    stats = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    print(f"성공 {stats['ok']} · 실패 {stats['fail']}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_backfill_image.py -q`
Expected: 3건 PASS.

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `uv run pytest -q`
Expected: 전건 PASS (기존 378 passed · 1 skip 기준 + 신규 11건).

```bash
git add src/bullet_in/backfill_image.py tests/test_backfill_image.py
git commit  # 제목: feat(backfill): bbc_gossip 기존 행 image_url 백필 CLI
```

---

### Task 4: football.london 정리 런북 (컨트롤러 직접 작성)

**Files:**
- Create: `docs/runbook/2026-07-19-football-london-canton-cleanup.md`

문서 트랙 선례 (BBC 정리 런북 `docs/runbook/2026-06-30-bbc-collection-cleanup.md`) 를 따라 컨트롤러가 직접 작성한다.
§2.2 서식 준수.
필수 내용:

- 배경: Tom Canton 만 허용 결정 (spec §3.1 · 지시 충돌 재확인 경위 한 줄).
- 전제: **journalist_allowlist 필터가 머지 · 배포된 뒤에만 실행** (삭제만 먼저 하면 재수집으로 부활).
- 사전 확인 쿼리 (실측 기대값 병기 — 2026-07-19 기준 220건 · Canton 63 · 삭제 대상 157):

```sql
SELECT journalist, COUNT(*) FROM articles
WHERE source_id='football_london' GROUP BY journalist ORDER BY 2 DESC;
SELECT COUNT(*) FROM articles
WHERE source_id='football_london'
  AND (journalist IS NULL OR journalist <> 'Tom Canton');
```

- 삭제 실행:

```sql
DELETE FROM articles
WHERE source_id='football_london'
  AND (journalist IS NULL OR journalist <> 'Tom Canton');
```

- 사후 검증: 남은 행 전건 `journalist='Tom Canton'` 확인 쿼리 + 다음 사이클 후 `author_drop_count` 로 재유입 0 관측.
- 주의: MariaDB 삭제는 비가역 (MongoDB raw 는 무접촉 · 보존) · 삭제 후 사이트 재생성 필요 (`run.py` 사이클이 수행).

- [ ] Step 1: 런북 작성 (위 필수 내용 전부 포함)
- [ ] Step 2: 커밋 — `git add docs/runbook/2026-07-19-football-london-canton-cleanup.md` · 제목: `docs(runbook): football.london Canton 정리 절차` (컨트롤러 단독 작업 — co-author 는 Fable 5 한 줄)

---

### Task 5: 머지 전 라이브 검증 (컨트롤러 직접 실행)

**Files:** 없음 (검증만).

fmkorea 무접촉 — bbc_gossip 단독 어댑터만 라이브로 친다.

- [ ] Step 1: bbc_gossip 어댑터 단독 fetch 로 og:image 실수집 확인

```bash
uv run python - <<'EOF'
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open("config/sources.yaml"))
ad = next(a for a in build_adapters(cfg)
          if getattr(a, "source_id", "") == "bbc_gossip")
items = asyncio.run(ad.fetch())
withimg = [i for i in items if i.raw_payload.get("image_url")]
print(f"수집 {len(items)}건 · image_url {len(withimg)}건")
for i in items[:5]:
    print(i.raw_payload.get("image_url"), "|", i.url)
EOF
```

Expected: 수집 N건 (>0) 중 대다수 image_url 채움 · URL 이 `https://` BBC CDN 형태.
0건이거나 전부 None 이면 셀렉터 · og:image 드리프트 — 원인 파악 전 머지 금지.

- [ ] Step 2: 백필 드라이런 (DB 는 읽기만 · BBC 재fetch 5건 한정)

```bash
set -a; source .env; set +a
uv run python -m bullet_in.backfill_image --limit 5 --dry-run
```

Expected: `[dry-run] <url> → <og:image url>` 5건 내외 · `성공 5 · 실패 0` 근사.

- [ ] Step 3: 전체 테스트 최종 확인 — `uv run pytest -q` 전건 PASS.

---

## 머지 후 라이브 반영 (spec §5 — 이 plan 의 태스크 아님, 순서 고정)

1. 백필 본실행 (`uv run python -m bullet_in.backfill_image`)
→ bbc_gossip 45건.
2. 정리 런북대로 football.london 157건 DELETE.
3. 전체 사이클 1회 (fmkorea 마지막 fetch 대비 2h 경과 확인 후)
→ 필터 · 썸네일 실증 + 사이트 재생성.
4. README 캡처 재촬영 (측정 런북 `docs/runbook/2026-07-19-slo-measurement.md` §6) + 후속 docs PR.
