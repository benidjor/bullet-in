# 발행일 복구 구현 계획

> **구현자에게**: 이 계획은 `superpowers:subagent-driven-development` 로 태스크 단위 실행한다.
> 단계는 체크박스 (`- [ ]`) 로 표시돼 있다.

**목표**: 발행일이 수집 시각으로 대체된 102건을 원문 발행일로 되돌리는 1회성 모듈을 만든다.

**설계**: `docs/superpowers/specs/2026-08-04-published-date-recovery-design.md`.
결정은 전부 그 문서에 있다 — 다시 열지 말고 계획대로 만든다.

**접근**: 기존 백필 모듈 (`backfill_journalist.py`) 과 같은 뼈대를 쓴다.
URL 을 다시 받아 `extract_published_at()` 만 돌리고 `published_at` · `published_precision` 두 칸만 갱신한다.

**스택**: Python 3.11 · httpx · SQLAlchemy · pytest.

## 전역 제약

- **`published_at` · `published_precision` 외의 컬럼을 쓰지 않는다.**
번역 4필드 · 본문 · 저자 · 이미지 · 분류 필드를 건드리면 안 된다.
- 추출에 실패하면 그 행을 건드리지 않는다.
- 추출값이 `fetched_at + 1시간` 을 넘으면 버린다.
- 요청 간격은 1.5초 (`REQUEST_GAP_SEC` 관례).
- `--dry-run` 은 DB 에 아무것도 쓰지 않는다.
- 트윗 소스 (`adapter == "x_playwright"`) 는 대상에서 제외한다.
- 요청 범위 밖 기능 · 추상화 · 설정 옵션을 만들지 않는다 (YAGNI).
- 인접 코드 · 주석 · 포맷을 "개선" 하지 않는다.
- 주석 · 문서는 한국어 · 컨벤션 §2.2 서식.
- 커밋 메시지는 `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러.

## 작업 위치 · git 규율 (필독)

- 워크트리 절대 경로
— `/Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date`
- 브랜치
— `fix/published-date-recovery` (base `f7ac946`)
- **모든 git 명령에 `-C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date` 를 붙인다.**
- 매 태스크 시작 시 `git -C <워크트리> rev-parse --abbrev-ref HEAD` 로 브랜치를 자기검증한다.
- **`git reset` 을 실행하지 마라.**
- **`git rebase` 를 실행하지 마라.**
- **`git checkout <다른 브랜치>` 를 실행하지 마라.**
- **`git push` 를 실행하지 마라.**
- **`gh pr` 명령을 실행하지 마라.**

## 파일 구조

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/backfill_published_at.py` | 대상 선정 · 재수집 · 발행일 갱신 | 신설 |
| `tests/test_backfill_published_at.py` | 판정 순수 함수 · 대상 SQL 계약 | 신설 |

---

### Task 1: 발행일 판정 함수와 대상 선정

**파일**
- 생성: `src/bullet_in/backfill_published_at.py`
- 테스트: `tests/test_backfill_published_at.py`

**인터페이스**
- 제공: `decide(html: str, fetched_at: datetime) -> tuple[datetime, str] | None`
— 저장할 (발행일, 정밀도). 추출 실패나 미래값이면 `None` 이고 그 행은 건드리지 않는다.
- 제공: `target_source_ids(sources: dict) -> list[str]`
— 재수집 대상 소스 목록. 트윗 어댑터를 뺀 나머지다.
- 제공: `_SELECT_SQL` — 대상 행 조회 SQL.

**왜 순수 함수로 떼는가**
판정 규칙 (추출 실패 · 미래값 가드) 은 네트워크 없이 검증할 수 있어야 한다.
`backfill_journalist.journalist_update()` 가 같은 방식으로 떨어져 있다.

- [ ] **1단계: 실패하는 테스트를 쓴다**

`tests/test_backfill_published_at.py` 를 새로 만든다.

