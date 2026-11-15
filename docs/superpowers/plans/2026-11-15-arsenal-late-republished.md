# Arsenal.com 옛 글 재유입 막기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arsenal.com 이 오래된 글의 수정 시각을 갱신해 우리 수집에 새 글처럼 들어오는 일을 막고, 이미 들어온 35건을 화면에서 뺀다.

**Architecture:** 수집 단계에서는 Arsenal.com 어댑터가 발행일이 30일 넘게 지난 글을 받지 않고 깔때기에 `stale` 수만 남긴다.
서빙 단계에서는 `run.drop_late_official` 이 Arsenal.com 행 중 「발행 뒤 30일 넘게 지나 저장된 행」 을 렌더 입력에서 뺀다 (DB 는 그대로 둔다).
서빙 목록을 만드는 두 곳 (`run.publish` · `confirm_player._render`) 이 같은 함수를 부른다.

**Tech Stack:** Python 3.11 · httpx · respx · pytest

**Spec:** 별도 설계 문서 없음 · 결정은 2026-11-15 세션의 사용자 결정 (아래 「결정」 절) 과 실측이다

## 배경

2026-11-02 00:00 UTC 실행과 11-03 00:02 UTC 실행에서 Arsenal.com 글 29건이 새 행으로 저장되고 번역됐다.
발행일은 2015-09-16 ~ 2026-07-13 이다 (「Every word from Arteta's post-Inter Milan presser」 · 「Vieira - I had to prove everything」 등).
같은 실행에서 수집 범위 판정이 버린 제목도 32건 · 40건이 한꺼번에 생겼다가 함께 사라졌다.
그래서 Arsenal.com 이 옛 글의 사이트맵 `lastmod` 를 한꺼번에 갱신한 것으로 보인다 (추정 · 원인은 확인하지 못했다).

29건은 모두 홈에 실렸다.
그중 4건은 단계가 `official` 로 붙어 「이적 뉴스」 구역에 있다 (마두에케 「콜니 카풀」 영상 · 에제 해트트릭 · 사카 재계약 · 요케레스 20골).
같은 일이 09-03 · 09-23 · 09-28 에도 6건 있었다 (「Bukayo Saka signs new long-term contract」 (2026-02-19 발행) 이 09-03 에 저장 등).

## 결정 (2026-11-15 사용자)

| 항목 | 결정 |
| --- | --- |
| 이미 들어온 옛 글 | 화면에서 뺀다 · 행을 지우지 않고 서빙 규칙으로 (세션 제안 · 사용자 「B + C」) |
| 앞으로 들어올 옛 글 | 수집 단계에서 받지 않는다 |
| 기준 | 발행 뒤 30일 넘게 지나 들어온 글 |
| 대상 소스 | Arsenal.com (`arsenal_official`) 만 |

## 작업 원칙 (Karpathy 4원칙 · CLAUDE.md 「행동 가이드라인」)

구현 · 리뷰 서브에이전트는 CLAUDE.md 의 4원칙을 지킨다.
특히 아래 둘은 이 계획에서 리뷰가 Important 로 다룬다.

- **요청 밖 변경 금지** — 작업의 Files 목록 밖 파일을 고치거나, 리뷰의 Minor 를 근거로 설계에 없는 동작을 더하지 않는다. 넣을 만하면 보고만 하고 사용자가 정한다.
- **근거 없는 단정 금지** — 보고 · 커밋 · 주석의 숫자와 사실은 실행한 명령이나 읽은 파일에 닿아야 한다. 닿지 않으면 「추정」 이라고 쓴다.

## 가정과 확인

| 가정 | 확인 방법 · 결과 |
| --- | --- |
| 30일 기준에 걸리는 정상 글이 없다 | 운영 DB `arsenal_official` 136행 (2026-11-15) · 발행 → 저장 2일 이하 95 · 2 ~ 7일 3 · 7 ~ 30일 3 · 30일 초과 35 · 2 ~ 30일 6건은 7월 첫 적재 · 8월 이적 발표로 모두 정상 · 30일 초과 35건은 모두 옛 글 재유입 |
| 서빙 규칙에 `fetched_at` 을 써도 `created_at` 과 같은 행을 고른다 | 같은 조회에서 30일 초과가 `created_at` 기준 35 · `fetched_at` 기준 35 · 한쪽에만 걸리는 행 0 · `SERVING_SELECT_SQL` 에 `created_at` 이 없어 `fetched_at` 을 쓴다 |
| `fetched_at` 은 다시 저장될 때 갱신된다 | `storage/mariadb.py:115` `fetched_at=VALUES(fetched_at)` · 수집 단계가 30일 넘은 글을 안 받으면 앞으로는 30일 넘어 갱신될 일이 없다 |
| 어댑터는 판정 전에 발행일을 이미 받는다 | `adapters/arsenal_api.py` 의 `GetArticle` 응답 `publicationDate` (예 `2026-07-23T12:10:38.401Z`) · 같은 값이 payload `published` 로 나간다 |
| 수집 창은 48시간이다 | `arsenal_api.WINDOW_HOURS = 48.0` · 창은 `lastmod` 기준이라 발행일이 오래돼도 창에 든다 |
| 백필은 같은 어댑터로 옛 글을 일부러 받는다 | `backfill_arsenal.py:66` `ArsenalApiAdapter("arsenal_official", window_hours=hours)` · 그래서 거르기는 생성자 인자로 켜고 기본은 끈다 |
| 서빙 목록을 만드는 곳이 둘이다 | `run.publish` (`run.py:712`) · `confirm_player._render` (`confirm_player.py:106`) · `_render` 독스트링에 한쪽이 빠져 838행이 907행으로 나온 사례 (2026-08-28) |
| 목록에서 빠진 행의 상세 페이지는 따로 정리된다 | `run.py` publish 주석 「목록에서 빠지면 sweep_orphan_pages 가 상세 페이지도 함께 정리한다」 |
| DB 의 `published_at` · `fetched_at` 은 시간대 없는 UTC 다 | `storage/mariadb.py:234` 주석 「fetched_at (어댑터가 UTC 저장)」 · 운영 조회 값에 시간대 표기 없음 |

## 더 단순한 꼴과 버린 이유

| 더 단순한 꼴 | 버린 이유 |
| --- | --- |
| 35행을 DB 에서 지운다 | 되돌릴 수 없고 운영 데이터 정정 승인이 따로 필요하다 · 서빙 규칙은 DB 를 두고 같은 꼴의 다음 일에도 그대로 작동한다 |
| 수집 단계 거르기만 한다 | 이미 들어온 35건이 화면에 남는다 |
| 서빙 규칙만 한다 | 옛 글이 계속 저장 · 번역돼 Gemini 요금이 나간다 |
| 기준을 「사이트맵 창 48시간」 으로 잡는다 | 7월 첫 적재 · 8월 이적 발표처럼 2 ~ 30일 늦게 들어온 정상 글 6건이 함께 빠진다 |
| 서빙 거르기를 `serving_rows` 안에 넣는다 | `serving_rows` 는 fmkorea 어댑터가 있을 때만 불리고 돌려주는 값이 셋 (남길 행 · 무관 수 · 옛 글 수) 이라 기존 시험이 그 꼴로 풀어 쓴다 · 따로 부르는 편이 바뀌는 곳이 적다 |
| 모든 소스에 같은 규칙을 건다 | 사용자 결정은 Arsenal.com 만이다 · 다른 소스의 늦은 저장 (fmkorea 옛 글 등) 은 이미 다른 규칙 (`FMKOREA_SERVING_SINCE`) 이 있다 |

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv venv --python 3.11 --project .` 뒤 `uv run --project . --extra dev pytest`)
- 전체 테스트 기준 = 1,961 통과 · 89 skip (DB 없이 · `061b90f` · 2026-11-15)
- 기준 상수 = `arsenal_api.REPUBLISHED_MAX_AGE_DAYS = 30` · 「30일 초과」 만 뺀다 (정확히 30일은 남긴다)
- 깔때기 키 = `stale` (거른 글 수 · 0이면 키를 만들지 않는다) · 거른 글은 `dropped` · `passed_by` · `men_news_rejects` 에 넣지 않는다
- 발행일이 없거나 형식이 깨진 글은 거르지 않는다 (지금 동작 그대로)
- 시험에서 Arsenal.com 에 접속하지 않는다 (`respx` 모킹)

## Review Focus

- **발행일 없음 · 형식 깨짐** — 수집 · 서빙 모두 거르지 않고 지금처럼 둔다 (Task 1 · Task 2 시험)
- **정확히 30일** — 남긴다 · 30일 1초부터 뺀다 (Task 1 · Task 2 시험)
- **백필** — `max_age_days` 를 안 주면 10년 전 글도 받는다 (Task 1 시험)
- **다른 소스의 늦게 저장된 행** — 이 규칙이 건드리지 않는다 (Task 2 시험)
- **fmkorea 어댑터가 없을 때** — `serving_rows` 를 안 불러도 Arsenal.com 옛 글은 빠진다 (Task 2 · 호출 자리를 `if fm is not None:` 밖에 둔다)

## 알고 두는 한계 (고치지 않음)

- **원인은 모른다** — Arsenal.com 이 왜 `lastmod` 를 한꺼번에 바꿨는지 확인하지 못했다 · 같은 일이 다시 생기면 깔때기 `stale` 수로 보인다
- **단계가 잘못 붙은 4건의 분류 오류 자체는 남는다** — 화면에서 빠질 뿐 `transfer_stage = official` 은 그대로다 (분류 개선은 안건 3ε)
- **번역 요금은 이미 나갔다** — 35건의 번역은 되돌릴 수 없다

---

### Task 1: 수집 단계에서 옛 글 거르기

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py` (상수 · 생성자 인자 · `fetch` 의 `GetArticle` 응답 직후)
- Modify: `src/bullet_in/adapters/factory.py` (`arsenal_api` 갈래에서 `max_age_days=REPUBLISHED_MAX_AGE_DAYS` 전달)
- Test: `tests/test_arsenal_api_adapter.py`

**Interfaces:**
- Produces: `REPUBLISHED_MAX_AGE_DAYS: int = 30` (`bullet_in.adapters.arsenal_api`) · `ArsenalApiAdapter(source_id, window_hours=WINDOW_HOURS, scope=None, max_age_days: float | None = None)` · 깔때기 `funnel["stale"]: int`

- [ ] **Step 1: 실패하는 시험을 쓴다** (파일 끝에 추가 · 기존 `_sitemap` · `_sitemap_entry` · `_gql_article` · `_mock_backend` 를 쓴다)

```python
from datetime import timedelta
from bullet_in.adapters.arsenal_api import REPUBLISHED_MAX_AGE_DAYS

def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def _late_backend(published_by_gid):
    entries = [_sitemap_entry(f"post-{g}", lastmod=_iso(datetime.now(timezone.utc)))
               for g in published_by_gid]
    return _mock_backend(_sitemap(entries), {
        g: _gql_article(f"Title {g}", ["Men", "News", "Transfer news"], published=p)
        for g, p in published_by_gid.items()})

@respx.mock
def test_max_age_drops_old_publication_and_counts_stale():
    now = datetime.now(timezone.utc)
    _late_backend({"aNEW00000001": _iso(now - timedelta(days=2)),
                   "aOLD00000001": _iso(now - timedelta(days=400))})
    a = ArsenalApiAdapter("arsenal_official", max_age_days=REPUBLISHED_MAX_AGE_DAYS)
    items = asyncio.run(a.fetch())
    assert [i.url.rsplit("-", 1)[1] for i in items] == ["aNEW00000001"]
    assert a.funnel["stale"] == 1
    assert a.men_news_rejects == []
    assert "dropped" not in a.funnel

@respx.mock
def test_max_age_keeps_just_inside_thirty_days():
    now = datetime.now(timezone.utc)
    _late_backend({"aEDGE0000001": _iso(now - timedelta(days=30) + timedelta(minutes=5))})
    a = ArsenalApiAdapter("arsenal_official", max_age_days=30)
    assert len(asyncio.run(a.fetch())) == 1
    assert "stale" not in a.funnel

@respx.mock
def test_max_age_keeps_missing_or_broken_publication_date():
    _late_backend({"aNONE0000001": None, "aBAD00000001": "not-a-date"})
    a = ArsenalApiAdapter("arsenal_official", max_age_days=30)
    assert len(asyncio.run(a.fetch())) == 2
    assert "stale" not in a.funnel

@respx.mock
def test_without_max_age_backfill_still_takes_old_articles():
    now = datetime.now(timezone.utc)
    _late_backend({"aOLD00000002": _iso(now - timedelta(days=3650))})
    a = ArsenalApiAdapter("arsenal_official")
    assert len(asyncio.run(a.fetch())) == 1

def test_factory_turns_max_age_on_for_arsenal_official():
    from bullet_in.adapters.factory import build_adapters
    cfg = {"sources": [{"source_id": "arsenal_official", "adapter": "arsenal_api",
                        "config": {"title_scope": True}}]}
    [a] = build_adapters(cfg)
    assert a.max_age_days == REPUBLISHED_MAX_AGE_DAYS == 30
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py -q -k "max_age or factory_turns"`
Expected: FAIL (`ImportError: cannot import name 'REPUBLISHED_MAX_AGE_DAYS'`)

- [ ] **Step 3: 구현한다**

- `arsenal_api.py` 에 `REPUBLISHED_MAX_AGE_DAYS = 30` 을 두고, 왜 있는지 (2026-11-02 · 11-03 옛 글 29건 재유입 · `lastmod` 일괄 갱신 추정) 주석 두세 줄을 단다.
- 생성자에 `max_age_days: float | None = None` 을 더하고 `self.max_age_days` 로 둔다.
- `fetch` 에서 `if not art: ... continue` 바로 뒤 (Men 계수 · `_accept` · `record` 보다 앞) 에, `max_age_days` 가 있고 `publicationDate` 를 `datetime.fromisoformat(s.replace("Z", "+00:00"))` 로 읽을 수 있고 그 값이 `now - timedelta(days=max_age_days)` 보다 앞이면 `self.funnel["stale"] = self.funnel.get("stale", 0) + 1` 하고 `continue` 한다.
- 읽지 못하면 (`None` · `ValueError` · `TypeError`) 거르지 않는다.
- 마지막 `log.info` 줄에 거른 수가 있으면 `" · 옛 글 %d"` 꼴로 붙인다.
- `factory.py` 의 `arsenal_api` 갈래에 `max_age_days=REPUBLISHED_MAX_AGE_DAYS` 를 넘긴다 (import 추가).

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py tests/test_backfill_arsenal.py -q`
Expected: 모두 PASS

- [ ] **Step 5: 커밋한다**

```bash
git -C . add src/bullet_in/adapters/arsenal_api.py src/bullet_in/adapters/factory.py tests/test_arsenal_api_adapter.py
git -C . commit -m "<type>(collect): …"   # 컨벤션 §1 · 본문 · Refs · 트레일러
```

### Task 2: 서빙 단계에서 늦게 들어온 옛 글 빼기

**Files:**
- Modify: `src/bullet_in/run.py` (`serving_rows` 근처에 함수 추가 · `publish` 의 서빙 목록 만드는 자리)
- Modify: `src/bullet_in/confirm_player.py` (`_render` 의 같은 자리)
- Test: `tests/test_serving_late_official.py` (새 파일)

**Interfaces:**
- Consumes: `REPUBLISHED_MAX_AGE_DAYS` (Task 1)
- Produces: `drop_late_official(rows: list[dict], max_age_days: float = REPUBLISHED_MAX_AGE_DAYS) -> tuple[list[dict], int]` (`bullet_in.run` · 남길 행 · 뺀 수)

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
from datetime import datetime, timedelta
from bullet_in.run import drop_late_official

T = datetime(2026, 11, 3, 0, 2, 9)

def _r(sid, pub, fetched=T, h="h"):
    return {"source_id": sid, "published_at": pub, "fetched_at": fetched, "content_hash": h}

def test_drops_official_rows_stored_long_after_publication():
    rows = [_r("arsenal_official", datetime(2015, 9, 16, 7), h="old"),
            _r("arsenal_official", T - timedelta(hours=3), h="new")]
    keep, n = drop_late_official(rows)
    assert [r["content_hash"] for r in keep] == ["new"] and n == 1

def test_exactly_thirty_days_is_kept():
    keep, n = drop_late_official([_r("arsenal_official", T - timedelta(days=30))])
    assert len(keep) == 1 and n == 0
    keep, n = drop_late_official([_r("arsenal_official", T - timedelta(days=30, seconds=1))])
    assert keep == [] and n == 1

def test_other_sources_are_untouched():
    rows = [_r("fmkorea", datetime(2022, 10, 1)), _r("guardian", datetime(2025, 1, 1))]
    keep, n = drop_late_official(rows)
    assert len(keep) == 2 and n == 0

def test_missing_dates_are_kept():
    rows = [_r("arsenal_official", None), _r("arsenal_official", T, fetched=None)]
    keep, n = drop_late_official(rows)
    assert len(keep) == 2 and n == 0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project . --extra dev pytest tests/test_serving_late_official.py -q`
Expected: FAIL (`ImportError: cannot import name 'drop_late_official'`)

- [ ] **Step 3: 구현한다**

- `run.py` 의 `serving_rows` 바로 앞에 `drop_late_official` 을 둔다 · 조건은 `source_id == "arsenal_official"` 이고 두 시각이 모두 있고 `fetched_at - published_at > timedelta(days=max_age_days)` · 독스트링에 「DB 는 두고 렌더 입력만 거른다 · 수집 단계 거르기 (Task 1) 가 생기기 전에 들어온 행 몫」 을 적는다.
- `publish` 에서 `rows = [...SERVING_SELECT_SQL...]` 바로 뒤, `if fm is not None:` **밖**에서 부른다 · 뺀 수가 있으면 `log.info("Arsenal.com 늦게 들어온 옛 글 서빙 제외 %d건 (발행 %d일 초과 뒤 저장)", n, REPUBLISHED_MAX_AGE_DAYS)`.
- `confirm_player._render` 도 같은 자리 (`rows` 를 읽은 직후 · `if fm is not None:` 밖) 에서 부르고, 기존 `log.info("서빙 제외 — …")` 와 별도로 한 줄 남긴다.

- [ ] **Step 4: 통과와 전체 시험을 확인한다**

Run: `uv run --project . --extra dev pytest -q`
Expected: 1,970 통과 · 89 skip (기준 1,961 + 새 시험 9)

- [ ] **Step 5: 운영 DB 로 효과를 잰다 (읽기만)**

VM 에서 이 브랜치 코드를 쓰지 않고, 같은 조건을 SQL 로 세어 35건인지 본다 (2026-11-15 측정값).

```bash
ssh … 'docker exec bullet-in-mariadb-1 mariadb -uroot -pbulletin bulletin -e "SELECT COUNT(*) FROM articles WHERE source_id=\"arsenal_official\" AND TIMESTAMPDIFF(SECOND,published_at,fetched_at) > 30*86400"'
```

Expected: 35 (그 사이 새로 들어온 옛 글이 있으면 그만큼 많다 · 그 행을 읽고 보고한다)

- [ ] **Step 6: 커밋한다**

```bash
git -C . add src/bullet_in/run.py src/bullet_in/confirm_player.py tests/test_serving_late_official.py
git -C . commit -m "<type>(serve): …"   # 컨벤션 §1 · 본문 · Refs · 트레일러
```

### Task 3: 배포 확인 (머지 뒤 · 세션이 한다)

**Files:**
- 바꾸는 파일 없음 · 확인 대상 `site/index.html` (배포본) · `pipeline_runs.fetch_detail` (`funnels.arsenal_official.stale`)

- [ ] **Step 1: 머지 뒤 첫 실행이 새 커밋을 내려받았는지 본다** — VM `git log --oneline -1` · judge 「반영 완료」
- [ ] **Step 2: 배포본 홈에서 35건이 빠졌는지 센다** — `curl -sSL -A "Mozilla/5.0"` 로 받은 `index.html` 에 29 + 6 해시가 0
- [ ] **Step 3: 렌더 로그에 「Arsenal.com 늦게 들어온 옛 글 서빙 제외 35건」 이 있는지 본다**
