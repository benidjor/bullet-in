# dbt 품질 게이트 실동 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장소에만 있던 dbt 모델과 테스트를 회차 안에서 실제로 돌리고, 계약 축이 깨지면 배포가 나가지 않게 만든다.

**Architecture:** 회차 맨 끝에서 `dbt build` 를 자식 프로세스로 부른다.
결과는 `dbt/target/run_results.json` 을 읽어 판정하고, 차단 사유가 있으면 Discord 로 알린 뒤 0 아닌 코드로 끝낸다.
systemd 가 `ExecStart` 실패 시 `ExecStartPost` 를 안 돌리므로 배포는 저절로 막힌다.

**Tech Stack:** Python 3.11 · uv · dbt-core 1.11 · dbt-duckdb · DuckDB `mysql_scanner` · MariaDB · pytest

**Spec:** `docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md`

## Global Constraints

- 게이트 호출 자리는 회차 맨 끝이다.
  `pipeline_runs` 적재와 `write_ops` 렌더가 끝난 뒤, `print(summary)` 앞이다.
- **두 축 모두 `severity` 는 `error` 로 둔다.**
  `severity: warn` 은 `error_if` 를 통째로 무시해서 차단이 영원히 안 걸린다.
  구간을 가르는 것은 `warn_if` 와 `error_if` 다.
- 임계는 고아 귀속 `error_if: ">100"` · 값 이탈 `error_if: ">20"` 이다.
  경고는 셋 다 `warn_if: ">0"` 이다.
- 테스트 인자는 dbt 1.11 문법인 `arguments:` 블록으로 넘긴다.
- 파이썬은 `uv run --project /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dbt-gate` 로 고정한다.
- dbt 는 `dbt/` 안에서 `DBT_PROFILES_DIR=.` 을 주고 부른다.
- 커밋 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>` 이다.
- 커밋 메시지는 `<type>(<scope>): 한국어 제목` + 본문 + `Refs:` + 트레일러 형식이다.
  트레일러는 `Co-authored-by: Claude Opus 5 (1M context) <noreply@anthropic.com>` 한 줄이다.
- `docs/` 아래 .md 는 서식 규칙을 지킨다.
  `→` 와 `—` 는 줄 시작에만 두고, `·` 양옆과 여는 괄호 앞에 공백을 둔다.

## 시작 전 준비

- [ ] **로컬 개발 DB 스키마를 맞춘다**

로컬 MariaDB 가 운영보다 뒤처져 있으면 신설 모델이 없는 컬럼을 참조해 실패한다.
2026-08-31 실측에서 `article_players.role` 이 없었다.

```bash
docker compose up -d
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin" \
  uv run python -c "
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
MartStore(create_engine(os.environ['MARIADB_URL'])).ensure_schema()
print('스키마 적용 완료')
"
```

- [ ] **dev 의존성을 설치한다**

```bash
uv sync --extra dev
uv run dbt --version   # Core 1.11.x 가 나와야 한다
```

---

### Task 1: dbt 접속 정보를 `MARIADB_URL` 하나로 모은다

지금 `dbt/profiles.yml` 에 `password=bulletin` 이 박혀 있다.
공개 저장소에 실린 값이고 운영 비밀번호와 달라서 VM 에서는 붙지도 않는다.

**Files:**
- Create: `src/bullet_in/dbt_gate.py`
- Create: `tests/test_dbt_gate.py`
- Modify: `dbt/profiles.yml`

**Interfaces:**
- Consumes: 없음
- Produces: `dbt_env(mariadb_url: str) -> dict[str, str]`
  다섯 키를 돌려준다 — `DBT_MARIA_HOST` · `DBT_MARIA_PORT` · `DBT_MARIA_USER` · `DBT_MARIA_PASSWORD` · `DBT_MARIA_DB`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dbt_gate.py`:

```python
from bullet_in.dbt_gate import dbt_env


def test_dbt_env_splits_url_into_five_variables():
    env = dbt_env("mysql+pymysql://root:secret@10.0.0.5:3307/bulletin")
    assert env == {
        "DBT_MARIA_HOST": "10.0.0.5",
        "DBT_MARIA_PORT": "3307",
        "DBT_MARIA_USER": "root",
        "DBT_MARIA_PASSWORD": "secret",
        "DBT_MARIA_DB": "bulletin",
    }


def test_dbt_env_fills_defaults_when_url_omits_them():
    env = dbt_env("mysql+pymysql://root@localhost/bulletin")
    assert env["DBT_MARIA_PORT"] == "3306"
    assert env["DBT_MARIA_PASSWORD"] == ""


def test_dbt_env_unquotes_percent_encoded_password():
    # 운영 비밀번호에 @ 나 / 가 들어가면 URL 에 퍼센트 인코딩으로 실린다.
    env = dbt_env("mysql+pymysql://root:p%40ss%2Fword@localhost:3306/bulletin")
    assert env["DBT_MARIA_PASSWORD"] == "p@ss/word"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.dbt_gate'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/bullet_in/dbt_gate.py`:

