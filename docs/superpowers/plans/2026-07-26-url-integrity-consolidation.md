# URL 정합 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 URL 충돌 시 완전체 보호 · 스텁 업그레이드 규칙으로 cross-source 덮어쓰기를 차단하고, 온스테인 트윗을 원문 기사 URL 로 키잉해 단일 상세로 합류시키며, BBC 오염 3행을 복구한다.

**Architecture:** `dedup.classify` 를 2축 (소스 동일 × 완전체) 판정으로 확장하고 seen 맵을 4-튜플로 넓힌다.
모든 적재 경로가 `pipeline.to_articles` 를 통과하므로 한 곳 수정으로 전 경로가 보호된다.
온스테인 카드 리졸브는 `x_playwright` 수집 직후 후처리로 붙는다.

**Tech Stack:** Python 3.11 · pydantic v2 · SQLAlchemy (MariaDB) · httpx + BeautifulSoup · Playwright · pytest.

**Spec:** `docs/superpowers/specs/2026-07-26-url-integrity-consolidation-design.md` (사용자 승인 2026-07-26).

## Global Constraints

- TDD: 각 태스크는 실패 테스트 먼저.
테스트 실행은 `uv run pytest -q` (통합은 `docker compose up -d` 로 mariadb 기동 후, 없으면 skip 확인).
- serve/ · templates · name_map.yaml 수정 금지 (UI 세션 병렬 중) · sources.yaml 변경 없음.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + 트레일러.
트레일러는 실제 작업 모델 — subagent 구현 시 두 줄 병기:
`Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>` + `Co-Authored-By: Claude <구현 모델명> (구현) <noreply@anthropic.com>`.
컨트롤러 단독 작업 커밋은 라벨 없이 Fable 5 한 줄.
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- PR 머지는 사용자 직접 (세션은 push + PR 생성까지).
- PR-1 브랜치 = `feat/url-integrity-guard` (spec 커밋 715cd13 존재 · origin/main 81f4cf5 분기).
PR-2 브랜치는 PR-1 머지 후 최신 origin/main 에서 새로 분기.
- 라이브 접촉 명령은 tee 필수 · 출력 확인 목적 재실행 금지.
- 가드 머지 전까지 fmkorea 백필 · 보충 임의 실행 금지.

---

## PR-1: URL 정합 가드 + refetch CLI (브랜치 feat/url-integrity-guard)

### Task 1: dedup.classify 2축 판정 확장

**Files:**
- Modify: `src/bullet_in/dedup.py` (전체 13줄 파일)
- Test: `tests/test_dedup.py` (기존 3케이스 시그니처 갱신 + 신규 3케이스)

**Interfaces:**
- Produces: `classify(url: str, new_hash: str, seen: dict[str, tuple[str, int, str, bool]], new_source: str, new_has_body: bool) -> tuple[Decision, int]`.
`Decision = Literal["new", "duplicate", "changed", "blocked", "upgrade"]`.
seen 값 = `(last_hash, last_revision, source_id, has_body)`.
- Consumes: 없음 (독립 모듈).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_dedup.py` 전체를 아래로 교체

```python
from bullet_in.dedup import classify

def test_new_when_url_unseen():
    assert classify("https://x.test/a", "h1", {}, "bbc_sport", True) == ("new", 1)

def test_duplicate_same_source_same_hash():
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", True)}
    assert classify("https://x.test/a", "h1", seen, "bbc_sport", True) == ("duplicate", 3)

def test_changed_same_source_hash_differs():
    # revision 원 목적 (같은 소스의 정당한 기사 갱신) 은 계속 허용 (spec §4)
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", True)}
    assert classify("https://x.test/a", "h2", seen, "bbc_sport", True) == ("changed", 4)

def test_blocked_cross_source_existing_complete():
    # BBC 완전체 행에 fmkorea 퍼온 글 도착 → 보호 (2026-07-25 오염 사례 차단)
    seen = {"https://x.test/a": ("h1", 1, "bbc_sport", True)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", True) == ("blocked", 1)

def test_upgrade_cross_source_stub_to_complete():
    # 온스테인 스텁 행에 fmkorea 전문 도착 → 같은 행 승격 (spec §4 upgrade)
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", False)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", True) == ("upgrade", 2)

def test_blocked_cross_source_both_stubs():
    # 정보가 늘지 않는 교체는 불허 — first-seen 승리
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", False)}
    assert classify("https://x.test/a", "h2", seen, "other_stub", False) == ("blocked", 1)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_dedup.py -q`
Expected: FAIL (TypeError — 기존 classify 는 인자 3개).

- [ ] **Step 3: 구현** — `src/bullet_in/dedup.py` 전체를 아래로 교체

```python
from typing import Literal

