# 링크 선수 명단 DB 구현 계획 (players · article_players)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** name_map.yaml 을 MariaDB `players` · `article_players` 로 옮기고, enrich 자동 발굴 + 사람 확정 CLI + 기존 기사 백필까지 스펙 전 범위를 PR 5개로 구현한다.

**Architecture:** 스키마 · 저장소 (PR 1) → 소비처 3곳 로더 전환과 YAML 폐지 (PR 2) → enrich 추출 · 후보 등재 · 알림 (PR 3) → 확정 CLI 의 즉각 소급 수정 (PR 4) → 기존 기사 백필 CLI (PR 5) 순서로, 앞 PR 이 머지된 뒤 다음 PR 을 분기한다.

**Tech Stack:** Python 3.11 · SQLAlchemy (MariaDB) · google-genai · pytest (단위 + `tests/integration` MariaDB 픽스처).

**SoT:** `docs/superpowers/specs/2026-07-31-player-roster-db-design.md` (PR #170 머지본).

## Global Constraints

- 스키마 DDL 은 스펙 §3 을 그대로 옮긴다 — enum 성 컬럼은 VARCHAR + 코드 검증 (기존 articles.transfer_stage 관례).
- 게이트 · 서빙 사전 술어는 `status IN ('confirmed','archived') AND ko_name IS NOT NULL` 이다 (스펙 §3.2 후보 배제 + §8 archived 포함).
- ko_candidate 는 게이트에 절대 공급하지 않는다 (스펙 §3.2 순환 차단).
- 두 단어 surname 은 확정 CLI 가 경고만 한다 — 가드 자체의 두 단어 성 지원은 범위 밖 (스펙 §3.3).
- name_map.yaml 삭제와 참조 제거는 마이그레이션 완료 후 같은 트랙 (PR 2) 에서 한다 (스펙 §5).
- Gemini 429 는 그 회차 즉시 중단 · WARNING 로깅, per-row 백오프 없음 (CLAUDE.md).
- 백필 약 500건 호출은 과금 (Tier 1 선불) — 코드 머지와 별개로, 실행은 사용자 확인 후 VM 에서만 한다.
- 로컬 구현 · 테스트만 한다 — 외부 사이트 접촉 금지, VM 접속은 각 PR 머지 후 반영 단계에서만.
- 커밋은 `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + 실제 작업 모델 트레일러 (컨벤션 §1.1 · §1.3).
- PR 머지는 사용자가 한다 — 세션은 push + PR 생성까지.
- 명단 실측은 39명이다 (스쿼드 · 감독 21 + 이적 실명 18) — 스펙 §7 의 "40명" 은 계수 착오로 확인됐고, 테스트 상수는 39 를 쓴다.
- transfer_status 에 3개 값을 추가한다 (2026-07-31 사용자 확정 · A안): `other_club` (타 클럽 이적 성사 · 배지 "타 클럽행"), `loan_in` (임대 합류 성사 · "임대 영입"), `loan_out` (임대 이탈 성사 · "임대 이적").
  link_dropped 는 성사 없는 링크 소멸 · 잔류로 좁아지고, 링크 단계 (in_link · out_link) 는 완전 · 임대 공용이다 (보도 단계엔 형태 유동 · 워치리스트 소비와 무관).
  임대 선수의 category 는 squad 유지 (임대 영입 = 스쿼드 합류 · 임대 이탈 = 아스날 계약 존속).
  스펙 §3.1 · §6 개정을 PR 1 에 포함한다 (DDL 은 VARCHAR 라 무변경).

---

## 파일 구조

| 파일 | 책임 | PR |
|---|---|---|
| `src/bullet_in/storage/schema.sql` | players · article_players DDL 추가 | 1 |
| `src/bullet_in/storage/players.py` | 신규 — PlayerStore (사전 조회 · seed · 후보 등재 · 링크 · 확정) | 1 · 3 · 4 |
| `src/bullet_in/roster_seed.py` | 신규 — 확정 분류표 39명 상수 (마이그레이션 · 테스트 스텁 원천) | 1 |
| `src/bullet_in/migrate_roster.py` | 신규 — 이관 CLI (멱등) | 1 |
| `src/bullet_in/run.py` | 게이트 사전 DB 전환 · 추출 쌍 저장 · 후보 알림 연결 | 2 · 3 |
| `src/bullet_in/serve/render.py` | `load_player_names` DB 전환 | 2 |
| `src/bullet_in/enrich.py` | 프롬프트 players 필드 · `_extract_full` 확장 · 추출 전용 프롬프트 | 3 · 5 |
| `src/bullet_in/roster.py` | 신규 — 추출 쌍 정규화 · 매칭 · 등재 (`record_article_players`) | 3 |
| `src/bullet_in/notify.py` | `build_candidate_alert` 추가 | 3 |
| `src/bullet_in/storage/mariadb.py` | `rows_for_hashes` · `clear_translation` 추가 · 번역 대상 SELECT 에 url | 3 · 4 |
| `src/bullet_in/confirm_player.py` | 신규 — 확정 CLI (승격 → 재검사 → 재번역 → 재렌더) | 4 |
| `src/bullet_in/backfill_article_players.py` | 신규 — 백필 CLI (1회성 · state 파일) | 5 |
| `tests/conftest.py` | 신규 — 서빙 사전 스텁 (단위 테스트 DB 비의존) | 2 |
| `tests/integration/conftest.py` | clean 픽스처에 새 테이블 추가 | 1 |
| `config/name_map.yaml` | 삭제 | 2 |

## PR 분할과 순서

1. **PR 1 — `feat(storage)`: 선수 명단 스키마 · 이관** (Task 1~3): 머지 후 VM 에서 `migrate_roster` 실행까지가 한 묶음.
2. **PR 2 — `feat(pipeline)`: 사전 로더 DB 전환 · name_map 폐지** (Task 4~6): 머지 전 PR 1 의 VM 이관이 선행돼야 한다 (사전이 비면 게이트가 조용히 꺼짐 — Task 4 가 경고 로그로 방어).
3. **PR 3 — `feat(enrich)`: 추출 쌍 저장 · 후보 등재 · 알림** (Task 7~11): 머지 + VM 반영 후 첫 회차에서 article_players 적재 · 알림 발송 확인.
4. **PR 4 — `feat(enrich)`: 확정 CLI** (Task 12~14): 머지 + VM 반영 후 실제 후보 1건으로 종단 확인.
5. **PR 5 — `feat(enrich)`: article_players 백필 · 운영 런북** (Task 15~17): 실행은 과금 확인 후.

각 PR 은 `origin/main` 에서 분기하고, 다음 PR 은 앞 PR 머지 후 분기한다 (순차 단일 트랙).

## 확정 분류표 (사용자 확정본을 Task 2 에 반영)

category · transfer_status 는 사람 확정 항목이다 (스펙 §7).
아래 제안표를 사용자에게 제시해 확정받은 값이 `roster_seed.py` 에 들어간다.
근거 열의 실측은 로컬 DB (최신 기사 2026-07-19 · VM 대비 구본) 기준이라, 그 이후 상태 변화는 사용자 확정으로 보정한다.
제안표 자체는 계획 승인 대화에 첨부한다 — 이 문서에는 결정 규칙만 남긴다.

- 스펙 §3.1 명시분: 마두에케 · 에제 · 요케레스 = squad · in_done.
- 로컬 실측 확인분: 멜리에 · 인카피에 · 촐리스 = squad · in_done, 트로사르 · 키비오르 = external · out_done.
- 타 클럽 이적 성사 (신설 other_club): 로저스 (첼시 · 7-18 실측) · 앤더슨 (맨시티 · 사용자 확인).
- 언급 보호용 (아스날 링크 아님): 오바메양 · 음바페 · 벨링엄 = external · none.
- 펠레그리니 = external · none — 이적 링크가 아니라 환각 실사례 (#76 · id 365 원문에 없는 인명 생성) 검출용 등재라 명단 유지가 필수다.
- 카비아 (Ismeal Kabia) · 비에이라 (Fabio Vieira) = squad · out_link 제안 — 게이트 오탐 차단 (#110) 으로 등재된 아스날 임대 선수 (처분 검토 보도 6-11) · 임대 지속 중이면 squad · loan_out.
- 나머지 진행형 링크는 external · in_link 를 기본 제안으로 하고 ❓ 표시로 사용자 판단을 받는다.

---

### Task 1: 스키마 — players · article_players DDL

**Files:**
- Modify: `src/bullet_in/storage/schema.sql` (파일 끝에 추가)
- Modify: `tests/integration/conftest.py:24-29` (clean 픽스처)
- Test: `tests/integration/test_player_store.py` (신규)

**Interfaces:**
- Consumes: `MartStore.ensure_schema()` 의 멱등 적용 관례 (`;` 분리 실행).
- Produces: `players` · `article_players` 테이블 — 이후 모든 Task 의 저장 대상.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/integration/test_player_store.py
from sqlalchemy import text


def test_ensure_schema_creates_player_tables(engine):
    # engine 픽스처가 schema.sql 을 적용하므로 테이블 존재 = DDL 반영 증거
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM players")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM article_players")).scalar_one() == 0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_player_store.py -v`
Expected: FAIL — `Table 'bulletin_test.players' doesn't exist`
(MariaDB 미가동이면 skip 되므로 `docker compose up -d` 선행.)

- [ ] **Step 3: DDL 추가 — 스펙 §3 그대로**

`schema.sql` 끝에 추가한다.

```sql
CREATE TABLE IF NOT EXISTS players (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(100) NOT NULL UNIQUE,
  first_name VARCHAR(50),
  surname VARCHAR(50) NOT NULL,
  ko_name VARCHAR(50),
  ko_candidate VARCHAR(50),
  club VARCHAR(50),
  category VARCHAR(16) NOT NULL,
  status VARCHAR(16) NOT NULL,
  transfer_status VARCHAR(16) NOT NULL,
  origin VARCHAR(16) NOT NULL,
  first_seen CHAR(64),
  added_at DATETIME NOT NULL,
  confirmed_at DATETIME,
  archived_at DATETIME);
CREATE TABLE IF NOT EXISTS article_players (
  content_hash CHAR(64) NOT NULL,
  player_id INT NOT NULL,
  stage VARCHAR(32),
  extracted_at DATETIME NOT NULL,
  PRIMARY KEY (content_hash, player_id));
```

컬럼 의미 주석은 스펙 §3 이 SoT 라 DDL 에는 옮기지 않는다 (기존 articles DDL 도 무주석).

- [ ] **Step 4: clean 픽스처에 새 테이블 추가**

`tests/integration/conftest.py` 의 `clean` 픽스처 DELETE 목록에 두 줄 추가 (자식 먼저).

```python
        c.execute(text("DELETE FROM article_players"))
        c.execute(text("DELETE FROM players"))
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/integration/test_player_store.py -v`
Expected: PASS

- [ ] **Step 6: 스펙 개정 — other_club 값 추가**

`docs/superpowers/specs/2026-07-31-player-roster-db-design.md` 를 고친다 (2026-07-31 사용자 지시 반영).

- §3 DDL 주석의 transfer_status 값 나열에 `other_club` · `loan_in` · `loan_out` 추가.
- §3.1 표의 "타 클럽행 · 링크 소멸" 행을 두 행으로 분리: 타 클럽 이적 성사 = `other_club` (배지 "타 클럽행"), 성사 없는 링크 소멸 = `link_dropped` (배지 "링크 소멸").
- §3.1 에 임대 행 추가: 임대 합류 성사 = squad · `loan_in` (배지 "임대 영입"), 임대 이탈 성사 = squad · `loan_out` (배지 "임대 이적") — 링크 단계는 완전 · 임대 공용 (in_link · out_link), category 는 두 경우 모두 squad.
- §6 의 "타 클럽행 · 링크 소멸" 항목도 같은 기준으로 분리 (둘 다 status → archived 는 동일).
- §6 에 임대 생애주기 추가: 임대 → 완전 전환 = `loan_in` → `in_done`, 임대 복귀 = `loan_out` → `none` (스쿼드 복귀) 또는 `out_link` (처분 재검토).
- §7 의 "40명" 을 "39명" 으로 정정 (name_map 실측 · 계수 착오).

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/storage/schema.sql tests/integration/ docs/superpowers/specs/
git commit  # feat(storage): players · article_players 테이블 추가 · 스펙 개정 (other_club · 39명)
```

### Task 2: roster_seed 상수 · PlayerStore 사전 조회

**Files:**
- Create: `src/bullet_in/roster_seed.py`
- Create: `src/bullet_in/storage/players.py`
- Test: `tests/test_roster_seed.py` (신규 · 단위)
- Test: `tests/integration/test_player_store.py` (추가)

**Interfaces:**
- Consumes: Task 1 의 테이블.
- Produces: `ROSTER: list[dict]` (키 full_name · first_name · surname · ko_name · club · category · transfer_status), `PlayerStore(engine)` 의 `seed(rows) -> int` · `gate_name_map() -> dict[str, str]` · `serving_names() -> list[str]`.

- [ ] **Step 1: 실패하는 단위 테스트 작성**

```python
# tests/test_roster_seed.py
from bullet_in.roster_seed import ROSTER

VALID_CATEGORY = {"squad", "manager", "external"}
VALID_TRANSFER = {"none", "in_link", "in_done", "out_link", "out_done",
                  "link_dropped", "other_club", "loan_in", "loan_out"}


def test_roster_shape_and_uniqueness():
    assert len(ROSTER) == 39                     # name_map 실측 (스펙 "40" 은 계수 착오)
    assert len({r["full_name"] for r in ROSTER}) == 39
    assert len({r["ko_name"] for r in ROSTER}) == 39


def test_roster_surnames_single_word():
    # 풀네임 근거 가드의 단일 단어 성 전제 (스펙 §3.3)
    assert all(" " not in r["surname"] for r in ROSTER)


def test_roster_enum_values():
    assert all(r["category"] in VALID_CATEGORY for r in ROSTER)
    assert all(r["transfer_status"] in VALID_TRANSFER for r in ROSTER)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_roster_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: bullet_in.roster_seed`

- [ ] **Step 3: roster_seed.py 작성 — 사용자 확정표 반영**

```python
"""링크 선수 명단 이관 상수 — 2026-07-31 사용자 확정 분류 (스펙 §7).

category · transfer_status 는 사람 확정 값이다.
운영 중 변경은 DB 가 SoT 이고, 이 상수는 이관 · 로컬 부트스트랩 · 테스트 스텁용으로만 쓴다.
"""

ROSTER: list[dict] = [
    {"full_name": "Mikel Arteta", "first_name": "Mikel", "surname": "Arteta",
     "ko_name": "아르테타", "club": "Arsenal",
     "category": "manager", "transfer_status": "none"},
    # … 확정표의 39명 전부를 같은 형태로 나열 (계획 승인 대화의 확정본이 원천) …
]
```

주의: 39개 전 항목을 실제 값으로 나열한다 — 확정 전 구현 착수 금지.

- [ ] **Step 4: PlayerStore 사전 조회 실패 테스트 작성**

```python
# tests/integration/test_player_store.py 에 추가
import yaml
from pathlib import Path
from bullet_in.roster_seed import ROSTER
from bullet_in.storage.players import PlayerStore


def test_seed_is_idempotent(engine):
    store = PlayerStore(engine)
    assert store.seed(ROSTER) == len(ROSTER)
    assert store.seed(ROSTER) == 0          # 재실행 시 신규 0 (INSERT IGNORE)


def test_gate_name_map_equals_yaml_name_map(engine):
    # 로더 동등성 (스펙 §9): 마이그레이션 결과 dict = 기존 YAML dict
    store = PlayerStore(engine)
    store.seed(ROSTER)
    expected = yaml.safe_load(Path("config/name_map.yaml").read_text())["names"]
    assert store.gate_name_map() == expected


def test_gate_name_map_excludes_candidate_and_blank_ko(engine):
    from sqlalchemy import text
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_candidate,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "('New Guy','Guy','뉴가이','external','candidate','in_link','extracted',NOW())"))
        c.execute(text("UPDATE players SET status='archived' WHERE full_name='Leandro Trossard'"))
    m = store.gate_name_map()
    assert "뉴가이" not in m                  # 후보 미공급 (스펙 §3.2)
    assert m.get("트로사르") == "Trossard"    # archived 잔류 (스펙 §6 · §8)