```python
"""회차 끝에서 dbt 품질 검사를 돌리고 결과로 배포를 막는 게이트.

설계 = docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md
"""
from __future__ import annotations

from urllib.parse import unquote, urlparse


def dbt_env(mariadb_url: str) -> dict[str, str]:
    """`MARIADB_URL` 을 dbt profiles 가 읽는 다섯 변수로 푼다.

    접속 정보의 단일 출처를 `MARIADB_URL` 하나로 두려는 것이다 — profiles.yml 에
    값을 박아 두면 공개 저장소에 비밀번호가 실리고 운영과도 갈린다.
    """
    p = urlparse(mariadb_url)
    return {
        "DBT_MARIA_HOST": p.hostname or "localhost",
        "DBT_MARIA_PORT": str(p.port or 3306),
        "DBT_MARIA_USER": unquote(p.username or "root"),
        "DBT_MARIA_PASSWORD": unquote(p.password or ""),
        "DBT_MARIA_DB": (p.path or "").lstrip("/") or "bulletin",
    }
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py -q`
Expected: PASS 3건

- [ ] **Step 5: `profiles.yml` 이 그 변수를 읽게 한다**

`dbt/profiles.yml` 의 `attach` 항목만 바꾼다.
기본값을 지금 값으로 두어 로컬과 CI 는 아무 설정 없이 지금과 똑같이 돈다.

```yaml
      attach:
        # 접속 정보의 단일 출처는 .env 의 MARIADB_URL 이다 — run.py 가 풀어서
        # 자식 프로세스 환경에 넣는다 (bullet_in.dbt_gate.dbt_env).
        # 기본값은 로컬 docker-compose 값이라 사람이 직접 부를 때도 그대로 돈다.
        - path: "host={{ env_var('DBT_MARIA_HOST', 'localhost') }} user={{ env_var('DBT_MARIA_USER', 'root') }} password={{ env_var('DBT_MARIA_PASSWORD', 'bulletin') }} port={{ env_var('DBT_MARIA_PORT', '3306') }} database={{ env_var('DBT_MARIA_DB', 'bulletin') }}"
          type: mysql
          alias: maria
```

- [ ] **Step 6: 로컬에서 dbt 가 여전히 도는지 확인한다**

```bash
cd dbt && DBT_PROFILES_DIR=. uv run dbt build
```

Expected: `PASS=16 WARN=0 ERROR=0`

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/dbt_gate.py tests/test_dbt_gate.py dbt/profiles.yml
git commit
```

제목: `refactor(dbt): 접속 정보를 MARIADB_URL 하나로 모은다`

---

### Task 2: 원천을 선언하고 staging 모델 둘을 신설한다

지금 staging 모델이 `maria.articles` 를 문자열로 직접 읽어 계보가 dbt 밖에서 끊긴다.
참조 무결성 테스트를 걸려면 `players` 와 `article_players` 도 모델로 있어야 한다.

**Files:**
- Modify: `dbt/models/sources.yml`
- Modify: `dbt/models/staging/stg_articles.sql`
- Modify: `dbt/models/staging/stg_pipeline_runs.sql`
- Modify: `dbt/models/staging/stg_source_freshness.sql`
- Create: `dbt/models/staging/stg_players.sql`
- Create: `dbt/models/staging/stg_article_players.sql`

**Interfaces:**
- Consumes: Task 1 의 `DBT_MARIA_DB` 환경 변수 이름
- Produces: dbt 모델 `stg_players` · `stg_article_players` · 원천 이름 `maria`

- [ ] **Step 1: 원천 블록을 넣는다**

`dbt/models/sources.yml` 맨 위에 `sources:` 를 더한다.
`models:` 아래 기존 내용은 건드리지 않는다.

DuckDB 가 붙인 MariaDB 는 카탈로그가 `maria` · 스키마가 MySQL 데이터베이스 이름이다.
2026-08-31 실측에서 `table_catalog='maria'` · `table_schema='bulletin'` 이었고, 같은 서버에 `bulletin_launch` 도 보였다.
그래서 스키마를 환경 변수로 받아 환경마다 다른 데이터베이스를 가리키게 한다.

```yaml
version: 2
sources:
  # DuckDB mysql_scanner 가 붙인 MariaDB — 카탈로그는 profiles.yml 의 alias 이고
  # 스키마는 MySQL 데이터베이스 이름이다 (로컬 bulletin · CI bulletin_test).
  - name: maria
    database: maria
    schema: "{{ env_var('DBT_MARIA_DB', 'bulletin') }}"
    tables:
      - name: articles
      - name: players
      - name: article_players
      - name: pipeline_runs
      - name: source_freshness