Decision = Literal["new", "duplicate", "changed", "blocked", "upgrade"]

def classify(url: str, new_hash: str,
             seen: dict[str, tuple[str, int, str, bool]],
             new_source: str, new_has_body: bool) -> tuple[Decision, int]:
    """seen: canonical url -> (last_hash, last_revision, source_id, has_body).

    2축 규칙 (spec 2026-07-26 §4) — 소스 동일 여부 × 완전체 여부:
    같은 소스는 현행대로 revision 갱신, 다른 소스는 완전체 보호 · 스텁 업그레이드.
    """
    if url not in seen:
        return "new", 1
    last_hash, last_rev, last_source, last_has_body = seen[url]
    if last_source == new_source:
        if last_hash == new_hash:
            return "duplicate", last_rev
        return "changed", last_rev + 1
    if last_has_body:
        return "blocked", last_rev
    if new_has_body:
        return "upgrade", last_rev + 1
    return "blocked", last_rev
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_dedup.py -q`
Expected: 6 passed.
이 시점에 `tests/test_pipeline.py` 는 깨진다 (to_articles 가 옛 시그니처로 호출)
— Task 3 에서 복구하므로 여기서는 test_dedup.py 만 확인한다.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_dedup.py src/bullet_in/dedup.py
git commit -m "feat(collect): dedup 판정을 2축 규칙으로 확장 — blocked · upgrade 추가"
```

(커밋 본문 · 트레일러는 Global Constraints 형식 준수.
본문 도입: cross-source URL 충돌이 "changed" 로 오판되던 결함의 판정 계층 수정.)

### Task 2: seen_map 4-튜플 · upsert source_id 갱신

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:43` (ON DUPLICATE 절) · `src/bullet_in/storage/mariadb.py:70-73` (seen_map)
- Test: `tests/integration/test_mariadb_store.py` (기존 1케이스 갱신 + 신규 2케이스)

**Interfaces:**
- Produces: `MartStore.seen_map() -> dict[str, tuple[str, int, str, bool]]` (Task 1 의 seen 값과 동형).
upsert 는 ON DUPLICATE 시 source_id 도 교체 (upgrade 전면 채택 — spec §5).
- Consumes: Task 1 의 튜플 형태 정의.

- [ ] **Step 1: 실패 테스트 작성** — `tests/integration/test_mariadb_store.py` 에 추가 + 기존 갱신

기존 `test_changed_url_updates_hash_and_resets_translation` 의 단언 1줄 교체:

```python
    assert store.seen_map()["https://x.test/a"] == ("h2", 2, "g", False)