def test_serving_names_matches_gate_keys(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    assert set(store.serving_names()) == set(store.gate_name_map())
```

- [ ] **Step 5: 실패 확인**

Run: `uv run pytest tests/integration/test_player_store.py -v`
Expected: FAIL — `ModuleNotFoundError: bullet_in.storage.players`

- [ ] **Step 6: PlayerStore 구현**

```python
# src/bullet_in/storage/players.py
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.engine import Engine

# 게이트 · 서빙 사전 술어 — 후보 (자동 등재) 배제 + archived 잔류 (스펙 §3.2 · §8)
_DICT_WHERE = "status IN ('confirmed','archived') AND ko_name IS NOT NULL"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlayerStore:
    """players · article_players 저장소 — 인명 사전의 단일 원천 (스펙 §5)."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def seed(self, rows: list[dict]) -> int:
        """큐레이션 명단 멱등 이관 — full_name UNIQUE 로 기존 행은 건드리지 않는다."""
        now = _utcnow()
        params = [{**r, "now": now} for r in rows]
        with self.engine.begin() as c:
            res = c.execute(text(
                "INSERT IGNORE INTO players (full_name,first_name,surname,ko_name,"
                "club,category,status,transfer_status,origin,added_at,confirmed_at) "
                "VALUES (:full_name,:first_name,:surname,:ko_name,:club,:category,"
                "'confirmed',:transfer_status,'curated',:now,:now)"), params)
        return res.rowcount

    def gate_name_map(self) -> dict[str, str]:
        """게이트 검출 사전 {ko_name: surname} — ko_candidate 는 공급하지 않는다."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                f"SELECT ko_name, surname FROM players WHERE {_DICT_WHERE}")).all()
        return {ko: sn for ko, sn in rows}

    def serving_names(self) -> list[str]:
        """서빙 사건 사전용 ko_name 목록 (스펙 §8) — 정렬은 서빙 로더 책임."""
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(text(
                f"SELECT ko_name FROM players WHERE {_DICT_WHERE}")).all()]