models:
```

- [ ] **Step 2: 기존 staging 셋을 원천 참조로 바꾼다**

`dbt/models/staging/stg_articles.sql`:

```sql
select content_hash, url, source_id, tier, confidence_score,
       title_original, title_ko, summary_ko, published_at, fetched_at
from {{ source('maria', 'articles') }}
```

`dbt/models/staging/stg_pipeline_runs.sql`:

```sql
select run_id, started_at, duration_sec, fetch_duration_sec,
       new_count, dup_count, error_count, success_rate
from {{ source('maria', 'pipeline_runs') }}
```

`dbt/models/staging/stg_source_freshness.sql`:

```sql
select run_id, checked_at, source_id, age_hours, stale
from {{ source('maria', 'source_freshness') }}
```

- [ ] **Step 3: staging 모델 둘을 신설한다**

`dbt/models/staging/stg_players.sql`:

```sql
select id, ko_name, ko_full_name, transfer_status
from {{ source('maria', 'players') }}
```

`dbt/models/staging/stg_article_players.sql`:

```sql
select content_hash, player_id, role, stage, extracted_at
from {{ source('maria', 'article_players') }}
```

- [ ] **Step 4: 계보가 실제로 이어졌는지 본다**

```bash
cd dbt && DBT_PROFILES_DIR=. uv run dbt ls --resource-type source
```

Expected: `source:bullet_in.maria.articles` 를 비롯한 다섯 줄

- [ ] **Step 5: 빌드가 통과하는지 본다**

```bash
cd dbt && DBT_PROFILES_DIR=. uv run dbt build
```

Expected: `ERROR=0` · staging 모델이 3개에서 5개로 늘어난다 (marts 3개를 합친 전체는 6개에서 8개)

- [ ] **Step 6: 커밋**

```bash
git add dbt/models
git commit
```

제목: `feat(dbt): 원천을 선언하고 선수 · 귀속 staging 모델을 신설`

---

### Task 3: 계약 축 테스트를 붙인다

오늘 위반이 0인 축이다.
깨졌다면 파이프라인이 고장 난 것이므로 배포를 세운다.

**Files:**
- Modify: `dbt/models/sources.yml`

**Interfaces:**
- Consumes: Task 2 의 모델 `stg_players` · `stg_article_players`
- Produces: 계약 축 테스트 7종

- [ ] **Step 1: 테스트를 더한다**

`dbt/models/sources.yml` 의 `models:` 아래에 더한다.
`stg_articles` 항목에는 `source_id` 를 더하고, 모델 둘은 새 항목으로 넣는다.

```yaml
  - name: stg_articles
    columns:
      - name: content_hash
        tests: [unique, not_null]
      - name: url
        tests: [unique, not_null]
      - name: title_original
        tests: [not_null]
      - name: source_id
        tests: [not_null]
      - name: tier
        tests:
          - accepted_values:
              arguments:
                values: [0, 1, 1.5, 2, 3, 4]
  - name: stg_players
    columns:
      - name: id
        tests: [unique, not_null]
  - name: stg_article_players
    columns:
      - name: player_id
        tests:
          - not_null
          - relationships:
              arguments:
                to: ref('stg_players')
                field: id
      - name: role
        tests:
          - accepted_values:
              arguments:
                values: ['subject', 'mention']