```

파일 끝에 신규 2케이스 추가:

```python
def test_seen_map_carries_source_and_body_flag(engine):
    # 가드 판정 입력 (spec §5) — has_body 는 body_source 비어있지 않음
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([_art(h="h1", url="https://x.test/a"),
                  Article(content_hash="h2", url="https://x.test/b", source_id="fmkorea",
                          title_original="T", body_source="원문",
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    seen = store.seen_map()
    assert seen["https://x.test/a"] == ("h1", 1, "guardian", False)
    assert seen["https://x.test/b"] == ("h2", 1, "fmkorea", True)

def test_upsert_upgrade_replaces_source_id(engine):
    # 스텁 업그레이드는 전면 채택 — source_id 까지 교체 (spec §3 사용자 확정)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="x_ornstein",
                          title_original="tweet text",
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="fmkorea",
                          title_original="전문 제목", body_source="전문", revision=2,
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    assert store.count() == 1
    assert store.seen_map()["https://x.test/a"] == ("h2", 2, "fmkorea", True)
```

- [ ] **Step 2: 실패 확인**

Run: `docker compose up -d && uv run pytest tests/integration/test_mariadb_store.py -q`
Expected: 신규 2케이스 + 갱신 1케이스 FAIL (seen_map 이 2-튜플 · source_id 미갱신).

- [ ] **Step 3: 구현**

`seen_map` 교체 (`src/bullet_in/storage/mariadb.py:70-73`):

```python
    def seen_map(self) -> dict[str, tuple[str, int, str, bool]]:
        """url -> (content_hash, revision, source_id, has_body).
        has_body = body_source 가 비어있지 않음 — 완전체 판정 기준 (spec §3)."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT url,content_hash,revision,source_id,"
                "COALESCE(body_source,'')<>'' FROM articles")).all()
        return {u: (h, rev, sid, bool(hb)) for u, h, rev, sid, hb in rows}
```

upsert ON DUPLICATE 절 (`mariadb.py:47-48` 사이) 에 1줄 추가:

```sql
             source_id=VALUES(source_id),
```

(위치는 `body_ko=IF(...)` 다음 · `title_original=VALUES(title_original)` 앞.
같은 소스 갱신에는 같은 값이라 무해하고, cross-source 도달은 upgrade 뿐이다
— blocked 는 pipeline 이 이미 드롭.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -q`
Expected: 전부 passed.

- [ ] **Step 5: 커밋**

```bash
git add tests/integration/test_mariadb_store.py src/bullet_in/storage/mariadb.py
git commit -m "feat(collect): seen 맵에 소스 · 완전체 플래그 추가, upsert 전면 채택"
```

### Task 3: pipeline 가드 배선 · blocked 집계 · run.py 로그

**Files:**
- Modify: `src/bullet_in/pipeline.py:49-98` (to_articles) · `src/bullet_in/run.py:75-77` (drop 집계 로그)
- Test: `tests/test_pipeline.py` (기존 1케이스 갱신 + 신규 5케이스)

**Interfaces:**
- Consumes: Task 1 `classify` 신 시그니처 · Task 2 seen 4-튜플.
- Produces: `to_articles(..., seen: dict[str, tuple[str, int, str, bool]], ...)` 반환 stats 에 `blocked_count` 키 추가.
기존 키 (dup_count · source_counts · women_count · author_drop_count) 유지.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_pipeline.py` 에 추가 + 기존 갱신

기존 `test_to_articles_prefers_en_source_over_fmkorea_for_same_url` 의 마지막 단언 교체
(동일 제목 = 스텁끼리 충돌이라 이제 duplicate 가 아니라 blocked 로 잡힌다):

```python
    assert stats["blocked_count"] == 1
```

파일에 신규 5케이스 추가:

```python
def test_cross_run_complete_row_blocks_fmkorea():
    # cross-run: DB 에 BBC 완전체 존재 → fmkorea 퍼온 글 드롭 (2026-07-25 오염 사례 재현 차단)
    now = datetime.now(timezone.utc)
    url = "https://www.bbc.com/sport/football/articles/x1"
    raw = [RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                   raw_payload={"title": "한국어 퍼온 제목", "body": "퍼온 본문"})]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4}}
    seen = {url: ("h_en", 1, "bbc_sport", True)}
    arts, stats = to_articles(raw, sources, seen=seen)
    assert arts == []
    assert stats["blocked_count"] == 1

def test_cross_run_stub_upgraded_by_complete_item():
    # 온스테인 스텁 → fmkorea 전문 도착 시 같은 행 승격 (rev+1 · 새 소스 귀속)
    now = datetime.now(timezone.utc)
    url = "https://www.nytimes.com/athletic/12345/"
    raw = [RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                   raw_payload={"title": "전문 제목", "body": "전문 본문"})]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4}}
    seen = {url: ("h_tweet", 1, "x_ornstein", False)}
    arts, stats = to_articles(raw, sources, seen=seen)
    assert len(arts) == 1
    assert arts[0].revision == 2
    assert arts[0].source_id == "fmkorea"
    assert stats["blocked_count"] == 0

def test_cross_run_stub_not_replaced_by_stub():
    now = datetime.now(timezone.utc)
    url = "https://www.nytimes.com/athletic/12345/"
    raw = [RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                   raw_payload={"title": "헤드라인만"})]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4}}
    seen = {url: ("h_tweet", 1, "x_ornstein", False)}
    arts, stats = to_articles(raw, sources, seen=seen)
    assert arts == []
    assert stats["blocked_count"] == 1

def test_in_batch_complete_en_beats_complete_fmkorea():
    # 같은 배치: 정렬로 EN 이 먼저 완전체 선점 → fmkorea blocked
    # (기존엔 한국어 제목 hash 불일치 = "changed" 로 두 행 모두 실려 뒤가 앞을 덮었다)
    now = datetime.now(timezone.utc)
    url = "https://www.bbc.com/sport/football/articles/x2"
    raw = [
        RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "한국어 퍼온 제목", "body": "퍼온 본문"}),
        RawItem(source_id="bbc_sport", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "Arsenal sign X", "body": "full body"}),
    ]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4},
               "bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, stats = to_articles(raw, sources, seen={})
    assert len(arts) == 1
    assert arts[0].source_id == "bbc_sport"
    assert stats["blocked_count"] == 1

def test_same_source_revision_still_allowed():
    # 같은 소스의 제목 수정 재수집은 가드 무관하게 통과 (revision 원 목적 보존)
    now = datetime.now(timezone.utc)
    url = "https://www.bbc.com/sport/football/articles/x3"
    raw = [RawItem(source_id="bbc_sport", source_type="html", url=url, fetched_at=now,
                   raw_payload={"title": "Arsenal sign X (updated)", "body": "full"})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    seen = {url: ("h_old", 1, "bbc_sport", True)}
    arts, stats = to_articles(raw, sources, seen=seen)
    assert len(arts) == 1
    assert arts[0].revision == 2
    assert stats["blocked_count"] == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: FAIL (classify 옛 호출 TypeError · blocked_count 키 부재).

- [ ] **Step 3: 구현** — `src/bullet_in/pipeline.py` 수정

시그니처 (`pipeline.py:49-51`):

```python
def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int, str, bool]],
                registry: "Registry | None" = None) -> tuple[list[Article], dict]:
```

카운터 초기화부 (`pipeline.py:54` 근처) 에 추가:

```python
    blocked_count = 0
```

classify 호출부 (`pipeline.py:74-80`) 교체:

```python
        url = canonical_url(item.url)
        h = content_hash(title, url)
        has_body = bool(item.raw_payload.get("body"))
        decision, rev = classify(url, h, local_seen, item.source_id, has_body)
        if decision == "duplicate":
            dup_count += 1
            continue
        if decision == "blocked":
            blocked_count += 1     # 완전체 보호 · 스텁끼리 충돌 (spec §4)
            continue
        local_seen[url] = (h, rev, item.source_id, has_body)
```

반환 stats (`pipeline.py:97-98`) 에 키 추가:

```python
    return out, {"dup_count": dup_count, "source_counts": source_counts,
                 "women_count": women_count, "author_drop_count": author_drop_count,
                 "blocked_count": blocked_count}
```

`src/bullet_in/run.py:75-77` 로그 교체:

```python
    logging.getLogger(__name__).info(
        "drop 집계 — 중복 %d · URL 보호 %d · 여자팀 %d · 기자 allowlist %d",
        stats["dup_count"], stats["blocked_count"], stats["women_count"],
        stats["author_drop_count"])
```

- [ ] **Step 4: 통과 확인 (전체 회귀)**

Run: `uv run pytest -q`
Expected: 전부 passed (통합 포함 · DB 기동 상태).

- [ ] **Step 5: 커밋**

```bash
git add tests/test_pipeline.py src/bullet_in/pipeline.py src/bullet_in/run.py
git commit -m "feat(collect): to_articles 에 완전체 보호 가드 배선 · blocked 집계"
```

### Task 4: refetch_urls 단건 재수집 CLI

**Files:**
- Create: `src/bullet_in/refetch_urls.py`
- Test: `tests/test_refetch_urls.py`

**Interfaces:**
- Consumes: `collect_fmkorea.persist(raw, mart) -> tuple[int, int]` (mongo 적재 + to_articles + upsert — 소스 무관 범용) · `adapters.meta` 추출 함수들.
- Produces: `build_item(source_id, url, html, body_selector, now) -> RawItem | None` · CLI `python -m bullet_in.refetch_urls --source-id S --url U [--url U2 ...] [--dry-run]`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_refetch_urls.py` 생성

```python
from datetime import datetime, timezone
from bullet_in.refetch_urls import build_item

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)

HTML = """<html><head>
<meta property="og:title" content="Arsenal complete Tzolis signing">
<meta property="og:image" content="https://img.test/t.jpg">
</head><body><article>Full body text here.</article></body></html>"""

def test_build_item_shapes_payload_like_html_adapter():
    # 정기 수집 (html 어댑터 상세 경로) 과 동형 payload — 가드의 same-source 갱신 경로로 통과
    it = build_item("bbc_sport", "https://www.bbc.com/sport/x", HTML, "article", NOW)
    assert it.source_type == "html"
    assert it.raw_payload["title"] == "Arsenal complete Tzolis signing"
    assert it.raw_payload["body"] == "Full body text here."
    assert it.raw_payload["image_url"] == "https://img.test/t.jpg"
    assert it.raw_payload["authors"] == []

def test_build_item_returns_none_without_title():
    # 제목 추출 실패 시 덮어쓰지 않는다 — 불완전 복원 방지
    assert build_item("bbc_sport", "https://x.test/a", "<html></html>", "article", NOW) is None

def test_build_item_without_body_selector_keeps_empty_body():
    it = build_item("bbc_sport", "https://x.test/a", HTML, None, NOW)
    assert it.raw_payload["body"] == ""
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_refetch_urls.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: 구현** — `src/bullet_in/refetch_urls.py` 생성

```python
"""오염 · 누락 행의 단건 URL 재수집 (멱등).

같은 소스의 재수집은 URL 정합 가드의 "changed" 경로로 통과한다 — cross-source 오염 행을
원문 값 (제목 · 기자 · 본문) 으로 복원하고 번역을 리셋해 다음 enrich 회차가 수렴한다.
첫 사용처는 BBC 오염 3행 복구 (spec 2026-07-26 §7).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.refetch_urls --source-id bbc_sport --url https://... --dry-run
    uv run python -m bullet_in.refetch_urls --source-id bbc_sport --url https://... --url https://...
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine

from bullet_in.adapters.meta import (extract_authors, extract_body_images,
                                     extract_og_image, extract_og_title,
                                     extract_published_at)
from bullet_in.collect_fmkorea import persist
from bullet_in.models import RawItem
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5   # backfill_journalist 와 같은 기준 (라이브 사이트 부담 회피)


def build_item(source_id: str, url: str, html: str,
               body_selector: str | None, now: datetime) -> RawItem | None:
    """기사 HTML → 정기 수집 (html 어댑터 상세 경로) 과 동형인 RawItem.
    제목 추출 실패 시 None — 불완전한 값으로 기존 행을 덮지 않는다."""
    title = extract_og_title(html)
    if not title:
        return None
    payload: dict = {"title": title}
    el = (BeautifulSoup(html, "html.parser").select_one(body_selector)
          if body_selector else None)
    payload["body"] = el.get_text(" ", strip=True) if el else ""
    payload["image_url"] = extract_og_image(html)
    payload["images"] = extract_body_images(html, body_selector, base_url=url)
    payload["authors"] = extract_authors(html)
    pub = extract_published_at(html)
    if pub:
        payload["published"] = pub[0].isoformat()
        payload["published_precision"] = pub[1]
    return RawItem(source_id=source_id, source_type="html", url=url,
                   fetched_at=now, raw_payload=payload)


async def refetch(source_id: str, urls: list[str], dry_run: bool = False) -> tuple[int, int]:
    sources = load_sources("config/sources.yaml")
    if source_id not in sources:
        raise SystemExit(f"미등록 소스: {source_id}")
    body_selector = sources[source_id].get("config", {}).get("body_selector")
    now = datetime.now(timezone.utc)
    items: list[RawItem] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as c:
        for i, url in enumerate(urls):
            try:
                r = await c.get(url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("fetch 실패 %s: %r", url, e)
                continue
            item = build_item(source_id, url, r.text, body_selector, now)
            if item is None:
                log.warning("제목 추출 실패 — 스킵 %s", url)
                continue
            items.append(item)
            if i < len(urls) - 1:
                await asyncio.sleep(REQUEST_GAP_SEC)
    if dry_run:
        for it in items:
            log.info("[dry-run] %s → title=%r body=%d자 authors=%s", it.url,
                     it.raw_payload["title"], len(it.raw_payload["body"]),
                     it.raw_payload["authors"])
        return len(items), 0
    mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
    mart.ensure_schema()
    return persist(items, mart)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="단건 URL 재수집 (멱등)")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--url", action="append", required=True, help="반복 지정 가능")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 추출 결과만 로깅")
    args = ap.parse_args()
    n, dup = asyncio.run(refetch(args.source_id, args.url, dry_run=args.dry_run))
    print(f"적재 {n} · 중복 {dup}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_refetch_urls.py -q && uv run pytest -q`
Expected: 전부 passed.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_refetch_urls.py src/bullet_in/refetch_urls.py
git commit -m "feat(collect): 단건 URL 재수집 CLI — 오염 행 원문 복원 경로"
```

### Task 5: PR-1 생성 (컨트롤러 직접)

- [ ] **Step 1: 전체 회귀 최종 확인** — `uv run pytest -q` (통합 포함).
- [ ] **Step 2: push** — `git push -u origin feat/url-integrity-guard`.
- [ ] **Step 3: PR 본문 작성** — 7섹션 한국어 · `--body-file` · Claude 서명 금지 · pull_request_template.md 주석 세칙 대조.
- [ ] **Step 4: humanize-korean (fast) 문체 점검 1회** — 서식 규칙 (§2.2) · 명사형 불릿 · 수치 · 경로는 변경 금지 목록으로 명시.
- [ ] **Step 5: `gh pr create`** 후 사용자에게 머지 요청 · UI 세션에 한 줄 공유 문구 준비.

---

## PR-2: 온스테인 카드 리졸브 (PR-1 머지 후 착수)

### Task 6: 카드 캡처 · parse_self_tweets 패스스루

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py:9-26` (_TWEET_JS) · `x_playwright.py:193-213` (parse_self_tweets)
- Test: `tests/test_x_playwright.py`

**사전 단계 (컨트롤러):** PR-1 머지 확인 후 `git fetch origin && git checkout -b feat/ornstein-card-resolve origin/main`.

**Interfaces:**
- Produces: `_TWEET_JS` 반환 dict 에 `card_href` 키 (카드 없으면 빈 문자열).
`parse_self_tweets` 산출 RawItem 의 `raw_payload["card_href"]` = 카드 href 또는 None.
- Consumes: 기존 `_rt` 테스트 픽스처 (card_href 미지정 시 `.get` 으로 안전).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_x_playwright.py` 에 추가

```python
def test_self_source_passes_card_href():
    rts = [_rt(text="Exclusive #AFC", status_id="41", card_href="https://t.co/abc")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["card_href"] == "https://t.co/abc"

def test_self_source_card_absent_is_none():
    rts = [_rt(text="News #AFC", status_id="42")]
    it = parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)[0]
    assert it.raw_payload["card_href"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: 신규 2케이스 FAIL (KeyError: 'card_href').

- [ ] **Step 3: 구현**

`_TWEET_JS` 교체 (card 2줄 · card_href 1줄 추가 — `_JOURN_JS` 의 기존 패턴 재사용):

```python
_TWEET_JS = """
els => els.map(a => {
  const t = a.querySelector('[data-testid="tweetText"]');
  const time = a.querySelector('time');
  const link = a.querySelector('a[href*="/status/"]');
  const img = a.querySelector('[data-testid="tweetPhoto"] img');
  const card = a.querySelector('[data-testid="card.wrapper"]');
  const ca = card ? card.querySelector('a[href]') : null;
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  const am = href ? href.match(/^\\/([A-Za-z0-9_]+)\\/status\\//) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    author: am ? am[1] : '',
    image_url: img ? img.src : null,
    card_href: ca ? ca.getAttribute('href') : ''
  };
})
"""
```

`parse_self_tweets` 의 RawItem raw_payload 에 1키 추가:

```python
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": "@" + handle,
                         "image_url": t.get("image_url"),
                         "card_href": t.get("card_href") or None}))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: 전부 passed (afcstuff 경로 회귀 포함 — 해당 파서는 card_href 를 무시).

- [ ] **Step 5: 커밋**

```bash
git add tests/test_x_playwright.py src/bullet_in/adapters/x_playwright.py
git commit -m "feat(adapters): 온스테인 트윗의 카드 링크 캡처 (card_href)"
```

### Task 7: 카드 리졸브 — 트윗 키를 원문 기사 URL 로

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py` (`resolve_card_urls` 신규 함수 + `fetch()` 배선)
- Test: `tests/test_x_playwright.py`

**Interfaces:**
- Consumes: Task 6 의 `raw_payload["card_href"]` · `x_backtrack.resolve_and_fetch(client, url)` (t.co 리다이렉트 추적 — 본문은 버림).
- Produces: `async resolve_card_urls(items: list[RawItem], log) -> list[RawItem]` — 리졸브 성공 시 `item.url` 을 기사 URL 로 교체 + `raw_payload["tweet_url"]` 에 원 트윗 URL 보존.
`fetch()` 가 `self_source` 일 때 파싱 직후 호출.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_x_playwright.py` 에 추가

```python
import asyncio
import logging as _logging
from bullet_in.adapters import x_playwright


def _self_items(card):
    rts = [_rt(text="News #AFC", status_id="51", card_href=card)]
    return x_playwright.parse_self_tweets("x_ornstein", "David_Ornstein", rts, NOW)

def _fake_resolver(final_url):
    async def fake(client, url):
        return (final_url, "ignored body", None, None, [])
    return fake

def test_resolve_card_rewrites_url_and_keeps_tweet_url(monkeypatch):
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver("https://www.nytimes.com/athletic/12345/"))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://www.nytimes.com/athletic/12345/"
    assert out[0].raw_payload["tweet_url"] == "https://x.com/David_Ornstein/status/51"

def test_resolve_card_failure_keeps_tweet_url(monkeypatch):
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver(None))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"
    assert "tweet_url" not in out[0].raw_payload

def test_resolve_card_tweet_domain_falls_back(monkeypatch):
    # 카드가 다른 트윗 (인용) 을 가리키면 기사 아님 — 현행 트윗 URL 유지 (spec §6)
    monkeypatch.setattr("bullet_in.adapters.x_backtrack.resolve_and_fetch",
                        _fake_resolver("https://x.com/other/status/99"))
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items("https://t.co/abc"), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"

def test_resolve_card_no_targets_skips_network():
    # card 없는 배치는 클라이언트 생성 전에 반환 — 외부 접촉 0회
    out = asyncio.run(x_playwright.resolve_card_urls(
        _self_items(""), _logging.getLogger("t")))
    assert out[0].url == "https://x.com/David_Ornstein/status/51"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_x_playwright.py -q`
Expected: 신규 4케이스 FAIL (resolve_card_urls 부재).

- [ ] **Step 3: 구현** — `x_playwright.py` 에 추가 (모듈 하단 · parse_self_tweets 뒤)

```python
def _is_tweet_host(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return (host in ("x.com", "twitter.com", "t.co")
            or host.endswith(".x.com") or host.endswith(".twitter.com"))


async def resolve_card_urls(items, log) -> list:
    """card_href 있는 트윗의 키를 원문 기사 URL 로 교체 (spec 2026-07-26 §6).
    같은 기사의 fmkorea 전문 도착 시 dedup upgrade 로 한 행에 합류하기 위한 선행 조건.
    리졸브 실패 · 트윗 도메인 카드 (인용 트윗) 는 현행 트윗 URL 폴백 — 본문은 저장하지 않는다."""
    import httpx
    from bullet_in.adapters import x_backtrack
    targets = [it for it in items if it.raw_payload.get("card_href")]
    if not targets:
        return items
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"}) as c:
        for it in targets:
            final_url, _body, _title, _image, _images = await x_backtrack.resolve_and_fetch(
                c, it.raw_payload["card_href"])
            if not final_url:
                log.info("card 리졸브 실패 — 트윗 URL 유지 %s", it.url)
                continue
            if _is_tweet_host(final_url):
                log.info("card 가 트윗 링크 — 트윗 URL 유지 %s", final_url)
                continue
            it.raw_payload["tweet_url"] = it.url
            it.url = final_url
    return items
```

`fetch()` 배선 (`x_playwright.py:129-133` — browser.close 와 bt 승격 사이):

```python
            await browser.close()
        if self.self_source:
            items = await resolve_card_urls(items, log)
        if bt:
```

- [ ] **Step 4: 통과 확인 (전체 회귀)**

Run: `uv run pytest -q`
Expected: 전부 passed.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_x_playwright.py src/bullet_in/adapters/x_playwright.py
git commit -m "feat(adapters): 온스테인 트윗 키를 카드 원문 URL 로 리졸브"
```

### Task 8: PR-2 생성 (컨트롤러 직접)

- [ ] **Step 1: 전체 회귀 최종 확인** — `uv run pytest -q`.
- [ ] **Step 2: push + PR** — Task 5 와 같은 절차 (7섹션 · humanize fast · 서명 금지).
- [ ] **Step 3:** 사용자에게 머지 요청.

---

## 운영 반영 (양 PR 머지 후 · 컨트롤러 + 사용자)

### Task 9: VM 반영 · BBC 3행 복구 · 수렴 · 검증

접촉 규율: 모든 라이브 명령은 `2>&1 | tee /tmp/<이름>.log` — 출력 확인 목적 재실행 금지.
원격 실행 예방책 3종 적용 (docs/troubleshooting/2026-07-26-remote-render-silent-pitfalls.md):
`export PATH="$HOME/.local/bin:$PATH"` 서두 고정 · 산출물 grep 게이트를 배포 앞에 · `docker exec -i` 는 heredoc 한정.

- [ ] **Step 1: VM 최신화** — `git pull` 로 main 반영 확인 (`git log --oneline -3`).
- [ ] **Step 2: 복구 dry-run** (VM · env source 후):

```bash
uv run python -m bullet_in.refetch_urls --source-id bbc_sport \
  --url "https://www.bbc.com/sport/football/articles/c77yg781lr8o" \
  --url "https://www.bbc.com/sport/football/articles/cvge7wen5g9o" \
  --url "https://www.bbc.com/sport/football/articles/c235lr80ekko" \
  --dry-run 2>&1 | tee /tmp/refetch-dry.log
```

기대: 3건 모두 영문 제목 · body 길이 > 0 · authors 로깅.
- [ ] **Step 3: 실제 복구** — 같은 명령에서 `--dry-run` 제거 · tee 파일명 변경.
기대: `적재 3 · 중복 0`.
- [ ] **Step 4: DB 확인** — 3행의 title_original 영문 복원 · revision 3 · title_ko NULL (재번역 큐 진입).
- [ ] **Step 5: enrich 수렴** — enrich-only 패스 (docs/runbook/2026-07-19-enrich-only-pass.md §4 · SERVING_SELECT_SQL import 규칙).
- [ ] **Step 6: 재렌더 · 배포** — grep 게이트 (3행 중 1건의 영문 제목 존재 확인) 통과 시에만 deploy-site.sh.
- [ ] **Step 7: 온스테인 전환기 정리 (필수 — 최종 리뷰 Important 1)** — 기존 x_ornstein 행은 트윗 URL 이 키다.
카드가 붙은 트윗이 다시 수집되면 키가 기사 URL 로 바뀌어 **새 행**이 생기고, 옛 행은 어떤 경로로도 갱신 · 삭제되지 않는다 (content_hash 가 URL 을 포함해 dedup 도 안 걸린다).
서빙 SELECT 가 전량을 읽으므로 같은 내용 카드 2장이 나란히 노출된다.

```sql
SELECT url, title_original, source_id, fetched_at FROM articles
WHERE source_id='x_ornstein' ORDER BY title_original, fetched_at;
```

같은 `title_original` 이 x.com 키와 기사 URL 키 양쪽에 있으면 **x.com 키 행만** 삭제한다 (사용자 확인 후 · 삭제는 임의 실행 금지).
카드 없는 트윗 행은 키가 안 바뀌므로 건드리지 않는다 (번역 4필드 재소모).
정리 후 재렌더.
- [ ] **Step 8: 검증 기준 확인 (최종 리뷰 Important 2)** — 이 회차의 성공 기준은 **"카드 있는 트윗의 url 이 기사 URL 로 저장됐는가"** 다.
fmkorea 와 한 행으로 합류하는지는 이번 검증 대상이 아니다
— fmkorea 는 퍼온 글에 붙어 있던 URL 을 그대로 저장하고 (`theathletic.com/...`) 온스테인은 리다이렉트 종점을 저장해 (`nytimes.com/athletic/...`) 키가 어긋날 수 있고, 현재 fmkorea 페이월 경로는 body 를 저장하지 않아 판정이 upgrade 가 아니라 blocked 다.
합류 확인은 E안 (금지 글 body 수집) 트랙 이후로 이월한다.
- [ ] **Step 9: 라이브 관찰 항목** (조치 없이 기록만 · 최종 리뷰 Minor)
  - 같은 회차에 같은 기사를 가리키는 트윗이 2건이면 뒤엣것이 앞엣것을 `changed` 로 덮어 트윗 하나가 조용히 사라진다.
  - 인용 트윗에 붙은 카드가 바깥 트윗의 카드로 잡히면 엉뚱한 기사 URL 이 키가 된다 (`querySelector` 가 article 하위 전체를 훑는 구조).
  - 카드가 이미 본문 보유 행이 있는 기사를 가리켜 blocked 되면 x_ornstein 워터마크가 갱신되지 않아 24h 신선도 알림이 오탐할 수 있다.
- [ ] **Step 10:** UI 세션에 머지 사실 한 줄 공유 · 메모리 갱신 (트랙 종료 스냅샷).

---

## Self-Review 결과 (작성 시 수행)

- spec §4 매트릭스 6분기 → Task 1 테스트 6개 1:1 대응.
spec §5 구현 지점 4곳 → Task 1–3.
spec §6 → Task 6–7 (폴백 · 접촉 예산 · tweet_url 보존 포함).
spec §7 → Task 4 + Task 9.
spec §8 테스트 목록 → 각 태스크 Step 1 에 배치.
spec §9 순서 → PR-1/PR-2 분리 · Task 5 · 8.
- 기존 테스트 파손 2건 (test_dedup 시그니처 · test_pipeline EN 우선 케이스) 은 Task 1 · 3 에서 명시적으로 갱신.
`tests/integration/test_mariadb_store.py:73` 의 seen_map 단언도 Task 2 에서 갱신.
- 타입 일관성: seen 4-튜플 `(hash, rev, source_id, has_body)` 가 Task 1 (classify) · 2 (seen_map) · 3 (local_seen) 에서 동형.