```

- [ ] **Step 7: 통과 확인**

Run: `uv run pytest tests/test_roster_seed.py tests/integration/test_player_store.py -v`
Expected: PASS 전부

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/roster_seed.py src/bullet_in/storage/players.py tests/
git commit  # feat(storage): 확정 명단 상수 · PlayerStore 사전 조회
```

### Task 3: 이관 CLI — migrate_roster

**Files:**
- Create: `src/bullet_in/migrate_roster.py`
- Test: `tests/integration/test_player_store.py` (Task 2 의 멱등 테스트가 핵심 검증 — CLI 는 얇은 래퍼)

**Interfaces:**
- Consumes: `PlayerStore.seed` · `MartStore.ensure_schema` · `ROSTER`.
- Produces: `python -m bullet_in.migrate_roster` — VM 반영 절차의 실행 명령.

- [ ] **Step 1: CLI 작성**

```python
"""name_map 39명 → players 이관 CLI (멱등 · 스펙 §7).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.migrate_roster
"""
from __future__ import annotations
import logging, os
from sqlalchemy import create_engine
from bullet_in.roster_seed import ROSTER
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore


def main() -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    MartStore(engine).ensure_schema()
    store = PlayerStore(engine)
    inserted = store.seed(ROSTER)
    print(f"이관: 신규 {inserted} / 명단 {len(ROSTER)} · 사전 {len(store.gate_name_map())}명")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
```

- [ ] **Step 2: 로컬 실행으로 검증**

Run: `set -a; source .env; set +a && uv run python -m bullet_in.migrate_roster` 를 2회 실행.
Expected: 1회차 `이관: 신규 39 / 명단 39 · 사전 39명`, 2회차 `신규 0`.

- [ ] **Step 3: 전체 테스트 · 커밋**

Run: `uv run pytest -q` → 전부 PASS 확인.

```bash
git add src/bullet_in/migrate_roster.py
git commit  # feat(storage): 명단 이관 CLI (멱등)
```

- [ ] **Step 4: PR 1 생성**

브랜치 `feat/roster-schema` push → PR 본문 7섹션 · humanize fast 점검 → 생성.
머지 후 반영 절차 (사용자와 함께): VM `git pull` → `migrate_roster` 실행 → 사전 39명 확인.

### Task 4: run.py 게이트 사전 DB 전환

**Files:**
- Modify: `src/bullet_in/run.py:104-105` (YAML 로드 → PlayerStore) · import 추가

**Interfaces:**
- Consumes: `PlayerStore.gate_name_map()`.
- Produces: `finalize_translation` 에 넘기는 `name_map` dict — 게이트 함수 본체는 무수정 (스펙 §5).

- [ ] **Step 1: 교체**

`run.py` 의 name_map YAML 로드 2줄을 다음으로 바꾸고, 파일 상단에 `from bullet_in.storage.players import PlayerStore` 를 추가한다.

```python
    name_map = PlayerStore(engine).gate_name_map()
    if not name_map:
        logging.getLogger(__name__).warning(
            "players 사전이 비어 있음 — migrate_roster 미실행이면 인명 게이트가 꺼진 채 돈다")
```

빈 사전 경고는 첫 배포 함정 (이관 전 회차) 을 조용한 게이트 꺼짐에서 관측 가능한 신호로 바꾼다.

- [ ] **Step 2: 검증 · 커밋**

Run: `uv run pytest -q`
Expected: 전부 PASS (게이트 단위 테스트는 dict 주입이라 영향 없음).

```bash
git add src/bullet_in/run.py
git commit  # feat(pipeline): 게이트 인명 사전을 players 테이블 조회로 전환
```

### Task 5: 서빙 사전 DB 전환 · 단위 테스트 스텁

**Files:**
- Modify: `src/bullet_in/serve/render.py:872-876` (`load_player_names`)
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: `PlayerStore.serving_names()`.
- Produces: `load_player_names(engine=None) -> list[str]` — 반환 형태 (긴 이름 우선 정렬 리스트) 는 기존과 동일, `render_index` 호출부 무수정.

- [ ] **Step 1: 단위 테스트 스텁 먼저 작성**

serve 단위 테스트 (test_serve_render 등) 는 지금 YAML 파일을 직접 읽는다.
DB 전환 후에도 DB 없이 돌도록 autouse 스텁을 둔다 — 스텁 원천은 ROSTER 라 사전 내용이 이중화되지 않는다.

```python
# tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def stub_serving_player_names(monkeypatch):
    """serve 단위 테스트가 DB 없이 돌도록 서빙 사건 사전을 이관 명단으로 대체한다."""
    from bullet_in.roster_seed import ROSTER
    names = sorted((r["ko_name"] for r in ROSTER), key=len, reverse=True)
    monkeypatch.setattr("bullet_in.serve.render.load_player_names",
                        lambda engine=None: names)
```

- [ ] **Step 2: load_player_names 를 DB 조회로 교체**

```python
def load_player_names(engine=None) -> list[str]:
    """서빙 사건 사전 — players 확정 ko_name (DB 단일 원천 · 스펙 §5 · §8).
    긴 이름을 앞에 둬 부분 매치를 막는다 (기존 규칙 유지).
    engine 미지정 시 MARIADB_URL 로 생성한다 — write_site 호출부 (run.py · 런북) 는
    이미 그 env 로 돌므로 시그니처 연쇄 변경 없이 전환된다."""
    from sqlalchemy import create_engine
    from bullet_in.storage.players import PlayerStore
    engine = engine or create_engine(os.environ["MARIADB_URL"])
    return sorted(PlayerStore(engine).serving_names(), key=len, reverse=True)
```

`render.py` 상단에 `import os` 가 없으면 추가한다.

- [ ] **Step 3: 검증 · 커밋**

Run: `uv run pytest -q`
Expected: 전부 PASS — serve 단위 테스트가 스텁 경유로 기존 결과 유지.

```bash
git add src/bullet_in/serve/render.py tests/conftest.py
git commit  # feat(serve): 서빙 사건 사전을 players 테이블 조회로 전환
```

### Task 6: name_map.yaml 삭제 · 참조 제거

**Files:**
- Delete: `config/name_map.yaml`
- Modify: `tests/integration/test_player_store.py` (동등성 테스트의 YAML 참조 → ROSTER 기준)
- Modify: `docs/runbook/2026-07-19-enrich-only-pass.md` §3 (name_map 로드 스니펫)
- Modify: `docs/runbook/2026-07-19-translation-quality-gates-ops.md` · `docs/runbook/2026-07-31-gate-change-offline-measurement.md` (name_map 로드 언급 · 스니펫)

**Interfaces:**
- Consumes: Task 2 의 동등성 테스트가 이미 YAML = DB 를 증명했다.
- Produces: 사전의 단일 원천 = DB (스펙 §5 완결).

- [ ] **Step 1: 동등성 테스트를 ROSTER 기준으로 개정**

```python
def test_gate_name_map_equals_seed_roster(engine):
    # YAML 폐지 후의 회귀 가드 — 술어 (후보 배제) 가 이관분을 깎지 않는지 고정
    store = PlayerStore(engine)
    store.seed(ROSTER)
    assert store.gate_name_map() == {r["ko_name"]: r["surname"] for r in ROSTER}
```

기존 `test_gate_name_map_equals_yaml_name_map` 은 이 테스트로 대체한다.

- [ ] **Step 2: YAML 삭제 · 소스 참조 검색**

```bash
git rm config/name_map.yaml
grep -rn "name_map" src/ tests/ config/ airflow/
```

Expected: 소스 잔존 참조 0 (enrich.py 의 docstring 서술 · 주석은 사전 일반론이라 유지 — 단 `config/name_map.yaml` 경로를 직접 가리키는 주석이 있으면 "players 테이블" 로 바꾼다).
`config/name_map.yaml` 경로 언급이 남는 파일: `enrich.py` 게이트 docstring · `render.py` (Task 5 에서 이미 제거) 를 확인한다.

- [ ] **Step 3: 활성 런북 3건 스니펫 갱신**

`2026-07-19-enrich-only-pass.md` §3 의 `name_map = _cfg("config/name_map.yaml", "names")` 를 다음으로 바꾼다.

```python
from bullet_in.storage.players import PlayerStore
name_map = PlayerStore(create_engine(os.environ["MARIADB_URL"])).gate_name_map()
```

(스니펫 내 engine 재사용이 가능하면 mart 의 engine 을 그대로 쓴다.)
나머지 2건은 name_map.yaml 언급 부분을 "players 테이블 (`PlayerStore.gate_name_map()`)" 로 고친다.
역사 기록물 (specs · plans · troubleshooting) 은 건드리지 않는다.

- [ ] **Step 4: 검증 · 커밋 · PR 2 생성**

Run: `uv run pytest -q` → 전부 PASS.
Run: `grep -rn "name_map.yaml" src/ tests/ docs/runbook/` → 0건.

```bash
git add -A
git commit  # feat(pipeline): name_map.yaml 폐지 — 사전 단일 원천을 DB 로
```

PR 2 본문에 명시: **머지 전 제약 = VM 에 PR 1 이관 (`migrate_roster`) 완료**.

### Task 7: enrich 프롬프트 players 필드 · 파서 확장