```python
"""발행일 복구 — 판정 규칙과 대상 선정."""
from datetime import datetime
from bullet_in.backfill_published_at import decide, target_source_ids

_FETCHED = datetime(2026, 7, 18, 21, 56, 51)


def _ld(iso: str) -> str:
    return ('<html><head><script type="application/ld+json">'
            f'{{"@type":"NewsArticle","datePublished":"{iso}"}}'
            '</script></head><body></body></html>')


def test_extracted_date_is_adopted():
    got = decide(_ld("2026-07-14T14:11:47.899Z"), _FETCHED)
    assert got is not None
    assert got[0] == datetime(2026, 7, 14, 14, 11, 47, 899000)
    assert got[1] == "time"


def test_no_date_in_html_is_skipped():
    # 추출 실패는 무변경 — 기존 값을 더 나쁜 값으로 덮지 않는다.
    assert decide("<html><head></head><body>no date</body></html>", _FETCHED) is None


def test_future_date_is_rejected():
    # 수집 시각 + 1시간을 넘는 값은 오파싱으로 본다 (pipeline._published 와 같은 가드).
    assert decide(_ld("2026-07-19T09:00:00Z"), _FETCHED) is None


def test_date_just_inside_the_guard_is_accepted():
    got = decide(_ld("2026-07-18T22:30:00Z"), _FETCHED)
    assert got is not None
    assert got[0] == datetime(2026, 7, 18, 22, 30)


def test_target_sources_exclude_tweets():
    sources = {"bbc_sport": {"adapter": "html"},
               "fmkorea": {"adapter": "fmkorea"},
               "x_afcstuff": {"adapter": "x_playwright"},
               "x_ornstein": {"adapter": "x_playwright"}}
    assert target_source_ids(sources) == ["bbc_sport", "fmkorea"]
```