```

- [ ] **Step 2: 통과를 확인한다**

```bash
cd dbt && DBT_PROFILES_DIR=. uv run dbt build
```

Expected: `ERROR=0 WARN=0`

- [ ] **Step 3: 게이트가 「있음」 도 낼 수 있는지 본다**

없음을 확인하는 검사는 안 돌아도 없음을 낸다.
그래서 일부러 깨뜨려 실패가 나오는 것을 눈으로 본다.

```bash
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin" \
  uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.begin() as c:
    c.execute(text(\"INSERT INTO article_players (content_hash, player_id, role, extracted_at)\"
                   \" VALUES (REPEAT('a',64), 424242, 'mention', NOW())\"))
print('계약 축 위반 1건 심음 — 없는 선수를 가리키는 귀속')
"
cd dbt && DBT_PROFILES_DIR=. uv run dbt build; echo "종료코드 = $?"
```

Expected: `ERROR=1` · 종료코드 1 · 실패한 테스트 이름에 `relationships_stg_article_players_player_id` 가 보인다

- [ ] **Step 4: 심은 것을 되돌린다**

```bash
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin" \
  uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.begin() as c:
    n = c.execute(text('DELETE FROM article_players WHERE player_id=424242')).rowcount
print('되돌린 행 =', n)
"
cd dbt && DBT_PROFILES_DIR=. uv run dbt build; echo "종료코드 = $?"
```

Expected: `ERROR=0` · 종료코드 0

- [ ] **Step 5: 커밋**

```bash
git add dbt/models/sources.yml
git commit
```

제목: `feat(dbt): 계약 축 테스트 7종 — 깨지면 배포를 세운다`

---

### Task 4: 품질 축 테스트와 임계를 붙인다

오늘 위반이 있는 축이다.
값이 틀어지면 화면이 나빠지지만 파이프라인이 죽은 것은 아니라서, 경고 구간과 차단 구간을 가른다.

**Files:**
- Modify: `dbt/models/staging/stg_articles.sql`
- Modify: `dbt/models/sources.yml`

**Interfaces:**
- Consumes: Task 2 의 모델 `stg_article_players`
- Produces: 품질 축 테스트 3종

- [ ] **Step 0: 테스트할 컬럼을 staging 모델이 내놓게 한다**

Task 2 가 옮겨 적은 `stg_articles` 의 SELECT 목록에 `transfer_stage` 와 `transfer_direction` 이 없다.
두 컬럼은 MariaDB 원본 표에는 있지만 모델이 안 고르므로, 테스트를 걸면 데이터 문제가 아니라 컴파일 오류가 난다.

`dbt/models/staging/stg_articles.sql` 을 이렇게 바꾼다.

```sql
select content_hash, url, source_id, tier, confidence_score,
       title_original, title_ko, summary_ko, transfer_stage, transfer_direction,
       published_at, fetched_at
from {{ source('maria', 'articles') }}
```

확인:

```bash
cd dbt && DBT_PROFILES_DIR=. uv run dbt build
```

Expected: `ERROR=0` — 아직 품질 축 테스트를 안 붙였으므로 경고도 0이다

- [ ] **Step 1: 테스트를 더한다**

`severity` 는 `error` 로 둔다.
`severity: warn` 을 쓰면 `error_if` 가 무시돼 차단이 영원히 안 걸린다 (스펙 §2.2 실측).

`stg_articles` 항목에 두 컬럼을 더한다.

```yaml
      - name: transfer_stage
        tests:
          - accepted_values:
              arguments:
                values: ['interest', 'negotiating', 'personal_terms', 'agreed',
                         'medical', 'done', 'official', 'collapsed', 'rumour', 'other']
              config:
                # 2026-08-31 실측 = 결측 1건 · 분류 패스가 한 회차에 만지는 건수보다
                # 큰 값을 차단 임계로 둔다.
                severity: error
                warn_if: ">0"
                error_if: ">20"
      - name: transfer_direction
        tests:
          - accepted_values:
              arguments:
                values: ['in', 'out', 'none']
              config:
                severity: error
                warn_if: ">0"
                error_if: ">20"
```

`stg_article_players` 항목에 `content_hash` 를 더한다.

```yaml
      - name: content_hash
        tests:
          - relationships:
              arguments:
                to: ref('stg_articles')
                field: content_hash
              config:
                # 기사 쪽이 사라진 귀속 — 해시가 갈릴 때 참조가 남는다.
                # 차단 임계 100 의 근거는 알려진 가장 큰 단일 사건이 43건이었다는 것이다
                # (2026-08-29 주소 정정) · 그 두 배가 넘으면 정상 운영에서 나올 수 없다.
                severity: error
                warn_if: ">0"
                error_if: ">100"
```

- [ ] **Step 2: 경고가 배포를 안 막는 것을 확인한다**

**선수 행을 먼저 넣어야 한다.**
Task 3 이 `player_id` 참조를 계약 축으로 걸어 두었으므로, 없는 선수를 가리키면 경고가 아니라 차단이 난다.
이 단계에서 재려는 것은 기사 쪽만 없는 고아다.

```bash
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin" \
  uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.begin() as c:
    c.execute(text(\"INSERT IGNORE INTO players\"
                   \" (id, full_name, surname, category, status, transfer_status,\"
                   \"  origin, added_at, ko_name)\"
                   \" VALUES (9999, '검사용 선수', '검사용', 'squad', 'active', 'none',\"
                   \"         'manual', NOW(), '검사용')\"))
    c.execute(text(\"INSERT INTO article_players (content_hash, player_id, role, extracted_at)\"
                   \" VALUES (REPEAT('b',64), 9999, 'mention', NOW())\"))
print('고아 귀속 1건 심음 — 선수는 있고 기사만 없다')
"
cd dbt && DBT_PROFILES_DIR=. uv run dbt build; echo "종료코드 = $?"
```

Expected: `WARN=1 ERROR=0` · **종료코드 0**
경고는 배포를 막지 않는다는 것이 이 단계의 확인 대상이다.
`ERROR` 가 나오면 선수 행이 안 들어간 것이니 그것부터 본다.

- [ ] **Step 3: 임계를 넘기면 막히는 것을 확인한다**

`error_if` 를 잠깐 `">0"` 으로 낮춰 돌리고 되돌린다.

```bash
cd dbt && sed -i '' 's/error_if: ">100"/error_if: ">0"/' models/sources.yml
DBT_PROFILES_DIR=. uv run dbt build; echo "종료코드 = $?"
sed -i '' 's/error_if: ">0"/error_if: ">100"/' models/sources.yml
```

Expected: 낮췄을 때 `ERROR=1` · 종료코드 1 · 되돌린 뒤 `WARN=1 ERROR=0` · 종료코드 0

- [ ] **Step 4: 심은 것을 되돌린다**

```bash
MARIADB_URL="mysql+pymysql://root:bulletin@localhost:3306/bulletin" \
  uv run python -c "
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ['MARIADB_URL'])
with e.begin() as c:
    n = c.execute(text('DELETE FROM article_players WHERE player_id=9999')).rowcount
    c.execute(text('DELETE FROM players WHERE id=9999'))
print('되돌린 행 =', n)
"
git diff --stat dbt/models/sources.yml
```

Expected: `error_if: ">100"` 이 그대로 남아 있고 `">0"` 은 없다

- [ ] **Step 5: 커밋**

```bash
git add dbt/models/sources.yml
git commit
```

제목: `feat(dbt): 품질 축 테스트 3종 — 경고 구간과 차단 구간을 가른다`

---

### Task 5: `run_results.json` 을 판정으로 옮긴다

dbt 의 종료 코드만 보면 무엇이 깨졌는지 알 수 없다.
알림과 로그에 테스트 이름과 행 수를 실으려면 결과 파일을 읽어야 한다.

**Files:**
- Modify: `src/bullet_in/dbt_gate.py`
- Modify: `tests/test_dbt_gate.py`

**Interfaces:**
- Consumes: Task 1 의 `src/bullet_in/dbt_gate.py`
- Produces:
  - `TestOutcome(name: str, failures: int)` — 데이터클래스
  - `GateResult(blocked: list[TestOutcome], warned: list[TestOutcome], ran: bool, error: str | None)` — 데이터클래스
  - `parse_results(path: Path) -> GateResult`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dbt_gate.py` 에 더한다.

```python
import json
from pathlib import Path

from bullet_in.dbt_gate import parse_results


def _write(tmp_path: Path, results: list[dict]) -> Path:
    p = tmp_path / "run_results.json"
    p.write_text(json.dumps({"metadata": {}, "results": results,
                             "elapsed_time": 0.5, "args": {}}))
    return p


def test_parse_results_separates_blocked_from_warned(tmp_path):
    path = _write(tmp_path, [
        {"unique_id": "test.bullet_in.unique_stg_articles_url.abc",
         "status": "fail", "failures": 3, "message": ""},
        {"unique_id": "test.bullet_in.relationships_stg_article_players_x.def",
         "status": "warn", "failures": 7, "message": ""},
        {"unique_id": "test.bullet_in.not_null_stg_articles_url.ghi",
         "status": "pass", "failures": 0, "message": ""},
        {"unique_id": "model.bullet_in.stg_articles",
         "status": "success", "failures": None, "message": ""},
    ])
    r = parse_results(path)
    assert [t.name for t in r.blocked] == ["unique_stg_articles_url"]
    assert r.blocked[0].failures == 3
    assert [t.name for t in r.warned] == ["relationships_stg_article_players_x"]
    assert r.warned[0].failures == 7
    assert r.ran is True
    assert r.error is None


def test_parse_results_counts_model_errors_as_blocking(tmp_path):
    # 모델이 못 돌면 테스트는 건너뛰어 조용히 통과한 것처럼 보인다.
    path = _write(tmp_path, [
        {"unique_id": "model.bullet_in.stg_article_players",
         "status": "error", "failures": None, "message": "Binder Error"},
    ])
    r = parse_results(path)
    assert [t.name for t in r.blocked] == ["stg_article_players"]


def test_parse_results_reports_missing_file(tmp_path):
    r = parse_results(tmp_path / "없는파일.json")
    assert r.ran is False
    assert r.blocked == []
    assert "run_results.json" in (r.error or "")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_results'`

- [ ] **Step 3: 구현을 쓴다**

`src/bullet_in/dbt_gate.py` 에 더한다.

```python
import json
from dataclasses import dataclass, field
from pathlib import Path

# dbt 가 내는 테스트 상태 — fail 은 error_if 를 넘긴 것 · warn 은 warn_if 만 넘긴 것.
_BLOCKING = {"fail", "error"}


@dataclass(frozen=True)
class TestOutcome:
    name: str
    failures: int


@dataclass(frozen=True)
class GateResult:
    blocked: list[TestOutcome] = field(default_factory=list)
    warned: list[TestOutcome] = field(default_factory=list)
    ran: bool = True
    error: str | None = None


def _short(unique_id: str) -> str:
    """`test.bullet_in.unique_stg_articles_url.abc` 에서 사람이 읽을 이름만 뽑는다."""
    parts = unique_id.split(".")
    return parts[2] if len(parts) > 2 else unique_id


def parse_results(path: Path) -> GateResult:
    """`dbt build` 가 남긴 결과 파일을 차단 · 경고로 가른다.

    모델 실패도 차단으로 센다 — 모델이 못 돌면 그 아래 테스트가 건너뛰어져
    아무것도 안 깨진 것처럼 보인다.
    """
    try:
        data = json.loads(Path(path).read_text())
    except OSError as e:
        return GateResult(ran=False, error=f"run_results.json 을 못 읽었다: {e}")
    blocked, warned = [], []
    for r in data.get("results", []):
        status = r.get("status")
        outcome = TestOutcome(_short(r.get("unique_id", "")), int(r.get("failures") or 0))
        if status in _BLOCKING:
            blocked.append(outcome)
        elif status == "warn":
            warned.append(outcome)
    return GateResult(blocked=blocked, warned=warned)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py -q`
Expected: PASS 6건

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/dbt_gate.py tests/test_dbt_gate.py
git commit
```

제목: `feat(gate): dbt 결과 파일을 차단 · 경고 판정으로 옮긴다`

---

### Task 6: 게이트를 회차에 붙이고 실패를 알린다

**Files:**
- Modify: `src/bullet_in/dbt_gate.py`
- Modify: `src/bullet_in/notify.py`
- Modify: `src/bullet_in/run.py`
- Modify: `tests/test_dbt_gate.py`
- Modify: `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 5 의 `GateResult` · `parse_results` · Task 1 의 `dbt_env`
- Produces:
  - `run_gate(project_dir: Path, mariadb_url: str) -> GateResult`
  - `enforce_gate(result: GateResult, *, run_id: str) -> None` — 차단이면 `SystemExit(1)`
  - `notify.build_dbt_gate_alert(result, *, run_id: str) -> dict`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_dbt_gate.py` 에 더한다.

```python
import pytest

from bullet_in.dbt_gate import GateResult, TestOutcome, enforce_gate


def test_enforce_gate_passes_when_nothing_broke(caplog):
    enforce_gate(GateResult(), run_id="r1")   # 예외가 안 나야 한다


def test_enforce_gate_logs_warnings_without_blocking(caplog):
    import logging
    result = GateResult(warned=[TestOutcome("relationships_orphans", 259)])
    with caplog.at_level(logging.WARNING):
        enforce_gate(result, run_id="r1")
    assert "relationships_orphans" in caplog.text
    assert "259" in caplog.text


def test_enforce_gate_raises_and_alerts_when_blocked(monkeypatch):
    sent = {}
    monkeypatch.setattr("bullet_in.notify.send_alert",
                        lambda **kw: sent.update(kw))
    result = GateResult(blocked=[TestOutcome("unique_stg_articles_url", 3)])
    with pytest.raises(SystemExit) as e:
        enforce_gate(result, run_id="r1")
    assert e.value.code == 1
    assert "unique_stg_articles_url" in str(sent)


def test_enforce_gate_blocks_when_dbt_could_not_run(monkeypatch):
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: None)
    result = GateResult(ran=False, error="dbt 실행 파일이 없다")
    with pytest.raises(SystemExit):
        enforce_gate(result, run_id="r1")
```

`tests/test_notify.py` 에 더한다.

```python
def test_build_dbt_gate_alert_lists_broken_tests():
    from bullet_in.dbt_gate import GateResult, TestOutcome
    payload = notify.build_dbt_gate_alert(
        GateResult(blocked=[TestOutcome("unique_stg_articles_url", 3)],
                   warned=[TestOutcome("relationships_orphans", 259)]),
        run_id="abcdef1234")
    assert payload["channel"] == notify.CHANNEL_INCIDENT
    assert payload["color"] == notify.COLOR_FAILURE
    body = str(payload["fields"])
    assert "unique_stg_articles_url" in body
    assert "3" in body
    assert "relationships_orphans" in body
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py tests/test_notify.py -q`
Expected: FAIL — `enforce_gate` 와 `build_dbt_gate_alert` 가 없다

- [ ] **Step 3: 알림 빌더를 쓴다**

`src/bullet_in/notify.py` 끝에 더한다.

```python
def build_dbt_gate_alert(result, *, run_id: str) -> dict:
    """dbt 품질 게이트가 배포를 세웠을 때의 알림 (설계 2026-08-31 §2.7).

    `OnFailure` 알림은 유닛이 죽었다는 사실만 말한다 — 무엇이 깨졌는지는 여기서 말한다.
    """
    fields = []
    if not result.ran:
        fields.append({"name": "게이트 고장", "value": f"- {result.error}",
                       "inline": False})
    if result.blocked:
        fields.append({"name": "차단",
                       "value": "\n".join(f"- {t.name} — {t.failures}행"
                                          for t in result.blocked),
                       "inline": False})
    if result.warned:
        fields.append({"name": "경고 (차단 아님)",
                       "value": "\n".join(f"- {t.name} — {t.failures}행"
                                          for t in result.warned),
                       "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": "🚧 dbt 품질 게이트 — 배포를 세웠습니다",
            "description": "회차는 끝났지만 배포가 나가지 않았다 · 화면은 직전 산출물 그대로다",
            "color": COLOR_FAILURE, "fields": fields,
            "channel": CHANNEL_INCIDENT}
```

- [ ] **Step 4: 게이트 실행과 판정 적용을 쓴다**

`src/bullet_in/dbt_gate.py` 에 더한다.

```python
import logging
import os
import subprocess

from bullet_in import notify

log = logging.getLogger(__name__)


def run_gate(project_dir: Path, mariadb_url: str) -> GateResult:
    """`dbt build` 를 돌리고 결과 파일을 읽어 판정한다.

    dbt 자체가 못 돌면 데이터 결함이 아니라 게이트 고장이다 — 그것도 차단으로 낸다.
    조용히 통과시키면 게이트가 있다는 착각만 남는다.
    """
    env = {**os.environ, **dbt_env(mariadb_url), "DBT_PROFILES_DIR": "."}
    try:
        proc = subprocess.run(["dbt", "build"], cwd=project_dir, env=env,
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return GateResult(ran=False, error=f"dbt 를 못 돌렸다: {e}")
    result = parse_results(Path(project_dir) / "target" / "run_results.json")
    if not result.ran:
        # 결과 파일이 없다는 것은 dbt 가 시작도 못 했다는 뜻이다.
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return GateResult(ran=False, error=f"{result.error} · dbt 출력: {' / '.join(tail)}")
    return result


def enforce_gate(result: GateResult, *, run_id: str) -> None:
    """경고는 저널에 남기고, 차단 사유가 있으면 알린 뒤 회차를 실패로 끝낸다.

    회차가 0 아닌 코드로 끝나면 systemd 가 ExecStartPost (배포) 를 안 돌린다.
    """
    if result.warned:
        log.warning("dbt 게이트 경고 %d건 — %s", len(result.warned),
                    " · ".join(f"{t.name} {t.failures}행" for t in result.warned))
    if not result.blocked and result.ran:
        log.info("dbt 게이트 통과 — 차단 0 · 경고 %d", len(result.warned))
        return
    notify.send_alert(**notify.build_dbt_gate_alert(result, run_id=run_id))
    log.error("dbt 게이트가 배포를 세웠다 — %s",
              result.error or " · ".join(f"{t.name} {t.failures}행"
                                         for t in result.blocked))
    raise SystemExit(1)
```

- [ ] **Step 5: 통과를 확인한다**

Run: `uv run pytest tests/test_dbt_gate.py tests/test_notify.py -q`
Expected: PASS

- [ ] **Step 6: 회차에 붙인다**

`src/bullet_in/run.py` 의 import 절에 더한다.

```python
from bullet_in import dbt_gate
```

`write_ops` 를 감싼 `try` 블록 다음, `print(summary)` 앞에 더한다.

```python
    # dbt 품질 게이트 (설계 2026-08-31): 마트가 이번 회차 행을 담은 뒤에 돌린다.
    # 차단 사유가 있으면 여기서 회차가 실패로 끝나고, systemd 가 ExecStartPost
    # (배포) 를 안 돌린다 — site/ 는 만들어져 있지만 올라가지 않는다.
    dbt_gate.enforce_gate(
        dbt_gate.run_gate(Path("dbt"), os.environ["MARIADB_URL"]), run_id=run_id)

    print(summary)
```

- [ ] **Step 7: 기존 테스트가 그대로 통과하는지 본다**

Run: `uv run pytest -q`
Expected: 기존 통과 수 + 새 테스트 · 실패 0 · 건너뜀 1

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/dbt_gate.py src/bullet_in/notify.py src/bullet_in/run.py \
        tests/test_dbt_gate.py tests/test_notify.py
git commit
```

제목: `feat(gate): 회차 끝에서 dbt 품질 검사를 돌리고 실패 시 배포를 세운다`

---

### Task 7: 운영과 CI 가 실제로 dbt 를 갖게 한다

운영 VM 에는 dbt 가 설치돼 있지 않다.
`dbt-duckdb` 가 `dev` extra 에만 있어서 운영 동기화에서 빠진다.

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 의 `DBT_MARIA_DB` 환경 변수 이름
- Produces: 없음

- [ ] **Step 1: 의존성을 옮긴다**

`pyproject.toml` 의 `dependencies` 끝에 더하고 `dev` 에서 뺀다.

```toml
  "python-dateutil>=2.9",
  "dbt-duckdb>=1.8",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-asyncio>=0.23", "respx>=0.21", "mongomock>=4.1"]
```

- [ ] **Step 2: 잠금 파일을 갱신하고 dev 없이도 dbt 가 있는지 본다**

```bash
uv lock
uv sync
uv run dbt --version
```

Expected: `dev` extra 없이도 Core 1.11.x 가 나온다

- [ ] **Step 3: CI 를 `dbt build` 로 올린다**

`.github/workflows/ci.yml` 의 「dbt 파싱」 단계를 바꾼다.
러너 MariaDB 에는 `bulletin_test` 만 있으므로 그쪽을 가리킨다.
이 데이터베이스는 앞 단계의 pytest 가 만든다.

```yaml
      # 테스트가 만든 bulletin_test 스키마에 붙여 모델과 테스트를 실제로 돌린다.
      # 데이터가 없어 컬럼 테스트는 빈 채로 통과하지만, dbt parse 가 못 보던
      # SQL · YAML 오류를 잡는다 (안건 2γ).
      - name: dbt 빌드
        working-directory: dbt
        env:
          DBT_PROFILES_DIR: .
          DBT_MARIA_DB: bulletin_test
        run: uv run dbt build
```

- [ ] **Step 4: 「안 보는 것」 목록에서 dbt 줄을 지운다**

`.github/workflows/ci.yml` 의 요약 블록에서 첫 줄을 뺀다.

```yaml
          cat >> "$GITHUB_STEP_SUMMARY" <<'EOF'
          ### 이 CI 가 안 보는 것

          - **라이브 소스 셀렉터** — 외부 사이트에 의존하는 자리라 단위 테스트가 모킹으로 지나감
          - **배포와 운영 회차** — VM 반영 · 재렌더 · 화면 확인은 사람의 몫
          - **PR 본문 규약** — 검사는 돌지만 알림만 하고 막지 않음
          - **운영 데이터의 품질** — CI 의 dbt 는 빈 표를 보므로 값 이탈 · 고아 귀속은 운영 회차에서만 드러남
          EOF
```

- [ ] **Step 5: 커밋**

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml
git commit
```

제목: `build(dbt): dbt 를 운영 의존성으로 올리고 CI 를 build 로 바꾼다`

---

### Task 8: 고아 귀속 259쌍을 지우고 0에서 시작한다

**운영 데이터를 지우는 일이다.**
`--dry-run` 으로 대상 수를 세어 사용자에게 보이고 승인을 받은 뒤에만 실행한다.

**Files:**
- 코드 변경 없음 — 기존 `src/bullet_in/migrate_url_identity.py` 를 쓴다

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 대상 수를 센다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.migrate_url_identity --dry-run'
```

`orphans_before` 값을 읽어 사용자에게 보인다.
2026-08-31 실측은 259쌍 · 기사 76건 몫이었다.

- [ ] **Step 2: 승인을 받는다**

숫자를 보이고 기다린다.
**승인 없이 다음 단계로 가지 않는다.**

- [ ] **Step 3: 지운다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.migrate_url_identity --apply --purge-orphans'
```

Expected: `purged` 가 대상 수와 같고 `orphans_after` 가 0이다

- [ ] **Step 4: 회차 저널에서 게이트 줄을 읽는다**

배포 뒤 첫 회차가 돈 다음에 확인한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service -n 200 --no-pager | grep -i "게이트"'
```

Expected: `dbt 게이트 통과 — 차단 0 · 경고 0`

**안 보이면 「대상이 없었나」 가 아니라 「게이트가 불렸나」 를 먼저 센다.**
로그가 없는 것은 죽었다는 것과 구분되지 않는다.

---

## 마무리

- [ ] `uv run pytest -q` 전량 통과
- [ ] PR 본문을 쓰고 게시 전에 검사기를 돌린다

```bash
python3 .claude/tools/check-pr-format.py --body <본문파일> --title "<제목>"
```

- [ ] push 하고 PR 을 만든다 (머지는 사용자가 한다)
- [ ] 머지 뒤 VM 반영 · 재렌더 · 배포 · 확인까지 묻지 않고 끝낸다
  VM 에서는 `uv sync` 를 함께 돌려야 dbt 가 설치된다