**Files:**
- Modify: `src/bullet_in/enrich.py` (TRANSLATE_PROMPT · PARAPHRASE_PROMPT · `_extract_full`)
- Test: `tests/test_enrich.py` (추가)

**Interfaces:**
- Consumes: 기존 enrich 호출 경로 (호출 수 불변 — 스펙 §4.1).
- Produces: `_extract_full` 반환 dict 에 `players: list` 키 (없거나 형식 오류면 `[]`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_enrich.py 에 추가
def test_enrich_returns_players_pairs():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a", "b", "c"],
               "body_ko": "B",
               "players": [{"full_name": "Bruno Guimaraes", "ko": "기마랑이스",
                            "stage": "personal_terms"}]}
    rows = [{"content_hash": "h1", "title_original": "T", "body_source": "Body"}]
    out = enrich_rows(rows, FullClient(payload), "m")
    assert out["h1"]["players"] == payload["players"]


def test_enrich_players_field_defaults_to_empty_list():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a"], "body_ko": "B"}
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": "B"}],
                      FullClient(payload), "m")
    assert out["h"]["players"] == []


def test_translate_prompts_list_player_stages():
    # 단계 값 세트가 프롬프트와 동기 (STAGE_PROMPT 동기 테스트와 같은 취지)
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for prompt in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert '"players"' in prompt
        for stage in ("rumour", "interest", "negotiating", "personal_terms",
                      "medical", "agreed", "other"):
            assert stage in prompt
        assert "official" not in prompt
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -k players -v`
Expected: FAIL 3건.

- [ ] **Step 3: 구현**

두 프롬프트의 `ONLY JSON` 줄 직전에 규칙을 추가하고, `ONLY JSON` 예시에 `"players":[...]` 를 넣는다.

```python
    "- players: 이 기사가 이적 · 거취 · 계약을 다룬 선수 · 감독 목록. 각 항목은 "
    '{{"full_name":"영문 풀네임","ko":"이 기사에서 쓴 한글 표기","stage":"단계"}}.\n'
    "- stage 는 rumour · interest · negotiating · personal_terms · medical · agreed · "
    "other 중 하나. 경기 · 근황만 다뤄진 인물은 other, 기사에 없는 인물은 넣지 않는다.\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],'
    '"body_ko":"...","players":[{{"full_name":"...","ko":"...","stage":"..."}}]}}'
```

`_extract_full` 의 반환에 한 키를 더한다 (players 는 필수 키가 아니다 — 없으면 빈 목록).

```python
        pairs = d.get("players")
        return {"title_ko": d["title_ko"], "summary_ko": d["summary_ko"],
                "summary3_ko": s3, "body_ko": d["body_ko"],
                "players": pairs if isinstance(pairs, list) else []}
```

- [ ] **Step 4: 통과 · 회귀 확인 · 커밋**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: 전부 PASS (기존 4필드 테스트는 키 추가에 영향받지 않는다 — 전체 dict 동등 비교가 있으면 players 키를 기대값에 추가).

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit  # feat(enrich): 번역 프롬프트에 (선수, 단계) 쌍 출력 필드 추가
```

### Task 8: PlayerStore 후보 등재 · 링크 메서드

**Files:**
- Modify: `src/bullet_in/storage/players.py`
- Test: `tests/integration/test_player_store.py` (추가)

**Interfaces:**
- Consumes: Task 1 테이블 · `enrich._fold_latin`.
- Produces: `match_maps() -> tuple[dict, dict]` · `insert_candidate(**kw) -> int` · `link_article(content_hash, player_id, stage, now)` · `articles_for(player_id) -> list[str]`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_insert_candidate_and_match(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pid = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                 surname="Williams", ko_candidate="니코 윌리엄스",
                                 first_seen="h" * 64)
    by_full, by_surname = store.match_maps()
    assert by_full["nico williams"] == pid
    assert by_surname["williams"] == pid


