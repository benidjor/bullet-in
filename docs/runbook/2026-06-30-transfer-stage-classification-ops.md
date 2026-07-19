# 런북 — 영입 단계 분류 운영 (마이그레이션 · backfill · 재태깅)

Tier 2-b (PR #18) 로 도입된 영입 단계 분류 (`articles.transfer_stage`) 의 운영 절차.

단계는 번역과 **분리된 전용 패스** (`enrich.classify_stage_rows`) 가 부여한다.
트리거는 `transfer_stage IS NULL` 이며, 신규 · 기존 기사를 한 경로로 균일 처리한다.
설계 상세는 `docs/superpowers/specs/2026-06-30-tier2b-transfer-stage-design.md`.

## 언제 쓰나

- 새 환경/DB에 분류를 처음 적용할 때 (스키마 마이그레이션 + backfill).
- 프롬프트 · taxonomy 를 바꿔 **전건 재분류**가 필요할 때.
- 분류가 안 채워지거나 분포가 이상할 때 진단.

## 비자명한 함정 (먼저 읽기)

- **한 번 태깅되면 자동 재분류 안 됨.** 트리거가 `transfer_stage IS NULL` 이라, 값이 채워진 행은 다음 사이클에 건드리지 않는다. 프롬프트 · 단계 정의를 개선해 **전건을 다시 분류**하려면 컬럼을 NULL 로 되돌려야 한다 (아래 3절).
- **revision 변경은 재태깅하지 않는다 (설계상 단계 보존).** url 이 같고 content_hash 가 바뀌는 (본문 개정) 경우, upsert 의 `ON DUPLICATE KEY UPDATE` 에 `transfer_stage` 가 일부러 빠져 있어 기존 단계가 유지된다. "본문이 바뀌었는데 단계가 그대로"는 버그가 아니라 의도된 동작이다.
- **타깃 분류 패스만 단독 실행하려면 `ensure_schema()` 선행.** 통합 테스트는 `bulletin_test` 에 스키마를 적용하지만, 실 `bulletin` DB 의 `transfer_stage` 컬럼은 `run.py` 의 `ensure_schema()` (또는 수동 호출) 로만 적용된다. 전체 파이프라인 없이 분류만 돌릴 때는 먼저 스키마를 보장해야 `transfer_stage IS NULL` 조회가 동작한다.
- **이 프로젝트는 dotenv 미사용** → 모든 실행 전에 `set -a; source .env; set +a`.

## 오피셜 규칙 분리 (2026-07-19)

'이적 합의' (agreed) 신설과 함께 official 부여 방식이 LLM 판정에서 소스 규칙으로 바뀌었다.
설계 배경은 `docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md` §2 · §4 참고.

- **규칙 경로만 official 을 생성한다.** `transfer_stage.rule_stage(source_id)` 는 `source_id` 가 `arsenal_official` (공홈) 인 행만 `"official"` 을 반환하고, 그 외는 `None` (LLM 분류 몫) 이다. `run.py` 의 분류 패스가 미태깅 행을 규칙 대상 / LLM 대상으로 나눠, 규칙 대상은 LLM 호출 없이 바로 `set_stage` 한다.
- **LLM enum 에서 official 이 제거됐다.** `STAGE_PROMPT` 는 더 이상 official 을 제시하지 않는다 — 공홈이 아닌 소스는 구조적으로 official 이 될 수 없다.
- **모델이 그래도 official 을 반환하면 agreed 로 강등한다.** `enrich.classify_stage_rows` 가 `stage == "official"` 응답을 agreed 로 낮추고 `WARNING` 로그를 남긴다 — 정상 흐름에서는 뜨지 않아야 하는 신호다.
- **진단: 비공홈 official 불변량.** 아래 SQL 은 항상 0 을 반환해야 한다. 0 이 아니면 규칙 분리가 깨졌거나 강등 방어를 우회한 경로가 있다는 뜻이다.

```sql
SELECT COUNT(*) FROM articles WHERE transfer_stage = 'official' AND source_id != 'arsenal_official';
```

## 1. 스키마 마이그레이션 (멱등)

전체 파이프라인 (`python -m bullet_in.run`) 은 시작 시 `ensure_schema()` 로 컬럼을 자동 적용하므로 별도 작업이 불필요하다.
분류 패스만 단독으로 돌리려면 먼저 한 번 적용한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
from bullet_in.storage.mariadb import MartStore
e = create_engine(os.environ["MARIADB_URL"])
MartStore(e).ensure_schema()   # ALTER ... ADD COLUMN IF NOT EXISTS (멱등)
with e.connect() as c:
    cols = [r[0] for r in c.execute(text("SHOW COLUMNS FROM articles")).all()]
print("transfer_stage present:", "transfer_stage" in cols)
PY
```

## 2. backfill (미태깅 행 분류)

전체 파이프라인을 돌리면 번역 패스 뒤에 분류 패스가 자동 실행된다.
이미 적재된 행만 분류하려면 (수집 없이) 분류 패스만 돌린다.
`rule_stage` (공홈 → official 직결) 대상은 LLM 을 거치지 않으므로, 아래 스니펫은 나머지 (LLM 대상) 행만 돌리는 2절 원본을 단순화한 것이다.
공홈 규칙 분리 상세는 "오피셜 규칙 분리 (2026-07-19)" 절을 참고한다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine
from google import genai
from bullet_in.storage.mariadb import MartStore
from bullet_in.enrich import classify_stage_rows

engine = create_engine(os.environ["MARIADB_URL"])
mart = MartStore(engine)
mart.ensure_schema()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

rows = mart.rows_missing_stage()
print(f"미태깅: {len(rows)}")
out = classify_stage_rows(rows, client, "gemini-2.5-flash-lite")
print(f"이번 회차 분류: {len(out)}")
for h, stage in out.items():
    mart.set_stage(h, stage)
PY
```

- **429 동작**: Gemini 무료 티어는 분당 *요청 수* 한도다. 429 를 만나면 그 회차는 **즉시 중단** 하고 남은 배치는 다음 실행에 누적된다 (멱등). 한 번에 다 안 되면 같은 명령을 다시 돌리면 된다.
- **부분 실패**: 응답 누락 · 파싱 실패 배치의 행은 NULL 로 남아 다음 회차에 재시도된다. 손상 없음.

## 3. 전건 재분류 (taxonomy · 프롬프트 개선 후)

`transfer_stage` 가 이미 채워져 있으면 트리거가 건너뛰므로, 재분류 대상을 NULL 로 되돌린 뒤 2절을 다시 돌린다.

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.begin() as c:
    n = c.execute(text("UPDATE articles SET transfer_stage = NULL")).rowcount
print(f"NULL 복원: {n}건 → 이제 2절 backfill 재실행")
PY
```

특정 단계만 다시 보려면 `WHERE transfer_stage = 'other'` (또는 `'agreed'`) 등으로 범위를 좁힌다.

**2026-07-19 실측**: 201건 NULL 복원 → LLM 분류 1패스로 수렴 (잔존 0). 규칙 경로는 0건 (공홈 적재 0건). 재분류 후 official 0건은 공홈 적재가 없는 동안 정상이다 ("오피셜 규칙 분리" 절 참고).

## 4. 분포 검증

```bash
set -a; source .env; set +a
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar()
    miss = c.execute(text("SELECT COUNT(*) FROM articles WHERE transfer_stage IS NULL")).scalar()
    print(f"total={total} 미태깅={miss}")
    for r in c.execute(text("SELECT COALESCE(transfer_stage,'<NULL>'), COUNT(*) "
                            "FROM articles GROUP BY transfer_stage ORDER BY 2 DESC")).all():
        print(f"  {r[0]:14s} {r[1]}")
PY
```

- `other` 가 비정상적으로 많으면 (이적 무관 기사 과다) 수집 단계 문제다 — 아래 참고.

## 알려진 한계

- **비-기사 링크가 `rumour` 등으로 오분류될 수 있다.** 라이브에서 "Want more transfer stories? Read Thursday's full gossip column" 같은 football.london 네비게이션 · teaser 링크가 `rumour` 로 태깅됐다. 근본 원인은 분류기가 아니라 **수집 단계의 이적 키워드 필터 미착수 (로드맵 Tier 1-3)** 로 비-기사 링크까지 적재되는 것이다. Tier 1-3 + 기존 데이터 정리가 들어오면 이 잡음이 줄어든다. 메모리 `tier1-cleanup-track` 참조.
- **재계약 기사도 공홈 official 배지를 받을 수 있다.** 공홈 sign 필터가 신규 영입과 재계약 (연장) 기사를 구분하지 않아, 재계약도 규칙 경로에서 official 로 태깅된다. 현재 공홈 적재가 0건이라 실측은 없다 — 적재가 시작되면 재검토한다 (spec §4.4).

## 참조

- spec: `docs/superpowers/specs/2026-06-30-tier2b-transfer-stage-design.md`
- 계획: `docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md`
- 단계 정의 단일 출처: `src/bullet_in/transfer_stage.py`
- 분류 패스: `src/bullet_in/enrich.py` (`classify_stage_rows`)
- 후속 트랙 (이적 키워드 필터 · 데이터 정리): 로드맵 `docs/superpowers/2026-06-28-v1-completion-roadmap.md` Tier 1