- [ ] **2단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date
uv run pytest tests/test_backfill_published_at.py -q
```
기대: `ModuleNotFoundError: No module named 'bullet_in.backfill_published_at'` 로 전건 실패.

- [ ] **3단계: 모듈의 판정 부분을 구현한다**

`src/bullet_in/backfill_published_at.py` 를 새로 만든다.

```python
"""발행일이 수집 시각으로 대체된 행 복구 (1회성 · 멱등).

수집 당시 발행일 추출에 실패하면 pipeline._published() 가 수집 시각을 넣는다.
추출기 자체는 지금 정상이라 URL 을 다시 받아 발행일만 다시 읽으면 복구된다.
번역 · 본문 · 저자는 건드리지 않는다 — 재번역 과금을 피하려는 설계다 (스펙 §4.1).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_published_at --dry-run
    uv run python -m bullet_in.backfill_published_at --source-id fmkorea
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timedelta
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_published_at
from bullet_in.score import load_sources

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 다른 백필들과 같은 기준 (라이브 사이트 부담 회피)
NEAR_FETCH_SEC = 300       # 발행일이 수집 시각의 5분 이내면 대체값으로 본다 (스펙 §3.1)


def decide(html: str, fetched_at: datetime) -> tuple[datetime, str] | None:
    """저장할 (발행일, 정밀도). 정할 수 없으면 None — 그 행은 건드리지 않는다.

    미래값 가드는 pipeline._published() 와 같은 기준이다 — 수집 시각보다 한 시간
    넘게 뒤인 발행일은 오파싱으로 본다.
    """
    got = extract_published_at(html)
    if not got:
        return None
    dt = got[0].replace(tzinfo=None)
    if dt > fetched_at + timedelta(hours=1):
        return None
    return dt, got[1]


def target_source_ids(sources: dict) -> list[str]:
    """재수집 대상 소스 — 트윗은 뺀다.

    트윗에는 JSON-LD 가 없고 날짜가 created_at 에서 오므로 재수집할 것이 없다.
    """
    return [sid for sid, s in sources.items()
            if s.get("adapter") != "x_playwright"]


_SELECT_SQL = text(
    "SELECT content_hash, url, source_id, published_at, fetched_at FROM articles "
    "WHERE published_precision IS NULL "
    f"AND ABS(TIMESTAMPDIFF(SECOND, published_at, fetched_at)) < {NEAR_FETCH_SEC} "
    "AND source_id IN :sids ORDER BY source_id, published_at"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수

_UPDATE_SQL = text(
    "UPDATE articles SET published_at=:p, published_precision=:pr "
    "WHERE content_hash=:h")
```

- [ ] **4단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date
uv run pytest tests/test_backfill_published_at.py -q
```
기대: 5 passed.

- [ ] **5단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date add src/bullet_in/backfill_published_at.py tests/test_backfill_published_at.py
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date commit -F - <<'MSG'
feat(backfill): 발행일 복구 판정 규칙 · 대상 선정

수집 당시 발행일을 못 읽으면 수집 시각이 대신 저장되는데, 추출기는 지금 정상이라 다시 받아 읽으면 복구된다.
네트워크 없이 검증할 수 있도록 판정 규칙을 순수 함수로 떼어 낸다.

- 판정: 추출 실패 시 무변경 · 수집 시각 한 시간 초과 발행일은 오파싱으로 폐기
- 대상 선정: 트윗 어댑터 제외 (JSON-LD 가 없고 날짜가 created_at 에서 옴)
- 조회 조건: 정밀도가 비어 있고 발행일이 수집 시각 5분 이내인 행
- 테스트: 판정 4건 · 대상 선정 1건

Refs: #219
MSG
```

---

### Task 2: 재수집 실행 · CLI

**파일**
- 수정: `src/bullet_in/backfill_published_at.py`
- 테스트: `tests/test_backfill_published_at.py`

**인터페이스**
- 사용: Task 1 의 `decide()` · `target_source_ids()` · `_SELECT_SQL` · `_UPDATE_SQL`.
- 제공: `async backfill(source_id: str | None, limit: int | None, dry_run: bool) -> dict[str, dict]`
— 소스별 `{"ok": int, "skip": int, "fail": int}`.
- 제공: `main()` — `--source-id` · `--limit` · `--dry-run`.

**소스를 나눠 돌릴 수 있어야 한다**
스펙 §4.4 가 언론사 81건과 fmkorea 21건을 따로 돌리라고 정했다.
`--source-id` 가 그 분리를 담당한다.

- [ ] **1단계: 실패하는 테스트를 쓴다**

`tests/test_backfill_published_at.py` 끝에 붙인다.

```python
def test_cli_accepts_source_and_dry_run_flags():
    # 스펙 §4.4 — 언론사와 fmkorea 를 따로 돌리려면 소스 지정이 필요하다.
    import bullet_in.backfill_published_at as m
    ap = m._parser()
    args = ap.parse_args(["--source-id", "fmkorea", "--dry-run", "--limit", "5"])
    assert args.source_id == "fmkorea"
    assert args.dry_run is True
    assert args.limit == 5


def test_cli_defaults_are_all_sources_and_write_mode():
    import bullet_in.backfill_published_at as m
    args = m._parser().parse_args([])
    assert args.source_id is None
    assert args.dry_run is False
    assert args.limit is None
```

- [ ] **2단계: 테스트가 실패하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date
uv run pytest tests/test_backfill_published_at.py -q -k cli
```
기대: `AttributeError: module 'bullet_in.backfill_published_at' has no attribute '_parser'` 로 실패.

- [ ] **3단계: 실행부와 CLI 를 구현한다**

`src/bullet_in/backfill_published_at.py` 끝에 이어 붙인다.

```python
async def backfill(source_id: str | None = None, limit: int | None = None,
                   dry_run: bool = False) -> dict[str, dict]:
    sources = load_sources("config/sources.yaml")
    sids = [source_id] if source_id else target_source_ids(sources)
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": sids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("대상 %d건 (소스 %s)", len(rows), ", ".join(sids))
    stats: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            sid = row["source_id"]
            st = stats.setdefault(sid, {"ok": 0, "skip": 0, "fail": 0})
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    st["fail"] += 1              # 404 · 차단 · 타임아웃 → 무변경
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                got = decide(r.text, row["fetched_at"])
                if got is None:
                    st["skip"] += 1
                    log.info("발행일 못 읽음 · 무변경 %s", row["url"])
                    continue
                log.info("%s %s → %s (%s)", sid, row["published_at"], got[0], got[1])
                if not dry_run:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"p": got[0], "pr": got[1],
                                                "h": row["content_hash"]})
                st["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="발행일 복구 (멱등)")
    ap.add_argument("--source-id", default=None, help="한 소스만 대상 (스펙 §4.4 분리 실행)")
    ap.add_argument("--limit", type=int, default=None, help="대상 상한")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    return ap


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args()
    stats = asyncio.run(backfill(source_id=args.source_id, limit=args.limit,
                                 dry_run=args.dry_run))
    for sid, s in sorted(stats.items()):
        print(f"{sid}: 복구 {s['ok']} · 무변경 {s['skip']} · 실패 {s['fail']}")


if __name__ == "__main__":
    main()
```

- [ ] **4단계: 테스트가 통과하는 것을 확인한다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date
uv run pytest tests/test_backfill_published_at.py -q
```
기대: 7 passed.

- [ ] **5단계: 전체 테스트를 돌린다**

실행:
```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date
uv run pytest -q
```
기대: 실패 0건.

- [ ] **6단계: 커밋한다**

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date rev-parse --abbrev-ref HEAD
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date add src/bullet_in/backfill_published_at.py tests/test_backfill_published_at.py
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/fix-published-date commit -F - <<'MSG'
feat(backfill): 발행일 복구 실행부 · 소스 분리 CLI

접촉이 막힌 이력이 있는 소스를 따로 돌릴 수 있어야 해서 소스 지정을 넣는다.
갱신 대상은 발행일 두 칸뿐이고 번역 · 본문 · 저자는 읽지도 쓰지도 않는다.

- 실행: 요청 간격 1.5초 · 소스별 복구 · 무변경 · 실패 집계
- 분리 실행: --source-id 로 언론사와 fmkorea 를 나눠 돌림
- 무변경 처리: fetch 실패와 발행일 미검출을 구분해 집계
- 테스트: CLI 기본값 · 인자 파싱 2건

Refs: #219
MSG
```

---

## 실행 · 검증 (머지 후 · 세션이 직접 수행)

태스크가 아니라 사람이 순서대로 밟는 절차다.

1. 사용자가 PR 을 직접 머지한다.
2. VM 에서 `git pull` 한다.
3. **전체 dry-run** 으로 실제 손상 규모를 먼저 본다.
`bbc_gossip` 45건은 수집일과 발행일이 원래 같을 수 있어 이 확인이 특히 필요하다.

```bash
uv run python -m bullet_in.backfill_published_at --dry-run 2>&1 | tee -a ~/bullet-in/logs_published_at.txt
```

확인 항목 두 가지를 덧붙인다.
- **날짜가 크게 튄 행을 눈으로 걸러낼 것**
— 삭제된 기사 URL 이 섹션 목록이나 언론사 홈으로 넘어가면 무관한 기사의 날짜가 채택될 수 있다.
dry-run 이 옛 값 → 새 값을 한 줄씩 찍으므로 사람이 볼 수 있다.
- **출력에 `bbc_gossip` · `fmkorea` · `goal` · `skysports` · `bbc_sport` 외의 소스가 찍히는지 볼 것**
— 코드에는 5개 소스 화이트리스트가 없고 배제는 5분 조건에만 달려 있다.

4. **1차 · 언론사** 를 소스별로 돌린다 (`bbc_gossip` · `goal` · `skysports` · `bbc_sport`).
5. **2차 · fmkorea** 는 따로 돌린다.
fmkorea 행의 URL 은 원문 언론사 주소라 이 실행은 fmkorea.com 에 접촉하지 않는다.
그 원문들은 수집 당시 이미 접속이 막혔던 쪽이라 실패가 다수 나오는 것이 정상이다.
실패를 버그로 읽지 말 것.
6. 검증한다
— 트윗 제외 `published_precision IS NULL` 건수 감소 · BBC 트로사르 기사가 `2026-07-14` 로 바뀜.
7. 런북 §4 스니펫으로 재렌더하고 배포한다.
8. 라이브에서 홈 정렬과 그 기사 날짜를 확인한다.

**잔여 실패 건은 재실행해도 결과가 같으므로 반복 실행하지 말 것**
— 영구 실패 URL 에 같은 외부 요청을 반복하게 된다.

## 자기 점검

- 스펙 §4.2 (두 칸만 갱신) 는 `_UPDATE_SQL` 이 `published_at` · `published_precision` 만 SET 하는 것으로 지켜진다.
- 스펙 §4.3 의 안전 장치 넷이 모두 코드에 있다
— 추출 실패 무변경 (`decide` 가 `None`) · 미래값 가드 (`timedelta(hours=1)`) · 요청 간격 (`REQUEST_GAP_SEC`) · 멱등 (`published_precision IS NULL` 조건).
- 스펙 §4.4 (분리 실행) 는 `--source-id` 가 담당한다.
- 스펙 §3.2 (트윗 제외) 는 `target_source_ids()` 가 담당한다.
- 타입 일관성
— `decide()` 는 `tuple[datetime, str] | None`, `_UPDATE_SQL` 이 그 두 값을 그대로 받는다.