def test_match_maps_drop_ambiguous_surname(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    store.insert_candidate(full_name="Brennan Johnson", first_name="Brennan",
                           surname="Johnson", ko_candidate=None, first_seen=None)
    store.insert_candidate(full_name="Ben Johnson", first_name="Ben",
                           surname="Johnson", ko_candidate=None, first_seen=None)
    _, by_surname = store.match_maps()
    assert "johnson" not in by_surname       # 동성 2명 — 성 단독 매칭은 모호해 제외


def test_link_article_upsert_is_idempotent(engine):
    from sqlalchemy import text
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pid = store.gate_player_id("기마랑이스")
    h = "a" * 64
    store.link_article(h, pid, "interest")
    store.link_article(h, pid, "agreed")     # 재추출 — 단계만 갱신
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT stage FROM article_players WHERE content_hash=:h"), {"h": h}).all()
    assert rows == [("agreed",)]
    assert store.articles_for(pid) == [h]
```

`gate_player_id(ko_name)` 는 테스트 편의 조회다 — 구현에 `SELECT id WHERE ko_name=:ko` 한 줄 메서드로 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_player_store.py -v`
Expected: FAIL — `AttributeError: insert_candidate`

- [ ] **Step 3: 구현**

```python
    def match_maps(self) -> tuple[dict[str, int], dict[str, int]]:
        """(접힌 full_name → id, 접힌 surname → id). 동성 복수 인원은 성 매핑에서 뺀다
        — 성 단독 매칭이 다른 선수에게 기사를 붙이는 것을 막는다."""
        from bullet_in.enrich import _fold_latin
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT id, full_name, surname FROM players")).all()
        by_full = {_fold_latin(fn): pid for pid, fn, _ in rows}
        grouped: dict[str, list[int]] = {}
        for pid, _, sn in rows:
            grouped.setdefault(_fold_latin(sn), []).append(pid)
        by_surname = {sn: pids[0] for sn, pids in grouped.items() if len(pids) == 1}
        return by_full, by_surname

    def insert_candidate(self, *, full_name: str, first_name: str | None,
                         surname: str, ko_candidate: str | None,
                         first_seen: str | None) -> int:
        """자동 발굴 후보 등재 (스펙 §4.1) — 호출 전 match_maps 미매칭이 전제.
        transfer_status 기본값은 in_link — 방향은 사람 확정 시 교정한다."""
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO players (full_name,first_name,surname,ko_candidate,"
                "category,status,transfer_status,origin,first_seen,added_at) "
                "VALUES (:fn,:fi,:sn,:ko,'external','candidate','in_link',"
                "'extracted',:seen,:now)"),
                {"fn": full_name, "fi": first_name, "sn": surname,
                 "ko": ko_candidate, "seen": first_seen, "now": _utcnow()})
            return c.execute(text("SELECT id FROM players WHERE full_name=:fn"),
                             {"fn": full_name}).scalar_one()

    def link_article(self, content_hash: str, player_id: int,
                     stage: str | None) -> None:
        """추출 쌍 저장 — 재추출 시 단계 · 시각만 갱신하는 멱등 upsert."""
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO article_players (content_hash,player_id,stage,extracted_at) "
                "VALUES (:h,:p,:s,:now) ON DUPLICATE KEY UPDATE "
                "stage=VALUES(stage), extracted_at=VALUES(extracted_at)"),
                {"h": content_hash, "p": player_id, "s": stage, "now": _utcnow()})

    def articles_for(self, player_id: int) -> list[str]:
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(text(
                "SELECT content_hash FROM article_players WHERE player_id=:p"),
                {"p": player_id}).all()]

    def gate_player_id(self, ko_name: str) -> int:
        with self.engine.connect() as c:
            return c.execute(text("SELECT id FROM players WHERE ko_name=:ko"),
                             {"ko": ko_name}).scalar_one()
```

(테스트 코드도 `link_article(h, pid, "interest")` 3인자 형태에 맞춘다 — now 는 내부 `_utcnow()`.)

- [ ] **Step 4: 통과 확인 · 커밋**

Run: `uv run pytest tests/integration/test_player_store.py -v` → PASS.

```bash
git add src/bullet_in/storage/players.py tests/integration/test_player_store.py
git commit  # feat(storage): 후보 등재 · 기사 링크 · 매칭 조회
```

### Task 9: roster 모듈 — 정규화 · 매칭 · 등재

**Files:**
- Create: `src/bullet_in/roster.py`
- Test: `tests/test_roster.py` (단위) · `tests/integration/test_player_store.py` (등재 멱등)

**Interfaces:**
- Consumes: `PlayerStore` (Task 8) · `transfer_stage.normalize` · `enrich._fold_latin`.
- Produces: `normalize_pairs(raw) -> list[dict]` · `record_article_players(store, content_hash, pairs) -> list[dict]` (신규 후보 목록 — 알림 입력).

- [ ] **Step 1: 실패하는 단위 테스트 작성**

```python
# tests/test_roster.py
from bullet_in.roster import normalize_pairs


def test_normalize_pairs_validates_and_normalizes():
    raw = [{"full_name": "Bruno Guimaraes", "ko": "기마랑이스", "stage": "personal_terms"},
           {"full_name": "", "ko": "x", "stage": "rumour"},          # 이름 없음 → drop
           {"full_name": "Nico Williams", "stage": "발표"},           # 비enum → other
           {"full_name": "Someone", "ko": "누군가", "stage": "official"},  # 규칙 경로 전용 → agreed
           "잘못된 항목",                                              # dict 아님 → drop
           {"full_name": "bruno guimarães", "ko": "기마랑", "stage": "agreed"}]  # 중복 → drop
    out = normalize_pairs(raw)
    assert [p["full_name"] for p in out] == ["Bruno Guimaraes", "Nico Williams", "Someone"]
    assert out[1]["stage"] == "other"
    assert out[2]["stage"] == "agreed"


def test_normalize_pairs_tolerates_non_list():
    assert normalize_pairs(None) == []
    assert normalize_pairs("아무거나") == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_roster.py -v`
Expected: FAIL — `ModuleNotFoundError: bullet_in.roster`

- [ ] **Step 3: 구현**

```python
# src/bullet_in/roster.py
"""enrich 추출 쌍 → players · article_players 반영 (스펙 §4.1)."""
from __future__ import annotations
import logging
from bullet_in import transfer_stage as _stage
from bullet_in.enrich import _fold_latin
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)


def normalize_pairs(raw) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화 (official 은 규칙 경로 전용이라 agreed 강등 · 분류 패스와 동일)."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = (item.get("full_name") or "").strip()
        if not fn or _fold_latin(fn) in seen:
            continue
        seen.add(_fold_latin(fn))
        stage = _stage.normalize(item.get("stage"))
        if stage == "official":
            stage = "agreed"
        out.append({"full_name": fn,
                    "ko": (item.get("ko") or "").strip() or None,
                    "stage": stage})
    return out


def record_article_players(store: PlayerStore, content_hash: str,
                           pairs: list[dict]) -> list[dict]:
    """쌍을 저장하고 명단 밖 선수는 후보 등재 — 신규 후보 목록을 반환한다 (알림 입력).
    매칭은 접힌 full_name 우선, 다음 접힌 성 (동성 복수면 제외) — 성만 온 출력이
    기존 선수의 중복 행을 만드는 것을 막는다."""
    if not pairs:
        return []
    by_full, by_surname = store.match_maps()
    created: list[dict] = []
    for p in pairs:
        folded = _fold_latin(p["full_name"])
        tokens = p["full_name"].split()
        pid = by_full.get(folded) or by_surname.get(_fold_latin(tokens[-1]))
        if pid is None:
            pid = store.insert_candidate(
                full_name=p["full_name"],
                first_name=" ".join(tokens[:-1]) or None,
                surname=tokens[-1],
                ko_candidate=p["ko"],
                first_seen=content_hash)
            by_full[folded] = pid
            created.append({**p, "player_id": pid})
            log.info("후보 등재: %s (%s) stage=%s 근거=%s",
                     p["ko"] or "?", p["full_name"], p["stage"], content_hash[:8])
        store.link_article(content_hash, pid, p["stage"])
    return created
```

- [ ] **Step 4: 등재 멱등 통합 테스트 추가 (스펙 §9 계약)**

```python
# tests/integration/test_player_store.py 에 추가
from bullet_in.roster import normalize_pairs, record_article_players


def test_record_article_players_candidate_idempotent(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Nico Williams", "ko": "니코 윌리엄스",
                              "stage": "rumour"}])
    h1, h2 = "b" * 64, "c" * 64
    created1 = record_article_players(store, h1, pairs)
    created2 = record_article_players(store, h2, pairs)   # 같은 선수 재등장
    assert len(created1) == 1 and created2 == []          # 중복 후보 없음
    pid = created1[0]["player_id"]
    assert sorted(store.articles_for(pid)) == sorted([h1, h2])


def test_record_article_players_links_existing_by_surname(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Gyokeres", "ko": "요케레스",
                              "stage": "agreed"}])       # 성만 온 출력
    created = record_article_players(store, "d" * 64, pairs)
    assert created == []                                  # 기존 요케레스에 링크, 후보 미생성
```

- [ ] **Step 5: 전체 통과 확인 · 커밋**

Run: `uv run pytest tests/test_roster.py tests/integration/test_player_store.py -v` → PASS.

```bash
git add src/bullet_in/roster.py tests/
git commit  # feat(enrich): 추출 쌍 정규화 · 매칭 · 후보 자동 등재
```

### Task 10: 후보 등재 Discord 알림

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py` (추가)

**Interfaces:**
- Consumes: `send_alert` (기존 — 신규 인프라 없음, 스펙 §4.2).
- Produces: `build_candidate_alert(candidates, *, run_id) -> dict` — candidates 항목 키: full_name · ko · stage · title · url · player_id.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_notify.py 에 추가
from bullet_in.notify import build_candidate_alert


def test_build_candidate_alert_lists_each_candidate():
    cands = [{"full_name": "Nico Williams", "ko": "니코 윌리엄스", "stage": "rumour",
              "title": "Arsenal eye Williams", "url": "https://x.test/a", "player_id": 41}]
    alert = build_candidate_alert(cands, run_id="abcd1234-0000")
    assert "1명" in alert["title"]
    body = str(alert["fields"])
    assert "니코 윌리엄스" in body and "rumour" in body and "https://x.test/a" in body


def test_build_candidate_alert_caps_fields():
    cands = [{"full_name": f"P {i}", "ko": None, "stage": "rumour",
              "title": "t", "url": None, "player_id": i} for i in range(15)]
    alert = build_candidate_alert(cands, run_id="abcd1234-0000")
    assert "15명" in alert["title"]
    assert len(alert["fields"]) <= 12        # 후보 10 + 넘침 요약 + 회차
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -k candidate -v` → FAIL (ImportError).

- [ ] **Step 3: 구현**

```python
COLOR_CANDIDATE = 0x3BA55D   # 등재 알림 — 경고 (주황) · 실패 (적) 와 구분

def build_candidate_alert(candidates: list[dict], *, run_id: str) -> dict:
    """enrich 자동 발굴 후보 등재 알림 (스펙 §4.2) — 후속 액션은 확정 CLI.
    Discord embed 필드 상한 (25) 안에서 10명까지 펼치고 나머지는 건수로 접는다."""
    fields = []
    for c in candidates[:10]:
        name = f"{c.get('ko') or '?'} ({c['full_name']})"
        lines = [f"단계: {c['stage']}", f"근거: {c.get('title') or '-'}"]
        if c.get("url"):
            lines.append(f"[기사]({c['url']})")
        fields.append({"name": name,
                       "value": "\n".join(f"- {ln}" for ln in lines), "inline": False})
    if len(candidates) > 10:
        fields.append({"name": "그 외",
                       "value": f"- 후보 {len(candidates) - 10}명 추가 — DB 확인",
                       "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": f"🆕 링크 선수 후보 {len(candidates)}명 등재",
            "description": "확정 전에는 게이트 · 서빙 사전에 실리지 않는다 — 확정 CLI 로 승격",
            "color": COLOR_CANDIDATE, "fields": fields}
```

- [ ] **Step 4: 통과 확인 · 커밋**

Run: `uv run pytest tests/test_notify.py -v` → PASS.

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit  # feat(enrich): 후보 등재 Discord 알림
```

### Task 11: run.py 연결 — 추출 저장 · 알림 발송

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:84-90` (`rows_missing_translation` SELECT 에 `url` 추가)
- Modify: `src/bullet_in/run.py` (results 조립 직후 추출 반영 블록)

**Interfaces:**
- Consumes: Task 7~10 전부.
- Produces: 회차마다 article_players 적재 + 신규 후보 시 알림 1건.

- [ ] **Step 1: rows_missing_translation 에 url 추가**

SELECT 목록을 `"SELECT content_hash,url,source_id,title_original,body_excerpt,"` 로 바꾼다 (알림의 근거 기사 링크용).
기존 소비자는 dict 키 접근이라 키 추가는 무해하다.

- [ ] **Step 2: run.py 에 추출 반영 블록 추가**

`results.update(title_only_rows(...))` 다음 · glossary 로드 이전에 넣는다.

```python
    # 추출 쌍 반영 (스펙 §4.1 · §4.2): 저장은 번역 채택 여부와 무관 — 원문 근거 추출이고
    # 재시도 회차의 재추출은 upsert 멱등이다
    from bullet_in import roster
    pstore = PlayerStore(engine)
    by_hash = {r["content_hash"]: r for r in missing}
    new_candidates: list[dict] = []
    for h, v in results.items():
        pairs = roster.normalize_pairs(v.get("players"))
        for cand in roster.record_article_players(pstore, h, pairs):
            row = by_hash.get(h, {})
            new_candidates.append({**cand, "title": row.get("title_original"),
                                   "url": row.get("url")})
    if new_candidates:
        notify.send_alert(**notify.build_candidate_alert(new_candidates, run_id=run_id))
```

주의: 기존 `by_hash` 정의 (line 108) 가 이 블록보다 뒤에 있으면 위로 끌어올려 한 번만 만든다.
Task 4 에서 만든 `PlayerStore(engine)` 인스턴스가 있으면 재사용한다 (게이트 사전 로드와 같은 객체).

- [ ] **Step 3: 검증 · 커밋 · PR 3 생성**

Run: `uv run pytest -q` → 전부 PASS.

```bash
git add src/bullet_in/run.py src/bullet_in/storage/mariadb.py
git commit  # feat(enrich): 회차 경로에 추출 쌍 저장 · 후보 알림 연결
```

PR 3 라이브 계약 (머지 + VM 반영 후 첫 회차): article_players 적재 확인 · 신규 후보 발생 시 Discord 알림 확인 (스펙 §9).

### Task 12: 확정 CLI 순수 함수 — 재검사 · 두 단어 경고

**Files:**
- Create: `src/bullet_in/confirm_player.py` (순수 함수부터)
- Test: `tests/test_confirm_player.py` (신규)

**Interfaces:**
- Consumes: `enrich.detect_title_hallucination` · `detect_title_mistranslation` · `BODY_AS_TITLE_SOURCES` · `NAME_MISSING_PREFIX` (본체 무수정 재사용).
- Produces: `surname_warning(surname) -> str | None` · `recheck_titles(rows, name_map) -> list[str]` (의심 content_hash 목록).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_confirm_player.py
from bullet_in.confirm_player import recheck_titles, surname_warning


def test_surname_warning_on_two_words():
    assert surname_warning("Van Dijk") is not None    # 가드 축 조용한 꺼짐 경고 (스펙 §3.3)
    assert surname_warning("Gyokeres") is None


def _row(**kw):
    base = {"content_hash": "h1", "source_id": "skysports",
            "title_original": "Arsenal agree Nico Williams deal",
            "title_ko": "아스날, 니코 윌리엄스 합의", "body_source": "Nico Williams ...",
            "body_excerpt": None}
    return {**base, **kw}


def test_recheck_flags_hallucinated_name():
    # 확장된 사전 기준으로 원문에 근거 없는 인명이 제목에 있으면 의심
    rows = [_row(title_ko="아스날, 윌리엄스 대신 조르제 영입",
                 title_original="Arsenal agree Nico Williams deal")]
    assert recheck_titles(rows, {"조르제": "Djordje", "윌리엄스": "Williams"}) == ["h1"]


def test_recheck_passes_grounded_title():
    rows = [_row()]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []


def test_recheck_skips_rows_without_translation():
    rows = [_row(title_ko=None)]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []


def test_recheck_excludes_roundup_reverse_axis():
    # bbc_gossip 은 제목 재초점이 정상 — 역방향 (인명 누락) 축 제외 (finalize 와 동일 규칙)
    rows = [_row(source_id="bbc_gossip", title_ko="아스날 이적 소식 모음",
                 title_original="Nico Williams to Arsenal gossip",
                 body_source="Nico Williams ...")]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_confirm_player.py -v` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: 구현**

```python
# src/bullet_in/confirm_player.py
"""후보 선수 확정 CLI — 승격 → 게이트 재검사 → 재번역 → 재렌더 (스펙 §4.3).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" \
        --category external --transfer-status in_link
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" --dry-run
"""
from __future__ import annotations
import argparse, logging, os
from bullet_in.enrich import (BODY_AS_TITLE_SOURCES, NAME_MISSING_PREFIX,
                              detect_title_hallucination, detect_title_mistranslation)

log = logging.getLogger(__name__)


def surname_warning(surname: str) -> str | None:
    """두 단어 성 경고 (스펙 §3.3) — 풀네임 근거 가드 축이 조용히 꺼진다."""
    if " " in surname.strip():
        return (f"surname '{surname}' 이 두 단어 — _has_name_context 가드가 근거를 못 찾아 "
                "이 축의 보호 없이 등재된다 (가드의 두 단어 성 지원은 범위 밖)")
    return None


def recheck_titles(rows: list[dict], name_map: dict[str, str]) -> list[str]:
    """저장된 번역 제목을 확장된 사전으로 재검사 — 의심 행 content_hash 목록 (스펙 §4.3).
    축 구성은 finalize_translation 1차 검출과 같다 (환각 + 역방향 · 라운드업 제외 · 트윗 예외).
    임대 무근거 축은 사전과 무관해 이미 1차에서 걸렀으므로 여기서 다시 보지 않는다."""
    suspects = []
    for row in rows:
        if not row.get("title_ko"):
            continue
        src_text = " ".join(filter(None, [row.get("title_original"),
                                          row.get("body_source"),
                                          row.get("body_excerpt")]))
        reasons = detect_title_hallucination(row["title_ko"], src_text, name_map)
        if row.get("source_id") != "bbc_gossip":
            rev = detect_title_mistranslation(row["title_ko"], row.get("title_original"),
                                              name_map, src_text)
            if row.get("source_id") in BODY_AS_TITLE_SOURCES:
                rev = [r for r in rev if not r.startswith(NAME_MISSING_PREFIX)]
            reasons += rev
        if reasons:
            log.warning("재검사 의심 content_hash=%s 사유=%s", row["content_hash"], reasons)
            suspects.append(row["content_hash"])
    return suspects
```

- [ ] **Step 4: 통과 확인 · 커밋**

Run: `uv run pytest tests/test_confirm_player.py -v` → PASS.

```bash
git add src/bullet_in/confirm_player.py tests/test_confirm_player.py
git commit  # feat(enrich): 확정 재검사 · 두 단어 성 경고 함수
```

### Task 13: MartStore — 대상 행 조회 · 번역 초기화, PlayerStore — 확정 전이

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py`
- Modify: `src/bullet_in/storage/players.py`
- Test: `tests/integration/test_mariadb_store.py` · `tests/integration/test_player_store.py` (추가)

**Interfaces:**
- Consumes: Task 1 테이블.
- Produces: `MartStore.rows_for_hashes(hashes) -> list[dict]` · `MartStore.clear_translation(hashes) -> int` · `PlayerStore.get_player(full_name) -> dict | None` · `PlayerStore.confirm(player_id, *, ko_name, category, transfer_status, club) -> None`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/integration/test_mariadb_store.py 에 추가
def test_rows_for_hashes_and_clear_translation(engine):
    store = MartStore(engine)
    store.upsert([_art(h="h1", url="https://x.test/1"), _art(h="h2", url="https://x.test/2")])
    store.set_translation("h1", "제목", "요약", "3줄", "본문")
    rows = store.rows_for_hashes(["h1"])
    assert [r["content_hash"] for r in rows] == ["h1"]
    assert rows[0]["title_ko"] == "제목"
    assert store.clear_translation(["h1"]) == 1
    assert {r["content_hash"] for r in store.rows_missing_translation()} >= {"h1", "h2"}
```

```python
# tests/integration/test_player_store.py 에 추가
def test_confirm_promotes_candidate(engine):
    store = PlayerStore(engine)
    pid = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                 surname="Williams", ko_candidate="니코 윌리엄스",
                                 first_seen=None)
    store.confirm(pid, ko_name="니코 윌리엄스", category="external",
                  transfer_status="in_link", club="Athletic Club")
    p = store.get_player("Nico Williams")
    assert p["status"] == "confirmed" and p["confirmed_at"] is not None
    assert store.gate_name_map()["니코 윌리엄스"] == "Williams"   # 확정 즉시 사전 편입
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration -v -k "rows_for_hashes or confirm_promotes"` → FAIL.

- [ ] **Step 3: 구현**

```python
# mariadb.py 에 추가 (bindparam 은 backfill_journalist 의 expanding 관례)
    def rows_for_hashes(self, hashes: list[str]) -> list[dict]:
        """확정 CLI 재검사 입력 — 대상 기사만 게이트 입력 컬럼으로 조회."""
        if not hashes:
            return []
        sql = text(
            "SELECT content_hash,source_id,title_original,title_ko,"
            "body_source,body_excerpt,summary_ko FROM articles "
            "WHERE content_hash IN :hs").bindparams(bindparam("hs", expanding=True))
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(sql, {"hs": hashes}).mappings().all()]

    def clear_translation(self, hashes: list[str]) -> int:
        """번역 4필드 초기화 — 재번역 큐 투입 (title_ko 만 지우면 재시도 판정이 어긋난다,
        런북 2026-07-19 §5.2 와 같은 이유로 4필드 전부)."""
        if not hashes:
            return 0
        sql = text(
            "UPDATE articles SET title_ko=NULL, summary_ko=NULL, "
            "summary3_ko=NULL, body_ko=NULL WHERE content_hash IN :hs"
        ).bindparams(bindparam("hs", expanding=True))
        with self.engine.begin() as c:
            return c.execute(sql, {"hs": hashes}).rowcount
```

```python
# players.py 에 추가
    def get_player(self, full_name: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM players WHERE full_name=:fn"),
                            {"fn": full_name}).mappings().first()
        return dict(row) if row else None

    def confirm(self, player_id: int, *, ko_name: str,
                category: str | None = None, transfer_status: str | None = None,
                club: str | None = None) -> None:
        """후보 승격 (스펙 §4.3 1단계) — ko_name 기입 · 분류는 지정한 것만 갱신."""
        with self.engine.begin() as c:
            c.execute(text(
                "UPDATE players SET status='confirmed', ko_name=:ko, "
                "confirmed_at=:now, category=COALESCE(:cat, category), "
                "transfer_status=COALESCE(:ts, transfer_status), "
                "club=COALESCE(:club, club) WHERE id=:id"),
                {"ko": ko_name, "now": _utcnow(), "cat": category,
                 "ts": transfer_status, "club": club, "id": player_id})
```

- [ ] **Step 4: 통과 확인 · 커밋**

Run: `uv run pytest tests/integration -v` → PASS.

```bash
git add src/bullet_in/storage/
git commit  # feat(storage): 확정 전이 · 대상 행 조회 · 번역 초기화
```

### Task 14: 확정 CLI main — 종단 연결

**Files:**
- Modify: `src/bullet_in/confirm_player.py` (main · 수렴 · 재렌더)
- Test: `tests/test_confirm_player.py` (dry-run 경로)

**Interfaces:**
- Consumes: Task 12 · 13 전부, `enrich` 수렴 함수들 (런북 2026-07-19 §3 과 같은 조합), `run.SERVING_SELECT_SQL` · `serve.render.write_site`.
- Produces: `python -m bullet_in.confirm_player` 종단 명령.

- [ ] **Step 1: main 구현**

```python
def _converge(mart, pstore, engine, targets: set[str]) -> None:
    """대상 행만 재번역 수렴 — 런북 2026-07-19 §3 의 함수 조합을 대상 축소로 재사용."""
    import yaml
    from pathlib import Path
    from google import genai
    from bullet_in.enrich import (enrich_rows, finalize_translation,
                                  partition_by_body_level, partition_generatable,
                                  rewrite_rows_guarded, title_only_rows)
    from bullet_in.run import GEMINI_MODEL
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
                or {}).get("replacements", {})
    club_map = (yaml.safe_load(Path("config/club_map.yaml").read_text())
                or {}).get("clubs", {})
    name_map = pstore.gate_name_map()
    for _ in range(3):
        missing = [r for r in mart.rows_missing_translation()
                   if r["content_hash"] in targets]
        if not missing:
            break
        by_hash = {r["content_hash"]: r for r in missing}
        generatable, title_only = partition_generatable(missing)
        rewrite_rows, translate_rows = partition_by_body_level(generatable)
        results = {}
        results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
        rewritten, gate_reports = rewrite_rows_guarded(rewrite_rows, client, GEMINI_MODEL)
        results.update(rewritten)
        results.update(title_only_rows(title_only, client, GEMINI_MODEL))
        for h, v in results.items():
            t, s, s3, b, _ = finalize_translation(v, by_hash.get(h, {}),
                                                  glossary, name_map, club_map)
            mart.set_translation(h, t, s, s3, b)
        for h, rep in gate_reports.items():
            mart.set_rewrite_retention(h, rep["retention"])


def _render(engine) -> None:
    """run.py 서빙 경로와 1:1 재렌더 (SERVING_SELECT_SQL import — 런북 스니펫 드리프트 방지)."""
    from sqlalchemy import text
    from bullet_in.run import SERVING_SELECT_SQL
    from bullet_in.score import load_sources
    from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
    from bullet_in.serve.render import write_site
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    write_site(rows, load_sources("config/sources.yaml"), "site",
               directory=journalist_directory("config/credibility.yaml"),
               registry=load_registry("config/credibility.yaml"),
               outlet_dir=outlet_directory("config/credibility.yaml"))
    print(f"site 재생성: {len(rows)} 행")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="players.full_name")
    ap.add_argument("--ko", required=True, help="검출용 한글 표기 (사람 확정 값)")
    ap.add_argument("--category", choices=["squad", "manager", "external"])
    ap.add_argument("--transfer-status", dest="transfer_status",
                    choices=["none", "in_link", "in_done", "out_link", "out_done",
                             "link_dropped", "other_club", "loan_in", "loan_out"])
    ap.add_argument("--club")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from sqlalchemy import create_engine
    from bullet_in.storage.mariadb import MartStore
    from bullet_in.storage.players import PlayerStore
    engine = create_engine(os.environ["MARIADB_URL"])
    mart, pstore = MartStore(engine), PlayerStore(engine)
    player = pstore.get_player(args.name)
    if player is None:
        print(f"선수 없음: {args.name}")
        return 1
    if (w := surname_warning(player["surname"])):
        log.warning(w)

    hashes = pstore.articles_for(player["id"])
    if args.dry_run:
        trial_map = {**pstore.gate_name_map(), args.ko: player["surname"]}
        suspects = recheck_titles(mart.rows_for_hashes(hashes), trial_map)
        print(f"[dry-run] 등장 기사 {len(hashes)} · 재번역 대상 {len(suspects)}")
        return 0

    pstore.confirm(player["id"], ko_name=args.ko, category=args.category,
                   transfer_status=args.transfer_status, club=args.club)
    suspects = recheck_titles(mart.rows_for_hashes(hashes),
                              pstore.gate_name_map())
    if suspects:
        mart.clear_translation(suspects)
        _converge(mart, pstore, engine, set(suspects))
    _render(engine)
    print(f"확정: {args.name} → {args.ko} · 등장 기사 {len(hashes)} · 재번역 {len(suspects)}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
```

- [ ] **Step 2: 상태 전이는 Task 13 통합 테스트가 검증 — dry-run 경로만 추가 확인**

dry-run 은 Gemini · 렌더를 부르지 않으므로 로컬 DB 로 직접 확인한다.

Run: `set -a; source .env; set +a && uv run python -m bullet_in.confirm_player --name "Bruno Guimaraes" --ko 기마랑이스 --dry-run`
Expected: `[dry-run] 등장 기사 0 · 재번역 대상 0` (백필 전이라 0 — 명령이 도는 것 자체가 검증).

- [ ] **Step 3: 전체 테스트 · 커밋 · PR 4 생성**

Run: `uv run pytest -q` → 전부 PASS.

```bash
git add src/bullet_in/confirm_player.py tests/test_confirm_player.py
git commit  # feat(enrich): 확정 CLI — 승격 · 재검사 · 재번역 · 재렌더 종단
```

PR 4 라이브 계약 (머지 + VM 반영 후): 실제 후보 1건으로 확정 CLI 종단 (승격 → 재검사 → 재렌더) 확인 (스펙 §9).

### Task 15: 추출 전용 프롬프트 · 파서

**Files:**
- Modify: `src/bullet_in/enrich.py` (EXTRACT_PLAYERS_PROMPT · `extract_players_rows`)
- Test: `tests/test_enrich.py` (추가)

**Interfaces:**
- Consumes: Task 7 의 players 항목 스키마 (동일 형태).
- Produces: `extract_players_rows(rows, client, model) -> dict[str, list]` — content_hash → 원시 pairs (정규화는 호출측 `normalize_pairs`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_extract_players_rows_returns_pairs_and_stops_on_429(caplog):
    import logging as _logging
    payload = {"players": [{"full_name": "Nico Williams", "ko": "니코 윌리엄스",
                            "stage": "rumour"}]}
    rows = [{"content_hash": "h1", "title_original": "T", "body_source": "B"}]
    out = extract_players_rows(rows, FullClient(payload), "m")
    assert out["h1"] == payload["players"]

    class _Boom:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
    with caplog.at_level(_logging.WARNING):
        out = extract_players_rows(rows, _Boom, "m")
    assert out == {} and "429" in caplog.text


def test_extract_players_prompt_lists_stages():
    from bullet_in.enrich import EXTRACT_PLAYERS_PROMPT
    for stage in ("rumour", "interest", "negotiating", "personal_terms",
                  "medical", "agreed", "other"):
        assert stage in EXTRACT_PLAYERS_PROMPT
    assert "official" not in EXTRACT_PLAYERS_PROMPT
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -k extract_players -v` → FAIL.

- [ ] **Step 3: 구현**

```python
EXTRACT_PLAYERS_PROMPT = (
    "다음 아스날 FC 관련 기사에서 이적 · 거취 · 계약의 주체로 다뤄진 선수 · 감독을 추출한다.\n"
    '각 항목은 {{"full_name":"영문 풀네임","ko":"기사에서 쓴 한글 표기 (원문이 영어면 통용 표기)",'
    '"stage":"단계"}}.\n'
    "- stage 는 rumour · interest · negotiating · personal_terms · medical · agreed · "
    "other 중 하나. 경기 · 근황만 다뤄진 인물은 other, 기사에 없는 인물은 넣지 않는다.\n"
    'ONLY JSON: {{"players":[...]}}'
    "\n\nTitle: {title}\nBody: {body}")


def extract_players_rows(rows: list[dict], client, model: str) -> dict[str, list]:
    """백필 전용 (선수, 단계) 쌍 추출 — 번역 없이 players 필드만 (스펙 §7).
    429 는 그 회차 즉시 중단, 파싱 실패는 행 스킵 (기존 enrich 루프와 동일 규칙)."""
    result: dict[str, list] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=EXTRACT_PLAYERS_PROMPT.format(
                    title=r["title_original"],
                    body=r.get("body_source") or r.get("body_excerpt") or ""),
                config={"max_output_tokens": 1024,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 추출 중단 — 남은 행 재실행 시 이어짐")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        m = re.search(r"\{.*\}", msg.text, re.DOTALL)
        try:
            pairs = json.loads(m.group(0))["players"] if m else None
        except (json.JSONDecodeError, KeyError, TypeError):
            pairs = None
        if not isinstance(pairs, list):
            log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
            continue
        result[h] = pairs
    return result
```

- [ ] **Step 4: 통과 확인 · 커밋**

Run: `uv run pytest tests/test_enrich.py -v` → PASS.

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit  # feat(enrich): 백필용 추출 전용 프롬프트 · 파서
```

### Task 16: 백필 CLI — backfill_article_players

**Files:**
- Create: `src/bullet_in/backfill_article_players.py`
- Modify: `.gitignore` (`backfill_players_state.txt`)
- Test: `tests/test_backfill_article_players.py` (신규 — 대상 선정 · state 파일)

**Interfaces:**
- Consumes: `extract_players_rows` · `roster.normalize_pairs` · `record_article_players` · `notify.build_candidate_alert`.
- Produces: `python -m bullet_in.backfill_article_players [--limit N] [--dry-run] [--state PATH]`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backfill_article_players.py
from bullet_in.backfill_article_players import filter_targets, load_state, append_state


def test_filter_targets_excludes_state(tmp_path):
    state = tmp_path / "state.txt"
    append_state(state, "h1")
    rows = [{"content_hash": "h1"}, {"content_hash": "h2"}]
    assert [r["content_hash"] for r in filter_targets(rows, load_state(state))] == ["h2"]


def test_load_state_missing_file_is_empty(tmp_path):
    assert load_state(tmp_path / "none.txt") == set()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backfill_article_players.py -v` → FAIL.

- [ ] **Step 3: 구현**

```python
"""기존 기사 article_players 백필 (1회성 · 스펙 §7).

Gemini 약 500건 호출 — Tier 1 선불 과금이라 실행 전 사용자 확인 필수.
15 RPM 속도 한도 기준 약 35분. 429 중단 시 재실행하면 이어서 처리한다.
state 파일은 추출 결과 0명 행의 재과금을 막는다 (article_players 만으로는 구분 불가).

실행 전 `set -a; source .env; set +a` 필수.
    uv run python -m bullet_in.backfill_article_players --limit 5 --dry-run
    uv run python -m bullet_in.backfill_article_players
"""
from __future__ import annotations
import argparse, logging, os
from pathlib import Path
from sqlalchemy import create_engine, text
from bullet_in import notify, roster
from bullet_in.enrich import extract_players_rows
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

_TARGET_SQL = text(
    "SELECT content_hash, title_original, body_source, body_excerpt, url "
    "FROM articles WHERE NOT EXISTS (SELECT 1 FROM article_players ap "
    "WHERE ap.content_hash = articles.content_hash) ORDER BY published_at, id")


def load_state(path: Path) -> set[str]:
    return set(path.read_text().split()) if path.exists() else set()


def append_state(path: Path, content_hash: str) -> None:
    with path.open("a") as f:
        f.write(content_hash + "\n")


def filter_targets(rows: list[dict], done: set[str]) -> list[dict]:
    return [r for r in rows if r["content_hash"] not in done]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", type=Path, default=Path("backfill_players_state.txt"))
    args = ap.parse_args(argv)

    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_TARGET_SQL).mappings().all()]
    targets = filter_targets(rows, load_state(args.state))
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상: {len(targets)} 행 (미링크 {len(rows)} · state 제외 {len(rows) - len(targets)})")
    if args.dry_run:
        return

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    pstore = PlayerStore(engine)
    by_hash = {r["content_hash"]: r for r in targets}
    new_candidates: list[dict] = []
    done = 0
    # 행 단위 호출 — 429 로 끊기면 state 에 남은 만큼만 재실행된다
    for r in targets:
        extracted = extract_players_rows([r], client, GEMINI_MODEL)
        if r["content_hash"] not in extracted:
            if done and not extracted:      # 429 중단 판별은 로그로 — 파싱 실패면 계속
                pass
            continue
        pairs = roster.normalize_pairs(extracted[r["content_hash"]])
        for cand in roster.record_article_players(pstore, r["content_hash"], pairs):
            row = by_hash[r["content_hash"]]
            new_candidates.append({**cand, "title": row.get("title_original"),
                                   "url": row.get("url")})
        append_state(args.state, r["content_hash"])
        done += 1
    if new_candidates:
        notify.send_alert(**notify.build_candidate_alert(
            new_candidates, run_id="backfill"))
    print(f"처리 {done} / {len(targets)} · 신규 후보 {len(new_candidates)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
```

구현 주의: `extract_players_rows` 를 행 단위로 부르면 429 중단 신호가 빈 dict 로 흡수된다.
루프 안에서 429 를 구분하려면 `extract_players_rows` 대신 전체 targets 를 한 번에 넘기고, 반환된 hash 만 state 에 적는 쪽이 단순하다 — 파싱 실패 행도 state 에 안 남아 재시도되고, 429 중단 시 뒷행이 자연히 남는다.
구현 시 이 방식 (일괄 호출 + 반환분만 등재 · state 기록) 을 택한다.

```python
    extracted = extract_players_rows(targets, client, GEMINI_MODEL)
    for h, raw in extracted.items():
        pairs = roster.normalize_pairs(raw)
        for cand in roster.record_article_players(pstore, h, pairs):
            row = by_hash[h]
            new_candidates.append({**cand, "title": row.get("title_original"),
                                   "url": row.get("url")})
        append_state(args.state, h)
```

- [ ] **Step 4: 통과 확인 · 로컬 소량 검증 · 커밋**

Run: `uv run pytest tests/test_backfill_article_players.py -v` → PASS.
Run: `uv run python -m bullet_in.backfill_article_players --dry-run` → 대상 건수만 출력.
로컬 유료 호출 검증은 하지 않는다 — 실행은 VM · 과금 확인 후 (규율).

```bash
git add src/bullet_in/backfill_article_players.py tests/ .gitignore
git commit  # feat(enrich): article_players 백필 CLI — state 파일 · 집계 알림
```

### Task 17: 운영 런북

**Files:**
- Create: `docs/runbook/2026-08-01-player-roster-ops.md` (작성일에 맞춰 조정)

**Interfaces:**
- Consumes: Task 3 · 14 · 16 의 CLI 3종.
- Produces: 등재 → 알림 → 확정 → 백필 · VM 반영 절차의 SoT.

- [ ] **Step 1: 런북 작성 — 담을 것**

- 이관: VM `git pull` → `migrate_roster` → 사전 39명 확인 (PR 1 반영 절차 기록).
- 회차 관측: 후보 알림 형태 · article_players 적재 확인 쿼리.
- 확정: `confirm_player` 사용법 (dry-run 먼저) · 두 단어 성 경고의 의미 · 회차 시각 (KST 09 · 15 · 21 · 03) 회피 (재번역이 Gemini 를 쓰므로 enrich-only 런북과 같은 이유).
- 백필: 과금 고지 (약 500건 · Tier 1 선불) · 사용자 확인 선행 · state 파일 · 429 재실행.
- 생애주기 수동 전이 (스펙 §6): 영입 성사 · 방출 성사 · 링크 소멸 · 시장 종료 일괄 archived 의 UPDATE 예시.
- 서식: 컨벤션 §2.2 (훅 자동 검사).

- [ ] **Step 2: 커밋 · PR 5 생성**

```bash
git add docs/runbook/
git commit  # docs(runbook): 선수 명단 DB 운영 절차
```

PR 5 라이브 계약: VM 반영 후 백필 실행 (사용자 과금 확인) → article_players 채움 → 후보 목록 검토 → 확정 CLI 로 순차 승격.

---

## 검증 매트릭스 (스펙 §9 계약 → Task)

| 계약 | Task |
|---|---|
| 추출 쌍 파싱 | 7 · 15 |
| candidate INSERT 멱등 (재등장 중복 없음) | 9 |
| 로더 동등성 (이관 dict = YAML 39명 dict) | 2 (YAML 대조) · 6 (ROSTER 회귀 가드) |
| 확정 CLI 상태 전이 | 13 |
| 두 단어 surname 경고 | 12 |
| 라이브: 후보 알림 · article_players 적재 | PR 3 반영 절차 |
| 라이브: 확정 CLI 종단 | PR 4 반영 절차 |

## Self-Review 결과

- 스펙 §3 DDL 원문 반영 (Task 1) · §3.2 술어 (Task 2) · §3.3 경고 (Task 12) · §4.1 (Task 7~9 · 11) · §4.2 (Task 10) · §4.3 (Task 12~14) · §5 (Task 4~6) · §7 (Task 2~3 · 15~16) · §8 술어 공유 (Task 2) · §9 (위 매트릭스) 확인.
- §4.4 (확정 전 서빙 a안) 은 무동작이 구현이다 — 후보를 사전에 안 넣는 술어 (Task 2) 가 그 자체.
- §6 생애주기는 수동 UPDATE 운영이라 런북 (Task 17) 에만 담고 코드 없음 — 스펙에 자동 만료 없음이 명시돼 있다.
- 타입 일관성: `link_article` 3인자 (now 내부화) 로 Task 8 테스트 · Task 9 호출 통일, `insert_candidate` 는 키워드 전용으로 Task 8 · 9 · 13 동일 시그니처.
- 남는 리스크: PARAPHRASE 경로 (fmkorea) 의 full_name 품질 — 한국어 게시글엔 영문 풀네임이 없어 모델이 성만 내거나 오철자를 낼 수 있다. 성 매칭 폴백 (Task 9) 이 1차 방어고, 오철자 신규 후보는 사람 확정 단계에서 걸러진다 (ko_candidate 는 게이트 미공급이라 오염 전파 없음).
